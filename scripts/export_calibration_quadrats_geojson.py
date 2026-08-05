"""Export every calibration quadrat as one GeoJSON for a single JOSM validation pass.

Completeness (the protocol's "Rule 1") is judged per quadrat against high-res imagery, and
until now that meant opening one boundary file at a time. This writes **one** layer holding
every quadrat at once:

- one `quadrat_boundary` polygon per quadrat -- the exact geodesic box, so the extent a
  completeness declaration applies to is unambiguous on screen. Completeness is judged
  strictly *inside* this line; a panel one metre outside is out of scope, not a miss.
- one `mapped_solar` polygon per already-mapped installation inside that box, split by the
  400 m² detection floor, so the mapper can see what OSM already has and look for what it
  does not.

Both layers matter for the job: the box alone does not say what is already mapped, and the
solar alone does not say where the mapper is meant to stop looking.

A sibling MapCSS is written next to the GeoJSON, because JOSM draws an imported data layer
in one flat colour otherwise and "which line is the boundary" is exactly the thing that has
to be obvious. Load it under Preferences -> Map Paint Styles.

**This layer is reference geometry, not OSM data.** The boxes do not exist in OSM and the
solar polygons are a snapshot copy of ones that do. Every feature carries a
`do_not_upload` tag; keep it as its own layer and make real edits in the OSM data layer.
See `docs/calibration-mapping-protocol.md`, "Validating every quadrat in one pass".

    pixi run calib-export
    python scripts/export_calibration_quadrats_geojson.py --boundaries-only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Geod
from shapely.geometry import box as shapely_box
from shapely.geometry import mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv import roofclf  # noqa: E402

LABELS = Path("data/labels")
STATS_CSV = Path("results/calibration_quadrats.csv")
GEOD = Geod(ellps="WGS84")
FLOOR_M2 = 400.0
DO_NOT_UPLOAD = "earthpv calibration reference layer - do not upload to OSM"

MAPCSS = """\
/* earthpv calibration quadrat validation layer.
   JOSM: Preferences -> Map Paint Styles -> + -> point at this file.
   Draws the quadrat box as a heavy dashed outline (near-zero fill so imagery shows
   through) and colours already-mapped PV by the 400 m2 detection floor. */

way[feature_type=quadrat_boundary] {
    color: #ff3b30;
    width: 4;
    dashes: 14,7;
    fill-color: #ff3b30;
    fill-opacity: 0.02;
    text: quadrat_label;
    text-color: #ff3b30;
    font-size: 15;
    font-weight: bold;
    z-index: 100;
}

/* Not yet completeness-checked: a low score here cannot be blamed on the model. */
way[feature_type=quadrat_boundary][rule1_complete=no] {
    color: #ff9500;
    fill-color: #ff9500;
    text-color: #ff9500;
}

way[feature_type=mapped_solar] {
    color: #ffb000;
    width: 2;
    fill-color: #ffb000;
    fill-opacity: 0.40;
    z-index: 120;
}

/* Below the segmentation model's per-object floor -- the population completeness
   matters most for, and the one most often missing from OSM. */
way[feature_type=mapped_solar][size_class=sub_400] {
    color: #2ec7ff;
    fill-color: #2ec7ff;
    fill-opacity: 0.45;
}

/* Already in OSM but only partly inside the box. Shown on purpose: an unmarked panel
   inside the line reads as unmapped, and re-mapping it would duplicate an existing
   feature. Out of scope for the completeness count, in scope for not double-mapping. */
way[feature_type=mapped_solar][edge_straddling=yes] {
    color: #9b8cff;
    fill-color: #9b8cff;
    fill-opacity: 0.22;
}

way[feature_type=mapped_solar][placement=ground] {
    dashes: 6,4;
}
"""


def _stats() -> dict[str, dict]:
    """Per-quadrat summary rows, so a mapper sees base rate / Rule-1 status on the box
    itself rather than having to cross-reference the docs page."""
    if not STATS_CSV.exists():
        return {}
    df = pd.read_csv(STATS_CSV)
    return {r["quadrat"]: r for r in df.to_dict("records")}


def _clean(v):
    """JSON-safe scalar. NaN is dropped rather than emitted as the literal `NaN`, which
    is invalid JSON and which JOSM rejects outright."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (bool, str, int)):
        return v
    if isinstance(v, float):
        return round(v, 6)
    if pd.isna(v):
        return None
    return str(v)


def _is_rect(geom, tol_frac: float = 1e-4) -> bool:
    """Whether the boundary is (to rounding) its own bounding box. True for every
    script-generated geodesic square, false for a boundary drawn in JOSM."""
    if geom.geom_type != "Polygon" or list(geom.interiors):
        return False
    env = shapely_box(*geom.bounds)
    return env.area > 0 and geom.symmetric_difference(env).area / env.area < tol_frac


def _side_m(geom, area_km2: float, row: dict):
    """A side length only where one exists: an explicit `side_m` from the stats CSV, else
    sqrt(area) for a rectangle, else nothing (dropped from the output by `_feature`)."""
    v = _clean(row.get("side_m"))
    if v:
        return v
    return round(area_km2 ** 0.5 * 1000, 1) if _is_rect(geom) else None


def _feature(geom, props: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {k: v for k, v in props.items() if v is not None},
        "geometry": mapping(geom),
    }


def build(labels_dir: Path, boundaries_only: bool) -> tuple[list[dict], list[dict]]:
    stats = _stats()
    feats: list[dict] = []
    summary: list[dict] = []

    for stem in roofclf.discover_quadrats(labels_dir):
        boundary, pv = roofclf.load_quadrat(stem, labels_dir)
        label = roofclf.quadrat_label(stem)
        area_km2 = abs(GEOD.geometry_area_perimeter(boundary)[0]) / 1e6
        row = stats.get(stem, {})

        # An installation "belongs" to the quadrat whose box contains its representative
        # point (the rule the creation script and the evidence atlas use). But the ones
        # straddling the edge are still EXPORTED, flagged rather than dropped: a panel
        # visibly inside the box with no polygon drawn over it reads as unmapped, and a
        # mapper acting on that would create a duplicate of an installation that is
        # already in OSM. Counted separately so `n_inside_box` stays comparable with the
        # other tools while `n_mapped_solar` matches `results/calibration_quadrats.csv`.
        in_box = (
            pv.geometry.representative_point().within(boundary)
            if len(pv) else pd.Series(dtype=bool)
        )
        n_inside = int(in_box.sum())
        n_straddle = len(pv) - n_inside

        rule1 = row.get("rule1_complete")
        rule1_str = {True: "yes", False: "no"}.get(bool(rule1), "unknown") if pd.notna(rule1) else "unknown"

        feats.append(_feature(boundary, {
            "feature_type": "quadrat_boundary",
            "quadrat": stem,
            "quadrat_label": label,
            "area_km2": round(area_km2, 4),
            # Only for boxes that really are axis-aligned squares. sqrt(area) on a drawn
            # boundary is a side length that does not exist, and a JOSM reader would take
            # it for a real dimension of the shape on screen.
            "side_m": _side_m(boundary, area_km2, row),
            "shape": "square" if _is_rect(boundary) else "drawn",
            "province": _clean(row.get("province")),
            "stratum": _clean(row.get("stratum")),
            "rule1_complete": rule1_str,
            "n_mapped_solar": int(len(pv)),
            "n_inside_box": n_inside,
            "n_straddling_edge": n_straddle,
            "n_sub_400": int((pv["area_m2"] < FLOOR_M2).sum()) if len(pv) else 0,
            "base_rate": _clean(row.get("base_rate")),
            "nn_median_m": _clean(row.get("nn_median_m")),
            "date_added": _clean(row.get("date_added")),
            "do_not_upload": DO_NOT_UPLOAD,
        }))

        if not boundaries_only:
            for i, r in enumerate(pv.itertuples()):
                a = float(getattr(r, "area_m2", 0.0) or 0.0)
                feats.append(_feature(r.geometry, {
                    "feature_type": "mapped_solar",
                    "quadrat": stem,
                    "quadrat_label": label,
                    "osm_id": _clean(getattr(r, "id", None)),
                    "placement": _clean(getattr(r, "placement", None)),
                    "area_m2": round(a, 1),
                    "size_class": "sub_400" if a < FLOOR_M2 else "at_or_above_400",
                    "edge_straddling": "no" if bool(in_box.iloc[i]) else "yes",
                    "osm_timestamp": _clean(getattr(r, "osm_timestamp", None)),
                    "do_not_upload": DO_NOT_UPLOAD,
                }))

        summary.append({
            "quadrat": stem, "area_km2": round(area_km2, 3),
            "n_mapped_solar": len(pv), "n_inside_box": n_inside,
            "n_straddling_edge": n_straddle, "rule1_complete": rule1_str,
        })
    return feats, summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/calibration_quadrats_validation.geojson")
    ap.add_argument("--labels-dir", default=str(LABELS))
    ap.add_argument("--boundaries-only", action="store_true",
                    help="boxes only, without the already-mapped solar polygons")
    ap.add_argument("--no-mapcss", action="store_true", help="skip the sibling JOSM style")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    feats, summary = build(Path(args.labels_dir), args.boundaries_only)
    if not feats:
        raise SystemExit(f"no quadrats found under {args.labels_dir}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "type": "FeatureCollection",
        "name": out.stem,
        # Foreign members: ignored by JOSM/iD, but they make the file self-describing for
        # anyone who opens it in a text editor a year from now.
        "earthpv": {
            "purpose": "calibration quadrat completeness validation against OSM imagery",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_quadrats": len(summary),
            "detection_floor_m2": FLOOR_M2,
            "warning": DO_NOT_UPLOAD,
            "workflow": "docs/calibration-mapping-protocol.md#validating-every-quadrat-in-one-pass",
        },
        "features": feats,
    }
    out.write_text(json.dumps(doc, indent=1) + "\n")

    n_box = sum(1 for f in feats if f["properties"]["feature_type"] == "quadrat_boundary")
    n_pv = len(feats) - n_box
    print(pd.DataFrame(summary).to_string(index=False))
    print(f"\n{n_box} quadrat boxes + {n_pv} mapped installations -> {out}")

    if not args.no_mapcss:
        style = out.with_suffix(".mapcss")
        style.write_text(MAPCSS)
        print(f"JOSM style -> {style}  (Preferences -> Map Paint Styles -> + -> this file)")
    print(f"\nReminder: {DO_NOT_UPLOAD}.")


if __name__ == "__main__":
    main()
