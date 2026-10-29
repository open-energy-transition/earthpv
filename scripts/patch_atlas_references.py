#!/usr/bin/env python
"""Add the "Against official and published figures" section to a published evidence atlas
without rebuilding it.

`earthpv atlas` embeds `totals.references` (`atlas.official_capacity`, from
configs/external/official_capacity.yaml, which scripts/official_capacity.py writes), and
the template draws it beside the page's own total and provinces with the Ember customs
record it already carries (`totals.import_ceiling`). A page built before 2026-10-29 has no
such key, and shows the Ember figure under its headline instead, which the template no
longer does.

This recovers the page's placeholder values exactly as `retemplate_atlas.py` does, sets
`totals.references` where the builder puts it (after `import_ceiling`), checking every
province key against the page's own provinces, and fills the current template. Every
other key is re-serialised byte for byte, which is checked before writing, so no figure
can change. A page whose AOI has no entry moves to the new template with the customs
record alone.

    pixi run python scripts/patch_atlas_references.py docs/assets/interactive/*evidence_atlas.html
    pixi run python scripts/patch_atlas_references.py PAGE --template <file> --dry-run
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
            values = extract(old, page.read_text())
            raw = values["__PV_DATA_JSON__"]
            data = json.loads(raw)
            if json.dumps(data, **DUMPS) != raw:
                raise ValueError("the data block does not re-serialise byte for byte")
            aoi = args.aoi or aoi_of(page)
            refs = atlas.official_capacity(aoi, [p["name"] for p in data["provinces"]])
            T = {k: v for k, v in data["totals"].items() if k != "references"}
            data["totals"] = _insert_after(T, "import_ceiling", {"references": refs}) if refs else T
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
        what = ", ".join(f"{r['name']} ({len(r.get('regions') or {})} provinces)"
                         for r in refs or []) or "no references"
        ic = "customs record" if data["totals"].get("import_ceiling") else "no customs record"
        print(f"  {'checked' if args.dry_run else 'wrote'} {page} [{aoi}]: {what}; {ic}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
