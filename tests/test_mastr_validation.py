"""Self-tests for the MaStR validation harness (`earthpv.mastr_validation`).

`validate_density_against_mastr` cannot be exercised against real data yet -- Germany has
composites for 14 of its 76 MGRS tiles and no per-cell density run at all -- so without
these it would ship completely unrun. They feed it a synthetic grid built FROM the register
so the correct answers are known in advance: a grid carrying exactly MaStR's own capacity
must come back with slope 1.0, and one carrying half of it with slope 0.5.

Run with `pixi run -e default python -m pytest tests/ -q` (pytest is not currently a
declared dependency; these are written to also run as a plain script).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.mastr_validation import (
    MIN_NATIONAL_COVERAGE,
    SEG_FLOOR_KWP,
    size_regime_shares,
    small_pv_share_dispersion,
    validate_density_against_mastr,
)

CALIB = Path("data/calibration")


def _synthetic_counts(n: int = 40) -> pd.DataFrame:
    """A register-shaped frame: `n` municipalities, a known share below the floor."""
    rng = np.random.default_rng(0)
    kw = rng.uniform(500, 50_000, n)
    below = kw * 0.6  # exactly 60% of every municipality's capacity is sub-floor
    return pd.DataFrame({
        "ags": [f"{i:08d}" for i in range(n)],
        "n_rooftop_units": rng.integers(50, 5000, n),
        "kw_rooftop": kw,
        f"kw_le_{SEG_FLOOR_KWP:g}": below,
        f"n_le_{SEG_FLOOR_KWP:g}": rng.integers(40, 4000, n),
        "kw_le_100": kw * 0.7,
        "n_le_100": rng.integers(45, 4500, n),
    })


def test_size_regime_shares_recovers_a_known_share() -> None:
    got = size_regime_shares(_synthetic_counts(), kwp_thresholds=(SEG_FLOOR_KWP, 100.0))
    assert abs(got["share_below_seg_floor"] - 0.6) < 1e-9, got["share_below_seg_floor"]
    assert abs(got["capacity_share_below"]["le_100_kwp"] - 0.7) < 1e-9


def test_dispersion_reports_zero_spread_when_the_share_is_constant() -> None:
    got = small_pv_share_dispersion(_synthetic_counts())["seg_floor"]
    # Every municipality has the same 0.6 share, so weighted and unweighted means agree
    # and the spread is zero -- the degenerate case the real data is very far from.
    assert abs(got["capacity_weighted_mean"] - 0.6) < 1e-9
    assert abs(got["unweighted_mean"] - 0.6) < 1e-9
    assert got["sd"] < 1e-9


def _write_grid(tmp: Path, gem: gpd.GeoDataFrame, counts: pd.DataFrame, factor: float) -> Path:
    """A density grid whose cells sit at municipality centroids and carry `factor` x truth."""
    pts = gem.geometry.representative_point()
    grid = gpd.GeoDataFrame({
        "cell": [f"c{i:04d}" for i in range(len(gem))],
        "lon_center": pts.x.to_numpy(),
        "lat_center": pts.y.to_numpy(),
        "est_mwp_rc_roof": gem.ags.map(
            counts.set_index("ags").kw_rooftop / 1000.0 * factor
        ).fillna(0.0).to_numpy(),
        "geometry": pts,
    }, crs="EPSG:4326")
    d = tmp / "density"
    d.mkdir(parents=True, exist_ok=True)
    grid.to_parquet(d / "grid.geoparquet")
    return d


def test_harness_recovers_slope_one_and_one_half(tmp_path: Path) -> None:
    """Feeding the register back through the harness must return slope 1.0; feeding half
    of it must return 0.5. This is what pins the arithmetic (units, the origin-forced OLS,
    the kW->MWp conversion) rather than merely running it."""
    gem = gpd.read_parquet(CALIB / "vg250_gem.parquet").head(200).reset_index(drop=True)
    counts = pd.read_parquet(CALIB / "mastr_rooftop_counts.parquet")
    counts = counts[counts.ags.isin(gem.ags)].reset_index(drop=True)

    for factor, expected in ((1.0, 1.0), (0.5, 0.5)):
        d = _write_grid(tmp_path / f"f{factor}", gem, counts, factor)
        got = validate_density_against_mastr(d, counts, CALIB / "vg250_gem.parquet")
        r = got["results"]["est_mwp_rc_roof"]
        assert abs(r["slope_ols_origin"] - expected) < 1e-6, r
        assert abs(r["median_ratio"] - expected) < 1e-6, r
        assert abs(r["spearman_rho"] - 1.0) < 1e-9, r
        # 200 of ~11k municipalities is far below the national-coverage bar, so the harness
        # must refuse to call this a national accuracy statement.
        assert got["coverage_frac"] < MIN_NATIONAL_COVERAGE
        assert got["verdict"].startswith("PARTIAL COVERAGE"), got["verdict"]


def test_missing_estimator_columns_are_reported_not_silently_dropped(tmp_path: Path) -> None:
    gem = gpd.read_parquet(CALIB / "vg250_gem.parquet").head(50).reset_index(drop=True)
    counts = pd.read_parquet(CALIB / "mastr_rooftop_counts.parquet")
    counts = counts[counts.ags.isin(gem.ags)].reset_index(drop=True)
    d = _write_grid(tmp_path / "m", gem, counts, 1.0)
    got = validate_density_against_mastr(d, counts, CALIB / "vg250_gem.parquet")
    assert "est_mwp_exp" in got["estimators_missing_from_grid"]
    assert "est_mwp_rc_roof" not in got["estimators_missing_from_grid"]


if __name__ == "__main__":
    import tempfile

    test_size_regime_shares_recovers_a_known_share()
    test_dispersion_reports_zero_spread_when_the_share_is_constant()
    with tempfile.TemporaryDirectory() as t:
        test_harness_recovers_slope_one_and_one_half(Path(t))
    with tempfile.TemporaryDirectory() as t:
        test_missing_estimator_columns_are_reported_not_silently_dropped(Path(t))
    print("all mastr_validation self-tests passed")
