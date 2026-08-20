"""Two-epoch PV growth from the evidence atlas's own instruments.

The first growth map (scripts/pv_growth_map.py, 2026-08-06) diffed two `density` runs
made with DIFFERENT segmentation checkpoints (current: v3_combined_india, pre-boom: an
undocumented pk16085 variant -- both since deleted from disk), with the pre-2026-08-11
pooled calibration and the old 0.07 land constant on the pre-boom side, and with no
roofclf half at all -- so it measured the >= 400 m2 segmentation floor only, through an
instrument that changed between the two epochs. This module supersedes that product.

Here both epochs go through ONE identical instrument pair -- the same segmentation
checkpoint for both epochs' inference, the same placement-split calibration YAML for
both `density` runs, and the same fitted roofclf model + coverage-ratio/area-recall
tables scoring both epochs' composites -- and the combination per cell mirrors
`atlas.build_evidence_atlas`'s Best-estimate composition, minus its hand-mapped OSM
component (OSM install dates don't exist, so mapped features cannot be assigned to an
epoch; both epochs' model components are deduplicated against the SAME present-day OSM
pull instead, which cancels in the diff):

- ground-mount: segmentation `est_mwp_rc_ground`, both epochs;
- rooftop, inside the density-calibrated domain (`density.CALIBRATED_BLDG_DENSITY_KM2`
  over the shared national cell-density table): roofclf's >= 400 m2 rooftop replacement,
  both epochs;
- rooftop, outside that domain: segmentation `est_mwp_rc_roof`, both epochs;
- sub-400 m2: roofclf's central estimate, both epochs.

**What a pre-boom roofclf/segmentation level means here.** Every calibration in this
project (candidate precision, coverage ratio, area recall, the roofclf fit itself) is
measured against current-epoch mapping and imagery. Applying it to the pre-boom epoch
assumes those calibrations transfer across epochs; that is untestable without pre-boom
ground truth and is exactly why this module publishes epoch DIFFS of a fixed instrument,
never a standalone historical capacity level. The systematic part of any calibration
error is shared by both epochs and largely cancels in the difference; what does not
cancel is documented in the summary's `caveats`.

**Negative per-cell deltas are kept, not clamped.** A cell where the instrument reads
lower in the current epoch than pre-boom is instrument noise (or, rarely, a real
decommissioning); clamping at zero would bias the national total up. The summary reports
the negative mass separately so its size is visible.

**The pre-boom segmentation level is persistence-gated** (`persistence_gate`, default
50 m, disable with `persistence_gate_m=0`): a pre-boom candidate with no current-epoch
candidate anywhere near it is dropped before the pre-boom level is recomputed
(`_seg_rc_cell_mwp`, the exact per-candidate est_mwp_rc math). The physical prior is
that PV is almost never decommissioned, so a real pre-boom installation must still be
detectable by the same instrument on the better (snow-free) current composite. The
2026-08-20 sanity check that motivated this found only 26.6% of pre-boom candidates
had any current counterpart within 50 m (rooftop 86%, ground_adjacent 44%, no_building
5.6%) with 91 of 155 km2 of vanishing area above lat 34 deg -- winter snow in the
2021-10..2022-01 composite, an FP mode the precision calibration never saw and that
made the ungated ground delta negative. The gate is one-directional by construction:
current-epoch-only false positives cannot be gated (indistinguishable from genuine new
installations) and are priced by p_real alone, so the residual FP bias on the delta is
upward -- see the summary's `caveats` and `persistence_gate` block.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger("growth")

# Column pulled from each epoch's segmentation density grid, per placement.
SEG_COLS = ["est_mwp_rc", "est_mwp_rc_roof", "est_mwp_rc_ground"]

# Pre-boom candidates with no current-epoch candidate within this distance are gated
# out of the pre-boom segmentation level (see persistence_gate).
PERSISTENCE_GATE_M = 50.0


def persistence_gate(
    pre_cands: gpd.GeoDataFrame,
    cur_cands: gpd.GeoDataFrame,
    max_dist_m: float = PERSISTENCE_GATE_M,
) -> tuple[np.ndarray, dict]:
    """Mask of pre-boom candidates corroborated by ANY current-epoch candidate within
    `max_dist_m` (metric, EPSG:6933), plus survival stats.

    Physical prior: PV is almost never decommissioned, so a real pre-boom installation
    still exists -- and is detectable by the SAME instrument on the better (snow-free
    dry-season) current composite. A pre-boom-only detection is therefore a false
    positive with near-certainty; keeping it inflates the pre-boom level and biases the
    growth delta down (measured 2026-08-20: it flipped the ground delta negative).

    Applied to EVERY pre-boom candidate, OSM-geometry-matched ones included: a real
    (OSM-mapped) installation the current-epoch model misses entirely contributes zero
    to the current level, so keeping it pre-boom would book a spurious negative delta
    for capacity the diff's current side does not carry; gating it books the honest
    0 - 0. Corroboration is tested against the RAW current candidate set (oversize
    blobs included) -- an oversize current detection is still presence evidence, even
    though it earns no capacity itself.
    """
    pre_m = pre_cands.reset_index(drop=True).to_crs(6933)
    cur_m = cur_cands.to_crs(6933)
    joined = gpd.sjoin_nearest(
        pre_m, cur_m[["geometry"]], how="left",
        max_distance=max_dist_m, distance_col="_gate_d",
    )
    survives = joined.groupby(level=0)["_gate_d"].min().notna().to_numpy()
    placement = (
        pre_cands["placement"].astype(str).to_numpy()
        if "placement" in pre_cands.columns else np.array(["unknown"] * len(pre_cands))
    )
    by_placement = {
        str(p): round(float(survives[placement == p].mean()), 4)
        for p in np.unique(placement)
    }
    stats = {
        "max_dist_m": float(max_dist_m),
        "n_population": int(len(pre_cands)),
        "n_gated_out": int((~survives).sum()),
        "share_gated_out": round(float((~survives).mean()), 4),
        "gated_out_area_m2": round(float(pre_cands.loc[~survives, "area_m2"].sum()), 1),
        "survival_by_placement": by_placement,
    }
    return survives, stats


def _seg_rc_cell_mwp(
    cands: gpd.GeoDataFrame,
    table: dict,
    origin: tuple[float, float],
    manifest_cells: set[str],
    recall_floor: float,
    kwp_module: float,
    kwp_land: float,
) -> pd.DataFrame:
    """Per-cell recall-corrected segmentation MWp (SEG_COLS) recomputed from a candidate
    frame -- the exact point-estimate math of `density._candidate_uncertainty`
    (rc = area * p_real / recall, cell assignment by representative point) and
    `density._ratios`' placement split (rooftop-placed at the module constant, the
    remainder at the land constant). Verified 2026-08-20 to reproduce a stored
    grid.geoparquet's est_mwp_rc columns to rounding (max per-cell diff 5e-5 MWp)."""
    from earthpv import capacity_calibration as cc
    from earthpv.density import CELL_DEG

    area = cands["area_m2"].to_numpy(float)
    placement = cands["placement"].astype(str).to_numpy()
    p_real = cc.candidate_p_real(area, table, glint_consistent=(
        cands["glint_consistent"].to_numpy() if "glint_consistent" in cands.columns
        else None), placement=placement)
    recall = cc.candidate_recall(area, table, floor=recall_floor, placement=placement)
    rc = area * p_real / recall
    reps = cands.geometry.representative_point()
    ix = np.floor((reps.x.to_numpy() - origin[0]) / CELL_DEG).astype(int)
    iy = np.floor((reps.y.to_numpy() - origin[1]) / CELL_DEG).astype(int)
    cell = np.array([f"{i:04d}_{j:04d}" for i, j in zip(ix, iy)])
    roof = placement == "rooftop"
    df = pd.DataFrame({"cell": cell, "rc": rc, "rc_roof": np.where(roof, rc, 0.0)})
    df = df[df["cell"].isin(manifest_cells)]
    per = df.groupby("cell", as_index=False).sum()
    per["est_mwp_rc_roof"] = (per.rc_roof * kwp_module / 1000.0).round(4)
    per["est_mwp_rc_ground"] = ((per.rc - per.rc_roof).clip(lower=0.0) * kwp_land / 1000.0).round(4)
    per["est_mwp_rc"] = (per.est_mwp_rc_roof + per.est_mwp_rc_ground).round(4)
    return per[["cell", *SEG_COLS]]


def _gate_preboom_grid(
    aoi: str,
    preboom_pred_dir: Path,
    current_pred_dir: Path,
    pre: pd.DataFrame,
    max_dist_m: float,
) -> tuple[pd.DataFrame, dict]:
    """Replace the pre-boom grid's SEG_COLS with values recomputed from the
    persistence-gated candidate population; the ungated originals are kept alongside
    as `*_preboom_ungated`. Returns (grid, stats-for-summary)."""
    from earthpv import capacity_calibration as cc
    from earthpv.config import Settings
    from earthpv.density import _grid_origin, capacity_relevant_candidates
    from earthpv.labels import resolve_aoi

    meta = json.loads(
        (Path(preboom_pred_dir) / aoi / "density" / "meta.json").read_text())
    pre_cands = gpd.read_parquet(Path(preboom_pred_dir) / aoi / "candidates.parquet")
    cur_cands = gpd.read_parquet(Path(current_pred_dir) / aoi / "candidates.parquet")
    pop, _ = capacity_relevant_candidates(pre_cands, meta["max_candidate_m2"])
    pop = pop.reset_index(drop=True)
    table = cc.load_table(Path(meta["calibration"]))
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    origin = _grid_origin(aoi, cfg, settings)
    manifest = set(pre["cell"])
    kwargs = dict(
        table=table, origin=origin, manifest_cells=manifest,
        recall_floor=meta["recall_floor"], kwp_module=meta["kwp_per_m2_module"],
        kwp_land=meta["kwp_per_m2_land"],
    )

    # Guard: the ungated recompute must reproduce the stored grid before the gated
    # version may replace it -- a mismatch means candidates.parquet or the calibration
    # YAML changed since that density run, and gating would silently mix vintages.
    ungated = _seg_rc_cell_mwp(pop, **kwargs)
    stored = pre.set_index("cell")["est_mwp_rc"].fillna(0.0)
    recomputed = ungated.set_index("cell")["est_mwp_rc"].reindex(stored.index).fillna(0.0)
    max_diff = float((stored - recomputed).abs().max())
    if max_diff > 0.01:
        raise RuntimeError(
            f"Ungated recompute of {aoi}'s pre-boom est_mwp_rc disagrees with the "
            f"stored density grid (max per-cell diff {max_diff:.4f} MWp > 0.01). "
            f"{preboom_pred_dir}/{aoi}/candidates.parquet or {meta['calibration']} "
            "has changed since that density run -- re-run `earthpv density` on the "
            "pre-boom pred dir first, or pass persistence_gate_m=0."
        )

    survives, stats = persistence_gate(pop, cur_cands, max_dist_m)
    gated = _seg_rc_cell_mwp(pop[survives], **kwargs).set_index("cell")
    pre = pre.copy()
    for col in SEG_COLS:
        pre[f"{col}_preboom_ungated"] = pre[col]
        pre[col] = pre["cell"].map(gated[col]).fillna(0.0)
    stats["recompute_max_cell_diff_mwp"] = round(max_diff, 6)
    stats["preboom_seg_mwp_ungated"] = {
        c: round(float(ungated[c].sum()), 1) for c in SEG_COLS}
    stats["preboom_seg_mwp_gated"] = {
        c: round(float(gated[c].sum()), 1) for c in SEG_COLS}
    log.info(
        "Persistence gate (%.0f m): %d/%d pre-boom candidates gated out -> pre-boom "
        "segmentation level %.1f -> %.1f MWp (roof %.1f -> %.1f, ground %.1f -> %.1f)",
        max_dist_m, stats["n_gated_out"], stats["n_population"],
        stats["preboom_seg_mwp_ungated"]["est_mwp_rc"],
        stats["preboom_seg_mwp_gated"]["est_mwp_rc"],
        stats["preboom_seg_mwp_ungated"]["est_mwp_rc_roof"],
        stats["preboom_seg_mwp_gated"]["est_mwp_rc_roof"],
        stats["preboom_seg_mwp_ungated"]["est_mwp_rc_ground"],
        stats["preboom_seg_mwp_gated"]["est_mwp_rc_ground"],
    )
    return pre, stats


def _roofclf_cell_mwp(path: Path, kwp_col: str) -> pd.Series:
    """Per-cell MWp sums from a sub400/ge400 incremental-buildings parquet."""
    df = pd.read_parquet(path, columns=["cell", kwp_col])
    return df.groupby("cell")[kwp_col].sum() / 1000.0


def _domain_cells(cell_density_path: Path) -> set[str]:
    """The density-calibrated domain, derived exactly as the capacity functions do:
    `density.CALIBRATED_BLDG_DENSITY_KM2` over the shared national cell-density table
    (NOT from which cells happen to have flagged buildings -- a domain cell where
    roofclf flags nothing in either epoch is a genuine roofclf zero, not a
    fall-back-to-segmentation cell)."""
    from earthpv.density import CALIBRATED_BLDG_DENSITY_KM2

    cd = pd.read_parquet(cell_density_path)
    lo, hi = CALIBRATED_BLDG_DENSITY_KM2
    dens_col = "density" if "density" in cd.columns else "bldg_density_km2"
    return set(cd.loc[(cd[dens_col] >= lo) & (cd[dens_col] <= hi), "cell"])


def build_growth(
    aoi: str,
    current_pred_dir: Path,
    preboom_pred_dir: Path,
    current_roofclf_density: Path,
    preboom_roofclf_density: Path,
    out_dir: Path,
    cell_density_path: Path = Path("data/roofclf/national_cell_density.parquet"),
    sppi_growth_grid: Path | None = None,
    current_label: str = "current",
    preboom_label: str = "pre-boom (2021-10..2022-01)",
    persistence_gate_m: float = PERSISTENCE_GATE_M,
) -> Path:
    """Combine both epochs' segmentation density grids and roofclf capacity outputs
    into a per-cell growth grid, region aggregates, and a summary JSON. See the module
    docstring for the composition and its assumptions."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cur = gpd.read_parquet(Path(current_pred_dir) / aoi / "density" / "grid.geoparquet")
    pre_path = Path(preboom_pred_dir) / aoi / "density" / "grid.geoparquet"
    if pre_path.exists():
        pre = gpd.read_parquet(pre_path)
    else:  # older density runs on a secondary pred dir only kept the CSV
        pre = pd.read_csv(Path(preboom_pred_dir) / aoi / "density" / "grid.csv")
    pre = pd.DataFrame(pre.drop(columns="geometry", errors="ignore"))

    gate_stats = None
    if persistence_gate_m:
        pre, gate_stats = _gate_preboom_grid(
            aoi, Path(preboom_pred_dir), Path(current_pred_dir), pre, persistence_gate_m)

    pre_cols = [*SEG_COLS, *[c for c in pre.columns if c.endswith("_preboom_ungated")]]
    grid = cur.merge(
        pre[["cell", *pre_cols]], on="cell", how="left", suffixes=("", "_preboom"),
    )
    # A cell with no pre-boom row never got a composite_1 / pre-boom inference: its
    # delta is NOT MEASURABLE there, which is different from zero pre-boom capacity.
    grid["preboom_covered"] = grid["est_mwp_rc_preboom"].notna()
    n_uncovered = int((~grid.preboom_covered).sum())
    if n_uncovered:
        log.warning(
            "%d/%d cells have no pre-boom epoch coverage -- excluded from every delta "
            "(their current-epoch capacity is reported but not differenced)",
            n_uncovered, len(grid),
        )

    # roofclf halves, per cell, both epochs. Missing cell = flagged nothing there = 0.
    sub_cur = _roofclf_cell_mwp(
        Path(current_roofclf_density) / "sub400_central_incremental_buildings.parquet",
        "est_kwp_sub400")
    sub_pre = _roofclf_cell_mwp(
        Path(preboom_roofclf_density) / "sub400_central_incremental_buildings.parquet",
        "est_kwp_sub400")
    ge4_cur = _roofclf_cell_mwp(
        Path(current_roofclf_density) / "ge400_roof_incremental_buildings.parquet",
        "est_kwp_ge400_roof")
    ge4_pre = _roofclf_cell_mwp(
        Path(preboom_roofclf_density) / "ge400_roof_incremental_buildings.parquet",
        "est_kwp_ge400_roof")
    for name, s in [("mwp_sub400_cur", sub_cur), ("mwp_sub400_pre", sub_pre),
                    ("mwp_ge400_roofclf_cur", ge4_cur), ("mwp_ge400_roofclf_pre", ge4_pre)]:
        grid[name] = grid["cell"].map(s).fillna(0.0)

    domain = _domain_cells(Path(cell_density_path))
    grid["in_domain"] = grid["cell"].isin(domain)
    grid["roof_source"] = np.where(grid.in_domain, "roofclf", "segmentation")

    covered = grid.preboom_covered
    fill = lambda c: grid[c].fillna(0.0)  # noqa: E731

    # Component levels per epoch, composed exactly as the evidence atlas does (minus OSM).
    grid["mwp_ground_cur"] = fill("est_mwp_rc_ground")
    grid["mwp_ground_pre"] = fill("est_mwp_rc_ground_preboom")
    grid["mwp_roof_cur"] = np.where(
        grid.in_domain, grid.mwp_ge400_roofclf_cur, fill("est_mwp_rc_roof"))
    grid["mwp_roof_pre"] = np.where(
        grid.in_domain, grid.mwp_ge400_roofclf_pre, fill("est_mwp_rc_roof_preboom"))
    grid["mwp_total_cur"] = grid.mwp_ground_cur + grid.mwp_roof_cur + grid.mwp_sub400_cur
    grid["mwp_total_pre"] = grid.mwp_ground_pre + grid.mwp_roof_pre + grid.mwp_sub400_pre

    for comp in ["ground", "roof", "sub400", "total"]:
        cur_c, pre_c = f"mwp_{comp}_cur", f"mwp_{comp}_pre"
        grid[f"delta_mwp_{comp}"] = np.where(covered, grid[cur_c] - grid[pre_c], np.nan)
    # Raw segmentation-only delta, for continuity with the superseded growth map.
    grid["delta_est_mwp_rc"] = np.where(
        covered, fill("est_mwp_rc") - fill("est_mwp_rc_preboom"), np.nan)

    if sppi_growth_grid and Path(sppi_growth_grid).exists():
        sppi = gpd.read_parquet(sppi_growth_grid).drop(columns="geometry")
        keep = [c for c in ["n_onset_buildings", "onset_roof_area_m2", "onset_mwp"]
                if c in sppi.columns]
        grid = grid.merge(sppi[["cell", *keep]], on="cell", how="left")
        grid[keep] = grid[keep].fillna(0.0)

    grid.to_parquet(out_dir / "growth_grid.geoparquet")
    grid.drop(columns="geometry").to_csv(out_dir / "growth_grid.csv", index=False)

    # Region aggregates: assign each cell by centroid to every region level present.
    regions_path = Path(current_pred_dir) / aoi / "density" / "regions.geoparquet"
    region_frames = []
    if regions_path.exists():
        regions = gpd.read_parquet(regions_path)
        cent = grid[["cell", "geometry"]].copy()
        cent["geometry"] = cent.geometry.representative_point()
        num_cols = [c for c in grid.columns if c.startswith(("mwp_", "delta_"))
                    or c in ("n_onset_buildings", "onset_roof_area_m2", "onset_mwp")]
        for level, rl in regions.groupby(regions.get("level", pd.Series("region", index=regions.index))):
            joined = gpd.sjoin(
                cent.set_geometry("geometry"), rl[["region_id", "name", "geometry"]],
                how="left", predicate="within",
            )[["cell", "region_id", "name"]]
            agg = (grid.drop(columns="geometry").merge(joined, on="cell")
                   .groupby(["region_id", "name"], as_index=False)[num_cols].sum(min_count=1))
            agg["level"] = level
            agg = rl[["region_id", "geometry"]].merge(agg, on="region_id")
            region_frames.append(agg)
    if region_frames:
        greg = pd.concat(region_frames, ignore_index=True)
        greg = gpd.GeoDataFrame(greg, geometry="geometry", crs=regions.crs)
        greg.to_parquet(out_dir / "growth_regions.geoparquet")
        greg.drop(columns="geometry").to_csv(out_dir / "growth_regions.csv", index=False)
        greg.to_file(out_dir / "growth_regions.geojson", driver="GeoJSON")

    def _tot(col: str) -> float:
        return round(float(grid.loc[covered, col].sum()), 1)

    deltas = {c: _tot(f"delta_mwp_{c}") for c in ["ground", "roof", "sub400", "total"]}
    summary = {
        "aoi": aoi,
        "method": "growth.build_growth",
        "epochs": {"current": current_label, "preboom": preboom_label},
        "inputs": {
            "current_pred_dir": str(current_pred_dir),
            "preboom_pred_dir": str(preboom_pred_dir),
            "current_roofclf_density": str(current_roofclf_density),
            "preboom_roofclf_density": str(preboom_roofclf_density),
            "cell_density_path": str(cell_density_path),
        },
        "n_cells": int(len(grid)),
        "n_cells_preboom_covered": int(covered.sum()),
        "n_domain_cells": int(grid.in_domain.sum()),
        "mwp_current": {c: _tot(f"mwp_{c}_cur") for c in ["ground", "roof", "sub400", "total"]},
        "mwp_preboom": {c: _tot(f"mwp_{c}_pre") for c in ["ground", "roof", "sub400", "total"]},
        "delta_mwp": deltas,
        "delta_mwp_negative_cell_mass": round(float(
            grid.loc[covered, "delta_mwp_total"].clip(upper=0).sum()), 1),
        "delta_est_mwp_rc_segmentation_only": _tot("delta_est_mwp_rc"),
        "persistence_gate": gate_stats,
        "caveats": [
            (
                f"The pre-boom segmentation level is persistence-gated at "
                f"{persistence_gate_m:.0f} m (see growth.persistence_gate): pre-boom "
                "candidates with no current-epoch detection anywhere near them are "
                "dropped as false positives (PV is almost never decommissioned). The "
                "gate is one-directional: current-epoch-only false positives cannot be "
                "gated (indistinguishable from genuine new installations) and are "
                "priced by p_real alone, so the residual FP bias on the delta is "
                "upward. A real pre-boom installation the current epoch misses "
                "contributes zero to both epochs (delta 0), not a negative delta; "
                "genuine decommissioning is booked as zero growth. Ungated per-cell "
                "values are kept in the grid as *_preboom_ungated."
                if gate_stats else
                "The pre-boom segmentation level is NOT persistence-gated "
                "(persistence_gate_m=0): the 2026-08-20 sanity check measured only "
                "26.6% of pre-boom candidates surviving into the current epoch "
                "(no_building 5.6%, mostly winter snow above lat 34 deg), so the "
                "ungated pre-boom level is FP-inflated and the delta biased LOW."
            ),
            "Every calibration (candidate precision, coverage ratio, area recall, the "
            "roofclf fit) is measured on current-epoch mapping/imagery and assumed to "
            "transfer to the pre-boom epoch; only the DIFF of the fixed instrument is "
            "meaningful, never the standalone pre-boom level.",
            "Hand-mapped OSM capacity is excluded from both epochs (no install dates); "
            "both epochs' components are deduplicated against the same present-day OSM "
            "pull, so the dedup cancels in the diff.",
            "OSM geometry replacement in postprocess uses present-day footprints in both "
            "epochs: a plant that physically EXPANDED since the pre-boom epoch gets its "
            "full present footprint in both, biasing its delta toward zero "
            "(conservative).",
            "Both epochs' composites were built before the 2026-07-26 imagery fallback "
            "baseline-offset fix; per-cell fallback-scene usage differs between epochs, "
            "an unquantified radiometric confound shared with the published atlas's own "
            "composites.",
            "VIDA building footprints are a single present-day snapshot; a building "
            "constructed after the pre-boom epoch still exists in that epoch's building "
            "table with (correctly) no PV signal on bare ground.",
            "No composed credible interval yet: coverage-ratio/kWp draws are shared "
            "between epochs and mostly cancel in the diff, but the residual is not "
            "priced. Point deltas only.",
            "The roofclf halves are NOT persistence-gated: they passed the 2026-08-20 "
            "persistence check (94% of pre-boom flagged cells still flagged, 3-4% of "
            "capacity on dropped cells). Their separate problem is epoch "
            "INsensitivity, not instability: the pre-boom roofclf level reads ~79% of "
            "the current one, so the sub-400/ge-400 deltas are floors on the true "
            "rooftop growth, limited by how much of roofclf's signal is the panel "
            "rather than adopter-propensity building appearance.",
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    log.info("Growth: current %.1f / pre-boom %.1f -> delta %.1f MWp "
             "(ground %.1f, roof %.1f, sub400 %.1f) over %d/%d covered cells -> %s",
             summary["mwp_current"]["total"], summary["mwp_preboom"]["total"],
             deltas["total"], deltas["ground"], deltas["roof"], deltas["sub400"],
             summary["n_cells_preboom_covered"], summary["n_cells"], out_dir)
    return out_dir
