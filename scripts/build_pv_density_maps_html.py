"""Render the two self-contained HTML choropleths from pv_density_vs_transitionzero.py's
output JSON: the PV density map and the vs-TransitionZero share-diff map.

Usage:
  .pixi/envs/default/bin/python scripts/build_pv_density_maps_html.py
"""

from __future__ import annotations

import json
from pathlib import Path

MAPS_DIR = Path("data/predictions_pk16085/pakistan/density/maps")

STYLE = """
<style>
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
    --gridline: #e1e0d9; --border: rgba(11,11,11,0.10);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d;
      --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
      --gridline: #2c2c2a; --border: rgba(255,255,255,0.10);
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --gridline: #2c2c2a; --border: rgba(255,255,255,0.10);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--page); }
  .viz-root { max-width: 980px; margin: 0 auto; padding: 24px 20px 40px; color: var(--text-primary); }
  h1 { font-size: 1.35rem; margin: 0 0 4px; }
  .subtitle { color: var(--text-secondary); font-size: 0.92rem; margin: 0 0 18px; max-width: 68ch; line-height: 1.5; }
  .stats { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }
  .stat { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
          padding: 10px 14px; min-width: 130px; }
  .stat .v { font-size: 1.3rem; font-weight: 600; font-variant-numeric: tabular-nums; }
  .stat .l { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
  .map-card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
              padding: 14px; position: relative; }
  svg { display: block; width: 100%; height: auto; }
  .outline { fill: none; stroke: var(--gridline); stroke-width: 1; }
  .mark { stroke: var(--border); stroke-width: 0.4; cursor: pointer; }
  .mark:hover, .mark:focus { stroke: var(--text-primary); stroke-width: 1.1; outline: none; }
  .legend { display: flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 0.78rem;
            color: var(--text-secondary); }
  .legend-bar { height: 10px; flex: 1; border-radius: 4px; border: 1px solid var(--border); }
  .legend-ticks { display: flex; justify-content: space-between; font-size: 0.72rem;
                  color: var(--text-muted); margin-top: 3px; font-variant-numeric: tabular-nums; }
  .legend-col { flex: 1; }
  .tooltip { position: absolute; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
             font-size: 0.76rem; padding: 5px 8px; border-radius: 6px; line-height: 1.4;
             transform: translate(-50%, -110%); white-space: nowrap; z-index: 10; }
  .tooltip strong { font-variant-numeric: tabular-nums; }
  .note { font-size: 0.78rem; color: var(--text-muted); margin-top: 14px; line-height: 1.5; max-width: 70ch; }
  footer.note { border-top: 1px solid var(--border); padding-top: 12px; margin-top: 20px; }
</style>
"""

PROJECT_JS = """
function makeProjector(bounds, W, H, pad) {
  const [minx, miny, maxx, maxy] = bounds;
  const cosLat = Math.cos((miny + maxy) / 2 * Math.PI / 180);
  const dx = (maxx - minx) * cosLat, dy = (maxy - miny);
  const innerW = W - 2 * pad, innerH = H - 2 * pad;
  const scale = Math.min(innerW / dx, innerH / dy);
  const usedW = dx * scale, usedH = dy * scale;
  const offX = pad + (innerW - usedW) / 2, offY = pad + (innerH - usedH) / 2;
  return {
    project([lon, lat]) {
      return [offX + (lon - minx) * cosLat * scale, offY + (maxy - lat) * scale];
    },
    cellPx: 0.1 * cosLat * scale,
  };
}
function ringToPath(ring, project) {
  return ring.map(([lon, lat], i) => {
    const [x, y] = project([lon, lat]);
    return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ") + "Z";
}
function geomToPath(geom, project) {
  if (geom.type === "Polygon") {
    return geom.coordinates.map(r => ringToPath(r, project)).join(" ");
  }
  if (geom.type === "MultiPolygon") {
    return geom.coordinates.map(poly => poly.map(r => ringToPath(r, project)).join(" ")).join(" ");
  }
  return "";
}
function hexToRgb(h) {
  h = h.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function mixHex(c1, c2, t) {
  t = Math.min(1, Math.max(0, t));
  const a = hexToRgb(c1), b = hexToRgb(c2);
  const r = Math.round(a[0] + (b[0] - a[0]) * t);
  const g = Math.round(a[1] + (b[1] - a[1]) * t);
  const bl = Math.round(a[2] + (b[2] - a[2]) * t);
  return `rgb(${r},${g},${bl})`;
}
function showTip(el, tip, html) {
  tip.innerHTML = "";
  const lines = Array.isArray(html) ? html : [html];
  lines.forEach((l, i) => {
    if (i > 0) tip.appendChild(document.createElement("br"));
    tip.appendChild(document.createTextNode(l));
  });
  tip.hidden = false;
}
function positionTip(evt, root, tip) {
  const r = root.getBoundingClientRect();
  tip.style.left = (evt.clientX - r.left) + "px";
  tip.style.top = (evt.clientY - r.top) + "px";
}
"""


def density_html(data: dict) -> str:
    W, PAD = 860, 20
    minx, miny, maxx, maxy = data["bounds"]
    cos_lat = __import__("math").cos((miny + maxy) / 2 * 3.14159265 / 180)
    dx, dy = (maxx - minx) * cos_lat, (maxy - miny)
    H = round(W * dy / dx) + 2 * PAD - round(2 * PAD * dy / dx)
    H = max(H, 300)
    max_mwp = max(f["properties"]["mwp"] for f in data["features"])

    return f"""<title>Pakistan Rooftop PV Density (pk16085)</title>
{STYLE}
<div class="viz-root">
  <h1>Pakistan rooftop PV density</h1>
  <p class="subtitle">Estimated installed capacity (est_mwp_det) per 0.1&deg; grid cell, from the
  pk16085 model's country-wide inference + epoch-diff-rescored candidates
  ({data["n_nonzero"]:,} of {data["n_cells"]:,} cells nonzero). Color and area both encode
  magnitude on a sqrt scale &mdash; a long right tail from a handful of dense urban/industrial
  clusters would otherwise wash out everywhere else.</p>
  <div class="stats">
    <div class="stat"><div class="v">{data["total_mwp"]:,.0f} MWp</div><div class="l">National total (est_mwp_det)</div></div>
    <div class="stat"><div class="v">{data["n_nonzero"]:,}</div><div class="l">Cells with detected PV</div></div>
  </div>
  <div class="map-card">
    <svg viewBox="0 0 {W} {H}" id="map"></svg>
    <div class="legend">
      <div class="legend-col">
        <div class="legend-bar" id="legend-bar"></div>
        <div class="legend-ticks"><span>0</span><span>{max_mwp/4:,.1f}</span><span>{max_mwp/2:,.1f}</span><span>{max_mwp:,.0f} MWp</span></div>
      </div>
    </div>
    <div class="tooltip" id="tooltip" hidden></div>
  </div>
  <p class="note">Cell size ~11km x 11km (0.1&deg;); provinces shown for orientation only, not a basemap.
  Detected capacity is model-inferred (recall-first, human-unvalidated at scale) &mdash; treat as a
  screening layer, not a metered figure.</p>
</div>
<script id="data" type="application/json">{json.dumps(data)}</script>
<script>
{PROJECT_JS}
const DATA = JSON.parse(document.getElementById("data").textContent);
const svg = document.getElementById("map");
const NS = "http://www.w3.org/2000/svg";
const W = {W}, H = {H}, PAD = {PAD};
const {{ project, cellPx }} = makeProjector(DATA.bounds, W, H, PAD);
const BLUE_LO = "#b7d3f6", BLUE_HI = "#0d366b";
const maxMwp = Math.max(...DATA.features.map(f => f.properties.mwp));

const gOutline = document.createElementNS(NS, "g");
DATA.outline.forEach(f => {{
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", geomToPath(f.geometry, project));
  p.setAttribute("class", "outline");
  gOutline.appendChild(p);
}});
svg.appendChild(gOutline);

const gCells = document.createElementNS(NS, "g");
const tip = document.getElementById("tooltip");
const root = document.querySelector(".map-card");
const half = Math.max(cellPx / 2, 1.1);
DATA.features.forEach(f => {{
  const mwp = f.properties.mwp;
  const [x, y] = project(f.geometry.coordinates);
  const t = Math.sqrt(mwp / maxMwp);
  const rect = document.createElementNS(NS, "rect");
  rect.setAttribute("x", (x - half).toFixed(2));
  rect.setAttribute("y", (y - half).toFixed(2));
  rect.setAttribute("width", (half * 2).toFixed(2));
  rect.setAttribute("height", (half * 2).toFixed(2));
  rect.setAttribute("fill", mixHex(BLUE_LO, BLUE_HI, t));
  rect.setAttribute("class", "mark");
  rect.setAttribute("tabindex", "0");
  rect.addEventListener("pointermove", e => {{
    showTip(rect, tip, [`<strong>${{mwp.toFixed(2)}} MWp</strong>`]);
    positionTip(e, root, tip);
  }});
  rect.addEventListener("pointerleave", () => tip.hidden = true);
  gCells.appendChild(rect);
}});
svg.appendChild(gCells);

document.getElementById("legend-bar").style.background =
  `linear-gradient(to right, ${{BLUE_LO}}, ${{mixHex(BLUE_LO, BLUE_HI, 0.5)}}, ${{BLUE_HI}})`;
</script>
"""


def tz_html(data: dict) -> str:
    W, PAD = 860, 20
    minx, miny, maxx, maxy = data["bounds"]
    import math
    cos_lat = math.cos((miny + maxy) / 2 * math.pi / 180)
    dx, dy = (maxx - minx) * cos_lat, (maxy - miny)
    H = max(round(W * dy / dx), 300)
    diff_min, diff_max = data["diff_min"], data["diff_max"]

    return f"""<title>Pakistan PV vs TransitionZero: share-of-national-total diff</title>
{STYLE}
<div class="viz-root">
  <h1>Our PV share vs TransitionZero, per H3 hexagon</h1>
  <p class="subtitle">TransitionZero's rooftop-solar estimate isn't in comparable absolute units to
  ours (different methodology/scope) &mdash; diffing raw MWp would be meaningless. Both datasets are
  instead normalized to <strong>percent of national total per spatial unit</strong>, then differenced:
  positive (blue) = our model concentrates more of the national share there than TransitionZero does;
  negative (red) = less. Answers "do the two datasets agree on where PV concentrates," not "whose
  number is bigger."</p>
  <div class="stats">
    <div class="stat"><div class="v">{data["n_hex"]:,}</div><div class="l">TZ hexagons (H3 res-5)</div></div>
    <div class="stat"><div class="v">{data["n_matched"]:,}</div><div class="l">Hexagons with &ge;1 of our cells</div></div>
    <div class="stat"><div class="v">{diff_min:+.2f} to {diff_max:+.2f} pp</div><div class="l">share_diff_pp range</div></div>
  </div>
  <div class="map-card">
    <svg viewBox="0 0 {W} {H}" id="map"></svg>
    <div class="legend">
      <div class="legend-col">
        <div class="legend-bar" id="legend-bar"></div>
        <div class="legend-ticks">
          <span>{diff_min:+.2f}pp (TZ&gt;us)</span><span>0</span><span>{diff_max:+.2f}pp (us&gt;TZ)</span>
        </div>
      </div>
    </div>
    <div class="tooltip" id="tooltip" hidden></div>
  </div>
  <p class="note">Diverging scale is asymmetric (independent arms per sign) since the two datasets
  disagree far more sharply in one direction ({diff_max:+.2f}pp) than the other ({diff_min:+.2f}pp) &mdash;
  a symmetric scale would crush the narrower arm to invisibility. Red ramp endpoint is a best-effort
  hue-rotation of the sequential blue ramp's dark step (no browser/validator available on this
  machine to check it against the palette's CVD gates independently); treat the diverging hues as
  indicative, the numeric diff as authoritative.</p>
  <footer class="note">Ours: pk16085 country-wide inference, est_mwp_det, {data["n_hex"]:,} hexagons
  joined by grid-cell-centroid-within-hexagon. TransitionZero: data/estimated_rooftop_solar_capacity.json,
  3,303 H3 res-5 hexagons.</footer>
</div>
<script id="data" type="application/json">{json.dumps(data)}</script>
<script>
{PROJECT_JS}
const DATA = JSON.parse(document.getElementById("data").textContent);
const svg = document.getElementById("map");
const NS = "http://www.w3.org/2000/svg";
const W = {W}, H = {H}, PAD = {PAD};
const {{ project }} = makeProjector(DATA.bounds, W, H, PAD);
const GRAY = "#f0efec", BLUE_HI = "#0d366b", RED_HI = "#6b1210";
const diffMin = {diff_min}, diffMax = {diff_max};

const gOutline = document.createElementNS(NS, "g");
DATA.outline.forEach(f => {{
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", geomToPath(f.geometry, project));
  p.setAttribute("class", "outline");
  gOutline.appendChild(p);
}});
svg.appendChild(gOutline);

const gHex = document.createElementNS(NS, "g");
const tip = document.getElementById("tooltip");
const root = document.querySelector(".map-card");
DATA.features.forEach(f => {{
  const {{ diff_pp, tz_pct, our_pct, name }} = f.properties;
  const color = diff_pp >= 0
    ? mixHex(GRAY, BLUE_HI, diffMax > 0 ? diff_pp / diffMax : 0)
    : mixHex(GRAY, RED_HI, diffMin < 0 ? diff_pp / diffMin : 0);
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", geomToPath(f.geometry, project));
  path.setAttribute("fill", color);
  path.setAttribute("class", "mark");
  path.setAttribute("tabindex", "0");
  path.addEventListener("pointermove", e => {{
    showTip(path, tip, [
      `<strong>${{diff_pp >= 0 ? "+" : ""}}${{diff_pp.toFixed(3)}}pp</strong>`,
      `our share: ${{our_pct.toFixed(3)}}%  |  TZ share: ${{tz_pct.toFixed(3)}}%`,
    ]);
    positionTip(e, root, tip);
  }});
  path.addEventListener("pointerleave", () => tip.hidden = true);
  gHex.appendChild(path);
}});
svg.appendChild(gHex);

document.getElementById("legend-bar").style.background =
  `linear-gradient(to right, ${{RED_HI}}, ${{GRAY}}, ${{BLUE_HI}})`;
</script>
"""


def main() -> None:
    density = json.loads((MAPS_DIR / "density_data.json").read_text())
    tz = json.loads((MAPS_DIR / "tz_compare_data.json").read_text())
    (MAPS_DIR / "pakistan_pv_density_map.html").write_text(density_html(density))
    (MAPS_DIR / "pakistan_pv_vs_transitionzero.html").write_text(tz_html(tz))
    print("Wrote", MAPS_DIR / "pakistan_pv_density_map.html")
    print("Wrote", MAPS_DIR / "pakistan_pv_vs_transitionzero.html")


if __name__ == "__main__":
    main()
