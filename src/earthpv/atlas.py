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

A fourth, richer template (`templates/pv_evidence_atlas.html`, `build_evidence_atlas`)
is the project's default going forward as of 2026-08-01 for AOIs with the extra
national-scale artifacts it needs (OSM solar pull, national roofclf+SPPI scoring, the
sub-400 m2 bracket's building-level parquets): three tiers by STANDARD OF PROOF
(Verified / Best / Ceiling) rather than by point estimate, plus the KPI-strip +
expandable-background page shell documented in `CLAUDE.md`'s "Results-page house
style". It supersedes `build_sub400_bracket_atlas` as the CLI's recommended path; that
function stays for reference and for AOIs that only have the older bracket inputs.
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
        "between them — the map, the hero number and the province ranking follow."
    )
    if data["totals"].get("kwpLand"):
        lede += (
            " Rooftop and ground-mount area convert at different rates, because a rooftop "
            "detection outlines the panels and a ground-mount detection outlines the site."
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


def build_evidence_atlas(
    aoi: str, density_dir: Path,
    osm_solar_path: Path, candidates_path: Path,
    low_buildings_path: Path, central_buildings_path: Path, high_buildings_path: Path,
    out: Path | None = None, zoom_out_frac: float = 0.0, labels_dir: Path = Path("data/labels"),
) -> Path:
    """Three-tier evidence atlas -- promoted 2026-08-01 to the project's default capacity
    atlas, superseding `build_sub400_bracket_atlas`'s Low/Central/High/All-PV framing
    (kept above for reference; no longer the CLI's default path). Each tier is a
    different STANDARD OF PROOF, not a different point estimate on the same scale:

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
    - **Ceiling**: roofclf flagged nationwide at a precision-tuned threshold, credited at
      a flat 0.5 precision weight rather than each building's own probability, restricted
      to buildings with no existing large detection nearby (`high_buildings_path`, the
      same "incremental" population `roofclf_capacity.incremental_capacity` writes) --
      plus every large installation already known, of every placement. An explicit,
      unvalidated national bound, not a tighter measurement.

    Ported from `scripts/build_pakistan_pv_evidence_overview.py` (see that file's git
    history for the full derivation and the 2026-08-01 redefinition of Ceiling) with one
    correctness fix: the three building-level parquets are now aggregated to cells via
    `_join_buildings_to_grid_cells` -- a spatial join against THIS run's own grid
    polygons -- rather than a plain string `cell`-id match. The id-matching join the
    standalone script used silently drops any building whose id came from a manifest
    that numbered cells differently than this run's grid (the same failure mode
    `build_combined_atlas`'s docstring measured directly: a naive id join lost cells a
    spatial join does not). Buildings that fall outside every cell of this run's grid are
    excluded from the map and totals with a warning, the same as every other atlas
    builder here -- not reconstructed from a guessed cell origin, which
    `_join_buildings_to_grid_cells`'s own docstring explains is unsafe.
    """
    density_dir = Path(density_dir)
    grid = gpd.read_parquet(density_dir / "grid.geoparquet")
    meta = json.loads((density_dir / "meta.json").read_text())
    if "est_mwp_rc" not in grid.columns:
        raise ValueError(
            f"{density_dir}/grid.geoparquet has no est_mwp_rc column -- run "
            "`earthpv calibrate-candidates` before `density` so recall-correction "
            "exists; the evidence atlas needs the large-PV instrument for the Best "
            "and Ceiling tiers."
        )
    title = aoi.replace("_", " ").title()
    kwp_mod = meta.get("kwp_per_m2_module", 0.18)
    kwp_land = meta.get("kwp_per_m2_land", 0.07)

    # --- hand-mapped OSM PV, per cell, split by whether the model already found it
    #     (candidates carry the id of the OSM feature they matched, if any).
    osm = gpd.read_parquet(osm_solar_path)
    cand = gpd.read_parquet(candidates_path)
    matched_ids = (
        set(cand["osm_matched_id"].dropna().astype(str))
        if "osm_matched_id" in cand.columns else set()
    )
    osm = osm.copy()
    osm["matched"] = osm["id"].astype(str).isin(matched_ids)
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
    osm_by_cell = joined_osm.dropna(subset=["cell"]).groupby("cell").apply(
        lambda d: pd.Series({
            "osm_mwp": d["kwp"].sum() / 1000,
            "osm_mwp_unmatched": d.loc[~d["matched"], "kwp"].sum() / 1000,
            "osm_n": float(len(d)),
        }),
        include_groups=False,
    )

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
    grid["osm_mwp"] = grid["cell"].map(osm_by_cell.get("osm_mwp", pd.Series(dtype=float))).fillna(0.0)
    grid["osm_mwp_unmatched"] = grid["cell"].map(
        osm_by_cell.get("osm_mwp_unmatched", pd.Series(dtype=float))
    ).fillna(0.0)
    grid["osm_n"] = grid["cell"].map(osm_by_cell.get("osm_n", pd.Series(dtype=float))).fillna(0.0)
    grid["small_low"] = grid["cell"].map(by_low).fillna(0.0)
    grid["small_central"] = grid["cell"].map(by_central).fillna(0.0)
    grid["small_high"] = grid["cell"].map(by_high).fillna(0.0)
    grid["in_domain"] = grid["cell"].isin(by_low.index) | grid["cell"].isin(by_central.index)
    n_domain_cells = int(grid["in_domain"].sum())

    grid["mwp_verified"] = grid["osm_mwp"] + grid["small_low"]
    grid["mwp_best"] = grid["osm_mwp_unmatched"] + grid["est_mwp_rc"] + grid["small_central"]
    grid["mwp_ceiling"] = grid["small_high"] + grid["est_mwp_rc"]

    cells = [
        [round(float(r.lon0), 3), round(float(r.lat0), 3),
         round(float(r.mwp_verified), 3), round(float(r.mwp_best), 3), round(float(r.mwp_ceiling), 3),
         round(float(r.osm_mwp), 3), int(r.osm_n),
         round(float(r.small_low), 3), round(float(r.small_central), 3), round(float(r.small_high), 3),
         round(float(r.est_mwp_rc), 3), int(r.in_domain), int(r.n_pv_buildings)]
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
            "mwp_verified", "mwp_best", "mwp_ceiling", "osm_mwp", "est_mwp_rc",
            "small_low", "small_central", "small_high",
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
                "mwp_ceiling": round(float(row["mwp_ceiling"]), 1),
                "osm_mwp": round(float(row["osm_mwp"]), 1),
                "mwp_large": round(float(row["est_mwp_rc"]), 1),
                "small_low": round(float(row["small_low"]), 1),
                "small_central": round(float(row["small_central"]), 1),
                "small_high": round(float(row["small_high"]), 1),
                "nb": int(r.n_pv_buildings),
                "rings": _rings(r.geometry),
            })
        provinces.sort(key=lambda p: -p["mwp_best"])

    total_verified = float(grid.mwp_verified.sum())
    total_best = float(grid.mwp_best.sum())
    total_ceiling = float(grid.mwp_ceiling.sum())
    total_large = float(grid.est_mwp_rc.sum())

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
            "mwp_ceiling": round(total_ceiling, 1),
            "mwp_large": round(total_large, 1),
            "osm_mwp": round(float(grid.osm_mwp.sum()), 1),
            "osm_mwp_unmatched": round(float(grid.osm_mwp_unmatched.sum()), 1),
            "osm_n": int(grid.osm_n.sum()),
            "n_osm_matched": int(osm["matched"].sum()),
            "small_low": round(float(grid.small_low.sum()), 1),
            "small_central": round(float(grid.small_central.sum()), 1),
            "small_high": round(float(grid.small_high.sum()), 1),
            "pv_buildings": int(grid.n_pv_buildings.sum()),
            "n_cells": int(len(grid)),
            "n_domain_cells": n_domain_cells,
            "kwp_per_m2": kwp_mod,
            "n_calib_boxes": len(calib_boxes),
            "n_calib_rule1": n_calib_rule1,
        },
    }

    html = EVIDENCE_TEMPLATE.read_text()
    for key, value in {
        "__PV_DATA_JSON__": json.dumps(data, separators=(",", ":")),
        "__PAGE_TITLE__": f"{title} Solar PV — Counted Three Times Over",
        "__H1__": f"{title}'s solar, counted three times over",
        "__AOI_TITLE__": title,
        "__KWP_MOD__": str(kwp_mod),
        "__LEDE_HTML__": (
            "The same country, the same imagery, three different standards of proof. "
            "<b>Verified</b> counts only PV a person has drawn in OpenStreetMap plus the "
            "small rooftops where two independent detectors agree. <b>Best</b> adds the "
            "satellite model's own recall-corrected detections and its per-building "
            "density estimate: the highest figure this project is willing to defend. "
            "<b>Ceiling</b> swaps the small-PV side for a much looser national "
            "assumption and adds every large installation already known on top: a "
            "bound built on a cruder assumption, not a tighter measurement. This is a "
            "research methodology under active validation, not a finished census &mdash; "
            "see &ldquo;How confident should you be in this?&rdquo; below for what's "
            "independently corroborated and what's still open."
        ),
        "__CONFIDENCE_HTML__": (
            "<p><b>Read this as promising preliminary results from an ongoing "
            "methodology, not a finished capacity census.</b> What's genuinely novel "
            "here &mdash; a reproducible pipeline using free satellite imagery and "
            "open-source geospatial AI to estimate distributed solar deployment where "
            "official statistics are sparse &mdash; is true regardless of whether any "
            "single number on this page holds up exactly. Treat the numbers as the "
            "current state of an experiment being actively tested, not a settled "
            "fact.</p>"
            "<p><b>The calibration quadrats are hand-picked, not randomly sampled.</b> "
            f"All <b>{data['totals']['n_calib_boxes']}</b> ground-truth quadrats behind "
            "the small-PV instruments were chosen by a researcher to cover a spread of "
            "landscape types (planned housing, dense informal urban, industrial, "
            "arid/bare-land), not drawn at random from a defined national frame. Only "
            f"<b>{data['totals']['n_calib_rule1']}</b> of them have been through a full "
            "human completeness pass strict enough to trust their negatives (see the "
            "teal markers on the map). Purposive sampling at any size &mdash; whether "
            "this many quadrats or several times more &mdash; does not by itself support "
            "a formal national margin of error; that would need a probability sample "
            "drawn from the national building-density frame, which does not yet exist. "
            "More quadrats have real value (each new one has surfaced a genuinely new "
            "failure mode so far), but count alone does not resolve this.</p>"
            "<p><b>Independent, non-imagery data points land in the same order of "
            "magnitude.</b> Pakistan's NEPRA net-metering register &mdash; a government "
            "administrative record with no connection to this pipeline &mdash; puts "
            "registered rooftop solar at 5.3-6.3 GW nationally (a floor, since it only "
            "counts customers who completed formal registration paperwork). Chinese "
            "customs export data separately puts cumulative panel imports into Pakistan "
            "at roughly 50 GW by mid-2025, a much looser ceiling on the whole market, "
            "utility-scale included. This page's Verified and Best tiers sit inside that "
            "bracket, and its Ceiling sits a further step above it &mdash; two "
            "independent, non-satellite data sources landing in a mutually consistent "
            "range is real corroboration for the order of magnitude, even though it "
            "cannot confirm any single number here precisely.</p>"
        ),
    }.items():
        html = html.replace(key, value)

    out = Path(out) if out else density_dir / f"{aoi}_pv_evidence_atlas.html"
    out.write_text(html)
    log.info(
        "Wrote evidence atlas (verified %.0f / best %.0f / ceiling %.0f MWp, "
        "%d/%d domain cells) -> %s",
        total_verified, total_best, total_ceiling, n_domain_cells, len(grid), out,
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
