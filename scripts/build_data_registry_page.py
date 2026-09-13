#!/usr/bin/env python
"""Render the country data registry as a filterable page for the docs site.

The CSV is the source of truth and ships in the repo; this only makes it browsable, because
ninety rows of prose across fifteen columns is not something anyone reads in a spreadsheet
while deciding whether their country has usable labels.

Filtering is client-side over a JSON blob inlined into the page, so the page works from the
docs site, from `file://`, and offline.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROLE_META = {
    "train_positives": ("Train on it", "#2fd9c4",
                        "Confirmed PV with geometry: Gold or Silver labels."),
    "roof_context": ("Roof context", "#4fb2e8",
                     "Buildings or roof potential, no PV label. Negatives and the roof "
                     "universe. Potential is not installed PV."),
    "pseudo_labels": ("Bronze only", "#9c6fd1",
                      "Model-derived detections. Active-learning pool; agreement is not "
                      "validation."),
    "calibration_only": ("Calibrate only", "#f5a623",
                         "Counts or capacity by area, no geometry. Never training labels."),
    "access_required": ("Ask first", "#93866c",
                        "Register exists, record-level export restricted. A partnership lead."),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/training_data_registry.html")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from earthpv.data_registry import ROLE_NEXT_STEP, load_registry

    d = load_registry(ROOT / "docs/assets/registry/earthpv_training_data_registry.csv")
    cols = ["continent", "country", "dataset_name", "provider", "earthpv_role", "priority",
            "source_type", "label_or_geometry", "confirmed_pv_presence_label",
            "scale_or_record_count", "license_or_access", "recommended_earthpv_use",
            "source_url", "notes"]
    rows = json.dumps([{c: ("" if str(r[c]) == "nan" else str(r[c])) for c in cols}
                       for _, r in d.iterrows()])
    countries = json.dumps(sorted(d.country.dropna().unique().tolist()))
    continents = json.dumps(sorted(d.continent.dropna().unique().tolist()))
    legend = "".join(
        f'<div class="lg"><span class="pill" style="background:{c}">{label}</span>'
        f'<span class="lgtxt">{html.escape(desc)}</span></div>'
        for label, c, desc in ROLE_META.values())
    steps = "".join(
        f'<details class="xdetails"><summary>{html.escape(ROLE_META[k][0])}: what to do next'
        f'</summary><p>{html.escape(v)}</p></details>' for k, v in ROLE_NEXT_STEP.items())
    role_json = json.dumps({k: v[0] for k, v in ROLE_META.items()})
    colour_json = json.dumps({k: v[1] for k, v in ROLE_META.items()})

    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>earthpv country data registry</title><style>
:root{{--bg:#100d09;--panel:#1a160f;--ink:#f7f1e6;--dim:#c9bda4;--rule:#3a2d16;--acc:#f5a623}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:22px 16px 60px}}
h1{{font-size:20px;margin:0 0 6px}} .sub{{color:var(--dim);margin:0 0 18px;max-width:74ch}}
.kpis{{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 18px}}
.kpi{{background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:10px 14px}}
.kpi b{{display:block;font-size:20px;color:var(--acc)}} .kpi span{{color:var(--dim);font-size:12px}}
.controls{{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}}
select,input{{background:var(--panel);color:var(--ink);border:1px solid var(--rule);
 border-radius:6px;padding:7px 9px;font-size:13px}}
.lg{{display:flex;gap:8px;align-items:flex-start;margin:3px 0}}
.lgtxt{{color:var(--dim);font-size:12.5px}}
.pill{{display:inline-block;color:#100d09;border-radius:999px;padding:1px 9px;font-size:11.5px;
 font-weight:700;white-space:nowrap}}
table{{width:100%;border-collapse:collapse;margin-top:14px}}
th,td{{text-align:left;padding:8px 9px;border-bottom:1px solid var(--rule);vertical-align:top}}
th{{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.04em;
 cursor:pointer;user-select:none}}
td.nm{{font-weight:600}} td small{{color:var(--dim)}}
a{{color:var(--acc)}} .xdetails{{background:var(--panel);border:1px solid var(--rule);
 border-radius:8px;padding:9px 12px;margin:6px 0}} summary{{cursor:pointer;color:var(--acc)}}
.tablewrap{{overflow-x:auto}} .none{{color:var(--dim);padding:18px 0}}
</style></head><body><div class="wrap">
<h1>Country data registry</h1>
<p class="sub">Ninety published datasets across fifty-one countries: PV labels, national
installation registers, aggregate statistics and building/roof layers. Use it to find out what
a country already publishes before starting a mapping campaign. The role tag is derived from
whether PV presence is confirmed and whether records carry geometry, because that decides
whether a source can train a model, only calibrate one, or neither.</p>
<div class="kpis" id="kpis"></div>
<div>{legend}</div>
{steps}
<div class="controls">
 <input id="q" placeholder="search name, provider, notes..." size="30">
 <select id="continent"><option value="">all continents</option></select>
 <select id="country"><option value="">all countries</option></select>
 <select id="role"><option value="">all roles</option></select>
</div>
<div class="tablewrap"><table><thead><tr>
<th data-k="country">Country</th><th data-k="dataset_name">Dataset</th>
<th data-k="earthpv_role">Role</th><th data-k="priority">Priority</th>
<th data-k="scale_or_record_count">Scale</th><th data-k="license_or_access">Licence / access</th>
</tr></thead><tbody id="tb"></tbody></table></div>
<div class="none" id="none" style="display:none">Nothing matches those filters.</div>
</div><script>
const ROWS={rows}, ROLE={role_json}, COLOUR={colour_json};
const $=s=>document.querySelector(s);
for(const c of {continents}) $("#continent").add(new Option(c,c));
for(const c of {countries}) $("#country").add(new Option(c,c));
for(const k in ROLE) $("#role").add(new Option(ROLE[k],k));
let sortK="country", sortDir=1;
function esc(s){{return (s||"").replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}})[c]);}}
function view(){{
 const q=$("#q").value.toLowerCase(), ct=$("#continent").value,
       co=$("#country").value, ro=$("#role").value;
 return ROWS.filter(r=>(!ct||r.continent===ct)&&(!co||r.country===co)&&(!ro||r.earthpv_role===ro)
  &&(!q||JSON.stringify(r).toLowerCase().includes(q)))
  .sort((a,b)=>String(a[sortK]).localeCompare(String(b[sortK]))*sortDir);
}}
function render(){{
 const v=view();
 $("#tb").innerHTML=v.map(r=>`<tr>
  <td>${{esc(r.country)}}<br><small>${{esc(r.continent)}}</small></td>
  <td class="nm"><a href="${{esc(r.source_url)}}" target="_blank" rel="noopener">${{esc(r.dataset_name)}}</a>
      <br><small>${{esc(r.provider)}}</small>
      <br><small>${{esc(r.recommended_earthpv_use)}}</small></td>
  <td><span class="pill" style="background:${{COLOUR[r.earthpv_role]}}">${{ROLE[r.earthpv_role]}}</span>
      <br><small>${{esc(r.confirmed_pv_presence_label)}}</small></td>
  <td>${{esc(r.priority)}}</td>
  <td><small>${{esc(r.scale_or_record_count)}}</small></td>
  <td><small>${{esc(r.license_or_access)}}</small></td></tr>`).join("");
 $("#none").style.display=v.length?"none":"block";
 const byRole={{}}; v.forEach(r=>byRole[r.earthpv_role]=(byRole[r.earthpv_role]||0)+1);
 $("#kpis").innerHTML=`<div class="kpi"><b>${{v.length}}</b><span>datasets shown</span></div>
  <div class="kpi"><b>${{new Set(v.map(r=>r.country)).size}}</b><span>countries</span></div>`+
  Object.keys(ROLE).filter(k=>byRole[k]).map(k=>
   `<div class="kpi"><b>${{byRole[k]}}</b><span>${{ROLE[k]}}</span></div>`).join("");
}}
document.querySelectorAll("th").forEach(th=>th.onclick=()=>{{
 const k=th.dataset.k; sortDir=(k===sortK)?-sortDir:1; sortK=k; render();}});
["q","continent","country","role"].forEach(id=>{{
 $("#"+id).oninput=render; $("#"+id).onchange=render;}});
render();
</script></body></html>"""
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(d)} datasets, {d.country.nunique()} countries)")


if __name__ == "__main__":
    main()
