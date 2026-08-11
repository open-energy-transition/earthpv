"""Validate this project's rooftop-PV methodology against Germany's MaStR register.

**Why Germany, and why this module exists.** Every accuracy statement this project can make
about Pakistan is bounded by 21 purposive calibration quadrats whose completeness is
owner-attested and epoch-relative (see `docs/methods/calibration-quadrats.md`). Germany is
the one place where a *legally complete* register exists: MaStR registration is mandatory
for grid-connected PV, so `data/calibration/mastr_gemeinden.parquet` is ground truth for
rooftop capacity per municipality, not a sample of it. That makes it the only available
external test of the assumptions the whole capacity chain rests on.

`calibrate.py` already calibrates a *probability raster* against MaStR. This module tests
the parts downstream of that, which nothing had ever checked:

1. `size_regime_shares` -- **the detection-floor claim.** The project's central argument for
   building the sub-400 m2 instruments at all is that the >= 400 m2 segmentation detector is
   blind to most rooftop capacity. That argument is currently supported by MaStR's "72.6% of
   rooftop capacity is in units <= 100 kWp", a proxy quoted at national level. MaStR carries
   exact per-unit capacity, so the share below the segmentation floor's own kWp equivalent
   (400 m2 of module x 0.18 kWp/m2 = 72 kWp) can be measured directly instead of proxied,
   nationally AND per municipality.
2. `small_pv_share_dispersion` -- **whether that share is transferable.** The project
   transfers the national figure to Pakistan as a single constant (the "MaStR-shape
   transfer", `docs/methods/density.md`). Measuring its spread across 11,000 German
   municipalities says how much a one-number transfer can be trusted.
3. `osm_completeness_by_count` -- **whether OSM can serve as the reference at all.** A
   natural plan is "use German OSM solar as the complete reference, since Germany is
   well-mapped". Measured here, non-circularly (by unit COUNT against the register, not by
   area against an assumed kWp/m2), that plan does not survive -- see the function's
   docstring for the numbers. Kept as a measured negative result, because the same
   reasoning is applied to Pakistan's OSM elsewhere in this project and deserves the same
   scepticism.
4. `validate_density_against_mastr` -- **the end-to-end harness.** Zonal-joins an AOI's
   `density` grid onto German municipalities and compares each estimator against MaStR's own
   rooftop capacity. This is the piece that turns "run the atlas on Germany" into one
   command; it is deliberately written to refuse to report a national number from partial
   imagery coverage, because that is the failure mode it would otherwise walk straight into
   (see `_coverage_guard`).

**What is NOT implemented here, and why.** A full Germany evidence atlas needs three things
this machine does not currently have: composites for 62 of Germany's 76 MGRS tiles
(`data/composites/germany/` is absent; only 14 tiles exist in the sibling project), a
building layer with small roofs (only Overture >= 500 m2 exists for Germany, and `roofclf`
needs the sub-400 m2 population VIDA provides -- `data/vida/DEU.parquet` is absent), and
Rule-1-style mapped quadrats to fit `roofclf` on. `docs/methods/mastr-validation.md`
records the acquisition runbook. Item 4 here runs on whatever coverage exists and reports
its own coverage, so it becomes the real end-to-end check the moment that data lands
rather than needing to be written then.

Everything here runs in the default (no-torch) env and needs no GPU.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_CALIB_DIR = Path("data/calibration")
DEFAULT_MASTR_SQLITE = Path.home() / ".open-MaStR/data/sqlite/open-mastr.db"
DEFAULT_CUTOFF = "2025-09-30"

# The segmentation detector's >= 400 m2 floor, expressed in the register's own units:
# 400 m2 of module area x DEFAULT_KWP_PER_M2_MODULE (0.18) = 72 kWp. This is the threshold
# that actually matters for the blindness claim; 100 kWp is the round number MaStR
# reporting conventions favour and is what this project has quoted so far.
SEG_FLOOR_KWP = 72.0
DEFAULT_KWP_THRESHOLDS = (10.0, 30.0, SEG_FLOOR_KWP, 100.0, 300.0, 1000.0)

# A municipality needs enough registered rooftop capacity for a ratio against it to mean
# anything; below this a single unit dominates and the share is noise.
MIN_GEMEINDE_KW = 100.0


def _num(v: float, digits: int = 4) -> float | None:
    """Round for a JSON report, mapping NaN/inf to None.

    `json.dumps` emits a bare `NaN` for a float nan, which is invalid JSON that most
    parsers reject -- so a degenerate input (a Spearman over a constant column, a ratio
    with a zero denominator) would produce a report file that cannot be read back. Caught
    by `tests/test_mastr_validation.py`'s constant-share case, which is exactly the
    degenerate shape real data never has and a synthetic fixture always does.
    """
    f = float(v)
    return round(f, digits) if np.isfinite(f) else None


def rooftop_unit_counts(
    sqlite_path: Path = DEFAULT_MASTR_SQLITE,
    cutoff: str = DEFAULT_CUTOFF,
    kwp_thresholds: tuple[float, ...] = DEFAULT_KWP_THRESHOLDS,
) -> pd.DataFrame:
    """Per-municipality rooftop-PV unit counts and capacity split by unit size, from the
    MaStR sqlite.

    `mastr.aggregate_gemeinden` already writes per-AGS rooftop *capacity*, but its
    `n_units` column counts every solar row in the municipality -- including the ~1.5M
    "Steckerfertige Solaranlage" (balcony) units `mastr.py`'s own comment excludes from the
    capacity columns -- so it cannot be used as a rooftop unit count. This aggregates
    rooftop units only, applying exactly `mastr.aggregate_gemeinden`'s filters (same
    `ArtDerSolaranlage`, same commissioning cutoff, same in-operation test), verified by
    reproducing its national `kw_rooftop` total to the kW.

    Returns one row per `ags` with `n_rooftop_units`, `kw_rooftop`, and for each threshold
    `t` in `kwp_thresholds` a pair `n_le_<t>` / `kw_le_<t>` -- the count and summed capacity
    of units at or below `t` kWp. Aggregated in SQL rather than pandas because the
    unfiltered table is ~5M rows.
    """
    import sqlalchemy as sa

    from earthpv.mastr import ROOFTOP_ART

    if len(ROOFTOP_ART) != 1:
        raise NotImplementedError(
            f"rooftop_unit_counts assumes a single ArtDerSolaranlage value, got {ROOFTOP_ART}"
        )
    cols = ",\n".join(
        f'       SUM(CASE WHEN "Bruttoleistung" <= {t} THEN 1 ELSE 0 END) AS "n_le_{t:g}",\n'
        f'       SUM(CASE WHEN "Bruttoleistung" <= {t} THEN "Bruttoleistung" ELSE 0 END) '
        f'AS "kw_le_{t:g}"'
        for t in kwp_thresholds
    )
    query = f"""
        SELECT "Gemeindeschluessel" AS ags,
               COUNT(*) AS n_rooftop_units,
               SUM("Bruttoleistung") AS kw_rooftop,
{cols}
        FROM solar_extended
        WHERE "Inbetriebnahmedatum" <= :cutoff
          AND "ArtDerSolaranlage" = :art
          AND "Gemeindeschluessel" IS NOT NULL
          AND "Bruttoleistung" IS NOT NULL
          AND ("EinheitBetriebsstatus" = 'In Betrieb'
               OR ("DatumEndgueltigeStilllegung" IS NOT NULL
                   AND "DatumEndgueltigeStilllegung" > :cutoff))
        GROUP BY "Gemeindeschluessel"
    """
    engine = sa.create_engine(f"sqlite:///{Path(sqlite_path)}")
    df = pd.read_sql(sa.text(query), engine, params={"cutoff": cutoff, "art": ROOFTOP_ART[0]})
    log.info(
        "MaStR rooftop units by AGS: %d municipalities, %d units, %.2f GWp (cutoff %s)",
        len(df), int(df.n_rooftop_units.sum()), df.kw_rooftop.sum() / 1e6, cutoff,
    )
    return df


def size_regime_shares(
    counts: pd.DataFrame,
    kwp_thresholds: tuple[float, ...] = DEFAULT_KWP_THRESHOLDS,
    min_gemeinde_kw: float = MIN_GEMEINDE_KW,
) -> dict:
    """What share of Germany's rooftop PV capacity sits below each unit-size threshold --
    the detection-floor claim, measured against a complete register instead of proxied.

    The number that matters is `share_below_seg_floor`: capacity in units at or below
    `SEG_FLOOR_KWP` (72 kWp = the 400 m2 detection floor converted at the project's own
    module constant). Everything below it is capacity the >= 400 m2 segmentation detector
    cannot see even in principle, so it bounds how much of a country's rooftop total the
    sub-400 m2 instruments are responsible for.

    Also returns the same shares by unit COUNT, which are much higher than by capacity and
    are the ones easy to quote misleadingly: a country can have 98% of its rooftop
    *installations* below the floor while they carry a smaller share of its *capacity*.
    Both are reported so the distinction cannot be lost.

    `per_gemeinde` carries the distribution of the seg-floor share across municipalities
    with at least `min_gemeinde_kw` of rooftop capacity, which is what
    `small_pv_share_dispersion` reads.
    """
    total_kw = float(counts.kw_rooftop.sum())
    total_n = int(counts.n_rooftop_units.sum())
    by_capacity, by_count = {}, {}
    for t in kwp_thresholds:
        by_capacity[f"le_{t:g}_kwp"] = round(float(counts[f"kw_le_{t:g}"].sum()) / total_kw, 4)
        by_count[f"le_{t:g}_kwp"] = round(float(counts[f"n_le_{t:g}"].sum()) / total_n, 4)

    big = counts[counts.kw_rooftop >= min_gemeinde_kw]
    share_col = big[f"kw_le_{SEG_FLOOR_KWP:g}"] / big.kw_rooftop
    return {
        "cutoff_source": "mastr.aggregate_gemeinden filters",
        "seg_floor_kwp": SEG_FLOOR_KWP,
        "seg_floor_derivation": "400 m2 module area x 0.18 kWp/m2 (DEFAULT_KWP_PER_M2_MODULE)",
        "n_gemeinden": int(len(counts)),
        "n_rooftop_units": total_n,
        "total_kw_rooftop": round(total_kw, 1),
        "capacity_share_below": by_capacity,
        "count_share_below": by_count,
        "share_below_seg_floor": by_capacity[f"le_{SEG_FLOOR_KWP:g}_kwp"],
        "count_share_below_seg_floor": by_count[f"le_{SEG_FLOOR_KWP:g}_kwp"],
        "per_gemeinde": {
            "n": int(len(big)),
            "min_gemeinde_kw": min_gemeinde_kw,
            "mean": round(float(share_col.mean()), 4),
            "sd": _num(share_col.std()),
            "quantiles": {
                f"p{int(q * 100)}": round(float(share_col.quantile(q)), 4)
                for q in (0.05, 0.25, 0.5, 0.75, 0.95)
            },
        },
    }


def small_pv_share_dispersion(
    counts: pd.DataFrame, min_gemeinde_kw: float = MIN_GEMEINDE_KW
) -> dict:
    """How transferable the national small-PV share actually is, measured as its spread
    across municipalities.

    This project uses Germany's national "share of rooftop capacity below X kWp" as a
    shape it transfers to Pakistan (`docs/methods/density.md`'s MaStR-shape transfer, which
    implied roughly 5.9 GWp of Pakistani sub-400 m2 capacity). A transfer like that is only
    as good as the constancy of the thing transferred. Measured here per municipality --
    and it is not constant: the share is highly dispersed, so a single-number transfer to
    another country carries far more uncertainty than the national point figure suggests.

    Also reports whether the share varies systematically with a municipality's own total
    rooftop capacity (Spearman), because that is the axis along which a transfer is most
    likely to be wrong in a *predictable* direction: capacity concentrates in municipalities
    with large industrial roofs, which have a lower small-PV share than the median
    municipality, so an unweighted average over municipalities and a capacity-weighted one
    are different numbers and only the latter is comparable to a national total.
    """
    big = counts[counts.kw_rooftop >= min_gemeinde_kw].copy()
    for name, col in (("seg_floor", f"kw_le_{SEG_FLOOR_KWP:g}"), ("le100", "kw_le_100")):
        big[f"share_{name}"] = big[col] / big.kw_rooftop

    out: dict = {"n_gemeinden": int(len(big)), "min_gemeinde_kw": min_gemeinde_kw}
    for name in ("seg_floor", "le100"):
        s = big[f"share_{name}"]
        # Capacity-weighted mean is the one comparable to the national share; the plain
        # mean over municipalities weights a 200 kW village the same as Munich.
        weighted = float(np.average(s, weights=big.kw_rooftop))
        rho = float(pd.Series(s).corr(big.kw_rooftop, method="spearman"))
        out[name] = {
            "national_share": round(float(big[f"kw_le_{'100' if name == 'le100' else f'{SEG_FLOOR_KWP:g}'}"].sum() / big.kw_rooftop.sum()), 4),
            "capacity_weighted_mean": round(weighted, 4),
            "unweighted_mean": round(float(s.mean()), 4),
            "sd": _num(s.std()),
            "quantiles": {
                f"p{int(q * 100)}": round(float(s.quantile(q)), 4)
                for q in (0.05, 0.25, 0.5, 0.75, 0.95)
            },
            "spearman_vs_gemeinde_kw": _num(rho),
            "p90_over_p10_ratio": _num(
                float(s.quantile(0.9) / max(s.quantile(0.1), 1e-9)), 3
            ),
        }
    return out


def osm_completeness_by_count(
    counts: pd.DataFrame,
    solar_path: Path,
    gemeinden_path: Path,
    thresholds: tuple[float, ...] = (0.3, 0.5, 0.8),
    min_units: int = 30,
    max_ground_share: float = 0.02,
    kw_ground: pd.Series | None = None,
) -> dict:
    """Is German OSM complete enough to serve as this project's reference for small PV?
    Measured, non-circularly. **Answer: no** -- kept as a measured negative result.

    The circularity worth avoiding: `data/calibration/completeness.parquet`'s own
    `completeness` column is `0.18 * osm_area / kw_rooftop`, i.e. it already assumes the
    kWp/m2 constant. Selecting "well-mapped" municipalities with it and then measuring
    `kw_rooftop / osm_area` to test that same constant is circular -- the selection is on
    the estimator. This function instead measures completeness by unit COUNT against the
    register, which involves no area and no conversion constant at all, and only then looks
    at the implied kWp/m2.

    Measured 2026-08-11 (159,444 OSM solar features nationally, MaStR 4,411,015 rooftop
    units): national count completeness **3.6%**, and the well-mapped tail is far too thin
    and too heterogeneous to calibrate anything -- 55 municipalities at >= 30% completeness,
    18 at >= 50%, 3 at >= 80%, with the pooled implied kWp/m2 swinging 0.239 -> 0.083 ->
    0.069 across those three cutoffs and per-municipality values spanning 0.02 to 0.99
    (against the project's 0.18). That instability is not sampling noise around a true
    value: it is mapper behaviour, because nothing in OSM says whether a `generator:source=
    solar` polygon outlines the panel array or the whole roof it sits on. So this route
    cannot validate the module constant, and the constant stays as calibrated.

    Two consequences worth carrying beyond this function. First, "Germany is well mapped in
    OSM" is true for buildings and false for rooftop PV, and the two get conflated easily.
    Second, the same scepticism applies to this project's Pakistani OSM reference: it is
    used as a recall denominator and as the Verified tier's own population, and it is not
    exempt from the array-vs-roof ambiguity measured here.

    `max_ground_share` restricts to municipalities the register says have essentially no
    ground-mount, which removes the need to classify OSM features as rooftop vs ground at
    all (a classification that would itself need a building layer Germany lacks here).
    """
    import geopandas as gpd

    from earthpv.labels import geodesic_area_m2

    solar = gpd.read_parquet(solar_path)
    gem = gpd.read_parquet(gemeinden_path)
    solar = solar.copy()
    solar["area_m2"] = [geodesic_area_m2(g) for g in solar.geometry]
    pts = solar.copy()
    pts["geometry"] = pts.geometry.representative_point()
    joined = gpd.sjoin(pts, gem[["ags", "geometry"]], predicate="within", how="inner")
    osm = joined.groupby("ags").agg(
        osm_n=("area_m2", "size"), osm_area_m2=("area_m2", "sum")
    ).reset_index()

    m = counts.merge(osm, on="ags", how="left")
    m[["osm_n", "osm_area_m2"]] = m[["osm_n", "osm_area_m2"]].fillna(0.0)
    if kw_ground is not None:
        m["kw_ground"] = m.ags.map(kw_ground).fillna(0.0)
    else:
        m["kw_ground"] = 0.0
    m["ground_share"] = m.kw_ground / (m.kw_rooftop + m.kw_ground).clip(lower=1e-9)
    m["count_completeness"] = m.osm_n / m.n_rooftop_units.clip(lower=1)

    tiers = []
    for t in thresholds:
        sel = m[
            (m.count_completeness >= t) & (m.n_rooftop_units >= min_units)
            & (m.ground_share < max_ground_share) & (m.osm_area_m2 > 0)
        ]
        per_gem = (sel.kw_rooftop / sel.osm_area_m2.clip(lower=1.0)) if len(sel) else pd.Series(dtype=float)
        tiers.append({
            "min_count_completeness": t,
            "n_gemeinden": int(len(sel)),
            "n_rooftop_units": int(sel.n_rooftop_units.sum()),
            "osm_area_km2": round(float(sel.osm_area_m2.sum()) / 1e6, 3),
            "kw_rooftop": round(float(sel.kw_rooftop.sum()), 1),
            "pooled_implied_kwp_per_m2": (
                round(float(sel.kw_rooftop.sum() / sel.osm_area_m2.sum()), 4) if len(sel) else None
            ),
            "per_gemeinde_implied_kwp_per_m2_quantiles": (
                {f"p{int(q * 100)}": round(float(per_gem.quantile(q)), 4)
                 for q in (0.1, 0.25, 0.5, 0.75, 0.9)} if len(sel) else None
            ),
        })

    pooled = [t["pooled_implied_kwp_per_m2"] for t in tiers if t["pooled_implied_kwp_per_m2"]]
    return {
        "verdict": (
            "OSM is not a usable complete reference for German rooftop PV: national count "
            "completeness is a few percent and the implied kWp/m2 is unstable across "
            "completeness cutoffs by more than the constant itself, so this route cannot "
            "validate DEFAULT_KWP_PER_M2_MODULE. Negative result, not a blocked one."
        ),
        "n_osm_features_national": int(len(solar)),
        "n_osm_features_in_a_gemeinde": int(len(joined)),
        "national_count_completeness": round(
            float(m.osm_n.sum() / max(m.n_rooftop_units.sum(), 1)), 4
        ),
        "count_completeness_quantiles": {
            f"p{int(q * 100)}": round(float(m.count_completeness.quantile(q)), 4)
            for q in (0.5, 0.75, 0.9, 0.95, 0.99)
        },
        "tiers": tiers,
        "pooled_implied_kwp_per_m2_spread": (
            round(max(pooled) / min(pooled), 2) if len(pooled) > 1 else None
        ),
        "project_kwp_per_m2_module": 0.18,
        "min_units": min_units,
        "max_ground_share": max_ground_share,
    }


def _coverage_guard(joined: pd.DataFrame, gem_total: int) -> dict:
    """Coverage bookkeeping for `validate_density_against_mastr`, and the reason it exists.

    A density run covering 4 of Germany's 76 MGRS tiles will happily produce a national sum
    that is ~5% of the truth, and the resulting "slope" would read as a catastrophic
    underestimate rather than as missing imagery. So the harness reports how many
    municipalities it actually covered, refuses to emit a national comparison below
    `MIN_NATIONAL_COVERAGE`, and always scopes its regression to the covered subset.
    """
    covered = int(len(joined))
    return {
        "n_gemeinden_covered": covered,
        "n_gemeinden_total": gem_total,
        "coverage_frac": round(covered / max(gem_total, 1), 4),
    }


MIN_NATIONAL_COVERAGE = 0.9


def validate_density_against_mastr(
    density_dir: Path,
    counts: pd.DataFrame,
    gemeinden_path: Path,
    estimators: tuple[str, ...] = ("est_mwp_rc_roof", "est_mwp_cal", "est_mwp_det", "est_mwp_exp"),
    min_gemeinde_kw: float = MIN_GEMEINDE_KW,
) -> dict:
    """Compare a `density` run's rooftop estimators against MaStR's registered rooftop
    capacity, per municipality.

    This is the end-to-end check the project cannot run in Pakistan: MaStR is complete, so
    a slope of 1.0 against it is a real accuracy statement and not a comparison of two
    estimates. Cells are assigned to municipalities by cell centroid (the same convention
    `density.aggregate`'s own region layer uses), which is coarse at 0.1 deg against German
    municipality sizes -- so this is a check on aggregate level and rank correlation, not on
    per-municipality values, and the returned `caveats` says so.

    Reports, on the covered subset only: the origin-forced OLS slope (the multiplicative
    bias -- 1.0 means the estimator is right on average), the median per-municipality ratio
    (robust to the long tail), Spearman rank correlation (does it put capacity in the right
    places), and log-log Pearson. Refuses a national total below `MIN_NATIONAL_COVERAGE` of
    municipalities, because partial imagery coverage reads exactly like a real underestimate.
    """
    import geopandas as gpd

    density_dir = Path(density_dir)
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    gem = gpd.read_parquet(gemeinden_path)
    present = [e for e in estimators if e in grid.columns]
    if not present:
        raise ValueError(
            f"{density_dir}/grid.geoparquet has none of {estimators} -- has `earthpv density` "
            "run for this AOI?"
        )
    missing = [e for e in estimators if e not in grid.columns]

    centroids = gpd.GeoDataFrame(
        grid[present],
        geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs="EPSG:4326",
    )
    j = gpd.sjoin(centroids, gem[["ags", "name", "geometry"]], predicate="within", how="inner")
    agg = j.groupby("ags", as_index=False)[present].sum()
    m = agg.merge(counts[["ags", "kw_rooftop", f"kw_le_{SEG_FLOOR_KWP:g}"]], on="ags", how="inner")
    m = m[m.kw_rooftop >= min_gemeinde_kw]

    out: dict = {
        "density_dir": str(density_dir),
        **_coverage_guard(m, int(len(gem))),
        "estimators_missing_from_grid": missing,
        "min_gemeinde_kw": min_gemeinde_kw,
        "caveats": [
            "cells are assigned to municipalities by 0.1 deg cell centroid, which is coarse "
            "against German municipality sizes -- read the aggregate slope and the rank "
            "correlation, not per-municipality values",
            "MaStR counts registered capacity at its commissioning date; the imagery "
            "composite is a different window, so a small timing mismatch is expected",
        ],
        "results": {},
    }
    if m.empty:
        out["verdict"] = "no municipality is covered by this density run -- nothing to compare"
        return out

    truth = m.kw_rooftop.to_numpy(float) / 1000.0  # MWp, to match the estimators' units
    for e in present:
        pred = m[e].to_numpy(float)
        ok = (truth > 0) & np.isfinite(pred)
        slope = float((pred[ok] * truth[ok]).sum() / (truth[ok] ** 2).sum())
        ratio = pred[ok] / truth[ok]
        pos = ok & (pred > 0)
        out["results"][e] = {
            "n": int(ok.sum()),
            "sum_pred_mwp": round(float(pred[ok].sum()), 1),
            "sum_truth_mwp": round(float(truth[ok].sum()), 1),
            "slope_ols_origin": round(slope, 4),
            "median_ratio": round(float(np.median(ratio)), 4),
            "spearman_rho": _num(
                pd.Series(pred[ok]).corr(pd.Series(truth[ok]), method="spearman")
            ),
            "loglog_pearson_r": (
                _num(np.corrcoef(np.log(pred[pos]), np.log(truth[pos]))[0, 1])
                if pos.sum() > 2 else None
            ),
            "frac_municipalities_zero_pred": round(float((pred[ok] == 0).mean()), 4),
        }
    if out["coverage_frac"] < MIN_NATIONAL_COVERAGE:
        out["verdict"] = (
            f"PARTIAL COVERAGE ({out['coverage_frac']:.1%} of municipalities): the slopes "
            "below describe only the covered subset and no national total is reported. "
            "Germany needs composites for its remaining MGRS tiles before this is a "
            "national accuracy statement -- see docs/methods/mastr-validation.md."
        )
    else:
        out["verdict"] = "national coverage sufficient; slopes are national accuracy estimates"
    return out


def run_mastr_validation(
    aoi: str = "germany",
    density_dir: Path | None = None,
    calib_dir: Path = DEFAULT_CALIB_DIR,
    sqlite_path: Path = DEFAULT_MASTR_SQLITE,
    solar_path: Path | None = None,
    cutoff: str = DEFAULT_CUTOFF,
    out: Path | None = None,
    skip_osm: bool = False,
) -> Path:
    """Run every available MaStR check and write one JSON report.

    `rooftop_unit_counts` is cached to `<calib_dir>/mastr_rooftop_counts.parquet` (the sqlite
    query takes ~40 s over ~5M rows); delete that file to re-derive. The density comparison
    is skipped with a warning when the AOI has no density run, so the register-internal
    checks -- the ones that need no imagery at all -- always produce their numbers.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    calib_dir = Path(calib_dir)
    calib_dir.mkdir(parents=True, exist_ok=True)
    counts_path = calib_dir / "mastr_rooftop_counts.parquet"
    if counts_path.exists():
        counts = pd.read_parquet(counts_path)
        log.info("Reusing %s (%d municipalities)", counts_path, len(counts))
    else:
        counts = rooftop_unit_counts(sqlite_path, cutoff=cutoff)
        counts.to_parquet(counts_path)
        log.info("Wrote %s", counts_path)

    report: dict = {
        "aoi": aoi,
        "mastr_cutoff": cutoff,
        "detection_floor": size_regime_shares(counts),
        "share_transferability": small_pv_share_dispersion(counts),
    }

    gem_path = calib_dir / "vg250_gem.parquet"
    if not skip_osm and solar_path and Path(solar_path).exists() and gem_path.exists():
        kw_ground = None
        gem_kw = calib_dir / "mastr_gemeinden.parquet"
        if gem_kw.exists():
            g = pd.read_parquet(gem_kw)
            kw_ground = g.set_index("ags")["kw_ground"]
        report["osm_as_reference"] = osm_completeness_by_count(
            counts, Path(solar_path), gem_path, kw_ground=kw_ground
        )
    else:
        log.warning("Skipping the OSM-completeness check (no solar pull / no municipality file)")

    dd = Path(density_dir) if density_dir else Path("data/predictions") / aoi / "density"
    if (dd / "grid.geoparquet").exists() and gem_path.exists():
        report["density_vs_mastr"] = validate_density_against_mastr(dd, counts, gem_path)
    else:
        log.warning(
            "No density run at %s -- the end-to-end comparison is skipped. This is the "
            "expected state for Germany until its composites and inference exist; see "
            "docs/methods/mastr-validation.md.", dd,
        )
        report["density_vs_mastr"] = {
            "status": "absent",
            "density_dir": str(dd),
            "blocked_on": "Germany composites + inference (see docs/methods/mastr-validation.md)",
        }

    out = Path(out) if out else Path("results") / f"{aoi}_mastr_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    log.info("Wrote %s", out)
    return out
