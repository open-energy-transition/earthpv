"""Redistribute an externally-supplied total PV capacity across this project's own
measured spatial shape.

Every other capacity number in this project is this pipeline's OWN estimate. This
module answers a different question: given a total capacity from an independent,
possibly more-trusted source (e.g. Pakistan's NEPRA net-metering register, ~5.3-6.3
GW nationally), how should that total be spread across cells/regions/buildings --
using the RELATIVE shape this project's Sentinel-2 detections measure, not this
project's own absolute number.

Kept deliberately out of density.py, matching this project's established convention
(sub400_capacity.py, pv_capacity.py, roofclf_capacity.py, plausibility.py are all
separate modules reading density/'s finished outputs for the same reason -- promoting
a different instrument INTO density.py's aggregation path has broken `check-density`
more than once, documented at length in docs/methods/density.md). This module only
ever reads grid.geoparquet/regions.geoparquet/buildings.geoparquet and writes its own
new sibling artifact; it never mutates density's own output files.

OPEN, UNTESTED ASSUMPTION: an external total necessarily includes small (< 400 m2) PV,
which this project cannot detect directly, so distributing it by the shape of the
>= 400 m2 population this project CAN validate assumes small-PV's spatial
distribution tracks large-PV's. The one place this has been looked at qualitatively
-- existing candidate density anti-correlates with true small-PV base rate in two
illustrative quadrats (Karachi coastal, Lahore; see docs/methods/density.md) -- leans
against the assumption, though it has never been computed as a formal statistic
across all quadrats. Treat every number this module produces as conditional on that
assumption holding, not as validated.

V1 SHIP SCOPE: point estimates only. `est_mwp_rc`'s posterior draws
(density._candidate_uncertainty) are not threaded through here -- doing so correctly
would require either persisting those draws to disk from density.py (an output-
contract change this module's whole reason for existing argues against) or
recomputing them from candidates.parquet + the calibration table here (real
duplicated work, not a fast post-hoc transform). A distributed credible interval is
left as a named, explicit follow-up, not attempted silently.

Also note: this module redistributes one chosen estimator column as a single
combined total. If a cell's roof/ground-mount split (`_roofcand`/`_ground`) were
separately redistributed alongside it, the implied kWp/m2 conversion for that cell
would no longer be the documented 0.18/0.07 constants -- it would be whatever
multiplier matched the external total. This module does not attempt that split.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_ESTIMATOR = "est_mwp_rc"
# regions.geoparquet carries province ("region") and district ("county") rows in ONE
# file, both independently summing to the same national total (see
# docs/methods/density.md's documented "summed across both, doubling it" bug). Any
# region-scope operation here filters to one level first; this is that default.
DEFAULT_REGION_LEVEL = "region"


def redistribute(series: pd.Series, external_total: float) -> pd.Series:
    """Each value's share of `series`'s own sum, times `external_total`.

    If `series` sums to <= 0 (no measured signal at all to allocate by -- e.g. an
    empty or all-zero region), splits `external_total` equally across every row
    instead of returning NaN or a silent zero: a group with no measured shape still
    receives its portion of a known total, it just can't be shaped by this
    instrument.
    """
    total = float(series.sum())
    n = len(series)
    if total <= 0:
        return pd.Series(external_total / n if n else 0.0, index=series.index)
    return series / total * external_total


def _validate_estimator(df: pd.DataFrame, estimator: str, source: str) -> None:
    if estimator in df.columns:
        return
    if source.startswith("buildings"):
        raise ValueError(
            f"{estimator!r} is not a column of {source} -- buildings.geoparquet only "
            "has est_kwp_{det,cal,exp} (kWp, not MWp: recall-correction and the "
            "roof/ground split are cell/region-level concepts with no per-building "
            "analogue). --total-capacity's units must match whichever column you pick."
        )
    raise ValueError(
        f"{estimator!r} is not a column of {source} -- choose one of this project's "
        "est_mwp_{det,cal,exp,rc,rc_roof,cal_total} columns (MWp)"
    )


def distribute_national(
    density_dir: Path, external_total: float, estimator: str = DEFAULT_ESTIMATOR,
    grain: str = "grid", out: Path | None = None,
) -> Path:
    """Single external total, redistributed nationally across every row of `grain`
    (grid cells or buildings) by `estimator`'s own relative shape. Writes a new
    sibling file (e.g. density/capacity_distributed_grid.geoparquet); grid.
    geoparquet/buildings.geoparquet are never modified in place.
    """
    density_dir = Path(density_dir)
    path = density_dir / f"{grain}.geoparquet"
    df = gpd.read_parquet(path)
    _validate_estimator(df, estimator, path.name)

    df = df.copy()
    out_col = f"{estimator}_distributed"
    df[out_col] = redistribute(df[estimator], external_total)

    out = Path(out) if out else density_dir / f"capacity_distributed_{grain}.geoparquet"
    df.to_parquet(out)
    df.drop(columns="geometry").to_csv(out.with_suffix(".csv"), index=False)
    log.info(
        "Distributed %.1f MWp nationally across %d %s rows by %s's shape "
        "(sum check: %.1f) -> %s",
        external_total, len(df), grain, estimator, float(df[out_col].sum()), out,
    )
    return out


def _region_label_for_grid(
    grid: gpd.GeoDataFrame, density_dir: Path, level: str
) -> pd.Series:
    """grid.geoparquet carries no 'region' column (only buildings.geoparquet does,
    from density.aggregate's own spatial join) -- derive one here via the same safe
    spatial-join-against-actual-polygons pattern atlas.py's `_join_buildings_to_grid_
    cells`/`build_evidence_atlas` already establish, rather than trusting any id
    string. Returns a Series indexed like `grid`, NaN where a cell's centroid falls
    outside every regions.geoparquet polygon at this level."""
    regions_path = density_dir / "regions.geoparquet"
    if not regions_path.exists():
        raise FileNotFoundError(f"{regions_path} missing -- region-scope redistribution needs it")
    regions = gpd.read_parquet(regions_path)
    scoped = regions[regions["level"] == level]
    pts = gpd.GeoDataFrame(
        {"__row": grid.index},
        geometry=gpd.points_from_xy(grid["lon_center"], grid["lat_center"]), crs=grid.crs,
    )
    joined = gpd.sjoin(pts, scoped[["name", "geometry"]], predicate="within", how="left")
    n_unmatched = int(joined["name"].isna().sum())
    if n_unmatched:
        log.warning(
            "%d of %d grid cells fall outside every %s-level region polygon -- "
            "excluded from region-scope redistribution, not a join bug",
            n_unmatched, len(grid), level,
        )
    return joined.groupby("__row")["name"].first().reindex(grid.index)


def distribute_by_region(
    density_dir: Path, region_totals: dict[str, float],
    estimator: str = DEFAULT_ESTIMATOR, grain: str = "grid",
    level: str = DEFAULT_REGION_LEVEL, out: Path | None = None,
) -> Path:
    """One external total per region (`region_totals`, keyed by the exact region
    name string), each spread across that region's own rows by `estimator`'s LOCAL
    shape within the region -- not the national shape.

    `grain="buildings"` uses buildings.geoparquet's own `region` column (already
    written by density.aggregate's spatial join). `grain="grid"` has no such column
    on grid.geoparquet, so this derives one via `_region_label_for_grid`'s safe
    spatial join rather than assuming one exists.

    A row whose region has no entry in `region_totals` gets NaN, not a guessed
    value or a silent zero -- a warning names exactly which regions were skipped, so
    a caller can tell an intentional gap from a typo in the mapping.
    """
    density_dir = Path(density_dir)
    path = density_dir / f"{grain}.geoparquet"
    df = gpd.read_parquet(path)
    _validate_estimator(df, estimator, path.name)

    if grain == "buildings":
        if "region" not in df.columns:
            raise ValueError(f"{path} has no 'region' column")
        region_labels = df["region"]
    else:
        region_labels = _region_label_for_grid(df, density_dir, level)

    present = set(region_labels.dropna().unique())
    missing = present - set(region_totals)
    if missing:
        log.warning(
            "%d of %d regions present in %s have no entry in region_totals -- their "
            "rows get NaN rather than a guess: %s",
            len(missing), len(present), path.name, sorted(missing),
        )

    out_col = f"{estimator}_distributed"
    df = df.copy()
    df["__region_label"] = region_labels.to_numpy()
    parts = []
    for name, sub in df.groupby("__region_label", dropna=False):
        sub = sub.copy()
        sub[out_col] = (
            redistribute(sub[estimator], region_totals[name]) if name in region_totals
            else float("nan")
        )
        parts.append(sub)
    df = pd.concat(parts).sort_index().drop(columns="__region_label")

    out = (
        Path(out) if out
        else density_dir / f"capacity_distributed_{grain}_by_region.geoparquet"
    )
    df.to_parquet(out)
    df.drop(columns="geometry").to_csv(out.with_suffix(".csv"), index=False)
    log.info(
        "Distributed %d region totals (%.1f MWp combined) across %d %s rows by "
        "%s's local shape -> %s",
        len(region_totals), sum(region_totals.values()), len(df), grain, estimator, out,
    )
    return out


def load_region_totals(path: Path) -> dict[str, float]:
    """CSV (two columns: region name, total MWp -- header optional) or YAML
    (`region: total_mwp` mapping) of per-region external totals. Keys must match
    whichever `level` regions.geoparquet's `name` column uses for the admin
    granularity being targeted (province by default) -- this loader does not itself
    check the level, since the mapping is only ever matched against grid/buildings'
    own region labels at redistribution time, where a mismatch surfaces as a named
    warning rather than silently.
    """
    path = Path(path)
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml

        return {str(k): float(v) for k, v in yaml.safe_load(path.read_text()).items()}
    df = pd.read_csv(path, header=None, names=["region", "total_mwp"])
    # A real header row ("region,total_mwp") parses its own text as a non-numeric
    # first data row; drop it if present rather than requiring --no-header.
    df = df[pd.to_numeric(df["total_mwp"], errors="coerce").notna()]
    return dict(zip(df["region"].astype(str), df["total_mwp"].astype(float)))
