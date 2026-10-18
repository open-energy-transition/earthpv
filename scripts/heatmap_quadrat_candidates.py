"""Candidate calibration quadrats from a mapped-solar heatmap (OpenInfraMap-style).

**What it does.** OpenInfraMap's solar layer is a density rendering of the OpenStreetMap
`generator:source=solar` features this pipeline already pulls. This builds the same
heatmap from those features directly (no tiles are scraped), normalises it by the VIDA
building count of each box, and ranks boxes as places where a quadrat might already be
close to Rule-1 complete -- every visible installation mapped -- so a mapper confirms
what is there instead of mapping a box from scratch.

**What it cannot do, and why the output is a candidate list.** A heatmap shows where
installations HAVE been mapped. It cannot show the ones nobody mapped, which is exactly
what Rule-1 certifies. Mapped density is completeness times adoption: a box can be bright
because mappers were thorough or because there is simply a lot of PV and a tenth of it is
mapped. Normalising by buildings removes building density, not adoption. So every
candidate still needs the protocol's imagery sweep (and its imagery-date check, see
CLAUDE.md "Calibration quadrats") before `scripts/new_calibration_quadrat.py` registers
it. `--validate-mastr` (Germany) measures how far the heatmap tracks completeness rather
than adoption, against the register's per-municipality unit counts.

A second bias to keep in view: selecting quadrats where mapping is dense selects for
mapper attention, which is not random. The calibration already carries a purposive-
sampling caveat; this does not remove it. Use `--per-band` to surface candidates in every
building-density band, since the sparse bands are where a quadrat widens the calibrated
domain (CLAUDE.md, "Density stage").

    python scripts/heatmap_quadrat_candidates.py --aoi germany --iso3 DEU \\
        --osm-solar data/labels/germany_national_osm_solar.parquet --validate-mastr

Writes results/<aoi>_quadrat_candidates/{boxes.parquet, candidates.geojson,
candidates.csv} and, with --validate-mastr, mastr_validation.json. Nothing is written
under data/labels/, so no candidate can reach a roofclf refit by accident.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

FLOOR_M2 = 400.0  # small PV: below the segmentation floor, what quadrats calibrate
OIM_LAYERS = "A,B,L,P,S"  # OpenInfraMap layer string, solar included, for review links


def _building_points(vida_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Lon/lat of every VIDA footprint from its bbox column (no geometry decode)."""
    import duckdb

    con = duckdb.connect()
    con.execute("SET parquet_metadata_cache=true;")
    arr = con.execute(
        f"SELECT (bbox.xmin + bbox.xmax) / 2 AS lon, (bbox.ymin + bbox.ymax) / 2 AS lat "
        f"FROM read_parquet('{vida_path}')"
    ).fetchnumpy()
    return arr["lon"].astype("float64"), arr["lat"].astype("float64")


def _small_pv(osm):
    """Rooftop or unclassified features below the 400 m2 floor, plus point features
    (a mapped generator node carries no area and is almost always a small array)."""
    pts = osm.geom_type == "Point"
    area = osm["area_m2"].fillna(0.0) if "area_m2" in osm.columns else 0.0
    keep = (osm["placement"] != "ground") & (pts | (area < FLOOR_M2))
    return osm[keep]


def _installations(small, crs, merge_m: float):
    """One point per mapped installation. Some mappers draw every panel row as its own
    polygon, which makes a box bright for convention rather than coverage; polygons
    within `merge_m` of each other are merged first (earliest edit kept as the epoch).
    Point features are kept as they are."""
    import geopandas as gpd

    if merge_m <= 0:
        return small
    pts = small[small.geom_type == "Point"]
    poly = small[small.geom_type != "Point"].to_crs(crs)
    if poly.empty:
        return small
    merged = gpd.GeoDataFrame(geometry=[poly.buffer(merge_m).union_all()], crs=crs).explode(
        index_parts=False).reset_index(drop=True)
    j = gpd.sjoin(poly[["osm_timestamp", "geometry"]] if "osm_timestamp" in poly.columns
                  else poly[["geometry"]], merged, predicate="intersects", how="inner")
    agg = j.groupby("index_right")["osm_timestamp"].min() if "osm_timestamp" in j.columns \
        else None
    merged["osm_timestamp"] = agg.reindex(merged.index).values if agg is not None else None
    merged["geometry"] = merged.geometry.buffer(-merge_m)
    merged = merged[~merged.geometry.is_empty].to_crs(small.crs)
    return pd.concat([pts[["osm_timestamp", "geometry"]] if "osm_timestamp" in pts.columns
                      else pts[["geometry"]], merged], ignore_index=True)


def mapped_pv_heatmap(osm, bldg_lon, bldg_lat, crs, box_m: float,
                      merge_m: float = 1.0) -> pd.DataFrame:
    """One row per box with at least one building: small mapped PV installations per
    1,000 buildings and the mapping epoch of what is in it."""
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    bx, by = tf.transform(bldg_lon, bldg_lat)
    bi = np.floor(np.asarray(bx) / box_m).astype("int64")
    bj = np.floor(np.asarray(by) / box_m).astype("int64")
    # One int64 key per box: np.unique over a 2 x 28M array with axis=1 is a lexsort of
    # structured rows and several times slower and larger.
    i0, j0 = bi.min(), bj.min()
    span = int(bj.max() - j0 + 1)
    keys, nb = np.unique((bi - i0) * span + (bj - j0), return_counts=True)
    boxes = pd.DataFrame({"i": keys // span + i0, "j": keys % span + j0, "n_bldg": nb})

    small = _installations(_small_pv(osm), crs, merge_m)
    rp = small.geometry.representative_point()
    px, py = tf.transform(rp.x.values, rp.y.values)
    pv = pd.DataFrame({
        "i": np.floor(np.asarray(px) / box_m).astype("int64"),
        "j": np.floor(np.asarray(py) / box_m).astype("int64"),
        "ts": pd.to_datetime(small["osm_timestamp"], utc=True, errors="coerce").values
        if "osm_timestamp" in small.columns else pd.NaT,
    })
    agg = pv.groupby(["i", "j"]).agg(n_pv=("ts", "size"), ts_median=("ts", "median"),
                                      ts_min=("ts", "min"), ts_max=("ts", "max"))
    boxes = boxes.merge(agg.reset_index(), on=["i", "j"], how="left")
    boxes["n_pv"] = boxes["n_pv"].fillna(0).astype(int)
    km2 = (box_m / 1000.0) ** 2
    boxes["bldg_km2"] = boxes["n_bldg"] / km2
    boxes["pv_per_1k_bldg"] = 1000.0 * boxes["n_pv"] / boxes["n_bldg"]

    # Neighbourhood context. A box on the edge of one mapper's campaign is half mapped;
    # one inside a contiguous well-mapped area is the better bet. Median over the 8
    # neighbours that hold buildings at all.
    lut = boxes.set_index(["i", "j"])["pv_per_1k_bldg"]
    neigh = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di or dj:
                k = pd.MultiIndex.from_arrays([boxes["i"] + di, boxes["j"] + dj])
                neigh.append(lut.reindex(k).to_numpy())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # isolated boxes: all-NaN
        boxes["neighbour_pv_per_1k"] = np.nanmedian(np.vstack(neigh), axis=0)
    return boxes


def quadrat_candidates(boxes: pd.DataFrame, min_bldg: int, min_pv: int, top: int,
                       per_band: bool, min_interior: float, box_m: float,
                       min_spacing_km: float = 10.0) -> pd.DataFrame:
    """Rank boxes by mapped small PV per building. With `per_band`, the top `top` of each
    decade of building density, so sparse candidates are not crowded out by city ones.
    A box within `min_spacing_km` of a better one is dropped: one mapper's campaign
    otherwise fills the whole list with its own neighbouring boxes."""
    c = boxes[(boxes.n_bldg >= min_bldg) & (boxes.n_pv >= min_pv)].copy()
    c["interior"] = (c["neighbour_pv_per_1k"] / c["pv_per_1k_bldg"]).clip(upper=1.0)
    c = c[c["interior"].fillna(0) >= min_interior]
    c["density_band"] = np.floor(np.log10(c["bldg_km2"].clip(lower=1))).astype(int)
    c = c.sort_values("pv_per_1k_bldg", ascending=False)
    if min_spacing_km > 0:
        r = min_spacing_km * 1000.0 / box_m
        kept: list[tuple[int, int]] = []
        keep = []
        for i, j in zip(c["i"].to_numpy(), c["j"].to_numpy()):
            ok = all((i - a) ** 2 + (j - b) ** 2 >= r * r for a, b in kept)
            keep.append(ok)
            if ok:
                kept.append((i, j))
        c = c[np.array(keep, dtype=bool)]
    if per_band:
        c = c.groupby("density_band", group_keys=False).head(top)
    else:
        c = c.head(top)
    return c.sort_values(["density_band", "pv_per_1k_bldg"], ascending=[True, False])


def _box_polygons(df: pd.DataFrame, crs, box_m: float):
    import geopandas as gpd
    from shapely.geometry import box

    geoms = [box(i * box_m, j * box_m, (i + 1) * box_m, (j + 1) * box_m)
             for i, j in zip(df["i"], df["j"])]
    return gpd.GeoDataFrame(df.reset_index(drop=True), geometry=geoms, crs=crs).to_crs(4326)


def _existing_quadrats() -> "object | None":
    import geopandas as gpd

    # Hand-mapped quadrats only: Pakistan's (flat directory) and France's communes. The
    # germany_* directories hold register and OSM pseudo-quadrats, which nobody mapped.
    paths = sorted(REPO.glob("data/labels/*_calib_*_boundary.geojson")) + sorted(
        REPO.glob("data/labels/france/*_calib_*_boundary.geojson"))
    if not paths:
        return None
    return pd.concat([gpd.read_file(p).assign(quadrat=p.stem) for p in paths]).to_crs(4326)


def validate_against_mastr(boxes_gdf, osm, bldg_lon, bldg_lat, cand_gdf,
                          merge_m: float = 1.0) -> dict:
    """Does the heatmap track mapping COMPLETENESS or just ADOPTION? Germany only.

    Per municipality (VG250 Gemeinde, joined to MaStR on AGS): completeness = small mapped
    OSM features / registered rooftop units (by count, no area or kWp constant involved,
    the same measure as `mastr_validation.osm_completeness_by_count`), adoption =
    registered units / VIDA buildings, heat = mapped features / VIDA buildings, the
    heatmap's own metric. Heat is completeness x adoption by construction, so the
    question is which of the two it ranks on. Then: what completeness do the municipalities
    under the top candidate boxes actually have?"""
    import geopandas as gpd
    from scipy.stats import spearmanr

    gem = gpd.read_parquet(REPO / "data/calibration/vg250_gem.parquet")[["ags", "geometry"]]
    gem = gem.to_crs(4326)
    counts = pd.read_parquet(REPO / "data/calibration/mastr_rooftop_counts.parquet")

    # Municipality of every building point and every small mapped feature, by a 100 m
    # municipality raster rather than 28M point-in-polygon tests.
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from pyproj import Transformer

    crs = boxes_gdf.attrs["crs"]
    g = gem.to_crs(crs).reset_index(drop=True)
    x0, y0, x1, y1 = g.total_bounds
    res = 100.0
    w, h = int(np.ceil((x1 - x0) / res)), int(np.ceil((y1 - y0) / res))
    tr = from_origin(x0, y1, res, res)
    ras = rasterize(((geom, k + 1) for k, geom in enumerate(g.geometry)), out_shape=(h, w),
                    transform=tr, fill=0, dtype="int32")

    tf = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    def lookup(lon, lat):
        x, y = tf.transform(lon, lat)
        c = np.floor((np.asarray(x) - x0) / res).astype("int64")
        r = np.floor((y1 - np.asarray(y)) / res).astype("int64")
        ok = (c >= 0) & (c < w) & (r >= 0) & (r < h)
        out = np.zeros(len(c), dtype="int32")
        out[ok] = ras[r[ok], c[ok]]
        return out

    nb = np.bincount(lookup(bldg_lon, bldg_lat), minlength=len(g) + 1)[1:]
    small = _installations(_small_pv(osm), crs, merge_m)  # same count as the heatmap
    rp = small.geometry.representative_point()
    npv = np.bincount(lookup(rp.x.values, rp.y.values), minlength=len(g) + 1)[1:]
    m = pd.DataFrame({"ags": g["ags"].values, "n_bldg": nb, "osm_n": npv}).merge(
        counts[["ags", "n_rooftop_units"]], on="ags", how="inner")
    m["km2"] = g.set_index("ags").reindex(m["ags"]).geometry.area.values / 1e6
    m = m[(m.n_bldg >= 200) & (m.n_rooftop_units >= 30)]
    m["heat"] = 1000 * m.osm_n / m.n_bldg
    m["completeness"] = m.osm_n / m.n_rooftop_units
    m["adoption"] = 1000 * m.n_rooftop_units / m.n_bldg
    m["count_km2"] = m.osm_n / m.km2
    # Most municipalities have nothing mapped, so heat and completeness tie at zero
    # together and inflate any rank correlation; the informative test is over the rest.
    mm = m[m.osm_n >= 5]
    rho_c = spearmanr(m.heat, m.completeness).statistic
    rho_a = spearmanr(m.heat, m.adoption).statistic
    rho_c5 = spearmanr(mm.heat, mm.completeness).statistic
    rho_a5 = spearmanr(mm.heat, mm.adoption).statistic
    rho_k5 = spearmanr(mm.count_km2, mm.completeness).statistic

    # The municipality under each candidate box (by box centroid).
    cg = cand_gdf.copy()
    cg["geometry"] = cg.geometry.representative_point()
    cj = gpd.sjoin(cg, gem, predicate="within", how="left").merge(
        m[["ags", "completeness"]], on="ags", how="left")
    allj = boxes_gdf[boxes_gdf.n_pv > 0].copy()
    allj["geometry"] = allj.geometry.representative_point()
    aj = gpd.sjoin(allj, gem, predicate="within", how="left").merge(
        m[["ags", "completeness"]], on="ags", how="left")

    def dist(s):
        s = s.dropna()
        return {"n": int(len(s)), "median": round(float(s.median()), 3) if len(s) else None,
                "share_ge_0.3": round(float((s >= 0.3).mean()), 3) if len(s) else None,
                "share_ge_0.5": round(float((s >= 0.5).mean()), 3) if len(s) else None,
                "share_gt_1.0": round(float((s > 1.0).mean()), 3) if len(s) else None}

    return {
        "municipalities": int(len(m)),
        "national_count_completeness": round(float(m.osm_n.sum() / m.n_rooftop_units.sum()), 4),
        "spearman_heat_vs_completeness": round(float(rho_c), 3),
        "spearman_heat_vs_adoption": round(float(rho_a), 3),
        "municipalities_with_ge5_mapped": int(len(mm)),
        "spearman_heat_vs_completeness_ge5": round(float(rho_c5), 3),
        "spearman_heat_vs_adoption_ge5": round(float(rho_a5), 3),
        "spearman_mapped_per_km2_vs_completeness_ge5": round(float(rho_k5), 3),
        "municipal_completeness_under_candidates": dist(cj["completeness"]),
        "municipal_completeness_under_all_mapped_boxes": dist(aj["completeness"]),
        "municipalities_ge_0.5": int((m.completeness >= 0.5).sum()),
        "municipalities_ge_0.8": int((m.completeness >= 0.8).sum()),
        "note": "completeness is a municipal count ratio; a box can be better or worse "
                "mapped than its municipality, and one OSM polygon is not always one "
                "registered unit (mastr_validation.osm_completeness_by_count)",
    }


def main() -> int:
    import geopandas as gpd

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--iso3", required=True, help="VIDA file: data/vida/<ISO3>.parquet")
    ap.add_argument("--osm-solar", type=Path, required=True,
                    help="placement-classified pull, e.g. data/labels/<aoi>_national_osm_solar.parquet")
    ap.add_argument("--box-m", type=float, default=1500.0,
                    help="box side; 1,500 m = 2.25 km2, the largest Rule-1 quadrat so far")
    ap.add_argument("--min-bldg", type=int, default=150)
    ap.add_argument("--min-pv", type=int, default=10)
    ap.add_argument("--min-interior", type=float, default=0.5,
                    help="neighbour median / box value; low = the box is a hot spot at the "
                         "edge of a mapped area rather than inside one")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--min-spacing-km", type=float, default=10.0,
                    help="drop a box within this distance of a better-ranked one")
    ap.add_argument("--merge-m", type=float, default=1.0,
                    help="merge mapped polygons within this distance into one installation")
    ap.add_argument("--per-band", action=argparse.BooleanOptionalAction, default=True,
                    help="top N per decade of building density (default), not overall")
    ap.add_argument("--validate-mastr", action="store_true",
                    help="Germany: test the heatmap against the register's municipal counts")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()

    out = a.out or REPO / "results" / f"{a.aoi}_quadrat_candidates"
    out.mkdir(parents=True, exist_ok=True)

    osm = gpd.read_parquet(a.osm_solar).to_crs(4326)
    lon, lat = _building_points(REPO / "data" / "vida" / f"{a.iso3}.parquet")
    crs = gpd.GeoSeries.from_xy([np.nanmedian(lon)], [np.nanmedian(lat)], crs=4326).estimate_utm_crs()
    print(f"{len(lon):,} buildings, {len(_small_pv(osm)):,} small mapped PV features; grid "
          f"{a.box_m:,.0f} m in {crs.name}")

    boxes = mapped_pv_heatmap(osm, lon, lat, crs, a.box_m, a.merge_m)
    cand = quadrat_candidates(boxes, a.min_bldg, a.min_pv, a.top, a.per_band, a.min_interior,
                              a.box_m, a.min_spacing_km)
    cg = _box_polygons(cand, crs, a.box_m)

    q = _existing_quadrats()
    cg["overlaps_quadrat"] = ""
    if q is not None:
        hit = gpd.sjoin(cg[["geometry"]], q[["quadrat", "geometry"]], predicate="intersects")
        cg.loc[hit.index, "overlaps_quadrat"] = hit.groupby(level=0)["quadrat"].first()
    c = cg.geometry.representative_point()
    cg["lat"], cg["lon"] = c.y.round(5), c.x.round(5)
    cg["osm_link"] = [f"https://www.openstreetmap.org/#map=16/{y}/{x}" for y, x in zip(cg.lat, cg.lon)]
    cg["openinframap_link"] = [f"https://openinframap.org/#15/{y}/{x}/{OIM_LAYERS}"
                               for y, x in zip(cg.lat, cg.lon)]
    for col in ("ts_median", "ts_min", "ts_max"):
        cg[col] = pd.to_datetime(cg[col]).dt.strftime("%Y-%m-%d")
    cg["status"] = "candidate: needs the imagery sweep before registration"

    bg = _box_polygons(boxes, crs, a.box_m)
    bg.attrs["crs"] = crs
    bg.drop(columns=["ts_median", "ts_min", "ts_max"]).to_parquet(out / "boxes.parquet")
    cg.to_file(out / "candidates.geojson", driver="GeoJSON")
    cg.drop(columns="geometry").to_csv(out / "candidates.csv", index=False)

    cols = ["density_band", "bldg_km2", "n_bldg", "n_pv", "pv_per_1k_bldg",
            "neighbour_pv_per_1k", "ts_median", "lat", "lon", "overlaps_quadrat"]
    print(cg[cols].round(1).to_string(index=False))
    print(f"\n{len(boxes):,} boxes with buildings, {int((boxes.n_pv > 0).sum()):,} with mapped "
          f"small PV; {len(cg)} candidates -> {out}")

    if a.validate_mastr:
        rep = validate_against_mastr(bg, osm, lon, lat, cg, a.merge_m)
        (out / "mastr_validation.json").write_text(json.dumps(rep, indent=2))
        print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
