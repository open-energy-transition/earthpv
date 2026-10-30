#!/usr/bin/env python
"""Add the size chart to a published evidence atlas without rebuilding it.

Since 2026-10-30 `earthpv atlas` embeds "The same Sentinel-2-detectable total, by
installation size" on every page; before, only a page with roofclf's >= 400 m2 replacement
(Pakistan) carried its `bins`, and every other page hid the section. Where a detector below
400 m2 is missing, the template marks those bins as not measured, keyed off the page's own
`small_rooftop_status` / `small_ground_status`.

This recovers the page's placeholder values exactly as `retemplate_atlas.py` does,
recomputes the bins with the builder's own `atlas._size_distribution_data` from the run
behind the page (`SOURCES`), and refuses the page unless they sum, with its farm ground PV,
to the page's own Best within the builder's own tolerance (2%, at least 1 MWp). It then
adds `bins` and the size totals (`atlas.size_totals`) to the embedded data block and fills
the current template. Every other key is re-serialised byte for byte, which is checked
before writing. A page that already carries bins keeps them and is only re-templated.

The OSM convention follows the page: one built before 2026-10-20 (no
`totals.osm_combination`) is recomputed with `legacy_osm_addition`, and one with OSM-only
cells (`model_covered` 0) with `include_offgrid_osm`.

    pixi run python scripts/patch_atlas_sizes.py docs/assets/interactive/egypt_pv_evidence_atlas.html
    pixi run python scripts/patch_atlas_sizes.py --dry-run docs/assets/interactive/*_evidence_atlas.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from patch_atlas_coverage import _insert_after  # noqa: E402
from patch_atlas_pose import DUMPS  # noqa: E402
from retemplate_atlas import PLACEHOLDER, TEMPLATE, aoi_of, extract, read_old_template  # noqa: E402

# The run behind each published page, where it is not data/predictions/<aoi> and the
# country's prepared national OSM pull. Germany's roofclf half is register-calibrated and
# priced per cell (scripts/build_germany_sub400_atlas_inputs.py).
_DE = "data/roofclf_national_germany_prod/germany/density"
SOURCES = {
    "france": {"pred": "data/predictions_v5"},
    "nigeria": {"pred": "data/predictions_v5_nigeria"},
    "germany": {"central": f"{_DE}/sub400_central_incremental_buildings.parquet",
                "low": f"{_DE}/sub400_low_incremental_buildings.parquet"},
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", nargs="+", type=Path)
    ap.add_argument("--old-template", default="HEAD",
                    help="git revision (or file) of the template the pages were built from")
    ap.add_argument("--template", type=Path, default=TEMPLATE,
                    help="template to fill (default: the working tree's)")
    ap.add_argument("--aoi")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "src"))
    from earthpv import atlas

    old = read_old_template(args.old_template)
    new = args.template.read_text()
    failed = 0
    for page in args.pages:
        try:
            values = extract(old, page.read_text())
            raw = values["__PV_DATA_JSON__"]
            data = json.loads(raw)
            if json.dumps(data, **DUMPS) != raw:
                raise ValueError("the data block does not re-serialise byte for byte")
            aoi = args.aoi or aoi_of(page)
            T = data["totals"]
            if data.get("bins"):
                note = f"already carries {len(data['bins'])} bins, re-templated only"
            else:
                src = SOURCES.get(aoi, {})
                pred = Path(src.get("pred", "data/predictions")) / aoi
                cols = data["cell_cols"]
                k = cols.index("model_covered") if "model_covered" in cols else None
                offgrid = k is not None and any(not c[k] for c in data["cells"])
                legacy = "osm_combination" not in T
                size = atlas._size_distribution_data(
                    aoi, pred / "density",
                    Path(src.get("osm", f"data/labels/{aoi}_national_osm_solar.parquet")),
                    pred / "candidates.parquet",
                    low_buildings_path=src.get("low"), central_buildings_path=src.get("central"),
                    legacy_osm_addition=legacy, include_offgrid_osm=offgrid,
                )
                ground = float(T.get("small_ground") or 0.0)
                got, want = size["totals"]["mwp_best"] + ground, float(T["mwp_best"])
                if abs(got - want) > max(1.0, want * 0.02):
                    raise ValueError(f"the bins sum to {got:,.1f} MWp, the page's Best is "
                                     f"{want:,.1f} ({abs(got - want) / want:.1%} apart): "
                                     f"not the run behind this page")
                data["totals"] = {**T, **atlas.size_totals(size["totals"], ground)}
                data = _insert_after(data, "totals", {"bins": size["bins"]})
                values["__PV_DATA_JSON__"] = json.dumps(data, **DUMPS)
                note = (f"bins sum to {got:,.1f} MWp against Best {want:,.1f} "
                        f"({(got - want) / want:+.2%}; legacy OSM {legacy}, off-grid OSM "
                        f"{offgrid})")
            fresh = {"__LAYERS_JSON__": lambda: atlas.map_layers_json(aoi),
                     "__AOI_KEY__": lambda: aoi}
            html = new
            for key in sorted(set(PLACEHOLDER.findall(new))):
                html = html.replace(key, values[key] if key in values else fresh[key]())
            html = atlas._assert_no_placeholders(html, page.name)
        except Exception as err:  # noqa: BLE001 - report every page, then fail
            failed += 1
            print(f"  FAIL {page}: {err}")
            continue
        if not args.dry_run:
            page.write_text(html)
        print(f"  {'checked' if args.dry_run else 'wrote'} {page} [{aoi}]: {note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
