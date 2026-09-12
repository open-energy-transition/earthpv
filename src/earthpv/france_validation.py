"""Validate earthpv against France's national production register, and against
OpenPVMapper -- the country's independent nationwide rooftop PV database.

This is the France counterpart to `mastr_validation.py`, and the two registers are
*not* the same instrument. Germany's MaStR publishes per-unit rows with an explicit
rooftop/ground field and coordinates at and above 30 kWp. France's ODRE register
publishes:

  * individual rows only at and above **36 kW** (`REGISTER_SMALL_CUTOFF_KW`), and
  * everything below that as **per-commune / per-IRIS aggregates** carrying a unit
    count and a total capacity, but no unit sizes,
  * **no coordinates at all**, and
  * **no rooftop/ground attribute**.

Three consequences drive every design choice in this module:

1. **The 72 kWp floor share is still exactly computable**, because the censoring cliff
   (36 kW) sits below the floor (72 kWp = 400 m2 x 0.18 kWp/m2). Capacity below the
   floor is "all aggregate capacity + individual units at or below 72 kW", with no
   interpolation. Thresholds *below* 36 kW are not recoverable and are reported as
   censored rather than estimated -- see `size_regime_shares`.

2. **There is no rooftop denominator.** Germany's headline "65.5% of *rooftop*
   capacity sits below the floor" has no exact French analogue. This module therefore
   reports the share against two explicit denominators, all-PV and BT-only
   (low-voltage connections, where ground-mount farms are rare), and never presents
   one of them as "the" French number. France's fleet is far more ground-mount-heavy
   than Germany's, so the all-PV share understates rooftop blindness badly.

3. **`p_unmapped` cannot be reproduced.** Germany's precision instrument works by
   testing whether a registered unit's coordinate falls inside a candidate polygon.
   With no coordinates in the French register, that check does not exist here, and
   this module deliberately offers no substitute for it.

What France *does* provide that Germany does not is dated vintages of the same
register (year-end 2017 onward), which let the register be read back to the epoch a
quadrat was mapped against instead of compared across a multi-year gap -- see
`interpolate_to_date`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# The French publication cliff: below this, units appear only inside per-commune
# aggregates (arrete du 7 juillet 2016). Not a physical threshold.
REGISTER_SMALL_CUTOFF_KW = 36.0

# Same floor as Germany, and derived the same way, so the two countries' shares are
# comparable: 400 m2 of module area x DEFAULT_KWP_PER_M2_MODULE (0.18 kWp/m2).
SEG_FLOOR_KWP = 72.0

# Module area equivalent of the register's small-aggregate band, used to match the
# hand-mapped polygons to the only register quantity that covers the same population.
SMALL_BAND_M2 = REGISTER_SMALL_CUTOFF_KW / 0.18  # 200 m2

# Communes below this drop out of ratio statistics: a 3 kW hamlet's ratio is noise.
MIN_COMMUNE_KW = 100.0

MIN_NATIONAL_COVERAGE = 0.9


def _num(v, digits: int = 4):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return round(float(v), digits)


def load_register(path: Path) -> pd.DataFrame:
    """One tidy row per ODRE register entry, PV only.

    `is_aggregate` separates the two record types that must never be pooled without
    thought: an aggregate row's `kw` is the SUM over `n_units` censored installations,
    so treating it as a unit size (it is often several hundred kW) silently reclassifies
    a village's worth of 5 kW roofs as one industrial plant. `kw_per_unit` is the only
    per-unit quantity the aggregates support.
    """
    df = pd.read_csv(path, sep=";", low_memory=False)
    df = df[df.technologie.astype(str).str.startswith("Photo")].copy()
    df["is_aggregate"] = df.nominstallation.astype(str).str.startswith("Agr")
    df["kw"] = pd.to_numeric(df.puismaxinstallee, errors="coerce")
    df["n_units"] = pd.to_numeric(df.nbinstallations, errors="coerce").fillna(1).astype(int)
    df["insee"] = df.codeinseecommune.astype(str).str.strip()
    df["tension"] = df.tensionraccordement.astype(str)
    # Older year-end vintages of the same publication omit the ISO date column and
    # carry only the dd/mm/yyyy text field, so neither can be assumed present.
    if "datemiseenservice_date" in df.columns:
        df["commissioned"] = pd.to_datetime(df.datemiseenservice_date, errors="coerce")
    elif "datemiseenservice" in df.columns:
        df["commissioned"] = pd.to_datetime(
            df.datemiseenservice, errors="coerce", format="%d/%m/%Y"
        )
    else:
        df["commissioned"] = pd.NaT
    df = df[df.kw.notna() & (df.kw > 0) & df.insee.ne("nan")]
    df["kw_per_unit"] = df.kw / df.n_units.clip(lower=1)
    return df.reset_index(drop=True)


def commune_capacity(reg: pd.DataFrame) -> pd.DataFrame:
    """Per-commune capacity table, split at both the censoring cliff and the seg floor.

    `kw_le_72` is exact, not interpolated: every aggregate unit is below 36 kW by
    construction, so the only judgement is which *individual* units fall under the
    floor, and those carry their own capacity.
    """
    agg = reg[reg.is_aggregate]
    ind = reg[~reg.is_aggregate]
    bt = reg[reg.tension.eq("BT")]

    def s(frame, col="kw"):
        return frame.groupby("insee")[col].sum()

    out = pd.DataFrame({
        "kw_total": s(reg),
        "kw_small_agg": s(agg),
        "kw_individual": s(ind),
        "kw_bt": s(bt),
        "kw_ind_le_72": s(ind[ind.kw <= SEG_FLOOR_KWP]),
        "kw_bt_ind_le_72": s(bt[~bt.is_aggregate & (bt.kw <= SEG_FLOOR_KWP)]),
        "kw_bt_small_agg": s(bt[bt.is_aggregate]),
        "n_small_units": agg.groupby("insee").n_units.sum(),
        "n_individual": ind.groupby("insee").size(),
    }).fillna(0.0)

    out["kw_le_72"] = out.kw_small_agg + out.kw_ind_le_72
    out["kw_above_floor"] = out.kw_total - out.kw_le_72
    out["kw_bt_le_72"] = out.kw_bt_small_agg + out.kw_bt_ind_le_72
    out["kw_bt_above_floor"] = out.kw_bt - out.kw_bt_le_72
    return out.reset_index().rename(columns={"insee": "insee"})


def size_regime_shares(cc: pd.DataFrame, min_commune_kw: float = MIN_COMMUNE_KW) -> dict:
    """What share of French PV capacity sits below the 400 m2 / 72 kWp detection floor.

    Reported against two denominators because France's register carries no
    rooftop/ground field:

      * `all_pv` -- every registered PV installation. France's fleet is heavily
        ground-mount, and ground-mount is essentially all above the floor, so this is a
        firm LOWER bound on the rooftop share.
      * `bt_only` -- low-voltage connections only. Utility-scale farms connect at HTA or
        above, so this is a rooftop-leaning proxy and an upper-leaning bound. Large
        BT-connected ground arrays keep it from being exact.

    The truth for rooftop lies between them. Germany's directly-measured rooftop figure
    (0.655) is quoted alongside precisely so the two are not confused: it is not
    reproducible here, and this module does not pretend otherwise.

    Sub-36 kW thresholds are censored by the register's own publication rule and are
    returned as None rather than modelled -- the mean unit size inside the aggregates is
    reported instead, which is the only per-unit fact the aggregates support.
    """
    tot = float(cc.kw_total.sum())
    below = float(cc.kw_le_72.sum())
    tot_bt = float(cc.kw_bt.sum())
    below_bt = float(cc.kw_bt_le_72.sum())
    n_small = int(cc.n_small_units.sum())
    n_ind = int(cc.n_individual.sum())

    big = cc[cc.kw_total >= min_commune_kw]
    share = (big.kw_le_72 / big.kw_total.clip(lower=1e-9))
    big_bt = cc[cc.kw_bt >= min_commune_kw]
    share_bt = (big_bt.kw_bt_le_72 / big_bt.kw_bt.clip(lower=1e-9))

    def dispersion(s, weights):
        return {
            "n_communes": int(len(s)),
            "capacity_weighted_mean": _num(np.average(s, weights=weights)),
            "unweighted_mean": _num(s.mean()),
            "sd": _num(s.std()),
            "quantiles": {f"p{int(q*100)}": _num(s.quantile(q))
                          for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
            "spearman_vs_commune_kw": _num(pd.Series(s).corr(weights, method="spearman")),
        }

    return {
        "register": "ODRE registre national des installations de production et de stockage",
        "seg_floor_kwp": SEG_FLOOR_KWP,
        "seg_floor_derivation": "400 m2 module area x 0.18 kWp/m2 (DEFAULT_KWP_PER_M2_MODULE)",
        "censoring_cutoff_kw": REGISTER_SMALL_CUTOFF_KW,
        "n_communes": int(len(cc)),
        "n_small_units_aggregated": n_small,
        "n_individual_units": n_ind,
        "mean_kw_per_small_unit": _num(float(cc.kw_small_agg.sum()) / max(n_small, 1), 3),
        "totals_mw": {
            "all_pv": _num(tot / 1000, 1),
            "below_floor": _num(below / 1000, 1),
            "bt_only": _num(tot_bt / 1000, 1),
            "bt_below_floor": _num(below_bt / 1000, 1),
        },
        "share_below_seg_floor": {
            "all_pv": _num(below / tot),
            "bt_only": _num(below_bt / tot_bt),
            "interpretation": (
                "rooftop share lies between these; the register has no rooftop/ground "
                "field, so neither is a direct analogue of Germany's 0.655"
            ),
            "germany_rooftop_reference": 0.655,
        },
        "count_share_below_seg_floor": _num(n_small / max(n_small + n_ind, 1)),
        "censored_thresholds_kwp": {
            "note": (
                f"below {REGISTER_SMALL_CUTOFF_KW:g} kW the register publishes only "
                "per-commune aggregates, so 10 and 30 kWp shares are not recoverable"
            ),
            "le_10_kwp": None,
            "le_30_kwp": None,
        },
        "dispersion_all_pv": dispersion(share, big.kw_total),
        "dispersion_bt_only": dispersion(share_bt, big_bt.kw_bt),
        "min_commune_kw": min_commune_kw,
    }


def interpolate_to_date(
    vintages: dict[str, pd.DataFrame], target: pd.Timestamp, column: str = "kw_small_agg"
) -> pd.Series:
    """Per-commune small-PV capacity read back to `target`, between year-end vintages.

    The aggregates carry one group-level commissioning date covering hundreds of units,
    so a registered small installation cannot be dated individually and the current
    register cannot be filtered to a past epoch. Dated vintages of the same publication
    can, and linear interpolation between the two straddling year-ends is the honest
    reading of a quantity that only exists at year-end snapshots.

    `vintages` maps an ISO date ('2024-12-31') to a `commune_capacity` frame.
    """
    dates = sorted(pd.Timestamp(d) for d in vintages)
    if target <= dates[0]:
        return vintages[dates[0].strftime("%Y-%m-%d")].set_index("insee")[column]
    if target >= dates[-1]:
        return vintages[dates[-1].strftime("%Y-%m-%d")].set_index("insee")[column]
    lo = max(d for d in dates if d <= target)
    hi = min(d for d in dates if d >= target)
    a = vintages[lo.strftime("%Y-%m-%d")].set_index("insee")[column]
    b = vintages[hi.strftime("%Y-%m-%d")].set_index("insee")[column]
    if hi == lo:
        return a
    w = (target - lo) / (hi - lo)
    idx = a.index.union(b.index)
    return a.reindex(idx).fillna(0.0) * (1 - w) + b.reindex(idx).fillna(0.0) * w


# ---------------------------------------------------------------------------
# OpenPVMapper: the independent nationwide rooftop database
# ---------------------------------------------------------------------------

# Kasmi, G. (2026), OpenPVMapper, doi:10.5281/zenodo.21534856, CC-BY-4.0.
# 1,135,850 rooftop installations, ~15.0 GWp, mainland France, from DeepPVMapper
# detections on IGN BD ORTHO plus OSM, FRPV and manual corrections.
OPVM_DOI = "10.5281/zenodo.21534856"


def load_openpvmapper(path: Path, columns: tuple[str, ...] = (
    "array_id", "insee", "dpt", "surface", "kWp", "sources", "first_seen", "last_seen",
    "false_positive_source", "frpv_proba", "tilt", "azimuth",
)) -> "pd.DataFrame":
    """OpenPVMapper's enriched national table, with geometry, as a GeoDataFrame.

    `sources` is the field that decides how much weight a row carries: the dataset's own
    validation puts single-source precision at 71.5% against 96.9% for two sources and
    98.2% for three, so a comparison that pools all rows is comparing against a ~75%
    precise reference and will read any earthpv miss as a false negative when it may be
    an OpenPVMapper false positive. `n_sources` is derived here so every downstream
    comparison can stratify on it.
    """
    import geopandas as gpd

    path = Path(path)
    g = gpd.read_parquet(path) if path.suffix == ".parquet" else gpd.read_file(path)
    keep = [c for c in columns if c in g.columns]
    g = g[[*keep, "geometry"]].copy()
    g["insee"] = g["insee"].astype(str).str.strip().str.zfill(5)
    if "sources" in g.columns:
        g["n_sources"] = g["sources"].apply(
            lambda v: len(v) if isinstance(v, (list, tuple))
            else len([x for x in str(v).replace("[", "").replace("]", "")
                      .replace("'", "").split(",") if x.strip()])
        )
    return g


def openpvmapper_by_commune(opvm: "pd.DataFrame") -> pd.DataFrame:
    """Per-commune OpenPVMapper totals, overall and restricted to corroborated rows."""
    o = opvm.copy()
    o["kWp"] = pd.to_numeric(o["kWp"], errors="coerce").fillna(0.0)
    o["surface"] = pd.to_numeric(o["surface"], errors="coerce").fillna(0.0)
    corr = o[o.get("n_sources", pd.Series(1, index=o.index)) >= 2]
    # The register's below-floor block only contains units under 72 kWp, so the
    # OpenPVMapper side of that comparison has to be cut at the same place -- otherwise a
    # ratio above 1 just means OpenPVMapper also mapped the large roofs.
    small = o[o.kWp <= SEG_FLOOR_KWP]
    out = pd.DataFrame({
        "opvm_kwp": o.groupby("insee").kWp.sum(),
        "opvm_m2": o.groupby("insee").surface.sum(),
        "opvm_n": o.groupby("insee").size(),
        "opvm_kwp_corroborated": corr.groupby("insee").kWp.sum(),
        "opvm_m2_corroborated": corr.groupby("insee").surface.sum(),
        "opvm_n_corroborated": corr.groupby("insee").size(),
        "opvm_kwp_le_72": small.groupby("insee").kWp.sum(),
        "opvm_m2_le_72": small.groupby("insee").surface.sum(),
        "opvm_n_le_72": small.groupby("insee").size(),
    }).fillna(0.0).reset_index()
    return out


def _fit(x: np.ndarray, y: np.ndarray) -> dict:
    """Agreement of `y` (estimate) against `x` (reference), the same battery
    `mastr_validation` reports: origin-forced slope, median ratio, rank and log-log
    correlation. Origin-forced because both quantities are non-negative capacities with
    a meaningful zero, so an intercept would absorb exactly the bias being measured.
    """
    ok = np.isfinite(x) & np.isfinite(y) & (x > 0)
    x, y = x[ok], y[ok]
    if len(x) < 10:
        return {"n": int(len(x)), "insufficient": True}
    slope = float((x * y).sum() / (x * x).sum())
    ratio = y / x
    lx, ly = np.log10(np.clip(x, 1e-9, None)), np.log10(np.clip(y, 1e-9, None))
    pos = y > 0
    return {
        "n": int(len(x)),
        "slope_through_origin": _num(slope),
        "median_ratio": _num(np.median(ratio)),
        "p25_ratio": _num(np.percentile(ratio, 25)),
        "p75_ratio": _num(np.percentile(ratio, 75)),
        "spearman": _num(pd.Series(x).corr(pd.Series(y), method="spearman")),
        "pearson_log10": _num(np.corrcoef(lx[pos], ly[pos])[0, 1]) if pos.sum() > 10 else None,
        "total_ref": _num(float(x.sum()), 1),
        "total_est": _num(float(y.sum()), 1),
        "total_ratio": _num(float(y.sum() / x.sum())),
    }


def compare_openpvmapper_to_register(
    opvm_cc: pd.DataFrame, cc: pd.DataFrame, min_commune_kw: float = MIN_COMMUNE_KW
) -> dict:
    """OpenPVMapper's per-commune capacity against the register's, and what that says
    about using it as a reference for earthpv.

    This is the step that decides how OpenPVMapper may be quoted. It is a model output
    with ~74-75% published precision, so it is not ground truth; but it is the only
    nationwide per-installation rooftop dataset France has, and the register is complete.
    Scoring it against the register first establishes its own bias, so a later earthpv
    versus OpenPVMapper comparison can be read knowing which way the reference leans
    rather than treating disagreement as earthpv's error.

    Two denominators again, and the BT-only one is the fair one: OpenPVMapper claims
    rooftop only, so scoring it against all registered PV (which is heavily ground-mount)
    would manufacture a large false shortfall.
    """
    m = cc.merge(opvm_cc, on="insee", how="left").fillna({"opvm_kwp": 0.0, "opvm_m2": 0.0,
                                                          "opvm_n": 0,
                                                          "opvm_kwp_corroborated": 0.0})
    m = m[m.kw_total >= min_commune_kw]
    out = {
        "source": OPVM_DOI,
        "n_communes_scored": int(len(m)),
        "vs_all_pv": _fit(m.kw_total.to_numpy(float), m.opvm_kwp.to_numpy(float)),
        "vs_bt_only": _fit(m.kw_bt.to_numpy(float), m.opvm_kwp.to_numpy(float)),
        "vs_bt_only_corroborated": _fit(
            m.kw_bt.to_numpy(float), m.opvm_kwp_corroborated.to_numpy(float)
        ),
        "vs_below_floor_bt": _fit(
            m.kw_bt_le_72.to_numpy(float), m.opvm_kwp_le_72.to_numpy(float)
        ),
        "implied_kwp_per_m2": _num(
            float(m.opvm_kwp.sum()) / max(float(m.opvm_m2.sum()), 1e-9), 4
        ),
        "project_module_constant": 0.18,
        "caveats": [
            "OpenPVMapper is a model output (~74-75% precision), not ground truth",
            "the register is complete but carries no rooftop/ground field, so `vs_bt_only` "
            "is a proxy denominator and still contains BT-connected ground-mount",
            "OpenPVMapper vintages are IGN flight dates per departement and do not match "
            "the register's 2026-06-30 snapshot; the register is the newer of the two, so "
            "a ratio below 1 is partly growth rather than under-detection",
        ],
    }
    return out


# ---------------------------------------------------------------------------
# The hand-mapped communes: the only ground truth in this comparison
# ---------------------------------------------------------------------------

def load_mapped_quadrats(labels_dir: Path) -> dict[str, dict]:
    """Every France calibration quadrat as {stem: {boundary, pv, insee, mapping_date}}.

    These are the only human-verified polygons in the France comparison. Both other
    sources are derived: the register is an administrative record with no geometry, and
    OpenPVMapper is a model output. Whenever the three disagree, this is the one that
    decides, within the epoch it was drawn against.
    """
    import geopandas as gpd

    out: dict[str, dict] = {}
    for b in sorted(Path(labels_dir).glob("*_calib_*_boundary.geojson")):
        stem = b.name[: -len("_boundary.geojson")]
        solar = sorted(Path(labels_dir).glob(f"{stem}_overpass_solar*.parquet"))
        if not solar:
            continue
        bnd = gpd.read_file(b)
        out[stem] = {
            "boundary": bnd,
            "pv": gpd.read_parquet(solar[-1]),
            "insee": str(bnd.get("insee", pd.Series(["" ])).iloc[0]).zfill(5),
            "mapping_date": bnd.get("mapping_date", pd.Series([None])).iloc[0],
            "km2": float(bnd.get("size_km2", pd.Series([np.nan])).iloc[0]),
            "commune": bnd.get("location", pd.Series([stem])).iloc[0],
        }
    return out


def module_constant_from_mapped(
    quadrats: dict[str, dict],
    vintages: dict[str, pd.DataFrame],
    max_installation_m2: float = SMALL_BAND_M2,
    exclude: tuple[str, ...] = ("saint_gely_du_fesc_calib_16p58km2",),
) -> dict:
    """Measure kWp per m2 of module area directly, from mapped polygons plus the register.

    This is the check Germany could not deliver. There, the module constant could not be
    externally calibrated because German OSM covers only ~3.6% of registered rooftop units
    and the well-mapped tail's implied kWp/m2 swings 0.02-0.99 on mapper convention. Here
    the numerator is a *complete* sweep of a commune by a human on sub-metre imagery, and
    the denominator is a legally-mandated register of the same commune, so the ratio is a
    real measurement of the constant rather than a measurement of mapping habits.

    Three matching rules make the two populations the same population:

    1. **Size.** Only mapped installations under `max_installation_m2` (200 m2, the module
       area equivalent of the register's 36 kW censoring cliff) are counted, against the
       register's small-aggregate capacity alone. Above the cliff the register lists units
       individually and the mapped set stops being complete for them.
    2. **Epoch.** The register is read back to the commune's own mapping date by
       `interpolate_to_date` rather than taken at its 2026 snapshot. France added roughly
       10 GWp between 2022 and 2025, so an uncorrected comparison would inflate the
       constant by tens of percent purely through installations mapped years after the
       imagery.
    3. **Technology.** Solar thermal is already excluded upstream by the quadrat builder's
       tag filter. It is the single largest confound available here: 381 of 3,335 mapped
       features are thermal collectors, which carry area but produce no kW.

    The result remains a LOWER bound on the true constant in one direction and an upper
    bound in another, and neither is removable: mapping misses installations hidden by
    tree cover or shadow (pushing the measured constant up), while the register's small
    band includes units the mapper could see no trace of on an older flight (also pushing
    it up). What it does bound tightly is whether 0.18 is the right order of magnitude for
    French residential PV.
    """
    rows, excluded = [], []
    for stem, q in quadrats.items():
        insee, date = q["insee"], q["mapping_date"]
        if not insee or insee in ("", "nan"):
            excluded.append({"quadrat": stem, "reason": "no INSEE code"})
            continue
        if stem in exclude:
            excluded.append({"quadrat": stem, "reason": "not Rule-1 complete"})
            continue
        pv = q["pv"]
        small = pv[pv.area_m2 < max_installation_m2]
        m2 = float(small.area_m2.sum())
        if m2 <= 0:
            continue
        target = pd.Timestamp(date) if date and str(date) != "nan" else pd.Timestamp("2024-07-01")
        kw_series = interpolate_to_date(vintages, target)
        kw = float(kw_series.get(insee, np.nan))
        latest = max(vintages)
        kw_now = float(vintages[latest].set_index("insee").kw_small_agg.get(insee, np.nan))
        if not np.isfinite(kw) or kw <= 0:
            # The register has no small-PV aggregate for this commune at this epoch. That
            # is a hole in the reference, not a commune with no PV -- the mapper found
            # installations there. Booking it as zero capacity over real mapped area would
            # drag the pooled constant down with a coverage gap.
            excluded.append({
                "quadrat": stem, "commune": q["commune"],
                "reason": f"register reports no sub-{REGISTER_SMALL_CUTOFF_KW:g} kW capacity "
                          f"at {str(date)[:10]} despite {len(small)} mapped installations",
            })
            continue
        rows.append(dict(
            quadrat=stem, commune=q["commune"], insee=insee, mapping_date=str(date)[:10],
            km2=q["km2"], n_mapped=int(len(small)), mapped_m2=round(m2, 1),
            register_kw_at_mapping=_num(kw, 1), register_kw_latest=_num(kw_now, 1),
            kwp_per_m2=_num(kw / m2 if m2 else np.nan),
            kwp_per_m2_uncorrected=_num(kw_now / m2 if m2 else np.nan),
        ))
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n_communes": 0}
    ok = df.kwp_per_m2.notna()
    pooled = float(df.loc[ok, "register_kw_at_mapping"].sum() / df.loc[ok, "mapped_m2"].sum())
    pooled_unc = float(
        df.loc[ok, "register_kw_latest"].sum() / df.loc[ok, "mapped_m2"].sum()
    )
    return {
        "n_communes": int(ok.sum()),
        "excluded": excluded,
        "max_installation_m2": max_installation_m2,
        "pooled_kwp_per_m2_epoch_matched": _num(pooled),
        "pooled_kwp_per_m2_uncorrected": _num(pooled_unc),
        "epoch_correction_factor": _num(pooled / pooled_unc if pooled_unc else np.nan),
        "median_commune_kwp_per_m2": _num(df.loc[ok, "kwp_per_m2"].median()),
        "iqr_commune_kwp_per_m2": [
            _num(df.loc[ok, "kwp_per_m2"].quantile(0.25)),
            _num(df.loc[ok, "kwp_per_m2"].quantile(0.75)),
        ],
        "project_module_constant": 0.18,
        "ratio_to_project_constant": _num(pooled / 0.18, 3),
        "per_commune": df.to_dict("records"),
    }


def mapped_vs_openpvmapper(
    quadrats: dict[str, dict],
    opvm,
    source_dir: Path = Path("data/labels/calibration_france"),
    size_bins: tuple[float, ...] = (0, 20, 50, 100, 200, 400, 1e9),
) -> dict:
    """OpenPVMapper's precision and recall inside the hand-mapped communes, decomposed.

    The mapped communes are swept exhaustively, so within their boundary and epoch both
    error directions are measurable: an OpenPVMapper polygon with no mapped PV underneath
    it is a false positive, and a mapped installation with no OpenPVMapper polygon is a
    miss. That is a stronger statement than the dataset's own stratified precision
    estimate, which by construction cannot measure recall at all.

    **A raw false-positive count would be unfair and uninformative**, because the mapper
    tagged three different things that a detector can land on: real PV (`normal`),
    solar-thermal collectors (`thermal`), and features they retracted (`false`). A thermal
    collector is a black glazed rectangle on a south-facing roof; confusing it with PV is
    the single most interesting failure mode available in this dataset, and it is invisible
    to any validation that does not carry the tag. So non-matching OpenPVMapper polygons
    are split into `on_thermal`, `on_retracted` and `unexplained`, and precision is
    reported both raw and with thermal confusions excluded from the denominator.

    Recall is reported per installation-size bin, because that is the quantity this
    project actually needs from France: how detection degrades toward the small end is the
    external check on the 400 m2 floor that Germany's register cannot give.

    **These communes are not independent of OpenPVMapper.** They are its
    manual-correction layer, so its rows here have been corrected toward this ground truth
    and its precision inside them is an optimistic bound on precision elsewhere. Recall is
    the more transferable half.
    """
    import geopandas as gpd

    rows, bin_rows = [], []
    for stem, q in quadrats.items():
        bnd = q["boundary"].geometry.iloc[0]
        truth = q["pv"].to_crs("EPSG:4326").reset_index(drop=True)
        if truth.empty:
            continue
        src = q["boundary"].get("source_geojson")
        tagged = None
        if src is not None and Path(str(src.iloc[0])).exists():
            tagged = gpd.read_file(str(src.iloc[0])).to_crs("EPSG:4326")
            tagged["tag"] = tagged["tag"].astype(str).str.lower()
            tagged = tagged[tagged.geometry.notna() & tagged.geometry.is_valid]

        s = opvm[opvm.geometry.intersects(bnd)].reset_index(drop=True)
        if s.empty:
            rows.append(dict(quadrat=stem, commune=q["commune"], n_truth=len(truth),
                             n_opvm=0, matched_truth=0, matched_opvm=0, recall=0.0,
                             precision=None, on_thermal=0, on_retracted=0, unexplained=0))
            continue

        j = gpd.sjoin(s[["geometry"]], truth[["geometry"]], how="inner", predicate="intersects")
        matched_opvm, matched_truth = set(j.index), set(j.index_right)
        unmatched = s.loc[~s.index.isin(matched_opvm)]

        on_thermal = on_retracted = 0
        if tagged is not None and not unmatched.empty:
            for tag, target in (("thermal", "on_thermal"), ("false", "on_retracted")):
                sub = tagged[tagged.tag == tag]
                if sub.empty:
                    continue
                hit = gpd.sjoin(unmatched[["geometry"]], sub[["geometry"]],
                                how="inner", predicate="intersects")
                n = len(set(hit.index))
                if target == "on_thermal":
                    on_thermal = n
                else:
                    on_retracted = n

        # recall by size bin, on the truth side
        cut = pd.cut(truth.area_m2, bins=list(size_bins), right=False)
        found = truth.index.isin(matched_truth)
        for b, grp in truth.assign(_f=found).groupby(cut, observed=True):
            bin_rows.append(dict(quadrat=stem, bin=str(b), n=len(grp),
                                 found=int(grp._f.sum()), m2=float(grp.area_m2.sum()),
                                 m2_found=float(grp.loc[grp._f, "area_m2"].sum())))

        rows.append(dict(
            quadrat=stem, commune=q["commune"], n_truth=int(len(truth)), n_opvm=int(len(s)),
            matched_truth=int(len(matched_truth)), matched_opvm=int(len(matched_opvm)),
            recall=_num(len(matched_truth) / len(truth)),
            precision=_num(len(matched_opvm) / len(s)),
            on_thermal=on_thermal, on_retracted=on_retracted,
            unexplained=int(len(unmatched) - on_thermal - on_retracted),
            truth_m2=round(float(truth.area_m2.sum()), 1),
            truth_m2_found=round(float(truth.loc[truth.index.isin(matched_truth),
                                                 "area_m2"].sum()), 1),
            opvm_m2=round(float(pd.to_numeric(s.get("surface"), errors="coerce").sum()), 1),
        ))

    df = pd.DataFrame(rows)
    bins = pd.DataFrame(bin_rows)
    by_bin = {}
    if not bins.empty:
        g = bins.groupby("bin", observed=True)[["n", "found", "m2", "m2_found"]].sum()
        by_bin = {
            str(i): {"n": int(r.n), "count_recall": _num(r.found / max(r.n, 1)),
                     "area_recall": _num(r.m2_found / max(r.m2, 1e-9))}
            for i, r in g.iterrows()
        }

    n_opvm = int(df.n_opvm.sum())
    n_thermal = int(df.on_thermal.sum())
    matched = int(df.matched_opvm.sum())
    return {
        "n_quadrats": int(len(df)),
        "n_truth": int(df.n_truth.sum()),
        "n_opvm": n_opvm,
        "pooled_count_recall": _num(df.matched_truth.sum() / max(df.n_truth.sum(), 1)),
        "pooled_area_recall": _num(df.truth_m2_found.sum() / max(df.truth_m2.sum(), 1e-9)),
        "pooled_precision_raw": _num(matched / max(n_opvm, 1)),
        "pooled_precision_excl_thermal": _num(matched / max(n_opvm - n_thermal, 1)),
        "unmatched_breakdown": {
            "on_solar_thermal": n_thermal,
            "on_retracted_feature": int(df.on_retracted.sum()),
            "unexplained": int(df.unexplained.sum()),
        },
        "area_ratio_opvm_over_truth": _num(
            df.opvm_m2.sum() / max(df.truth_m2.sum(), 1e-9)
        ),
        "recall_by_installation_m2": by_bin,
        "independence_caveat": (
            "these communes are OpenPVMapper's own manual-correction layer, so precision "
            "measured here is an optimistic bound; recall is the more transferable half"
        ),
        "epoch_caveat": (
            "OpenPVMapper rows carry IGN flight vintages per departement and the mapping "
            "carries its own imageDate; where the flight postdates the mapping, an "
            "unmatched OpenPVMapper polygon may be a genuinely newer installation rather "
            "than a false positive"
        ),
        "per_quadrat": df.to_dict("records"),
    }


def mapped_vs_earthpv(
    quadrats: dict[str, dict],
    candidates_path: Path,
    grid_path: Path | None = None,
    size_bins: tuple[float, ...] = (0, 20, 50, 100, 200, 400, 1e9),
    opvm_recall_by_bin: dict | None = None,
    min_covered_frac: float = 0.99,
) -> dict:
    """earthpv's own recall against the hand-mapped communes, per installation size.

    **This is the external test of the 400 m2 detection floor**, and the reason France is
    worth the effort even though `roofclf` does not transfer here. The floor has always
    been argued from the sensor (400 m2 is four Sentinel-2 pixels) and from Pakistani
    quadrats that are themselves labelled off imagery. These annotations are drawn on
    sub-metre IGN orthophotos, so they are independent of what a 10 m sensor can resolve:
    an installation missing from earthpv but present in the truth set is a real miss, not
    an annotation gap.

    **Recall, not precision, is the measurable half here** -- the same asymmetry
    `derive_placement_tables` was fixed for in 2026-09-02. Four of the fourteen communes
    were mapped one to three years before the 2024 composite window, so an unmatched
    candidate may be a genuinely newer installation rather than a false positive. That
    biases precision and says nothing about recall: PV that was on a roof in 2021 is still
    there in 2024, so every mapped installation is a fair thing to require a detector to
    find. Precision over these communes is deliberately not reported.

    **The control that makes the result interpretable is OpenPVMapper.** Pass its own
    per-bin recall as `opvm_recall_by_bin` (from `mapped_vs_openpvmapper`). It reads the
    same installations from sub-metre imagery and recalls them with no size gradient
    across 0-400 m2, so whatever gradient earthpv shows against the same truth in the same
    communes is the sensor, not the annotator. Without that control a size gradient could
    just as easily be mappers drawing small things less reliably.

    **A commune that was never inferred must not read as recall 0**, which is the one way
    this measurement silently produces a wrong answer. When `grid_path` is given (a
    density run's `grid.geoparquet`), each boundary's covered fraction is measured against
    the inferred cells and anything below `min_covered_frac` is excluded from the pooled
    figures with its reason recorded, rather than counted as a total miss.

    Saint-Gely-du-Fesc is **kept** here, unlike in every fit: the mapper marked it
    unfinished, but incomplete mapping removes installations from the truth set rather
    than adding phantom ones, so it biases precision and leaves recall-over-mapped
    unaffected.
    """
    import geopandas as gpd

    cand = gpd.read_parquet(candidates_path)[["geometry", "area_m2", "placement"]]
    cand = cand.to_crs("EPSG:4326").reset_index(drop=True)

    grid = None
    if grid_path is not None and Path(grid_path).exists():
        grid = gpd.read_parquet(grid_path)[["geometry"]].to_crs("EPSG:4326")

    rows, bin_rows, skipped = [], [], {}
    for stem, q in quadrats.items():
        bnd_gs = q["boundary"].to_crs("EPSG:4326")
        bnd = bnd_gs.geometry.iloc[0]
        truth = q["pv"].to_crs("EPSG:4326").reset_index(drop=True)
        if truth.empty:
            continue

        covered = None
        if grid is not None:
            hit = grid[grid.geometry.intersects(bnd)]
            if hit.empty:
                covered = 0.0
            else:
                inter = hit.geometry.union_all().intersection(bnd)
                covered = float(inter.area / bnd.area) if bnd.area > 0 else 0.0
            if covered < min_covered_frac:
                skipped[stem] = (
                    f"only {covered:.1%} of the boundary falls in inferred cells -- "
                    "excluded so an uninferred commune cannot read as recall 0"
                )
                continue

        s = cand[cand.geometry.intersects(bnd)]
        if s.empty:
            matched_truth: set = set()
        else:
            j = gpd.sjoin(s[["geometry"]], truth[["geometry"]], how="inner",
                          predicate="intersects")
            matched_truth = set(j.index_right)

        found = truth.index.isin(matched_truth)
        cut = pd.cut(truth.area_m2, bins=list(size_bins), right=False)
        for b, grp in truth.assign(_f=found).groupby(cut, observed=True):
            bin_rows.append(dict(quadrat=stem, bin=str(b), n=len(grp),
                                 found=int(grp._f.sum()), m2=float(grp.area_m2.sum()),
                                 m2_found=float(grp.loc[grp._f, "area_m2"].sum())))

        rows.append(dict(
            quadrat=stem, commune=q["commune"], covered_frac=_num(covered),
            n_truth=int(len(truth)), n_candidates=int(len(s)),
            matched_truth=int(len(matched_truth)),
            recall=_num(len(matched_truth) / len(truth)),
            truth_m2=round(float(truth.area_m2.sum()), 1),
            truth_m2_found=round(float(truth.loc[found, "area_m2"].sum()), 1),
            mapping_date=str(q["mapping_date"]),
        ))

    df = pd.DataFrame(rows)
    bins = pd.DataFrame(bin_rows)
    by_bin: dict = {}
    if not bins.empty:
        g = bins.groupby("bin", observed=True)[["n", "found", "m2", "m2_found"]].sum()
        by_bin = {
            str(i): {"n": int(r.n), "count_recall": _num(r.found / max(r.n, 1)),
                     "area_recall": _num(r.m2_found / max(r.m2, 1e-9))}
            for i, r in g.iterrows()
        }

    def _gradient(d: dict | None) -> dict | None:
        """Spearman of recall against bin order -- the number the control exists to make
        readable. A detector limited by resolution climbs with size; one limited by the
        annotator does not."""
        if not d:
            return None
        order = [(i, v) for i, (_, v) in enumerate(sorted(
            d.items(), key=lambda kv: float(str(kv[0]).split(",")[0].lstrip("[("))))]
        if len(order) < 3:
            return None
        from scipy.stats import spearmanr
        idx = [i for i, _ in order]
        rec = [v["count_recall"] or 0.0 for _, v in order]
        rho, p = spearmanr(idx, rec)
        return {"spearman_recall_vs_size": _num(float(rho)), "p_value": _num(float(p), 4)}

    below = bins[~bins.bin.str.startswith("[400")] if not bins.empty else bins
    above = bins[bins.bin.str.startswith("[400")] if not bins.empty else bins
    floor_split = {}
    for name, part in (("below_400_m2", below), ("at_or_above_400_m2", above)):
        if part is not None and not part.empty:
            floor_split[name] = {
                "n": int(part.n.sum()),
                "count_recall": _num(part.found.sum() / max(part.n.sum(), 1)),
                "area_recall": _num(part.m2_found.sum() / max(part.m2.sum(), 1e-9)),
            }

    return {
        "candidates": str(candidates_path),
        "n_quadrats_used": int(len(df)),
        "n_truth": int(df.n_truth.sum()) if not df.empty else 0,
        "pooled_count_recall": _num(df.matched_truth.sum() / max(df.n_truth.sum(), 1))
        if not df.empty else None,
        "pooled_area_recall": _num(df.truth_m2_found.sum() / max(df.truth_m2.sum(), 1e-9))
        if not df.empty else None,
        "recall_by_installation_m2": by_bin,
        "floor_split": floor_split,
        "size_gradient_earthpv": _gradient(by_bin),
        "size_gradient_openpvmapper_control": _gradient(opvm_recall_by_bin),
        "openpvmapper_recall_by_installation_m2": opvm_recall_by_bin or {},
        "skipped_quadrats": skipped,
        "precision_caveat": (
            "precision is deliberately not reported: four communes were mapped 1-3 years "
            "before the 2024 composite window, so an unmatched candidate may be a newer "
            "installation rather than a false positive. Recall over mapped installations "
            "is unaffected by that epoch gap"
        ),
        "control_caveat": (
            "OpenPVMapper reads the same installations at sub-metre resolution, so its "
            "flat recall across size is the control: a gradient in earthpv against the "
            "same truth in the same communes is the 10 m sensor, not the annotator"
        ),
        "per_quadrat": df.to_dict("records") if not df.empty else [],
    }


# ---------------------------------------------------------------------------
# earthpv against the register
# ---------------------------------------------------------------------------

def validate_density_against_register(
    density_dir: Path,
    cc: pd.DataFrame,
    communes_path: Path,
    estimators: tuple[str, ...] = ("est_mwp_rc_roof", "est_mwp_cal", "est_mwp_det", "est_mwp_exp"),
    min_commune_kw: float = MIN_COMMUNE_KW,
) -> dict:
    """Compare a `density` run's rooftop estimators against the register, per commune.

    Mirrors `mastr_validation.validate_density_against_mastr`, including the
    area-weighted apportionment of each 0.1 degree cell to the communes it intersects
    (a cell near 47 N is roughly 82 km2 against a French commune median near 11 km2, so
    a centroid join would miss most communes outright).

    The denominator question is sharper here than in Germany. `results_above_floor` uses
    `kw_total - kw_le_72`, the capacity a >= 400 m2 segmentation model could see in
    principle -- but unlike MaStR that figure still contains ground-mount, which is what
    `density`'s ground estimators are separately responsible for. So the rooftop
    estimators are additionally scored against the BT-only above-floor block, which is
    the closest France offers to Germany's rooftop denominator.
    """
    import geopandas as gpd
    import shapely

    from earthpv.labels import geodesic_area_m2

    density_dir = Path(density_dir)
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    com = gpd.read_parquet(communes_path)
    present = [e for e in estimators if e in grid.columns]
    if not present:
        raise ValueError(
            f"{density_dir}/grid.geoparquet has none of {estimators} -- has `earthpv "
            "density` run for this AOI?"
        )
    if not grid.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError(
            f"{density_dir}/grid.geoparquet carries non-polygon cell geometry; the "
            "area-weighted commune join needs cell footprints from `earthpv density`"
        )
    cells = gpd.GeoDataFrame(grid[present], geometry=grid.geometry, crs=grid.crs or "EPSG:4326")
    j = gpd.sjoin(cells, com[["insee", "geometry"]], predicate="intersects", how="inner")
    inter = shapely.intersection(
        j.geometry.to_numpy(), com.geometry.reindex(j.index_right).to_numpy()
    )
    cell_area = np.array([geodesic_area_m2(g) for g in j.geometry])
    w = np.array([geodesic_area_m2(g) for g in inter]) / np.clip(cell_area, 1e-9, None)
    j = j.loc[w > 0, ["insee", *present]]
    j[present] = j[present].to_numpy(float) * w[w > 0, None]
    agg = j.groupby("insee", as_index=False)[present].sum()

    m = agg.merge(cc, on="insee", how="inner")
    m = m[m.kw_total >= min_commune_kw]
    covered_kw = float(m.kw_total.sum())
    national_kw = float(cc.kw_total.sum())
    coverage = covered_kw / max(national_kw, 1e-9)

    out: dict = {
        "density_dir": str(density_dir),
        "n_communes_scored": int(len(m)),
        "n_communes_register": int(len(cc)),
        "coverage_by_capacity": _num(coverage),
        "coverage_by_count": _num(len(m) / max(len(cc), 1)),
        "national": bool(coverage >= MIN_NATIONAL_COVERAGE),
        "min_commune_kw": min_commune_kw,
        "denominators": {
            "all_capacity": "every registered PV kW in the commune",
            "above_floor": f"kw_total - kw_le_{SEG_FLOOR_KWP:g}, what a >= 400 m2 model can see",
            "above_floor_bt": "same, low-voltage only -- the closest France has to a "
                              "rooftop denominator",
        },
        "results": {}, "results_above_floor": {}, "results_above_floor_bt": {},
    }
    for e in present:
        est_kw = m[e].to_numpy(float) * 1000.0
        out["results"][e] = _fit(m.kw_total.to_numpy(float), est_kw)
        out["results_above_floor"][e] = _fit(m.kw_above_floor.to_numpy(float), est_kw)
        out["results_above_floor_bt"][e] = _fit(m.kw_bt_above_floor.to_numpy(float), est_kw)
    out["caveats"] = [
        "cell-to-commune apportionment assumes PV is spread uniformly within a 0.1 degree "
        "cell, so this checks aggregate level and rank, not per-commune values",
        "the register carries no rooftop/ground field, so no denominator here is purely "
        "rooftop; `above_floor_bt` is a proxy",
    ]
    if not out["national"]:
        out["warning"] = (
            f"only {coverage:.1%} of registered capacity is covered by composited cells; "
            "partial imagery coverage reads exactly like a real underestimate"
        )
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def load_vintages(register_dir: Path) -> dict[str, pd.DataFrame]:
    """{'YYYY-12-31': commune_capacity frame} for every year-end export present.

    A vintage that failed to export completely looks exactly like a year in which PV
    barely existed, so anything implausibly small for its year is refused loudly rather
    than quietly flattening the growth curve it exists to measure.
    """
    out: dict[str, pd.DataFrame] = {}
    for p in sorted(Path(register_dir).glob("odre_solaire_3112*.csv")):
        yy = p.stem[-2:]
        reg = load_register(p)
        cc = commune_capacity(reg)
        mw = float(cc.kw_total.sum()) / 1000
        if mw < 1000:
            raise ValueError(
                f"{p} reports only {mw:.0f} MW of French PV -- almost certainly a "
                "truncated export (the ODRE endpoint returns short CSVs on an SSL reset "
                "with no error); re-fetch with scripts/fetch_odre_vintages.sh"
            )
        out[f"20{yy}-12-31"] = cc
        log.info("vintage 20%s: %.1f MW over %d communes", yy, mw, len(cc))
    return out


def run_france_validation(
    register_csv: Path = Path("data/register/odre_solaire_raw.csv"),
    register_dir: Path = Path("data/register"),
    labels_dir: Path = Path("data/labels/france"),
    opvm_path: Path | None = None,
    density_dir: Path | None = None,
    communes_path: Path | None = None,
    pred_dir: Path | None = None,
    out_dir: Path = Path("results/france_validation"),
) -> dict:
    """Run every France check that its inputs allow, and write the report.

    Deliberately partial-tolerant: the register blocks (which need only a CSV) run even
    when no imagery exists yet, so the country-level findings are available long before a
    national compose finishes. Each block that could not run records why, rather than
    being silently absent from the report.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    reg = load_register(register_csv)
    cc = commune_capacity(reg)
    cc.to_parquet(out_dir / "commune_capacity.parquet")

    report: dict = {
        "register_snapshot": str(register_csv),
        "size_regime": size_regime_shares(cc),
        "skipped": {},
    }

    try:
        vintages = load_vintages(register_dir)
        report["vintages"] = {k: _num(float(v.kw_total.sum()) / 1000, 1) for k, v in vintages.items()}
    except Exception as e:  # noqa: BLE001
        vintages, report["skipped"]["vintages"] = {}, str(e)

    quadrats = load_mapped_quadrats(labels_dir)
    report["n_mapped_quadrats"] = len(quadrats)
    if quadrats and vintages:
        report["module_constant"] = module_constant_from_mapped(quadrats, vintages)
    elif not quadrats:
        report["skipped"]["module_constant"] = f"no quadrats under {labels_dir}"

    if opvm_path and Path(opvm_path).exists():
        opvm = load_openpvmapper(Path(opvm_path))
        opvm_cc = openpvmapper_by_commune(opvm)
        opvm_cc.to_parquet(out_dir / "openpvmapper_by_commune.parquet")
        report["openpvmapper_vs_register"] = compare_openpvmapper_to_register(opvm_cc, cc)
        if quadrats:
            report["openpvmapper_vs_mapped"] = mapped_vs_openpvmapper(quadrats, opvm)
    else:
        report["skipped"]["openpvmapper"] = f"not found: {opvm_path}"

    # The detection-floor test: earthpv's own recall against the same hand-mapped truth,
    # with OpenPVMapper's (flat) size gradient passed in as the control that separates a
    # sensor limit from an annotation limit.
    if pred_dir is not None:
        cand_path = Path(pred_dir) / "france" / "candidates.parquet"
        if not quadrats:
            report["skipped"]["earthpv_vs_mapped"] = f"no quadrats under {labels_dir}"
        elif not cand_path.exists():
            report["skipped"]["earthpv_vs_mapped"] = f"not found: {cand_path}"
        else:
            grid_path = Path(pred_dir) / "france" / "density" / "grid.geoparquet"
            report["earthpv_vs_mapped"] = mapped_vs_earthpv(
                quadrats, cand_path,
                grid_path=grid_path if grid_path.exists() else None,
                opvm_recall_by_bin=(report.get("openpvmapper_vs_mapped") or {}).get(
                    "recall_by_installation_m2"),
            )
    else:
        report["skipped"]["earthpv_vs_mapped"] = (
            "pass --pred-dir to measure earthpv's recall against the hand-mapped communes"
        )

    if density_dir and communes_path and Path(density_dir).exists():
        try:
            report["earthpv_vs_register"] = validate_density_against_register(
                Path(density_dir), cc, Path(communes_path)
            )
        except Exception as e:  # noqa: BLE001
            report["skipped"]["earthpv_vs_register"] = str(e)
    else:
        report["skipped"]["earthpv_vs_register"] = (
            "needs a completed `earthpv density --aoi france` run and national commune "
            "polygons"
        )

    (out_dir / "france_validation.json").write_text(json.dumps(report, indent=2, default=str))
    log.info("wrote %s", out_dir / "france_validation.json")
    return report
