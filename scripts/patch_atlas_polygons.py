#!/usr/bin/env python
"""Add the solar polygon download to a published evidence atlas without rebuilding it.

`earthpv atlas` embeds `totals.polygons` (`atlas.polygons_release`, from the manifest
scripts/release_polygons.py writes), which the Downloads section turns into a card linking
the country's GeoParquet of every model outline and OpenStreetMap solar feature behind the
page. A page built before 2026-11-11 has no such key.

This recovers the page's placeholder values exactly as `retemplate_atlas.py` does, sets
`totals.polygons` from the manifest where `patch_atlas_leads.py` puts the lead files (after
`leads`), and fills the current template. Every other key is re-serialised byte for byte,
which is checked before writing, so no figure can change. A page whose AOI has no manifest
entry is left alone. Patch the sync source in results/ too, or `pixi run docs-figures`
copies the old page back.

    pixi run python scripts/patch_atlas_polygons.py docs/assets/interactive/india_pv_evidence_atlas.html \
        results/india_pv_evidence_atlas.html
    pixi run python scripts/patch_atlas_polygons.py PAGE --template <file> --dry-run
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
            aoi = args.aoi or aoi_of(page)
            polygons = atlas.polygons_release(aoi)
            if not polygons:
                print(f"  skip {page} [{aoi}]: no polygon file in the manifest")
                continue
            values = extract(old, page.read_text())
            raw = values["__PV_DATA_JSON__"]
            data = json.loads(raw)
            if json.dumps(data, **DUMPS) != raw:
                raise ValueError("the data block does not re-serialise byte for byte")
            T = {k: v for k, v in data["totals"].items() if k != "polygons"}
            after = "leads" if "leads" in T else "import_ceiling"
            data["totals"] = _insert_after(T, after, {"polygons": polygons})
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
        print(f"  {'checked' if args.dry_run else 'wrote'} {page} [{aoi}]: "
              f"{polygons['n_model']:,} model + {polygons['n_osm']:,} OSM outlines, "
              f"{polygons['file']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
