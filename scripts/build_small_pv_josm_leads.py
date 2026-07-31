"""Small-PV (< 400 m2) validation leads for manual checking in JOSM.

Answers a narrower question than the density pipeline's own numbers: not "how much
capacity," but "does the model actually point at real, previously-unmapped
installations when a human looks at the imagery?"

2026-08-01 revision: switched from the "Central" population (roofclf alone) to "Low"
(roofclf AND SPPI both agree) after a first 300-lead batch came back "promising but
still lots of false positives." Low is the AND-gate `sub400_capacity.
domain_restricted_and_gate_capacity` already computes for the evidence atlas's Verified
tier -- measured precision 0.55 -> 0.62 on held-out calibration quadrats vs. roofclf
alone, no retraining needed, at the cost of recall (fewer leads per cell). Also switched
ranking from `roof_area_m2` (a weak proxy) to the model's own `p_roofclf` score, recovered
by joining each Low building back to its source per-cell probability parquet
(`data/roofclf_national_with_sppi/pakistan/prob/<cell>.parquet`) on exact geometry --
verified these match by WKB equality, since Low is a straight threshold filter of that
same per-building table, not a re-derived geometry.

Two filters on top of what `domain_restricted_and_gate_capacity` already applied:
- **Not already mapped**: dropped if within 30 m of an existing OSM solar feature
  (`export.filter_new_leads`, the same distance convention used throughout this project's
  "is this a new lead" checks) -- otherwise this file would mostly confirm installations
  already in OSM, not test whether the model finds anything NEW.
- **Top-N by confidence, capped per cell**: sorted by `p_roofclf` descending (ties broken
  by `sppi`), capped at `--per-cell` (default 6) before the overall `--limit` (default
  300) -- a plain top-N by confidence alone clusters into whichever cells roofclf is most
  confident about overall; the per-cell cap trades a little peak confidence for a sample
  that actually spans the checked area instead of one or two cells.

Usage:
    pixi run python scripts/build_small_pv_josm_leads.py
    pixi run python scripts/build_small_pv_josm_leads.py --limit 500
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from earthpv.export import filter_new_leads

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
LOW_BUILDINGS = (
    ROOT / "data" / "roofclf_national_with_sppi" / "pakistan" / "density"
    / "sub400_low_incremental_buildings.parquet"
)
PROB_DIR = ROOT / "data" / "roofclf_national_with_sppi" / "pakistan" / "prob"
OSM_SOLAR = ROOT / "data" / "labels" / "pakistan_overpass_solar.parquet"
OUT = ROOT / "results" / "pakistan_small_pv_josm_leads.geojson"

MIN_DISTANCE_M = 30.0


def _imagery_note(lon: float, lat: float) -> str:
    return (
        f"osm={lon:.5f},{lat:.5f} | "
        f"bing=https://www.bing.com/maps?cp={lat:.5f}~{lon:.5f}&lvl=19&style=a | "
        f"google=https://www.google.com/maps/@{lat:.5f},{lon:.5f},200m/data=!3m1!1e3"
    )


def _attach_scores(low: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Recover p_roofclf/sppi for each Low building by joining back to its source
    per-cell probability parquet on exact geometry (WKB) -- Low is a threshold filter
    of that same table, not a re-derived one, so this is an exact-match lookup, not a
    spatial join with any tolerance to get wrong."""
    parts = []
    for cell, group in low.groupby("cell"):
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
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=low.crs)


def build(limit: int, per_cell: int) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    candidates = gpd.read_parquet(LOW_BUILDINGS)
    log.info("Loaded %d domain-restricted, incremental, AND-gate (roofclf & SPPI) buildings", len(candidates))

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

    new_leads = new_leads.sort_values(
        ["p_roofclf", "sppi"], ascending=[False, False]
    ).reset_index(drop=True)
    spread = new_leads.groupby("cell", group_keys=False).head(per_cell)
    spread = spread.sort_values(
        ["p_roofclf", "sppi"], ascending=[False, False]
    ).reset_index(drop=True)
    log.info(
        "%d leads remain after capping at %d per cell (%d distinct cells); taking top %d",
        len(spread), per_cell, spread["cell"].nunique(), limit,
    )
    top = spread.head(limit).copy()

    centroids = top.geometry.representative_point()
    top["lead_id"] = [f"pakistan-small-pv-{i:04d}" for i in range(len(top))]
    top["est_kwp"] = (top["est_kwp_sub400_and_gate"]).round(2)
    top["p_roofclf"] = top["p_roofclf"].round(4)
    top["sppi"] = top["sppi"].round(4)
    top["fixme"] = [
        f"Possible small rooftop PV ({row.roof_area_m2:.0f} m2 roof, roofclf p={row.p_roofclf:.2f} "
        f"AND SPPI={row.sppi:.2f} agree, not near any existing OSM solar feature) -- check "
        "imagery; if real, map as generator:source=solar or power=generator + "
        "generator:source=solar"
        for row in top.itertuples()
    ]
    top["imagery_note"] = [
        _imagery_note(p.x, p.y) for p in centroids
    ]

    out_cols = [
        "lead_id", "cell", "roof_area_m2", "est_kwp", "p_roofclf", "sppi",
        "fixme", "imagery_note", "geometry",
    ]
    top = top[out_cols]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    top.to_file(OUT, driver="GeoJSON")
    log.info(
        "Wrote %d small-PV JOSM leads (of %d filtered, %d before OSM filter) -> %s",
        len(top), len(new_leads), len(candidates), OUT,
    )
    return OUT


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=300, help="Max leads to write (default 300)")
    ap.add_argument("--per-cell", type=int, default=6, help="Max leads per 0.1° cell (default 6)")
    args = ap.parse_args()
    build(args.limit, args.per_cell)


if __name__ == "__main__":
    main()
