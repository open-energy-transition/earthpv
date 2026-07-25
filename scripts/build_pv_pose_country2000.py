"""Build results/glint_validation_pakistan/pv_pose_country2000.html -- the 2000-target
country-scale re-run of pv_pose_pakistan.html's fitted-orientation polar plot.

Same page design (polar tilt(radius) x azimuth(angle) plot with the sensor-geometry
mirror-across-180deg trick, tilt/azimuth histograms, detected/validated strip chart),
but every number is recomputed from data/glint/country2000_summary.csv (n=2000,
4x the original study) instead of hardcoded. In particular the mirror axis and the
"still unreachable" excluded wedge are derived from this run's own observed
min/max fitted azimuth, not the original study's 81.7/180.1.

Usage: .pixi/envs/default/bin/python scripts/build_pv_pose_country2000.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SUMMARY = Path("data/glint/country2000_summary.csv")
OUT = Path("results/glint_validation_pakistan/pv_pose_country2000.html")

TEMPLATE = r"""<title>__PAGE_TITLE__</title>
<style>
:root {
  --bg: #f2efe6;
  --bg-panel: #eae4d3;
  --bg-chart: #ece6d6;
  --ink: #2a2620;
  --ink-dim: #675f4d;
  --ink-faint: #a49874;
  --rule: #d6cbac;
  --accent-sun: #a8641f;
  --accent-glint: #1f7a72;
  --excluded: #ddd3b3;
  --excluded-line: #b7a87d;
  --card-shadow: 0 1px 2px rgba(60,50,20,0.06);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #11151d; --bg-panel: #171d28; --bg-chart: #141a24;
    --ink: #e9e6db; --ink-dim: #8d94a6; --ink-faint: #565e70;
    --rule: #262d3c; --accent-sun: #e3a34d; --accent-glint: #5fc9c1;
    --excluded: #202536; --excluded-line: #333c52; --card-shadow: none;
  }
}
:root[data-theme="dark"] {
  --bg: #11151d; --bg-panel: #171d28; --bg-chart: #141a24;
  --ink: #e9e6db; --ink-dim: #8d94a6; --ink-faint: #565e70;
  --rule: #262d3c; --accent-sun: #e3a34d; --accent-glint: #5fc9c1;
  --excluded: #202536; --excluded-line: #333c52; --card-shadow: none;
}
:root[data-theme="light"] {
  --bg: #f2efe6; --bg-panel: #eae4d3; --bg-chart: #ece6d6;
  --ink: #2a2620; --ink-dim: #675f4d; --ink-faint: #a49874;
  --rule: #d6cbac; --accent-sun: #a8641f; --accent-glint: #1f7a72;
  --excluded: #ddd3b3; --excluded-line: #b7a87d; --card-shadow: 0 1px 2px rgba(60,50,20,0.06);
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--ink); }
body { font-family: Iowan Old Style, Sitka Text, Georgia, "Noto Serif", serif; font-size: 16px; line-height: 1.55; -webkit-font-smoothing: antialiased; }
.mono { font-family: ui-monospace, SFMono-Regular, "Cascadia Code", "Roboto Mono", Consolas, monospace; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 48px 24px 64px; }
header { margin-bottom: 40px; }
.eyebrow { font-size: 11px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--ink-dim); margin: 0 0 14px; }
h1 { font-size: clamp(28px, 4vw, 42px); font-weight: 600; line-height: 1.12; margin: 0 0 14px; text-wrap: balance; max-width: 20ch; }
.dek { font-size: 17px; color: var(--ink-dim); max-width: 62ch; margin: 0; }
.dek .mono { font-size: 15px; }
.grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr); gap: 28px; align-items: start; }
@media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }
.panel { background: var(--bg-panel); border: 1px solid var(--rule); border-radius: 3px; box-shadow: var(--card-shadow); }
.chart-panel { padding: 22px 22px 18px; }
.chart-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; flex-wrap: wrap; gap: 8px; }
.chart-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--ink-dim); font-family: inherit; }
.chart-title.mono { font-family: ui-monospace, SFMono-Regular, "Cascadia Code", "Roboto Mono", Consolas, monospace; }
.chart-n { font-size: 12px; color: var(--ink-faint); }
#polar-wrap { position: relative; width: 100%; }
#polar { width: 100%; height: auto; display: block; }
.legend { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 6px; padding-top: 14px; border-top: 1px solid var(--rule); font-size: 12.5px; color: var(--ink-dim); }
.legend-item { display: flex; align-items: center; gap: 7px; }
.swatch { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
.swatch.sun { background: var(--accent-sun); }
.swatch.glint { background: var(--accent-glint); }
.swatch.excl { width: 13px; height: 13px; border-radius: 2px; background: repeating-linear-gradient(45deg, var(--excluded-line), var(--excluded-line) 1px, var(--excluded) 1px, var(--excluded) 4px); border: 1px solid var(--excluded-line); }
.swatch.mirror { background: transparent; border: 1.5px dashed var(--ink-faint); }
.tooltip { position: absolute; pointer-events: none; background: var(--ink); color: var(--bg); font-size: 11.5px; padding: 7px 9px; border-radius: 3px; line-height: 1.5; white-space: nowrap; transform: translate(-50%, -115%); opacity: 0; transition: opacity 0.1s; z-index: 5; }
.tooltip.show { opacity: 0.96; }
.tooltip b { font-weight: 600; }
.sidebar { display: flex; flex-direction: column; gap: 16px; }
.stat-card { padding: 16px 18px; }
.stat-row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 7px 0; }
.stat-row + .stat-row { border-top: 1px dashed var(--rule); }
.stat-label { font-size: 12.5px; color: var(--ink-dim); }
.stat-val { font-size: 15px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.stat-big { padding: 16px 18px; }
.stat-big .num { font-size: 32px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1; }
.stat-big .num small { font-size: 16px; font-weight: 400; color: var(--ink-dim); }
.stat-big .label { font-size: 12.5px; color: var(--ink-dim); margin-top: 6px; }
.callout { padding: 18px 20px; border-left: 3px solid var(--accent-sun); }
.callout h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--ink-dim); margin: 0 0 10px; font-family: inherit; }
.callout p { margin: 0 0 10px; font-size: 14.5px; }
.callout p:last-child { margin-bottom: 0; }
.callout .fig { font-weight: 600; color: var(--ink); }
.lower { margin-top: 28px; display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
@media (max-width: 760px) { .lower { grid-template-columns: 1fr; } }
.hist-panel { padding: 18px 20px 14px; }
.hist-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--ink-dim); margin-bottom: 10px; }
svg text { fill: var(--ink-dim); }
.strip-panel { margin-top: 20px; padding: 18px 20px 16px; }
.strip-title { font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--ink-dim); margin-bottom: 12px; }
footer { margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--rule); font-size: 12.5px; color: var(--ink-faint); }
footer p { margin: 0 0 6px; max-width: 70ch; }
</style>

<div class="wrap">
  <header>
    <p class="eyebrow mono">Glint-derived orientation survey · Pakistan · n=2000</p>
    <h1>Which way does a Pakistani solar panel actually face? (4x sample)</h1>
    <p class="dek">
      Fitted tilt and azimuth for <span class="mono" id="hdr-n">__N_FITTED__</span> installations whose
      historical Sentinel-2 specular reflections agree on a single fixed panel orientation --
      out of <span class="mono">__N_TOTAL__</span> installations checked, stratified by size, across
      two years of imagery (a 4x-larger, chunked-tile-batch re-run of the original 500-target study).
      <b>This is not a neutral sample of installed pose</b> -- read the envelope note before trusting the shape.
    </p>
  </header>

  <div class="grid">
    <div class="panel chart-panel">
      <div class="chart-head">
        <span class="chart-title mono">Tilt (radius) x Azimuth (angle)</span>
        <span class="chart-n mono">__N_FITTED__ measured + __N_FITTED__ mirrored (assumed)</span>
      </div>
      <div id="polar-wrap">
        <svg id="polar" viewBox="0 0 640 640" role="img" aria-label="Polar plot of fitted panel tilt and azimuth"></svg>
        <div class="tooltip" id="tooltip"></div>
      </div>
      <div class="legend">
        <span class="legend-item"><span class="swatch sun"></span> rooftop generator</span>
        <span class="legend-item"><span class="swatch glint"></span> ground plant</span>
        <span class="legend-item"><span class="swatch mirror"></span> mirrored across 180&deg; -- assumed, not measured</span>
        <span class="legend-item"><span class="swatch excl"></span> still unreachable even under mirror symmetry</span>
      </div>
    </div>

    <div class="sidebar">
      <div class="panel stat-big">
        <div class="num">__PCT_GE1000__<small>%</small></div>
        <div class="label">of &ge; 1,000 m&sup2; installations get a pose in this plot at all -- the rest never produce two self-consistent spikes, so there's nothing to fit</div>
      </div>
      <div class="panel stat-card">
        <div class="stat-row"><span class="stat-label">&ge;1 spike, no fittable pose&dagger;</span><span class="stat-val mono">__PCT_ONESPIKE__%</span></div>
        <div class="stat-row"><span class="stat-label">no glint signal at all</span><span class="stat-val mono">__PCT_NOSIGNAL__%</span></div>
        <div class="stat-row"><span class="stat-label">azimuth range observed</span><span class="stat-val mono">__AZ_MIN__&deg; &ndash; __AZ_MAX__&deg;</span></div>
        <div class="stat-row"><span class="stat-label">tilt IQR observed</span><span class="stat-val mono">__TILT_Q25__&deg; &ndash; __TILT_Q75__&deg;</span></div>
      </div>
      <p style="font-size:11.5px;color:var(--ink-faint);margin:-6px 2px 0;">figures restricted to the &ge; 1,000 m&sup2; target class (n=__N_GE1000__ of __N_TOTAL__)</p>
      <div class="panel callout">
        <h3>Why nothing measured crosses 180&deg; -- and the mirrored half</h3>
        <p>
          Sentinel-2 crosses this latitude at a fixed <b>~10:30 local time</b>, so across two full
          years of imagery the sun's azimuth at the moment of every overpass never once swings
          west of due south -- a panel facing southwest, west, or north <b>cannot glint into this
          sensor no matter how long you wait.</b> That's a sensor limit, not a property of
          Pakistani rooftops, so the <span class="fig">dashed outline points beyond 180&deg;</span>
          are this same measured sample <b>mirrored</b> across the south axis. The residual shaded
          wedge (<span class="fig">__WEDGE_DEG__&deg;</span> wide) is what stays unreachable even
          granting the mirror-symmetry assumption.
        </p>
        <p>
          &dagger; A single spike can't be checked for self-consistency -- __PCT_ONESPIKE__% of installations glint
          <i>once</i> (or on dates that disagree on a panel geometry) and so are correctly
          detected as "PV is probably here" but carry <b>no orientation information</b>.
        </p>
      </div>
    </div>
  </div>

  <div class="lower">
    <div class="panel hist-panel">
      <div class="hist-title mono">Tilt distribution</div>
      <svg id="hist-tilt" viewBox="0 0 460 200"></svg>
    </div>
    <div class="panel hist-panel">
      <div class="hist-title mono">Azimuth distribution <span style="opacity:.6">(180&deg; = geometric ceiling)</span></div>
      <svg id="hist-az" viewBox="0 0 460 200"></svg>
    </div>
  </div>

  <div class="panel strip-panel">
    <div class="strip-title mono">For context -- validation rate by installation size (all __N_TOTAL__, not just the fitted __N_FITTED__)</div>
    <svg id="strip" viewBox="0 0 1000 150" style="width:100%; height:auto; display:block;"></svg>
  </div>

  <footer>
    <p>
      Data: <span class="mono">data/glint/country2000_summary.csv</span> (2000-target stratified
      country study, chunked tile-batch pull). Validated = a single
      (tilt, azimuth) explains &ge; 2 independent spike dates via the specular reflection condition,
      tolerance 3&deg;. Point size &prop; &radic;(installation area).
    </p>
  </footer>
</div>

<script type="application/json" id="pvdata">__PV_DATA_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById("pvdata").textContent);

const isDark = () => {
  const t = document.documentElement.getAttribute('data-theme');
  if (t === 'dark') return true;
  if (t === 'light') return false;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
};
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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
  const NS = 'http://www.w3.org/2000/svg';
  const cx = 320, cy = 320, R = 250, tiltMax = 30;
  const ink = css('--ink'), inkFaint = css('--ink-faint'), rule = css('--rule'),
        sun = css('--accent-sun'), glint = css('--accent-glint'),
        excl = css('--excluded'), exclLine = css('--excluded-line');
  const el = (tag, attrs) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  svg.appendChild(el('path', { d: buildWedgePath(cx, cy, R, DATA.wedge[0], DATA.wedge[1]), fill: excl, opacity: 0.9 }));
  [10, 20, 30].forEach((t) => {
    const r = (t / tiltMax) * R;
    svg.appendChild(el('circle', { cx, cy, r, fill: 'none', stroke: rule, 'stroke-width': 1 }));
    const [lx, ly] = polarXY(cx, cy, r, 250);
    const lbl = el('text', { x: lx, y: ly, 'font-size': 11, 'text-anchor': 'middle', class: 'mono' });
    lbl.textContent = t + '°';
    svg.appendChild(lbl);
  });
  const compass = [[0, 'N'], [45, 'NE'], [90, 'E'], [135, 'SE'], [180, 'S'], [225, 'SW'], [270, 'W'], [315, 'NW']];
  compass.forEach(([deg, label]) => {
    const [x1, y1] = polarXY(cx, cy, R, deg);
    const [x2, y2] = polarXY(cx, cy, R + 8, deg);
    svg.appendChild(el('line', { x1, y1, x2, y2, stroke: inkFaint, 'stroke-width': 1 }));
    const [lx, ly] = polarXY(cx, cy, R + 24, deg);
    const t = el('text', { x: lx, y: ly, 'font-size': 12, 'text-anchor': 'middle', 'dominant-baseline': 'middle' });
    t.setAttribute('class', 'mono');
    t.textContent = label;
    t.style.fill = (label === 'N' || label === 'E' || label === 'S' || label === 'W') ? ink : inkFaint;
    svg.appendChild(t);
  });
  {
    const [x2, y2] = polarXY(cx, cy, R, 180);
    svg.appendChild(el('line', { x1: cx, y1: cy, x2, y2, stroke: inkFaint, 'stroke-width': 1, 'stroke-dasharray': '1,3', opacity: 0.5 }));
  }
  DATA.hard_edges.forEach((deg) => {
    const [x2, y2] = polarXY(cx, cy, R, deg);
    svg.appendChild(el('line', { x1: cx, y1: cy, x2, y2, stroke: exclLine, 'stroke-width': 2, 'stroke-dasharray': '5,4' }));
  });
  const areas = DATA.points.map(d => d.a);
  const minA = Math.min(...areas), maxA = Math.max(...areas);
  const sizeFor = (a) => 3 + 7 * (Math.sqrt(a - minA + 1) / Math.sqrt(maxA - minA + 1));
  const tip = document.getElementById('tooltip');
  const wrap = document.getElementById('polar-wrap');
  DATA.points.forEach((d) => {
    const r = (d.t / tiltMax) * R;
    const [x, y] = polarXY(cx, cy, r, d.az);
    const color = d.k === 'generator' ? sun : glint;
    const c = el('circle', d.m ? {
      cx: x, cy: y, r: sizeFor(d.a), fill: 'none', stroke: color, 'stroke-width': 1.25,
      'stroke-dasharray': '2,1.5', opacity: 0.55, style: 'cursor: pointer;',
    } : {
      cx: x, cy: y, r: sizeFor(d.a), fill: color, stroke: css('--bg-chart'), 'stroke-width': 1,
      opacity: 0.88, style: 'cursor: pointer;',
    });
    c.addEventListener('mouseenter', () => {
      const tag = d.m ? ' · MIRRORED (assumed, not measured)' : '';
      tip.innerHTML = `<b>${d.p}</b> · ${d.k} · ${d.pl}${tag}<br>` +
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
  const NS = 'http://www.w3.org/2000/svg';
  const r = document.createElementNS(NS, 'rect');
  r.setAttribute('x', x); r.setAttribute('y', y - h);
  r.setAttribute('width', w); r.setAttribute('height', Math.max(h, 0));
  r.setAttribute('fill', fill);
  svg.appendChild(r);
}
function text(svg, x, y, s, opts = {}) {
  const NS = 'http://www.w3.org/2000/svg';
  const t = document.createElementNS(NS, 'text');
  t.setAttribute('x', x); t.setAttribute('y', y);
  t.setAttribute('font-size', opts.size || 10.5);
  t.setAttribute('text-anchor', opts.anchor || 'middle');
  t.setAttribute('class', 'mono');
  if (opts.fill) t.style.fill = opts.fill;
  t.textContent = s;
  svg.appendChild(t);
}

function renderHistTilt() {
  const svg = document.getElementById('hist-tilt');
  svg.innerHTML = '';
  const W = 460, H = 200, padL = 24, padB = 26, padT = 10, padR = 10;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const binSize = 3, maxTilt = 30;
  const bins = Array.from({ length: maxTilt / binSize }, () => ({ gen: 0, plant: 0 }));
  DATA.points.forEach(d => {
    const i = Math.min(Math.floor(d.t / binSize), bins.length - 1);
    bins[i][d.k === 'generator' ? 'gen' : 'plant']++;
  });
  const maxCount = Math.max(...bins.map(b => b.gen + b.plant), 1);
  const bw = plotW / bins.length;
  const sun = css('--accent-sun'), glint = css('--accent-glint'), inkFaint = css('--ink-faint');
  bins.forEach((b, i) => {
    const x = padL + i * bw + bw * 0.12;
    const w = bw * 0.76;
    const totalH = (b.gen + b.plant) / maxCount * plotH;
    const genH = b.gen / maxCount * plotH;
    const baseY = padT + plotH;
    bar(svg, x, baseY - genH, w, genH, sun);
    bar(svg, x, baseY - totalH, w, totalH - genH, glint);
    if (i % 2 === 0) text(svg, x + w / 2, H - 8, (i * binSize) + '°', { size: 9.5, fill: inkFaint });
  });
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  line.setAttribute('x1', padL); line.setAttribute('x2', W - padR);
  line.setAttribute('y1', padT + plotH); line.setAttribute('y2', padT + plotH);
  line.setAttribute('stroke', css('--rule'));
  svg.appendChild(line);
}

function renderHistAz() {
  const svg = document.getElementById('hist-az');
  svg.innerHTML = '';
  const W = 460, H = 200, padL = 24, padB = 26, padT = 10, padR = 10;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const lo = 60, hi = 200, binSize = 10;
  const nbins = (hi - lo) / binSize;
  const bins = Array.from({ length: nbins }, () => ({ gen: 0, plant: 0 }));
  DATA.points.forEach(d => {
    const i = Math.min(Math.max(Math.floor((d.az - lo) / binSize), 0), nbins - 1);
    bins[i][d.k === 'generator' ? 'gen' : 'plant']++;
  });
  const maxCount = Math.max(...bins.map(b => b.gen + b.plant), 1);
  const bw = plotW / nbins;
  const sun = css('--accent-sun'), glint = css('--accent-glint'), inkFaint = css('--ink-faint'), exclLine = css('--excluded-line');
  bins.forEach((b, i) => {
    const x = padL + i * bw + bw * 0.12;
    const w = bw * 0.76;
    const totalH = (b.gen + b.plant) / maxCount * plotH;
    const genH = b.gen / maxCount * plotH;
    const baseY = padT + plotH;
    bar(svg, x, baseY - genH, w, genH, sun);
    bar(svg, x, baseY - totalH, w, totalH - genH, glint);
    if (i % 2 === 0) text(svg, x + w / 2, H - 8, (lo + i * binSize), { size: 9.5, fill: inkFaint });
  });
  const xCeil = padL + ((180 - lo) / (hi - lo)) * plotW;
  const vline = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  vline.setAttribute('x1', xCeil); vline.setAttribute('x2', xCeil);
  vline.setAttribute('y1', padT); vline.setAttribute('y2', padT + plotH);
  vline.setAttribute('stroke', exclLine); vline.setAttribute('stroke-width', 1.5);
  vline.setAttribute('stroke-dasharray', '4,3');
  svg.appendChild(vline);
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  line.setAttribute('x1', padL); line.setAttribute('x2', W - padR);
  line.setAttribute('y1', padT + plotH); line.setAttribute('y2', padT + plotH);
  line.setAttribute('stroke', css('--rule'));
  svg.appendChild(line);
}

function renderStrip() {
  const svg = document.getElementById('strip');
  svg.innerHTML = '';
  const rows = DATA.strip;
  const W = 1000, H = 150, padL = 50, padR = 20, padT = 14, padB = 28;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const groupW = plotW / rows.length;
  const inkDim = css('--ink-dim'), inkFaint = css('--ink-faint'), glint = css('--accent-glint'), rule = css('--rule');
  rows.forEach(([label, det, val], i) => {
    const gx = padL + i * groupW;
    const bw = groupW * 0.28;
    const hDet = det / 100 * plotH, hVal = val / 100 * plotH;
    const baseY = padT + plotH;
    bar(svg, gx + groupW * 0.22, baseY - hDet, bw, hDet, inkFaint);
    bar(svg, gx + groupW * 0.52, baseY - hVal, bw, hVal, glint);
    text(svg, gx + groupW / 2, H - 8, label, { size: 11 });
  });
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  line.setAttribute('x1', padL); line.setAttribute('x2', W - padR);
  line.setAttribute('y1', padT + plotH); line.setAttribute('y2', padT + plotH);
  line.setAttribute('stroke', rule);
  svg.appendChild(line);
  [0, 25, 50, 75].forEach(p => {
    const y = padT + plotH - (p / 100) * plotH;
    text(svg, padL - 10, y + 3, p + '%', { size: 10, anchor: 'end', fill: inkFaint });
  });
  text(svg, padL, 10, 'grey = detected (>= 1 spike)   teal = validated (>= 2 consistent)', { size: 10.5, anchor: 'start', fill: inkDim });
}

function renderAll() { renderPolar(); renderHistTilt(); renderHistAz(); renderStrip(); }
renderAll();
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderAll);
new MutationObserver(renderAll).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
</script>
"""


def main() -> None:
    s = pd.read_csv(SUMMARY)
    fit = s[s.n_consistent >= 2].copy().reset_index(drop=True)

    az_min, az_max = float(fit.fit_az.min()), float(fit.fit_az.max())
    mirror_lo, mirror_hi = 360.0 - az_max, 360.0 - az_min
    wedge = [round(mirror_hi, 1), round(az_min + 360.0, 1)]
    wedge_span = round(wedge[1] - wedge[0], 1)

    points = []
    for r in fit.itertuples():
        base = dict(p=r.pid, k=r.kind, pl=r.placement, a=round(float(r.area_m2), 1),
                    t=round(float(r.fit_tilt), 1), az=round(float(r.fit_az), 1),
                    n=int(r.n_consistent), m=False)
        points.append(base)
        mirror_az = round(360.0 - float(r.fit_az), 1)
        points.append({**base, "p": r.pid + "_mirror", "az": mirror_az, "m": True})

    ge1000 = s[s.area_m2 >= 1000]
    pct_ge1000 = round(100 * (ge1000.n_consistent >= 2).mean(), 1) if len(ge1000) else 0.0
    pct_onespike = round(100 * ((ge1000.n_spikes >= 1) & (ge1000.n_consistent < 2)).mean(), 1) if len(ge1000) else 0.0
    pct_nosignal = round(100 * (ge1000.n_spikes == 0).mean(), 1) if len(ge1000) else 0.0

    BINS = [0, 100, 500, 1000, 5000, 50000, 1e18]
    LABELS = ["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"]
    s["detected"] = s.n_spikes >= 1
    s["validated"] = s.n_consistent >= 2
    s["bucket"] = pd.cut(s.area_m2, bins=BINS, labels=LABELS)
    strip = []
    for label in LABELS:
        g = s[s.bucket == label]
        strip.append([label, round(100 * g.detected.mean(), 1), round(100 * g.validated.mean(), 1)])

    data = {
        "points": points,
        "wedge": wedge,
        "hard_edges": [round(az_min, 1), round(mirror_hi, 1)],
        "strip": strip,
    }

    html = TEMPLATE
    for key, value in {
        "__PAGE_TITLE__": "Fitted Panel Pose — Pakistan Glint Survey (n=2000)",
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__N_FITTED__": str(len(fit)),
        "__N_TOTAL__": str(len(s)),
        "__N_GE1000__": str(len(ge1000)),
        "__PCT_GE1000__": f"{pct_ge1000:.1f}",
        "__PCT_ONESPIKE__": f"{pct_onespike:.1f}",
        "__PCT_NOSIGNAL__": f"{pct_nosignal:.1f}",
        "__AZ_MIN__": f"{az_min:.1f}",
        "__AZ_MAX__": f"{az_max:.1f}",
        "__TILT_Q25__": f"{fit.fit_tilt.quantile(.25):.1f}",
        "__TILT_Q75__": f"{fit.fit_tilt.quantile(.75):.1f}",
        "__WEDGE_DEG__": f"{wedge_span:.0f}",
    }.items():
        html = html.replace(key, value)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"n_fitted={len(fit)}/{len(s)} az=[{az_min:.1f},{az_max:.1f}] wedge={wedge_span:.0f}deg -> {OUT}")


if __name__ == "__main__":
    main()
