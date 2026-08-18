"""Composition breakdown of the evidence atlas's headline "Best estimate" figure --
which data sources and methods it is actually built from, and in what proportion.

Not a new measurement: reads the `uncertainty.components` breakdown the published
atlas (`docs/assets/interactive/pakistan_evidence_atlas.html`) already embeds
(`atlas.py::_evidence_uncertainty`, whose docstring asserts these components sum
to the published total) and presents it as its own page, since the atlas itself
never renders this breakdown as a standalone view -- only as an internal
uncertainty-composition detail.

Every component is tagged with which of four methods produced it:
  - OSM (hand-mapped): human-mapped installations the model had not already found,
    plus a per-cell floor correction (both converted at the module/land kWp priors).
  - TerraMind segmentation: the fine-tuned pixel segmentation model, for ground-mount
    everywhere (roofclf has no footprint to classify there) and >= 400 m2 rooftop
    outside the density-calibrated domain.
  - roofclf alone: the per-building classifier's own density-calibrated coverage-ratio
    and recall-corrected
    estimate, for >= 400 m2 rooftop inside the calibrated domain (replacing
    segmentation there) and the sub-400 m2 "central" estimate.
  - roofclf + SPPI: the classifier's AND-gate agreement with the zero-training SPPI
    spectral index, used only for the out-of-domain sub-400 m2 extrapolation inside
    Best (the in-domain AND-gate, `small_low`, feeds Verified instead -- shown here
    for context, not summed into Best).

Usage:
    .pixi/envs/default/bin/python scripts/build_atlas_composition.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS_HTML = ROOT / "docs/assets/interactive/pakistan_evidence_atlas.html"
OUT = ROOT / "results/pakistan_atlas_composition.html"
TEMPLATE = ROOT / "src/earthpv/templates/atlas_composition.html"

METHOD = {
    "osm_unmatched_roof": "osm", "osm_unmatched_ground": "osm", "floor_offset": "osm",
    "seg_roof_outdomain": "seg", "seg_ground": "seg",
    "ge400_roof": "roofclf", "small_central": "roofclf",
    "small_outdomain": "sppi",
}
VERIFIED_METHOD = {"osm_roof": "osm", "osm_ground": "osm", "small_low": "sppi"}

LABEL = {
    "osm_unmatched_roof": "OSM hand-mapped - rooftop (not already found by the model)",
    "osm_unmatched_ground": "OSM hand-mapped - ground-mount (not already found by the model)",
    "floor_offset": "OSM floor correction (cells where the model fell short of hand-mapped OSM)",
    "seg_roof_outdomain": "TerraMind segmentation - rooftop, outside the calibrated domain",
    "seg_ground": "TerraMind segmentation - ground-mount (every cell; roofclf has no footprint there)",
    "ge400_roof": "roofclf - ≥ 400 m² rooftop, replacing segmentation inside the calibrated domain",
    "small_central": "roofclf alone - sub-400 m² rooftop, coverage ratio and recall, density-calibrated",
    "small_outdomain": "roofclf + SPPI agreement - sub-400 m², extrapolated outside the calibrated domain",
    "osm_roof": "OSM hand-mapped - rooftop (all of it, matched or not)",
    "osm_ground": "OSM hand-mapped - ground-mount (all of it, matched or not)",
    "small_low": "roofclf + SPPI agreement - sub-400 m², inside the calibrated domain",
}

METHOD_META = {
    "osm": {"name": "OSM (hand-mapped)", "desc": "Human-mapped installations from OpenStreetMap solar tagging."},
    "seg": {"name": "TerraMind segmentation", "desc": "The fine-tuned pixel-segmentation model, outlining panels directly."},
    "roofclf": {"name": "roofclf (alone)", "desc": "Per-building classifier, density-calibrated coverage ratio and recall correction, no spectral cross-check."},
    "sppi": {"name": "roofclf + SPPI", "desc": "roofclf AND the zero-training SPPI spectral index agreeing - a stricter, cross-validated signal."},
}

# Fixed categorical order (never cycled): most-directly-measured to
# least-direct, matching this project's own trust ordering (hand-mapped ground
# truth, then pixel model, then tabular classifier alone, then a
# cross-validated-but-extrapolated signal).
METHOD_ORDER = ["osm", "seg", "roofclf", "sppi"]

COLORS = {
    "osm":     {"dark": "#399260", "light": "#227a45"},
    "seg":     {"dark": "#3f7fd6", "light": "#2a68c4"},
    "roofclf": {"dark": "#b87d1e", "light": "#96620a"},
    "sppi":    {"dark": "#9c6fd1", "light": "#7550b0"},
}


def load_totals() -> dict:
    html = ATLAS_HTML.read_text()
    start_tag = '<script id="pv" type="application/json">'
    i = html.find(start_tag) + len(start_tag)
    j = html.find("</script>", i)
    if i < 0 or j < 0:
        raise RuntimeError(f"could not find embedded #pv JSON in {ATLAS_HTML}")
    return json.loads(html[i:j])["totals"]


def build_rows(totals: dict) -> tuple[list[dict], list[dict]]:
    u = totals["uncertainty"]
    comp = dict(u["components"])
    floor_offset = u["best_floor_offset_mwp"]
    best_total = totals["mwp_best"]
    verified_total = totals["mwp_verified"]

    best_keys = ["osm_unmatched_roof", "osm_unmatched_ground", "floor_offset",
                 "seg_roof_outdomain", "seg_ground", "ge400_roof", "small_central", "small_outdomain"]
    best_rows = []
    for k in best_keys:
        if k == "floor_offset":
            mwp, ci = floor_offset, None
        elif k not in comp:
            # An optional component the atlas was not built with (the out-of-domain
            # extrapolation, say) is absent rather than zero -- skip it instead of drawing
            # an empty slice for a quantity the atlas does not report.
            continue
        else:
            mwp, ci = comp[k]["mwp"], comp[k]["ci"]
        best_rows.append({
            "key": k, "label": LABEL[k], "method": METHOD[k],
            "mwp": mwp, "ci": ci, "pct": 100 * mwp / best_total,
        })

    verified_keys = ["osm_roof", "osm_ground", "small_low"]
    verified_rows = []
    for k in verified_keys:
        mwp, ci = comp[k]["mwp"], comp[k]["ci"]
        verified_rows.append({
            "key": k, "label": LABEL[k], "method": VERIFIED_METHOD[k],
            "mwp": mwp, "ci": ci, "pct": 100 * mwp / verified_total,
        })

    check = sum(r["mwp"] for r in best_rows)
    if abs(check - best_total) > 1.0:
        raise AssertionError(f"best rows sum to {check:.1f} but published total is {best_total:.1f}")
    check_v = sum(r["mwp"] for r in verified_rows)
    if abs(check_v - verified_total) > 1.0:
        raise AssertionError(f"verified rows sum to {check_v:.1f} but published total is {verified_total:.1f}")

    return best_rows, verified_rows


def method_totals(rows: list[dict], total: float) -> list[dict]:
    sums: dict[str, float] = {m: 0.0 for m in METHOD_ORDER}
    for r in rows:
        sums[r["method"]] += r["mwp"]
    return [
        {"method": m, **METHOD_META[m], "mwp": sums[m], "pct": 100 * sums[m] / total}
        for m in METHOD_ORDER if sums[m] > 0
    ]


def main() -> None:
    totals = load_totals()
    best_rows, verified_rows = build_rows(totals)
    best_by_method = method_totals(best_rows, totals["mwp_best"])
    verified_by_method = method_totals(verified_rows, totals["mwp_verified"])

    data = {
        "mwp_best": totals["mwp_best"],
        "mwp_best_ci": totals["mwp_best_ci"],
        "mwp_verified": totals["mwp_verified"],
        "mwp_verified_ci": totals["mwp_verified_ci"],
        "best_rows": best_rows,
        "verified_rows": verified_rows,
        "best_by_method": best_by_method,
        "verified_by_method": verified_by_method,
        "colors": COLORS,
        "method_order": METHOD_ORDER,
        "method_meta": METHOD_META,
        "n_draws": totals["uncertainty"]["n_draws"],
        "ci_pct": totals["uncertainty"]["ci_pct"],
        "n_calib_boxes": totals["n_calib_boxes"],
        "n_domain_cells": totals["n_domain_cells"],
        "n_cells": totals["n_cells"],
    }

    print(f"Best estimate {data['mwp_best']:.1f} MWp (90% CI {data['mwp_best_ci'][0]:.1f}-{data['mwp_best_ci'][1]:.1f})")
    for r in best_by_method:
        print(f"  {r['name']:<22} {r['mwp']:>9.1f} MWp  ({r['pct']:.1f}%)")
    print(f"Verified (floor) {data['mwp_verified']:.1f} MWp")
    for r in verified_by_method:
        print(f"  {r['name']:<22} {r['mwp']:>9.1f} MWp  ({r['pct']:.1f}%)")

    html = TEMPLATE.read_text()
    html = html.replace("__PV_COMPOSITION_JSON__", json.dumps(data, separators=(",", ":")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
