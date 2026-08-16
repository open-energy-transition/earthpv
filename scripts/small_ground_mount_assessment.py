"""Can any existing instrument be pointed at the sub-400 m2 GROUND-mount gap?

`docs/issues/small-ground-mount-instrument.md` established the gap structurally and sized it
against two external estimates, but measured nothing. This script measures it, in five
stages, against the project's own Rule-1-complete calibration quadrats plus the national OSM
solar pull. Written to answer one question the sketch in that document left open: whether the
candidate universe has to be invented from scratch (cropland parcels, sliding tiles) or
whether the VIDA building index that `roofclf` already scores nationally brackets the
population well enough to serve.

Stages, each runnable on its own:

    census      per-quadrat count/area of strict ground-mount PV, and distance from each
                installation to the nearest VIDA building, against a null model of random
                points in the same quadrat
    national    the same anchor test on every OSM ground-tagged generator under 400 m2 in
                Pakistan, independent of where the quadrats happen to be drawn
    searchspace share of national land within 20/30/50 m of a VIDA building, stratified over
                the whole cell-density range -- what a building anchor costs in coverage
    parcels     builds one row per in-boundary VIDA building carrying three feature blocks
                (roof, yard, both) plus a ground-mount label, to `data/ground_mount/`
    evaluate    leave-one-quadrat-out AUC and precision-at-recall on that table

Definitions that matter and are easy to get wrong:

- **strict ground-mount** = OSM `placement == "ground"` AND less than 30% of the polygon
  overlapping a VIDA footprint. Either test alone disagrees with the other on roughly half
  the population (743 OSM-ground of which 443 sit on a footprint; 15,560 OSM-rooftop of
  which 592 do not), so requiring both is the conservative read and is what every number
  here uses.
- **the yard** is partitioned by a distance-transform Voronoi over the building mask, not by
  buffering each footprint. Overlapping buffers would credit the same pixel to several
  buildings, and in a dense quadrat almost every pixel is in several buffers.
- capacity uses `DEFAULT_KWP_PER_M2_MODULE`, deliberately **not** the ground-mount land
  constant: these are `power=generator` polygons traced around the panel array itself
  (quadrat median 65 m2), whereas `DEFAULT_KWP_PER_M2_LAND` was calibrated on `power=plant`
  site perimeters. Using the land constant here understates by 3.6x.

Usage:
    .pixi/envs/default/bin/python scripts/small_ground_mount_assessment.py census
    .pixi/envs/default/bin/python scripts/small_ground_mount_assessment.py parcels
    .pixi/envs/default/bin/python scripts/small_ground_mount_assessment.py evaluate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
from rasterio.warp import transform_bounds
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.buildings import fetch_vida_buildings  # noqa: E402
from earthpv.capacity_calibration import (  # noqa: E402
    DEFAULT_KWP_PER_M2_LAND, DEFAULT_KWP_PER_M2_MODULE,
)
from earthpv.labels import geodesic_area_m2  # noqa: E402
from earthpv.local_source import composite_index  # noqa: E402
from earthpv.roofclf import (  # noqa: E402
    BAND_NAMES, COMPOSITE_FILL, REFL_SCALE, _raster_for, _read_prob, auc,
    discover_quadrats, fit_logistic, load_quadrat, predict_proba, quadrat_label,
    shape_features, zonal_mean_max,
)
from earthpv.sppi import compute_sppi  # noqa: E402

OUT = Path("data/ground_mount")
LABELS = Path("data/labels")
COMPOSITES = Path("data/composites/pakistan")
SEG_DIR = Path("data/predictions_v4/pakistan/prob")
FRAC_DIR = Path("data/predictions_frac_pk_v2/pakistan/prob")
CELL_DENSITY = Path("data/roofclf/national_cell_density.parquet")
NATIONAL_SOLAR = Path("data/labels/pakistan_overpass_solar.parquet")

RING_M = 20.0            # yard depth; 96% of strict ground-mount sits inside it
MAX_GM_AREA = 400.0      # above this, segmentation is the instrument of record
VIDA_OVERLAP_MAX = 0.30  # above this the array is on the roof, not beside it
SEED = 20260816
DERIV = ["sppi", "ndvi", "ndbi", "brightness", "swir_vis", "blue_red"]
EPS = 1e-6


def _utm(lon: float, lat: float) -> int:
    return (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1


def _strict_ground(pv: gpd.GeoDataFrame, bu_utm: gpd.GeoDataFrame) -> np.ndarray:
    """Boolean mask over `pv`: OSM says ground AND it does not sit on a VIDA footprint."""
    pv_utm = pv.to_crs(bu_utm.crs)
    ov = np.zeros(len(pv))
    sidx = bu_utm.sindex
    for i, g in enumerate(pv_utm.geometry):
        hits = sidx.query(g, predicate="intersects")
        if len(hits):
            ov[i] = sum(g.intersection(bu_utm.geometry.iloc[h]).area
                        for h in hits) / max(g.area, EPS)
    return (pv["placement"].to_numpy() == "ground") & (ov < VIDA_OVERLAP_MAX)


def _derived(b: dict, prefix: str) -> dict:
    d = {f"{prefix}{k}": b[k] for k in BAND_NAMES}
    d[f"{prefix}sppi"] = compute_sppi(b["b02"], b["b03"], b["b08"], b["b11"], b["b12"])
    d[f"{prefix}ndvi"] = (b["b08"] - b["b04"]) / (b["b08"] + b["b04"] + EPS)
    d[f"{prefix}ndbi"] = (b["b11"] - b["b08"]) / (b["b11"] + b["b08"] + EPS)
    d[f"{prefix}brightness"] = np.mean([b[k] for k in BAND_NAMES], axis=0)
    d[f"{prefix}swir_vis"] = b["b11"] / (np.mean([b["b02"], b["b03"], b["b04"]], axis=0) + EPS)
    d[f"{prefix}blue_red"] = b["b02"] / (b["b04"] + EPS)
    return d


# --------------------------------------------------------------------------------------
def cmd_census(_args) -> None:
    """Population census plus the anchor test, per quadrat, with a same-quadrat null."""
    rng = np.random.default_rng(SEED)
    rows, inst = [], []
    for stem in discover_quadrats(LABELS):
        name = quadrat_label(stem)
        boundary, pv = load_quadrat(stem, LABELS)
        minx, miny, maxx, maxy = boundary.bounds
        epsg = _utm((minx + maxx) / 2, (miny + maxy) / 2)
        bnd = gpd.GeoSeries([boundary], crs="EPSG:4326").to_crs(epsg).iloc[0]
        # Buildings are fetched beyond the boundary on purpose: a building just outside it
        # is still a real anchor for an installation just inside. The building COUNT below
        # is taken from the in-boundary subset only, which is the denominator that
        # reproduces density.CALIBRATED_BLDG_DENSITY_KM2.
        bu = fetch_vida_buildings((minx - 0.01, miny - 0.01, maxx + 0.01, maxy + 0.01), "PAK")
        bu_utm = bu.to_crs(epsg)
        n_in = int(bu_utm.geometry.representative_point().within(bnd).sum())
        union = bu_utm.geometry.union_all() if len(bu_utm) else None

        pts, (bx0, by0, bx1, by1) = [], bnd.bounds
        while len(pts) < 4000:
            cand = gpd.GeoSeries(gpd.points_from_xy(
                rng.uniform(bx0, bx1, 8000), rng.uniform(by0, by1, 8000)), crs=epsg)
            pts.extend(cand[cand.within(bnd)].tolist())
        null_d = gpd.GeoSeries(pts[:4000], crs=epsg).distance(union)

        n_gm = 0
        gm_area = 0.0
        if not pv.empty and union is not None:
            pv = pv.copy()
            pv["area_m2"] = [geodesic_area_m2(g) for g in pv.geometry]
            strict = _strict_ground(pv, bu_utm)
            d = pv.to_crs(epsg).distance(union).to_numpy()
            for i in np.flatnonzero(strict & (pv.area_m2.to_numpy() < MAX_GM_AREA)):
                inst.append({"quadrat": name, "osm_id": pv["id"].iloc[i],
                             "area_m2": float(pv.area_m2.iloc[i]), "dist_bldg_m": float(d[i])})
            keep = strict & (pv.area_m2.to_numpy() < MAX_GM_AREA)
            n_gm, gm_area = int(keep.sum()), float(pv.area_m2.to_numpy()[keep].sum())

        area_km2 = bnd.area / 1e6
        rows.append({"quadrat": name, "area_km2": round(area_km2, 3), "n_bldg": n_in,
                     "bldg_km2": round(n_in / area_km2, 1), "n_ground_sub400": n_gm,
                     "ground_sub400_area_m2": round(gm_area, 1),
                     "null_within_30m": round(float((null_d <= 30).mean()), 4),
                     "null_within_100m": round(float((null_d <= 100).mean()), 4)})
        print(f"{name:26s} {area_km2:5.2f} km2  bldg {n_in:6d}  ground<400 {n_gm:3d} "
              f"({gm_area:7.1f} m2)  null<=30m {rows[-1]['null_within_30m']:.3f}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "quadrat_census.csv", index=False)
    d = pd.DataFrame(inst)
    d.to_csv(OUT / "installations.csv", index=False)
    print(f"\n=== anchor: distance from {len(d)} installations to the nearest VIDA building")
    for m in (5, 10, 20, 30, 50, 100):
        print(f"  <= {m:3d} m: {100*(d.dist_bldg_m <= m).mean():5.1f}% of installations, "
              f"{100*d.loc[d.dist_bldg_m <= m, 'area_m2'].sum()/d.area_m2.sum():5.1f}% of area")


def cmd_national(_args) -> None:
    """The same anchor test on the national OSM pull, independent of the quadrat set."""
    rng = np.random.default_rng(SEED)
    pv = gpd.read_parquet(NATIONAL_SOLAR).to_crs("EPSG:4326")
    pv = pv[pv.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    pv["area_m2"] = [geodesic_area_m2(g) for g in pv.geometry]
    gm = pv[(pv.placement == "ground") & (pv["kind"] == "generator")
            & (pv.area_m2 < MAX_GM_AREA)].reset_index(drop=True)
    print(f"national OSM ground-tagged generators < {MAX_GM_AREA:.0f} m2: {len(gm)}")
    cent = gm.to_crs("EPSG:4326").geometry.representative_point()
    gm["cx"], gm["cy"] = np.floor(cent.x / 0.1).astype(int), np.floor(cent.y / 0.1).astype(int)

    obs, nul = [], []
    for (cx, cy), g in gm.groupby(["cx", "cy"]):
        lon0, lat0 = cx * 0.1, cy * 0.1
        bu = fetch_vida_buildings(
            (lon0 - 0.005, lat0 - 0.005, lon0 + 0.105, lat0 + 0.105), "PAK")
        if bu.empty:
            continue
        epsg = _utm(lon0, lat0)
        bu_u = bu.to_crs(epsg)
        union = bu_u.geometry.union_all()
        obs.extend(g.to_crs(epsg).distance(union).tolist())
        pts = gpd.GeoSeries(gpd.points_from_xy(
            rng.uniform(lon0, lon0 + 0.1, 200), rng.uniform(lat0, lat0 + 0.1, 200)),
            crs="EPSG:4326").to_crs(epsg)
        nul.extend(pts.distance(union).tolist())
    obs, nul = np.array(obs), np.array(nul)
    print(f"\n{'d (m)':>7s} {'PV within':>10s} {'random within':>14s} {'lift':>7s}")
    for m in (5, 10, 20, 30, 50, 100, 200):
        o, n = (obs <= m).mean(), (nul <= m).mean()
        print(f"{m:7d} {o:10.3f} {n:14.3f} {o/max(n, EPS):6.1f}x")


def cmd_searchspace(_args) -> None:
    """Share of national land within 20/30/50 m of a building, by cell density octile."""
    rng = np.random.default_rng(SEED)
    nat = pd.read_parquet(CELL_DENSITY)
    nat["oct"] = pd.qcut(nat.density, 8, labels=False)
    samp = nat.groupby("oct", group_keys=False).apply(
        lambda g: g.sample(min(6, len(g)), random_state=42))
    rows = []
    for r in samp.itertuples():
        tif = SEG_DIR / f"{r.cell}.tif"
        if not tif.exists():
            continue
        with rasterio.open(tif) as src:
            lon0, lat0, lon1, lat1 = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        bu = fetch_vida_buildings((lon0 - .006, lat0 - .006, lon1 + .006, lat1 + .006), "PAK")
        if bu.empty:
            rows.append({"oct": r.oct, "density": r.density, "f20": 0., "f30": 0., "f50": 0.})
            continue
        epsg = _utm(lon0, lat0)
        bu_u = bu.to_crs(epsg)
        pts = gpd.GeoSeries(gpd.points_from_xy(
            rng.uniform(lon0, lon1, 3000), rng.uniform(lat0, lat1, 3000)),
            crs="EPSG:4326").to_crs(epsg)
        d = pts.distance(bu_u.geometry.union_all()).to_numpy()
        rows.append({"oct": r.oct, "density": r.density, "f20": float((d <= 20).mean()),
                     "f30": float((d <= 30).mean()), "f50": float((d <= 50).mean())})
    d = pd.DataFrame(rows)
    print(d.groupby("oct").agg(n=("density", "size"), density=("density", "median"),
                               f20=("f20", "mean"), f30=("f30", "mean"),
                               f50=("f50", "mean")).round(3).to_string())
    w = nat.groupby("oct").size()
    per = d.groupby("oct").mean(numeric_only=True)
    for c in ("f20", "f30", "f50"):
        tot = float((per[c] * w.reindex(per.index)).sum() / w.reindex(per.index).sum())
        print(f"national land within {c[1:]} m of a building: {tot:.3f} "
              f"({1/max(tot, EPS):.1f}x search-space cut)")


# --------------------------------------------------------------------------------------
def cmd_parcels(_args) -> None:
    """One row per in-boundary VIDA building: roof block, yard block, ground-mount label."""
    parts = []
    for stem in discover_quadrats(LABELS):
        name = quadrat_label(stem)
        boundary, pv = load_quadrat(stem, LABELS)
        minx, miny, maxx, maxy = boundary.bounds
        res = composite_index(str(COMPOSITES), layers=1).read_window((minx, miny, maxx, maxy))
        if res is None:
            print(f"{name}: no composite coverage, skipped")
            continue
        arr, transform, crs = res
        arr = arr.astype("float32")[: len(BAND_NAMES)] / REFL_SCALE
        h, w = arr.shape[-2:]
        px_m = abs(transform.a)

        bu = fetch_vida_buildings((minx - .01, miny - .01, maxx + .01, maxy + .01), "PAK")
        bnd_utm = gpd.GeoSeries([boundary], crs="EPSG:4326").to_crs(crs).iloc[0]
        bu_utm = bu.to_crs(crs).reset_index(drop=True)
        bu_utm = bu_utm[bu_utm.geometry.representative_point().within(bnd_utm).to_numpy()]
        bu_utm = bu_utm.reset_index(drop=True)
        n_b = len(bu_utm)
        if n_b == 0:
            continue

        valid = ~np.all(arr == COMPOSITE_FILL, axis=0)
        inbnd = rasterio.features.rasterize(
            [(bnd_utm, 1)], out_shape=(h, w), transform=transform, fill=0,
            dtype="uint8").astype(bool)
        probs = {}
        for lab, pdir in (("seg", SEG_DIR), ("frac", FRAC_DIR)):
            p = _raster_for(boundary.representative_point(), pdir)
            probs[lab] = (_read_prob(p, (minx, miny, maxx, maxy), crs, transform, (h, w))
                          if p is not None else np.zeros((h, w), "float32"))

        roof_means, _ = zonal_mean_max(bu_utm, arr, transform, nodata=COMPOSITE_FILL)
        roof_b = {k: roof_means[i] for i, k in enumerate(BAND_NAMES)}

        bid = rasterio.features.rasterize(
            ((g, i + 1) for i, g in enumerate(bu_utm.geometry)), out_shape=(h, w),
            transform=transform, fill=0, dtype="int32", all_touched=True)
        dist, (iy, ix) = ndimage.distance_transform_edt(
            bid == 0, sampling=px_m, return_indices=True)
        ring_id = np.where((bid == 0) & (dist <= RING_M) & valid & inbnd, bid[iy, ix], 0)
        flat = ring_id.ravel()
        counts = np.bincount(flat, minlength=n_b + 1)[1:]

        def zmean(a, _flat=flat, _c=counts, _n=n_b):
            s = np.bincount(_flat, weights=a.ravel().astype("float64"), minlength=_n + 1)[1:]
            with np.errstate(invalid="ignore", divide="ignore"):
                return np.where(_c > 0, s / np.maximum(_c, 1), np.nan)

        def zmax(a, _flat=flat, _c=counts, _n=n_b):
            m = np.full(_n + 1, -np.inf)
            np.maximum.at(m, _flat, a.ravel().astype("float64"))
            return np.where(_c > 0, m[1:], np.nan)

        yard_b = {k: zmean(arr[i]) for i, k in enumerate(BAND_NAMES)}
        sppi_px = compute_sppi(arr[0], arr[1], arr[6], arr[8], arr[9])
        out = pd.DataFrame({
            "quadrat": name,
            "roof_area_m2": bu_utm["area_m2"].to_numpy(float),
            "bf_confidence": bu_utm.get(
                "bf_confidence", pd.Series(np.nan, index=bu_utm.index)).to_numpy(),
            "yard_px": counts, "yard_area_m2": counts * px_m * px_m,
            **_derived(roof_b, "roof_"), **_derived(yard_b, "yard_"),
        })
        for k, v in shape_features(bu_utm.geometry).items():
            out[f"roof_{k}"] = v
        rs, rsx = zonal_mean_max(bu_utm, probs["seg"], transform)
        rf, rfx = zonal_mean_max(bu_utm, probs["frac"], transform)
        out["roof_seg"], out["roof_seg_max"] = rs[0], rsx[0]
        out["roof_frac"], out["roof_frac_max"] = rf[0], rfx[0]
        out["roof_sppi_max"] = zonal_mean_max(bu_utm, sppi_px, transform)[1][0]
        out["yard_seg"], out["yard_seg_max"] = zmean(probs["seg"]), zmax(probs["seg"])
        out["yard_frac"], out["yard_frac_max"] = zmean(probs["frac"]), zmax(probs["frac"])
        out["yard_sppi_max"] = zmax(sppi_px)

        y = np.zeros(n_b)
        y_area = np.zeros(n_b)
        y_roof = np.zeros(n_b)
        if not pv.empty:
            pv = pv.copy()
            pv["area_m2"] = [geodesic_area_m2(g) for g in pv.geometry]
            pvu = pv.to_crs(crs)
            sidx = bu_utm.sindex
            for i, g in enumerate(pvu.geometry):
                for hh in sidx.query(g, predicate="intersects"):
                    y_roof[hh] += g.intersection(bu_utm.geometry.iloc[hh]).area
            strict = np.flatnonzero(_strict_ground(pv, bu_utm)
                                    & (pv.area_m2.to_numpy() < MAX_GM_AREA))
            if len(strict):
                gm = pvu.geometry.iloc[strict]
                nb = sidx.nearest(gm, return_all=False)[1]
                for j, k in enumerate(strict):
                    if gm.iloc[j].distance(bu_utm.geometry.iloc[nb[j]]) <= RING_M:
                        y[nb[j]] = 1
                        y_area[nb[j]] += float(pv.area_m2.iloc[k])
        out["has_gm"], out["gm_area_m2"], out["roof_pv_area_m2"] = y, y_area, y_roof
        keep = np.isfinite(out[[f"roof_{k}" for k in BAND_NAMES]].to_numpy()).all(axis=1)
        parts.append(out[keep].reset_index(drop=True))
        print(f"{name:26s} bldgs {int(keep.sum()):6d}  ground-mount yards "
              f"{int(y.sum()):4d}  with yard pixels {100*(counts>0).mean():3.0f}%", flush=True)

    df = pd.concat(parts, ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / "parcels.parquet")
    print(f"\nwrote {OUT/'parcels.parquet'} {df.shape}, {int(df.has_gm.sum())} positives, "
          f"base rate {df.has_gm.mean():.5f}")


# --------------------------------------------------------------------------------------
def _loqo(df: pd.DataFrame, feats: list[str], label: str) -> np.ndarray:
    X = df[feats].to_numpy(float)
    X = np.where(np.isfinite(X), X, np.nanmedian(X, axis=0))
    X = (X - X.mean(0)) / (X.std(0) + EPS)
    y = df[label].to_numpy(float)
    oof = np.full(len(df), np.nan)
    q = df.quadrat.to_numpy()
    for qq in np.unique(q):
        te = q == qq
        if y[~te].sum() < 5:
            continue
        oof[te] = predict_proba(fit_logistic(X[~te], y[~te], l2=1.0), X[te])
    return oof


def _wauc(df: pd.DataFrame, score, label: str) -> float:
    """Per-quadrat AUC averaged, weighted by positives. Never pooled: a quadrat's own
    reflectance level must not be what does the discriminating."""
    d = df.assign(_s=score)
    num = den = 0.0
    for _, g in d.groupby("quadrat"):
        if g[label].sum() == 0 or (1 - g[label]).sum() == 0:
            continue
        v = auc(g[label].to_numpy(), g["_s"].to_numpy())
        if np.isfinite(v):
            num += v * g[label].sum()
            den += g[label].sum()
    return num / den if den else float("nan")


def _pr(df: pd.DataFrame, score, label: str) -> dict:
    y = df[label].to_numpy(bool)
    s = np.asarray(score, float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    y = y[np.argsort(-s)]
    prec = np.cumsum(y) / np.arange(1, len(y) + 1)
    rec = np.cumsum(y) / max(y.sum(), 1)
    return {f"P@R{int(r*100)}": float(prec[min(np.searchsorted(rec, r), len(prec) - 1)])
            for r in (0.3, 0.5, 0.7)}


def cmd_evaluate(_args) -> None:
    df = pd.read_parquet(OUT / "parcels.parquet")
    df["log_roof_area"] = np.log10(df.roof_area_m2.clip(lower=1.0))
    df["log_yard_area"] = np.log10(df.yard_area_m2.clip(lower=1.0))
    df["has_yard"] = (df.yard_px > 0).astype(float)

    roof = (["log_roof_area", "bf_confidence"] + [f"roof_{b}" for b in BAND_NAMES]
            + [f"roof_{d}" for d in DERIV])
    yard = ([f"yard_{b}" for b in BAND_NAMES] + [f"yard_{d}" for d in DERIV]
            + ["yard_sppi_max", "log_yard_area", "has_yard"])
    blocks = {"roof only (= roofclf today)": roof, "yard only": yard,
              "roof + yard": roof + yard,
              "roof + yard + prob rasters": roof + yard + [
                  "yard_frac", "yard_frac_max", "yard_seg_max",
                  "roof_frac", "roof_frac_max", "roof_seg_max"]}

    # Per-quadrat in-boundary density, so the rural stratum can be reported separately: it
    # is the one that dominates the national building population and the one where an
    # instrument would have to earn its keep.
    dens = df.groupby("quadrat").size() / _quadrat_area_km2(df)
    low = dens[dens < 600].index
    for sname, sub in (("all quadrats", df),
                       ("no rooftop PV on the building", df[df.roof_pv_area_m2 == 0]),
                       ("quadrats under 600 bldg/km2", df[df.quadrat.isin(low)])):
        print(f"\n=== {sname}: {len(sub):,} buildings, {int(sub.has_gm.sum())} positives, "
              f"base rate {sub.has_gm.mean():.5f}")
        for bname, feats in blocks.items():
            s = _loqo(sub, feats, "has_gm")
            print(f"  {bname:30s} AUC {_wauc(sub, s, 'has_gm'):.3f}   "
                  + "  ".join(f"{k} {v:.3f}" for k, v in _pr(sub, s, "has_gm").items()))

    _capacity_scale(df, dens)


def _quadrat_area_km2(df: pd.DataFrame) -> pd.Series:
    """Quadrat areas in km2, read back from the boundary files."""
    out = {}
    for stem in discover_quadrats(LABELS):
        name = quadrat_label(stem)
        if name not in set(df.quadrat):
            continue
        b, _ = load_quadrat(stem, LABELS)
        c = b.centroid
        out[name] = gpd.GeoSeries([b], crs="EPSG:4326").to_crs(_utm(c.x, c.y)).iloc[0].area / 1e6
    return pd.Series(out)


def _capacity_scale(df: pd.DataFrame, dens: pd.Series) -> None:
    """Size the gap as a RATIO to the rooftop population, stratified by building density.

    An absolute per-building rate must not be used here. These quadrats' own rooftop PV area
    is 14,846 m2 per 1,000 buildings, which extrapolated over the national building count
    would read 202 GWp against the atlas's actual 7,890 MWp for the same sub-400 m2 rooftop
    population -- a 26x overstatement, and precisely the documented "ranking transfers across
    quadrats, absolute adoption rates do not" trap. The within-quadrat ratio does transfer,
    re-weighted onto the national building population by density stratum, which is the same
    stratification `sub400_capacity.coverage_ratio_by_size_and_density` uses.
    """
    SUB400_ROOFTOP_MWP = 7890.2
    BINS, LBL = [0, 150, 600, 2000, 1e9], ["<150", "150-600", "600-2000", ">=2000"]
    nat = pd.read_parquet(CELL_DENSITY)
    nat["stratum"] = pd.cut(nat.density, BINS, labels=LBL)
    share = nat.groupby("stratum", observed=True).n_buildings.sum()
    share = share / share.sum()

    q = df.groupby("quadrat").agg(roof_pv=("roof_pv_area_m2", "sum"),
                                  gm_pv=("gm_area_m2", "sum"))
    q["stratum"] = pd.cut(dens.reindex(q.index), BINS, labels=LBL)
    st = q.groupby("stratum", observed=True).agg(
        n_quadrats=("roof_pv", "size"), roof_pv=("roof_pv", "sum"), gm_pv=("gm_pv", "sum"))
    st["ratio"] = st.gm_pv / st.roof_pv
    st["nat_share"] = share.reindex(st.index)
    print("\n=== sub-400 m2 ground-mount PV as a share of rooftop PV area, by density ===")
    print(st.round(4).to_string())

    pooled = q.gm_pv.sum() / q.roof_pv.sum()
    strat = float((st.ratio * st.nat_share).sum() / st.nat_share.sum())
    print(f"\npooled ratio {pooled:.4f} -> {SUB400_ROOFTOP_MWP*pooled:,.0f} MWp")
    print(f"density-weighted ratio {strat:.4f} -> {SUB400_ROOFTOP_MWP*strat:,.0f} MWp")
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(3000):
        p = rng.choice(q.index.to_numpy(), len(q), replace=True)
        s = q.loc[p].groupby("stratum", observed=True).agg(r=("roof_pv", "sum"),
                                                           g=("gm_pv", "sum"))
        ns = st.nat_share.reindex(s.index).fillna(0.0)
        if ns.sum() == 0:
            continue
        draws.append(SUB400_ROOFTOP_MWP * float(((s.g / s.r) * ns).sum() / ns.sum()))
    print(f"  quadrat-bootstrap 90% CI {np.percentile(draws, 5):,.0f} - "
          f"{np.percentile(draws, 95):,.0f} MWp")
    print(f"\nconversion uses the module constant {DEFAULT_KWP_PER_M2_MODULE}; at the "
          f"ground-mount land constant {DEFAULT_KWP_PER_M2_LAND} every figure above would "
          f"read {DEFAULT_KWP_PER_M2_MODULE/DEFAULT_KWP_PER_M2_LAND:.1f}x lower, which is "
          f"why the constant choice is not a detail")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("census", cmd_census), ("national", cmd_national),
                     ("searchspace", cmd_searchspace), ("parcels", cmd_parcels),
                     ("evaluate", cmd_evaluate)):
        sub.add_parser(name).set_defaults(fn=fn)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
