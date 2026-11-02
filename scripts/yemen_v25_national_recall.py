"""v13 against v25 on every OpenStreetMap array of 400 m2 and up in Yemen (2026-11-02).

Yemen's holdout ('Amran) is now almost all the owner's Huth farm area, small arrays beside
fields that no checkpoint sees, so it cannot decide between v13 and v25. This scores both
national probability rasters against every mapped array instead.

Per installation (OSM polygons dissolved per placement, as the atlas does): the highest
probability any pixel touching it reaches (all_touched), so "found at t" means some pixel
>= t, as `compare_backbones.py` scores. Pixel precision per threshold: predicted pixels
touching any mapped polygon (any size) over all predicted pixels, nationally and again
outside both models' training chips (a floor: unmapped PV counts as false, the same for
both models). Each model is also read at the lowest threshold reaching v13's precision at
0.3, with an exact McNemar test on the arrays one finds and the other misses, per placement,
size bin, mapping date (by the 2026-10-24 pull both models trained on, or added after) and
training-chip overlap.

Per-candidate counts would mislead here: `postprocess.replace_with_osm_geometry` gives a
matched candidate one OpenStreetMap polygon, so its neighbours lose the match.

    pixi run python scripts/yemen_v25_national_recall.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from scipy.stats import binomtest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from earthpv.labels import dissolve_overlapping  # noqa: E402

THR = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
CHIP_HALF_M = 1120.0  # 224 px chips at 10 m


def chip_boxes(index: Path, splits: list[str]) -> gpd.GeoDataFrame:
    c = pd.read_parquet(index)
    c = c[c.split.isin(splits)]
    h = CHIP_HALF_M
    return gpd.GeoDataFrame(
        geometry=[box(lo - h / (111320 * np.cos(np.radians(la))), la - h / 111320,
                      lo + h / (111320 * np.cos(np.radians(la))), la + h / 111320)
                  for lo, la in zip(c.lon, c.lat)], crs=4326)


def touches(g: gpd.GeoDataFrame, other: gpd.GeoDataFrame) -> np.ndarray:
    j = gpd.sjoin(g[["geometry"]], other[["geometry"]], predicate="intersects", how="left")
    hit = j.groupby(level=0)["index_right"].apply(lambda s: s.notna().any())
    return hit.reindex(g.index).fillna(False).to_numpy(bool)


def operating_point(prec: dict, target: float) -> float:
    ok = [t for t in THR if prec[t] >= target]
    return min(ok) if ok else max(THR, key=lambda t: prec[t])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--osm", type=Path, default=Path("data/labels/yemen_national_osm_solar.parquet"),
                    help="the 2026-11-01 national OSM layer (prepare_national_osm_solar.py)")
    ap.add_argument("--old-osm", type=Path,
                    default=Path("/home/tobi/earthpv_data/yemen_PRE_v25_20261101/"
                                 "yemen_national_osm_solar.parquet"),
                    help="the layer from the late 2026-10-24 pull both models were trained on")
    ap.add_argument("--v13", type=Path, default=Path("data/predictions/yemen/prob"))
    ap.add_argument("--v25", type=Path, default=Path("data/predictions_v25/yemen/prob"))
    ap.add_argument("--v13-chips", type=Path, default=Path("data/chips/yemen/index.parquet"))
    ap.add_argument("--v25-chips", type=Path, default=Path("data/chips/yemen_v25/index.parquet"))
    ap.add_argument("--out", type=Path, default=Path("results/yemen_v25_national_recall"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    runs = {"v13": a.v13, "v25": a.v25}

    poly = ["Polygon", "MultiPolygon"]
    osm = gpd.read_parquet(a.osm)
    osm = osm[osm.geometry.geom_type.isin(poly)].copy()
    old = gpd.read_parquet(a.old_osm)
    old = old[old.geometry.geom_type.isin(poly)]
    allpoly = osm[["geometry"]].copy()  # every mapped polygon, any size, for pixel precision
    d = dissolve_overlapping(osm[["placement", "area_m2", "geometry"]].copy(),
                             group_col="placement").reset_index(drop=True)
    d = d[d["area_m2"] >= 400].copy()
    d["mapped"] = np.where(touches(d, old), "by 10-24", "10-25..10-31")
    train13 = chip_boxes(a.v13_chips, ["train"])
    train25 = chip_boxes(a.v25_chips, ["train"])
    trainbox = pd.concat([train25, train13], ignore_index=True)
    d["in_v25_train"] = touches(d, train25)
    d["in_v13_train"] = touches(d, train13)
    d["in_holdout"] = touches(d, chip_boxes(a.v25_chips, ["val", "buffer"]))
    d["size_bin"] = pd.cut(d["area_m2"], [400, 1000, 5000, 50000, np.inf],
                           labels=["400-1k", "1k-5k", "5k-50k", ">50k"], right=False).astype(str)

    maxp = {k: np.zeros(len(d), dtype=np.uint8) for k in runs}
    px = {k: {t: [0, 0] for t in THR} for k in runs}
    pxo = {k: {t: [0, 0] for t in THR} for k in runs}
    cells = sorted(p.name for p in a.v13.glob("*.tif"))
    for i, name in enumerate(cells):
        for k, root in runs.items():
            with rasterio.open(root / name) as r:
                arr = r.read(1)
                crs, tr, shape, bnd = r.crs, r.transform, arr.shape, r.bounds
            cellbox = gpd.GeoSeries([box(*bnd)], crs=crs).to_crs(4326).iloc[0]
            mp = allpoly[allpoly.intersects(cellbox)].to_crs(crs)
            mask = (features.rasterize(((g, 1) for g in mp.geometry), out_shape=shape,
                                       transform=tr, all_touched=True, dtype="uint8") > 0
                    if len(mp) else np.zeros(shape, bool))
            tb = trainbox[trainbox.intersects(cellbox)].to_crs(crs)
            outside = (features.rasterize(((g, 1) for g in tb.geometry), out_shape=shape,
                                          transform=tr, all_touched=True, dtype="uint8") == 0
                       if len(tb) else np.ones(shape, bool))
            for t in THR:
                hot = arr >= round(t * 255)
                px[k][t][0] += int(hot.sum())
                px[k][t][1] += int((hot & mask).sum())
                pxo[k][t][0] += int((hot & outside).sum())
                pxo[k][t][1] += int((hot & outside & mask).sum())
            sub = d[d.intersects(cellbox)]
            for idx, g in zip(sub.index, sub.to_crs(crs).geometry):
                c0f, r0f = ~tr * (g.bounds[0], g.bounds[3])
                c1f, r1f = ~tr * (g.bounds[2], g.bounds[1])
                r0, c0 = max(0, int(np.floor(r0f)) - 1), max(0, int(np.floor(c0f)) - 1)
                r1 = min(shape[0], int(np.ceil(r1f)) + 1)
                c1 = min(shape[1], int(np.ceil(c1f)) + 1)
                if r1 <= r0 or c1 <= c0:
                    continue
                wt = rasterio.windows.transform(rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0), tr)
                m = features.rasterize([(g, 1)], out_shape=(r1 - r0, c1 - c0), transform=wt,
                                       all_touched=True, dtype="uint8")
                if m.any():
                    pos = d.index.get_loc(idx)
                    maxp[k][pos] = max(maxp[k][pos], int(arr[r0:r1, c0:c1][m > 0].max()))
        if i % 100 == 0:
            print(f"{i}/{len(cells)}", flush=True)

    for k in runs:
        d[f"maxp_{k}"] = maxp[k]
    d.drop(columns="geometry").to_csv(a.out / "installations.csv", index=False)
    prec = {k: {t: px[k][t][1] / max(px[k][t][0], 1) for t in THR} for k in runs}
    preco = {k: {t: pxo[k][t][1] / max(pxo[k][t][0], 1) for t in THR} for k in runs}
    op = {k: operating_point(prec[k], prec["v13"][0.3]) for k in runs}
    opo = {k: operating_point(preco[k], preco["v13"][0.3]) for k in runs}

    def compare(sub, ta, tb):
        x = sub["maxp_v13"].to_numpy() >= round(ta * 255)
        y = sub["maxp_v25"].to_numpy() >= round(tb * 255)
        gain, loss = int((y & ~x).sum()), int((x & ~y).sum())
        p = binomtest(gain, gain + loss).pvalue if gain + loss else 1.0
        return dict(n=len(sub), v13=round(x.mean(), 3) if len(sub) else None,
                    v25=round(y.mean(), 3) if len(sub) else None,
                    only_v25=gain, only_v13=loss, p=round(p, 4))

    groups = {"all": d}
    for pl in ("rooftop", "ground"):
        groups[pl] = d[d.placement == pl]
        for sb in ("400-1k", "1k-5k", "5k-50k", ">50k"):
            groups[f"{pl} {sb}"] = d[(d.placement == pl) & (d.size_bin == sb)]
        for when in ("by 10-24", "10-25..10-31"):
            groups[f"{pl}, mapped {when}"] = d[(d.placement == pl) & (d.mapped == when)]
        groups[f"{pl}, outside both models' training chips"] = d[
            (d.placement == pl) & ~d.in_v25_train & ~d.in_v13_train]
        groups[f"{pl}, 'Amran holdout"] = d[(d.placement == pl) & d.in_holdout]
    res = dict(
        precision={k: {str(t): round(v, 4) for t, v in prec[k].items()} for k in runs},
        precision_target=round(prec["v13"][0.3], 4), operating_points=op,
        predicted_pixels={k: {str(t): px[k][t][0] for t in THR} for k in runs},
        at_0_3={g: compare(s, 0.3, 0.3) for g, s in groups.items()},
        at_matched_precision={g: compare(s, op["v13"], op["v25"]) for g, s in groups.items()},
        precision_outside_train={k: {str(t): round(v, 4) for t, v in preco[k].items()}
                                 for k in runs},
        pixels_outside_train={k: {str(t): pxo[k][t][0] for t in THR} for k in runs},
        operating_points_outside_train=opo,
        at_matched_precision_outside_train={g: compare(s, opo["v13"], opo["v25"])
                                            for g, s in groups.items()},
        training_chip_share={pl: {"v25": round(float(d[d.placement == pl].in_v25_train.mean()), 3),
                                  "v13": round(float(d[d.placement == pl].in_v13_train.mean()), 3)}
                             for pl in ("rooftop", "ground")},
    )
    (a.out / "summary.json").write_text(json.dumps(res, indent=1))
    for key in ("at_0_3", "at_matched_precision", "at_matched_precision_outside_train"):
        print("==", key)
        for g, r in res[key].items():
            print(f"  {g:48s} n={r['n']:5d} v13={r['v13']} v25={r['v25']} "
                  f"+{r['only_v25']}/-{r['only_v13']} p={r['p']}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
