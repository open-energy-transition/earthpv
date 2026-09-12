#!/usr/bin/env python
"""Synthesize roofclf quadrats whose labels come from OpenPVMapper, not from a human.

The control for one specific objection to
[the French roofclf result](../docs/results/france.md): that 0.627 within-size AUC reflects
1,231 hand-mapped positives being too few, rather than a 20 m2 array being a fifth of a
Sentinel-2 pixel. OpenPVMapper supplies 1.13M rooftop polygons nationally, so a model fitted
on them has roughly thirty times the supervision and can be scored on exactly the same
hand-mapped truth.

**These are written to their own directory, never to `data/labels/`.** `discover_quadrats`
globs that directory, so a pseudo-quadrat left there would silently join the next Pakistani
refit -- the Kalat Rural footgun, which is also why the real French quadrats live in
`data/labels/france/`.

**The fourteen hand-mapped communes are excluded by INSEE**, because they are OpenPVMapper's
own manual-correction layer: training on them and testing on them would be leakage in both
directions at once.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("opvm-quadrats")

ROOT = Path(__file__).resolve().parents[1]


def slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "_" for c in name]
    out = "".join(keep)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True, help="CSV with an insee column")
    ap.add_argument("--out-dir", default="data/labels/france_opvm")
    ap.add_argument("--communes", default="data/labels/france_communes.parquet")
    ap.add_argument("--opvm", default="data/openpvmapper/enriched_national.parquet")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sel = pd.read_csv(args.selection, dtype={"insee": str})
    sel["insee"] = sel.insee.str.zfill(5)
    want = set(sel.insee)

    log.info("reading communes")
    com = gpd.read_parquet(args.communes)
    com["insee"] = com.insee.astype(str).str.zfill(5)
    com = com[com.insee.isin(want)].to_crs("EPSG:4326").reset_index(drop=True)

    log.info("reading OpenPVMapper (%d communes wanted)", len(want))
    o = gpd.read_parquet(args.opvm)
    o["insee"] = o.insee.astype(str).str.zfill(5)
    o = o[o.insee.isin(want) & (o.false_positive != True)]  # noqa: E712
    o = o.to_crs("EPSG:4326")
    log.info("OpenPVMapper arrays in selection: %d", len(o))

    from earthpv.labels import geodesic_area_m2

    manifest = []
    for _, c in com.iterrows():
        pv = o[o.insee == c.insee].copy()
        if pv.empty:
            continue
        pv = pv[pv.geometry.notna() & pv.geometry.is_valid]
        pv = pv[pv.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
        if pv.empty:
            continue
        km2 = float(c.surface_ha) / 100.0
        stem = f"{slug(c.nom)}_opvm_{km2:.2f}".replace(".", "p") + "km2"

        pv_out = gpd.GeoDataFrame({
            "id": pv.array_id.astype(str).to_numpy(),
            "kind": "generator",
            # OpenPVMapper is a rooftop-only product, so every row is rooftop by
            # construction; parcel_pv_area reads this column to decide what counts as
            # yard ground-mount, and would otherwise treat them all as unknown.
            "placement": "rooftop",
            "area_m2": [geodesic_area_m2(g) for g in pv.geometry],
            "label_tag": "opvm",
            "geometry": pv.geometry.to_numpy(),
        }, geometry="geometry", crs="EPSG:4326")
        pv_out.to_parquet(out / f"{stem}_overpass_solar.parquet")

        gpd.GeoDataFrame([{
            "quadrat_id": stem, "location": c.nom, "insee": c.insee,
            "province": f"dept-{str(c.insee)[:2]}", "size_km2": km2,
            "shape": "commune", "stratum": "opvm_pseudo_label",
            # Not a human mapping date: these labels are a model output, and nothing
            # downstream should read them as Rule-1 complete.
            "mapping_date": None, "source_geojson": None,
            "label_source": "openpvmapper",
        }], geometry=[c.geometry], crs="EPSG:4326").to_file(
            out / f"{stem}_boundary.geojson", driver="GeoJSON")

        manifest.append({"stem": stem, "insee": c.insee, "commune": c.nom,
                         "km2": round(km2, 3), "n_arrays": int(len(pv_out)),
                         "median_array_m2": round(float(pv_out.area_m2.median()), 1)})

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    tot = sum(m["n_arrays"] for m in manifest)
    log.info("wrote %d pseudo-quadrats, %d arrays, %.0f km2 -> %s",
             len(manifest), tot, sum(m["km2"] for m in manifest), out)


if __name__ == "__main__":
    main()
