"""Plausibility checks on the density stage's capacity output.

The leads product has a human on every candidate; the capacity atlas has nobody. A
false-positive mode that survives `p_real` weighting therefore reaches the headline number
unchallenged, and the failure is quiet - a province total simply comes out too large.
These are the cheap, data-only sanity tests the pipeline can run against artifacts it has
already written. `earthpv check-density` runs them and exits non-zero, so a regression
fails CI instead of shipping to the site.

Two independent per-region signals, both from `density/`:

1. **Ground-mount vs rooftop balance** (`nonroof_ratio`). Detections off a building are the
   dominant false-positive mode: bare ground, dry riverbed, salt flat, rock and snow all
   read bright in a dry-season composite, and unlike a rooftop detection nothing constrains
   them to a plausible host. A region whose ground-mount estimate dwarfs its rooftop
   estimate is claiming utility-scale solar that would be independently documented if it
   existed. This check exists because Pakistan's Gilgit-Baltistan - Karakoram rock and
   glacier - scored 166 MWp all-PV against 0.8 MWp rooftop, a ratio near 200.

2. **Single-cell concentration** (`top_cell_share`). `postprocess` merges every touching
   thresholded pixel into one polygon with no upper bound, so one blob can carry a whole
   province. If a single 0.1 deg cell holds more than `max_cell_share` of a region's
   capacity, that region's total is one object, not a population, and no amount of
   per-bin calibration makes it a statistic.

Both need an absolute floor as well as a ratio: a region holding 0.3 MWp of ground-mount
against 0.05 MWp of rooftop has a ratio of 6 and means nothing. `min_nonroof_mwp` is that
floor, so the checks fire on regions large enough for the answer to matter.

The national `oversize` count that `density` excluded is reported alongside (from
`meta.json`), because a jump there is the leading indicator for both checks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

log = logging.getLogger(__name__)

# A region with 3x more ground-mount than rooftop capacity is worth a look; 5x is a
# finding. Pakistan's real provinces land at 1.9-3.8, so the warn threshold sits just
# above the plausible band rather than being tuned to it.
NONROOF_RATIO_WARN = 3.0
NONROOF_RATIO_FAIL = 5.0
# Below this much ground-mount capacity the ratio is noise, not a claim.
MIN_NONROOF_MWP = 50.0
# One 0.1 deg cell (~110 km2) holding this share of a province is a merged blob.
MAX_CELL_SHARE = 0.25

# Regions exempted from check 1 (ground-mount vs rooftop balance) specifically, not from
# check 2 (single-cell concentration) or from the report. Gilgit-Baltistan's real rooftop
# base rate is close to zero (sparse Karakoram settlement), so any ground-mount signal at
# all there - bug or genuine remote solar - reads as an extreme ratio; the ratio check is
# structurally uninformative for it rather than a useful signal. This does NOT mean its
# absolute ground-mount number is trusted. The ratio failures that originally motivated
# this exemption in KP/Balochistan were root-caused in 2026-08-11 as pooled rooftop and
# ground-mount precision/recall (fixed via capacity_calibration.derive_placement_tables;
# KP moved 3.35-8x -> 0.49x), and this exemption survives on its own separate ground: a
# near-zero rooftop base rate makes the ratio uninformative here regardless. See
# docs/open-questions.md.
RATIO_CHECK_EXEMPT_REGIONS = {"Gilgit-Baltistan"}

_STATUS_ORDER = {"fail": 0, "suspect": 1, "ok": 2}

# Preference order for the (rooftop, ground, total) capacity triple. The recall-corrected
# split is the headline estimator; the calibrated one is the fallback for a run with no
# recall reference (where it also covers the uncalibrated case, since cal degenerates to
# det). Legacy outputs predating the placement-split conversion carry no `*_ground` column,
# so it is derived as total - rooftop there, which is right for those files: they applied
# one constant throughout.
_METRIC_CHAIN = (
    ("est_mwp_rc_roof", "est_mwp_rc_ground", "est_mwp_rc"),
    ("est_mwp_cal_total_roofcand", "est_mwp_cal_total_ground", "est_mwp_cal_total"),
)


def _resolve_metric(cols: set[str]) -> tuple[str, str | None, str] | None:
    """First (roof, ground, total) triple in `_METRIC_CHAIN` this frame can serve."""
    for roof_col, ground_col, total_col in _METRIC_CHAIN:
        if roof_col not in cols:
            continue
        if ground_col in cols or total_col in cols:
            return roof_col, ground_col if ground_col in cols else None, total_col
    return None


def _top_cell_shares(density_dir: Path, regions: gpd.GeoDataFrame, total_col: str) -> pd.DataFrame:
    """Largest single cell's name and capacity share per region.

    Repeats `density.aggregate`'s cell-centroid-in-region join rather than trusting a
    stored region column, so this stays a check on the published layers instead of on an
    intermediate the same code path produced.
    """
    empty = pd.DataFrame({"id": [], "top_cell": [], "top_cell_mwp": [], "top_cell_share": []})
    grid_path = density_dir / "grid.geoparquet"
    if not grid_path.exists():
        log.warning("%s missing - skipping the concentration check", grid_path)
        return empty
    grid = gpd.read_parquet(grid_path)
    if grid.empty or total_col not in grid.columns:
        log.warning("grid layer has no %s - skipping the concentration check", total_col)
        return empty
    centroids = gpd.GeoDataFrame(
        grid[["cell", total_col]],
        geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs="EPSG:4326",
    )
    j = gpd.sjoin(centroids, regions[["id", "geometry"]], how="inner", predicate="within")
    if j.empty:
        return empty
    rows = []
    for rid, grp in j.groupby("id"):
        total = float(grp[total_col].sum())
        top = grp.loc[grp[total_col].idxmax()]
        rows.append({
            "id": rid,
            "top_cell": str(top["cell"]),
            "top_cell_mwp": round(float(top[total_col]), 3),
            "top_cell_share": round(float(top[total_col]) / total, 4) if total > 0 else 0.0,
        })
    return pd.DataFrame(rows)


def check_density(
    aoi: str,
    pred_dir: Path = Path("data/predictions"),
    warn_ratio: float = NONROOF_RATIO_WARN,
    fail_ratio: float = NONROOF_RATIO_FAIL,
    min_nonroof_mwp: float = MIN_NONROOF_MWP,
    max_cell_share: float = MAX_CELL_SHARE,
) -> tuple[pd.DataFrame, dict]:
    """Run the plausibility checks over an AOI's density output.

    Returns `(per-region table, summary)` and writes the table to
    `density/plausibility.csv`. Every region gets a `status` of ok / suspect / fail and a
    `reason`; `summary["n_fail"]` is what a CI caller should gate on. Raises
    `FileNotFoundError` if the density stage has not run, and returns an empty table with
    `summary["status"] = "skipped"` when the output carries no admin-region layer (nothing
    to check against, which is not the same as passing).
    """
    density_dir = Path(pred_dir) / aoi / "density"
    regions_path = density_dir / "regions.geoparquet"
    if not regions_path.exists():
        raise FileNotFoundError(
            f"{regions_path} missing - run `earthpv density --aoi {aoi}` first"
        )
    meta_path = density_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    reg = gpd.read_parquet(regions_path)
    reg = reg[reg.get("level", "region") == "region"].reset_index(drop=True)
    # `density.aggregate` writes the geoBoundaries key as `region_id`; normalise to `id`
    # (and synthesise one if a hand-supplied --regions-file carried neither) so the
    # concentration join below has something stable to group on.
    if "id" not in reg.columns:
        reg["id"] = (
            reg["region_id"] if "region_id" in reg.columns else reg.index.astype(str)
        )
    summary: dict = {
        "aoi": aoi,
        "n_regions": int(len(reg)),
        "warn_ratio": warn_ratio,
        "fail_ratio": fail_ratio,
        "min_nonroof_mwp": min_nonroof_mwp,
        "max_cell_share": max_cell_share,
        "n_oversize_excluded": meta.get("n_oversize_excluded"),
        "oversize_area_m2": meta.get("oversize_area_m2"),
        "max_candidate_m2": meta.get("max_candidate_m2"),
        "kwp_per_m2_module": meta.get("kwp_per_m2_module", meta.get("kwp_per_m2")),
        "kwp_per_m2_land": meta.get("kwp_per_m2_land"),
    }
    if reg.empty:
        summary.update({"status": "skipped", "n_fail": 0, "n_suspect": 0,
                        "note": "no admin-region layer in the density output"})
        return pd.DataFrame(), summary

    metric = _resolve_metric(set(reg.columns))
    if metric is None:
        summary.update({"status": "skipped", "n_fail": 0, "n_suspect": 0,
                        "note": "regions layer carries no recognised capacity estimator"})
        return pd.DataFrame(), summary
    roof_col, ground_col, total_col = metric
    summary["metric"] = total_col
    summary["ground_source"] = ground_col or f"{total_col} - {roof_col}"

    out = pd.DataFrame({
        "region": reg["name"].astype(str),
        "id": reg["id"],
        "mwp_roof": reg[roof_col].astype(float).round(3),
    })
    if ground_col is not None:
        out["mwp_ground"] = reg[ground_col].astype(float).round(3)
    else:  # legacy output: _resolve_metric only drops ground_col when total_col is present
        out["mwp_ground"] = (reg[total_col] - reg[roof_col]).clip(lower=0.0).astype(float).round(3)
    out["mwp_total"] = (out.mwp_roof + out.mwp_ground).round(3)
    # A region with rooftop capacity at or near zero has an undefined ratio, not an
    # infinite one; report it as the ratio against a 0.001 MWp floor so it sorts worst
    # rather than turning into NaN and silently passing.
    out["nonroof_ratio"] = (out.mwp_ground / out.mwp_roof.clip(lower=1e-3)).round(2)

    shares = _top_cell_shares(density_dir, reg, total_col)
    if not shares.empty:
        out = out.merge(shares, on="id", how="left")
    for col, default in (("top_cell", None), ("top_cell_mwp", 0.0), ("top_cell_share", 0.0)):
        if col not in out.columns:
            out[col] = default

    statuses, reasons = [], []
    for r in out.itertuples():
        notes, status = [], "ok"
        exempt = r.region in RATIO_CHECK_EXEMPT_REGIONS
        big_enough = r.mwp_ground >= min_nonroof_mwp
        if exempt:
            notes.append(
                f"check 1 (ground-mount:rooftop) exempted for {r.region} - "
                f"ratio {r.nonroof_ratio:.0f}x not evaluated, see RATIO_CHECK_EXEMPT_REGIONS"
            )
        elif r.nonroof_ratio >= fail_ratio and big_enough:
            status = "fail"
            notes.append(
                f"ground-mount {r.mwp_ground:,.0f} MWp is {r.nonroof_ratio:.0f}x rooftop "
                f"({r.mwp_roof:,.1f} MWp)"
            )
        elif r.nonroof_ratio >= warn_ratio:
            status = "suspect"
            notes.append(
                f"ground-mount is {r.nonroof_ratio:.1f}x rooftop"
                + ("" if big_enough else f" (only {r.mwp_ground:,.1f} MWp, below the floor)")
            )
        share = float(r.top_cell_share or 0.0)
        if share > max_cell_share and r.mwp_total >= min_nonroof_mwp:
            status = "fail"
            notes.append(f"cell {r.top_cell} alone is {share:.0%} of the region total")
        statuses.append(status)
        reasons.append("; ".join(notes))
    out["status"] = statuses
    out["reason"] = reasons

    out = out.sort_values(
        ["status", "mwp_ground"], key=lambda s: s.map(_STATUS_ORDER) if s.name == "status" else -s
    ).reset_index(drop=True)
    csv_path = density_dir / "plausibility.csv"
    out.to_csv(csv_path, index=False)

    n_fail = int((out.status == "fail").sum())
    summary.update({
        "status": "fail" if n_fail else ("suspect" if (out.status == "suspect").any() else "ok"),
        "n_fail": n_fail,
        "n_suspect": int((out.status == "suspect").sum()),
        "mwp_roof": round(float(out.mwp_roof.sum()), 3),
        "mwp_ground": round(float(out.mwp_ground.sum()), 3),
        "mwp_total": round(float(out.mwp_total.sum()), 3),
        "report": str(csv_path),
    })
    log.info("Plausibility: %s (%d fail, %d suspect) -> %s",
             summary["status"], summary["n_fail"], summary["n_suspect"], csv_path)
    return out, summary
