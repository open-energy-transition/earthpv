"""Compare this project's evidence atlas against an independently produced national
rooftop-solar dataset, by spatial concentration rather than by magnitude.

## Why this comparison exists, and what it can and cannot show

Two models of the same country's rooftop solar rarely define "capacity" the same way --
different training data, different detection floors, different treatment of ground-mount.
Diffing their raw totals conflates a genuine disagreement about *where* solar is with an
arbitrary difference in *what counts*. Both datasets are therefore normalized to **percent
of the national total per spatial unit** before anything is compared. That sidesteps the
unit/scope mismatch and asks the answerable question -- "do the two estimates agree on
where PV concentrates" -- rather than the unanswerable one, "whose number is bigger."

**Neither dataset is treated as ground truth here.** This is a spatial-agreement check
between two independent, imperfect estimates, not a validation of one against the other.
A cell where this project's share is higher says only that these two particular models
disagree there -- it is not evidence this project is right and the other estimate is wrong,
or the reverse. Read `share_diff_pp` as "how differently the two models weight this cell,"
not as an error signal.

## Data sources

- **This project's estimate**: the per-cell `mwp_best` column already embedded in the
  published evidence atlas (`docs/assets/interactive/pakistan_evidence_atlas.html`'s inline
  `#pv` JSON block) -- read directly from that file rather than re-deriving it from
  `data/predictions/.../density`, so this comparison always reflects whatever is actually
  published, not a `density/` snapshot that may have moved on since. Best estimate, not
  Verified, is the fair comparison point: Verified only counts what a person has confirmed
  or two detectors agree on, so it undercounts by construction and would make any other
  *modelled* estimate look artificially larger by comparison regardless of merit.
- **The external reference**: `data/estimated_rooftop_solar_capacity.json`, 3,303 H3
  resolution-5 hexagons (~252 km^2 each) with one modelled capacity value per hexagon, in
  units that do not match this project's MWp figure (confirmed by direct comparison,
  2026-07-16) -- hence the share-based comparison above.

## Usage

    .pixi/envs/default/bin/python scripts/pv_reference_share_comparison.py

Writes one self-contained HTML page to `results/pakistan_pv_reference_comparison.html`
with two views: this project's own per-cell estimate, and the share-of-national-total
difference against the external reference.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
ATLAS_PATH = ROOT / "docs/assets/interactive/pakistan_evidence_atlas.html"
REFERENCE_PATH = ROOT / "data/estimated_rooftop_solar_capacity.json"
OUT_PATH = ROOT / "results/pakistan_pv_reference_comparison.html"

# Index layout of the evidence atlas's compact per-cell array -- see
# `atlas.py::build_evidence_atlas`'s own `cells = [...]` construction, which this must
# stay aligned with. Only the indices actually used here are named; the rest of that row
# (osm_mwp, osm_n, small_low, small_central, in_domain, n_pv_buildings, small_outdomain,
# is_extended) is not needed for this comparison.
_CELL_LON0, _CELL_LAT0, _CELL_MWP_VERIFIED, _CELL_MWP_BEST = 0, 1, 2, 3


def load_atlas_cells(atlas_path: Path = ATLAS_PATH) -> tuple[pd.DataFrame, dict, list[dict]]:
    """This project's published per-cell Best-estimate capacity, straight out of the
    evidence atlas HTML it already ships -- no separate `density/` read for the capacity
    figure itself, so this comparison can never silently drift from what is actually on
    the site.

    Returns `(cells, totals, provinces)`: a `(lon0, lat0, lon_center, lat_center,
    mwp_verified, mwp_best)` row per grid cell; the atlas's own `totals` dict; and its
    per-province rollups verbatim (each carrying `name`, `mwp_best`, and simplified
    outline `rings` -- a flat list of `[lon, lat]` rings, not GeoJSON), for callers that
    want province-level figures or outlines without a second, separate read of
    `regions.geoparquet`.
    """
    html = atlas_path.read_text()
    m = re.search(r'id="pv"[^>]*>(.*?)</script>', html, flags=re.S)
    if not m:
        raise SystemExit(f"could not find the embedded #pv data block in {atlas_path}")
    data = json.loads(m.group(1))
    rows = [
        {
            "lon0": c[_CELL_LON0], "lat0": c[_CELL_LAT0],
            "lon_center": round(c[_CELL_LON0] + 0.05, 4),
            "lat_center": round(c[_CELL_LAT0] + 0.05, 4),
            "mwp_verified": c[_CELL_MWP_VERIFIED], "mwp_best": c[_CELL_MWP_BEST],
        }
        for c in data["cells"]
    ]
    return pd.DataFrame(rows), data["totals"], data.get("provinces", [])


def load_reference(path: Path = REFERENCE_PATH) -> gpd.GeoDataFrame:
    """The external reference hexagons, normalized to percent of their own national total."""
    raw = json.loads(path.read_text())
    rows = []
    for r in raw:
        geom = shape(json.loads(r["geojson"]))
        val = float(r["value"][0]) if r["value"] else 0.0
        rows.append({"name": r["name"], "value": val, "geometry": geom})
    ref = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    ref["ext_share_pct"] = ref.value / ref.value.sum() * 100.0
    return ref


def build_comparison(cells: pd.DataFrame, total_best: float, ref: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Assign each of this project's cell centroids to its containing reference hexagon,
    then diff the two sides' shares within each hexagon."""
    cells = cells.copy()
    cells["our_share_pct"] = cells.mwp_best / total_best * 100.0
    reps = gpd.GeoDataFrame(
        {"our_share_pct": cells.our_share_pct},
        geometry=gpd.points_from_xy(cells.lon_center, cells.lat_center), crs="EPSG:4326",
    )
    hits = gpd.sjoin(reps, ref[["name", "geometry"]], predicate="within", how="left")
    our_share_by_hex = hits.dropna(subset=["name"]).groupby("name").our_share_pct.sum()

    ref = ref.set_index("name").copy()
    ref["our_share_pct"] = our_share_by_hex.reindex(ref.index).fillna(0.0)
    ref["share_diff_pp"] = ref.our_share_pct - ref.ext_share_pct
    return ref


# --------------------------------------------------------------------------------------
# Rendering. One self-contained page, two toggled views, sharing one SVG mount point and
# one legend -- simpler than shipping the density map and the diff map as two separate
# files (the shape of the two scripts this one replaces), and it halves the CSS/JS to
# keep in sync.
#
# Palette: this project's own established sequential (amber, --pv-accent/--pv-accent-2)
# and diverging (blue low / amber high, --pv-large / --pv-accent, neutral --pv-land
# midpoint) pairs from docs/assets/stylesheets/extra.css -- reused rather than invented,
# since no browser/validator is available on this machine to check a new pair against
# the dataviz skill's CVD gates (see CLAUDE.md's "no node/browser" note), and this exact
# pair is already shipped, unchanged, on several other pages in this project.
# --------------------------------------------------------------------------------------

_TEMPLATE = r"""<!doctype html>
<meta charset="utf-8">
<title>Pakistan rooftop PV: this project's estimate vs. an external reference</title>
<style>
  :root {
    --page: #f1ebdd; --panel: #faf6ec; --panel-2: #f3ecdb; --land: #e6dcc7;
    --ink: #2a2216; --ink-2: #5f5540; --muted: #857a61;
    --hair: rgba(120, 80, 20, 0.16); --ring: rgba(120, 80, 20, 0.14);
    --seq-lo: #f6e2c4; --seq-hi: #c25e12; --div-lo: #1c6fa8; --div-hi: #c25e12;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --page: #100d09; --panel: #1a160f; --panel-2: #221d14; --land: #241f16;
      --ink: #f7f1e6; --ink-2: #c9bda4; --muted: #93866c;
      --hair: rgba(247, 183, 51, 0.14); --ring: rgba(247, 183, 51, 0.1);
      --seq-lo: #3a2c14; --seq-hi: #f5a623; --div-lo: #4fb2e8; --div-hi: #f5a623;
    }
  }
  :root[data-theme="dark"] {
    --page: #100d09; --panel: #1a160f; --panel-2: #221d14; --land: #241f16;
    --ink: #f7f1e6; --ink-2: #c9bda4; --muted: #93866c;
    --hair: rgba(247, 183, 51, 0.14); --ring: rgba(247, 183, 51, 0.1);
    --seq-lo: #3a2c14; --seq-hi: #f5a623; --div-lo: #4fb2e8; --div-hi: #f5a623;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--page); color: var(--ink);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  .wrap { max-width: 980px; margin: 0 auto; padding: 28px 20px 44px; }
  h1 { font-size: 1.4rem; margin: 0 0 6px; }
  .lede { color: var(--ink-2); font-size: 0.94rem; max-width: 70ch; line-height: 1.55; margin: 0 0 18px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tab { background: var(--panel); border: 1px solid var(--ring); border-radius: 10px;
         padding: 9px 14px; font-size: 0.86rem; color: var(--ink-2); cursor: pointer; }
  .tab[aria-pressed="true"] { color: var(--ink); border-color: var(--seq-hi); font-weight: 600; }
  .stats { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
  .stat { background: var(--panel); border: 1px solid var(--ring); border-radius: 10px;
          padding: 10px 14px; min-width: 140px; }
  .stat .v { font-size: 1.25rem; font-weight: 600; font-variant-numeric: tabular-nums; }
  .stat .l { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.03em; }
  .map-card { background: var(--panel); border: 1px solid var(--ring); border-radius: 12px;
              padding: 14px; position: relative; }
  svg.map { display: block; width: 100%; height: auto; }
  .outline { fill: none; stroke: var(--hair); stroke-width: 1; }
  .mark { stroke: var(--panel-2); stroke-width: 0.4; cursor: pointer; }
  .mark:hover, .mark:focus { stroke: var(--ink); stroke-width: 1.1; outline: none; }
  .legend { display: flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 0.78rem; color: var(--ink-2); }
  .legend-bar { height: 10px; flex: 1; border-radius: 4px; border: 1px solid var(--ring); }
  .legend-ticks { display: flex; justify-content: space-between; font-size: 0.72rem; color: var(--muted);
                  margin-top: 3px; font-variant-numeric: tabular-nums; }
  .legend-col { flex: 1; }
  .tooltip { position: absolute; pointer-events: none; background: var(--ink); color: var(--panel);
             font-size: 0.76rem; padding: 5px 8px; border-radius: 6px; line-height: 1.4;
             transform: translate(-50%, -110%); white-space: nowrap; z-index: 10; }
  .note { font-size: 0.8rem; color: var(--muted); margin-top: 14px; line-height: 1.55; max-width: 74ch; }
  details.bg { margin-top: 10px; border: 1px solid var(--ring); border-radius: 10px; background: var(--panel); }
  details.bg summary { cursor: pointer; padding: 12px 14px; font-size: 0.88rem; font-weight: 600; }
  details.bg .body { padding: 0 14px 14px; font-size: 0.85rem; color: var(--ink-2); line-height: 1.6; }
  details.bg .body p { margin: 0 0 10px; }
  code { font-family: ui-monospace, "SF Mono", monospace; font-size: 0.85em; background: var(--panel-2);
         padding: 1px 5px; border-radius: 4px; }
</style>

<div class="wrap">
  <h1>This project's estimate vs. an independent reference, per spatial unit</h1>
  <p class="lede">Two estimates of Pakistan's rooftop solar, built independently and in
  different units, checked against each other for spatial agreement rather than magnitude.
  Neither is ground truth here -- this shows where the two estimates weight the country
  differently, not which one is correct.</p>

  <div class="tabs" role="group" aria-label="View">
    <button class="tab" id="tabOurs" type="button" aria-pressed="true">This project's estimate</button>
    <button class="tab" id="tabDiff" type="button" aria-pressed="false">Vs. external reference</button>
  </div>

  <div class="stats" id="stats"></div>

  <div class="map-card">
    <svg class="map" viewBox="0 0 860 620" id="map"></svg>
    <div class="legend">
      <div class="legend-col">
        <div class="legend-bar" id="legbar"></div>
        <div class="legend-ticks" id="legticks"></div>
      </div>
    </div>
    <div class="tooltip" id="tooltip" hidden></div>
  </div>
  <p class="note" id="mapnote"></p>

  <details class="bg">
    <summary>Sources, units, and what this comparison can and can't show</summary>
    <div class="body">
      <p>Both layers are normalized to <strong>percent of national total per spatial
      unit</strong> before comparing. This project's estimate and the external reference
      are not in comparable absolute units or scope (confirmed by direct comparison,
      2026-07-16) -- almost certainly different training data, different detection floors,
      and a different definition of what counts as rooftop solar. Diffing raw magnitudes
      would answer a question neither dataset can actually settle; the share-based
      comparison instead asks whether the two agree on <em>where</em> solar concentrates.</p>
      <p>Only <span id="xMatched">-</span> of <span id="xNhex">-</span> external hexagons
      receive any of this project's grid cells at all. A hexagon with no overlap is not
      necessarily a place either model disagrees about -- this project's own composited
      coverage only reaches building-populated cells, so part of the non-overlap is a
      coverage gap rather than a disagreement.</p>
      <p>This project's estimate: the Best-estimate tier of the published evidence atlas,
      per 0.1&deg; grid cell (<code>docs/assets/interactive/pakistan_evidence_atlas.html</code>).
      External reference: <code>data/estimated_rooftop_solar_capacity.json</code>, 3,303 H3
      resolution-5 hexagons.</p>
    </div>
  </details>
</div>

<script id="data" type="application/json">__DATA_JSON__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById("data").textContent);
  const [minx, miny, maxx, maxy] = DATA.bounds;
  const W = 860, PAD = 20;
  const cosLat = Math.cos((miny + maxy) / 2 * Math.PI / 180);
  const dx = (maxx - minx) * cosLat, dy = (maxy - miny);
  const innerW = W - 2 * PAD;
  const H = Math.max(Math.round(innerW * dy / dx) + 2 * PAD, 320);
  const innerH = H - 2 * PAD;
  const scale = Math.min(innerW / dx, innerH / dy);
  const usedW = dx * scale, usedH = dy * scale;
  const offX = PAD + (innerW - usedW) / 2, offY = PAD + (innerH - usedH) / 2;
  function project([lon, lat]) { return [offX + (lon - minx) * cosLat * scale, offY + (maxy - lat) * scale]; }
  const cellPx = 0.1 * cosLat * scale;

  function ringToPath(ring) {
    return ring.map(([lon, lat], i) => {
      const [x, y] = project([lon, lat]);
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ") + "Z";
  }
  // Every geometry on this page (province outlines, reference hexagons) travels as a
  // flat list of [lon, lat] rings, not GeoJSON -- one shape, one path builder.
  function ringsToPath(rings) { return rings.map(ringToPath).join(" "); }
  function hex2rgb(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
  function mix(c1, c2, t) {
    t = Math.min(1, Math.max(0, t));
    const a = hex2rgb(c1), b = hex2rgb(c2);
    return `rgb(${Math.round(a[0] + (b[0] - a[0]) * t)},${Math.round(a[1] + (b[1] - a[1]) * t)},${Math.round(a[2] + (b[2] - a[2]) * t)})`;
  }
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  const NS = "http://www.w3.org/2000/svg";
  const svg = document.getElementById("map");
  const tip = document.getElementById("tooltip");
  const root = document.querySelector(".map-card");
  const statsEl = document.getElementById("stats");
  const noteEl = document.getElementById("mapnote");
  const tabOurs = document.getElementById("tabOurs"), tabDiff = document.getElementById("tabDiff");

  function showTip(evt, lines) {
    tip.innerHTML = "";
    lines.forEach((l, i) => { if (i > 0) tip.appendChild(document.createElement("br")); tip.appendChild(document.createTextNode(l)); });
    const r = root.getBoundingClientRect();
    tip.style.left = (evt.clientX - r.left) + "px";
    tip.style.top = (evt.clientY - r.top) + "px";
    tip.hidden = false;
  }
  function hideTip() { tip.hidden = true; }

  function drawOutline(g) {
    DATA.outline.forEach(f => {
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", ringsToPath(f.rings));
      p.setAttribute("class", "outline");
      g.appendChild(p);
    });
  }

  function renderOurs() {
    svg.innerHTML = "";
    const SEQ_LO = cssVar("--seq-lo"), SEQ_HI = cssVar("--seq-hi");
    const gOutline = document.createElementNS(NS, "g"); drawOutline(gOutline); svg.appendChild(gOutline);
    const gCells = document.createElementNS(NS, "g");
    const half = Math.max(cellPx / 2, 1.1);
    const maxMwp = Math.max(1, ...DATA.ours.map(f => f.mwp));
    DATA.ours.forEach(f => {
      const t = Math.sqrt(f.mwp / maxMwp);
      const [x, y] = project([f.lon, f.lat]);
      const rect = document.createElementNS(NS, "rect");
      rect.setAttribute("x", (x - half).toFixed(2)); rect.setAttribute("y", (y - half).toFixed(2));
      rect.setAttribute("width", (half * 2).toFixed(2)); rect.setAttribute("height", (half * 2).toFixed(2));
      rect.setAttribute("fill", mix(SEQ_LO, SEQ_HI, t));
      rect.setAttribute("class", "mark"); rect.setAttribute("tabindex", "0");
      rect.addEventListener("pointermove", e => showTip(e, [`<strong>${f.mwp.toFixed(2)} MWp</strong>`]));
      rect.addEventListener("pointerleave", hideTip);
      gCells.appendChild(rect);
    });
    svg.appendChild(gCells);
    document.getElementById("legbar").style.background = `linear-gradient(to right, ${SEQ_LO}, ${mix(SEQ_LO, SEQ_HI, 0.5)}, ${SEQ_HI})`;
    document.getElementById("legticks").innerHTML =
      `<span>0</span><span>${(maxMwp/4).toFixed(1)}</span><span>${(maxMwp/2).toFixed(1)}</span><span>${maxMwp.toFixed(0)} MWp</span>`;
    statsEl.innerHTML =
      `<div class="stat"><div class="v">${DATA.total_best.toLocaleString(undefined,{maximumFractionDigits:0})} MWp</div><div class="l">This project, Best estimate total</div></div>
       <div class="stat"><div class="v">${DATA.n_nonzero.toLocaleString()}</div><div class="l">of ${DATA.n_cells.toLocaleString()} cells nonzero</div></div>`;
    noteEl.textContent = "Best-estimate capacity per 0.1° grid cell, from the published evidence atlas. Color and area both encode magnitude on a square-root scale so a handful of dense urban/industrial clusters don't wash out everywhere else.";
  }

  function renderDiff() {
    svg.innerHTML = "";
    const DIV_LO = cssVar("--div-lo"), DIV_HI = cssVar("--div-hi"), MID = cssVar("--land");
    const gOutline = document.createElementNS(NS, "g"); drawOutline(gOutline); svg.appendChild(gOutline);
    const gHex = document.createElementNS(NS, "g");
    const diffMin = DATA.diff_min, diffMax = DATA.diff_max;
    DATA.diff.forEach(f => {
      const d = f.diff_pp;
      const color = d >= 0 ? mix(MID, DIV_HI, diffMax > 0 ? d / diffMax : 0)
                            : mix(MID, DIV_LO, diffMin < 0 ? d / diffMin : 0);
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", ringsToPath(f.rings)); p.setAttribute("fill", color);
      p.setAttribute("class", "mark"); p.setAttribute("tabindex", "0");
      p.addEventListener("pointermove", e => showTip(e, [
        `<strong>${d >= 0 ? "+" : ""}${d.toFixed(3)} pp</strong>`,
        `this project: ${f.our_pct.toFixed(3)}%  |  external reference: ${f.ext_pct.toFixed(3)}%`,
      ]));
      p.addEventListener("pointerleave", hideTip);
      gHex.appendChild(p);
    });
    svg.appendChild(gHex);
    document.getElementById("legbar").style.background = `linear-gradient(to right, ${DIV_LO}, ${MID}, ${DIV_HI})`;
    document.getElementById("legticks").innerHTML =
      `<span>${diffMin.toFixed(2)}pp (reference higher)</span><span>0</span><span>+${diffMax.toFixed(2)}pp (this project higher)</span>`;
    statsEl.innerHTML =
      `<div class="stat"><div class="v">${DATA.n_hex.toLocaleString()}</div><div class="l">External reference hexagons</div></div>
       <div class="stat"><div class="v">${DATA.n_matched.toLocaleString()}</div><div class="l">With &ge;1 of this project's cells</div></div>
       <div class="stat"><div class="v">${diffMin >= 0 ? "+" : ""}${diffMin.toFixed(2)} to +${diffMax.toFixed(2)} pp</div><div class="l">Share-diff range</div></div>`;
    noteEl.textContent = "Positive = this project assigns a larger share of the national total to that hexagon than the external reference does; negative = smaller. This describes disagreement, not error -- see “Sources, units, and what this comparison can and can't show” below.";
    document.getElementById("xMatched").textContent = DATA.n_matched.toLocaleString();
    document.getElementById("xNhex").textContent = DATA.n_hex.toLocaleString();
  }

  tabOurs.addEventListener("click", () => {
    tabOurs.setAttribute("aria-pressed", "true"); tabDiff.setAttribute("aria-pressed", "false");
    renderOurs();
  });
  tabDiff.addEventListener("click", () => {
    tabDiff.setAttribute("aria-pressed", "true"); tabOurs.setAttribute("aria-pressed", "false");
    renderDiff();
  });
  renderOurs();
})();
</script>
"""


def render_html(
    cells: pd.DataFrame, totals: dict, ref: gpd.GeoDataFrame, bounds: list[float], outline: list[dict],
) -> str:
    nonzero = cells[cells.mwp_best > 0]
    ours_features = [
        {"lon": round(float(r.lon_center), 4), "lat": round(float(r.lat_center), 4), "mwp": round(float(r.mwp_best), 3)}
        for r in nonzero.itertuples()
    ]
    diff_features = [
        {
            "rings": [
                [[round(x, 4), round(y, 4)] for x, y in ring.coords]
                for ring in _exterior_rings(row.geometry.simplify(0.002, preserve_topology=True))
            ],
            "diff_pp": round(float(row.share_diff_pp), 4),
            "our_pct": round(float(row.our_share_pct), 4),
            "ext_pct": round(float(row.ext_share_pct), 4),
        }
        for _, row in ref.iterrows()
    ]
    matched = int((ref.our_share_pct > 0).sum())

    data = {
        "bounds": bounds,
        "total_best": round(totals["mwp_best"], 1),
        "n_cells": int(len(cells)),
        "n_nonzero": int(len(nonzero)),
        "outline": outline,
        "ours": ours_features,
        "diff": diff_features,
        "diff_min": round(float(ref.share_diff_pp.min()), 4),
        "diff_max": round(float(ref.share_diff_pp.max()), 4),
        "n_hex": int(len(ref)),
        "n_matched": matched,
    }
    return _TEMPLATE.replace("__DATA_JSON__", json.dumps(data))


def _exterior_rings(geom):
    """Exterior ring(s) of a (Multi)Polygon as shapely `LinearRing`-like coordinate
    sequences -- mirrors `atlas.py::_rings`'s own simplify-then-take-exterior shape."""
    polys = getattr(geom, "geoms", [geom])
    return [p.exterior for p in polys if not p.is_empty]


def main() -> None:
    cells, totals, provinces = load_atlas_cells()
    outline = [{"rings": p["rings"]} for p in provinces]
    ref = load_reference()
    ref = build_comparison(cells, totals["mwp_best"], ref)

    matched = int((ref.our_share_pct > 0).sum())
    print(f"This project's estimate: {len(cells):,} cells, Best-estimate total {totals['mwp_best']:.1f} MWp")
    print(f"External reference: {len(ref):,} hexagons, {matched:,} received >=1 of this project's cells")
    print(f"share_diff_pp range: {ref.share_diff_pp.min():+.3f} to {ref.share_diff_pp.max():+.3f}")

    bounds = [
        round(float(cells.lon0.min()), 3), round(float(cells.lat0.min()), 3),
        round(float(cells.lon0.max()) + 0.1, 3), round(float(cells.lat0.max()) + 0.1, 3),
    ]
    html = render_html(cells, totals, ref, bounds, outline)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
