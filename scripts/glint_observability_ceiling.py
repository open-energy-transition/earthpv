"""Step 1: can a predicted glint date ever help, and where? Geometry only, no pixel reads.

A glint needs the panel normal to bisect the sun and view vectors. Sentinel-2 views
near-nadir, so the pose that glints is roughly tilt ~ sun_zenith/2, azimuth ~ sun azimuth at
the ~10:30 overpass. Both vary with latitude and season, so each place has its own band of
*observable* poses, and a panel whose installed pose falls outside that band cannot glint
into Sentinel-2 at all, on any date, ever.

This script measures that band per calibration quadrat from REAL granule geometry (the
per-scene `MTD_TL.xml` sun/view angles, which is metadata only -- no COG reads, so this is
cheap), and answers three things:

1. What fraction of a plausible installed pose population could ever glint here (the
   ceiling on how much a glint-date feature could possibly contribute).
2. Which single date lights up the most panels (the "optimal date" the idea needs).
3. How sensitive 1 is to the assumed installed pose distribution.

**Why the pose distribution has to be assumed.** The project's own 192-installation pose
survey cannot supply it: those poses were *fitted from observed glints*, so every one of
them satisfies the glint condition by construction. Measured directly here -- the survey's
de-mirrored azimuths sit inside the observable band, which is what censoring predicts, not
what installer practice predicts. So the fraction below is reported across a grid of
assumed distributions and the spread between them IS the uncertainty.

Usage:
  .pixi/envs/default/bin/python scripts/glint_observability_ceiling.py
"""

from __future__ import annotations

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv import roofclf  # noqa: E402

log = logging.getLogger("glint_ceiling")

# Two years, matching the glint validation studies. One year sweeps the full seasonal solar
# zenith range, but a second year adds more of the OTHER axis that matters: a point covered
# by more than one relative orbit is seen from several view azimuths, and it is that
# diversity, not the season, that widens the observable pose band. Measured: restricting to
# one year and collapsing same-day orbits took the Lahore ceiling from 29% to 6.6%.
START = datetime(2024, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 1, tzinfo=timezone.utc)
TOL_DEG = 3.0            # the tolerance `fit_best_orientation` uses
TOL_MARGINAL_DEG = 6.0   # panel texturing/roughness widens the real lobe somewhat
MAX_CLOUD = 100          # geometry only: cloud is irrelevant to whether a pose CAN glint
N_POSE_SAMPLES = 3000

OUT_CSV = Path("results/glint_observability_by_quadrat.csv")
OUT_JSON = Path("results/glint_observability_summary.json")

# Assumed installed pose distributions. The middle row is the "plausible installer
# practice" baseline (tilt near latitude, facing due south); the others bracket it.
POSE_PRIORS = {
    "flat_roofs":        dict(tilt_mu=10, tilt_sd=6,  az_mu=180, az_sd=40),
    "shallow_south":     dict(tilt_mu=18, tilt_sd=7,  az_mu=180, az_sd=25),
    "textbook_south":    dict(tilt_mu=25, tilt_sd=8,  az_mu=180, az_sd=25),
    "steep_south":       dict(tilt_mu=30, tilt_sd=6,  az_mu=180, az_sd=20),
    "any_orientation":   dict(tilt_mu=20, tilt_sd=10, az_mu=180, az_sd=70),
}


def sample_poses(prior: dict, n: int = N_POSE_SAMPLES, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    tilt = rng.normal(prior["tilt_mu"], prior["tilt_sd"], n).clip(0, 60)
    az = rng.normal(prior["az_mu"], prior["az_sd"], n) % 360.0
    return tilt, az


def quadrat_points(labels_dir: Path = Path("data/labels")) -> pd.DataFrame:
    """(stem, label, lon, lat) for every discoverable quadrat, from its own boundary."""
    rows = []
    for stem in roofclf.discover_quadrats(labels_dir):
        b = roofclf.load_boundary(labels_dir / f"{stem}{roofclf._BOUNDARY_SUFFIX}")
        p = b.representative_point()
        rows.append(dict(stem=stem, label=roofclf.quadrat_label(stem), lon=p.x, lat=p.y))
    return pd.DataFrame(rows)


def fetch_geometry(lon: float, lat: float, n_threads: int = 8) -> pd.DataFrame:
    """Per-scene sun/view angles at a point, from granule metadata only.

    Deliberately does NOT read any band asset: the question here is purely geometric, so a
    full `scene_series` pull (which opens two or three COGs per scene) would cost orders of
    magnitude more for no extra information.
    """
    d = 0.05
    items = glint._search_items_bbox(
        "planetary-computer", (lon - d, lat - d, lon + d, lat + d), START, END, MAX_CLOUD
    )
    if not items:
        return pd.DataFrame()
    rows: list[dict] = []

    def one(item):
        try:
            ta = glint._cached_tile_angles(item, "planetary-computer")
            ang = ta.at(lon, lat)
            if ang is None:
                return None
            return dict(time=ta.sensing_time or item.datetime, **ang)
        except Exception as e:  # noqa: BLE001 -- one unreadable granule must not stop the sweep
            log.debug("angles failed for %s: %s", item.id, e)
            return None

    with ThreadPoolExecutor(n_threads) as ex:
        for f in as_completed([ex.submit(one, it) for it in items]):
            r = f.result()
            if r:
                rows.append(r)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Dedup to the MINUTE, not the day (glint.py's own convention). Two scenes on the same
    # date from different relative orbits view the point from different azimuths, so they
    # are distinct geometry and collapsing them shrinks the observable band artificially.
    df["_k"] = pd.to_datetime(df["time"]).dt.strftime("%Y%m%d%H%M")
    return df.drop_duplicates("_k").drop(columns="_k").sort_values("time").reset_index(drop=True)


def misalignment_matrix(geom: pd.DataFrame, tilt: np.ndarray, az: np.ndarray) -> np.ndarray:
    """(n_poses, n_scenes) misalignment in degrees, computed in one broadcast.

    `glint.misalignment_deg` builds ENU vectors stacking on the last axis, so feeding it
    scene angles shaped (1, n_scenes) against pose angles shaped (n_poses, 1) broadcasts to
    (n_poses, n_scenes, 3) internally and reduces to the matrix. Worth doing: the obvious
    nested Python loop is 3,000 poses x 5 priors x 23 quadrats x ~150 scenes of interpreted
    overhead, which dominated everything else in this script.
    """
    sz = geom.sun_zen.to_numpy()[None, :]
    sa = geom.sun_az.to_numpy()[None, :]
    vz = geom.view_zen.to_numpy()[None, :]
    va = geom.view_az.to_numpy()[None, :]
    return glint.misalignment_deg(sz, sa, vz, va, tilt[:, None], az[:, None])


def observability(geom: pd.DataFrame, tilt: np.ndarray, az: np.ndarray, tol: float) -> np.ndarray:
    """Boolean per sampled pose: does ANY scene in `geom` put it within `tol` of glinting."""
    return misalignment_matrix(geom, tilt, az).min(axis=1) <= tol


def per_scene_lit_fraction(geom: pd.DataFrame, tilt: np.ndarray, az: np.ndarray,
                           tol: float) -> np.ndarray:
    """Fraction of the sampled pose population that glints ON EACH scene -- the quantity the
    'optimal date' maximises. This is what decides whether a single date can brighten many
    panels at once (the signal-to-noise argument) rather than one panel occasionally."""
    return (misalignment_matrix(geom, tilt, az) <= tol).mean(axis=0)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    qs = quadrat_points()
    log.info("%d quadrats discovered", len(qs))

    baseline = POSE_PRIORS["textbook_south"]
    tilt0, az0 = sample_poses(baseline)

    rows, per_quadrat_scenes = [], {}
    for q in qs.itertuples():
        geom = fetch_geometry(q.lon, q.lat)
        if geom.empty:
            log.warning("%s: no granule geometry", q.label)
            rows.append(dict(quadrat=q.label, n_scenes=0))
            continue
        lit = per_scene_lit_fraction(geom, tilt0, az0, TOL_DEG)
        order = np.argsort(-lit)
        best = geom.iloc[order[0]]
        row = dict(
            quadrat=q.label, lon=round(q.lon, 4), lat=round(q.lat, 4), n_scenes=len(geom),
            sun_zen_min=round(float(geom.sun_zen.min()), 1),
            sun_zen_max=round(float(geom.sun_zen.max()), 1),
            sun_az_min=round(float(geom.sun_az.min()), 1),
            sun_az_max=round(float(geom.sun_az.max()), 1),
            view_zen_max=round(float(geom.view_zen.max()), 1),
            best_date=str(pd.to_datetime(best.time).date()),
            best_date_lit_frac=round(float(lit[order[0]]), 4),
            top3_dates=";".join(str(pd.to_datetime(geom.iloc[i].time).date()) for i in order[:3]),
            top3_lit_frac=";".join(f"{lit[i]:.3f}" for i in order[:3]),
        )
        for name, prior in POSE_PRIORS.items():
            t, a = sample_poses(prior)
            row[f"ever_{name}"] = round(float(observability(geom, t, a, TOL_DEG).mean()), 4)
        row[f"ever_baseline_tol{TOL_MARGINAL_DEG:.0f}"] = round(
            float(observability(geom, tilt0, az0, TOL_MARGINAL_DEG).mean()), 4
        )
        rows.append(row)
        per_quadrat_scenes[q.label] = pd.DataFrame(
            dict(time=geom.time.astype(str), lit_frac=lit,
                 req_tilt=glint.required_orientation(
                     geom.sun_zen.to_numpy(), geom.sun_az.to_numpy(),
                     geom.view_zen.to_numpy(), geom.view_az.to_numpy())[0],
                 req_az=glint.required_orientation(
                     geom.sun_zen.to_numpy(), geom.sun_az.to_numpy(),
                     geom.view_zen.to_numpy(), geom.view_az.to_numpy())[1])
        ).to_dict("list")
        log.info("%-26s scenes %3d  best %s lit %.1f%%  ever(textbook) %.1f%%",
                 q.label, len(geom), row["best_date"], 100 * row["best_date_lit_frac"],
                 100 * row["ever_textbook_south"])

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps({
        "window": [str(START.date()), str(END.date())],
        "tol_deg": TOL_DEG,
        "tol_marginal_deg": TOL_MARGINAL_DEG,
        "pose_priors": POSE_PRIORS,
        "n_pose_samples": N_POSE_SAMPLES,
        "note": ("Installed pose is ASSUMED, not measured: the project's pose survey is "
                 "censored by the glint condition it was fitted from, so the spread across "
                 "`pose_priors` is the real uncertainty on these fractions."),
        "per_quadrat_scenes": per_quadrat_scenes,
    }, indent=2))
    print("\n" + out.to_string(index=False))
    ok = out[out.n_scenes > 0]
    if len(ok):
        print(f"\nacross {len(ok)} quadrats, share of an assumed installed population that "
              f"could EVER glint (tol {TOL_DEG:.0f} deg):")
        for name in POSE_PRIORS:
            c = ok[f"ever_{name}"]
            print(f"  {name:16s} median {c.median():.1%}  range {c.min():.1%}-{c.max():.1%}")
        print(f"\nbest single date lights up (baseline prior): median "
              f"{ok.best_date_lit_frac.median():.1%}, range "
              f"{ok.best_date_lit_frac.min():.1%}-{ok.best_date_lit_frac.max():.1%}")
    print(f"\n-> {OUT_CSV}\n-> {OUT_JSON}")


if __name__ == "__main__":
    main()
