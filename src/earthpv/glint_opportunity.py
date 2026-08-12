"""Opportunity-normalised glint evidence: how many chances did this target actually have?

`capacity_calibration` inverts the glint instrument to estimate what fraction of unmapped
candidates are real: a size bin's *sensitivity* (the rate at which glint validates
OSM-confirmed PV in that bin) divides the rate at which it validates unmapped candidates.
That sensitivity is estimated **per size bin, pooled across locations** -- and the number of
chances a target gets to glint is not constant across locations at all.

Two measured reasons it varies, both from 2026-08-11:

- **Scene count.** Whether a point is covered by one relative orbit or several changes how
  many Sentinel-2 looks it gets. Across the 23 calibration quadrats this ranges 156 to 530
  scenes in two years, and within the 500-target validation study `n_clear` ranges from
  about 114 to 222 across its interquartile range alone.
- **Pose compatibility.** Sentinel-2 views near-nadir, so the pose that reflects the sun
  into the sensor is a narrow locus, and how much of a plausible installed pose population
  falls on it varies 6.7% to 23.6% between quadrats (see
  `scripts/glint_observability_ceiling.py` and `docs/methods/glint.md`).

Multiply those and one target can have several times the glint opportunity of another in the
same size bin. Pooling them estimates a sensitivity that is right on average and wrong
everywhere, which biases the inverted precision whenever the unmapped candidate population
sits at a different opportunity than the OSM-confirmed study population did.

This module replaces the pooled constant with a one-parameter model that is opportunity
aware:

    expected opportunities  E_i = sum over clear scenes of P(pose glints | pose prior)
    glint count             k_i ~ Poisson(q_b * E_i)
    validated               P(k_i >= 2) = 1 - exp(-lam)(1 + lam),  lam = q_b * E_i

`q_b` is the per-opportunity glint probability for size bin `b` -- a property of the panels
and the sensor, not of where a target happens to sit -- so it transfers between locations in
a way a pooled sensitivity does not. Sensitivity for any target is then predicted from its
own `E_i`.

**Whether this is worth using is an empirical question, and `opportunity_response` is the
test**: if the validated rate does not actually rise with `E` within a size bin, the premise
is wrong and the pooled constant should be kept. Run that before wiring anything.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Installed-pose prior. It has to be ASSUMED: this project's pose survey was fitted from
# observed glints, so every pose in it satisfies the glint condition by construction and it
# cannot supply an uncensored distribution (measured 2026-08-11 -- its de-mirrored azimuths
# sit inside the observable band). Chosen as plausible installer practice at these latitudes:
# facing south, tilt near latitude. `expected_opportunities` takes it as an argument so a
# caller can test sensitivity to it, and `docs/methods/glint.md` reports that sensitivity.
DEFAULT_POSE_PRIOR = dict(tilt_mu=25.0, tilt_sd=8.0, az_mu=180.0, az_sd=25.0)
DEFAULT_TOL_DEG = 6.0   # the wider lobe: panel texturing spreads the specular return
N_POSE_SAMPLES = 2000
POSE_SEED = 11


def sample_poses(prior: dict | None = None, n: int = N_POSE_SAMPLES,
                 seed: int = POSE_SEED) -> tuple[np.ndarray, np.ndarray]:
    p = {**DEFAULT_POSE_PRIOR, **(prior or {})}
    rng = np.random.default_rng(seed)
    tilt = rng.normal(p["tilt_mu"], p["tilt_sd"], n).clip(0.0, 60.0)
    az = rng.normal(p["az_mu"], p["az_sd"], n) % 360.0
    return tilt, az


def expected_opportunities(geom: pd.DataFrame, tilt: np.ndarray, az: np.ndarray,
                           tol_deg: float = DEFAULT_TOL_DEG) -> float:
    """Expected number of scenes in `geom` on which a panel drawn from the pose prior glints.

    `geom` needs `sun_zen`, `sun_az`, `view_zen`, `view_az` -- one row per scene, as
    `glint._cached_tile_angles(...).at(lon, lat)` produces. Summing a per-scene probability
    rather than counting "pose-compatible scenes" keeps this a proper expectation: no single
    scene is compatible with the whole prior, and thresholding one would throw away the
    partial credit that makes the sum meaningful.
    """
    from earthpv.glint import misalignment_deg

    if geom.empty:
        return 0.0
    mis = misalignment_deg(
        geom.sun_zen.to_numpy()[None, :], geom.sun_az.to_numpy()[None, :],
        geom.view_zen.to_numpy()[None, :], geom.view_az.to_numpy()[None, :],
        tilt[:, None], az[:, None],
    )
    return float((mis <= tol_deg).mean(axis=0).sum())


def target_opportunities(
    targets: pd.DataFrame, start: datetime, end: datetime,
    pose_prior: dict | None = None, tol_deg: float = DEFAULT_TOL_DEG,
    max_cloud: int = 100, n_threads: int = 8, workers: int = 4,
) -> pd.DataFrame:
    """`(pid, n_scenes, expected_opportunities)` per target, from granule metadata only.

    Reads no pixels: the question is purely geometric, so a full `scene_series` pull would
    cost orders of magnitude more for the same answer. Targets need `pid`, `lon`, `lat`.

    Note the cloud caveat this deliberately does NOT handle: `max_cloud` filters by the
    whole-scene property, which 2026-08-11 measurements showed is nearly uninformative about
    whether a specific target was clear. A caller that has per-scene cloud evidence for its
    targets (the `scl_ring_cloud_frac` column `scene_series` now records) should scale `E`
    by its own clear fraction rather than trusting this filter.
    """
    from earthpv import glint

    tilt, az = sample_poses(pose_prior)
    rows: list[dict] = []

    def one(t) -> dict:
        d = 0.03
        try:
            items = glint._search_items_bbox(
                "planetary-computer", (t.lon - d, t.lat - d, t.lon + d, t.lat + d),
                start, end, max_cloud,
            )
        except Exception as e:  # noqa: BLE001 -- one failed search must not kill the sweep
            log.warning("search failed for %s: %s", t.pid, e)
            return dict(pid=t.pid, n_scenes=0, expected_opportunities=np.nan)
        angs: list[dict] = []

        def ang_of(item):
            try:
                a = glint._cached_tile_angles(item, "planetary-computer").at(t.lon, t.lat)
                return a
            except Exception:  # noqa: BLE001
                return None

        with ThreadPoolExecutor(n_threads) as ex:
            for f in as_completed([ex.submit(ang_of, it) for it in items]):
                a = f.result()
                if a:
                    angs.append(a)
        if not angs:
            return dict(pid=t.pid, n_scenes=0, expected_opportunities=np.nan)
        g = pd.DataFrame(angs)
        return dict(pid=t.pid, n_scenes=len(g),
                    expected_opportunities=expected_opportunities(g, tilt, az, tol_deg))

    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(one, t) for t in targets.itertuples()]
        for i, f in enumerate(as_completed(futs), 1):
            rows.append(f.result())
            if i % 25 == 0:
                log.info("opportunities: %d/%d targets", i, len(futs))
    return pd.DataFrame(rows)


def validated_probability(expected: np.ndarray, q: float, k_min: int = 2) -> np.ndarray:
    """P(at least `k_min` consistent glints) for Poisson(q * expected)."""
    lam = np.clip(np.asarray(expected, dtype=float) * q, 0.0, None)
    if k_min <= 0:
        return np.ones_like(lam)
    if k_min == 1:
        return 1.0 - np.exp(-lam)
    if k_min == 2:
        return 1.0 - np.exp(-lam) * (1.0 + lam)
    raise NotImplementedError(f"k_min={k_min} not supported")


def fit_glint_rate(expected: np.ndarray, validated: np.ndarray, k_min: int = 2,
                   grid: np.ndarray | None = None) -> dict:
    """Maximum-likelihood per-opportunity glint probability `q` for one size bin.

    One parameter, fitted on a grid rather than with an optimiser: the likelihood is smooth
    and bounded on (0, 1], a 2,000-point log grid resolves it far below the sampling noise of
    a few hundred targets, and it keeps `scipy` out of the dependency set (this project has
    kept it optional elsewhere for the same reason).
    """
    e = np.asarray(expected, dtype=float)
    y = np.asarray(validated).astype(bool)
    ok = np.isfinite(e) & (e >= 0)
    e, y = e[ok], y[ok]
    if len(e) == 0 or e.sum() <= 0:
        return dict(q=np.nan, n=int(len(e)), n_validated=int(y.sum()), loglik=np.nan)
    if grid is None:
        grid = np.logspace(-6, 0, 2000)
    ll = np.empty(len(grid))
    for i, q in enumerate(grid):
        pi = np.clip(validated_probability(e, q, k_min), 1e-12, 1 - 1e-12)
        ll[i] = float(np.sum(np.log(pi[y])) + np.sum(np.log1p(-pi[~y])))
    j = int(np.argmax(ll))
    q = float(grid[j])
    return dict(q=q, n=int(len(e)), n_validated=int(y.sum()), loglik=float(ll[j]),
                mean_expected=float(e.mean()),
                pooled_rate=float(y.mean()),
                modelled_mean_rate=float(validated_probability(e, q, k_min).mean()))


def opportunity_response(df: pd.DataFrame, bin_col: str = "bucket",
                         expected_col: str = "expected_opportunities",
                         validated_col: str = "validated", n_tertiles: int = 3) -> pd.DataFrame:
    """**The test of the premise**: within a size bin, does the validated rate rise with
    opportunity? Splits each bin into equal-count opportunity tertiles and reports the
    validated rate in each.

    If these are flat, opportunity carries no information and the pooled per-bin sensitivity
    `capacity_calibration` already uses is the right thing to keep. Run this before adopting
    anything else in this module.
    """
    out = []
    for b, g in df.groupby(bin_col):
        g = g[np.isfinite(g[expected_col])]
        if len(g) < 3 * n_tertiles:
            continue
        try:
            g = g.assign(_t=pd.qcut(g[expected_col], n_tertiles, labels=False, duplicates="drop"))
        except ValueError:
            continue
        for t, gg in g.groupby("_t"):
            out.append(dict(
                bucket=b, tertile=int(t), n=len(gg),
                expected_lo=round(float(gg[expected_col].min()), 2),
                expected_hi=round(float(gg[expected_col].max()), 2),
                expected_med=round(float(gg[expected_col].median()), 2),
                validated_rate=round(float(gg[validated_col].mean()), 4),
            ))
    return pd.DataFrame(out)


def sensitivity_table(df: pd.DataFrame, bin_col: str = "bucket", k_min: int = 2) -> pd.DataFrame:
    """Per-size-bin `q`, alongside the pooled rate it replaces, for comparison."""
    rows = []
    for b, g in df.groupby(bin_col):
        fit = fit_glint_rate(g.expected_opportunities.to_numpy(),
                             g.validated.to_numpy(), k_min=k_min)
        rows.append(dict(bucket=b, **fit))
    return pd.DataFrame(rows)


def predicted_sensitivity(expected: np.ndarray, bucket: np.ndarray,
                          table: pd.DataFrame, k_min: int = 2) -> np.ndarray:
    """Per-target sensitivity from its own opportunity count and its bin's fitted `q`.

    This is what replaces a single pooled number per bin in the glint inversion: a target
    that had few chances is not evidence of absence to the same degree as one that had many.
    """
    q_by_bin = dict(zip(table.bucket, table.q))
    q = np.array([q_by_bin.get(b, np.nan) for b in np.asarray(bucket)], dtype=float)
    e = np.asarray(expected, dtype=float)
    lam = e * q  # NaN q (an unfitted bin) propagates to NaN, which callers must handle
    return validated_probability(lam, 1.0, k_min)


def population_sensitivity(rate_table: pd.DataFrame, population: pd.DataFrame,
                           bin_col: str = "bucket",
                           expected_col: str = "expected_opportunities",
                           k_min: int = 2) -> dict:
    """Glint sensitivity for the population being *inverted*, not for the study population.

    This is the correction that motivates the whole module. `capacity_calibration`'s glint
    inversion estimates the real fraction of unmapped candidates in bin b as
    `(v_b - f) / (S_b - f)`, where `v_b` is the rate at which sampled unmapped candidates
    validate and `S_b` is sensitivity. It currently takes `S_b` straight from the
    500-target OSM-confirmed study -- but sensitivity is not a constant of the bin, it is a
    function of how many chances a target had, and the candidate sample sits at its own
    opportunity distribution which need not match the study's. Using the study's `S_b`
    against the candidates' `v_b` divides two rates measured under different exposure.

    Returns `{bin: {"sensitivity", "n", "mean_expected", "study_sensitivity_shift"}}`,
    where the sensitivity is the mean predicted `P(validate)` over this population's own
    `E`. Bins with no population rows are omitted, and the caller keeps the study constant
    for those.
    """
    q_by_bin = dict(zip(rate_table.bucket, rate_table.q))
    out: dict[str, dict] = {}
    for b, g in population.groupby(bin_col):
        q = q_by_bin.get(b)
        e = pd.to_numeric(g[expected_col], errors="coerce").to_numpy(dtype=float)
        e = e[np.isfinite(e)]
        if q is None or not np.isfinite(q) or len(e) == 0:
            continue
        s = float(validated_probability(e, q, k_min).mean())
        out[str(b)] = dict(sensitivity=round(s, 4), n=int(len(e)),
                           mean_expected=round(float(e.mean()), 3), q=round(float(q), 5))
    return out


def load_or_compute(path: Path, targets: pd.DataFrame, start: datetime, end: datetime,
                    **kw) -> pd.DataFrame:
    """Cached `target_opportunities`. The granule sweep is minutes to an hour of network for
    a few hundred targets, and nothing about it changes between runs."""
    path = Path(path)
    if path.exists():
        log.info("reusing %s", path)
        return pd.read_parquet(path)
    out = target_opportunities(targets, start, end, **kw)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path)
    log.info("wrote %s", path)
    return out
