#!/usr/bin/env python
"""Propose calibration-area candidates for a country by stratified random sampling.

Until now every candidate was picked by hand (Pakistan's Boxes 18 and 19), which is how the
two failure modes `docs/calibration-mapping-protocol.md` lists under "Quadrat selection"
kept happening: selection bias ("do not choose a box because you can see solar there" is a
rule a human has to keep obeying) and wasted mapping (six Pakistani boxes drawn or fully
swept before anyone found their imagery predated the composite). This does the protocol's
own recipe, in its order, with no human choice anywhere in it:

1. **Strata from the country's own density grid.** `data/predictions/<aoi>/density/
   grid.geoparquet` (`n_buildings`, `bldg_density_km2` per 0.1 deg cell) is cut into
   `--strata` bands holding equal shares of the country's BUILDINGS, so the bands follow
   the population the published estimate is applied to. Eight bands of one candidate,
   not four of two: a building-weighted draw lands near a band's dense end, and four bands
   left Egypt's sparsest pair at 235 and 326 bldg/km2 against a 5th percentile of 79.
2. **Cells drawn at random within each band**, weighted by building count, from a seed
   recorded on every candidate. Spread is enforced, not chosen: a new candidate keeps
   `--min-spacing-km` from every other one and from every registered quadrat, and prefers
   a province no candidate has used yet.
3. **The box is placed on the buildings, not on the cell centroid.** A cell centroid is a
   coarse pointer (Box 18's three quadrats measured 895/237/146 bldg/km2 against source
   cells of 549/250/150). Every `--side-m` window inside the cell is counted from VIDA
   footprints, and one whose OWN density is within 25% of the cell's is drawn at random.
   That is what makes the box represent its stratum, and the box's own density is what
   `density.CALIBRATED_BLDG_DENSITY_BY_AOI` will later be fitted from. Cells denser than
   600 bldg/km2 get 1 km boxes (the protocol's dense-urban size), the rest 2 km.
4. **The imagery gate, before anyone maps.** Esri World Imagery's own metadata service (the
   one iD reads for its "imagery date" panel) is asked for the capture date at the centre
   and the four corners; the OLDEST must be no more than `--max-imagery-lag-months` before
   the AOI's `compose_window` start in `configs/aoi.yaml`. A box that fails is recorded in
   `screened_out.csv` with the date and the next draw from the same band takes its place.

Output: `data/labels/<aoi>/candidate_quadrats/<stem>_candidate.geojson` (Pakistan:
`data/labels/candidate_quadrats/`), the layout `scripts/publish_calibration_areas.py` reads;
run `pixi run calib-publish` afterwards and every atlas shows them as hollow diamonds.
**Do not re-run with another seed to get nicer-looking boxes**: that reintroduces exactly
the hand-picking this replaces. Re-running with the same seed reproduces the same draw.

`scripts/heatmap_quadrat_candidates.py` is not this: it ranks boxes by OSM-mapped PV per
building, which is the selection bias the protocol warns about, and needs a PV pull.

**`--farmland`: farm calibration areas for the ground-PV detector (`roofclf_ground`).**
The building strata above describe where ROOFS are, which is the wrong frame for small
ground arrays beside fields: in Yemen's 'Amran test ground only 6.6% of mapped array area
lies on a building footprint (2026-10-23). This mode runs the same recipe on farmland:

1. **Strata from cropland.** ESA WorldCover's cropland share of every density-grid cell
   (`worldcover.cell_cropland`, cached in `data/cells_cache/<aoi>_cropland.parquet`), cut
   into `--strata` bands holding equal shares of the country's cropland AREA. Cells under
   `--farm-min-crop` cropland hold no farm to sample. Only density-grid cells are drawn
   from, i.e. cells the country's compose imaged, because the detector cannot score
   anything else.
2. **Cells drawn cropland-weighted** within each band, same spacing and province spread.
3. **The box is placed on the farmland**: every `--farm-side-m` window (3 km by default:
   farm PV is sparse, 'Amran held about 2 arrays per km2) is counted from WorldCover at
   100 m, and one whose own cropland share is within 25% of the cell's is drawn at random.
4. **The same imagery gate.**

Farm boxes are written as `<place>_f<k>_farm_calib_<side>_candidate.geojson`, register with
`new_calibration_quadrat.py --farm`, and are invisible to the rooftop roofclf
(`roofclf.FARM_QUADRAT_INFIX`). Map ALL solar in a farm box, ground and rooftop, tracing
panels rather than enclosures.

    pixi run calib-candidates -- --aoi zambia --dry-run
    pixi run calib-candidates -- --bronze                  # every Bronze atlas
    pixi run calib-candidates -- --aoi india --replace     # redraw a country's candidates
    pixi run calib-candidates -- --aoi yemen --farmland    # farm boxes for roofclf_ground
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import zlib
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from new_calibration_quadrat import GEOD, geodesic_square  # noqa: E402

from earthpv.config import Settings  # noqa: E402

LABELS = Path("data/labels")
FLAT_AOI = "pakistan"               # see atlas.calib_boundary_path
PAGES = Path("docs/assets/interactive")
ESRI_METADATA = ("https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/"
                 "MapServer/4/query")
ESRI_ZOOM = 18                       # the level a mapper traces panels at
MIN_BOX_BUILDINGS = 25               # below this there is nothing to calibrate against
OWN_DENSITY_TOL = 1.25               # a box's own density within x/÷ this of its cell's
MAX_ATTEMPTS = 120                   # draws per band before it is reported short
# Above this a 2 km box holds over 2,400 buildings, a long sweep; such cells get the
# protocol's dense-urban 1 km box instead (--dense-side-m).
DENSE_BLDG_KM2 = 600.0
SELECTION = "stratified random by building density"
# --priority: the purposive "start here" boxes. Selected on buildings alone, never on solar.
PRIORITY_SELECTION = "purposive: dense cells, most large-roof area"
LARGE_ROOF_M2 = 1000.0               # a footprint this big is commercial or industrial
PRIORITY_STRATA = 2                  # the densest 2 of --strata bands: a quarter of buildings
PRIORITY_CELLS = 40                  # cells scanned per ranking (roof cover, mean footprint)
CAND_SPACING_KM = 5.0                # from an existing candidate; quadrats keep --min-spacing-km
# --farmland: boxes for the ground-PV detector, stratified by cropland instead of buildings.
FARM_SELECTION = "stratified random by cropland area"
OWN_CROP_TOL = 1.25                  # a box's own cropland share within x/÷ this of its cell's
MIN_WINDOW_COVER = 0.8               # of the cell's best-covered window: no half-sea boxes


def grid_path(aoi: str) -> Path:
    """The AOI's density grid: `data/predictions/<aoi>/` first, else the one other
    `data/predictions_*/<aoi>/` run that has one (Nigeria's lives under
    `predictions_v5_nigeria/`). Several candidates is an error, not a guess."""
    main = Path(f"data/predictions/{aoi}/density/grid.geoparquet")
    if main.exists():
        return main
    found = sorted(Path("data").glob(f"predictions_*/{aoi}/density/grid.geoparquet"))
    if len(found) == 1:
        return found[0]
    raise SystemExit(f"{aoi}: no unique density grid ({[str(p) for p in found] or 'none'}); "
                     "pass --grid")


def bronze_aois() -> list[str]:
    """AOIs whose published atlas carries the Bronze calibration badge."""
    out = []
    for p in sorted(PAGES.glob("*evidence_atlas.html")):
        m = re.match(r"(.+?)_(?:pv_)?evidence_atlas\.html$", p.name)
        if m and 'class="vscore-tier">Bronze<' in p.read_text():
            out.append(m.group(1))
    return out


def strata_edges(cells: pd.DataFrame, k: int, value: str = "bldg_density_km2",
                 weight: str = "n_buildings") -> np.ndarray:
    """`value` edges cutting the cells into `k` bands of equal `weight` share (building
    density by building count by default; cropland share by cropland area for farms)."""
    c = cells.sort_values(value)
    share = c[weight].cumsum() / c[weight].sum()
    inner = [float(c[value][share >= i / k].iloc[0]) for i in range(1, k)]
    return np.array([0.0, *inner, float("inf")])


def cropland_table(aoi: str, grid: pd.DataFrame) -> pd.DataFrame:
    """WorldCover cropland share per density-grid cell, cached per AOI. Recomputed when the
    grid has cells the cache lacks (a widened compose), never silently partial."""
    from earthpv.worldcover import cell_cropland

    cache = Path("data/cells_cache") / f"{aoi}_cropland.parquet"
    if cache.exists():
        got = pd.read_parquet(cache)
        if set(grid["cell"]) <= set(got["cell"]):
            return got
    print(f"  {aoi}: cropland share of {len(grid)} cells from ESA WorldCover (one read per tile)")
    got = cell_cropland(grid[["cell", "lon0", "lat0"]])
    cache.parent.mkdir(parents=True, exist_ok=True)
    got.to_parquet(cache)
    return got


def slug(text: str) -> str:
    """A stem-safe place name, without the admin-type words ("Province de Nador" -> nador)."""
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")
    admin = r"(province|prefecture|governorate|district|municipality|city|markz|wilaya)"
    s = re.sub(rf"^{admin}(_(de|du|of|d))?_", "", s)
    s = re.sub(rf"_{admin}$", "", s)
    return s or "area"


def esri_capture(lon: float, lat: float, retries: int = 3) -> dict | None:
    """Esri World Imagery metadata at a point, for the layer serving `ESRI_ZOOM`."""
    q = urllib.parse.urlencode({
        "returnGeometry": "false", "geometry": f"{lon},{lat}", "inSR": 4326,
        "geometryType": "esriGeometryPoint", "f": "json",
        "outFields": "SRC_DATE2,SRC_RES,NICE_NAME,MinMapLevel,MaxMapLevel"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(f"{ESRI_METADATA}?{q}", timeout=30) as r:
                feats = json.load(r).get("features", [])
            for f in feats:
                a = f["attributes"]
                if a.get("MinMapLevel", 99) <= ESRI_ZOOM <= a.get("MaxMapLevel", -1) and a.get("SRC_DATE2"):
                    return {"date": datetime.fromtimestamp(a["SRC_DATE2"] / 1000, timezone.utc).date(),
                            "res_m": a.get("SRC_RES"), "name": a.get("NICE_NAME") or ""}
            return None
        except Exception:  # noqa: BLE001 -- network hiccup; retried, then reported as unknown
            time.sleep(2 * (attempt + 1))
    return None


def imagery_gate(poly, earliest: date) -> tuple[bool, dict]:
    """The oldest Esri capture date over the box's centre and corners, against `earliest`."""
    w, s, e, n = poly.bounds
    pts = [((w + e) / 2, (s + n) / 2), (w, s), (w, n), (e, s), (e, n)]
    caps = [esri_capture(x, y) for x, y in pts]
    if any(c is None for c in caps):
        return False, {"reason": "no Esri imagery date at zoom 18 for part of the box"}
    old = min(caps, key=lambda c: c["date"])
    info = {"imagery_date": old["date"].isoformat(), "imagery_res_m": round(float(old["res_m"]), 2),
            "imagery_layer": f"Esri World Imagery ({old['name']})" if old["name"] else "Esri World Imagery"}
    if old["date"] < earliest:
        info["reason"] = f"Esri imagery from {old['date']} predates {earliest}"
        return False, info
    return True, info


def window_densities(lon: np.ndarray, lat: np.ndarray, cell: pd.Series, side_m: float,
                     weights: tuple = ()):
    """(centre lon, centre lat, n buildings, *sum of each of `weights`) for every `side_m`
    window inside the cell, on a quarter-side step, counted with a summed-area table over
    a 100 m raster."""
    lat_c = cell.lat0 + 0.05
    m_lat = 111_132.954 - 559.822 * math.cos(2 * math.radians(lat_c))
    m_lon = 111_412.84 * math.cos(math.radians(lat_c))
    res_y, res_x = 100.0 / m_lat, 100.0 / m_lon
    nx, ny = int(math.ceil(0.1 / res_x)), int(math.ceil(0.1 / res_y))
    rng = [[cell.lon0, cell.lon0 + nx * res_x], [cell.lat0, cell.lat0 + ny * res_y]]
    sats = []
    for w in (None, *weights):
        hist, _, _ = np.histogram2d(lon, lat, bins=[nx, ny], range=rng, weights=w)
        sat = np.zeros((nx + 1, ny + 1))
        sat[1:, 1:] = hist.cumsum(0).cumsum(1)
        sats.append(sat)
    wx, wy = int(round(side_m / 100)), int(round(side_m / 100))
    step = max(1, wx // 4)
    out = []
    for i in range(0, nx - wx + 1, step):
        for j in range(0, ny - wy + 1, step):
            sums = [s[i + wx, j + wy] - s[i, j + wy] - s[i + wx, j] + s[i, j] for s in sats]
            out.append((cell.lon0 + (i + wx / 2) * res_x, cell.lat0 + (j + wy / 2) * res_y, *sums))
    return np.array(out)


class Admin:
    """District / region names from the density stage's own admin parquet files."""

    def __init__(self, aoi: str):
        import geopandas as gpd

        self.layers = []
        for kind in ("districts", "regions"):
            p = LABELS / f"{aoi}_{kind}.parquet"
            self.layers.append(gpd.read_parquet(p).to_crs(4326) if p.exists() else None)

    def lookup(self, lon: float, lat: float) -> tuple[str | None, str | None]:
        """(district, region) containing the point, else the nearest within ~5 km: the
        simplified admin outlines miss the coast (94 South African cells hold 768k
        buildings with their centre outside every province)."""
        import warnings

        from shapely.geometry import Point

        pt, out = Point(lon, lat), []
        for g in self.layers:
            if g is None:
                out.append(None)
                continue
            hit = g[g.contains(pt)]
            if hit.empty:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")   # degrees, deliberately: a rough 5 km
                    d = g.distance(pt)
                hit = g.loc[[d.idxmin()]] if d.min() < 0.05 else hit
            # Whitespace collapsed: one Vietnamese province name carries a trailing tab.
            out.append(" ".join(str(hit.iloc[0]["name"]).split()) if len(hit) else None)
        return out[0], out[1]


def existing_boxes(home: Path) -> list:
    """Every registered quadrat of this AOI: the overlap/spacing reference."""
    from earthpv.roofclf import load_boundary

    return [load_boundary(p) for p in sorted(home.glob("*_calib_*_boundary.geojson"))]


def propose(aoi: str, args) -> list[dict]:
    import duckdb
    from shapely.geometry import mapping

    from earthpv.buildings import fetch_vida_building_points

    cfg = Settings.load().aois.get(aoi) or {}
    div = cfg.get("division") or {}
    iso3, country = div.get("iso3"), div.get("name")
    if not iso3 or not cfg.get("compose_window"):
        raise SystemExit(f"{aoi}: configs/aoi.yaml needs division.iso3 and compose_window")
    win0 = date.fromisoformat(cfg["compose_window"][0])
    months = win0.year * 12 + win0.month - 1 - args.max_imagery_lag_months
    earliest = date(months // 12, months % 12 + 1, 1)

    home = LABELS if aoi == FLAT_AOI else LABELS / aoi
    out_dir = home / "candidate_quadrats"
    auto = [p for p in sorted(out_dir.glob("*_candidate.geojson"))
            if SELECTION in json.loads(p.read_text())["features"][0]["properties"].get("selection", "")]
    if auto and not args.replace:
        print(f"{aoi}: {len(auto)} sampled candidates already exist in {out_dir}; "
              "pass --replace to redraw them")
        return []

    grid = pd.read_parquet(args.grid or grid_path(aoi),
                           columns=["cell", "lon0", "lat0", "n_buildings", "bldg_density_km2"])
    grid = grid[grid["n_buildings"] >= MIN_BOX_BUILDINGS].reset_index(drop=True)
    edges = strata_edges(grid, args.strata)
    grid["stratum"] = np.searchsorted(edges, grid["bldg_density_km2"], side="right") - 1
    seed = args.seed if args.seed is not None else zlib.crc32(aoi.encode()) % 100_000
    rng = np.random.default_rng(seed)
    admin = Admin(aoi)
    taken = existing_boxes(home)
    # Other candidates (start-here boxes, hand-picked ones) are never overlapped: two boxes
    # sharing ground would count the same installations twice once both are mapped.
    from earthpv.roofclf import load_boundary

    others = [load_boundary(p) for p in sorted(out_dir.glob("*_candidate.geojson")) if p not in auto]
    used_regions: set = set()
    picked, screened = [], []
    con = duckdb.connect()
    con.execute("SET parquet_metadata_cache=true;")  # India: 105k row groups per scan

    for k in range(args.strata):
        band = grid[grid["stratum"] == k]
        lo, hi = edges[k], edges[k + 1]
        label = (f"density stratum {k + 1} of {args.strata}: "
                 + (f"{lo:,.0f}-{hi:,.0f}" if math.isfinite(hi) else f">{lo:,.0f}") + " bldg/km2 (cell)")
        got = 0
        for attempt in range(MAX_ATTEMPTS):
            if got == args.per_stratum or band.empty:
                break
            cell = band.iloc[rng.choice(len(band), p=band["n_buildings"] / band["n_buildings"].sum())]
            # Cheap rejections first, from the cell centre: a province already used is skipped
            # while there is room to spread (past half the attempts a band takes what it can
            # get rather than coming back short), a cell no window of which can keep the
            # spacing is skipped, and a cell whose centre imagery already fails the gate never
            # costs a footprint query.
            ccx, ccy = cell.lon0 + 0.05, cell.lat0 + 0.05
            _, region0 = admin.lookup(ccx, ccy)
            if region0 and region0 in used_regions and attempt < MAX_ATTEMPTS // 2:
                continue
            if any(GEOD.inv(ccx, ccy, b.centroid.x, b.centroid.y)[2] / 1000 < args.min_spacing_km - 8
                   for b in taken):
                continue
            cap = esri_capture(ccx, ccy)
            if cap is None or cap["date"] < earliest:
                screened.append({"aoi": aoi, "stratum": k + 1, "cell": cell.cell, "lat": round(ccy, 6),
                                 "lon": round(ccx, 6), "reason": "cell centre: " + (
                                     f"Esri imagery from {cap['date']} predates {earliest}" if cap
                                     else "no Esri imagery date at zoom 18"),
                                 "imagery_date": cap["date"].isoformat() if cap else "",
                                 "date_screened": date.today().isoformat()})
                continue
            side = args.dense_side_m if cell.bldg_density_km2 >= DENSE_BLDG_KM2 else args.side_m
            bbox = (cell.lon0, cell.lat0, cell.lon0 + 0.1, cell.lat0 + 0.1)
            pts = fetch_vida_building_points(bbox, iso3, con=con)
            if pts.empty:
                continue
            wins = window_densities(pts["lon"].to_numpy(), pts["lat"].to_numpy(), cell, side)
            if not len(wins):
                continue
            area_km2 = side * side / 1e6
            dens = wins[:, 2] / area_km2
            ok = (wins[:, 2] >= MIN_BOX_BUILDINGS) & (np.abs(np.log(np.maximum(dens, 1e-9) / cell.bldg_density_km2))
                                                      <= math.log(OWN_DENSITY_TOL))
            idx = np.flatnonzero(ok)
            if not len(idx):
                continue
            cx, cy, _ = wins[rng.choice(idx)]
            poly = geodesic_square(float(cy), float(cx), side)
            near = [GEOD.inv(cx, cy, b.centroid.x, b.centroid.y)[2] / 1000 for b in taken]
            if (any(d < args.min_spacing_km for d in near)
                    or any(b.intersects(poly) for b in taken + others)):
                continue
            district, region = admin.lookup(cx, cy)
            passed, img = imagery_gate(poly, earliest)
            if not passed:
                screened.append({"aoi": aoi, "stratum": k + 1, "cell": cell.cell, "lat": round(cy, 6),
                                 "lon": round(cx, 6), "reason": img["reason"],
                                 "imagery_date": img.get("imagery_date", ""),
                                 "date_screened": date.today().isoformat()})
                continue
            w, s, e, n = poly.bounds
            sel = pts[(pts.lon >= w) & (pts.lon <= e) & (pts.lat >= s) & (pts.lat <= n)]
            geo_km2 = abs(GEOD.geometry_area_perimeter(poly)[0]) / 1e6
            tag = f"{int(side // 1000)}km" if side % 1000 == 0 else f"{side:g}m"
            base = f"{slug(district or region or aoi)}_s{k + 1}"
            stem = next(f"{base}{x}_calib_{tag}" for x in ("", *"bcdefgh")
                        if f"{base}{x}_calib_{tag}" not in {c['stem'] for c in picked})
            props = {
                "quadrat_id": stem,
                "stratum": label,
                "location": ", ".join(x for x in (district, region, country) if x),
                "province": region,
                "size_km2": round(geo_km2, 4),
                "center": f"[{cx:.6f} {cy:.6f}]",
                "shape": "square (geodesic)",
                "side_m": float(side),
                "source_grid_cell": cell.cell,
                "source_grid_density_bldg_km2": round(float(cell.bldg_density_km2), 2),
                "source_grid_n_buildings": int(cell.n_buildings),
                "own_n_buildings": int(len(sel)),
                "own_density_bldg_km2": round(len(sel) / geo_km2, 2),
                **img,
                "imagery_checked": True,
                "selection": f"{SELECTION}, seed {seed}",
                "note": (f"Drawn by scripts/propose_calibration_candidates.py: a building-weighted "
                         f"random cell from {label}, then a {side / 1000:g} km window inside it "
                         f"whose own density ({len(sel) / geo_km2:,.0f} bldg/km2, VIDA) is within "
                         f"25% of the cell's ({cell.bldg_density_km2:,.0f}). Esri imagery here "
                         f"dates from {img['imagery_date']} (oldest of centre and corners), "
                         f"no older than {earliest} for a composite starting {win0}. Not "
                         "checked on the ground: confirm it is mappable before you start, and "
                         "do not move it toward visible solar."),
            }
            picked.append({"stem": stem, "k": k + 1, "props": props, "geometry": mapping(poly)})
            taken.append(poly)
            if region:
                used_regions.add(region)
            got += 1
        if got < args.per_stratum:
            print(f"  {aoi}: stratum {k + 1} short, {got} of {args.per_stratum} after {MAX_ATTEMPTS} draws")

    print(f"{aoi}: {len(picked)} candidates, {len(screened)} draws screened out on imagery "
          f"(seed {seed}, imagery no older than {earliest})")
    for c in picked:
        p = c["props"]
        print(f"  {c['stem']:<42} s{c['k']}  cell {p['source_grid_density_bldg_km2']:>8,.1f}"
              f"  box {p['own_density_bldg_km2']:>8,.1f} bldg/km2  {p['own_n_buildings']:>6} bldg"
              f"  Esri {p['imagery_date']} {p['imagery_res_m']} m  {p['location']}")
    if args.dry_run:
        return picked

    out_dir.mkdir(parents=True, exist_ok=True)
    for p in auto:
        p.unlink()
    for c in picked:
        doc = {"type": "FeatureCollection", "name": f"{c['stem']}_candidate",
               "features": [{"type": "Feature", "properties": c["props"], "geometry": c["geometry"]}]}
        (out_dir / f"{c['stem']}_candidate.geojson").write_text(json.dumps(doc, indent=2) + "\n")
    if screened:
        log = out_dir / "screened_out.csv"
        new = not log.exists()
        with log.open("a", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(screened[0]))
            if new:
                wr.writeheader()
            wr.writerows(screened)
    print(f"  wrote {len(picked)} files to {out_dir}")
    return picked


def propose_priority(aoi: str, args) -> list[dict]:
    """The `--n-priority` boxes a mapper should start with: dense, with the most roof in
    large buildings, where rooftop PV is most likely and a first area pays off fastest.

    Purposive, unlike `propose`, and recorded as such on every box: a sample of the
    country's densest, most industrial districts runs at a higher PV base rate than the
    country, which is what the per-density-stratum coverage ratio and `rate_ratio` exist to
    absorb (Pakistan's first quadrats were chosen the same way). What keeps it honest is
    what it is chosen ON: building footprints only. No solar layer, OSM or model, is read,
    so a box is never placed where solar is already visible. Deterministic: the best box
    by the rule, no seed.

    1. **Pool**: cells in the densest `PRIORITY_STRATA` of the `--strata` equal-building
       bands, i.e. where the densest quarter of the country's buildings sit.
    2. **Cells scanned**: the `PRIORITY_CELLS` with the most roof area per km2 (density and
       big roofs both raise it) and the `PRIORITY_CELLS` with the largest mean footprint
       (industrial estates), after a cheap imagery check at the cell centre.
    3. **Box**: every `--dense-side-m` window of the cell (1 km, whatever the density: a
       first area should be one a newcomer can finish), scored by the roof area in
       buildings of at least `LARGE_ROOF_M2`; a window must itself be as dense as the
       pool's lower edge.
    4. **Pick** the best-scoring windows across cells, `--min-spacing-km` apart from each
       other and from registered quadrats, `CAND_SPACING_KM` from (and never overlapping)
       the sampled candidates, through the same Esri imagery gate as `propose`.
    """
    import duckdb
    from shapely.geometry import mapping

    from earthpv.buildings import fetch_vida_building_points
    from earthpv.roofclf import load_boundary

    cfg = Settings.load().aois.get(aoi) or {}
    div = cfg.get("division") or {}
    iso3, country = div.get("iso3"), div.get("name")
    if not iso3 or not cfg.get("compose_window"):
        raise SystemExit(f"{aoi}: configs/aoi.yaml needs division.iso3 and compose_window")
    win0 = date.fromisoformat(cfg["compose_window"][0])
    months = win0.year * 12 + win0.month - 1 - args.max_imagery_lag_months
    earliest = date(months // 12, months % 12 + 1, 1)

    home = LABELS if aoi == FLAT_AOI else LABELS / aoi
    out_dir = home / "candidate_quadrats"
    files = sorted(out_dir.glob("*_candidate.geojson"))
    sel_of = {p: json.loads(p.read_text())["features"][0]["properties"].get("selection", "")
              for p in files}
    mine = [p for p in files if sel_of[p].startswith(PRIORITY_SELECTION)]
    if mine and not args.replace:
        print(f"{aoi}: {len(mine)} priority candidates already exist in {out_dir}; "
              "pass --replace to redraw them")
        return []
    others = [load_boundary(p) for p in files if p not in mine]

    grid = pd.read_parquet(args.grid or grid_path(aoi), columns=[
        "cell", "lon0", "lat0", "n_buildings", "bldg_density_km2", "roof_area_m2", "cell_area_km2"])
    grid = grid[grid["n_buildings"] >= MIN_BOX_BUILDINGS].reset_index(drop=True)
    edges = strata_edges(grid, args.strata)
    floor = float(edges[args.strata - PRIORITY_STRATA])
    pool = grid[grid["bldg_density_km2"] >= floor].copy()
    pool["roof_cover"] = pool["roof_area_m2"] / (pool["cell_area_km2"] * 1e6)
    pool["mean_roof_m2"] = pool["roof_area_m2"] / pool["n_buildings"]
    scan = pd.concat([pool.nlargest(PRIORITY_CELLS, "roof_cover"),
                      pool.nlargest(PRIORITY_CELLS, "mean_roof_m2")]).drop_duplicates("cell")
    criterion = (f"densest {PRIORITY_STRATA} of {args.strata} density bands (cells from "
                 f"{floor:,.0f} bldg/km2), most roof area in buildings of "
                 f"{LARGE_ROOF_M2:,.0f} m2 or more")

    admin = Admin(aoi)
    con = duckdb.connect()
    con.execute("SET parquet_metadata_cache=true;")  # India: 105k row groups per scan
    screened, windows = [], []
    for cell in scan.itertuples():
        ccx, ccy = cell.lon0 + 0.05, cell.lat0 + 0.05
        cap = esri_capture(ccx, ccy)
        if cap is None or cap["date"] < earliest:
            screened.append({"aoi": aoi, "stratum": "priority", "cell": cell.cell, "lat": round(ccy, 6),
                             "lon": round(ccx, 6), "reason": "cell centre: " + (
                                 f"Esri imagery from {cap['date']} predates {earliest}" if cap
                                 else "no Esri imagery date at zoom 18"),
                             "imagery_date": cap["date"].isoformat() if cap else "",
                             "date_screened": date.today().isoformat()})
            continue
        # Always the dense-urban size: a first area should be one a newcomer can finish.
        side = args.dense_side_m
        pts = fetch_vida_building_points((cell.lon0, cell.lat0, cell.lon0 + 0.1, cell.lat0 + 0.1),
                                         iso3, con=con, with_area=True)
        if pts.empty:
            continue
        area = pts["area_m2"].to_numpy(dtype=float)
        big = area >= LARGE_ROOF_M2
        wins = window_densities(pts["lon"].to_numpy(), pts["lat"].to_numpy(), cell, side,
                                weights=(big.astype(float), np.where(big, area, 0.0), area))
        if not len(wins):
            continue
        ok = (wins[:, 2] >= MIN_BOX_BUILDINGS) & (wins[:, 2] / (side * side / 1e6) >= floor)
        if not ok.any():
            continue
        i = np.flatnonzero(ok)[np.argmax(wins[ok, 4])]
        windows.append((wins[i], cell, side))
    windows.sort(key=lambda w: (-w[0][4], -w[0][2]))

    taken = existing_boxes(home)
    picked = []
    for (cx, cy, _, _, large_area, _), cell, side in windows:
        if len(picked) == args.n_priority or large_area <= 0:
            break
        poly = geodesic_square(float(cy), float(cx), side)
        too_close = [(b, args.min_spacing_km) for b in taken] + [(b, CAND_SPACING_KM) for b in others]
        if any(b.intersects(poly) or GEOD.inv(cx, cy, b.centroid.x, b.centroid.y)[2] / 1000 < km
               for b, km in too_close):
            continue
        passed, img = imagery_gate(poly, earliest)
        if not passed:
            screened.append({"aoi": aoi, "stratum": "priority", "cell": cell.cell, "lat": round(cy, 6),
                             "lon": round(cx, 6), "reason": img["reason"],
                             "imagery_date": img.get("imagery_date", ""),
                             "date_screened": date.today().isoformat()})
            continue
        district, region = admin.lookup(cx, cy)
        inside = fetch_vida_building_points(poly.bounds, iso3, con=con, with_area=True)
        big = inside[inside["area_m2"] >= LARGE_ROOF_M2]
        geo_km2 = abs(GEOD.geometry_area_perimeter(poly)[0]) / 1e6
        tag = f"{int(side // 1000)}km" if side % 1000 == 0 else f"{side:g}m"
        base = f"{slug(district or region or aoi)}_priority"
        used = {c["stem"] for c in picked} | {p.name[: -len("_candidate.geojson")] for p in files
                                              if p not in mine}
        stem = next(f"{base}{x}_calib_{tag}" for x in ("", *"bcdefgh")
                    if f"{base}{x}_calib_{tag}" not in used)
        dens = len(inside) / geo_km2
        props = {
            "quadrat_id": stem,
            "criterion": criterion,
            "location": ", ".join(x for x in (district, region, country) if x),
            "province": region,
            "size_km2": round(geo_km2, 4),
            "center": f"[{cx:.6f} {cy:.6f}]",
            "shape": "square (geodesic)",
            "side_m": float(side),
            "source_grid_cell": cell.cell,
            "source_grid_density_bldg_km2": round(float(cell.bldg_density_km2), 2),
            "source_grid_n_buildings": int(cell.n_buildings),
            "own_n_buildings": int(len(inside)),
            "own_density_bldg_km2": round(dens, 2),
            "own_large_buildings": int(len(big)),
            "own_large_roof_m2": round(float(big["area_m2"].sum())),
            "own_roof_cover": round(float(inside["area_m2"].sum()) / (geo_km2 * 1e6), 3),
            **img,
            "imagery_checked": True,
            "selection": PRIORITY_SELECTION,
            "note": (f"Chosen by scripts/propose_calibration_candidates.py --priority as a place "
                     f"to start: among the cells holding {country or aoi}'s densest quarter of "
                     f"buildings (from {floor:,.0f} bldg/km2), the {side / 1000:g} km window with "
                     f"the most roof area in buildings of {LARGE_ROOF_M2:,.0f} m2 or more "
                     f"({len(big):,} such buildings, {big['area_m2'].sum() / 1e4:,.1f} ha of roof; "
                     f"{len(inside):,} buildings in all, {dens:,.0f} per km2, VIDA). Large and "
                     f"dense roofs are where rooftop solar is most likely; the box was chosen on "
                     f"buildings only, never on solar seen there. Esri imagery here dates from "
                     f"{img['imagery_date']} (oldest of centre and corners), no older than "
                     f"{earliest} for a composite starting {win0}. Not checked on the ground: "
                     "confirm it is mappable before you start, and do not move it toward "
                     "visible solar."),
        }
        picked.append({"stem": stem, "props": props, "geometry": mapping(poly)})
        taken.append(poly)

    print(f"{aoi}: {len(picked)} priority candidates from {len(windows)} scanned cells, "
          f"{len(screened)} screened out on imagery (pool from {floor:,.0f} bldg/km2)")
    for c in picked:
        p = c["props"]
        print(f"  {c['stem']:<44} box {p['own_density_bldg_km2']:>7,.0f} bldg/km2"
              f"  {p['own_large_buildings']:>4} large, {p['own_large_roof_m2'] / 1e4:>6,.1f} ha"
              f"  cover {p['own_roof_cover']:.2f}  Esri {p['imagery_date']}  {p['location']}")
    if len(picked) < args.n_priority:
        print(f"  {aoi}: short, {len(picked)} of {args.n_priority}")
    if args.dry_run:
        return picked

    out_dir.mkdir(parents=True, exist_ok=True)
    for p in mine:
        p.unlink()
    for c in picked:
        doc = {"type": "FeatureCollection", "name": f"{c['stem']}_candidate",
               "features": [{"type": "Feature", "properties": c["props"], "geometry": c["geometry"]}]}
        (out_dir / f"{c['stem']}_candidate.geojson").write_text(json.dumps(doc, indent=2) + "\n")
    if screened:
        log = out_dir / "screened_out.csv"
        new = not log.exists()
        with log.open("a", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(screened[0]))
            if new:
                wr.writeheader()
            wr.writerows(screened)
    print(f"  wrote {len(picked)} files to {out_dir}")
    return picked


def propose_farmland(aoi: str, args) -> list[dict]:
    """Farm calibration areas for `roofclf_ground`: `propose`'s recipe on cropland.

    Strata are bands of equal cropland AREA by cell cropland share; a cell is drawn
    cropland-weighted; the box is a `--farm-side-m` window whose own cropland share (ESA
    WorldCover at 100 m) is within `OWN_CROP_TOL` of the cell's. Chosen on land cover
    only, never on a solar layer, so a box is never placed where PV is already visible.
    """
    import duckdb
    from shapely.geometry import mapping

    from earthpv.buildings import _iso3_for, fetch_vida_building_points
    from earthpv.roofclf import load_boundary
    from earthpv.worldcover import landcover_points

    cfg = Settings.load().aois.get(aoi) or {}
    div = cfg.get("division") or {}
    # Pakistan predates `division.iso3` and `compose_window`: the ISO2 map covers the first,
    # `--window-start` the second (its composites carry no window tag, see the flag's help).
    iso3, country = _iso3_for(cfg), div.get("name")
    start = (cfg.get("compose_window") or [args.window_start])[0]
    if not iso3 or not start:
        raise SystemExit(f"{aoi}: configs/aoi.yaml needs division.iso3 and compose_window "
                         "(or pass --window-start)")
    win0 = date.fromisoformat(start)
    months = win0.year * 12 + win0.month - 1 - args.max_imagery_lag_months
    earliest = date(months // 12, months % 12 + 1, 1)

    home = LABELS if aoi == FLAT_AOI else LABELS / aoi
    out_dir = home / "candidate_quadrats"
    files = sorted(out_dir.glob("*_candidate.geojson"))
    mine = [p for p in files
            if FARM_SELECTION in json.loads(p.read_text())["features"][0]["properties"].get("selection", "")]
    if mine and not args.replace:
        print(f"{aoi}: {len(mine)} farm candidates already exist in {out_dir}; "
              "pass --replace to redraw them")
        return []
    others = [load_boundary(p) for p in files if p not in mine]

    grid = pd.read_parquet(args.grid or grid_path(aoi), columns=["cell", "lon0", "lat0", "n_buildings"])
    grid = grid.merge(cropland_table(aoi, grid), on="cell", how="left").fillna({"crop_frac": 0.0, "crop_km2": 0.0})
    grid = grid[grid["crop_frac"] >= args.farm_min_crop].reset_index(drop=True)
    if grid.empty:
        print(f"{aoi}: no imaged cell has {args.farm_min_crop:.0%} cropland or more")
        return []
    edges = strata_edges(grid, args.strata, value="crop_frac", weight="crop_km2")
    grid["stratum"] = np.searchsorted(edges, grid["crop_frac"], side="right") - 1
    # A seed of its own: the building draw's seed would otherwise walk the same random
    # sequence over a differently-sorted cell list, which is not a bias but is a needless
    # coupling between two draws that should be independent.
    seed = args.seed if args.seed is not None else zlib.crc32(f"{aoi}:farmland".encode()) % 100_000
    rng = np.random.default_rng(seed)
    admin = Admin(aoi)
    taken = existing_boxes(home)
    used_regions: set = set()
    picked, screened = [], []
    con = duckdb.connect()
    con.execute("SET parquet_metadata_cache=true;")
    side = args.farm_side_m

    for k in range(args.strata):
        band = grid[grid["stratum"] == k]
        lo, hi = edges[k], edges[k + 1]
        label = (f"cropland stratum {k + 1} of {args.strata}: "
                 + (f"{lo:.1%}-{hi:.1%}" if math.isfinite(hi) else f">{lo:.1%}") + " cropland (cell)")
        got = 0
        for attempt in range(MAX_ATTEMPTS):
            if got == args.per_stratum or band.empty:
                break
            cell = band.iloc[rng.choice(len(band), p=band["crop_km2"] / band["crop_km2"].sum())]
            ccx, ccy = cell.lon0 + 0.05, cell.lat0 + 0.05
            _, region0 = admin.lookup(ccx, ccy)
            if region0 and region0 in used_regions and attempt < MAX_ATTEMPTS // 2:
                continue
            if any(GEOD.inv(ccx, ccy, b.centroid.x, b.centroid.y)[2] / 1000 < args.min_spacing_km - 8
                   for b in taken):
                continue
            cap = esri_capture(ccx, ccy)
            if cap is None or cap["date"] < earliest:
                screened.append({"aoi": aoi, "stratum": f"farm {k + 1}", "cell": cell.cell,
                                 "lat": round(ccy, 6), "lon": round(ccx, 6), "reason": "cell centre: " + (
                                     f"Esri imagery from {cap['date']} predates {earliest}" if cap
                                     else "no Esri imagery date at zoom 18"),
                                 "imagery_date": cap["date"].isoformat() if cap else "",
                                 "date_screened": date.today().isoformat()})
                continue
            lon, lat, crop = landcover_points((cell.lon0, cell.lat0, cell.lon0 + 0.1, cell.lat0 + 0.1))
            if not crop.any():
                continue
            wins = window_densities(lon, lat, cell, side, weights=(crop.astype(float),))
            if not len(wins):
                continue
            n_px, n_crop = wins[:, 2], wins[:, 3]
            share = n_crop / np.maximum(n_px, 1)
            ok = ((n_px >= MIN_WINDOW_COVER * n_px.max()) & (share > 0)
                  & (np.abs(np.log(np.maximum(share, 1e-9) / cell.crop_frac)) <= math.log(OWN_CROP_TOL)))
            idx = np.flatnonzero(ok)
            if not len(idx):
                continue
            j = rng.choice(idx)
            cx, cy, own_share = wins[j, 0], wins[j, 1], float(share[j])
            poly = geodesic_square(float(cy), float(cx), side)
            near = [GEOD.inv(cx, cy, b.centroid.x, b.centroid.y)[2] / 1000 for b in taken]
            if (any(d < args.min_spacing_km for d in near)
                    or any(b.intersects(poly) for b in taken + others)):
                continue
            passed, img = imagery_gate(poly, earliest)
            if not passed:
                screened.append({"aoi": aoi, "stratum": f"farm {k + 1}", "cell": cell.cell,
                                 "lat": round(cy, 6), "lon": round(cx, 6), "reason": img["reason"],
                                 "imagery_date": img.get("imagery_date", ""),
                                 "date_screened": date.today().isoformat()})
                continue
            district, region = admin.lookup(cx, cy)
            geo_km2 = abs(GEOD.geometry_area_perimeter(poly)[0]) / 1e6
            n_bldg = len(fetch_vida_building_points(poly.bounds, iso3, con=con))
            tag = f"{int(side // 1000)}km" if side % 1000 == 0 else f"{side:g}m"
            base = f"{slug(district or region or aoi)}_f{k + 1}"
            used = {c["stem"] for c in picked} | {p.name[: -len("_candidate.geojson")] for p in files
                                                  if p not in mine}
            stem = next(f"{base}{x}_farm_calib_{tag}" for x in ("", *"bcdefgh")
                        if f"{base}{x}_farm_calib_{tag}" not in used)
            props = {
                "quadrat_id": stem,
                "stratum": label,
                "location": ", ".join(x for x in (district, region, country) if x),
                "province": region,
                "size_km2": round(geo_km2, 4),
                "center": f"[{cx:.6f} {cy:.6f}]",
                "shape": "square (geodesic)",
                "side_m": float(side),
                "source_grid_cell": cell.cell,
                "source_grid_crop_frac": round(float(cell.crop_frac), 4),
                "own_crop_frac": round(own_share, 4),
                "own_n_buildings": int(n_bldg),
                "own_density_bldg_km2": round(n_bldg / geo_km2, 2),
                **img,
                "imagery_checked": True,
                "selection": f"{FARM_SELECTION}, seed {seed}",
                "detector": "roofclf_ground",
                "note": (f"Farm calibration area for the ground-PV detector, drawn by "
                         f"scripts/propose_calibration_candidates.py --farmland: a cropland-weighted "
                         f"random cell from {label}, then a {side / 1000:g} km window inside it whose "
                         f"own cropland share ({own_share:.1%}, ESA WorldCover) is within 25% of the "
                         f"cell's ({cell.crop_frac:.1%}). Map ALL solar inside, ground and rooftop, "
                         f"tracing the panels rather than the fence. Esri imagery here dates from "
                         f"{img['imagery_date']} (oldest of centre and corners), no older than "
                         f"{earliest} for a composite starting {win0}. Register with "
                         "new_calibration_quadrat.py --farm. Not checked on the ground: confirm it "
                         "is mappable before you start, and do not move it toward visible solar."),
            }
            picked.append({"stem": stem, "k": k + 1, "props": props, "geometry": mapping(poly)})
            taken.append(poly)
            if region:
                used_regions.add(region)
            got += 1
        if got < args.per_stratum:
            print(f"  {aoi}: farm stratum {k + 1} short, {got} of {args.per_stratum} after {MAX_ATTEMPTS} draws")

    print(f"{aoi}: {len(picked)} farm candidates, {len(screened)} draws screened out on imagery "
          f"(seed {seed}, imagery no older than {earliest})")
    for c in picked:
        p = c["props"]
        print(f"  {c['stem']:<44} f{c['k']}  cell {p['source_grid_crop_frac']:>6.1%}"
              f"  box {p['own_crop_frac']:>6.1%} cropland  {p['own_n_buildings']:>6} bldg"
              f"  Esri {p['imagery_date']} {p['imagery_res_m']} m  {p['location']}")
    if args.dry_run:
        return picked

    out_dir.mkdir(parents=True, exist_ok=True)
    for p in mine:
        p.unlink()
    for c in picked:
        doc = {"type": "FeatureCollection", "name": f"{c['stem']}_candidate",
               "features": [{"type": "Feature", "properties": c["props"], "geometry": c["geometry"]}]}
        (out_dir / f"{c['stem']}_candidate.geojson").write_text(json.dumps(doc, indent=2) + "\n")
    if screened:
        log = out_dir / "screened_out.csv"
        new = not log.exists()
        with log.open("a", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(screened[0]))
            if new:
                wr.writeheader()
            wr.writerows(screened)
    print(f"  wrote {len(picked)} files to {out_dir}")
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--aoi", nargs="+", help="AOI(s) as in configs/aoi.yaml")
    who.add_argument("--bronze", action="store_true", help="every AOI whose atlas is Bronze")
    ap.add_argument("--strata", type=int, default=8, help="density bands of equal building share")
    ap.add_argument("--per-stratum", type=int, default=1)
    ap.add_argument("--side-m", type=float, default=2000.0)
    ap.add_argument("--dense-side-m", type=float, default=1000.0,
                    help=f"box side in cells denser than {DENSE_BLDG_KM2:g} bldg/km2")
    ap.add_argument("--min-spacing-km", type=float, default=20.0)
    ap.add_argument("--max-imagery-lag-months", type=int, default=12,
                    help="oldest acceptable Esri capture, in months before the compose window start")
    ap.add_argument("--seed", type=int, default=None, help="default: derived from the AOI name")
    ap.add_argument("--grid", type=Path, default=None, help="density grid, for a single --aoi")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--priority", action="store_true",
                      help="draw the purposive start-here boxes (dense, large roofs) instead")
    mode.add_argument("--farmland", action="store_true",
                      help="draw farm calibration areas for the ground-PV detector, stratified "
                           "by cropland instead of buildings")
    ap.add_argument("--n-priority", type=int, default=2, help="start-here boxes per AOI")
    ap.add_argument("--farm-side-m", type=float, default=3000.0,
                    help="--farmland box side (farm PV is sparse: about 2 arrays per km2 in 'Amran)")
    ap.add_argument("--farm-min-crop", type=float, default=0.01,
                    help="--farmland: skip cells with less cropland than this share")
    ap.add_argument("--window-start", default=None,
                    help="--farmland, for an AOI with no compose_window in configs/aoi.yaml: the "
                         "start of the composite window the imagery gate measures against. "
                         "Pakistan's composites were built 2026-07-04 with compose's default then, "
                         "2025-11-01, and carry no window tag, so this is the recorded default, "
                         "not a value read from the files")
    ap.add_argument("--replace", action="store_true",
                    help="redraw an AOI's sampled (or, with --priority / --farmland, those) candidates")
    ap.add_argument("--dry-run", action="store_true", help="draw and report, write nothing")
    args = ap.parse_args()
    os.chdir(ROOT)
    aois = bronze_aois() if args.bronze else args.aoi
    if args.grid and len(aois) != 1:
        raise SystemExit("--grid applies to a single --aoi")
    for aoi in aois:
        (propose_priority if args.priority else propose_farmland if args.farmland else propose)(aoi, args)
    if not args.dry_run:
        print("next: pixi run calib-publish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
