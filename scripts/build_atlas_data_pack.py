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

A roofclf table priced by probability (the default since 2026-10-25,
`sub400_capacity.WEIGHTINGS`) is one row per cell and size bin, not one per building, so it
is published as `..._by_cell_and_size.parquet` rather than `..._buildings.parquet`. The
quadrat boundaries zip, pose survey, checkpoint and data dictionary join the pack when
their inputs exist (`--pose-csv`, `--checkpoint`, `--dictionary`).

    pixi run python scripts/build_atlas_data_pack.py --aoi zambia
    gh release create zambia-atlas-data-$(date +%Y-%m-%d) dist/zambia-atlas-data/* \
        --title "Zambia atlas data" --notes "Point-in-time snapshot"

Then rebuild the atlas with --downloads-manifest configs/zambia_atlas_downloads.json and
--data-release-url https://github.com/<owner>/<repo>/releases/download/<tag>.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import shutil
import zipfile
from pathlib import Path

log = logging.getLogger("data_pack")


def _rows(path: Path) -> int | None:
    try:
        if path.suffix == ".csv":
            with open(path, newline="") as f:
                return sum(1 for _ in csv.reader(f)) - 1
        import pyarrow.parquet as pq

        return pq.ParquetFile(path).metadata.num_rows
    except Exception:  # noqa: BLE001 - a row count is a nicety, not a reason to fail
        return None


def _probability_weighted(path: Path) -> bool:
    """A roofclf component priced by probability carries `sum_p` (the expected number of PV
    roofs) on one row per (cell, size bin) instead of one row per flagged building."""
    try:
        import pyarrow.parquet as pq

        return "sum_p" in pq.read_schema(path).names
    except Exception:  # noqa: BLE001 - unreadable here means the copy step reports it
        return False


def _quadrat_zip(calib_dir: Path, labels_dir: Path, roofclf_dir: Path, dst: Path) -> int:
    """Zip the boundary of every quadrat in the roofclf fit (`folds.csv`), plus a
    `quadrats.csv` index: each quadrat's held-out skill and whether the coverage ratio and
    area recall were fitted on it (the precision-trusted subset the capacity summaries
    name). Returns the number of boundaries written; 0 writes nothing."""
    folds_path = calib_dir / "folds.csv"
    if not folds_path.exists():
        return 0
    with open(folds_path, newline="") as f:
        folds = list(csv.DictReader(f))
    # `roofclf.quadrat_name`'s rule, kept here so this script needs no earthpv import
    stems = {re.sub(r"_calib_.*$", "", b.name.removesuffix("_boundary.geojson")): b
             for b in sorted(labels_dir.glob("*_calib_*_boundary.geojson"))}
    trusted: set[str] = set()
    summary = roofclf_dir / "sub400_central_summary.json"
    if summary.exists():
        trusted = set(json.loads(summary.read_text()).get("calibration_quadrats") or [])
    rows, n = [], 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for r in folds:
            b = stems.get(r["quadrat"])
            if b is None:
                log.warning("quadrat %s: no boundary under %s", r["quadrat"], labels_dir)
            else:
                z.write(b, b.name)
                n += 1
            rows.append({
                "quadrat": r["quadrat"], "boundary_file": b.name if b else "",
                "n_buildings": r.get("n", ""), "n_pv_buildings": r.get("n_pv", ""),
                "base_rate": r.get("base_rate", ""), "held_out_auc": r.get("auc", ""),
                "rate_ratio": r.get("rate_ratio", ""),
                "coverage_ratio_quadrat": r["quadrat"] in trusted if trusted else "",
            })
        if n:
            lines = [",".join(rows[0])] + [",".join(str(v) for v in r.values()) for r in rows]
            z.writestr("quadrats.csv", "\n".join(lines) + "\n")
    if not n:
        dst.unlink()
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--pred-dir", type=Path, default=None,
                    help="default data/predictions")
    ap.add_argument("--roofclf-dir", type=Path, default=None,
                    help="default data/roofclf_national_with_sppi/<aoi>/density")
    ap.add_argument("--calib-dir", type=Path, default=Path("data/roofclf"))
    ap.add_argument("--labels-dir", type=Path, default=None,
                    help="where the quadrat boundaries are; default data/labels/<aoi> when it "
                    "exists, else data/labels (Pakistan's are flat)")
    ap.add_argument("--atlas-cells", type=Path, default=None,
                    help="the atlas's own per-cell table; default "
                    "docs/assets/interactive/<aoi>_evidence_atlas_capacity_by_cell.parquet")
    ap.add_argument("--pose-csv", type=Path, default=None,
                    help="glint pose survey, e.g. data/glint/country2000_summary.csv")
    ap.add_argument("--checkpoint", type=Path, default=None,
                    help="the segmentation checkpoint behind the page's detections")
    ap.add_argument("--dictionary", type=Path, default=None,
                    help="data dictionary; default configs/<aoi>_atlas_data_dictionary.md")
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
    labels_dir = args.labels_dir or (
        Path("data/labels") / aoi if (Path("data/labels") / aoi).is_dir() else Path("data/labels"))
    atlas_cells = args.atlas_cells or (
        Path("docs/assets/interactive") / f"{aoi}_evidence_atlas_capacity_by_cell.parquet")
    dictionary = args.dictionary or Path("configs") / f"{aoi}_atlas_data_dictionary.md"
    out.mkdir(parents=True, exist_ok=True)

    # (source, published name, label, note). Order is the order of the Downloads section.
    items = [
        (atlas_cells, f"{aoi}_atlas_capacity_by_cell.parquet",
         "Best estimate and Verified per grid cell",
         "The atlas's own map: every Best and Verified component per 0.1 degree cell, "
         "summing to the page's headline figures. The PyPSA-ready table."),
        (dens / "grid.geoparquet", f"{aoi}_capacity_by_cell.parquet",
         "Segmentation estimate per grid cell",
         "The >= 400 m2 segmentation half alone (est_mwp_rc and its estimators), with "
         "building counts and roof area per cell."),
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
         "Explicitly-flagged extrapolation beyond the calibrated domain, in the atlas's "
         "figures only when it was built with --sub400-outdomain-cells."),
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
        (args.pose_csv, f"{aoi}_glint_pose_survey.csv",
         "Panel pose survey (glint)",
         "Sentinel-2 specular-glint detections and fitted panel tilt/azimuth per surveyed "
         "installation."),
        (args.checkpoint, "terramind_pv_segmentation_checkpoint.ckpt",
         "TerraMind segmentation checkpoint",
         "The fine-tune that produced this release's detections and segmentation capacity."),
        (dictionary, "DATA_DICTIONARY.md",
         "Data dictionary",
         "Column definitions, units and known caveats for every file in this release."),
    ]
    # Built rather than copied, so it goes in by hand just before the pose survey.
    zip_name = f"{aoi}_calibration_quadrat_boundaries.zip"
    n_quadrats = _quadrat_zip(args.calib_dir, labels_dir, rc, out / zip_name)

    entries, missing = [], []
    for src, name, label, note in items:
        if name == f"{aoi}_glint_pose_survey.csv" and n_quadrats:
            entries.append({
                "file": zip_name, "label": "Calibration quadrat boundaries",
                "note": f"GeoJSON boundary of each of the {n_quadrats} quadrats roofclf was "
                        "fitted on, with quadrats.csv: held-out skill and which ones the "
                        "coverage ratio was fitted on.",
                "size_bytes": (out / zip_name).stat().st_size,
            })
            log.info("packed %-56s %d quadrats", zip_name, n_quadrats)
        if src is None or not src.exists():
            missing.append(str(src or f"--{label.lower()}: not given"))
            continue
        if name.endswith("_buildings.parquet") and src.parent == rc and _probability_weighted(src):
            name = name.removesuffix("_buildings.parquet") + "_by_cell_and_size.parquet"
            note += (" One row per cell and size bin, every building weighted by its score: "
                     "n_buildings, sum_p (the expected number of PV roofs) and roof_area_m2 "
                     "(the bin's capacity-weighted mean roof size).")
        dst = out / name
        shutil.copy2(src, dst)
        n = _rows(dst) if dst.suffix in (".parquet", ".csv") else None
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
