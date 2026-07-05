"""Build Germany as a 2-layer 0.1-degree composed AOI (base summer + winter contrast).

Germany's base imagery is stored as huge per-MGRS-tile composites; building a matching
winter tile means re-downloading a whole season over 10k x 10k px (~hours/tile). Instead
we composite only the 0.1-degree cells that actually contain PV labels (the chip-sampling
footprint), both seasons, at ~50 s/cell — the same fast per-cell path Punjab/Pakistan use.
Output mirrors the composed-AOI layout (data/composites/germany/composites/<ix>_<iy>/),
which chips.py/infer.py already prefer. Resumable.

The geographic val split is the SW cells (the old 32TPT/32TQT region); their names are
printed so configs/aoi.yaml germany.val_tiles can be set to them.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from odc.geo.geobox import GeoBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.imagery import annual_composite  # noqa: E402
from earthpv.local_source import CompositeIndex, load_solar_labels  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("de-seasonal")

CELL = 0.1
SUMMER = ("2025-04-01", "2025-09-30")   # base: leaf-on, matches original germany composites
WINTER = ("2025-11-01", "2026-03-15")   # contrast: leaf-off
RS = Path("/run/media/tobi/aidisc/rooftopsenti/data/germany_500")
OUT = Path("data/composites/germany/composites")
# SW val box (~Freiburg/Stuttgart, the old 32TPT/32TQT tiles held out for validation)
VAL_BOX = (7.3, 47.4, 9.7, 49.2)


def top_pv_cells(n: int) -> pd.DataFrame:
    lab = load_solar_labels(RS)
    cov = CompositeIndex(RS).coverage
    lab = lab[lab.geometry.centroid.within(cov)]
    pos = lab[lab.placement.isin(["rooftop", "ground"]) & (lab.area_m2 >= 400)]
    c = pos.geometry.centroid
    ix = np.floor(c.x / CELL).astype(int)
    iy = np.floor(c.y / CELL).astype(int)
    vc = pd.Series(list(zip(ix, iy))).value_counts().head(n)
    rows = [{"ix": a, "iy": b, "n": int(k), "lon0": a * CELL, "lat0": b * CELL}
            for (a, b), k in vc.items()]
    return pd.DataFrame(rows)


def _build_cell(cell) -> str | None:
    """Build both season layers for one 0.1-deg cell. Returns cell name on success."""
    name = f"{int(cell.ix):04d}_{int(cell.iy):04d}"
    x0, y0 = cell.lon0, cell.lat0
    cell_dir = OUT / name
    cell_dir.mkdir(parents=True, exist_ok=True)
    bbox = (x0, y0, x0 + CELL, y0 + CELL)
    base = cell_dir / "composite_0.tif"
    try:
        if not base.exists():
            res = annual_composite(bbox, date_range=SUMMER, max_cloud=60, max_items=15)
            if res is None:
                log.warning("%s: no summer scenes, skip", name)
                return None
            _write(base, *res)
        contrast = cell_dir / "composite_1.tif"
        if not contrast.exists():
            with rasterio.open(base) as b:
                gbox = GeoBox((b.height, b.width), b.transform, b.crs)
            res = annual_composite(bbox, date_range=WINTER, geobox=gbox, max_cloud=60, max_items=15)
            if res is None:
                log.warning("%s: no winter scenes, skip", name)
                return None
            _write(contrast, *res)
    except Exception as e:  # noqa: BLE001 — one bad cell must not kill the run
        log.warning("%s failed: %s", name, e)
        return None
    log.info("%s: done (%d positives)", name, int(cell.n))
    return name


def main(n: int = 160, workers: int = 5) -> None:
    from concurrent.futures import ThreadPoolExecutor

    cells = top_pv_cells(n)
    OUT.mkdir(parents=True, exist_ok=True)
    val = [f"{int(c.ix):04d}_{int(c.iy):04d}" for _, c in cells.iterrows()
           if VAL_BOX[0] <= c.lon0 < VAL_BOX[2] and VAL_BOX[1] <= c.lat0 < VAL_BOX[3]]
    rows = [c for _, c in cells.iterrows()]
    ok = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_build_cell, rows):
            ok += int(r is not None)
    log.info("Germany seasonal cells built: %d/%d. VAL cells (%d): %s",
             ok, len(cells), len(val), val)


def _write(path: Path, arr: np.ndarray, transform, crs) -> None:
    # temp+rename so a killed run never leaves a half-written COG the resume would skip
    tmp = path.with_suffix(".tif.tmp")
    with rasterio.open(
        tmp, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
        dtype="uint16", crs=crs, transform=transform, compress="deflate", predictor=2,
    ) as dst:
        dst.write(arr)
    tmp.rename(path)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 160)
