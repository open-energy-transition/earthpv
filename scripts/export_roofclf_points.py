#!/usr/bin/env python
"""Every building `roofclf-score-national` scored, as one point per building, for checking
the national result on a map.

    .pixi/envs/default/bin/python scripts/export_roofclf_points.py --aoi pakistan

Writes to `--out-dir` (default data/roofclf_points/<aoi>):

- `<aoi>_roofclf_points.parquet`: GeoParquet, every building, for analysis.
- `<aoi>_roofclf_points.fgb`: the same in FlatGeobuf with a spatial index, so a desktop GIS
  reads only the viewport. Pakistan is 75.7M points: zoom in, or filter on `flagged`.
- `<aoi>_roofclf_flagged.fgb`: `flagged` buildings only, light enough to load whole.
- `README.md`, `stats.json`: the columns, the cut-offs and the checks below.

The point is the footprint's `point_on_surface`, so it always lands on the roof. A scored
cell is read, converted and dropped, never held with the others: loading every building at
once is what runs this machine out of memory (CLAUDE.md).

**The flags are the published chain's own.** The deployment threshold comes from the scoring's
`sub400_low_summary.json`, the domain from `sub400_capacity.national_cell_domain`, and the SPPI
cut is refit with the chain's own function (`sppi_cut`), because that summary stores it rounded
to four decimals, which lets in 195 extra buildings in Pakistan. The run reproduces the
summaries' counts or says it did not. The model is checked against the calibration directory
(`roofclf.check_scoring_matches_calibration`) before anything is read.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Six decimals is about 0.1 m, far finer than a 10 m pixel or a footprint's own accuracy.
COORD_DECIMALS = 6
GEO_META = {"version": "1.0.0", "primary_column": "geometry",
            "columns": {"geometry": {"encoding": "WKB", "geometry_types": ["Point"]}}}
SCHEMA = pa.schema([
    ("geometry", pa.binary()), ("lon", pa.float64()), ("lat", pa.float64()),
    ("p_roofclf", pa.float32()), ("sppi", pa.float32()), ("roof_area_m2", pa.float32()),
    ("flagged", pa.bool_()), ("and_gate", pa.bool_()), ("in_domain", pa.bool_()),
    ("calib_area", pa.string()), ("calib_in_fit", pa.bool_()), ("cell", pa.string()),
], metadata={b"geo": json.dumps(GEO_META).encode()})
BATCH = 65_536

_CTX: dict = {}


def sppi_cut(calib_dir: Path, low: dict, min_precision: float = 0.5) -> float:
    """The AND gate's exact SPPI cut, as `domain_restricted_and_gate_capacity` fits it
    (`min_precision` is `sub400-capacity`'s default). Refuses a value that does not round to
    what the published summary recorded: it would be a different cut."""
    import geopandas as gpd

    from earthpv.sppi import add_sppi, pooled_precision_threshold

    bt = gpd.read_parquet(calib_dir / "buildings.geoparquet")
    if "sppi" not in bt.columns:
        bt = add_sppi(bt)
    cut = float(pooled_precision_threshold(bt, low["calibration_quadrats"],
                                           min_precision=min_precision))
    if round(cut, 4) != low["sppi_threshold"]:
        raise SystemExit(f"SPPI cut {cut} does not round to the published "
                         f"{low['sppi_threshold']}: this scoring is not that summary's")
    return cut


def _init(ctx: dict) -> None:
    _CTX.update(ctx)
    _CTX["areas"] = [(stem, fit, shapely.from_wkb(wkb)) for stem, fit, wkb in ctx["areas"]]
    for _, _, geom in _CTX["areas"]:
        shapely.prepare(geom)


def _cell_table(path: Path) -> tuple[pa.Table | None, dict]:
    """One scored cell as a table in `SCHEMA`, plus its counts."""
    t = pq.read_table(path, columns=["cell", "geometry", "roof_area_m2", "p_roofclf", "sppi"])
    n = t.num_rows
    if not n:
        return None, {}
    cell = path.stem
    pts = shapely.point_on_surface(shapely.from_wkb(t["geometry"].to_numpy(zero_copy_only=False)))
    x = np.round(shapely.get_x(pts), COORD_DECIMALS)
    y = np.round(shapely.get_y(pts), COORD_DECIMALS)
    p = t["p_roofclf"].to_numpy(zero_copy_only=False).astype(float)
    s = t["sppi"].to_numpy(zero_copy_only=False).astype(float)
    area = t["roof_area_m2"].to_numpy(zero_copy_only=False).astype(float)
    flagged = p >= _CTX["threshold"]        # NaN (no valid composite pixel) is never flagged
    gate = flagged & (s >= _CTX["sppi_threshold"])
    dom = np.full(n, cell in _CTX["domain"])

    area_of = np.full(n, None, dtype=object)
    in_fit = np.zeros(n, dtype=bool)
    x0, y0, x1, y1 = x.min(), y.min(), x.max(), y.max()
    for stem, fit, geom in _CTX["areas"]:
        a0, b0, a1, b1 = geom.bounds
        if a0 > x1 or a1 < x0 or b0 > y1 or b1 < y0:
            continue
        inside = shapely.contains_xy(geom, x, y)
        area_of[inside] = stem
        in_fit[inside] = fit

    table = pa.table({
        "geometry": pa.array(shapely.to_wkb(shapely.points(x, y)), type=pa.binary()),
        "lon": pa.array(x, type=pa.float64()), "lat": pa.array(y, type=pa.float64()),
        "p_roofclf": pa.array(p, type=pa.float32(), mask=np.isnan(p)),
        "sppi": pa.array(s, type=pa.float32(), mask=np.isnan(s)),
        "roof_area_m2": pa.array(area, type=pa.float32()),
        "flagged": pa.array(flagged), "and_gate": pa.array(gate), "in_domain": pa.array(dom),
        "calib_area": pa.array(area_of, type=pa.string()), "calib_in_fit": pa.array(in_fit),
        "cell": pa.array(np.full(n, cell, dtype=object), type=pa.string()),
    }, schema=SCHEMA)
    ge400 = area >= 400
    return table, {
        "n": n, "n_scored": int((~np.isnan(p)).sum()), "n_flagged": int(flagged.sum()),
        "n_and_gate": int(gate.sum()), "n_in_domain": int(dom.sum()),
        "n_flagged_in_domain": int((flagged & dom).sum()),
        "n_and_gate_in_domain": int((gate & dom).sum()),
        "n_ge400_in_domain": int((ge400 & dom).sum()), "n_ge400": int(ge400.sum()),
        "n_ge400_scored_in_domain": int((ge400 & dom & ~np.isnan(p)).sum()),
        "n_calib_area": int(sum(v is not None for v in area_of)),
        "sum_p": float(np.nansum(p)), "cells_in_domain": int(dom[0]),
    }


def write_parquet(files: list[Path], out: Path, ctx: dict, workers: int) -> dict:
    """Cells in name order (so geographic), one row group per cell. Atomic: a killed run
    leaves no file that looks finished."""
    part = out.with_suffix(".parquet.part")
    totals: dict = {}
    with Pool(workers, initializer=_init, initargs=(ctx,)) as pool, \
            pq.ParquetWriter(part, SCHEMA, compression="zstd", compression_level=6) as w:
        for i, (table, stats) in enumerate(pool.imap(_cell_table, files, chunksize=4), 1):
            if table is not None:
                w.write_table(table, row_group_size=max(table.num_rows, 1))
                for k, v in stats.items():
                    totals[k] = totals.get(k, 0) + v
            if i % 250 == 0 or i == len(files):
                print(f"  {i:,}/{len(files):,} cells, {totals.get('n', 0):,} points", flush=True)
    part.rename(out)
    return totals


def write_fgb(parquet: Path, out: Path, flagged_only: bool) -> int:
    """FlatGeobuf with a spatial index, streamed from the GeoParquet. `lon`/`lat` stay out:
    the geometry holds them, and they would add about 1.5 GB to Pakistan's file."""
    from pyogrio import write_arrow

    cols = [f.name for f in SCHEMA if f.name not in ("lon", "lat")]
    schema = pa.schema([SCHEMA.field(c) for c in cols])
    count = [0]

    def batches():
        for b in pq.ParquetFile(parquet).iter_batches(batch_size=BATCH, columns=cols):
            b = b.select(cols)
            if flagged_only:
                b = b.filter(b.column("flagged"))
            if b.num_rows:
                count[0] += b.num_rows
                yield b

    part = out.with_suffix(".fgb.part.fgb")
    part.unlink(missing_ok=True)
    write_arrow(pa.RecordBatchReader.from_batches(schema, batches()), part, driver="FlatGeobuf",
                layer=out.stem, geometry_name="geometry", geometry_type="Point", crs="EPSG:4326",
                SPATIAL_INDEX="YES", TEMPORARY_DIR=str(out.parent))
    part.rename(out)
    return count[0]


def checks(totals: dict, low: dict, central: dict, ge400: dict) -> list[dict]:
    """This export's counts against what the published chain recorded for the same scoring."""
    rows = [
        ("roofclf AND SPPI buildings in the domain", totals["n_and_gate_in_domain"],
         low.get("n_flagged_in_domain"), "sub400_low_summary.json"),
        ("cells in the domain", totals["cells_in_domain"], low.get("n_domain_cells"),
         "sub400_low_summary.json"),
        ("scored buildings >= 400 m2 in the domain", totals["n_ge400_scored_in_domain"],
         ge400.get("n_buildings_in_size_range"), "ge400_roof_summary.json"),
        ("buildings in the domain", totals["n_in_domain"], central.get("n_buildings_in_domain"),
         "sub400_central_summary.json"),
    ]
    return [dict(check=c, this_export=a, published=b, source=s, match=a == b)
            for c, a, b, s in rows]


def write_readme(path: Path, aoi: str, s: dict) -> None:
    t = s["totals"]
    check_rows = "\n".join(
        f"| {c['check']} | {c['this_export']:,} | {c['published']:,} | {'yes' if c['match'] else 'NO'} |"
        for c in s["checks"])
    path.write_text(f"""# {aoi}: every roofclf score as a point

Exported {s['date']} by `scripts/export_roofclf_points.py` from `{s['scoring_dir']}`, the
scoring behind the published atlas (model fingerprint `{s['fingerprint']}`).

| Buildings | Scored | Flagged | roofclf AND SPPI | In the domain |
|---:|---:|---:|---:|---:|
| {t['n']:,} | {t['n_scored']:,} | {t['n_flagged']:,} | {t['n_and_gate']:,} | {t['n_in_domain']:,} |

## Files

- `{aoi}_roofclf_points.parquet`: GeoParquet, every building.
- `{aoi}_roofclf_points.fgb`: the same in FlatGeobuf with a spatial index. In QGIS, stay
  zoomed in or filter on `flagged`: drawing every point at country scale is very slow.
- `{aoi}_roofclf_flagged.fgb`: flagged buildings only, light enough to load whole.

## Columns

| Column | Meaning |
|---|---|
| `geometry` | a point on the roof (`point_on_surface` of the VIDA footprint), EPSG:4326 |
| `lon`, `lat` | the same, as numbers (GeoParquet only) |
| `p_roofclf` | the score; empty for a building with no valid composite pixel |
| `sppi` | the SPPI spectral index, unbounded where its denominator is near zero |
| `roof_area_m2` | footprint area |
| `flagged` | `p_roofclf >= {s['threshold']}`, the deployment threshold |
| `and_gate` | `flagged` and `sppi >= {s['sppi_threshold']:.6f}`, the stricter floor population |
| `in_domain` | the cell is inside the density-calibrated domain, where roofclf is priced |
| `calib_area` | the registered calibration area the point falls in, else empty |
| `calib_in_fit` | that area was in the published fit, so it is not independent evidence |
| `cell` | the 0.1 degree grid cell |

## Reading it

- **A score is not a measured probability of PV.** At {s['threshold']} the leave-one-area-out
  precision was {s['threshold_precision']} and recall {s['threshold_recall']}, in calibration
  areas that are purposive. Whether scores hold their level in sparse cells is unmeasured.
- **A point is not a capacity claim.** Best prices every in-domain building by its score,
  after removing buildings near OSM or priced segmentation detections and below the size
  floor, and those steps are not per-point columns here. `flagged` does not reproduce Best,
  and `and_gate` is only the input to the Verified floor.
- **PV may be beside the roof.** The production label credits mapped PV within 20 m of a
  footprint, so a correct flag can have its panels in the yard.
- **Check the imagery date first.** The scores come from composites whose scenes have a
  median date of {s['imagery']['median']} (middle half {s['imagery']['p25']} to
  {s['imagery']['p75']}). A roof under older imagery can look empty and still carry panels, so
  a false alarm there says nothing either way.
- **Areas with `calib_in_fit` true were trained on.** Use other areas to judge the model;
  a registered area with `calib_in_fit` false was mapped and not fitted.

## Checks against the published chain

| Count | This export | Published | Match |
|---|---:|---:|---|
{check_rows}
""")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--scoring-dir", type=Path, help="default data/roofclf_national_with_sppi/<aoi>")
    ap.add_argument("--calib-dir", type=Path, default=Path("data/roofclf"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--out-dir", type=Path, help="default data/roofclf_points/<aoi>")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit-cells", type=int, default=0, help="a pilot: first N cells only")
    ap.add_argument("--skip-parquet", action="store_true", help="reuse the finished GeoParquet")
    args = ap.parse_args()

    import geopandas as gpd
    import pandas as pd
    import yaml

    from earthpv import roofclf, sub400_capacity

    scoring = args.scoring_dir or Path(f"data/roofclf_national_with_sppi/{args.aoi}")
    prob, density = scoring / "prob", scoring / "density"
    out = args.out_dir or Path(f"data/roofclf_points/{args.aoi}")
    out.mkdir(parents=True, exist_ok=True)
    roofclf.check_scoring_matches_calibration(prob, args.calib_dir)

    low = json.loads((density / "sub400_low_summary.json").read_text())
    central = json.loads((density / "sub400_central_summary.json").read_text())
    ge400 = json.loads((density / "ge400_roof_summary.json").read_text())
    summary = json.loads((args.calib_dir / "summary.json").read_text())
    domain = sub400_capacity.national_cell_domain(
        args.calib_dir / "national_cell_density.parquet", args.aoi)

    fit = set(pd.read_csv(args.calib_dir / "folds.csv").quadrat)
    areas = []
    for stem in roofclf.discover_quadrats(args.labels_dir):
        geom = gpd.read_file(args.labels_dir / f"{stem}_boundary.geojson").to_crs(4326).union_all()
        areas.append((stem, stem.split("_calib_")[0] in fit, shapely.to_wkb(geom)))

    files = sorted(p for p in prob.glob("*.parquet"))
    if args.limit_cells:
        files = files[:args.limit_cells]
    cut = sppi_cut(args.calib_dir, low)
    print(f"{len(files):,} cells; flagged at {low['roofclf_threshold']}, SPPI floor at "
          f"{cut:.6f}; {len(domain):,} domain cells; {len(areas)} calibration "
          f"areas, {sum(a[1] for a in areas)} in the fit", flush=True)

    stem = f"{args.aoi}_roofclf"
    parquet, stats_path = out / f"{stem}_points.parquet", out / "stats.json"
    ctx = dict(threshold=low["roofclf_threshold"], sppi_threshold=cut,
               domain=domain, areas=areas)
    if args.skip_parquet:
        s = json.loads(stats_path.read_text())
    else:
        totals = write_parquet(files, parquet, ctx, args.workers)
        s = dict(date=date.today().isoformat(), aoi=args.aoi, scoring_dir=str(prob),
                 fingerprint=json.loads((prob / "_model.json").read_text())["fingerprint"],
                 threshold=low["roofclf_threshold"], sppi_threshold=cut,
                 threshold_precision=summary["deployment_threshold_stats"]["precision"],
                 threshold_recall=summary["deployment_threshold_stats"]["recall"],
                 imagery=yaml.safe_load(Path("configs/atlas_imagery_dates.yaml").read_text())
                 ["aois"][args.aoi],
                 n_cells=len(files), totals=totals, checks=checks(totals, low, central, ge400))
        stats_path.write_text(json.dumps(s, indent=1))
        write_readme(out / "README.md", args.aoi, s)
        for c in s["checks"]:
            print(f"  {'ok ' if c['match'] else 'DIFF'} {c['check']}: {c['this_export']:,} "
                  f"(published {c['published']:,}, {c['source']})", flush=True)

    print("flagged FlatGeobuf ...", flush=True)
    n = write_fgb(parquet, out / f"{stem}_flagged.fgb", flagged_only=True)
    print(f"  {n:,} points", flush=True)
    print("full FlatGeobuf ...", flush=True)
    n = write_fgb(parquet, out / f"{stem}_points.fgb", flagged_only=False)
    print(f"  {n:,} points", flush=True)
    print("EXPORT DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
