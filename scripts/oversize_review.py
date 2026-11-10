"""Judge the model's very large outlines (blobs) by eye, and count those judged solar.

**This review is a standing step of every country's run, like the random-cell validation.**
`postprocess.MAX_CANDIDATE_M2` (100,000 m2) keeps model outlines above it out of capacity,
because a sheet of false alarms merges into one shape as readily as a solar park does. A blob
enters capacity once it is mapped in OpenStreetMap or once it carries a `pv` verdict here
(owner, 2026-11-01; `density.load_oversize_admission`, each whole), and nothing else admits
one. Large parks are also the fastest capacity to verify: one look per outline.

    pixi run blob-review draw --aoi india     # review.csv + the review package
    # open data/oversize_review/index.html (every country), judge with keys 1 / 2 / 3, export:
    pixi run blob-review apply --aoi india --reviewer "<name>" --verdicts <the export>
    pixi run blob-review status               # who has what left, and refresh that index
    pixi run earthpv density --aoi india --districts    # no --force: the cells stay valid
    # then rebuild the atlas as usual; `status` prints each country's share of its blobs

**The queue is the published blob file's population, largest first**: model-drawn outlines
above the cap that are new leads (`export.new_lead_mask`, no mapped solar within
`--min-distance-m`), inside the regions the atlas draws, through the lead screens
(`export.steep_lead_screen`, `low_confidence_lead_screen`, and `water_lead_screen` where a
country switches it on), so nobody judges what the leads already leave out. A country's
candidates and mapped reference are the run behind its published atlas (`run_source`). `draw`
on an existing review.csv appends outlines it does not hold and keeps every verdict; `--redraw`
starts again. Sittings can be partial: `apply` takes any export and keeps earlier verdicts, an
outline left blank or unsure stays out of capacity and returns on the next page, and an outline
already judged leaves the page when it is next packaged (`--include-judged` keeps it).

`--census-n` / `--sample-n` optionally draw a measured share ahead of the queue: a census of the
largest outlines and a sample of the rest with probability proportional to area, without
replacement. Neither prices anything since 2026-11-01. India's 90 of 2026-10-28/29 are kept as
the record of how the review began, and `apply` needs every census and sample row judged.

**The review is done on disk, from the imagery the model saw** (`package`, run by `draw`,
2026-10-29). Each outline gets one image of four panels in
`data/oversize_review/<aoi>/crops/`: the Sentinel-2 composite of the imagery window in true
colour around the whole outline, the same at native 10 m pixels over 1.3 km, a false colour
(SWIR, NIR, red), and Esri World Imagery with its capture date. `index.html` beside them is
`build_review_page.py`'s page: one outline at a time, PV / not PV / unsure, a note, links to
Google, Bing, Esri Wayback and JOSM for an outline the panels cannot settle. The composite
is the right epoch: 11 of the 50 parks of India's sample were built after their Esri capture.
Its limit is 10 m: 9 of India's 60 sampled outlines needed the Esri panel to decide. The page
shows no model score, and nothing from an earlier verdict, so a second reviewer judges blind;
`apply` reports agreement. `review.geojson` holds the same outlines for JOSM. The review is a
human reading of imagery: record who reviewed it in `--reviewer`.

**A verdict names one candidate file.** An outline judged and then mapped in OpenStreetMap
leaves the pool and is counted from the map (no error, `apply` reports it). A new model run
renumbers the candidates, so `apply` and `density` refuse the old review; `draw --redraw` starts
a new one, and because the page's saved progress is keyed to the draw, old verdicts cannot
attach themselves to the new outlines.

**`--kind large`: the large installation review (owner, 2026-11-10), a default step too.** The
same review for the leads BELOW the cap, from `LARGE_MIN_M2` (10,000 m2, `--min-area-m2`) up to
it: model-drawn new leads through the same regions and screens, rooftop and ground alike,
largest first, in `results/<aoi>_large_review/` and `data/large_review/` (on /home). These
leads are already in capacity, each at its size bin's P(real); a verdict replaces that price
for its own lead (`pv` 1 on the ground and 1/2.5 on a roof, where the model's outline is
about 2.5 times the array, owner 2026-11-10; `not_pv` 0) and keeps the bin's recall
(`capacity_calibration.LEAD_REVIEW_KEY`, `density._lead_verdicts`). Any named reviewer's
verdict counts (owner, 2026-11-10). The crops are cut tighter (1 km of composite, 400 m of
native pixels, about 250 m of Esri), because a 1 ha roof is a speck in a park's window.

    pixi run large-review draw --aoi india
    # open data/large_review/index.html, judge, export, then:
    pixi run large-review apply --aoi india --reviewer "<name>" --verdicts <the export>
    pixi run earthpv density --aoi india --districts    # no --force; then the atlas

**Bright roofs are kept apart (owner, 2026-11-10).** Both pages carry a fourth verdict, key 4
"Bright roof": not PV, and the outline sits on a very bright roof (white or light metal, a
reflective coating). `apply` prices it as `not_pv` and writes `bright_roof` into review.csv's
`flag` column (and `review_flag` in review.geojson), so these false alarms can be pulled out
and studied together; `status` counts them.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

VERDICTS = ("pv", "not_pv")
# The page's export values -> review.csv's verdict and flag. `bright_roof` is a not-PV verdict
# on a very bright roof, kept apart for study; it prices exactly as not PV.
PAGE_VERDICTS = {"pv": ("pv", ""), "no_pv": ("not_pv", ""), "unsure": ("unsure", ""),
                 "bright_roof": ("not_pv", "bright_roof"), "": ("", "")}
LARGE_MIN_M2 = 10_000.0


@dataclass(frozen=True)
class Kind:
    """What one review covers and where it lives; `main` picks one with `--kind`."""
    name: str
    title: str             # the page's and the hub's heading
    suffix: str            # results/<aoi><suffix>/review.csv
    packages: Path         # crops, pages and the hub
    export: str            # the page's export file name
    task: str              # the pixi task the instructions name
    table_key: str         # the calibration table block `apply` writes
    context_min_m: float   # the composite panels show at least this much ground
    detail_m: float        # the native-pixel panel's width
    esri_min_m: float | None  # the Esri panel's width (None: as the composite's)
    noun: str              # what one row is, in messages


KINDS = {
    "blob": Kind("blob", "Solar farm review", "_oversize_review", REPO / "data" / "oversize_review",
                 "{aoi}_blob_verdicts.csv", "blob-review", "oversize_review", 1500.0, 1280.0, None,
                 "outlines above the cap"),
    "large": Kind("large", "Large installation review", "_large_review",
                  REPO / "data" / "large_review", "{aoi}_large_verdicts.csv", "large-review",
                  "lead_review", 1000.0, 400.0, 250.0, "leads below the cap"),
}
K = KINDS["blob"]  # set by `main`; the module's functions read the kind from here
PACKAGES = K.packages  # kept for callers that import it (the blob review's own directory)
# France's leads were audited and released on their own (scripts/build_france_osm_leads.py):
# its run is not in release_leads.SOURCES, its reference is that build's own three pulls in
# one file, and its blob file went through none of the later lead screens.
FRANCE = {"pred": "data/predictions_v5/france", "osm": "data/labels/france_mapped_20261022.parquet",
          "screens": False}


def run_source(aoi: str) -> dict:
    """`pred` (candidates), `osm` (mapped reference) and `screens` of the run behind `aoi`'s
    published atlas: the lead release's table, so a queue names the outlines its blob file does.
    A country that has not been released yet uses the default paths."""
    from release_leads import SOURCES

    if aoi == "france":
        return FRANCE
    src = SOURCES.get(aoi, {})
    return {"pred": src.get("pred", f"data/predictions/{aoi}"),
            "osm": (src.get("osm") or [f"data/labels/{aoi}_overpass_solar.parquet"])[0],
            "screens": True}


def candidates_path(aoi: str) -> Path:
    return REPO / run_source(aoi)["pred"] / "candidates.parquet"


def population(aoi: str, labels: Path, min_distance_m: float, min_area_m2: float | None = None):
    """New-lead model outlines above the cap (the blob review), or from `min_area_m2` up to
    the cap (the large installation review), with their ADM1 region."""
    import geopandas as gpd

    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.density import fetch_geoboundaries
    from earthpv.export import new_lead_mask
    from earthpv.labels import resolve_aoi
    from earthpv.postprocess import MAX_CANDIDATE_M2

    c = gpd.read_parquet(candidates_path(aoi))
    src = c["geometry_source"].fillna("model") if "geometry_source" in c.columns else "model"
    if min_area_m2 is None:
        pool = c[(c["area_m2"] > MAX_CANDIDATE_M2) & (src != "osm")]
    else:
        pool = c[(c["area_m2"] >= min_area_m2) & (c["area_m2"] <= MAX_CANDIDATE_M2) & (src != "osm")]
    ref = gpd.read_parquet(labels)[["geometry"]]
    ref = ref[ref.geometry.notna() & ~ref.geometry.is_empty]
    pool = pool[new_lead_mask(pool, ref, min_distance_m=min_distance_m)].copy()
    _, cfg = resolve_aoi(aoi, Settings.load())
    adm1 = fetch_geoboundaries(_iso3_for(cfg), "ADM1").to_crs(4326)
    rp = gpd.GeoDataFrame(geometry=pool.geometry.representative_point(), crs=4326)
    j = gpd.sjoin(rp, adm1[["name", "geometry"]], how="left", predicate="within")
    pool["region"] = j.groupby(level=0)["name"].first().reindex(pool.index)
    pool["lon"] = rp.geometry.x.round(5)
    pool["lat"] = rp.geometry.y.round(5)
    pool["candidate_index"] = pool.index
    return pool


def lead_screened(aoi: str, pool):
    """`pool` as the published blob file holds it: inside the regions the atlas draws (the
    ADM1 layer before `density` has written them, as in a country's first run), through the
    lead screens in `release_leads.build`'s order."""
    from earthpv import atlas
    from earthpv.export import (lead_water_screen_enabled, low_confidence_lead_screen,
                                steep_lead_screen, water_lead_screen)

    src = run_source(aoi)
    regions = REPO / src["pred"] / "density" / "regions.geoparquet"
    rep = pool.geometry.representative_point()
    if regions.exists():
        inside = rep.within(atlas._page_regions(aoi, regions).geometry.union_all()).to_numpy()
    else:
        inside = pool["region"].notna().to_numpy()
    pool = pool[inside].copy()
    if not src["screens"] or pool.empty:
        return pool
    _, drop, review = steep_lead_screen(pool)
    pool["steep_review"] = review
    pool = pool[~drop].copy()
    pool = pool[~low_confidence_lead_screen(pool)].copy()
    if lead_water_screen_enabled(aoi):
        _, wet = water_lead_screen(pool)
        pool = pool[~wet].copy()
    return pool


def _draw_id(rev) -> str:
    """Names one draw for the page's saved progress: the first row never changes when the
    queue grows, and a new candidate file or sample cannot reproduce it."""
    import hashlib

    first = rev.iloc[0]
    return hashlib.sha1(f"{first['candidate_index']}:{first['area_m2']}".encode()).hexdigest()[:8]


def cmd_draw(a) -> int:
    import numpy as np
    import pandas as pd

    path = a.out / "review.csv"
    if K.name == "large" and (a.census_n or a.sample_n):
        raise SystemExit("--census-n / --sample-n belong to the blob review; the large "
                         "installation review is a queue only")
    pool = population(a.aoi, a.labels, a.min_distance_m, a.min_area_m2)
    queue = lead_screened(a.aoi, pool)
    print(f"{a.aoi}: {len(pool)} {K.noun} with no mapped solar within "
          f"{a.min_distance_m:.0f} m ({pool.area_m2.sum() / 1e6:.1f} km2); {len(queue)} after "
          f"the atlas's regions and the lead screens ({queue.area_m2.sum() / 1e6:.1f} km2)")
    if path.exists() and not a.redraw:
        _queue_rest(path, queue)
        return cmd_package(a)
    if queue.empty:
        print(f"nothing to review in {a.aoi}")
        return 0
    rng = np.random.default_rng(a.seed)
    census = queue.sort_values("area_m2", ascending=False).head(a.census_n)
    rest = queue.drop(census.index)
    pick = (rng.choice(rest.index, size=min(a.sample_n, len(rest)), replace=False,
                       p=rest["area_m2"] / rest["area_m2"].sum()) if a.sample_n else [])
    sample = rest.loc[pick]
    cols = _columns(queue)
    out = pd.concat([census[cols].assign(stratum="census", k=range(len(census))),
                     sample[cols].assign(stratum="sample", k=range(len(sample)))])
    out["code"] = [f"{s[0]}{k:02d}" for s, k in zip(out.stratum, out.k)]
    out["verdict"] = ""
    out["evidence"] = ""
    a.out.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    # The crops are named by code, and a new draw reuses the codes.
    shutil.rmtree(K.packages / a.aoi / "crops", ignore_errors=True)
    _queue_rest(path, queue)
    return cmd_package(a)


def _columns(pool) -> list[str]:
    """review.csv's columns from the pool: the large review also keeps each lead's placement,
    since a roof and a field read differently and convert at different constants."""
    cols = ["candidate_index", "lon", "lat", "area_m2", "region"]
    return cols + (["placement"] if K.name == "large" and "placement" in pool.columns else [])


def _queue_rest(path: Path, pool) -> None:
    """Append every outline of `pool` review.csv does not hold yet, largest first, as stratum
    `queue` (codes q0000...), keeping every row and verdict already there."""
    import pandas as pd

    rev = pd.read_csv(path)
    rest = pool[~pool["candidate_index"].isin(rev["candidate_index"])]
    rest = rest.sort_values("area_m2", ascending=False)
    in_queue = rev["stratum"] == "queue"
    k0 = int(rev.loc[in_queue, "k"].max() + 1) if in_queue.any() else 0
    q = rest[_columns(rest)].assign(stratum="queue", k=range(k0, k0 + len(rest)))
    q["code"] = [f"q{k:04d}" for k in q["k"]]
    q["verdict"] = ""
    q["evidence"] = ""
    pd.concat([rev, q], ignore_index=True).to_csv(path, index=False)
    print(f"queued {len(q)} more outlines ({q.area_m2.sum() / 1e6:.1f} km2), largest first; "
          f"{len(rev) + len(q)} in {path}")


def cmd_apply(a) -> int:
    import geopandas as gpd
    import numpy as np
    import pandas as pd

    from earthpv import capacity_calibration as cc
    from earthpv.postprocess import MAX_CANDIDATE_M2

    rev = pd.read_csv(a.review)
    if a.verdicts is not None:
        rev = _merge_page_verdicts(rev, a.verdicts, a.unsure_as, a.reviewer)
    queue = rev["stratum"] == "queue"
    bad = sorted(set(rev["verdict"].fillna("")) - set(VERDICTS) - {""})
    blank = rev["verdict"].fillna("").eq("") & ~queue
    if bad or blank.any():
        raise SystemExit(f"{a.review}: verdicts must be {VERDICTS}, found {bad or ['']}; only a "
                         "queue outline may stay blank (unreviewed)")
    if K.name == "large":
        if a.exclude_region:
            raise SystemExit("--exclude-region belongs to the blob review")
        # The band the review was drawn over, even if a later draw asked for a lower floor.
        a.min_area_m2 = float(min(a.min_area_m2, rev["area_m2"].min()))
    pool = population(a.aoi, a.labels, a.min_distance_m, a.min_area_m2)
    gone = rev[~rev["candidate_index"].isin(pool["candidate_index"])]
    c = pd.read_parquet(candidates_path(a.aoi), columns=["area_m2"])
    same = gone["candidate_index"].isin(c.index)
    if not same.all() or not np.allclose(c.loc[gone.loc[same, "candidate_index"], "area_m2"],
                                         gone.loc[same, "area_m2"], rtol=1e-6, atol=1.0):
        raise SystemExit(f"{len(gone)} reviewed outlines are not in the current population and "
                         "not in the candidates as drawn: candidates.parquet changed since the "
                         "draw, so start a new review with `draw --redraw`")
    if a.verdicts is not None:  # only once nothing above can refuse the sitting
        rev.to_csv(a.review, index=False)
    prior = (cc.load_table(cc.default_table_path(a.aoi)) or {}).get(K.table_key) or {}
    if K.name == "large":
        return _apply_large(a, rev, gone, prior)
    unknown = set(a.exclude_region) - set(pool["region"].dropna())
    if unknown:
        raise SystemExit(f"--exclude-region names no outline's region: {sorted(unknown)}")
    excluded = set(a.exclude_region) or set(prior.get("excluded_regions") or [])
    rev["real"] = rev["verdict"] == "pv"
    rev["excluded"] = rev["region"].isin(excluded)
    judged = rev["verdict"].fillna("").ne("")
    census = rev[rev.stratum == "census"]
    if census["excluded"].any():
        raise SystemExit("a census outline lies in an excluded region; the strata would overlap")
    sample = rev[(rev.stratum == "sample") & ~rev.excluded]
    ex = rev[(rev.stratum == "sample") & rev.excluded]
    earlier = prior.get("reviewer")  # every sitting's reviewer stays on record
    block = {
        "derived": date.today().isoformat(),
        "reviewer": f"{earlier}; {a.reviewer}" if earlier and a.reviewer not in earlier
                    else a.reviewer,
        "review_csv": str(a.review),
        "population": "model-drawn outlines above max_candidate_m2 with no mapped solar within "
                      "min_distance_m of them (export.new_lead_mask)",
        "max_candidate_m2": float(MAX_CANDIDATE_M2),
        "min_distance_m": float(a.min_distance_m),
        "mapped_reference": str(a.labels),
        "n_outlines": int(len(rev)),
        "n_judged": int(judged.sum()),
        "n_pv": int(rev["real"].sum()),
    }
    measured = ""
    if len(census) or len(sample) or len(ex):  # a drawn share, the record of how a review began
        block.update({
            "census_min_area_m2": float(census["area_m2"].min()) if len(census) else None,
            "census_n": int(len(census)),
            "census_real": int(census["real"].sum()),
            "sample_design": prior.get("sample_design") or (
                f"probability proportional to area, without replacement, seed {a.seed}, from "
                "the outlines below the census"),
            "sample_n": int(len(sample)),
            "sample_real": int(sample["real"].sum()),
            "excluded_regions": sorted(excluded),
            "excluded_sample_n": int(len(ex)),
            "excluded_sample_real": int(ex["real"].sum()),
        })
        p = cc.oversize_review_p_real(block)
        lo, hi = np.percentile(cc.oversize_review_draws(block, 4000)["sample"], cc.CI_PCT)
        block["p_real_census"] = round(p["census"], 4)
        block["p_real_sample"] = round(p["sample"], 4)
        block["p_real_sample_lo"] = round(float(lo), 4)
        block["p_real_sample_hi"] = round(float(hi), 4)
        measured = (f"census {block['census_real']}/{block['census_n']} real; sample "
                    f"{block['sample_real']}/{block['sample_n']} = {p['sample']:.3f} (90% "
                    f"{lo:.3f}-{hi:.3f}). ")
    path = cc.default_table_path(a.aoi)
    table = cc.load_table(path)
    table[cc.OVERSIZE_REVIEW_KEY] = block
    cc.write_table(table, path)
    pv = rev[rev["real"]]
    mapped_pv = pv[pv["candidate_index"].isin(gone["candidate_index"])]
    admits = pv.drop(mapped_pv.index)
    print(f"{measured}{block['n_judged']} of {len(rev)} outlines judged, {block['n_pv']} solar. "
          f"Admits {len(admits)}, {admits['area_m2'].sum() / 1e6:.1f} km2 -> {path}")
    if len(gone):
        print(f"{len(gone)} reviewed outlines are mapped since ({len(mapped_pv)} judged solar): "
              "the map counts those, not the verdict")
    write_hub()
    print(f"Next: `earthpv density --aoi {a.aoi} --districts`, then the atlas. `package` drops "
          "the judged outlines from the page.")
    return 0


def _apply_large(a, rev, gone, prior: dict) -> int:
    """`apply` for the large installation review: the `lead_review` block. Each judged lead
    is priced by its verdict in `density` (`_lead_verdicts`); nothing is drawn as a share."""
    import pandas as pd

    from earthpv import capacity_calibration as cc
    from earthpv.postprocess import MAX_CANDIDATE_M2

    v = rev["verdict"].fillna("")
    earlier = prior.get("reviewer")  # every sitting's reviewer stays on record
    block = {
        "derived": date.today().isoformat(),
        "reviewer": f"{earlier}; {a.reviewer}" if earlier and a.reviewer not in earlier
                    else a.reviewer,
        "review_csv": str(a.review),
        "population": "model-drawn new leads from min_area_m2 up to max_candidate_m2 with no "
                      "mapped solar within min_distance_m of them (export.new_lead_mask), inside "
                      "the atlas's regions and through the lead screens",
        "pricing": "a pv verdict sets the lead's P(real) to 1 on the ground and to "
                   "1/rooftop_outline_ratio on a roof (the model's roof outline is about that "
                   "many times its array), not_pv to 0; its size bin's recall still applies; "
                   "unsure or blank keeps the bin's P(real)",
        "rooftop_outline_ratio": float(prior.get("rooftop_outline_ratio")
                                       or cc.LEAD_ROOF_OUTLINE_RATIO),
        "min_area_m2": float(a.min_area_m2),
        "max_candidate_m2": float(MAX_CANDIDATE_M2),
        "min_distance_m": float(a.min_distance_m),
        "mapped_reference": str(a.labels),
        "n_outlines": int(len(rev)),
        "n_judged": int(v.isin(VERDICTS).sum()),
        "n_pv": int(v.eq("pv").sum()),
        "n_not_pv": int(v.eq("not_pv").sum()),
    }
    path = cc.default_table_path(a.aoi)
    table = cc.load_table(path)
    table[K.table_key] = block
    cc.write_table(table, path)
    live = ~rev["candidate_index"].isin(gone["candidate_index"])
    pv, no = live & v.eq("pv"), live & v.eq("not_pv")
    roof = (rev["placement"].astype(str).eq("rooftop") if "placement" in rev.columns
            else pd.Series(False, index=rev.index))
    credited = (rev.loc[pv & ~roof, "area_m2"].sum()
                + rev.loc[pv & roof, "area_m2"].sum() / block["rooftop_outline_ratio"])
    print(f"{block['n_judged']} of {len(rev)} leads judged: {int(pv.sum())} solar "
          f"({rev.loc[pv, 'area_m2'].sum() / 1e6:.2f} km2 of outline, {credited / 1e6:.2f} km2 "
          f"credited, roofs at 1/{block['rooftop_outline_ratio']:g}), {int(no.sum())} not solar "
          f"({rev.loc[no, 'area_m2'].sum() / 1e6:.2f} km2) count nothing -> {path}")
    if len(gone):
        print(f"{len(gone)} reviewed leads are mapped since: the map counts those, not the verdict")
    write_hub()
    print(f"Next: `earthpv density --aoi {a.aoi} --districts`, then the atlas. `package` drops "
          "the judged leads from the page.")
    return 0


def _share_row(aoi: str, path: Path) -> dict:
    import pandas as pd

    rev = pd.read_csv(path)
    v = rev["verdict"].fillna("")
    left = v.eq("")
    flag = rev["flag"].fillna("") if "flag" in rev.columns else pd.Series("", index=rev.index)
    return {"aoi": aoi, "n": len(rev), "judged": int((~left).sum()), "pv": int(v.eq("pv").sum()),
            "not_pv": int(v.eq("not_pv").sum()), "left": int(left.sum()),
            "bright": int(flag.eq("bright_roof").sum()),
            "left_km2": float(rev.loc[left, "area_m2"].sum() / 1e6),
            "page": (K.packages / aoi / "index.html").exists()}


def share_table() -> list[dict]:
    rows = [_share_row(p.parent.name.removesuffix(K.suffix), p)
            for p in sorted((REPO / "results").glob(f"*{K.suffix}/review.csv"))]
    return sorted(rows, key=lambda r: -r["left_km2"])


def cmd_status(a) -> int:
    rows = share_table()
    print(f"{'country':14s} {'outlines':>8s} {'judged':>7s} {'solar':>6s} {'not':>5s} "
          f"{'bright':>6s} {'left':>6s} {'left km2':>9s}  share judged")
    for r in rows:
        print(f"{r['aoi']:14s} {r['n']:8d} {r['judged']:7d} {r['pv']:6d} {r['not_pv']:5d} "
              f"{r['bright']:6d} {r['left']:6d} {r['left_km2']:9.1f}  "
              f"{r['judged'] / max(r['n'], 1):.0%}")
    print("bright: not PV on a very bright roof (key 4 on the page), counted inside 'not'")
    print(f"-> {write_hub()}")
    return 0


# --------------------------------------------------------------------------------------
# The review package: four panels per outline on disk, and the page to judge them in
# --------------------------------------------------------------------------------------
PANEL = 480
CONTEXT_MIN_M = 1500.0  # the context panels show at least this much ground
DETAIL_M = 1280.0       # the detail panel: native 10 m pixels around the outline's centre
# A FIXED reflectance stretch (L2A DN minus the 1,000 BOA offset, over 10,000), so a panel
# block reads as dark on every crop. India's first review used a per-crop percentile stretch,
# under which dark ploughed fields and burn scars looked like panels.
TRUE_RGB = (("B04", 0.30), ("B03", 0.28), ("B02", 0.26))
FALSE_RGB = (("B12", 0.45), ("B08", 0.50), ("B04", 0.30))
YELLOW = (255, 214, 0)

GUIDE = r"""      <ul>
        <li><b>PV</b>: a solar park inside the yellow outline. On the composite, blocks of
          even dark blue-grey with straight edges, a grid of access roads and small bright
          inverter pads; dark purple in the false colour; rows of panels on Esri. The outline
          is the model's and may be ragged or leave gaps: judge whether a park is there, not
          how well it is traced.</li>
        <li><b>Not PV</b>: something else, typically dark ploughed fields, water or aquaculture
          ponds, burn scars, rock, a shaded slope, snow, a riverbed or greenhouses. Fields are
          dark only in true colour; water is dark in every panel.</li>
        <li><b>Unsure</b>: these four panels cannot settle it. Open the links and decide, or
          leave it unsure: it does not count, and it comes back next time.</li>
        <li><b>Bright roof</b>: not PV, and the outline sits on very bright roofs (white or
          light metal, a reflective coating). It counts as Not PV; the label keeps these
          false alarms apart so they can be studied.</li>
      </ul>
      <p>The composite is the imagery the model read, so it shows parks built after the Esri
        capture: panels on the composite and bare or freshly cleared ground on an older Esri
        image is a park built since. A flat grey block is a cell nobody imaged; a black block,
        dark red in the false colour, is a cell that lost bands. Neither is ground: judge
        those parts on Esri. Keys: <kbd>1</kbd> PV, <kbd>2</kbd> Not PV,
        <kbd>3</kbd> unsure, <kbd>4</kbd> bright roof, <kbd>&larr;</kbd> <kbd>&rarr;</kbd>
        step, <kbd>n</kbd> note.</p>
      <p>Stop whenever you like: progress stays in this browser, and any export can be
        applied, however partial. An outline left blank or unsure stays out of capacity and
        comes back on the next page. Export, then run
        <code>pixi run blob-review apply --aoi __AOI__ --reviewer "&lt;name&gt;"
        --verdicts &lt;the export&gt;</code>.</p>"""

GUIDE_LARGE = r"""      <ul>
        <li><b>PV</b>: solar panels inside or touching the yellow outline, on a roof or on the
          ground. On Esri, rows of dark blue-grey rectangles in a regular grid, often with a
          thin gap between rows; on a roof they follow its edges and leave a margin. On the
          composite, an even dark patch with straight edges, dark purple in the false colour.
          The outline is the model's and is often larger than the array: judge whether PV is
          there, not how much of the outline it fills.</li>
        <li><b>Not PV</b>: something else, typically a dark or blue metal roof, a tar or wet
          roof, greenhouses or shade netting, solar water heaters (small, scattered, with a
          tank), a car park, water, a dark field, rock or a shadow, and the imagery is recent
          enough to show panels if they were there.</li>
        <li><b>Unsure</b>: these four panels cannot settle it. Open the links and decide, or
          leave it unsure: it keeps the price it had, and it comes back next time.</li>
        <li><b>Bright roof</b>: not PV, and the outline sits on a very bright roof (white or
          light metal, a reflective coating), bright on the composite as well as on Esri. It
          counts as Not PV; the label keeps these false alarms apart so they can be
          studied. A bright roof that does carry panels is PV.</li>
      </ul>
      <p>These leads already count, each at the share its size class is usually right. Your
        verdict replaces that share for this lead alone: solar counts it as real (a roof
        outline at 1/2.5 of its area, since the model draws about 2.5 times the array there),
        not solar counts it as nothing. The composite is the imagery the model read, so it shows arrays
        built after the Esri capture. A flat grey block is a cell nobody imaged. Keys:
        <kbd>1</kbd> PV, <kbd>2</kbd> Not PV, <kbd>3</kbd> unsure, <kbd>4</kbd> bright roof,
        <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step, <kbd>n</kbd> note.</p>
      <p>Stop whenever you like: progress stays in this browser, and any export can be
        applied, however partial. Export, then run
        <code>pixi run large-review apply --aoi __AOI__ --reviewer "&lt;name&gt;"
        --verdicts &lt;the export&gt;</code>.</p>"""


def _render_job(job: tuple) -> tuple[str, bool, str | None]:
    code, args = job
    try:
        ok, esri_date = _render(*args)
    except Exception as e:  # noqa: BLE001 -- one bad outline must not stop the country
        print(f"  {code}: not rendered: {e}", flush=True)
        return code, False, None
    return code, ok, esri_date


def _epoch(aoi: str, cfg: dict) -> str:
    """The imagery window as the page says it; an AOI built before `compose_window` existed
    gets the span of its scenes, from `scripts/imagery_median_date.py`."""
    import yaml

    window = cfg.get("compose_window")
    if window:
        return f"{_month(window[0])} to {_month(window[1])}"
    path = REPO / "configs" / "atlas_imagery_dates.yaml"
    dates = (yaml.safe_load(path.read_text()).get("aois") or {}).get(aoi) if path.exists() else None
    if dates:
        return f"{_month(str(dates['first']))} to {_month(str(dates['last']))}"
    return "composite"


def cmd_package(a) -> int:
    """Render every row of review.csv and write the page, the JOSM GeoJSON and the codes."""
    import geopandas as gpd
    import pandas as pd

    from build_review_page import write_page

    from earthpv.config import Settings
    from earthpv.density import _grid_origin

    path = a.out / "review.csv"
    rev = pd.read_csv(path)
    if "code" not in rev.columns:
        rev.insert(0, "code", [f"{s[0]}{k:02d}" for s, k in zip(rev.stratum, rev.k)])
        rev.to_csv(path, index=False)
    cands = gpd.read_parquet(candidates_path(a.aoi), columns=["geometry"])
    geoms = cands.geometry.loc[rev.candidate_index].to_numpy()
    s = Settings.load()
    cfg = s.aois[a.aoi]
    origin = _grid_origin(a.aoi, cfg, s)
    epoch = _epoch(a.aoi, cfg)
    pkg = K.packages / a.aoi
    (pkg / "crops").mkdir(parents=True, exist_ok=True)
    comp = REPO / f"data/composites/{a.aoi}/composites"
    show = rev["verdict"].fillna("").eq("") | a.include_judged
    jobs = []
    for r, g, on_page in zip(rev.itertuples(), geoms, show):
        jpg, meta = pkg / "crops" / f"{r.code}.jpg", pkg / "crops" / f"{r.code}.esri"
        if on_page and (a.force or not jpg.exists() or not meta.exists()):
            jobs.append((r.code, (g, comp, origin, epoch, jpg, not a.no_esri,
                                  K.context_min_m, K.detail_m, K.esri_min_m)))
    no_esri = 0
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for n, (code, ok, esri_date) in enumerate(pool.map(_render_job, jobs, chunksize=4), 1):
            # No marker for a failed Esri fetch, so the next `package` tries that one again.
            if ok:
                (pkg / "crops" / f"{code}.esri").write_text(esri_date or "")
            no_esri += not ok
            if n % 100 == 0 or n == len(jobs):
                print(f"  {a.aoi}: {n} of {len(jobs)} rendered", flush=True)
    items, dates, unrendered = [], [], []
    for r, g, on_page in zip(rev.itertuples(), geoms, show):
        meta = pkg / "crops" / f"{r.code}.esri"
        esri_date = meta.read_text().strip() if meta.exists() else ""
        dates.append(esri_date)
        if not on_page:
            continue
        if not (pkg / "crops" / f"{r.code}.jpg").exists():
            unrendered.append(r.code)
            continue
        w, so, e, n = g.bounds
        p = g.representative_point()
        size = (f"{r.area_m2:,.0f} m² · {PLACES.get(getattr(r, 'placement', ''), 'placement unknown')}"
                if K.name == "large" else f"{r.area_m2 / 1e4:,.0f} ha")
        items.append({
            "code": r.code, "img": f"crops/{r.code}.jpg", "date": esri_date,
            "date_label": f"{size} · {r.region} · Esri {esri_date or 'not fetched'}",
            "lon": round(p.x, 6), "lat": round(p.y, 6),
            "bbox": [round(w - 0.002, 6), round(so - 0.002, 6), round(e + 0.002, 6),
                     round(n + 0.002, 6)],
        })
    if not items:
        (pkg / "index.html").unlink(missing_ok=True)
        print(f"every outline of {a.aoi} has a verdict; no page")
    else:
        guide = GUIDE_LARGE if K.name == "large" else GUIDE
        page = write_page(pkg / "index.html", f"{a.aoi}{K.suffix}", items,
                          guide=guide.replace("__AOI__", a.aoi), title=K.title,
                          store=f"{a.aoi}{K.suffix}:{_draw_id(rev)}",
                          export_name=K.export.format(aoi=a.aoi), back="../index.html",
                          bright_roof=True)
        print(f"{len(items)} of {len(rev)} outlines on the page -> {page}"
              + (f"; {no_esri} without their Esri panel (`package` retries)" if no_esri else ""))
    if unrendered:
        print(f"{len(unrendered)} outlines could not be rendered and are not on the page "
              f"(`package` retries them): {unrendered[:8]}")
    rev["esri_date"] = dates
    gj = gpd.GeoDataFrame({
        "name": [f"{c} {v}" if isinstance(v, str) and v else c
                 for c, v in zip(rev.code, rev.verdict)],
        "review_verdict": rev.verdict, "review_evidence": rev.evidence, "esri_date": rev.esri_date,
        "stratum": rev.stratum, "k": rev.k, "area_ha": (rev.area_m2 / 1e4).round(1),
        "region": rev.region, "candidate_index": rev.candidate_index,
        **({"placement": rev.placement} if "placement" in rev.columns else {}),
        **({"review_flag": rev["flag"]} if "flag" in rev.columns else {}),
    }, geometry=geoms, crs="EPSG:4326")
    gj.to_file(a.out / "review.geojson", driver="GeoJSON")
    print(f"JOSM layer {a.out / 'review.geojson'}. Do not upload it: the outlines are the model's.")
    write_hub()
    return 0


HUB_ROW = ('<tr><td>{link}</td><td>{left:,}</td><td>{left_km2:,.1f}</td><td>{judged:,} of {n:,} '
           '({share:.0%})</td><td>{pv:,}</td><td>{not_pv:,}</td></tr>')
PLACES = {"rooftop": "on a roof", "ground_adjacent": "beside a building",
          "no_building": "open ground"}
HUB_INTRO = {
    "blob": """Very large model outlines, one look each: Sentinel-2 as the model saw it, its false colour,
and Esri for texture. An outline counts towards capacity only once a person judges it solar
or it is mapped in OpenStreetMap. Largest first within each country.""",
    "large": """The model's large leads below the solar farm cap, from 10,000 m&sup2;, on roofs and on the
ground, one look each: Sentinel-2 as the model saw it, its native pixels, its false colour, and
Esri for texture. They already count, each at the share its size class is usually right; a
verdict replaces that share for its own lead (solar: real, a roof outline at 1/2.5 of its area;
not solar: nothing). Largest first
within each country. The <a href="../oversize_review/index.html">solar farm review</a> has the
outlines above the cap.""",
}
HUB = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { color-scheme: light dark; --ink: light-dark(#1d2330, #e6e9ef);
  --muted: light-dark(#5d6677, #98a2b3); --line: light-dark(#d9dde5, #2a3140);
  --accent: light-dark(#2563eb, #6ea8ff); --bg: light-dark(#f6f7f9, #0f131a); }
body { margin: 0 auto; max-width: 860px; padding: 24px 16px; background: var(--bg);
  color: var(--ink); font: 15px/1.5 system-ui, sans-serif; }
h1 { font-size: 22px; margin: 0 0 8px; }
p { color: var(--muted); }
a { color: var(--accent); }
table { width: 100%; border-collapse: collapse; margin: 16px 0; }
th, td { padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: right;
  font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; }
th { font-size: 13px; color: var(--muted); font-weight: 600; }
code { font-size: 13px; }
</style></head><body>
<h1>__TITLE__</h1>
<p>__INTRO__</p>
<table><thead><tr><th>Country</th><th>To judge</th><th>km&sup2; to judge</th><th>Judged</th>
<th>Solar</th><th>Not solar</th></tr></thead><tbody>
__ROWS__
</tbody></table>
<p>Counts are what <code>apply</code> has recorded. Progress since then is in each page, until
you export it and run<br>
<code>pixi run __TASK__ apply --aoi &lt;country&gt; --reviewer "&lt;name&gt;" --verdicts
&lt;the export&gt;</code><br>
then <code>earthpv density --aoi &lt;country&gt; --districts</code> and the atlas.</p>
</body></html>
"""


def write_hub() -> Path:
    """`<packages>/index.html` (`data/oversize_review/` or `data/large_review/`): every country's
    page and what `apply` has recorded."""
    from release_leads import country_name

    rows = []
    for r in share_table():
        name = country_name(r["aoi"])
        link = f'<a href="{r["aoi"]}/index.html">{name}</a>' if r["page"] else name
        rows.append(HUB_ROW.format(link=link, share=r["judged"] / max(r["n"], 1), **r))
    K.packages.mkdir(parents=True, exist_ok=True)
    out = K.packages / "index.html"
    out.write_text(HUB.replace("__TITLE__", K.title).replace("__INTRO__", HUB_INTRO[K.name])
                   .replace("__TASK__", K.task).replace("__ROWS__", "\n".join(rows)))
    return out


def _month(day: str) -> str:
    from datetime import date as _d

    return _d.fromisoformat(day).strftime("%b %Y")


def _render(geom, comp_dir: Path, origin, epoch: str, out: Path, esri: bool = True,
            context_min_m: float = CONTEXT_MIN_M, detail_m: float = DETAIL_M,
            esri_min_m: float | None = None) -> tuple[bool, str | None]:
    """One outline's four panels as a 2 x 2 JPEG. Returns whether the panels are as asked (an
    Esri fetch that failed is not, and wants another try) and the Esri capture date. The
    widths are the review kind's (`Kind`); `esri_min_m` None gives Esri the composite's."""
    from PIL import Image
    from pyproj import Transformer

    rep = geom.representative_point()
    utm = f"EPSG:{(32600 if rep.y >= 0 else 32700) + int((rep.x + 180) // 6) + 1}"
    to_utm = Transformer.from_crs("EPSG:4326", utm, always_xy=True)
    gu = _transform(geom, to_utm)
    x0, y0, x1, y1 = gu.bounds
    extent = max(x1 - x0, y1 - y0)
    side = max(context_min_m, 1.25 * extent)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = to_utm.transform(rep.x, rep.y)
    bands = sorted({b for b, _ in TRUE_RGB + FALSE_RGB})
    ctx, ctx_tf = _s2_window(comp_dir, origin, utm, cx, cy, side, bands)
    det, det_tf = _s2_window(comp_dir, origin, utm, rx, ry, detail_m, bands)
    km = f"{side / 1000:.1f} km across"
    panels = [
        _caption(_outline(_rgb(ctx, bands, TRUE_RGB), gu, ctx_tf), f"Sentinel-2 {epoch}, {km}"),
        _caption(_outline(_rgb(det, bands, TRUE_RGB), gu, det_tf),
                 f"10 m pixels, {detail_m / 1000:.1f} km across"),
        _caption(_outline(_rgb(ctx, bands, FALSE_RGB), gu, ctx_tf),
                 "false colour: SWIR, NIR, red"),
    ]
    esri_date, ok = None, True
    if esri:
        esri_side = side if esri_min_m is None else max(esri_min_m, 1.6 * extent)
        im, esri_date = _esri(geom, rep, esri_side)
        ok = im is not None
        width = "" if esri_min_m is None else f", {esri_side:,.0f} m across"
        panels.append(_caption(im, f"Esri World Imagery {esri_date or '(no capture date)'}{width}"))
    if len(panels) < 4 or panels[3] is None:
        panels = panels[:3] + [_caption(Image.new("RGB", (PANEL, PANEL), (40, 40, 40)),
                                        "Esri not fetched")]
    sheet = Image.new("RGB", (2 * PANEL, 2 * PANEL))
    for i, p in enumerate(panels):
        sheet.paste(p, ((i % 2) * PANEL, (i // 2) * PANEL))
    sheet.save(out, "JPEG", quality=86)
    return ok, esri_date


def _transform(geom, tr):
    from shapely.ops import transform

    return transform(lambda x, y, z=None: tr.transform(x, y), geom)


def _s2_window(comp_dir: Path, origin, utm: str, cx: float, cy: float, side: float, bands):
    """The composite cells under a square window, mosaicked onto one PANEL x PANEL grid in
    the outline's own UTM zone (a window can cross cells, and cells can sit in other zones)."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject, transform_bounds

    from earthpv.config import LOCAL_BANDS

    res = side / PANEL
    tf = from_origin(cx - side / 2, cy + side / 2, res, res)
    out = np.zeros((len(bands), PANEL, PANEL), "float32")
    w, s, e, n = transform_bounds(utm, "EPSG:4326", cx - side / 2, cy - side / 2,
                                  cx + side / 2, cy + side / 2)
    ox, oy = origin
    rs = Resampling.nearest if res <= 10.0 else Resampling.average
    for i in range(int((w - ox) // 0.1), int((e - ox) // 0.1) + 1):
        for j in range(int((s - oy) // 0.1), int((n - oy) // 0.1) + 1):
            f = comp_dir / f"{i:04d}_{j:04d}" / "composite_0.tif"
            if not f.exists():
                continue
            with rasterio.open(f) as src:
                for k, b in enumerate(bands):
                    tmp = np.zeros((PANEL, PANEL), "float32")
                    reproject(rasterio.band(src, LOCAL_BANDS.index(b) + 1), tmp, src_nodata=0,
                              dst_nodata=0, dst_transform=tf, dst_crs=utm, resampling=rs)
                    out[k] = np.where(out[k] == 0, tmp, out[k])
    return out, tf


def _rgb(arr, bands, spec):
    import numpy as np
    from PIL import Image

    chans = []
    for b, top in spec:
        dn = arr[bands.index(b)]
        refl = np.clip((dn - 1000.0) / 10000.0, 0.0, None)
        chans.append(np.where(dn > 0, np.clip(refl / top, 0, 1) * 255, 40))
    return Image.fromarray(np.stack(chans, -1).astype("uint8"))


def _outline(im, geom_utm, tf):
    from PIL import ImageDraw

    d = ImageDraw.Draw(im)
    inv = ~tf
    for part in getattr(geom_utm, "geoms", [geom_utm]):
        for ring in [part.exterior, *part.interiors]:
            d.line([inv * xy for xy in ring.coords], fill=YELLOW, width=2)
    return im


def _caption(im, text: str):
    from PIL import ImageDraw, ImageFont

    if im is None:
        return None
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=15)
    d.rectangle([0, PANEL - 24, PANEL, PANEL], fill=(0, 0, 0))
    d.text((6, PANEL - 21), text, fill=(255, 255, 255), font=font)
    return im


def _esri(geom, rep, side: float):
    """Esri World Imagery over the context window (Web Mercator, so the crop is square), the
    outline drawn on it, and the capture date at the outline's centre (the calibration
    sampler's own query). (None, None) on any network failure.

    Where Esri holds nothing as fine as the window asks for (most of Namibia stops at zoom 17,
    about 1.2 m), `export` answers HTTP 500, so a failed request is asked again at half and
    then a quarter of the pixels over the same window and scaled up: the large installation
    review's 250 m windows ask for 0.5 m."""
    import io
    import math
    import urllib.request

    from PIL import Image, ImageDraw
    from pyproj import Transformer

    from propose_calibration_candidates import esri_capture

    to_m = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    gm = _transform(geom, to_m)
    x0, y0, x1, y1 = gm.bounds
    half = side / math.cos(math.radians(rep.y)) / 2
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bbox = (cx - half, cy - half, cx + half, cy + half)
    im = None
    for px in (PANEL, PANEL // 2, PANEL // 4):
        url = ("https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/"
               f"export?bbox={','.join(f'{v:.2f}' for v in bbox)}&bboxSR=3857&imageSR=3857"
               f"&size={px},{px}&format=jpg&f=image")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "earthpv-oversize-review"})
            im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=60).read())).convert("RGB")
            break
        except Exception:  # noqa: BLE001 -- coarser next; the panel says it is missing at last
            continue
    if im is None:
        return None, None
    if im.size != (PANEL, PANEL):
        im = im.resize((PANEL, PANEL), Image.Resampling.BICUBIC)
    d = ImageDraw.Draw(im)
    scale = PANEL / (2 * half)
    for part in getattr(gm, "geoms", [gm]):
        for ring in [part.exterior, *part.interiors]:
            d.line([((x - bbox[0]) * scale, (bbox[3] - y) * scale) for x, y in ring.coords],
                   fill=YELLOW, width=2)
    cap = esri_capture(rep.x, rep.y)
    return im, (cap["date"].isoformat() if cap else None)


def _merge_page_verdicts(rev, verdicts: Path, unsure_as: str | None, reviewer: str):
    """The page's export (`code,imagery_date,verdict,note`) into review.csv's rows."""
    import numpy as np
    import pandas as pd

    v = pd.read_csv(verdicts, dtype=str).fillna("").set_index("code")
    v = v.reindex(rev.code).fillna("")
    queue = (rev["stratum"] == "queue").to_numpy()
    prev0 = rev["verdict"].fillna("").to_numpy()
    missing = sorted(set(rev.code[(v.verdict.to_numpy() == "") & ~queue & (prev0 == "")]))
    if missing:
        raise SystemExit(f"{len(missing)} outlines have no verdict in {verdicts}: {missing[:8]}")
    unknown = sorted(set(v["verdict"]) - set(PAGE_VERDICTS))
    if unknown:
        raise SystemExit(f"{verdicts}: unknown verdicts {unknown}; the page writes "
                         f"{sorted(k for k in PAGE_VERDICTS if k)}")
    page = v["verdict"].map({k: m[0] for k, m in PAGE_VERDICTS.items()})
    flag = v["verdict"].map({k: m[1] for k, m in PAGE_VERDICTS.items()}).to_numpy()
    # No verdict on the page for an outline judged before: keep the earlier one.
    page = pd.Series(np.where(page.to_numpy() == "", prev0, page.to_numpy()), index=page.index)
    is_unsure = (page == "unsure").to_numpy()
    unsure = list(rev.code[is_unsure & ~queue])
    if unsure and unsure_as is None:
        raise SystemExit(f"{len(unsure)} census or sample outlines are unsure ({unsure[:8]}): "
                         "their share needs a verdict. Settle them on the linked imagery, or "
                         "pass --unsure-as not_pv to price them as absent")
    # An unsure queue outline stays open: it does not count and comes back on the next page.
    open_q = is_unsure & queue
    if unsure_as is None:
        page = page.where(~open_q, prev0)
        if open_q.any():
            print(f"{int(open_q.sum())} queue outlines left unsure: out of capacity, back on "
                  "the next page")
    else:
        unsure = list(rev.code[is_unsure])
    page = page.replace("unsure", unsure_as or "unsure").to_numpy()
    prev = rev["verdict"].fillna("").to_numpy()
    judged = (prev != "") & (v["verdict"].to_numpy() != "")
    if judged.any():
        agree = (prev[judged] == page[judged]).sum()
        print(f"{reviewer} agrees with the earlier verdicts on {agree} of {judged.sum()} outlines; "
              f"they differ on {', '.join(rev.code[judged & (prev != page)]) or 'none'}")
        # The first differing verdict stays on record over repeated partial applies.
        changed = judged & (prev != page)
        if "verdict_prev" not in rev:
            rev["verdict_prev"] = ""
        rev["verdict_prev"] = rev["verdict_prev"].astype(object)
        rev.loc[changed, "verdict_prev"] = prev[changed]
    rev["verdict"] = page
    note = v["note"].to_numpy()
    fresh = v["verdict"].to_numpy() != ""
    # A fresh verdict sets the flag (or clears one an earlier sitting set); none keeps it.
    old_flag = (rev["flag"].astype(object).fillna("").to_numpy() if "flag" in rev
                else np.full(len(rev), "", dtype=object))
    rev["flag"] = np.where(fresh, flag, old_flag)
    if (flag == "bright_roof").any():
        print(f"{int((flag == 'bright_roof').sum())} outlines judged not PV on a very bright "
              "roof: priced as not_pv, flagged bright_roof in review.csv")
    # A column of blanks reads back as floats.
    old = (rev["evidence"].astype(object).fillna("").to_numpy() if "evidence" in rev
           else [""] * len(rev))
    rev["evidence"] = [(f"{reviewer}: {n}" if n else f"{reviewer}") if f else o
                       for n, f, o in zip(note, fresh, old)]
    if unsure_as is None and open_q.any():
        rev.loc[open_q, "evidence"] = rev.loc[open_q, "evidence"].astype(str) + " (unsure)"
    for c in unsure:
        rev.loc[rev.code == c, "evidence"] += f" (unsure, priced as {unsure_as})"
    return rev


def main() -> int:
    global K
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kind", choices=sorted(KINDS), default="blob",
                    help="blob: outlines above the cap (the solar farm review); large: leads "
                         "from --min-area-m2 up to the cap (the large installation review)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("draw", "package", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--aoi", required=True)
        p.add_argument("--labels", type=Path, default=None,
                       help="the mapped reference (default: the published run's own, run_source)")
        p.add_argument("--min-distance-m", type=float, default=100.0)
        p.add_argument("--seed", type=int, default=20261028)
        p.add_argument("--min-area-m2", type=float, default=None,
                       help=f"--kind large: the smallest lead drawn (default {LARGE_MIN_M2:,.0f})")
    sub.add_parser("status", help="every country's verdicts; refreshes the index page")
    d = sub.choices["draw"]
    d.add_argument("--census-n", type=int, default=0,
                   help="judge the N largest outlines as a census, ahead of the queue")
    d.add_argument("--sample-n", type=int, default=0,
                   help="judge N more drawn by area as a sample, ahead of the queue")
    d.add_argument("--redraw", action="store_true",
                   help="start over from the current candidates (every verdict is lost)")
    for name in ("draw", "package"):
        q = sub.choices[name]
        q.add_argument("--out", type=Path, default=None)
        q.add_argument("--no-esri", action="store_true", help="leave the Esri panel out (offline)")
        q.add_argument("--force", action="store_true", help="re-render crops that exist")
        q.add_argument("--workers", type=int, default=4)
        q.add_argument("--include-judged", action="store_true",
                       help="keep outlines with a verdict on the page, to judge them again")
    p = sub.choices["apply"]
    p.add_argument("--review", type=Path, default=None)
    p.add_argument("--verdicts", type=Path, default=None,
                   help="the review page's export (code,imagery_date,verdict,note)")
    p.add_argument("--unsure-as", choices=VERDICTS, default=None,
                   help="price an outline left unsure as this verdict (default: a queue outline "
                        "stays open; a census or sample outline is refused)")
    p.add_argument("--exclude-region", action="append", default=[],
                   help="keep a region's sample rows apart in the measured share; a record only")
    p.add_argument("--reviewer", required=True)
    a = ap.parse_args()
    K = KINDS[a.kind]
    if a.cmd == "status":
        return cmd_status(a)
    if K.name == "large":
        a.min_area_m2 = LARGE_MIN_M2 if a.min_area_m2 is None else a.min_area_m2
    elif a.min_area_m2 is not None:
        raise SystemExit("--min-area-m2 belongs to --kind large; the blob review starts at the cap")
    a.labels = a.labels or Path(run_source(a.aoi)["osm"])
    if a.cmd in ("draw", "package"):
        a.out = a.out or REPO / "results" / f"{a.aoi}{K.suffix}"
        return cmd_draw(a) if a.cmd == "draw" else cmd_package(a)
    a.review = a.review or Path(f"results/{a.aoi}{K.suffix}/review.csv")
    return cmd_apply(a)


if __name__ == "__main__":
    raise SystemExit(main())
