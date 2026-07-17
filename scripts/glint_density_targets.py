"""Build glint-validation target sets for the density-improvement experiment.

Density (`density.py`) reports two numbers per building/region: `pv_area_det` (the
precision-honest floor — only pixels crossing the 0.3 threshold) and `pv_area_exp`
(a probability-weighted ceiling). The true regional PV area sits somewhere between
them, driven mostly by installations the model recall-misses entirely (README:
Germany 83-95% per-installation recall, Punjab 14-55% — the *missed* fraction is not
random, and it disproportionately determines how far `pv_area_det` undershoots truth).

Question: can a glint check on the missed candidates recover some of that gap, at an
acceptable false-positive cost — i.e. can `pv_area_det + recovered_area` be a better
density estimate than `pv_area_det` alone? This script builds two matched samples per
region (`missed` true installations the model's own detected-candidate mask does not
overlap, and `control` non-PV buildings) so a later glint pull can measure the
corroboration rate on each. `glint_density_pull.py` / `glint_density_analyze.py`
consume the *_targets.parquet this writes.

Usage:
  .pixi/envs/ml/bin/python scripts/glint_density_targets.py germany
  .pixi/envs/default/bin/python scripts/glint_density_targets.py lahore
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.warp
from rasterio import features as rio_features
from shapely.geometry import box
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv.config import DATA_DIR, Settings  # noqa: E402
from earthpv.labels import geodesic_area_m2, resolve_aoi  # noqa: E402
from earthpv.local_source import load_buildings, load_solar_labels  # noqa: E402

log = logging.getLogger("glint_density_targets")
app = typer.Typer(pretty_exceptions_show_locals=False)

OUT_DIR = DATA_DIR / "glint"
GERMANY_CHECKPOINT = Path("data/models/v2_combined/terramind-pv-epoch=39-step=8240.ckpt")
THRESHOLD = 0.3
SEED = 42
N_CONTROLS = 70

LAHORE_BBOX = (74.05, 31.30, 74.55, 31.65)  # covers Lahore city + suburbs


def _write(name: str, missed: list[dict], controls: list[dict]) -> None:
    for r in missed:
        r["kind"] = "missed"
    for r in controls:
        r["kind"] = "control"
    rows = missed + controls
    out = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    out["pid"] = [f"{name}_{i:04d}" for i in range(len(out))]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_DIR / f"{name}_density_targets.parquet")
    log.info("%s: %d missed (area=%.0f m2 total), %d controls -> %s", name, len(missed),
             sum(r["area_m2"] for r in missed), len(controls),
             OUT_DIR / f"{name}_density_targets.parquet")


@app.command()
def germany(limit: int = typer.Option(0, help="cap chips processed, 0 = all val chips")):
    """Run the production checkpoint over Germany's held-out val chips; every ground-truth
    installation the thresholded mask doesn't overlap becomes a `missed` target; non-PV
    buildings in the same chips become `control` targets."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import torch

    from earthpv.infer import load_model

    rng = np.random.default_rng(SEED)
    settings = Settings.load()
    _, cfg = resolve_aoi("germany", settings)
    region_dir = Path(settings.raw["local_root"]) / cfg["source_region"]
    labels = load_solar_labels(region_dir)
    labels = labels[labels.placement.isin(["rooftop", "ground"])].reset_index(drop=True)
    buildings = load_buildings(region_dir)
    log.info("%d GT installations, %d candidate buildings in %s", len(labels),
             0 if buildings is None else len(buildings), region_dir)

    index = pd.read_parquet(Path("data/chips/germany") / "index.parquet")
    val = index[index.split == "val"]
    if limit:
        val = val.head(limit)
    log.info("Scanning %d val chips with %s", len(val), GERMANY_CHECKPOINT)

    task, device, task_type = load_model(GERMANY_CHECKPOINT, task_type="auto")
    labels_sindex = labels.sindex
    buildings_sindex = buildings.sindex if buildings is not None else None

    missed, controls, seen_osm = [], [], set()
    for _, row in val.iterrows():
        with rasterio.open(row["image"]) as src:
            arr = src.read().astype("float32")
            transform, crs, shape_ = src.transform, src.crs, (src.height, src.width)
            chip_geo = box(*rasterio.warp.transform_bounds(crs, "EPSG:4326", *src.bounds))
        x = torch.from_numpy(arr / 10000.0)[None].to(device)
        with torch.no_grad(), torch.autocast(device_type=device, enabled=device == "cuda"):
            out = task(x)
            logits = out.output if hasattr(out, "output") else out
            frac = torch.softmax(logits, 1)[0, 1].cpu().numpy() if task_type != "regression" \
                else logits[0].clamp(0, 1).cpu().numpy()
        pred = frac >= THRESHOLD

        gt_idx = labels_sindex.query(chip_geo, predicate="intersects")
        for i in gt_idx:
            inst = labels.iloc[i]
            if inst.osm_id in seen_osm:
                continue
            seen_osm.add(inst.osm_id)
            poly = gpd.GeoSeries([inst.geometry], crs="EPSG:4326").to_crs(crs).iloc[0]
            inst_mask = rio_features.rasterize(
                [(poly, 1)], out_shape=shape_, transform=transform, all_touched=True, dtype="uint8"
            ).astype(bool)
            if not inst_mask.any() or (pred & inst_mask).any():
                continue
            area = inst.area_m2 if inst.area_m2 > 0 else geodesic_area_m2(inst.geometry)
            missed.append({"geometry": inst.geometry, "area_m2": round(float(area), 1)})

        if buildings_sindex is not None and len(controls) < N_CONTROLS * 3:
            b_idx = buildings_sindex.query(chip_geo, predicate="intersects")
            for i in b_idx:
                bldg = buildings.iloc[i]
                if labels_sindex.query(bldg.geometry, predicate="intersects").size:
                    continue
                area = geodesic_area_m2(bldg.geometry)
                if not (50 <= area <= 5000):
                    continue
                controls.append({"geometry": bldg.geometry, "area_m2": round(float(area), 1)})

    if len(controls) > N_CONTROLS:
        keep = rng.choice(len(controls), N_CONTROLS, replace=False)
        controls = [controls[i] for i in keep]
    _write("germany", missed, controls)


@app.command()
def lahore():
    """Offline (no GPU): use the already-computed Pakistan country-wide prob rasters +
    candidates.parquet + density buildings layer to find, within the Lahore bbox, every
    OSM-mapped installation the thresholded raster mask doesn't overlap (`missed`), plus
    a control sample of buildings the density stage found zero PV signal on."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from glint_iou_experiment import prob_raster_index, pred_plain, read_window, T_BASE  # noqa: E402

    rng = np.random.default_rng(SEED)
    osm = gpd.read_file(DATA_DIR / "osm_pk_solar_160726.geojson")
    osm = osm[osm.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    lahore_osm = osm.cx[LAHORE_BBOX[0]:LAHORE_BBOX[2], LAHORE_BBOX[1]:LAHORE_BBOX[3]].reset_index(drop=True)
    lahore_osm["area_m2"] = [geodesic_area_m2(g) for g in lahore_osm.geometry]
    log.info("%d OSM solar features in Lahore bbox", len(lahore_osm))

    idx = prob_raster_index()
    reps = gpd.GeoDataFrame(geometry=lahore_osm.geometry.representative_point(), crs="EPSG:4326")
    hits = gpd.sjoin(reps, idx, predicate="within", how="left")
    lahore_osm["path"] = hits["path"].to_numpy()[: len(lahore_osm)]

    missed = []
    n_detected = n_norasrer = 0
    for row in lahore_osm.itertuples():
        if not isinstance(row.path, str):
            n_norasrer += 1
            continue
        rw = read_window(row.path, row.geometry)
        if rw is None:
            n_norasrer += 1
            continue
        prob, gt = rw
        pred = pred_plain(prob, T_BASE)
        if (pred & gt).any():
            n_detected += 1
            continue
        missed.append({"geometry": row.geometry, "area_m2": round(float(row.area_m2), 1)})
    log.info("Lahore: %d detected, %d missed, %d had no covering raster/footprint",
             n_detected, len(missed), n_norasrer)

    # Lahore's missed mass is dominated by tiny (<500 m2) residential rooftop generators
    # that the size-stratified country study already showed almost never glint-validate
    # (2.5-8.8%) -- pulling all ~3.6k of them would spend the whole network budget for
    # little signal. Keep every missed install >= 500 m2 (this project's actual target
    # class) and a bounded context sample of the smaller ones.
    big = [m for m in missed if m["area_m2"] >= 500]
    small = [m for m in missed if m["area_m2"] < 500]
    if len(small) > 80:
        keep = rng.choice(len(small), 80, replace=False)
        small = [small[i] for i in keep]
    log.info("Lahore missed: keeping all %d >=500m2 + %d/%d <500m2 sample", len(big),
             len(small), len(missed) - len(big))
    missed = big + small

    density_bldgs = gpd.read_parquet(Path("data/predictions/pakistan/density/buildings.geoparquet"))
    lb = density_bldgs.cx[LAHORE_BBOX[0]:LAHORE_BBOX[2], LAHORE_BBOX[1]:LAHORE_BBOX[3]]
    lb = lb[(lb.pv_area_det_m2 <= 0) & (lb.roof_area_m2.between(50, 5000))]
    log.info("%d zero-PV Lahore buildings available as controls", len(lb))
    keep = rng.choice(len(lb), min(N_CONTROLS, len(lb)), replace=False)
    controls = [{"geometry": g, "area_m2": round(float(a), 1)}
                for g, a in zip(lb.geometry.iloc[keep], lb.roof_area_m2.iloc[keep])]

    _write("lahore", missed, controls)


if __name__ == "__main__":
    app()
