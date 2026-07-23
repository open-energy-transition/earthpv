"""Glint as a standalone PV detector: instead of scoring existing segmentation-model
candidates (`postprocess.add_glint_prior`), run the self-referenced glint check directly
over building footprints, independent of whether the segmentation model ever flagged
them. Point of this: the model has a known recall floor for small arrays (Lahore
calibration box, docs/issues/pakistan-calibration-boxes.md: 0/8 recall on 314-577 m2
installations) -- glint physics doesn't care about array size the way a vision model's
learned prior does, so it's a genuinely independent detection channel, not just a
re-ranking of the same candidates.

Self-referenced criterion (`glint.annotate_spikes(..., self_referenced=True)`) is
required, not the default spatial one: most urban buildings sit among similarly-bright
neighbours, so "annulus must be dim right now" rarely fires (see
[[earthpv-glint-direct-detection]] -- confirmed 0% in a dense Lahore block with the
default criterion).

Usage:
  .pixi/envs/default/bin/python scripts/glint_direct_detect.py --pilot            # Lahore, capped
  .pixi/envs/default/bin/python scripts/glint_direct_detect.py --city lahore      # one city, full
  .pixi/envs/default/bin/python scripts/glint_direct_detect.py                    # all cities
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR, Settings  # noqa: E402
from earthpv.export import _load_mapped_reference, new_lead_mask  # noqa: E402
from earthpv.labels import resolve_aoi  # noqa: E402

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
VIDA_CACHE = Path("data/predictions_pk16085/pakistan/buildings/pakistan_vida.parquet")
OUT_DIR = DATA_DIR / "glint" / "direct_detect"
MIN_AREA_M2, MAX_AREA_M2 = 80.0, 20_000.0
MIN_DISTANCE_M = 100.0  # matches export.py's new-lead convention

CITIES = [
    # Caps sized from the Lahore pilot's real runtime: 198 candidates took 2.5+ hours
    # under current (degraded) Planetary Computer conditions -- 600-1200/city would
    # have meant days of unattended runtime. Bumped max_workers below to claw some of
    # that back; still expect roughly a pilot-sized run per remaining city.
    dict(name="lahore", lat=31.5497, lon=74.3436, radius_km=10, cap=1200),
    dict(name="karachi", lat=24.8607, lon=67.0011, radius_km=12, cap=150),
    dict(name="faisalabad", lat=31.4180, lon=73.0790, radius_km=8, cap=150),
    dict(name="rawalpindi_islamabad", lat=33.6424, lon=73.0551, radius_km=10, cap=150),
    dict(name="multan", lat=30.1575, lon=71.5249, radius_km=8, cap=150),
    dict(name="gujranwala", lat=32.1877, lon=74.1945, radius_km=7, cap=150),
    dict(name="peshawar", lat=34.0151, lon=71.5249, radius_km=7, cap=150),
]


def bbox_for(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def stratified_sample(gdf: gpd.GeoDataFrame, cap: int, seed: int = 0) -> gpd.GeoDataFrame:
    """Take up to `cap` buildings spread across size terciles, not just the largest --
    the calibration-box finding was about SMALL arrays the model misses, so a
    large-only sample would just re-confirm what the model already sees fine."""
    if len(gdf) <= cap:
        return gdf
    terciles = gdf.area_m2.quantile([1 / 3, 2 / 3]).tolist()
    bins = pd.cut(gdf.area_m2, [-np.inf, terciles[0], terciles[1], np.inf], labels=["s", "m", "l"])
    per_bin = cap // 3
    parts = [
        grp.sample(n=min(len(grp), per_bin), random_state=seed)
        for _, grp in gdf.groupby(bins, observed=True)
    ]
    return pd.concat(parts).sample(frac=1, random_state=seed).reset_index(drop=True)


def select_candidates(
    city: dict, buildings: gpd.GeoDataFrame, mapped: gpd.GeoDataFrame | None,
) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = bbox_for(city["lat"], city["lon"], city["radius_km"])
    sub = buildings.cx[minx:maxx, miny:maxy]
    sub = sub[(sub.area_m2 >= MIN_AREA_M2) & (sub.area_m2 <= MAX_AREA_M2)].reset_index(drop=True)
    print(f"{city['name']}: {len(sub)} buildings in bbox after area filter")
    if mapped is not None and not mapped.empty:
        keep = new_lead_mask(sub, mapped, min_distance_m=MIN_DISTANCE_M)
        sub = sub[keep].reset_index(drop=True)
        print(f"{city['name']}: {len(sub)} remain after excluding already-OSM-mapped (>{MIN_DISTANCE_M:.0f}m)")
    sub = stratified_sample(sub, city["cap"])
    print(f"{city['name']}: {len(sub)} candidates selected for glint check")
    return sub


def run_city(city: dict, buildings: gpd.GeoDataFrame, mapped: gpd.GeoDataFrame | None) -> pd.DataFrame:
    cands = select_candidates(city, buildings, mapped)
    if cands.empty:
        return pd.DataFrame()
    targets = pd.DataFrame({
        "pid": cands["id"].to_numpy(),
        "geometry": cands.geometry.to_numpy(),
        "lon": cands.geometry.centroid.x.to_numpy(),
        "lat": cands.geometry.centroid.y.to_numpy(),
    })
    series_by_pid = glint.tile_scene_series_batch(
        targets, *DATE_RANGE, tile_deg=1.0, max_workers=20,
    )
    rows = []
    for pid, area in zip(cands["id"], cands.area_m2):
        df = series_by_pid.get(pid, pd.DataFrame())
        if df.empty:
            continue
        res = glint.spike_fit(df, self_referenced=True)
        rows.append(dict(
            pid=pid, city=city["name"], area_m2=float(area),
            n_scenes=res["n_scenes"], n_spikes=res["n_spikes"],
            n_consistent=res["n_consistent"], fit_tilt=res["fit_tilt"], fit_az=res["fit_az"],
        ))
    out = pd.DataFrame(rows)
    if not out.empty:
        out["validated"] = out.n_consistent >= 2
        out = out.merge(
            cands[["id", "geometry"]].rename(columns={"id": "pid"}), on="pid", how="left",
        )
    n_val = int(out.validated.sum()) if not out.empty else 0
    print(f"{city['name']}: {len(out)} scored, {n_val} validated (n_consistent>=2)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="Lahore only, capped at 200")
    ap.add_argument("--city", default=None, help="Run a single city by name")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cities = CITIES
    if args.pilot:
        cities = [dict(CITIES[0], cap=200)]
    elif args.city:
        cities = [c for c in CITIES if c["name"] == args.city]
        if not cities:
            raise SystemExit(f"Unknown city {args.city!r}; choices: {[c['name'] for c in CITIES]}")

    print("Loading VIDA buildings cache...")
    buildings = gpd.read_parquet(VIDA_CACHE)
    print(f"Loaded {len(buildings)} buildings")

    settings = Settings.load()
    _, cfg = resolve_aoi("pakistan", settings)
    mapped = _load_mapped_reference("pakistan", cfg, settings)
    print(f"Already-mapped reference: {0 if mapped is None else len(mapped)} features")

    for city in cities:
        marker = OUT_DIR / f"{city['name']}.csv"
        if marker.exists():
            print(f"{city['name']}: already done ({marker}), skipping")
            continue
        try:
            out = run_city(city, buildings, mapped)
        except Exception as e:  # noqa: BLE001 -- one bad city must not kill the run
            print(f"{city['name']}: FAILED ({e.__class__.__name__}: {e})")
            continue
        out.to_csv(marker, index=False)
        print(f"Wrote {marker}")

    all_parts = [pd.read_csv(p) for p in OUT_DIR.glob("*.csv")]
    if all_parts:
        combined = pd.concat(all_parts, ignore_index=True)
        n_val = int(combined.validated.sum())
        print(f"\n=== Combined so far: {len(combined)} scored, {n_val} validated across "
              f"{combined.city.nunique()} cities ===")


if __name__ == "__main__":
    main()
