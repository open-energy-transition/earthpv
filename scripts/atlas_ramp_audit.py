"""Measure and preview the evidence atlas's capacity ramp against its own cell distribution.

A choropleth ramp cannot be judged from swatches. What matters is what the AOI's real cells
look like drawn at their real spatial distribution, against the land and map-background
colours they sit on, and whether neighbouring percentiles of the actual value distribution
are far enough apart in a perceptual space to be told apart.

This does both: it scores a ramp on the metrics `pv_evidence_atlas.html` commits to in its
own comment, and renders candidates side by side onto the real grid.

    audit    score the shipped dark and light ramps (and any candidates below)
    preview  render them onto the AOI's cells as a PNG

Metrics, all in OKLab:
  pctStep   mean distance between the colours of neighbouring percentiles of the lit-cell
            value distribution. The headline "can you tell two similar cells apart" number.
  p10       the same at the 10th percentile of steps, i.e. the worst regions of the ramp.
  p50-90    distance across the crowded middle, where most of the country sits.
  p90-100   distance across the sparse top decade, which should stay large enough that the
            biggest cities still read as exceptional.
  dLmin     smallest adjacent lightness step; keeps the ramp an ordered scale in greyscale.
  dim|land  distance from the ramp's dimmest stop to the unlit land colour. This is the
            lit-versus-unlit contrast and it is easy to lose.
  cvd       pctStep under simulated deuteranopia.

Usage:
    .pixi/envs/default/bin/python scripts/atlas_ramp_audit.py audit
    .pixi/envs/default/bin/python scripts/atlas_ramp_audit.py preview --out /tmp/ramp.png
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "docs" / "assets" / "interactive" / "pakistan_evidence_atlas.html"
TEMPLATE = ROOT / "src" / "earthpv" / "templates" / "pv_evidence_atlas.html"
# straight from the template's :root blocks
LAND_DARK, MAPBG_DARK = "#241f16", "#0c0a07"
LAND_LIGHT, MAPBG_LIGHT = "#e6dcc7", "#efe8d8"
VMIN = 0.02


# ------------------------------------------------------------------ colour
def hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float) / 255.0


def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])
_LMS = np.array([[0.31399022, 0.63951294, 0.04649755],
                 [0.15537241, 0.75789446, 0.08670142],
                 [0.01775239, 0.10944209, 0.87256922]])


def rgb2oklab(rgb):
    return np.cbrt(srgb_to_linear(np.asarray(rgb, float)) @ _M1.T) @ _M2.T


def deuteranope(rgb):
    lms = srgb_to_linear(rgb) @ _LMS.T
    out = lms.copy()
    out[:, 1] = 0.9513092 * lms[:, 0] + 0.04866992 * lms[:, 2]
    return linear_to_srgb(np.clip(out @ np.linalg.inv(_LMS).T, 0, 1))


# ------------------------------------------------------------------ data + ramp
def load_cells():
    d = json.loads(re.search(r'<script id="pv" type="application/json">(.*?)</script>',
                             ATLAS.read_text(), re.S).group(1))
    return d


def shipped_ramps():
    """The two ramps currently in the TEMPLATE, so the audit tracks the source of truth."""
    s = TEMPLATE.read_text()
    out = {}
    for name in ("RAMP_DARK", "RAMP_LIGHT"):
        m = re.search(rf'const {name} = \[(.*?)\];', s, re.S)
        out[name] = re.findall(r'#[0-9a-fA-F]{6}', m.group(1))
    return out["RAMP_DARK"], out["RAMP_LIGHT"]


def t_of(v, vmax):
    return (np.log(np.maximum(v, VMIN)) - np.log(VMIN)) / (np.log(vmax) - np.log(VMIN))


def ramp_color(t, stops_rgb):
    """The template's own piecewise-linear sRGB interpolation, reproduced exactly."""
    t = np.clip(np.asarray(t, float), 0, 1)
    n = len(stops_rgb) - 1
    f = t * n
    i = np.minimum(n - 1, np.floor(f).astype(int))
    r = (f - i)[:, None]
    a, b = stops_rgb[i], stops_rgb[i + 1]
    return a + (b - a) * r


def score(stops, values, land):
    rgb = np.array([hex2rgb(h) for h in stops])
    vmax = max(8.0, values.max())
    qs = np.percentile(values, np.linspace(0, 100, 101))
    lab = rgb2oklab(ramp_color(t_of(qs, vmax), rgb))
    steps = np.linalg.norm(np.diff(lab, axis=0), axis=1)
    marks = rgb2oklab(ramp_color(t_of(np.percentile(values, [0, 50, 90, 100]), vmax), rgb))
    slab = rgb2oklab(rgb)
    dL = np.diff(slab[:, 0])
    cvd = np.linalg.norm(np.diff(rgb2oklab(deuteranope(
        ramp_color(t_of(qs, vmax), rgb))), axis=0), axis=1)
    return {
        "pctStep": steps.mean(), "p10": np.percentile(steps, 10),
        "p0-50": np.linalg.norm(marks[1] - marks[0]),
        "p50-90": np.linalg.norm(marks[2] - marks[1]),
        "p90-100": np.linalg.norm(marks[3] - marks[2]),
        "dLmin": np.abs(dL).min(),
        "mono": bool(np.all(dL > 0) or np.all(dL < 0)),
        "dim|land": float(np.linalg.norm(slab[0] - rgb2oklab(hex2rgb(land)))),
        "cvd": cvd.mean(),
    }


def cmd_audit(args):
    d = load_cells()
    v = np.array([c[3] for c in d["cells"]], float)
    v = v[v > 0]
    dark, light = shipped_ramps()
    print(f"{len(v)} lit cells, {v.min():.3f}-{v.max():.1f} MWp\n")
    hdr = (f"{'ramp':16s} {'pctStep':>8s} {'p10':>7s} {'p0-50':>6s} {'p50-90':>7s} "
           f"{'p90-100':>8s} {'dLmin':>6s} {'dim|land':>8s} {'cvd':>7s} mono")
    print(hdr)
    print("-" * len(hdr))
    for name, stops, land in (("shipped dark", dark, LAND_DARK),
                              ("shipped light", light, LAND_LIGHT)):
        s = score(stops, v, land)
        print(f"{name:16s} {s['pctStep']:8.4f} {s['p10']:7.4f} {s['p0-50']:6.3f} "
              f"{s['p50-90']:7.3f} {s['p90-100']:8.3f} {s['dLmin']:6.3f} "
              f"{s['dim|land']:8.3f} {s['cvd']:7.4f} {'y' if s['mono'] else 'NO'}")
        print(f"{'':16s} {stops}")


def cmd_preview(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    d = load_cells()
    dark, light = shipped_ramps()
    stops = light if args.light else dark
    land = LAND_LIGHT if args.light else LAND_DARK
    mapbg = MAPBG_LIGHT if args.light else MAPBG_DARK
    cells = np.array([[c[0], c[1], c[3]] for c in d["cells"]], float)
    b0, b1, b2, b3 = d["bounds"]
    k = np.cos(np.radians((b1 + b3) / 2))
    v = cells[:, 2]
    t = np.where(v > 0, t_of(v, max(8.0, v.max())), -1)
    rgb = np.array([hex2rgb(h) for h in stops])
    cols = ramp_color(np.clip(t, 0, 1), rgb)

    fig, ax = plt.subplots(figsize=(6.4, 8.0), facecolor=mapbg)
    ax.set_facecolor(mapbg)
    for i in range(len(cells)):
        c = cols[i] if t[i] >= 0 else hex2rgb(land)
        ax.add_patch(Rectangle((cells[i, 0], cells[i, 1]), 0.1, 0.1,
                               facecolor=tuple(np.clip(c, 0, 1)), edgecolor="none"))
    strip = ramp_color(np.linspace(0, 1, 256), rgb).reshape(1, 256, 3)
    ax.imshow(np.clip(strip, 0, 1), extent=[b0, b2, b1 - 1.15, b1 - 0.35], aspect="auto")
    ax.set_xlim(b0, b2)
    ax.set_ylim(b1 - 1.3, b3)
    ax.set_aspect(1 / k)
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.tight_layout()
    fig.savefig(args.out, dpi=90, facecolor=mapbg)
    print("wrote", args.out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit").set_defaults(fn=cmd_audit)
    p = sub.add_parser("preview")
    p.add_argument("--out", default="ramp_preview.png")
    p.add_argument("--light", action="store_true")
    p.set_defaults(fn=cmd_preview)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
