"""Candidate-precision calibration for the PV capacity atlas.

The pipeline serves two products from one recall-first model. The *leads* product
(postprocess -> export -> MapRoulette) tolerates false positives because humans
validate every candidate. The *capacity atlas* (density stage) has no human in the
loop, so raw candidate area systematically overstates MWp. This module estimates
P(real PV | model candidate) per area bin — `p_real` — which density uses to weight
candidate area into the calibrated `est_mwp_cal` estimator. The leads product never
consumes this table, and this module never consumes `rank_score`: that is the
separation between the two products.

`p_real` per bin combines two independent evidence sources:

- **mapped fraction** — candidates within `min_distance_m` (default 100 m, matching
  the new-leads export filter) of an already-mapped OSM solar feature are taken as
  real. Computed offline from data that always exists.
- **glint inversion on the unmapped remainder** — the glint instrument validates a
  true array in bin b with probability S_b (sensitivity, measured on 500
  OSM-confirmed Pakistan installations: results/glint_validation_pakistan/) and a
  no-PV building with probability f = 0.087 (69 Lahore controls). If a stratified
  sample of *unmapped* candidates in bin b glint-validates at rate v_b, the real
  fraction among them is

      p_u(b) = clip((v_b - f) / (S_b - f), 0, 1)

  This is only measurable where S_b - f is comfortably positive (>= ~500 m2; below
  that the instrument has no discrimination) and the sample is big enough.
  `scripts/glint_candidate_precision.py` produces the sample CSV.

      p_real(b) = mapped_frac(b) + (1 - mapped_frac(b)) * p_u(b)

Bins where p_u is unmeasurable fall back to the nearest measurable bin's p_u
(flagged `extrapolated`); with no glint sample at all, p_u = 0 everywhere and the
table is an honest lower bound (status `interim-mapped-only`).

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
    _GLINT_FALSE_VALIDATED as FALSE_FLOOR,
    _GLINT_VALIDATED_RATE as SENSITIVITY,
)

log = logging.getLogger(__name__)

BIN_LABELS = ("<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k")
CALIBRATION_DIR = Path("configs/calibration")
# p_u is only invertible where the instrument discriminates and the sample carries
# signal: require S_b - f >= 0.05 and >= 30 sampled candidates in the bin.
MIN_DISCRIMINATION = 0.05
MIN_SAMPLE_N = 30


def default_table_path(aoi: str) -> Path:
    return CALIBRATION_DIR / f"{aoi}_candidate_precision.yaml"


def bin_index(area_m2: np.ndarray) -> np.ndarray:
    return np.digitize(np.asarray(area_m2, dtype=float), BIN_EDGES_M2)


def derive_table(
    cands: gpd.GeoDataFrame,
    mapped: gpd.GeoDataFrame | None,
    aoi: str,
    glint_sample: pd.DataFrame | None = None,
    min_distance_m: float = 100.0,
) -> dict:
    """Derive the per-bin p_real table from candidates + mapped reference (+ glint sample).

    `glint_sample` needs columns `bin_label`, `n`, `n_validated` (one row per bin),
    as written by `scripts/glint_candidate_precision.py analyze`.
    """
    from earthpv.export import new_lead_mask

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

    bins: list[dict] = []
    for b, label in enumerate(BIN_LABELS):
        in_bin = idx == b
        n = int(in_bin.sum())
        mapped_frac = float(is_mapped[in_bin].mean()) if n else 0.0
        sens = float(SENSITIVITY[b])

        p_u: float | None = None
        source = "none"
        n_sample, n_validated = sample_by_bin.get(label, (0, 0))
        if n_sample >= MIN_SAMPLE_N and sens - FALSE_FLOOR >= MIN_DISCRIMINATION:
            v = n_validated / n_sample
            p_u = float(np.clip((v - FALSE_FLOOR) / (sens - FALSE_FLOOR), 0.0, 1.0))
            source = "measured"
        bins.append({
            "label": label,
            "n_candidates": n,
            "mapped_frac": round(mapped_frac, 4),
            "sensitivity": sens,
            "glint_sample_n": n_sample,
            "glint_sample_validated": n_validated,
            "p_unmapped": p_u,
            "p_unmapped_source": source,
        })

    # Unmeasurable bins inherit the nearest measured bin's p_u (prefer the adjacent
    # larger bin: small-candidate precision is, if anything, below it).
    measured = [i for i, r in enumerate(bins) if r["p_unmapped_source"] == "measured"]
    for i, row in enumerate(bins):
        if row["p_unmapped"] is None:
            if measured:
                j = min(measured, key=lambda m: (abs(m - i), m))
                row["p_unmapped"] = bins[j]["p_unmapped"]
                row["p_unmapped_source"] = f"extrapolated from {bins[j]['label']}"
            else:
                row["p_unmapped"] = 0.0

    for row in bins:
        row["p_unmapped"] = round(float(row["p_unmapped"]), 4)
        row["p_real"] = round(
            row["mapped_frac"] + (1.0 - row["mapped_frac"]) * row["p_unmapped"], 4
        )

    status = "glint-calibrated" if measured else "interim-mapped-only"
    return {
        "aoi": aoi,
        "status": status,
        "derived": date.today().isoformat(),
        "min_distance_m": min_distance_m,
        "false_floor": FALSE_FLOOR,
        "bin_edges_m2": list(BIN_EDGES_M2),
        "bins": bins,
        "provenance": (
            "p_real(b) = mapped_frac(b) + (1-mapped_frac(b)) * p_u(b); "
            "p_u(b) = clip((v_b - f)/(S_b - f), 0, 1). S from the 500-target study on "
            "OSM-confirmed installations (results/glint_validation_pakistan/), f from "
            "69 Lahore no-PV controls, v from a stratified glint sample of unmapped "
            "candidates (scripts/glint_candidate_precision.py). interim-mapped-only "
            "means p_u=0 everywhere: an honest lower bound."
        ),
    }


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
