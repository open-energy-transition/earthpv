"""SPPI (He et al. 2026) as a building-scoped, precision-calibrated PV detector.

Promotes the formula and evaluation validated in `scripts/sppi_index_test.py` /
`docs/issues/sppi-spectral-index-evaluation.md` into reusable code. That evaluation found
SPPI is a real, substantially independent per-building signal (median AUC 0.828 within
size band, only 30.6% overlap with what the segmentation model catches) but NOT a
standalone capacity instrument (18x scale spread across quadrats, worst case 4.7x
over-prediction on bare arid ground -- exactly this project's dominant false-positive
mode).

The design here is scoped to close that specific gap: SPPI-driven candidates are
restricted to BUILDING FOOTPRINTS. Bare rock, glacier, and desert have no building to
attach a candidate to, so they cannot enter this path at all -- the arid failure mode is
structurally excluded rather than statistically corrected. This module only prepares and
validates the mechanism (leave-one-quadrat-out threshold calibration and precision
measurement on the 9 mapped quadrats, via `scripts/sppi_capacity_validation.py`); it does
not run at national scale, which is an explicit follow-up decision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-6

# NOT `pooled_precision_threshold`'s building-classification value (-0.0183, fit for 50%
# precision on has_pv) -- that threshold costs 31.1% of confirmed real PV when used as a
# leads veto (measured 2026-08-02, 2,421 OSM-confirmed real vs. 694 confirmed FP: vegetation-
# cycle-refuted + epoch-persistent), because it was calibrated for a different task (balanced
# building classification, not "drop as little real PV as possible"). Swept the full
# threshold curve instead and picked a point matching this project's other vetoes' cost
# convention (the vegetation veto costs ~2% of real PV):
#   thr      real cost   fp catch (694 confirmed FP)   catch on the 21 hardest cases*
#   -0.06    2.3%        57.5%                          9.5%
#   -0.05    3.9%         62.8%                         19.0%
#   -0.04    7.9%         67.9%                            -
#   -0.0183  31.1%        75.6%                         66.7%
# *21 confirmed bare-terrain FPs flagged by hand in Balochistan desert / Gilgit-Baltistan
# mountains -- a harder population for SPPI than the aggregate (vegetation and epoch-
# persistent FPs separate more cleanly), so a low-cost cut catches noticeably fewer of
# exactly this failure class. See candidate_sppi's docstring for the full picture; this is
# a real trade-off, not a bug -- tune `sppi_min` explicitly if catching more of the remote-
# terrain class matters more than a low false-veto rate.
DEFAULT_SPPI_MIN = -0.05


def compute_sppi(b02, b03, b08, b11, b12):
    """SPPI = (B02/B03) * ((B11 - B03 - |B08-B03| - |B12-B03|) / (B11 + B03)).

    B02 (blue) substitutes for the paper's B01 (coastal aerosol, 60 m), which earthpv's
    10-band composites exclude (`config.LOCAL_BANDS`) -- the paper's own recommended
    substitution, costed by the authors at +/-2% accuracy. Every term is a ratio or
    normalized difference of same-scaled reflectance, so it is invariant to whatever
    fixed scale factor the input bands carry (composite DN or true reflectance) --
    accepts numpy arrays, pandas Series, or scalars.
    """
    return (b02 / (b03 + EPS)) * (
        (b11 - b03 - np.abs(b08 - b03) - np.abs(b12 - b03)) / (b11 + b03 + EPS)
    )


def add_sppi(df: pd.DataFrame) -> pd.DataFrame:
    """Add an `sppi` column from a DataFrame carrying `b02_mean`...`b12_mean` (the
    `roofclf.building_table` column convention)."""
    df = df.copy()
    df["sppi"] = compute_sppi(df.b02_mean, df.b03_mean, df.b08_mean, df.b11_mean, df.b12_mean)
    return df


def _youden_threshold(y: np.ndarray, s: np.ndarray) -> tuple[float, dict]:
    """Threshold maximizing Youden's J (sensitivity + specificity - 1).

    Prevalence-independent, unlike F1 -- appropriate here since quadrat base rates span
    3% to 30% (`roofclf`'s own fold table) and a prevalence-sensitive criterion would
    chase specificity in the low-base-rate quadrats rather than a genuinely better cut.
    Candidate thresholds are every distinct score value (a full ROC sweep, not a grid).
    """
    y = np.asarray(y).astype(bool)
    order = np.argsort(s)
    s_sorted = s[order]
    thresholds = np.unique(s_sorted)
    best_j, best_t, best_stats = -np.inf, float(thresholds[0]), {}
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float(np.median(s)), {"sensitivity": float("nan"), "specificity": float("nan")}
    for t in thresholds:
        pred = s >= t
        tp = int((pred & y).sum())
        fp = int((pred & ~y).sum())
        fn = int((~pred & y).sum())
        tn = int((~pred & ~y).sum())
        sens = tp / n_pos
        spec = tn / n_neg
        j = sens + spec - 1
        if j > best_j:
            precision = tp / (tp + fp) if (tp + fp) else float("nan")
            f1 = 2 * precision * sens / (precision + sens) if (precision + sens) else float("nan")
            best_j, best_t = j, float(t)
            best_stats = {
                "sensitivity": sens, "specificity": spec, "precision": precision, "f1": f1,
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            }
    return best_t, best_stats


def _precision_threshold(y: np.ndarray, s: np.ndarray, min_precision: float = 0.5) -> float:
    """Highest (most conservative) threshold whose cumulative precision, sweeping
    scores from the top down, first reaches `min_precision`. If nothing clears it,
    returns a threshold above the max score (flags nothing) rather than silently
    falling back to a low-precision cut -- a candidate class with no reliable
    precision floor should contribute zero capacity, not a guess.
    """
    y = np.asarray(y).astype(bool)
    order = np.argsort(-s)
    s_sorted, y_sorted = s[order], y[order]
    cum_tp = np.cumsum(y_sorted)
    cum_n = np.arange(1, len(y_sorted) + 1)
    precision = cum_tp / cum_n
    ok = np.where(precision >= min_precision)[0]
    return float(s_sorted[ok[-1]]) if len(ok) else float(s_sorted[0]) + 1.0


def pooled_precision_threshold(
    t: pd.DataFrame, quadrats: list[str], score_col: str = "sppi",
    truth_col: str = "has_pv", min_precision: float = 0.5,
) -> float:
    """Single SPPI threshold fit by pooling `quadrats` together (no LOQO held-out unit --
    there is no national quadrat to hold out), for deployment as one national constant.
    Same convention `roofclf.score_buildings_national` already uses for its own
    `deployment_threshold`: one pooled precision-targeted cut, not a per-region value.
    """
    sub = t[t["quadrat"].isin(quadrats)]
    if sub.empty:
        raise ValueError(f"None of {quadrats} found in the table")
    return _precision_threshold(
        sub[truth_col].to_numpy(bool), sub[score_col].to_numpy(float), min_precision=min_precision
    )


def calibrate_threshold_loqo(
    t: pd.DataFrame, score_col: str = "sppi", truth_col: str = "has_pv",
    quadrat_col: str = "quadrat", criterion: str = "precision", min_precision: float = 0.5,
) -> pd.DataFrame:
    """Leave-one-quadrat-out SPPI threshold calibration, same protocol as
    `roofclf.evaluate`: fit on the other N-1 quadrats (pooled), apply to the held-out
    one, so every reported number is out-of-fold. Returns one row per quadrat with the
    threshold and its performance *on the held-out quadrat* (the deployment-honest
    number), not on the quadrats that set it.

    `criterion="precision"` (the default, and the right one for a capacity-contributing
    detector, where a false positive directly inflates the published number) picks the
    most conservative threshold clearing `min_precision` on the training pool.
    `criterion="youden"` instead maximizes sensitivity+specificity-1 -- a general
    classifier-evaluation criterion (matches `roofclf`'s own AUC-oriented framing) that
    this session measured trades away far too much precision for this specific use:
    median held-out precision 0.272 (youden) vs 0.524 (precision, min_precision=0.5),
    and youden left the arid quadrat (Quetta) at 4.9% precision -- unusably low.
    """
    rows = []
    for q in t[quadrat_col].unique():
        train = t[t[quadrat_col] != q]
        test = t[t[quadrat_col] == q]
        y_train, s_train = train[truth_col].to_numpy(bool), train[score_col].to_numpy(float)
        if criterion == "precision":
            thresh = _precision_threshold(y_train, s_train, min_precision=min_precision)
            train_stats: dict = {}
        elif criterion == "youden":
            thresh, train_stats = _youden_threshold(y_train, s_train)
        else:
            raise ValueError(f"unknown criterion {criterion!r}")
        y_test = test[truth_col].to_numpy(bool)
        s_test = test[score_col].to_numpy(float)
        pred = s_test >= thresh
        tp = int((pred & y_test).sum())
        fp = int((pred & ~y_test).sum())
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / y_test.sum() if y_test.sum() else float("nan")
        rows.append({
            "quadrat": q, "criterion": criterion, "threshold": round(thresh, 4),
            "n": len(test), "n_pv": int(y_test.sum()),
            "n_flagged": int(pred.sum()),
            "precision_held_out": round(precision, 4) if precision == precision else np.nan,
            "recall_held_out": round(recall, 4) if recall == recall else np.nan,
            "train_sensitivity": round(train_stats.get("sensitivity", np.nan), 4),
            "train_specificity": round(train_stats.get("specificity", np.nan), 4),
        })
    return pd.DataFrame(rows)


def candidate_sppi(geoms, aoi: str, cfg: dict, settings) -> np.ndarray:
    """Zonal SPPI per candidate footprint, from whatever local composites this AOI has.

    This module's own header restricts SPPI to BUILDING footprints specifically to keep
    bare rock/glacier/desert candidates (no building to attach to) structurally out of
    the SPPI path, rather than trusting a statistical cut to reject them. This function
    is the opposite: it scores the raw formula directly on a candidate's OWN polygon --
    exactly the `no_building`/`ground_adjacent` population the header excludes -- so it
    is a genuinely new, unvalidated use of the instrument, not the one the rest of this
    module describes.

    Measured 2026-08-02 at country scale: 2,421 OSM-confirmed real candidates vs. 694
    confirmed false positives (vegetation-cycle-refuted + epoch-persistent bright,
    `hard_negatives_veg.parquet` + `hard_negatives_confirmed.parquet`) give AUC 0.790
    overall (0.68-0.86 size-conditional) -- a meaningfully cleaner separation than the
    equivalent S1 backscatter check (`sar.py`, AUC 0.71-0.73) -- and a real, substantial
    catch rate at every cost level tried (see `DEFAULT_SPPI_MIN`'s threshold table: 57.5%
    of confirmed FP caught at just 2.3% cost to real PV, far ahead of the S1 veto's
    13.9%-caught/6.8%-cost). This is NOT a free win, though: at the building-classification
    threshold (-0.0183) real-cost balloons to 31.1%, because that threshold was tuned for
    a different task. It is also uneven across false-positive types: on the 21 confirmed
    bare-terrain FPs flagged by hand (Balochistan desert, Gilgit-Baltistan mountains --
    the population this function exists to catch), a low-cost cut (-0.05, matching the
    project's other vetoes' ~2-4% convention) only catches 19% of them, rising to 67% only
    at the much costlier -0.0183 cut. Vegetation-cycle and epoch-persistent false positives
    separate far more cleanly from real PV than this specific remote-terrain class does.
    The threshold was also calibrated (both the -0.0183 and the swept alternatives) on
    urban/industrial Punjab and Sindh quadrats -- none resemble the remote terrain this
    function is actually being asked to screen -- so read any of these numbers as
    encouraging, not proven (the same "ranking transfers, absolute rates do not" caution
    this project applies everywhere else).

    NaN where no local composite covers the point -- the caller must treat NaN as
    "unchecked", never as a veto (same contract as `vegetation.composite_max_ndvi`).
    """
    import geopandas as gpd
    import rasterio
    import rasterio.features as rfeat
    import rasterio.transform
    from rasterio.windows import Window, from_bounds
    from rasterio.windows import transform as window_transform

    from earthpv.config import LOCAL_BANDS
    from earthpv.local_source import CompositeIndex
    from earthpv.vegetation import _composites_region_dir

    # rasterio band indices are 1-based
    band_idx = {b: LOCAL_BANDS.index(b) + 1 for b in ("B02", "B03", "B08", "B11", "B12")}
    region_dir = _composites_region_dir(aoi, cfg, settings)
    idx = CompositeIndex(region_dir).index

    geoms = geoms.reset_index(drop=True)
    reps = gpd.GeoDataFrame(geometry=geoms.representative_point(), crs=geoms.crs)
    hits = gpd.sjoin(reps, idx[["path", "geometry"]], predicate="within", how="left")
    hits = hits[~hits.index.duplicated(keep="first")]

    out = np.full(len(geoms), np.nan)
    for tif_path, rows in hits.dropna(subset=["path"]).groupby("path").groups.items():
        rows = list(rows)
        with rasterio.open(tif_path) as src:
            gg = geoms.iloc[rows].to_crs(src.crs)
            for pos, geom in zip(rows, gg):
                # A bare Point (a hard-negative center, no polygon) has zero-area bounds
                # -- from_bounds degenerates to a <1 px window and would wrongly read as
                # "no coverage" rather than falling back to its own pixel, the same
                # sub-pixel convention `roofclf.zonal_mean_max` uses for tiny footprints.
                if geom.geom_type == "Point" or geom.area == 0:
                    rr, cc = rasterio.transform.rowcol(src.transform, geom.x, geom.y)
                    if not (0 <= rr < src.height and 0 <= cc < src.width):
                        continue
                    vals = src.read(list(band_idx.values()), window=Window(cc, rr, 1, 1))
                    b02, b03, b08, b11, b12 = vals.astype("float32").reshape(5)
                    out[pos] = compute_sppi(b02, b03, b08, b11, b12)
                    continue
                try:
                    win = from_bounds(*geom.bounds, transform=src.transform)
                    win = win.round_offsets().round_lengths().intersection(
                        Window(0, 0, src.width, src.height)
                    )
                except rasterio.errors.WindowError:
                    continue
                if win.width < 1 or win.height < 1:
                    continue
                arr = src.read(list(band_idx.values()), window=win).astype("float32")
                transform = window_transform(win, src.transform)
                mask = rfeat.geometry_mask(
                    [geom], out_shape=arr.shape[1:], transform=transform,
                    invert=True, all_touched=True,
                )
                if not mask.any():
                    continue
                b02, b03, b08, b11, b12 = (arr[i][mask].mean() for i in range(5))
                out[pos] = compute_sppi(b02, b03, b08, b11, b12)
    return out


def score_buildings_national_growth(
    aoi: str, composites, out_dir, min_roof_area_m2: float = 0.0,
    force: bool = False, limit: int = 0,
) -> "Path":
    """Per-building SPPI against BOTH epochs in one pass, nationally -- the spectral-index
    counterpart to the segmentation-based growth map (scripts/pv_growth_map.py).

    Unlike that map this needs no GPU inference: SPPI is a five-band formula read
    straight off the composite, so the only cost is the same per-cell building
    zonal-stats pass `roofclf.score_buildings_national` already proved tractable at this
    scale (~82M buildings nationally, ~2h16m for one epoch there) -- here it reads both
    layers (`CompositeIndex(layers=2)`: composite_0 current, composite_1 pre-boom) in one
    window per cell, so the building fetch and rasterization happen once, not twice.

    `delta_sppi = sppi_current - sppi_preboom` is the change signal to read. Either
    epoch's SPPI *level* alone carries the same adopter-propensity confound the
    step-change work measured for a static spectral index (~0.82 AUC from roof/context
    alone, before panels exist, [[earthpv-step-change-small-pv]]) -- differencing is the
    same move `postprocess.add_epoch_prior` already makes with the segmentation
    probability, applied here to SPPI instead.

    A handful of cells never got a composite_1 (see compose_loop_preboom.sh's log) --
    `CompositeIndex.read_window` raises `FileNotFoundError` there at `layers=2` (unlike
    the layers=1 "no coverage" `None` return), so those are caught and skipped with a
    warning rather than crashing the whole national run.
    """
    import logging
    from pathlib import Path

    import geopandas as gpd

    from earthpv.buildings import _iso3_for, fetch_vida_buildings
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    from earthpv.local_source import composite_index
    from earthpv.roofclf import BAND_NAMES, COMPOSITE_FILL, REFL_SCALE, zonal_mean_max
    from earthpv import overture

    log = logging.getLogger("sppi")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    iso3 = _iso3_for(cfg)
    if iso3 is None:
        raise ValueError(f"AOI '{aoi}' has no division.iso3 -> cannot locate VIDA buildings")

    i02, i03, i08, i11, i12 = (BAND_NAMES.index(b) for b in ("b02", "b03", "b08", "b11", "b12"))
    nb = len(BAND_NAMES)

    comp_idx = composite_index(str(composites), layers=2)
    con = overture.connect()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_cells, n_buildings, n_skipped_no_preboom, n_unscored_nodata = 0, 0, 0, 0
    for row in comp_idx.index.itertuples():
        if limit and n_cells >= limit:
            break
        cell = Path(row.path).parent.name
        out_path = out_dir / f"{cell}.parquet"
        if out_path.exists() and not force:
            continue
        bbox = row.geometry.bounds
        bu = fetch_vida_buildings(bbox, iso3, min_area_m2=min_roof_area_m2, con=con)
        if bu.empty:
            pd.DataFrame().to_parquet(out_path)
            continue
        # Half-open claim on the cell's own box, matching density.process_cell /
        # roofclf.score_buildings_national's convention so every building nationwide is
        # scored by exactly one cell.
        inside = bu.geometry.representative_point().within(row.geometry)
        bu = bu[inside.to_numpy()].reset_index(drop=True)
        if bu.empty:
            pd.DataFrame().to_parquet(out_path)
            continue

        try:
            res = comp_idx.read_window(bbox)
        except FileNotFoundError:
            log.warning(
                "cell %s: no composite_1 (pre-boom), skipping %d buildings", cell, len(bu)
            )
            n_skipped_no_preboom += 1
            continue
        if res is None:
            log.warning("cell %s: no composite coverage, skipping %d buildings", cell, len(bu))
            continue
        arr, transform, crs = res
        arr = arr.astype("float32") / REFL_SCALE
        current, preboom = arr[:nb], arr[nb : 2 * nb]
        bu_utm = bu.to_crs(crs)
        means_cur, _ = zonal_mean_max(bu_utm, current, transform, nodata=COMPOSITE_FILL)
        means_pre, _ = zonal_mean_max(bu_utm, preboom, transform, nodata=COMPOSITE_FILL)

        sppi_cur = compute_sppi(
            means_cur[i02], means_cur[i03], means_cur[i08], means_cur[i11], means_cur[i12]
        )
        sppi_pre = compute_sppi(
            means_pre[i02], means_pre[i03], means_pre[i08], means_pre[i11], means_pre[i12]
        )

        # NaN in either epoch means no valid composite pixel there (see
        # roofclf.zonal_mean_max) -- the row is kept so the building population stays
        # complete, but every SPPI column stays NaN rather than carrying the fill
        # value's spectral signature into a change signal.
        n_unscored_nodata += int((np.isnan(sppi_cur) | np.isnan(sppi_pre)).sum())

        result = gpd.GeoDataFrame({
            "cell": cell, "geometry": bu.geometry.to_numpy(),
            "roof_area_m2": bu["area_m2"].to_numpy(float),
            "sppi_current": sppi_cur, "sppi_preboom": sppi_pre,
            "delta_sppi": sppi_cur - sppi_pre,
        }, crs="EPSG:4326")
        result.to_parquet(out_path)

        n_cells += 1
        n_buildings += len(bu)
        if n_cells % 200 == 0:
            log.info(
                "Scored %d cells, %d buildings so far (%d cells skipped, no pre-boom composite)",
                n_cells, n_buildings, n_skipped_no_preboom,
            )

    log.info(
        "Done: %d cells scored this run, %d buildings, %d cells skipped (no pre-boom "
        "composite), %d buildings left unscored (SPPI NaN) for having no valid "
        "composite pixel in one or both epochs -> %s",
        n_cells, n_buildings, n_skipped_no_preboom, n_unscored_nodata, out_dir,
    )
    return out_dir


def sppi_only_incremental(
    t: pd.DataFrame, thresholds: pd.DataFrame, seg_threshold: float = 0.3,
    kwp_per_m2_module: float = 0.18,
) -> pd.DataFrame:
    """Per quadrat: buildings SPPI flags (at its LOQO-calibrated threshold) that the
    segmentation model's own raster does NOT already flag at its operating point
    (`seg_max < seg_threshold`) -- the incremental, SPPI-only, building-scoped
    candidates this module could add.

    Measures, per quadrat: how many buildings are flagged, the measured precision among
    them (`has_pv` ground truth -- this doubles as this candidate class's own `p_real`,
    the thing a raw SPPI raster has no way to supply), their total roof area, and the
    capacity impact of that area at `kwp_per_m2_module`, precision-weighted -- directly
    comparable to that quadrat's existing segmentation-only capacity
    (`data/roofclf/exp_scale_anchor.csv`'s `true_pv_area_m2` denominator).
    """
    thresh_by_quadrat = thresholds.set_index("quadrat")["threshold"].to_dict()
    rows = []
    for q, g in t.groupby("quadrat"):
        thresh = thresh_by_quadrat.get(q)
        if thresh is None:
            continue
        incremental = g[(g["sppi"] >= thresh) & (g["seg_max"] < seg_threshold)]
        n_flagged = len(incremental)
        n_true = int(incremental["has_pv"].sum())
        precision = n_true / n_flagged if n_flagged else float("nan")
        roof_area = float(incremental["roof_area_m2"].sum())
        true_pv_area_of_flagged = float(incremental["pv_area_true_m2"].sum())
        capacity_kwp = roof_area * kwp_per_m2_module * (precision if precision == precision else 0.0)
        rows.append({
            "quadrat": q,
            "n_buildings": len(g),
            "n_seg_missed_sppi_flagged": n_flagged,
            "n_true_positive": n_true,
            "precision": round(precision, 4) if precision == precision else np.nan,
            "incremental_roof_area_m2": round(roof_area, 1),
            "true_pv_area_in_flagged_m2": round(true_pv_area_of_flagged, 1),
            "incremental_capacity_kwp": round(capacity_kwp, 1),
        })
    return pd.DataFrame(rows)


def recall_effect(
    t: pd.DataFrame, thresholds: pd.DataFrame, seg_threshold: float = 0.3,
) -> pd.DataFrame:
    """Per quadrat: does treating an SPPI-flagged building as "detected" raise the
    matched fraction of true installations, the same question `capacity_calibration
    .derive_table`'s recall block asks nationally -- computed directly here since
    quadrat ground truth links `has_pv` to each building 1:1 (no distance-matching
    needed at this scale, unlike the national `new_lead_mask`-based check).
    """
    thresh_by_quadrat = thresholds.set_index("quadrat")["threshold"].to_dict()
    rows = []
    for q, g in t.groupby("quadrat"):
        thresh = thresh_by_quadrat.get(q)
        if thresh is None:
            continue
        true = g[g["has_pv"].astype(bool)]
        if true.empty:
            continue
        seg_recall = float((true["seg_max"] >= seg_threshold).mean())
        combined_recall = float(((true["seg_max"] >= seg_threshold) | (true["sppi"] >= thresh)).mean())
        rows.append({
            "quadrat": q, "n_true_installations": len(true),
            "seg_only_recall": round(seg_recall, 4),
            "combined_recall": round(combined_recall, 4),
            "recall_delta": round(combined_recall - seg_recall, 4),
        })
    return pd.DataFrame(rows)


def and_gate_regime_precision(
    t: pd.DataFrame, quadrats: list[str], thresholds: pd.DataFrame,
    roofclf_col: str = "p_oof", roofclf_thresh: float = 0.3064,
) -> dict:
    """Pooled roofclf-alone vs. AND-gate (roofclf AND SPPI agree) precision/recall
    across `quadrats`, matching `sub400_capacity.density_regime_precision`'s pooling
    convention (raw TP/FP/FN summed across quadrats, not an average of per-quadrat
    precisions -- the quadrats have very different sample sizes, so a plain average
    would let a small quadrat outvote a large one).

    Also reports roofclf-alone's precision AT THE AND-GATE'S OWN RECALL (found by
    sweeping `roofclf_col` from its top score down), the matched-recall comparison this
    project already uses when judging whether agreement adds anything beyond a stricter
    cutoff on roofclf alone. `thresholds` is `calibrate_threshold_loqo`'s output
    (LOQO-fit SPPI thresholds, one per held-out quadrat).

    Verified 2026-07-30 on the 9-quadrat table pooling Multan/Sialkot/Sundar (the three
    quadrats `sub400_capacity.select_calibrated_quadrats` excludes from the density-regime
    precision fit for over-predicting 2x+): AND-gate precision 0.578 vs. roofclf-alone
    0.462 at the same 0.153 recall -- a real +11.6 point gain, consistent with (a bit
    larger than) the individual per-quadrat deltas measured earlier (+10.7/+5.5/+5.1pp).
    The cost is recall: only 15% of true installations survive the AND-gate in this
    regime. This is not yet wired into any capacity figure -- see the module docstring
    and `docs/methods/density.md`'s SPPI section for why (no national proxy exists to
    say which cells this regime's precision should even apply to).
    """
    thresh_by_q = thresholds.set_index("quadrat")["threshold"].to_dict()
    g = t[t["quadrat"].isin(quadrats)]
    y = g["has_pv"].astype(bool).to_numpy()
    roof_pred = (g[roofclf_col] >= roofclf_thresh).to_numpy()
    row_thresh = g["quadrat"].map(thresh_by_q).fillna(np.inf).to_numpy()
    and_pred = roof_pred & (g["sppi"].to_numpy() >= row_thresh)

    def _stats(pred: np.ndarray) -> dict:
        tp = int((pred & y).sum())
        fp = int((pred & ~y).sum())
        fn = int((~pred & y).sum())
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        return {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn}

    roof_stats = _stats(roof_pred)
    and_stats = _stats(and_pred)

    # roofclf-alone at the AND-gate's own recall: sweep roofclf_col from the top down.
    order = np.argsort(-g[roofclf_col].to_numpy())
    y_sorted = y[order]
    n_pos = int(y.sum())
    cum_tp = np.cumsum(y_sorted)
    recalls = cum_tp / n_pos if n_pos else np.zeros(len(y_sorted))
    idx = min(int(np.searchsorted(recalls, and_stats["recall"])), len(recalls) - 1) if n_pos else 0
    matched_recall = float(recalls[idx]) if n_pos else float("nan")
    matched_precision = float(cum_tp[idx] / (idx + 1)) if n_pos else float("nan")

    return {
        "quadrats": quadrats,
        "n": int(len(g)),
        "roofclf_alone": {k: round(v, 4) if isinstance(v, float) else v for k, v in roof_stats.items()},
        "and_gate": {k: round(v, 4) if isinstance(v, float) else v for k, v in and_stats.items()},
        "roofclf_alone_at_matched_recall": {
            "recall": round(matched_recall, 4), "precision": round(matched_precision, 4),
        },
        "precision_gain_at_matched_recall": round(and_stats["precision"] - matched_precision, 4),
    }


def agreement_rate_by_quadrat(
    t: pd.DataFrame, thresholds: pd.DataFrame, roofclf_col: str = "p_oof",
    roofclf_thresh: float = 0.3064,
) -> pd.DataFrame:
    """Per quadrat: among buildings roofclf flags, what fraction does SPPI also confirm
    (at that quadrat's LOQO-fit threshold)? Tested 2026-07-30 as a candidate national
    stratification proxy -- "which cells look like the over-predicting Multan/Sialkot/
    Sundar regime vs. the well-calibrated one" is exactly the proxy this project has
    twice failed to find (existing candidate density anti-correlates with true small-PV
    rate; roofclf's own raw predicted rate does not separate the regimes either -- see
    `docs/methods/density.md`). A per-cell signal needs no ground truth to compute
    nationally, so if it tracked `rate_ratio` it would be a genuinely new, deployable
    handle.

    **Result: it does not, at least not on 9 quadrats.** Correlation against `rate_ratio`
    is weak among the 7 quadrats with an ordinary failure mode (Pearson r=0.19, Spearman
    rho=0.36, n=7) and only looks strong (r=0.50, rho=0.63) when Mardan and Quetta are
    included -- but those are exactly the two quadrats already separately diagnosed as
    distinct failure modes (threshold-transfer failure and arid false positives,
    respectively), so that apparent strength is almost certainly driven by two known
    outliers, not a general relationship. Karachi coastal (well-calibrated, rate_ratio
    0.68) shows a LOWER confirmation rate (0.10) than Sundar (over-predicting, rate_ratio
    1.71, confirmation rate 0.32) -- the opposite of what the hypothesis predicts. This
    is a negative result, kept here (not deleted) in the same spirit as
    `roofclf_capacity.py`: a record of what was tried and did not work, so it is not
    re-tried from scratch next time.
    """
    thresh_by_q = thresholds.set_index("quadrat")["threshold"].to_dict()
    rows = []
    for q, g in t.groupby("quadrat"):
        flagged = g[g[roofclf_col] >= roofclf_thresh]
        if flagged.empty:
            continue
        thresh = thresh_by_q.get(q)
        confirmed = float((flagged["sppi"] >= thresh).mean()) if thresh is not None else float("nan")
        rows.append({
            "quadrat": q, "n_flagged": int(len(flagged)),
            "confirmation_rate": round(confirmed, 4) if confirmed == confirmed else np.nan,
        })
    return pd.DataFrame(rows)
