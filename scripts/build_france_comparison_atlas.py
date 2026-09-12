#!/usr/bin/env python
"""Build the France comparison atlas: register, OpenPVMapper and earthpv side by side.

France is the first country where this project can put three independent views of the
same rooftops next to each other:

  * **ODRE's national register** -- legally mandated, complete, but geometry-free,
    censored below 36 kW into per-commune aggregates, and carrying no rooftop/ground
    attribute.
  * **OpenPVMapper** (Kasmi 2026, doi:10.5281/zenodo.21534856) -- 1.14 M rooftop
    installation polygons with area and estimated kWp, from sub-metre IGN aerial
    imagery. Complete-looking, but a model output with ~74-75% published precision.
  * **earthpv** -- this project, from 10 m Sentinel-2, where one French residential
    array (median 20 m2) is a fifth of a pixel.

and, in fourteen communes, a fourth: an exhaustive human sweep on sub-metre imagery,
which is the only one of the four that is ground truth.

The page's argument is that the three disagree in *structured*, explainable ways rather
than randomly, and that each one's blind spot is another's strength. It is built from
`results/france_validation/france_validation.json` and the parquet tables beside it, so
it cannot drift from the numbers those record.

    pixi run python scripts/build_france_comparison_atlas.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

TEMPLATE = REPO / "src" / "earthpv" / "templates" / "pv_evidence_atlas.html"
log = logging.getLogger("france-atlas")

# Germany's directly-measured rooftop figure, for the one comparison that motivates the
# whole page. Source: mastr_validation.size_regime_shares, docs/results/germany.md.
GERMANY_ROOFTOP_BELOW_FLOOR = 0.655


def slice_css() -> str:
    """The night-lights design tokens, taken from the reference implementation.

    Sliced rather than copied so the palette cannot drift from
    `templates/pv_evidence_atlas.html`, which CLAUDE.md names as the house style for any
    new results page.
    """
    s = TEMPLATE.read_text()
    try:
        i = s.index("<style>")
        j = s.index("</style>", i)
    except ValueError as exc:  # pragma: no cover - operator-facing
        raise ValueError(
            f"could not slice the <style> block out of {TEMPLATE.name}; re-sync the "
            "markers or inline the CSS here"
        ) from exc
    return s[i:j] + "</style>"


def simplify_rings(geom, tol: float = 0.008, min_ring_deg2: float = 3e-4):
    """Outer rings of a (Multi)Polygon as rounded lon/lat lists, small islands dropped.

    The page embeds every departement outline inline, so the geometry has to be small
    enough to ship in one HTML file: full-resolution IGN commune boundaries dissolved to
    96 departements are ~16 MB of coordinates, which is most of the artifact budget for
    something drawn 900 px wide.
    """
    g = geom.simplify(tol, preserve_topology=True)
    polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
    out = []
    for p in polys:
        if p.area < min_ring_deg2:
            continue
        out.append([[round(x, 3), round(y, 3)] for x, y in p.exterior.coords])
    if not out and polys:  # never drop a departement entirely
        biggest = max(polys, key=lambda p: p.area)
        out.append([[round(x, 3), round(y, 3)] for x, y in biggest.exterior.coords])
    return out


def build_data(args) -> dict:
    val = json.loads(Path(args.validation).read_text())
    cc = pd.read_parquet(Path(args.validation).parent / "commune_capacity.parquet")
    opvm_cc = pd.read_parquet(Path(args.validation).parent / "openpvmapper_by_commune.parquet")
    communes = gpd.read_parquet(args.communes)

    m = communes[["insee", "nom", "dep", "geometry"]].merge(cc, on="insee", how="left")
    m = m.merge(opvm_cc, on="insee", how="left")
    num = [c for c in m.columns if c not in ("insee", "nom", "dep", "geometry")]
    m[num] = m[num].fillna(0.0)

    deps = m.dissolve(by="dep", aggfunc={c: "sum" for c in num}).reset_index()
    dep_rows = []
    for _, r in deps.iterrows():
        rings = simplify_rings(r.geometry)
        if not rings:
            continue
        dep_rows.append({
            "code": r.dep,
            "kw_total": round(float(r.kw_total), 1),
            "kw_bt": round(float(r.kw_bt), 1),
            "kw_bt_le72": round(float(r.kw_bt_le_72), 1),
            "opvm_kwp": round(float(r.opvm_kwp), 1),
            "opvm_kwp_le72": round(float(r.get("opvm_kwp_le_72", 0.0)), 1),
            "opvm_n": int(r.opvm_n),
            "rings": rings,
        })

    # Commune scatter: every commune with both a register and an OpenPVMapper figure is
    # 22k points, which renders fine as plain circles but bloats the file. Sampled on a
    # fixed seed so the page is reproducible.
    sc = m[(m.kw_bt > 0) & (m.opvm_kwp > 0)][["kw_bt", "opvm_kwp"]]
    if len(sc) > args.scatter_n:
        sc = sc.sample(args.scatter_n, random_state=20260904)
    scatter = [[round(float(a), 1), round(float(b), 1)] for a, b in sc.to_numpy()]

    quad = val.get("openpvmapper_vs_mapped", {}).get("per_quadrat", [])
    mc = val.get("module_constant", {})
    sr = val["size_regime"]

    return {
        "generated_from": str(args.validation),
        "register_snapshot": val.get("register_snapshot"),
        "opvm_doi": val.get("openpvmapper_vs_register", {}).get("source"),
        "kpi": {
            "register_gwp": round(sr["totals_mw"]["all_pv"] / 1000, 2),
            "register_bt_gwp": round(sr["totals_mw"]["bt_only"] / 1000, 2),
            # The dataset's own national total, not `vs_all_pv.total_est` -- that one is
            # restricted to communes carrying at least MIN_COMMUNE_KW of registered
            # capacity, so quoting it as "OpenPVMapper" understates the database by about
            # 1 GWp and would not reconcile with its published 15.0 GWp.
            "opvm_gwp": round(float(opvm_cc.opvm_kwp.sum()) / 1e6, 2),
            "opvm_gwp_scored": round(
                val["openpvmapper_vs_register"]["vs_all_pv"]["total_est"] / 1e6, 2),
            "below_floor_all": sr["share_below_seg_floor"]["all_pv"],
            "below_floor_bt": sr["share_below_seg_floor"]["bt_only"],
            "germany_rooftop": GERMANY_ROOFTOP_BELOW_FLOOR,
            "module_constant": mc.get("pooled_kwp_per_m2_epoch_matched"),
            "module_constant_uncorrected": mc.get("pooled_kwp_per_m2_uncorrected"),
            "n_small_units": sr["n_small_units_aggregated"],
            "mean_kw_small": sr["mean_kw_per_small_unit"],
        },
        "opvm_vs_register": val["openpvmapper_vs_register"],
        "opvm_vs_mapped": {
            k: v for k, v in val["openpvmapper_vs_mapped"].items() if k != "per_quadrat"
        },
        "quadrats": quad,
        "module_constant": mc,
        "deps": dep_rows,
        "scatter": scatter,
        "earthpv": val.get("earthpv_vs_register"),
        "skipped": val.get("skipped", {}),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--validation", default="results/france_validation/france_validation.json")
    ap.add_argument("--communes", default="data/labels/france_communes.parquet")
    ap.add_argument("--out", default="results/france_pv_comparison_atlas.html")
    ap.add_argument("--scatter-n", type=int, default=6000)
    a = ap.parse_args()

    data = build_data(a)
    html = PAGE.replace("__CSS__", slice_css()).replace(
        "__DATA__", json.dumps(data, separators=(",", ":"))
    )
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    log.info("wrote %s (%.1f MB)", out, out.stat().st_size / 1e6)
    return 0

PAGE = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>France PV Comparison Atlas</title>
__CSS__
<style>
  .cmp-grid{display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));}
  .cmp-wide{grid-column:1/-1;}
  table.cmp{width:100%;border-collapse:collapse;font-size:13px;font-family:var(--font-mono);}
  table.cmp th,table.cmp td{padding:6px 8px;border-bottom:1px solid var(--hair);text-align:right;white-space:nowrap;}
  table.cmp th:first-child,table.cmp td:first-child{text-align:left;}
  table.cmp th{color:var(--muted);font-weight:600;}
  .scroll{overflow-x:auto;}
  .tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 6px;}
  .tabs button{font:inherit;font-size:13px;padding:8px 14px;border-radius:999px;cursor:pointer;
    background:var(--panel-2);color:var(--ink-2);border:1px solid var(--card-ring);}
  .tabs button[aria-selected="true"]{background:var(--accent);color:#1a1206;border-color:var(--accent);font-weight:650;}
  .swatch{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:middle;}
  .note{color:var(--muted);font-size:12.5px;line-height:1.55;}
</style>
</head>
<body>
<div class="wrap">

  <header class="hero">
    <div class="eyebrow">France &middot; comparison atlas</div>
    <h1>Three views of the same rooftops</h1>
    <p class="lede">A complete national register with no geometry, a nationwide model with
    1.14 million polygons and ~75% precision, and a 10 m satellite detector for which the
    median French residential array is a fifth of one pixel. In fourteen communes a human
    swept every roof, which is the only ground truth here.</p>
  </header>

  <section class="kpis" id="kpis"></section>

  <div class="tabs" role="tablist" id="tabs">
    <button role="tab" data-tab="reg" aria-selected="true">Register vs OpenPVMapper</button>
    <button role="tab" data-tab="truth" aria-selected="false">Against ground truth</button>
    <button role="tab" data-tab="floor" aria-selected="false">The 400 m&sup2; floor</button>
  </div>

  <section class="panel-tab" id="tab-reg">
    <div class="cmp-grid">
      <section class="card cmp-wide">
        <div class="map-head">
          <div class="map-title">OpenPVMapper capacity as a share of the register, by d&eacute;partement</div>
          <div class="map-sub">Low-voltage registered capacity is the denominator, the closest
          France offers to a rooftop total. Brighter means OpenPVMapper accounts for more of it.</div>
        </div>
        <div id="mapmount"></div>
        <div id="maplegend" class="note" style="margin-top:10px"></div>
      </section>

      <section class="card">
        <div class="map-head">
          <div class="map-title">Per commune</div>
          <div class="map-sub">Registered low-voltage kW (x) against OpenPVMapper kWp (y), log-log.
          The diagonal is exact agreement.</div>
        </div>
        <div id="scattermount"></div>
      </section>

      <section class="card">
        <div class="map-head">
          <div class="map-title">Agreement statistics</div>
          <div class="map-sub">Origin-forced slope, median ratio and rank correlation across communes.</div>
        </div>
        <div class="scroll"><table class="cmp" id="fittable"></table></div>
        <p class="note" id="fitnote"></p>
      </section>
    </div>
  </section>

  <section class="panel-tab" id="tab-truth" hidden>
    <div class="cmp-grid">
      <section class="card cmp-wide">
        <div class="map-head">
          <div class="map-title">The fourteen hand-mapped communes</div>
          <div class="map-sub">Every visible panel drawn on sub-metre IGN imagery, with solar
          thermal tagged separately. Recall is what transfers; precision here is optimistic,
          because these communes are OpenPVMapper's own correction layer.</div>
        </div>
        <div class="scroll"><table class="cmp" id="quadtable"></table></div>
      </section>

      <section class="card">
        <div class="map-head">
          <div class="map-title">What the unmatched detections are sitting on</div>
          <div class="map-sub">Not all of them are errors, and one class is systematic.</div>
        </div>
        <div id="fpmount"></div>
      </section>

      <section class="card">
        <div class="map-head">
          <div class="map-title">The module constant, measured</div>
          <div class="map-sub">Register capacity divided by hand-mapped module area, read back
          to each commune's own mapping year.</div>
        </div>
        <div id="mcmount"></div>
      </section>
    </div>
  </section>

  <section class="panel-tab" id="tab-floor" hidden>
    <div class="cmp-grid">
      <section class="card">
        <div class="map-head">
          <div class="map-title">Capacity below the 400 m&sup2; detection floor</div>
          <div class="map-sub">72 kWp = 400 m&sup2; of module at 0.18 kWp/m&sup2;. Germany's figure is
          measured against rooftop capacity; France has no rooftop field, so it is bracketed.</div>
        </div>
        <div id="floormount"></div>
      </section>

      <section class="card">
        <div class="map-head">
          <div class="map-title">OpenPVMapper recall by installation size</div>
          <div class="map-sub">Against the hand-mapped truth, in m&sup2; of module area.
          One Sentinel-2 pixel is 100 m&sup2;.</div>
        </div>
        <div id="sizemount"></div>
      </section>
    </div>
  </section>

  <section class="card" style="margin-top:22px">
    <details class="xdetails">
      <summary>How each number here was produced, and what it cannot tell you</summary>
      <div class="xbody" id="method"></div>
    </details>
  </section>

  <footer class="foot" id="foot"></footer>
</div>

<script>
const DATA = __DATA__;
const el = (t, a) => { const n = document.createElementNS("http://www.w3.org/2000/svg", t);
  for (const k in (a||{})) n.setAttribute(k, a[k]); return n; };
const fmt = (v, d=1) => (v===null||v===undefined||!isFinite(v)) ? "n/a"
  : Number(v).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const pct = v => (v===null||v===undefined) ? "n/a" : (100*v).toFixed(1)+"%";
const isDark = () => document.documentElement.getAttribute("data-theme") !== "light";

/* ---------- KPI strip ---------- */
function kpis(){
  const k = DATA.kpi;
  const items = [
    ["Registered PV", fmt(k.register_gwp,2)+" GWp", "ODR&Eacute; national register, complete"],
    ["OpenPVMapper", fmt(k.opvm_gwp,2)+" GWp", "1.14M rooftop polygons, model output"],
    ["Below the floor", pct(k.below_floor_all)+" &ndash; "+pct(k.below_floor_bt),
     "vs Germany "+pct(k.germany_rooftop)+" of rooftop"],
    ["Module constant", fmt(k.module_constant,3)+" kWp/m&sup2;", "project assumes 0.180"],
  ];
  document.getElementById("kpis").innerHTML = items.map(([a,b,c]) =>
    `<div class="kpi"><div class="kpi-label">${a}</div><div class="kpi-value">${b}</div>
     <div class="kpi-sub">${c}</div></div>`).join("");
}

/* ---------- map ---------- */
const W = 900, H = 900;
function bboxOf(deps){
  let b=[999,999,-999,-999];
  for(const d of deps) for(const r of d.rings) for(const p of r){
    b[0]=Math.min(b[0],p[0]); b[1]=Math.min(b[1],p[1]);
    b[2]=Math.max(b[2],p[0]); b[3]=Math.max(b[3],p[1]); }
  return b;
}
function renderMap(){
  const deps = DATA.deps; if(!deps.length) return;
  const b = bboxOf(deps);
  const latMid = (b[1]+b[3])/2, kx = Math.cos(latMid*Math.PI/180);
  const dw = (b[2]-b[0])*kx, dh = (b[3]-b[1]);
  const s = Math.min((W-40)/dw, (H-40)/dh);
  const ox = (W - dw*s)/2, oy = (H - dh*s)/2;
  const proj = (lon,lat) => [ox + (lon-b[0])*kx*s, H - oy - (lat-b[1])*s];

  const vals = deps.map(d => d.kw_bt>0 ? d.opvm_kwp/d.kw_bt : null).filter(v=>v!==null)
    .sort((a,b)=>a-b);
  // Clamp the ramp at the 95th percentile rather than the maximum. One departement
  // (Gironde) runs to 3.7x while the median is 0.67, so scaling to the max would push
  // nearly every departement into the darkest two stops and hide the actual spread. The
  // top swatch is labelled as a floor, and the tooltip always carries the real value.
  const vmax = Math.max(1.0, vals[Math.floor(0.95*(vals.length-1))] || 1.0);
  const ramp = isDark()
    ? ["#1b1710","#4a2f0c","#8a4e08","#c97a10","#f5a623","#ffd479"]
    : ["#efe8d8","#f3d9ac","#eeb96f","#e0913c","#c96a18","#9c4a06"];
  const col = t => ramp[Math.max(0,Math.min(ramp.length-1,Math.floor(t*(ramp.length-1)+0.5)))];

  const mount = document.getElementById("mapmount"); mount.innerHTML="";
  const svg = el("svg",{viewBox:`0 0 ${W} ${H}`,class:"map",role:"img",
    "aria-label":"Map of France by departement showing OpenPVMapper capacity as a share of registered low-voltage capacity"});
  svg.appendChild(el("rect",{x:0,y:0,width:W,height:H,fill:"var(--map-bg)"}));
  for(const d of deps){
    let path="";
    for(const r of d.rings){
      r.forEach((p,i)=>{ const q=proj(p[0],p[1]);
        path += (i?"L":"M")+q[0].toFixed(1)+" "+q[1].toFixed(1); });
      path += "Z";
    }
    const ratio = d.kw_bt>0 ? d.opvm_kwp/d.kw_bt : null;
    const p = el("path",{d:path, fill: ratio===null? "var(--land)" : col(Math.min(ratio,vmax)/vmax),
      stroke:"var(--prov-stroke)","stroke-width":"0.6"});
    const t = el("title",{}); t.textContent =
      `${d.code}  OpenPVMapper ${(d.opvm_kwp/1000).toFixed(1)} MWp / register BT ${(d.kw_bt/1000).toFixed(1)} MW`
      + (ratio===null?"":`  =  ${(100*ratio).toFixed(0)}%`);
    p.appendChild(t); svg.appendChild(p);
  }
  mount.appendChild(svg);
  document.getElementById("maplegend").innerHTML =
    ramp.map((c,i)=>{
      const v=(100*vmax*i/(ramp.length-1)).toFixed(0);
      return `<span class="swatch" style="background:${c}"></span>${i===ramp.length-1?"&ge;"+v:v}%`;
    }).join(" &nbsp; ")
    + ' &nbsp; <span style="color:var(--muted)">ramp clamped at the 95th percentile; hover for each departement\'s real value</span>';
}

/* ---------- scatter ---------- */
function renderScatter(){
  const pts = DATA.scatter; const S=380, pad=44;
  const lo=1, hi=Math.max(...pts.map(p=>Math.max(p[0],p[1])),1000);
  const lx=Math.log10(lo), hx=Math.log10(hi);
  const X=v=>pad+(Math.log10(Math.max(v,lo))-lx)/(hx-lx)*(S-2*pad);
  const Y=v=>S-pad-(Math.log10(Math.max(v,lo))-lx)/(hx-lx)*(S-2*pad);
  const m=document.getElementById("scattermount"); m.innerHTML="";
  const svg=el("svg",{viewBox:`0 0 ${S} ${S}`,class:"bars",role:"img",
    "aria-label":"Log-log scatter of registered low-voltage capacity against OpenPVMapper capacity per commune"});
  svg.appendChild(el("rect",{x:0,y:0,width:S,height:S,fill:"var(--map-bg)"}));
  const diag=el("line",{x1:X(lo),y1:Y(lo),x2:X(hi),y2:Y(hi),stroke:"var(--ink-2)",
    "stroke-width":1,"stroke-dasharray":"4 4"}); svg.appendChild(diag);
  for(const [a,bv] of pts){
    svg.appendChild(el("circle",{cx:X(a).toFixed(1),cy:Y(bv).toFixed(1),r:1.3,
      fill:"var(--accent)","fill-opacity":0.30}));
  }
  for(const v of [10,100,1000,10000]){
    if(v>hi) continue;
    const t1=el("text",{x:X(v),y:S-pad+16,"text-anchor":"middle",class:"tick"}); t1.textContent=v>=1000?(v/1000)+"MW":v+"kW";
    const t2=el("text",{x:pad-8,y:Y(v)+4,"text-anchor":"end",class:"tick"}); t2.textContent=v>=1000?(v/1000)+"MW":v+"kW";
    svg.appendChild(t1); svg.appendChild(t2);
  }
  m.appendChild(svg);
}

/* ---------- tables & bars ---------- */
function renderFit(){
  const f=DATA.opvm_vs_register;
  const rows=[["All registered PV","vs_all_pv"],["Low-voltage only","vs_bt_only"],
              ["Below 72 kWp, both sides","vs_below_floor_bt"],
              ["Low-voltage, 2+ sources only","vs_bt_only_corroborated"]];
  let h="<tr><th>Comparison</th><th>n</th><th>slope</th><th>median ratio</th><th>Spearman</th><th>total ratio</th></tr>";
  for(const [lab,key] of rows){
    const r=f[key]||{};
    h+=`<tr><td>${lab}</td><td>${(r.n||0).toLocaleString()}</td><td>${fmt(r.slope_through_origin,3)}</td>
        <td>${fmt(r.median_ratio,3)}</td><td>${fmt(r.spearman,3)}</td><td>${fmt(r.total_ratio,3)}</td></tr>`;
  }
  document.getElementById("fittable").innerHTML=h;
  document.getElementById("fitnote").innerHTML =
    `OpenPVMapper's own implied capacity density is ${fmt(f.implied_kwp_per_m2,3)} kWp/m&sup2;, against
     ${fmt(DATA.kpi.module_constant,3)} measured here from the register and hand-mapped area.`;
}

function renderQuad(){
  const q=DATA.quadrats||[];
  let h="<tr><th>Commune</th><th>mapped PV</th><th>OpenPVMapper</th><th>recall</th><th>precision</th><th>on thermal</th></tr>";
  for(const r of q){
    h+=`<tr><td>${r.commune}</td><td>${r.n_truth}</td><td>${r.n_opvm}</td>
        <td>${pct(r.recall)}</td><td>${r.precision===null?"n/a":pct(r.precision)}</td>
        <td>${r.on_thermal}</td></tr>`;
  }
  const p=DATA.opvm_vs_mapped;
  h+=`<tr style="font-weight:700"><td>Pooled</td><td>${(p.n_truth||0).toLocaleString()}</td>
      <td>${(p.n_opvm||0).toLocaleString()}</td><td>${pct(p.pooled_count_recall)}</td>
      <td>${pct(p.pooled_precision_raw)}</td><td>${p.unmatched_breakdown.on_solar_thermal}</td></tr>`;
  document.getElementById("quadtable").innerHTML=h;
}

function barChart(mountId, items, unit, ariaLabel){
  const m=document.getElementById(mountId); m.innerHTML="";
  const Wb=380, rowH=34, H2=items.length*rowH+26;
  const max=Math.max(...items.map(i=>i[1]),1e-9);
  const svg=el("svg",{viewBox:`0 0 ${Wb} ${H2}`,class:"bars",role:"img","aria-label":ariaLabel});
  items.forEach(([lab,v,colr],i)=>{
    const y=i*rowH+8, w=Math.max(2,(v/max)*(Wb-190));
    svg.appendChild(el("rect",{x:150,y:y,width:w.toFixed(1),height:15,rx:3,
      fill:colr||"var(--accent)"}));
    const t=el("text",{x:144,y:y+12,"text-anchor":"end",class:"tick"}); t.textContent=lab;
    const t2=el("text",{x:150+w+6,y:y+12,class:"tick"}); t2.textContent=unit(v);
    svg.appendChild(t); svg.appendChild(t2);
  });
  m.appendChild(svg);
}

function renderTruthCharts(){
  const u=DATA.opvm_vs_mapped.unmatched_breakdown;
  barChart("fpmount", [
    ["solar thermal", u.on_solar_thermal, "var(--large)"],
    ["mapper retracted", u.on_retracted_feature, "var(--extended)"],
    ["unexplained", u.unexplained, "var(--accent)"],
  ], v=>v.toLocaleString()+" polygons",
  "Bar chart of what unmatched OpenPVMapper polygons overlap");

  const mc=DATA.module_constant||{};
  barChart("mcmount", [
    ["measured, epoch-matched", mc.pooled_kwp_per_m2_epoch_matched||0, "var(--domain)"],
    ["measured, uncorrected", mc.pooled_kwp_per_m2_uncorrected||0, "var(--accent-dim)"],
    ["project constant", 0.18, "var(--accent)"],
    ["OpenPVMapper implied", DATA.opvm_vs_register.implied_kwp_per_m2||0, "var(--large)"],
  ], v=>v.toFixed(3)+" kWp/m2",
  "Bar chart comparing measured and assumed capacity per square metre");
}

function renderFloor(){
  const k=DATA.kpi;
  barChart("floormount", [
    ["France, all PV", k.below_floor_all, "var(--accent-dim)"],
    ["France, low-voltage", k.below_floor_bt, "var(--accent)"],
    ["Germany, rooftop", k.germany_rooftop, "var(--large)"],
  ], v=>(100*v).toFixed(1)+"%",
  "Bar chart of capacity share below the 400 square metre detection floor");

  const rb=DATA.opvm_vs_mapped.recall_by_installation_m2||{};
  const order=Object.keys(rb).sort((a,b)=>parseFloat(a.slice(1))-parseFloat(b.slice(1)));
  barChart("sizemount", order.map(k2=>{
    const lo=parseFloat(k2.slice(1).split(",")[0]);
    const hi=parseFloat(k2.split(", ")[1]);
    const lab=hi>1e8?`${lo}+ m2`:`${lo}–${hi} m2`;
    return [lab+" (n="+rb[k2].n+")", rb[k2].area_recall, "var(--domain)"];
  }), v=>(100*v).toFixed(0)+"%",
  "Bar chart of OpenPVMapper area recall by installation size");
}

function renderMethod(){
  const s=DATA.skipped||{};
  const missing = Object.keys(s).length
    ? "<p><strong>Not yet included on this page:</strong> " +
      Object.entries(s).map(([k,v])=>`<code>${k}</code> (${v})`).join("; ") + ".</p>"
    : "";
  document.getElementById("method").innerHTML = `
  <p><strong>The register</strong> is ODR&Eacute;'s <em>registre national des installations de
  production et de stockage d'&eacute;lectricit&eacute;</em>, snapshot ${DATA.register_snapshot||""}.
  It covers every network operator, including the local distributors serving five of the
  mapped communes. Installations below 36 kW are published only as per-commune or per-IRIS
  aggregates carrying a unit count and a total, so individual sizes below that cliff do not
  exist in the data and no share below 36 kW can be recovered. There are no coordinates at
  any size, which is why Germany's <code>p_unmapped</code> precision check has no French
  counterpart.</p>

  <p><strong>There is no rooftop/ground field.</strong> Every share on this page is therefore
  bracketed rather than stated: all registered PV as the lower bound, low-voltage
  connections only as the rooftop-leaning upper one. France's fleet is far more
  ground-mount-heavy than Germany's, which is most of why its below-floor share looks so
  different from Germany's 65.5%. The two are not the same measurement.</p>

  <p><strong>OpenPVMapper</strong> (${DATA.opvm_doi}, CC-BY-4.0) is a model output, not
  ground truth: its own validation puts weighted precision near 74-75%, rising from 71.5%
  for single-source rows to 98.2% where three sources agree. Agreement between it and
  earthpv would not be validation of either. Its vintages are IGN flight dates per
  d&eacute;partement and do not match the register's snapshot, so a ratio below one is
  partly growth rather than under-detection.</p>

  <p><strong>The fourteen communes are the only ground truth</strong>, and they are not
  independent of OpenPVMapper: they are its manual-correction layer. Precision measured
  inside them is an optimistic bound; recall is the half that transfers. Saint-G&eacute;ly-du-Fesc
  is marked unfinished by the mapper and is excluded from every calibration fit.</p>

  <p><strong>Solar thermal is tagged separately and excluded from PV.</strong> 381 of the
  3,335 mapped features are hot-water collectors. They carry area and produce no kilowatts,
  and a detector working from imagery alone has little to separate them from PV, which is
  why the unmatched-detection breakdown reports them as their own class rather than as
  errors.</p>

  <p><strong>The module constant</strong> is register capacity divided by hand-mapped module
  area, restricted on both sides to the population under the register's 36 kW cliff
  (200 m&sup2; at 0.18 kWp/m&sup2;), and with the register read back to each commune's own mapping
  year by interpolating between year-end vintages. Without that epoch correction the same
  ratio reads
  ${fmt(DATA.module_constant&&DATA.module_constant.pooled_kwp_per_m2_uncorrected,3)} kWp/m&sup2;,
  inflated by the installations France added between the flight and today.</p>
  ${missing}`;
}

/* ---------- tabs & theme ---------- */
document.getElementById("tabs").addEventListener("click", e => {
  const b = e.target.closest("button[data-tab]"); if(!b) return;
  for(const x of document.querySelectorAll("#tabs button")) x.setAttribute("aria-selected", String(x===b));
  for(const id of ["reg","truth","floor"]) document.getElementById("tab-"+id).hidden = (id!==b.dataset.tab);
});
new MutationObserver(()=>{renderMap();}).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderMap);

kpis(); renderMap(); renderScatter(); renderFit(); renderQuad();
renderTruthCharts(); renderFloor(); renderMethod();
document.getElementById("foot").innerHTML =
  "Built by scripts/build_france_comparison_atlas.py from results/france_validation/. " +
  "Register: ODR&Eacute;. Reference database: OpenPVMapper, " + (DATA.opvm_doi||"") + ", CC-BY-4.0.";
</script>
</body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
