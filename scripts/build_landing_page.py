"""Write the data behind the Electrify Earth landing page, the site root.

The page (`docs/overrides/landing.html`, `docs/assets/landing/`) draws the Earth as an ink
sketch: a country EarthPV has processed is inked in, every other country stays a pencil
line, and the brush stroke round the globe is the share of the world's installed PV the
atlases have reached so far. It shows only what the published atlases hold, so everything
here is read from the pages under `docs/assets/interactive/`, the same files
`scripts/build_atlas_pages.py` reads its tiers from. A new country therefore reaches the
globe with one row in `ATLASES` and a rerun; `build_atlas_pages.py` calls `write()` itself.

    python scripts/build_landing_page.py     # rewrites earth.json and docs/index.md

The world figure the stroke is measured against is `configs/external/global_pv_capacity.yaml`.

The base map, `docs/assets/landing/world.json`, changes only with the Natural Earth release.
It is rebuilt with:

    python scripts/build_landing_page.py \
        --base-map countries-50m.json --iso-codes codes.json

from world-atlas@2.0.2 (Natural Earth 1:50m, public domain) and
i18n-iso-countries@7.14.0/codes.json. On the way Crimea moves from Russia, where Natural
Earth's de facto borders put it, to Ukraine (`TRANSFERS`).

The United States and China are drawn and picked state by state, from
`docs/assets/landing/regions.json`, which is rebuilt with:

    python scripts/build_landing_page.py \
        --admin1 ne_50m_admin_1_states_provinces.geojson \
        --geoboundaries gb_USA_ADM1.geojson gb_CHN_ADM1.geojson

from Natural Earth 5.1.2 (public domain) and the geoBoundaries gbOpen ADM1 layers, which are
read only to check that every division name is spelled as the pipeline will look it up.

In dark mode the globe hangs in the real night sky behind it, from
`docs/assets/landing/stars.json`: the Yale Bright Star Catalogue down to V 6.5, rebuilt with:

    python scripts/build_landing_page.py --stars bsc5.dat

from the ASCII catalogue at http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz (5th revised
edition, Hoffleit and Warren 1991; also CDS V/50).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_atlas_pages import ATLASES, DOCS, REPO, tier_of  # noqa: E402

LANDING = DOCS / "assets" / "landing"
WORLD = LANDING / "world.json"
REGIONS = LANDING / "regions.json"
STARS = LANDING / "stars.json"
STARS_VMAX = 6.5
EARTH = LANDING / "earth.json"
INDEX = DOCS / "index.md"
GLOBAL_PV = REPO / "configs" / "external" / "global_pv_capacity.yaml"

# The globe's hover card draws an atlas's size chart in four bars (owner, 2026-11-11): its seven
# bins, as `atlas._size_bin_display_labels` writes them, merged at the 400 m2 floor and at 5,000
# and 100,000 m2. The first bar is everything below the floor, the capacity with no
# per-installation size (`size_unbinned_*`) included, and the card highlights it.
SIZE_GROUPS = (
    ("<400 m²", ("<100 m²", "100–400 m²")),
    ("400–5k m²", ("400–1k m²", "1k–5k m²")),
    ("5k–100k m²", ("5k–20k m²", "20k–100k m²")),
    ("≥100k m²", ("≥100k m²",)),
)

# The atlases' own resolution: one 0.1 degree cell, one entry. An off-lattice country's cells
# keep their one-to-one bins and move by at most half a cell.
BIN_DEG = 0.1
# Below this a cell reads as a trace of ink whatever its size, so the file need not say more.
MIN_CELL_MWP = 0.01
# A polygon of an atlas country counts as processed when a processed cell lies within this
# many degrees of it, so that coastal islets stay with their country and an overseas
# territory the atlas never imaged (French Guiana, Reunion) does not.
PART_BUFFER_DEG = 0.5
# Douglas-Peucker tolerance of the base map, in degrees: 80,617 points come down to about
# a third, which a browser can redraw on every frame of a turning globe.
SIMPLIFY_DEG = 0.035
# A state's outline is only picked and highlighted, never drawn as a coast, so it can be
# coarser; an islet below this many square degrees falls to the nearest state when picked.
REGION_SIMPLIFY_DEG = 0.05
REGION_MIN_PART_DEG2 = 0.01

# Countries too large for one atlas on one PC: the globe draws and picks them state by state.
SUBDIVIDED = {
    "United States of America": {"iso3": "USA", "label": "United States", "short": "US", "name_key": "name"},
    "China": {"iso3": "CHN", "label": "China", "short": "China", "name_key": "name_en"},
}
# The pipeline finds a state by its name in geoBoundaries ADM1 (`compose._aoi_boundary`), which
# spells China's provinces in full. Every province not listed here is "<name> Province".
CHINA_DIVISION = {
    "Beijing": "Beijing Municipality",
    "Chongqing": "Chongqing Municipality",
    "Shanghai": "Shanghai Municipality",
    "Tianjin": "Tianjin Municipality",
    "Guangdong": "Guangzhou Province",  # sic: geoBoundaries' own label for Guangdong
    "Guangxi": "Guangxi Zhuang Autonomous Region",
    "Inner Mongolia": "Inner Mongolia Autonomous Region",
    "Ningxia": "Ningxia Ningxia Hui Autonomous Region",  # sic
    "Tibet": "Tibet Autonomous Region",
    "Xinjiang": "Xinjiang Uyghur Autonomous Region",
}

# Natural Earth abbreviates long names for its own labels; the page and the commands on
# the contribute page want them in full.
FULL_NAMES = {
    "Antigua and Barb.": "Antigua and Barbuda",
    "Ashmore and Cartier Is.": "Ashmore and Cartier Islands",
    "Bosnia and Herz.": "Bosnia and Herzegovina",
    "Br. Indian Ocean Ter.": "British Indian Ocean Territory",
    "British Virgin Is.": "British Virgin Islands",
    "Cayman Is.": "Cayman Islands",
    "Central African Rep.": "Central African Republic",
    "Cook Is.": "Cook Islands",
    "Dem. Rep. Congo": "Democratic Republic of the Congo",
    "Dominican Rep.": "Dominican Republic",
    "Eq. Guinea": "Equatorial Guinea",
    "Faeroe Is.": "Faroe Islands",
    "Falkland Is.": "Falkland Islands",
    "Fr. Polynesia": "French Polynesia",
    "Fr. S. Antarctic Lands": "French Southern and Antarctic Lands",
    "Heard I. and McDonald Is.": "Heard Island and McDonald Islands",
    "Indian Ocean Ter.": "Indian Ocean Territories",
    "Marshall Is.": "Marshall Islands",
    "N. Cyprus": "Northern Cyprus",
    "N. Mariana Is.": "Northern Mariana Islands",
    "Pitcairn Is.": "Pitcairn Islands",
    "S. Geo. and the Is.": "South Georgia and the South Sandwich Islands",
    "S. Sudan": "South Sudan",
    "Solomon Is.": "Solomon Islands",
    "St. Kitts and Nevis": "Saint Kitts and Nevis",
    "St. Pierre and Miquelon": "Saint Pierre and Miquelon",
    "St. Vin. and Gren.": "Saint Vincent and the Grenadines",
    "Turks and Caicos Is.": "Turks and Caicos Islands",
    "U.S. Virgin Is.": "U.S. Virgin Islands",
    "W. Sahara": "Western Sahara",
    "Wallis and Futuna Is.": "Wallis and Futuna",
}

# Natural Earth draws the borders held on the ground, so world-atlas brings Crimea in as a
# polygon of Russia. The globe draws the internationally recognised border (UN General
# Assembly resolution 68/262): Crimea, Sevastopol with it, is part of Ukraine (owner,
# 2026-11-14). Each entry moves the donor's polygon holding the point to the receiver and
# dissolves the border between them, so no line is left across the Perekop isthmus.
TRANSFERS = (
    ("RUS", "UKR", (34.10, 44.95)),  # Crimea, by Simferopol
)


def _delta_coded(points) -> list[int]:
    """Lon/lat pairs as one flat list of deltas, in hundredths of a degree."""
    flat, px, py = [], 0, 0
    for lon, lat, *_ in points:
        x, y = round(lon * 100), round(lat * 100)
        flat += [x - px, y - py]
        px, py = x, y
    return flat


def _splice(receiver: list[int], donor: list[int]) -> tuple[list[int], set[int]]:
    """One ring from two rings that share a stretch of border, and the arcs that border held.

    The rings come from one topology, so the donor runs the shared arcs backwards. With the
    donor rotated to start on its shared run (Y to X) and the receiver to start on its own
    (X to Y), the union is the donor's other arcs (X to Y) followed by the receiver's (Y to X).
    """
    in_receiver = [~a in receiver for a in donor]
    k = sum(in_receiver)
    if not k or k == len(donor):
        raise ValueError("the rings share no border, or the donor ring is all border")
    starts = [i for i in range(len(donor)) if in_receiver[i] and not in_receiver[i - 1]]
    if len(starts) != 1:
        raise ValueError("the rings share more than one stretch of border")
    d = donor[starts[0]:] + donor[:starts[0]]
    run = [~a for a in reversed(d[:k])]
    for i in range(len(receiver)):
        u = receiver[i:] + receiver[:i]
        if u[:k] == run:
            return d[k:] + u[k:], {a if a >= 0 else ~a for a in d[:k]}
    raise ValueError("the shared border runs in a different order in the two rings")


def _apply_transfers(features: list[dict], arcs: list, outline) -> list:
    """Move each `TRANSFERS` polygon to its receiver and return the arcs left in use.

    `outline(ids)` is a ring of arc ids as a shapely Polygon. An arc no ring uses any more
    (the dissolved border) is dropped and every arc id renumbered, since the page draws every
    arc it is given as a coast or a border.
    """
    from shapely.geometry import Point

    by_iso = {f["i"]: f for f in features}
    for donor_iso, receiver_iso, (lon, lat) in TRANSFERS:
        donor, receiver = by_iso[donor_iso], by_iso[receiver_iso]
        hit = [k for k, p in enumerate(donor["p"]) if outline(p[0]).contains(Point(lon, lat))]
        if len(hit) != 1:
            raise ValueError(f"{len(hit)} polygons of {donor_iso} hold {lon}, {lat}")
        poly = donor["p"].pop(hit[0])
        if len(poly) != 1:
            raise ValueError(f"the {donor_iso} polygon at {lon}, {lat} has holes")
        for p in receiver["p"]:
            if any(~a in p[0] for a in poly[0]):
                p[0], _ = _splice(p[0], poly[0])
                break
        else:
            receiver["p"].append(poly)  # no shared border: it joins as an island
        print(f"moved the {donor_iso} polygon at {lon}, {lat} to {receiver_iso}")

    used = sorted({a if a >= 0 else ~a for f in features for p in f["p"] for r in p for a in r})
    new_id = {old: new for new, old in enumerate(used)}
    for f in features:
        for p in f["p"]:
            for r in p:
                r[:] = [new_id[a] if a >= 0 else ~new_id[~a] for a in r]
    if len(used) < len(arcs):
        print(f"dropped {len(arcs) - len(used)} arcs no ring uses any more")
    return [arcs[k] for k in used]


def build_regions(admin1_path: Path, geoboundaries: list[Path]) -> None:
    """Write regions.json: the states of `SUBDIVIDED`, and the borders between them."""
    from shapely.geometry import LineString, MultiLineString, MultiPolygon, shape
    from shapely.geometry.polygon import orient
    from shapely.ops import linemerge

    known = {f["properties"]["shapeName"] for p in geoboundaries
             for f in json.loads(p.read_text())["features"]}
    countries = {f["n"] for f in json.loads(WORLD.read_text())["features"]}
    features = json.loads(admin1_path.read_text())["features"]

    regions, lines = [], []
    for country, spec in SUBDIVIDED.items():
        units = []
        for f in features:
            if f["properties"]["admin"] != country:
                continue
            name = f["properties"][spec["name_key"]]
            division = CHINA_DIVISION.get(name, f"{name} Province") if spec["iso3"] == "CHN" else name
            if division not in known:
                raise SystemExit(f"{division}: not a name in the geoBoundaries layers given")
            units.append((name, division, f["properties"]["type_en"], shape(f["geometry"])))

        for name, division, kind, geom in units:
            parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
            largest = max(p.area for p in parts)
            kept = [p for p in parts if p.area >= REGION_MIN_PART_DEG2 or p.area == largest]
            # d3 reads a ring's winding on the sphere: exterior clockwise, or it fills the rest
            # of the Earth, and simplifying can flip it. Orient last.
            polys = [orient(p.simplify(REGION_SIMPLIFY_DEG, preserve_topology=True), sign=-1.0)
                     for p in kept]
            west, south, east, north = geom.bounds
            region = {
                # Georgia is also a country, and a name here has to identify one place.
                "n": f"{name} ({spec['short']})" if name in countries else name,
                "c": country,
                "i": spec["iso3"],
                "t": f"{kind}, {spec['label']}",
                "b": [math.floor(west * 10) / 10, math.floor(south * 10) / 10,
                      math.ceil(east * 10) / 10, math.ceil(north * 10) / 10],
                "d": division,
                "p": [[_delta_coded(r.coords) for r in [p.exterior, *p.interiors]] for p in polys],
            }
            regions.append(region)

        shared = []
        for i, (*_, a) in enumerate(units):
            for *_, b in units[i + 1:]:
                if a.intersects(b):
                    meet = a.boundary.intersection(b.boundary)
                    shared += [g for g in getattr(meet, "geoms", [meet])
                               if isinstance(g, LineString) and g.length > 0]
        merged = linemerge(MultiLineString(shared))
        for line in getattr(merged, "geoms", [merged]):
            lines.append(_delta_coded(line.simplify(SIMPLIFY_DEG).coords))

    REGIONS.write_text(json.dumps({"scale": 0.01, "lines": lines, "regions": regions},
                                  separators=(",", ":")))
    print(f"wrote {REGIONS.name}: {len(regions)} states and provinces, {len(lines)} border lines, "
          f"{REGIONS.stat().st_size / 1e3:,.0f} kB")


def build_stars(bsc_path: Path, vmax: float = STARS_VMAX) -> None:
    """Write stars.json, the night sky behind the globe in dark mode.

    Four integers a star, to keep the file small: RA and Dec (J2000) in units of 0.02 degree,
    about a third of a pixel at the page's scale, then V and B-V in tenths. A star with no
    B-V is written as 0.6, a sun-like white."""
    flat, n = [], 0
    for line in bsc_path.read_text(encoding="latin-1").splitlines():
        line = line.ljust(114)
        rah, vmag, bv = line[75:77], line[102:107].strip(), line[109:114].strip()
        if not rah.strip() or not vmag or float(vmag) > vmax:
            continue      # a few entries (novae, non-stellar objects) have no J2000 position
        ra = (int(rah) + int(line[77:79]) / 60 + float(line[79:83]) / 3600) * 15
        dec = int(line[84:86]) + int(line[86:88]) / 60 + int(line[88:90]) / 3600
        if line[83] == "-":
            dec = -dec
        flat += [round(ra / 0.02) % 18000, round(dec / 0.02), round(float(vmag) * 10),
                 round((float(bv) if bv else 0.6) * 10)]
        n += 1
    STARS.write_text(json.dumps({
        "source": "Yale Bright Star Catalogue, 5th revised edition (Hoffleit and Warren 1991)",
        "vmax": vmax,
        "units": "per star: RA and Dec J2000 in 0.02 degree, V x 10, B-V x 10",
        "stars": flat,
    }, separators=(",", ":")) + "\n")
    print(f"{STARS.relative_to(REPO)}: {n:,} stars to V {vmax}")


def build_base_map(topo_path: Path, codes_path: Path) -> None:
    """Simplify world-atlas's arcs in place and keep only what the page reads.

    Each arc is simplified on its own, end points fixed, so two countries sharing a
    border still share it exactly. Arcs are stored delta-coded in hundredths of a degree.
    """
    from shapely.geometry import LineString, MultiPolygon, Polygon

    topo = json.loads(topo_path.read_text())
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs: list[list[tuple[float, float]]] = []
    for raw in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in raw:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def simplify(pts):
        if len(pts) <= 3:
            return pts
        out = list(LineString(pts).simplify(SIMPLIFY_DEG, preserve_topology=False).coords)
        if pts[0] == pts[-1] and len(out) < 5:     # keep a small island a shape, not a line
            step = max(1, (len(pts) - 1) // 4)
            out = [*pts[::step][:4], pts[0]]
        return out

    simple = [simplify(a) for a in arcs]

    def ring(ids, source=None):
        source = source or simple
        out = []
        for i, a in enumerate(ids):
            seg = source[a] if a >= 0 else source[~a][::-1]
            out.extend(seg if i == 0 else seg[1:])
        return out

    def turning(pts):
        return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))

    # d3 reads a ring's winding on the sphere: a tiny ring simplified into the opposite
    # winding, or down to a sliver, becomes a polygon covering the rest of the Earth. Any
    # ring that lost its orientation keeps its original arcs.
    geometries = topo["objects"]["countries"]["geometries"]
    all_rings = [r for g in geometries
                 for p in (g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]) for r in p]
    restored = 0
    for ids in all_rings:
        before, after = turning(ring(ids, arcs)), turning(ring(ids))
        if len(ring(ids)) < 5 or before * after <= 0:
            for a in ids:
                k = a if a >= 0 else ~a
                restored += simple[k] is not arcs[k]
                simple[k] = arcs[k]
    print(f"kept {restored} arcs unsimplified to preserve ring winding")

    iso3 = {row[2]: row[1] for row in json.loads(codes_path.read_text())}
    features = []
    for g in topo["objects"]["countries"]["geometries"]:
        name = g["properties"]["name"]
        features.append({
            "n": FULL_NAMES.get(name, name),
            "i": iso3.get(str(g.get("id", "")).zfill(3), ""),
            "p": g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]],
        })
    simple = _apply_transfers(features, simple, lambda ids: Polygon(ring(ids)))
    for f in features:
        polys = f.pop("p")
        west, south, east, north = MultiPolygon([Polygon(ring(p[0])) for p in polys]).bounds
        # The outer box, rounded outward to a tenth of a degree, for the commands on the
        # contribute page.
        f["b"] = [math.floor(west * 10) / 10, math.floor(south * 10) / 10,
                  math.ceil(east * 10) / 10, math.ceil(north * 10) / 10]
        f["p"] = polys

    coded = [_delta_coded(pts) for pts in simple]
    LANDING.mkdir(parents=True, exist_ok=True)
    WORLD.write_text(json.dumps({"scale": 0.01, "arcs": coded, "features": features},
                                separators=(",", ":")))
    print(f"wrote {WORLD.name}: {len(features)} countries, {sum(map(len, simple)):,} points "
          f"(from {sum(map(len, arcs)):,}), {WORLD.stat().st_size / 1e3:,.0f} kB")


def _page_data(html: str) -> dict:
    import re

    text = (DOCS / "assets" / "interactive" / html).read_text()
    m = re.search(r'<script id="pv" type="application/json">(.*?)</script>', text, re.S)
    if not m:
        raise SystemExit(f"{html}: no data block; rebuild the atlas first")
    return json.loads(m.group(1))


def _ring_arcs(ids: list[int], arcs: list[list[tuple[float, float]]]):
    out: list[tuple[float, float]] = []
    for i, a in enumerate(ids):
        seg = arcs[a] if a >= 0 else arcs[~a][::-1]
        out.extend(seg if i == 0 else seg[1:])
    return out


def _decode_arcs(world: dict) -> list[list[tuple[float, float]]]:
    k = world["scale"]
    out = []
    for flat in world["arcs"]:
        x = y = 0
        pts = []
        for i in range(0, len(flat), 2):
            x += flat[i]
            y += flat[i + 1]
            pts.append((x * k, y * k))
        out.append(pts)
    return out


def _processed_parts(feature: dict, arcs, lons, lats) -> list[int]:
    """Which polygons of a country hold processed cells, as indices into `feature["p"]`."""
    from shapely import contains_xy
    from shapely.geometry import Polygon

    keep = []
    for i, poly in enumerate(feature["p"]):
        shape = Polygon(_ring_arcs(poly[0], arcs)).buffer(PART_BUFFER_DEG)
        if contains_xy(shape, lons, lats).any():
            keep.append(i)
    return keep


def _sig(value: float, digits: int = 2) -> float:
    if value <= 0:
        return 0
    return float(f"{value:.{digits}g}")


def _atlas_facts(data: dict) -> dict:
    """An atlas's size chart in the four bars of `SIZE_GROUPS`, MWp, and what it did not measure.

    From the page's own size chart: its bins, plus the capacity below the floor that has no
    per-installation size (`size_unbinned_*`), so the bars add up to the chart's total. Where a
    page did not measure something below the floor, the first bar is only a floor and the card
    has to say so.
    """
    totals = data["totals"]
    group_of = {label: i for i, (_, bins) in enumerate(SIZE_GROUPS) for label in bins}
    mwp = [0.0] * len(SIZE_GROUPS)
    mwp[0] = totals["size_unbinned_roof_mwp"] + totals["size_unbinned_ground_mwp"]
    for b in data["bins"]:
        if b["label"] not in group_of:
            raise SystemExit(f"size bin {b['label']!r} is in no SIZE_GROUPS bar")
        mwp[group_of[b["label"]]] += b["roof_mwp"] + b["ground_mwp"]
    return {
        "sizes": [round(v, 1) for v in mwp],
        "rooftop_measured": bool(totals["small_rooftop_status"]["measured"]),
        "farm_ground_measured": bool(totals["small_ground_status"]["measured"]),
    }


def write() -> None:
    """Rewrite earth.json and docs/index.md from the published atlases."""
    world = json.loads(WORLD.read_text())
    arcs = _decode_arcs(world)
    by_name = {f["n"]: f for f in world["features"]}
    regions = {r["n"]: r for r in json.loads(REGIONS.read_text())["regions"]}
    ref = yaml.safe_load(GLOBAL_PV.read_text())

    atlases = []
    processed: dict[tuple[int, int], int] = {}
    capacity: dict[tuple[int, int], float] = {}
    for stem, country, html, *_ in ATLASES:
        data = _page_data(html)
        totals = data["totals"]
        cols = {c: i for i, c in enumerate(data["cell_cols"])}
        cells = np.asarray(data["cells"], dtype=float)
        covered = cells[:, cols["model_covered"]] > 0
        lons = cells[:, cols["lon0"]] + 0.05
        lats = cells[:, cols["lat0"]] + 0.05
        best = cells[:, cols["mwp_best"]]
        for lon, lat, mwp, seen in zip(lons, lats, best, covered, strict=True):
            key = (math.floor(lon / BIN_DEG), math.floor(lat / BIN_DEG))
            if seen:
                processed[key] = 1
            if mwp > 0:
                capacity[key] = capacity.get(key, 0.0) + float(mwp)

        feature = by_name.get(country)
        region = regions.get(country)
        if feature is None and region is None:
            raise SystemExit(f"{country}: neither a country in {WORLD.name} nor a state in {REGIONS.name}")
        parts: list[int] = []    # a state is inked whole
        if feature is not None:
            parts = _processed_parts(feature, arcs, lons[covered], lats[covered])
            if not parts:
                raise SystemExit(f"{country}: no processed cell inside its outline")
            left_out = len(feature["p"]) - len(parts)
            if left_out:
                print(f"  {country}: {left_out} of {len(feature['p'])} polygons hold no processed "
                      "cell and stay in pencil")
        atlases.append({
            "name": country,
            "iso3": (feature or region)["i"],
            "href": f"{stem}/",
            "tier": tier_of(html),
            "best": round(totals["mwp_best"], 1),
            "verified": round(totals["mwp_verified"], 1),
            "parts": parts,
            "facts": _atlas_facts(data),
        })

    atlases.sort(key=lambda a: -a["best"])
    best_mwp = sum(a["best"] for a in atlases)
    verified_mwp = sum(a["verified"] for a in atlases)

    # Rows of constant latitude keep the file small: [lat, lon0, run, lon1, run, ...] for
    # the processed cells and [lat, dlon, mwp, dlon, mwp, ...] for the capacity, each dlon
    # counted from the entry before it in the row.
    rows: dict[int, list[int]] = {}
    for lon, lat in sorted(processed, key=lambda k: (k[1], k[0])):
        row = rows.setdefault(lat, [])
        if row and row[-2] + row[-1] == lon:
            row[-1] += 1
        else:
            row += [lon, 1]
    pv_rows: dict[int, list[float]] = {}
    previous: dict[int, int] = {}
    for (lon, lat), mwp in sorted(capacity.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        pv_rows.setdefault(lat, []).extend([lon - previous.get(lat, 0), _sig(max(mwp, MIN_CELL_MWP))])
        previous[lat] = lon

    earth = {
        "bin_deg": BIN_DEG,
        "world": ref,
        "best_mwp": round(best_mwp, 1),
        "verified_mwp": round(verified_mwp, 1),
        "size_labels": [label for label, _ in SIZE_GROUPS],
        "atlases": atlases,
        "processed": [[lat, *row] for lat, row in rows.items()],
        "pv": [[lat, *row] for lat, row in pv_rows.items()],
    }
    EARTH.write_text(json.dumps(earth, separators=(",", ":")))
    INDEX.write_text(_index_md(atlases))
    share = best_mwp / 1000 / ref["gw"]
    print(f"wrote {EARTH.name} ({EARTH.stat().st_size / 1e3:,.0f} kB, {len(processed):,} processed "
          f"bins, {len(capacity):,} with PV) and {INDEX.name}: Best {best_mwp / 1000:,.1f} GW, "
          f"Verified {verified_mwp / 1000:,.1f} GW, {share:.1%} of {ref['gw']:,} GW")


def _index_md(atlases: list[dict]) -> str:
    """The page's text: one link per atlas, also what shows without scripts. The figures are in
    the readout beside the globe, which landing.js fills from earth.json."""
    links = "\n".join(f'- [{a["name"]}]({a["href"].rstrip("/")}.md){{ data-iso="{a["iso3"]}" }}'
                      for a in sorted(atlases, key=lambda a: a["name"]))
    return f"""---
title: Electrify Earth
template: landing.html
n_atlases: {len(atlases)}
search:
  exclude: true
---

<!-- Generated by scripts/build_landing_page.py, from the published atlases. Do not edit. -->

<div class="atlas-links" markdown>

{links}

</div>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-map", type=Path, help="world-atlas countries-50m.json")
    ap.add_argument("--iso-codes", type=Path, help="i18n-iso-countries codes.json")
    ap.add_argument("--admin1", type=Path, help="Natural Earth ne_50m_admin_1_states_provinces.geojson")
    ap.add_argument("--geoboundaries", type=Path, nargs="+", help="gbOpen ADM1 GeoJSON, one per country")
    ap.add_argument("--stars", type=Path, help="Yale Bright Star Catalogue, ASCII bsc5.dat")
    a = ap.parse_args()
    if a.stars:
        build_stars(a.stars)
    if a.base_map:
        if not a.iso_codes:
            ap.error("--base-map needs --iso-codes")
        build_base_map(a.base_map, a.iso_codes)
    if a.admin1:
        if not a.geoboundaries:
            ap.error("--admin1 needs --geoboundaries")
        build_regions(a.admin1, a.geoboundaries)
    write()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
