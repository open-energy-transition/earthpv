"""Pull GlobalBuildingAtlas building heights over the calibration quadrats.

GBA (zhu-xlab) publishes global building polygons plus an LoD1 height per building. Height
is a dimension nothing in `roofclf` has: a warehouse and a shed with identical footprints
are different PV propensities, and the feature set currently cannot tell them apart.

Two files are needed per 5-degree tile and they are big, so this STREAMS them rather than
downloading:

  Polygon/<tile>.geojson  ~3.0 GB   geometry + id, EPSG:3857, one feature per line, ODbL
  LoD1/<tile>.json        ~4.0 GB   a flat {building_id: {height, var}} lookup, CC BY-NC 4.0

Only features inside a quadrat bbox are kept, which is a few km2 out of a ~250,000 km2 tile,
so the retained output is small. The first pass collects ids and geometry, the second keeps
heights for those ids only.

**LICENCE, read before using any of this downstream.** The polygons are ODbL but the HEIGHTS
are CC BY-NC 4.0. This project publishes open data and has already turned down one dataset
on exactly this ground (the African rooftop PV dataset, CC BY-NC-ND). Measuring whether
height helps is research; shipping a capacity figure derived from it is not, unless the
licence is cleared. Nothing here writes into the published pipeline.

    pixi run python scripts/gba_height_extract.py --tile e070_n35_e075_n30
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import box as shp_box
from shapely.geometry import shape

from earthpv.roofclf import discover_quadrats, load_quadrat

log = logging.getLogger("gba_height")
HF = "https://huggingface.co/datasets/zhu-xlab"
POLY = HF + "/GBA.ODbLPolygon/resolve/main/asiawest/{tile}.geojson"
LOD1 = HF + "/GBA.LoD1/resolve/main/LoD1/asiawest/{tile}.json"
# The polygons are web mercator; quadrat bounds are lon/lat.
MERC = "EPSG:3857"
_COORD = re.compile(rb"\[\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\]")
_ID = re.compile(rb'"id":\s*"([^"]+)"')
_HEIGHT = re.compile(rb'"([^"]+?)":\s*\{"height":\s*(-?\d+\.?\d*),\s*"var":\s*(-?\d+\.?\d*)\}')


def quadrat_bounds(labels_dir: Path, margin_m: float = 300.0):
    """Union of quadrat bboxes, in web mercator, as a list plus a fast overall box."""
    rows = []
    for stem in sorted(discover_quadrats(labels_dir)):
        b, _ = load_quadrat(stem, labels_dir)
        g = gpd.GeoSeries([shp_box(*b.bounds)], crs="EPSG:4326").to_crs(MERC).iloc[0]
        rows.append((stem, g.buffer(margin_m).bounds))
    return rows


def stream(url: str):
    """Yield raw lines from a remote file without ever storing it."""
    p = subprocess.Popen(["curl", "-sL", url], stdout=subprocess.PIPE, bufsize=1 << 22)
    try:
        for line in p.stdout:
            yield line
    finally:
        p.stdout.close()
        p.terminate()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tile", default="e070_n35_e075_n30")
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--out", type=Path, default=Path("data/gba"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)

    qb = quadrat_bounds(args.labels_dir)
    boxes = [b for _, b in qb]
    gx0 = min(b[0] for b in boxes)
    gy0 = min(b[1] for b in boxes)
    gx1 = max(b[2] for b in boxes)
    gy1 = max(b[3] for b in boxes)
    log.info("%d quadrats; overall mercator box %.0f %.0f %.0f %.0f", len(qb), gx0, gy0, gx1, gy1)

    keep_geom, keep_id = [], []
    n_seen = 0
    for line in stream(POLY.format(tile=args.tile)):
        if b'"Feature"' not in line:
            continue
        n_seen += 1
        m = _COORD.search(line)
        if not m:
            continue
        x, y = float(m.group(1)), float(m.group(2))
        if not (gx0 <= x <= gx1 and gy0 <= y <= gy1):
            continue
        if not any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes):
            continue
        mid = _ID.search(line)
        try:
            feat = json.loads(line.rstrip(b",\n").decode("utf8"))
        except Exception:  # noqa: BLE001 - a truncated line is not worth killing the pass
            continue
        keep_geom.append(shape(feat["geometry"]))
        keep_id.append(feat["properties"].get("id") or (mid and mid.group(1).decode()))
        if n_seen % 2_000_000 == 0:
            log.info("  polygons scanned %d, kept %d", n_seen, len(keep_id))
    log.info("polygon pass done: %d scanned, %d kept inside quadrats", n_seen, len(keep_id))
    if not keep_id:
        raise SystemExit("no GBA polygons fell inside any quadrat -- wrong tile?")

    want = set(keep_id)
    heights = {}
    for chunk in stream(LOD1.format(tile=args.tile)):
        for m in _HEIGHT.finditer(chunk):
            bid = m.group(1).decode("utf8", "replace")
            if bid in want:
                h = float(m.group(2))
                if h > -900:
                    heights[bid] = (h, float(m.group(3)))
    log.info("height pass done: %d of %d kept buildings have a height (%.1f%%)",
             len(heights), len(want), 100 * len(heights) / max(len(want), 1))

    g = gpd.GeoDataFrame(
        {"gba_id": keep_id,
         "gba_height": [heights.get(i, (np.nan, np.nan))[0] for i in keep_id],
         "gba_height_var": [heights.get(i, (np.nan, np.nan))[1] for i in keep_id]},
        geometry=keep_geom, crs=MERC).to_crs("EPSG:4326")
    dst = args.out / f"{args.tile}_quadrats.parquet"
    g.to_parquet(dst)
    h = g.gba_height.dropna()
    log.info("wrote %s: %d buildings, height median %.1f m, p10 %.1f, p90 %.1f",
             dst, len(g), h.median(), h.quantile(.1), h.quantile(.9))


if __name__ == "__main__":
    main()
