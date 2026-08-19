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
  expected) for runs without recall-correction - e.g. Germany, or a partial/
  validation-only density run that skipped calibration.

`density` calls `build_atlas` at the end of every run; the `earthpv atlas` CLI
command regenerates it standalone.

A fourth, richer template (`templates/pv_evidence_atlas.html`, `build_evidence_atlas`)
is the project's default going forward as of 2026-08-01 for AOIs with the extra
national-scale artifacts it needs (OSM solar pull, national roofclf+SPPI scoring, the
sub-400 m2 bracket's building-level parquets): tiers by STANDARD OF PROOF (Verified /
Best, a third Ceiling tier removed 2026-08-06) rather than by point estimate, plus the
KPI-strip + expandable-background page shell documented in `CLAUDE.md`'s "Results-page
house style". It supersedes `build_sub400_bracket_atlas` as the CLI's recommended path;
that function stays for reference and for AOIs that only have the older bracket inputs.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TEMPLATE = Path(__file__).parent / "templates" / "pv_atlas.html"
ESTIMATOR_TEMPLATE = Path(__file__).parent / "templates" / "pv_estimator_atlas.html"
SUB400_BRACKET_TEMPLATE = Path(__file__).parent / "templates" / "pv_sub400_bracket_atlas.html"
EVIDENCE_TEMPLATE = Path(__file__).parent / "templates" / "pv_evidence_atlas.html"
POTENTIAL_TEMPLATE = Path(__file__).parent / "templates" / "pv_potential_atlas.html"
SIZE_TEMPLATE = Path(__file__).parent / "templates" / "pv_size_atlas.html"

# Major-city annotations per AOI (the map renders fine with none).
CITIES: dict[str, list] = {
    "pakistan": [
        ["Karachi", 67.01, 24.86], ["Lahore", 74.34, 31.55], ["Islamabad", 73.05, 33.68],
        ["Faisalabad", 73.08, 31.42], ["Multan", 71.52, 30.2], ["Peshawar", 71.58, 34.01],
        ["Quetta", 66.98, 30.18], ["Hyderabad", 68.37, 25.4], ["Rawalpindi", 73.07, 33.6],
        ["Gujranwala", 74.19, 32.16], ["Sukkur", 68.85, 27.7], ["Bahawalpur", 71.68, 29.4],
    ],
}

# Calibration ground-truth quadrats per AOI (docs/issues/pakistan-calibration-boxes.md),
# pooled into the recall-corrected estimator's denominator.
# `stem` is the full quadrat file prefix, so the box size is not baked into the code
# (the protocol allows 1-4 km2 and the first Rule-1-complete box is 0.49 km2).
# status: "rule1" = every visible panel mapped and verified, so its has-no-PV buildings
# are trustworthy negatives; "corroborated" = visual pass supports the count but
# completeness is not asserted; "suspect" = needs re-verification.
# All seventeen carry status "rule1" as of 2026-08-05: the repository owner declared
# completeness for the whole current set, which is what Rule-1 means here (see roofclf.py's
# module docstring -- it is a mapper's declaration, never something code infers or a script
# can produce). That is a reversal for Karachi coastal, whose Rule-1 the owner had withdrawn
# earlier the same day when its boundary was extended, and a promotion for the five quadrats
# added that day. A missing stem is skipped SILENTLY by `calibration_box_features`, so this
# list must track every rename -- six stems changed on 2026-08-05.
CALIBRATION_BOXES: dict[str, list] = {
    "pakistan": [
        # Extended 2026-08-05 from a 1 km2 square to a 6.61 km2 hand-drawn boundary that
        # fully contains it (`_calib_1km` retired to data/labels/retired/).
        {"name": "Lahore DHA Phase V", "stem": "lahore_calib_6p61km2", "status": "rule1"},
        {"name": "Faisalabad (PSIE)", "stem": "faisalabad_calib_1km", "status": "rule1"},
        # Extended 2026-08-05, 1 km2 square -> hand-drawn 3.92 km2 that fully contains it
        # (`_calib_1km` retired to data/labels/retired/). Rule-1 explicitly re-declared by
        # the owner for the extended area the same day (initially withheld, since the
        # blanket declaration predated this boundary).
        {"name": "Multan Industrial Estate", "stem": "multan_calib_3p92km2", "status": "rule1"},
        # Extended 2026-08-05, 1 km2 square -> hand-drawn 4.34 km2 that fully contains it.
        {"name": "Sundar Industrial Estate", "stem": "sundar_calib_4p34km2", "status": "rule1"},
        # Extended 2026-08-05, 1 km2 square -> hand-drawn 4.14 km2 that fully contains it.
        {"name": "SITE Karachi", "stem": "site_karachi_calib_4p14km2", "status": "rule1"},
        # Extended 2026-08-05, 0.49 -> 2.16 km2. Not a strict superset: 8.6% of the old box
        # falls outside this boundary, but that sliver held zero mapped installations.
        {"name": "Karachi DHA Phase 5 / Zamzama (coastal)",
         "stem": "karachi_coast_calib_2p16km2", "status": "rule1"},
        {"name": "Sialkot Old City", "stem": "sialkot_calib_1km", "status": "rule1"},
        {"name": "Sheikh Maltoon Town, Mardan", "stem": "mardan_calib_1km", "status": "rule1"},
        {"name": "Quetta City", "stem": "quetta_calib_1km", "status": "rule1"},
        {"name": "Peshawar", "stem": "peshawar_calib_1km", "status": "rule1"},
        # Peshawar East removed 2026-08-05 as wrong (retired to data/labels/retired/): 32.1%
        # of its installations sat inside the 6.56% corner it shared with Peshawar, so the
        # pair could not be pooled without double-counting them or breaking LOQO fold
        # independence, and its 3.7% base rate against Peshawar's 16.5% at 995 m was never
        # reconciled. Do not re-add without resolving both.
        # Extended 2026-08-05, 1.5 km square -> hand-drawn 4.39 km2 that fully contains it.
        # Never listed here before that date, so the atlas silently omitted it.
        {"name": "Peshawar West", "stem": "peshawar_west_calib_4p39km2", "status": "rule1"},
        # Extended 2026-08-05, 1 km2 square -> hand-drawn 2.06 km2 that fully contains it.
        {"name": "Rahim Yar Khan District", "stem": "rahim_yar_khan_calib_2p06km2",
         "status": "rule1"},
        # Added 2026-08-05. Sukkur is the first quadrat in Sindh outside Karachi, and at
        # 100% of installations below the 400 m2 floor (median 27 m2) it is the purest
        # sub-floor population in the set.
        {"name": "Sukkur", "stem": "sukkur_calib_2p63km2", "status": "rule1"},
        # Added 2026-08-05: four mutually non-overlapping diamonds around Islamabad, the
        # first quadrats placed as a directional ring rather than purposively, and the first
        # in Islamabad Capital Territory.
        {"name": "Islamabad North", "stem": "islamabad_north_calib_2p79km2", "status": "rule1"},
        {"name": "Islamabad East", "stem": "islamabad_east_calib_2p79km2", "status": "rule1"},
        {"name": "Islamabad South", "stem": "islamabad_south_calib_2p79km2", "status": "rule1"},
        {"name": "Islamabad West", "stem": "islamabad_west_calib_2p79km2", "status": "rule1"},
        # Added the same day as the other four Islamabad diamonds but never listed here --
        # found 2026-08-10/11: one of the 13 quadrats sub400_capacity's coverage-ratio and
        # precision fits actually trust, so it was invisible on a map whose own numbers
        # partly came from it. `_load_calib_boxes` skips a missing stem without erroring,
        # which is exactly how this went unnoticed for days -- see that function's
        # docstring on why a caller can't rely on it to catch this by itself.
        {"name": "Islamabad Northeast", "stem": "islamabad_northeast_calib_3p34km2", "status": "rule1"},
        # Added 2026-08-10, never listed here. Not one of the 13 quadrats behind the
        # precision/coverage-ratio fits (rate_ratio outside the trusted band), but it is
        # Rule-1 ground truth like every other quadrat -- see this file's own domain-vs-
        # multiplier note for why that distinction matters and why it still belongs on
        # the map.
        {"name": "Hasal", "stem": "hasal_calib_1p00km2", "status": "rule1"},
        # Added 2026-08-11, purpose-built to test whether the density-matched domain
        # (national_cell_domain) could be widened downward with evidence -- picked from
        # the densest 200x200 m building cluster inside a national cell averaging ~200
        # bldg/km2, specifically to still have enough buildings to map. The quadrat's OWN
        # density (639 bldg/km2) came out INSIDE the existing 553-5,258 bldg/km2 range,
        # not below it -- a real, non-obvious finding, not the intended result: a small
        # quadrat centered on a real settlement reads far denser than the coarse 0.1 deg
        # cell average surrounding it, because villages cluster and farmland does not.
        # Extremely low base rate (0.94%, second-lowest after Quetta's 3.0%) makes it
        # valuable ground truth for the low end of the currently-calibrated range even
        # though it does not extend that range. See CLAUDE.md's "Out-of-domain AND-gate"
        # entry for the full story and what an actually range-extending quadrat needs.
        {"name": "Muzaffargarh Rural", "stem": "muzaffargarh_rural_calib_1km", "status": "rule1"},
        # Added 2026-08-11: a mapper-drawn (not geodesic-square) boundary, checked the
        # same way -- 1,427.8 bldg/km2, also inside the existing calibrated range, but
        # its rate_ratio (0.858) falls inside the trusted [0.5, 2.0] precision band, so
        # unlike muzaffargarh_rural it DOES enter the 13-quadrat precision/coverage-ratio
        # fit (-> 14). Declared Rule-1 complete by the owner "as complete as the imagery
        # in JOSM allows" -- see CLAUDE.md's Rule-1-epoch-relative amendment the same day
        # for what that qualification does and does not certify.
        {"name": "Malok", "stem": "malok_calib_4p13km2", "status": "rule1"},
        # Added 2026-08-11, the same day as Muzaffargarh Rural and Malok but for a
        # different purpose: deliberately drawn to include open farmland alongside a
        # village (4 km2, centered 7.2 km from Muzaffargarh Rural) rather than tracing a
        # settlement's built-up edge, specifically to test whether a quadrat could
        # average BELOW density.CALIBRATED_BLDG_DENSITY_KM2's floor. It did: 277.75
        # bldg/km2 (unaffected by the correction below, since building count -- not PV --
        # sets density). This quadrat moved the calibrated floor 553.40 -> 277.75 bldg/km2,
        # growing the roofclf domain restriction from 163 to 646 of Pakistan's 4,463
        # national cells.
        #
        # CORRECTED same day: the first OSM pull found 0 installations after 8
        # independent non-timeout Overpass queries over ~20 minutes, which was treated as
        # a confirmed-empty result (`build_overpass_labels` hard-fails on any single empty
        # response by design and has no path to accept a genuine zero through its normal
        # retry logic, so this required a manual override at the time). The owner then
        # found and mapped PV the original pass had missed -- a genuine Rule-1
        # completeness gap in the original sweep, not an Overpass reliability issue after
        # all. Re-pulled once the new mapping was uploaded and propagated: **12
        # installations** (7 rooftop, 5 ground; 9 of 1,111 buildings flagged has_pv),
        # base_rate 0.81%, not 0.0%. `rate_ratio` (3.39) keeps it out of the trusted
        # precision-calibration subset either way, so this correction did not need to
        # touch any published capacity number beyond the domain-restriction share that
        # naturally follows from more cells being in-domain.
        {"name": "Muzaffargarh Rural Wide", "stem": "muzaffargarh_rural_wide_calib_2km",
         "status": "rule1"},
        # Added 2026-08-11, same session: a second range-extending quadrat, same method
        # (a 4 km2 box deliberately including farmland, verified via direct VIDA building
        # count before mapping) but in Khairpur District, Sindh, for geographic diversity
        # from the Muzaffargarh-area quadrats. Measured 141.0 bldg/km2, moving the floor
        # 277.75 -> 141.00 and growing the domain from 646 to 1,680 of Pakistan's 4,463
        # cells. 3 installations (all ground-mount), base_rate 0.53%, rate_ratio (4.36)
        # excluded from the trusted precision subset like Muzaffargarh Rural Wide.
        {"name": "Khairpur Rural", "stem": "khairpur_rural_calib_2km", "status": "rule1"},
        # Added 2026-08-12: a mapper-drawn 2x2 km boundary (3.98 km2 geodesic) in Sanghar
        # District, Sindh -- 115 km from the nearest existing quadrat (Khairpur Rural), and
        # the first quadrat in Sanghar. Overpass pull cleanly cross-checked (465 features
        # written, confirming query saw 465 -- no truncation, no empty-response retry
        # needed): 464 installations inside the boundary after the representative-point
        # filter, 99.8% below the 400 m2 floor (median 30.2 m2), packing distance 24.4 m --
        # a dense small-rooftop population close in character to Sialkot/Hasal. Declared
        # Rule-1 complete by the owner. Not yet in a roofclf refit, so
        # results/calibration_quadrats.csv carries it with n_buildings/n_pv_buildings/
        # base_rate/nn_median_m blank rather than guessed -- those need `roofclf` re-run
        # with this quadrat included, same as any other newly added box.
        {"name": "Sanghar", "stem": "sanghar_calib_3p98km2", "status": "rule1"},
    ],
}


def _load_calib_boxes(aoi: str, labels_dir: Path = Path("data/labels")) -> list[dict]:
    """Ring geometry + live-pulled installation count for each defined calibration
    quadrat. A box with no `<stem>_overpass_solar*.parquet` had zero solar features on its
    last live Overpass pull, not a missing fetch. The newest dated pull wins, because a
    quadrat gets re-pulled after a completeness pass and the stale one would silently
    become ground truth."""
    import pandas as pd

    out = []
    for box in CALIBRATION_BOXES.get(aoi, []):
        boundary = Path(labels_dir) / f"{box['stem']}_boundary.geojson"
        if not boundary.exists():
            log.warning(
                "Calibration box %r (stem %r) has no boundary file at %s -- skipped, "
                "will not appear on the map. If this quadrat is Rule-1 complete and in "
                "use elsewhere (e.g. sub400_capacity's precision fit), this is a real "
                "gap, not just a missing map marker.",
                box["name"], box["stem"], boundary,
            )
            continue
        geom = gpd.read_file(boundary)
        centroid = geom.union_all().centroid
        pulls = sorted(Path(labels_dir).glob(f"{box['stem']}_overpass_solar*.parquet"))
        n = len(pd.read_parquet(pulls[-1])) if pulls else 0
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
            "candidate by its measured P(real | size, glint) - the floor and ceiling bracket it."
        )
        howto = (
            "<b>How to read it.</b> Colour is <b>calibrated</b> panel area - each candidate "
            "weighted by its measured probability of being real PV (size-binned OSM-mapped "
            "fraction + glint corroboration) - converted to peak capacity at "
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
            "bracket the truth - the model is tuned for recall, so detections are a floor "
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
        f"{word} panel area becomes an estimate of installed rooftop capacity - the input "
        "an energy-system model needs. The map glows where that capacity concentrates."
    )
    det_total_note = round(float(grid.est_mwp_det.sum()))
    exp_total_note = round(float(grid.est_mwp_exp.sum()))
    formula_note = (
        "<b>A<sub>det</sub></b> counts only pixels above the 0.30 threshold that fall on a "
        "building footprint &mdash; the precision-honest floor. <b>A<sub>exp</sub></b> "
        "integrates sub-threshold probability, so it leans high. Reported capacity is "
        "<b>P&nbsp;=&nbsp;A&nbsp;&times;&nbsp;&eta;</b> for each, giving the detected / "
        f"expected pair ({det_total_note:,} / {exp_total_note:,} MWp nationwide) that "
        "brackets the true installed capacity."
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
        "__SECONDARY_LABEL__": "Expected",
        "__SECONDARY_COL__": "Exp",
        "__TILE_LARGE_LABEL__": f"{label} MWp",
        "__TILE_SMALL_LABEL__": "Expected MWp",
        "__BRACKET_HTML__": bracket,
        "__N_CELLS_TOTAL__": f"{len(grid):,}",
        "__FOOT_MODEL__": (
            "Model: TerraMind-tiny fine-tuned on Germany + Pakistan OSM solar"
            + (" · calibrated capacity (P(real | size, glint))" if calibrated else "")
        ),
        "__AOI_TITLE__": title,
        "__HOWTO_HTML__": howto,
        "__METHOD_LEDE__": method_lede,
        "__FORMULA_NOTE_HTML__": formula_note,
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else density_dir / f"{aoi}_pv_atlas.html"
    out.write_text(html)
    log.info("Wrote capacity atlas (%s metric) -> %s", word, out)
    return out


# Size bins in m2, split at the 400 m2 detection floor: below it, a "large" candidate
# cannot exist by construction (the segmentation model burns everything smaller as
# ignore during training -- see chips.MIN_PV_AREA); above it, a "small" checked building
# has already been dropped by the contamination filter in
# `sub400_capacity.domain_restricted_capacity`. So the two series never share a bin --
# this is one continuous size axis assembled from two instruments, not two overlapping
# ones.
_SMALL_BIN_EDGES = [0, 25, 50, 100, 200, 400]
_LARGE_BIN_EDGES = [400, 1000, 2500, 5000, 10000, 25000, 100000]


def _bin_counts(values: np.ndarray, edges: list[float]) -> list[int]:
    values = values[np.isfinite(values)]
    idx = np.digitize(values, edges[1:-1], right=False)
    return [int((idx == i).sum()) for i in range(len(edges) - 1)]


def _bin_label(lo: float, hi: float) -> str:
    def fmt(v: float) -> str:
        return f"{v / 1000:g}k" if v >= 1000 else f"{v:g}"
    return f"{fmt(lo)}–{fmt(hi)} m²"


def _size_distribution(density_dir: Path, sub400_cells_path: Path | None) -> dict:
    """Installation-count histogram spanning both instruments this atlas combines:
    detected candidate polygons (>= 400 m2, from `postprocess`) and checked buildings
    (< 400 m2, from the domain-restricted sub400 population). Counts only, not area or
    capacity, so it answers "how many installations of each size" -- the long tail of
    small installations the 400 m2 floor otherwise hides entirely from view.
    """
    bins: list[dict] = []
    if sub400_cells_path is not None and Path(sub400_cells_path).exists():
        small = pd.read_parquet(sub400_cells_path, columns=["roof_area_m2"])
        counts = _bin_counts(small["roof_area_m2"].to_numpy(float), _SMALL_BIN_EDGES)
        for lo, hi, n in zip(_SMALL_BIN_EDGES[:-1], _SMALL_BIN_EDGES[1:], counts):
            bins.append({"label": _bin_label(lo, hi), "n": n, "series": "small"})

    cand_path = Path(density_dir).parent / "candidates.parquet"
    if cand_path.exists():
        cands = pd.read_parquet(cand_path, columns=["area_m2", "oversize"])
        areas = cands.loc[~cands["oversize"].astype(bool), "area_m2"].to_numpy(float)
        counts = _bin_counts(areas, _LARGE_BIN_EDGES)
        for lo, hi, n in zip(_LARGE_BIN_EDGES[:-1], _LARGE_BIN_EDGES[1:], counts):
            bins.append({"label": _bin_label(lo, hi), "n": n, "series": "large"})

    return {"bins": bins}


def build_combined_atlas(
    aoi: str, density_dir: Path, sub400_cells_path: Path,
    out: Path | None = None, zoom_out_frac: float = 0.0,
    labels_dir: Path = Path("data/labels"),
) -> Path:
    """Large-PV (>= 400 m2, national, recall-corrected) + small-PV (sub-400 m2,
    density-domain-restricted -- see `sub400_capacity.domain_restricted_capacity`) in ONE
    per-cell map, reusing `templates/pv_atlas.html` (the same template `_build_simple_atlas`
    uses) rather than a bespoke page.

    The two instruments have wildly different national coverage -- large-PV covers every
    cell, small-PV only the ~93 cells whose building density matches the calibration
    quadrats' range -- so a cell outside that domain shows large-PV alone, not "zero
    small-PV" (the small-PV contribution there is simply unmeasured). The map draws a
    dashed teal outline on every in-domain cell regardless of its value, so that
    distinction survives the color scale: a color alone cannot show "this number includes
    a second, differently-calibrated instrument" the way an outline can.

    `sub400_cells_path` is the building-level domain-restricted parquet
    `sub400_capacity.domain_restricted_capacity` writes (columns: `cell`, `roof_area_m2`,
    `p_roofclf`, `est_kwp_sub400`) -- summing `est_kwp_sub400` per `cell` gives that cell's
    small-PV MWp exactly as the 6,628 MWp national (domain-only) figure sums it.
    """
    density_dir = Path(density_dir)
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    meta = json.loads((density_dir / "meta.json").read_text())
    if "est_mwp_rc" not in grid.columns:
        raise ValueError(
            f"{density_dir}/grid.geoparquet has no est_mwp_rc column -- run "
            "`earthpv calibrate-candidates` before `density` so recall-correction exists; "
            "the combined atlas needs a large-PV instrument to add the small-PV figure to."
        )
    title = aoi.replace("_", " ").title()

    # Reassign buildings to cells by spatial join against THIS grid's own cell polygons
    # (grid.geometry is exactly the [lon0,lon0+0.1) x [lat0,lat0+0.1) box), rather than
    # trusting the `cell` id already baked into sub400_cells_path: that id was computed
    # against whatever manifest was current when roofclf's national scoring ran, and even
    # reconstructing ix/iy from "this grid's observed min lon0/lat0" is unsafe -- that min
    # is just the smallest POPULATED cell, not the true compose-grid origin, so a run with
    # a slightly different populated extent shatters cells that should be one. Measured on
    # the pinned pre-OSM-replace snapshot: the naive string-id join silently dropped 3
    # cells (746.7 MWp); the origin-guessing rebuild fragmented the 93 cells into 245 and
    # still dropped 39. A spatial join against the grid's actual polygons is the only
    # version of this that cannot silently misplace a building.
    sub400 = gpd.read_parquet(sub400_cells_path, columns=["est_kwp_sub400", "geometry"])
    sub400 = sub400.set_geometry(sub400.geometry.representative_point())
    joined = gpd.sjoin(sub400, grid[["cell", "geometry"]], predicate="within", how="left")
    n_unmatched = int(joined["cell"].isna().sum())
    if n_unmatched:
        unmatched_mwp = float(joined.loc[joined["cell"].isna(), "est_kwp_sub400"].sum()) / 1000.0
        log.warning(
            "Combined atlas: %d of %d domain-restricted buildings (%.1f MWp) fall outside "
            "every cell of this %d-cell grid -- likely outside this run's AOI/manifest "
            "bounds entirely (a different density run's coverage), not a join bug. Their "
            "capacity is excluded from the map/totals below.",
            n_unmatched, len(joined), unmatched_mwp, len(grid),
        )
    by_cell = joined.dropna(subset=["cell"]).groupby("cell")["est_kwp_sub400"].sum() / 1000.0
    n_domain_cells = int(by_cell.size)

    grid = grid.copy()
    grid["est_mwp_sub400"] = grid["cell"].map(by_cell).fillna(0.0)
    grid["in_domain"] = grid["cell"].isin(by_cell.index)
    grid["est_mwp_combined"] = grid["est_mwp_rc"] + grid["est_mwp_sub400"]

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         round(float(r.est_mwp_combined), 3), round(float(r.est_mwp_rc), 3),
         int(r.n_pv_buildings), round(float(r.roof_area_m2) / 1e6, 3), int(r.in_domain)]
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
        reg_regions = reg[reg.level == "region"]
        # Sum the two new per-cell columns into each province by point-in-polygon --
        # regions.geoparquet's own precomputed sums predate est_mwp_sub400/combined and
        # don't have them, so this is a join, not a lookup.
        pts = gpd.GeoDataFrame(
            grid[["est_mwp_rc", "est_mwp_sub400", "est_mwp_combined"]],
            geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs=grid.crs,
        )
        joined = gpd.sjoin(pts, reg_regions[["region_id", "geometry"]], predicate="within", how="left")
        by_region = joined.groupby("region_id")[["est_mwp_sub400", "est_mwp_combined"]].sum()
        for r in reg_regions.itertuples():
            area_km2 = max(float(r.area_km2), 1e-9)
            region_sub400 = float(by_region["est_mwp_sub400"].get(r.region_id, 0.0))
            region_combined = float(by_region["est_mwp_combined"].get(r.region_id, r.est_mwp_rc))
            provinces.append({
                "name": str(r.name),
                # "mwp_det"/"mwp_exp" are the template's field names; here "det" is the
                # combined (primary, colours the map) figure and "exp" is large-PV alone
                # (the secondary/bracket column), NOT literally detected/expected.
                "mwp_det": round(region_combined, 1),
                "mwp_exp": round(float(r.est_mwp_rc), 1),
                "mwp_sub400": round(region_sub400, 1),
                "nb": int(r.n_pv_buildings),
                "dens": round(float(r.pv_area_rc_total_m2) / area_km2, 1),
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["mwp_det"])

    total_rc = float(grid.est_mwp_rc.sum())
    total_sub400 = float(grid.est_mwp_sub400.sum())
    total_combined = float(grid.est_mwp_combined.sum())

    data = {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "calibBoxes": _load_calib_boxes(aoi, labels_dir),
        "totals": {
            "mwp_det": round(total_combined),
            "mwp_exp": round(total_rc),
            "mwp_large": round(total_rc),
            "mwp_small": round(total_sub400),
            "pv_buildings": int(grid.n_pv_buildings.sum()),
            "det_km2": round(float(grid.pv_area_rc_total_m2.sum()) / 1e6, 1),
            "n_cells": int(len(grid)),
            "kwp_per_m2": meta.get("kwp_per_m2_module", 0.18),
            "threshold": meta.get("threshold", 0.3),
        },
        "sizeDist": _size_distribution(density_dir, sub400_cells_path),
    }

    lede = (
        f"This map estimates solar power capacity across {title}, combining two methods "
        "so both large solar sites and small rooftop installations show up in one place. "
        "A satellite based model scans Sentinel-2 imagery to find installations of "
        "400 square metres or larger everywhere in the country. A second, building by "
        "building model adds smaller installations, but only in areas that have been "
        "checked against real, hand mapped locations in OpenStreetMap. Colour shows the "
        "combined total wherever both estimates apply. A dashed outline marks exactly "
        "which areas that is."
    )
    bracket = (
        'Large installations alone (400 square metres and larger, nationwide): '
        f'<b id="expNum">0</b> MWp. Including smaller installations inside the '
        f"{n_domain_cells} outlined cells brings the total shown to "
        f"<b>{round(total_combined):,}</b> MWp. This is <b>not</b> a nationwide estimate "
        "for small installations: outside the outlined cells, the map shows large "
        "installations only, because there is not yet enough checked ground data there, "
        "not because small scale solar is known to be absent. The checked area is "
        f"measured elsewhere as 93 locations; {n_domain_cells} is that same area, redrawn "
        "on this map's own grid, not a larger coverage claim."
    )
    howto = (
        "<b>How to read this map.</b> Colour shows <b>combined</b> capacity: large "
        "installations everywhere, plus small installations inside the "
        f"{n_domain_cells} dashed outline cells. Outside the outline, colour reflects "
        "large installations only, since the small-installation estimate is unmeasured "
        "there, not zero. Teal dots mark calibration areas, small locations checked by "
        "hand against real installations, which is how the small-installation estimate "
        "was validated. Hover any cell or marker for details."
    )
    method_lede = (
        "Large scale solar capacity comes from a satellite image model trained to "
        "recognise solar panels in Sentinel-2 imagery, corrected for installations the "
        "model is known to miss. Small scale solar capacity comes from a separate model "
        "that scores each building individually, calibrated against a set of small areas "
        "mapped by hand in OpenStreetMap and checked against real installations (the "
        "calibration areas marked on the map). That calibration currently covers a small "
        f"share of the country, {n_domain_cells} of this map's {len(grid):,} cells "
        f"({100 * n_domain_cells / len(grid):.1f} percent), based on a national survey of "
        "building density computed separately from this map's own grid. Because the two "
        f"surveys use slightly different cell boundaries, the same checked area appears as "
        f"{n_domain_cells} cells here even though it is reported as 93 locations "
        "elsewhere; the total shown is exact either way, since buildings were matched by "
        "location rather than by cell name. Extending the small-installation estimate "
        "beyond the checked areas is left for future work rather than assumed here."
    )
    formula_note = (
        f"Large installations shown: <b>{round(total_rc):,} MWp</b> (corrected for "
        f"detection misses, all placements, nationwide). Small installations shown: "
        f"<b>{round(total_sub400):,} MWp</b> (limited to the checked area only). "
        f"Combined: <b>{round(total_combined):,} MWp</b>. This combined figure is shown "
        "on request; it is not treated as a single validated estimate in this project's "
        "own methodology, since the two figures cover very different shares of the "
        "country and rest on different levels of confidence. See the dashed outline "
        "cells above for exactly where the small-installation figure is greater than zero."
    )

    html = TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} Solar Capacity: Large and Small Installations",
        "__H1__": f"Every scale of solar power in {title}, on one map",
        "__LEDE_HTML__": lede,
        "__PRIMARY_WORD__": "combined",
        "__PRIMARY_LABEL__": "Combined",
        "__PRIMARY_COL__": "Combined",
        "__SECONDARY_LABEL__": "Large only",
        "__SECONDARY_COL__": "Large only",
        "__TILE_LARGE_LABEL__": "Large capacity MWp",
        "__TILE_SMALL_LABEL__": "Small capacity MWp",
        "__BRACKET_HTML__": bracket,
        "__N_CELLS_TOTAL__": f"{len(grid):,}",
        "__FOOT_MODEL__": (
            "Large-scale detector: TerraMind satellite image model. Small-scale detector: "
            "a per-building classifier calibrated against OpenStreetMap-mapped areas "
            f"({n_domain_cells}-cell checked area)"
        ),
        "__AOI_TITLE__": title,
        "__HOWTO_HTML__": howto,
        "__METHOD_LEDE__": method_lede,
        "__FORMULA_NOTE_HTML__": formula_note,
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else density_dir / f"{aoi}_pv_combined_atlas.html"
    out.write_text(html)
    log.info(
        "Wrote combined atlas (large %.0f + small %.0f = %.0f MWp, %d/%d domain cells) -> %s",
        total_rc, total_sub400, total_combined, n_domain_cells, len(grid), out,
    )
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

    sub400 = meta.get("sub400_roofclf_supplemental")
    if sub400 is not None:
        # Requested explicitly despite the "do not sum" note above: the two instruments
        # cover disjoint populations (>=400 m2 recall-corrected vs. a 93-cell sub-400 m2
        # domain restriction) at very different confidence levels, so this combined figure
        # is a user-requested convenience number, not a validated national estimate.
        sub400 = {**sub400, "combined_mwp": round(
            float(grid.est_mwp_rc.sum()) + float(sub400["total_est_mwp"]), 1
        )}

    data = {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "calibBoxes": _load_calib_boxes(aoi, labels_dir),
        "plausibilityNote": meta.get("plausibility_note"),
        "sub400": sub400,
        "totals": {
            "m": [round(float(grid[c].sum())) for c in _EST_COLS],
            # From the country-level summed draws in meta, NOT by adding the per-cell
            # bounds: bin-level calibration uncertainty is fully correlated across cells,
            # so summing per-cell quantiles is the error density.py's docstring warns
            # about. It gave [4854, 8465] here against the correct [5034, 8239].
            "rc_ci": [
                round(meta.get("total_est_mwp_rc_lo", grid.est_mwp_rc_lo.sum())),
                round(meta.get("total_est_mwp_rc_hi", grid.est_mwp_rc_hi.sum())),
            ],
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
        "between them - the map, the hero number and the province ranking follow."
    )
    if data["totals"].get("kwpLand"):
        lede += (
            " Rooftop and ground-mount area convert at different rates, because a rooftop "
            "detection outlines the panels and a ground-mount detection outlines the site."
        )
    html = ESTIMATOR_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} PV Capacity - Six Estimates, One Map",
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


def _join_buildings_to_grid_cells(
    buildings: gpd.GeoDataFrame, value_col: str, grid: gpd.GeoDataFrame,
) -> pd.Series:
    """Aggregate a building-level per-cell estimate onto the density grid's OWN cell
    polygons via a representative-point spatial join, rather than trusting the `cell`
    id string already on `buildings` to match `grid`'s.

    This is the same safe pattern `build_combined_atlas` already established: those ids
    come from whatever manifest was current when `roofclf.score_buildings_national` ran,
    and even reconstructing them from this grid's own observed bounds is unsafe (a run
    with a slightly different populated extent shatters/misaligns cells). Measured there:
    a naive string-id join silently dropped cells; the origin-guessing rebuild fragmented
    and dropped more. A spatial join against the grid's actual polygons cannot misplace a
    building.
    """
    pts = buildings[[value_col, "geometry"]].copy()
    pts = pts.set_geometry(pts.geometry.representative_point())
    joined = gpd.sjoin(pts, grid[["cell", "geometry"]], predicate="within", how="left")
    n_unmatched = int(joined["cell"].isna().sum())
    if n_unmatched:
        unmatched_val = float(joined.loc[joined["cell"].isna(), value_col].sum())
        log.warning(
            "%d of %d buildings (%.1f in %s) fall outside every cell of this %d-cell "
            "grid -- excluded from the map/totals below, not a join bug (likely outside "
            "this run's AOI/manifest bounds entirely).",
            n_unmatched, len(joined), unmatched_val, value_col, len(grid),
        )
    return joined.dropna(subset=["cell"]).groupby("cell")[value_col].sum()


def build_sub400_bracket_atlas(
    aoi: str, density_dir: Path,
    low_buildings_path: Path, central_buildings_path: Path, high_buildings_path: Path,
    out: Path | None = None, zoom_out_frac: float = 0.0, labels_dir: Path = Path("data/labels"),
) -> Path:
    """Per-cell atlas of the three sub-400 m² capacity bracket members
    (`docs/methods/density.md`'s "A sub-400 m² capacity bracket", 2026-07-31), switchable
    between them, with the large-PV (>= 400 m², recall-corrected, rooftop-scope)
    instrument ALWAYS shown alongside every view -- both populations resolve to the same
    0.1 degree grid, so the two read together regardless of which small-PV view is active.

    `*_buildings_path` are the per-building parquets each bracket function already
    returns (this only aggregates them to cells, it recomputes nothing):

    - `low_buildings_path`: `sub400_capacity.domain_restricted_and_gate_capacity`'s
      `incr` (columns: cell, geometry, roof_area_m2, est_kwp_sub400_and_gate) --
      roofclf AND SPPI agree, 93-cell density-calibrated domain only.
    - `central_buildings_path`: `sub400_capacity.domain_restricted_capacity`'s `incr`
      (est_kwp_sub400) -- roofclf alone, the SAME 93-cell domain.
    - `high_buildings_path`: `roofclf_capacity.incremental_capacity`'s `incr`
      (est_kwp_roofclf) -- flat national precision, unrestricted, explicitly
      uncalibrated ceiling.

    Low and central share one domain (`in_domain`, drawn as a dashed outline regardless
    of the selected view -- it does not change meaning when High is selected, since High
    is unrestricted and simply has no signal in most cells rather than being "out of
    domain"). Large-PV is `est_mwp_rc_roof` from the run's own `grid.geoparquet` --
    national, rooftop-scope, recall-corrected -- so it converts capacity at the same
    module constant the sub-400 figures use throughout, not the ground-mount site
    constant.
    """
    density_dir = Path(density_dir)
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    if "est_mwp_rc_roof" not in grid.columns:
        raise ValueError(
            f"{density_dir}/grid.geoparquet has no est_mwp_rc_roof column -- run "
            "`earthpv calibrate-candidates` before `density` so recall-correction "
            "exists; the bracket atlas needs the large-PV instrument to show alongside."
        )
    title = aoi.replace("_", " ").title()

    by_low = _join_buildings_to_grid_cells(
        gpd.read_parquet(low_buildings_path), "est_kwp_sub400_and_gate", grid
    ) / 1000.0
    by_central = _join_buildings_to_grid_cells(
        gpd.read_parquet(central_buildings_path), "est_kwp_sub400", grid
    ) / 1000.0
    by_high = _join_buildings_to_grid_cells(
        gpd.read_parquet(high_buildings_path), "est_kwp_roofclf", grid
    ) / 1000.0

    grid = grid.copy()
    grid["mwp_low"] = grid["cell"].map(by_low).fillna(0.0)
    grid["mwp_central"] = grid["cell"].map(by_central).fillna(0.0)
    grid["mwp_high"] = grid["cell"].map(by_high).fillna(0.0)
    grid["in_domain"] = grid["cell"].isin(by_low.index) | grid["cell"].isin(by_central.index)
    n_domain_cells = int(grid["in_domain"].sum())
    # Low and Central are combined with large PV (>= 400 m2, recall-corrected rooftop)
    # into a single reported total, per the user's explicit request (2026-07-31): fold
    # the >= 400 m2 instrument into the Low and Central estimates specifically, the same
    # "large everywhere + small where checked" combination `build_combined_atlas` already
    # ships for its own single roofclf-alone case. High stays UNCOMBINED on purpose -- it
    # is presented as an explicit, unvalidated national ceiling on the sub-400 m2 signal
    # alone, and folding an already-uncalibrated national extrapolation together with the
    # project's main validated number would blur exactly the distinction this atlas exists
    # to preserve.
    grid["mwp_combined_low"] = grid["mwp_low"] + grid["est_mwp_rc_roof"]
    grid["mwp_combined_central"] = grid["mwp_central"] + grid["est_mwp_rc_roof"]
    # All-PV (2026-07-31): Central's small-PV component plus large PV across EVERY
    # placement (`est_mwp_rc`, ground-mount included), not just rooftop. Kept as a
    # fourth, separately labelled view rather than folded into Central, because it
    # answers a different question -- "how much PV of any kind" vs. "how much rooftop
    # PV" -- and ground-mount converts at a different constant (site area, not module
    # area) and carries its own, separately documented plausibility risk (the ground
    # mount vs. rooftop ratio check in `plausibility.py` exists precisely because this
    # is the pipeline's most bug-prone component). Folding it into Central silently
    # would make a rooftop number look bigger without saying why.
    grid["mwp_all_pv"] = grid["mwp_central"] + grid["est_mwp_rc"]

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         round(float(r.mwp_low), 3), round(float(r.mwp_central), 3), round(float(r.mwp_high), 3),
         round(float(r.est_mwp_rc_roof), 3), int(r.n_pv_buildings),
         round(float(r.roof_area_m2) / 1e6, 3), int(r.in_domain),
         round(float(r.mwp_combined_low), 3), round(float(r.mwp_combined_central), 3),
         round(float(r.est_mwp_rc), 3), round(float(r.mwp_all_pv), 3)]
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
        reg_regions = reg[reg.level == "region"]
        pts = gpd.GeoDataFrame(
            grid[[
                "mwp_low", "mwp_central", "mwp_high", "est_mwp_rc_roof", "est_mwp_rc",
                "mwp_combined_low", "mwp_combined_central", "mwp_all_pv", "n_pv_buildings",
            ]],
            geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs=grid.crs,
        )
        joined = gpd.sjoin(pts, reg_regions[["region_id", "geometry"]], predicate="within", how="left")
        by_region = joined.groupby("region_id")[
            ["mwp_low", "mwp_central", "mwp_high", "est_mwp_rc_roof", "est_mwp_rc",
             "mwp_combined_low", "mwp_combined_central", "mwp_all_pv"]
        ].sum()
        for r in reg_regions.itertuples():
            area_km2 = max(float(r.area_km2), 1e-9)
            row = by_region.reindex([r.region_id]).fillna(0.0).iloc[0]
            provinces.append({
                "name": str(r.name),
                "mwp_low": round(float(row["mwp_combined_low"]), 1),
                "mwp_central": round(float(row["mwp_combined_central"]), 1),
                "mwp_high": round(float(row["mwp_high"]), 1),
                "mwp_all_pv": round(float(row["mwp_all_pv"]), 1),
                "mwp_large": round(float(row["est_mwp_rc_roof"]), 1),
                "mwp_large_all": round(float(row["est_mwp_rc"]), 1),
                "mwp_low_small_only": round(float(row["mwp_low"]), 1),
                "mwp_central_small_only": round(float(row["mwp_central"]), 1),
                "nb": int(r.n_pv_buildings),
                "dens": round(float(r.pv_area_rc_total_m2) / area_km2, 1),
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["mwp_central"])

    total_low = float(grid.mwp_low.sum())
    total_central = float(grid.mwp_central.sum())
    total_high = float(grid.mwp_high.sum())
    total_large = float(grid.est_mwp_rc_roof.sum())
    total_large_all = float(grid.est_mwp_rc.sum())
    total_combined_low = float(grid.mwp_combined_low.sum())
    total_combined_central = float(grid.mwp_combined_central.sum())
    total_all_pv = float(grid.mwp_all_pv.sum())

    data = {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "calibBoxes": _load_calib_boxes(aoi, labels_dir),
        "totals": {
            "mwp_low": round(total_combined_low, 1),
            "mwp_central": round(total_combined_central, 1),
            "mwp_high": round(total_high, 1),
            "mwp_large": round(total_large, 1),
            "mwp_low_small_only": round(total_low, 1),
            "mwp_central_small_only": round(total_central, 1),
            "mwp_all_pv": round(total_all_pv, 1),
            "mwp_large_all": round(total_large_all, 1),
            "pv_buildings": int(grid.n_pv_buildings.sum()),
            "n_cells": int(len(grid)),
            "n_domain_cells": n_domain_cells,
            "kwp_per_m2": 0.18,
        },
    }

    html = SUB400_BRACKET_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} Sub-400 m² Capacity Bracket",
        "__H1__": f"How much rooftop solar is too small for {title}'s satellite map to see?",
        "__AOI_TITLE__": title,
        "__LEDE_HTML__": (
            "The satellite model above only detects installations of 400 square metres "
            "or larger. Four different, differently-confident methods estimate what "
            "that leaves out, or restate it at a wider scope. Switch between them: "
            "large installations (400 m² and up, from the main model) are always shown "
            "alongside, on every view. For Low and Central, the total shown adds "
            "large rooftop installations to small ones; for High, large rooftop "
            "installations are shown for scale only and are not added in; All-PV adds "
            "large installations of every placement, ground-mount farms included, to "
            "Central's small-PV component, a wider and separately labelled question "
            "from the other three."
        ),
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else density_dir / f"{aoi}_pv_sub400_bracket_atlas.html"
    out.write_text(html)
    log.info(
        "Wrote sub-400 bracket atlas (low combined %.0f / central combined %.0f / "
        "high %.0f / all-PV %.0f MWp, large-PV roof %.0f / all-placement %.0f MWp, "
        "%d/%d domain cells) -> %s",
        total_combined_low, total_combined_central, total_high, total_all_pv,
        total_large, total_large_all, n_domain_cells, len(grid), out,
    )
    return out


GROWTH_TEMPLATE = Path(__file__).parent / "templates" / "pv_growth_atlas.html"


def build_growth_atlas(
    aoi: str, growth_dir: Path, out: Path | None = None,
    zoom_out_frac: float = 0.0,
) -> Path:
    """Three-tab atlas from `scripts/pv_growth_map.py` (segmentation, current vs.
    pre-boom epoch -- called once with segmentation density dirs, growth_dir, and once
    more with fraction-sourced density dirs into the sibling `growth_fraction/` dir) and
    `scripts/sppi_growth_map.py` (per-building SPPI epoch-diff), all reading from
    `growth_dir` (default `<density_dir>/growth`) and its `growth_fraction` sibling.

    Deliberately does not attempt to visualize the boom-window stacked-model retrain
    (`docs/issues/boom-window-stacking-experiment.md`) as a map layer -- that experiment
    produced no usable per-cell output (a training collapse, not a spatial result) --
    it is summarized in this page's background section as text instead.
    """
    growth_dir = Path(growth_dir)
    grid = gpd.read_parquet(growth_dir / "growth_grid.geoparquet")

    sppi_path = growth_dir / "sppi_growth_grid.geoparquet"
    sppi_cols = ["n_onset_buildings", "onset_roof_area_m2", "onset_mwp"]
    if sppi_path.exists():
        sppi = gpd.read_parquet(sppi_path).drop(columns="geometry")
        missing = [c for c in sppi_cols if c not in sppi.columns]
        for c in missing:  # older sppi_growth_grid.geoparquet predating onset_mwp
            sppi[c] = 0.0
        grid = grid.merge(sppi[["cell", *sppi_cols]], on="cell", how="left")
    else:
        for c in sppi_cols:
            grid[c] = 0.0
    grid[sppi_cols] = grid[sppi_cols].fillna(0.0)

    # Fraction-sourced growth: scripts/pv_growth_map.py run a second time against
    # density runs built with --fraction-prob-dir, in a sibling directory (not a
    # subdirectory of growth_dir, since it comes from an entirely separate pair of
    # density runs, current + pre-boom, both fraction-sourced).
    frac_dir = growth_dir.parent / "growth_fraction"
    frac_cols = ["delta_mwp_exp_fraction", "mwp_exp_fraction_current", "mwp_exp_fraction_preboom"]
    frac_path = frac_dir / "growth_grid.geoparquet"
    if frac_path.exists():
        frac = gpd.read_parquet(frac_path).drop(columns="geometry")
        frac = frac.rename(columns={
            "delta_est_mwp_exp": "delta_mwp_exp_fraction",
            "est_mwp_exp": "mwp_exp_fraction_current",
            "est_mwp_exp_preboom": "mwp_exp_fraction_preboom",
        })
        grid = grid.merge(frac[["cell", *frac_cols]], on="cell", how="left")
    else:
        for c in frac_cols:
            grid[c] = 0.0
    grid[frac_cols] = grid[frac_cols].fillna(0.0)

    title = aoi.replace("_", " ").title()

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         round(float(r.delta_est_mwp_rc), 3), round(float(r.delta_est_mwp_det), 3),
         int(r.n_onset_buildings), round(float(r.onset_roof_area_m2) / 1e6, 4),
         round(float(r.onset_mwp), 3), round(float(r.delta_mwp_exp_fraction), 3)]
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
    regions_path = growth_dir / "growth_regions.geoparquet"
    sppi_regions_path = growth_dir / "sppi_growth_regions.geoparquet"
    frac_regions_path = frac_dir / "growth_regions.geoparquet"
    sppi_by_name = {}
    if sppi_regions_path.exists():
        sr = gpd.read_parquet(sppi_regions_path)
        sppi_by_name = {str(row["name"]): row for _, row in sr.iterrows()}
    frac_by_name = {}
    if frac_regions_path.exists():
        fr = gpd.read_parquet(frac_regions_path)
        frac_by_name = {str(row["name"]): row for _, row in fr.iterrows()}
    if regions_path.exists():
        reg = gpd.read_parquet(regions_path)
        for r in reg[reg.level == "region"].itertuples():
            sr = sppi_by_name.get(str(r.name))
            fr = frac_by_name.get(str(r.name))
            provinces.append({
                "name": str(r.name),
                "delta_mwp_rc": round(float(r.delta_est_mwp_rc), 1),
                "delta_mwp_det": round(float(r.delta_est_mwp_det), 1),
                "mwp_rc": round(float(r.est_mwp_rc), 1),
                "mwp_rc_preboom": round(float(r.est_mwp_rc_preboom), 1),
                "n_onset": int(sr["n_onset_buildings"]) if sr is not None else 0,
                "onset_km2": (
                    round(float(sr["onset_roof_area_m2"]) / 1e6, 2) if sr is not None else 0.0
                ),
                "onset_mwp": (
                    round(float(sr["onset_mwp"]), 1)
                    if sr is not None and "onset_mwp" in sr else 0.0
                ),
                "delta_mwp_exp_fraction": (
                    round(float(fr["delta_est_mwp_exp"]), 1) if fr is not None else 0.0
                ),
                "mwp_exp_fraction_current": (
                    round(float(fr["est_mwp_exp"]), 1) if fr is not None else 0.0
                ),
                "mwp_exp_fraction_preboom": (
                    round(float(fr["est_mwp_exp_preboom"]), 1) if fr is not None else 0.0
                ),
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["delta_mwp_rc"])

    data = {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "totals": {
            "delta_mwp_rc": round(float(grid.delta_est_mwp_rc.sum()), 1),
            "delta_mwp_det": round(float(grid.delta_est_mwp_det.sum()), 1),
            "mwp_rc_current": round(float(grid.est_mwp_rc.sum()), 1),
            "mwp_rc_preboom": round(float(grid.est_mwp_rc_preboom.sum()), 1),
            "n_onset_buildings": int(grid.n_onset_buildings.sum()),
            "onset_km2": round(float(grid.onset_roof_area_m2.sum()) / 1e6, 1),
            "onset_mwp": round(float(grid.onset_mwp.sum()), 1),
            "delta_mwp_exp_fraction": round(float(grid.delta_mwp_exp_fraction.sum()), 1),
            "mwp_exp_fraction_current": round(float(grid.mwp_exp_fraction_current.sum()), 1),
            "mwp_exp_fraction_preboom": round(float(grid.mwp_exp_fraction_preboom.sum()), 1),
            "n_cells": int(len(grid)),
        },
    }

    html = GROWTH_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} PV Growth Atlas",
        "__H1__": f"Where {title}'s rooftop solar appeared since before the boom",
        "__AOI_TITLE__": title,
        "__LEDE_HTML__": (
            "Pakistan's rooftop PV stock is dominated by a post-2022 import boom. Three "
            "independent instruments diff the same pre-boom (2021/22) and current "
            "Sentinel-2 imagery to show where that growth actually landed: a trained "
            "segmentation model's own recall-corrected capacity estimate, that same "
            "checkpoint's fraction head reaching below its 400 m² floor, and a "
            "model-free spectral index computed directly on each building's own "
            "reflectance. Switch between them below."
        ),
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else growth_dir / f"{aoi}_pv_growth_atlas.html"
    out.write_text(html)
    log.info(
        "Wrote growth atlas (Δ %.1f MWp recall-corrected, %d SPPI-onset buildings, "
        "%.1f km² onset roof area, %.1f MWp uncalibrated SPPI ceiling, "
        "Δ %.1f MWp fraction-sourced expected area) -> %s",
        data["totals"]["delta_mwp_rc"], data["totals"]["n_onset_buildings"],
        data["totals"]["onset_km2"], data["totals"]["onset_mwp"],
        data["totals"]["delta_mwp_exp_fraction"], out,
    )
    return out


GROWTH_EVIDENCE_TEMPLATE = Path(__file__).parent / "templates" / "pv_growth_evidence_atlas.html"


def build_growth_evidence_atlas(
    aoi: str, growth_dir: Path, out: Path | None = None, zoom_out_frac: float = 0.0,
) -> Path:
    """Night-lights atlas for `earthpv growth`'s output (growth.build_growth): the
    two-epoch, same-instrument growth grid composed the way the evidence atlas composes
    capacity. Five views: total / sub-400 (roofclf) / rooftop >= 400 (roofclf-or-seg by
    domain) / ground-mount (seg) / SPPI onset (corroboration only, not in the total).
    Supersedes `build_growth_atlas`, which renders the old cross-checkpoint
    segmentation-only diff."""
    growth_dir = Path(growth_dir)
    grid = gpd.read_parquet(growth_dir / "growth_grid.geoparquet")
    summary = json.loads((growth_dir / "summary.json").read_text())

    for c in ["n_onset_buildings", "onset_mwp"]:  # absent when no SPPI grid was merged
        if c not in grid.columns:
            grid[c] = 0.0
    delta_cols = ["delta_mwp_total", "delta_mwp_sub400", "delta_mwp_roof", "delta_mwp_ground"]
    grid[delta_cols] = grid[delta_cols].fillna(0.0)  # uncovered cells render dark, not lit

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         round(float(r.delta_mwp_total), 3), round(float(r.delta_mwp_sub400), 3),
         round(float(r.delta_mwp_roof), 3), round(float(r.delta_mwp_ground), 3),
         round(float(r.mwp_total_cur), 3), round(float(r.mwp_total_pre), 3),
         int(r.n_onset_buildings), round(float(r.onset_mwp), 3), int(bool(r.in_domain))]
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
    regions_path = growth_dir / "growth_regions.geoparquet"
    if regions_path.exists():
        reg = gpd.read_parquet(regions_path)
        for r in reg[reg.level == "region"].itertuples():
            provinces.append({
                "name": str(r.name),
                "d_total": round(float(r.delta_mwp_total), 1),
                "d_sub400": round(float(r.delta_mwp_sub400), 1),
                "d_roof": round(float(r.delta_mwp_roof), 1),
                "d_ground": round(float(r.delta_mwp_ground), 1),
                "cur_total": round(float(r.mwp_total_cur), 1),
                "pre_total": round(float(r.mwp_total_pre), 1),
                "onset_mwp": round(float(getattr(r, "onset_mwp", 0.0) or 0.0), 1),
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["d_total"])

    d, cur, pre = summary["delta_mwp"], summary["mwp_current"], summary["mwp_preboom"]
    data = {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "epochs": summary["epochs"],
        "totals": {
            "d_total": d["total"], "d_sub400": d["sub400"], "d_roof": d["roof"],
            "d_ground": d["ground"],
            "cur": cur, "pre": pre,
            "n_cells": summary["n_cells"],
            "n_covered": summary["n_cells_preboom_covered"],
            "n_domain": summary["n_domain_cells"],
            "neg_mass": summary["delta_mwp_negative_cell_mass"],
            "seg_only_delta": summary["delta_est_mwp_rc_segmentation_only"],
            "n_onset": int(grid.n_onset_buildings.sum()),
            "onset_mwp": round(float(grid.onset_mwp.sum()), 1),
        },
    }

    title = aoi.replace("_", " ").title()
    html = GROWTH_EVIDENCE_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} PV Growth Atlas",
        "__H1__": f"How much solar {title} added since before the boom",
        "__AOI_TITLE__": title,
        "__LEDE_HTML__": (
            f"The evidence atlas's own instruments &mdash; the TerraMind segmentation "
            f"fine-tune and the per-building roofclf classifier &mdash; applied "
            f"identically to a pre-boom (2021/22) and a current Sentinel-2 composite, "
            f"then differenced per cell. One checkpoint, one calibration, both epochs: "
            f"what changed between the maps is the country, not the instrument."
        ),
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else growth_dir / f"{aoi}_pv_growth_evidence_atlas.html"
    out.write_text(html)
    log.info(
        "Wrote growth evidence atlas (Δ total %.1f MWp = ground %.1f + roof %.1f + "
        "sub400 %.1f; current %.1f vs pre-boom %.1f) -> %s",
        d["total"], d["ground"], d["roof"], d["sub400"], cur["total"], pre["total"], out,
    )
    return out


# --------------------------------------------------------------------------------------
# Evidence-atlas uncertainty
# --------------------------------------------------------------------------------------
EVIDENCE_N_DRAWS = 1000
EVIDENCE_DRAWS_SEED = 20260811

# The ONLY term in the evidence atlas's intervals that is a stated judgement rather than a
# measurement, applied to the out-of-domain AND-gate component alone (a uniform
# multiplicative factor on it). It exists because that component is a strict
# extrapolation: every out-of-domain cell nationally sits BELOW the calibrated
# building-density band (measured 2026-08-11 -- all of them below, none above), median
# out-of-domain density ~6x sparser than the least-dense calibration quadrat, so no
# quadrat anywhere in this project constrains its coverage ratio in either direction.
# `coverage_ratio_bootstrap_factors` cannot price this: resampling the 15 urban/semi-urban
# quadrats measures how much the answer moves within the kind of place that HAS been
# mapped, which is a different question from whether that fit transfers to rural roofs at
# all. Skewed down rather than symmetric because the plausible failure is over-crediting
# sparse rural roofs the classifier was never calibrated on, not under-crediting them.
# Deliberately visible and configurable (`extrapolation_ci90`), and reported separately in
# `totals.uncertainty.components` so a reader can see the Best interval with and without
# it -- the alternative (leaving this component out of the interval entirely) would report
# a *narrower* Best interval precisely because part of it is less well founded, which is
# the wrong direction.
OUTDOMAIN_EXTRAPOLATION_CI90 = (0.25, 1.25)

# Which atlas component each `density` estimator backs, so a missing interval can be checked
# against whether that component actually carries any capacity in this run.
_SEG_COMPONENT = {
    "est_mwp_rc_roof": "seg_roof_outdomain",
    "est_mwp_rc_ground": "seg_ground",
}


def _segmentation_total_factors(
    density_dir: Path, meta: dict, keys: tuple[str, ...], n_draws: int, seed: int
) -> tuple[dict[str, np.ndarray], str, list[str]]:
    """Relative (draw / point) factors for `density`'s own >= 400 m2 estimators.

    Prefers `density/total_draws.parquet`, the exact national draw vectors `aggregate`
    writes (each already carries both the bin-level calibration posterior AND the
    area->capacity constant, since `_composed_mwp_draws` applies the kWp draws itself --
    so a caller must NOT multiply these by a kWp factor a second time). Falls back to a
    lognormal matched to `meta`'s `*_lo`/`*_hi` for density runs that predate that file,
    which is an approximation in one specific way worth knowing: it reproduces the
    published 90% interval and the published point estimate, but assumes the shape between
    them is lognormal and drops the correlation between the roof and ground estimators
    (they are drawn independently in the fallback, which slightly narrows their sum).

    Returns `(factors, method, unresolved)`. `unresolved` lists estimators for which neither
    source carried an interval -- their factor is all-ones, which is NOT "no uncertainty" but
    "uncertainty this function could not find", and the caller must substitute something
    rather than accept a zero-width interval. Density runs before 2026-08-11 have no
    `est_mwp_rc_ground_lo/hi` pair in `meta`, and ground-mount converts at the widest prior
    in the pipeline, so that case is real and was silently dropping the largest single term
    from the Best tier's interval before this was returned explicitly.
    """
    from earthpv.capacity_calibration import CI_PCT, _lognormal_draws

    draws_path = Path(density_dir) / "total_draws.parquet"
    out: dict[str, np.ndarray] = {}
    if draws_path.exists():
        d = pd.read_parquet(draws_path)
        absent = [k for k in keys if k not in d.columns]
        if not absent:
            idx = np.arange(n_draws) % len(d)
            for k in keys:
                v = d[k].to_numpy(float)[idx]
                point = float(meta.get(f"total_{k}", 0.0))
                out[k] = v / point if point else np.ones(n_draws)
            return out, f"exact draws from {draws_path.name} ({len(d)} replicates)", []
        log.warning(
            "%s exists but lacks %s -- falling back to a lognormal matched to meta's "
            "credible intervals", draws_path, absent,
        )

    rng = np.random.default_rng(seed)
    unresolved: list[str] = []
    for k in keys:
        point = float(meta.get(f"total_{k}", 0.0))
        lo = meta.get(f"total_{k}_lo")
        hi = meta.get(f"total_{k}_hi")
        if not point or lo is None or hi is None or not 0 < float(lo) < float(hi):
            out[k] = np.ones(n_draws)
            unresolved.append(k)
            continue
        out[k] = _lognormal_draws(rng, 1.0, (float(lo) / point, float(hi) / point), n_draws)
    return out, (
        f"lognormal matched to meta's {CI_PCT[0]:.0f}/{CI_PCT[1]:.0f} intervals "
        f"({draws_path.name} absent -- re-run `earthpv density` for exact draws)"
    ), unresolved


def _aligned_coverage_factors(
    boot: dict, n_draws: int, label: str
) -> tuple[np.ndarray, dict | None]:
    """Coverage-ratio bootstrap factors from a capacity summary, stretched to `n_draws`.

    Indexing is `arange(n_draws) % n_boot`, the SAME index for every component, which is
    the whole point: all four capacity functions resample the same quadrat list under the
    same fixed seed (`sub400_capacity.COVERAGE_BOOTSTRAP_SEED`), so replicate b means the
    same resampled quadrat set everywhere, and reusing one index vector keeps those
    components' errors correlated when they are added. Drawing each component's factors
    independently would treat four estimates built from ONE calibration set as
    independent and report a Best interval narrower than the evidence supports.

    Returns ones (and None) when a summary carries no bootstrap -- an older artifact, or
    `--coverage-boot 0`. That is a silently NARROWER interval, so the caller records which
    components were missing in `totals.uncertainty.coverage_bootstrap_missing`.
    """
    factors = (boot or {}).get("factors") or []
    if not factors:
        log.warning(
            "Evidence atlas: %s has no coverage-ratio bootstrap -- its interval will omit "
            "quadrat-resampling uncertainty (re-run its capacity function to add it)", label,
        )
        return np.ones(n_draws), None
    arr = np.asarray(factors, dtype=float)
    return arr[np.arange(n_draws) % len(arr)], {
        "n_boot": int(len(arr)),
        "factor_ci90": (boot or {}).get("factor_ci90"),
        # Reported because it is NOT always ~1.0, and the direction is a finding rather than
        # a defect: the point fit uses every calibrated quadrat, while a resample often omits
        # whichever ones carry the highest coverage in the largest size bins, so a mean below
        # 1 says the published point sits at the high end of what equally plausible quadrat
        # sets produce (measured 2026-08-11: 0.99 for both sub-400 m2 components, 0.93 for
        # the >= 400 m2 rooftop one). Deliberately NOT bias-corrected away -- the factor of
        # 1.0 still falls inside every component's own interval, so the published number
        # stays inside its reported range while the skew remains visible.
        "factor_mean": (boot or {}).get("factor_mean"),
        "seed": (boot or {}).get("seed"),
    }


def _capacity_summary_for(buildings_path: Path | None, method: str) -> dict:
    """The `*_summary.json` a capacity function wrote next to its building parquet, found by
    its own `method` field rather than by filename.

    Filenames are not derivable from each other here (`sub400_outdomain_and_gate_
    incremental_buildings.parquet` sits beside `sub400_outdomain_summary.json`), and
    hard-coding the pairs would break silently the next time one is renamed -- picking the
    sidecar whose recorded `method` matches cannot mismatch. Returns `{}` when the parquet
    path is None or no sidecar matches, which downstream reads as "no bootstrap for this
    component" (a warning, not an error, since older artifacts predate it).
    """
    if buildings_path is None:
        return {}
    for path in sorted(Path(buildings_path).parent.glob("*_summary.json")):
        try:
            d = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:  # noqa: PERF203
            log.warning("Evidence atlas: could not read %s (%s)", path, e)
            continue
        if d.get("method") == method:
            return d
    log.warning(
        "Evidence atlas: no *_summary.json with method=%s beside %s -- that component's "
        "coverage-ratio uncertainty will be omitted from the tier intervals",
        method, buildings_path,
    )
    return {}


def _ci(draws: np.ndarray) -> list[float]:
    from earthpv.capacity_calibration import CI_PCT

    return [round(float(v), 1) for v in np.percentile(draws, CI_PCT)]


def _evidence_uncertainty(
    *,
    density_dir: Path,
    meta: dict,
    kwp_mod: float,
    kwp_land: float,
    components: dict[str, float],
    boots: dict[str, dict],
    total_verified: float,
    total_best: float,
    n_draws: int = EVIDENCE_N_DRAWS,
    seed: int = EVIDENCE_DRAWS_SEED,
    extrapolation_ci90: tuple[float, float] = OUTDOMAIN_EXTRAPOLATION_CI90,
) -> dict:
    """90% intervals for the evidence atlas's two tier totals, composed from every
    uncertainty this pipeline actually measures.

    Until 2026-08-11 the evidence atlas -- the project's documented primary output --
    reported Verified and Best as bare point estimates, while the older
    `build_atlas`/`_build_estimator_atlas` path had carried credible intervals all along.
    That was the wrong way round: the two headline figures moved by 20-35% five times in
    the week before this was written, purely from recalibration (placement-split
    precision, dissolved OSM, a widened density domain, one added quadrat), and a reader
    had no way to see that from the page.

    Each tier is built as a sum of components, each multiplied by its own relative-error
    factor, sharing draws where the underlying errors are shared:

    - **The two area->capacity constants** (`capacity_calibration.kwp_draws`, lognormal on
      the published `KWP_MODULE_CI90`/`KWP_LAND_CI90`). ONE module draw vector multiplies
      every module-area component and one land vector every site-area component, because
      it is the same physical constant in all of them -- drawing per component would
      cancel out most of its effect, which is exactly wrong for a constant that applies
      to the whole country at once.
    - **Segmentation's >= 400 m2 recall/precision posterior** (`_segmentation_total_
      factors`). Already includes its own kWp uncertainty, so those components are NOT
      multiplied by the kWp factors again.
    - **The coverage ratio's quadrat-resampling error** (`_aligned_coverage_factors`), on
      all four roofclf-based components, correlated across them.
    - **The out-of-domain extrapolation** (`OUTDOMAIN_EXTRAPOLATION_CI90`), a stated
      judgement, on that one component only.

    Two things this interval does NOT cover, and no arithmetic here can fix: the
    calibration quadrats are purposive rather than a probability sample, so this is not a
    design-based national margin of error; and Rule-1 completeness is relative to the
    mapping imagery's epoch, not the composite's, which biases measured precision and
    `base_rate` low in a direction this says nothing about. Both are stated on the page.

    `components` are the point MWp values, keyed as in the returned breakdown. The invariant
    the caller can rely on: the component points sum to each published tier total, up to an
    explicit `best_floor_offset` carrying `mwp_best`'s per-cell floor at `mwp_verified`
    (a deterministic correction, applied to every draw rather than given an error of its
    own). This is asserted, not assumed -- a mismatch means a component was added to the
    atlas and not to this function, and would silently report an interval for a different
    quantity than the number beside it.
    """
    from earthpv import capacity_calibration as cc

    kwp = cc.kwp_draws(n_draws=n_draws, module=kwp_mod, land=kwp_land, seed=seed)
    f_mod = kwp["module"] / kwp_mod
    f_land = kwp["land"] / kwp_land

    seg_keys = ("est_mwp_rc_roof", "est_mwp_rc_ground")
    f_seg, seg_method, seg_unresolved = _segmentation_total_factors(
        density_dir, meta, seg_keys, n_draws, seed + 1
    )
    # An estimator whose interval could not be found must not silently contribute a
    # zero-width one. Substitute the area->capacity prior for its own placement -- the
    # single largest term in it -- using the SAME draw vector the hand-mapped components
    # use, since it is literally the same constant. This still omits that estimator's
    # calibration posterior (precision/recall), so the substitution is recorded as a
    # degradation, not treated as equivalent.
    seg_degraded: list[str] = []
    for key, fallback in (
        ("est_mwp_rc_roof", f_mod), ("est_mwp_rc_ground", f_land),
    ):
        if key in seg_unresolved and components.get(_SEG_COMPONENT[key], 0.0):
            f_seg[key] = fallback
            seg_degraded.append(key)
            log.warning(
                "Evidence atlas: %s has no interval in meta (older density run) -- "
                "substituting the kWp/m2 prior alone for it, which omits its "
                "precision/recall posterior. Re-run `earthpv density` to fix properly.",
                key,
            )

    cov: dict[str, np.ndarray] = {}
    cov_meta: dict[str, dict] = {}
    missing: list[str] = []
    for key in ("small_low", "small_central", "small_outdomain", "ge400_roof"):
        # A component the atlas was never given (no `--sub400-outdomain-cells`, say)
        # contributes exactly zero MWp, so its coverage-ratio bootstrap cannot move the
        # published interval -- asking for it would only warn about a calibration nothing
        # in the number depends on.
        if not components.get(key):
            cov[key] = np.ones(n_draws)
            continue
        f, info = _aligned_coverage_factors(boots.get(key, {}), n_draws, key)
        cov[key] = f
        if info is None:
            missing.append(key)
        else:
            cov_meta[key] = info

    rng = np.random.default_rng(seed + 2)
    f_extrap = rng.uniform(extrapolation_ci90[0], extrapolation_ci90[1], n_draws)

    c = components
    # Verified: hand-mapped OSM (exact areas, so only the conversion constant moves) plus
    # the AND-gate's coverage-ratio-weighted small-PV.
    verified_parts = {
        "osm_roof": c["osm_roof"] * f_mod,
        "osm_ground": c["osm_ground"] * f_land,
        "small_low": c["small_low"] * cov["small_low"] * f_mod,
    }
    # Best: the OSM the model did not already find, its own >= 400 m2 estimate (roofclf
    # in-domain, segmentation outside it, segmentation ground everywhere) and the two
    # roofclf-alone small-PV components.
    best_parts = {
        "osm_unmatched_roof": c["osm_unmatched_roof"] * f_mod,
        "osm_unmatched_ground": c["osm_unmatched_ground"] * f_land,
        "ge400_roof": c["ge400_roof"] * cov["ge400_roof"] * f_mod,
        "seg_roof_outdomain": c["seg_roof_outdomain"] * f_seg["est_mwp_rc_roof"],
        "seg_ground": c["seg_ground"] * f_seg["est_mwp_rc_ground"],
        "small_central": c["small_central"] * cov["small_central"] * f_mod,
    }
    # Only carried when the out-of-domain extrapolation was actually supplied: a zero
    # component would otherwise publish an empty slice, an all-zero table column and a
    # legend key for a quantity this atlas does not report.
    if c["small_outdomain"]:
        best_parts["small_outdomain"] = (
            c["small_outdomain"] * cov["small_outdomain"] * f_mod * f_extrap
        )

    v_point = sum(components[k] for k in ("osm_roof", "osm_ground", "small_low"))
    b_point = sum(components[k] for k in best_parts)
    floor_offset = total_best - b_point
    for name, point, target in (
        ("mwp_verified", v_point, total_verified), ("mwp_best", b_point + floor_offset, total_best),
    ):
        if abs(point - target) > 0.5:
            raise AssertionError(
                f"Evidence-atlas uncertainty: {name} components sum to {point:.1f} MWp but "
                f"the published total is {target:.1f} MWp. A component was added to the "
                "atlas without being added to _evidence_uncertainty, so the interval would "
                "describe a different quantity than the number next to it."
            )

    v_draws = sum(verified_parts.values())
    b_draws = sum(best_parts.values()) + floor_offset
    # Best is defined as "the highest defensible figure", so it cannot read below Verified
    # in a draw any more than it can in a cell (`n_cells_best_floored`). Rarely binds --
    # nationally the two are far apart -- but reported rather than applied silently.
    n_below = int((b_draws < v_draws).sum())
    b_draws = np.maximum(b_draws, v_draws)

    # The Best interval WITHOUT the extrapolation judgement, so its contribution is visible
    # rather than baked in: same draws, that one component held at its point value.
    b_draws_no_extrap = (
        sum(v for k, v in best_parts.items() if k != "small_outdomain")
        + c["small_outdomain"] * cov["small_outdomain"] * f_mod
        + floor_offset
    )

    return {
        "n_draws": n_draws,
        "ci_pct": list(cc.CI_PCT),
        "mwp_verified_ci": _ci(v_draws),
        "mwp_best_ci": _ci(b_draws),
        "mwp_best_ci_without_extrapolation": _ci(np.maximum(b_draws_no_extrap, v_draws)),
        "best_floor_offset_mwp": round(float(floor_offset), 1),
        "n_draws_best_below_verified": n_below,
        "components": {
            k: {"mwp": round(float(components[k]), 1), "ci": _ci(v)}
            for parts in (verified_parts, best_parts) for k, v in parts.items()
        },
        "segmentation_factor_method": seg_method,
        "segmentation_estimators_without_interval": seg_unresolved,
        "segmentation_estimators_using_kwp_prior_only": seg_degraded,
        "coverage_bootstrap": cov_meta,
        "coverage_bootstrap_missing": missing,
        "kwp_module_ci90": list(cc.KWP_MODULE_CI90),
        "kwp_land_ci90": list(cc.KWP_LAND_CI90),
        "outdomain_extrapolation_ci90": list(extrapolation_ci90),
        "not_covered": [
            "purposive (not probability-sampled) calibration quadrats -- this is not a "
            "design-based national margin of error",
            "Rule-1 completeness is relative to the mapping imagery's epoch, not the "
            "Sentinel-2 composite's, which biases measured precision and base_rate low",
            "roofclf's own threshold transfer between density regimes",
        ],
    }


def build_evidence_atlas(
    aoi: str, density_dir: Path,
    osm_solar_path: Path, candidates_path: Path,
    low_buildings_path: Path, central_buildings_path: Path,
    out: Path | None = None, zoom_out_frac: float = 0.0, labels_dir: Path = Path("data/labels"),
    ge400_roof_buildings_path: Path | None = None,
    sub400_outdomain_buildings_path: Path | None = None,
    pose_summary_csv: Path | None = None,
    pose_history_note: str = "", pose_data_note: str = "",
    imagery_date_range: str | None = None,
    downloads: list[dict] | None = None,
    data_release_url: str | None = None,
) -> Path:
    """Two-tier evidence atlas -- promoted 2026-08-01 to the project's default capacity
    atlas, superseding `build_sub400_bracket_atlas`'s Low/Central/High/All-PV framing
    (kept above for reference; no longer the CLI's default path). A third tier, Ceiling
    (roofclf flagged nationwide at a flat 0.5 precision weight, restricted only to
    buildings with no existing large detection nearby, plus every large installation
    already known), was removed 2026-08-06 at the owner's request: a lower deployment
    threshold from a later roofclf refit roughly doubled it (37,173 -> 79,221 MWp small-PV
    component) with no accompanying validation, so it had stopped being a meaningful
    bound and the owner judged it not worth carrying forward. `high_buildings_path` /
    `roofclf_capacity.incremental_capacity` are unaffected -- `build_sub400_bracket_atlas`
    still uses them for its own High view. Each remaining tier is a different STANDARD OF
    PROOF, not a different point estimate on the same scale:

    - **Verified**: every PV installation hand-mapped in OpenStreetMap (`osm_solar_path`,
      any placement, converted at the module constant for rooftop and the land constant
      for everything else), plus sub-400 m2 buildings where roofclf AND SPPI
      independently agree (`low_buildings_path`). No model detection enters this tier by
      itself.
    - **Best**: the hand-mapped population minus what the model already found -- so the
      two don't double count, `candidates_path`'s `osm_matched_id` marks the overlap --
      plus the model's own recall-corrected >= 400 m2 detections (`grid.est_mwp_rc`,
      every placement), plus the roofclf-alone density estimate
      (`central_buildings_path`). This project's own pick, the highest figure it
      defends.

    **`ge400_roof_buildings_path` (added 2026-08-07): roofclf replaces segmentation's own
    rooftop estimate for >= 400 m2 buildings, inside the density-matched domain only.**
    Measured on the same buildings (13 quadrats, LOQO): roofclf AUC 0.896 vs
    segmentation's own raster AUC 0.726-0.775 (`seg_mean`/`seg_mean_main`, both the
    undocumented `pk16085` checkpoint and the actual production `v3_combined_india` one),
    and at matched ~54% precision, recall 94.2% (roofclf) vs 19-25% (segmentation) --
    segmentation is a known weak instrument for small PV, including small PV *on large
    buildings*, which is exactly the >= 400 m2 rooftop population this replaces.
    `roofclf_ge400_capacity.domain_restricted_ge400_roof_capacity` produces this path's
    buildings (`est_kwp_ge400_roof` per building); `grid.est_mwp_rc_roof` (segmentation)
    stays authoritative outside the ~92-cell domain, where roofclf has no calibration
    evidence. Ground-mount (`grid.est_mwp_rc_ground`) is untouched either way -- roofclf
    has no footprint to score there. Optional: omitting it falls back to the pre-2026-08-07
    behavior (segmentation's own `est_mwp_rc`, roof+ground combined, unchanged) for AOIs
    with no roofclf national scoring yet.

    **`sub400_outdomain_buildings_path` (added 2026-08-11): roofclf-AND-SPPI agreement
    outside the density-calibrated domain, folded into Best only.** A manual JOSM
    validation pass for cells outside the calibrated domain (drawn to test whether that
    domain could be widened with evidence) turned out to be blocked by reference imagery
    too old to confirm or refute recently-installed small PV -- see
    `docs/methods/roofclf-national-validation.md`. Requiring two independently-built
    detectors (roofclf, a supervised classifier; SPPI, a zero-training spectral index) to
    agree is used as a substitute standard of evidence for exactly the cells that cannot
    currently be checked by eye. `sub400_capacity.out_of_domain_and_gate_capacity`
    produces this path's buildings; its own docstring states the caveat that must travel
    with this number: EVERY out-of-domain cell nationally sits outside the calibrated
    density band in one direction (measured 2026-08-11: all 4,300 below, none above), so
    this is a strict extrapolation of a fit measured on 13 urban/semi-urban quadrats
    across the rural remainder of the country, not a modest widening of it. It is added
    to `mwp_best` alongside `small_central`, marked separately in the map/totals as
    `small_outdomain` (never merged into `small_central` itself) and cells it touches get
    their own `is_extended` flag distinct from `in_domain` -- a reader must be able to
    tell "calibrated" and "extrapolated" apart, the same reasoning that keeps Verified
    and Best as separate tiers in the first place. Optional; omitting it reproduces the
    pre-2026-08-11 Best-estimate total exactly.

    Ported from `scripts/build_pakistan_pv_evidence_overview.py` (see that file's git
    history for the full derivation and the 2026-08-01 redefinition of Ceiling) with two
    correctness fixes:

    - The building-level parquets are now aggregated to cells via
      `_join_buildings_to_grid_cells` -- a spatial join against THIS run's own grid
      polygons -- rather than a plain string `cell`-id match. The id-matching join the
      standalone script used silently drops any building whose id came from a manifest
      that numbered cells differently than this run's grid (the same failure mode
      `build_combined_atlas`'s docstring measured directly: a naive id join lost cells a
      spatial join does not). Buildings that fall outside every cell of this run's grid
      are excluded from the map and totals with a warning, the same as every other atlas
      builder here -- not reconstructed from a guessed cell origin, which
      `_join_buildings_to_grid_cells`'s own docstring explains is unsafe.
    - **OSM-matched dedup is now geometric, not an id lookup (2026-08-06 fix).**
      `postprocess.replace_with_osm_geometry` assigns `osm_matched_id` as a one-to-one
      nearest match: one candidate polygon can only ever carry a single OSM id, even
      when it overlaps many mapped installations (a common shape in dense residential
      quadrats). Using that id set to mark OSM features as "found by the model" left
      2,007 ids covering only 1,674 of 16,085 OSM installations, so `osm_mwp_unmatched`
      counted the model's own detections as if they were still missing -- measured
      2026-08-06 at ~1,900 MWp of double-counting. Replaced with
      `~export.new_lead_mask(osm, cand, min_distance_m=NEAR_BUILDING_M)`, the same
      proximity test the rest of the pipeline uses for "is this a genuinely new lead."
    - **`mwp_best` is now floored at `mwp_verified` per cell (2026-08-06 fix).** Best
      subtracts a cell's matched OSM value and substitutes the model's own recall- and
      density-based estimate, which can be smaller than the mapped value it replaced --
      e.g. Quaid-e-Azam Solar Park scored Verified 866 MWp against Best 243 MWp before
      this fix, since `est_mwp_rc` for that cell was ~0. Best is defined as "the highest
      defensible figure," so it can never legitimately read below Verified in the same
      cell; `np.maximum(mwp_best, mwp_verified)` enforces that ordering after both are
      computed, and `n_cells_best_floored` records how often it had to.

    **Two more sections, both optional and both re-using data this call already has
    (added 2026-08-13):**

    - **A "Capacity per size bin, rooftop vs ground-mount" chart**, the same one
      `build_size_distribution_atlas` publishes as its own page, embedded natively
      (same SVG/CSS, no iframe) since it already shares this template's colour tokens.
      Computed via `_size_distribution_data` with the exact same six inputs this
      function itself takes, so the two numbers are the same calculation, not two
      independent ones re-verified against each other -- unlike the standalone page,
      which is built from a separate CLI invocation and can drift by the residual
      `docs/results/capacity-by-size.md` documents (candidates that fall just outside
      every grid cell's polygon). Only rendered when `ge400_roof_buildings_path` is
      given, matching every other roofclf-dependent section on this page; an AOI with
      no roofclf national scoring yet (e.g. Gujarat) gets the map without this chart
      rather than a chart of zeroes.
    - **The panel-pose survey** (`pose.py`, glint-derived tilt/azimuth), embedded
      NATIVELY (2026-08-13, superseding an earlier iframe version -- an iframe forced a
      second internal scrollbar on a sub-page, which read as a worse experience than
      the extra CSS-scoping work needed to inline it properly). It keeps its own serif
      "voice", distinct from this page's night-lights palette, exactly as the
      standalone page does -- but every one of its CSS custom properties and classes is
      declared under the `.pose-native` container (`--pose-*`, `.pose-*`) rather than on
      `:root`/bare tag selectors, so nothing it defines leaks onto the rest of this
      page (its original standalone-page CSS styled bare `body`/`h1`/`header`/`footer`/
      `svg text`, which would otherwise repaint this atlas's own map and KPI strip).
      `pose_summary_csv` is the same glint-validation summary CSV
      `build_pose_survey_page` takes; `pose.compute_pose_survey_data` (shared with that
      function) computes chart data and every stat once. Omit it and no pose section is
      written at all.

    **`imagery_date_range` (added 2026-08-14): a free-text label for the Sentinel-2
    scene window the composites were built from** (e.g. "Oct 2025 - Jun 2026"), shown
    in the page footer next to a `generated_at` timestamp (always stamped, this
    function's own run date) -- so a reader can tell how stale the underlying imagery
    and the atlas build itself are without having to ask. There is no single
    pipeline-tracked source for this yet: composites for one AOI can mix cells built by
    `earthpv compose` (whatever `--window` that run used, `imagery.annual_composite`'s
    own default otherwise) with cells reused from a `source_region` cache built by a
    different project on its own schedule, so this is passed in by the caller rather
    than derived here. Omit it and the footer shows the generation date alone.

    **`downloads` / `data_release_url` (added 2026-08-14): a Downloads section linking to a
    point-in-time data release** (parquets, calibration boundaries, the pose survey, raw
    detections, model checkpoint) hosted as GitHub Release assets, since `data/` itself is
    gitignored and several of these files are well over what git handles comfortably.
    `downloads` is a list of `{"file", "label", "note", "size_bytes"}` dicts (see
    `configs/pakistan_atlas_downloads.json` for the Pakistan manifest); `data_release_url` is
    the release's asset base URL (`.../releases/download/<tag>`), joined with each `file` to
    build the actual link. Omit either and no Downloads section is written -- this is a frozen
    snapshot the atlas does not regenerate on its own, so an AOI with no release yet should not
    show a section pointing at nothing.
    """
    density_dir = Path(density_dir)
    out = Path(out) if out else density_dir / f"{aoi}_pv_evidence_atlas.html"
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    meta = json.loads((density_dir / "meta.json").read_text())
    if "est_mwp_rc" not in grid.columns:
        raise ValueError(
            f"{density_dir}/grid.geoparquet has no est_mwp_rc column -- run "
            "`earthpv calibrate-candidates` before `density` so recall-correction "
            "exists; the evidence atlas needs the large-PV instrument for the Best "
            "tier."
        )
    from earthpv import capacity_calibration as cc
    from earthpv.config import Settings

    title = aoi.replace("_", " ").title()
    division = (Settings.load().aois.get(aoi) or {}).get("division") or {}
    if division.get("subtype") == "region" and division.get("name"):
        # OSM's `ISO3166-1` tag is country-only; a province/state-level AOI (e.g.
        # Punjab, Gujarat) has to be matched by boundary name instead, at
        # admin_level=4 (the level used for provinces/states/Länder in every
        # country this project currently targets).
        overpass_area_tags = (
            '["boundary"="administrative"]\n'
            '  ["admin_level"="4"]\n'
            f'  ["name"="{division["name"]}"]'
        )
    else:
        overpass_area_tags = (
            '["boundary"="administrative"]\n'
            '  ["admin_level"="2"]\n'
            f'  ["ISO3166-1"="{division.get("country", "")}"]'
        )
    kwp_mod = meta.get("kwp_per_m2_module", cc.DEFAULT_KWP_PER_M2_MODULE)
    kwp_land = meta.get("kwp_per_m2_land", cc.DEFAULT_KWP_PER_M2_LAND)

    # --- hand-mapped OSM PV, per cell, split by whether the model already found it.
    #     Geometric proximity, not `osm_matched_id`: that id is assigned one-to-one by
    #     `postprocess.replace_with_osm_geometry`, so one candidate blob overlapping many
    #     mapped installations only ever "claims" one of them -- see this function's
    #     docstring for the ~1,900 MWp of double-counting that undercounted matches.
    from earthpv.density import capacity_relevant_candidates
    from earthpv.export import new_lead_mask
    from earthpv.labels import dissolve_overlapping
    from earthpv.postprocess import NEAR_BUILDING_M

    osm = gpd.read_parquet(osm_solar_path)
    # Two OSM features (a `plant` perimeter and a nested `generator` way, or two
    # overlapping mapping passes) can describe one real installation -- summing their
    # individual areas double-counts it (measured 2026-08-10: ground-mount OSM area
    # shrinks 24.4% once dissolved; see labels.dissolve_overlapping's docstring).
    osm = dissolve_overlapping(osm, group_col="placement")
    cand = gpd.read_parquet(candidates_path)
    # Match against the SAME population that actually earns capacity, not the raw
    # candidate file: an OSM installation matched only by a candidate this run
    # excludes from capacity (a non-exempt oversize blob) is not "already found by
    # the model" in any sense `mwp_large` reflects -- counting it as matched would
    # double-subtract it from `osm_mwp_unmatched` for nothing (measured 2026-08-10 at
    # 1,704 MWp nationally, see capacity_relevant_candidates's docstring).
    cand, _ = capacity_relevant_candidates(cand)
    osm = osm.copy()
    osm["matched"] = ~new_lead_mask(osm, cand, min_distance_m=NEAR_BUILDING_M)
    osm["kwp"] = np.where(
        osm["placement"] == "rooftop", osm["area_m2"] * kwp_mod, osm["area_m2"] * kwp_land
    )
    pts = osm.copy()
    pts["geometry"] = pts.geometry.representative_point()
    joined_osm = gpd.sjoin(pts, grid[["cell", "geometry"]], predicate="within", how="left")
    n_unmatched_osm = int(joined_osm["cell"].isna().sum())
    if n_unmatched_osm:
        log.warning(
            "Evidence atlas: %d of %d OSM-mapped installations fall outside every cell "
            "of this %d-cell grid -- excluded from the map/totals below.",
            n_unmatched_osm, len(joined_osm), len(grid),
        )
    in_grid_osm = joined_osm.dropna(subset=["cell"])
    n_osm_ge400 = int((in_grid_osm["area_m2"] >= 400.0).sum())
    n_osm_lt400 = int((in_grid_osm["area_m2"] < 400.0).sum())
    osm_by_cell = in_grid_osm.groupby("cell").apply(
        lambda d: pd.Series({
            "osm_mwp": d["kwp"].sum() / 1000,
            "osm_mwp_unmatched": d.loc[~d["matched"], "kwp"].sum() / 1000,
            "osm_n": float(len(d)),
        }),
        include_groups=False,
    )
    # Same population, split by which kWp/m2 constant converted it, for the uncertainty
    # composition below: rooftop is module area, everything else is site area, and the two
    # constants have their own (very different) priors. Derived from `in_grid_osm` rather
    # than `osm` so these parts sum to the cell-aggregated totals exactly, excluding the
    # features that fell outside the grid.
    _osm_roof_m = in_grid_osm["placement"] == "rooftop"
    osm_parts = {
        "osm_roof": float(in_grid_osm.loc[_osm_roof_m, "kwp"].sum()) / 1000,
        "osm_ground": float(in_grid_osm.loc[~_osm_roof_m, "kwp"].sum()) / 1000,
        "osm_unmatched_roof": float(
            in_grid_osm.loc[_osm_roof_m & ~in_grid_osm["matched"], "kwp"].sum()
        ) / 1000,
        "osm_unmatched_ground": float(
            in_grid_osm.loc[~_osm_roof_m & ~in_grid_osm["matched"], "kwp"].sum()
        ) / 1000,
    }

    by_low = _join_buildings_to_grid_cells(
        gpd.read_parquet(low_buildings_path), "est_kwp_sub400_and_gate", grid
    ) / 1000.0
    by_central = _join_buildings_to_grid_cells(
        gpd.read_parquet(central_buildings_path), "est_kwp_sub400", grid
    ) / 1000.0
    by_outdomain = (
        _join_buildings_to_grid_cells(
            gpd.read_parquet(sub400_outdomain_buildings_path), "est_kwp_sub400_outdomain", grid
        ) / 1000.0
        if sub400_outdomain_buildings_path is not None
        else pd.Series(dtype=float)
    )

    grid = grid.copy()
    grid["osm_mwp"] = grid["cell"].map(osm_by_cell.get("osm_mwp", pd.Series(dtype=float))).fillna(0.0)
    grid["osm_mwp_unmatched"] = grid["cell"].map(
        osm_by_cell.get("osm_mwp_unmatched", pd.Series(dtype=float))
    ).fillna(0.0)
    grid["osm_n"] = grid["cell"].map(osm_by_cell.get("osm_n", pd.Series(dtype=float))).fillna(0.0)
    grid["small_low"] = grid["cell"].map(by_low).fillna(0.0)
    grid["small_central"] = grid["cell"].map(by_central).fillna(0.0)
    grid["small_outdomain"] = grid["cell"].map(by_outdomain).fillna(0.0)
    grid["in_domain"] = grid["cell"].isin(by_low.index) | grid["cell"].isin(by_central.index)
    n_domain_cells = int(grid["in_domain"].sum())
    # Distinct from `in_domain`: these cells carry an EXTRAPOLATED small-PV contribution
    # (out_of_domain_and_gate_capacity, no calibration quadrat in their density range),
    # never a calibrated one -- must render differently on the map, not folded into the
    # same "checked" visual as in_domain.
    grid["is_extended"] = grid["cell"].isin(by_outdomain.index)

    # roofclf replaces segmentation's rooftop estimate inside the density-matched domain
    # (see docstring); outside it, segmentation's own est_mwp_rc_roof is the only
    # evidence-backed number, so it stays. Falls back to the pre-2026-08-07 combined
    # est_mwp_rc when no ge400 rooftop path is given (e.g. an AOI with no roofclf yet).
    ge400_domain_cells: set[str] = set()
    if ge400_roof_buildings_path is not None:
        by_ge400_roof = _join_buildings_to_grid_cells(
            gpd.read_parquet(ge400_roof_buildings_path), "est_kwp_ge400_roof", grid
        ) / 1000.0
        ge400_domain_cells = set(by_ge400_roof.index)
        grid["mwp_large_roof"] = np.where(
            grid["cell"].isin(ge400_domain_cells),
            grid["cell"].map(by_ge400_roof).fillna(0.0),
            grid["est_mwp_rc_roof"],
        )
        grid["in_domain"] = grid["in_domain"] | grid["cell"].isin(ge400_domain_cells)
        n_domain_cells = int(grid["in_domain"].sum())
    else:
        grid["mwp_large_roof"] = grid["est_mwp_rc_roof"]
    grid["mwp_large"] = grid["mwp_large_roof"] + grid["est_mwp_rc_ground"]

    grid["mwp_verified"] = grid["osm_mwp"] + grid["small_low"]
    grid["mwp_best"] = (
        grid["osm_mwp_unmatched"] + grid["mwp_large"] + grid["small_central"] + grid["small_outdomain"]
    )
    # Best is "the highest defensible figure" -- it must never read below Verified in the
    # same cell. It can, before this floor: Best drops a cell's matched-OSM value in favor
    # of the model's own est_mwp_rc/small_central, which is sometimes smaller (e.g.
    # Quaid-e-Azam Solar Park: Verified 866 MWp vs Best 243 MWp pre-fix, since est_mwp_rc
    # there was ~0). See this function's docstring, 2026-08-06 fix.
    n_cells_best_floored = int((grid["mwp_best"] < grid["mwp_verified"]).sum())
    if n_cells_best_floored:
        log.info(
            "Evidence atlas: flooring mwp_best at mwp_verified in %d/%d cells "
            "(model estimate below the mapped value it was meant to supersede)",
            n_cells_best_floored, len(grid),
        )
    grid["mwp_best"] = np.maximum(grid["mwp_best"], grid["mwp_verified"])

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         round(float(r.mwp_verified), 3), round(float(r.mwp_best), 3),
         round(float(r.osm_mwp), 3), int(r.osm_n),
         round(float(r.small_low), 3), round(float(r.small_central), 3),
         round(float(r.mwp_large), 3), int(r.in_domain), int(r.n_pv_buildings),
         round(float(r.small_outdomain), 3), int(r.is_extended)]
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
        reg_regions = reg[reg.level == "region"]
        keep = [
            "mwp_verified", "mwp_best", "osm_mwp", "mwp_large",
            "small_low", "small_central", "small_outdomain",
        ]
        pts2 = gpd.GeoDataFrame(
            grid[keep], geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs=grid.crs,
        )
        joined = gpd.sjoin(pts2, reg_regions[["region_id", "geometry"]], predicate="within", how="left")
        by_region = joined.groupby("region_id")[keep].sum()
        for r in reg_regions.itertuples():
            row = by_region.reindex([r.region_id]).fillna(0.0).iloc[0]
            provinces.append({
                "name": str(r.name),
                "mwp_verified": round(float(row["mwp_verified"]), 1),
                "mwp_best": round(float(row["mwp_best"]), 1),
                "osm_mwp": round(float(row["osm_mwp"]), 1),
                "mwp_large": round(float(row["mwp_large"]), 1),
                "small_low": round(float(row["small_low"]), 1),
                "small_central": round(float(row["small_central"]), 1),
                "small_outdomain": round(float(row["small_outdomain"]), 1),
                "nb": int(r.n_pv_buildings),
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["mwp_best"])

    total_verified = float(grid.mwp_verified.sum())
    total_best = float(grid.mwp_best.sum())
    total_large = float(grid.mwp_large.sum())

    # --- 90% intervals on both tiers. The point estimates above have moved 20-35% several
    #     times purely from recalibration; reporting them bare was the atlas's single
    #     largest presentational gap. See `_evidence_uncertainty` for what is and is not
    #     inside these numbers.
    _in_ge400 = grid["cell"].isin(ge400_domain_cells)
    unc_components = {
        **osm_parts,
        # `mwp_large_roof` is roofclf inside the ge400 domain and segmentation outside it
        # (see above); the two carry completely different uncertainty, so they are split
        # here on exactly the same mask that built the column.
        "ge400_roof": float(grid.loc[_in_ge400, "mwp_large_roof"].sum()),
        "seg_roof_outdomain": float(grid.loc[~_in_ge400, "mwp_large_roof"].sum()),
        "seg_ground": float(grid.est_mwp_rc_ground.sum()),
        "small_low": float(grid.small_low.sum()),
        "small_central": float(grid.small_central.sum()),
        "small_outdomain": float(grid.small_outdomain.sum()),
    }
    uncertainty = _evidence_uncertainty(
        density_dir=density_dir, meta=meta, kwp_mod=kwp_mod, kwp_land=kwp_land,
        components=unc_components,
        boots={
            "small_low": _capacity_summary_for(
                low_buildings_path, "domain_restricted_and_gate_sub400_capacity"
            ).get("coverage_ratio_bootstrap", {}),
            "small_central": _capacity_summary_for(
                central_buildings_path, "domain_restricted_sub400_capacity"
            ).get("coverage_ratio_bootstrap", {}),
            "small_outdomain": _capacity_summary_for(
                sub400_outdomain_buildings_path, "out_of_domain_and_gate_sub400_capacity"
            ).get("coverage_ratio_bootstrap", {}),
            "ge400_roof": _capacity_summary_for(
                ge400_roof_buildings_path, "domain_restricted_ge400_roof_capacity"
            ).get("coverage_ratio_bootstrap", {}),
        },
        total_verified=total_verified, total_best=total_best,
    )
    log.info(
        "Evidence atlas: Verified %.1f MWp (90%% %.0f-%.0f), Best %.1f MWp (90%% %.0f-%.0f)",
        total_verified, *uncertainty["mwp_verified_ci"], total_best, *uncertainty["mwp_best_ci"],
    )

    calib_boxes = _load_calib_boxes(aoi, labels_dir)
    n_calib_rule1 = sum(1 for b in calib_boxes if b["status"] == "rule1")

    data = {
        "bounds": bounds,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "calibBoxes": calib_boxes,
        "totals": {
            "mwp_verified": round(total_verified, 1),
            "mwp_best": round(total_best, 1),
            "mwp_large": round(total_large, 1),
            "osm_mwp": round(float(grid.osm_mwp.sum()), 1),
            "osm_mwp_unmatched": round(float(grid.osm_mwp_unmatched.sum()), 1),
            "osm_n": int(grid.osm_n.sum()),
            "osm_n_ge400": n_osm_ge400,
            "osm_n_lt400": n_osm_lt400,
            "n_osm_matched": int(osm["matched"].sum()),
            "small_low": round(float(grid.small_low.sum()), 1),
            "small_central": round(float(grid.small_central.sum()), 1),
            "small_outdomain": round(float(grid.small_outdomain.sum()), 1),
            "pv_buildings": int(grid.n_pv_buildings.sum()),
            "n_cells": int(len(grid)),
            "n_domain_cells": n_domain_cells,
            "n_extended_cells": int(grid.is_extended.sum()),
            "n_cells_best_floored": n_cells_best_floored,
            "kwp_per_m2": kwp_mod,
            "n_calib_boxes": len(calib_boxes),
            "n_calib_rule1": n_calib_rule1,
            "mwp_verified_ci": uncertainty["mwp_verified_ci"],
            "mwp_best_ci": uncertainty["mwp_best_ci"],
            "uncertainty": uncertainty,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
            "imagery_date_range": imagery_date_range,
        },
    }

    if downloads and data_release_url:
        base = data_release_url.rstrip("/")
        data["totals"]["downloads"] = [
            {**d, "url": f"{base}/{d['file']}"} for d in downloads
        ]

    # Second lens on the same Best-estimate total: by installation size and placement
    # instead of by cell. Same computation `build_size_distribution_atlas` publishes as
    # its own page (see `_size_distribution_data`'s docstring) -- only available once
    # roofclf's >= 400 m2 replacement exists, same gate every other roofclf-dependent
    # section on this page uses.
    if ge400_roof_buildings_path is not None:
        size_data = _size_distribution_data(
            aoi, density_dir, osm_solar_path, candidates_path,
            low_buildings_path, central_buildings_path, ge400_roof_buildings_path,
            sub400_outdomain_buildings_path,
        )
        size_best = size_data["totals"]["mwp_best"]
        if abs(size_best - total_best) > max(1.0, total_best * 0.02):
            log.warning(
                "Evidence atlas: size-bin re-binning totals %.1f MWp vs this page's own "
                "%.1f MWp (%.1f%% apart) -- investigate before trusting the embedded "
                "chart; see _size_distribution_data's docstring for the residual this is "
                "normally expected to stay within.",
                size_best, total_best, abs(size_best - total_best) / max(total_best, 1) * 100,
            )
        data["bins"] = size_data["bins"]
        data["totals"]["mwp_roof"] = size_data["totals"]["mwp_roof"]
        data["totals"]["mwp_ground"] = size_data["totals"]["mwp_ground"]

    # The panel-pose survey (glint-derived tilt/azimuth, `pose.py`) is embedded
    # natively -- see this function's docstring for why its CSS is namespaced under
    # `.pose-native` rather than living on `:root`/bare tag selectors like the
    # standalone page's own copy. Optional; an AOI with no glint-validation summary
    # yet gets no section at all rather than an empty one.
    if pose_summary_csv is not None:
        from earthpv import pose as pose_mod

        data["pose"] = pose_mod.compute_pose_survey_data(
            pose_summary_csv, title, pose_history_note, pose_data_note,
        )

    html = EVIDENCE_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title}'s Solar Atlas",
        "__H1__": f"{title}'s Solar Atlas",
        "__AOI_TITLE__": title,
        "__AOI_OVERPASS_AREA_TAGS__": overpass_area_tags,
        "__CONFIDENCE_HTML__": (
            "<p><b>Best estimate: "
            f"{total_best:,.0f} MWp, with a 90% range of "
            f"{uncertainty['mwp_best_ci'][0]:,.0f}&ndash;"
            f"{uncertainty['mwp_best_ci'][1]:,.0f} MWp.</b> That range covers three "
            "specific, measured sources of uncertainty -- but not everything that "
            "could move this number. Below: what's inside the range, what isn't, "
            "how many ground-truth areas it rests on, and how it compares to two "
            "unrelated data sources.</p>"
            "<p><b>What's inside the range:</b></p>"
            "<ul>"
            "<li><b>The two \"panel area to power\" conversion numbers.</b> One "
            "converts rooftop panel area to kWp, the other converts open-ground "
            "solar-farm land to kWp. Both are measured against real, confirmed "
            "power plants rather than assumed, but each carries its own "
            "uncertainty.</li>"
            "<li><b>How well the detection model finds panels of different "
            "sizes.</b> Its measured precision and recall were checked "
            "installation-size by installation-size, and that check itself has a "
            "margin of error.</li>"
            "<li><b>How much the small-panel corrections shift depending on which "
            "neighborhoods were ground-truthed.</b> Two corrections -- how much of "
            "a flagged roof is actually covered in panels, and what share of real "
            "installations get flagged at all -- are fit on the same set of "
            "ground-truthed neighborhoods (\"quadrats\"). This source of "
            "uncertainty is measured by refitting both on random subsets of those "
            "quadrats and seeing how far the answer moves.</li>"
            + (
                "<li><b>An added allowance for a rural extrapolation.</b> This "
                "build also includes a rough small-rooftop-solar estimate for "
                "rural cells outside the areas the small-panel correction was "
                "actually calibrated against, and that extrapolation's own "
                "uncertainty is folded into the range too.</li>"
                if int(grid["is_extended"].sum()) > 0 else
                ""
            ) +
            "</ul>"
            "<p><b>What's outside the range -- and can't be added back in with "
            "more arithmetic:</b></p>"
            "<ul>"
            "<li><b>The ground-truth areas were hand-picked, not randomly "
            "sampled, so this isn't a formal statistical margin of error.</b> "
            "That wasn't a shortcut: a genuine random sample needs every sampled "
            "location to have recent-enough reference imagery to confirm or rule "
            "out a small installation, and random locations outside the "
            "calibrated areas have so far landed on imagery too old to tell "
            "\"no panels\" apart from \"panels installed after this photo was "
            "taken.\" Hand-picking was the fallback that let ground-truth areas "
            "be placed where recent-enough imagery actually exists.</li>"
            "<li><b>Ground-truth \"complete\" means complete as of when that "
            "area was mapped, not as of the satellite image used for "
            "detection.</b> That cuts both ways, but in the same direction: it "
            "makes the model's measured accuracy look slightly worse than it is "
            "(recent real installations get scored as false alarms) and its "
            "measured miss rate look slightly better than it is (installations "
            "built after mapping can't be missed if they were never counted as "
            "ground truth to begin with). Both effects point the same way -- "
            "this page's figure is more likely an undercount than an "
            "overcount.</li>"
            "<li><b>About four-fifths of the Best estimate leans on one "
            "correction that hasn't been tested where it's applied most.</b> "
            "That correction is fit using the densest available ground-truth "
            "areas (about 872 buildings/km&sup2; at the sparsest of them), but "
            "84% of the buildings it's actually applied to nationally are "
            "three to four times sparser than that (measured 2026-08-16). The "
            "range above only resamples the denser areas the correction was fit "
            "on -- it says nothing about how well that correction holds up in "
            "the much sparser areas where most of it is actually used.</li>"
            "</ul>"
            "<p><b>Treat this as an early-stage estimate from an active research "
            "pipeline, not a finished census.</b> What's genuinely new here -- a "
            "reproducible way to estimate distributed solar from free satellite "
            "imagery and open-source AI, in a country where official statistics "
            "are sparse -- holds regardless of whether any single number on this "
            "page turns out exactly right. Expect these figures to keep moving "
            "as more ground-truth areas get added.</p>"
            "<p><b>The ground-truth areas: hand-picked to cover a mix of "
            "landscapes, not a random sample.</b> All "
            f"<b>{data['totals']['n_calib_boxes']}</b> quadrats behind the "
            "small-panel instruments were chosen by a researcher to span "
            "different kinds of places -- planned housing developments, dense "
            "informal urban neighborhoods, industrial estates, arid/bare land -- "
            "rather than drawn at random from a national list. Only "
            f"<b>{data['totals']['n_calib_rule1']}</b> of them have had a full "
            "manual check thorough enough to trust their \"no panels here\" "
            "verdicts (the teal markers on the map). However many quadrats "
            "exist, hand-picked ones can't produce a formal national margin of "
            "error on their own -- that needs a genuine random sample of the "
            "country's buildings, which doesn't exist yet. More quadrats do "
            "help: each new one added so far has turned up a new way the method "
            "can go wrong.</p>"
            "<p><b>Two independent, non-satellite data sources land in the same "
            "ballpark.</b> Pakistan's NEPRA net-metering register -- a "
            "government administrative record with no connection to this "
            "project -- puts registered rooftop solar at <b>5.3&ndash;6.3 "
            "GW</b> nationally; that's a floor, since it only counts customers "
            "who completed formal registration paperwork. Separately, Chinese "
            "customs export data puts cumulative solar-panel imports into "
            "Pakistan at roughly <b>50 GW</b> by mid-2025 -- a much looser "
            "ceiling that covers the whole market, utility-scale plants "
            "included. This page's headline figure falls inside that bracket. "
            "Two unrelated, non-satellite sources agreeing on the same order of "
            "magnitude is real corroboration -- though it can't confirm any "
            "single number on this page precisely.</p>"
        ),
    }.items():
        html = html.replace(key, value)

    out.write_text(html)
    log.info(
        "Wrote evidence atlas (verified %.0f / best %.0f MWp, "
        "%d/%d domain cells, %d extended-only cells contributing %.0f MWp) -> %s",
        total_verified, total_best, n_domain_cells, len(grid),
        int(grid.is_extended.sum()), float(grid.small_outdomain.sum()), out,
    )
    return out


# --------------------------------------------------------------------------------------
# Capacity-by-size atlas -- an alternate lens on the SAME Best-estimate total, sliced by
# installation size and placement instead of by geography. Added 2026-08-12.
# --------------------------------------------------------------------------------------

# Display bins only -- independent of `capacity_calibration.BIN_EDGES_M2`, which governs
# the p_real/recall LOOKUP for a candidate, not how this chart groups results for
# display. The top edge is open-ended so a utility-scale plant (e.g. Quaid-e-Azam Solar
# Park, ~8.9M m2) gets its own visible bin rather than silently sharing a bar with a
# 100,000 m2 site.
SIZE_BIN_EDGES_M2 = [0.0, 100.0, 400.0, 1000.0, 5000.0, 20000.0, 100000.0, float("inf")]


def _size_bin_sum(
    area_m2: np.ndarray, mwp: np.ndarray, edges: list[float] = SIZE_BIN_EDGES_M2,
) -> tuple[np.ndarray, np.ndarray]:
    """Sum `mwp` and count objects into fixed-width `edges` bins by `area_m2`."""
    n_bins = len(edges) - 1
    idx = np.digitize(area_m2, edges[1:-1], right=False)
    sums = np.zeros(n_bins)
    counts = np.zeros(n_bins, dtype=int)
    for i in range(n_bins):
        m = idx == i
        sums[i] = mwp[m].sum()
        counts[i] = int(m.sum())
    return sums, counts


def _size_bin_display_labels(edges: list[float] = SIZE_BIN_EDGES_M2) -> list[str]:
    def fmt(v: float) -> str:
        return f"{v / 1000:g}k" if v >= 1000 else f"{v:g}"

    labels = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        if hi == float("inf"):
            labels.append(f"≥{fmt(lo)} m²")
        elif lo == 0:
            labels.append(f"<{fmt(hi)} m²")
        else:
            labels.append(f"{fmt(lo)}–{fmt(hi)} m²")
    return labels


def _size_distribution_data(
    aoi: str, density_dir: Path,
    osm_solar_path: Path, candidates_path: Path,
    low_buildings_path: Path, central_buildings_path: Path, ge400_roof_buildings_path: Path,
    sub400_outdomain_buildings_path: Path | None = None,
) -> dict:
    """Re-bins `build_evidence_atlas`'s Best-estimate total by installation size and
    placement (rooftop / ground-mount) instead of by 0.1-degree cell. Shared by
    `build_size_distribution_atlas` (its own standalone page) and `build_evidence_atlas`
    (which embeds the same chart as a second lens on its own map).

    Does NOT recompute capacity by any new method -- every MWp here comes from the
    identical formula `build_evidence_atlas`/`density.py` already use, so the grand
    total should equal the published Best estimate for the same run (both callers log
    a comparison; the caller should treat a mismatch against a published atlas as a
    bug, not a footnote).

    Six populations carry every MWp shown, each with a real per-object size field --
    exactly `build_evidence_atlas`'s `best_parts`:

    - segmentation candidates, ground-mount placement, no domain restriction
      (`seg_ground`) and rooftop placement, cells OUTSIDE the ge400-roof domain
      (`seg_roof_outdomain`) -- roofclf replaces segmentation's own rooftop estimate
      INSIDE that domain, so counting both there would double it.
    - `ge400_roof_buildings_path` (roofclf's own >= 400 m2 rooftop replacement,
      in-domain). Under the parcel label, a flat quadrat-measured share of each
      building's MWp (`est_kwp_ge400_roof_ground`) is OSM `placement=ground` PV in the
      yard rather than on the roof and is split into `ground_mwp`, not `roof_mwp` --
      see `parcel_label_composition`. 0 under a roof-only calibration table.
    - `central_buildings_path` (roofclf alone, < 400 m2, in-domain). Same split, via
      `est_kwp_sub400_ground`.
    - `sub400_outdomain_buildings_path` (roofclf+SPPI agreement, < 400 m2,
      extrapolated outside the domain) -- optional, matches `earthpv atlas`'s own
      `--sub400-outdomain-cells`; rendered as a visually distinct slice. Not split by
      the parcel-label ground share (this component doesn't track it; it is also
      unpublished as of 2026-08-15, see CLAUDE.md's "Density stage").
    - hand-mapped OSM installations the model never detected
      (`osm_unmatched_roof`/`osm_unmatched_ground`).

    `low_buildings_path` (the AND-gate population) is NOT one of those six and is
    never shown as its own bin -- it never feeds Best estimate on its own (see
    `build_evidence_atlas`'s docstring). It is still a REQUIRED input here, for one
    narrow purpose: `build_evidence_atlas` floors Best at Verified (`osm_mwp +
    small_low`) *per cell*, because a matched OSM installation's own bin-averaged
    precision/recall correction can undershoot its true mapped area (Quaid-e-Azam
    Solar Park read Verified 866 MWp against Best's pre-fix 243 MWp in exactly this
    way). Skipping that floor here would silently undercount this page's total
    against the published one -- measured 2026-08-12: omitting it understated the
    Pakistan total by ~736 MWp (4.5%), concentrated in a handful of cells holding the
    country's largest OSM-matched ground-mount plants. Wherever the floor applies,
    the shortfall is attributed to that cell's own OSM-matched installations (weighted
    by their share of the cell's matched capacity, sized by their own true geodesic
    area), or to its `low` buildings if a cell has no matched OSM at all -- so the
    top-up lands in the size bin it actually belongs to rather than a flat correction.

    Domain cells are derived from `ge400_roof_buildings_path` via
    `_join_buildings_to_grid_cells` (a fresh spatial join against THIS grid's own cell
    polygons), not a fresh `sub400_capacity.national_cell_domain` call or a trusted
    `cell` string column -- matching `build_evidence_atlas` line for line so domain
    membership can't drift between the two atlases.
    """
    from earthpv import capacity_calibration as cc
    from earthpv.density import capacity_relevant_candidates
    from earthpv.export import new_lead_mask
    from earthpv.labels import dissolve_overlapping
    from earthpv.postprocess import NEAR_BUILDING_M

    density_dir = Path(density_dir)
    meta = json.loads((density_dir / "meta.json").read_text())
    kwp_mod = meta.get("kwp_per_m2_module", cc.DEFAULT_KWP_PER_M2_MODULE)
    kwp_land = meta.get("kwp_per_m2_land", cc.DEFAULT_KWP_PER_M2_LAND)
    edges = SIZE_BIN_EDGES_M2
    n_bins = len(edges) - 1
    roof_mwp = np.zeros(n_bins)
    ground_mwp = np.zeros(n_bins)
    roof_n = np.zeros(n_bins, dtype=int)
    ground_n = np.zeros(n_bins, dtype=int)
    extrap_mwp = np.zeros(n_bins)  # the sub-400 out-of-domain slice, WITHIN roof_mwp

    def _size_bin_add(area_v: np.ndarray, mwp_v: np.ndarray, roof: bool) -> None:
        s, n = _size_bin_sum(area_v, mwp_v, edges)
        if roof:
            roof_mwp[:] += s; roof_n[:] += n
        else:
            ground_mwp[:] += s; ground_n[:] += n

    def _cell_sum(keys: np.ndarray, values: np.ndarray) -> pd.Series:
        return pd.Series(values).groupby(pd.Series(keys)).sum()

    grid = gpd.read_parquet(density_dir / "grid.geoparquet")

    # --- segmentation candidates: seg_ground (everywhere) + seg_roof_outdomain -------
    cands = gpd.read_parquet(candidates_path)
    cands, _ = capacity_relevant_candidates(cands)
    table = cc.load_table(cc.default_table_path(aoi))

    ge400 = gpd.read_parquet(ge400_roof_buildings_path)
    # Domain membership by a fresh spatial join against THIS grid's own cell polygons,
    # not by trusting `ge400`'s own `cell` string column -- that id comes from whatever
    # manifest was current when roofclf's national scoring ran, which can silently
    # mismatch this grid's id scheme (see `_join_buildings_to_grid_cells`'s docstring;
    # `build_evidence_atlas` makes the identical call for the identical reason).
    ge400_by_cell = (
        _join_buildings_to_grid_cells(ge400, "est_kwp_ge400_roof", grid) / 1000.0
        if not ge400.empty else pd.Series(dtype=float)
    )
    ge400_cells = set(ge400_by_cell.index)

    pts = cands.copy()
    pts["geometry"] = pts.geometry.representative_point()
    joined = gpd.sjoin(pts, grid[["cell", "geometry"]], predicate="within", how="left")
    cell_of = joined["cell"].to_numpy()

    area = cands["area_m2"].to_numpy(float)
    placement = (
        cands["placement"].astype(str).to_numpy()
        if "placement" in cands.columns else np.full(len(cands), "", dtype=object)
    )
    glint = cands["glint_consistent"].to_numpy() if "glint_consistent" in cands.columns else None
    p_real = cc.candidate_p_real(area, table, glint_consistent=glint, placement=placement)
    recall = cc.candidate_recall(area, table, floor=cc.DEFAULT_RECALL_FLOOR, placement=placement)
    rc_area = area * p_real / np.clip(recall, cc.DEFAULT_RECALL_FLOOR, None)
    is_roof = placement == "rooftop"
    in_domain = np.isin(cell_of, np.array(list(ge400_cells), dtype=object)) if ge400_cells else np.zeros(len(cands), bool)

    ground_mask = ~is_roof
    roof_outdomain_mask = is_roof & ~in_domain

    seg_ground_mwp_arr = rc_area * kwp_land / 1000.0
    seg_roof_mwp_arr = rc_area * kwp_mod / 1000.0
    _size_bin_add(area[ground_mask], seg_ground_mwp_arr[ground_mask], roof=False)
    _size_bin_add(area[roof_outdomain_mask], seg_roof_mwp_arr[roof_outdomain_mask], roof=True)

    seg_ground_by_cell = _cell_sum(cell_of[ground_mask], seg_ground_mwp_arr[ground_mask])
    seg_roof_all_by_cell = _cell_sum(cell_of[is_roof], seg_roof_mwp_arr[is_roof])

    # --- roofclf's own >= 400 m2 rooftop replacement, in-domain ----------------------
    # A flat, quadrat-measured share of each building's priced capacity is actually OSM
    # `placement=ground` PV in the yard, not on the roof (`parcel_label_composition`,
    # `est_kwp_ge400_roof_ground` -- 0 under a roof-only calibration table). Split the
    # MWp by that share; `roof_n`/`ground_n` stay whole-building counts under roof_n,
    # since this isn't a distinct ground-mount OBJECT the way a segmentation/OSM ground
    # candidate is -- one building's estimate is just partly ground-tagged area.
    if not ge400.empty:
        ge400_ground_kwp = (
            ge400["est_kwp_ge400_roof_ground"].to_numpy(float)
            if "est_kwp_ge400_roof_ground" in ge400.columns else np.zeros(len(ge400))
        )
        ge400_roof_kwp = ge400["est_kwp_ge400_roof"].to_numpy(float) - ge400_ground_kwp
        area_v = ge400["roof_area_m2"].to_numpy(float)
        _size_bin_add(area_v, ge400_roof_kwp / 1000.0, roof=True)
        s, _ = _size_bin_sum(area_v, ge400_ground_kwp / 1000.0, edges)
        ground_mwp[:] += s

    # --- roofclf alone, < 400 m2, in-domain ------------------------------------------
    central = gpd.read_parquet(central_buildings_path)
    central_by_cell = pd.Series(dtype=float)
    if not central.empty:
        central_ground_kwp = (
            central["est_kwp_sub400_ground"].to_numpy(float)
            if "est_kwp_sub400_ground" in central.columns else np.zeros(len(central))
        )
        central_roof_kwp = central["est_kwp_sub400"].to_numpy(float) - central_ground_kwp
        area_v = central["roof_area_m2"].to_numpy(float)
        _size_bin_add(area_v, central_roof_kwp / 1000.0, roof=True)
        s, _ = _size_bin_sum(area_v, central_ground_kwp / 1000.0, edges)
        ground_mwp[:] += s
        central_by_cell = _join_buildings_to_grid_cells(central, "est_kwp_sub400", grid) / 1000.0

    # --- roofclf+SPPI, < 400 m2, extrapolated outside the domain --------------------
    outd_by_cell = pd.Series(dtype=float)
    if sub400_outdomain_buildings_path is not None and Path(sub400_outdomain_buildings_path).exists():
        outd = gpd.read_parquet(sub400_outdomain_buildings_path)
        if not outd.empty:
            s, n = _size_bin_sum(
                outd["roof_area_m2"].to_numpy(float),
                outd["est_kwp_sub400_outdomain"].to_numpy(float) / 1000.0, edges,
            )
            roof_mwp[:] += s; roof_n[:] += n
            extrap_mwp[:] += s
            outd_by_cell = _join_buildings_to_grid_cells(outd, "est_kwp_sub400_outdomain", grid) / 1000.0

    # --- AND-gate ("low"), < 400 m2, in-domain -- NEVER shown, floor-check input only
    low = gpd.read_parquet(low_buildings_path)
    low_by_cell = (
        _join_buildings_to_grid_cells(low, "est_kwp_sub400_and_gate", grid) / 1000.0
        if not low.empty else pd.Series(dtype=float)
    )

    # --- hand-mapped OSM: unmatched feeds Best directly; matched feeds the floor ----
    osm = gpd.read_parquet(osm_solar_path)
    osm = dissolve_overlapping(osm, group_col="placement")
    osm = osm.copy()
    osm["matched"] = ~new_lead_mask(osm, cands, min_distance_m=NEAR_BUILDING_M)
    osm["kwp"] = np.where(
        osm["placement"] == "rooftop", osm["area_m2"] * kwp_mod, osm["area_m2"] * kwp_land
    )
    unmatched = osm.loc[~osm["matched"]]
    u_roof = (unmatched["placement"] == "rooftop").to_numpy()
    _size_bin_add(
        unmatched.loc[u_roof, "area_m2"].to_numpy(float), unmatched.loc[u_roof, "kwp"].to_numpy(float) / 1000.0,
        roof=True,
    )
    _size_bin_add(
        unmatched.loc[~u_roof, "area_m2"].to_numpy(float), unmatched.loc[~u_roof, "kwp"].to_numpy(float) / 1000.0,
        roof=False,
    )

    osm_pts = osm.copy()
    osm_pts["geometry"] = osm_pts.geometry.representative_point()
    osm_joined = gpd.sjoin(osm_pts, grid[["cell", "geometry"]], predicate="within", how="left")
    osm_joined = osm_joined.dropna(subset=["cell"])
    osm_all_by_cell = osm_joined.groupby("cell")["kwp"].sum() / 1000.0
    osm_unmatched_by_cell = (
        osm_joined.loc[~osm_joined["matched"]].groupby("cell")["kwp"].sum() / 1000.0
    )

    # --- replicate build_evidence_atlas's per-cell "Best floored at Verified" -------
    def _get(s: pd.Series, c: str) -> float:
        v = s.get(c) if len(s) else None
        return float(v) if v is not None and pd.notna(v) else 0.0

    all_cells = grid["cell"].to_numpy()
    shortfalls: dict[str, float] = {}
    for c in all_cells:
        large_roof = _get(ge400_by_cell, c) if c in ge400_cells else _get(seg_roof_all_by_cell, c)
        best_raw = (
            _get(osm_unmatched_by_cell, c) + large_roof + _get(seg_ground_by_cell, c)
            + _get(central_by_cell, c) + _get(outd_by_cell, c)
        )
        verified = _get(osm_all_by_cell, c) + _get(low_by_cell, c)
        sf = verified - best_raw
        if sf > 1e-6:
            shortfalls[c] = sf

    matched_joined = osm_joined.loc[osm_joined["matched"]]
    low_joined = pd.DataFrame()
    if not low.empty:
        # Drop `low`'s own stale `cell` column first -- keeping it collides with
        # grid's `cell` in the join output (silently renamed to `cell_left`/
        # `cell_right` by geopandas rather than raising), the exact string-id-vs-
        # spatial-join mismatch `_join_buildings_to_grid_cells` exists to avoid.
        low_pts = low.drop(columns=["cell"]).copy()
        low_pts["geometry"] = low_pts.geometry.representative_point()
        low_joined = gpd.sjoin(low_pts, grid[["cell", "geometry"]], predicate="within", how="left")
        low_joined = low_joined.dropna(subset=["cell"])

    unattributed = 0.0
    for c, sf in shortfalls.items():
        sub = matched_joined.loc[matched_joined["cell"] == c]
        if not sub.empty:
            wsum = float(sub["kwp"].sum())
            for _, row in sub.iterrows():
                share = (row["kwp"] / wsum) if wsum > 0 else 1.0 / len(sub)
                amt = sf * share
                idx = int(np.digitize([row["area_m2"]], edges[1:-1])[0])
                if row["placement"] == "rooftop":
                    roof_mwp[idx] += amt
                else:
                    ground_mwp[idx] += amt
            continue
        sub2 = low_joined.loc[low_joined["cell"] == c] if not low_joined.empty else low_joined
        if not sub2.empty:
            wsum = float(sub2["est_kwp_sub400_and_gate"].sum())
            for _, row in sub2.iterrows():
                share = (row["est_kwp_sub400_and_gate"] / wsum) if wsum > 0 else 1.0 / len(sub2)
                amt = sf * share
                idx = int(np.digitize([row["roof_area_m2"]], edges[1:-1])[0])
                roof_mwp[idx] += amt
            continue
        unattributed += sf

    if unattributed:
        log.warning(
            "Size-distribution atlas: %.1f MWp of the Best-estimate floor could not be "
            "attributed to a specific installation (no matched OSM or AND-gate building "
            "in the affected cell) -- added to the largest ground-mount bin instead.",
            unattributed,
        )
        ground_mwp[-1] += unattributed

    total_roof = float(roof_mwp.sum())
    total_ground = float(ground_mwp.sum())
    total = total_roof + total_ground
    labels = _size_bin_display_labels(edges)
    bins = [
        {
            "label": labels[i],
            "roof_mwp": round(float(roof_mwp[i]), 2),
            "ground_mwp": round(float(ground_mwp[i]), 2),
            "roof_extrapolated_mwp": round(float(extrap_mwp[i]), 2),
            "roof_n": int(roof_n[i]),
            "ground_n": int(ground_n[i]),
        }
        for i in range(n_bins)
    ]

    return {
        "bins": bins,
        "totals": {
            "mwp_best": round(total, 1),
            "mwp_roof": round(total_roof, 1),
            "mwp_ground": round(total_ground, 1),
            "n_bins": n_bins,
        },
        "n_cells_floored": len(shortfalls),
    }


def build_size_distribution_atlas(
    aoi: str, density_dir: Path,
    osm_solar_path: Path, candidates_path: Path,
    low_buildings_path: Path, central_buildings_path: Path, ge400_roof_buildings_path: Path,
    sub400_outdomain_buildings_path: Path | None = None,
    out: Path | None = None,
) -> Path:
    """Standalone size-distribution page. See `_size_distribution_data` for what's
    actually computed -- this just templates it into its own HTML file."""
    title = aoi.replace("_", " ").title()
    size_data = _size_distribution_data(
        aoi, density_dir, osm_solar_path, candidates_path,
        low_buildings_path, central_buildings_path, ge400_roof_buildings_path,
        sub400_outdomain_buildings_path,
    )
    data = {"bins": size_data["bins"], "totals": size_data["totals"]}

    html = SIZE_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} Solar PV - Capacity by Installation Size",
        "__H1__": f"{title}'s solar, by installation size",
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else density_dir / f"{aoi}_pv_size_atlas.html"
    out.write_text(html)
    t = size_data["totals"]
    log.info(
        "Wrote size-distribution atlas (roof %.0f + ground %.0f = %.0f MWp across "
        "%d bins, %d cells floored at Verified) -> %s -- compare this total against "
        "the published evidence atlas's Best estimate for the same run; a mismatch is "
        "a bug, not a footnote.",
        t["mwp_roof"], t["mwp_ground"], t["mwp_best"], t["n_bins"], size_data["n_cells_floored"], out,
    )
    return out


def build_potential_atlas(
    aoi: str, density_dir: Path, potential_buildings_path: Path,
    out: Path | None = None, zoom_out_frac: float = 0.0,
    irradiance_cache: Path | None = None, n_probe: int = 36,
) -> Path:
    """Two-tab atlas: **Potential** (uncovered large-roof area, weighted by modelled
    annual irradiance -- a siting signal for FUTURE rooftop solar, not a capacity
    measurement of existing PV) and **Saturation** (existing PV area / roof area,
    already computed by `density.py::_ratios` -- this tab adds no new computation,
    only a new choropleth view of `pv_ratio_det`).

    `potential_buildings_path` is `potential.large_roof_buildings`'s output (columns
    `cell, geometry, roof_area_m2`, every building >= its `min_roof_m2`, national, no
    domain restriction -- see that function's docstring for why this is pure geometry
    and carries none of the sub-400 m2 calibration caveats the rest of this codebase
    documents at length). `irradiance_cache` defaults to a CSV alongside this run's
    density outputs so a re-run of the same AOI reuses the cached PVGIS probes instead
    of re-fetching them.
    """
    from earthpv.pv_capacity import grid_specific_yield, interpolate_yield

    density_dir = Path(density_dir)
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    meta = json.loads((density_dir / "meta.json").read_text())
    title = aoi.replace("_", " ").title()
    kwp_module = meta.get("kwp_per_m2_module", 0.18)

    large = gpd.read_parquet(potential_buildings_path)
    large_by_cell = _join_buildings_to_grid_cells(large, "roof_area_m2", grid)

    grid = grid.copy()
    grid["large_roof_m2"] = grid["cell"].map(large_by_cell).fillna(0.0)
    # Subtract the upper-leaning expected-coverage estimate (not the detected floor), so
    # a roof already showing ANY sub-threshold PV signal is conservatively excluded from
    # "opportunity" rather than double-suggested.
    grid["uncovered_large_m2"] = (
        grid["large_roof_m2"] - grid["pv_area_exp_roof_m2"]
    ).clip(lower=0.0)
    grid["potential_kwp"] = grid["uncovered_large_m2"] * kwp_module
    grid["potential_mwp"] = grid["potential_kwp"] / 1000.0

    irradiance_cache = (
        Path(irradiance_cache) if irradiance_cache else density_dir / "irradiance_probes.csv"
    )
    bounds = tuple(grid.total_bounds)
    probes = grid_specific_yield(bounds, irradiance_cache, n_probe=n_probe)
    grid["kwh_per_kwp_yr"] = interpolate_yield(
        probes, grid["lon_center"].to_numpy(), grid["lat_center"].to_numpy()
    )
    grid["potential_gwh_yr"] = grid["potential_kwp"] * grid["kwh_per_kwp_yr"] / 1e6

    grid["sat_pct"] = (grid["pv_ratio_det"] * 100.0).round(4)

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         round(float(r.potential_gwh_yr), 4), round(float(r.potential_mwp), 3),
         round(float(r.sat_pct), 2), int(r.n_pv_buildings),
         round(float(r.roof_area_m2) / 1e6, 4), round(float(r.large_roof_m2) / 1e6, 4),
         round(float(r.uncovered_large_m2) / 1e6, 4)]
        for r in grid.itertuples()
    ]
    bounds_out = [
        round(float(grid.lon0.min()), 3), round(float(grid.lat0.min()), 3),
        round(float(grid.lon0.max()) + 0.1, 3), round(float(grid.lat0.max()) + 0.1, 3),
    ]
    if zoom_out_frac:
        lon_pad = (bounds_out[2] - bounds_out[0]) * zoom_out_frac / 2
        lat_pad = (bounds_out[3] - bounds_out[1]) * zoom_out_frac / 2
        bounds_out = [
            round(bounds_out[0] - lon_pad, 3), round(bounds_out[1] - lat_pad, 3),
            round(bounds_out[2] + lon_pad, 3), round(bounds_out[3] + lat_pad, 3),
        ]

    provinces = []
    regions_path = density_dir / "regions.geoparquet"
    if regions_path.exists():
        reg = gpd.read_parquet(regions_path)
        reg_regions = reg[reg.level == "region"]
        # Potential is derived from a building parquet regions.geoparquet predates, so
        # join the grid's own per-cell potential columns to provinces by centroid --
        # the same pattern build_combined_atlas/build_sub400_bracket_atlas already use
        # for a column that isn't already a region aggregate.
        pts = gpd.GeoDataFrame(
            grid[["potential_gwh_yr", "potential_mwp", "large_roof_m2", "uncovered_large_m2"]],
            geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs=grid.crs,
        )
        joined = gpd.sjoin(pts, reg_regions[["region_id", "geometry"]], predicate="within", how="left")
        by_region = joined.groupby("region_id")[
            ["potential_gwh_yr", "potential_mwp", "large_roof_m2", "uncovered_large_m2"]
        ].sum()
        for r in reg_regions.itertuples():
            row = by_region.reindex([r.region_id]).fillna(0.0).iloc[0]
            provinces.append({
                "name": str(r.name),
                "gwh_potential": round(float(row["potential_gwh_yr"]), 1),
                "mwp_potential": round(float(row["potential_mwp"]), 1),
                "sat_pct": round(float(r.pv_ratio_det) * 100.0, 2),
                "nb": int(r.n_pv_buildings),
                "large_km2": round(float(row["large_roof_m2"]) / 1e6, 2),
                "uncovered_km2": round(float(row["uncovered_large_m2"]) / 1e6, 2),
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["gwh_potential"])

    total_gwh = float(grid.potential_gwh_yr.sum())
    total_mwp = float(grid.potential_mwp.sum())
    total_uncovered_km2 = float(grid.uncovered_large_m2.sum()) / 1e6
    total_large_km2 = float(grid.large_roof_m2.sum()) / 1e6
    national_sat_pct = (
        100.0 * float(grid.pv_area_det_roof_m2.sum()) / max(float(grid.roof_area_m2.sum()), 1e-9)
    )

    data = {
        "bounds": bounds_out,
        "cells": cells,
        "provinces": provinces,
        "cities": CITIES.get(aoi, []),
        "totals": {
            "gwh_potential": round(total_gwh, 1),
            "mwp_potential": round(total_mwp, 1),
            "sat_pct": round(national_sat_pct, 2),
            "large_km2": round(total_large_km2, 2),
            "uncovered_km2": round(total_uncovered_km2, 2),
            "n_large_buildings": int(len(large)),
            "pv_buildings": int(grid.n_pv_buildings.sum()),
            "n_cells": int(len(grid)),
            "kwp_per_m2": kwp_module,
            "kwh_per_kwp_range": [
                round(float(probes.kwh_per_kwp_yr.min()), 0),
                round(float(probes.kwh_per_kwp_yr.max()), 0),
            ],
        },
    }

    html = POTENTIAL_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} Rooftop Potential & Saturation",
        "__H1__": f"Where {title} could add more rooftop solar",
        "__AOI_TITLE__": title,
        "__LEDE_HTML__": (
            "Two views of the same buildings, neither one a capacity measurement of "
            "existing PV. <b>Potential</b> highlights large roofs (&ge; 200 m&sup2;) "
            "showing no detected PV signal, weighted by modelled annual irradiance -- a "
            "siting signal for future installations, built from building footprint "
            "geometry alone, never a PV-presence probability. <b>Saturation</b> shows "
            "how much of each cell's total roof area already carries detected PV, to "
            "contrast dense-adoption urban areas against under-adopted ones."
        ),
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else density_dir / f"{aoi}_pv_potential_atlas.html"
    out.write_text(html)
    log.info(
        "Wrote potential atlas (potential %.0f GWh/yr / %.0f MWp uncovered large-roof, "
        "national saturation %.2f%%) -> %s",
        total_gwh, total_mwp, national_sat_pct, out,
    )
    return out
