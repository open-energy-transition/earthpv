#!/usr/bin/env python
"""Set the view a published evidence atlas opens on, from its country's `map_view`, without
rebuilding it.

`earthpv atlas` writes the map's frame into the page's data block as `bounds` [west, south,
east, north]: the whole country with every unimaged cell, or `map_view` from
`configs/atlas/<aoi>.yaml` where the country names one (owner, 2026-11-10: Spain and
Portugal open on the mainland, not on an ocean holding the Canaries, the Azores and
Madeira). The template reads `bounds` for the opening view, the map's height and the reset
button, and for nothing else, so this rewrites that one value and leaves every other byte of
the page alone, which it checks before writing.

    pixi run python scripts/patch_atlas_view.py docs/assets/interactive/spain_pv_evidence_atlas.html \\
        results/spain_pv_evidence_atlas.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earthpv import atlas_config  # noqa: E402

BLOCK = re.compile(r'(<script[^>]*id="pv"[^>]*>)(.*?)(</script>)', re.S)
BOUNDS = re.compile(r'"bounds":\[[^\]]*\]')


def aoi_of(html: str) -> str:
    m = re.search(r'class="wrap"[^>]*data-aoi-key="([^"]+)"', html)
    if not m:
        raise SystemExit("page carries no data-aoi-key")
    return m.group(1)


def patch(path: Path, dry_run: bool = False) -> str:
    html = path.read_text(encoding="utf-8")
    aoi = aoi_of(html)
    view = atlas_config.load(aoi).map_view
    if not view:
        raise SystemExit(f"{path}: configs/atlas/{aoi}.yaml has no map_view; a page without "
                         "one frames the whole country, which only a rebuild can recompute")
    m = BLOCK.search(html)
    if not m or len(BLOCK.findall(html)) != 1:
        raise SystemExit(f"{path}: expected exactly one data block")
    block = m.group(2)
    if len(BOUNDS.findall(block)) != 1:
        raise SystemExit(f"{path}: expected exactly one compact \"bounds\" in the data block")
    old = json.loads(block)
    new_bounds = [round(v, 3) for v in view]
    new_block = BOUNDS.sub(lambda _: '"bounds":' + json.dumps(new_bounds, separators=(",", ":")),
                           block)
    new = json.loads(new_block)
    if new["bounds"] != new_bounds:
        raise SystemExit(f"{path}: rewrite did not land")
    if {k: v for k, v in new.items() if k != "bounds"} != {k: v for k, v in old.items()
                                                          if k != "bounds"}:
        raise SystemExit(f"{path}: something besides bounds changed")
    out = html[:m.start(2)] + new_block + html[m.end(2):]
    if not dry_run and out != html:
        path.write_text(out, encoding="utf-8")
    return f"{path}: {aoi} bounds {old['bounds']} -> {new_bounds}" + (" (dry run)" if dry_run else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pages", nargs="+", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    for p in a.pages:
        print(patch(p, a.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
