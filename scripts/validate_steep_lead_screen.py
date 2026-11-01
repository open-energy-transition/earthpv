#!/usr/bin/env python
"""Validate the steep-ground lead screen (`export.steep_lead_screen`, owner 2026-10-31).

The released lead files leave out a lead under 1,000 m2 on ground steeper than 15 degrees
and keep a larger one as `steep_review`. Two questions, per country:

1. **What real solar would the rule throw away?** Applied to the solar we know is real:
   every mapped OpenStreetMap solar polygon in the country's pull (its own outline area and
   GLO-90 slope; an upper bound, since a model outline is about twice the panel area it
   found and so crosses 1,000 m2 sooner), and every model candidate within the lead files'
   `min_distance_m` of mapped solar (the candidates that are NOT leads because they found
   something already mapped).
2. **What does it actually throw away?** A random sample of the dropped leads (old lead
   file minus new, by `candidate_id`; both files come from the same runs and OSM pulls, so
   the difference is exactly the screen) and of the leads kept as `steep_review`, rendered
   as oversize_review's four-panel sheets (the composite the model read, its 10 m pixels,
   false colour, Esri with its capture date) on one review page.

    pixi run python scripts/validate_steep_lead_screen.py \\
        --old /home/tobi/earthpv_data/pv_new_leads_2026-10-28 \\
        --new /home/tobi/earthpv_data/pv_new_leads_2026-11-01

Writes `results/leads_steep_screen/`: `summary.csv` (per country), `osm_steep.csv` (the
mapped polygons the rule would hit) and `sample.csv` (the drawn leads), and the review page
with its crops in `data/leads_steep_screen/review/` (gitignored, ~20 MB of JPEGs). Verdicts
go in `results/leads_steep_screen/verdicts_<reviewer>.csv`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "results" / "leads_steep_screen"
REVIEW = ROOT / "data" / "leads_steep_screen" / "review"
SEED = 20261031


def _rule(slope: np.ndarray, area: np.ndarray):
    from earthpv.export import STEEP_MAX_AREA_M2, STEEP_SLOPE_DEG

    steep = np.nan_to_num(slope, nan=0.0) > STEEP_SLOPE_DEG
    return steep & (area < STEEP_MAX_AREA_M2), steep & (area >= STEEP_MAX_AREA_M2)


def _slope(g: gpd.GeoSeries) -> np.ndarray:
    from earthpv.groundclf import dem_slope_at

    rep = g.to_crs(4326).representative_point()
    return dem_slope_at(rep.x.to_numpy(), rep.y.to_numpy())


def country(aoi: str, src: dict, old_dir: Path, new_dir: Path) -> tuple[dict, pd.DataFrame,
                                                                      gpd.GeoDataFrame,
                                                                      gpd.GeoDataFrame]:
    from earthpv.export import new_lead_mask
    from earthpv.labels import geodesic_area_m2

    old = gpd.read_file(old_dir / f"{aoi}_pv_new_leads.geojson")
    new = gpd.read_file(new_dir / f"{aoi}_pv_new_leads.geojson")
    dropped = old[~old.candidate_id.isin(new.candidate_id)].copy()
    dropped["slope_deg"] = _slope(dropped.geometry)
    d_rule, _ = _rule(dropped.slope_deg.to_numpy(), dropped.area_m2.to_numpy(float))
    review = new[new.steep_review.astype(bool)].copy()

    # Mapped solar: every polygon in the pull, on its own outline.
    paths = [ROOT / p for p in src.get("osm", [f"data/labels/{aoi}_overpass_solar.parquet"])]
    osm = gpd.GeoDataFrame(pd.concat([gpd.read_parquet(p)[["geometry"]] for p in paths],
                                     ignore_index=True), geometry="geometry", crs="EPSG:4326")
    osm = osm[osm.geometry.notna() & osm.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    osm = osm.reset_index(drop=True)
    osm["area_m2"] = [geodesic_area_m2(g) for g in osm.geometry]
    osm["slope_deg"] = _slope(osm.geometry)
    o_drop, o_review = _rule(osm.slope_deg.to_numpy(), osm.area_m2.to_numpy())

    # Model candidates that found mapped solar: within min_distance_m, so not leads.
    pred = ROOT / src.get("pred", f"data/predictions/{aoi}")
    cands = gpd.read_parquet(pred / "candidates.parquet")
    found = cands[~new_lead_mask(cands, osm[["geometry"]], 100.0)].copy()
    found["slope_deg"] = _slope(found.geometry)
    f_drop, f_review = _rule(found.slope_deg.to_numpy(), found.area_m2.to_numpy(float))

    row = {
        "aoi": aoi, "leads_before": len(old), "leads_after": len(new),
        "dropped": len(dropped), "dropped_not_by_rule": int((~d_rule).sum()),
        "steep_review": len(review),
        "osm_polygons": len(osm), "osm_would_drop": int(o_drop.sum()),
        "osm_would_drop_area_share": round(float(osm.area_m2[o_drop].sum() / osm.area_m2.sum()), 5)
        if len(osm) else np.nan,
        "osm_steep_ge1000": int(o_review.sum()),
        "found_candidates": len(found), "found_would_drop": int(f_drop.sum()),
        "found_steep_ge1000": int(f_review.sum()),
    }
    hit = osm[o_drop | o_review].assign(aoi=aoi, rule=np.where(o_drop[o_drop | o_review], "drop", "review"))
    return row, pd.DataFrame(hit.drop(columns="geometry").assign(
        lon=hit.geometry.representative_point().x, lat=hit.geometry.representative_point().y)), \
        dropped.assign(aoi=aoi), review.assign(aoi=aoi)


def render(sample: gpd.GeoDataFrame, out: Path) -> list[dict]:
    """oversize_review's four-panel sheet per lead, and the review page's items."""
    import oversize_review as ov

    from earthpv.config import Settings
    from earthpv.density import _grid_origin

    s = Settings.load()
    crops = out / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    items = []
    for r in sample.itertuples():
        cfg = s.aois[r.aoi]
        jpg, meta = crops / f"{r.code}.jpg", crops / f"{r.code}.esri"
        if not jpg.exists():
            window = cfg.get("compose_window")
            epoch = f"{window[0][:7]} to {window[1][:7]}" if window else "composite"
            d = ov._render(r.geometry, ROOT / f"data/composites/{r.aoi}/composites",
                           _grid_origin(r.aoi, cfg, s), epoch, jpg)
            meta.write_text(d or "")
        date = meta.read_text().strip() if meta.exists() else ""
        w, so, e, n = r.geometry.bounds
        p = r.geometry.representative_point()
        items.append({
            "code": r.code, "img": f"crops/{r.code}.jpg", "date": date,
            "date_label": (f"{r.aoi} · {r.kind} · {r.area_m2:,.0f} m2 · slope "
                           f"{r.slope_deg:.0f} deg · Esri {date or 'not fetched'}"),
            "lon": round(p.x, 6), "lat": round(p.y, 6),
            "bbox": [round(w - 0.002, 6), round(so - 0.002, 6), round(e + 0.002, 6),
                     round(n + 0.002, 6)],
        })
    return items


GUIDE = r"""      <ul>
        <li><b>PV</b>: solar panels inside or touching the yellow outline, on any of the panels
          (the composite is the imagery the model read and can be newer than Esri).</li>
        <li><b>Not PV</b>: something else: a shaded slope, a cliff edge or its shadow, a gully,
          dark rock, a field, water, a road.</li>
        <li><b>Unsure</b>: these panels cannot settle it; open the links.</li>
      </ul>
      <p>Codes starting <code>d</code> are leads the steep-ground screen LEFT OUT (under
        1,000 m&sup2;, steeper than 15&deg;): a PV verdict there is a real installation the
        screen costs. Codes starting <code>r</code> are larger steep leads KEPT as
        <code>steep_review</code>. Keys: <kbd>1</kbd> PV, <kbd>2</kbd> Not PV, <kbd>3</kbd>
        unsure, <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step, <kbd>n</kbd> note.</p>
      <p>Export <code>verdicts.csv</code> and save it as
        <code>results/leads_steep_screen/verdicts_owner.csv</code>.</p>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", type=Path, required=True, help="lead release before the screen")
    ap.add_argument("--new", type=Path, required=True, help="lead release with the screen")
    ap.add_argument("--aoi", action="append", help="only these AOIs (default: every built one)")
    ap.add_argument("--per-country", type=int, default=8,
                    help="dropped leads drawn per country (Yemen: 3x)")
    ap.add_argument("--review-per-country", type=int, default=4,
                    help="steep_review leads drawn per country (Yemen: 5x)")
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()

    import os
    os.chdir(ROOT)
    from release_leads import SOURCES

    OUT.mkdir(parents=True, exist_ok=True)
    rows, hits, drops, reviews = [], [], [], []
    for aoi in a.aoi or list(SOURCES):
        if not (a.new / f"{aoi}_pv_new_leads.geojson").exists():
            continue
        row, hit, dropped, review = country(aoi, SOURCES[aoi], a.old, a.new)
        print(" ", row)
        rows.append(row)
        hits.append(hit)
        drops.append(dropped)
        reviews.append(review)
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False)
    pd.concat(hits, ignore_index=True).to_csv(OUT / "osm_steep.csv", index=False)

    # One generator per country, seeded alike, so a country's draw (and its codes, e.g.
    # `yemen-d03`) does not change when other countries are added to a run.
    picks = []
    for dropped, review in zip(drops, reviews):
        aoi = dropped.aoi.iat[0] if len(dropped) else review.aoi.iat[0]
        rng = np.random.default_rng(SEED)
        for kind, f, k, boost in (("dropped", dropped, a.per_country, 3),
                                  ("review", review, a.review_per_country, 5)):
            if f.empty:
                continue
            n = min(len(f), k * boost if aoi == "yemen" else k)
            pick = f.iloc[rng.choice(len(f), n, replace=False)].assign(kind=kind)
            pick["code"] = [f"{aoi}-{kind[0]}{i:02d}" for i in range(len(pick))]
            picks.append(pick)
    sample = gpd.GeoDataFrame(pd.concat(picks, ignore_index=True), geometry="geometry",
                              crs="EPSG:4326")
    # The page shows them shuffled, so a reviewer does not judge one country in a block.
    sample = sample.iloc[np.random.default_rng(SEED + 1).permutation(len(sample))]
    sample = sample.reset_index(drop=True)
    cols = ["code", "kind", "aoi", "candidate_id", "area_m2", "slope_deg", "placement",
            "rank_score"]
    sample[cols].assign(lon=sample.geometry.representative_point().x,
                        lat=sample.geometry.representative_point().y).to_csv(
        OUT / "sample.csv", index=False)
    if not a.no_render:
        from build_review_page import write_page

        items = render(sample, REVIEW)
        write_page(REVIEW / "index.html", "leads_steep_screen", items, guide=GUIDE)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} countries, {len(sample)} leads drawn")
    return 0


if __name__ == "__main__":
    sys.exit(main())
