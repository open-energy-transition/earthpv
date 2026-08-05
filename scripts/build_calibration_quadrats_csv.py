"""Regenerate `results/calibration_quadrats.csv` from the label files + a roofclf fold table.

`docs/methods/calibration-quadrats.md` has always described this table as "regenerated from
the label files directly rather than hand-maintained prose". That was aspirational: no writer
existed, and the file was edited by hand, which is how a stale row survives a boundary change
(measured 2026-08-05, when six quadrats were replaced and one removed in one session).

Two sources, and the split matters:

- **Geometry and mapped-PV columns** come from the boundary + newest `_overpass_solar` pull,
  so they always describe the CURRENT boundary. Free, no model involved.
- **`n_buildings` / `n_pv_buildings` / `base_rate` / `nn_median_m`** come from a `roofclf`
  run's `folds.csv`, because they need the VIDA building join `roofclf.building_table` does.
  Passing a fold table from a run that predates a boundary change would silently reintroduce
  exactly the staleness this script exists to prevent, so quadrats missing from it are left
  blank rather than filled from a previous value.

Columns `province`, `stratum`, `rule1_complete` and `date_added` are human judgements that no
file records, so they are carried over from the existing CSV when the stem matches and left
for a human otherwise -- `rule1_complete` especially: it means a mapper's completeness
declaration and must never be inferred.

    python scripts/build_calibration_quadrats_csv.py \
        --folds data/roofclf_20260805_newquadrats/folds.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.roofclf import (  # noqa: E402
    _newest_solar, discover_quadrats, load_boundary, quadrat_label,
)

GEOD = Geod(ellps="WGS84")
LABELS = Path("data/labels")
CARRIED = ["province", "stratum", "rule1_complete", "date_added",
           # The reference imagery a mapper declared completeness AGAINST. Rule-1 is
           # epoch-relative: it certifies "every panel visible in THIS imagery is mapped",
           # and the Sentinel-2 composite the model reads is generally NEWER, so
           # installations built in between are in the model's input and absent from the
           # labels. Without these two fields the size of that gap is unknowable per quadrat.
           # The protocol has required them since 2026-07-18 and they have never been
           # populated (docs/issues/calibration-imagery-dating.md); carried and reported as
           # missing rather than dropped, so the gap stays visible in the table itself.
           "imagery_layer", "imagery_date"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", required=True, help="folds.csv from the roofclf run to trust")
    ap.add_argument("--out", default="results/calibration_quadrats.csv")
    ap.add_argument("--labels-dir", default=str(LABELS))
    args = ap.parse_args()

    labels = Path(args.labels_dir)
    folds = pd.read_csv(args.folds).set_index("quadrat")
    prev = pd.read_csv(args.out).set_index("quadrat") if Path(args.out).exists() else None

    rows = []
    for stem in discover_quadrats(labels):
        bnd = load_boundary(labels / f"{stem}_boundary.geojson")
        pv = gpd.read_parquet(_newest_solar(stem, labels)).to_crs(4326)
        pv = pv[pv.geometry.geom_type.isin(("Polygon", "MultiPolygon"))]
        a = pv["area_m2"].to_numpy(float)
        label = quadrat_label(stem)
        area_km2 = abs(GEOD.geometry_area_perimeter(bnd)[0]) / 1e6
        rep = bnd.representative_point()

        r = {
            "quadrat": stem, "label": label, "area_km2": round(area_km2, 4),
            "n_installations": int(len(pv)),
            "total_pv_area_m2": round(float(a.sum()), 1) if len(a) else 0.0,
            "median_install_m2": round(float(np.median(a)), 1) if len(a) else np.nan,
            "frac_sub400": round(float((a < 400).mean()), 4) if len(a) else np.nan,
            # A representative point, not the centroid: a concave drawn boundary can put its
            # centroid outside itself.
            "center_lat": round(float(rep.y), 6), "center_lon": round(float(rep.x), 6),
        }
        # Model-side columns, only from the fold table given on the command line.
        f = folds.loc[label] if label in folds.index else None
        r["n_buildings"] = int(f["n"]) if f is not None else pd.NA
        r["n_pv_buildings"] = int(f["n_pv"]) if f is not None else pd.NA
        r["base_rate"] = round(float(f["base_rate"]), 4) if f is not None else pd.NA
        r["nn_median_m"] = round(float(f["nn_median_m"]), 1) if f is not None else pd.NA
        if f is None:
            print(f"  NOTE {stem}: absent from {args.folds}; building columns left blank "
                  "rather than carried over from a pre-change value")
        for c in CARRIED:
            # `c not in prev.columns` matters when a column is newly introduced: the previous
            # CSV simply has no such field, which must read as "unknown", not raise.
            have = prev is not None and stem in prev.index and c in prev.columns
            r[c] = prev.loc[stem][c] if have else pd.NA
            if pd.isna(r[c]):
                extra = {
                    "rule1_complete": " (rule1 means a mapper's declaration, never infer it)",
                    "imagery_date": " (Rule-1 is only as current as this date -- see below)",
                }.get(c, "")
                print(f"  NOTE {stem}: '{c}' unknown -- fill in by hand{extra}")
        rows.append(r)

    cols = ["quadrat", "label", "area_km2", "n_buildings", "n_pv_buildings", "base_rate",
            "n_installations", "total_pv_area_m2", "median_install_m2", "frac_sub400",
            "nn_median_m", "province", "stratum", "rule1_complete", "imagery_layer",
            "imagery_date", "date_added", "center_lat", "center_lon"]
    df = pd.DataFrame(rows)[cols].sort_values("base_rate").reset_index(drop=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"\n{len(df)} quadrats -> {args.out}")
    print(df[["quadrat", "area_km2", "n_buildings", "base_rate", "n_installations",
              "median_install_m2", "frac_sub400", "nn_median_m"]].to_string(index=False))


if __name__ == "__main__":
    main()
