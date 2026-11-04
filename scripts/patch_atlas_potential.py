#!/usr/bin/env python
"""Add the rooftop potential layer's data to a published evidence atlas without rebuilding it.

`earthpv atlas` does this by itself wherever `earthpv roof-potential` has run. A page built
before that needs `scripts/retemplate_atlas.py` first, for the layer's code, and then this for
its data: `potential_gwh` and `potential_mwp` at the end of every cell, and
`totals.potential`. Nothing else on the page changes; every other key is re-serialised byte for
byte, which is checked before writing. Re-running replaces the earlier figures.

    pixi run python scripts/patch_atlas_potential.py docs/assets/interactive/pakistan_evidence_atlas.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from patch_atlas_pose import DUMPS  # noqa: E402
from retemplate_atlas import aoi_of  # noqa: E402

from earthpv import potential  # noqa: E402

DATA_BLOCK = re.compile(r'(<script id="pv" type="application/json">)(.*?)(</script>)', re.S)


def patch(html: str, aoi: str, density_dir: Path) -> tuple[str, dict]:
    if '"potential_gwh"' not in html:
        raise ValueError("no layer code on this page: run retemplate_atlas.py on it first")
    block = DATA_BLOCK.search(html)
    data = json.loads(block.group(2))
    if json.dumps(data, **DUMPS) != block.group(2):
        raise ValueError("the data block does not re-serialise byte for byte")

    cols = data["cell_cols"]
    n_old = next((i for i, c in enumerate(cols) if c in potential.POTENTIAL_CELL_COLS), len(cols))
    grid = pd.read_parquet(density_dir / "grid.geoparquet", columns=["cell", "lon0", "lat0"])
    pot = potential.load_potential(
        density_dir.parent / potential.POTENTIAL_CELLS_RELPATH, grid["cell"], aoi,
        data["totals"]["kwp_per_m2"])
    by_corner = {
        (round(float(x), 3), round(float(y), 3)): (round(float(g), 2), round(float(m), 2))
        for x, y, g, m in zip(
            grid["lon0"], grid["lat0"], pot["gwh"].sum(axis=1), pot["mwp"].sum(axis=1))
    }
    corners = {(c[0], c[1]) for c in data["cells"]}
    missing = set(by_corner) - corners
    if missing:
        raise ValueError(f"{len(missing)} cells of the grid are not on this page")
    data["cell_cols"] = [*cols[:n_old], *potential.POTENTIAL_CELL_COLS]
    data["cells"] = [
        [*c[:n_old], *by_corner.get((c[0], c[1]), (0.0, 0.0))] for c in data["cells"]
    ]
    data["totals"]["potential"] = potential.potential_totals(pot)
    new = block.group(1) + json.dumps(data, **DUMPS) + block.group(3)
    return html[:block.start()] + new + html[block.end():], data["totals"]["potential"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", nargs="+", type=Path)
    ap.add_argument("--aoi")
    ap.add_argument("--density-dir", type=Path,
                    help="the run behind the page (default data/predictions/<aoi>/density)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for page in args.pages:
        aoi = args.aoi or aoi_of(page)
        density_dir = args.density_dir or ROOT / "data" / "predictions" / aoi / "density"
        html, totals = patch(page.read_text(), aoi, density_dir)
        if not args.dry_run:
            page.write_text(html)
        print(f"{page}: {totals}{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
