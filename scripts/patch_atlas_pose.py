#!/usr/bin/env python
"""Add or replace the panel-pose section of a published evidence atlas without rebuilding it.

`earthpv atlas --pose-summary-csv` embeds the glint pose survey when a page is built. A
survey that finishes after its country's atlas was published (France, 2026-10-26), or a
change to what each pose point carries, would otherwise need a full rebuild, which re-reads
every pipeline input and can move figures that were never meant to change.

This recovers the page's placeholder values exactly as `retemplate_atlas.py` does, replaces
only the `pose` key of the embedded data block with `pose.compute_pose_survey_data`'s output
(the same function the builder calls, with the same admin-1 regions), and fills the CURRENT
template. Every other key is re-serialised byte for byte, which is checked before writing.

    pixi run python scripts/patch_atlas_pose.py results/france_pv_evidence_atlas.html \\
        --summary data/glint/france_pose/summary.csv --country France \\
        --density-dir data/predictions_v5/france/density \\
        --data-note "(all 6,337 OSM installations of 1,000 m2 or more, imagery Oct 2025 to Sep 2026)"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from retemplate_atlas import PLACEHOLDER, TEMPLATE, aoi_of, extract, read_old_template  # noqa: E402

# What build_evidence_atlas writes, except that a NaN fails here instead of reaching the
# page, where it is not JSON and blanks the whole atlas.
DUMPS = dict(separators=(",", ":"), allow_nan=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", nargs="+", type=Path, help="copies of one country's atlas")
    ap.add_argument("--summary", required=True, type=Path, help="glint pose summary CSV")
    ap.add_argument("--country", required=True, help="name the pose section uses")
    ap.add_argument("--density-dir", type=Path, help="its regions.geoparquet names each "
                    "point's province; omit and points carry no province")
    ap.add_argument("--history-note", default="")
    ap.add_argument("--data-note", default="")
    ap.add_argument("--old-template", default="HEAD",
                    help="git revision (or file) of the template the pages were built from")
    ap.add_argument("--aoi")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "src"))
    import geopandas as gpd

    from earthpv import atlas, pose

    regions = None
    if args.density_dir is not None:
        regions = atlas._region_rows(gpd.read_parquet(args.density_dir / "regions.geoparquet"))
    new_pose = pose.compute_pose_survey_data(args.summary, args.country, args.history_note,
                                             args.data_note, regions=regions)

    old = read_old_template(args.old_template)
    new = TEMPLATE.read_text()
    failed = 0
    for page in args.pages:
        try:
            values = extract(old, page.read_text())
            raw = values["__PV_DATA_JSON__"]
            data = json.loads(raw)
            if json.dumps(data, **DUMPS) != raw:
                raise ValueError("the data block does not re-serialise byte for byte")
            before = data.get("pose")
            data["pose"] = new_pose
            values["__PV_DATA_JSON__"] = json.dumps(data, **DUMPS)
            aoi = args.aoi or aoi_of(page)
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
        st = new_pose["stats"]
        was = f"{before['stats']['n_fitted']} fits" if before else "no pose section"
        if not args.dry_run:
            page.write_text(html)
        print(f"  {'checked' if args.dry_run else 'wrote'} {page} [{aoi}]: {was} -> "
              f"{st['n_fitted']} of {st['n_total']} fitted")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
