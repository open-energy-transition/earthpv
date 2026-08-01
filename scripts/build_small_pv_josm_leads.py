"""Small-PV (< 400 m2) validation leads for manual checking in JOSM.

Answers a narrower question than the density pipeline's own numbers: not "how much
capacity," but "does the model actually point at real, previously-unmapped
installations when a human looks at the imagery?" A regular, repeatable task (see
`pixi run small-pv-leads` in `pixi.toml`) -- re-run it whenever the underlying
roofclf/SPPI scoring or the national OSM solar pull is refreshed, not a one-off.

Writes THREE lead files, one per population, so all three can be checked against each
other in JOSM (does requiring SPPI agreement actually cut false positives, or just
recall? does SPPI alone do any better or worse than roofclf alone?):

- **AND-gate** (`sub400_low_incremental_buildings.parquet`, roofclf AND SPPI both
  agree): `sub400_capacity.domain_restricted_and_gate_capacity`'s population, measured
  precision 0.55 -> 0.62 on held-out calibration quadrats vs. roofclf alone, at the
  cost of recall. This is the evidence atlas's Verified tier's small-PV component.
- **roofclf-only** (`sub400_central_incremental_buildings.parquet`, roofclf alone, no
  SPPI gate): `sub400_capacity.domain_restricted_capacity`'s population, the evidence
  atlas's Best-estimate tier's small-PV component. Higher recall, lower precision.
- **SPPI-only** (derived fresh here, not a pre-built artifact): SPPI alone, gated at a
  pooled precision-targeted threshold (`sppi.pooled_precision_threshold`, the same call
  `domain_restricted_and_gate_capacity` makes to set its AND-gate's SPPI side), over the
  same 93-cell domain and the same incremental/contamination filters, but with NO
  roofclf condition. SPPI alone was never adopted as its own deployable capacity
  instrument in this project (see CLAUDE.md's SPPI cross-validation notes) -- this is
  the first time it is scored as a standalone population rather than a feature or an
  AND-gate partner, specifically to let a human compare all three detectors' real-world
  false-positive rates side by side. Its `est_kwp` is therefore explicitly
  **uncalibrated** (raw roof area x the module constant, no measured precision weight
  applied), unlike the other two files' calibrated `est_kwp_sub400*` figures.

All three files rank leads by the model's own `p_roofclf`/`sppi` scores (whichever the
population wasn't gated on is still shown, for reference), recovered for the two
pre-built populations by joining each building back to its source per-cell probability
parquet (`data/roofclf_national_with_sppi/pakistan/prob/<cell>.parquet`) on exact
geometry -- verified these match by WKB equality, since both are straight threshold
filters of that same per-building table, not re-derived geometry. The SPPI-only
population is built directly from those same per-cell parquets, so it already carries
both scores with no join needed.

Two filters on top of what `sub400_capacity.py`'s domain restriction/incremental/
contamination filters already applied, identical for all three populations:
- **Not already mapped**: dropped if within 30 m of an existing OSM solar feature
  (`export.filter_new_leads`, the same distance convention used throughout this
  project's "is this a new lead" checks) -- otherwise these files would mostly confirm
  installations already in OSM, not test whether the model finds anything NEW.
- **Top-N by confidence, capped per cell**: sorted by `p_roofclf` (roofclf-based
  populations) or `sppi` (the SPPI-only population) descending, capped at `--per-cell`
  (default 6) before the overall `--limit` (default 300) -- a plain top-N by confidence
  alone clusters into whichever cells the detector is most confident about overall; the
  per-cell cap trades a little peak confidence for a sample that actually spans the
  checked area instead of one or two cells.

Usage:
    pixi run small-pv-leads
    pixi run python scripts/build_small_pv_josm_leads.py --limit 500
    pixi run python scripts/build_small_pv_josm_leads.py --population and_gate
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from earthpv.export import filter_new_leads, new_lead_mask

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ROOFCLF_DENSITY_DIR = (
    ROOT / "data" / "roofclf_national_with_sppi" / "pakistan" / "density"
)
PROB_DIR = ROOT / "data" / "roofclf_national_with_sppi" / "pakistan" / "prob"
OSM_SOLAR = ROOT / "data" / "labels" / "pakistan_overpass_solar.parquet"
CANDIDATES_PATH = ROOT / "data" / "predictions" / "pakistan" / "candidates.parquet"
RESULTS_DIR = ROOT / "results"

# Current calibration snapshot -- the same one `sub400_capacity.py`'s functions read
# for the pre-built AND-gate/roofclf-only populations (`data/roofclf/`, not the dated
# `data/roofclf_with_*_20260730/` backups).
FOLDS_PATH = ROOT / "data" / "roofclf" / "folds.csv"
CELL_DENSITY_PATH = ROOT / "data" / "roofclf" / "national_cell_density.parquet"
CALIBRATION_BUILDINGS_PATH = ROOT / "data" / "roofclf" / "buildings.geoparquet"

MIN_DISTANCE_M = 30.0
CONTAMINATION_MAX_M2 = 400.0
SPPI_MIN_PRECISION = 0.5
KWP_PER_M2_MODULE = 0.18


def _imagery_note(lon: float, lat: float) -> str:
    return (
        f"osm={lon:.5f},{lat:.5f} | "
        f"bing=https://www.bing.com/maps?cp={lat:.5f}~{lon:.5f}&lvl=19&style=a | "
        f"google=https://www.google.com/maps/@{lat:.5f},{lon:.5f},200m/data=!3m1!1e3"
    )


def _attach_scores(buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Recover p_roofclf/sppi for each building by joining back to its source per-cell
    probability parquet on exact geometry (WKB) -- both pre-built populations are
    threshold filters of that same table, not re-derived geometry, so this is an
    exact-match lookup, not a spatial join with any tolerance to get wrong."""
    parts = []
    for cell, group in buildings.groupby("cell"):
        prob_path = PROB_DIR / f"{cell}.parquet"
        if not prob_path.exists():
            log.warning("No probability parquet for cell %s; dropping %d buildings", cell, len(group))
            continue
        prob = gpd.read_parquet(prob_path, columns=["geometry", "p_roofclf", "sppi"])
        scores = dict(zip(prob["geometry"].apply(lambda g: g.wkb), zip(prob["p_roofclf"], prob["sppi"])))
        matched = group.geometry.apply(lambda g: g.wkb).map(scores)
        n_unmatched = matched.isna().sum()
        if n_unmatched:
            log.warning("%d/%d buildings in cell %s had no exact geometry match; dropped", n_unmatched, len(group), cell)
        g = group.loc[matched.notna()].copy()
        g["p_roofclf"] = matched.loc[matched.notna()].apply(lambda t: t[0])
        g["sppi"] = matched.loc[matched.notna()].apply(lambda t: t[1])
        parts.append(g)
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=buildings.crs)


def _load_prebuilt(path: Path) -> gpd.GeoDataFrame:
    buildings = gpd.read_parquet(path)
    return _attach_scores(buildings)


def _derive_sppi_only() -> gpd.GeoDataFrame:
    """SPPI alone, gated at a pooled precision-targeted threshold, over the same
    93-cell domain-restricted, incremental, contamination-filtered population the
    AND-gate/roofclf-only files use -- see module docstring. Not a pre-built artifact
    anywhere in this project; derived fresh each run from the current calibration
    snapshot (cheap: one threshold fit + a scan of the ~93 domain cells' probability
    parquets, not a retrain).
    """
    from earthpv.sppi import add_sppi, pooled_precision_threshold
    from earthpv.sub400_capacity import national_cell_domain, select_calibrated_quadrats

    domain_cells = national_cell_domain(CELL_DENSITY_PATH)
    quadrats, _ = select_calibrated_quadrats(FOLDS_PATH)

    bt = gpd.read_parquet(CALIBRATION_BUILDINGS_PATH)
    if "sppi" not in bt.columns:
        bt = add_sppi(bt)
    sppi_thresh = pooled_precision_threshold(bt, quadrats, min_precision=SPPI_MIN_PRECISION)
    log.info(
        "SPPI-only pooled threshold (min_precision=%.2f, quadrats=%s): %.4f",
        SPPI_MIN_PRECISION, quadrats, sppi_thresh,
    )

    parts = []
    for cell in sorted(domain_cells):
        p = PROB_DIR / f"{cell}.parquet"
        if not p.exists():
            continue
        d = gpd.read_parquet(p)
        if d.empty or "sppi" not in d.columns:
            continue
        f = d[d.sppi >= sppi_thresh]
        if not f.empty:
            parts.append(f)
    flagged = (
        gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326") if parts
        else gpd.GeoDataFrame(columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"], crs="EPSG:4326")
    )
    log.info(
        "SPPI-only: %d domain cells scanned, %d flagged buildings before incremental/contamination filters",
        len(domain_cells), len(flagged),
    )

    cands = gpd.read_parquet(CANDIDATES_PATH)
    is_new = new_lead_mask(flagged, cands, min_distance_m=MIN_DISTANCE_M)
    incremental = flagged[is_new].reset_index(drop=True)
    incremental = incremental[incremental.roof_area_m2 < CONTAMINATION_MAX_M2].reset_index(drop=True)
    incremental = incremental.copy()
    incremental["est_kwp_uncalibrated"] = incremental.roof_area_m2 * KWP_PER_M2_MODULE
    return incremental


POPULATIONS = {
    "and_gate": {
        "loader": lambda: _load_prebuilt(ROOFCLF_DENSITY_DIR / "sub400_low_incremental_buildings.parquet"),
        "value_col": "est_kwp_sub400_and_gate",
        "out": RESULTS_DIR / "pakistan_small_pv_josm_leads.geojson",
        "id_prefix": "pakistan-small-pv-andgate",
        "rank_cols": ["p_roofclf", "sppi"],
        "fixme": lambda r: (
            f"Possible small rooftop PV ({r.roof_area_m2:.0f} m2 roof, roofclf "
            f"p={r.p_roofclf:.2f} AND SPPI={r.sppi:.2f} agree, not near any existing "
            "OSM solar feature) -- check imagery; if real, map as "
            "generator:source=solar or power=generator + generator:source=solar"
        ),
    },
    "roofclf_only": {
        "loader": lambda: _load_prebuilt(ROOFCLF_DENSITY_DIR / "sub400_central_incremental_buildings.parquet"),
        "value_col": "est_kwp_sub400",
        "out": RESULTS_DIR / "pakistan_small_pv_josm_leads_roofclf_only.geojson",
        "id_prefix": "pakistan-small-pv-roofclf",
        "rank_cols": ["p_roofclf", "sppi"],
        "fixme": lambda r: (
            f"Possible small rooftop PV ({r.roof_area_m2:.0f} m2 roof, roofclf "
            f"p={r.p_roofclf:.2f} alone -- SPPI={r.sppi:.2f} shown for reference only, "
            "not used to filter this population -- not near any existing OSM solar "
            "feature) -- check imagery; if real, map as generator:source=solar or "
            "power=generator + generator:source=solar"
        ),
    },
    "sppi_only": {
        "loader": _derive_sppi_only,
        "value_col": "est_kwp_uncalibrated",
        "out": RESULTS_DIR / "pakistan_small_pv_josm_leads_sppi_only.geojson",
        "id_prefix": "pakistan-small-pv-sppi",
        "rank_cols": ["sppi", "p_roofclf"],
        "fixme": lambda r: (
            f"Possible small rooftop PV ({r.roof_area_m2:.0f} m2 roof, SPPI={r.sppi:.3f} "
            f"alone -- roofclf p={r.p_roofclf:.2f} shown for reference only, not used to "
            "filter this population -- not near any existing OSM solar feature; kWp "
            "estimate is UNCALIBRATED, no measured precision weight exists for SPPI "
            "alone) -- check imagery; if real, map as generator:source=solar or "
            "power=generator + generator:source=solar"
        ),
    },
}


def build_one(population: str, limit: int, per_cell: int) -> Path:
    cfg = POPULATIONS[population]
    log.info("--- population: %s ---", population)

    candidates = cfg["loader"]()
    log.info("Loaded %d domain-restricted, incremental buildings (%s)", len(candidates), population)
    if "p_roofclf" not in candidates.columns or "sppi" not in candidates.columns:
        candidates = _attach_scores(candidates)
        log.info("Recovered p_roofclf/sppi for %d buildings", len(candidates))

    mapped = gpd.read_parquet(OSM_SOLAR)
    new_leads = filter_new_leads(candidates, mapped, min_distance_m=MIN_DISTANCE_M)
    log.info(
        "%d/%d (%.1f%%) are not within %.0f m of an existing OSM solar feature -- these "
        "are the genuinely untested leads",
        len(new_leads), len(candidates), 100 * len(new_leads) / max(len(candidates), 1),
        MIN_DISTANCE_M,
    )

    rank_cols = cfg["rank_cols"]
    new_leads = new_leads.sort_values(rank_cols, ascending=[False] * len(rank_cols)).reset_index(drop=True)
    spread = new_leads.groupby("cell", group_keys=False).head(per_cell)
    spread = spread.sort_values(rank_cols, ascending=[False] * len(rank_cols)).reset_index(drop=True)
    log.info(
        "%d leads remain after capping at %d per cell (%d distinct cells); taking top %d",
        len(spread), per_cell, spread["cell"].nunique(), limit,
    )
    top = spread.head(limit).copy()

    centroids = top.geometry.representative_point()
    top["lead_id"] = [f"{cfg['id_prefix']}-{i:04d}" for i in range(len(top))]
    top["est_kwp"] = top[cfg["value_col"]].round(2)
    top["p_roofclf"] = top["p_roofclf"].round(4)
    top["sppi"] = top["sppi"].round(4)
    top["fixme"] = [cfg["fixme"](row) for row in top.itertuples()]
    top["imagery_note"] = [_imagery_note(p.x, p.y) for p in centroids]

    out_cols = [
        "lead_id", "cell", "roof_area_m2", "est_kwp", "p_roofclf", "sppi",
        "fixme", "imagery_note", "geometry",
    ]
    top = top[out_cols]

    out = cfg["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    top.to_file(out, driver="GeoJSON")
    log.info(
        "Wrote %d small-PV JOSM leads (%s; of %d filtered, %d before OSM filter) -> %s",
        len(top), population, len(new_leads), len(candidates), out,
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=300, help="Max leads to write per file (default 300)")
    ap.add_argument("--per-cell", type=int, default=6, help="Max leads per 0.1° cell (default 6)")
    ap.add_argument(
        "--population", choices=list(POPULATIONS) + ["all"], default="all",
        help="Which population to build (default: all three)",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    populations = list(POPULATIONS) if args.population == "all" else [args.population]
    for population in populations:
        build_one(population, args.limit, args.per_cell)


if __name__ == "__main__":
    main()
