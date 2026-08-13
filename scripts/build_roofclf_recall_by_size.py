"""Recall-focused recreation of `results/roofclf_precision_by_size.html` (that file's
own source script did not survive -- see `roofclf_size_density_signal.py`'s
docstring). Same equal-count, by-size-bin methodology, but recall is the metric this
page leads with, precision is demoted to context.

Why the swap: precision on this population is a documented lower bound whenever the
validation imagery predates the current epoch -- a genuinely new installation still
reads as a false positive until someone re-maps it, so precision is biased down by an
unknown, unmeasured amount. Recall over the labelled installations already on the
ground has no equivalent bias; it is the clean number here, and it is also the one
this project has explicitly prioritized (`CLAUDE.md`: "recall-first ... false
positives are tolerated"). A synthetic size floor spends *recall* directly and
*measurably*; the precision it buys back is real but of unknown size. Read the recall
curve as the primary evidence, and treat precision as directional context only.

Recomputed fresh against whatever `data/roofclf/` currently holds (27 Rule-1-complete
quadrats as of 2026-08-13, not the 13-18 the original diagnostic saw) --
`select_calibrated_quadrats`'s own ratio-band filter decides how many of those are
trusted here, same as every other roofclf capacity path.

Usage:
    .pixi/envs/default/bin/python scripts/build_roofclf_recall_by_size.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.sub400_capacity import select_calibrated_quadrats  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUILDINGS = ROOT / "data/roofclf/buildings.geoparquet"
FOLDS = ROOT / "data/roofclf/folds.csv"
SUMMARY_JSON = ROOT / "data/roofclf/summary.json"
OUT = ROOT / "results/roofclf_recall_by_size.html"

N_SIZE_BINS = 12
FLOOR_BREAKPOINTS_M2 = (0, 50, 100, 150, 200, 250, 300, 350, 400)


def _confusion(pred: np.ndarray, has_pv: np.ndarray) -> dict:
    tp = int((pred & (has_pv == 1)).sum())
    fp = int((pred & (has_pv == 0)).sum())
    fn = int((~pred & (has_pv == 1)).sum())
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if (tp + fp) else float("nan"),
        "recall": tp / (tp + fn) if (tp + fn) else float("nan"),
    }


def size_bin_table(b: pd.DataFrame, threshold: float, n_bins: int) -> pd.DataFrame:
    area = b["roof_area_m2"].to_numpy(float)
    edges = np.unique(np.quantile(area, np.linspace(0.0, 1.0, n_bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    bin_idx = np.clip(np.searchsorted(edges, area, side="right") - 1, 0, len(edges) - 2)

    rows = []
    for i in range(len(edges) - 1):
        sub = b[bin_idx == i]
        pred = sub.p_oof.to_numpy(float) >= threshold
        has_pv = sub.has_pv.to_numpy(int)
        conf = _confusion(pred, has_pv)
        n_pv = int((has_pv == 1).sum())
        rows.append({
            "size": float(sub["roof_area_m2"].median()),
            "lo": float(sub["roof_area_m2"].min()),
            "hi": float(sub["roof_area_m2"].max()),
            "n": int(len(sub)), "nf": int(pred.sum()), "n_pv": n_pv,
            "base": n_pv / len(sub) if len(sub) else float("nan"),
            "prec": conf["precision"], "rec": conf["recall"],
        })
    return pd.DataFrame(rows)


def floor_curve(b: pd.DataFrame, threshold: float, floors: tuple[float, ...]) -> pd.DataFrame:
    area = b["roof_area_m2"].to_numpy(float)
    p_oof = b["p_oof"].to_numpy(float)
    has_pv = b["has_pv"].to_numpy(int)
    rows = []
    for floor in floors:
        pred = (p_oof >= threshold) & (area >= floor)
        conf = _confusion(pred, has_pv)
        rows.append({"floor_m2": floor, "n_flagged": int(pred.sum()), **conf})
    return pd.DataFrame(rows)


def fmt_range(lo: float, hi: float) -> str:
    lo_s = f"{lo:.1f}" if lo < 1 else f"{lo:.0f}"
    hi_s = f"{round(hi / 1000)}k" if hi > 9000 else f"{hi:.0f}"
    return f"{lo_s}–{hi_s}"


def main() -> None:
    threshold = json.loads(SUMMARY_JSON.read_text())["deployment_threshold"]
    quadrats, folds_subset = select_calibrated_quadrats(FOLDS)
    n_total_quadrats = len(pd.read_csv(FOLDS))

    all_buildings = gpd.read_parquet(BUILDINGS)
    b = all_buildings[all_buildings.quadrat.isin(quadrats)].copy()

    bins = size_bin_table(b, threshold, N_SIZE_BINS)
    floors = floor_curve(b, threshold, FLOOR_BREAKPOINTS_M2)

    no_floor = floors[floors.floor_m2 == 0].iloc[0]
    f100 = floors[floors.floor_m2 == 100].iloc[0]
    f200 = floors[floors.floor_m2 == 200].iloc[0]
    smallest = bins.iloc[0]
    half_bin = bins[bins.rec >= 0.5].iloc[0]

    print(f"threshold = {threshold}")
    print(f"{len(quadrats)}/{n_total_quadrats} quadrats calibrated: {quadrats}")
    print(f"n buildings = {len(b)}, n_pv = {int(b.has_pv.sum())}")
    print(bins.to_string(index=False))
    print()
    print(floors.to_string(index=False))

    data_js = ",\n    ".join(
        "{size:%.4f, lo:%.4f, hi:%.4f, n:%d, nf:%d, n_pv:%d, base:%.4f, prec:%.4f, rec:%.4f}" % (
            r.size, r.lo, r.hi, r.n, r.nf, r.n_pv, r.base, r.prec, r.rec,
        )
        for r in bins.itertuples()
    )

    half_bin_size = round(half_bin.size)
    n_pv_total = int(b.has_pv.sum())

    html = HTML_TEMPLATE.format(
        n_quadrats=len(quadrats),
        n_total_quadrats=n_total_quadrats,
        threshold=f"{threshold:.4f}",
        no_floor_rec=f"{no_floor.recall:.3f}",
        no_floor_prec=f"{no_floor.precision:.3f}",
        smallest_lo=fmt_range(smallest.lo, smallest.hi).split("–")[0],
        smallest_hi=fmt_range(smallest.lo, smallest.hi).split("–")[1],
        smallest_rec=f"{smallest.rec:.3f}",
        smallest_prec=f"{smallest.prec:.3f}",
        half_bin_size=half_bin_size,
        half_bin_rec=f"{half_bin.rec:.3f}",
        f200_cost_pp=f"{(no_floor.recall - f200.recall) * 100:.1f}",
        f200_rec_from=f"{no_floor.recall:.3f}",
        f200_rec_to=f"{f200.recall:.3f}",
        f100_cost_pp=f"{(no_floor.recall - f100.recall) * 100:.1f}",
        f100_rec_from=f"{no_floor.recall:.3f}",
        f100_rec_to=f"{f100.recall:.3f}",
        f100_prec_gain_pp=f"{(f100.precision - no_floor.precision) * 100:.1f}",
        f200_prec_gain_pp=f"{(f200.precision - no_floor.precision) * 100:.1f}",
        n_pv_total=f"{n_pv_total:,}",
        n_total=f"{len(b):,}",
        per_bin_n=f"{int(bins.n.median()):,}",
        data_js=data_js,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"-> {OUT}")


HTML_TEMPLATE = """<title>roofclf: recall by building size</title>
<style>
.rbs-root {{
  color-scheme: dark;
  --surface-0:      #100e0b;
  --surface-1:      #1a1712;
  --surface-2:      #211d17;
  --line:           #35301F;
  --line-soft:      #26221a;
  --text-primary:   #f3efe4;
  --text-secondary: #b9b19c;
  --text-muted:     #837c6c;
  --recall:         #4f95e8;
  --recall-soft:    rgba(79,149,232,0.16);
  --precision:      #f0b429;
  --precision-soft: rgba(240,180,41,0.14);
  --good:           #4fae6d;
  --rule-marker:    #e2665a;
  --shadow: 0 1px 0 rgba(0,0,0,0.4), 0 12px 32px -16px rgba(0,0,0,0.6);
}}
@media (prefers-color-scheme: light) {{
  :root:where(:not([data-theme="dark"])) .rbs-root {{
    color-scheme: light;
    --surface-0:      #faf8f3;
    --surface-1:      #ffffff;
    --surface-2:      #f2efe6;
    --line:           #e3ddcb;
    --line-soft:      #ece7d9;
    --text-primary:   #211d17;
    --text-secondary: #5b5646;
    --text-muted:     #8a8471;
    --recall:         #2a68c4;
    --recall-soft:    rgba(42,104,196,0.10);
    --precision:      #b5790a;
    --precision-soft: rgba(181,121,10,0.08);
    --good:           #227a45;
    --rule-marker:    #b8443a;
    --shadow: 0 1px 0 rgba(0,0,0,0.03), 0 12px 32px -18px rgba(0,0,0,0.18);
  }}
}}
:root[data-theme="light"] .rbs-root {{
  color-scheme: light;
  --surface-0:      #faf8f3;
  --surface-1:      #ffffff;
  --surface-2:      #f2efe6;
  --line:           #e3ddcb;
  --line-soft:      #ece7d9;
  --text-primary:   #211d17;
  --text-secondary: #5b5646;
  --text-muted:     #8a8471;
  --recall:         #2a68c4;
  --recall-soft:    rgba(42,104,196,0.10);
  --precision:      #b5790a;
  --precision-soft: rgba(181,121,10,0.08);
  --good:           #227a45;
  --rule-marker:    #b8443a;
  --shadow: 0 1px 0 rgba(0,0,0,0.03), 0 12px 32px -18px rgba(0,0,0,0.18);
}}

* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
.rbs-root {{
  background: var(--surface-0);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  min-height: 100vh;
  padding: 48px 20px 80px;
}}
.rbs-wrap {{ max-width: 900px; margin: 0 auto; }}
.mono {{
  font-family: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;
}}

.eyebrow {{
  font-size: 12px; font-weight: 600; letter-spacing: 0.09em; text-transform: uppercase;
  color: var(--recall); margin: 0 0 10px;
}}
h1 {{
  font-size: 30px; line-height: 1.2; font-weight: 650; margin: 0 0 12px; text-wrap: balance;
  letter-spacing: -0.01em;
}}
.lede {{
  font-size: 16px; line-height: 1.6; color: var(--text-secondary); max-width: 64ch; margin: 0 0 36px;
}}
.lede code {{ color: var(--text-primary); }}

.kpis {{
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px;
  background: var(--line); border: 1px solid var(--line); border-radius: 12px;
  overflow: hidden; margin-bottom: 32px; box-shadow: var(--shadow);
}}
.kpi {{ background: var(--surface-1); padding: 18px 16px; }}
.kpi .label {{ font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }}
.kpi .value {{ font-size: 23px; font-weight: 650; letter-spacing: -0.01em; }}
.kpi .value.recall {{ color: var(--recall); }}
.kpi .sub {{ font-size: 12.5px; color: var(--text-secondary); margin-top: 4px; }}

.card {{
  background: var(--surface-1); border: 1px solid var(--line); border-radius: 14px;
  padding: 26px 26px 18px; box-shadow: var(--shadow); margin-bottom: 28px;
}}
.card h2 {{ font-size: 15px; font-weight: 650; margin: 0 0 2px; }}
.card .card-sub {{ font-size: 12.5px; color: var(--text-muted); margin: 0 0 18px; }}

.legend {{ display: flex; gap: 20px; margin-bottom: 4px; }}
.legend-item {{ display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-secondary); }}
.legend-swatch {{ width: 18px; height: 3px; border-radius: 2px; }}

svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
.axis-label {{ font-size: 10.5px; fill: var(--text-muted); }}
.axis-line {{ stroke: var(--line); stroke-width: 1; }}
.grid-line {{ stroke: var(--line-soft); stroke-width: 1; }}
.series-line {{ fill: none; stroke-width: 2.25; }}
.series-line.secondary {{ stroke-width: 1.75; opacity: 0.75; }}
.dot {{ stroke: var(--surface-1); stroke-width: 1.5; }}
.marker-line {{ stroke: var(--rule-marker); stroke-width: 1.5; stroke-dasharray: 4 3; }}
.marker-label {{
  font-size: 10.5px; fill: var(--rule-marker); font-weight: 600;
}}
.hover-x {{ stroke: var(--text-muted); stroke-width: 1; opacity: 0; pointer-events: none; }}

.tooltip {{
  position: absolute; pointer-events: none; background: var(--surface-2);
  border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
  font-size: 12px; line-height: 1.55; box-shadow: var(--shadow); opacity: 0;
  transition: opacity 0.08s ease; min-width: 168px; z-index: 5;
}}
.tooltip .t-size {{ font-weight: 650; margin-bottom: 5px; color: var(--text-primary); }}
.tooltip .t-row {{ display: flex; justify-content: space-between; gap: 14px; }}
.tooltip .t-row .k {{ color: var(--text-muted); }}
.tooltip .t-row .v {{ color: var(--text-primary); }}
.tooltip .t-row.recall .v {{ color: var(--recall); }}
.tooltip .t-row.precision .v {{ color: var(--precision); }}

.chart-wrap {{ position: relative; }}

.note {{
  background: var(--surface-1); border: 1px solid var(--line); border-radius: 14px;
  padding: 20px 24px; box-shadow: var(--shadow);
}}
.note h2 {{ font-size: 14.5px; font-weight: 650; margin: 0 0 10px; }}
.note p {{ font-size: 14px; line-height: 1.65; color: var(--text-secondary); margin: 0 0 10px; }}
.note p:last-child {{ margin-bottom: 0; }}
.note .foot {{ font-size: 12px; color: var(--text-muted); margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line-soft); }}

@media (max-width: 640px) {{
  .kpis {{ grid-template-columns: repeat(2, 1fr); }}
  h1 {{ font-size: 24px; }}
}}
</style>

<div class="rbs-root">
  <div class="rbs-wrap">
    <div class="eyebrow">roofclf &middot; sub-400 m&sup2; classifier</div>
    <h1>Recall climbs steeply with building size &mdash; and it's the number to trust here</h1>
    <p class="lede">
      Precision on this population is a documented <strong>lower bound</strong>: validation
      imagery predates the current epoch, so a genuinely new installation still scores as a
      false positive until someone re-maps it. Recall over the {n_pv_total} labelled
      installations already mapped carries no equivalent bias &mdash; it is the clean signal for
      judging a sub-400&nbsp;m&sup2; size floor. Measured on the {n_quadrats} of {n_total_quadrats}
      Rule-1-complete quadrats <code>select_calibrated_quadrats</code> currently trusts,
      out-of-fold (<code>p_oof &ge; {threshold}</code>, the deployed threshold), split into 12
      equal-count bins (~{per_bin_n} buildings each) by each building's own roof area.
    </p>

    <div class="kpis">
      <div class="kpi">
        <div class="label">No size floor</div>
        <div class="value recall">{no_floor_rec}</div>
        <div class="sub">recall &middot; precision {no_floor_prec} (biased low)</div>
      </div>
      <div class="kpi">
        <div class="label">Smallest bin (&lt;{smallest_hi}&nbsp;m&sup2;)</div>
        <div class="value recall">{smallest_rec}</div>
        <div class="sub">recall &middot; precision {smallest_prec}</div>
      </div>
      <div class="kpi">
        <div class="label">Recall passes 50%</div>
        <div class="value">~{half_bin_size}&nbsp;m&sup2;</div>
        <div class="sub">bin median size &middot; recall {half_bin_rec}</div>
      </div>
      <div class="kpi">
        <div class="label">Cost of a 200&nbsp;m&sup2; floor</div>
        <div class="value">&minus;{f200_cost_pp}&nbsp;pp</div>
        <div class="sub">recall: {f200_rec_from} &rarr; {f200_rec_to}</div>
      </div>
    </div>

    <div class="card">
      <h2>Recall &amp; precision by roof-size bin</h2>
      <p class="card-sub">x-axis log-scaled &middot; ~{per_bin_n} buildings per bin (equal count) &middot; hover a point for detail</p>
      <div class="legend">
        <div class="legend-item"><span class="legend-swatch" style="background:var(--recall)"></span>Recall</div>
        <div class="legend-item"><span class="legend-swatch" style="background:var(--precision)"></span>Precision (biased low)</div>
      </div>
      <div class="chart-wrap" id="chartWrap">
        <svg id="chart" viewBox="0 0 860 400" preserveAspectRatio="xMidYMid meet"></svg>
        <div class="tooltip" id="tooltip"></div>
      </div>
    </div>

    <div class="note">
      <h2>Reading this the recall-first way</h2>
      <p>
        Below roughly 60&nbsp;m&sup2;, recall sits in the 0.21&ndash;0.35 range: the classifier
        is structurally missing most small installations, and that gap is real &mdash; it isn't
        an artifact of stale validation imagery the way the low precision numbers in the same
        bins are. Recall only crosses 50% around <strong>{half_bin_size}&nbsp;m&sup2;</strong> and
        keeps climbing past 0.9 for the largest roofs. Any size floor is spent against this
        curve directly.
      </p>
      <p>
        A <strong>100&nbsp;m&sup2;</strong> floor gives up <strong
        style="color:var(--recall)">{f100_cost_pp}&nbsp;pp of recall</strong> ({f100_rec_from}
        &rarr; {f100_rec_to}) for a precision gain of only +{f100_prec_gain_pp}&nbsp;pp &mdash; and
        that precision gain is itself measured on the same lower-bound metric, so its true size
        is unverified. A <strong>200&nbsp;m&sup2;</strong> floor gives up
        <strong style="color:var(--recall)">{f200_cost_pp}&nbsp;pp</strong> ({f200_rec_from}
        &rarr; {f200_rec_to}, roughly a third of recall gone) for +{f200_prec_gain_pp}&nbsp;pp on
        the same unverified metric. Given recall is the side of this trade we can actually
        measure without bias, a floor that steep is hard to justify from this chart alone.
      </p>
      <div class="foot">
        Recreated from `results/roofclf_precision_by_size.html` (that page's own build script
        did not survive) on current data: {n_quadrats}/{n_total_quadrats} Rule-1-complete
        quadrats, {n_total} buildings, {n_pv_total} labelled installations. Source:
        <code>scripts/build_roofclf_recall_by_size.py</code>.
      </div>
    </div>
  </div>
</div>

<script>
(function () {{
  const data = [
    {data_js}
  ];

  const svg = document.getElementById('chart');
  const ns = 'http://www.w3.org/2000/svg';
  const W = 860, H = 400;
  const M = {{top: 14, right: 20, bottom: 40, left: 42}};
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;

  const xMin = Math.log10(10), xMax = Math.log10(600);
  const xScale = (v) => M.left + (Math.log10(v) - xMin) / (xMax - xMin) * plotW;
  const yScale = (v) => M.top + (1 - v) * plotH;

  function el(tag, attrs) {{
    const e = document.createElementNS(ns, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }}

  const gridG = el('g', {{}});
  [0, 0.25, 0.5, 0.75, 1].forEach((v) => {{
    gridG.appendChild(el('line', {{
      x1: M.left, x2: W - M.right, y1: yScale(v), y2: yScale(v), class: 'grid-line',
    }}));
    const t = el('text', {{ x: M.left - 8, y: yScale(v) + 3, class: 'axis-label mono', 'text-anchor': 'end' }});
    t.textContent = v.toFixed(2);
    gridG.appendChild(t);
  }});
  [20, 50, 100, 200, 400].forEach((v) => {{
    const x = xScale(v);
    gridG.appendChild(el('line', {{ x1: x, x2: x, y1: M.top, y2: M.top + plotH, class: 'grid-line' }}));
    const t = el('text', {{ x: x, y: H - M.bottom + 18, class: 'axis-label mono', 'text-anchor': 'middle' }});
    t.textContent = v + ' m²';
    gridG.appendChild(t);
  }});
  gridG.appendChild(el('line', {{ x1: M.left, x2: M.left, y1: M.top, y2: M.top + plotH, class: 'axis-line' }}));
  gridG.appendChild(el('line', {{ x1: M.left, x2: W - M.right, y1: M.top + plotH, y2: M.top + plotH, class: 'axis-line' }}));
  svg.appendChild(gridG);

  const mx = xScale({half_bin_size});
  svg.appendChild(el('line', {{ x1: mx, x2: mx, y1: M.top, y2: M.top + plotH, class: 'marker-line' }}));
  const mLabel = el('text', {{ x: mx + 6, y: M.top + 13, class: 'marker-label' }});
  mLabel.textContent = 'recall passes 50% (~{half_bin_size} m²)';
  svg.appendChild(mLabel);

  function path(key) {{
    return data.map((d, i) => `${{i === 0 ? 'M' : 'L'}} ${{xScale(d.size).toFixed(1)}} ${{yScale(d[key]).toFixed(1)}}`).join(' ');
  }}

  const precPath = el('path', {{ d: path('prec'), class: 'series-line secondary', stroke: 'var(--precision)' }});
  const recPath = el('path', {{ d: path('rec'), class: 'series-line', stroke: 'var(--recall)' }});
  svg.appendChild(precPath);
  svg.appendChild(recPath);

  const dotsG = el('g', {{}});
  data.forEach((d) => {{
    dotsG.appendChild(el('circle', {{ cx: xScale(d.size), cy: yScale(d.prec), r: 3, fill: 'var(--precision)', class: 'dot' }}));
    dotsG.appendChild(el('circle', {{ cx: xScale(d.size), cy: yScale(d.rec), r: 3.5, fill: 'var(--recall)', class: 'dot' }}));
  }});
  svg.appendChild(dotsG);

  const hoverLine = el('line', {{ x1: 0, x2: 0, y1: M.top, y2: M.top + plotH, class: 'hover-x' }});
  svg.appendChild(hoverLine);

  const wrap = document.getElementById('chartWrap');
  const tooltip = document.getElementById('tooltip');

  function fmtRange(d) {{
    const lo = d.lo < 1 ? d.lo.toFixed(1) : Math.round(d.lo);
    const hi = d.hi > 9000 ? Math.round(d.hi / 1000) + 'k' : Math.round(d.hi);
    return `${{lo}}–${{hi}} m²`;
  }}

  function showTooltip(i) {{
    const d = data[i];
    hoverLine.setAttribute('x1', xScale(d.size));
    hoverLine.setAttribute('x2', xScale(d.size));
    hoverLine.style.opacity = 1;
    tooltip.innerHTML = `
      <div class="t-size">${{fmtRange(d)}}</div>
      <div class="t-row recall"><span class="k">Recall</span><span class="v mono">${{d.rec.toFixed(3)}}</span></div>
      <div class="t-row precision"><span class="k">Precision</span><span class="v mono">${{d.prec.toFixed(3)}}</span></div>
      <div class="t-row"><span class="k">Base rate</span><span class="v mono">${{(d.base * 100).toFixed(1)}}%</span></div>
      <div class="t-row"><span class="k">n / n_pv</span><span class="v mono">${{d.n.toLocaleString()}} / ${{d.n_pv.toLocaleString()}}</span></div>
    `;
    const rect = wrap.getBoundingClientRect();
    const px = (xScale(d.size) / W) * rect.width;
    tooltip.style.left = Math.min(px + 14, rect.width - 190) + 'px';
    tooltip.style.top = '8px';
    tooltip.style.opacity = 1;
  }}
  function hideTooltip() {{
    tooltip.style.opacity = 0;
    hoverLine.style.opacity = 0;
  }}

  function nearest(px) {{
    let best = 0, bestDist = Infinity;
    data.forEach((d, i) => {{
      const dist = Math.abs(xScale(d.size) - px);
      if (dist < bestDist) {{ bestDist = dist; best = i; }}
    }});
    return best;
  }}

  svg.addEventListener('mousemove', (evt) => {{
    const rect = svg.getBoundingClientRect();
    const px = (evt.clientX - rect.left) / rect.width * W;
    showTooltip(nearest(px));
  }});
  svg.addEventListener('mouseleave', hideTooltip);
  svg.addEventListener('touchstart', (evt) => {{
    const touch = evt.touches[0];
    const rect = svg.getBoundingClientRect();
    const px = (touch.clientX - rect.left) / rect.width * W;
    showTooltip(nearest(px));
  }}, {{ passive: true }});
}})();
</script>
"""


if __name__ == "__main__":
    main()
