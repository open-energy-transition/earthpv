"""Does the empirically-fitted glint geometry actually agree with an independent
Skyfield computation of the sun/panel/Sentinel-2 geometry?

`glint.py`'s spike fit (`fit_best_orientation`) works entirely off angles baked into
each scene's own MTD_TL.xml granule metadata (ESA's ground-truth sun/view angles for
that exact acquisition) -- it never calls Skyfield. Skyfield only appears in the
*forward-looking* calendar (`predict_overpasses`/`glint_windows`), which needs a
TLE-propagated satellite position and is explicitly documented as accurate for sun
geometry but drifting in *timing* far from today (TLEs are ~weeks-valid).

This checks, with real pulled data, whether those two independent geometric
computations -- ESA's per-scene metadata vs. Skyfield's own ephemeris/TLE math --
actually agree, at three levels:

  A. Sun position only (no satellite/TLE involved): Skyfield's DE421-ephemeris sun
     (zenith, azimuth) at each real scene's exact time/location vs. that scene's own
     MTD-derived sun_zen/sun_az. Pure astronomy vs. pure astronomy -- should be near-
     exact; any large disagreement would mean a bug (wrong frame, wrong time, wrong
     coordinates) in one of the two computations.
  B. Required panel orientation with the sun swapped for Skyfield's: recompute each
     spike's required (tilt, az) using (Skyfield sun, real MTD view) instead of (real
     MTD sun, real MTD view), and see whether the fitted orientation / consistency
     count survives the swap -- i.e. would the spike fit still validate the same
     installation if it trusted Skyfield's sun instead of the metadata's?
  C. Full TLE-propagated forward prediction: for a handful of validated targets, use
     *today's* TLEs to predict S2 overpasses across the historical 2-year pull window
     and check (i) how close the predicted overpass dates land to real acquisition
     dates in the archive (quantifies the documented TLE-drift-over-time caveat) and
     (ii) whether the required orientation at the nearest predicted overpass still
     matches the real metadata-derived one despite that drift.

Usage:
  .pixi/envs/default/bin/python scripts/glint_skyfield_check.py sun-check
  .pixi/envs/default/bin/python scripts/glint_skyfield_check.py orientation-check
  .pixi/envs/default/bin/python scripts/glint_skyfield_check.py overpass-check
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

app = typer.Typer(pretty_exceptions_show_locals=False)

SERIES_DIR = DATA_DIR / "glint" / "pakistan"
TARGETS_FILE = DATA_DIR / "glint" / "pakistan_targets.parquet"
SUMMARY_FILE = DATA_DIR / "glint" / "pakistan_summary.csv"


def _load_sample(n_targets: int, seed: int = 0) -> list[tuple[str, float, float, pd.DataFrame]]:
    tgts = gpd.read_parquet(TARGETS_FILE)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(tgts), min(n_targets, len(tgts)), replace=False)
    out = []
    for i in idx:
        row = tgts.iloc[i]
        p = SERIES_DIR / f"{row.pid}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty:
            continue
        out.append((row.pid, row.geometry.centroid.y, row.geometry.centroid.x, d))
    return out


@app.command("sun-check")
def sun_check(n_targets: int = 80):
    """Test A: Skyfield ephemeris sun position vs. each scene's own MTD_TL.xml sun
    angles, across every pulled scene of a random target sample (no TLE involved)."""
    sample = _load_sample(n_targets)
    rows = []
    for pid, lat, lon, d in sample:
        for r in d.itertuples():
            sz_sf, sa_sf = glint.sun_position(lat, lon, r.time)
            rows.append(dict(pid=pid, dz=sz_sf - r.sun_zen,
                             da=((sa_sf - r.sun_az + 180) % 360) - 180))
    df = pd.DataFrame(rows)
    print(f"\n=== Test A: Skyfield sun ephemeris vs. MTD_TL.xml sun angles "
          f"({len(sample)} targets, {len(df)} scenes) ===")
    print(f"zenith  delta: median={df.dz.median():+.4f} deg  "
          f"p95={df.dz.abs().quantile(.95):.4f}  max_abs={df.dz.abs().max():.4f}")
    print(f"azimuth delta: median={df.da.median():+.4f} deg  "
          f"p95={df.da.abs().quantile(.95):.4f}  max_abs={df.da.abs().max():.4f}")


@app.command("orientation-check")
def orientation_check(n_targets: int = 150, tol_deg: float = 3.0):
    """Test B: does substituting Skyfield's sun for the MTD one change the fitted
    panel orientation / consistency count that validates an installation?"""
    sample = _load_sample(n_targets)
    rows = []
    for pid, lat, lon, d in sample:
        ann = glint.annotate_spikes(d)
        if ann.empty or ann.spike.sum() < 2:
            continue
        sf_sun = [glint.sun_position(lat, lon, t) for t in ann.time]
        sf_sz, sf_sa = zip(*sf_sun) if sf_sun else ([], [])
        ann_sf = ann.copy()
        ann_sf["glint_tilt"], ann_sf["glint_az"] = glint.required_orientation(
            np.array(sf_sz), np.array(sf_sa), ann.view_zen.to_numpy(), ann.view_az.to_numpy()
        )
        # fit_best_orientation needs sun_zen/sun_az/view_zen/view_az columns for its
        # internal misalignment_deg re-check -- swap in the Skyfield sun there too.
        ann_sf["sun_zen"], ann_sf["sun_az"] = sf_sz, sf_sa

        fit_mtd = glint.fit_best_orientation(ann, tol_deg)
        fit_sf = glint.fit_best_orientation(ann_sf, tol_deg)
        if fit_mtd is None or fit_sf is None:
            continue
        d_tilt = fit_sf[0] - fit_mtd[0]
        d_az = ((fit_sf[1] - fit_mtd[1] + 180) % 360) - 180
        rows.append(dict(pid=pid, n_mtd=fit_mtd[2], n_sf=fit_sf[2],
                         tilt_mtd=fit_mtd[0], tilt_sf=fit_sf[0], d_tilt=d_tilt,
                         az_mtd=fit_mtd[1], az_sf=fit_sf[1], d_az=d_az))
    df = pd.DataFrame(rows)
    print(f"\n=== Test B: fitted orientation, MTD sun vs. Skyfield-substituted sun "
          f"({len(df)} targets with >=2 spikes) ===")
    if df.empty:
        print("no targets with enough spikes in this sample")
        return
    same_n = int((df.n_sf == df.n_mtd).sum())
    print(f"n_consistent unchanged: {same_n}/{len(df)} ({100*same_n/len(df):.0f}%)")
    print(f"n_consistent worse under Skyfield sun: {int((df.n_sf < df.n_mtd).sum())}/{len(df)}")
    print(f"tilt delta:    median={df.d_tilt.median():+.3f} deg  "
          f"p95_abs={df.d_tilt.abs().quantile(.95):.3f}  max_abs={df.d_tilt.abs().max():.3f}")
    print(f"azimuth delta: median={df.d_az.median():+.3f} deg  "
          f"p95_abs={df.d_az.abs().quantile(.95):.3f}  max_abs={df.d_az.abs().max():.3f}")
    df.to_csv(DATA_DIR / "glint" / "skyfield_orientation_check.csv", index=False)


@app.command("overpass-check")
def overpass_check(n_targets: int = 6, tol_deg: float = 3.0):
    """Test C: current-TLE Skyfield overpass prediction vs. real historical
    acquisitions, for a handful of well-validated targets."""
    summ = pd.read_csv(SUMMARY_FILE)
    validated = summ[summ.n_consistent >= 2].sort_values("n_consistent", ascending=False)
    tgts = gpd.read_parquet(TARGETS_FILE).set_index("pid")
    picks = validated.head(n_targets)

    print(f"\n=== Test C: TLE-propagated Skyfield overpass prediction vs. real archive "
          f"({len(picks)} validated targets) ===")
    for r in picks.itertuples():
        pid = r.pid
        geom = tgts.loc[pid].geometry
        lat, lon = geom.centroid.y, geom.centroid.x
        d = pd.read_parquet(SERIES_DIR / f"{pid}.parquet")
        ann = glint.annotate_spikes(d)
        fit = glint.fit_best_orientation(ann, tol_deg)
        if fit is None:
            continue
        tilt, az, n_consistent = fit
        start, end = d.time.min(), d.time.max()
        passes = glint.predict_overpasses(lat, lon, start.to_pydatetime(), end.to_pydatetime())
        if not passes:
            print(f"{pid}: no predicted overpasses (TLE fetch issue?)")
            continue
        real_times = pd.to_datetime(d.time).sort_values().reset_index(drop=True)
        pass_times = pd.Series([pd.Timestamp(p.time) for p in passes])
        gaps = np.array([
            (real_times - pt).abs().min().total_seconds() / 86400 for pt in pass_times
        ])
        n_glint_pred = sum(1 for pss in passes if pss.misalignment(tilt, az) <= tol_deg)

        # The direct question: for each REAL spike date (empirically detected glint),
        # does the TLE-predicted overpass nearest that date -- using the fit orientation
        # -- land within tolerance? This is what a purely-forward Skyfield/TLE calendar
        # would have told you, with no metadata at all.
        spike_times = pd.to_datetime(ann.loc[ann.spike, "time"])
        hits = 0
        for st in spike_times:
            j = (pass_times - st).abs().idxmin()
            gap = abs((pass_times.iloc[j] - st).total_seconds()) / 86400
            mis = passes[j].misalignment(tilt, az)
            if gap <= 2 and mis <= tol_deg:
                hits += 1
        print(f"{pid} (fit tilt={tilt:.1f} az={az:.1f}, n_consistent={n_consistent}): "
              f"{len(passes)} TLE-predicted overpasses over {(end-start).days}d, "
              f"median date-gap to nearest real scene={np.median(gaps):.1f}d, "
              f"predicted glint windows (all overpasses)={n_glint_pred}, "
              f"real spike dates recovered by nearest TLE overpass={hits}/{len(spike_times)}")


if __name__ == "__main__":
    app()
