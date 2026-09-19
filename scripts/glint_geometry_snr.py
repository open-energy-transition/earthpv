"""Does a near-specular viewing geometry raise the per-scene PV signal-to-noise?

A glass-fronted panel is partly specular, so on a date when the sun-panel-sensor geometry
approaches the mirror condition it should be brighter relative to the roof around it than on
any other date. The project already uses that as a per-target CORROBORATION signal
(`glint.py`); what it has never measured is whether it raises the DETECTION contrast that
`roofclf` depends on, and for how many observations.

This measures it directly, with no classifier in the way. For each saved quadrat scene stack:

  * per scene, the specular misalignment for each of the 192 poses fitted from real
    Pakistani installations (`results/glint_validation_pakistan/pv_pose_pakistan_data.json`),
    using that scene's own sun and view angles from STAC;
  * per scene, d-prime between pixels inside mapped PV and PV-free roof pixels.

Then the question is whether d-prime rises as the geometry approaches specular. The SNR
budget measured on 2026-09-19 gives the scale to beat: the whole panel-minus-roof contrast
is 1.34 background sd at full cover, and a typical roof yields 0.41 sd.

    pixi run python scripts/glint_geometry_snr.py --aoi pakistan
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import rasterio.features

from earthpv.glint import misalignment_deg
from earthpv.imagery import _es_catalog
from earthpv.preprocess import load_scene_stack
from earthpv.roofclf import discover_quadrats, load_quadrat

log = logging.getLogger("glint_geometry_snr")
GLINT_TOL_DEG = 10.0     # a panel within this of the mirror condition can glint
VIS_NIR = [0, 1, 2, 6]   # B02 B03 B04 B08


def scene_geometry(bbox, date_range) -> dict:
    """Sun and view angles per solar day, from STAC metadata only (no pixels)."""
    items = _es_catalog().search(
        collections=["sentinel-2-l2a"], bbox=bbox,
        datetime=f"{date_range[0]}/{date_range[1]}").items()
    out = {}
    for it in items:
        p = it.properties
        try:
            out[str(np.datetime64(it.datetime.date()))] = {
                "sun_zen": 90.0 - float(p["view:sun_elevation"]),
                "sun_az": float(p["view:sun_azimuth"]),
                "view_zen": float(p.get("view:incidence_angle", 5.0)),
                "view_az": float(p.get("view:azimuth", 0.0)),
            }
        except (KeyError, TypeError):
            continue
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", default="pakistan")
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--iso3", default="PAK")
    ap.add_argument("--poses", type=Path,
                    default=Path("results/glint_validation_pakistan/pv_pose_pakistan_data.json"))
    ap.add_argument("--window", default="2025-11-01:2026-03-15")
    ap.add_argument("--out", type=Path, default=Path("results/glint_geometry_snr.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    poses = json.loads(args.poses.read_text())
    tilt = np.array([p["tilt"] for p in poses], dtype=float)
    paz = np.array([p["az"] for p in poses], dtype=float)
    log.info("%d fitted poses: median tilt %.1f deg, median azimuth %.1f deg",
             len(tilt), np.median(tilt), np.median(paz))
    window = tuple(args.window.split(":"))

    from earthpv import overture
    from earthpv.buildings import fetch_vida_buildings
    con = overture.connect()

    rows = []
    for stem in sorted(discover_quadrats(args.labels_dir)):
        loaded = load_scene_stack(args.composites, stem)
        if loaded is None:
            continue
        stack, transform, crs = loaded
        npz = np.load(args.composites / "stacks" / f"{stem}.npz", allow_pickle=False)
        dates = [str(d) for d in npz["dates"]]
        boundary, pv = load_quadrat(stem, args.labels_dir)
        if pv.empty:
            continue
        shape = stack.shape[-2:]
        pv_m = rasterio.features.rasterize(
            ((g, 1) for g in pv.to_crs(crs).geometry), out_shape=shape,
            transform=transform, fill=0, dtype="uint8").astype(bool)
        bu = fetch_vida_buildings(boundary.bounds, args.iso3, con=con)
        if bu.empty or pv_m.sum() < 20:
            continue
        roof_m = rasterio.features.rasterize(
            ((g, 1) for g in bu.to_crs(crs).geometry), out_shape=shape,
            transform=transform, fill=0, dtype="uint8").astype(bool)
        ctrl_m = roof_m & ~pv_m
        if ctrl_m.sum() < 20:
            continue
        geom = scene_geometry(boundary.bounds, window)

        for i, d in enumerate(dates):
            g = geom.get(d)
            if g is None:
                continue
            mis = misalignment_deg(g["sun_zen"], g["sun_az"], g["view_zen"], g["view_az"],
                                   tilt, paz)
            sc = stack[i]
            vis = np.nanmean(sc[VIS_NIR], axis=0)
            a, c = vis[pv_m], vis[ctrl_m]
            a, c = a[np.isfinite(a)], c[np.isfinite(c)]
            if len(a) < 20 or len(c) < 20:
                continue
            s = np.sqrt(0.5 * (np.var(a) + np.var(c)))
            rows.append({
                "quadrat": stem, "date": d,
                "min_misalign_deg": float(np.min(mis)),
                "median_misalign_deg": float(np.median(mis)),
                "frac_poses_glinting": float(np.mean(mis < GLINT_TOL_DEG)),
                "sun_zen": g["sun_zen"], "sun_az": g["sun_az"],
                "dprime": float((np.mean(a) - np.mean(c)) / s),
                "pv_mean": float(np.mean(a)), "roof_mean": float(np.mean(c)),
                "n_pv_px": int(len(a)),
            })
        log.info("%-38s %d scenes scored", stem, sum(r["quadrat"] == stem for r in rows))

    import pandas as pd
    from scipy import stats
    df = pd.DataFrame(rows)
    df.to_csv("results/glint_geometry_snr_scenes.csv", index=False)
    out = {"n_scenes": int(len(df)), "n_quadrats": int(df.quadrat.nunique()),
           "glint_tol_deg": GLINT_TOL_DEG,
           "frac_scenes_with_any_pose_glinting": float((df.frac_poses_glinting > 0).mean()),
           "median_min_misalign_deg": round(float(df.min_misalign_deg.median()), 2)}
    # Signed d-prime is negative (PV is darker). A glint should push it toward zero or above.
    for col in ("min_misalign_deg", "frac_poses_glinting"):
        rho, p = stats.spearmanr(df[col], df.dprime)
        out[f"spearman_dprime_vs_{col}"] = round(float(rho), 3)
        out[f"p_dprime_vs_{col}"] = round(float(p), 4)
    near = df[df.min_misalign_deg <= df.min_misalign_deg.quantile(0.25)]
    far = df[df.min_misalign_deg >= df.min_misalign_deg.quantile(0.75)]
    out["dprime_nearest_quartile"] = round(float(near.dprime.median()), 3)
    out["dprime_farthest_quartile"] = round(float(far.dprime.median()), 3)
    out["misalign_nearest_quartile"] = round(float(near.min_misalign_deg.median()), 2)
    out["misalign_farthest_quartile"] = round(float(far.min_misalign_deg.median()), 2)
    args.out.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
