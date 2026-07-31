"""Combine the sub-400 m2 capacity bracket atlas and the panel-pose glint survey into
one lean, single-page national overview for Pakistan, in the bracket atlas's dark
"night lights" style.

This is a presentation-layer merge, not a new analysis: it reads the `pv`/`pvdata`
JSON payloads already embedded in the two existing, self-contained pages
(`results/pakistan_pv_sub400_bracket_atlas.html`,
`results/glint_validation_pakistan/pv_pose_country2000.html`) plus the pose survey's
own summary CSV for the header percentages, and renders them into one new template.

Unlike `earthpv.dashboard` (which composes independent pages behind lazy-loaded
iframes specifically to avoid a CSS-variable collision between differently-styled
source pages), this page recolors the pose survey's charts onto the bracket atlas's
own palette so the whole thing reads as one document instead of two panels bolted
together. That only works because both sources already targeted a dark/light
`data-theme` toggle with the same shape; a source page with an incompatible design
would need the iframe approach instead.

Re-run after either source page or the pose CSV changes:
    pixi run python scripts/build_pakistan_pv_overview.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BRACKET_HTML = ROOT / "results" / "pakistan_pv_sub400_bracket_atlas.html"
POSE_HTML = ROOT / "results" / "glint_validation_pakistan" / "pv_pose_country2000.html"
POSE_CSV = ROOT / "data" / "glint" / "country2000_summary.csv"
OUT = ROOT / "results" / "pakistan_pv_overview.html"


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
        pct_onespike=round(100 * ((ge1000.n_spikes >= 1) & (ge1000.n_consistent < 2)).mean(), 1) if n_ge1000 else 0.0,
        pct_nosignal=round(100 * (ge1000.n_spikes == 0).mean(), 1) if n_ge1000 else 0.0,
        tilt_q25=round(float(fit.fit_tilt.quantile(0.25)), 1),
        tilt_q75=round(float(fit.fit_tilt.quantile(0.75)), 1),
    )


TEMPLATE = r"""<meta charset="utf-8">
<title>__PAGE_TITLE__</title>
<script id="pv" type="application/json">__PV_JSON__</script>
<script id="pose" type="application/json">__POSE_JSON__</script>

<style>
  :root {
    --font-display: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    --font-mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;

    /* dark = the primary "night lights" world */
    --page: #100d09;
    --panel: #1a160f;
    --panel-2: #221d14;
    --land: #241f16;
    --map-bg: #0c0a07;
    --ink: #f7f1e6;
    --ink-2: #c9bda4;
    --muted: #93866c;
    --hair: rgba(247,183,51,0.14);
    --prov-stroke: rgba(247,183,51,0.26);
    --accent: #f5a623;
    --accent-dim: #b5610f;
    --domain: #2fd9c4;
    --large: #4fb2e8;
    --bloom: 0.55;
    --card-ring: rgba(247,183,51,0.10);
    --shadow: 0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 30px rgba(0,0,0,0.45);
  }
  @media (prefers-color-scheme: light) {
    :root {
      --page: #f1ebdd; --panel: #faf6ec; --panel-2: #f3ecdb;
      --land: #e6dcc7; --map-bg: #efe8d8;
      --ink: #2a2216; --ink-2: #5f5540; --muted: #857a61;
      --hair: rgba(120,80,20,0.16); --prov-stroke: rgba(120,74,16,0.35);
      --accent: #c25e12; --accent-dim: #db7f24; --domain: #1f9b8a; --large: #1c6fa8; --bloom: 0;
      --card-ring: rgba(120,80,20,0.14);
      --shadow: 0 1px 0 rgba(255,255,255,0.6) inset, 0 8px 24px rgba(80,55,15,0.10);
    }
  }
  :root[data-theme="light"] {
    --page: #f1ebdd; --panel: #faf6ec; --panel-2: #f3ecdb;
    --land: #e6dcc7; --map-bg: #efe8d8;
    --ink: #2a2216; --ink-2: #5f5540; --muted: #857a61;
    --hair: rgba(120,80,20,0.16); --prov-stroke: rgba(120,74,16,0.35);
    --accent: #c25e12; --accent-dim: #db7f24; --domain: #1f9b8a; --large: #1c6fa8; --bloom: 0;
    --card-ring: rgba(120,80,20,0.14);
    --shadow: 0 1px 0 rgba(255,255,255,0.6) inset, 0 8px 24px rgba(80,55,15,0.10);
  }
  :root[data-theme="dark"] {
    --page: #100d09; --panel: #1a160f; --panel-2: #221d14;
    --land: #241f16; --map-bg: #0c0a07;
    --ink: #f7f1e6; --ink-2: #c9bda4; --muted: #93866c;
    --hair: rgba(247,183,51,0.14); --prov-stroke: rgba(247,183,51,0.26);
    --accent: #f5a623; --accent-dim: #b5610f; --domain: #2fd9c4; --large: #4fb2e8; --bloom: 0.55;
    --card-ring: rgba(247,183,51,0.10);
    --shadow: 0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 30px rgba(0,0,0,0.45);
  }

  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--page); color: var(--ink);
    font-family: var(--font-display);
    -webkit-font-smoothing: antialiased; line-height: 1.5;
  }
  .wrap { max-width: 1280px; margin: 0 auto; padding: clamp(20px, 3.5vw, 48px); }

  header { margin-bottom: 6px; }
  .eyebrow {
    font-family: var(--font-mono); font-size: 12px; letter-spacing: 0.22em;
    text-transform: uppercase; color: var(--accent); margin: 0 0 10px;
  }
  h1 {
    font-size: clamp(26px, 4.4vw, 46px); line-height: 1.05; margin: 0;
    font-weight: 780; letter-spacing: -0.02em; text-wrap: balance; max-width: 24ch;
  }
  .lede {
    margin: 14px 0 0; max-width: 72ch; color: var(--ink-2);
    font-size: clamp(15px, 1.5vw, 17px);
  }
  .lede b { color: var(--ink); font-weight: 640; }

  /* ── section scaffolding ─────────────────────────────────────────── */
  .sec { margin-top: 44px; }
  .sec-head { display: flex; align-items: baseline; justify-content: space-between;
    gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
  .sec-label { font-family: var(--font-mono); font-size: 12px; letter-spacing: 0.18em;
    text-transform: uppercase; color: var(--accent); }
  .sec-title { font-size: 20px; font-weight: 700; letter-spacing: -0.01em; margin: 2px 0 0; }
  .sec-sub { font-family: var(--font-mono); font-size: 11.5px; color: var(--muted); }

  /* ── kpi strip ───────────────────────────────────────────────────── */
  .kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-top: 26px; }
  @media (max-width: 980px) { .kpis { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 520px) { .kpis { grid-template-columns: 1fr; } }
  .kpi { background: var(--panel); border: 1px solid var(--card-ring); border-radius: 14px;
    padding: 15px 16px; box-shadow: var(--shadow); }
  .kpi .v { font-size: 25px; font-weight: 780; letter-spacing: -0.01em; color: var(--accent);
    font-variant-numeric: tabular-nums; }
  .kpi .v small { font-size: 0.52em; font-weight: 650; color: var(--ink-2); margin-left: 4px; }
  .kpi .k { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.05em;
    text-transform: uppercase; color: var(--muted); margin-top: 7px; line-height: 1.5; }

  /* ── view selector ──────────────────────────────────────────────── */
  .switch { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; }
  .tab {
    font-family: var(--font-mono); font-size: 12.5px; padding: 9px 14px;
    background: var(--panel); border: 1px solid var(--card-ring); border-radius: 8px;
    color: var(--ink-2); cursor: pointer; transition: border-color .15s, color .15s; text-align: left;
  }
  .tab .tt1 { display: block; font-weight: 650; }
  .tab .tt2 { display: block; font-size: 10.5px; letter-spacing: 0.04em; text-transform: uppercase;
    color: var(--muted); margin-top: 2px; }
  .tab:hover { color: var(--ink); border-color: var(--accent-dim); }
  .tab:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .tab[aria-pressed="true"] { color: var(--ink); background: var(--panel-2); border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }

  .grid { display: grid; grid-template-columns: 1.55fr 1fr; gap: 22px; align-items: start; margin-top: 16px; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel); border-radius: 16px; padding: 18px;
    box-shadow: var(--shadow); border: 1px solid var(--card-ring);
  }
  .map-card { padding: 14px; position: relative; overflow: hidden; }

  .map-head { display: flex; justify-content: space-between; align-items: baseline;
    gap: 12px; margin: 4px 6px 12px; flex-wrap: wrap; }
  .map-title { font-weight: 640; font-size: 15px; }
  .map-sub { font-family: var(--font-mono); font-size: 11.5px; color: var(--muted);
    letter-spacing: 0.02em; }

  svg.map { width: 100%; height: auto; display: block; }
  .cell { shape-rendering: crispEdges; }
  .prov-fill { fill: var(--land); }
  .prov-line { fill: none; stroke: var(--prov-stroke); stroke-width: 1; stroke-linejoin: round; }
  .city-dot { fill: var(--ink); opacity: 0.55; }
  .city-label { fill: var(--ink-2); font-family: var(--font-mono); font-size: 21px;
    paint-order: stroke; stroke: var(--map-bg); stroke-width: 2.4px; opacity: 0.9; }
  .domain-ring-rect { fill: none; stroke: var(--domain); stroke-width: 1;
    stroke-dasharray: 2 1.5; opacity: 0.85; pointer-events: none; }
  .large-dot { fill: none; stroke: var(--large); opacity: 0.9; pointer-events: none; }
  .tip .rowt.domain-flag span:first-child { color: var(--domain); }
  .tip .rowt.large-flag span:first-child { color: var(--large); }
  .legend .domain-key { display: flex; align-items: center; gap: 5px; font-family: var(--font-mono);
    font-size: 10.5px; color: var(--ink-2); }
  .legend .domain-key .sw { width: 10px; height: 10px; border: 1px dashed var(--domain);
    border-radius: 2px; }
  .legend .large-key { display: flex; align-items: center; gap: 5px; font-family: var(--font-mono);
    font-size: 10.5px; color: var(--ink-2); }
  .legend .large-key .sw { width: 10px; height: 10px; border: 1.4px solid var(--large);
    border-radius: 50%; }
  .calib-ring { fill: none; stroke: var(--domain); stroke-width: 1.4;
    stroke-dasharray: 3 2; opacity: 0.95; }
  .calib-dot { fill: var(--domain); stroke: var(--map-bg); stroke-width: 1.2;
    cursor: pointer; }
  .legend .calib-key { display: flex; align-items: center; gap: 5px; font-family: var(--font-mono);
    font-size: 10.5px; color: var(--ink-2); }
  .legend .calib-key .sw { width: 9px; height: 9px; border-radius: 50%;
    background: var(--domain); }

  .legend { display: flex; align-items: center; gap: 12px; margin: 12px 6px 2px;
    flex-wrap: wrap; }
  .legend .bar { height: 12px; width: min(260px, 50vw); border-radius: 6px; }
  .legend .ticks { position: relative; height: 14px; width: min(260px, 50vw);
    font-family: var(--font-mono); font-size: 10.5px; color: var(--muted); margin-top: 3px; }
  .legend .ticks span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
  .legend .ticks span::before { content: ""; position: absolute; top: -4px; left: 50%;
    width: 1px; height: 3px; background: var(--muted); }
  .legend .cap { font-family: var(--font-mono); font-size: 11px; color: var(--ink-2);
    letter-spacing: 0.03em; }
  .legend .lg-col { display: flex; flex-direction: column; }

  .hero-num { font-size: clamp(36px, 5.4vw, 54px); font-weight: 800; letter-spacing: -0.03em;
    line-height: 0.95; color: var(--accent); font-variant-numeric: tabular-nums; }
  .hero-unit { font-size: 0.34em; font-weight: 700; color: var(--ink-2); letter-spacing: 0;
    margin-left: 6px; }
  .hero-label { font-family: var(--font-mono); font-size: 11.5px; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--muted); margin-top: 8px; }
  .hero-desc { margin-top: 10px; font-size: 13.5px; color: var(--ink-2); min-height: 3.2em; }
  .hero-desc b { color: var(--ink); font-weight: 660; }

  .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
  .tile { background: var(--panel-2); border-radius: 12px; padding: 12px 13px;
    border: 1px solid var(--card-ring); }
  .tile.large-tile { border-color: var(--large); }
  .tile .v { font-size: 22px; font-weight: 740; letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums; }
  .tile.large-tile .v { color: var(--large); }
  .tile .k { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--muted); margin-top: 4px; }

  .rank { margin-top: 4px; }
  .rank h3 { font-size: 14px; font-weight: 640; margin: 2px 2px 12px; }
  .row { display: grid; grid-template-columns: 1fr; gap: 5px; margin-bottom: 11px; }
  .row .top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .row .nm { font-size: 13px; font-weight: 560; }
  .row .vl { font-family: var(--font-mono); font-size: 12px; color: var(--ink-2);
    font-variant-numeric: tabular-nums; }
  .track { height: 9px; background: var(--panel-2); border-radius: 5px; overflow: hidden; }
  .fill { height: 100%; border-radius: 5px; background: linear-gradient(90deg, var(--accent-dim), var(--accent)); }

  details.tablewrap { margin-top: 14px; }
  details.tablewrap summary { font-family: var(--font-mono); font-size: 11.5px;
    letter-spacing: 0.06em; text-transform: uppercase; color: var(--accent); cursor: pointer; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12.5px; }
  th, td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--hair);
    font-variant-numeric: tabular-nums; }
  th:first-child, td:first-child { text-align: left; }
  th { font-family: var(--font-mono); font-weight: 500; color: var(--muted);
    font-size: 10.5px; letter-spacing: 0.05em; text-transform: uppercase; }

  .tip, .ptip { position: fixed; pointer-events: none; z-index: 20; opacity: 0;
    transform: translate(-50%, calc(-100% - 12px)); transition: opacity .1s;
    background: var(--panel); color: var(--ink); border: 1px solid var(--card-ring);
    border-radius: 10px; padding: 9px 11px; box-shadow: var(--shadow);
    font-size: 12px; min-width: 160px; }
  .tip .th, .ptip .th { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted);
    letter-spacing: 0.05em; margin-bottom: 5px; }
  .tip .rowt { display: flex; justify-content: space-between; gap: 14px; }
  .tip .rowt span:last-child { font-family: var(--font-mono); font-variant-numeric: tabular-nums;
    color: var(--ink); }
  .tip .rowt span:first-child { color: var(--ink-2); }
  .tip .rowt.sel span:first-child { color: var(--accent); }
  .ptip.show { opacity: 1; }
  .ptip b { color: var(--ink); font-weight: 650; }

  .foot { margin-top: 34px; font-family: var(--font-mono); font-size: 11px; color: var(--muted);
    letter-spacing: 0.03em; line-height: 1.7; }
  .theme-btn { position: fixed; top: 14px; right: 14px; z-index: 30;
    background: var(--panel); color: var(--ink-2); border: 1px solid var(--card-ring);
    border-radius: 999px; padding: 7px 12px; font-family: var(--font-mono); font-size: 11px;
    cursor: pointer; letter-spacing: 0.04em; }
  .theme-btn:focus-visible, summary:focus-visible { outline: 2px solid var(--accent);
    outline-offset: 3px; }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }

  .tag { font-family: var(--font-mono); font-size: 9px; letter-spacing: 0.06em;
    text-transform: uppercase; padding: 2px 7px; border-radius: 999px; }
  .tag.low { background: rgba(245,166,35,0.14); color: var(--accent-dim); }
  .tag.central { background: rgba(245,166,35,0.22); color: var(--accent); }
  .tag.high { background: rgba(201,189,164,0.16); color: var(--ink-2); }
  .tag.large { background: rgba(79,178,232,0.18); color: var(--large); }

  /* ── panel-orientation section ───────────────────────────────────── */
  #polar-wrap { position: relative; width: 100%; }
  #polar { width: 100%; height: auto; display: block; }
  svg.posechart text { fill: var(--muted); font-family: var(--font-mono); }
  .pose-legend { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 10px;
    padding-top: 12px; border-top: 1px solid var(--hair); font-size: 12.5px; color: var(--ink-2); }
  .pose-legend .li { display: flex; align-items: center; gap: 7px; }
  .pose-legend .sw { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
  .pose-legend .sw.sun { background: var(--accent); }
  .pose-legend .sw.glint { background: var(--domain); }
  .pose-legend .sw.excl { width: 13px; height: 13px; border-radius: 2px;
    background: repeating-linear-gradient(45deg, var(--muted) 0, var(--muted) 1px, var(--panel-2) 1px, var(--panel-2) 4px);
    border: 1px solid var(--muted); opacity: .7; }
  .hero-mini .num { font-size: 30px; font-weight: 800; color: var(--accent);
    font-variant-numeric: tabular-nums; line-height: 1; }
  .hero-mini .num small { font-size: 15px; font-weight: 650; color: var(--ink-2); margin-left: 2px; }
  .hero-mini .lbl { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--muted); margin-top: 8px; line-height: 1.55; }
  .stat-row2 { display: flex; justify-content: space-between; align-items: baseline; gap: 10px;
    padding: 7px 0; font-size: 12.5px; }
  .stat-row2 + .stat-row2 { border-top: 1px dashed var(--hair); }
  .stat-row2 .l { color: var(--ink-2); }
  .stat-row2 .v { font-family: var(--font-mono); color: var(--ink); font-variant-numeric: tabular-nums;
    white-space: nowrap; }
  .lower2 { margin-top: 14px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 760px) { .lower2 { grid-template-columns: 1fr; } }
  .hist-title2 { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }

  /* ── expandable background sections ─────────────────────────────── */
  .xdetails { background: var(--panel); border: 1px solid var(--card-ring);
    border-radius: 14px; margin-top: 12px; overflow: hidden; }
  .xdetails summary { list-style: none; cursor: pointer; padding: 15px 18px;
    display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .xdetails summary::-webkit-details-marker { display: none; }
  .xdetails summary .xt { font-weight: 650; font-size: 14px; }
  .xdetails summary .xs { display: block; font-family: var(--font-mono); font-size: 10.5px;
    letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); margin-top: 3px;
    font-weight: 500; }
  .xdetails summary .xi { font-family: var(--font-mono); color: var(--accent); font-size: 17px;
    flex: none; }
  .xdetails[open] summary .xi { transform: rotate(45deg); }
  .xdetails .xbody { padding: 0 18px 18px; color: var(--ink-2); font-size: 13.5px; line-height: 1.65; }
  .xdetails .xbody p { margin: 0 0 12px; }
  .xdetails .xbody p:last-child { margin-bottom: 0; }
  .xdetails .xbody b { color: var(--ink); font-weight: 650; }
  .xdetails .xbody a { color: var(--accent); }
  dl.viewdefs { margin: 0; }
  dl.viewdefs dt { font-weight: 640; font-size: 13.5px; margin-top: 14px; display: flex;
    align-items: center; gap: 8px; }
  dl.viewdefs dt:first-child { margin-top: 0; }
  dl.viewdefs dd { margin: 6px 0 0; font-size: 13px; color: var(--ink-2); }
</style>

<button class="theme-btn" id="themeBtn" type="button" aria-label="Toggle light or dark theme">Dark mode</button>

<div class="wrap">
  <header>
    <p class="eyebrow">EarthPV · Sentinel-2 · TerraMind · roofclf · SPPI · glint survey</p>
    <h1>Solar PV across Pakistan: how much, where, and which way it faces</h1>
    <p class="lede">A satellite-derived national picture built from three linked
    measurements: <b>large rooftop and ground-mount PV</b> (&ge;400 m&sup2;, detected
    directly and recall-corrected), a <b>sub-400 m&sup2; capacity bracket</b> for the
    smaller rooftops the detector cannot resolve on its own, and a <b>panel-orientation
    survey</b> derived from specular sun glint. Every number below traces back to the
    project's own methodology notes; the expandable sections throughout give the
    reasoning and caveats without cluttering the page.</p>
  </header>

  <div class="kpis">
    <div class="kpi"><div class="v" id="kCentral">0<small>MWp</small></div>
      <div class="k">Central estimate, combined, nationwide</div></div>
    <div class="kpi"><div class="v" id="kLarge">0<small>MWp</small></div>
      <div class="k">Large PV, &ge;400 m&sup2;, rooftop, validated</div></div>
    <div class="kpi"><div class="v" id="kBuild">0</div>
      <div class="k">Buildings carrying a large PV detection</div></div>
    <div class="kpi"><div class="v" id="kDomain">0</div>
      <div class="k">of 0.1&deg; cells have density-matched sub-400 m&sup2; calibration</div></div>
    <div class="kpi"><div class="v" id="kPose">0<small>%</small></div>
      <div class="k">of &ge;1,000 m&sup2; installations yield a fitted panel orientation</div></div>
  </div>

  <section class="sec" id="capacity">
    <div class="sec-head">
      <div>
        <div class="sec-label">Capacity</div>
        <div class="sec-title">How much PV, by 0.1&deg; cell</div>
      </div>
      <div class="switch" role="group" aria-label="Sub-400 m² estimate">
        <button class="tab" id="tabLow" type="button" data-i="0">
          <span class="tt1">Low</span><span class="tt2">roofclf &amp; SPPI, plus large PV</span>
        </button>
        <button class="tab" id="tabCentral" type="button" data-i="1">
          <span class="tt1">Central</span><span class="tt2">roofclf alone, plus large PV</span>
        </button>
        <button class="tab" id="tabHigh" type="button" data-i="2">
          <span class="tt1">High</span><span class="tt2">national, uncalibrated, small only</span>
        </button>
        <button class="tab" id="tabAllPv" type="button" data-i="3">
          <span class="tt1">All-PV</span><span class="tt2">roofclf, plus every placement</span>
        </button>
      </div>
    </div>

    <div class="grid">
      <section class="card map-card">
        <div class="map-head">
          <div class="map-title">Sub-400 m² capacity per cell, plus large PV for scale</div>
          <div class="map-sub" id="mapsub">≈11 km × 11 km cells · log scale</div>
        </div>
        <div id="mapmount"></div>
        <div class="legend">
          <div class="lg-col">
            <div class="bar" id="legbar"></div>
            <div class="ticks" id="legticks"></div>
          </div>
          <div class="cap" id="legcap">MWp&nbsp;/&nbsp;cell, selected view</div>
          <div class="large-key">
            <span class="sw"></span>large PV (&ge;400 m²): ring size, always shown
          </div>
          <div class="domain-key" id="domainKey" style="margin-left:14px">
            <span class="sw"></span>checked area for Low/Central (dashed outline)
          </div>
          <div class="calib-key" id="calibKey" style="display:none;margin-left:14px">
            <span class="sw"></span>hand-checked calibration area (hover for detail)
          </div>
        </div>
      </section>

      <aside>
        <div class="card">
          <div class="hero-num"><span id="heroNum">0</span><span class="hero-unit">MWp</span></div>
          <div class="hero-label" id="heroLabel">Selected view, nationwide</div>
          <div class="hero-desc" id="heroDesc"></div>
          <div class="tiles">
            <div class="tile large-tile"><div class="v" id="tLarge">0</div><div class="k" id="tLargeLabel">Large PV MWp, always shown</div></div>
            <div class="tile"><div class="v" id="tSel">0</div><div class="k" id="tSelLabel">Selected view MWp</div></div>
            <div class="tile"><div class="v" id="tSmall">0</div><div class="k" id="tSmallLabel">Of which small PV MWp</div></div>
            <div class="tile"><div class="v" id="tBuild">0</div><div class="k">Large-PV buildings</div></div>
          </div>
        </div>

        <div class="card rank" style="margin-top:14px;">
          <h3 id="rankH">Provinces, ranked by selected view</h3>
          <div id="ranks"></div>
          <details class="tablewrap">
            <summary>Full province figures</summary>
            <div style="overflow-x:auto;"><table id="ptable">
              <thead><tr><th>Province</th><th>Low, combined</th><th>Central, combined</th>
                <th>High, small only</th><th>All-PV</th><th>Large PV, roof</th>
                <th>Large PV, all placements</th></tr></thead>
              <tbody></tbody>
            </table></div>
          </details>
        </div>
      </aside>
    </div>
  </section>

  <section class="sec" id="orientation">
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
      </aside>
    </div>

    <div class="lower2">
      <div class="card">
        <div class="hist-title2">Tilt distribution</div>
        <svg id="hist-tilt" class="posechart" viewBox="0 0 460 200"></svg>
      </div>
      <div class="card">
        <div class="hist-title2">Azimuth distribution <span style="opacity:.6">(180° = geometric ceiling)</span></div>
        <svg id="hist-az" class="posechart" viewBox="0 0 460 200"></svg>
      </div>
    </div>
    <div class="card" style="margin-top:14px;">
      <div class="hist-title2" id="stripTitle">Validation rate by installation size</div>
      <svg id="strip" class="posechart" viewBox="0 0 1000 150" style="width:100%; height:auto; display:block;"></svg>
    </div>
  </section>

  <section class="sec" id="background">
    <div class="sec-head">
      <div>
        <div class="sec-label">Background</div>
        <div class="sec-title">How to read these numbers</div>
      </div>
    </div>

    <details class="xdetails">
      <summary><span><span class="xt">What each capacity view means</span>
        <span class="xs">Low / Central / High / All-PV, defined</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <dl class="viewdefs">
          <dt><span class="tag low">Low</span> conservative</dt>
          <dd><b>Large rooftop PV, plus roofclf AND SPPI agreeing</b> on a building, restricted
          to the checked cells whose building density matches the calibration quadrats.
          Requiring both detectors to agree raises measured precision (0.55 &rarr; 0.62 on
          held-out quadrats) at the cost of recall. The small-PV component is <b>not a
          national figure</b> on its own.</dd>

          <dt><span class="tag central">Central</span> this project's own pick</dt>
          <dd><b>Large rooftop PV, plus roofclf alone</b>, same checked cells &mdash; the
          small-PV instrument this project currently regards as its best domain-restricted
          estimate. Its own component is also <b>not a national figure</b>: the checked
          cells cover about a fifth of national buildings, concentrated in large cities.</dd>

          <dt><span class="tag high">High</span> explicit ceiling, small PV only</dt>
          <dd><b>Flat national precision</b> applied to every roofclf-flagged building
          countrywide, with no density restriction. This is a national number, but an
          <b>explicitly uncalibrated</b> one &mdash; the precision weight is known not to
          survive the shift from 9 urban/industrial calibration quadrats to the country's
          mostly rural buildings. Treat it as an outer bound on plausibility, not an
          estimate; large PV is shown alongside for scale only, not added in.</dd>

          <dt><span class="tag large">All-PV</span> wider question, ground-mount included</dt>
          <dd><b>Central's small PV, plus large PV of every placement</b>, ground-mount farms
          included, not just rooftops. Answers a different question: how much PV capacity
          exists at all, not how much sits on a roof. Ground-mount converts at a different,
          site-area constant and is the pipeline's most bug-prone component, so this view
          carries more composition risk than the other three.</dd>
        </dl>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">Where the small-PV numbers apply</span>
        <span class="xs">reading the dashed outline on the map</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Low and Central only add a small-PV component <b>inside the dashed outline</b> &mdash;
        the cells whose building density matches the nine hand-mapped calibration quadrats used
        to train and validate the roofclf/SPPI classifiers. Outside that outline, small PV reads
        as zero for those two views not because small solar is known to be absent there, but
        because there is no calibration evidence either way yet. Large PV (the &ge;400 m² ring)
        is unaffected by this and is always shown everywhere, on every view.</p>
        <p>High deliberately breaks this pattern: it reports small PV <b>alone</b>, nationwide, with
        no density restriction, precisely because it is an explicit, uncalibrated ceiling rather
        than a validated estimate &mdash; combining it with the project's main number would blur
        that distinction. All-PV reuses Central's small-PV component but swaps in large PV across
        every placement, ground-mount farms included.</p>
        <p>This map's own 0.1° grid uses a slightly different origin than the field survey that
        measured the checked area, so it draws that coverage as a slightly different cell count
        than the 93 locations reported in the methodology notes &mdash; the totals are exact
        either way, since buildings were matched by location, not by cell name.</p>
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
        evidence about how rooftops in Pakistan are actually oriented. The shaded wedge in the
        polar plot marks orientations this survey cannot observe at all; nothing is drawn there
        because nothing was measured there, and no mirrored or interpolated points are added to
        fill the gap.</p>
        <p>A further <span id="xOne">25.1</span>% of &ge;1,000 m² installations glint only once
        (or on dates that disagree on a panel geometry), so they are correctly flagged as
        "PV is probably here" but carry no orientation information at all; another
        <span id="xNo">51.2</span>% show no glint signal in either year. Only installations with
        two or more mutually consistent spike dates get a plotted point.</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">External validation, outside this pipeline</span>
        <span class="xs">two independent, non-imagery anchors</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Two administrative/trade data points, neither derived from this pipeline, help sanity-check
        the bracket above:</p>
        <div style="overflow-x:auto;"><table>
          <thead><tr><th style="text-align:left">Bracket member</th><th>Value</th><th style="text-align:left">Scope</th></tr></thead>
          <tbody>
            <tr><td style="text-align:left">Low (roofclf &amp; SPPI agree)</td><td>2,651 MWp</td><td style="text-align:left">93 checked cells only</td></tr>
            <tr><td style="text-align:left">Central (roofclf alone)</td><td>6,628 MWp</td><td style="text-align:left">93 checked cells only</td></tr>
            <tr><td style="text-align:left">MaStR-shape-implied</td><td>~5,900 MWp</td><td style="text-align:left">national (implied by transfer)</td></tr>
            <tr><td style="text-align:left">NEPRA net-metering register</td><td>5,300–6,300 MWp</td><td style="text-align:left">national (registered only)</td></tr>
            <tr><td style="text-align:left">High (flat precision ceiling)</td><td>37,197 MWp</td><td style="text-align:left">national, unrestricted, uncalibrated</td></tr>
          </tbody>
        </table></div>
        <p style="margin-top:12px;"><b>NEPRA net-metering</b> (Pakistan's regulator, the closest
        available analogue to Germany's MaStR register): 5.3 GW registered nationally by April 2025
        across 283,000 consumers, average size 18.7 kWp &mdash; well under this project's 400 m²
        detection floor, so the register is itself dominated by exactly the sub-400 m² population
        this bracket is about. It is a <b>floor, not a total</b>: unregistered, self-consumption, and
        off-grid installs never appear in it at all.</p>
        <p><b>Chinese customs panel exports</b> put Pakistan's 2024 imports at 16.91 GW, roughly 50 GW
        cumulative by August 2025 &mdash; a much looser, order-of-magnitude check, since it is import
        volume rather than installed rooftop capacity and mixes utility-scale procurement with rooftop
        installs of every size.</p>
        <p><b>MaStR-shape-implied</b> applies Germany's own, legally complete rooftop size distribution
        (72.6% of capacity in units &le;100 kWp) to this project's validated large-PV total. It lands
        close to the domain-restricted Central figure despite sharing no inputs with it &mdash; the
        strongest corroboration available for this bracket, though it assumes Pakistan's roof-size
        distribution resembles Germany's, which is unverified.</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">Data &amp; methods</span>
        <span class="xs">what's under the hood</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Imagery is Sentinel-2 L2A, dry-season composites. <b>Large PV</b> (&ge;400 m², the practical
        floor for reliable per-pixel supervision at 10 m resolution) comes from a TerraMind
        geospatial foundation model fine-tuned for segmentation, trained on Germany and inferred
        on Pakistan, recall-corrected against held-out labels. <b>Sub-400 m² capacity</b> comes from
        two per-building classifiers (<code>roofclf</code>, a size/reflectance model; SPPI, a
        zero-training spectral index) trained and validated on nine hand-mapped calibration
        quadrats, restricted to cells whose building density matches those quadrats (Low/Central),
        or applied nationally at a flat precision weight explicitly known to be uncalibrated at
        that scale (High). <b>Panel orientation</b> comes from fitting a fixed tilt/azimuth to
        specular sun-glint spikes across two years of imagery, checked for self-consistency across
        independent dates. Building footprints are VIDA Open Buildings. Full derivations and
        caveats live in this project's methodology notes (<code>docs/methods/density.md</code>).</p>
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

  const SMALL_IDX = [2, 3, 4, 3];
  const IDX = [9, 10, 4, 12];
  const LARGE_ROOF_IDX = 5;
  const LARGE_ALL_IDX = 11;
  const LARGE_REF_IDX = [5, 5, 5, 11];
  const VIEWS = [
    { key: "low", label: "Low", name: "Low, combined: roofclf & SPPI agree, plus large rooftop PV",
      desc: "Large rooftop PV nationwide, plus buildings both roofclf and SPPI flag inside the density-checked cells.",
      combined: true, largeLabel: "Large PV (rooftop, &ge;400 m&sup2;)", vmax: 3 },
    { key: "central", label: "Central", name: "Central, combined: roofclf alone, plus large rooftop PV",
      desc: "Large rooftop PV nationwide, plus buildings roofclf flags inside the same density-checked cells.",
      combined: true, largeLabel: "Large PV (rooftop, &ge;400 m&sup2;)", vmax: 6 },
    { key: "high", label: "High", name: "High, small PV only: national, uncalibrated ceiling",
      desc: "Flat precision applied nationwide, no density restriction, small PV only. An explicit, unvalidated upper bound; large rooftop PV is shown for scale only, not added in.",
      combined: false, largeLabel: "Large PV (rooftop, &ge;400 m&sup2;)", vmax: 40 },
    { key: "allpv", label: "All-PV", name: "All-PV: Central's small PV, plus large PV of every placement",
      desc: "Large PV across every placement, ground-mount farms included, plus the same Central small-PV component.",
      combined: true, largeLabel: "Large PV (all placements, incl. ground-mount)", vmax: 10 },
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
    const view = VIEWS[sel], mi = IDX[sel], largeIdx = LARGE_REF_IDX[sel];
    const VMIN = 0.02, VMAX = Math.max(view.vmax, 0.1, ...DATA.cells.map(c => c[mi]));
    const lVMIN = Math.log(VMIN), lVMAX = Math.log(VMAX);
    const tOf = (v) => (Math.log(Math.max(v, VMIN)) - lVMIN) / (lVMAX - lVMIN);
    const bright = (v) => v > 0 ? tOf(v) : -1;

    const largeMax = Math.max(1, ...DATA.cells.map(c => c[largeIdx]));

    const mount = document.getElementById("mapmount");
    mount.innerHTML = "";
    const svg = el("svg", {viewBox:`0 0 ${W} ${H}`, class:"map", role:"img",
      "aria-label":`Choropleth map of Pakistan showing the ${view.name} sub-400 square metre estimate per cell, with large PV always overlaid`});

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

    if (DATA.cells.some(c => c[8])) {
      const gD = el("g", {class:"domain-ring"});
      for (const c of DATA.cells){
        if (!c[8]) continue;
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
        if (c[largeIdx] <= 0) continue;
        const frac = Math.min(1, Math.sqrt(c[largeIdx] / largeMax));
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
      const rows = VIEWS.map((v, i) => {
        const label = v.combined ? `${v.label} (combined)` : `${v.label} (small only)`;
        const main = `<div class="rowt${i===sel?' sel':''}"><span>${label}</span><span>${c[IDX[i]].toFixed(1)} MWp</span></div>`;
        const small = v.combined
          ? `<div class="rowt${i===sel?' sel':''}"><span>&nbsp;&nbsp;of which small PV</span><span>${c[SMALL_IDX[i]].toFixed(1)} MWp</span></div>`
          : "";
        return main + small;
      }).join("");
      const domainRow = (c[8]) ? `<div class="rowt domain-flag"><span>&#9679; Low/Central coverage</span><span>checked</span></div>` : "";
      tip.innerHTML = `<div class="th">CELL ${clat}°N ${clon}°E</div>`
        + rows
        + `<div class="rowt large-flag"><span>&#9675; Large PV, rooftop only</span><span>${c[LARGE_ROOF_IDX].toFixed(1)} MWp</span></div>`
        + `<div class="rowt large-flag"><span>&#9675; Large PV, all placements</span><span>${c[LARGE_ALL_IDX].toFixed(1)} MWp</span></div>`
        + `<div class="rowt"><span>Large-PV buildings</span><span>${c[6].toLocaleString()}</span></div>`
        + domainRow;
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
    document.getElementById("legcap").textContent = `MWp per cell, ${view.name}`;
  }

  const T = DATA.totals;
  const fmt = n => Math.round(n).toLocaleString("en-US");
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

  document.getElementById("tBuild").textContent = fmt(T.pv_buildings);
  document.getElementById("kBuild").textContent = fmt(T.pv_buildings);
  document.getElementById("kLarge").innerHTML = `${fmt(T.mwp_large)}<small>MWp</small>`;
  document.getElementById("kDomain").innerHTML = `${fmt(T.n_domain_cells)}<small>/ ${fmt(T.n_cells)}</small>`;
  document.getElementById("kCentral").innerHTML = `${fmt(T.mwp_central)}<small>MWp</small>`;

  const TOTAL_KEY = ["mwp_low", "mwp_central", "mwp_high", "mwp_all_pv"];
  const LARGE_TOTAL_KEY = ["mwp_large", "mwp_large", "mwp_large", "mwp_large_all"];

  function drawTable() {
    const provs = [...DATA.provinces].sort((a,b) => b[TOTAL_KEY[sel]] - a[TOTAL_KEY[sel]]);
    const maxP = provs.length ? Math.max(...provs.map(p => p[TOTAL_KEY[sel]]), 1) : 1;
    document.getElementById("ranks").innerHTML = provs.map(p => {
      const nm = p.name.replace("Islamabad Capital Territory","Islamabad").replace("Khyber Pakhtunkhwa","Kh. Pakhtunkhwa");
      const v = p[TOTAL_KEY[sel]];
      return `<div class="row"><div class="top"><span class="nm">${nm}</span>`
        + `<span class="vl">${fmt(v)} MWp</span></div>`
        + `<div class="track"><div class="fill" style="width:${(v/maxP*100).toFixed(1)}%"></div></div></div>`;
    }).join("");
    document.querySelector("#ptable tbody").innerHTML = provs.map(p =>
      `<tr><td>${p.name}</td><td>${fmt(p.mwp_low)}</td><td>${fmt(p.mwp_central)}</td>`
      + `<td>${fmt(p.mwp_high)}</td><td>${fmt(p.mwp_all_pv)}</td><td>${fmt(p.mwp_large)}</td>`
      + `<td>${fmt(p.mwp_large_all)}</td></tr>`).join("");
  }

  const SMALL_TOTAL_KEY = ["mwp_low_small_only", "mwp_central_small_only", "mwp_high", "mwp_central_small_only"];

  function setView(i) {
    sel = i;
    ["tabLow", "tabCentral", "tabHigh", "tabAllPv"].forEach((id, j) =>
      document.getElementById(id).setAttribute("aria-pressed", String(j === i)));
    const view = VIEWS[i];
    countUp("heroNum", T[TOTAL_KEY[i]], 700);
    document.getElementById("heroLabel").textContent = view.combined
      ? `${view.label}, combined, nationwide`
      : `${view.label}, small PV only, nationwide`;
    document.getElementById("heroDesc").innerHTML = `<b>${view.name}.</b> ${view.desc}`;
    document.getElementById("tSel").textContent = fmt(T[TOTAL_KEY[i]]);
    document.getElementById("tSelLabel").textContent = view.combined
      ? `${view.label} view MWp, combined`
      : `${view.label} view MWp, small PV only`;
    document.getElementById("tSmall").textContent = fmt(T[SMALL_TOTAL_KEY[i]]);
    document.getElementById("tSmallLabel").textContent = view.combined
      ? "Of which small PV MWp"
      : "Small PV MWp (same as above, not combined)";
    document.getElementById("tLarge").textContent = fmt(T[LARGE_TOTAL_KEY[i]]);
    document.getElementById("tLargeLabel").innerHTML = `${view.largeLabel} MWp, always shown`;
    document.getElementById("rankH").textContent = `Provinces, ranked by ${view.label.toLowerCase()} view`;
    renderMap(); drawTable();
  }
  document.getElementById("tabLow").addEventListener("click", () => setView(0));
  document.getElementById("tabCentral").addEventListener("click", () => setView(1));
  document.getElementById("tabHigh").addEventListener("click", () => setView(2));
  document.getElementById("tabAllPv").addEventListener("click", () => setView(3));

  /* ── panel-orientation charts (recolored onto the same palette) ──── */
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

  function renderHistTilt() {
    const svg = document.getElementById('hist-tilt');
    svg.innerHTML = '';
    const Wc = 460, Hc = 200, padL = 24, padB = 26, padT = 10, padR = 10;
    const plotW = Wc - padL - padR, plotH = Hc - padT - padB;
    const binSize = 3, maxTilt = 30;
    const bins = Array.from({ length: maxTilt / binSize }, () => ({ gen: 0, plant: 0 }));
    POSE.points.forEach(d => {
      const i = Math.min(Math.floor(d.t / binSize), bins.length - 1);
      bins[i][d.k === 'generator' ? 'gen' : 'plant']++;
    });
    const maxCount = Math.max(...bins.map(b => b.gen + b.plant), 1);
    const bw = plotW / bins.length;
    bins.forEach((b, i) => {
      const x = padL + i * bw + bw * 0.12;
      const w = bw * 0.76;
      const totalH = (b.gen + b.plant) / maxCount * plotH;
      const genH = b.gen / maxCount * plotH;
      const baseY = padT + plotH;
      bar(svg, x, baseY - genH, w, genH, 'var(--accent)');
      bar(svg, x, baseY - totalH, w, totalH - genH, 'var(--domain)');
      if (i % 2 === 0) ptext(svg, x + w / 2, Hc - 8, (i * binSize) + '°', { size: 9.5, fill: 'var(--muted)' });
    });
    svg.appendChild(el('line', { x1: padL, x2: Wc - padR, y1: padT + plotH, y2: padT + plotH, stroke: 'var(--hair)' }));
  }

  function renderHistAz() {
    const svg = document.getElementById('hist-az');
    svg.innerHTML = '';
    const Wc = 460, Hc = 200, padL = 24, padB = 26, padT = 10, padR = 10;
    const plotW = Wc - padL - padR, plotH = Hc - padT - padB;
    const lo = 60, hi = 200, binSize = 10;
    const nbins = (hi - lo) / binSize;
    const bins = Array.from({ length: nbins }, () => ({ gen: 0, plant: 0 }));
    POSE.points.forEach(d => {
      const i = Math.min(Math.max(Math.floor((d.az - lo) / binSize), 0), nbins - 1);
      bins[i][d.k === 'generator' ? 'gen' : 'plant']++;
    });
    const maxCount = Math.max(...bins.map(b => b.gen + b.plant), 1);
    const bw = plotW / nbins;
    bins.forEach((b, i) => {
      const x = padL + i * bw + bw * 0.12;
      const w = bw * 0.76;
      const totalH = (b.gen + b.plant) / maxCount * plotH;
      const genH = b.gen / maxCount * plotH;
      const baseY = padT + plotH;
      bar(svg, x, baseY - genH, w, genH, 'var(--accent)');
      bar(svg, x, baseY - totalH, w, totalH - genH, 'var(--domain)');
      if (i % 2 === 0) ptext(svg, x + w / 2, Hc - 8, (lo + i * binSize), { size: 9.5, fill: 'var(--muted)' });
    });
    const xCeil = padL + ((180 - lo) / (hi - lo)) * plotW;
    svg.appendChild(el('line', { x1: xCeil, x2: xCeil, y1: padT, y2: padT + plotH, stroke: 'var(--muted)', 'stroke-width': 1.5, 'stroke-dasharray': '4,3' }));
    svg.appendChild(el('line', { x1: padL, x2: Wc - padR, y1: padT + plotH, y2: padT + plotH, stroke: 'var(--hair)' }));
  }

  function renderStrip() {
    const svg = document.getElementById('strip');
    svg.innerHTML = '';
    const rows = POSE.strip;
    const Wc = 1000, Hc = 150, padL = 50, padR = 20, padT = 14, padB = 28;
    const plotW = Wc - padL - padR, plotH = Hc - padT - padB;
    const groupW = plotW / rows.length;
    rows.forEach(([label, det, val], i) => {
      const gx = padL + i * groupW;
      const bw = groupW * 0.28;
      const hDet = det / 100 * plotH, hVal = val / 100 * plotH;
      const baseY = padT + plotH;
      bar(svg, gx + groupW * 0.22, baseY - hDet, bw, hDet, 'var(--muted)');
      bar(svg, gx + groupW * 0.52, baseY - hVal, bw, hVal, 'var(--domain)');
      ptext(svg, gx + groupW / 2, Hc - 8, label, { size: 11, fill: 'var(--ink-2)' });
    });
    svg.appendChild(el('line', { x1: padL, x2: Wc - padR, y1: padT + plotH, y2: padT + plotH, stroke: 'var(--hair)' }));
    [0, 25, 50, 75].forEach(p => {
      const y = padT + plotH - (p / 100) * plotH;
      ptext(svg, padL - 10, y + 3, p + '%', { size: 10, anchor: 'end', fill: 'var(--muted)' });
    });
    ptext(svg, padL, 10, 'grey = detected (≥ 1 spike)   teal = validated (≥ 2 consistent)', { size: 10.5, anchor: 'start', fill: 'var(--ink-2)' });
  }

  function renderPose(){ renderPolar(); renderHistTilt(); renderHistAz(); renderStrip(); }

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
    `TerraMind-tiny segmentation (large PV) + roofclf/SPPI classifiers (sub-400 m²) + glint geometry (orientation) · `
    + `${fmt(T.n_cells)} cells × 0.1° · ${T.kwp_per_m2} kWp/m² of panel area · `
    + `Sentinel-2 L2A dry-season composites · buildings from VIDA Open Buildings · `
    + `see docs/methods/density.md for full derivations and caveats.`;

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
    bracket = _extract_json(BRACKET_HTML.read_text(), "pv")
    pose = _extract_json(POSE_HTML.read_text(), "pvdata")
    stats = _pose_stats(POSE_CSV)
    az_min, az_max = pose["hard_edges"]

    html = TEMPLATE
    replacements = {
        "__PAGE_TITLE__": "Pakistan Solar PV — National Overview",
        "__PV_JSON__": json.dumps(bracket, separators=(",", ":")),
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
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"-> {OUT} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
