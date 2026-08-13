"""Re-cut the existing country2000 glint/pose study by latitude band and province, to
check whether detection rate, validation rate, fitted tilt, or fitted azimuth vary
regionally -- rather than running a new national glint pass, which would cost ~1
min/target at true national scale (tens of millions of buildings) and is not something
this project has ever done or currently plans to do.

Motivation: Sentinel-2 crosses a given latitude at a fixed local time, so the specular-
reflection condition `pose.py` fits (see its module docstring) is latitude-dependent in
principle, and Pakistan spans ~13 degrees of latitude (24-37N). The existing 2000-target
study (`data/glint/country2000_summary.csv`) was stratified by installation SIZE, not by
region (`docs/methods/glint.md`), so this is the first time it has been split
geographically. This is a free re-analysis of data already on disk -- no new Overpass
pulls, no new Planetary Computer reads, no new GPU/CPU-heavy processing.

Two prior attempts at a REGIONAL DENSITY signal from glint both went negative
(`glint_density_*.py`, `glint_cell_density_*.py`, `docs/methods/glint.md`). This is a
different question -- not "does glint density track PV density regionally" but "does the
fitted POSE (tilt/azimuth) or the raw detection/validation RATE shift with latitude" --
so a negative history on the first question does not predict the answer to this one.

Usage:
    .pixi/envs/default/bin/python scripts/glint_pose_by_region.py
    .pixi/envs/default/bin/python scripts/glint_pose_by_region.py \
        --summary data/glint/pakistan_combined_summary.csv \
        --targets data/glint/pakistan_combined_targets.parquet \
        --out results/glint_pose_by_region_combined.csv \
        --points-out data/glint/pakistan_combined_points_enriched.parquet

Writes the region/latitude-band summary CSV (one row per latitude band + one per
province) and prints the same table. `--points-out`, if given, also writes the full
per-target table enriched with `lat_band`/`name` (province) -- the shape
`glint_pose_atlas.py` reads to plot individual points, not just aggregates.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

REGIONS = Path("data/labels/pakistan_regions.parquet")

# Coarse, round-number bins rather than data-driven quantiles -- the point is to see
# whether a real physical quantity (fitted tilt/azimuth) trends with a real physical
# axis (latitude), which a human should be able to sanity-check against a map without
# first decoding an arbitrary binning scheme.
LAT_EDGES = [24, 26, 28, 30, 32, 34, 37]
# Below this many FITTED (n_consistent >= 2) targets in a bin, tilt/azimuth medians are
# noise, not signal -- flagged explicitly rather than silently printed alongside
# well-sampled bins at the same precision.
MIN_N_FOR_POSE_STATS = 20


def _lat_bands(lat: pd.Series) -> pd.Series:
    labels = [f"{lo}-{hi}N" for lo, hi in zip(LAT_EDGES[:-1], LAT_EDGES[1:])]
    return pd.cut(lat, bins=LAT_EDGES, labels=labels)


def _rate_row(name: str, sub: pd.DataFrame) -> dict:
    n = len(sub)
    fit = sub[sub["n_consistent"] >= 2]
    n_fit = len(fit)
    row = {
        "group": name,
        "n_targets": n,
        "n_detected": int(sub["n_spikes"].ge(1).sum()),
        "pct_detected": round(100 * sub["n_spikes"].ge(1).mean(), 1) if n else float("nan"),
        "n_validated": n_fit,
        "pct_validated": round(100 * n_fit / n, 1) if n else float("nan"),
        "median_tilt_deg": round(float(fit["fit_tilt"].median()), 1) if n_fit >= MIN_N_FOR_POSE_STATS else float("nan"),
        "az_min_deg": round(float(fit["fit_az"].min()), 1) if n_fit >= MIN_N_FOR_POSE_STATS else float("nan"),
        "az_max_deg": round(float(fit["fit_az"].max()), 1) if n_fit >= MIN_N_FOR_POSE_STATS else float("nan"),
        "pose_stats_reliable": n_fit >= MIN_N_FOR_POSE_STATS,
    }
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, default=Path("data/glint/country2000_summary.csv"))
    ap.add_argument("--targets", type=Path, default=Path("data/glint/country2000_targets.parquet"))
    ap.add_argument("--out", type=Path, default=Path("results/glint_pose_by_region.csv"))
    ap.add_argument("--points-out", type=Path, default=None,
                     help="also write the full per-target table enriched with lat_band/province")
    args = ap.parse_args()

    summ = pd.read_csv(args.summary)
    tgt = gpd.read_parquet(args.targets)[["pid", "lon", "lat"]]
    df = summ.merge(tgt, on="pid", how="left")
    missing = df["lat"].isna().sum()
    if missing:
        raise RuntimeError(f"{missing} targets have no matched geometry -- pid mismatch, fix before trusting output")

    regions = gpd.read_parquet(REGIONS).to_crs(4326)
    pts = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=4326)
    joined = gpd.sjoin(pts, regions[["name", "geometry"]], predicate="within", how="left")
    if joined["name"].isna().any():
        n_out = int(joined["name"].isna().sum())
        print(f"NOTE: {n_out} targets fell outside every region polygon (coastline/border rounding) -- excluded from the province cut, kept in the latitude cut")

    joined["lat_band"] = _lat_bands(joined["lat"])

    rows = [_rate_row(f"lat {band}", sub) for band, sub in joined.groupby("lat_band", observed=True)]
    rows += [_rate_row(f"province {prov}", sub) for prov, sub in joined.dropna(subset=["name"]).groupby("name", observed=True)]
    out = pd.DataFrame(rows)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(out.to_string(index=False))
    n_thin = int((~out["pose_stats_reliable"]).sum())
    print(f"\n{n_thin}/{len(out)} groups have fewer than {MIN_N_FOR_POSE_STATS} fitted targets -- "
          f"tilt/azimuth left blank for those rather than reported on a handful of points.")
    print(f"-> {args.out}")

    if args.points_out:
        args.points_out.parent.mkdir(parents=True, exist_ok=True)
        joined.drop(columns=["index_right"], errors="ignore").to_parquet(args.points_out)
        print(f"-> {args.points_out} ({len(joined)} points)")


if __name__ == "__main__":
    main()
