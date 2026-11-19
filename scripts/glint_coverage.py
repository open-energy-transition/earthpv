#!/usr/bin/env python
"""How much of a country's large installations a glint survey has measured: the numbers
behind Gold's glint requirement (`validation.glint_survey`; owner, 2026-11-19).

**Eligible** are the installations of `atlas.GLINT_MIN_AREA_M2` (1 ha) and more mapped in
OpenStreetMap, as the atlas counts them: its own `--osm-solar` file
(`release_polygons.atlas_osm_solar`), dissolved per placement (`labels.dissolve_overlapping`),
geodesic area. **Measured** are the eligible installations holding the point of a survey
target (scripts/glint_pose_survey.py's `summary.csv`, or Pakistan's older
`data/glint/country2000_summary.csv`) that was read on at least `atlas.GLINT_MIN_CLEAR` clear
Sentinel-2 scenes. Matching by place, not OSM id, so a survey drawn from an older pull still
counts where the installation has been redrawn since. Whether a panel pose fitted is reported
beside it, never required: it depends on latitude, season and tilt.

The rule (`atlas.glint_required`): at least a third of the eligible installations, never
fewer than 100 or all of them where a country has fewer, and 1,000 where a third would be
more, from a census or a random draw. A survey of the largest only does not qualify: say how
its targets were drawn in the declaration's `note`.

    pixi run python scripts/glint_coverage.py --aoi france --survey france
    pixi run python scripts/glint_coverage.py --aoi pakistan --survey data/glint/country2000_summary.csv

Prints the `validation.glint_survey` block for configs/atlas/<aoi>.yaml and writes
results/glint_coverage/<aoi>.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from earthpv import atlas  # noqa: E402
from earthpv.labels import dissolve_overlapping, geodesic_area_m2  # noqa: E402


def summary_path(survey: str) -> Path:
    """A survey name (data/glint/<name>_pose/summary.csv) or a summary CSV's path."""
    p = Path(survey)
    if p.suffix == ".csv":
        return p if p.is_absolute() else ROOT / p
    return ROOT / "data" / "glint" / f"{survey.removesuffix('_pose')}_pose" / "summary.csv"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--survey", required=True, help="survey name or summary.csv path")
    ap.add_argument("--osm", type=Path, help="the atlas's OSM solar file (default: as published)")
    ap.add_argument("--by", default="owner")
    a = ap.parse_args()

    from release_polygons import atlas_osm_solar

    osm_path = a.osm or atlas_osm_solar(a.aoi)
    osm = gpd.read_parquet(osm_path)
    osm = osm[osm.geometry.notna() & ~osm.geometry.is_empty
              & osm.geom_type.isin(["Polygon", "MultiPolygon"])]
    group = "placement" if "placement" in osm.columns else None
    osm = dissolve_overlapping(osm, group_col=group)
    area = np.array([geodesic_area_m2(g) for g in osm.geometry])
    big = osm[area >= atlas.GLINT_MIN_AREA_M2].reset_index(drop=True)
    big["area_m2"] = area[area >= atlas.GLINT_MIN_AREA_M2]

    path = summary_path(a.survey)
    s = pd.read_csv(path)
    if not {"lon", "lat"} <= set(s.columns):
        # Pakistan's older survey keeps its points in <name>_targets.parquet beside the
        # summary; a <name>_pose survey in targets.parquet.
        tpath = (path.parent / "targets.parquet" if path.name == "summary.csv"
                 else path.with_name(path.name.replace("_summary.csv", "_targets.parquet")))
        t = pd.read_parquet(tpath)
        if not {"lon", "lat"} <= set(t.columns):
            t = gpd.GeoDataFrame(t)
            rep = t.geometry.representative_point()
            t["lon"], t["lat"] = rep.x, rep.y
        s = s.merge(pd.DataFrame(t)[["pid", "lon", "lat"]], on="pid", how="left")
    read = s[s["n_clear"].fillna(0) >= atlas.GLINT_MIN_CLEAR]
    pts = gpd.GeoDataFrame(read, geometry=gpd.points_from_xy(read["lon"], read["lat"]),
                           crs="EPSG:4326")
    hit = gpd.sjoin(pts, big[["geometry"]], predicate="within", how="inner")
    measured_ids = set(hit["index_right"])
    per = hit.groupby("index_right").agg(detected=("detected", "max"),
                                         validated=("validated", "max"))
    eligible, measured = len(big), len(measured_ids)
    required = atlas.glint_required(eligible)
    out = {
        "aoi": a.aoi, "survey": a.survey, "summary": str(path.relative_to(ROOT))
        if path.is_relative_to(ROOT) else str(path),
        "osm_solar": str(osm_path), "min_area_m2": atlas.GLINT_MIN_AREA_M2,
        "min_clear_scenes": atlas.GLINT_MIN_CLEAR, "survey_targets": len(s),
        "eligible": eligible, "measured": measured, "required": required,
        "met": measured >= required,
        "measured_with_glint": int(per["detected"].astype(bool).sum()),
        "measured_with_pose": int(per["validated"].astype(bool).sum()),
    }
    dest = ROOT / "results" / "glint_coverage" / f"{a.aoi}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2) + "\n")

    print(f"{a.aoi}: {eligible:,} installations of {atlas.GLINT_MIN_AREA_M2:,.0f} m2 and up in "
          f"{Path(osm_path).name}; {measured:,} measured by {a.survey} (>= "
          f"{atlas.GLINT_MIN_CLEAR} clear scenes), {required:,} required -> "
          f"{'MET' if out['met'] else 'NOT MET'}")
    print(f"  of the measured: {out['measured_with_glint']:,} glinted, "
          f"{out['measured_with_pose']:,} with a fitted panel pose (reported, not required)")
    print("\nconfigs/atlas/<aoi>.yaml, under `validation:`:")
    print(f"  glint_survey:\n    survey: {a.survey}\n    eligible: {eligible}\n"
          f"    measured: {measured}\n    min_area_m2: {atlas.GLINT_MIN_AREA_M2:.0f}\n"
          f"    by: {a.by}\n    date: \"{dt.date.today().isoformat()}\"\n"
          f"    note: \"<census or random sample; which OSM pull>\"")
    print(f"\n-> {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
