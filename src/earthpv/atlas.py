"""Self-contained HTML capacity atlas from `density` outputs.

Renders the night-lights-style choropleth page originally hand-built as
results/pakistan_7_7/pakistan_pv_atlas.html (template extracted to
templates/pv_atlas.html): an SVG 0.1° cell map with province outlines, hero
capacity number, province ranking and method notes — no external requests, dark
and light themes. `density` calls `build_atlas` at the end of every run; the
`earthpv atlas` CLI command regenerates it standalone.

The colour/hero metric is `est_mwp_cal` when the run was calibrated
(capacity_calibration), else `est_mwp_det`; detected and expected stay visible
as the bracketing floor/ceiling.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd

log = logging.getLogger(__name__)

TEMPLATE = Path(__file__).parent / "templates" / "pv_atlas.html"

# Major-city annotations per AOI (the map renders fine with none).
CITIES: dict[str, list] = {
    "pakistan": [
        ["Karachi", 67.01, 24.86], ["Lahore", 74.34, 31.55], ["Islamabad", 73.05, 33.68],
        ["Faisalabad", 73.08, 31.42], ["Multan", 71.52, 30.2], ["Peshawar", 71.58, 34.01],
        ["Quetta", 66.98, 30.18], ["Hyderabad", 68.37, 25.4], ["Rawalpindi", 73.07, 33.6],
        ["Gujranwala", 74.19, 32.16], ["Sukkur", 68.85, 27.7], ["Bahawalpur", 71.68, 29.4],
    ],
}


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
) -> Path:
    """`zoom_out_frac` pads the map's lon/lat bounds by this fraction of their own
    span on every side (e.g. 0.10 = 10% less zoom: the map draws 10% smaller within
    the same frame, showing that much more surrounding context). The template's
    `proj()` fits the SVG viewBox exactly to `DATA.bounds`, so this is the only knob
    that changes -- cells, province outlines and city labels all fall out unchanged,
    just at the new scale (a city just outside the old bounds may now come into view;
    none already inside can drop out, since the box only grows)."""
    density_dir = Path(density_dir)
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    meta = json.loads((density_dir / "meta.json").read_text())
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
            "kwp_per_m2": meta.get("kwp_per_m2", 0.18),
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
