"""Hard-negative chip centres from land cover the segmentation model mistakes for PV.

Indonesia's published leads (v28 at 0.98, 2026-11-25) are mostly false, and the owner named
the land covers: mines, ponds, clearings and above all oil palm monoculture (2026-11-26).
OpenStreetMap maps too little of it to teach a model: its mine, aquaculture, oil palm and
clearing polygons touch 442 of the 9,400 leads. Three open land-cover layers fill the gap:

  - oil palm extent 2016-2021 at 10 m (Descals et al. 2024, ESSD 16, 5111; Zenodo
    10.5281/zenodo.13379129; CC BY 4.0), industrial and smallholder;
  - mining footprints, 74,548 polygons of pits, tailings and heap leach pads (Tang & Werner
    2023, Commun. Earth Environ. 4, 134; Zenodo 10.5281/zenodo.6806817; CC BY 4.0);
  - forest loss year at 30 m (Hansen et al. 2013, Global Forest Change 2000-2025 v1.13;
    CC BY 4.0): land cleared since `--clearing-since`, the clearings;

plus OSM's own polygons of those classes (`--osm-landuse`, a GDAL read of the Geofabrik
extract with `landuse`, `natural`, `man_made` and `other_tags` columns).

Two kinds of centre, both written for `earthpv hard-negative-chips --centers`:

  lead        a candidate of the published run lying on one of `--lead-classes` (oil palm: at
              least `--palm-share` of its outline on palm pixels; mine, aquaculture: its
              outline touches a polygon), more than `--halo-m` from any mapped solar feature
              of the given (fresh) OSM pull and not itself an OSM geometry. These are the
              confusions: the chip shows the model the very place it fired.

              Clearing is not a lead class by default, measured 2026-11-26: forest lost since
              2021 lies under 11.4% of the leads, but also under 9.8% of the 122 installations
              the owner mapped from them and 14.9% of the installations mapped in OSM before
              (solar farms are built on cleared land), so a lead on a clearing is no likelier
              false than any other. Oil palm (10.6% of leads, 0% and 0.9% of real PV) and
              mines (4.3%; 0% and 0.3%) do separate them.
  landscape   random points in each land cover over the composited cells, so the model also
              sees the class where it did not fire, and `--background N` random points over
              the composited cells of `--background-region` provinces.

A real installation inside a mine or a plantation can become a negative here. The halo
around mapped solar (the fresh pull holds the owner's mapping from the leads) and the chip
builder's mask burn from that same pull limit it; what remains is label noise of the size
of the share of real PV among such leads, which the owner judged small.

Centres whose 2.24 km chip could reach a cell of `--exclude-cells` (the whole-cell
comparison's random sample, data/sheet_scan/<aoi>/cells_random.txt) are dropped, so the
retrained model's false-alarm rate there stays out of sample. Centres in the AOI's val_tiles stay: the chip
builder puts them in the val split, scored apart from the normal val chips.

    pixi run python scripts/landcover_hard_negatives.py --aoi indonesia \\
        --labels data/labels/indonesia_pull_20261126/indonesia_overpass_solar.parquet \\
        --palm-dir /home/tobi/earthpv_data/landcover/oilpalm_descals2024/extent \\
        --mining /home/tobi/earthpv_data/landcover/mining_tang2023/<polygons>.shp \\
        --osm-landuse /home/tobi/earthpv_data/indonesia_hardneg/landuse_polygons.parquet \\
        --exclude-cells data/sheet_scan/indonesia/cells_random.txt \\
        --out /home/tobi/earthpv_data/indonesia_hardneg/centers.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

DEG_M = 111_320.0
CHIP_HALF_DEG = 0.0112  # half of a 2.24 km chip
CLASS_ORDER = ["mine", "aquaculture", "oil_palm", "clearing"]  # first match wins


def _cell(lon, lat, origin, step=0.1):
    return (f"{int(np.floor((lon - origin[0]) / step + 1e-9)):04d}_"
            f"{int(np.floor((lat - origin[1]) / step + 1e-9)):04d}")


def _cell_bounds(cell: str, origin, step=0.1):
    i, j = (int(x) for x in cell.split("_"))
    x0, y0 = origin[0] + i * step, origin[1] + j * step
    return x0, y0, x0 + step, y0 + step


def osm_classes(path: Path) -> gpd.GeoDataFrame:
    """OSM polygons per class from the land-use read of the extract."""
    f = gpd.read_parquet(path)
    if f.crs is None:
        f = f.set_crs("EPSG:4326")
    ot = f["other_tags"].fillna("")

    def tag(k):
        return ot.str.extract(r'"%s"=>"([^"]*)"' % k)[0]

    industrial, water, resource = tag("industrial"), tag("water"), tag("resource")
    palm = ot.str.contains(r'oil_palm|"trees"=>"oil_palms"|palm_oil|palm oil|kelapa sawit',
                           regex=True)
    cls = pd.Series(None, index=f.index, dtype=object)
    masks = {
        "clearing": f["landuse"].isin(["brownfield", "construction", "greenfield"]),
        "oil_palm": palm,
        "aquaculture": f["landuse"].isin(["aquaculture", "salt_pond"]) | water.eq("fishpond"),
        "mine": (f["landuse"].isin(["quarry", "mining"]) | industrial.eq("mine")
                 | f["man_made"].isin(["spoil_heap", "tailings_pond", "mineshaft"])
                 | resource.notna()),
    }
    for c in reversed(CLASS_ORDER):  # the first class in CLASS_ORDER wins
        cls[masks[c]] = c
    f = f.assign(lc_class=cls)[cls.notna()]
    f = f[f.geom_type.isin(["Polygon", "MultiPolygon"])]
    return f[["lc_class", "geometry"]].reset_index(drop=True)


class RasterTiles:
    """Land-cover tiles intersecting the AOI, read per geometry (no mosaic: the AOI at
    10 m is ~80 G pixels). Every tile must share one CRS. `hit(a)` marks the class's
    pixels (oil palm: any non-zero class; forest loss: a loss year from `--clearing-since`)."""

    def __init__(self, palm_dir: Path, bounds, hit=lambda a: a > 0):
        self.hit = hit
        import rasterio
        from rasterio.warp import transform_bounds

        self.tiles = []
        for p in sorted(palm_dir.rglob("*.tif")):
            with rasterio.open(p) as r:
                b = transform_bounds(r.crs, "EPSG:4326", *r.bounds)
                crs = r.crs
            if b[2] > bounds[0] and b[0] < bounds[2] and b[3] > bounds[1] and b[1] < bounds[3]:
                self.tiles.append((b, p))
                self.crs = crs
        if not self.tiles:
            raise SystemExit(f"no tiles in {palm_dir} intersect {bounds}")
        self._open: dict[Path, object] = {}

    def _src(self, p: Path):
        import rasterio

        if p not in self._open:
            self._open[p] = rasterio.open(p)
        return self._open[p]

    def covering(self, b):
        return [p for tb, p in self.tiles
                if tb[2] > b[0] and tb[0] < b[2] and tb[3] > b[1] and tb[1] < b[3]]

    def counts(self, geom_ll, geom_tile):
        """(pixels inside the outline, of them on the class) over the tiles it touches."""
        from rasterio import features
        from rasterio.windows import from_bounds

        n = palm = 0
        for p in self.covering(geom_ll.bounds):
            r = self._src(p)
            w = from_bounds(*geom_tile.buffer(abs(r.transform.a)).bounds, transform=r.transform)
            w = w.round_offsets().round_lengths()
            a = r.read(1, window=w, boundless=True, fill_value=0)
            if a.size == 0:
                continue
            m = features.geometry_mask([geom_tile], out_shape=a.shape,
                                       transform=r.window_transform(w), invert=True,
                                       all_touched=True)
            inside = m & self._inside_tile(r, w, a.shape)
            n += int(inside.sum())
            palm += int(self.hit(a[inside]).sum())
        return n, palm

    @staticmethod
    def _inside_tile(r, w, shape):
        rows = np.arange(shape[0])[:, None] + int(w.row_off)
        cols = np.arange(shape[1])[None, :] + int(w.col_off)
        return (rows >= 0) & (rows < r.height) & (cols >= 0) & (cols < r.width)

    def look(self, b, step_px: int = 10):
        """The tile holding the centre of lon/lat box `b`, read over `b` at `step_px` decimation."""
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        c = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        tiles = self.covering((c[0], c[1], c[0], c[1]))
        if not tiles:
            return None
        r = self._src(tiles[0])
        tb = transform_bounds("EPSG:4326", r.crs, *b)
        w = from_bounds(*tb, transform=r.transform).round_offsets().round_lengths()
        a = r.read(1, window=w, boundless=True, fill_value=0, out_shape=(
            max(1, int(w.height) // step_px), max(1, int(w.width) // step_px)))
        return a


def class_share(cands: gpd.GeoDataFrame, tiles: RasterTiles) -> np.ndarray:
    """Share of each candidate outline (all_touched) on the class's pixels."""
    out = np.zeros(len(cands))
    g_ll = cands.geometry.to_crs("EPSG:4326")
    g_t = g_ll.to_crs(tiles.crs)
    for k, (gl, gt) in enumerate(zip(g_ll, g_t)):
        n, palm = tiles.counts(gl, gt)
        if n:
            out[k] = palm / n
    return out


def random_class_points(tiles: RasterTiles, cells: list[str], origin, n: int, rng,
                        label: str, step_px: int = 10) -> pd.DataFrame:
    """`n` random class pixels, from cells drawn at random among `cells` holding the class."""
    rows, order = [], rng.permutation(len(cells))
    for idx in order:
        if len(rows) >= n:
            break
        b = _cell_bounds(cells[idx], origin)
        a = tiles.look(b, step_px)  # ~100 m look
        if a is None:
            continue
        yy, xx = np.nonzero(tiles.hit(a))
        if len(yy) < 50:  # under ~0.5 km2 of it: not that landscape
            continue
        j = rng.integers(len(yy))
        fx = (xx[j] + rng.random()) / a.shape[1]
        fy = (yy[j] + rng.random()) / a.shape[0]
        rows.append(dict(lon=b[0] + fx * (b[2] - b[0]), lat=b[3] - fy * (b[3] - b[1]),
                         lc_class=label))
    return pd.DataFrame(rows)


def random_in_polygons(polys: gpd.GeoDataFrame, n: int, rng, label: str) -> pd.DataFrame:
    """`n` points, polygons drawn by area, a uniform point inside each."""
    if polys.empty or n <= 0:
        return pd.DataFrame(columns=["lon", "lat", "lc_class"])
    area = polys.to_crs(polys.estimate_utm_crs()).area.to_numpy()
    pick = rng.choice(len(polys), size=n, p=area / area.sum())
    rows = []
    for i in pick:
        g = polys.geometry.iloc[i]
        x0, y0, x1, y1 = g.bounds
        for _ in range(200):
            x, y = x0 + rng.random() * (x1 - x0), y0 + rng.random() * (y1 - y0)
            if g.contains(gpd.points_from_xy([x], [y])[0]):
                rows.append(dict(lon=x, lat=y, lc_class=label))
                break
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--candidates", type=Path, help="default data/predictions/<aoi>/candidates.parquet")
    ap.add_argument("--labels", type=Path, required=True, help="fresh OSM solar pull (mapped halo)")
    ap.add_argument("--palm-dir", type=Path, required=True)
    ap.add_argument("--mining", type=Path, required=True)
    ap.add_argument("--osm-landuse", type=Path, required=True)
    ap.add_argument("--exclude-cells", type=Path, action="append", default=[])
    ap.add_argument("--background-region", action="append", default=[],
                    help="ADM1 name whose composited cells get random background centres")
    ap.add_argument("--background", type=int, default=300)
    ap.add_argument("--landscape-palm", type=int, default=400)
    ap.add_argument("--landscape-mine", type=int, default=300)
    ap.add_argument("--landscape-aquaculture", type=int, default=150)
    ap.add_argument("--palm-share", type=float, default=0.25)
    ap.add_argument("--lead-classes", default="mine,aquaculture,oil_palm",
                    help="classes whose candidates become lead centres (clearing: see above)")
    ap.add_argument("--loss-dir", type=Path, help="Hansen GFC lossyear tiles (recent clearing)")
    ap.add_argument("--clearing-since", type=int, default=2021,
                    help="forest lost in this year or later counts as a clearing")
    ap.add_argument("--clearing-share", type=float, default=0.25)
    ap.add_argument("--landscape-clearing", type=int, default=300)
    ap.add_argument("--halo-m", type=float, default=200.0)
    ap.add_argument("--declutter-m", type=float, default=500.0)
    ap.add_argument("--seed", type=int, default=20261126)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    from earthpv.local_source import CompositeIndex

    _, cfg = resolve_aoi(a.aoi, Settings.load())
    origin = tuple(cfg["grid_origin"])
    comp = sorted(p.parent.name for p in (REPO / "data" / "composites" / a.aoi / "composites")
                  .glob("*/composite_0.tif"))
    comp_set = set(comp)
    excl = set()
    for f in a.exclude_cells:
        excl |= set(f.read_text().split())
    idx = CompositeIndex(REPO / "data" / "composites" / a.aoi)
    bounds = tuple(gpd.GeoSeries([idx.coverage], crs="EPSG:4326").total_bounds)

    def spills_into_excluded(lon, lat) -> bool:
        return any(_cell(lon + dx, lat + dy, origin) in excl
                   for dx in (-CHIP_HALF_DEG, 0, CHIP_HALF_DEG)
                   for dy in (-CHIP_HALF_DEG, 0, CHIP_HALF_DEG))

    # ---- land cover
    t0 = time.time()
    osm = osm_classes(a.osm_landuse)
    mines = (gpd.read_parquet(a.mining) if a.mining.suffix == ".parquet"
             else gpd.read_file(a.mining)).to_crs("EPSG:4326")
    mines = mines[mines.intersects(idx.coverage)]
    mines = gpd.GeoDataFrame({"lc_class": ["mine"] * len(mines)},
                             geometry=mines.geometry.values, crs="EPSG:4326")
    polys = gpd.GeoDataFrame(pd.concat([osm, mines], ignore_index=True), crs="EPSG:4326")
    tiles = RasterTiles(a.palm_dir, bounds)
    print(f"oil palm: {len(tiles.tiles)} tiles over the AOI", flush=True)
    loss = None
    if a.loss_dir:
        since = a.clearing_since - 2000  # Hansen lossyear: 1 = 2001
        loss = RasterTiles(a.loss_dir, bounds, hit=lambda v: v >= since)
        print(f"forest loss since {a.clearing_since}: {len(loss.tiles)} tiles", flush=True)
    print(f"land cover: {len(osm):,} OSM polygons {osm.lc_class.value_counts().to_dict()}, "
          f"{len(mines):,} mining polygons in the AOI ({time.time() - t0:.0f} s)", flush=True)

    # ---- lead centres
    cands = gpd.read_parquet(a.candidates or REPO / "data" / "predictions" / a.aoi / "candidates.parquet")
    cands = cands.reset_index(drop=True).rename_axis("candidate_index").reset_index()
    n0 = len(cands)
    cands = cands[cands.get("geometry_source", pd.Series("model", index=cands.index)) != "osm"]
    mapped = gpd.read_parquet(a.labels)
    mapped = mapped[mapped.geometry.notna()].to_crs("EPSG:4326")
    halo = mapped.geometry.buffer(a.halo_m / DEG_M)
    near = cands.geometry.intersects(halo.union_all())
    cands = cands[~near].copy()
    print(f"candidates: {n0:,}; {int(near.sum()):,} within {a.halo_m:.0f} m of mapped solar "
          f"dropped; {len(cands):,} left", flush=True)

    cls = pd.Series(None, index=cands.index, dtype=object)
    hit = gpd.sjoin(cands[["geometry"]], polys, predicate="intersects", how="inner")
    if len(hit):
        order = {c: i for i, c in enumerate(CLASS_ORDER)}
        best = hit.assign(o=hit.lc_class.map(order)).sort_values("o").groupby(level=0).lc_class.first()
        cls.loc[best.index] = best
    share = class_share(cands, tiles)
    cands["palm_share"] = share
    on_palm = (share >= a.palm_share) & ~cls.isin(["mine", "aquaculture"]).to_numpy()
    cls[on_palm] = "oil_palm"
    cands["clearing_share"] = np.nan
    if loss is not None:
        cshare = class_share(cands, loss)
        cands["clearing_share"] = cshare
        cls[(cshare >= a.clearing_share) & cls.isna().to_numpy()] = "clearing"
    cands["lc_class"] = cls
    lead_classes = {c.strip() for c in a.lead_classes.split(",") if c.strip()}
    print(f"candidates on a class: {cands.lc_class.value_counts().to_dict()}; lead centres "
          f"from {sorted(lead_classes)}", flush=True)
    lead = cands[cands.lc_class.isin(lead_classes)].copy()
    rp = lead.geometry.representative_point()
    lead["lon"], lead["lat"] = rp.x.to_numpy(), rp.y.to_numpy()
    lead["source"] = "lead"
    print(f"lead centres: {lead.lc_class.value_counts().to_dict()} "
          f"({time.time() - t0:.0f} s)", flush=True)

    # ---- landscape centres
    cells_cov = [c for c in comp if c not in excl]
    land = [random_class_points(tiles, cells_cov, origin, a.landscape_palm, rng, "oil_palm")]
    if loss is not None:  # Hansen is 0.00025 deg: 4 px is ~110 m
        land.append(random_class_points(loss, cells_cov, origin, a.landscape_clearing, rng,
                                        "clearing", step_px=4))
    for c, n in (("mine", a.landscape_mine), ("aquaculture", a.landscape_aquaculture)):
        land.append(random_in_polygons(polys[polys.lc_class == c], n, rng, c))
    if a.background and a.background_region:
        adm = gpd.read_file(sorted((REPO / "data" / "geoboundaries").glob(
            f"gb_{cfg['division']['iso3']}_ADM1*.geojson"))[0])
        reg = adm[adm.shapeName.isin(a.background_region)].union_all()
        pool = [c for c in cells_cov
                if reg.contains(gpd.points_from_xy(
                    [(_cell_bounds(c, origin)[0] + _cell_bounds(c, origin)[2]) / 2],
                    [(_cell_bounds(c, origin)[1] + _cell_bounds(c, origin)[3]) / 2])[0])]
        pick = rng.choice(pool, size=min(a.background, len(pool)), replace=False)
        rows = []
        for c in pick:
            b = _cell_bounds(c, origin)
            rows.append(dict(lon=b[0] + 0.015 + rng.random() * 0.07,
                             lat=b[1] + 0.015 + rng.random() * 0.07, lc_class="background"))
        land.append(pd.DataFrame(rows))
        print(f"background: {len(rows)} of {len(pool)} composited cells in "
              f"{len(a.background_region)} provinces", flush=True)
    land = pd.concat(land, ignore_index=True)
    land["source"] = "landscape"

    # ---- assemble: inside imagery, away from mapped solar and the sample cells, decluttered
    cols = ["lon", "lat", "lc_class", "source"]
    extra = ["candidate_index", "area_m2", "confidence", "placement", "palm_share",
             "clearing_share"]
    allc = pd.concat([lead[cols + extra], land[cols]], ignore_index=True)
    allc["cell"] = [_cell(x, y, origin) for x, y in zip(allc.lon, allc.lat)]
    pts = gpd.GeoSeries(gpd.points_from_xy(allc.lon, allc.lat), crs="EPSG:4326")
    keep = allc.cell.isin(comp_set).to_numpy().copy()
    keep &= ~np.array([spills_into_excluded(x, y) for x, y in zip(allc.lon, allc.lat)])
    keep &= ~pts.intersects(halo.union_all()).to_numpy()
    dropped = {"no_imagery_or_sample_or_mapped": int((~keep).sum())}
    allc = allc[keep]
    allc = allc.assign(_lead=allc.source.eq("lead")).sort_values(
        ["_lead", "area_m2"], ascending=[False, False], na_position="last")
    deg = a.declutter_m / DEG_M
    g = (allc.lon / deg).round().astype(int).astype(str) + "_" + (allc.lat / deg).round().astype(int).astype(str)
    dropped["declutter"] = int(g.duplicated().sum())
    allc = allc[~g.duplicated()].drop(columns="_lead").reset_index(drop=True)
    allc["kind"] = "hard_negative"
    allc["osm_class"] = allc.lc_class + "_" + allc.source  # the chip index carries it
    a.out.parent.mkdir(parents=True, exist_ok=True)
    allc.to_parquet(a.out)
    summ = dict(aoi=a.aoi, made=time.strftime("%F %T"), centres=len(allc),
                by_class={f"{c}/{s}": int(n) for (c, s), n in
                          allc.groupby(["lc_class", "source"]).size().items()},
                dropped=dropped, palm_share_min=a.palm_share, halo_m=a.halo_m,
                declutter_m=a.declutter_m, labels=str(a.labels), seed=a.seed,
                exclude_cells=[str(p) for p in a.exclude_cells],
                sources={"oil_palm": "Descals et al. 2024, doi:10.5281/zenodo.13379129, CC BY 4.0",
                         "mine": "Tang & Werner 2023, doi:10.5281/zenodo.6806817, CC BY 4.0; "
                                 "OpenStreetMap (ODbL)",
                         "clearing": "Hansen et al. 2013, Global Forest Change 2000-2025 v1.13 "
                                     "lossyear, CC BY 4.0; OpenStreetMap (ODbL)",
                         "aquaculture": "OpenStreetMap (ODbL)"},
                clearing_since=a.clearing_since if a.loss_dir else None,
                lead_classes=sorted(lead_classes))
    a.out.with_suffix(".json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
