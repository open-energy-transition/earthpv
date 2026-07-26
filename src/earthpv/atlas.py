"""Self-contained HTML capacity atlas from `density` outputs.

Two templates, chosen automatically by what the density run actually computed:

- **Six-estimator atlas** (`templates/pv_estimator_atlas.html`, the default whenever
  the columns exist): the night-lights choropleth originally hand-built as
  results/pakistan_pv_estimator_atlas.html, switchable between all six capacity
  estimators (detected / calibrated / expected / recall-corrected-rooftop in
  rooftop scope; calibrated / recall-corrected in all-PV scope) with a national
  comparison chart, credible-interval bands and a province ranking that follows
  the selected estimator. Requires `est_mwp_rc*` columns, i.e. a run that had a
  capacity_calibration table (`earthpv calibrate-candidates` before `density`).
- **Simple atlas** (`templates/pv_atlas.html`, the fallback): a single-metric
  night-lights map (est_mwp_cal if calibrated, else est_mwp_det, bracketed by
  expected) for runs without recall-correction — e.g. Germany, or a partial/
  validation-only density run that skipped calibration.

`density` calls `build_atlas` at the end of every run; the `earthpv atlas` CLI
command regenerates it standalone.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

import geopandas as gpd

log = logging.getLogger(__name__)

TEMPLATE = Path(__file__).parent / "templates" / "pv_atlas.html"
ESTIMATOR_TEMPLATE = Path(__file__).parent / "templates" / "pv_estimator_atlas.html"

# Major-city annotations per AOI (the map renders fine with none).
CITIES: dict[str, list] = {
    "pakistan": [
        ["Karachi", 67.01, 24.86], ["Lahore", 74.34, 31.55], ["Islamabad", 73.05, 33.68],
        ["Faisalabad", 73.08, 31.42], ["Multan", 71.52, 30.2], ["Peshawar", 71.58, 34.01],
        ["Quetta", 66.98, 30.18], ["Hyderabad", 68.37, 25.4], ["Rawalpindi", 73.07, 33.6],
        ["Gujranwala", 74.19, 32.16], ["Sukkur", 68.85, 27.7], ["Bahawalpur", 71.68, 29.4],
    ],
}

# Calibration ground-truth quadrats per AOI (docs/issues/pakistan-calibration-boxes.md):
# 1 km^2 boxes fully re-mapped this session and pooled into the recall-corrected
# estimator's denominator. `status` is an AI visual pass against high-res imagery,
# NOT a Rule-1 two-mapper verification -- corroboration, not independent ground truth.
CALIBRATION_BOXES: dict[str, list] = {
    "pakistan": [
        {"name": "Lahore DHA Phase V", "file": "lahore", "status": "corroborated"},
        {"name": "Faisalabad (PSIE)", "file": "faisalabad", "status": "suspect"},
        {"name": "Multan Industrial Estate", "file": "multan", "status": "corroborated"},
        {"name": "Sundar Industrial Estate", "file": "sundar", "status": "corroborated"},
        {"name": "SITE Karachi", "file": "site_karachi", "status": "corroborated"},
    ],
}


def _load_calib_boxes(aoi: str, labels_dir: Path = Path("data/labels")) -> list[dict]:
    """Ring geometry + live-pulled installation count for each defined calibration
    quadrat. A box with no `<file>_calib_1km_overpass_solar.parquet` (Multan) had
    zero solar features on its last live Overpass pull, not a missing fetch."""
    import pandas as pd

    out = []
    for box in CALIBRATION_BOXES.get(aoi, []):
        boundary = Path(labels_dir) / f"{box['file']}_calib_1km_boundary.geojson"
        if not boundary.exists():
            continue
        geom = gpd.read_file(boundary)
        centroid = geom.union_all().centroid
        solar_path = Path(labels_dir) / f"{box['file']}_calib_1km_overpass_solar.parquet"
        n = len(pd.read_parquet(solar_path)) if solar_path.exists() else 0
        out.append({
            "name": box["name"], "status": box["status"],
            "lon": round(float(centroid.x), 4), "lat": round(float(centroid.y), 4),
            "n": n, "rings": _rings(geom.union_all(), tolerance=0.0),
        })
    return out


def _rings(geom, tolerance: float = 0.03) -> list:
    """Exterior rings of a (Multi)Polygon, simplified and rounded for embedding."""
    simple = geom.simplify(tolerance, preserve_topology=True)
    polys = getattr(simple, "geoms", [simple])
    return [
        [[round(x, 3), round(y, 3)] for x, y in p.exterior.coords]
        for p in polys if not p.is_empty
    ]


def build_atlas(
    aoi: str, density_dir: Path, out: Path | None = None, zoom_out_frac: float = 0.0,
    labels_dir: Path = Path("data/labels"),
) -> Path:
    """`zoom_out_frac` pads the map's lon/lat bounds by this fraction of their own
    span on every side (e.g. 0.10 = 10% less zoom: the map draws 10% smaller within
    the same frame, showing that much more surrounding context).

    Dispatches to the six-estimator template when the run has recall-correction
    columns (est_mwp_rc*, i.e. `calibrate-candidates` ran before `density`); falls
    back to the single-metric template otherwise. See module docstring."""
    density_dir = Path(density_dir)
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    meta = json.loads((density_dir / "meta.json").read_text())
    if "est_mwp_rc" in grid.columns:
        return _build_estimator_atlas(aoi, density_dir, grid, meta, out, zoom_out_frac, labels_dir)
    return _build_simple_atlas(aoi, density_dir, grid, meta, out, zoom_out_frac)


def _build_simple_atlas(
    aoi: str, density_dir: Path, grid: gpd.GeoDataFrame, meta: dict,
    out: Path | None = None, zoom_out_frac: float = 0.0,
) -> Path:
    """The template's `proj()` fits the SVG viewBox exactly to `DATA.bounds`, so
    `zoom_out_frac` is the only knob that changes -- cells, province outlines and
    city labels all fall out unchanged, just at the new scale (a city just outside
    the old bounds may now come into view; none already inside can drop out, since
    the box only grows)."""
    calibrated = (
        meta.get("calibration_status", "uncalibrated") != "uncalibrated"
        and "est_mwp_cal" in grid.columns
    )
    pcol = "est_mwp_cal" if calibrated else "est_mwp_det"
    pacol = "pv_area_cal_roof_m2" if calibrated else "pv_area_det_roof_m2"
    title = aoi.replace("_", " ").title()

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3), round(float(getattr(r, pcol)), 3),
         round(float(r.est_mwp_exp), 3), int(r.n_pv_buildings),
         round(float(r.roof_area_m2) / 1e6, 3)]
        for r in grid.itertuples()
    ]
    bounds = [
        round(float(grid.lon0.min()), 3), round(float(grid.lat0.min()), 3),
        round(float(grid.lon0.max()) + 0.1, 3), round(float(grid.lat0.max()) + 0.1, 3),
    ]
    if zoom_out_frac:
        lon_pad = (bounds[2] - bounds[0]) * zoom_out_frac / 2
        lat_pad = (bounds[3] - bounds[1]) * zoom_out_frac / 2
        bounds = [
            round(bounds[0] - lon_pad, 3), round(bounds[1] - lat_pad, 3),
            round(bounds[2] + lon_pad, 3), round(bounds[3] + lat_pad, 3),
        ]

    provinces = []
    regions_path = density_dir / "regions.geoparquet"
    if regions_path.exists():
        reg = gpd.read_parquet(regions_path)
        for r in reg[reg.level == "region"].itertuples():
            area_km2 = max(float(r.area_km2), 1e-9)
            provinces.append({
                "name": str(r.name),
                # "mwp_det" is the template's primary-metric field name.
                "mwp_det": round(float(getattr(r, pcol)), 1),
                "mwp_exp": round(float(r.est_mwp_exp), 1),
                "nb": int(r.n_pv_buildings),
                "dens": round(float(getattr(r, pacol)) / area_km2, 1),
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["mwp_det"])

    data = {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "totals": {
            "mwp_det": round(float(grid[pcol].sum())),
            "mwp_exp": round(float(grid.est_mwp_exp.sum())),
            "pv_buildings": int(grid.n_pv_buildings.sum()),
            "det_km2": round(float(grid[pacol].sum()) / 1e6, 1),
            "n_cells": int(len(grid)),
            # Every metric on this page is roof-scope (footprint intersections), so the
            # module constant is the only one that applies here. `kwp_per_m2` is the
            # pre-split key, kept as a fallback for older meta.json files.
            "kwp_per_m2": meta.get("kwp_per_m2_module", meta.get("kwp_per_m2", 0.18)),
            "threshold": meta.get("threshold", 0.3),
        },
    }

    if calibrated:
        word, label, col = "calibrated", "Calibrated", "Cal"
        det_total = round(float(grid.est_mwp_det.sum()))
        bracket = (
            f'Detected (raw threshold) floor: <b>{det_total:,}</b> MWp; probability-weighted '
            'expectation: <b id="expNum">0</b> MWp. The calibrated number weights each '
            "candidate by its measured P(real | size, glint) — the floor and ceiling bracket it."
        )
        howto = (
            "<b>How to read it.</b> Colour is <b>calibrated</b> panel area — each candidate "
            "weighted by its measured probability of being real PV (size-binned OSM-mapped "
            "fraction + glint corroboration) — converted to peak capacity at "
            f"{data['totals']['kwp_per_m2']} kWp/m². Detected and expected bracket it as "
            "floor and ceiling. Cells with no detected PV are drawn as bare land; treat cell "
            "values as indicative, not metered."
        )
        method_lede = (
            "The model returns a PV probability for every 10&nbsp;m Sentinel-2 pixel. Panel "
            "area on building roofs is converted to peak DC capacity with a single "
            "module-density constant, then summed per cell, province and country. Detected "
            "and expected areas bracket the truth; the headline weights each candidate by "
            "P(real | size, glint) measured against OSM mapping and the solar-glint study "
            "(configs/calibration/)."
        )
    else:
        word, label, col = "detected", "Detected", "Det"
        bracket = (
            'Probability-weighted expectation: <b id="expNum">0</b> MWp. The two numbers '
            "bracket the truth — the model is tuned for recall, so detections are a floor "
            "and the expectation leans high."
        )
        howto = (
            "<b>How to read it.</b> Colour is detected panel area converted to peak capacity "
            f"at {data['totals']['kwp_per_m2']} kWp/m². <b>Detected</b> counts pixels above "
            f"the {data['totals']['threshold']} probability threshold that fall on a building "
            "footprint; <b>expected</b> sums probability across the footprint. Cells with no "
            "detected PV are drawn as bare land. Candidates are meant for human validation, "
            "so treat cell values as indicative, not metered."
        )
        method_lede = (
            "The model returns a PV probability for every 10&nbsp;m Sentinel-2 pixel. Panel "
            "area on building roofs is converted to peak DC capacity with a single "
            "module-density constant, then summed per cell, province and country. Two area "
            "estimates bracket the truth."
        )

    lede = (
        "A recall-first segmentation model reads a year of Sentinel-2 imagery across every "
        f"building-populated cell of {title} and marks the pixels that look like photovoltaic "
        "panels. Aggregated to each building and then to a <b>0.1° grid</b>, the "
        f"{word} panel area becomes an estimate of installed rooftop capacity — the input "
        "an energy-system model needs. The map glows where that capacity concentrates."
    )
    html = TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} Rooftop Solar Atlas",
        "__H1__": f"Where {title}'s rooftops already carry solar",
        "__LEDE_HTML__": lede,
        "__PRIMARY_WORD__": word,
        "__PRIMARY_LABEL__": label,
        "__PRIMARY_COL__": col,
        "__BRACKET_HTML__": bracket,
        "__N_CELLS_TOTAL__": f"{len(grid):,}",
        "__FOOT_MODEL__": (
            "Model: TerraMind-tiny fine-tuned on Germany + Pakistan OSM solar"
            + (" · calibrated capacity (P(real | size, glint))" if calibrated else "")
        ),
        "__AOI_TITLE__": title,
        "__HOWTO_HTML__": howto,
        "__METHOD_LEDE__": method_lede,
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else density_dir / f"{aoi}_pv_atlas.html"
    out.write_text(html)
    log.info("Wrote capacity atlas (%s metric) -> %s", word, out)
    return out


# Cell/province/total field order shared with templates/pv_estimator_atlas.html's
# METRICS registry -- keep the two in sync if either changes.
_EST_COLS = [
    "est_mwp_det", "est_mwp_cal", "est_mwp_exp", "est_mwp_rc_roof",
    "est_mwp_cal_total", "est_mwp_rc",
]


def _build_estimator_atlas(
    aoi: str, density_dir: Path, grid: gpd.GeoDataFrame, meta: dict,
    out: Path | None = None, zoom_out_frac: float = 0.0,
    labels_dir: Path = Path("data/labels"),
) -> Path:
    """Six-estimator dark night-lights atlas (see module docstring)."""
    title = aoi.replace("_", " ").title()

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         *[round(float(getattr(r, c)), 3) for c in _EST_COLS],
         int(r.n_pv_buildings),
         round(float(r.est_mwp_rc_lo), 3), round(float(r.est_mwp_rc_hi), 3)]
        for r in grid.itertuples()
    ]
    bounds = [
        round(float(grid.lon0.min()), 3), round(float(grid.lat0.min()), 3),
        round(float(grid.lon0.max()) + 0.1, 3), round(float(grid.lat0.max()) + 0.1, 3),
    ]
    if zoom_out_frac:
        lon_pad = (bounds[2] - bounds[0]) * zoom_out_frac / 2
        lat_pad = (bounds[3] - bounds[1]) * zoom_out_frac / 2
        bounds = [
            round(bounds[0] - lon_pad, 3), round(bounds[1] - lat_pad, 3),
            round(bounds[2] + lon_pad, 3), round(bounds[3] + lat_pad, 3),
        ]

    provinces = []
    regions_path = density_dir / "regions.geoparquet"
    if regions_path.exists():
        reg = gpd.read_parquet(regions_path)
        for r in reg[reg.level == "region"].itertuples():
            provinces.append({
                "name": str(r.name),
                "m": [round(float(getattr(r, c)), 1) for c in _EST_COLS],
                "rc_ci": [round(float(r.est_mwp_rc_lo), 1), round(float(r.est_mwp_rc_hi), 1)],
                "rcr_ci": [round(float(r.est_mwp_rc_roof_lo), 1), round(float(r.est_mwp_rc_roof_hi), 1)],
                "ct_ci": [round(float(r.est_mwp_cal_total_lo), 1), round(float(r.est_mwp_cal_total_hi), 1)],
                "rings": _rings(r.geometry),
            })

    run_date = meta.get("run_date")
    if not run_date:
        meta_path = density_dir / "meta.json"
        run_date = (
            datetime.datetime.fromtimestamp(meta_path.stat().st_mtime).strftime("%Y-%m-%d")
            if meta_path.exists() else "n/a"
        )

    data = {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "calibBoxes": _load_calib_boxes(aoi, labels_dir),
        "totals": {
            "m": [round(float(grid[c].sum())) for c in _EST_COLS],
            "rc_ci": [round(float(grid.est_mwp_rc_lo.sum())), round(float(grid.est_mwp_rc_hi.sum()))],
            "rcr_ci": [
                round(meta.get("total_est_mwp_rc_roof_lo", grid.est_mwp_rc_roof.sum())),
                round(meta.get("total_est_mwp_rc_roof_hi", grid.est_mwp_rc_roof.sum())),
            ],
            "ct_ci": [
                round(meta.get("total_est_mwp_cal_total_lo", grid.est_mwp_cal_total.sum())),
                round(meta.get("total_est_mwp_cal_total_hi", grid.est_mwp_cal_total.sum())),
            ],
            "n_cells": int(len(grid)),
            # Two conversion constants, because roof-scope metrics are module area and
            # all-PV metrics include ground-mount candidates whose polygon is site area.
            # `kwp` keeps the module value under its original key for older templates.
            "kwp": meta.get("kwp_per_m2_module", meta.get("kwp_per_m2", 0.18)),
            "kwpLand": meta.get("kwp_per_m2_land"),
            "recall_floor": meta.get("recall_floor", 0.05),
            "nOversize": meta.get("n_oversize_excluded"),
            "maxCandidateM2": meta.get("max_candidate_m2"),
            "run_date": run_date,
        },
    }

    lede = (
        "One recall-first model read a year of Sentinel-2 imagery over every "
        f"building-populated cell of {title}. How much photovoltaic capacity it saw "
        "depends on how honestly you count: the same probability rasters support "
        "<b>six defensible estimates</b>, from a raw-detection floor to a "
        "recall-corrected estimate of the whole detectable population. Switch "
        "between them — the map, the hero number and the province ranking follow."
    )
    html = ESTIMATOR_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} PV Capacity — Six Estimates, One Map",
        "__EYEBROW__": f"earthpv · Sentinel-2 × TerraMind · 0.1° grid · {run_date}",
        "__H1__": f"{title}'s solar boom, at six exposures",
        "__LEDE_HTML__": lede,
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else density_dir / f"{aoi}_pv_atlas.html"
    out.write_text(html)
    log.info(
        "Wrote six-estimator capacity atlas (headline %s MWp, %s calibration quadrats) -> %s",
        f"{data['totals']['m'][5]:,}", len(data["calibBoxes"]), out,
    )
    return out
