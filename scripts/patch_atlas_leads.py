#!/usr/bin/env python
"""Add the mapping-lead download to a published evidence atlas without rebuilding it.

`earthpv atlas` embeds `totals.leads` (`atlas.leads_release`, from the manifest
scripts/release_leads.py writes), which the Downloads section turns into a link to the
country's lead file on GitHub. A page built before 2026-10-28 has no such key.

This recovers the page's placeholder values exactly as `retemplate_atlas.py` does, sets
`totals.leads` from the manifest where the builder puts it (after `import_ceiling`), with
its blob file where there is one, re-resolves the calibration badge (Gold and Silver need a
share of the leads mapped and the model retrained on them, `atlas.resolve_validation_badge`,
so a new declaration can move a badge either way), and fills the current template. Every other key is re-serialised byte for byte, which is
checked before writing, so no figure can change. A page whose AOI has no manifest entry
moves to the new template without a lead link.

    pixi run python scripts/patch_atlas_leads.py docs/assets/interactive/*evidence_atlas.html
    pixi run python scripts/patch_atlas_leads.py PAGE --template <file> --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from patch_atlas_coverage import _insert_after  # noqa: E402
from patch_atlas_pose import DUMPS  # noqa: E402
from retemplate_atlas import PLACEHOLDER, TEMPLATE, aoi_of, extract, read_old_template  # noqa: E402


# The tier a page's badge shows, and the tier it earned when it shows a lower one.
EARNED = re.compile(r'class="vscore vscore--([a-z]+)"[^>]*?(?:data-earned="([a-z]+)")?>')


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
            leads = atlas.leads_for_page(aoi)
            # The badge follows the lead rule (atlas.resolve_validation_badge): the tier the
            # page EARNED is read from the badge it carries (`data-earned` when it shows a
            # lower one), so declaring a country's leads mapped restores it without a rebuild.
            m = EARNED.search(values["__VALIDATION_BADGE__"])
            earned = m.group(2) or m.group(1)
            values["__VALIDATION_BADGE__"] = atlas.resolve_validation_badge(aoi, earned)
            shown = atlas.shown_validation_score(aoi, atlas.earned_validation_score(aoi, earned))
            T = {k: v for k, v in data["totals"].items() if k != "leads"}
            data["totals"] = _insert_after(T, "import_ceiling", {"leads": leads}) if leads else T
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
        what = f"{leads['n']:,} leads, {leads['file']}" if leads else "no lead file"
        what += f"; badge {shown}" + (f" (earned {earned})" if shown != earned else "")
        print(f"  {'checked' if args.dry_run else 'wrote'} {page} [{aoi}]: {what}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
