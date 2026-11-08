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
i18n-iso-countries@7.14.0/codes.json.
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
EARTH = LANDING / "earth.json"
INDEX = DOCS / "index.md"
GLOBAL_PV = REPO / "configs" / "external" / "global_pv_capacity.yaml"

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
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        shapes = [Polygon(ring(p[0])) for p in polys]
        west, south, east, north = MultiPolygon(shapes).bounds
        name = g["properties"]["name"]
        features.append({
            "n": FULL_NAMES.get(name, name),
            "i": iso3.get(str(g.get("id", "")).zfill(3), ""),
            # The outer box, rounded outward to a tenth of a degree, for the commands on
            # the contribute page.
            "b": [math.floor(west * 10) / 10, math.floor(south * 10) / 10,
                  math.ceil(east * 10) / 10, math.ceil(north * 10) / 10],
            "p": polys,
        })

    coded = []
    for pts in simple:
        flat, px, py = [], 0, 0
        for lon, lat in pts:
            x, y = round(lon * 100), round(lat * 100)
            flat += [x - px, y - py]
            px, py = x, y
        coded.append(flat)
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


def _atlas_facts(totals: dict) -> dict:
    """What the globe's hover card adds about one atlas, from its page's own totals."""
    return {
        "gwh": (totals.get("generation") or {}).get("gwh"),
        "imagery": (totals.get("imagery_dates") or {}).get("median"),
    }


def write() -> None:
    """Rewrite earth.json and docs/index.md from the published atlases."""
    world = json.loads(WORLD.read_text())
    arcs = _decode_arcs(world)
    by_name = {f["n"]: f for f in world["features"]}
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
        if feature is None:
            raise SystemExit(f"{country}: not a country name in {WORLD.name}")
        parts = _processed_parts(feature, arcs, lons[covered], lats[covered])
        if not parts:
            raise SystemExit(f"{country}: no processed cell inside its outline")
        left_out = len(feature["p"]) - len(parts)
        if left_out:
            print(f"  {country}: {left_out} of {len(feature['p'])} polygons hold no processed "
                  "cell and stay in pencil")
        atlases.append({
            "name": country,
            "iso3": feature["i"],
            "href": f"{stem}/",
            "tier": tier_of(html),
            "best": round(totals["mwp_best"], 1),
            "verified": round(totals["mwp_verified"], 1),
            "parts": parts,
            "facts": _atlas_facts(totals),
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
        "atlases": atlases,
        "processed": [[lat, *row] for lat, row in rows.items()],
        "pv": [[lat, *row] for lat, row in pv_rows.items()],
    }
    EARTH.write_text(json.dumps(earth, separators=(",", ":")))
    INDEX.write_text(_index_md(atlases, best_mwp, verified_mwp, ref))
    share = best_mwp / 1000 / ref["gw"]
    print(f"wrote {EARTH.name} ({EARTH.stat().st_size / 1e3:,.0f} kB, {len(processed):,} processed "
          f"bins, {len(capacity):,} with PV) and {INDEX.name}: Best {best_mwp / 1000:,.1f} GW, "
          f"Verified {verified_mwp / 1000:,.1f} GW, {share:.1%} of {ref['gw']:,} GW")


def _index_md(atlases: list[dict], best_mwp: float, verified_mwp: float, ref: dict) -> str:
    """The page's text: the figures and one link per atlas, also what shows without scripts."""
    share = best_mwp / 1000 / ref["gw"]
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

<p class="stats"><span>{best_mwp / 1000:,.1f} GW best estimate in {len(atlases)} countries</span>
<span>{verified_mwp / 1000:,.1f} GW verified</span>
<span>{share:.1%} of the world\'s installed solar</span></p>

<div class="atlas-links" markdown>

{links}

</div>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-map", type=Path, help="world-atlas countries-50m.json")
    ap.add_argument("--iso-codes", type=Path, help="i18n-iso-countries codes.json")
    a = ap.parse_args()
    if a.base_map:
        if not a.iso_codes:
            ap.error("--base-map needs --iso-codes")
        build_base_map(a.base_map, a.iso_codes)
    write()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
