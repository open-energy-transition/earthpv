"""Is there sub-pixel diversity between Sentinel-2 acquisitions to fuse?

Google's Open Buildings 2.5D Temporal reaches an effective ~4 m from nominal 10 m Sentinel-2
by fusing up to 32 acquisitions whose viewpoints differ slightly. Multi-frame fusion works
only if the frames sample the ground on DIFFERENT sub-pixel grids; if every acquisition lands
on the same phase, N frames carry no more high-frequency information than one.

That is measurable before building anything, and it is the precondition worth checking first,
because this project's SNR budget (2026-09-19) found signal proportional to fill fraction and
declared it out of reach: "no amount of processing changes f -- it is pixel size against
array size". Multi-frame fusion is the one exception, and it stands or falls on this.

The subtlety: Sentinel-2 L2A is DELIVERED on a fixed MGRS grid, so ESA has already resampled
every acquisition onto the same nominal pixels. The exploitable diversity is therefore
residual geolocation error, a few metres and varying per acquisition and orbit, which has to
be estimated rather than read from metadata. That is what this measures, by phase-correlating
each frame against the stack's own reference.

Reuses `pv_step_signal._phase_shift`, the same estimator the step detector uses to guard
co-registration.

    pixi run python scripts/measure_subpixel_shifts.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from earthpv.preprocess import load_scene_stack
from earthpv.roofclf import discover_quadrats

log = logging.getLogger("subpixel_shifts")
B08 = 6          # native 10 m, sharp, good contrast on built-up land
MIN_VALID = 0.80


def _load_phase_shift():
    """Import `_phase_shift` from the step-signal script without running it."""
    p = Path("scripts/pv_step_signal.py")
    spec = importlib.util.spec_from_file_location("pv_step_signal", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._phase_shift


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--out", type=Path, default=Path("results/subpixel_shifts.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    phase_shift = _load_phase_shift()

    rows = []
    for stem in sorted(discover_quadrats(args.labels_dir)):
        loaded = load_scene_stack(args.composites, stem)
        if loaded is None:
            continue
        stack, _, _ = loaded
        band = stack[:, B08]                      # (time, y, x)
        valid = np.isfinite(band).mean(axis=(1, 2))
        use = np.flatnonzero(valid >= MIN_VALID)
        if len(use) < 4:
            continue
        # Reference is the most complete frame, not the mean, so the comparison is
        # frame-to-frame rather than frame-to-a-blurred-average.
        ref_i = use[int(np.argmax(valid[use]))]
        ref = band[ref_i]
        for i in use:
            if i == ref_i:
                continue
            dy, dx = phase_shift(ref, band[i])
            # A whole-pixel jump is a co-registration failure, not sub-pixel diversity.
            if abs(dy) > 3 or abs(dx) > 3:
                continue
            rows.append({"quadrat": stem, "frame": int(i), "dy": dy, "dx": dx,
                         "mag": float(np.hypot(dy, dx))})
        log.info("%-38s %d frames vs reference", stem, sum(r["quadrat"] == stem for r in rows))

    d = pd.DataFrame(rows)
    d.to_csv("results/subpixel_shifts_frames.csv", index=False)
    # Fractional phase: where inside a pixel each frame lands. Diversity here is what
    # multi-frame fusion consumes; all-zero means every frame samples the same phase.
    frac_y = np.mod(d.dy, 1.0)
    frac_x = np.mod(d.dx, 1.0)
    # Distance of each frame's phase from the nearest whole pixel, in [0, 0.5].
    off_y = np.minimum(frac_y, 1 - frac_y)
    off_x = np.minimum(frac_x, 1 - frac_x)
    out = {
        "n_pairs": int(len(d)), "n_quadrats": int(d.quadrat.nunique()),
        "median_shift_px": round(float(d.mag.median()), 3),
        "p90_shift_px": round(float(d.mag.quantile(0.9)), 3),
        "median_shift_m": round(float(d.mag.median() * 10), 2),
        "share_above_0p2px": round(float((d.mag > 0.2).mean()), 3),
        "share_above_0p5px": round(float((d.mag > 0.5).mean()), 3),
        "median_subpixel_offset_y": round(float(off_y.median()), 3),
        "median_subpixel_offset_x": round(float(off_x.median()), 3),
        # A uniform phase spread would put this near 0.25; near 0 means frames pile up on
        # the same grid and there is nothing extra to fuse.
        "phase_uniformity_target": 0.25,
    }
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    print("\nper-quadrat median shift (px):")
    print(d.groupby("quadrat").mag.median().sort_values(ascending=False).head(10).round(3).to_string())


if __name__ == "__main__":
    main()
