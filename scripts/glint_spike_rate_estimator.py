"""Glint spike-rate as a statistical PV-adoption estimator for the sub-pixel class.

Segmentation-based density collapses below ~500 m2 (6-16% detection,
results/glint_validation_pakistan/REPORT.md), which is where most of Pakistan's
distributed PV lives. Instead of trying to *find every panel* down there, this
estimates *what fraction of buildings have PV*, using glint as a sampling
instrument (docs/issues/glint-spike-rate-density-estimator.md):

  1. `sample`  -- draw a size-stratified random sample of VIDA building footprints
                  in a bbox, writing a targets parquet compatible with the existing
                  `glint_density_pull.py` (which does the ~2y scene-series pull,
                  resumable, unchanged).
  2. (pull)    -- .pixi/envs/default/bin/python scripts/glint_density_pull.py <region>
  3. `analyze` -- per size bucket: observed spike rate r with a Wilson CI, inverted
                  through the measured detection curve d (pct_detected per bucket,
                  pakistan_stats_by_size.csv) and a false-spike rate f (from control
                  buildings): adoption a = (r - f) / (d - f), clipped to [0, 1].
                  Combined estimate weights buckets by their share of the *building
                  population* in the sampled bbox (recorded at sample time), not the
                  stratified sample's equal shares.

Honest limitations (all documented in the issue; v1 accepts them):
- d was measured on *installation* area buckets, applied here to *roof* area
  buckets. Panels are smaller than their roof, so true per-roof detectability is
  lower than d -> the adoption estimate is a LOWER bound, tightest for small roofs
  where panel ~ roof. Quadrat data (docs/calibration-mapping-protocol.md) should
  eventually replace this curve with a roof-size-conditioned one.
- d's own sampling error (~80 targets/bucket) is not yet propagated; the reported
  CI reflects the spike-rate sample only.
- f defaults to the corroboration experiment's control buildings; controls were
  50-5000 m2, so <100 m2 and >5k m2 buckets borrow that rate.

Usage:
  .pixi/envs/default/bin/python scripts/glint_spike_rate_estimator.py sample \
      lahore_rate --bbox 74.05,31.30,74.55,31.65 --iso3 PAK --n-per-bucket 120
  .pixi/envs/default/bin/python scripts/glint_density_pull.py lahore_rate
  .pixi/envs/default/bin/python scripts/glint_spike_rate_estimator.py analyze lahore_rate
"""

from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("glint_spike_rate")
app = typer.Typer(pretty_exceptions_show_locals=False)

GLINT_DIR = DATA_DIR / "glint"
CURVE_CSV = Path("results/glint_validation_pakistan/pakistan_stats_by_size.csv")
BUCKET_EDGES = [0, 100, 500, 1000, 5000, 50000, np.inf]
BUCKET_LABELS = ["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"]
SEED = 42
Z = 1.96  # 95% Wilson interval


def _bucket(areas: pd.Series) -> pd.Series:
    return pd.cut(areas, bins=BUCKET_EDGES, labels=BUCKET_LABELS, right=False)


def _wilson(k: int, n: int, z: float = Z) -> tuple[float, float, float]:
    """(point, lo, hi) Wilson score interval for a binomial proportion."""
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def _invert(r: float, d: float, f: float) -> float:
    """Adoption rate from observed spike rate r, detection prob d, false-spike prob f."""
    if not np.isfinite(r) or d <= f + 1e-9:
        return float("nan")
    return float(np.clip((r - f) / (d - f), 0.0, 1.0))


@app.command()
def sample(
    region: str = typer.Argument(..., help="New region name, e.g. lahore_rate (must not collide with an existing targets file)"),
    bbox: str = typer.Option(..., help="lon1,lat1,lon2,lat2"),
    iso3: str = typer.Option("PAK"),
    n_per_bucket: int = typer.Option(120),
    min_confidence: float = typer.Option(0.0, help="VIDA bf_confidence floor (0 = keep all)"),
    seed: int = typer.Option(SEED),
):
    """Draw a size-stratified random building sample; write <region>_density_targets.parquet
    (kind='sample') consumable by glint_density_pull.py, plus a meta json with the bucket
    population counts needed to weight the combined estimate at analyze time."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from earthpv.buildings import fetch_vida_buildings

    targets_file = GLINT_DIR / f"{region}_density_targets.parquet"
    if targets_file.exists():
        raise typer.BadParameter(
            f"{targets_file} already exists -- pick a fresh region name (refusing to "
            "overwrite; the corroboration experiment shares this naming scheme)."
        )
    bb = tuple(float(x) for x in bbox.split(","))
    rng = np.random.default_rng(seed)

    log.info("Fetching VIDA buildings for %s in %s ...", iso3, bb)
    bldgs = fetch_vida_buildings(bb, iso3)
    if min_confidence > 0 and "bf_confidence" in bldgs.columns:
        bldgs = bldgs[bldgs.bf_confidence >= min_confidence]
    bldgs = bldgs[bldgs.area_m2 > 0].reset_index(drop=True)
    bldgs["bucket"] = _bucket(bldgs.area_m2)
    pop_counts = bldgs.bucket.value_counts().reindex(BUCKET_LABELS).fillna(0).astype(int)
    log.info("%d buildings in bbox; bucket population: %s", len(bldgs), pop_counts.to_dict())

    parts = []
    for b in BUCKET_LABELS:
        pool = bldgs[bldgs.bucket == b]
        if pool.empty:
            continue
        take = min(n_per_bucket, len(pool))
        parts.append(pool.iloc[rng.choice(len(pool), take, replace=False)])
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    out["kind"] = "sample"
    out["pid"] = [f"{region}_{i:04d}" for i in range(len(out))]
    out = out[["pid", "kind", "area_m2", "bucket", "geometry"]]
    out["bucket"] = out.bucket.astype(str)

    GLINT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(targets_file)
    meta = dict(region=region, bbox=bb, iso3=iso3, seed=seed, n_per_bucket=n_per_bucket,
                min_confidence=min_confidence, n_sampled=len(out),
                bucket_population=pop_counts.to_dict())
    (GLINT_DIR / f"{region}_density_targets_meta.json").write_text(json.dumps(meta, indent=2))
    log.info("Wrote %d sampled targets -> %s (+ meta json). Next: "
             "scripts/glint_density_pull.py %s", len(out), targets_file, region)


@app.command()
def analyze(
    region: str = typer.Argument(...),
    curve_csv: Path = typer.Option(CURVE_CSV, help="Measured detection curve by size bucket"),
    control_summary: Path = typer.Option(
        None, help="A *_density_summary.csv with kind=control rows for the false-spike "
                   "rate; default: lahore then germany, whichever exists"),
    criterion: str = typer.Option("detected", help="detected (n_spikes>=1) | validated (n_consistent>=2)"),
    tol_deg: float = typer.Option(3.0),
):
    """Invert per-bucket observed spike rates into PV adoption-rate estimates with CIs."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from glint_validation import analyze_point

    tgts = gpd.read_parquet(GLINT_DIR / f"{region}_density_targets.parquet")
    series_dir = GLINT_DIR / f"{region}_density"
    meta_p = GLINT_DIR / f"{region}_density_targets_meta.json"
    pop = json.loads(meta_p.read_text())["bucket_population"] if meta_p.exists() else None

    # detection curve
    curve = pd.read_csv(curve_csv).set_index("bucket")
    d_col = {"detected": "pct_detected", "validated": "pct_validated"}[criterion]

    # false-spike rate from control buildings of the corroboration experiment
    if control_summary is None:
        for cand in ("lahore_density_summary.csv", "germany_density_summary.csv"):
            if (GLINT_DIR / cand).exists():
                control_summary = GLINT_DIR / cand
                break
    if control_summary is None:
        raise typer.BadParameter("No control summary found; pass --control-summary")
    ctrl = pd.read_csv(control_summary)
    ctrl = ctrl[ctrl.kind == "control"]
    f_rate = float(ctrl[criterion].mean())
    log.info("false-%s rate from %d controls (%s): %.3f",
             criterion, len(ctrl), control_summary.name, f_rate)

    rows = []
    for r in tgts.itertuples():
        p = series_dir / f"{r.pid}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty:
            res = dict(n_scenes=0, n_spikes=0, n_consistent=0)
        else:
            res, _ = analyze_point(d, tol_deg)
        rows.append(dict(pid=r.pid, area_m2=r.area_m2, bucket=str(r.bucket),
                         n_scenes=res["n_scenes"], n_spikes=res["n_spikes"],
                         n_consistent=res["n_consistent"]))
    s = pd.DataFrame(rows)
    if s.empty:
        log.info("No pulled series found under %s -- run glint_density_pull.py %s first",
                 series_dir, region)
        raise typer.Exit(1)
    s["hit"] = (s.n_spikes >= 1) if criterion == "detected" else (s.n_consistent >= 2)

    out_rows = []
    for b in BUCKET_LABELS:
        grp = s[s.bucket == b]
        if grp.empty:
            continue
        k, n = int(grp.hit.sum()), len(grp)
        r_pt, r_lo, r_hi = _wilson(k, n)
        d_b = float(curve.loc[b, d_col]) / 100.0 if b in curve.index else float("nan")
        a_pt = _invert(r_pt, d_b, f_rate)
        a_lo = _invert(r_lo, d_b, f_rate)
        a_hi = _invert(r_hi, d_b, f_rate)
        out_rows.append(dict(bucket=b, n=n, k_hits=k,
                             spike_rate=round(r_pt, 4), rate_lo=round(r_lo, 4),
                             rate_hi=round(r_hi, 4), detect_prob=round(d_b, 4),
                             false_rate=round(f_rate, 4),
                             adoption=round(a_pt, 4) if np.isfinite(a_pt) else np.nan,
                             adoption_lo=round(a_lo, 4) if np.isfinite(a_lo) else np.nan,
                             adoption_hi=round(a_hi, 4) if np.isfinite(a_hi) else np.nan,
                             population=int(pop.get(b, 0)) if pop else np.nan))
    res = pd.DataFrame(out_rows)

    if pop:
        ok = res.dropna(subset=["adoption"])
        w = ok.population / max(ok.population.sum(), 1)
        combined = float((ok.adoption * w).sum())
        combined_lo = float((ok.adoption_lo * w).sum())
        combined_hi = float((ok.adoption_hi * w).sum())
    else:
        combined = combined_lo = combined_hi = float("nan")

    out_csv = GLINT_DIR / f"{region}_spike_rate_estimate.csv"
    res.to_csv(out_csv, index=False)
    print(f"\n=== {region}: glint spike-rate adoption estimate (criterion={criterion}) ===")
    print(res.to_string(index=False))
    if np.isfinite(combined):
        print(f"\nPopulation-weighted adoption: {100*combined:.2f}% "
              f"[{100*combined_lo:.2f}, {100*combined_hi:.2f}] "
              f"(weights = bucket building counts in sampled bbox)")
    print(f"-> {out_csv}")
    print("\nCaveats: adoption is a LOWER bound (installation-size curve applied to roof "
          "sizes); detection-curve sampling error not yet propagated; f borrowed from "
          "50-5000 m2 controls for the extreme buckets. See module docstring.")


if __name__ == "__main__":
    app()
