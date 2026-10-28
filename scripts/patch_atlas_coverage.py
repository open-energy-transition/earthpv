#!/usr/bin/env python
"""Add the unimaged cells to a published evidence atlas without rebuilding it.

`earthpv atlas` embeds `unimaged`, the country's 0.1-degree cells that no detector looked
at, which the map hatches, and `totals.n_cells_country` / `n_cells_processed`, which the
coverage tile reports (both from `atlas._cell_coverage`). A page built before 2026-10-28 has
no `unimaged`, and one built before 2026-10-24 has neither: on its map an unimaged cell and
an imaged cell where nothing was found are both bare land.

This recovers the page's placeholder values exactly as `retemplate_atlas.py` does, computes
the coverage with the builder's own function, on the regions the builder drew
(`atlas._page_regions`) and the page's own imaged cells (`model_covered`), adds it to the
embedded data block, widens the map's `bounds` to the whole country as the builder now does,
and fills the current template. Every other key is re-serialised byte
for byte, which is checked before writing; a page that already carries the two counts must
get the same counts back, or it is refused.

    pixi run python scripts/patch_atlas_coverage.py docs/assets/interactive/egypt_pv_evidence_atlas.html
    pixi run python scripts/patch_atlas_coverage.py results/france_pv_evidence_atlas.html \\
        --density-dir data/predictions_v5/france/density
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from patch_atlas_pose import DUMPS  # noqa: E402
from retemplate_atlas import PLACEHOLDER, TEMPLATE, aoi_of, extract, read_old_template  # noqa: E402


def _insert_after(d: dict, after: str, items: dict) -> dict:
    """`d` with `items` placed where the builder writes them, after key `after`."""
    out = {}
    for k, v in d.items():
        if k not in items:
            out[k] = v
        if k == after:
            out.update(items)
    if after not in d:
        out.update(items)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", nargs="+", type=Path)
    ap.add_argument("--density-dir", type=Path,
                    help="holds the regions.geoparquet the page was built with "
                         "(default data/predictions/<aoi>/density)")
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
            density_dir = args.density_dir or Path(f"data/predictions/{aoi}/density")
            regions = atlas._page_regions(aoi, density_dir / "regions.geoparquet")
            names = sorted(p["name"] for p in data.get("provinces", []))
            if names != sorted(map(str, regions.name)):
                raise ValueError(f"{density_dir} does not hold the regions this page draws")
            cols = data["cell_cols"]
            k = cols.index("model_covered") if "model_covered" in cols else None
            cells = [c for c in data["cells"] if k is None or c[k]]
            processed = pd.DataFrame({"lon_center": [c[0] + 0.05 for c in cells],
                                      "lat_center": [c[1] + 0.05 for c in cells]})
            cover = atlas._cell_coverage(aoi, regions.geometry.union_all(), processed)
            runs = cover.pop("unimaged")
            T = data["totals"]
            for key, v in cover.items():
                if key in T and T[key] != v:
                    raise ValueError(f"totals.{key} is {T[key]} on the page, {v} recomputed")
            if sum(r[2] for r in runs) != cover["n_cells_country"] - cover["n_cells_processed"]:
                raise ValueError("the unimaged runs do not add up to the two counts")
            data["totals"] = _insert_after(T, "n_cells", cover)
            data["bounds"] = atlas._bounds_with_runs(data["bounds"], runs)
            data = _insert_after(data, "cell_cols", {"unimaged": runs})
            values["__PV_DATA_JSON__"] = json.dumps(data, **DUMPS)
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
        n = cover["n_cells_country"]
        print(f"  {'checked' if args.dry_run else 'wrote'} {page} [{aoi}]: "
              f"{cover['n_cells_processed']:,} of {n:,} cells imaged, "
              f"{n - cover['n_cells_processed']:,} unimaged in {len(runs):,} runs")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
