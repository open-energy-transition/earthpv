#!/usr/bin/env python
"""Choose a country's validation holdout from its label map, before any training.

The localized-segmentation ship rule (owner, 2026-09-23) compares the local checkpoint
against v5 on a held-out region, so that region has to be fixed before either model is
scored and has to be chosen without looking at a score. Vietnam's and India's were picked
by hand on that principle; this script states the rule so a run can apply it unattended:

  - positives are dissolved OSM solar features at or above the 400 m2 chip floor
    (`chips.MIN_PV_AREA`), counted once per connected cluster;
  - each is assigned to a geoBoundaries ADM1 region by representative point;
  - the region holding the MOST positives is never chosen (it is the training core);
  - among regions holding between 8% and 30% of positives and at least 15 of them, the one
    closest to `--target` (17%, Vietnam's share) wins; failing that, any region but the
    largest with at least 10 positives, then at least 5, closest to the target.

`val_tiles` are the composited-or-selected cells (the duckdb cell cache at the compose
building floor, plus every cell holding a positive) whose centre lies in the region.
`--write` replaces the AOI's `val_tiles: []` in configs/aoi.yaml with that list and a
comment recording the choice, and refuses to overwrite a non-empty list.

    python scripts/pick_val_region.py --aoi morocco [--write]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from earthpv.chips import MIN_PV_AREA  # noqa: E402
from earthpv.config import CONFIG_PATH, Settings  # noqa: E402
from earthpv.density import fetch_geoboundaries  # noqa: E402
from earthpv.labels import dissolve_overlapping  # noqa: E402

CELL_DEG = 0.1


def pick(aoi: str, target: float, min_buildings: int) -> tuple[str, list[str], dict]:
    cfg = Settings.load().aois[aoi]
    iso3 = cfg["division"]["iso3"]
    ox, oy = cfg.get("grid_origin", cfg["bbox"][:2])

    lab = gpd.read_parquet(REPO / f"data/labels/{aoi}_overpass_solar.parquet")
    lab = lab[lab.geom_type.isin(["Polygon", "MultiPolygon"])]
    pos = dissolve_overlapping(lab, group_col=None)
    pos = pos[pos["area_m2"] >= MIN_PV_AREA]
    pts = gpd.GeoDataFrame(geometry=pos.geometry.representative_point(), crs=pos.crs)

    adm = fetch_geoboundaries(iso3, "ADM1")
    adm = adm.to_crs(pts.crs)
    joined = gpd.sjoin(pts, adm[["name", "geometry"]], predicate="within", how="inner")
    counts = joined.groupby("name").size().sort_values(ascending=False)
    total = int(counts.sum())
    share = counts / total
    core = counts.index[0]
    ok = share[(share >= 0.08) & (share <= 0.30) & (counts >= 15) & (share.index != core)]
    if ok.empty:
        ok = share[(counts >= 10) & (share.index != core)]
    if ok.empty:
        # Thin label maps (Morocco 2026-10-10: 39 positives once solar-thermal is removed).
        # A holdout this small cannot settle the ship rule, and the results page must say
        # so; it still keeps the comparison out of sample.
        ok = share[(counts >= 5) & (share.index != core)]
    if ok.empty:
        raise SystemExit(f"{aoi}: no ADM1 region qualifies as a holdout ({dict(counts)})")
    region = (ok - target).abs().idxmin()

    cells = pd.read_parquet(REPO / f"data/cells_cache/{aoi}_cells.parquet")
    cells = cells[cells["n"] >= min_buildings][["ix", "iy"]]
    lab_cells = pd.DataFrame({
        "ix": ((pts.geometry.x - ox) // CELL_DEG).astype(int),
        "iy": ((pts.geometry.y - oy) // CELL_DEG).astype(int),
    })
    cells = pd.concat([cells, lab_cells]).drop_duplicates()
    centres = gpd.GeoDataFrame(
        cells,
        geometry=gpd.points_from_xy(ox + (cells.ix + 0.5) * CELL_DEG, oy + (cells.iy + 0.5) * CELL_DEG),
        crs="EPSG:4326",
    )
    poly = adm.loc[adm["name"] == region, "geometry"].to_crs("EPSG:4326").union_all()
    inside = centres[centres.within(poly)]
    tiles = sorted(f"{ix:04d}_{iy:04d}" for ix, iy in zip(inside.ix, inside.iy))
    info = {
        "region": region, "positives": int(counts[region]), "total_positives": total,
        "share": round(float(share[region]), 3), "core": core, "core_positives": int(counts[core]),
        "cells": len(tiles), "regions_with_positives": len(counts),
    }
    return region, tiles, info


def write(aoi: str, tiles: list[str], info: dict) -> None:
    text = CONFIG_PATH.read_text()
    m = re.search(rf"\n  {re.escape(aoi)}:\n", text)
    if not m:
        raise SystemExit(f"{aoi} not found in {CONFIG_PATH}")
    j = text.find("    val_tiles: []\n", m.end())
    nxt = re.search(r"\n  [a-z_]+:\n", text[m.end():])
    if j < 0 or (nxt and j > m.end() + nxt.start()):
        raise SystemExit(f"{aoi}: no empty `val_tiles: []` in its block; refusing to overwrite")
    comment = (
        f"    # Val holdout = {info['region']} (geoBoundaries ADM1), {info['cells']} cells, chosen by\n"
        f"    # scripts/pick_val_region.py from the label map before training: {info['positives']} of\n"
        f"    # {info['total_positives']} dissolved >= 400 m2 positives ({100 * info['share']:.1f}%); the largest\n"
        f"    # region ({info['core']}, {info['core_positives']}) is never the holdout.\n"
    )
    rows = [", ".join(f'"{t}"' for t in tiles[k:k + 8]) for k in range(0, len(tiles), 8)]
    block = comment + "    val_tiles: [\n" + "".join(f"      {r},\n" for r in rows) + "    ]\n"
    new = text[:j] + block + text[j + len("    val_tiles: []\n"):]
    parsed = yaml.safe_load(new)
    assert parsed["aois"][aoi]["val_tiles"] == tiles
    CONFIG_PATH.write_text(new)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--target", type=float, default=0.17)
    ap.add_argument("--min-buildings", type=int, default=1000)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    region, tiles, info = pick(a.aoi, a.target, a.min_buildings)
    print(info)
    if a.write:
        write(a.aoi, tiles, info)
        print(f"wrote {len(tiles)} val_tiles for {a.aoi} to {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
