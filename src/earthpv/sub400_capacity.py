"""Sub-400 m2 capacity: fraction head + roofclf, density-stratified, kept OUT of `density.py`.

This is a deliberately separate, experimental product -- NOT the segmentation-based
atlas (`density.py`), and NOT merged into it. Two things forced that separation:

- Promoting the fraction head as `density.py`'s default expected-area instrument
  (2026-07-30) broke `earthpv check-density` when forced through the current candidate
  population (a disproportionate 46% collapse in roof-intersected candidate area vs.
  29% overall -- a `density.py`/`postprocess.py` aggregation issue, not something this
  module can fix). The segmentation-based atlas was restored and stays the default.
- roofclf's national capacity fold-in was separately rejected (see `roofclf_capacity.py`):
  a flat LOQO precision (0.50, measured at ~10.8% PV prevalence across 9 quadrats) gives
  18-37 GWp nationally, 3.5-8x the country's entire segmentation-based total, because PPV
  at a fixed threshold falls as true prevalence falls and the calibration quadrats are not
  representative of national prevalence.

The second failure is exactly what this module measures and partially corrects. Per-quadrat
precision at the deployment threshold is NOT flat -- it ranges 0.30-0.81 across the 8
quadrats (see `select_calibrated_quadrats`), and it is not simply "higher density is
better": quadrats where roofclf's raw predicted rate roughly matches the true rate
(rate_ratio within 2x either direction) sit in a *middle* density band (12-19% base rate),
with sparser quadrats (<10%) overestimating 2x+ and the one much-denser residential quadrat
(lahore, 30%) underestimating instead. Restricting to that middle band lifts pooled
precision from 0.499 (all 8) to 0.549 (the 3-quadrat band) at comparable recall -- a real,
measured improvement, not a guess -- but it is still an extrapolation from three quadrats to
81M national buildings, not a national measurement. Report it as such.

No reliable *national* proxy for "which cells resemble the calibrated density band" was
found to exist: tried and rejected here (see `docs/issues/` write-up) are (a) existing
segmentation-detected candidate density per cell -- anti-correlated with true small-PV base
rate, since large-PV (industrial) and small-PV (residential) adoption are different
populations, and (b) roofclf's own raw predicted rate per cell -- does not separate
calibrated from miscalibrated quadrats either (multan/sundar's predicted rate sits inside the
"good" band despite 2x+ true miscalibration).

**Measured 2026-07-30: the precision correction alone does not fix national deployment.**
Applying the density-regime precision (0.5495) to the SAME unrestricted 2,276,331
incrementally-flagged buildings used by the rejected flat-0.50 attempt gives 40,879 MWp --
*worse* than the original 37,197 MWp, because 0.5495 > 0.5. The precision fix and the
volume problem are separate failures; fixing one does not touch the other. The volume
problem needs restricting WHICH buildings count, which needs a national proxy -- and per
the paragraph above, none was found to exist. The only defensible move left is the
building-density domain restriction already used for roofclf's feature space (rejected on
its own in `docs/issues/roofclf-national-deployment-and-temporal-features.md` at flat 0.50
precision: 11,817 MWp, still implausible, plus a 13.4%-of-buildings/49%-of-area confound
where "incremental" buildings were already >=400 m2, i.e. not sub-400 at all). Combining
all three corrections -- domain restriction (93 cells matching the 8 quadrats'
737-4750 bldg/km2 range) + the >=400 m2 contamination filter + the density-regime precision
(0.5495 instead of 0.50) -- gives **6,628 MWp**, the same order of magnitude as the
country's entire existing segmentation-based total (5,078 MWp). That is `domain_restricted_
capacity` below. It is a real result, but it describes only those 93 cells (2.1% of
national cells, 19.1% of national buildings) -- extrapolating it to the other 97.9% of the
country (naive rate x 1/0.021 ~ 315 GWp) is exactly the failure mode this whole module
exists to avoid, and must not be done.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Symmetric log-scale band: a quadrat is "reasonably calibrated" if roofclf's raw
# predicted rate is within 2x of the true (labelled) rate in either direction. Chosen
# because it is a direct measure of calibration quality (not a proxy like base_rate
# itself), computed once from data, not tuned to hit a target number.
DEFAULT_RATIO_LO = 0.5
DEFAULT_RATIO_HI = 2.0
# mardan is excluded on its own documented grounds (worst fold, AUC 0.743, a distinct
# and already-diagnosed problem unrelated to density -- see CLAUDE.md); it also fails
# the ratio band on its own (0.312), so this is belt-and-suspenders, not load-bearing.
DEFAULT_EXCLUDE = ("mardan",)


def select_calibrated_quadrats(
    folds_path: Path,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE,
) -> tuple[list[str], pd.DataFrame]:
    """Quadrats whose roofclf rate_ratio (predicted/true adoption rate) falls in
    [ratio_lo, ratio_hi] -- i.e. where the classifier's raw predicted rate is not wildly
    off from ground truth. Returns `(quadrat_names, folds_subset_df)` for logging/audit.
    """
    folds = pd.read_csv(folds_path).set_index("quadrat")
    folds = folds[~folds.index.isin(exclude)]
    sel = folds[(folds.rate_ratio >= ratio_lo) & (folds.rate_ratio <= ratio_hi)]
    if sel.empty:
        raise ValueError(
            f"No quadrat has rate_ratio in [{ratio_lo}, {ratio_hi}] -- "
            f"loosen the band or check {folds_path}"
        )
    log.info(
        "Density-calibrated quadrats (rate_ratio in [%.2f, %.2f]): %s (base_rate %.3f-%.3f)",
        ratio_lo, ratio_hi, sel.index.tolist(), sel.base_rate.min(), sel.base_rate.max(),
    )
    excluded_lo = folds[folds.rate_ratio < ratio_lo]
    excluded_hi = folds[folds.rate_ratio > ratio_hi]
    if not excluded_lo.empty:
        log.info(
            "Excluded (underestimate, ratio<%.2f): %s -- roofclf UNDER-predicts here, so "
            "including them would only make the correction more conservative, but they "
            "are dropped for symmetry with the overestimate side, not for any other reason",
            ratio_lo, excluded_lo.index.tolist(),
        )
    if not excluded_hi.empty:
        log.info(
            "Excluded (overestimate, ratio>%.2f): %s -- these are the low-true-density "
            "quadrats (base_rate %.3f-%.3f) that drove the original flat-precision "
            "national number to 18-37 GWp; excluding them is the whole point of this module",
            ratio_hi, excluded_hi.index.tolist(),
            excluded_hi.base_rate.min(), excluded_hi.base_rate.max(),
        )
    return sel.index.tolist(), sel


def density_regime_precision(
    buildings_path: Path, quadrats: list[str], threshold: float
) -> dict:
    """Pooled precision/recall of roofclf's leave-one-quadrat-out OOF predictions
    (`p_oof`/`has_pv` in `roofclf.evaluate()`'s per-building table), restricted to
    `quadrats`, at `threshold`. This is a real held-out measurement (each quadrat's
    `p_oof` was produced by a model that never saw that quadrat), not a training-set
    fit -- the same LOQO discipline `roofclf.py` uses everywhere else.
    """
    df = gpd.read_parquet(buildings_path)
    sub = df[df.quadrat.isin(quadrats)]
    if sub.empty:
        raise ValueError(f"None of {quadrats} found in {buildings_path}")
    pred = sub.p_oof >= threshold
    tp = int((pred & (sub.has_pv == 1)).sum())
    fp = int((pred & (sub.has_pv == 0)).sum())
    fn = int((~pred & (sub.has_pv == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    result = {
        "quadrats": quadrats,
        "threshold": threshold,
        "n": int(len(sub)),
        "n_flagged": int(pred.sum()),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
    }
    log.info("Density-regime precision: %s", result)
    return result


def parcel_label_composition(
    buildings_path: Path, quadrats: list[str], threshold: float
) -> dict | None:
    """What the parcel label actually added, on the population the coverage ratio is fit on.

    Returns None for a roof-only calibration table (no `pv_area_yard_m2` column), so every
    caller can attach this to its summary unconditionally.

    This exists because the two things `roofclf.parcel_pv_area` picks up mean different
    things downstream and the atlas reports them under one heading. Measured on the 27
    quadrats, the OSM `placement=ground` term -- genuine small ground-mounted arrays, the
    thing the widening was built for -- is the minority of it; most is mapped rooftop PV
    whose polygon extends past an imagery-derived VIDA outline. Both are real PV on the
    parcel and both belong in `pv_area_true_m2` (the overhang term is self-consistent: an
    undersized footprint shrinks the calibration denominator and the national flagged roof
    area by the same bias, so the ratio transfers), but only the ground term makes the
    "rooftop" capacity line partly ground-mount. `yard_ground_share_of_flagged` is the
    number to quote for that, and it is what keeps the atlas's placement split honest.
    """
    df = gpd.read_parquet(buildings_path)
    if "pv_area_yard_m2" not in df.columns:
        return None
    sub = df[df.quadrat.isin(quadrats)]
    flagged = sub[sub.p_oof.to_numpy(float) >= threshold]
    total = float(flagged.pv_area_true_m2.sum())
    ground = float(flagged.pv_area_yard_ground_m2.sum())
    overhang = float(flagged.pv_area_yard_overhang_m2.sum())
    return {
        "flagged_pv_area_m2": round(total, 1),
        "roof_m2": round(float(flagged.pv_area_roof_m2.sum()), 1),
        "yard_ground_tagged_m2": round(ground, 1),
        "yard_rooftop_overhang_m2": round(overhang, 1),
        "yard_ground_share_of_flagged": round(ground / total, 4) if total else 0.0,
        "yard_total_share_of_flagged": round((ground + overhang) / total, 4) if total else 0.0,
    }


# Quantile bin count / minimum flagged buildings per bin for `coverage_ratio_by_size` --
# see that function's docstring for why quantile (equal-count) bins, not equal-width ones.
DEFAULT_COVERAGE_N_SIZE_BINS = 10
DEFAULT_COVERAGE_MIN_BIN_N = 25


def coverage_ratio_by_size(
    buildings_path: Path | None,
    quadrats: list[str],
    threshold: float,
    sppi_min_precision: float | None = None,
    n_bins: int = DEFAULT_COVERAGE_N_SIZE_BINS,
    min_bin_n: int = DEFAULT_COVERAGE_MIN_BIN_N,
    df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Measured (true mapped PV area / roof area) on the buildings roofclf (optionally AND
    SPPI) flags in `quadrats`, binned by each flagged building's OWN `roof_area_m2` -- the
    size-dependent replacement for a single flat multiplier.

    A flat ratio (this function's predecessor, `density_regime_coverage_ratio`, measured
    2026-08-06) already improved on precision-alone by netting out "how much of a flagged
    roof is actually covered in panels" -- but it then applied one number to every building
    regardless of size. Measured directly against the quadrats' own `pv_area_true_m2` (all
    13 calibrated quadrats, deployment threshold, 10 equal-count size bins): coverage rises
    from ~0.20 in the smallest decile of roofclf-flagged roofs to ~0.26 in the largest, and
    the roofclf-AND-SPPI population shows a much sharper rise, ~0.21 to ~0.45 across the same
    size range (measured 2026-08-09). Bigger flagged roofs carry proportionally MORE panel
    area, not just more roof area -- a flat ratio was over-charging the smallest flagged
    buildings and under-charging the largest ones by construction. This measures the
    relationship directly from the calibration labels, in bins, instead of assuming it away.

    Bin edges are quantiles of the FLAGGED population's own `roof_area_m2` (equal-count, not
    equal-width) so every bin carries comparable statistical weight no matter how skewed the
    size distribution is. A bin with fewer than `min_bin_n` flagged buildings (noisy) falls
    back to the pooled ratio across the whole flagged population rather than reporting an
    unstable per-bin value. The calibration spans whatever size range `quadrats` covers --
    sub-400 m2 and >= 400 m2 buildings alike, in ONE shared fit: both
    `domain_restricted_capacity`/`domain_restricted_and_gate_capacity` here and
    `roofclf_ge400_capacity.domain_restricted_ge400_roof_capacity` call this same function
    and each only ever looks up its own building population's own bins via
    `apply_size_coverage_ratio` -- there is no separate >= 400 m2 refit, since the ratio is
    continuous across that boundary (no discontinuity was measured there).

    `sppi_min_precision`, when given, additionally requires SPPI above the pooled
    precision-targeted threshold (`sppi.pooled_precision_threshold`) -- the AND-gate's own
    selection -- so this can be called with the same predicate
    `domain_restricted_and_gate_capacity` uses instead of roofclf alone.

    Returns one row per bin: `bin_lo`, `bin_hi`, `n_flagged`, `roof_area_m2` (summed),
    `true_pv_area_m2` (summed), `coverage_ratio`. Feed straight to
    `apply_size_coverage_ratio`.

    `df` skips the parquet read and fits the table from an already-loaded frame instead
    (`buildings_path` may then be None). Only `coverage_ratio_bootstrap_factors` uses it,
    to refit this table a few hundred times over resampled quadrat sets without paying
    for a few hundred `read_parquet` calls; every production caller still passes a path.
    """
    df = gpd.read_parquet(buildings_path) if df is None else df
    sub = df[df.quadrat.isin(quadrats)]
    if sub.empty:
        raise ValueError(f"None of {quadrats} found in {buildings_path}")
    pred = sub.p_oof.to_numpy(float) >= threshold
    if sppi_min_precision is not None:
        from earthpv.sppi import add_sppi, pooled_precision_threshold

        if "sppi" not in df.columns:
            df = add_sppi(df)
            sub = df[df.quadrat.isin(quadrats)]
        sppi_thresh = pooled_precision_threshold(df, quadrats, min_precision=sppi_min_precision)
        pred = pred & (sub.sppi.to_numpy(float) >= sppi_thresh)
    flagged = sub[pred]

    roof = flagged.roof_area_m2.to_numpy(float)
    true = flagged.pv_area_true_m2.to_numpy(float)
    if len(roof) == 0:
        log.warning(
            "coverage_ratio_by_size: no buildings flagged (quadrats=%s, threshold=%.4f, "
            "sppi_min_precision=%s) -- returning coverage_ratio=0.0", quadrats, threshold,
            sppi_min_precision,
        )
        return pd.DataFrame([{
            "bin_lo": -np.inf, "bin_hi": np.inf, "n_flagged": 0,
            "roof_area_m2": 0.0, "true_pv_area_m2": 0.0, "coverage_ratio": 0.0,
        }])
    overall_ratio = float(true.sum() / roof.sum())

    edges = np.unique(np.quantile(roof, np.linspace(0.0, 1.0, n_bins + 1)))
    if len(edges) < 3:
        edges = np.array([roof.min(), roof.max()])
    edges[0], edges[-1] = -np.inf, np.inf
    bin_idx = np.clip(np.searchsorted(edges, roof, side="right") - 1, 0, len(edges) - 2)

    rows = []
    for i in range(len(edges) - 1):
        m = bin_idx == i
        n = int(m.sum())
        roof_sum = float(roof[m].sum())
        true_sum = float(true[m].sum())
        ratio = true_sum / roof_sum if roof_sum and n >= min_bin_n else overall_ratio
        rows.append({
            "bin_lo": float(edges[i]), "bin_hi": float(edges[i + 1]), "n_flagged": n,
            "roof_area_m2": round(roof_sum, 1), "true_pv_area_m2": round(true_sum, 1),
            "coverage_ratio": round(ratio, 4),
        })
    table = pd.DataFrame(rows)
    log.info(
        "Coverage ratio by size (%d bins, %d quadrats, sppi_min_precision=%s, overall=%.4f):\n%s",
        len(table), len(quadrats), sppi_min_precision, overall_ratio, table.to_string(index=False),
    )
    return table


def _lookup_by_size(roof_area_m2: np.ndarray, bin_table: pd.DataFrame, column: str) -> np.ndarray:
    """Per-building value from a `bin_lo`/`bin_hi` size table, by the building's own roof
    area. Shared by `apply_size_coverage_ratio` and `apply_size_area_recall` so the two
    size-binned corrections cannot drift apart in how they resolve a bin edge."""
    edges = np.concatenate([[bin_table.bin_lo.iloc[0]], bin_table.bin_hi.to_numpy()])
    idx = np.clip(np.searchsorted(edges, roof_area_m2, side="right") - 1, 0, len(bin_table) - 1)
    return bin_table[column].to_numpy()[idx]


def apply_size_coverage_ratio(roof_area_m2: np.ndarray, bin_table: pd.DataFrame) -> np.ndarray:
    """Per-building coverage ratio looked up from `coverage_ratio_by_size`'s bin table by
    each building's own `roof_area_m2` -- the size-dependent replacement for multiplying
    every building by one flat ratio regardless of how big its roof is."""
    return _lookup_by_size(roof_area_m2, bin_table, "coverage_ratio")


# Number of building-density strata `coverage_ratio_by_size_and_density` splits the
# calibrated quadrats into. 2 (a median split) is deliberate, not a default left
# unconsidered: with only 13 ratio-selected quadrats, 3+ strata leaves 4 or fewer
# quadrats per band -- too thin to trust a band-specific fit over the pooled one. 2 is
# the coarsest split that still says something a single pooled number can't.
DEFAULT_N_DENSITY_STRATA = 2


def _density_band_edges(quadrat_density: pd.Series, n_bands: int) -> np.ndarray:
    """Quantile edges (equal-count bands OF QUADRATS, not of buildings) over
    `quadrat_density`'s own values, outer edges forced to +-inf. Factored out so
    `coverage_ratio_by_size_and_density` (fits a per-band coverage-ratio table) and
    `size_floor_by_density_band` (applies a per-band inclusion floor) agree on what
    "dense" and "sparse" mean -- both stratify the SAME calibration quadrats the same way.
    """
    edges = np.unique(np.quantile(quadrat_density.to_numpy(float), np.linspace(0, 1, n_bands + 1)))
    if len(edges) < 3:
        edges = np.array([quadrat_density.min(), quadrat_density.max()])
    edges[0], edges[-1] = -np.inf, np.inf
    return edges


def size_floor_by_density_band(
    roof_area_m2: np.ndarray, cell_density_km2: np.ndarray, band_edges: np.ndarray, floors_m2: list[float],
) -> np.ndarray:
    """Boolean KEEP mask for an OPTIONAL, prototype density-conditional size floor:
    True where a building's own `roof_area_m2` clears the floor for ITS CELL's density
    band. `band_edges`/`floors_m2` are aligned index-for-index and use the SAME band
    definition as `apply_stratified_coverage_ratio` -- a cell's own density picks the
    band, not the building's roof size, so a national cell is treated consistently by
    both the coverage-ratio reweighting and this inclusion filter.

    Measured 2026-08-10 on the 13-quadrat calibration set
    (`scripts/roofclf_size_density_signal.py`): a size floor buys roughly 2x more
    precision per point of recall spent in the denser calibration band than in the
    sparser one (e.g. at a 100 m2 floor: high-density +2.6pp precision / -5.7pp recall
    vs. low-density +1.7pp / -8.6pp) -- so if a floor is used at all, it should bite
    mainly in dense cells, not sparse ones, the opposite of a flat floor's implicit
    assumption. `floors_m2` of all zeros (the default when this is left unset -- see
    `domain_restricted_capacity`) is a no-op: every building clears a 0 m2 floor, so
    passing nothing changes no existing production number. This is a prototype gated on
    only 2 density bands / 13 quadrats -- treat any nonzero floor as a measured lead to
    evaluate, not a settled calibration.
    """
    if len(floors_m2) != len(band_edges) - 1:
        raise ValueError(
            f"size_floor_by_density_band: {len(floors_m2)} floors for "
            f"{len(band_edges) - 1} density bands"
        )
    band_idx = np.clip(np.searchsorted(band_edges, cell_density_km2, side="right") - 1, 0, len(floors_m2) - 1)
    floor_per_building = np.asarray(floors_m2, dtype=float)[band_idx]
    return roof_area_m2 >= floor_per_building


def quadrat_building_density_km2(quadrat_profile_path: Path, quadrats: list[str]) -> pd.Series:
    """Each quadrat's own building density (buildings/km2), from
    `results/calibration_quadrats.csv`'s `n_buildings`/`area_km2` -- the same quantity
    `national_cell_domain` uses for national cells, computed here per calibration quadrat
    so `coverage_ratio_by_size_and_density` can stratify by it. Returns a `label -> density`
    Series indexed by quadrat name, restricted to `quadrats`.
    """
    profile = pd.read_csv(quadrat_profile_path)
    profile = profile[profile.label.isin(quadrats)].set_index("label")
    density = profile.n_buildings / profile.area_km2
    missing = set(quadrats) - set(density.index)
    if missing:
        raise ValueError(f"{quadrat_profile_path} has no row for quadrats {sorted(missing)}")
    return density.loc[quadrats]


def coverage_ratio_by_size_and_density(
    buildings_path: Path | None,
    quadrats: list[str],
    threshold: float,
    quadrat_density: pd.Series,
    sppi_min_precision: float | None = None,
    n_density_bands: int = DEFAULT_N_DENSITY_STRATA,
    n_size_bins: int = DEFAULT_COVERAGE_N_SIZE_BINS,
    min_bin_n: int = DEFAULT_COVERAGE_MIN_BIN_N,
    df: pd.DataFrame | None = None,
) -> dict:
    """`coverage_ratio_by_size`, fit independently within each of `n_density_bands`
    building-density strata instead of once over all calibrated quadrats pooled together --
    the per-stratum correction called for in place of a single flat threshold/ratio applied
    everywhere in the domain regardless of a cell's own settlement density.

    Motivation: `rate_ratio` (roofclf's predicted/true adoption rate) is close to flat
    across quadrats while true `base_rate` spans 3-30% (see CLAUDE.md's "Density and
    detection quality" section) -- i.e. the SAME threshold and coverage ratio are already
    known to behave differently depending on local building density, even though every
    domain-restricted capacity function up to now applied one pooled fit uniformly across
    the whole 92-163-cell domain regardless of which density band a given cell actually
    sits in. This stratifies `coverage_ratio_by_size`'s own size-binned fit by density band
    so a dense urban cell and a sparser peri-urban cell (both still inside the calibrated
    domain) get their own band's measured ratio rather than the same pooled one.

    `quadrat_density` is `quadrat_building_density_km2`'s output (label -> bldg/km2),
    restricted to and aligned with `quadrats`. Density band edges are quantiles of the
    QUADRATS' own density values (equal-count bands of quadrats, not of buildings), since
    density here is a per-quadrat/per-cell covariate, not a per-building one -- a national
    cell is assigned to a band by its OWN density value at deployment time
    (`apply_stratified_coverage_ratio`), not by which buildings happen to be in it.

    A band whose quadrats' flagged population is too sparse to trust its own fit (fewer
    total flagged buildings across ALL its size bins than `min_bin_n`) falls back to the
    fully pooled (`coverage_ratio_by_size`, all quadrats) table -- the same graceful
    degradation `coverage_ratio_by_size` itself already applies per size bin, one level up.

    Returns `{"band_edges": [...], "bands": [{"density_lo", "density_hi", "quadrats",
    "n_flagged", "coverage_table": <records>}, ...], "pooled_fallback": <records>}`. Feed
    straight to `apply_stratified_coverage_ratio`.
    """
    return _stratify_by_density(
        coverage_ratio_by_size, "coverage_table", buildings_path, quadrats, threshold,
        quadrat_density, sppi_min_precision, n_density_bands, n_size_bins, min_bin_n, df,
        n_col="n_flagged",
    )


def _stratify_by_density(
    fit, table_key: str, buildings_path: Path | None, quadrats: list[str], threshold: float,
    quadrat_density: pd.Series, sppi_min_precision: float | None, n_density_bands: int,
    n_size_bins: int, min_bin_n: int, df: pd.DataFrame | None, n_col: str,
) -> dict:
    """Fit `fit` (a size-binned table function) once per building-density band of
    `quadrats`, with a pooled fallback for any band whose own calibration population is
    thinner than `min_bin_n`. Shared by `coverage_ratio_by_size_and_density` and
    `area_recall_by_size_and_density` so the two corrections a building is multiplied and
    divided by are stratified identically -- if they used different band edges, a national
    cell could sit in the dense band for one and the sparse band for the other.
    """
    quadrat_density = quadrat_density.loc[quadrats]
    edges = _density_band_edges(quadrat_density, n_density_bands)

    pooled_table = fit(
        buildings_path, quadrats, threshold, sppi_min_precision=sppi_min_precision,
        n_bins=n_size_bins, min_bin_n=min_bin_n, df=df,
    )
    band_idx = np.clip(
        np.searchsorted(edges, quadrat_density.to_numpy(float), side="right") - 1, 0, len(edges) - 2
    )
    bands = []
    for i in range(len(edges) - 1):
        band_quadrats = quadrat_density.index[band_idx == i].tolist()
        if not band_quadrats:
            continue
        table = fit(
            buildings_path, band_quadrats, threshold, sppi_min_precision=sppi_min_precision,
            n_bins=n_size_bins, min_bin_n=min_bin_n, df=df,
        )
        n_band = int(table[n_col].sum())
        used_pooled_fallback = n_band < min_bin_n
        if used_pooled_fallback:
            log.warning(
                "Density band %d (%s, density %.1f-%.1f/km2) has only %d calibration rows "
                "(%s) -- falling back to the pooled %s fit for this band",
                i, band_quadrats, edges[i], edges[i + 1], n_band, n_col, table_key,
            )
            table = pooled_table
        bands.append({
            "density_lo": float(edges[i]), "density_hi": float(edges[i + 1]),
            "quadrats": band_quadrats, "n_flagged": n_band,
            "used_pooled_fallback": used_pooled_fallback,
            table_key: table.to_dict("records"),
        })
    result = {
        "band_edges": [float(e) for e in edges],
        "bands": bands,
        "pooled_fallback": pooled_table.to_dict("records"),
    }
    log.info(
        "%s by size and density (%d bands from %d quadrats): %s",
        table_key, len(bands), len(quadrats),
        [(b["density_lo"], b["density_hi"], b["quadrats"], b["used_pooled_fallback"]) for b in bands],
    )
    return result


def apply_stratified_coverage_ratio(
    roof_area_m2: np.ndarray, cell_density_km2: np.ndarray, stratified: dict
) -> np.ndarray:
    """Per-building coverage ratio from `coverage_ratio_by_size_and_density`'s output: each
    building's CELL density (not the building's own roof size) picks the density band, then
    that band's size-binned table (`apply_size_coverage_ratio`) picks the ratio by roof size
    -- the two covariates stack rather than substitute for each other.
    """
    return _apply_stratified(roof_area_m2, cell_density_km2, stratified, "coverage_table", "coverage_ratio")


def _apply_stratified(
    roof_area_m2: np.ndarray, cell_density_km2: np.ndarray, stratified: dict,
    table_key: str, column: str,
) -> np.ndarray:
    """Shared band-then-size lookup behind `apply_stratified_coverage_ratio` and
    `apply_stratified_area_recall`: a cell's own density picks the band, the building's own
    roof size picks the bin within it."""
    edges = np.array(stratified["band_edges"])
    band_idx = np.clip(np.searchsorted(edges, cell_density_km2, side="right") - 1, 0, len(stratified["bands"]) - 1)
    out = np.empty(len(roof_area_m2), dtype=float)
    for i, band in enumerate(stratified["bands"]):
        m = band_idx == i
        if not m.any():
            continue
        out[m] = _lookup_by_size(roof_area_m2[m], pd.DataFrame(band[table_key]), column)
    return out


# --------------------------------------------------------------------------------------
# roofclf's own missed installations: the recall half of the correction (2026-08-15)
# --------------------------------------------------------------------------------------
# A bin measured below this cannot pin its own denominator down, and 1/recall there would
# inflate a handful of flagged buildings into an unbounded national total. Mirrors
# `capacity_calibration.DEFAULT_RECALL_FLOOR`'s role for segmentation (there 0.05, a 20x
# cap; here 0.10, a 10x cap, because roofclf's measured area recall is an order of
# magnitude higher -- the lowest decile on the current 17-quadrat set is 0.268, so this
# floor does not bind anywhere today and exists only to bound a future degenerate refit).
AREA_RECALL_FLOOR = 0.10


def area_recall_by_size(
    buildings_path: Path | None,
    quadrats: list[str],
    threshold: float,
    sppi_min_precision: float | None = None,
    n_bins: int = DEFAULT_COVERAGE_N_SIZE_BINS,
    min_bin_n: int = DEFAULT_COVERAGE_MIN_BIN_N,
    df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Share of the quadrats' true mapped PV **area** that sits on a building roofclf
    actually flags, binned by roof size -- the denominator correction the coverage ratio
    alone cannot make.

    `coverage_ratio_by_size` answers "of the roof area we flagged, how much is panel?".
    Multiplying a national flagged population by it therefore estimates *the PV on roofs
    roofclf flagged*, and silently books zero for every installation on a roof it missed.
    Segmentation has never been read that way: `capacity_calibration`'s recall table and
    `density.py`'s `est_mwp_rc` divide each surviving candidate by the measured recall of
    its size class precisely so the estimate describes the whole population rather than the
    detected part. This is the same Horvitz-Thompson correction for the other instrument,
    fit on the same quadrats, at the same time, so the two halves of the atlas are built on
    one estimator rather than two.

    Measured on the 17 rate_ratio-trusted quadrats at the 2026-08-13 refit's deployment
    threshold: pooled area recall is 0.808 for sub-400 m2 buildings and 0.982 for
    >= 400 m2 ones, and it rises monotonically with roof size across the sub-400 m2 range
    (0.29 in the smallest decile of PV-carrying roofs to 0.91 in the largest) -- so, exactly
    like the coverage ratio, a single pooled number would over-correct the largest roofs and
    badly under-correct the smallest.

    **Area, not count.** A count recall (roofclf's own `deployment_threshold_stats`, 0.634)
    answers "how many PV buildings did we flag", which is not the quantity a capacity total
    needs: missing one 300 m2 array and missing one 20 m2 array cost the same under a count
    and differ 15-fold in MWp. The numerator and denominator here are both `pv_area_true_m2`.

    **One assumption, with a known sign.** The national population this is applied to has
    already been deduped against segmentation candidates and OSM features, while recall is
    measured over a quadrat's whole building population, deduped or not (the calibration
    table carries no proximity flag to condition on). Dividing the former by the latter
    assumes roofclf's misses split between "already counted by another component" and
    "incremental" in the same proportion its hits do. Where that fails it fails
    conservatively: a large, obvious array is both the kind roofclf flags and the kind
    segmentation or an OSM mapper already found, so flagged PV is if anything
    over-represented among the already-counted, which makes the incremental share of MISSED
    PV larger than assumed and this correction an underestimate.

    **This correction is conservative by construction.** Rule 1 certifies completeness only
    as of the mapping imagery's own epoch (`docs/calibration-mapping-protocol.md`), so an
    array present in the composite but installed after that imagery is missing from
    `pv_area_true_m2` on flagged and unflagged buildings alike. On a flagged building it
    leaves both numerator and denominator; on an unflagged one it leaves only the
    denominator -- which biases measured recall UP and this correction DOWN. It is a floor
    on the correction, not a point estimate of it.

    Bins are quantiles of the PV-CARRYING population's roof area (equal-count in
    installations, not in buildings), since a bin's recall is measured from the
    installations in it -- a bin with fewer than `min_bin_n` PV-carrying buildings falls
    back to the pooled recall across all of `quadrats`, the same degradation
    `coverage_ratio_by_size` applies. Returns `bin_lo`, `bin_hi`, `n_pv_buildings`,
    `n_pv_flagged`, `true_pv_area_m2`, `flagged_pv_area_m2`, `area_recall`. `df` is the
    same bootstrap escape hatch `coverage_ratio_by_size` documents.
    """
    df = gpd.read_parquet(buildings_path) if df is None else df
    sub = df[df.quadrat.isin(quadrats)]
    if sub.empty:
        raise ValueError(f"None of {quadrats} found in {buildings_path}")
    pred = sub.p_oof.to_numpy(float) >= threshold
    if sppi_min_precision is not None:
        from earthpv.sppi import add_sppi, pooled_precision_threshold

        if "sppi" not in df.columns:
            df = add_sppi(df)
            sub = df[df.quadrat.isin(quadrats)]
        sppi_thresh = pooled_precision_threshold(df, quadrats, min_precision=sppi_min_precision)
        pred = pred & (sub.sppi.to_numpy(float) >= sppi_thresh)

    true = sub.pv_area_true_m2.to_numpy(float)
    roof = sub.roof_area_m2.to_numpy(float)
    has_pv = true > 0
    if not has_pv.any() or true.sum() <= 0:
        log.warning(
            "area_recall_by_size: no mapped PV in quadrats=%s -- returning area_recall=1.0 "
            "(no correction), since a recall this population cannot measure must not be "
            "invented", quadrats,
        )
        return pd.DataFrame([{
            "bin_lo": -np.inf, "bin_hi": np.inf, "n_pv_buildings": 0, "n_pv_flagged": 0,
            "true_pv_area_m2": 0.0, "flagged_pv_area_m2": 0.0, "area_recall": 1.0,
        }])
    overall_recall = float(true[pred].sum() / true.sum())

    edges = np.unique(np.quantile(roof[has_pv], np.linspace(0.0, 1.0, n_bins + 1)))
    if len(edges) < 3:
        edges = np.array([roof[has_pv].min(), roof[has_pv].max()])
    edges[0], edges[-1] = -np.inf, np.inf
    bin_idx = np.clip(np.searchsorted(edges, roof, side="right") - 1, 0, len(edges) - 2)

    rows = []
    for i in range(len(edges) - 1):
        m = bin_idx == i
        n_pv = int((m & has_pv).sum())
        true_sum = float(true[m].sum())
        flagged_sum = float(true[m & pred].sum())
        recall = flagged_sum / true_sum if true_sum > 0 and n_pv >= min_bin_n else overall_recall
        rows.append({
            "bin_lo": float(edges[i]), "bin_hi": float(edges[i + 1]),
            "n_pv_buildings": n_pv, "n_pv_flagged": int((m & has_pv & pred).sum()),
            "true_pv_area_m2": round(true_sum, 1), "flagged_pv_area_m2": round(flagged_sum, 1),
            "area_recall": round(max(recall, AREA_RECALL_FLOOR), 4),
        })
    table = pd.DataFrame(rows)
    log.info(
        "Area recall by size (%d bins, %d quadrats, sppi_min_precision=%s, overall=%.4f):\n%s",
        len(table), len(quadrats), sppi_min_precision, overall_recall, table.to_string(index=False),
    )
    return table


def apply_size_area_recall(roof_area_m2: np.ndarray, bin_table: pd.DataFrame) -> np.ndarray:
    """Per-building area recall from `area_recall_by_size`'s bin table, by roof size."""
    return _lookup_by_size(roof_area_m2, bin_table, "area_recall")


def area_recall_by_size_and_density(
    buildings_path: Path | None,
    quadrats: list[str],
    threshold: float,
    quadrat_density: pd.Series,
    sppi_min_precision: float | None = None,
    n_density_bands: int = DEFAULT_N_DENSITY_STRATA,
    n_size_bins: int = DEFAULT_COVERAGE_N_SIZE_BINS,
    min_bin_n: int = DEFAULT_COVERAGE_MIN_BIN_N,
    df: pd.DataFrame | None = None,
) -> dict:
    """`area_recall_by_size`, stratified by building density exactly as
    `coverage_ratio_by_size_and_density` stratifies the coverage ratio -- same band edges
    (`_density_band_edges` over the same quadrats), same equal-count-of-quadrats logic, same
    pooled fallback for a band too thin to fit on its own. Both corrections therefore see
    the same definition of "dense" and "sparse", which matters because they are multiplied
    together per building.

    Measured spread across the 17 trusted quadrats is wide (pooled sub-400 m2 area recall
    ranges 0.26 in Malok to 0.94 in Islamabad North), and that variability is priced by
    resampling quadrats in `coverage_ratio_bootstrap_factors`, not swept into a point value.

    Returns the same shape `coverage_ratio_by_size_and_density` does, with `recall_table`
    in place of `coverage_table`. Feed to `apply_stratified_area_recall`.
    """
    return _stratify_by_density(
        area_recall_by_size, "recall_table", buildings_path, quadrats, threshold,
        quadrat_density, sppi_min_precision, n_density_bands, n_size_bins, min_bin_n, df,
        n_col="n_pv_buildings",
    )


def apply_stratified_area_recall(
    roof_area_m2: np.ndarray, cell_density_km2: np.ndarray, stratified: dict
) -> np.ndarray:
    """Per-building area recall from `area_recall_by_size_and_density`'s output. Divide a
    building's coverage-ratio-weighted capacity by this to estimate the whole population of
    its size/density stratum rather than only the flagged part of it."""
    return _apply_stratified(roof_area_m2, cell_density_km2, stratified, "recall_table", "area_recall")


# Bootstrap replicates behind `coverage_ratio_bootstrap_factors`. 200 is enough for a
# stable 5/95 interval (the 5th/95th order statistics of 200 draws) and costs roughly
# 30-60 s per capacity function, which is noise next to the per-cell parquet reads those
# functions already do.
DEFAULT_COVERAGE_N_BOOT = 200

# Fixed, and deliberately SHARED by every capacity function that calls this. Replicate b
# must mean "the same resampled quadrat set" in `domain_restricted_capacity`,
# `domain_restricted_and_gate_capacity`, `out_of_domain_and_gate_capacity` and
# `roofclf_ge400_capacity.domain_restricted_ge400_roof_capacity` alike -- all four fit
# their coverage ratio on the SAME quadrats, so their errors are strongly positively
# correlated, and `atlas.build_evidence_atlas` adds their draws replicate-by-replicate to
# keep that correlation instead of pretending four estimates built from one calibration
# set are independent (which would understate the Best tier's interval). Changing this
# constant silently breaks that alignment for any summary written before the change.
COVERAGE_BOOTSTRAP_SEED = 20260811


def coverage_ratio_bootstrap_factors(
    buildings_path: Path,
    quadrats: list[str],
    threshold: float,
    quadrat_density: pd.Series,
    stratified: dict,
    roof_area_m2: np.ndarray,
    cell_density_km2: np.ndarray,
    sppi_min_precision: float | None = None,
    n_density_bands: int = DEFAULT_N_DENSITY_STRATA,
    n_boot: int = DEFAULT_COVERAGE_N_BOOT,
    seed: int = COVERAGE_BOOTSTRAP_SEED,
    recall_stratified: dict | None = None,
) -> dict:
    """Dimensionless multiplicative uncertainty on a capacity total, from resampling the
    CALIBRATION QUADRATS behind its coverage-ratio fit.

    `recall_stratified`, when given (`area_recall_by_size_and_density`'s point fit), prices
    the recall correction in the SAME replicates rather than in a second bootstrap of its
    own: each replicate refits both tables on one resampled quadrat set and re-prices the
    target population with both, so the factor returned describes
    `coverage_ratio / area_recall` as a single quantity. That is the honest composition --
    the two are fit on the same quadrats from the same labels, so their errors are strongly
    dependent (a quadrat whose mapping is stale depresses the measured coverage ratio and
    inflates the measured recall at once), and multiplying two independently-bootstrapped
    factors would both mis-state the width and lose the sign of that dependence. It also
    means `atlas.build_evidence_atlas` needs no change: it keeps reading one
    `coverage_ratio_bootstrap` per component.

    **The resampling unit is the quadrat, not the building.** Buildings inside one quadrat
    share a mapper, a settlement pattern, a roof-material mix and one background-imagery
    epoch, so a building-level bootstrap would treat ~100k highly correlated rows as ~100k
    independent observations and report an interval far too narrow to be honest. The
    variation that has actually moved this project's published numbers has always been
    quadrat *composition*: adding one quadrat (Malok, 2026-08-11) moved the trusted set
    from 13 to 15 and every capacity component by 1-8% at once, and dropping Multan from
    that set moved the coverage ratio on its own. That is the sampling variability this
    function measures -- "if a different, equally plausible handful of quadrats had been
    mapped, how different would this total be?".

    Each replicate resamples `quadrats` with replacement, refits
    `coverage_ratio_by_size_and_density` on the resampled set (a quadrat drawn twice
    genuinely counts twice: its rows are duplicated under distinct synthetic labels rather
    than deduplicated by `isin`, which would silently turn the bootstrap into an
    m-out-of-n subsample), re-prices the SAME target population
    (`roof_area_m2`/`cell_density_km2`, passed in by the caller after all of its own
    filtering), and records the resulting total as a ratio to the point-estimate total.
    Returning a dimensionless factor rather than MWp is what lets `atlas.build_evidence_
    atlas` compose these without re-reading a single quadrat: the area->capacity constant
    cancels, so the factor is valid whatever kWp/m2 the caller applied.

    What this does NOT cover, and must not be read as covering: the quadrats are purposive,
    not a probability sample, so this is variability *within* the kind of place that has
    been mapped, not a design-based national margin of error. It says nothing about the
    out-of-domain extrapolation (no quadrat exists in that density range at all -- see
    `out_of_domain_and_gate_capacity`), nor about roofclf's own threshold-transfer bias,
    nor about whether the mapping imagery was contemporaneous with the composite.

    `stratified` is the point fit the caller already computed (reused rather than refit, so
    the returned factors are guaranteed to be relative to the total the caller published).
    Degenerate replicates -- a resample whose fit raises, e.g. one that draws a single
    quadrat with no flagged building at all -- are dropped and counted, not silently
    treated as a factor of 1.0.
    """
    empty = {
        "n_boot": 0, "n_boot_requested": int(n_boot), "n_degenerate_replicates": 0,
        "seed": int(seed), "resample_unit": "quadrat", "n_quadrats": len(set(quadrats)),
        "factors": [], "factor_ci90": None, "factor_mean": None,
    }
    roof_area_m2 = np.asarray(roof_area_m2, dtype=float)
    cell_density_km2 = np.asarray(cell_density_km2, dtype=float)
    if n_boot <= 0 or len(roof_area_m2) == 0:
        return empty

    def _priced(cov_fit: dict, rec_fit: dict | None) -> float:
        w = roof_area_m2 * apply_stratified_coverage_ratio(roof_area_m2, cell_density_km2, cov_fit)
        if rec_fit is not None:
            w = w / apply_stratified_area_recall(roof_area_m2, cell_density_km2, rec_fit)
        return float(w.sum())

    point_total = _priced(stratified, recall_stratified)
    if point_total <= 0:
        return empty

    df = gpd.read_parquet(buildings_path)
    if sppi_min_precision is not None and "sppi" not in df.columns:
        from earthpv.sppi import add_sppi

        df = add_sppi(df)
    # Drop geometry and everything the fit path does not read: the per-replicate concat
    # below copies these rows a few hundred times, and carrying polygons through that is
    # the difference between seconds and minutes.
    keep_cols = [
        c for c in ("quadrat", "roof_area_m2", "pv_area_true_m2", "p_oof", "has_pv", "sppi")
        if c in df.columns
    ]
    slim = pd.DataFrame(df[keep_cols])
    uniq = list(dict.fromkeys(quadrats))
    by_quadrat = {q: slim[slim.quadrat == q] for q in uniq}

    rng = np.random.default_rng(seed)
    factors: list[float] = []
    n_degenerate = 0
    prev_level = log.level
    # Each replicate logs its own fitted table at INFO (3 tables x n_boot = ~600 lines of
    # noise that says nothing a caller can act on); the point fit was already logged.
    log.setLevel(logging.WARNING)
    try:
        for _ in range(n_boot):
            pick = rng.integers(0, len(uniq), size=len(uniq))
            frames, dens = [], {}
            for k, i in enumerate(pick):
                q = uniq[int(i)]
                label = f"{q}#{k}"
                frame = by_quadrat[q].copy()
                frame["quadrat"] = label
                frames.append(frame)
                dens[label] = float(quadrat_density[q])
            rep_density = pd.Series(dens)
            try:
                rep_df = pd.concat(frames, ignore_index=True)
                rep_stratified = coverage_ratio_by_size_and_density(
                    None, list(rep_density.index), threshold, rep_density,
                    sppi_min_precision=sppi_min_precision,
                    n_density_bands=n_density_bands,
                    df=rep_df,
                )
                rep_recall = None if recall_stratified is None else area_recall_by_size_and_density(
                    None, list(rep_density.index), threshold, rep_density,
                    sppi_min_precision=sppi_min_precision,
                    n_density_bands=n_density_bands,
                    df=rep_df,
                )
                rep_total = _priced(rep_stratified, rep_recall)
            except Exception as e:  # noqa: BLE001 -- a degenerate resample must not kill the run
                n_degenerate += 1
                log.warning("Coverage-ratio bootstrap: replicate dropped (%s)", e)
                continue
            factors.append(rep_total / point_total)
    finally:
        log.setLevel(prev_level)

    if not factors:
        log.warning(
            "Coverage-ratio bootstrap: every one of %d replicates was degenerate -- no "
            "interval reported for this component", n_boot,
        )
        return {**empty, "n_degenerate_replicates": n_degenerate}

    from earthpv.capacity_calibration import CI_PCT

    arr = np.asarray(factors, dtype=float)
    lo, hi = (float(v) for v in np.percentile(arr, CI_PCT))
    out = {
        "n_boot": len(factors),
        "n_boot_requested": int(n_boot),
        "n_degenerate_replicates": n_degenerate,
        "seed": int(seed),
        "resample_unit": "quadrat",
        "n_quadrats": len(uniq),
        "prices": "coverage_ratio / area_recall" if recall_stratified is not None else "coverage_ratio",
        "factors": [round(float(f), 6) for f in arr],
        "factor_ci90": [round(lo, 4), round(hi, 4)],
        "factor_mean": round(float(arr.mean()), 4),
    }
    log.info(
        "Quadrat bootstrap (%s): %d replicates over %d quadrats, factor "
        "%.3f-%.3f (90%%), mean %.3f", out["prices"], len(factors), len(uniq), lo, hi, arr.mean(),
    )
    return out


def national_incremental_capacity(
    roofclf_dir: Path,
    candidates_path: Path,
    folds_path: Path,
    buildings_path: Path,
    threshold: float,
    max_distance_m: float = 30.0,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
) -> tuple[gpd.GeoDataFrame, dict]:
    """The density-stratified version of `roofclf_capacity.incremental_capacity`: same
    dedup-vs-segmentation mechanics, but weighted by the density-regime-restricted
    precision instead of the flat all-quadrat LOQO number. Returns
    `(incremental_buildings, summary)`; `summary` carries both the calibration-selection
    diagnostics and the capacity result so a caller never has to re-derive the precision
    used to produce a given number.
    """
    from earthpv.roofclf_capacity import incremental_capacity

    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)
    precision_info = density_regime_precision(buildings_path, quadrats, threshold)

    incremental, cap_summary = incremental_capacity(
        roofclf_dir=roofclf_dir,
        candidates_path=candidates_path,
        threshold=threshold,
        precision=precision_info["precision"],
        max_distance_m=max_distance_m,
    )
    summary = {
        "method": "density_regime_restricted",
        "calibration_quadrats": quadrats,
        "calibration_base_rate_range": [
            round(float(folds_subset.base_rate.min()), 4),
            round(float(folds_subset.base_rate.max()), 4),
        ],
        "calibration_precision_n": precision_info["n"],
        "calibration_precision_n_flagged": precision_info["n_flagged"],
        "calibration_recall": precision_info["recall"],
        **cap_summary,
        "caveat": (
            "Extrapolated nationally from 3 calibration quadrats at a flat precision; "
            "no reliable per-cell national proxy for local PV density was found (tested: "
            "existing candidate density anti-correlates, roofclf's own predicted rate "
            "does not separate calibration regimes). Not validated at national scale, "
            "not merged into density.py's headline total_est_mwp_rc."
        ),
    }
    return incremental, summary


def cell_density_from_grid(grid_csv_path: Path) -> pd.DataFrame:
    """`(cell, n_buildings, density)` derived from `density.py`'s own `grid.csv` -- the
    building count and the geodesic cell area this needs are already there, so producing
    the file this module's functions read as `cell_density_path` needs no new fetch, just
    a projection. Recomputes `density` (buildings/km2) directly from `n_buildings` /
    `cell_area_km2` rather than reading `grid.csv`'s own `bldg_density_km2` column, which
    `density.aggregate` only writes when `exp_source == "segmentation"` -- this way the
    main workflow's `earthpv sub400-capacity` step works regardless of which expected-area
    instrument the preceding `earthpv density` run used.
    """
    grid = pd.read_csv(grid_csv_path, usecols=["cell", "n_buildings", "cell_area_km2"])
    grid["density"] = grid.n_buildings / grid.cell_area_km2.clip(lower=1e-9)
    return grid[["cell", "n_buildings", "density"]]


def national_cell_domain(cell_density_path: Path) -> set[str]:
    """Cells whose building density falls in the calibration quadrats' range
    (`density.CALIBRATED_BLDG_DENSITY_KM2`) -- the same range `density.py`'s
    segmentation-only completeness flag reads, reused here for the opposite purpose:
    restricting WHERE this module's national deployment is allowed to count buildings at
    all, not just flagging confidence after the fact.
    """
    from earthpv.density import CALIBRATED_BLDG_DENSITY_KM2

    lo, hi = CALIBRATED_BLDG_DENSITY_KM2
    cells = pd.read_parquet(cell_density_path)
    in_range = cells[(cells.density >= lo) & (cells.density <= hi)]
    return set(in_range.cell)


def domain_restricted_capacity(
    roofclf_dir: Path,
    candidates_path: Path,
    folds_path: Path,
    buildings_path: Path,
    cell_density_path: Path,
    threshold: float,
    max_distance_m: float = 30.0,
    contamination_max_m2: float = 400.0,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
    osm_solar_path: Path | None = None,
    quadrat_profile_path: Path = Path("results/calibration_quadrats.csv"),
    n_density_bands: int = DEFAULT_N_DENSITY_STRATA,
    n_coverage_boot: int = DEFAULT_COVERAGE_N_BOOT,
    size_floor_m2: list[float] | None = None,
    recall_correct: bool = True,
) -> tuple[gpd.GeoDataFrame, dict]:
    """The module's actually-recommended output (see module docstring's 2026-07-30 note):
    combines four corrections, each individually insufficient on its own when measured:

    1. **Domain restriction** -- only buildings in cells whose building density falls in
       the calibration quadrats' range count at all (`national_cell_domain`). This is the
       one necessary handle on WHICH buildings this module may speak about; no other
       tested proxy (existing candidate density, roofclf's own raw rate) restricts the
       population defensibly -- see module docstring.
    2. **Contamination filter** -- buildings whose own footprint is already
       >= `contamination_max_m2` are dropped from "incremental": they were never sub-400
       m2 to begin with, they are just outside `new_lead_mask`'s 30 m matching radius of
       an existing segmentation candidate (a geometry-matching gap, not sub-floor signal).
    3. **Size- AND density-stratified coverage ratio** --
       `coverage_ratio_by_size_and_density`'s measured (true mapped PV area / roof area) on
       the flagged population (from the quadrats whose rate_ratio is within `[ratio_lo,
       ratio_hi]`), looked up per building by its OWN `roof_area_m2` *and* its CELL's own
       building density via `apply_stratified_coverage_ratio` -- not a single ratio applied
       uniformly across the whole domain regardless of whether a cell is Multan-dense or
       Faisalabad-sparse. A flat, pooled fit (this function's predecessor, measured
       2026-08-09) already showed the ratio rises with roof size; it did not yet account for
       density, even though `rate_ratio`'s own near-flatness against a 3-30% spread in true
       `base_rate` is the standing evidence that pooling across density regimes hides real
       structure (see CLAUDE.md's "Density and detection quality" section). Falls back to
       the fully pooled fit for any density band too thin to trust on its own -- see that
       function's docstring. `calibration_precision`/`calibration_recall` are still reported
       in the summary for diagnostic comparison, but no longer drive the MWp figure.
    4. **Area-recall correction** (`recall_correct`, default True, added 2026-08-15) --
       divide each building's coverage-ratio-weighted capacity by
       `area_recall_by_size_and_density`'s measured share of true PV area that roofclf
       actually flags in that size/density stratum. Correction 3 estimates the PV on roofs
       roofclf FLAGGED; without this one the estimate books zero for every installation on
       a roof it missed, which on the current 17-quadrat calibration is 19.2% of mapped
       sub-400 m2 PV area pooled and 71-73% in the smallest deciles. This is the same
       Horvitz-Thompson correction `density.py`'s `est_mwp_rc` has always applied to
       segmentation candidates (`capacity_calibration`'s recall table), applied to the
       other instrument at last -- see `area_recall_by_size`'s docstring, including why the
       correction is a floor rather than a point estimate. Set False to reproduce the
       pre-2026-08-15 flagged-population-only figure exactly.

    `osm_solar_path`, when given, adds a FIFTH exclusion: buildings within `max_distance_m`
    of an already hand-mapped OSM solar feature. Without it, "incremental" only means "no
    nearby *segmentation* candidate" -- a roofclf-flagged building that OSM already mapped
    but segmentation missed entirely (no candidate anywhere near it) passes straight
    through, and the evidence atlas counts it twice: once as `osm_mwp_unmatched`, once here.
    Measured 2026-08-06 against the then-current outputs: 2.8% of buildings / 3.3% of MWp
    in this population sat within 30 m of an OSM feature -- real, not hypothetical. Optional
    (not required) only because some callers may not have a national OSM pull handy; every
    call that feeds the evidence atlas should pass it.

    `size_floor_m2`, when given (default `None` = no floor, existing behavior unchanged),
    adds an OPTIONAL SIXTH exclusion: `size_floor_by_density_band` drops any building
    below its own cell's density-band-specific size floor -- e.g. `[0.0, 100.0]` keeps
    every sub-400 m2 building in the sparser calibration band but drops anything under
    100 m2 in the denser band. This is a 2026-08-10 prototype answering whether a lower
    size floor should be flat or density-conditional: measured on the calibration
    quadrats, a given floor buys ~2x more precision per point of recall spent in the
    denser band than the sparser one, so a flat floor is the wrong shape for this
    tradeoff. Must have exactly `n_density_bands` entries, applied to `incremental`
    AFTER the contamination filter and using the SAME band edges
    `apply_stratified_coverage_ratio` uses, via each building's own national CELL
    density (not its roof size or quadrat). Still gated on only 2 bands / 13 quadrats --
    treat any nonzero value as a measured lead, not a settled calibration; not called by
    the CLI yet.

    Returns `(incremental_buildings, summary)`. `summary["scope"]` states exactly what
    population this describes -- READ IT before quoting the MWp number. It is a LOCAL
    figure (the in-domain cells only, 93 of 4,473 nationally as measured 2026-07-30) and
    must NOT be divided by the domain's share of national cells/buildings to infer a
    country total -- doing so was the exact failure this module exists to avoid.
    """
    from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE
    from earthpv.export import new_lead_mask

    all_cells = pd.read_parquet(cell_density_path)
    in_domain_cells = national_cell_domain(cell_density_path)
    n_buildings_in_domain = int(
        all_cells.loc[all_cells.cell.isin(in_domain_cells), "n_buildings"].sum()
    )
    n_buildings_national = int(all_cells.n_buildings.sum())
    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)
    precision_info = density_regime_precision(buildings_path, quadrats, threshold)
    composition = parcel_label_composition(buildings_path, quadrats, threshold)
    ground_share = composition["yard_ground_share_of_flagged"] if composition else 0.0
    quadrat_density = quadrat_building_density_km2(quadrat_profile_path, quadrats)
    stratified = coverage_ratio_by_size_and_density(
        buildings_path, quadrats, threshold, quadrat_density, n_density_bands=n_density_bands
    )
    recall_stratified = area_recall_by_size_and_density(
        buildings_path, quadrats, threshold, quadrat_density, n_density_bands=n_density_bands
    ) if recall_correct else None

    # Read only the ~93 in-domain per-cell parquets, not all 4,473 -- files are named
    # <cell>.parquet by `score_buildings_national`, so this is a filename filter, not a
    # post-hoc one. `load_flagged_buildings` (roofclf_capacity.py) reads everything and
    # would be ~50x slower here for no benefit, since the domain restriction throws away
    # all but ~2% of cells anyway.
    parts = []
    for cell in sorted(in_domain_cells):
        p = Path(roofclf_dir) / f"{cell}.parquet"
        if not p.exists():
            continue
        d = gpd.read_parquet(p)
        if d.empty or "p_roofclf" not in d.columns:
            continue
        f = d[d.p_roofclf >= threshold]
        if not f.empty:
            parts.append(f)
    flagged = (
        gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
        if parts else gpd.GeoDataFrame(columns=["cell", "geometry", "roof_area_m2", "p_roofclf"], crs="EPSG:4326")
    )
    log.info(
        "Domain-restricted: %d/%d cells, %d flagged buildings in-domain",
        len(in_domain_cells), len(all_cells), len(flagged),
    )

    cands = gpd.read_parquet(candidates_path)
    is_new = new_lead_mask(flagged, cands, min_distance_m=max_distance_m)
    n_near_osm = 0
    if osm_solar_path is not None:
        osm = gpd.read_parquet(osm_solar_path)
        is_new_osm = new_lead_mask(flagged, osm, min_distance_m=max_distance_m)
        n_near_osm = int((is_new & ~is_new_osm).sum())
        is_new = is_new & is_new_osm
    incremental_raw = flagged[is_new].reset_index(drop=True)

    over = incremental_raw.roof_area_m2 >= contamination_max_m2
    n_contaminated = int(over.sum())
    contaminated_area_m2 = float(incremental_raw.loc[over, "roof_area_m2"].sum())
    incremental = incremental_raw[~over].reset_index(drop=True)

    incremental = incremental.copy()
    cell_density_lookup = all_cells.set_index("cell")["density"]
    incremental_cell_density = incremental["cell"].map(cell_density_lookup).to_numpy(float)

    n_excluded_by_size_floor = 0
    area_m2_excluded_by_size_floor = 0.0
    if size_floor_m2 is not None:
        floor_band_edges = np.array(stratified["band_edges"])
        keep = size_floor_by_density_band(
            incremental.roof_area_m2.to_numpy(float), incremental_cell_density,
            floor_band_edges, size_floor_m2,
        )
        n_excluded_by_size_floor = int((~keep).sum())
        area_m2_excluded_by_size_floor = float(incremental.loc[~keep, "roof_area_m2"].sum())
        incremental = incremental[keep].reset_index(drop=True)
        incremental_cell_density = incremental_cell_density[keep]

    total_area_m2 = float(incremental.roof_area_m2.sum())
    incremental["coverage_ratio"] = apply_stratified_coverage_ratio(
        incremental.roof_area_m2.to_numpy(float), incremental_cell_density, stratified
    )
    incremental["area_recall"] = (
        apply_stratified_area_recall(
            incremental.roof_area_m2.to_numpy(float), incremental_cell_density, recall_stratified
        ) if recall_correct else np.ones(len(incremental))
    )
    incremental["est_kwp_sub400"] = (
        incremental.roof_area_m2.to_numpy(float)
        * DEFAULT_KWP_PER_M2_MODULE
        * incremental["coverage_ratio"].to_numpy()
        / incremental["area_recall"].to_numpy()
    )
    # Per `parcel_label_composition`, a flat fraction of every parcel-label building's
    # priced capacity is OSM `placement=ground` PV standing in the yard, not on the roof
    # -- measured pooled over the quadrats, not per building (no ground-truth PV exists on
    # the national population this table scores). `ground_share` is 0.0 for a roof-only
    # calibration table, so this column always exists and downstream size-by-placement
    # charts (`atlas._size_distribution_data`) don't need a column-presence check.
    incremental["est_kwp_sub400_ground"] = incremental["est_kwp_sub400"] * ground_share
    total_mwp = float(incremental.est_kwp_sub400.sum()) / 1000.0
    mean_coverage_ratio = (
        float(np.average(incremental["coverage_ratio"], weights=incremental.roof_area_m2))
        if len(incremental) else float("nan")
    )
    # Capacity-weighted, so it reads as the factor the published total was actually divided
    # by, not as an unweighted average over a population dominated by tiny roofs.
    effective_area_recall = (
        float(
            (incremental.roof_area_m2 * incremental.coverage_ratio).sum()
            / (incremental.roof_area_m2 * incremental.coverage_ratio / incremental.area_recall).sum()
        ) if len(incremental) and total_mwp > 0 else float("nan")
    )
    cov_boot = coverage_ratio_bootstrap_factors(
        buildings_path, quadrats, threshold, quadrat_density, stratified,
        incremental.roof_area_m2.to_numpy(float), incremental_cell_density,
        n_density_bands=n_density_bands, n_boot=n_coverage_boot,
        recall_stratified=recall_stratified,
    )

    summary = {
        "method": "domain_restricted_sub400_capacity",
        "calibration_quadrats": quadrats,
        # None for a roof-only calibration table; present (and worth reading before
        # quoting this component as "rooftop") for a parcel-label one.
        "parcel_label_composition": composition,
        "calibration_precision": precision_info["precision"],
        "calibration_recall": precision_info["recall"],
        "calibration_coverage_ratio_by_size_and_density": stratified,
        "calibration_coverage_ratio_area_weighted_mean": (
            round(mean_coverage_ratio, 4) if mean_coverage_ratio == mean_coverage_ratio else None
        ),
        "recall_correction_applied": bool(recall_correct),
        "calibration_area_recall_by_size_and_density": recall_stratified,
        "calibration_effective_area_recall": (
            round(effective_area_recall, 4)
            if effective_area_recall == effective_area_recall else None
        ),
        # Quadrat-resampling uncertainty on this component, as dimensionless multiplicative
        # factors (`coverage_ratio_bootstrap_factors`), pricing the coverage ratio and the
        # area-recall correction together in one set of replicates. `atlas.build_evidence_
        # atlas` reads `factors` replicate-by-replicate so components sharing a calibration
        # set keep their correlation; read `factor_ci90` for this component on its own.
        "coverage_ratio_bootstrap": cov_boot,
        "n_domain_cells": len(in_domain_cells),
        "n_national_cells": int(len(all_cells)),
        "n_buildings_in_domain": n_buildings_in_domain,
        "n_buildings_national": n_buildings_national,
        "n_flagged_in_domain": int(len(flagged)),
        "osm_dedup_applied": osm_solar_path is not None,
        "n_excluded_near_osm": n_near_osm,
        "n_incremental_before_contamination_filter": int(len(incremental_raw)),
        "n_contaminated_excluded_ge_400m2": n_contaminated,
        "contaminated_area_m2_excluded": round(contaminated_area_m2, 1),
        "size_floor_applied": size_floor_m2 is not None,
        "size_floor_m2": size_floor_m2,
        "size_floor_band_edges": (
            [float(e) for e in stratified["band_edges"]] if size_floor_m2 is not None else None
        ),
        "n_excluded_by_size_floor": n_excluded_by_size_floor,
        "area_m2_excluded_by_size_floor": round(area_m2_excluded_by_size_floor, 1),
        "n_incremental_sub400": int(len(incremental)),
        "total_incremental_sub400_area_m2": round(total_area_m2, 1),
        "total_est_mwp_sub400_domain_restricted": round(total_mwp, 4),
        "scope": (
            f"{len(in_domain_cells)} of {len(all_cells)} national cells "
            f"({100 * len(in_domain_cells) / len(all_cells):.1f}% of cells, "
            f"{100 * n_buildings_in_domain / n_buildings_national:.1f}% of national "
            "buildings) whose building density falls in the calibration quadrats' range. "
            "NOT a national figure -- do not rescale by the domain's share of "
            "cells/buildings to estimate a country total; the other cells are mostly "
            "rural and not known to share this rate."
        ),
    }
    log.info("Domain-restricted sub-400 capacity: %s", summary)
    return incremental, summary


def domain_restricted_and_gate_capacity(
    roofclf_dir: Path,
    candidates_path: Path,
    folds_path: Path,
    buildings_path: Path,
    cell_density_path: Path,
    threshold: float,
    sppi_min_precision: float = 0.5,
    max_distance_m: float = 30.0,
    contamination_max_m2: float = 400.0,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
    osm_solar_path: Path | None = None,
    quadrat_profile_path: Path = Path("results/calibration_quadrats.csv"),
    n_density_bands: int = DEFAULT_N_DENSITY_STRATA,
    n_coverage_boot: int = DEFAULT_COVERAGE_N_BOOT,
    size_floor_m2: list[float] | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """The sub-400 bracket's LOW end: `domain_restricted_capacity`'s same 93-cell
    population, but requiring `p_roofclf >= threshold` AND SPPI above a pooled
    precision-targeted threshold, instead of roofclf alone.

    `docs/methods/density.md`'s "SPPI cross-validation" section measured this AND-gate
    on the domain-restricted population in prose on 2026-07-30 (496,122 -> 343,032
    flagged buildings, 6,628 -> 4,690 MWp, precision flat at ~0.55) but never saved it as
    reusable code or a pinned artifact -- this is that promotion, re-measured against
    whatever `roofclf_dir`/`candidates_path` are current rather than assumed to
    reproduce the exact prior figure. It was rejected there as *the* domain-restricted
    number (no precision gain, only lost recall) -- that verdict still holds. As a
    bracket LOW end it is being asked a different question: not "is this the best
    domain-restricted estimate" but "what does the more conservative of two measured
    detector agreements say", which is exactly what a stricter join criterion is for.

    The SPPI threshold is a single pooled fit on the SAME calibration quadrats
    `select_calibrated_quadrats` already selects (`sppi.pooled_precision_threshold`) --
    no LOQO here, since there is no national quadrat to hold out, matching how
    roofclf's own national `deployment_threshold` is one pooled constant.

    `osm_solar_path`: see `domain_restricted_capacity`'s docstring -- same fix, same
    reason (measured 2026-08-06: 3.0% of buildings / 3.8% of MWp in this population
    were within 30 m of an OSM feature before this parameter existed).

    `size_floor_m2`: see `domain_restricted_capacity`'s docstring -- same optional,
    2026-08-10 prototype density-conditional floor, same band edges, applied here to the
    AND-gate's own flagged population instead of roofclf-alone's.

    **Capacity multiplier is the measured coverage ratio, not `and_precision`
    (2026-08-06 fix)** -- see `domain_restricted_capacity`'s docstring point 3:
    `and_precision` (0.63) assumes full-footprint PV coverage on every true positive, but
    the AND-gate's own flagged sub-400 m2 population covers only ~26.5% of its footprint
    on average, so precision alone overstated this tier's capacity ~1.4x. **Size-binned as
    of 2026-08-09** (`coverage_ratio_by_size`/`apply_size_coverage_ratio`, replacing that
    flat 26.5% average): the AND-gate's flagged population shows a much sharper
    coverage-vs-size rise than roofclf-only (~0.21 in the smallest decile of flagged roofs
    to ~0.45 in the largest), so a flat ratio here was the more distorting of the two.
    **Size- AND density-stratified, same day**: see `domain_restricted_capacity`'s
    docstring point 3 -- `coverage_ratio_by_size_and_density`/
    `apply_stratified_coverage_ratio` replace the single pooled size-binned fit with one
    fit per building-density stratum, each still size-binned internally.

    **No area-recall correction here, deliberately (2026-08-15).**
    `domain_restricted_capacity` now divides by `area_recall_by_size_and_density` to
    estimate the whole population rather than the flagged part of it. This function does
    not, and takes no `recall_correct` parameter, because its output is used as a FLOOR --
    the atlas's per-cell minimum alongside hand-mapped OSM. A floor that extrapolates to
    installations no instrument saw is not a floor. Requiring two independent detectors to
    agree and then counting only what they jointly flagged is the whole point of this
    tier; correcting it back up to the population would collapse the distinction between
    it and `domain_restricted_capacity`.
    """
    from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE
    from earthpv.export import new_lead_mask
    from earthpv.sppi import add_sppi, pooled_precision_threshold

    all_cells = pd.read_parquet(cell_density_path)
    in_domain_cells = national_cell_domain(cell_density_path)
    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)

    bt = gpd.read_parquet(buildings_path)
    if "sppi" not in bt.columns:
        bt = add_sppi(bt)
    sppi_thresh = pooled_precision_threshold(bt, quadrats, min_precision=sppi_min_precision)

    cal = bt[bt.quadrat.isin(quadrats)]
    y = cal.has_pv.to_numpy(bool)
    roof_pred = cal.p_oof.to_numpy(float) >= threshold
    and_pred = roof_pred & (cal.sppi.to_numpy(float) >= sppi_thresh)
    tp = int((and_pred & y).sum())
    fp = int((and_pred & ~y).sum())
    and_precision = tp / (tp + fp) if (tp + fp) else float("nan")
    and_recall = tp / int(y.sum()) if y.sum() else float("nan")
    roof_tp = int((roof_pred & y).sum())
    roof_fp = int((roof_pred & ~y).sum())
    roof_only_precision = roof_tp / (roof_tp + roof_fp) if (roof_tp + roof_fp) else float("nan")
    roof_only_recall = roof_tp / int(y.sum()) if y.sum() else float("nan")

    quadrat_density = quadrat_building_density_km2(quadrat_profile_path, quadrats)
    stratified = coverage_ratio_by_size_and_density(
        buildings_path, quadrats, threshold, quadrat_density,
        sppi_min_precision=sppi_min_precision, n_density_bands=n_density_bands,
    )

    parts = []
    for cell in sorted(in_domain_cells):
        p = Path(roofclf_dir) / f"{cell}.parquet"
        if not p.exists():
            continue
        d = gpd.read_parquet(p)
        if d.empty or "p_roofclf" not in d.columns or "sppi" not in d.columns:
            continue
        f = d[(d.p_roofclf >= threshold) & (d.sppi >= sppi_thresh)]
        if not f.empty:
            parts.append(f)
    flagged = (
        gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
        if parts
        else gpd.GeoDataFrame(
            columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"], crs="EPSG:4326"
        )
    )
    log.info(
        "Domain-restricted AND-gate: %d/%d cells, %d flagged buildings in-domain "
        "(sppi_threshold=%.4f)", len(in_domain_cells), len(all_cells), len(flagged), sppi_thresh,
    )

    cands = gpd.read_parquet(candidates_path)
    is_new = new_lead_mask(flagged, cands, min_distance_m=max_distance_m)
    n_near_osm = 0
    if osm_solar_path is not None:
        osm = gpd.read_parquet(osm_solar_path)
        is_new_osm = new_lead_mask(flagged, osm, min_distance_m=max_distance_m)
        n_near_osm = int((is_new & ~is_new_osm).sum())
        is_new = is_new & is_new_osm
    incremental_raw = flagged[is_new].reset_index(drop=True)

    over = incremental_raw.roof_area_m2 >= contamination_max_m2
    n_contaminated = int(over.sum())
    contaminated_area_m2 = float(incremental_raw.loc[over, "roof_area_m2"].sum())
    incremental = incremental_raw[~over].reset_index(drop=True)

    incremental = incremental.copy()
    cell_density_lookup = all_cells.set_index("cell")["density"]
    incremental_cell_density = incremental["cell"].map(cell_density_lookup).to_numpy(float)

    n_excluded_by_size_floor = 0
    area_m2_excluded_by_size_floor = 0.0
    if size_floor_m2 is not None:
        floor_band_edges = np.array(stratified["band_edges"])
        keep = size_floor_by_density_band(
            incremental.roof_area_m2.to_numpy(float), incremental_cell_density,
            floor_band_edges, size_floor_m2,
        )
        n_excluded_by_size_floor = int((~keep).sum())
        area_m2_excluded_by_size_floor = float(incremental.loc[~keep, "roof_area_m2"].sum())
        incremental = incremental[keep].reset_index(drop=True)
        incremental_cell_density = incremental_cell_density[keep]

    total_area_m2 = float(incremental.roof_area_m2.sum())
    incremental["coverage_ratio"] = apply_stratified_coverage_ratio(
        incremental.roof_area_m2.to_numpy(float), incremental_cell_density, stratified
    )
    incremental["est_kwp_sub400_and_gate"] = (
        incremental.roof_area_m2.to_numpy(float)
        * DEFAULT_KWP_PER_M2_MODULE
        * incremental["coverage_ratio"].to_numpy()
    )
    total_mwp = float(incremental.est_kwp_sub400_and_gate.sum()) / 1000.0
    mean_coverage_ratio = (
        float(np.average(incremental["coverage_ratio"], weights=incremental.roof_area_m2))
        if len(incremental) else float("nan")
    )
    cov_boot = coverage_ratio_bootstrap_factors(
        buildings_path, quadrats, threshold, quadrat_density, stratified,
        incremental.roof_area_m2.to_numpy(float), incremental_cell_density,
        sppi_min_precision=sppi_min_precision,
        n_density_bands=n_density_bands, n_boot=n_coverage_boot,
    )

    summary = {
        "method": "domain_restricted_and_gate_sub400_capacity",
        "calibration_quadrats": quadrats,
        "roofclf_threshold": threshold,
        "sppi_threshold": round(float(sppi_thresh), 4),
        "roofclf_only_precision_same_quadrats": (
            round(roof_only_precision, 4) if roof_only_precision == roof_only_precision else None
        ),
        "roofclf_only_recall_same_quadrats": (
            round(roof_only_recall, 4) if roof_only_recall == roof_only_recall else None
        ),
        "and_gate_precision": round(and_precision, 4) if and_precision == and_precision else None,
        "and_gate_recall": round(and_recall, 4) if and_recall == and_recall else None,
        "and_gate_coverage_ratio_by_size_and_density": stratified,
        "and_gate_coverage_ratio_area_weighted_mean": (
            round(mean_coverage_ratio, 4) if mean_coverage_ratio == mean_coverage_ratio else None
        ),
        # Quadrat-resampling uncertainty on this component, as dimensionless multiplicative
        # factors (`coverage_ratio_bootstrap_factors`). `atlas.build_evidence_atlas` reads
        # `factors` replicate-by-replicate so components sharing a calibration set keep
        # their correlation; read `factor_ci90` for this component on its own.
        "coverage_ratio_bootstrap": cov_boot,
        "n_domain_cells": len(in_domain_cells),
        "n_national_cells": int(len(all_cells)),
        "n_flagged_in_domain": int(len(flagged)),
        "osm_dedup_applied": osm_solar_path is not None,
        "n_excluded_near_osm": n_near_osm,
        "n_incremental_before_contamination_filter": int(len(incremental_raw)),
        "n_contaminated_excluded_ge_400m2": n_contaminated,
        "contaminated_area_m2_excluded": round(contaminated_area_m2, 1),
        "size_floor_applied": size_floor_m2 is not None,
        "size_floor_m2": size_floor_m2,
        "size_floor_band_edges": (
            [float(e) for e in stratified["band_edges"]] if size_floor_m2 is not None else None
        ),
        "n_excluded_by_size_floor": n_excluded_by_size_floor,
        "area_m2_excluded_by_size_floor": round(area_m2_excluded_by_size_floor, 1),
        "n_incremental_sub400": int(len(incremental)),
        "total_incremental_sub400_area_m2": round(total_area_m2, 1),
        "total_est_mwp_sub400_and_gate": round(total_mwp, 4),
        "scope": (
            f"{len(in_domain_cells)} of {len(all_cells)} national cells "
            f"({100 * len(in_domain_cells) / len(all_cells):.1f}% of cells) -- the SAME "
            "population `domain_restricted_capacity` uses, joined against SPPI instead "
            "of roofclf alone. NOT a national figure; see that function's docstring for "
            "why rescaling by cell/building share is invalid. This is the sub-400 "
            "bracket's LOW member -- read alongside `total_est_mwp_sub400_domain_"
            "restricted` (central, roofclf alone, same population) and the unrestricted "
            "flat-precision national fold-in (high, see roofclf_capacity.py / "
            "docs/methods/density.md)."
        ),
    }
    log.info("Domain-restricted AND-gate sub-400 capacity: %s", summary)
    return incremental, summary


def out_of_domain_and_gate_capacity(
    roofclf_dir: Path,
    candidates_path: Path,
    folds_path: Path,
    buildings_path: Path,
    cell_density_path: Path,
    threshold: float,
    sppi_min_precision: float = 0.5,
    max_distance_m: float = 30.0,
    contamination_max_m2: float = 400.0,
    ratio_lo: float = DEFAULT_RATIO_LO,
    ratio_hi: float = DEFAULT_RATIO_HI,
    osm_solar_path: Path | None = None,
    quadrat_profile_path: Path = Path("results/calibration_quadrats.csv"),
    n_density_bands: int = DEFAULT_N_DENSITY_STRATA,
    n_coverage_boot: int = DEFAULT_COVERAGE_N_BOOT,
    size_floor_m2: list[float] | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """`domain_restricted_and_gate_capacity`'s mirror image: the SAME roofclf-AND-SPPI
    join, coverage-ratio-by-size-and-density fit, OSM/candidate dedup and contamination
    filter, applied to national cells OUTSIDE `national_cell_domain()` instead of inside
    it. Added 2026-08-11 at the owner's explicit direction, after a manual JOSM
    validation pass for the out-of-domain random-cell batch
    (`results/pakistan_roofclf_validation_outdomain/`) turned out to be blocked by
    stale reference imagery -- too old to confirm or refute recently-installed small PV.
    The AND-gate was proposed as a substitute standard of evidence for exactly the cells
    that cannot currently be manually checked: requiring two independent, differently-
    built detectors (a supervised classifier and a zero-training spectral index) to agree
    is a real, if partial, substitute for a human looking at fresh imagery, which is why
    this is wired into the Best-estimate tier alongside `domain_restricted_capacity`
    (roofclf alone) rather than left as a one-off estimate.

    **This is a strict extrapolation, not a modest widening, and callers must not
    mistake it for one.** Measured against the current national cell-density table the
    day this was added: of 4,300 out-of-domain cells, precisely ZERO sit above
    `density.CALIBRATED_BLDG_DENSITY_KM2`'s upper edge -- all of them are below its lower
    edge (median 86.6 bldg/km2 against the calibrated floor of ~553/km2, roughly 6x
    sparser than the least-dense calibrated quadrat). So this does not interpolate
    between calibrated regimes, it extrapolates a fit measured on 13 urban/semi-urban
    quadrats across the entire rural remainder of the country, which has no calibration
    quadrat anywhere in its density range. `apply_stratified_coverage_ratio` handles this
    mechanically (every out-of-domain cell's density clips to the lowest calibrated
    stratum via `np.searchsorted` against band edges forced to +-inf), but "handles
    gracefully" is not "validated" -- rural roof material, vegetation context and true PV
    prevalence could all differ from the urban quadrats this coverage ratio was measured
    on, and nothing in this function's inputs could detect that if it were true.

    Returns `(incremental_buildings, summary)` with the same shape as
    `domain_restricted_and_gate_capacity`; `summary["scope"]` restates this caveat so it
    travels with the number wherever it is logged or displayed.

    **No area-recall correction here either (2026-08-15)**, for a second reason on top of
    the AND-gate one: this component already extrapolates a coverage ratio measured on
    urban/semi-urban quadrats across cells with no calibration coverage at all. Dividing
    that by a recall measured on the same non-representative quadrats would compound one
    extrapolation with another and widen the claim without widening the evidence.
    """
    from earthpv.capacity_calibration import DEFAULT_KWP_PER_M2_MODULE
    from earthpv.export import new_lead_mask
    from earthpv.sppi import add_sppi, pooled_precision_threshold

    all_cells = pd.read_parquet(cell_density_path)
    in_domain_cells = national_cell_domain(cell_density_path)
    out_domain_cells = set(all_cells.cell) - in_domain_cells
    quadrats, folds_subset = select_calibrated_quadrats(folds_path, ratio_lo, ratio_hi)

    from earthpv.density import CALIBRATED_BLDG_DENSITY_KM2

    lo, hi = CALIBRATED_BLDG_DENSITY_KM2
    out_density = all_cells.loc[all_cells.cell.isin(out_domain_cells), "density"]
    n_below = int((out_density < lo).sum())
    n_above = int((out_density > hi).sum())
    log.warning(
        "Out-of-domain AND-gate: %d/%d out-of-domain cells are BELOW the calibrated "
        "band (%.1f/km2), %d are ABOVE it (%.1f/km2) -- this is an extrapolation in "
        "whichever direction dominates, not an interpolation",
        n_below, len(out_domain_cells), lo, n_above, hi,
    )

    bt = gpd.read_parquet(buildings_path)
    if "sppi" not in bt.columns:
        bt = add_sppi(bt)
    sppi_thresh = pooled_precision_threshold(bt, quadrats, min_precision=sppi_min_precision)

    quadrat_density = quadrat_building_density_km2(quadrat_profile_path, quadrats)
    stratified = coverage_ratio_by_size_and_density(
        buildings_path, quadrats, threshold, quadrat_density,
        sppi_min_precision=sppi_min_precision, n_density_bands=n_density_bands,
    )

    parts = []
    for cell in sorted(out_domain_cells):
        p = Path(roofclf_dir) / f"{cell}.parquet"
        if not p.exists():
            continue
        d = gpd.read_parquet(p)
        if d.empty or "p_roofclf" not in d.columns or "sppi" not in d.columns:
            continue
        f = d[(d.p_roofclf >= threshold) & (d.sppi >= sppi_thresh)]
        if not f.empty:
            parts.append(f)
    flagged = (
        gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
        if parts
        else gpd.GeoDataFrame(
            columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"], crs="EPSG:4326"
        )
    )
    log.info(
        "Out-of-domain AND-gate: %d/%d cells, %d flagged buildings out-of-domain "
        "(sppi_threshold=%.4f)", len(out_domain_cells), len(all_cells), len(flagged), sppi_thresh,
    )

    cands = gpd.read_parquet(candidates_path)
    is_new = new_lead_mask(flagged, cands, min_distance_m=max_distance_m)
    n_near_osm = 0
    if osm_solar_path is not None:
        osm = gpd.read_parquet(osm_solar_path)
        is_new_osm = new_lead_mask(flagged, osm, min_distance_m=max_distance_m)
        n_near_osm = int((is_new & ~is_new_osm).sum())
        is_new = is_new & is_new_osm
    incremental_raw = flagged[is_new].reset_index(drop=True)

    over = incremental_raw.roof_area_m2 >= contamination_max_m2
    n_contaminated = int(over.sum())
    contaminated_area_m2 = float(incremental_raw.loc[over, "roof_area_m2"].sum())
    incremental = incremental_raw[~over].reset_index(drop=True)

    incremental = incremental.copy()
    cell_density_lookup = all_cells.set_index("cell")["density"]
    incremental_cell_density = incremental["cell"].map(cell_density_lookup).to_numpy(float)

    n_excluded_by_size_floor = 0
    area_m2_excluded_by_size_floor = 0.0
    if size_floor_m2 is not None:
        floor_band_edges = np.array(stratified["band_edges"])
        keep = size_floor_by_density_band(
            incremental.roof_area_m2.to_numpy(float), incremental_cell_density,
            floor_band_edges, size_floor_m2,
        )
        n_excluded_by_size_floor = int((~keep).sum())
        area_m2_excluded_by_size_floor = float(incremental.loc[~keep, "roof_area_m2"].sum())
        incremental = incremental[keep].reset_index(drop=True)
        incremental_cell_density = incremental_cell_density[keep]

    total_area_m2 = float(incremental.roof_area_m2.sum())
    incremental["coverage_ratio"] = apply_stratified_coverage_ratio(
        incremental.roof_area_m2.to_numpy(float), incremental_cell_density, stratified
    )
    incremental["est_kwp_sub400_outdomain"] = (
        incremental.roof_area_m2.to_numpy(float)
        * DEFAULT_KWP_PER_M2_MODULE
        * incremental["coverage_ratio"].to_numpy()
    )
    total_mwp = float(incremental.est_kwp_sub400_outdomain.sum()) / 1000.0
    mean_coverage_ratio = (
        float(np.average(incremental["coverage_ratio"], weights=incremental.roof_area_m2))
        if len(incremental) else float("nan")
    )
    # Same quadrat bootstrap as the in-domain functions, and it means LESS here: it
    # measures how much the answer moves if a different set of the SAME urban/semi-urban
    # quadrats had been mapped, which is not the dominant uncertainty for a population
    # that has no calibration quadrat in its density range at all. The extrapolation
    # itself is priced separately, in `atlas.build_evidence_atlas`
    # (`OUTDOMAIN_EXTRAPOLATION_CI90`), and is much wider than this.
    cov_boot = coverage_ratio_bootstrap_factors(
        buildings_path, quadrats, threshold, quadrat_density, stratified,
        incremental.roof_area_m2.to_numpy(float), incremental_cell_density,
        sppi_min_precision=sppi_min_precision,
        n_density_bands=n_density_bands, n_boot=n_coverage_boot,
    )

    summary = {
        "method": "out_of_domain_and_gate_sub400_capacity",
        "calibration_quadrats": quadrats,
        "roofclf_threshold": threshold,
        "sppi_threshold": round(float(sppi_thresh), 4),
        "and_gate_coverage_ratio_area_weighted_mean": (
            round(mean_coverage_ratio, 4) if mean_coverage_ratio == mean_coverage_ratio else None
        ),
        # Quadrat-resampling uncertainty on this component, as dimensionless multiplicative
        # factors (`coverage_ratio_bootstrap_factors`). `atlas.build_evidence_atlas` reads
        # `factors` replicate-by-replicate so components sharing a calibration set keep
        # their correlation; read `factor_ci90` for this component on its own.
        "coverage_ratio_bootstrap": cov_boot,
        "n_out_domain_cells": len(out_domain_cells),
        "n_out_domain_cells_below_calibrated_band": n_below,
        "n_out_domain_cells_above_calibrated_band": n_above,
        "n_national_cells": int(len(all_cells)),
        "n_flagged_out_domain": int(len(flagged)),
        "osm_dedup_applied": osm_solar_path is not None,
        "n_excluded_near_osm": n_near_osm,
        "n_incremental_before_contamination_filter": int(len(incremental_raw)),
        "n_contaminated_excluded_ge_400m2": n_contaminated,
        "contaminated_area_m2_excluded": round(contaminated_area_m2, 1),
        "size_floor_applied": size_floor_m2 is not None,
        "size_floor_m2": size_floor_m2,
        "n_excluded_by_size_floor": n_excluded_by_size_floor,
        "area_m2_excluded_by_size_floor": round(area_m2_excluded_by_size_floor, 1),
        "n_incremental_sub400": int(len(incremental)),
        "total_incremental_sub400_area_m2": round(total_area_m2, 1),
        "total_est_mwp_sub400_outdomain_and_gate": round(total_mwp, 4),
        "scope": (
            f"{len(out_domain_cells)} of {len(all_cells)} national cells OUTSIDE the "
            "calibrated density domain, roofclf-AND-SPPI agreement only. STRICT "
            f"EXTRAPOLATION: {n_below} of these cells sit below the calibrated density "
            f"band and {n_above} above it -- no calibration quadrat exists anywhere in "
            "this density range. Not a substitute for manual validation, only for cells "
            "where manual validation is currently blocked by stale reference imagery "
            "(see docs/methods/roofclf-national-validation.md). Feeds the Best-estimate "
            "tier only, never Verified."
        ),
    }
    log.info("Out-of-domain AND-gate sub-400 capacity: %s", summary)
    return incremental, summary


def suggest_high_density_regions(
    cell_density_path: Path,
    calibration_quadrat_densities: dict[str, float],
    top_n: int = 20,
) -> pd.DataFrame:
    """Rank national 0.1-degree cells by building density (buildings/km2) as the best
    *available* proxy for "resembles a calibration quadrat" -- explicitly NOT a validated
    predictor of small-PV adoption (see module docstring: no such proxy was found). This
    only answers "where should new calibration quadrats be mapped to extend the density
    range this module depends on", which is a weaker and more honest question than "where
    is sub-400 m2 capacity concentrated".

    `calibration_quadrat_densities` should be the 8-quadrat building-density table (name
    -> buildings/km2) so the ranked cells can be read against the existing density range.
    """
    cells = pd.read_parquet(cell_density_path)
    ranked = cells.sort_values("density", ascending=False).head(top_n).reset_index(drop=True)
    lo = min(calibration_quadrat_densities.values())
    hi = max(calibration_quadrat_densities.values())
    ranked["vs_calibration_range"] = np.where(
        ranked.density < lo, "below", np.where(ranked.density > hi, "above", "within")
    )
    log.info(
        "Top %d national cells by building density (calibration range %.0f-%.0f/km2): "
        "see returned DataFrame",
        top_n, lo, hi,
    )
    return ranked
