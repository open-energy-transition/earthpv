"""Build the Pakistan PV growth atlas (segmentation growth-map diff + SPPI epoch-diff).

Reads scripts/pv_growth_map.py's and scripts/sppi_growth_map.py's outputs (both under
data/predictions/pakistan/density/growth/) and writes the two-tab night-lights atlas to
results/pakistan_pv_growth_atlas.html via earthpv.atlas.build_growth_atlas.
"""

from __future__ import annotations

import logging
from pathlib import Path

from earthpv.atlas import build_growth_atlas

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if __name__ == "__main__":
    build_growth_atlas(
        aoi="pakistan",
        growth_dir=Path("data/predictions/pakistan/density/growth"),
        out=Path("results/pakistan_pv_growth_atlas.html"),
    )
