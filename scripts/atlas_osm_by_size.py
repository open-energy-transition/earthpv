#!/usr/bin/env python
"""Hand-mapped capacity below and above 400 m2 for every published atlas.

A page built before 2026-11-09 holds its hand-mapped installations by size only as two
counts (`totals.osm_n_lt400`, `osm_n_ge400`). This prices the OSM file behind the page the
way `atlas.build_evidence_atlas` does and writes `configs/atlas_osm_sizes.yaml`, which the
globe's hover card reads (`build_landing_page._atlas_facts`). A page built later carries
`totals.osm_mwp_lt400` and `osm_mwp_ge400` itself and needs no entry.

The page checks the work: a country is written only if the file reproduces the page's two
counts and its `osm_mwp`, so an OSM file pulled after the page was built is refused rather
than published as that page's figure. Solar thermal plants are inside `osm_mwp` at their
electric rating, so they are inside the 400 m2 and up class here, as on the page; the
page's counts leave them out, so the counts here do too.

    pixi run python scripts/atlas_osm_by_size.py [--aoi yemen ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import yaml
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_atlas_pages import ATLASES  # noqa: E402

from earthpv import atlas  # noqa: E402
from earthpv import capacity_calibration as cc  # noqa: E402
from earthpv.labels import dissolve_overlapping  # noqa: E402

OUT = ROOT / "configs" / "atlas_osm_sizes.yaml"
INTERACTIVE = ROOT / "docs" / "assets" / "interactive"
LABELS = ROOT / "data" / "labels"
CELL_DEG = 0.1
MWP_TOLERANCE = 0.15    # the two classes and the page's total are each rounded to 0.1 MWp

# The OSM file behind a page, where it is not <aoi>_national_osm_solar.parquet.
OSM_FILES = {
    "pakistan": "data/labels/pakistan_overpass_solar.parquet",
    "yemen": "data/predictions_v25/yemen/yemen_national_osm_solar_20261101.parquet",
}


def page_data(html: str) -> dict:
    text = (INTERACTIVE / html).read_text()
    block = re.search(r'<script[^>]*id="pv"[^>]*>(.*?)</script>', text, re.S)
    return json.loads(block.group(1))


def aoi_of(html: str) -> str:
    return re.sub(r"(_pv)?_evidence_atlas\.html$", "", html)


def priced(aoi: str, path: Path, totals: dict) -> gpd.GeoDataFrame:
    """The atlas's hand-mapped population with its capacity, before the grid join."""
    osm = gpd.read_parquet(path)
    osm = dissolve_overlapping(osm, group_col="placement")
    osm = atlas._apply_screen_credit(osm)
    osm, _ = atlas._append_csp(osm, aoi, LABELS)
    area = osm["area_m2"].to_numpy(float)
    kwp_mod = totals.get("kwp_per_m2", cc.DEFAULT_KWP_PER_M2_MODULE)
    traced = atlas._osm_traced_ground(osm)
    kwp = np.where(
        osm["placement"] == "rooftop", area * cc.osm_rooftop_kwp_per_m2(area, aoi),
        area * np.where(traced, kwp_mod, cc.DEFAULT_KWP_PER_M2_LAND),
    )
    osm["kwp"] = atlas._csp_kwp(osm, np.asarray(kwp, dtype=float))
    return osm


def in_page_cells(osm: gpd.GeoDataFrame, data: dict) -> gpd.GeoDataFrame:
    """Keep what falls in a cell of the page, as the atlas's own grid join does."""
    cols = {c: i for i, c in enumerate(data["cell_cols"])}
    cells = np.asarray(data["cells"], dtype=float)
    boxes = gpd.GeoDataFrame(
        {"cell_row": range(len(cells))},
        geometry=[box(x, y, x + CELL_DEG, y + CELL_DEG)
                  for x, y in zip(cells[:, cols["lon0"]], cells[:, cols["lat0"]], strict=True)],
        crs=osm.crs,
    )
    points = osm.copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(points, boxes, predicate="within", how="inner")
    return joined[~joined.index.duplicated()]


def split(osm: gpd.GeoDataFrame) -> dict:
    small = osm["area_m2"].to_numpy(float) < 400.0
    kwp = osm["kwp"].to_numpy(float)
    pv = ~osm["csp"].astype(bool).to_numpy()
    return {
        "osm_mwp_lt400": round(float(kwp[small].sum()) / 1000, 1),
        "osm_mwp_ge400": round(float(kwp[~small].sum()) / 1000, 1),
        "n_lt400": int((small & pv).sum()),
        "n_ge400": int((~small & pv).sum()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", nargs="*", help="only these countries (default: every atlas)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    table = yaml.safe_load(OUT.read_text()) if OUT.exists() else {}
    failed = []
    for _, country, html, *_ in ATLASES:
        aoi = aoi_of(html)
        if args.aoi and aoi not in args.aoi:
            continue
        data = page_data(html)
        totals = data["totals"]
        if "osm_mwp_lt400" in totals:
            table.pop(aoi, None)
            continue
        name = OSM_FILES.get(aoi, f"data/labels/{aoi}_national_osm_solar.parquet")
        got = split(in_page_cells(priced(aoi, ROOT / name, totals), data))
        total = got["osm_mwp_lt400"] + got["osm_mwp_ge400"]
        page = (totals["osm_n_lt400"], totals["osm_n_ge400"], totals["osm_mwp"])
        if (got["n_lt400"], got["n_ge400"]) != page[:2] or abs(total - page[2]) > MWP_TOLERANCE:
            failed.append(country)
            print(f"{country:13} NOT REPRODUCED from {name}: {got['n_lt400']}/{got['n_ge400']} "
                  f"features and {total:,.1f} MWp, page {page[0]}/{page[1]} and {page[2]:,.1f}",
                  flush=True)
            continue
        table[aoi] = {k: got[k] for k in ("osm_mwp_lt400", "osm_mwp_ge400")}
        print(f"{country:13} {got['osm_mwp_lt400']:>10,.1f} + {got['osm_mwp_ge400']:>10,.1f} "
              f"= {total:>10,.1f} MWp (page {page[2]:,.1f})", flush=True)

    if failed:
        print("not written, not reproduced:", ", ".join(failed))
        return 1
    if not args.dry_run:
        header = ("# Hand-mapped capacity (MWp) below and above 400 m2 per published atlas, for\n"
                  "# pages that do not carry it in their totals. Written by\n"
                  "# scripts/atlas_osm_by_size.py, each checked against its page's counts and\n"
                  "# osm_mwp. Do not edit by hand.\n")
        OUT.write_text(header + yaml.safe_dump(dict(sorted(table.items())), sort_keys=False))
        print(f"wrote {OUT.relative_to(ROOT)}: {len(table)} atlases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
