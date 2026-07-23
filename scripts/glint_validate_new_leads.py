"""Glint-validate the segmentation model's own new-leads pool, restricted to Lahore +
other major Pakistani cities -- the pivot from `glint_direct_detect.py` (which found
random VIDA buildings have a ~1% glint hit rate: 2/198 in the Lahore pilot, far too
sparse to reach 200 leads in tractable time). `candidates.parquet` has never been
glint-checked at all this session (no `glint_*` columns) -- this pool is already
vision-pre-filtered by the model, so the glint hit rate should be far higher than on
raw buildings, closer to the 500-target OSM-confirmed study's per-bucket rates
(pakistan_stats_by_size.csv: ~30-73% validated for >=1k m2).

Self-referenced criterion (matches [[earthpv-glint-direct-detection]]'s dense-urban
fix) -- these are all urban candidates, same failure mode as the calibration-box work.

Also writes a `<glint_sample>`-schema CSV (bin_label/n/n_validated) compatible with
`earthpv calibrate-candidates --glint-sample`, so this run can directly upgrade the
calibration table beyond "interim-mapped-only" -- the concrete answer to "how could
glint improve the density method."

Usage:
  .pixi/envs/default/bin/python scripts/glint_validate_new_leads.py
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.capacity_calibration import BIN_LABELS, bin_index  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
NEW_LEADS = Path("data/predictions_pk16085/pakistan/pakistan_pv_new_leads.geojson")
OUT_DIR = DATA_DIR / "glint" / "new_leads_validate"

CITIES = [
    dict(name="lahore", lat=31.5497, lon=74.3436, radius_km=20),
    dict(name="karachi", lat=24.8607, lon=67.0011, radius_km=22),
    dict(name="faisalabad", lat=31.4180, lon=73.0790, radius_km=15),
    dict(name="rawalpindi_islamabad", lat=33.6424, lon=73.0551, radius_km=18),
    dict(name="multan", lat=30.1575, lon=71.5249, radius_km=15),
    dict(name="gujranwala", lat=32.1877, lon=74.1945, radius_km=14),
    dict(name="peshawar", lat=34.0151, lon=71.5249, radius_km=14),
    # Second wave, added once the first 7 cities' ~11% hit rate showed the ~200-lead
    # target needed a bigger candidate pool -- secondary cities/towns, same rationale
    # (urban clusters where new_leads concentrate, good tile-batch amortization).
    dict(name="sialkot", lat=32.4945, lon=74.5229, radius_km=10),
    dict(name="hyderabad", lat=25.3960, lon=68.3578, radius_km=10),
    dict(name="sukkur", lat=27.7052, lon=68.8574, radius_km=10),
    dict(name="sargodha", lat=32.0836, lon=72.6711, radius_km=10),
    dict(name="bahawalpur", lat=29.3956, lon=71.6836, radius_km=10),
    dict(name="sheikhupura", lat=31.7167, lon=73.9850, radius_km=10),
    dict(name="jhang", lat=31.2679, lon=72.3181, radius_km=10),
    dict(name="rahim_yar_khan", lat=28.4212, lon=70.2989, radius_km=10),
    dict(name="sahiwal", lat=30.6682, lon=73.1114, radius_km=10),
    dict(name="kasur", lat=31.1156, lon=74.4502, radius_km=10),
    dict(name="okara", lat=30.8081, lon=73.4460, radius_km=10),
    dict(name="mardan", lat=34.1989, lon=72.0404, radius_km=10),
    dict(name="dera_ghazi_khan", lat=29.9903, lon=70.6339, radius_km=10),
    dict(name="nawabshah", lat=26.2442, lon=68.4100, radius_km=10),
    dict(name="mirpur_khas", lat=25.5269, lon=69.0116, radius_km=10),
]


def bbox_for(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def run_city(city: dict, leads: gpd.GeoDataFrame) -> pd.DataFrame:
    minx, miny, maxx, maxy = bbox_for(city["lat"], city["lon"], city["radius_km"])
    sub = leads.cx[minx:maxx, miny:maxy].reset_index(drop=True)
    print(f"{city['name']}: {len(sub)} new_leads in bbox")
    if sub.empty:
        return pd.DataFrame()
    targets = pd.DataFrame({
        "pid": sub["candidate_id"].to_numpy(),
        "geometry": sub.geometry.to_numpy(),
        "lon": sub.geometry.centroid.x.to_numpy(),
        "lat": sub.geometry.centroid.y.to_numpy(),
    })
    series_by_pid = glint.tile_scene_series_batch(
        targets, *DATE_RANGE, tile_deg=1.0, max_workers=20,
    )
    rows = []
    for pid, area, conf, rank in zip(sub["candidate_id"], sub.area_m2, sub.confidence,
                                      sub.rank_score if "rank_score" in sub else sub.confidence):
        df = series_by_pid.get(pid, pd.DataFrame())
        if df.empty:
            continue
        res = glint.spike_fit(df, self_referenced=True)
        rows.append(dict(
            pid=pid, city=city["name"], area_m2=float(area), confidence=float(conf),
            rank_score=float(rank), n_scenes=res["n_scenes"], n_spikes=res["n_spikes"],
            n_consistent=res["n_consistent"], fit_tilt=res["fit_tilt"], fit_az=res["fit_az"],
        ))
    out = pd.DataFrame(rows)
    if not out.empty:
        out["validated"] = out.n_consistent >= 2
        out = out.merge(
            sub[["candidate_id", "geometry"]].rename(columns={"candidate_id": "pid"}),
            on="pid", how="left",
        )
    n_val = int(out.validated.sum()) if not out.empty else 0
    print(f"{city['name']}: {len(out)} scored, {n_val} validated (n_consistent>=2)")
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading new_leads...")
    leads = gpd.read_file(NEW_LEADS)
    print(f"Loaded {len(leads)} new_leads")

    for city in CITIES:
        marker = OUT_DIR / f"{city['name']}.csv"
        if marker.exists():
            print(f"{city['name']}: already done ({marker}), skipping")
            continue
        try:
            out = run_city(city, leads)
        except Exception as e:  # noqa: BLE001 -- one bad city must not kill the run
            print(f"{city['name']}: FAILED ({e.__class__.__name__}: {e})")
            continue
        out.to_csv(marker, index=False)
        print(f"Wrote {marker}")

    parts = [pd.read_csv(p) for p in OUT_DIR.glob("*.csv") if p.stem != "combined"]
    if not parts:
        print("No results yet.")
        return
    combined = pd.concat(parts, ignore_index=True)
    n_val = int(combined.validated.sum())
    print(f"\n=== Combined: {len(combined)} scored, {n_val} validated across "
          f"{combined.city.nunique()} cities ===")
    combined.to_csv(OUT_DIR / "combined.csv", index=False)

    # glint_sample-schema CSV for `earthpv calibrate-candidates --glint-sample`
    combined["bucket"] = pd.Categorical.from_codes(
        bin_index(combined["area_m2"].to_numpy()), categories=list(BIN_LABELS)
    ).astype(str)
    per_bin = combined.groupby("bucket", sort=False).agg(
        n=("validated", "size"), n_validated=("validated", "sum")
    ).reindex(list(BIN_LABELS)).dropna().astype(int).reset_index(names="bin_label")
    sample_out = OUT_DIR / "pakistan_new_leads_glint_sample.csv"
    per_bin.to_csv(sample_out, index=False)
    print(per_bin.to_string(index=False))
    print(f"\nWrote {sample_out} -- feed it to:\n"
          f"  earthpv calibrate-candidates --aoi pakistan --pred-dir data/predictions_pk16085 "
          f"--glint-sample {sample_out}")


if __name__ == "__main__":
    main()
