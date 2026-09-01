"""Candidate-precision calibration for the PV capacity atlas.

The pipeline serves two products from one recall-first model. The *leads* product
(postprocess -> export -> MapRoulette) tolerates false positives because humans
validate every candidate. The *capacity atlas* (density stage) has no human in the
loop, so raw candidate area systematically overstates MWp. This module estimates
P(real PV | model candidate) per area bin - `p_real` - which density uses to weight
candidate area into the calibrated `est_mwp_cal` estimator. The leads product never
consumes this table, and this module never consumes `rank_score`: that is the
separation between the two products.

`p_real` per bin combines independent evidence sources, in order of directness:

- **mapped fraction** - candidates within `min_distance_m` (default 100 m, matching
  the new-leads export filter) of an already-mapped OSM solar feature are taken as
  real. Computed offline from data that always exists.
- **manual review of the unmapped remainder** - a human verdict (high-res imagery)
  on a stratified per-bin sample of unmapped candidates measures P(real | unmapped)
  directly. This is the only instrument that works below ~500 m2, where glint has no
  discrimination; `earthpv calibrate-sample` emits the review file.
- **glint inversion on the unmapped remainder** - the glint instrument validates a
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
direction - the fraction of independently-mapped installations of bin b that the
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
and - in density - per-region/-country credible intervals instead of bare points.

The derived table is written to `configs/calibration/<aoi>_candidate_precision.yaml`
(checked in - `data/` is gitignored) with full provenance.
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

# --------------------------------------------------------------------------------------
# Area -> capacity conversion: two constants, because detected area means two things
# --------------------------------------------------------------------------------------
# A *rooftop* detection outlines the panel field on a roof, which is close to module
# area: ~5.5 m2 of c-Si module per kWp -> 0.18 kWp/m2 (grounded against the CEC
# datasheet database by pv_capacity.check_kwp_per_m2).
DEFAULT_KWP_PER_M2_MODULE = 0.18
# A *ground-mount* detection outlines the SITE, not the modules. The ground-PV training
# labels are OSM `power=plant` perimeters (labels.py), which enclose access roads,
# inter-row spacing and substations, so the model is taught to fill the fence line and a
# detected polygon is site area. Only the ground-cover ratio of it is module.
#
# Calibrated 2026-08-10 against the two named-plant ground-mount calibration boxes
# (docs/issues/pakistan-calibration-boxes.md, results/groundmount_quadrat_validation.csv)
# -- the only external nameplate-capacity anchors this project has for the constant,
# where before it was reasoned from a GCR assumption alone:
#   Quaid-e-Azam Solar Park: 400 MW operational (Wikipedia/PPDB/Global Energy Monitor)
#     / 8,904,839 m2 dissolved OSM footprint (labels.dissolve_overlapping; the raw,
#     un-dissolved pull nested a `generator` way inside its own `plant` perimeter,
#     which would have understated the implied constant by treating one site as two)
#     -> 0.0449 kWp/m2.
#   Sukkur solar farm: 150 MW combined (3 x 50 MW phases -- Helios/Meridian/HND-Scatec,
#     confirmed via Global Energy Monitor and Scatec's own financial-close reporting;
#     the single `plant:output:electricity=50 MW` OSM tag on the calibration box's
#     matched way describes only ONE phase, not the combined complex, so 50 MW alone
#     would have been a 3x undercount here) / 2,606,013 m2 -> 0.0576 kWp/m2.
# Geometric mean 0.0509, rounded to 0.05 -- close to the LOW end of the old GCR-reasoned
# range (0.045-0.11 for GCR 0.25-0.6), i.e. the old 0.07 point sat nearer the range's
# upper-middle than either measured site does. n=2 is not enough to claim a tight
# posterior, so the 90% range is kept close to its old width (log-ratio ~2.44) rather
# than collapsed to bracket only these two points -- other sites plausibly use tracking
# or wider row spacing this pair doesn't cover.
DEFAULT_KWP_PER_M2_LAND = 0.05
# 90% ranges for the two constants, carried as lognormal priors so the conversion enters
# the credible intervals instead of being treated as exact (it was the largest term
# previously excluded from them). Module: module-efficiency spread plus roof packing.
# Land: bracketed by the two measured plants above with a margin on each side for GCR
# regimes they don't cover (tracking, wider fixed-tilt spacing). Each range is centred
# geometrically on its point value, so the point is the prior's median.
KWP_MODULE_CI90 = (0.15, 0.21)
KWP_LAND_CI90 = (0.035, 0.075)
# Offset so the conversion draws are independent of the precision/recall draws, which
# use `seed` directly.
KWP_SEED_OFFSET = 7
_Z95 = 1.6448536269514722  # standard-normal 95th percentile


def default_table_path(aoi: str) -> Path:
    return CALIBRATION_DIR / f"{aoi}_candidate_precision.yaml"


def _lognormal_draws(
    rng: np.random.Generator, median: float, ci90: tuple[float, float], n: int
) -> np.ndarray:
    """Lognormal draws with the given median and (to within the median's own offset from
    the range's geometric centre) the given 90% range."""
    lo, hi = float(ci90[0]), float(ci90[1])
    if not 0 < lo < hi:
        raise ValueError(f"ci90 must satisfy 0 < lo < hi, got {ci90}")
    sigma = np.log(hi / lo) / (2.0 * _Z95)
    return float(median) * np.exp(rng.normal(0.0, sigma, n))


def kwp_draws(
    n_draws: int = N_DRAWS,
    module: float = DEFAULT_KWP_PER_M2_MODULE,
    land: float = DEFAULT_KWP_PER_M2_LAND,
    module_ci90: tuple[float, float] = KWP_MODULE_CI90,
    land_ci90: tuple[float, float] = KWP_LAND_CI90,
    seed: int | None = None,
) -> dict:
    """Prior draws for the two area->capacity constants, in kWp per m2.

    `module` converts rooftop panel area, `land` converts ground-mount *site* area; see
    the constants above for why they differ by ~2.5x. Both are lognormal (a strictly
    positive multiplicative factor) centred on their point value. Returns
    `{"module": (n_draws,), "land": (n_draws,), "module_point": float,
    "land_point": float}` so a caller can compose per-cell draw matrices and point
    estimates from one object.
    """
    rng = np.random.default_rng(SEED + KWP_SEED_OFFSET if seed is None else seed)
    return {
        "module": _lognormal_draws(rng, module, module_ci90, n_draws),
        "land": _lognormal_draws(rng, land, land_ci90, n_draws),
        "module_point": float(module),
        "land_point": float(land),
    }


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
    neighbour on ties - conservative for both p_u and recall)."""
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
    sensitivity_override: dict[str, float] | None = None,
    min_distance_m: float = 100.0,
    manual_reviews: pd.DataFrame | None = None,
    recall_reference: gpd.GeoDataFrame | None = None,
    recall_reference_name: str = "none",
    recall_cands: gpd.GeoDataFrame | None = None,
    by_placement: bool = False,
    mapped_attrs: gpd.GeoDataFrame | None = None,
    p_unmapped_by_placement: dict[str, dict[str, tuple[int, int]]] | None = None,
) -> dict:
    """Derive the per-bin p_real (+ recall + CI) table.

    `glint_sample` needs columns `bin_label`, `n`, `n_validated` (one row per bin),
    as written by `scripts/glint_candidate_precision.py analyze`. `manual_reviews`
    needs `bin_label`, `n`, `n_real` (aggregated by the CLI from a reviewed
    calibrate-sample file). `recall_reference` is a GeoDataFrame of mapped OSM solar
    *polygons* independent of this pipeline's own contributions, already restricted
    to imaged coverage (`coverage_filter`).

    `recall_cands` lets the recall check (below) be measured against a DIFFERENT
    candidate population than the one precision (`p_real`, mapped fraction) is measured
    against -- e.g. `cands` unioned with a second detector's candidates, so recall(b)
    reflects "did EITHER detector find this", while precision still only speaks to
    `cands`' own candidates (a second detector's own precision is a separate, unmeasured
    question, and conflating the two would silently launder it in). Defaults to `cands`,
    so every existing caller's behavior is unchanged.

    `by_placement`, if True, additionally derives `table["placement_bins"]`
    (`derive_placement_tables`) -- separate rooftop/ground precision+recall, so
    density.py's per-candidate weighting can stop applying rooftop's much higher
    mapped fraction to ground candidates in the same area bin. Needs `mapped_attrs`
    (a `placement`-carrying reference, e.g. `export.load_mapped_reference_attrs`'s
    output -- NOT `mapped`, which is boolean-only) to restrict the mapped-fraction
    test by placement; without it, falls back to the unrestricted `mapped` for both
    groups (see `derive_placement_tables`'s own docstring for what that costs).
    """
    from earthpv.export import new_lead_mask
    from earthpv.labels import geodesic_area_m2

    idx = bin_index(cands["area_m2"].to_numpy())
    if mapped is not None and not mapped.empty:
        is_mapped = ~new_lead_mask(cands, mapped, min_distance_m=min_distance_m)
    else:
        log.warning("No mapped OSM reference - mapped fraction is 0 everywhere")
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
    recall_pop = cands if recall_cands is None else recall_cands
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
            matched = ~new_lead_mask(ref, recall_pop, min_distance_m=min_distance_m)
            for b, label in enumerate(BIN_LABELS):
                in_bin = ridx == b
                recall_by_bin[label] = (int(in_bin.sum()), int(matched[in_bin].sum()))

    bins: list[dict] = []
    for b, label in enumerate(BIN_LABELS):
        in_bin = idx == b
        n = int(in_bin.sum())
        n_mapped = int(is_mapped[in_bin].sum())
        # Glint sensitivity for this bin. The study constant is a rate measured on the
        # 500-target OSM-confirmed population; `sensitivity_override` replaces it with the
        # rate predicted for THIS candidate population's own glint opportunity (see
        # `glint_opportunity.population_sensitivity`). Measured 2026-08-12: within a single
        # size bin the validated rate varies about 2x between the lowest and highest
        # opportunity tertile (5k-50k m2: 0.036 -> 0.538), so dividing a candidate `v_b` by
        # a study `S_b` measured at different exposure biases the inversion.
        sens = float(SENSITIVITY[b])
        sens_source = "study"
        if sensitivity_override and label in sensitivity_override:
            sens = float(sensitivity_override[label])
            sens_source = "opportunity_adjusted"

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
            "sensitivity_source": sens_source,
            "sensitivity_study": float(SENSITIVITY[b]),
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
            "below the false floor the floor-leaning point can fall below p_real_lo - "
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

    if by_placement:
        table["placement_bins"] = derive_placement_tables(
            cands, bins, aoi, mapped_attrs=mapped_attrs, min_distance_m=min_distance_m,
            recall_reference=recall_reference, recall_cands=recall_pop,
            n_draws=N_DRAWS, seed=SEED,
            p_unmapped_by_placement=p_unmapped_by_placement,
        )
        # `status` is computed from the POOLED bins, which stay mapped-only when the
        # p_unmapped evidence is register-derived (it is attributable to a placement, so
        # it is only applied there). Saying "interim-mapped-only" would then describe a
        # table whose placement bins -- the ones `density` actually consumes when present
        # -- do carry measured p_unmapped. Only upgrade the mapped-only label; never
        # overwrite "glint-calibrated", which `_table_evidence` keys on.
        if table["status"] == "interim-mapped-only" and any(
            b.get("p_unmapped_source") == "mastr-geolocated"
            for bins_g in table["placement_bins"].values()
            for b in bins_g
        ):
            table["status"] = "register-calibrated-by-placement"
    return table


PLACEMENT_GROUPS = ("rooftop", "ground")


def _placement_group(placement: np.ndarray) -> np.ndarray:
    """Rooftop vs everything else -- matches `density.py`'s own roof/ground split
    (`placement == "rooftop"` vs `no_building`/`ground_adjacent`) and the two area ->
    capacity constants (module vs land)."""
    is_rooftop = np.asarray(placement).astype(str) == "rooftop"
    return np.where(is_rooftop, "rooftop", "ground")


def derive_placement_tables(
    cands: gpd.GeoDataFrame,
    pooled_bins: list[dict],
    aoi: str,
    mapped_attrs: gpd.GeoDataFrame | None = None,
    min_distance_m: float = 100.0,
    recall_reference: gpd.GeoDataFrame | None = None,
    recall_cands: gpd.GeoDataFrame | None = None,
    n_draws: int = N_DRAWS,
    seed: int = SEED,
    p_unmapped_by_placement: dict[str, dict[str, tuple[int, int]]] | None = None,
) -> dict:
    """Separate rooftop/ground precision+recall tables, so ground-mount stops
    borrowing rooftop's much higher mapped fraction in the same area bin.

    Pooling both placements into one set of bins was measured 2026-08-10 to matter a
    lot: nationally, only ~1% of surviving model-only ground candidates sit within
    100 m of ANY mapped OSM solar feature (vs ~14% for rooftop), so the pooled table's
    `p_real` for a mid-size bin is dominated by rooftop's much better corroboration
    and applied unchanged to ground candidates that have almost none of their own.

    `mapped_frac` and `recall` are pure geometric OSM matches - no glint needed - so
    both are split by placement directly, using `mapped_attrs` (must carry a
    `placement` column; `export.load_mapped_reference_attrs`'s output, NOT the
    boolean-only `mapped` `derive_table` itself uses) and, where given,
    `recall_reference`'s own `placement` column. Either falls back to the unrestricted
    (pooled) population with a warning if it lacks a `placement` column - a rooftop
    candidate matching a ground reference feature 100 m away is a rare, not a
    systematic, error, so this is a fallback worth having rather than refusing to run.

    `p_unmapped` (the glint-inversion component of precision) is NOT independently
    split: the existing glint sample (`data/glint/pakistan_cand_targets.parquet`,
    pulled 2026-07-19) predates three subsequent candidate-population regenerations
    (the 2026-07-29 OSM-geometry replacement, the 2026-08-06 edge-overlap fix, the
    2026-08-10 postprocess refresh) and cannot be reliably re-attributed to a
    placement it never recorded. Rather than fabricate a split or silently reuse a
    number that may not describe either group:
      - **ground** bins force `p_unmapped = 0.0` ("interim-mapped-only-by-placement"),
        an honest floor in the same sense this project already uses that label
        elsewhere (Gujarat's `recall-reference none`) -- so `p_real = mapped_frac`
        for ground, i.e. only geometrically-corroborated ground candidates count as
        real until a placement-specific glint pull exists.
      - **rooftop** bins inherit the pooled table's own `p_unmapped` per bin
        ("inherited-from-pooled"), since rooftop dominates the pooled population these
        values were fit on and a placement-restricted mapped_frac for rooftop is
        already a real improvement over the fully pooled number on its own.

    `p_unmapped_by_placement` overrides both defaults where supplied, as
    `{placement: {bin_label: (n_unmapped, n_confirmed)}}`. This exists because the
    objection above is specific to the *glint* sample -- it never recorded a placement.
    An external register that geolocates individual units does, so its verdicts can be
    attributed to rooftop vs ground directly. Germany's MaStR is the first such source
    (`scripts/mastr_p_unmapped.py`, 2026-09-01): it publishes per-unit coordinates for
    units >= 30 kWp, so a registered installation's address point falling inside an
    unmapped candidate polygon is direct evidence that candidate is real. Bins with
    fewer than `MIN_MANUAL_N` reviews fall back to the defaults above, and
    `_nearest_measured` then extrapolates across the gap as usual. Supplying nothing
    reproduces the previous behaviour exactly, so AOIs without such a register (all of
    them except Germany) are unaffected.

    Returns `{"rooftop": [...6 bins...], "ground": [...6 bins...]}`, each shaped like
    `derive_table`'s own `table["bins"]` (same keys, `p_real_lo`/`_hi` included via
    `posterior_draws` reused on a synthetic per-group table).
    """
    from earthpv.export import new_lead_mask
    from earthpv.labels import geodesic_area_m2

    cands = cands.reset_index(drop=True)
    groups = _placement_group(cands["placement"].to_numpy())
    recall_cands = cands if recall_cands is None else recall_cands
    recall_groups = (
        _placement_group(recall_cands["placement"].to_numpy())
        if "placement" in recall_cands.columns else None
    )
    if recall_groups is None and recall_reference is not None and not recall_reference.empty:
        log.warning(
            "recall_cands has no `placement` column - recall split by placement will "
            "use the unrestricted candidate population for both groups"
        )

    ref_groups = None
    if recall_reference is not None and not recall_reference.empty:
        if "placement" in recall_reference.columns:
            ref_groups = _placement_group(recall_reference["placement"].to_numpy())
        else:
            log.warning(
                "recall_reference has no `placement` column - recall split by "
                "placement will pool both groups against the same reference"
            )

    mapped_groups = None
    if mapped_attrs is not None and not mapped_attrs.empty:
        if "placement" in mapped_attrs.columns:
            mapped_groups = _placement_group(mapped_attrs["placement"].to_numpy())
        else:
            log.warning(
                "mapped_attrs has no `placement` column - mapped_frac split by "
                "placement will use the unrestricted reference for both groups"
            )

    pooled_p_u = {row["label"]: row["p_unmapped"] for row in pooled_bins}
    out: dict[str, list[dict]] = {}
    for g in PLACEMENT_GROUPS:
        g_cands = cands[groups == g].reset_index(drop=True)
        idx = bin_index(g_cands["area_m2"].to_numpy()) if len(g_cands) else np.array([], dtype=int)

        if mapped_attrs is not None and not mapped_attrs.empty:
            ref = mapped_attrs[mapped_groups == g] if mapped_groups is not None else mapped_attrs
            is_mapped = (
                ~new_lead_mask(g_cands, ref, min_distance_m=min_distance_m)
                if len(g_cands) and not ref.empty else np.zeros(len(g_cands), dtype=bool)
            )
        else:
            is_mapped = np.zeros(len(g_cands), dtype=bool)

        recall_by_bin: dict[str, tuple[int, int]] = {}
        if recall_reference is not None and not recall_reference.empty:
            ref_sub = (
                recall_reference[ref_groups == g] if ref_groups is not None else recall_reference
            )
            ref_sub = ref_sub[
                ref_sub.geometry.geom_type.isin(("Polygon", "MultiPolygon"))
            ].reset_index(drop=True)
            pop_sub = recall_cands[recall_groups == g] if recall_groups is not None else recall_cands
            if not ref_sub.empty:
                areas = np.array([geodesic_area_m2(geom) for geom in ref_sub.geometry])
                ridx = bin_index(areas)
                matched = (
                    ~new_lead_mask(ref_sub, pop_sub, min_distance_m=min_distance_m)
                    if not pop_sub.empty else np.zeros(len(ref_sub), dtype=bool)
                )
                for b, label in enumerate(BIN_LABELS):
                    in_bin = ridx == b
                    recall_by_bin[label] = (int(in_bin.sum()), int(matched[in_bin].sum()))

        bins: list[dict] = []
        for b, label in enumerate(BIN_LABELS):
            in_bin = idx == b
            n = int(in_bin.sum())
            n_mapped = int(is_mapped[in_bin].sum())
            mapped_frac = round(n_mapped / n, 4) if n else 0.0
            p_u = 0.0 if g == "ground" else float(pooled_p_u.get(label, 0.0))
            p_u_source = "interim-mapped-only-by-placement" if g == "ground" else "inherited-from-pooled"
            manual_n = manual_real = 0
            ext = (p_unmapped_by_placement or {}).get(g, {}).get(label)
            if ext is not None and int(ext[0]) >= MIN_MANUAL_N:
                manual_n, manual_real = int(ext[0]), int(ext[1])
                p_u = manual_real / manual_n
                p_u_source = "mastr-geolocated"

            recall_n, recall_matched = recall_by_bin.get(label, (0, 0))
            recall: float | None = None
            recall_source = "none"
            if recall_n >= MIN_RECALL_N:
                recall = round(recall_matched / recall_n, 4)
                recall_source = "measured"

            bins.append({
                "label": label, "n_candidates": n, "n_mapped": n_mapped,
                "mapped_frac": mapped_frac, "p_unmapped": round(p_u, 4),
                "p_unmapped_source": p_u_source,
                "manual_n": manual_n, "manual_real": manual_real,
                "p_real": round(mapped_frac + (1.0 - mapped_frac) * p_u, 4),
                "recall_n": recall_n, "recall_matched": recall_matched,
                "recall": recall, "recall_source": recall_source,
                # Placement-independent property of the glint instrument itself (from
                # the 500-target OSM-confirmed study), not fit on this group's own
                # candidates -- carried only so `posterior_draws` (reused as-is below)
                # has the key it unconditionally reads. Still unused by the branches
                # that would consume it: a placement table's `p_unmapped_source` is
                # never "measured" (the glint mixture branch). It CAN now be
                # "mastr-geolocated", but that branch draws a Beta on manual_n/
                # manual_real and does not read `sensitivity` either.
                "sensitivity": float(SENSITIVITY[b]),
            })
        _nearest_measured(bins, "recall_source")
        for row in bins:
            row["recall"] = None if row["recall"] is None else round(float(row["recall"]), 4)

        synthetic = {
            "seed": seed, "n_draws": n_draws,
            "false_validated": FALSE_VALIDATED_N, "false_n": FALSE_N,
            "bins": bins,
        }
        draws = posterior_draws(synthetic, n_draws=n_draws, seed=seed)
        for i, row in enumerate(bins):
            lo, hi = np.percentile(draws["p_real"][i], CI_PCT)
            row["p_real_lo"], row["p_real_hi"] = round(float(lo), 4), round(float(hi), 4)
            if row["recall"] is not None:
                lo, hi = np.percentile(draws["recall"][i], CI_PCT)
                row["recall_lo"], row["recall_hi"] = round(float(lo), 4), round(float(hi), 4)
        out[g] = bins
        log.info(
            "Placement table [%s]: n=%d mapped_frac(mean)=%.3f p_unmapped(mean)=%.3f "
            "p_real(mean)=%.3f (p_unmapped sources: %s)",
            g, len(g_cands), float(np.mean([r["mapped_frac"] for r in bins])),
            float(np.mean([r["p_unmapped"] for r in bins])),
            float(np.mean([r["p_real"] for r in bins])),
            ", ".join(sorted({r["p_unmapped_source"] for r in bins})),
        )
    return out


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
    Reproducible from the YAML alone - all counts are stored in the table. Tables
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
        if source in ("manual", "mastr-geolocated"):
            # Both are direct per-candidate verdicts on the unmapped remainder (a human
            # review, or a geolocated MaStR unit inside the polygon), so both carry a
            # Beta posterior on their own success counts rather than the glint mixture.
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

    # Extrapolated bins copy the source bin's draws (fully correlated - they carry
    # no independent information).
    label_to_i = {row["label"]: i for i, row in enumerate(bins)}
    for i, row in enumerate(bins):
        for src_key, mat in (("p_unmapped_source", p_u), ("recall_source", recall)):
            source = row.get(src_key, "") or ""
            if source.startswith("extrapolated from "):
                mat[i] = mat[label_to_i[source.removeprefix("extrapolated from ")]]

    return {"p_real": m + (1.0 - m) * p_u, "recall": recall, "lr": sens / f}


# Evidence a table can only LOSE by being re-derived with fewer inputs than the one it
# replaces. `write_table` refuses such an overwrite unless the caller says so explicitly.
# Not hypothetical: `configs/calibration/pakistan_candidate_precision.yaml` was
# regenerated 2026-08-14 without `--by-placement` and without the glint sample and the
# calibration boxes, quietly replacing the placement-split, glint-calibrated table the
# published atlas was actually built from with a pooled, mapped-only one derived from a
# different candidate population. Nothing errored; the loss was only visible by diffing
# the file against a backup.
def _table_evidence(table: dict) -> set[str]:
    evidence = set()
    if "placement_bins" in table:
        evidence.add("placement_bins")
    if table.get("status") == "glint-calibrated":
        evidence.add("glint-calibrated")
    if any(b.get("manual_n") for b in table.get("bins", [])):
        evidence.add("manual-reviews")
    # A register-derived per-placement p_unmapped lives only in `placement_bins`, so the
    # `bins` check above cannot see it. Without this, a bare `calibrate-candidates` re-run
    # would silently drop it -- the same regression the pooled/mapped-only overwrite of
    # 2026-08-14 caused for Pakistan.
    if any(
        b.get("p_unmapped_source") == "mastr-geolocated"
        for bins in (table.get("placement_bins") or {}).values()
        for b in bins
    ):
        evidence.add("register-p-unmapped")
    return evidence


def write_table(table: dict, path: Path, allow_downgrade: bool = False) -> Path:
    path = Path(path)
    if path.exists() and not allow_downgrade:
        try:
            existing = yaml.safe_load(path.read_text())
        except Exception as e:  # noqa: BLE001 -- an unreadable old table must not block a write
            log.warning("Could not read %s to check for an evidence downgrade (%s)", path, e)
            existing = None
        if existing:
            lost = _table_evidence(existing) - _table_evidence(table)
            if lost:
                raise ValueError(
                    f"{path} already carries {sorted(lost)} and the table about to replace "
                    f"it does not. Re-derive with the inputs that produced it (--by-placement, "
                    "--glint-sample, --calibration-box, --manual-reviews, "
                    "--mastr-p-unmapped as applicable), or "
                    "pass --allow-downgrade to overwrite deliberately. See "
                    "capacity_calibration._table_evidence."
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(table, sort_keys=False))
    log.info("Wrote calibration table (%s) -> %s", table["status"], path)
    return path


def load_table(path: Path) -> dict:
    table = yaml.safe_load(Path(path).read_text())
    edges = tuple(float(e) for e in table["bin_edges_m2"])
    if edges != tuple(float(e) for e in BIN_EDGES_M2):
        raise ValueError(
            f"{path}: bin_edges_m2 {edges} do not match the study edges {BIN_EDGES_M2} - "
            "re-derive with `earthpv calibrate-candidates`"
        )
    return table


def candidate_p_real(
    area_m2: np.ndarray,
    table: dict,
    glint_consistent: np.ndarray | None = None,
    min_consistent: int = 2,
    placement: np.ndarray | None = None,
) -> np.ndarray:
    """Per-candidate P(real): the bin prior, Bayes-updated where glint evidence exists.

    A glint-validated candidate (>= `min_consistent` mutually-consistent spike dates)
    gets posterior odds = prior odds * LR with LR = S_b / f - the same measured
    evidence weight the leads-side rank boost uses. Candidates without a validated
    fit keep the prior: absence of glint is weak evidence (~70% of real arrays never
    validate), mirroring the reward-only convention of `add_glint_prior`.

    `placement`, if given and `table` carries `placement_bins`
    (`derive_placement_tables`), looks the bin prior up in that candidate's OWN
    placement group's subtable instead of the pooled one -- see that function's
    docstring for why pooling understated ground-mount's false-positive rate. Falls
    back to the pooled `table["bins"]` for a table with no placement split (older
    tables, or an AOI not yet re-derived with `--by-placement`).
    """
    idx = bin_index(area_m2)
    if placement is not None and "placement_bins" in table:
        groups = _placement_group(placement)
        prior = np.empty(len(idx), dtype=float)
        for g in PLACEMENT_GROUPS:
            gm = groups == g
            if gm.any():
                gbins = table["placement_bins"][g]
                prior[gm] = np.array([gbins[b]["p_real"] for b in idx[gm]], dtype=float)
    else:
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
    area_m2: np.ndarray, table: dict, floor: float = DEFAULT_RECALL_FLOOR,
    placement: np.ndarray | None = None,
) -> np.ndarray:
    """Per-candidate model recall for its size bin, clamped to `floor`.

    Bins whose recall was never measured (recall None / absent - pre-v2 tables)
    return 1.0: no correction rather than a made-up one. `placement` selects the
    candidate's own placement group's subtable when `table` carries
    `placement_bins` -- see `candidate_p_real`.
    """
    idx = bin_index(area_m2)
    if placement is not None and "placement_bins" in table:
        groups = _placement_group(placement)
        per_row = np.empty(len(idx), dtype=float)
        for g in PLACEMENT_GROUPS:
            gm = groups == g
            if gm.any():
                gbins = table["placement_bins"][g]
                per_bin = np.array(
                    [1.0 if row.get("recall") is None else float(row["recall"]) for row in gbins]
                )
                per_row[gm] = per_bin[idx[gm]]
    else:
        per_bin = np.array(
            [1.0 if row.get("recall") is None else float(row["recall"]) for row in table["bins"]]
        )
        per_row = per_bin[idx]
    return np.maximum(per_row, floor)
