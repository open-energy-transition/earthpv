"""Assemble a country's atlas DATA PACK and its downloads manifest, ready for a release.

`data/` is gitignored and the per-cell and per-building tables are far past what git
handles comfortably, so an atlas publishes its raw numbers as **GitHub Release assets**
and the repository carries only a manifest pointing at them. `earthpv atlas` reads that
manifest (`--downloads-manifest`) plus the release's asset base URL (`--data-release-url`)
and writes a Downloads section into the atlas page. This script builds both halves: it
collects whichever artifacts the pipeline actually produced, names them by the shared
convention, measures them, and writes `configs/<aoi>_atlas_downloads.json`.

It is deliberately tolerant. A country with no calibration quadrats has no roofclf half
and no sub-400 tables; a country with no glint survey has no pose CSV. Missing inputs are
reported and skipped rather than failing the run, so a segmentation-only atlas packs
cleanly.

    pixi run python scripts/build_atlas_data_pack.py --aoi zambia
    gh release create zambia-atlas-data-$(date +%Y-%m-%d) dist/zambia-atlas-data/* \
        --title "Zambia atlas data" --notes "Point-in-time snapshot"

Then rebuild the atlas with --downloads-manifest configs/zambia_atlas_downloads.json and
--data-release-url https://github.com/<owner>/<repo>/releases/download/<tag>.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger("data_pack")


def _rows(path: Path) -> int | None:
    try:
        import pyarrow.parquet as pq

        return pq.ParquetFile(path).metadata.num_rows
    except Exception:  # noqa: BLE001 - a row count is a nicety, not a reason to fail
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--pred-dir", type=Path, default=None,
                    help="default data/predictions")
    ap.add_argument("--roofclf-dir", type=Path, default=None,
                    help="default data/roofclf_national_with_sppi/<aoi>/density")
    ap.add_argument("--calib-dir", type=Path, default=Path("data/roofclf"))
    ap.add_argument("--out", type=Path, default=None,
                    help="default dist/<aoi>-atlas-data")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="default configs/<aoi>_atlas_downloads.json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    aoi = args.aoi
    dens = (args.pred_dir or Path("data/predictions")) / aoi / "density"
    rc = args.roofclf_dir or Path("data/roofclf_national_with_sppi") / aoi / "density"
    out = args.out or Path("dist") / f"{aoi}-atlas-data"
    manifest_path = args.manifest or Path("configs") / f"{aoi}_atlas_downloads.json"
    out.mkdir(parents=True, exist_ok=True)

    # (source, published name, label, note). Order is the order of the Downloads section.
    items = [
        (dens / "grid.geoparquet", f"{aoi}_capacity_by_cell.parquet",
         "Capacity per grid cell",
         "PyPSA-ready cell aggregate: n_buildings, roof_area_m2, est_mwp_rc and friends."),
        (dens / "buildings.geoparquet", f"{aoi}_capacity_by_building.parquet",
         "Capacity per building",
         "One row per building carrying a segmentation detection. Sums BELOW the cell "
         "table: each building is credited only with its own geometric intersection."),
        (dens / "regions.geoparquet", f"{aoi}_capacity_by_region.parquet",
         "Capacity per admin region",
         "Region-level aggregate, if `density --districts` was run."),
        (rc / "ge400_roof_incremental_buildings.parquet",
         f"{aoi}_roofclf_ge400_roof_buildings.parquet",
         "roofclf >= 400 m2 rooftop replacement",
         "In-domain replacement for segmentation's own rooftop estimate."),
        (rc / "sub400_central_incremental_buildings.parquet",
         f"{aoi}_roofclf_sub400_central_buildings.parquet",
         "roofclf sub-400 m2, central estimate",
         "In-domain, feeds Best estimate."),
        (rc / "sub400_low_incremental_buildings.parquet",
         f"{aoi}_roofclf_sub400_low_buildings.parquet",
         "roofclf+SPPI sub-400 m2, stricter floor",
         "In-domain, the internal floor population."),
        (rc / "sub400_outdomain_and_gate_incremental_buildings.parquet",
         f"{aoi}_roofclf_sub400_outdomain_andgate_buildings.parquet",
         "roofclf+SPPI sub-400 m2, out-of-domain",
         "Explicitly-flagged extrapolation beyond the calibrated domain."),
        (Path("data/predictions") / aoi / "candidates.parquet",
         f"{aoi}_raw_detections_unreviewed.parquet",
         "Raw model detections (unreviewed)",
         "Every thresholded candidate polygon, before human validation. Leads, not truth."),
        (args.calib_dir / "model_full.json", f"{aoi}_roofclf_model.json",
         "Fitted roofclf model",
         "Coefficients, feature list and the zonal convention they were fitted under."),
        (args.calib_dir / "summary.json", f"{aoi}_roofclf_summary.json",
         "roofclf calibration summary",
         "Leave-one-quadrat-out skill, the deployment threshold and its precision/recall."),
    ]

    entries, missing = [], []
    for src, name, label, note in items:
        if not src.exists():
            missing.append(str(src))
            continue
        dst = out / name
        shutil.copy2(src, dst)
        n = _rows(dst) if dst.suffix == ".parquet" else None
        entries.append({
            "file": name, "label": label,
            "note": note + (f" {n:,} rows." if n else ""),
            "size_bytes": dst.stat().st_size,
        })
        log.info("packed %-56s %8.1f MB%s", name, dst.stat().st_size / 1e6,
                 f"  {n:,} rows" if n else "")

    if not entries:
        raise SystemExit(
            f"Nothing to pack for {aoi}. Expected density output under {dens} -- run the "
            "pipeline first (docs/reproduce.md, 'The full pipeline')."
        )
    for m in missing:
        log.warning("absent, skipped: %s", m)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(entries, indent=2) + "\n")
    total = sum(e["size_bytes"] for e in entries)
    log.info("%d files, %.1f MB -> %s", len(entries), total / 1e6, out)
    log.info("manifest -> %s", manifest_path)
    print(f"""
Next:
  gh release create {aoi}-atlas-data-$(date +%Y-%m-%d) {out}/* \\
      --title "{aoi.title()} atlas data" --notes "Point-in-time snapshot"

  earthpv atlas --aoi {aoi} ... \\
      --downloads-manifest {manifest_path} \\
      --data-release-url https://github.com/<owner>/<repo>/releases/download/<tag>

Commit the MANIFEST, not the pack: dist/ is gitignored and the assets live on the release.
""")


if __name__ == "__main__":
    main()
