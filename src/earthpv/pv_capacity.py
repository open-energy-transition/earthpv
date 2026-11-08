"""pvlib-based cross-checks for the `density` stage's capacity heuristic.

`density.py` converts area to capacity with **two** constants
(capacity_calibration.DEFAULT_KWP_PER_M2_{MODULE,LAND}): rooftop detections are ~module
area, ground-mount detections are site area of which only the ground-cover ratio is
module. This module cross-checks two things:

1. `check_kwp_per_m2` grounds the *module* constant against pvlib's CEC module database
   (real datasheets) instead of a single literature figure. **It validates only that
   constant**: it says nothing about whether a detected polygon's area is module area,
   which is the assumption that actually fails for ground-mount (hence the land constant
   and its wider prior). Passing this check is not evidence the conversion is right for
   anything but a rooftop detection.
2. `expected_annual_yield` converts each region's estimated MWp into expected annual
   generation (GWh/yr) via PVGIS-modelled specific yield at representative coordinates,
   so the capacity estimate can be cross-checked against known Pakistani generation
   anchors (NEPRA net-metering totals, an independent 27.5 GW distributed-solar study -
   see README.md) independently of the detection pipeline entirely.

Both are sanity checks, not silent replacements: the density-stage constants are left
as-is; this module only surfaces the comparison. For a check that gates the output, see
`plausibility.py` / `earthpv check-density`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pvlib

log = logging.getLogger(__name__)

# Modern-module STC power range for the module-efficiency sanity check; older/small
# panels in the CEC database (tiny off-grid modules etc.) would skew kWp/m2 low.
MODERN_MODULE_STC_RANGE_W = (350, 600)

# PVGIS default system loss (soiling, wiring, inverter, mismatch) for the yield model.
DEFAULT_SYSTEM_LOSS_PCT = 14.0


def check_kwp_per_m2(assumed: float) -> dict:
    """Compare `assumed` kWp/m2 against pvlib's CEC module database for modern
    (350-600 W STC) panels, where kWp/m2 = STC power / module area (A_c)."""
    df = pvlib.pvsystem.retrieve_sam("CECMod").T
    stc = df["STC"].astype(float)
    modern = df[(stc >= MODERN_MODULE_STC_RANGE_W[0]) & (stc <= MODERN_MODULE_STC_RANGE_W[1])]
    kwp_per_m2 = modern["STC"].astype(float) / 1000.0 / modern["A_c"].astype(float)
    stats = {
        "n_modules": int(len(modern)),
        "median_kwp_per_m2": float(kwp_per_m2.median()),
        "p25_kwp_per_m2": float(kwp_per_m2.quantile(0.25)),
        "p75_kwp_per_m2": float(kwp_per_m2.quantile(0.75)),
        "assumed_kwp_per_m2": float(assumed),
    }
    log.info(
        "pvlib CEC module check (%d modern modules): median %.3f kWp/m2 [IQR %.3f-%.3f] "
        "vs assumed %.3f", stats["n_modules"], stats["median_kwp_per_m2"],
        stats["p25_kwp_per_m2"], stats["p75_kwp_per_m2"], stats["assumed_kwp_per_m2"],
    )
    return stats


def specific_yield_kwh_per_kwp(
    lat: float, lon: float, year: int = 2020, loss_pct: float = DEFAULT_SYSTEM_LOSS_PCT,
) -> float | None:
    """Modelled annual kWh/kWp for a fixed-tilt (tilt=|lat|, equator-facing) rooftop
    system via PVGIS's PVcalc - a standard, widely-used tool for exactly this
    capacity-to-generation reconciliation, so this doesn't hand-roll a ModelChain.
    `PVGIS-ERA5` is used (not `PVGIS-SARAH3`, which doesn't cover Pakistan's longitude).

    Returns None (rather than raising) if PVGIS is unreachable, so one bad lookup
    doesn't kill a batch of regions - this machine has documented restrictions
    reaching some external APIs (see the Overture-S3 timeout note in CLAUDE.md).
    """
    try:
        data, _ = pvlib.iotools.get_pvgis_hourly(
            lat, lon, start=year, end=year, raddatabase="PVGIS-ERA5",
            # Facing the equator: pvlib's azimuth is clockwise from north, so south of the
            # equator that is 0. Until 2026-11-07 it was 180 everywhere, which turned every
            # southern-hemisphere probe away from the sun (South Africa read 1,073 kWh/kWp).
            surface_tilt=abs(lat), surface_azimuth=180 if lat >= 0 else 0, pvcalculation=True,
            peakpower=1, loss=loss_pct, outputformat="json",
        )
        return float(data["P"].sum() / 1000.0)
    except Exception as e:  # noqa: BLE001 - network/API best-effort
        log.warning("PVGIS lookup failed for (%.3f, %.3f): %s", lat, lon, e)
        return None


def expected_annual_yield(
    regions_geoparquet: Path, kwp_per_m2: float, loss_pct: float = DEFAULT_SYSTEM_LOSS_PCT,
) -> pd.DataFrame:
    """One row per admin region from `density.py`'s `regions.geoparquet`, adding
    `kwh_per_kwp_yr` (PVGIS specific yield at the region's centroid) and
    `expected_gwh_det/exp` = est_mwp_{det,exp} * kwh_per_kwp_yr / 1000 - an
    independent cross-check on installed-capacity-implied generation.
    """
    regions = gpd.read_parquet(regions_geoparquet)
    yields = []
    for _, row in regions.iterrows():
        c = row.geometry.centroid
        yields.append(specific_yield_kwh_per_kwp(c.y, c.x, loss_pct=loss_pct))
    regions["kwh_per_kwp_yr"] = yields
    regions["expected_gwh_det"] = regions["est_mwp_det"] * regions["kwh_per_kwp_yr"] / 1000.0
    regions["expected_gwh_exp"] = regions["est_mwp_exp"] * regions["kwh_per_kwp_yr"] / 1000.0
    if "est_mwp_cal" in regions.columns:  # older density outputs predate the calibrated column
        regions["expected_gwh_cal"] = regions["est_mwp_cal"] * regions["kwh_per_kwp_yr"] / 1000.0
    return regions.drop(columns="geometry")


def grid_specific_yield(
    bounds: tuple[float, float, float, float], cache_path: Path,
    n_probe: int = 36, year: int = 2020, loss_pct: float = DEFAULT_SYSTEM_LOSS_PCT,
) -> pd.DataFrame:
    """PVGIS-modelled specific yield (kWh/kWp/yr) on a coarse probe grid spanning
    `bounds` (minx, miny, maxx, maxy), cached at `cache_path` so repeat calls (including
    repeat pipeline runs) don't re-hit PVGIS for a probe already fetched.

    Reuses `specific_yield_kwh_per_kwp` unchanged, just at more points than the single
    region-centroid call `expected_annual_yield` makes. Irradiance is smooth at country
    scale, so a coarse regular grid (default 6x6 = 36 points) is enough to interpolate
    any finer grid-cell centroid from (`interpolate_yield`) without a per-cell PVGIS
    call, which would be both slow (thousands of cells) and unnecessary.
    """
    minx, miny, maxx, maxy = bounds
    side = max(1, round(n_probe ** 0.5))
    lons = np.linspace(minx, maxx, side)
    lats = np.linspace(miny, maxy, side)
    probe_lon, probe_lat = np.meshgrid(lons, lats)
    probe_lon, probe_lat = probe_lon.ravel(), probe_lat.ravel()

    cache_path = Path(cache_path)
    cached = (
        pd.read_csv(cache_path) if cache_path.exists()
        else pd.DataFrame(columns=["lon", "lat", "kwh_per_kwp_yr"])
    )
    have = set(zip(cached["lon"].round(4), cached["lat"].round(4)))

    new_rows = []
    for lon, lat in zip(probe_lon, probe_lat):
        key = (round(float(lon), 4), round(float(lat), 4))
        if key in have:
            continue
        yield_val = specific_yield_kwh_per_kwp(lat, lon, year=year, loss_pct=loss_pct)
        if yield_val is not None:
            new_rows.append({"lon": key[0], "lat": key[1], "kwh_per_kwp_yr": yield_val})

    if new_rows:
        cached = pd.concat([cached, pd.DataFrame(new_rows)], ignore_index=True)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cached.to_csv(cache_path, index=False)

    if cached.empty:
        raise RuntimeError(
            f"No PVGIS probe succeeded for bounds {bounds} -- check network access; "
            f"see {cache_path}"
        )
    log.info(
        "Irradiance probe grid: %d points cached at %s, kwh_per_kwp_yr range %.0f-%.0f "
        "(mean %.0f)", len(cached), cache_path, cached["kwh_per_kwp_yr"].min(),
        cached["kwh_per_kwp_yr"].max(), cached["kwh_per_kwp_yr"].mean(),
    )
    return cached


def interpolate_yield(
    probes: pd.DataFrame, lons: np.ndarray, lats: np.ndarray, k: int = 4,
) -> np.ndarray:
    """Inverse-distance-weighted (power 2) interpolation of `probes`' `kwh_per_kwp_yr` onto
    arbitrary (lon, lat) points, from each point's `k` nearest probes. Plain numpy -- `scipy` is
    not a project dependency.

    Local on purpose. With every probe in the sum, the far ones outweigh the near ones (their
    number grows as distance squared while each weight falls by the same factor), so anywhere
    between probes reads close to the national mean: Punjab's map showed a lattice of dark dots,
    one at each probe, and its yield read high.
    """
    plon = probes["lon"].to_numpy(float)
    plat = probes["lat"].to_numpy(float)
    pval = probes["kwh_per_kwp_yr"].to_numpy(float)
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    k = min(k, len(pval))

    d2 = (lons[:, None] - plon[None, :]) ** 2 + (lats[:, None] - plat[None, :]) ** 2
    near = np.argsort(d2, axis=1)[:, :k]
    w = 1.0 / np.maximum(np.take_along_axis(d2, near, axis=1), 1e-12)  # on a probe: no 1/0
    return (w * pval[near]).sum(axis=1) / w.sum(axis=1)


# Where an AOI's PVGIS probe grid is cached: `roof-potential` writes one beside its density
# run, and `earthpv atlas` (`fetch_irradiance_probes`, on by default) or
# `scripts/patch_atlas_generation.py --fetch` writes `data/irradiance_probes/<aoi>.csv` for a
# country without one, once; every later build reads the cache.
IRRADIANCE_PROBES_DIR = Path("data/irradiance_probes")
DEFAULT_GENERATION_N_PROBE = 100
GENERATION_SOURCE = (
    f"PVGIS-ERA5 2020, fixed panels facing the equator at a tilt equal to the latitude, "
    f"{DEFAULT_SYSTEM_LOSS_PCT:g}% system loss"
)


def irradiance_probes_path(aoi: str, density_dir: Path | None = None) -> Path | None:
    """The cached PVGIS probe grid for an AOI, or None: the density run's own
    (`<density_dir>/irradiance_probes.csv`), else `data/irradiance_probes/<aoi>.csv`."""
    cands = ([Path(density_dir) / "irradiance_probes.csv"] if density_dir else []) + [
        IRRADIANCE_PROBES_DIR / f"{aoi}.csv"]
    return next((c for c in cands if c.exists()), None)


def fetch_irradiance_probes(
    aoi: str, lon0, lat0, n_probe: int = DEFAULT_GENERATION_N_PROBE,
) -> Path | None:
    """Query PVGIS on a regular grid over 0.1 degree cells with corners (`lon0`, `lat0`) and
    cache it as `data/irradiance_probes/<aoi>.csv` (a few minutes; probes already cached are not
    asked again). None, with a warning, when no probe succeeds, e.g. offline."""
    path = IRRADIANCE_PROBES_DIR / f"{aoi}.csv"
    lon0, lat0 = np.asarray(lon0, dtype=float), np.asarray(lat0, dtype=float)
    bounds = (float(lon0.min()) + 0.05, float(lat0.min()) + 0.05,
              float(lon0.max()) + 0.05, float(lat0.max()) + 0.05)
    try:
        grid_specific_yield(bounds, path, n_probe=n_probe)
    except RuntimeError as err:
        log.warning("No PVGIS probe grid for %s: %s", aoi, err)
        return None
    return path


def run_pv_capacity_check(
    aoi: str, pred_dir: Path = Path("data/predictions"), kwp_per_m2: float | None = None,
) -> Path:
    from earthpv.density import DEFAULT_KWP_PER_M2

    kwp_per_m2 = DEFAULT_KWP_PER_M2 if kwp_per_m2 is None else kwp_per_m2
    density_dir = Path(pred_dir) / aoi / "density"
    regions_path = density_dir / "regions.geoparquet"
    if not regions_path.exists():
        raise FileNotFoundError(f"{regions_path} missing - run `earthpv density --aoi {aoi}` first")

    module_check = check_kwp_per_m2(kwp_per_m2)
    yields = expected_annual_yield(regions_path, kwp_per_m2)
    out_csv = density_dir / "regions_yield.csv"
    yields.to_csv(out_csv, index=False)

    summary = {
        "module_check": module_check,
        "total_expected_gwh_det": float(yields["expected_gwh_det"].sum()),
        "total_expected_gwh_exp": float(yields["expected_gwh_exp"].sum()),
    }
    if "expected_gwh_cal" in yields.columns:
        summary["total_expected_gwh_cal"] = float(yields["expected_gwh_cal"].sum())
    (density_dir / "pv_capacity_check.json").write_text(json.dumps(summary, indent=2))
    log.info("Wrote %s and %s", out_csv, density_dir / "pv_capacity_check.json")
    log.info("Summary: %s", json.dumps(summary, indent=2))
    return out_csv
