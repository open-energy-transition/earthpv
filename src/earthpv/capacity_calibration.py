"""Candidate-precision calibration for the PV capacity atlas.

The pipeline serves two products from one recall-first model. The *leads* product
(postprocess -> export -> MapRoulette) tolerates false positives because humans
validate every candidate. The *capacity atlas* (density stage) has no human in the
loop, so raw candidate area systematically overstates MWp. This module estimates
P(real PV | model candidate) per area bin — `p_real` — which density uses to weight
candidate area into the calibrated `est_mwp_cal` estimator. The leads product never
consumes this table, and this module never consumes `rank_score`: that is the
separation between the two products.

`p_real` per bin combines independent evidence sources, in order of directness:

- **mapped fraction** — candidates within `min_distance_m` (default 100 m, matching
  the new-leads export filter) of an already-mapped OSM solar feature are taken as
  real. Computed offline from data that always exists.
- **manual review of the unmapped remainder** — a human verdict (high-res imagery)
  on a stratified per-bin sample of unmapped candidates measures P(real | unmapped)
  directly. This is the only instrument that works below ~500 m2, where glint has no
  discrimination; `earthpv calibrate-sample` emits the review file.
- **glint inversion on the unmapped remainder** — the glint instrument validates a
  true array in bin b with probability S_b (sensitivity, measured on 500
  OSM-confirmed Pakistan installations: results/glint_validation_pakistan/) and a
  no-PV building with probability f = 6/69 (Lahore controls). If a stratified
  sample of *unmapped* candidates in bin b glint-validates at rate v_b, the real
  fraction among them is

      p_u(b) = clip((v_b - f) / (S_b - f), 0, 1)

  This is only measurable where S_b - f is comfortably positive (>= ~500 m2) and
  the sample is big enough. `scripts/glint_candidate_precision.py` produces it.

      p_real(b) = mapped_frac(b) + (1 - mapped_frac(b)) * p_u(b)

Bins where p_u is unmeasurable fall back to the nearest measurable bin's p_u
(flagged `extrapolated`); with no sample at all, p_u = 0 everywhere and the table is
an honest lower bound (status `interim-mapped-only`).

**Model recall per bin** (v2): the same mapped OSM reference, in the reverse
direction — the fraction of independently-mapped installations of bin b that the
model matched with any candidate. It feeds density's recall-corrected
(Horvitz–Thompson) estimator: each surviving candidate stands in for 1/recall(b)
real installations of its size class, so `est_mwp_rc = sum(area * p_real / recall)`
estimates the *whole* population of that size class, not just the detected part.
The reference must predate the pipeline's own OSM contributions (else recall is
self-confirmed upward) and be restricted to imaged cells (else deflated by
never-imaged installations); the CLI handles both.

**Uncertainty** (v2): every rate in the table is a binomial estimate whose counts
are stored alongside it. `posterior_draws` samples Jeffreys-prior Beta posteriors
for all of them (mapped fraction, glint sample rate, sensitivity, false floor,
manual verdicts, recall) and pushes them through the same estimator, giving per-bin
and — in density — per-region/-country credible intervals instead of bare points.

The derived table is written to `configs/calibration/<aoi>_candidate_precision.yaml`
(checked in — `data/` is gitignored) with full provenance.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

# Single source of the glint-study numbers (sensitivity on OSM-confirmed true PV per
# area bucket + control false-validation floor), shared with the leads-side boost.
from earthpv.postprocess import (
    _GLINT_BUCKET_EDGES_M2 as BIN_EDGES_M2,
    _GLINT_FALSE_N as FALSE_N,
    _GLINT_FALSE_N_VALIDATED as FALSE_VALIDATED_N,
    _GLINT_FALSE_VALIDATED as FALSE_FLOOR,
    _GLINT_STUDY_N as SENSITIVITY_N,
    _GLINT_STUDY_VALIDATED as SENSITIVITY_VALIDATED_N,
    _GLINT_VALIDATED_RATE as SENSITIVITY,
)

log = logging.getLogger(__name__)

BIN_LABELS = ("<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k")
CALIBRATION_DIR = Path("configs/calibration")
# p_u is only invertible where the instrument discriminates and the sample carries
# signal: require S_b - f >= 0.05 and >= 30 sampled candidates in the bin.
MIN_DISCRIMINATION = 0.05
MIN_SAMPLE_N = 30
# A direct human verdict needs fewer samples than an inversion through a noisy
# instrument; below this the bin falls through to glint/extrapolation.
MIN_MANUAL_N = 20
# Mapped reference installations needed to measure model recall in a bin.
MIN_RECALL_N = 20
# Recall is clamped at use time: a bin measured at recall 0.01 would inflate its
# candidates 100x on a denominator this pipeline cannot pin down. 0.05 caps the
# Horvitz-Thompson inflation at 20x; bins below the floor are dominated by the
# `exp` metric's sub-threshold signal anyway.
DEFAULT_RECALL_FLOOR = 0.05
N_DRAWS = 4000
SEED = 20260723
CI_PCT = (5.0, 95.0)  # 90% equal-tailed credible interval


def default_table_path(aoi: str) -> Path:
    return CALIBRATION_DIR / f"{aoi}_candidate_precision.yaml"


def bin_index(area_m2: np.ndarray) -> np.ndarray:
    return np.digitize(np.asarray(area_m2, dtype=float), BIN_EDGES_M2)


def coverage_filter(features: gpd.GeoDataFrame, prob_dir: Path) -> gpd.GeoDataFrame:
    """Keep features whose representative point falls inside an inferred raster.

    A mapped installation the pipeline never imaged cannot be detected; counting it
    in the recall denominator would deflate recall and inflate the correction.
    """
    import rasterio
    from rasterio.warp import transform_bounds
    from shapely.geometry import box as shapely_box
    from shapely.strtree import STRtree

    tifs = sorted(Path(prob_dir).glob("*.tif"))
    if not tifs:
        raise FileNotFoundError(f"No probability rasters in {prob_dir}")
    boxes = []
    for tif in tifs:
        with rasterio.open(tif) as src:
            boxes.append(shapely_box(*transform_bounds(src.crs, "EPSG:4326", *src.bounds)))
    tree = STRtree(boxes)
    reps = features.geometry.representative_point()
    hits = tree.query(reps.values, predicate="within")
    keep = np.zeros(len(features), dtype=bool)
    keep[np.unique(hits[0])] = True
    return features[keep].reset_index(drop=True)


def _nearest_measured(bins: list[dict], key_source: str) -> None:
    """Fill unmeasured bins from the nearest measured bin (prefer the larger
    neighbour on ties — conservative for both p_u and recall)."""
    val_key = {"p_unmapped_source": "p_unmapped", "recall_source": "recall"}[key_source]
    measured = [i for i, r in enumerate(bins) if r[key_source] in ("measured", "manual")]
    for i, row in enumerate(bins):
        if row[val_key] is None:
            if measured:
                j = min(measured, key=lambda m: (abs(m - i), -m))
                row[val_key] = bins[j][val_key]
                row[key_source] = f"extrapolated from {bins[j]['label']}"
            else:
                row[val_key] = 0.0 if val_key == "p_unmapped" else None


def derive_table(
    cands: gpd.GeoDataFrame,
    mapped: gpd.GeoDataFrame | None,
    aoi: str,
    glint_sample: pd.DataFrame | None = None,
    min_distance_m: float = 100.0,
    manual_reviews: pd.DataFrame | None = None,
    recall_reference: gpd.GeoDataFrame | None = None,
    recall_reference_name: str = "none",
) -> dict:
    """Derive the per-bin p_real (+ recall + CI) table.

    `glint_sample` needs columns `bin_label`, `n`, `n_validated` (one row per bin),
    as written by `scripts/glint_candidate_precision.py analyze`. `manual_reviews`
    needs `bin_label`, `n`, `n_real` (aggregated by the CLI from a reviewed
    calibrate-sample file). `recall_reference` is a GeoDataFrame of mapped OSM solar
    *polygons* independent of this pipeline's own contributions, already restricted
    to imaged coverage (`coverage_filter`).
    """
    from earthpv.export import new_lead_mask
    from earthpv.labels import geodesic_area_m2

    idx = bin_index(cands["area_m2"].to_numpy())
    if mapped is not None and not mapped.empty:
        is_mapped = ~new_lead_mask(cands, mapped, min_distance_m=min_distance_m)
    else:
        log.warning("No mapped OSM reference — mapped fraction is 0 everywhere")
        is_mapped = np.zeros(len(cands), dtype=bool)

    sample_by_bin: dict[str, tuple[int, int]] = {}
    if glint_sample is not None and len(glint_sample):
        for row in glint_sample.itertuples():
            sample_by_bin[str(row.bin_label)] = (int(row.n), int(row.n_validated))
    manual_by_bin: dict[str, tuple[int, int]] = {}
    if manual_reviews is not None and len(manual_reviews):
        for row in manual_reviews.itertuples():
            manual_by_bin[str(row.bin_label)] = (int(row.n), int(row.n_real))

    # Model recall per bin: mapped reference installations matched by any candidate.
    recall_by_bin: dict[str, tuple[int, int]] = {}
    if recall_reference is not None and not recall_reference.empty:
        ref = recall_reference[
            recall_reference.geometry.geom_type.isin(("Polygon", "MultiPolygon"))
        ].reset_index(drop=True)
        if len(ref) < len(recall_reference):
            log.info(
                "Recall reference: dropped %d point/line features (no measurable area)",
                len(recall_reference) - len(ref),
            )
        if not ref.empty:
            areas = np.array([geodesic_area_m2(g) for g in ref.geometry])
            ridx = bin_index(areas)
            matched = ~new_lead_mask(ref, cands, min_distance_m=min_distance_m)
            for b, label in enumerate(BIN_LABELS):
                in_bin = ridx == b
                recall_by_bin[label] = (int(in_bin.sum()), int(matched[in_bin].sum()))

    bins: list[dict] = []
    for b, label in enumerate(BIN_LABELS):
        in_bin = idx == b
        n = int(in_bin.sum())
        n_mapped = int(is_mapped[in_bin].sum())
        sens = float(SENSITIVITY[b])

        p_u: float | None = None
        source = "none"
        n_sample, n_validated = sample_by_bin.get(label, (0, 0))
        n_manual, n_real = manual_by_bin.get(label, (0, 0))
        if n_manual >= MIN_MANUAL_N:
            p_u = n_real / n_manual
            source = "manual"
        elif n_sample >= MIN_SAMPLE_N and sens - FALSE_FLOOR >= MIN_DISCRIMINATION:
            v = n_validated / n_sample
            p_u = float(np.clip((v - FALSE_FLOOR) / (sens - FALSE_FLOOR), 0.0, 1.0))
            source = "measured"

        recall_n, recall_matched = recall_by_bin.get(label, (0, 0))
        recall: float | None = None
        recall_source = "none"
        if recall_n >= MIN_RECALL_N:
            recall = recall_matched / recall_n
            recall_source = "measured"

        bins.append({
            "label": label,
            "n_candidates": n,
            "n_mapped": n_mapped,
            "mapped_frac": round(n_mapped / n, 4) if n else 0.0,
            "sensitivity": sens,
            "sensitivity_n": int(SENSITIVITY_N[b]),
            "sensitivity_validated": int(SENSITIVITY_VALIDATED_N[b]),
            "glint_sample_n": n_sample,
            "glint_sample_validated": n_validated,
            "manual_n": n_manual,
            "manual_real": n_real,
            "p_unmapped": p_u,
            "p_unmapped_source": source,
            "recall_n": recall_n,
            "recall_matched": recall_matched,
            "recall": recall,
            "recall_source": recall_source,
        })

    _nearest_measured(bins, "p_unmapped_source")
    _nearest_measured(bins, "recall_source")

    for row in bins:
        row["p_unmapped"] = round(float(row["p_unmapped"]), 4)
        row["p_real"] = round(
            row["mapped_frac"] + (1.0 - row["mapped_frac"]) * row["p_unmapped"], 4
        )
        row["recall"] = None if row["recall"] is None else round(float(row["recall"]), 4)

    p_u_measured = any(r["p_unmapped_source"] in ("measured", "manual") for r in bins)
    status = "glint-calibrated" if p_u_measured else "interim-mapped-only"
    table = {
        "aoi": aoi,
        "status": status,
        "derived": date.today().isoformat(),
        "min_distance_m": min_distance_m,
        "false_floor": FALSE_FLOOR,
        "false_n": FALSE_N,
        "false_validated": FALSE_VALIDATED_N,
        "recall_reference": recall_reference_name,
        "recall_reference_n": int(sum(r["recall_n"] for r in bins)),
        "n_draws": N_DRAWS,
        "seed": SEED,
        "ci_pct": list(CI_PCT),
        "bin_edges_m2": list(BIN_EDGES_M2),
        "bins": bins,
        "provenance": (
            "p_real(b) = mapped_frac(b) + (1-mapped_frac(b)) * p_u(b); p_u from manual "
            "review of unmapped candidates where sampled (n>=20), else glint inversion "
            "p_u(b) = clip((v_b - f)/(S_b - f), 0, 1). S from the 500-target study on "
            "OSM-confirmed installations (results/glint_validation_pakistan/), f from "
            "69 Lahore no-PV controls, v from a stratified glint sample of unmapped "
            "candidates (scripts/glint_candidate_precision.py). recall(b) = fraction of "
            "coverage-restricted, pipeline-independent mapped OSM installations of bin b "
            "matched by any candidate; density divides by it (clamped at a floor) for "
            "the Horvitz-Thompson estimator est_mwp_rc. *_lo/*_hi are the 5th/95th "
            "percentiles of posteriors over every stored count (Jeffreys Beta for the "
            "direct rates; for glint bins a uniform-prior binomial-mixture likelihood "
            "k ~ Binom(n, p_u*S + (1-p_u)*f), which stays honestly flat where S ~ f). "
            "The p_real point clips p_u at 0, so where the observed glint rate sits "
            "below the false floor the floor-leaning point can fall below p_real_lo — "
            "the interval, not the point, is the uncertainty statement. "
            "interim-mapped-only means p_u=0 everywhere: an honest lower bound."
        ),
    }

    draws = posterior_draws(table)
    for i, row in enumerate(bins):
        lo, hi = np.percentile(draws["p_real"][i], CI_PCT)
        row["p_real_lo"], row["p_real_hi"] = round(float(lo), 4), round(float(hi), 4)
        if row["recall"] is not None:
            lo, hi = np.percentile(draws["recall"][i], CI_PCT)
            row["recall_lo"], row["recall_hi"] = round(float(lo), 4), round(float(hi), 4)
    return table


def _binom_mixture_posterior(
    rng: np.random.Generator, k: int, n: int, sens: np.ndarray, f: np.ndarray,
    grid_n: int = 201,
) -> np.ndarray:
    """Sample p_u | (k of n glint-validated) with per-draw sensitivity/false-floor.

    Uniform prior on a p_u grid; per draw d the validated probability is
    q = p_u * S_d + (1 - p_u) * f_d, likelihood Binomial(k; n, q). Returns one p_u
    sample per draw (inverse-CDF on the gridded posterior).
    """
    grid = np.linspace(0.0, 1.0, grid_n)
    q = np.clip(np.outer(sens, grid) + np.outer(f, 1.0 - grid), 1e-9, 1 - 1e-9)
    loglik = k * np.log(q) + (n - k) * np.log1p(-q)
    post = np.exp(loglik - loglik.max(axis=1, keepdims=True))
    cdf = np.cumsum(post, axis=1)
    cdf /= cdf[:, -1:]
    u = rng.random(len(sens))
    idx = np.array([np.searchsorted(cdf[d], u[d]) for d in range(len(sens))])
    return grid[np.minimum(idx, grid_n - 1)]


def posterior_draws(table: dict, n_draws: int | None = None, seed: int | None = None) -> dict:
    """Jeffreys Beta posterior draws for every bin-level rate in the table.

    Returns arrays shaped (n_bins, n_draws): `p_real`, `recall` (1.0 where
    unmeasured), and `lr` (per-draw glint likelihood ratio S_b/f, for the same
    posterior update `candidate_p_real` applies to glint-validated candidates).
    Reproducible from the YAML alone — all counts are stored in the table. Tables
    from before the counts existed degrade to point-mass draws.
    """
    rng = np.random.default_rng(table.get("seed", SEED) if seed is None else seed)
    n_draws = int(table.get("n_draws", N_DRAWS)) if n_draws is None else n_draws
    bins = table["bins"]
    nb = len(bins)

    k_f = int(table.get("false_validated", FALSE_VALIDATED_N))
    n_f = int(table.get("false_n", FALSE_N))
    f = rng.beta(k_f + 0.5, n_f - k_f + 0.5, size=n_draws)

    def beta_or_point(k: int | None, n: int | None, point: float) -> np.ndarray:
        if n:
            return rng.beta(k + 0.5, n - k + 0.5, size=n_draws)
        return np.full(n_draws, point)

    sens = np.empty((nb, n_draws))
    m = np.empty((nb, n_draws))
    p_u = np.zeros((nb, n_draws))
    recall = np.ones((nb, n_draws))
    for i, row in enumerate(bins):
        sens[i] = beta_or_point(
            row.get("sensitivity_validated"), row.get("sensitivity_n"), row["sensitivity"]
        )
        n_c = int(row["n_candidates"])
        k_m = row.get("n_mapped")
        if k_m is None:
            k_m = int(round(row["mapped_frac"] * n_c))
        m[i] = beta_or_point(k_m, n_c, row["mapped_frac"])

        source = row.get("p_unmapped_source", "none")
        if source == "manual":
            p_u[i] = beta_or_point(row["manual_real"], row["manual_n"], row["p_unmapped"])
        elif source == "measured":
            # Proper likelihood, not the point inversion: the k validated of n sampled
            # are Binomial(n, p_u*S + (1-p_u)*f). Where a draw's S ~ f the likelihood
            # goes flat in p_u (instrument uninformative -> wide posterior), instead of
            # the ratio (v-f)/(S-f) blowing up to a spurious spike at 1.
            p_u[i] = _binom_mixture_posterior(
                rng, int(row["glint_sample_validated"]), int(row["glint_sample_n"]),
                sens[i], f,
            )

        if row.get("recall_source") == "measured":
            recall[i] = beta_or_point(row["recall_matched"], row["recall_n"], row["recall"])

    # Extrapolated bins copy the source bin's draws (fully correlated — they carry
    # no independent information).
    label_to_i = {row["label"]: i for i, row in enumerate(bins)}
    for i, row in enumerate(bins):
        for src_key, mat in (("p_unmapped_source", p_u), ("recall_source", recall)):
            source = row.get(src_key, "") or ""
            if source.startswith("extrapolated from "):
                mat[i] = mat[label_to_i[source.removeprefix("extrapolated from ")]]

    return {"p_real": m + (1.0 - m) * p_u, "recall": recall, "lr": sens / f}


def write_table(table: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(table, sort_keys=False))
    log.info("Wrote calibration table (%s) -> %s", table["status"], path)
    return path


def load_table(path: Path) -> dict:
    table = yaml.safe_load(Path(path).read_text())
    edges = tuple(float(e) for e in table["bin_edges_m2"])
    if edges != tuple(float(e) for e in BIN_EDGES_M2):
        raise ValueError(
            f"{path}: bin_edges_m2 {edges} do not match the study edges {BIN_EDGES_M2} — "
            "re-derive with `earthpv calibrate-candidates`"
        )
    return table


def candidate_p_real(
    area_m2: np.ndarray,
    table: dict,
    glint_consistent: np.ndarray | None = None,
    min_consistent: int = 2,
) -> np.ndarray:
    """Per-candidate P(real): the bin prior, Bayes-updated where glint evidence exists.

    A glint-validated candidate (>= `min_consistent` mutually-consistent spike dates)
    gets posterior odds = prior odds * LR with LR = S_b / f — the same measured
    evidence weight the leads-side rank boost uses. Candidates without a validated
    fit keep the prior: absence of glint is weak evidence (~70% of real arrays never
    validate), mirroring the reward-only convention of `add_glint_prior`.
    """
    idx = bin_index(area_m2)
    prior = np.array([table["bins"][b]["p_real"] for b in idx], dtype=float)
    if glint_consistent is None:
        return prior
    validated = np.asarray(glint_consistent) >= min_consistent
    lr = np.asarray(SENSITIVITY, dtype=float)[idx] / FALSE_FLOOR
    prior_c = prior.clip(1e-6, 1 - 1e-6)
    odds = prior_c / (1.0 - prior_c) * lr
    posterior = odds / (1.0 + odds)
    return np.where(validated, posterior, prior)


def candidate_recall(
    area_m2: np.ndarray, table: dict, floor: float = DEFAULT_RECALL_FLOOR
) -> np.ndarray:
    """Per-candidate model recall for its size bin, clamped to `floor`.

    Bins whose recall was never measured (recall None / absent — pre-v2 tables)
    return 1.0: no correction rather than a made-up one.
    """
    per_bin = np.array(
        [1.0 if row.get("recall") is None else float(row["recall"]) for row in table["bins"]]
    )
    return np.maximum(per_bin[bin_index(area_m2)], floor)
