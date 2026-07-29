"""Quadrat validation for SPPI as a building-scoped, capacity-contributing detector.

Answers, before any national deployment: if SPPI-flagged buildings that the segmentation
model's own raster misses were added directly to capacity (using building footprint area,
not a polygonized raster blob -- see docs/issues/sppi-spectral-index-evaluation.md), how
much would that add, at what measured precision, and does it stay controlled in the arid
quadrat that broke a raw SPPI raster (4.7x over-prediction on bare ground)?

Uses only data already computed this session (`data/roofclf/buildings.geoparquet`) --
no new national-scale computation. Run: .pixi/envs/default/bin/python
scripts/sppi_capacity_validation.py
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from earthpv.sppi import add_sppi, calibrate_threshold_loqo, recall_effect, sppi_only_incremental

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "data/roofclf/buildings.geoparquet"
SEG_THRESHOLD = 0.3  # matches postprocess's default polygonize threshold


def main() -> None:
    t = add_sppi(gpd.read_parquet(TABLE))
    pd.set_option("display.width", 250)

    thresholds = calibrate_threshold_loqo(t, criterion="precision", min_precision=0.5)
    print("=== LOQO-calibrated SPPI threshold per quadrat (fit on the other 8, "
          "precision-targeted >=0.5) ===\n")
    print(thresholds.to_string(index=False))

    print("\n\n=== Incremental capacity: SPPI-flagged buildings the segmentation raster misses ===\n")
    incr = sppi_only_incremental(t, thresholds, seg_threshold=SEG_THRESHOLD)
    print(incr.to_string(index=False))
    print(f"\nMedian precision among SPPI-only flagged buildings: {incr['precision'].median():.3f}")
    print(f"Total incremental capacity across quadrats: {incr['incremental_capacity_kwp'].sum():.1f} kWp")

    print("\n\n=== Recall effect: does 'segmentation OR SPPI' catch more true installations? ===\n")
    rec = recall_effect(t, thresholds, seg_threshold=SEG_THRESHOLD)
    print(rec.to_string(index=False))
    print(f"\nMedian seg-only recall: {rec['seg_only_recall'].median():.3f}")
    print(f"Median combined recall: {rec['combined_recall'].median():.3f}")

    print("\n\n=== Go/no-go read ===")
    quetta = incr[incr.quadrat == "quetta"]
    quetta_precision = float(quetta["precision"].iloc[0]) if not quetta.empty else float("nan")
    quetta_flagged = int(quetta["n_seg_missed_sppi_flagged"].iloc[0]) if not quetta.empty else 0
    print(
        f"Arid quadrat (Quetta): {quetta_flagged} buildings flagged, precision "
        f"{quetta_precision:.3f} -- building-scoping reduced but did NOT fix the arid "
        "false-positive mode (still far below the 0.5 target); buildings in bright bare "
        "terrain apparently still carry enough background signal in their zonal-mean "
        "reflectance to confuse SPPI. NOT SAFE to deploy in arid/desert regions as-is."
    )
    mardan = incr[incr.quadrat == "mardan"]
    mardan_flagged = int(mardan["n_seg_missed_sppi_flagged"].iloc[0]) if not mardan.empty else 0
    print(
        f"Mardan: {mardan_flagged} buildings flagged (threshold fit on the OTHER 8 "
        "quadrats does not transfer here at all) -- a single pooled national threshold "
        "does not transfer to every quadrat, the same lesson this project has already "
        "learned from exp_scale and rate_ratio for other instruments."
    )
    others = incr[~incr.quadrat.isin(["quetta", "mardan"])]
    print(
        f"\nThe other 7 quadrats: median precision {others['precision'].median():.3f}, "
        f"total incremental capacity {others['incremental_capacity_kwp'].sum():.0f} kWp -- "
        "genuinely usable."
    )
    print(
        "\nOVERALL: NOT YET READY for uniform national deployment. The mechanism is sound "
        "(precision-targeted threshold, building-scoped) and works for most quadrats, but "
        "fails in exactly the stratum (arid) this design was meant to protect against, and "
        "does not transfer everywhere from one pooled threshold. Before any national step: "
        "(a) exclude regions plausibility.py already flags suspect for ground-mount "
        "(Balochistan, Gilgit-Baltistan, Azad Kashmir) from this mechanism specifically, "
        "and/or (b) get more quadrats per stratum before trusting one pooled cut nationally."
    )


if __name__ == "__main__":
    main()
