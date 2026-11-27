#!/usr/bin/env python
"""Out-of-sample sensitivity check: do OSM-mapped small PV roofs outside the calibration
areas score like the quadrat PV roofs that price them?

Rerun after every roofclf refit or national rescoring, and after every national OSM pull.

**What it validates.** roofclf's score on roofs that carry PV, i.e. the sensitivity half of
the pricing. The probability-weighted area recall (`sub400_capacity.area_recall_by_size_and_
density`) assumes PV roofs in national cells score like PV roofs in the quadrats. Every
mapped installation outside a calibration area is a PV roof the fit never saw. Compared
within array-size bins (PV area on the roof), so the mappers' size mix drops out.

**What it cannot validate, by construction.** Two things, so don't read them from here:
1. *The level.* About half the quadrat score mass sits on PV-free roofs
   ([`roofclf_level_review.py`] measures that). A positive-only set holds no PV-free roof,
   and outside a complete area "unmapped" does not mean "no PV".
2. *Fill per PV roof and the coverage ratio.* What got mapped is selected (near segmentation
   leads, larger arrays), so the mapped share of a PV roof reads 1.2-1.3x the pricing
   quadrats' (2026-11-27; a roof-only exploratory read on 2026-11-07 gave 1.4-2.5x).
   `selection.csv` prints that diagnostic so it stays visible. It is not a check.

**Mapping followed segmentation leads**, then area screening and occasional finds (owner,
2026-11-07). Segmentation and roofclf read the same composite, so arrays found through a
segmentation lead score higher than a typical PV roof of the same size. Keeping only arrays
far from any lead does not fix that, because it keeps the faint ones. So every PV roof, on
both sides, is tagged `seg_near` (within `--lead-radius-m` of any segmentation candidate or
lead file on disk). The national rate is compared within each stratum, and post-stratified to
the quadrats' own `seg_near` share per size bin. The quadrats are completely mapped, so their
share is what a PV roof looks like.

**Arrays mapped from roofclf's own leads** (`build_small_pv_josm_leads.py`, first handed out
2026-08-01) are circular for this check. Dropping them biases the rate down and keeping them
biases it up, so both are reported: `excl_roofclf_leads` and `incl_roofclf_leads`. A roof
counts as roofclf-led if it lies within `--lead-radius-m` of such a lead and its OSM array
was last edited on or after `--roofclf-leads-date`. OSM keeps only the last edit, so an older
array edited later is counted as roofclf-led, which is conservative.

**Label.** The production parcel label, built by the same functions on both sides: the roof
term (`roofclf.roof_pv_area`) plus off-roof PV within `YARD_RING_M` of its nearest building
(`roofclf.parcel_pv_area`). Kept: roofs with 0 < PV < 400 m2 that touch no mapped array of
400 m2 or more. National roofs inside any registered calibration area are dropped, as are
cells outside the density domain.

**Uncertainty.** Cluster bootstrap: national cells and quadrats are resampled jointly.

    pixi run python scripts/roofclf_osm_positive_check.py --aoi pakistan \\
        --osm-solar data/labels/pakistan_overpass_solar.parquet
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Lead/PV proximity buffers in degrees are deliberate (a ~40 m candidate pre-filter).
warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")

ARRAY_BINS = (0.0, 25.0, 50.0, 100.0, 200.0, 400.0)
ROOF_BINS = (0.0, 100.0, 200.0, 400.0, 1000.0, np.inf)
SIZE_FLOOR_M2 = 400.0
MIN_STRATUM_N = 20       # national PV roofs per (bin, seg stratum) before it is used
NEAR_PV_DEG = 0.0004     # ~37-44 m at Pakistan's latitudes, > YARD_RING_M
N_BOOT = 1000
DEFAULT_SEED = 20261107
TOLERANCE = 0.05
# Declared 2026-11-07 after the first exploratory run (scratch, same day), so it governs
# reruns, not that run. Status stays "proposed" until the owner confirms it.
RULE = {
    "statistic": "d = post-stratified national mean p - quadrat mean p, per array-size bin, "
                 "on PV roofs (mean p is what probability-weighted pricing uses; the flag "
                 "rate at the deployment threshold is reported beside it)",
    "consistent": f"the 90% interval of d contains 0, or |d| <= {TOLERANCE}",
    "evaluated": f"bins where every seg stratum the quadrats populate holds >= {MIN_STRATUM_N} "
                 "national PV roofs",
    "transfers": "every evaluated bin consistent, in both roofclf-lead variants",
    "mixed": "consistent in one roofclf-lead variant only: the roofclf-led arrays decide it",
    "check": "some evaluated bin inconsistent in both variants: the sensitivity the national "
             "pricing assumes does not hold there",
    "status": "proposed 2026-11-07 -- confirm before relying on it",
}
DEFAULT_SEG_LEADS = (
    "data/predictions/{aoi}/candidates.parquet",
    "data/predictions/{aoi}/candidates_PRE_*.parquet",
    "data/predictions/{aoi}/{aoi}_pv_new_leads*.geojson",
    "results/{aoi}_pv_new_leads*.geojson",
    "results/{aoi}_v*_leads_*/{aoi}_v*_new_leads.geojson",
)
DEFAULT_ROOFCLF_LEADS = ("results/{aoi}_small_pv_josm_leads*.geojson",)


def utm_epsg(lon: float, lat: float) -> int:
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1


def load_leads(patterns, aoi: str):
    """Union of every lead/candidate polygon matched by `patterns`, EPSG:4326."""
    import geopandas as gpd

    files = sorted({f for p in patterns for f in glob.glob(str(ROOT / p.format(aoi=aoi)))})
    parts = []
    for f in files:
        g = gpd.read_parquet(f) if f.endswith(".parquet") else gpd.read_file(f)
        parts.append(g.to_crs(4326)[["geometry"]])
    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs=4326), []
    return (gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326),
            [str(Path(f).relative_to(ROOT)) for f in files])


def near(geoms_utm, leads, radius_m: float) -> np.ndarray:
    """True where a geometry lies within `radius_m` of any lead (both in one UTM CRS)."""
    if len(leads) == 0 or len(geoms_utm) == 0:
        return np.zeros(len(geoms_utm), bool)
    hit = leads.sindex.query(geoms_utm.buffer(radius_m).to_numpy(), predicate="intersects")[0]
    out = np.zeros(len(geoms_utm), bool)
    out[np.unique(hit)] = True
    return out


def _valid(gdf):
    """Invalid VIDA/OSM polygons (self-touching rings) repaired by a zero buffer, so GEOS set
    operations do not raise; valid geometries are passed through untouched."""
    bad = ~gdf.geometry.is_valid.to_numpy()
    if bad.any():
        gdf = gdf.copy()
        gdf.loc[gdf.index[bad], "geometry"] = gdf.geometry[bad].buffer(0)
    return gdf


def parcel_label(bu, pv):
    """Production parcel label (roof term + off-roof yard terms) for footprints `bu` and
    PV polygons `pv`, both EPSG:4326, and whether each roof touches a >= 400 m2 array."""
    from earthpv.roofclf import parcel_pv_area, roof_pv_area

    bu, pv = _valid(bu), _valid(pv)
    c = bu.geometry.union_all().centroid
    bu_utm = bu.to_crs(utm_epsg(c.x, c.y))
    roof = roof_pv_area(bu, pv)
    ground, overhang, _ = parcel_pv_area(bu, bu_utm, pv)
    big = pv[pv["area_m2"] >= SIZE_FLOOR_M2]
    touch = np.zeros(len(bu), bool)
    if len(big):
        hit = big.sindex.query(bu.geometry.to_numpy(), predicate="intersects")[0]
        touch[np.unique(hit)] = True
    return roof + ground + overhang, touch, bu_utm


def national_positives(args, osm, exclusion, seg, rcl, bands) -> tuple[pd.DataFrame, dict]:
    import geopandas as gpd

    from earthpv.density import calibrated_density_range

    lo, hi = calibrated_density_range(args.aoi)
    grid = gpd.read_parquet(args.grid, columns=["cell", "geometry"])
    dens = pd.read_parquet(args.cell_density)[["cell", "density"]]
    grid = grid.merge(dens, on="cell", how="left")
    small = osm[(osm["area_m2"] < SIZE_FLOOR_M2) & (osm["placement"].fillna("") != "ground")
                & osm.geom_type.isin(["Polygon", "MultiPolygon"])]
    if exclusion is not None:
        small = small[~small.geometry.representative_point().within(exclusion)]
    pts = gpd.GeoDataFrame(geometry=small.geometry.representative_point(), crs=4326)
    cells = gpd.sjoin(pts, grid, predicate="within", how="inner")["cell"].unique()
    in_dom = grid[grid.cell.isin(cells) & grid.density.between(lo, hi)]
    notes = {"small_rooftop_arrays_outside_calibration": int(len(small)),
             "cells_with_arrays": int(len(cells)), "cells_in_domain": int(len(in_dom)),
             "density_domain_bldg_km2": [lo, hi]}
    rows = []
    for r in in_dom.itertuples():
        p = args.roofclf_dir / f"{r.cell}.parquet"
        if not p.exists():
            continue
        cell_pv = osm.iloc[osm.sindex.query(r.geometry, predicate="intersects")]
        cell_pv = cell_pv[cell_pv.geom_type.isin(["Polygon", "MultiPolygon"])]
        if cell_pv.empty:
            continue
        bu = gpd.read_parquet(p, columns=["geometry", "roof_area_m2", "p_roofclf"])
        bu = bu[bu["p_roofclf"].notna()].reset_index(drop=True)
        # Only footprints within ~40 m of mapped PV can carry a label (the yard ring is
        # 20 m), and passing a whole city cell makes roof_pv_area's ground guard union
        # 300k footprints per large array. The label is identical on this subset.
        near_pv = np.unique(bu.sindex.query(cell_pv.geometry.buffer(NEAR_PV_DEG).to_numpy(),
                                            predicate="intersects")[1])
        bu = bu.iloc[near_pv].reset_index(drop=True)
        if bu.empty:
            continue
        pv_true, touch_big, bu_utm = parcel_label(bu, cell_pv)
        keep = (pv_true > 0) & (pv_true < SIZE_FLOOR_M2) & ~touch_big
        if exclusion is not None:
            keep &= ~bu.geometry.representative_point().within(exclusion).to_numpy()
        idx = np.flatnonzero(keep)
        if not len(idx):
            continue
        sel_utm = bu_utm.geometry.iloc[idx]
        crs = bu_utm.crs
        seg_l = seg.iloc[seg.sindex.query(r.geometry.buffer(0.01), predicate="intersects")].to_crs(crs)
        rcl_l = rcl.iloc[rcl.sindex.query(r.geometry.buffer(0.01), predicate="intersects")].to_crs(crs)
        # Last edit of the arrays on each roof: roofclf leads only count after they existed.
        arr = cell_pv[cell_pv["area_m2"] < SIZE_FLOOR_M2].to_crs(crs)
        ts = pd.to_datetime(arr["osm_timestamp"], errors="coerce", utc=True).reset_index(drop=True)
        hit_r, hit_a = arr.sindex.query(sel_utm.buffer(1.0).to_numpy(), predicate="intersects")
        last = ts.iloc[hit_a].groupby(hit_r).max()
        last_edit = pd.Series(pd.NaT, index=range(len(idx)), dtype=ts.dtype)
        last_edit.loc[last.index] = last.to_numpy()
        led = near(sel_utm, rcl_l, args.lead_radius_m) & (
            last_edit >= pd.Timestamp(args.roofclf_leads_date, tz="UTC")).to_numpy()
        band = "lower" if r.density < bands["edge"] else "upper"
        rows.append(pd.DataFrame({
            "cell": r.cell, "density": r.density, "band": band,
            "roof_area_m2": bu["roof_area_m2"].to_numpy()[idx], "pv_m2": pv_true[idx],
            "p": bu["p_roofclf"].to_numpy()[idx],
            "seg_near": near(sel_utm, seg_l, args.lead_radius_m),
            "roofclf_led": led, "last_edit": last_edit.to_numpy(),
            "lon": bu.geometry.iloc[idx].representative_point().x.to_numpy(),
            "lat": bu.geometry.iloc[idx].representative_point().y.to_numpy()}))
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    notes["pv_roofs"] = int(len(out))
    return out, notes


def quadrat_positives(args, bands, seg) -> pd.DataFrame:
    import geopandas as gpd

    from earthpv.roofclf import discover_quadrats, load_quadrat, quadrat_label

    b = gpd.read_parquet(args.model_dir / "buildings.geoparquet",
                         columns=["quadrat", "geometry", "roof_area_m2", "pv_area_true_m2", "p_oof"])
    stems = {quadrat_label(s): s for s in discover_quadrats(args.labels_dir)}
    rows = []
    for band, quads in (("lower", bands["lower"]), ("upper", bands["upper"])):
        for q in quads:
            if q not in stems:
                raise SystemExit(f"pricing quadrat {q!r} has no registered boundary in "
                                 f"{args.labels_dir}")
            bu = b[b["quadrat"] == q].reset_index(drop=True)
            pv = bu["pv_area_true_m2"].to_numpy(float)
            _, qpv = load_quadrat(stems[q], args.labels_dir)
            qpv = qpv.to_crs(4326)
            if "area_m2" not in qpv.columns:
                from earthpv.labels import geodesic_area_m2
                qpv["area_m2"] = [geodesic_area_m2(g) for g in qpv.geometry]
            big = qpv[qpv["area_m2"] >= SIZE_FLOOR_M2]
            touch = np.zeros(len(bu), bool)
            if len(big):
                touch[np.unique(big.sindex.query(bu.geometry.to_numpy(), predicate="intersects")[0])] = True
            keep = (pv > 0) & (pv < SIZE_FLOOR_M2) & ~touch
            idx = np.flatnonzero(keep)
            c = bu.geometry.union_all().centroid
            crs = utm_epsg(c.x, c.y)
            sel = bu.iloc[idx].to_crs(crs).geometry
            # Preselect leads near the area by its buffered bounding box, a superset of the
            # buffered footprint union; `near` then applies the real radius. Buffering the
            # union of an area's 4-14k footprints by 0.01 deg took >10 GB (2026-11-27).
            from shapely.geometry import box
            seg_l = seg.iloc[seg.sindex.query(box(*bu.total_bounds).buffer(0.01),
                                              predicate="intersects")].to_crs(crs)
            rows.append(pd.DataFrame({
                "quadrat": q, "band": band, "roof_area_m2": bu["roof_area_m2"].to_numpy()[idx],
                "pv_m2": pv[idx], "p": bu["p_oof"].to_numpy()[idx],
                "seg_near": near(sel, seg_l, args.lead_radius_m)}))
    return pd.concat(rows, ignore_index=True)


def _keys(df: pd.DataFrame, thr: float) -> pd.DataFrame:
    d = pd.concat([df, df.assign(band="all")], ignore_index=True)
    d["abin"] = pd.cut(d["pv_m2"], ARRAY_BINS, labels=False, include_lowest=True)
    d["flag"] = (d["p"] >= thr).astype(float)
    return d


def _cluster_sums(d, cluster, key_index):
    """(clusters x keys) arrays of n, sum p and sum flag for one side."""
    clusters = pd.Index(sorted(d[cluster].unique()))
    ci = clusters.get_indexer(d[cluster])
    ki = key_index.get_indexer(pd.MultiIndex.from_frame(d[["band", "abin", "seg_near"]]))
    shape = (len(clusters), len(key_index))
    out = []
    for w in (np.ones(len(d)), d["p"].to_numpy(), d["flag"].to_numpy()):
        a = np.zeros(shape)
        np.add.at(a, (ci, ki), w)
        out.append(a)
    return out


def compare(nat: pd.DataFrame, quad: pd.DataFrame, thr: float, seed: int, n_boot: int) -> pd.DataFrame:
    n_d, q_d = _keys(nat, thr), _keys(quad, thr)
    key_index = pd.MultiIndex.from_product(
        [["lower", "upper", "all"], range(len(ARRAY_BINS) - 1), [False, True]],
        names=["band", "abin", "seg_near"])
    N = _cluster_sums(n_d, "cell", key_index)
    Q = _cluster_sums(q_d, "quadrat", key_index)
    rng = np.random.default_rng(seed)
    mN = np.vstack([np.ones(N[0].shape[0])] + [
        np.bincount(rng.integers(0, N[0].shape[0], N[0].shape[0]), minlength=N[0].shape[0])
        for _ in range(n_boot)])
    mQ = np.vstack([np.ones(Q[0].shape[0])] + [
        np.bincount(rng.integers(0, Q[0].shape[0], Q[0].shape[0]), minlength=Q[0].shape[0])
        for _ in range(n_boot)])
    nN, pN, fN = (mN @ a for a in N)     # (1 + n_boot) x keys; row 0 is the point estimate
    nQ, pQ, fQ = (mQ @ a for a in Q)
    rows = []
    for band in ("lower", "upper", "all"):
        for b in range(len(ARRAY_BINS) - 1):
            k = [key_index.get_loc((band, b, s)) for s in (False, True)]
            nq = nQ[:, k]
            wq = nq / np.where(nq.sum(1, keepdims=True) > 0, nq.sum(1, keepdims=True), np.nan)
            n_nat = nN[0, k]
            used = nq[0] > 0
            evaluated = bool(used.any() and np.all(n_nat[used] >= MIN_STRATUM_N))
            row = {"band": band, "array_bin": f"{ARRAY_BINS[b]:g}-{ARRAY_BINS[b + 1]:g}",
                   "n_quadrat": int(nq[0].sum()), "n_national": int(n_nat.sum()),
                   "n_national_seg_near": int(n_nat[1]),
                   "quadrat_seg_near_share": round(float(wq[0, 1]), 3) if nq[0].sum() else None,
                   "national_seg_near_share": round(float(n_nat[1] / n_nat.sum()), 3)
                   if n_nat.sum() else None, "evaluated": evaluated}
            for metric, sN, sQ in (("mean_p", pN, pQ), ("flag", fN, fQ)):
                with np.errstate(invalid="ignore", divide="ignore"):
                    rq_s = sQ[:, k] / nq
                    rn_s = sN[:, k] / nN[:, k]
                    q_rate = sQ[:, k].sum(1) / nq.sum(1)
                    raw = sN[:, k].sum(1) / nN[:, k].sum(1)
                    adj = np.nansum(wq * np.where(nq > 0, rn_s, 0.0), axis=1)
                # A replicate whose resampled cells leave a populated stratum empty has no
                # post-stratified estimate; it is dropped, not filled with zero.
                empty = ((nq > 0) & ~(nN[:, k] > 0)).any(axis=1)
                adj = np.where(np.isfinite(q_rate) & ~empty, adj, np.nan)
                d = adj - q_rate
                row[f"{metric}_quadrat"] = _r(q_rate[0])
                row[f"{metric}_national_raw"] = _r(raw[0])
                row[f"{metric}_national_adj"] = _r(adj[0]) if evaluated else None
                row[f"{metric}_quadrat_far"], row[f"{metric}_national_far"] = _r(rq_s[0, 0]), _r(rn_s[0, 0])
                row[f"{metric}_quadrat_near"], row[f"{metric}_national_near"] = _r(rq_s[0, 1]), _r(rn_s[0, 1])
                if evaluated:
                    lo, hi = np.nanpercentile(d[1:], [5, 95])
                    row[f"{metric}_diff"] = _r(d[0])
                    row[f"{metric}_diff_ci90"] = [_r(lo), _r(hi)]
                    if metric == "mean_p":
                        row["consistent"] = bool(lo <= 0 <= hi or abs(d[0]) <= TOLERANCE)
            rows.append(row)
    return pd.DataFrame(rows)


def _r(x) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), 4)


def selection(nat: pd.DataFrame, quad: pd.DataFrame) -> pd.DataFrame:
    """Why fill and level cannot be read from the mapped set (diagnostic, not a check)."""
    rows = []
    for name, d in (("quadrats", quad), ("national_mapped", nat)):
        a = pd.cut(d["pv_m2"], ARRAY_BINS, include_lowest=True).value_counts(normalize=True, sort=False)
        f = (d["pv_m2"] / d["roof_area_m2"]).clip(upper=1)
        m = f.groupby(pd.cut(d["roof_area_m2"], ROOF_BINS), observed=False).median()
        rows += [{"side": name, "measure": "array_size_share", "bin": str(i), "value": round(v, 4)}
                 for i, v in a.items()]
        rows += [{"side": name, "measure": "median_fill_on_pv_roof", "bin": str(i),
                  "value": None if pd.isna(v) else round(float(v), 4)} for i, v in m.items()]
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--osm-solar", type=Path, default=None,
                    help="national OSM solar pull (default data/labels/<aoi>_overpass_solar.parquet)")
    ap.add_argument("--roofclf-dir", type=Path, default=None,
                    help="national scoring (default data/roofclf_national_with_sppi/<aoi>/prob)")
    ap.add_argument("--model-dir", type=Path, default=Path("data/roofclf"),
                    help="`roof-classifier` output: summary.json, buildings.geoparquet (p_oof)")
    ap.add_argument("--pricing-summary", type=Path, default=None,
                    help="sub400_central_summary.json: coverage-ratio density bands and their "
                         "quadrats (default data/roofclf_national_with_sppi/<aoi>/density/)")
    ap.add_argument("--grid", type=Path, default=None,
                    help="density grid (default data/predictions/<aoi>/density/grid.geoparquet)")
    ap.add_argument("--cell-density", type=Path, default=Path("data/roofclf/national_cell_density.parquet"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--seg-leads", nargs="+", default=list(DEFAULT_SEG_LEADS),
                    help="glob patterns ({aoi} expands) of segmentation candidate/lead files")
    ap.add_argument("--roofclf-leads", nargs="+", default=list(DEFAULT_ROOFCLF_LEADS),
                    help="glob patterns of roofclf/SPPI lead files handed to mappers")
    ap.add_argument("--roofclf-leads-date", default="2026-08-01",
                    help="first day roofclf leads were handed out")
    ap.add_argument("--lead-radius-m", type=float, default=30.0)
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="default results/<aoi>_roofclf_osm_positive_check/")
    args = ap.parse_args()
    aoi = args.aoi
    args.osm_solar = args.osm_solar or Path(f"data/labels/{aoi}_overpass_solar.parquet")
    args.roofclf_dir = args.roofclf_dir or Path(f"data/roofclf_national_with_sppi/{aoi}/prob")
    args.pricing_summary = args.pricing_summary or Path(
        f"data/roofclf_national_with_sppi/{aoi}/density/sub400_central_summary.json")
    args.grid = args.grid or Path(f"data/predictions/{aoi}/density/grid.geoparquet")
    args.out_dir = args.out_dir or Path("results") / f"{aoi}_roofclf_osm_positive_check"

    import geopandas as gpd
    from shapely.ops import unary_union

    from earthpv.roofclf import check_scoring_matches_calibration, discover_quadrats, load_boundary

    check_scoring_matches_calibration(args.roofclf_dir, args.model_dir)
    thr = float(json.loads((args.model_dir / "summary.json").read_text())["deployment_threshold"])
    fit = json.loads(args.pricing_summary.read_text())["calibration_coverage_ratio_by_size_and_density"]
    if len(fit["bands"]) != 2:
        raise SystemExit(f"expected two density bands in {args.pricing_summary}, got {len(fit['bands'])}")
    bands = {"edge": float(fit["band_edges"][1]), "lower": fit["bands"][0]["quadrats"],
             "upper": fit["bands"][1]["quadrats"]}
    stems = discover_quadrats(args.labels_dir)
    exclusion = unary_union([load_boundary(args.labels_dir / f"{s}_boundary.geojson")
                             for s in stems]) if stems else None
    seg, seg_files = load_leads(args.seg_leads, aoi)
    rcl, rcl_files = load_leads(args.roofclf_leads, aoi)
    osm = gpd.read_parquet(args.osm_solar).to_crs(4326)
    print(f"threshold {thr}; {len(stems)} calibration areas excluded; {len(seg):,} segmentation "
          f"lead polygons from {len(seg_files)} files; {len(rcl):,} roofclf lead polygons")

    nat, notes = national_positives(args, osm, exclusion, seg, rcl, bands)
    quad = quadrat_positives(args, bands, seg)
    print(f"national PV roofs {len(nat):,} ({int(nat.roofclf_led.sum())} roofclf-led); "
          f"quadrat PV roofs {len(quad):,}")

    tables, status = {}, {}
    for variant, d in (("excl_roofclf_leads", nat[~nat.roofclf_led]), ("incl_roofclf_leads", nat)):
        t = compare(d, quad, thr, args.seed, args.n_boot)
        t.insert(0, "variant", variant)
        tables[variant] = t
        ev = t[t.evaluated]
        status[variant] = {b: bool(ev[ev.band == b]["consistent"].all()) for b in ("lower", "upper", "all")}
    verdict = {}
    for b in ("lower", "upper", "all"):
        ok = [status[v][b] for v in status]
        verdict[b] = "transfers" if all(ok) else "mixed" if any(ok) else "check"

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    table = pd.concat(tables.values(), ignore_index=True)
    table.to_csv(out / "by_size.csv", index=False)
    selection(nat, quad).to_csv(out / "selection.csv", index=False)
    nat.to_parquet(out / "national_pv_roofs.parquet")
    quad.to_parquet(out / "quadrat_pv_roofs.parquet")
    osm_ts = pd.to_datetime(osm.get("osm_timestamp"), errors="coerce", utc=True)
    summary = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aoi": aoi, "osm_solar": str(args.osm_solar),
        "osm_newest_edit": str(osm_ts.max()) if osm_ts.notna().any() else None,
        "roofclf_dir": str(args.roofclf_dir), "model_dir": str(args.model_dir),
        "pricing_summary": str(args.pricing_summary), "deployment_threshold": thr,
        "band_edge_bldg_km2": bands["edge"], "quadrats": {"lower": bands["lower"], "upper": bands["upper"]},
        "calibration_areas_excluded": len(stems), "seg_lead_files": seg_files,
        "roofclf_lead_files": rcl_files, "roofclf_leads_date": args.roofclf_leads_date,
        "lead_radius_m": args.lead_radius_m, **notes,
        "national_pv_roofs_roofclf_led": int(nat.roofclf_led.sum()),
        "quadrat_pv_roofs": int(len(quad)), "n_boot": args.n_boot, "seed": args.seed,
        "rule": RULE, "verdict": verdict, "status_by_variant": status,
        "not_validated_here": "level (score mass on PV-free roofs) and fill per PV roof / "
                              "coverage ratio -- see the module docstring and selection.csv",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n")
    cols = ["variant", "band", "array_bin", "n_quadrat", "n_national", "quadrat_seg_near_share",
            "national_seg_near_share", "mean_p_quadrat", "mean_p_national_raw", "mean_p_national_adj",
            "mean_p_diff", "mean_p_diff_ci90", "flag_quadrat", "flag_national_adj", "consistent"]
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(table[[c for c in cols if c in table.columns]].to_string(index=False))
    print(f"verdict: {verdict}  (rule status: {RULE['status']})")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
