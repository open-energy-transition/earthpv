"""How many 0.1 deg cells does Nigeria's compose have to build, by threshold?

`--min-buildings` is the single biggest lever on a country-scale compose: the link is the
binding constraint (CLAUDE.md, "compose is bandwidth-bound"), so the cell count IS the
schedule. Zambia ran at 1000; Germany and France were rebuilt on 2026-09-15 with no filter
at all, which only added 188/988 cells because both are uniformly built. Nigeria is not,
so this prints the whole curve before anything is committed.

Read-only: it runs the same `compose.populated_cells` selection the real run would, at
min_buildings=1 and without labels, then histograms the per-cell building counts.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from earthpv.compose import populated_cells  # noqa: E402
from earthpv.config import Settings  # noqa: E402

AOI = "nigeria"
MB_PER_CELL = 13.0  # measured: Zambia's 1,843 cells occupy 24 GB
CELLS_PER_MIN = 0.6  # measured on the concurrent France pass, 2026-09-15

settings = Settings.load()
cfg = settings.aois[AOI]
cells = populated_cells(AOI, cfg, settings, min_buildings=1, include_labels=False)
n = cells.n.values
print(f"\n{AOI}: {len(cells):,} cells hold at least one VIDA building "
      f"({n.sum():,.0f} buildings total)\n")
print(f"{'min_buildings':>14} {'cells':>9} {'% of bldgs':>11} {'GB':>7} {'days @0.6/min':>14}")
for t in (1, 10, 50, 100, 250, 500, 1000, 2000, 5000):
    sel = n >= t
    print(f"{t:>14} {sel.sum():>9,} {100 * n[sel].sum() / n.sum():>10.1f}% "
          f"{sel.sum() * MB_PER_CELL / 1024:>6.0f}G {sel.sum() / CELLS_PER_MIN / 1440:>13.1f}")
