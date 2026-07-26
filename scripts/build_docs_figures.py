#!/usr/bin/env python
"""Regenerate every figure the documentation site and the README embed.

Run with the pixi `default` environment (matplotlib + pillow only, no GPU):

    pixi run docs-figures
    # or
    .pixi/envs/default/bin/python scripts/build_docs_figures.py

Outputs land in `docs/assets/figures/`. Each chart is written twice, as
`<name>.svg` (light) and `<name>.dark.svg` (dark), so MkDocs Material can swap
them with the `#only-light` / `#only-dark` image suffixes and the site reads
correctly in both themes.

Numbers come from files on disk wherever a file exists, so a re-run after a new
pipeline pass picks up the new values:

  * glint sensitivity      results/glint_validation_pakistan/pakistan_stats_by_size.csv
  * capacity estimators    results/pakistan_pv_estimator_atlas.html (embedded JSON)
  * calibration table      configs/calibration/pakistan_candidate_precision.yaml
  * hero capacity map      results/pakistan_pv_density_scientific.png (auto-cropped)

The one exception is the per-installation recall table, which `earthpv evaluate`
prints to stdout rather than writing to disk; it is transcribed into RECALL
below with the checkpoint it came from.

Palette: the validated default categorical slots 1-3 (blue / orange / aqua),
used unchanged in the documented fixed order.
"""

from __future__ import annotations

import csv
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "figures"


# --------------------------------------------------------------------------- theme


@dataclass(frozen=True)
class Theme:
    """One rendering mode. Series hues are the validated slots, per mode."""

    name: str
    surface: str
    ink: str
    ink_dim: str
    ink_faint: str
    rule: str
    s1: str
    s2: str
    s3: str
    band: str


LIGHT = Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#8a8880", "#e1e0d9",
              "#2a78d6", "#eb6834", "#1baf7a", "#f0efec")
DARK = Theme("dark", "#1a1a19", "#ffffff", "#c3c2b7", "#8a8880", "#383835",
             "#3987e5", "#d95926", "#199e70", "#262624")
THEMES = (LIGHT, DARK)


def new_fig(t: Theme, w: float, h: float):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(t.surface)
    ax.set_facecolor(t.surface)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=t.ink_dim, labelsize=9, length=0)
    return fig, ax


def style_axes(ax, t: Theme, *, xgrid=False, ygrid=False):
    ax.grid(axis="y" if ygrid else "x", visible=xgrid or ygrid,
            color=t.rule, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_color(t.ink_dim)


def save(fig, t: Theme, stem: str):
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = ".svg" if t.name == "light" else ".dark.svg"
    path = OUT / f"{stem}{suffix}"
    fig.savefig(path, format="svg", facecolor=t.surface, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)
    print(f"  wrote {path.relative_to(ROOT)}")


def titled(fig, t: Theme, title: str, subtitle: str = "", width: int = 96):
    """Left-aligned title block above the axes, wrapped so it never collides."""
    h = fig.get_size_inches()[1]
    line = 0.19 / h  # one 9.5pt line, in figure-height units
    lines = textwrap.wrap(subtitle, width) if subtitle else []
    top = 1.0 + (len(lines) + 1.4) * line
    fig.text(0.0, top, title, ha="left", va="baseline", color=t.ink,
             fontsize=12.5, fontweight="bold")
    for i, ln in enumerate(lines):
        fig.text(0.0, top - (i + 1.15) * line, ln, ha="left", va="baseline",
                 color=t.ink_dim, fontsize=9.5)


plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "svg.fonttype": "none",
    "figure.dpi": 110,
})


# ------------------------------------------------------------------- source data

# Per-installation recall at threshold 0.3, checkpoint v2_combined/terramind-pv-epoch=39.
# Printed by `earthpv evaluate`; transcribed because that stage has no file output.
RECALL = {
    "buckets": ["250 - 500", "500 - 1000", ">= 1000"],
    "germany": [0.95, 0.84, 0.83],
    "punjab": [0.14, 0.16, 0.55],
    "punjab_germany_only": [None, None, 0.18],
}


def read_glint_by_size():
    path = ROOT / "results/glint_validation_pakistan/pakistan_stats_by_size.csv"
    rows = list(csv.DictReader(path.open()))
    return {
        "buckets": [r["bucket"] for r in rows],
        "n": [int(float(r["n"])) for r in rows],
        "detected": [float(r["pct_detected"]) for r in rows],
        "validated": [float(r["pct_validated"]) for r in rows],
    }


def read_estimator_totals():
    """Pull the six capacity estimates out of the atlas page's embedded JSON."""
    html = (ROOT / "results/pakistan_pv_estimator_atlas.html").read_text()
    m = re.search(r'id="pvdata"[^>]*>(.*?)</script>', html, flags=re.S)
    if not m:
        raise SystemExit("could not locate the atlas data block")
    return json.loads(m.group(1))["totals"]


def read_calibration_recall():
    """Measured per-size-bin model recall + credible band from the calibration table."""
    text = (ROOT / "configs/calibration/pakistan_candidate_precision.yaml").read_text()
    bins, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- label:"):
            cur = {"label": s.split(":", 1)[1].strip()}
            bins.append(cur)
        elif cur is not None and ":" in s and s.startswith(("recall", "n_candidates")):
            k, v = s.split(":", 1)
            try:
                cur[k.strip()] = float(v.strip())
            except ValueError:
                pass
    return [b for b in bins if "recall" in b]


# ----------------------------------------------------------------------- figures


def fig_recall_by_size(t: Theme):
    fig, ax = new_fig(t, 6.6, 3.1)
    b = RECALL["buckets"]
    x = range(len(b))
    w = 0.34
    gap = 0.012  # 2px surface gap between adjacent fills at this figure scale
    ax.bar([i - w / 2 - gap for i in x], RECALL["germany"], w, color=t.s1,
           label="Germany validation states", zorder=3)
    ax.bar([i + w / 2 + gap for i in x], RECALL["punjab"], w, color=t.s2,
           label="Punjab validation cells", zorder=3)
    for i, (g, p) in enumerate(zip(RECALL["germany"], RECALL["punjab"])):
        ax.text(i - w / 2 - gap, g + 0.03, f"{g:.2f}", ha="center", color=t.ink, fontsize=9)
        ax.text(i + w / 2 + gap, p + 0.03, f"{p:.2f}", ha="center", color=t.ink, fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{s} m$^2$" for s in b])
    ax.set_ylim(0, 1.30)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    style_axes(ax, t, ygrid=True)
    leg = ax.legend(frameon=False, loc="upper right", fontsize=9)
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "Detection recall holds in Germany, drops on Pakistani rooftops",
           "Share of real installations recovered by at least one candidate, threshold 0.3, "
           "checkpoint v2_combined")
    save(fig, t, "recall_by_size")


def fig_glint_by_size(t: Theme):
    d = read_glint_by_size()
    fig, ax = new_fig(t, 6.8, 3.3)
    x = range(len(d["buckets"]))
    w = 0.34
    gap = 0.012
    ax.bar([i - w / 2 - gap for i in x], d["detected"], w, color=t.s1,
           label="at least one glint spike", zorder=3)
    ax.bar([i + w / 2 + gap for i in x], d["validated"], w, color=t.s2,
           label="spikes fit one fixed panel pose", zorder=3)
    ax.axhline(8.7, color=t.s3, linewidth=2, zorder=4)
    ax.text(1.42, 62, "8.7% false-validation floor (green line),\n"
            "measured on 69 control roofs with no PV",
            fontsize=8.5, color=t.s3, ha="left", va="bottom")
    for i, (det, val) in enumerate(zip(d["detected"], d["validated"])):
        ax.text(i - w / 2 - gap, det + 1.4, f"{det:.0f}", ha="center", color=t.ink, fontsize=9)
        ax.text(i + w / 2 + gap, val + 1.4, f"{val:.0f}", ha="center", color=t.ink, fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{b}\nn={n}" for b, n in zip(d["buckets"], d["n"])], fontsize=8.5)
    ax.set_ylim(0, 96)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    style_axes(ax, t, ygrid=True)
    leg = ax.legend(frameon=False, loc="upper left", fontsize=9,
                    bbox_to_anchor=(-0.02, 1.02))
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "Solar glint confirms PV, and does so more often on bigger arrays",
           "500 OSM-confirmed Pakistani installations, two years of Sentinel-2, "
           "grouped by installation area (m$^2$)")
    save(fig, t, "glint_by_size")


ESTIMATORS = [
    # (label, index into the atlas totals array, CI key or None, scope)
    ("Detected, rooftop", 0, None, "roof"),
    ("Calibrated, rooftop (headline)", 1, None, "roof"),
    ("Expected, rooftop", 2, None, "roof"),
    ("Recall-corrected, rooftop", 3, "rcr_ci", "roof"),
    ("Calibrated, all PV", 4, "ct_ci", "all"),
    ("Recall-corrected, all PV", 5, "rc_ci", "all"),
]


def fig_capacity_estimators(t: Theme):
    tot = read_estimator_totals()
    fig, ax = new_fig(t, 7.6, 3.6)
    labels = [e[0] for e in ESTIMATORS]
    ends = [max(tot["m"][e[1]], tot[e[2]][1] if e[2] else 0) / 1000.0 for e in ESTIMATORS]
    ys = list(range(len(ESTIMATORS)))[::-1]
    for y, (label, idx, ci, scope) in zip(ys, ESTIMATORS):
        v = tot["m"][idx] / 1000.0
        col = t.s1 if scope == "roof" else t.s2
        ax.barh(y, v, height=0.46, color=col, zorder=3)
        end = v
        if ci:
            lo, hi = tot[ci][0] / 1000.0, tot[ci][1] / 1000.0
            ax.plot([lo, hi], [y, y], color=t.ink_dim, linewidth=1.5, zorder=4)
            for b in (lo, hi):
                ax.plot([b, b], [y - 0.12, y + 0.12], color=t.ink_dim, linewidth=1.5, zorder=4)
            end = hi
        ax.text(end + 0.45, y, f"{v:.1f} GWp", va="center", color=t.ink, fontsize=9.5)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=9.5)
    ax.set_ylim(-1.15, len(ESTIMATORS) - 0.4)
    ax.set_xlim(0, max(ends) * 1.22)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_xlabel("GWp", color=t.ink_dim, fontsize=9)
    style_axes(ax, t, xgrid=True)
    ax.grid(axis="x", color=t.rule, linewidth=0.8, zorder=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=t.s1),
               plt.Rectangle((0, 0), 1, 1, color=t.s2)]
    leg = ax.legend(handles, ["rooftop scope", "all PV, ground-mount farms included"],
                    frameon=False, loc="lower left", fontsize=9, ncol=2,
                    bbox_to_anchor=(0.0, -0.05), handlelength=1.1)
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "One model, six defensible answers to “how much PV?”",
           f"Pakistan, {tot['n_cells']:,} grid cells, {tot['kwp']} kWp/m$^2$, run {tot['run_date']}. "
           "Whiskers are 90% credible intervals.")
    save(fig, t, "capacity_estimators")


def fig_model_recall_bins(t: Theme):
    bins = read_calibration_recall()
    fig, ax = new_fig(t, 6.6, 3.0)
    labels = [b["label"].strip("'\"") for b in bins]
    vals = [b["recall"] * 100 for b in bins]
    los = [b.get("recall_lo", b["recall"]) * 100 for b in bins]
    his = [b.get("recall_hi", b["recall"]) * 100 for b in bins]
    x = list(range(len(bins)))
    ax.bar(x, vals, 0.52, color=t.s1, zorder=3)
    for i, (v, lo, hi) in enumerate(zip(vals, los, his)):
        ax.plot([i, i], [lo, hi], color=t.ink_dim, linewidth=1.5, zorder=4)
        ax.text(i, hi + 3, f"{v:.0f}%", ha="center", color=t.ink, fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s} m$^2$" for s in labels], fontsize=9)
    ax.set_ylim(0, 112)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    style_axes(ax, t, ygrid=True)
    titled(fig, t, "Measured model recall by installation size",
           "Share of a pre-pipeline OpenStreetMap reference matched by a candidate. "
           "This curve is what the recall correction divides by.")
    save(fig, t, "model_recall_bins")


INSTRUMENTS = [
    # row label, lo m2, hi m2, colour slot, note under the bar
    ("Aggregate density\nestimate", 20, 3_000_000, "s3",
     "capacity per building, cell and district; no per-object geometry"),
    ("Individual detection\nas polygons", 400, 3_000_000, "s1",
     "exported as leads, verified by mappers in OpenStreetMap"),
    ("Glint existence\nand pose check", 1_000, 3_000_000, "s2",
     "confirms one fixed panel plane; no discrimination below 500 m$^2$"),
]


def fig_size_spectrum(t: Theme):
    fig, ax = new_fig(t, 7.8, 3.2)
    ax.set_xscale("log")
    n = len(INSTRUMENTS)
    for i, (label, lo, hi, slot, note) in enumerate(INSTRUMENTS):
        y = n - 1 - i
        ax.barh(y, hi - lo, left=lo, height=0.30, color=getattr(t, slot), zorder=3)
        ax.text(lo * 1.18, y - 0.27, note, color=t.ink_dim, fontsize=8.5, va="top",
                zorder=6, bbox=dict(facecolor=t.surface, edgecolor="none", pad=1.5))
    ax.axvline(400, color=t.ink, linewidth=1.1, linestyle=(0, (4, 3)), zorder=5)
    ax.annotate("400 m$^2$, roughly four Sentinel-2 pixels:\n"
                "the floor for outlining an array at all",
                xy=(400, n - 0.62), xytext=(560, n - 0.30), fontsize=8.5, color=t.ink,
                ha="left", va="top",
                arrowprops=dict(arrowstyle="-", color=t.ink, linewidth=0.9))
    ax.set_xlim(20, 3_000_000)
    ax.set_ylim(-0.72, n - 0.20)
    ax.set_yticks(list(range(n))[::-1])
    ax.set_yticklabels([r[0] for r in INSTRUMENTS], fontsize=9.5)
    for lbl in ax.get_yticklabels():
        lbl.set_color(t.ink)
    ax.set_xticks([100, 1_000, 10_000, 100_000, 1_000_000])
    ax.set_xticklabels(["100 m$^2$\nsmall rooftop", "1,000 m$^2$\nlarge rooftop",
                        "1 ha\ncommercial", "10 ha", "100 ha\nutility plant"], fontsize=8.5)
    ax.grid(axis="x", color=t.rule, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    titled(fig, t, "Which instrument covers which installation size",
           "Sentinel-2 samples the ground at 10 m. Below 400 m$^2$ an array is a handful of "
           "mixed pixels, so it is counted rather than outlined.")
    save(fig, t, "size_spectrum")


def read_pose_points():
    """Fitted (tilt, azimuth) pairs, read out of the tracked pose survey page."""
    html = (ROOT / "results/glint_validation_pakistan/pv_pose_country2000.html").read_text()
    m = re.search(r'id="pvdata"[^>]*>(.*?)</script>', html, flags=re.S)
    if not m:
        raise SystemExit("could not locate the pose data block")
    return json.loads(m.group(1))


def fig_pv_pose(t: Theme):
    """Polar view of the fitted panel poses: tilt as radius, azimuth as angle."""
    import math

    d = read_pose_points()
    fig = plt.figure(figsize=(6.4, 5.6))
    fig.patch.set_facecolor(t.surface)
    ax = fig.add_subplot(projection="polar")
    ax.set_facecolor(t.surface)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    lo, hi = d["wedge"]
    ax.bar(x=math.radians((lo + hi) / 2), height=32, width=math.radians(hi - lo),
           bottom=0, color=t.rule, alpha=0.55, zorder=0, linewidth=0)
    ax.text(math.radians(335), 25, "never reachable\nfrom this orbit", ha="center",
            va="center", fontsize=8, color=t.ink_dim, zorder=6)

    groups = [("rooftop", "rooftop generator", t.s1), ("ground", "ground plant", t.s2)]
    for placement, label, col in groups:
        for mirrored, kw in ((False, dict(alpha=0.85, linewidths=0)),
                             (True, dict(facecolors="none", linewidths=0.8, alpha=0.55))):
            pts = [p for p in d["points"] if p["pl"] == placement and p["m"] is mirrored]
            if not pts:
                continue
            ax.scatter([math.radians(p["az"]) for p in pts], [p["t"] for p in pts],
                       s=[max(9, min(90, p["a"] * 1.1)) for p in pts],
                       color=col if not mirrored else None,
                       edgecolors=col if mirrored else "none",
                       label=f"{label}, mirrored" if mirrored else label,
                       zorder=3, **kw)

    ax.set_rlim(0, 32)
    ax.set_rticks([10, 20, 30])
    ax.set_rlabel_position(8)
    ax.set_yticklabels(["10", "20", "30 deg tilt"], fontsize=8, color=t.ink_dim)
    ax.set_xticks([math.radians(a) for a in range(0, 360, 45)])
    ax.set_xticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
                       fontsize=9, color=t.ink_dim)
    ax.grid(color=t.rule, linewidth=0.8)
    ax.spines["polar"].set_color(t.rule)
    leg = ax.legend(frameon=False, fontsize=8.5, loc="lower center",
                    bbox_to_anchor=(0.5, -0.20), ncol=2)
    for txt in leg.get_texts():
        txt.set_color(t.ink_dim)
    titled(fig, t, "How Pakistani solar panels are actually mounted",
           "Fitted tilt and azimuth for 290 installations whose Sentinel-2 glints agree on "
           "one fixed panel plane, out of 2,000 checked. Hollow points are the measured "
           "sample mirrored across due south.", width=76)
    save(fig, t, "pv_pose_polar")


# ----------------------------------------------------- hand-authored SVG diagrams

FLYWHEEL = """<svg xmlns="http://www.w3.org/2000/svg" width="900" height="480"
     viewBox="0 0 900 480" font-family="DejaVu Sans, system-ui, sans-serif">
  <defs>
    <marker id="a{sfx}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8"
            orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="{s1}"/>
    </marker>
    <marker id="b{sfx}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8"
            orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="{s2}"/>
    </marker>
  </defs>
  <rect width="900" height="480" rx="10" fill="{surface}"/>
  <text x="50" y="42" font-size="17" font-weight="600" fill="{ink}">The mapping flywheel</text>
  <text x="50" y="64" font-size="12" fill="{dim}">Every turn leaves the training data larger, cleaner and more local.</text>

  <g stroke="{s1}" stroke-width="2" fill="none" marker-end="url(#a{sfx})">
    <path d="M432,148 H466"/>
    <path d="M660,196 V266"/>
  </g>
  <g stroke="{s2}" stroke-width="2" fill="none" marker-end="url(#b{sfx})">
    <path d="M468,330 H434"/>
    <path d="M240,266 V200"/>
  </g>

  <rect x="50" y="102" width="382" height="94" rx="8" fill="{card}" stroke="{rule}"/>
  <text x="72" y="132" font-size="13" font-weight="600" fill="{ink}">1. OpenStreetMap labels</text>
  <text x="72" y="154" font-size="11" fill="{dim}">Solar polygons drawn by mappers, pulled live</text>
  <text x="72" y="172" font-size="11" fill="{dim}">through Overpass or Overture Maps.</text>

  <rect x="468" y="102" width="382" height="94" rx="8" fill="{card}" stroke="{rule}"/>
  <text x="490" y="132" font-size="13" font-weight="600" fill="{ink}">2. Fine-tune TerraMind on Sentinel-2</text>
  <text x="490" y="154" font-size="11" fill="{dim}">Free 10 m imagery, worldwide, every five days.</text>
  <text x="490" y="172" font-size="11" fill="{dim}">No commercial tile licence in the way.</text>

  <rect x="468" y="266" width="382" height="128" rx="8" fill="{card}" stroke="{rule}"/>
  <text x="490" y="296" font-size="13" font-weight="600" fill="{ink}">3. Rank candidates, publish leads</text>
  <text x="490" y="318" font-size="11" fill="{dim}">Recall-first. A building prior, glint corroboration,</text>
  <text x="490" y="336" font-size="11" fill="{dim}">a pre-boom epoch check and a vegetation veto</text>
  <text x="490" y="354" font-size="11" fill="{dim}">reorder the queue; a MapRoulette challenge</text>
  <text x="490" y="372" font-size="11" fill="{dim}">carries it to mappers.</text>

  <rect x="50" y="266" width="382" height="128" rx="8" fill="{card}" stroke="{rule}"/>
  <text x="72" y="296" font-size="13" font-weight="600" fill="{ink}">4. People verify what the model found</text>
  <text x="72" y="318" font-size="11" fill="{dim}">Local mappers open each lead in the OpenStreetMap</text>
  <text x="72" y="336" font-size="11" fill="{dim}">editor, check it against Esri, Bing and Mapbox</text>
  <text x="72" y="354" font-size="11" fill="{dim}">imagery, then map it properly with local context.</text>
  <text x="72" y="376" font-size="11" fill="{s2}">Verified installations become the next training labels.</text>

  <text x="676" y="236" font-size="11" fill="{s1}">detections out</text>
  <text x="256" y="236" font-size="11" fill="{s2}">verified labels back in</text>
  <text x="50" y="440" font-size="11" fill="{dim}">Only free and openly licensed imagery reaches the model. The high-resolution</text>
  <text x="50" y="458" font-size="11" fill="{dim}">layers are used by people, inside the editor, where their licences allow it.</text>
</svg>
"""

PIPELINE_STRIP = """<svg xmlns="http://www.w3.org/2000/svg" width="900" height="214"
     viewBox="0 0 900 214" font-family="DejaVu Sans, system-ui, sans-serif">
  <rect width="900" height="214" rx="10" fill="{surface}"/>
  <text x="30" y="34" font-size="14" font-weight="600" fill="{ink}">Two products from one model</text>

  <rect x="30" y="56" width="180" height="60" rx="7" fill="{card}" stroke="{rule}"/>
  <text x="48" y="82" font-size="12" font-weight="600" fill="{ink}">Sentinel-2 L2A</text>
  <text x="48" y="100" font-size="10.5" fill="{dim}">dry-season composites</text>

  <rect x="238" y="56" width="180" height="60" rx="7" fill="{card}" stroke="{rule}"/>
  <text x="256" y="82" font-size="12" font-weight="600" fill="{ink}">TerraMind-tiny</text>
  <text x="256" y="100" font-size="10.5" fill="{dim}">probability raster</text>

  <rect x="446" y="26" width="204" height="60" rx="7" fill="{card}" stroke="{s1}"/>
  <text x="464" y="52" font-size="12" font-weight="600" fill="{s1}">Leads product</text>
  <text x="464" y="70" font-size="10.5" fill="{dim}">polygons for human review</text>

  <rect x="446" y="116" width="204" height="60" rx="7" fill="{card}" stroke="{s3}"/>
  <text x="464" y="142" font-size="12" font-weight="600" fill="{s3}">Capacity product</text>
  <text x="464" y="160" font-size="10.5" fill="{dim}">MWp per building and cell</text>

  <rect x="678" y="26" width="192" height="60" rx="7" fill="{card}" stroke="{rule}"/>
  <text x="696" y="52" font-size="12" font-weight="600" fill="{ink}">OpenStreetMap</text>
  <text x="696" y="70" font-size="10.5" fill="{dim}">MapRoulette challenge</text>

  <rect x="678" y="116" width="192" height="60" rx="7" fill="{card}" stroke="{rule}"/>
  <text x="696" y="142" font-size="12" font-weight="600" fill="{ink}">PyPSA-Earth</text>
  <text x="696" y="160" font-size="10.5" fill="{dim}">0.1 degree grid CSV</text>

  <g stroke="{dim}" stroke-width="1.6" fill="none">
    <path d="M210,86 H236"/>
    <path d="M418,86 H432 V56 H444"/>
    <path d="M418,86 H432 V146 H444"/>
  </g>
  <g stroke="{s1}" stroke-width="1.6" fill="none"><path d="M650,56 H676"/></g>
  <g stroke="{s3}" stroke-width="1.6" fill="none"><path d="M650,146 H676"/></g>

  <text x="30" y="200" font-size="10.5" fill="{dim}">False positives are useful on the top path and forbidden on the bottom one, so only the bottom path is precision-calibrated.</text>
</svg>
"""


def write_svg_pair(template: str, stem: str):
    for t in THEMES:
        card = "#ffffff" if t.name == "light" else "#232321"
        svg = template.format(surface=t.surface, ink=t.ink, dim=t.ink_dim, rule=t.rule,
                              card=card, s1=t.s1, s2=t.s2, s3=t.s3, sfx=t.name)
        suffix = ".svg" if t.name == "light" else ".dark.svg"
        path = OUT / f"{stem}{suffix}"
        OUT.mkdir(parents=True, exist_ok=True)
        path.write_text(svg)
        print(f"  wrote {path.relative_to(ROOT)}")


# ------------------------------------------------------------------- raster crop


def crop_hero_map():
    """Trim the whitespace margins off the scientific capacity map for embedding."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        print("  pillow not installed, skipping hero crop")
        return
    Image.MAX_IMAGE_PIXELS = None
    src = ROOT / "results/pakistan_pv_density_scientific.png"
    if not src.exists():
        print(f"  {src.relative_to(ROOT)} missing, skipping hero crop")
        return
    im = Image.open(src).convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
    bbox = ImageChops.difference(im, bg).getbbox()
    if bbox:
        pad = 24
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad))
        im = im.crop(bbox)
    im.thumbnail((2200, 2200), Image.LANCZOS)
    dst = OUT / "pakistan_capacity_map.png"
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(dst, optimize=True)
    print(f"  wrote {dst.relative_to(ROOT)} ({im.width}x{im.height})")


# Interactive pages the site embeds in an iframe. MkDocs only serves what lives
# under `docs/`, so the tracked originals in `results/` are copied in here.
INTERACTIVE = [
    ("results/pakistan_pv_estimator_atlas.html", "pakistan_capacity_atlas.html"),
    ("results/glint_validation_pakistan/pv_pose_country2000.html", "pakistan_pv_pose.html"),
    ("results/pakistan_pv_density/pakistan_pv_density_map.html", "pakistan_density_map.html"),
]


def sync_interactive():
    dst_dir = ROOT / "docs" / "assets" / "interactive"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src_rel, name in INTERACTIVE:
        src = ROOT / src_rel
        if not src.exists():
            print(f"  {src_rel} missing, skipping")
            continue
        (dst_dir / name).write_bytes(src.read_bytes())
        print(f"  wrote docs/assets/interactive/{name}")


LOGO_SRC = ROOT / "docs" / "assets" / "earthpv-logo.png"
BRAND_NAVY = (18, 41, 63)


def derive_logo():
    """Trim and recolour the source logo into the variants the site and README need.

    The source is a black mark on transparency, off-centre with wide margins. Black is
    invisible on the navy header bar and on a dark README, so a white variant is
    generated from the same alpha channel; nothing is redrawn.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  pillow not installed, skipping logo derivation")
        return
    if not LOGO_SRC.exists():
        print(f"  {LOGO_SRC.relative_to(ROOT)} missing, skipping logo derivation")
        return
    OUT.mkdir(parents=True, exist_ok=True)

    src = Image.open(LOGO_SRC).convert("RGBA")
    alpha = src.split()[-1]
    box = alpha.getbbox()
    mark = src.crop(box)

    # Square canvas with a small even margin, so the mark scales predictably wherever
    # it is placed and never sits off-centre.
    side = int(max(mark.size) * 1.08)
    for name, rgb in (("earthpv-logo-mark", (0, 0, 0)), ("earthpv-logo-mark-white", (255, 255, 255))):
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        tinted = Image.new("RGBA", mark.size, rgb + (0,))
        tinted.putalpha(mark.split()[-1])
        canvas.paste(tinted, ((side - mark.width) // 2, (side - mark.height) // 2), tinted)
        out = canvas.resize((512, 512), Image.LANCZOS)
        out.save(OUT / f"{name}.png", optimize=True)
        print(f"  wrote docs/assets/figures/{name}.png")

    # Favicon: the white mark on the brand navy, rounded, at browser-tab scale.
    size = 256
    fav = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    plate = Image.new("RGBA", (size, size), BRAND_NAVY + (255,))
    rounded = Image.new("L", (size, size), 0)
    ImageDraw.Draw(rounded).rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=255)
    fav.paste(plate, (0, 0), rounded)
    white = Image.open(OUT / "earthpv-logo-mark-white.png").resize(
        (int(size * 0.74), int(size * 0.74)), Image.LANCZOS)
    fav.paste(white, ((size - white.width) // 2, (size - white.height) // 2), white)
    fav.save(OUT / "favicon.png", optimize=True)
    print("  wrote docs/assets/figures/favicon.png")


def main():
    print("charts")
    for t in THEMES:
        fig_recall_by_size(t)
        fig_glint_by_size(t)
        fig_capacity_estimators(t)
        fig_model_recall_bins(t)
        fig_size_spectrum(t)
        fig_pv_pose(t)
    print("diagrams")
    write_svg_pair(FLYWHEEL, "osm_ai_flywheel")
    write_svg_pair(PIPELINE_STRIP, "two_products")
    print("logo")
    derive_logo()
    print("rasters")
    crop_hero_map()
    print("interactive pages")
    sync_interactive()


if __name__ == "__main__":
    main()
