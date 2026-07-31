"""An alternative national overview for Pakistan, headlined by three *evidence tiers*
rather than by the four sub-400 m2 bracket members of `build_pakistan_pv_overview.py`.

Where that page asks "how much small rooftop PV is the detector missing", this one asks
"how much PV can we claim, and on what evidence", and answers it three times over:

  1. VERIFIED   human-mapped OpenStreetMap PV (every installation drawn by a person)
                plus the sub-400 m2 buildings where roofclf AND SPPI independently agree.
  2. BEST       the verified OSM population, plus the model's own recall-corrected
                >= 400 m2 detections, plus the roofclf-alone per-building density
                estimate inside the density-calibrated cells.
  3. CEILING    roofclf flagged nationwide at a precision-tuned threshold (0.3064),
                credited at a flat 0.5 precision weight rather than each building's own
                probability, restricted to buildings with no existing >= 400 m2 detection
                nearby (`roofclf_capacity.incremental_capacity`'s own "High" figure,
                37,197 MWp) -- plus every >= 400 m2 installation already known, of every
                placement (`est_mwp_rc`, recall-corrected, national).

The three are nested by the evidence they admit, so they read as a ladder. Composition
is deliberately NOT a naive sum of the pieces -- see `_tier_frame` for how the overlap
between OSM mapping and model detections is removed (candidates carry `osm_matched_id`,
so "OSM the model already found" is subtracted from the OSM term in tier 2 rather than
counted twice), and how tier 3's own "incremental" filter already keeps its small-PV
component clear of the known large-PV population it is added to.

Unlike the bracket page this one recomputes its own per-cell payload from the density
grid, the national OSM pull, the candidate frame and three pre-computed roofclf/SPPI
per-building parquets (`data/roofclf_national_with_sppi/pakistan/density/`); it reuses
only the panel-pose survey's embedded JSON for the orientation section, exactly as the
sibling script does.

    pixi run python scripts/build_pakistan_pv_evidence_overview.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DENSITY_DIR = ROOT / "data" / "predictions" / "pakistan" / "density"
ROOFCLF_DIR = ROOT / "data" / "roofclf_national_with_sppi" / "pakistan"
CAND_PATH = ROOT / "data" / "predictions" / "pakistan" / "candidates.parquet"
OSM_PATH = ROOT / "data" / "labels" / "pakistan_overpass_solar.parquet"
BRACKET_HTML = ROOT / "results" / "pakistan_pv_sub400_bracket_atlas.html"
POSE_HTML = ROOT / "results" / "glint_validation_pakistan" / "pv_pose_country2000.html"
POSE_CSV = ROOT / "data" / "glint" / "country2000_summary.csv"
OUT = ROOT / "results" / "pakistan_pv_evidence_overview.html"

KWP_MOD = 0.18   # module area -> kWp (rooftop detections are module area)
KWP_LAND = 0.07  # site area -> kWp (ground plants are perimeters, not modules)

# The 0.1 degree grid's origin, recovered from the density grid itself, so the ten cells
# that roofclf scored but `density` never inferred can still be placed on the map.
CELL_RE = re.compile(r"^(\d+)_(\d+)$")


def _extract_json(text: str, script_id: str) -> dict:
    m = re.search(rf'<script[^>]*id="{script_id}"[^>]*>(.*?)</script>', text, re.S)
    if not m:
        raise ValueError(f"no <script id={script_id!r}> found")
    return json.loads(m.group(1))


def _pose_stats(csv_path: Path) -> dict:
    s = pd.read_csv(csv_path)
    ge1000 = s[s.area_m2 >= 1000]
    fit = s[s.n_consistent >= 2]
    n_ge1000 = len(ge1000)
    return dict(
        n_total=len(s),
        n_fitted=len(fit),
        n_ge1000=n_ge1000,
        pct_ge1000=round(100 * (ge1000.n_consistent >= 2).mean(), 1) if n_ge1000 else 0.0,
        pct_onespike=round(
            100 * ((ge1000.n_spikes >= 1) & (ge1000.n_consistent < 2)).mean(), 1
        ) if n_ge1000 else 0.0,
        pct_nosignal=round(100 * (ge1000.n_spikes == 0).mean(), 1) if n_ge1000 else 0.0,
        tilt_q25=round(float(fit.fit_tilt.quantile(0.25)), 1),
        tilt_q75=round(float(fit.fit_tilt.quantile(0.75)), 1),
    )


def _by_cell(path: Path, col: str) -> pd.Series:
    d = pd.read_parquet(path, columns=["cell", col])
    return d.groupby("cell")[col].sum() / 1000.0


def _tier_frame() -> tuple[gpd.GeoDataFrame, dict]:
    grid = gpd.read_parquet(DENSITY_DIR / "grid.geoparquet")
    lon_origin = float((grid.lon0 - grid.ix * 0.1).round(6).mode().iloc[0])
    lat_origin = float((grid.lat0 - grid.iy * 0.1).round(6).mode().iloc[0])

    # --- human-mapped OSM PV, per cell, split by placement and by whether the model
    #     already found it (candidates carry the id of the OSM feature they matched).
    osm = gpd.read_parquet(OSM_PATH)
    cand = gpd.read_parquet(CAND_PATH)
    matched_ids = set(cand.osm_matched_id.dropna().astype(str))
    osm["matched"] = osm["id"].astype(str).isin(matched_ids)
    osm["kwp"] = np.where(
        osm.placement == "rooftop", osm.area_m2 * KWP_MOD, osm.area_m2 * KWP_LAND
    )
    pts = osm.copy()
    pts["geometry"] = pts.geometry.representative_point()
    joined = gpd.sjoin(pts, grid[["cell", "geometry"]], predicate="within", how="left")
    osm_cells = joined.dropna(subset=["cell"]).groupby("cell").apply(
        lambda d: pd.Series({
            "osm_mwp": d.kwp.sum() / 1000,
            "osm_mwp_roof": d.loc[d.placement == "rooftop", "kwp"].sum() / 1000,
            "osm_mwp_unmatched": d.loc[~d.matched, "kwp"].sum() / 1000,
            "osm_n": float(len(d)),
        }),
        include_groups=False,
    )

    low = _by_cell(ROOFCLF_DIR / "density" / "sub400_low_incremental_buildings.parquet",
                   "est_kwp_sub400_and_gate")
    central = _by_cell(ROOFCLF_DIR / "density" / "sub400_central_incremental_buildings.parquet",
                       "est_kwp_sub400")
    # The old bracket atlas's "High" figure: roofclf flagged at a precision-tuned
    # threshold (0.3064), flat 0.5 precision weight on the flagged area (not each
    # building's own probability), restricted to buildings with no existing >= 400 m2
    # candidate of any placement within 30 m ("incremental" -- see
    # `roofclf_capacity.incremental_capacity`, which wrote this file).
    high = _by_cell(ROOFCLF_DIR / "density" / "sub400_high_incremental_buildings.parquet",
                    "est_kwp_roofclf")

    # roofclf scored ten cells that `density` never inferred (they hold buildings but no
    # composite). Append them with zeroed segmentation fields so the map's own sum equals
    # the reported national totals instead of quietly falling ~5% short of them.
    missing = sorted((set(low.index) | set(central.index) | set(high.index)) - set(grid.cell))
    if missing:
        extra = []
        for cell in missing:
            m = CELL_RE.match(cell)
            ix, iy = int(m.group(1)), int(m.group(2))
            extra.append({
                "cell": cell, "ix": ix, "iy": iy,
                "lon0": lon_origin + ix * 0.1, "lat0": lat_origin + iy * 0.1,
            })
        extra_df = pd.DataFrame(extra)
        for col in grid.columns:
            if col not in extra_df.columns and col != "geometry":
                extra_df[col] = 0.0
        grid = pd.concat([pd.DataFrame(grid.drop(columns="geometry")), extra_df],
                         ignore_index=True)
    else:
        grid = pd.DataFrame(grid.drop(columns="geometry"))

    g = grid.copy()
    for col in ["osm_mwp", "osm_mwp_roof", "osm_mwp_unmatched", "osm_n"]:
        g[col] = g["cell"].map(osm_cells[col]).fillna(0.0)
    g["small_low"] = g["cell"].map(low).fillna(0.0)
    g["small_central"] = g["cell"].map(central).fillna(0.0)
    g["small_high"] = g["cell"].map(high).fillna(0.0)
    g["in_domain"] = (g["cell"].isin(low.index) | g["cell"].isin(central.index)).astype(int)

    # Tier 1: everything a person has drawn, plus the sub-400 m2 buildings two
    # independent detectors both flag. No model detection enters this tier.
    g["t1"] = g.osm_mwp + g.small_low
    # Tier 2: the model's recall-corrected detections ALREADY contain the 2,022 OSM
    # features it matched (those candidates carry OSM geometry), so only the OSM the
    # model never found is added on top -- otherwise those installations are counted
    # twice. Plus the roofclf-alone density estimate inside the calibrated cells.
    g["t2"] = g.osm_mwp_unmatched + g.est_mwp_rc + g.small_central
    # Tier 3: the flat-precision, thresholded national "High" figure (its own
    # "incremental" filter already excludes buildings near an existing >= 400 m2
    # candidate of any placement, so this does not double count against est_mwp_rc)
    # plus every large PV installation already known, of every placement.
    g["t3"] = g.small_high + g.est_mwp_rc

    totals = {k: float(g[k].sum()) for k in [
        "t1", "t2", "t3", "osm_mwp", "osm_mwp_roof", "osm_mwp_unmatched", "osm_n",
        "small_low", "small_central", "small_high", "est_mwp_rc", "est_mwp_rc_roof",
        "est_mwp_rc_ground", "n_pv_buildings",
    ]}
    totals["n_cells"] = int(len(g))
    totals["n_domain_cells"] = int(g.in_domain.sum())
    totals["n_osm_matched"] = int(osm.matched.sum())
    totals["n_candidates"] = int(len(cand))
    totals["osm_area_km2"] = float(osm.area_m2.sum() / 1e6)
    totals["osm_n_sub400"] = int((osm.area_m2 < 400).sum())
    return g, totals


def _rings(geom, tol: float = 0.01) -> list:
    g = geom.simplify(tol)
    polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    out = []
    for p in polys:
        if p.is_empty:
            continue
        out.append([[round(x, 3), round(y, 3)] for x, y in p.exterior.coords])
    return out


def build_payload() -> dict:
    g, totals = _tier_frame()

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         round(float(r.t1), 3), round(float(r.t2), 3), round(float(r.t3), 3),
         round(float(r.osm_mwp), 3), int(r.osm_n),
         round(float(r.small_low), 3), round(float(r.small_central), 3),
         round(float(r.est_mwp_rc), 3), int(r.in_domain),
         round(float(r.osm_mwp_unmatched), 3), int(r.n_pv_buildings),
         round(float(r.small_high), 3)]
        for r in g.itertuples()
    ]
    bounds = [
        round(float(g.lon0.min()), 3), round(float(g.lat0.min()), 3),
        round(float(g.lon0.max()) + 0.1, 3), round(float(g.lat0.max()) + 0.1, 3),
    ]

    provinces = []
    regions_path = DENSITY_DIR / "regions.geoparquet"
    if regions_path.exists():
        reg = gpd.read_parquet(regions_path)
        reg = reg[reg.level == "region"]
        keep = ["t1", "t2", "t3", "osm_mwp", "est_mwp_rc", "small_low", "small_central",
                "small_high"]
        pts = gpd.GeoDataFrame(
            g[keep], geometry=gpd.points_from_xy(
                g.lon0 + 0.05, g.lat0 + 0.05), crs=reg.crs,
        )
        j = gpd.sjoin(pts, reg[["region_id", "geometry"]], predicate="within", how="left")
        by_region = j.groupby("region_id")[keep].sum()
        for r in reg.itertuples():
            row = by_region.reindex([r.region_id]).fillna(0.0).iloc[0]
            provinces.append({
                "name": str(r.name),
                **{k: round(float(row[k]), 1) for k in keep},
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["t2"])

    # City labels reused from the bracket atlas payload so both pages annotate alike.
    bracket = _extract_json(BRACKET_HTML.read_text(), "pv")
    return {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": bracket.get("cities", []),
        "calibBoxes": bracket.get("calibBoxes", []),
        "totals": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in totals.items()},
    }


# ── shared design, borrowed from the sibling overview page ──────────────────────
# The two pages are the same document in two framings, so the palette and card
# scaffolding are sliced out of `build_pakistan_pv_overview.py` rather than duplicated
# here -- a copy would drift. The orientation SECTION, however, deliberately diverges
# from the sibling as of 2026-08-01 (this page drops the tilt/azimuth histograms and
# moves the validation-rate-by-size chart up next to the polar plot; the sibling keeps
# its original three-chart layout) -- so that markup and its render functions are
# defined directly below (`POSE_HTML`, `POSE_JS`) instead of sliced.
SIBLING = ROOT / "scripts" / "build_pakistan_pv_overview.py"


def _slice(text: str, start: str, end: str, what: str) -> str:
    try:
        i = text.index(start)
        j = text.index(end, i)
    except ValueError as exc:  # pragma: no cover - operator-facing
        raise ValueError(
            f"could not slice {what} out of {SIBLING.name}: marker {start!r}/{end!r} "
            "no longer present. Both overview pages share the same CSS; re-sync the "
            "markers or inline the fragment here."
        ) from exc
    return text[i:j]


def _shared_fragments() -> dict[str, str]:
    src = SIBLING.read_text()
    return {
        "css": _slice(src, "<style>", "</style>", "the CSS block") + "</style>",
    }


POSE_SECTION_HTML = r"""  <section class="sec" id="orientation">
    <div class="sec-head">
      <div>
        <div class="sec-label">Orientation</div>
        <div class="sec-title">Which way panels actually face</div>
      </div>
      <div class="sec-sub" id="poseN">n fitted / n checked</div>
    </div>

    <div class="grid">
      <section class="card">
        <div class="map-head">
          <div class="map-title">Fitted tilt (radius) × azimuth (angle)</div>
          <div class="map-sub" id="poseNMini"></div>
        </div>
        <div id="polar-wrap">
          <svg id="polar" class="posechart" viewBox="0 0 640 640" role="img"
            aria-label="Polar plot of fitted panel tilt and azimuth"></svg>
          <div class="ptip" id="ptip"></div>
        </div>
        <div class="pose-legend">
          <span class="li"><span class="sw sun"></span>rooftop generator</span>
          <span class="li"><span class="sw glint"></span>ground plant</span>
          <span class="li"><span class="sw excl"></span>unreachable by this sensor's fixed overpass time</span>
        </div>
      </section>

      <aside>
        <div class="card hero-mini">
          <div class="num" id="poseHero">0<small>%</small></div>
          <div class="lbl">of &ge;1,000 m² installations get a pose in this plot at all &mdash; the
          rest never produce two self-consistent spikes, so there's nothing to fit</div>
        </div>
        <div class="card" style="margin-top:14px;">
          <div class="stat-row2"><span class="l">&ge;1 spike, no fittable pose</span><span class="v" id="pOne">0%</span></div>
          <div class="stat-row2"><span class="l">no glint signal at all</span><span class="v" id="pNo">0%</span></div>
          <div class="stat-row2"><span class="l">azimuth range observed</span><span class="v" id="pAz">–</span></div>
          <div class="stat-row2"><span class="l">tilt IQR observed</span><span class="v" id="pTilt">–</span></div>
        </div>
        <div class="card" style="margin-top:14px;">
          <div class="hist-title2" id="stripTitle">Validation rate by installation size</div>
          <svg id="strip" class="posechart" viewBox="0 0 460 260" style="width:100%; height:auto; display:block;"></svg>
          <div class="pose-legend" style="margin-top:6px;padding-top:8px;">
            <span class="li"><span class="sw" style="background:var(--muted)"></span>detected (&ge;1 spike)</span>
            <span class="li"><span class="sw glint"></span>validated (&ge;2 consistent)</span>
          </div>
        </div>
      </aside>
    </div>
  </section>

"""

POSE_SECTION_JS = r"""  /* ── panel-orientation charts (recolored onto the same palette) ──── */
  function polarXY(cx, cy, r, azDeg) {
    const a = azDeg * Math.PI / 180;
    return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  }
  function buildWedgePath(cx, cy, r, fromDeg, toDeg) {
    let d = `M ${cx} ${cy} `;
    const steps = Math.round((toDeg - fromDeg) / 2);
    for (let i = 0; i <= steps; i++) {
      const az = fromDeg + (toDeg - fromDeg) * (i / steps);
      const [x, y] = polarXY(cx, cy, r, az % 360);
      d += `L ${x.toFixed(2)} ${y.toFixed(2)} `;
    }
    d += 'Z';
    return d;
  }

  function renderPolar() {
    const svg = document.getElementById('polar');
    svg.innerHTML = '';
    const cx = 320, cy = 320, R = 250, tiltMax = 30;
    svg.appendChild(el('path', { d: buildWedgePath(cx, cy, R, POSE.wedge[0], POSE.wedge[1]), fill: 'var(--panel-2)', opacity: 0.9 }));
    [10, 20, 30].forEach((t) => {
      const r = (t / tiltMax) * R;
      svg.appendChild(el('circle', { cx, cy, r, fill: 'none', stroke: 'var(--hair)', 'stroke-width': 1 }));
      const [lx, ly] = polarXY(cx, cy, r, 250);
      const lbl = el('text', { x: lx, y: ly, 'font-size': 11, 'text-anchor': 'middle' });
      lbl.textContent = t + '°';
      svg.appendChild(lbl);
    });
    const compass = [[0, 'N'], [45, 'NE'], [90, 'E'], [135, 'SE'], [180, 'S'], [225, 'SW'], [270, 'W'], [315, 'NW']];
    compass.forEach(([deg, label]) => {
      const [x1, y1] = polarXY(cx, cy, R, deg);
      const [x2, y2] = polarXY(cx, cy, R + 8, deg);
      svg.appendChild(el('line', { x1, y1, x2, y2, stroke: 'var(--muted)', 'stroke-width': 1 }));
      const [lx, ly] = polarXY(cx, cy, R + 24, deg);
      const t = el('text', { x: lx, y: ly, 'font-size': 12, 'text-anchor': 'middle', 'dominant-baseline': 'middle' });
      t.textContent = label;
      t.setAttribute('fill', (label === 'N' || label === 'E' || label === 'S' || label === 'W') ? 'var(--ink)' : 'var(--muted)');
      svg.appendChild(t);
    });
    POSE.hard_edges.forEach((deg) => {
      const [x2, y2] = polarXY(cx, cy, R, deg);
      svg.appendChild(el('line', { x1: cx, y1: cy, x2, y2, stroke: 'var(--muted)', 'stroke-width': 2, 'stroke-dasharray': '5,4' }));
    });
    const areas = POSE.points.map(d => d.a);
    const minA = Math.min(...areas), maxA = Math.max(...areas);
    const sizeFor = (a) => 3 + 7 * (Math.sqrt(a - minA + 1) / Math.sqrt(maxA - minA + 1));
    const tip = document.getElementById('ptip');
    const wrap = document.getElementById('polar-wrap');
    POSE.points.forEach((d) => {
      const r = (d.t / tiltMax) * R;
      const [x, y] = polarXY(cx, cy, r, d.az);
      const color = d.k === 'generator' ? 'var(--accent)' : 'var(--domain)';
      const c = el('circle', {
        cx: x, cy: y, r: sizeFor(d.a), fill: color, stroke: 'var(--panel)', 'stroke-width': 1,
        opacity: 0.9, style: 'cursor: pointer;',
      });
      c.addEventListener('mouseenter', () => {
        tip.innerHTML = `<b>${d.p}</b> · ${d.k} · ${d.pl}<br>` +
          `tilt ${d.t}° · az ${d.az}° · area ${Math.round(d.a).toLocaleString()} m²<br>` +
          `${d.n} consistent spike dates`;
        tip.classList.add('show');
      });
      c.addEventListener('mousemove', (ev) => {
        const rect = wrap.getBoundingClientRect();
        tip.style.left = (ev.clientX - rect.left) + 'px';
        tip.style.top = (ev.clientY - rect.top) + 'px';
      });
      c.addEventListener('mouseleave', () => tip.classList.remove('show'));
      svg.appendChild(c);
    });
  }

  function bar(svg, x, y, w, h, fill) {
    const r = el('rect', { x, y: y - h, width: w, height: Math.max(h, 0), fill });
    svg.appendChild(r);
  }
  function ptext(svg, x, y, s, opts) {
    opts = opts || {};
    const t = el('text', { x, y, 'font-size': opts.size || 10.5, 'text-anchor': opts.anchor || 'middle' });
    if (opts.fill) t.setAttribute('fill', opts.fill);
    t.textContent = s;
    svg.appendChild(t);
  }

  function renderStrip() {
    // Narrower, taller viewBox than the sibling page's version -- this copy renders
    // in the orientation grid's aside column (next to the polar plot) rather than a
    // full-width card, so the 1000x150 wide-and-flat layout would squash unreadably.
    const svg = document.getElementById('strip');
    svg.innerHTML = '';
    const rows = POSE.strip;
    const Wc = 460, Hc = 260, padL = 30, padR = 8, padT = 12, padB = 26;
    const plotW = Wc - padL - padR, plotH = Hc - padT - padB;
    const groupW = plotW / rows.length;
    rows.forEach(([label, det, val], i) => {
      const gx = padL + i * groupW;
      const bw = groupW * 0.3;
      const hDet = det / 100 * plotH, hVal = val / 100 * plotH;
      const baseY = padT + plotH;
      bar(svg, gx + groupW * 0.18, baseY - hDet, bw, hDet, 'var(--muted)');
      bar(svg, gx + groupW * 0.52, baseY - hVal, bw, hVal, 'var(--domain)');
      ptext(svg, gx + groupW / 2, Hc - 8, label, { size: 9, fill: 'var(--ink-2)' });
    });
    svg.appendChild(el('line', { x1: padL, x2: Wc - padR, y1: padT + plotH, y2: padT + plotH, stroke: 'var(--hair)' }));
    [0, 25, 50, 75].forEach(p => {
      const y = padT + plotH - (p / 100) * plotH;
      ptext(svg, padL - 6, y + 3, p + '%', { size: 9, anchor: 'end', fill: 'var(--muted)' });
    });
  }

"""


TEMPLATE = r"""<meta charset="utf-8">
<title>__PAGE_TITLE__</title>
<script id="pv" type="application/json">__PV_JSON__</script>
<script id="pose" type="application/json">__POSE_JSON__</script>

__CSS__
<style>
  /* This page's top legend tick runs to four digits on the ceiling tier, where the
     shared stylesheet only budgets for two; the centred label then overlaps the
     caption beside it. Reserve the overhang rather than move the label off its tick. */
  .legend .lg-col { padding-right: 26px; }
</style>

<button class="theme-btn" id="themeBtn" type="button" aria-label="Toggle light or dark theme">Dark mode</button>

<div class="wrap">
  <header>
    <p class="eyebrow">EarthPV · Sentinel-2 · OpenStreetMap · TerraMind · roofclf · SPPI</p>
    <h1>Pakistan's solar, counted three times over</h1>
    <p class="lede">The same country, the same imagery, three different standards of proof.
    <b>Verified</b> counts only PV a person has drawn in OpenStreetMap plus the small
    rooftops where two independent detectors agree. <b>Best estimate</b> adds the
    satellite model's own recall-corrected detections and its per-building density
    estimate: the highest figure this project is willing to defend. <b>Ceiling</b> swaps
    the small-PV side for a much looser national assumption &mdash; every roofclf-flagged
    building nationwide at a flat, un-tuned precision weight, not the calibrated per-cell
    estimate &mdash; and adds every large installation already known on top: a bound built
    on a cruder assumption, not a tighter measurement. The gap between the three is the
    honest measure of how much of this is still unresolved.</p>
  </header>

  <div class="kpis">
    <div class="kpi"><div class="v" id="kT1">0<small>MWp</small></div>
      <div class="k">Verified: mapped by people, or agreed by two detectors</div></div>
    <div class="kpi"><div class="v" id="kT2">0<small>MWp</small></div>
      <div class="k">Best estimate, the highest defensible figure</div></div>
    <div class="kpi"><div class="v" id="kOsm">0</div>
      <div class="k">Installations hand-mapped in OpenStreetMap</div></div>
    <div class="kpi"><div class="v" id="kDomain">0</div>
      <div class="k">of 0.1&deg; cells have density-matched sub-400 m&sup2; calibration</div></div>
    <div class="kpi"><div class="v" id="kPose">0<small>%</small></div>
      <div class="k">of &ge;1,000 m&sup2; installations yield a fitted panel orientation</div></div>
  </div>

  <section class="sec" id="capacity">
    <div class="sec-head">
      <div>
        <div class="sec-label">Capacity</div>
        <div class="sec-title">How much PV, by 0.1&deg; cell, by standard of proof</div>
      </div>
      <div class="switch" role="group" aria-label="Evidence tier">
        <button class="tab" id="tab0" type="button" data-i="0">
          <span class="tt1">Verified</span><span class="tt2">hand-mapped + two detectors agree</span>
        </button>
        <button class="tab" id="tab1" type="button" data-i="1">
          <span class="tt1">Best estimate</span><span class="tt2">+ calibrated detections + density</span>
        </button>
        <button class="tab" id="tab2" type="button" data-i="2">
          <span class="tt1">Ceiling</span><span class="tt2">flat precision, plus known large PV</span>
        </button>
      </div>
    </div>

    <div class="grid">
      <section class="card map-card">
        <div class="map-head">
          <div class="map-title">Capacity per cell at the selected standard of proof</div>
          <div class="map-sub">≈11 km × 11 km cells · log scale</div>
        </div>
        <div id="mapmount"></div>
        <div class="legend">
          <div class="lg-col">
            <div class="bar" id="legbar"></div>
            <div class="ticks" id="legticks"></div>
          </div>
          <div class="cap" id="legcap">MWp&nbsp;/&nbsp;cell, selected tier</div>
          <div class="large-key">
            <span class="sw"></span>hand-mapped OSM PV: ring size, always shown
          </div>
          <div class="domain-key" id="domainKey" style="margin-left:14px">
            <span class="sw"></span>cells with sub-400 m² calibration (dashed outline)
          </div>
          <div class="calib-key" style="margin-left:14px">
            <span class="sw"></span>hand-checked calibration area (hover for detail)
          </div>
        </div>
      </section>

      <aside>
        <div class="card">
          <div class="hero-num"><span id="heroNum">0</span><span class="hero-unit">MWp</span></div>
          <div class="hero-label" id="heroLabel">Selected tier, nationwide</div>
          <div class="hero-desc" id="heroDesc"></div>
          <div class="tiles" id="tiles"></div>
        </div>

        <div class="card rank" style="margin-top:14px;">
          <h3 id="rankH">Provinces, ranked by selected tier</h3>
          <div id="ranks"></div>
          <details class="tablewrap">
            <summary>Full province figures</summary>
            <div style="overflow-x:auto;"><table id="ptable">
              <thead><tr><th>Province</th><th>Verified</th><th>Best estimate</th>
                <th>Ceiling</th><th>OSM mapped</th><th>Model, &ge;400 m²</th>
                <th>Small PV, checked cells</th><th>Flat precision, national</th></tr></thead>
              <tbody></tbody>
            </table></div>
          </details>
        </div>
      </aside>
    </div>
  </section>

__POSE_HTML__
  <section class="sec" id="background">
    <div class="sec-head">
      <div>
        <div class="sec-label">Background</div>
        <div class="sec-title">How to read these numbers</div>
      </div>
    </div>

    <details class="xdetails">
      <summary><span><span class="xt">What each tier admits as evidence</span>
        <span class="xs">Verified / Best estimate / Ceiling, defined</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <dl class="viewdefs">
          <dt><span class="tag low">Verified</span> nothing here rests on a single model</dt>
          <dd><b>Every PV installation drawn by a person in OpenStreetMap</b>
          (<span id="dOsmN">0</span> of them, <span id="dOsmKm">0</span> km² of panel and
          site area), <b>plus</b> the sub-400 m² buildings where two independent
          instruments agree &mdash; roofclf, a per-building size and reflectance
          classifier, and SPPI, a zero-training spectral index. Requiring agreement
          raises measured precision from 0.55 to 0.62 on held-out hand-mapped quadrats,
          at the cost of recall. This is a <b>floor and it is known to be one</b>:
          OpenStreetMap coverage of Pakistan is incomplete and uneven, and the small-PV
          term only applies inside the checked cells.</dd>

          <dt><span class="tag central">Best estimate</span> this project's own pick</dt>
          <dd>The hand-mapped population <b>plus the satellite model's own &ge;400 m²
          detections</b>, precision-calibrated and recall-corrected, <b>plus</b> the
          roofclf per-building density estimate inside the same checked cells. The
          model's detections and the OSM mapping overlap heavily, so the overlap is
          removed rather than added twice (see the next section). This is the highest
          number the project defends; it is still incomplete, because the small-PV term
          covers only about a fifth of national buildings.</dd>

          <dt><span class="tag high">Ceiling</span> a bound, not an estimate</dt>
          <dd><b>A much looser assumption on the small-PV side, plus every large
          installation already known.</b> Every roofclf-flagged building nationwide
          (threshold 0.3064, the same cut used to train the classifier) is credited at a
          <b>flat 0.5 precision weight</b> &mdash; not its own per-building probability,
          not restricted to the density-checked cells &mdash; after excluding buildings
          that already sit near a known &ge;400 m² detection, so the two terms don't
          overlap. The large-PV side is the same recall-corrected total used everywhere
          else on this page, across every placement. The small-PV side is <b>explicitly
          uncalibrated at national scale</b>: a flat weight known not to survive the
          shift from nine urban/industrial calibration quadrats to the country's mostly
          rural buildings. Treat this tier as an outer bound on plausibility, not a
          measurement.</dd>
        </dl>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">How double counting is avoided</span>
        <span class="xs">the mapped and the detected are largely the same installations</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>OpenStreetMap and the satellite detector are looking at the same country, so
        naively adding them would count many installations twice. Each model detection
        carries the identity of the OSM feature it matched, if any:
        <b><span id="dMatched">0</span> of the <span id="dOsmN2">0</span> hand-mapped
        installations were also found by the model</b>, and those detections already
        carry the OSM geometry. The Best estimate therefore adds only the
        <b><span id="dUnmatched">0</span> MWp of hand-mapped PV the model never
        found</b>, on top of the model's own recall-corrected total.</p>
        <p>Two residual overlaps are known and small. The recall correction is itself an
        estimate of what the model missed, so adding measured misses on top double counts
        that correction &mdash; but nationally the correction only adds 0.8% to the
        calibrated total, so the effect is negligible here. Separately, small OSM rooftop
        installations may sit on buildings the roofclf term also flags; nationally all
        sub-400 m² OSM features together amount to under 200 MWp, so this is on the order
        of 1% of the Best estimate.</p>
        <p>The Ceiling tier avoids the same overlap by construction rather than by
        subtraction: its small-PV component only includes buildings with <b>no existing
        &ge;400 m² detection within 30 m</b> (the "incremental" population
        <code>roofclf_capacity.incremental_capacity</code> already computes), so adding
        the known large-PV total on top does not double count either.</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">Where the small-PV numbers apply</span>
        <span class="xs">reading the dashed outline on the map</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Installations under 400 m² are below the satellite detector's practical floor at
        10 m resolution, so they are estimated per building instead. That estimate is only
        reported <b>inside the dashed outline</b>: the
        <span id="dDomain">0</span> cells whose building density falls inside the range
        covered by the hand-mapped calibration quadrats. Outside it, small PV reads as zero
        in the Verified and Best estimate tiers &mdash; not because small solar is absent
        there, but because there is no calibration evidence either way. Those cells hold
        roughly a fifth of the country's buildings and concentrate in its largest cities,
        so both tiers understate the national small-PV total by an unknown but certainly
        positive amount.</p>
        <p>The Ceiling tier deliberately ignores this restriction, along with every other
        one.</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">External checks, outside this pipeline</span>
        <span class="xs">two independent, non-imagery anchors</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Two administrative and trade data points, neither derived from this pipeline,
        bracket the ladder from outside:</p>
        <div style="overflow-x:auto;"><table>
          <thead><tr><th style="text-align:left">Figure</th><th>Value</th><th style="text-align:left">Scope</th></tr></thead>
          <tbody id="anchorRows"></tbody>
        </table></div>
        <p style="margin-top:12px;"><b>NEPRA net-metering</b> (Pakistan's regulator, the closest
        available analogue to Germany's MaStR register): 5.3 GW registered nationally by April
        2025 across 283,000 consumers, average size 18.7 kWp &mdash; far below this project's
        400 m² detection floor, so the register is dominated by exactly the small rooftops the
        detector cannot see. It is a <b>floor, not a total</b>: unregistered, self-consumption
        and off-grid installations never appear in it.</p>
        <p><b>Chinese customs panel exports</b> put Pakistan's 2024 imports at 16.91 GW and
        roughly 50 GW cumulative by August 2025 &mdash; a loose order-of-magnitude ceiling,
        since it is import volume rather than installed capacity. Both the Best estimate
        and the Ceiling sit between the two anchors, with the Ceiling closer to the
        customs figure &mdash; that proximity is a coincidence of the flat precision
        weight chosen, not evidence the Ceiling is calibrated; its own components are
        still an explicitly uncalibrated national extrapolation, not a measurement.</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">Why the orientation plot only fills part of the circle</span>
        <span class="xs">a sensor limit, not a property of Pakistani rooftops</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Sentinel-2 crosses this latitude at a fixed <b>~10:30 local time</b>, so across two full
        years of imagery the sun's azimuth at the moment of every overpass never once swings west
        of due south. A panel facing southwest, west, or north <b>cannot glint into this sensor
        no matter how long you wait</b> &mdash; that is a limit of the satellite's orbit, not
        evidence about how rooftops in Pakistan are actually oriented. The shaded wedge marks
        orientations this survey cannot observe at all; nothing is drawn there because nothing
        was measured there.</p>
        <p>A further <span id="xOne">0</span>% of &ge;1,000 m² installations glint only once
        (or on dates that disagree on a panel geometry), so they are correctly flagged as
        "PV is probably here" but carry no orientation information; another
        <span id="xNo">0</span>% show no glint signal in either year.</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">Data &amp; methods</span>
        <span class="xs">what's under the hood</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Imagery is Sentinel-2 L2A, dry-season composites. <b>Hand-mapped PV</b> is the
        national OpenStreetMap solar pull, areas measured geodesically, converted at
        0.18 kWp/m² for rooftop module area and 0.07 kWp/m² for ground-mount site area.
        <b>Detections &ge;400 m²</b> come from a TerraMind geospatial foundation model
        fine-tuned for segmentation, trained on Germany and inferred on Pakistan, then
        precision-calibrated against a glint-based validation study and recall-corrected.
        <b>Sub-400 m² capacity</b> comes from two per-building instruments (roofclf, a
        size and reflectance classifier; SPPI, a zero-training spectral index) trained and
        validated on hand-mapped 1 km² quadrats, restricted to cells whose building density
        matches those quadrats (Verified and Best estimate), or applied nationally at a
        flat precision weight explicitly known to be uncalibrated at that scale (Ceiling).
        <b>Panel orientation</b> comes from fitting a fixed
        tilt and azimuth to specular sun-glint spikes across two years of imagery, checked
        for self-consistency across independent dates. Building footprints are VIDA Open
        Buildings. Full derivations and caveats live in this project's methodology notes
        (<code>docs/methods/density.md</code>).</p>
      </div>
    </details>
  </section>

  <div class="foot" id="foot"></div>
</div>

<div class="tip" id="tip" role="status" aria-live="off"></div>

<script>
(function () {
  const DATA = JSON.parse(document.getElementById("pv").textContent);
  const POSE = JSON.parse(document.getElementById("pose").textContent);
  const [b0, b1, b2, b3] = DATA.bounds;
  const lonspan = b2 - b0, latspan = b3 - b1;
  const meanlat = (b1 + b3) / 2, k = Math.cos(meanlat * Math.PI / 180);
  const W = 1000, H = Math.round(W * latspan / (lonspan * k));

  const RAMP_DARK = ["#3c2a12","#7a3f0e","#b5610f","#e07d17","#f5a623","#ffcf5c","#fff1c2"];
  const RAMP_LIGHT = ["#f2e3bf","#eec98a","#e5a24e","#d97f22","#c25e12","#9c4410","#5f2c0a"];

  /* cell columns: 0 lon0, 1 lat0, 2 verified, 3 best, 4 ceiling, 5 osm MWp, 6 osm n,
     7 small (and-gate), 8 small (roofclf), 9 model rc, 10 in_domain, 11 osm unmatched,
     12 buildings with a large-PV detection */
  const IDX = [2, 3, 4];
  const OSM_IDX = 5;
  const T = DATA.totals;
  const fmt = n => Math.round(n).toLocaleString("en-US");

  const VIEWS = [
    { key: "verified", label: "Verified", vmax: 3,
      name: "Verified: hand-mapped OSM PV, plus small rooftops two detectors both flag",
      desc: "No single model is trusted on its own here. Every installation is either drawn by a person or flagged independently by roofclf and SPPI.",
      tiles: [
        ["osm_mwp", "Hand-mapped OSM PV, MWp"],
        ["small_low", "Two detectors agree, MWp"],
        ["osm_n", "OSM installations"],
        ["n_domain_cells", "Cells with small-PV calibration"],
      ] },
    { key: "best", label: "Best estimate", vmax: 8,
      name: "Best estimate: mapped PV, plus calibrated detections, plus per-building density",
      desc: "Adds the model's own recall-corrected detections above 400 m² and its per-building estimate below, with the mapped-and-detected overlap removed.",
      tiles: [
        ["est_mwp_rc", "Model detections &ge;400 m², MWp"],
        ["osm_mwp_unmatched", "Mapped but never detected, MWp"],
        ["small_central", "Small PV, checked cells, MWp"],
        ["n_pv_buildings", "Buildings with a large detection"],
      ] },
    { key: "ceiling", label: "Ceiling", vmax: 40,
      name: "Ceiling: flat national precision, plus every large installation already known",
      desc: "roofclf flagged nationwide at a precision-tuned threshold, credited at a flat 0.5 precision rather than each building's own probability, restricted to buildings with no existing large detection nearby &mdash; plus every &ge;400 m² installation of any placement already known. An explicit, unvalidated national ceiling on the small-PV side; the large-PV side is real.",
      tiles: [
        ["small_high", "Flat-precision small PV, national, MWp"],
        ["est_mwp_rc", "Known large PV, all placements, MWp"],
        ["n_pv_buildings", "Buildings with a large detection"],
        ["n_cells", "Cells, no restriction"],
      ] },
  ];
  let sel = 1;

  function proj(lon, lat) {
    return [ (lon - b0) / lonspan * W, (b3 - lat) / latspan * H ];
  }
  function hex2rgb(h){ return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)]; }
  function lerp(a,b,t){ return a+(b-a)*t; }
  function ramp(t, stops){
    t = Math.max(0, Math.min(1, t));
    const n = stops.length - 1, f = t * n, i = Math.min(n-1, Math.floor(f)), r = f - i;
    const a = hex2rgb(stops[i]), c = hex2rgb(stops[i+1]);
    return `rgb(${Math.round(lerp(a[0],c[0],r))},${Math.round(lerp(a[1],c[1],r))},${Math.round(lerp(a[2],c[2],r))})`;
  }

  function isDark(){
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr) return attr === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  const SVGNS = "http://www.w3.org/2000/svg";
  function el(n, a){ const e = document.createElementNS(SVGNS, n); for (const kk in a) e.setAttribute(kk, a[kk]); return e; }

  function ringPath(rings){
    let d = "";
    for (const ring of rings){
      for (let i=0;i<ring.length;i++){
        const p = proj(ring[i][0], ring[i][1]);
        d += (i===0?"M":"L") + p[0].toFixed(1) + " " + p[1].toFixed(1);
      }
      d += "Z";
    }
    return d;
  }

  function renderMap(){
    const dark = isDark();
    const stops = dark ? RAMP_DARK : RAMP_LIGHT;
    const view = VIEWS[sel], mi = IDX[sel];
    const VMIN = 0.02, VMAX = Math.max(view.vmax, 0.1, ...DATA.cells.map(c => c[mi]));
    const lVMIN = Math.log(VMIN), lVMAX = Math.log(VMAX);
    const tOf = (v) => (Math.log(Math.max(v, VMIN)) - lVMIN) / (lVMAX - lVMIN);
    const bright = (v) => v > 0 ? tOf(v) : -1;

    const osmMax = Math.max(1, ...DATA.cells.map(c => c[OSM_IDX]));

    const mount = document.getElementById("mapmount");
    mount.innerHTML = "";
    const svg = el("svg", {viewBox:`0 0 ${W} ${H}`, class:"map", role:"img",
      "aria-label":`Choropleth map of Pakistan showing ${view.name}, with hand-mapped OpenStreetMap PV always overlaid as rings`});

    svg.appendChild(el("rect", {x:0,y:0,width:W,height:H,fill:"var(--map-bg)"}));

    const defs = el("defs", {});
    const filt = el("filter", {id:"bloom", x:"-20%", y:"-20%", width:"140%", height:"140%"});
    filt.appendChild(el("feGaussianBlur", {stdDeviation:"4"}));
    defs.appendChild(filt); svg.appendChild(defs);

    const gLand = el("g", {});
    for (const p of DATA.provinces) gLand.appendChild(el("path", {d:ringPath(p.rings), class:"prov-fill"}));
    svg.appendChild(gLand);

    const cw = (0.1 / lonspan * W) + 0.4, ch = (0.1 / latspan * H) + 0.4;
    const lit = DATA.cells.filter(c => c[mi] > 0).sort((a,b)=>a[mi]-b[mi]);

    if (dark){
      const gB = el("g", {filter:"url(#bloom)", opacity:"var(--bloom)"});
      for (const c of lit){
        const tl = proj(c[0], c[1] + 0.1);
        gB.appendChild(el("rect", {x:tl[0].toFixed(1), y:tl[1].toFixed(1),
          width:cw.toFixed(1), height:ch.toFixed(1), fill:ramp(bright(c[mi]), stops)}));
      }
      svg.appendChild(gB);
    }

    const gC = el("g", {});
    for (const c of DATA.cells){
      const tl = proj(c[0], c[1] + 0.1);
      const t = bright(c[mi]);
      const r = el("rect", {x:tl[0].toFixed(1), y:tl[1].toFixed(1),
        width:cw.toFixed(1), height:ch.toFixed(1),
        fill: t >= 0 ? ramp(t, stops) : "var(--land)", class:"cell"});
      r.__c = c;
      gC.appendChild(r);
    }
    svg.appendChild(gC);

    if (sel < 2 && DATA.cells.some(c => c[10])) {
      const gD = el("g", {class:"domain-ring"});
      for (const c of DATA.cells){
        if (!c[10]) continue;
        const tl = proj(c[0], c[1] + 0.1);
        gD.appendChild(el("rect", {
          x:(tl[0]+0.8).toFixed(1), y:(tl[1]+0.8).toFixed(1),
          width:Math.max(cw-1.6,0.5).toFixed(1), height:Math.max(ch-1.6,0.5).toFixed(1),
          class:"domain-ring-rect",
        }));
      }
      svg.appendChild(gD);
    }

    {
      const gL = el("g", {class:"large-ring"});
      for (const c of DATA.cells){
        if (c[OSM_IDX] <= 0) continue;
        const frac = Math.min(1, Math.sqrt(c[OSM_IDX] / osmMax));
        const rad = 0.9 + frac * (Math.min(cw, ch) * 0.42);
        gL.appendChild(el("circle", {
          cx: (proj(c[0], c[1]+0.05)[0]).toFixed(1), cy: (proj(c[0], c[1]+0.05)[1]).toFixed(1),
          r: rad.toFixed(2), class:"large-dot", "stroke-width": (0.6 + frac*1.2).toFixed(2),
        }));
      }
      svg.appendChild(gL);
    }

    const gS = el("g", {});
    for (const p of DATA.provinces) gS.appendChild(el("path", {d:ringPath(p.rings), class:"prov-line"}));
    svg.appendChild(gS);

    const gCity = el("g", {});
    for (const [nm, lon, lat] of DATA.cities){
      if (lon < b0 || lon > b2 || lat < b1 || lat > b3) continue;
      const p = proj(lon, lat);
      gCity.appendChild(el("circle", {cx:p[0].toFixed(1), cy:p[1].toFixed(1), r:2.6, class:"city-dot"}));
      const t = el("text", {x:(p[0]+8).toFixed(1), y:(p[1]+7).toFixed(1), class:"city-label"});
      t.textContent = nm; gCity.appendChild(t);
    }
    svg.appendChild(gCity);

    if (DATA.calibBoxes && DATA.calibBoxes.length){
      const gCalib = el("g", {class:"calib-group"});
      for (const b of DATA.calibBoxes){
        if (b.lon < b0 || b.lon > b2 || b.lat < b1 || b.lat > b3) continue;
        if (b.rings && b.rings.length) {
          gCalib.appendChild(el("path", {d:ringPath(b.rings), class:"calib-ring"}));
        }
        const p = proj(b.lon, b.lat);
        const dot = el("circle", {
          cx:p[0].toFixed(1), cy:p[1].toFixed(1), r:4.5, class:"calib-dot", tabindex:"0",
        });
        dot.__b = b;
        gCalib.appendChild(dot);
      }
      svg.appendChild(gCalib);
    }

    const tip = document.getElementById("tip");
    gC.addEventListener("pointermove", (e) => {
      const c = e.target.__c; if (!c){ tip.style.opacity = 0; return; }
      tip.style.opacity = 1; tip.style.left = e.clientX + "px"; tip.style.top = e.clientY + "px";
      const clon = (c[0]+0.05).toFixed(2), clat = (c[1]+0.05).toFixed(2);
      const rows = VIEWS.map((v, i) =>
        `<div class="rowt${i===sel?' sel':''}"><span>${v.label}</span><span>${c[IDX[i]].toFixed(1)} MWp</span></div>`
      ).join("");
      tip.innerHTML = `<div class="th">CELL ${clat}°N ${clon}°E</div>`
        + rows
        + `<div class="rowt large-flag"><span>&#9675; Hand-mapped in OSM</span><span>${c[OSM_IDX].toFixed(1)} MWp</span></div>`
        + `<div class="rowt"><span>&nbsp;&nbsp;OSM installations</span><span>${c[6].toLocaleString()}</span></div>`
        + `<div class="rowt"><span>Model detections &ge;400 m²</span><span>${c[9].toFixed(1)} MWp</span></div>`
        + `<div class="rowt"><span>Small PV, roofclf alone</span><span>${c[8].toFixed(1)} MWp</span></div>`
        + `<div class="rowt"><span>Flat precision, national</span><span>${c[13].toFixed(1)} MWp</span></div>`
        + (c[10] ? `<div class="rowt domain-flag"><span>&#9679; Small-PV calibration</span><span>checked</span></div>` : "");
    });
    gC.addEventListener("pointerleave", () => { tip.style.opacity = 0; });

    svg.querySelectorAll(".calib-dot").forEach((dot) => {
      dot.addEventListener("pointerenter", (e) => {
        const b = e.target.__b;
        tip.style.opacity = 1; tip.style.left = e.clientX + "px"; tip.style.top = e.clientY + "px";
        const statusLabel = b.status === "rule1"
          ? "Fully checked against real ground survey"
          : b.status === "suspect"
          ? "Needs re-checking"
          : "Checked against high-resolution imagery";
        tip.innerHTML = `<div class="th">CALIBRATION AREA: ${b.name}</div>`
          + `<div class="rowt"><span>Mapped installations</span><span>${b.n}</span></div>`
          + `<div class="rowt"><span>Status</span><span>${statusLabel}</span></div>`;
      });
      dot.addEventListener("pointermove", (e) => {
        tip.style.left = e.clientX + "px"; tip.style.top = e.clientY + "px";
      });
      dot.addEventListener("pointerleave", () => { tip.style.opacity = 0; });
    });

    mount.appendChild(svg);

    const grad = stops.map((s,i)=>`${s} ${(i/(stops.length-1)*100).toFixed(0)}%`).join(",");
    document.getElementById("legbar").style.background = `linear-gradient(90deg, ${grad})`;
    const ticks = [VMIN, Math.sqrt(VMIN*VMAX), VMAX].map(v => Math.round(v*100)/100);
    document.getElementById("legticks").innerHTML =
      ticks.map(v => `<span style="left:${(tOf(v)*100).toFixed(1)}%">${v}</span>`).join("");
    document.getElementById("legcap").textContent = `MWp per cell, ${view.label} tier`;
  }

  function countUp(id, target, dur){
    const e = document.getElementById(id);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches){ e.textContent = fmt(target); return; }
    const t0 = performance.now();
    function step(now){
      const p = Math.min(1, (now - t0)/dur), e2 = 1 - Math.pow(1-p, 3);
      e.textContent = fmt(target * e2);
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  document.getElementById("kT1").innerHTML = `${fmt(T.t1)}<small>MWp</small>`;
  document.getElementById("kT2").innerHTML = `${fmt(T.t2)}<small>MWp</small>`;
  document.getElementById("kOsm").textContent = fmt(T.osm_n);
  document.getElementById("kDomain").innerHTML = `${fmt(T.n_domain_cells)}<small>/ ${fmt(T.n_cells)}</small>`;

  const TOTAL_KEY = ["t1", "t2", "t3"];
  const PROV_KEY = ["t1", "t2", "t3"];

  function drawTable() {
    const provs = [...DATA.provinces].sort((a,b) => b[PROV_KEY[sel]] - a[PROV_KEY[sel]]);
    const maxP = provs.length ? Math.max(...provs.map(p => p[PROV_KEY[sel]]), 1) : 1;
    document.getElementById("ranks").innerHTML = provs.map(p => {
      const nm = p.name.replace("Islamabad Capital Territory","Islamabad").replace("Khyber Pakhtunkhwa","Kh. Pakhtunkhwa");
      const v = p[PROV_KEY[sel]];
      return `<div class="row"><div class="top"><span class="nm">${nm}</span>`
        + `<span class="vl">${fmt(v)} MWp</span></div>`
        + `<div class="track"><div class="fill" style="width:${(v/maxP*100).toFixed(1)}%"></div></div></div>`;
    }).join("");
    document.querySelector("#ptable tbody").innerHTML = provs.map(p =>
      `<tr><td>${p.name}</td><td>${fmt(p.t1)}</td><td>${fmt(p.t2)}</td><td>${fmt(p.t3)}</td>`
      + `<td>${fmt(p.osm_mwp)}</td><td>${fmt(p.est_mwp_rc)}</td><td>${fmt(p.small_central)}</td>`
      + `<td>${fmt(p.small_high)}</td></tr>`).join("");
  }

  function setView(i) {
    sel = i;
    ["tab0", "tab1", "tab2"].forEach((id, j) =>
      document.getElementById(id).setAttribute("aria-pressed", String(j === i)));
    const view = VIEWS[i];
    countUp("heroNum", T[TOTAL_KEY[i]], 700);
    document.getElementById("heroLabel").textContent = `${view.label}, nationwide`;
    document.getElementById("heroDesc").innerHTML = `<b>${view.name}.</b> ${view.desc}`;
    document.getElementById("tiles").innerHTML = view.tiles.map(([key, label]) =>
      `<div class="tile"><div class="v">${fmt(T[key])}</div><div class="k">${label}</div></div>`).join("");
    document.getElementById("rankH").textContent = `Provinces, ranked by ${view.label.toLowerCase()}`;
    document.getElementById("domainKey").style.display = i < 2 ? "" : "none";
    renderMap(); drawTable();
  }
  ["tab0", "tab1", "tab2"].forEach((id, i) =>
    document.getElementById(id).addEventListener("click", () => setView(i)));

  const ANCHORS = [
    ["Verified (mapped, or two detectors agree)", fmt(T.t1) + " MWp", "national mapping + 93 checked cells"],
    ["NEPRA net-metering register", "5,300 MWp", "national, registered installations only"],
    ["Best estimate (this project's pick)", fmt(T.t2) + " MWp", "national detections + 93 checked cells"],
    ["Ceiling (flat precision, plus known large PV)", fmt(T.t3) + " MWp", "national, unrestricted, uncalibrated"],
    ["Chinese customs, cumulative imports", "~50,000 MWp", "national, all market segments"],
  ];
  document.getElementById("anchorRows").innerHTML = ANCHORS.map(([a,b,c]) =>
    `<tr><td style="text-align:left">${a}</td><td>${b}</td><td style="text-align:left">${c}</td></tr>`).join("");

  document.getElementById("dOsmN").textContent = fmt(T.osm_n);
  document.getElementById("dOsmN2").textContent = fmt(T.osm_n);
  document.getElementById("dOsmKm").textContent = T.osm_area_km2.toFixed(1);
  document.getElementById("dMatched").textContent = fmt(T.n_osm_matched);
  document.getElementById("dUnmatched").textContent = fmt(T.osm_mwp_unmatched);
  document.getElementById("dDomain").textContent = fmt(T.n_domain_cells);

__POSE_JS__
  function renderPose(){ renderPolar(); renderStrip(); }

  document.getElementById("poseN").textContent = `n=${POSE.points.length} fitted of __POSE_N_TOTAL__ checked`;
  document.getElementById("poseNMini").textContent = `${POSE.points.length} measured`;
  document.getElementById("kPose").innerHTML = `__POSE_PCT_GE1000__<small>%</small>`;
  document.getElementById("poseHero").innerHTML = `__POSE_PCT_GE1000__<small>%</small>`;
  document.getElementById("pOne").textContent = `__POSE_PCT_ONESPIKE__%`;
  document.getElementById("pNo").textContent = `__POSE_PCT_NOSIGNAL__%`;
  document.getElementById("pAz").textContent = `__POSE_AZ_MIN__° – __POSE_AZ_MAX__°`;
  document.getElementById("pTilt").textContent = `__POSE_TILT_Q25__° – __POSE_TILT_Q75__°`;
  document.getElementById("xOne").textContent = `__POSE_PCT_ONESPIKE__`;
  document.getElementById("xNo").textContent = `__POSE_PCT_NOSIGNAL__`;
  document.getElementById("stripTitle").textContent =
    `Validation rate by installation size (all __POSE_N_TOTAL__ checked, not just the __POSE_N_FITTED__ fitted)`;

  document.getElementById("foot").innerHTML =
    `OpenStreetMap national solar pull + TerraMind-tiny segmentation + roofclf/SPPI per-building `
    + `classifiers + glint geometry · ${fmt(T.n_cells)} cells × 0.1° · 0.18 kWp/m² of module area, `
    + `0.07 kWp/m² of ground-mount site area · Sentinel-2 L2A dry-season composites · `
    + `buildings from VIDA Open Buildings · see docs/methods/density.md for full derivations.`;

  const btn = document.getElementById("themeBtn");
  function updateThemeBtn(){ btn.textContent = isDark() ? "Light mode" : "Dark mode"; }
  function renderAll(){ renderMap(); renderPose(); }
  btn.addEventListener("click", () => {
    const cur = isDark();
    document.documentElement.setAttribute("data-theme", cur ? "light" : "dark");
    updateThemeBtn();
    renderAll();
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!document.documentElement.getAttribute("data-theme")) { updateThemeBtn(); renderAll(); }
  });

  updateThemeBtn();
  setView(sel);
  renderPose();
})();
</script>
"""


def main() -> None:
    payload = build_payload()
    pose = _extract_json(POSE_HTML.read_text(), "pvdata")
    stats = _pose_stats(POSE_CSV)
    az_min, az_max = pose["hard_edges"]
    frag = _shared_fragments()

    html = TEMPLATE
    for key, value in {
        "__CSS__": frag["css"],
        "__POSE_HTML__": POSE_SECTION_HTML,
        "__POSE_JS__": POSE_SECTION_JS,
        "__PAGE_TITLE__": "Pakistan Solar PV — Counted Three Times Over",
        "__PV_JSON__": json.dumps(payload, separators=(",", ":")),
        "__POSE_JSON__": json.dumps(pose, separators=(",", ":")),
        "__POSE_N_TOTAL__": str(stats["n_total"]),
        "__POSE_N_FITTED__": str(stats["n_fitted"]),
        "__POSE_PCT_GE1000__": f"{stats['pct_ge1000']:.1f}",
        "__POSE_PCT_ONESPIKE__": f"{stats['pct_onespike']:.1f}",
        "__POSE_PCT_NOSIGNAL__": f"{stats['pct_nosignal']:.1f}",
        "__POSE_AZ_MIN__": f"{az_min:.1f}",
        "__POSE_AZ_MAX__": f"{az_max:.1f}",
        "__POSE_TILT_Q25__": f"{stats['tilt_q25']:.1f}",
        "__POSE_TILT_Q75__": f"{stats['tilt_q75']:.1f}",
    }.items():
        html = html.replace(key, value)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    t = payload["totals"]
    print(f"-> {OUT} ({len(html):,} bytes)")
    print(f"   verified {t['t1']:,.0f} / best {t['t2']:,.0f} / ceiling {t['t3']:,.0f} MWp")


if __name__ == "__main__":
    main()
