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

**The page shows Sentinel-2 only, and a verdict counts only from such a page (owner,
2026-11-20).** The project uses no verdict drawn from imagery it is not licensed to use for
that: Esri's terms forbid using its imagery to verify a published compilation (Master
Agreement 3.3(b)) and allow it only for tracing into open data such as OpenStreetMap, and
Mapbox's likewise. So the page (`package`, run by `draw`) is the Sentinel-2 composite of the
imagery window the model saw, free Copernicus data, three panels saved in
`data/oversize_review/<aoi>/crops/`: `<code>_s2.jpg` true colour around the whole outline,
`<code>_pixels.jpg` the same at native 10 m pixels, `<code>_false.jpg` a false colour of SWIR,
NIR and red. Its links open only free data: Sentinel-2 at any date in the Copernicus Browser,
the OpenStreetMap map, and JOSM to map the installation, where the editor's imagery is licensed
for exactly that. The export's `imagery_date` says `Sentinel-2 only` (`S2_ONLY`), `apply`
records it in review.csv's `imagery` column and refuses an export from any earlier page, which
showed Esri World Imagery beside Sentinel-2 (saved before 2026-11-19, live after). Verdicts
applied before 2026-11-20 have no `imagery` and stand as given. The composite is also the right
epoch: 11 of the 50 parks of India's sample were built after their Esri capture. Its limit is
10 m: an outline Sentinel-2 cannot settle is left unsure, and mapping it is how it then counts.
The page shows no model score, and nothing from an earlier verdict, so a second reviewer judges
blind; `apply` reports agreement. The review is a human reading of imagery: record who reviewed
it in `--reviewer`.

**JOSM: review while mapping into OpenStreetMap (owner, 2026-11-20).** `package` also writes
`<packages>/<aoi>/<aoi><suffix>.osm`, the open outlines as a JOSM layer that refuses upload
(`write_josm`), largest first, each tagged `earthpv:code`, its size, placement and region, and
`earthpv:review=todo`; it refuses download as well, so JOSM's continuous download cannot fill
it. A reviewer opens it beside the OpenStreetMap data (docs/contribute/review.md: the Todo list
and continuous download, as for the confirmed leads), looks at each outline on the imagery JOSM
offers for mapping and maps the solar that is there. **The map is the verdict**: a mapped
outline needs no mark; once the country's OpenStreetMap solar is pulled again it leaves the
pool (`osm` = `mapped` in review.csv, the same for an outline anyone mapped) and the map counts
it at its own shape. An outline with no solar is marked `earthpv:review=not_pv` (`unsure`, or
`mapped` to say so before the pull, are accepted), the layer saved, and `apply --josm <the
saved layer>` records the marks in review.csv's `josm` column (`read_josm`; the layer names its
draw, `earthpv:draw`, and `apply` refuses another's). A `not_pv` mark is a judgement on imagery
licensed only for mapping into OpenStreetMap, so it takes the outline off the review and
prices nothing: a large lead keeps its size class's measured share, a blob still counts
nothing, and no lead file, study or training set reads it. This is the large installation
review's default (`--kind large` writes no page unless `--page`); the blob review writes both.

**Verdicts become mapping leads (2026-11-19).** scripts/release_leads.py reads the review
blocks `apply` writes: an outline judged solar that OpenStreetMap still lacks goes to the
country's `<aoi>_pv_confirmed_leads.geojson`, the first file a mapper opens, and one judged not
solar leaves the lead and blob files. Re-run it (`--aoi <aoi> --upload`, then
scripts/patch_atlas_leads.py) after the atlas whenever a sitting is applied.

**A verdict names one candidate file.** An outline judged and then mapped in OpenStreetMap
leaves the pool and is counted from the map (no error, `apply` reports it). A new model run
renumbers the candidates, so `apply` and `density` refuse the old review; `draw --redraw` starts
a new one, and because the page's saved progress is keyed to the draw, old verdicts cannot
attach themselves to the new outlines.

**`--kind large`: the large installation review (owner, 2026-11-10), a default step too.** The
same review for the leads BELOW the cap, from `LARGE_MIN_M2` (10,000 m2, `--min-area-m2`) up to
it: model-drawn new leads through the same regions and screens, rooftop and ground alike,
largest first, in `results/<aoi>_large_review/` and `data/large_review/` (on /home). These
leads are already in capacity, each at its size bin's P(real). **It is done in JOSM, mapping
the real installations into OpenStreetMap (owner, 2026-11-20)**: `draw` writes the JOSM layer
and no page. A lead mapped counts from the map once the country's solar is pulled again (its
model outline is then de-duplicated against the mapped one). `--page` adds the Sentinel-2 page
for leads 10 m pixels can settle, mostly on open ground: its verdicts replace the lead's price
(`pv` 1 on the ground and 1/2.5 on a roof, where the model's outline is about 2.5 times the
array, owner 2026-11-10; `not_pv` 0) and keep the bin's recall
(`capacity_calibration.LEAD_REVIEW_KEY`, `density._lead_verdicts`). Any named reviewer counts
(owner, 2026-11-10). Its crops are cut tighter (1 km of composite, 400 m of native pixels),
because a 1 ha roof is a speck in a park's window.

    pixi run large-review draw --aoi india
    # open data/large_review/india/india_large_review.osm in JOSM, map, set earthpv:review, save
    pixi run large-review apply --aoi india --reviewer "<name>" --josm <the saved layer>
    # pull the country's OpenStreetMap solar again, then (with the new pull as --labels):
    pixi run large-review apply --aoi india --reviewer "<name>" --labels <the new pull>
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
# What a page built since 2026-11-20 writes in its export's `imagery_date`, and review.csv's
# `imagery` for the verdicts it gave: the page showed the Sentinel-2 composite and nothing else.
# `apply` takes no verdict without it (owner, 2026-11-20: no verdict from imagery the project
# may not use).
S2_ONLY = "Sentinel-2 only"
# A JOSM layer's `earthpv:review` values (`read_josm`): `todo` is open, as `unsure` is. A lead
# mapped needs no mark (the next OpenStreetMap pull finds it); `mapped` only says so early.
JOSM_OUTCOMES = ("mapped", "not_pv", "unsure")
JOSM_DONE = ("mapped", "not_pv")
DO_NOT_UPLOAD = "earthpv review layer - do not upload to OpenStreetMap"
HASHTAGS = ["#tracethesun", "#earthpv"]


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
    noun: str              # what one row is, in messages
    page: bool             # `package` writes the Sentinel-2 page by default (else JOSM only)
    hashtag: str           # the JOSM changeset's own hashtag, beside HASHTAGS


KINDS = {
    "blob": Kind("blob", "Solar farm review", "_oversize_review", REPO / "data" / "oversize_review",
                 "{aoi}_blob_verdicts.csv", "blob-review", "oversize_review", 1500.0, 1280.0,
                 "outlines above the cap", True, "#earthpv-solar-farm-review"),
    "large": Kind("large", "Large installation review", "_large_review",
                  REPO / "data" / "large_review", "{aoi}_large_verdicts.csv", "large-review",
                  "lead_review", 1000.0, 400.0, "leads below the cap", False,
                  "#earthpv-large-review"),
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
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    from earthpv.density import is_subnational, subnational_units

    # A state or province AOI names its leads by its own ADM2 units, which are also the
    # regions `density` will write: the country's ADM1 layer would keep the leads of the
    # border cells that lie in a neighbouring state.
    adm1 = (subnational_units(aoi, cfg, settings) if is_subnational(cfg)
            else fetch_geoboundaries(_iso3_for(cfg), "ADM1")).to_crs(4326)
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
        rev = pd.read_csv(path)
        gone, same = _gone(rev, pool, a.aoi)
        if same:
            _mark_mapped(rev, gone).to_csv(path, index=False)
        else:
            print(f"{len(gone)} reviewed outlines are not in the candidates as drawn: "
                  "candidates.parquet changed since the draw, so start again with `--redraw`")
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


def _gone(rev, pool, aoi: str):
    """review.csv's rows no longer in `pool` (mapped in OpenStreetMap since the draw, by the
    reference `pool` was drawn against), and whether every one of them is still in the
    candidates at the area drawn (False: candidates.parquet changed since the draw)."""
    import numpy as np
    import pandas as pd

    gone = rev[~rev["candidate_index"].isin(pool["candidate_index"])]
    c = pd.read_parquet(candidates_path(aoi), columns=["area_m2"])
    same = gone["candidate_index"].isin(c.index)
    ok = bool(same.all()) and bool(np.allclose(c.loc[gone.loc[same, "candidate_index"], "area_m2"],
                                               gone.loc[same, "area_m2"], rtol=1e-6, atol=1.0))
    return gone, ok


def _mark_mapped(rev, gone):
    """review.csv's `osm` column: `mapped` for an outline now mapped in OpenStreetMap (it left
    the pool), whoever mapped it; the map counts it and any verdict on it rests."""
    import numpy as np

    rev["osm"] = np.where(rev["candidate_index"].isin(gone["candidate_index"]), "mapped", "")
    return rev


def _text(rev, col: str):
    """A column of review.csv as text, blank where absent (a column of blanks reads as floats)."""
    import pandas as pd

    if col not in rev.columns:
        return pd.Series("", index=rev.index, dtype=object)
    return rev[col].astype(object).where(rev[col].notna(), "").astype(str)


def cmd_apply(a) -> int:
    import geopandas as gpd
    import numpy as np
    import pandas as pd

    from earthpv import capacity_calibration as cc
    from earthpv.postprocess import MAX_CANDIDATE_M2

    rev = pd.read_csv(a.review)
    if a.verdicts is not None:
        rev = _merge_page_verdicts(rev, a.verdicts, a.unsure_as, a.reviewer)
    if a.josm is not None:
        rev = _merge_josm(rev, a.josm, a.reviewer)
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
    gone, same = _gone(rev, pool, a.aoi)
    if not same:
        raise SystemExit(f"{len(gone)} reviewed outlines are not in the current population and "
                         "not in the candidates as drawn: candidates.parquet changed since the "
                         "draw, so start a new review with `draw --redraw`")
    # Only once nothing above can refuse the sitting; `osm` is refreshed from --labels every time.
    _mark_mapped(rev, gone).to_csv(a.review, index=False)
    _report_josm(rev, a.labels)
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
    print(f"Next: `earthpv density --aoi {a.aoi} --districts`, then the atlas, then "
          f"`scripts/release_leads.py --aoi {a.aoi} --upload` and scripts/patch_atlas_leads.py, "
          "which put the outlines judged solar in the country's confirmed-lead file for mappers "
          "and take those judged not solar out of its lead files. `package` drops the judged "
          "outlines from the page.")
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
    print(f"Next: `earthpv density --aoi {a.aoi} --districts`, then the atlas, then "
          f"`scripts/release_leads.py --aoi {a.aoi} --upload` and scripts/patch_atlas_leads.py, "
          "which put the outlines judged solar in the country's confirmed-lead file for mappers "
          "and take those judged not solar out of its lead files. `package` drops the judged "
          "leads from the page.")
    return 0


def _report_josm(rev, labels: Path) -> None:
    """What the JOSM review has recorded, against the OpenStreetMap pull `apply` read."""
    j, osm = _text(rev, "josm"), _text(rev, "osm").eq("mapped")
    if not (j.ne("") | osm).any():
        return
    said = j.eq("mapped")
    print(f"OpenStreetMap ({labels}): {int(osm.sum())} outlines mapped since the draw, which "
          "the map counts at their own shape")
    if (said & ~osm).any():
        print(f"{int((said & ~osm).sum())} marked mapped in JOSM are not in that pull yet: pull "
              "the country's solar again and apply with it as --labels")
    no = j.eq("not_pv") & ~osm
    if no.any():
        print(f"{int(no.sum())} found not solar in JOSM: off the review, priced as before (a "
              "judgement on the editor's imagery prices nothing)")
    if j.eq("unsure").any():
        print(f"{int(j.eq('unsure').sum())} left unsure in JOSM: back in the next layer")


def _open_rows(rev):
    """The outlines still to review: no verdict, not settled in JOSM, not mapped since."""
    return (rev["verdict"].fillna("").isin(("", "unsure")) & ~_text(rev, "josm").isin(JOSM_DONE)
            & ~_text(rev, "osm").eq("mapped"))


def _share_row(aoi: str, path: Path) -> dict:
    import pandas as pd

    rev = pd.read_csv(path)
    v = rev["verdict"].fillna("")
    j, osm = _text(rev, "josm"), _text(rev, "osm").eq("mapped")
    left = _open_rows(rev)
    flag = rev["flag"].fillna("") if "flag" in rev.columns else pd.Series("", index=rev.index)
    pkg = K.packages / aoi
    return {"aoi": aoi, "n": len(rev), "judged": int((~left).sum()),
            "pv": int(v.eq("pv").sum()), "not_pv": int(v.eq("not_pv").sum()),
            "mapped": int(osm.sum()), "josm_not": int((j.eq("not_pv") & ~osm).sum()),
            "left": int(left.sum()),
            "bright": int(flag.eq("bright_roof").sum()),
            "left_km2": float(rev.loc[left, "area_m2"].sum() / 1e6),
            "page": (pkg / "index.html").exists(),
            "josm": (pkg / f"{aoi}{K.suffix}.osm").exists()}


def share_table() -> list[dict]:
    rows = [_share_row(p.parent.name.removesuffix(K.suffix), p)
            for p in sorted((REPO / "results").glob(f"*{K.suffix}/review.csv"))]
    return sorted(rows, key=lambda r: -r["left_km2"])


def cmd_status(a) -> int:
    rows = share_table()
    print(f"{'country':14s} {'outlines':>8s} {'checked':>7s} {'mapped':>6s} {'solar':>6s} "
          f"{'not':>5s} {'josm no':>7s} {'bright':>6s} {'left':>6s} {'left km2':>9s}  share")
    for r in rows:
        print(f"{r['aoi']:14s} {r['n']:8d} {r['judged']:7d} {r['mapped']:6d} {r['pv']:6d} "
              f"{r['not_pv']:5d} {r['josm_not']:7d} {r['bright']:6d} {r['left']:6d} "
              f"{r['left_km2']:9.1f}  {r['judged'] / max(r['n'], 1):.0%}")
    print("mapped: in OpenStreetMap since the draw, by the pull `apply` last read; solar / not: "
          "verdicts on a review page; josm no: found not solar in JOSM (prices nothing); "
          "bright: not PV on a very bright roof (key 4 on the page), inside 'not'")
    print(f"-> {write_hub()}")
    return 0


# --------------------------------------------------------------------------------------
# The review package: a JOSM layer of the open outlines, and a page of three Sentinel-2
# panels per outline on disk, the only imagery a verdict may come from
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

GUIDE = r"""      <p><b>Judge on these three Sentinel-2 panels alone.</b> They are free Copernicus data,
        the imagery the model read. A verdict taken from Google, Bing, Esri or Mapbox imagery
        cannot be used: their terms do not allow it.</p>
      <ul>
        <li><b>PV</b>: a solar park inside the yellow outline. On the composite, blocks of
          even dark blue-grey with straight edges, a grid of access roads and small bright
          inverter pads; dark purple in the false colour, where vegetation is bright green.
          The outline is the model's and may be ragged or leave gaps: judge whether a park is
          there, not how well it is traced.</li>
        <li><b>Not PV</b>: something else, typically dark ploughed fields, water or aquaculture
          ponds, burn scars, rock, a shaded slope, snow, a riverbed or greenhouses. Fields are
          dark only in true colour; water is dark in every panel.</li>
        <li><b>Unsure</b>: 10 m pixels cannot settle it. Leave it unsure: it does not count and
          comes back next time. If you map in OpenStreetMap, <i>Map it in JOSM</i> opens the
          spot there: an installation you map counts from the map.</li>
        <li><b>Bright roof</b>: not PV, and the outline sits on very bright roofs (white or
          light metal, a reflective coating). It counts as Not PV; the label keeps these
          false alarms apart so they can be studied.</li>
      </ul>
      <p>A flat grey block is a cell nobody imaged; a black block, dark red in the false colour,
        is a cell that lost bands. Neither is ground: if the rest cannot settle it, leave it
        unsure. The Copernicus Browser link shows Sentinel-2 on other dates, free as well, to
        see a park being built. Keys: <kbd>1</kbd> PV, <kbd>2</kbd> Not PV,
        <kbd>3</kbd> unsure, <kbd>4</kbd> bright roof, <kbd>&larr;</kbd> <kbd>&rarr;</kbd>
        step, <kbd>n</kbd> note.</p>
      <p>Stop whenever you like: progress stays in this browser, and any export can be
        applied, however partial. An outline left blank or unsure stays out of capacity and
        comes back on the next page. Export, then run
        <code>pixi run blob-review apply --aoi __AOI__ --reviewer "&lt;name&gt;"
        --verdicts &lt;the export&gt;</code>.</p>"""

GUIDE_LARGE = r"""      <p><b>Judge on these three Sentinel-2 panels alone.</b> They are free Copernicus data,
        the imagery the model read. A verdict taken from Google, Bing, Esri or Mapbox imagery
        cannot be used: their terms do not allow it. This page is for the leads 10 m pixels
        can settle, mostly on open ground; the rest are reviewed in JOSM, where the editor's
        imagery may be used to map them into OpenStreetMap.</p>
      <ul>
        <li><b>PV</b>: solar panels inside or touching the yellow outline. On the composite, an
          even dark patch with straight edges, dark purple in the false colour, where
          vegetation is bright green. The outline is the model's and is often larger than the
          array: judge whether PV is there, not how much of the outline it fills.</li>
        <li><b>Not PV</b>: something else, plain at 10 m, typically water, a dark field, rock,
          a shadow or a burn scar.</li>
        <li><b>Unsure</b>: 10 m pixels cannot settle it, as on most roofs (a dark or blue metal
          roof, a tar or wet roof and a roof full of panels look alike). Leave it unsure: it
          keeps the price it had, and the JOSM review takes it up.</li>
        <li><b>Bright roof</b>: not PV, and the outline sits on a very bright roof (white or
          light metal, a reflective coating). It counts as Not PV; the label keeps these false
          alarms apart so they can be studied.</li>
      </ul>
      <p>These leads already count, each at the share its size class is usually right. Your
        verdict replaces that share for this lead alone: solar counts it as real (a roof
        outline at 1/2.5 of its area, since the model draws about 2.5 times the array there),
        not solar counts it as nothing. A flat grey block is a cell nobody imaged. Keys:
        <kbd>1</kbd> PV, <kbd>2</kbd> Not PV, <kbd>3</kbd> unsure, <kbd>4</kbd> bright roof,
        <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step, <kbd>n</kbd> note.</p>
      <p>Stop whenever you like: progress stays in this browser, and any export can be
        applied, however partial. Export, then run
        <code>pixi run large-review apply --aoi __AOI__ --reviewer "&lt;name&gt;"
        --verdicts &lt;the export&gt;</code>.</p>"""


# The three Sentinel-2 panels of an outline on disk: crops/<code>_<name>.jpg, in page order.
S2_FILES = ("s2", "pixels", "false")


def _s2_files(pkg: Path, code: str) -> list[Path]:
    return [pkg / "crops" / f"{code}_{name}.jpg" for name in S2_FILES]


def _s2_job(job: tuple) -> tuple[str, bool]:
    """Render and save one outline's three Sentinel-2 panels (no network)."""
    code, (geom, comp_dir, origin, epoch, outs, context_min_m, detail_m) = job
    try:
        panels, *_ = _s2_panels(geom, comp_dir, origin, epoch, context_min_m, detail_m)
        for im, out in zip(panels, outs):
            tmp = out.with_suffix(".tmp.jpg")
            im.save(tmp, "JPEG", quality=86)
            tmp.replace(out)
    except Exception as e:  # noqa: BLE001 -- one bad outline must not stop the country
        print(f"  {code}: not rendered: {e}", flush=True)
        return code, False
    return code, True


def write_josm(rev, geoms, path: Path, draw_id: str) -> int:
    """The outlines of `rev` as a JOSM layer that refuses upload (`upload="never"` on the root
    element, which JOSM honours and a GeoJSON opened as data is not given), largest first.
    Each polygon part is a closed way (holes left out: it marks where to look and is never
    uploaded) carrying the outline's tags; the reviewer sets `earthpv:review`. Returns how many
    outlines it holds."""
    from xml.sax.saxutils import quoteattr

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<osm version="0.6" generator="earthpv oversize_review" upload="never" '
           'download="never">']
    ways, nid, wid, n = [], 0, 0, 0
    order = rev.assign(outline_=list(geoms)).sort_values("area_m2", ascending=False)
    for r in order.itertuples():
        g = r.outline_.simplify(1e-5, preserve_topology=True)
        place = PLACES.get(str(getattr(r, "placement", "") or ""), "")
        size = f"{r.area_m2 / 1e4:,.1f} ha" if r.area_m2 >= 1e4 else f"{r.area_m2:,.0f} m²"
        tags = {"name": f"{r.code} {size}" + (f" {place}" if place else ""),
                "earthpv:code": r.code, "earthpv:review": "todo",
                "earthpv:area_m2": f"{r.area_m2:.0f}",
                **({"earthpv:placement": str(r.placement)} if place else {}),
                **({"earthpv:region": r.region} if isinstance(r.region, str) else {}),
                "earthpv:draw": draw_id, "do_not_upload": DO_NOT_UPLOAD}
        n += 1
        for part in getattr(g, "geoms", [g]):
            refs = []
            for x, y in list(part.exterior.coords)[:-1]:
                nid += 1
                out.append(f'  <node id="-{nid}" lat="{y:.7f}" lon="{x:.7f}"/>')
                refs.append(nid)
            wid += 1
            ways.append((wid, refs, tags))
    for wid, refs, tags in ways:
        out.append(f'  <way id="-{wid}">')
        out.extend(f'    <nd ref="-{x}"/>' for x in refs + refs[:1])
        out.extend(f"    <tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
        out.append("  </way>")
    out.append("</osm>")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n")
    tmp.replace(path)
    return n


def read_josm(path: Path, draw_id: str) -> dict[str, str]:
    """Code -> `earthpv:review` from a layer `write_josm` wrote and a reviewer saved. A way the
    reviewer deleted is absent, `todo` or blank is no outcome, and the parts of one outline
    must agree. Refuses a layer of another draw, whose codes name other outlines."""
    import xml.etree.ElementTree as ET

    got: dict[str, set[str]] = {}
    draws = set()
    for el in ET.parse(path).getroot():
        if el.tag not in ("way", "relation", "node") or el.get("action") == "delete":
            continue
        tags = {t.get("k"): (t.get("v") or "").strip() for t in el.findall("tag")}
        code = tags.get("earthpv:code")
        if not code:
            continue
        draws.add(tags.get("earthpv:draw", ""))
        v = tags.get("earthpv:review", "").lower().replace(" ", "_").replace("-", "_")
        got.setdefault(code, set()).add(v)
    if draws - {draw_id}:
        raise SystemExit(f"{path} belongs to another draw ({', '.join(sorted(draws - {draw_id}))};"
                         f" this review is {draw_id}): its codes name other outlines")
    out = {}
    for code, vs in got.items():
        vs -= {"", "todo"}
        bad = vs - set(JOSM_OUTCOMES)
        if bad:
            raise SystemExit(f"{path}: {code} has earthpv:review={sorted(bad)}; use one of "
                             f"{', '.join(JOSM_OUTCOMES)}, or todo")
        if len(vs) > 1:
            raise SystemExit(f"{path}: the parts of {code} disagree: {sorted(vs)}")
        if vs:
            out[code] = vs.pop()
    return out


def _merge_josm(rev, path: Path, reviewer: str):
    """A saved JOSM review layer into review.csv's `josm` and `josm_reviewer` columns. The
    `verdict` column is not touched: a mapped outline counts from the map once the country's
    solar is pulled again, and `not_pv` was judged on imagery licensed only for mapping into
    OpenStreetMap, so it takes the outline off the review and prices nothing."""
    import pandas as pd

    got = read_josm(path, _draw_id(rev))
    unknown = sorted(set(got) - set(rev["code"]))
    if unknown:
        raise SystemExit(f"{path}: codes this review does not hold: {unknown[:8]}")
    rev["josm"] = _text(rev, "josm")
    rev["josm_reviewer"] = _text(rev, "josm_reviewer")
    fresh = rev["code"].isin(list(got))
    rev.loc[fresh, "josm"] = rev.loc[fresh, "code"].map(got)
    rev.loc[fresh, "josm_reviewer"] = f"{reviewer}, {date.today().isoformat()}"
    n = pd.Series(got, dtype=object).value_counts()
    print(f"{path}: {len(got)} outlines reviewed in JOSM by {reviewer}: "
          + ", ".join(f"{int(n.get(k, 0))} {k}" for k in JOSM_OUTCOMES))
    return rev


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
    """Write the JOSM layer of the open outlines, render their Sentinel-2 panels and write the
    page (where the kind or `--page` asks for one), and review.geojson of every outline."""
    import geopandas as gpd
    import pandas as pd

    from build_review_page import COPERNICUS, LINKS_FREE, josm_link, write_page

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
    name = a.aoi
    pkg = K.packages / name
    (pkg / "crops").mkdir(parents=True, exist_ok=True)
    comp = REPO / f"data/composites/{a.aoi}/composites"
    show = (_open_rows(rev) | a.include_judged).to_numpy()
    # The JOSM layer: every open outline, no imagery.
    layer = pkg / f"{name}{K.suffix}.osm"
    if show.any():
        n = write_josm(rev[show], geoms[show], layer, _draw_id(rev))
        print(f"JOSM layer, {n} outlines, refuses upload -> {layer}")
    else:
        layer.unlink(missing_ok=True)
    # Pages before 2026-11-20 showed Esri World Imagery; nothing of it is kept. The four-panel
    # sheets of pages before 2026-11-19 (crops/<code>.jpg, no underscore) held it, saved, which
    # Esri's terms do not allow; later pages cached its capture dates in esri_meta.json.
    sheets = [f for f in (pkg / "crops").glob("*.jpg") if "_" not in f.stem]
    for f in sheets:
        f.unlink()
    if sheets:
        print(f"{len(sheets)} older sheets holding saved Esri imagery deleted")
    for f in [pkg / "esri_meta.json", *(pkg / "crops").glob("*.esri")]:
        f.unlink(missing_ok=True)
    # A page: where asked (`--page`), by the kind's default, or to keep a Sentinel-2 page drawn
    # earlier current. A page of before 2026-11-20 showed Esri imagery: it goes, since `apply`
    # takes none of its verdicts.
    old = pkg / "index.html"
    s2_page = old.exists() and S2_ONLY in old.read_text(errors="ignore")[:2000]
    page = a.page if a.page is not None else (K.page or s2_page)
    unrendered = []
    if not page:
        if old.exists():
            old.unlink()
            print("the page is removed: " + ("--no-page" if s2_page else
                  "it showed Esri imagery, and `apply` takes none of its verdicts")
                  + "; `--page` draws the Sentinel-2 page")
    else:
        jobs = []
        for r, g, on_page in zip(rev.itertuples(), geoms, show):
            outs = _s2_files(pkg, r.code)
            if on_page and (a.force or not all(o.exists() for o in outs)):
                jobs.append((r.code, (g, comp, origin, epoch, outs, K.context_min_m, K.detail_m)))
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            for n, _done in enumerate(pool.map(_s2_job, jobs, chunksize=4), 1):
                if n % 100 == 0 or n == len(jobs):
                    print(f"  {a.aoi}: {n} of {len(jobs)} rendered", flush=True)
        items = []
        for r, g, on_page in zip(rev.itertuples(), geoms, show):
            if not on_page:
                continue
            if not all(o.exists() for o in _s2_files(pkg, r.code)):
                unrendered.append(r.code)
                continue
            w, so, e, n = g.bounds
            p = g.representative_point()
            size = (f"{r.area_m2:,.0f} m² · "
                    f"{PLACES.get(getattr(r, 'placement', ''), 'placement unknown')}"
                    if K.name == "large" else f"{r.area_m2 / 1e4:,.0f} ha")
            items.append({
                "code": r.code,
                "panels": [{"src": f"crops/{f.name}", "cap": ""} for f in _s2_files(pkg, r.code)],
                "date": f"{S2_ONLY}, {epoch}",
                "date_label": f"{size} · {r.region} · Sentinel-2, {epoch}",
                "lon": round(p.x, 6), "lat": round(p.y, 6),
                "bbox": [round(w - 0.002, 6), round(so - 0.002, 6), round(e + 0.002, 6),
                         round(n + 0.002, 6)],
            })
        if not items:
            (pkg / "index.html").unlink(missing_ok=True)
            print(f"every outline of {a.aoi} is settled; no page")
        else:
            guide = GUIDE_LARGE if K.name == "large" else GUIDE
            comment = (f"Map solar PV found by the EarthPV {K.title.lower()}")
            page = write_page(pkg / "index.html", f"{name}{K.suffix}", items,
                              guide=guide.replace("__AOI__", a.aoi),
                              title=f"{K.title}, Sentinel-2 only",
                              store=f"{name}{K.suffix}:{_draw_id(rev)}",
                              export_name=K.export.format(aoi=name), back="../index.html",
                              bright_roof=True, credits=[COPERNICUS],
                              links=LINKS_FREE + [josm_link(HASHTAGS + [K.hashtag], comment)])
            print(f"{len(items)} of {len(rev)} outlines on the Sentinel-2 page -> {page}")
    if unrendered:
        print(f"{len(unrendered)} outlines could not be rendered and are not on the page "
              f"(`package` retries them): {unrendered[:8]}")
    gj = gpd.GeoDataFrame({
        "name": [f"{c} {v}" if isinstance(v, str) and v else c
                 for c, v in zip(rev.code, rev.verdict)],
        "review_verdict": rev.verdict, "review_evidence": rev.evidence,
        "stratum": rev.stratum, "k": rev.k, "area_ha": (rev.area_m2 / 1e4).round(1),
        "region": rev.region, "candidate_index": rev.candidate_index,
        **({"placement": rev.placement} if "placement" in rev.columns else {}),
        **({"review_flag": rev["flag"]} if "flag" in rev.columns else {}),
        **{f"review_{c}": _text(rev, c) for c in ("imagery", "josm", "osm") if c in rev.columns},
    }, geometry=geoms, crs="EPSG:4326")
    gj.to_file(a.out / "review.geojson", driver="GeoJSON")
    write_hub()
    return 0


HUB_ROW = ('<tr><td>{name}</td><td>{links}</td><td>{left:,}</td><td>{left_km2:,.1f}</td>'
           '<td>{judged:,} of {n:,} ({share:.0%})</td><td>{mapped:,}</td><td>{pv:,}</td>'
           '<td>{nots:,}</td></tr>')
PLACES = {"rooftop": "on a roof", "ground_adjacent": "beside a building",
          "no_building": "open ground"}
HUB_INTRO = {
    "blob": """Very large model outlines, one look each on Sentinel-2 alone: the composite the model saw,
its native pixels and its false colour, all free Copernicus data. An outline counts towards
capacity only once a person judges it solar on that page or it is mapped in OpenStreetMap.
What 10 m pixels cannot settle is left unsure, and mapping it is how it then counts: each
country's JOSM layer holds the same outlines, ready to map from. Largest first within each
country.""",
    "large": """The model's large leads below the solar farm cap, from 10,000 m&sup2;, on roofs and on the
ground. They are reviewed in JOSM while mapping: open a country's layer beside the
OpenStreetMap data, look at each lead on the imagery JOSM offers for mapping and map the solar
that is there; mark a lead with none <code>earthpv:review=not_pv</code> and save the layer. A
lead mapped counts from the map once the country's solar is pulled again. They already count,
each at the share its size class is usually right, and a lead found not solar in JOSM keeps
that share: a judgement on imagery licensed for mapping prices nothing. Where a country has
a Sentinel-2 page (<code>--page</code>), a verdict given there on 10 m pixels alone replaces the
share. Largest first within each country. The
<a href="../oversize_review/index.html">solar farm review</a> has the outlines above the cap.""",
}
HUB = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { color-scheme: light dark; --ink: light-dark(#1d2330, #e6e9ef);
  --muted: light-dark(#5d6677, #98a2b3); --line: light-dark(#d9dde5, #2a3140);
  --accent: light-dark(#2563eb, #6ea8ff); --bg: light-dark(#f6f7f9, #0f131a); }
body { margin: 0 auto; max-width: 980px; padding: 24px 16px; background: var(--bg);
  color: var(--ink); font: 15px/1.5 system-ui, sans-serif; }
h1 { font-size: 22px; margin: 0 0 8px; }
p { color: var(--muted); }
a { color: var(--accent); }
.wide { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; margin: 16px 0; }
th, td { padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: right;
  font-variant-numeric: tabular-nums; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { font-size: 13px; color: var(--muted); font-weight: 600; }
code { font-size: 13px; }
</style></head><body>
<h1>__TITLE__</h1>
<p>__INTRO__</p>
<div class="wide"><table><thead><tr><th>Country</th><th>Review in</th><th>To review</th>
<th>km&sup2; to review</th><th>Checked</th><th>Mapped since</th><th>Judged solar</th>
<th>Not solar</th></tr></thead><tbody>
__ROWS__
</tbody></table></div>
<p>Counts are what <code>apply</code> has recorded. <i>Mapped since</i> counts the outlines now in
OpenStreetMap, by the pull <code>apply</code> last read; <i>Judged solar</i> and <i>Not solar</i>
count verdicts on a Sentinel-2 page (and on the review pages before 20 November 2026) and
outlines found not solar in JOSM. Record a Sentinel-2 page's export with<br>
<code>pixi run __TASK__ apply --aoi &lt;country&gt; --reviewer "&lt;name&gt;" --verdicts
&lt;the export&gt;</code><br>
and a JOSM layer you saved with <code>--josm &lt;the layer&gt;</code> in its place. After
mapping, pull the country's OpenStreetMap solar again and apply with it as
<code>--labels</code>; then <code>earthpv density --aoi &lt;country&gt; --districts</code>, the
atlas, and <code>scripts/release_leads.py --aoi &lt;country&gt; --upload</code>.</p>
</body></html>
"""


def write_hub() -> Path:
    """`<packages>/index.html` (`data/oversize_review/` or `data/large_review/`): every country's
    page and JOSM layer, and what `apply` has recorded."""
    from release_leads import country_name

    rows = []
    for r in share_table():
        links = [f'<a href="{r["aoi"]}/index.html">Sentinel-2 page</a>' if r["page"] else "",
                 f'<a href="{r["aoi"]}/{r["aoi"]}{K.suffix}.osm">JOSM layer</a>'
                 if r["josm"] else ""]
        rows.append(HUB_ROW.format(name=country_name(r["aoi"]),
                                   links=" &middot; ".join(x for x in links if x) or "&ndash;",
                                   share=r["judged"] / max(r["n"], 1),
                                   nots=r["not_pv"] + r["josm_not"], **r))
    K.packages.mkdir(parents=True, exist_ok=True)
    out = K.packages / "index.html"
    out.write_text(HUB.replace("__TITLE__", K.title).replace("__INTRO__", HUB_INTRO[K.name])
                   .replace("__TASK__", K.task).replace("__ROWS__", "\n".join(rows)))
    return out


def _month(day: str) -> str:
    from datetime import date as _d

    return _d.fromisoformat(day).strftime("%b %Y")


def _s2_panels(geom, comp_dir: Path, origin, epoch: str, context_min_m: float = CONTEXT_MIN_M,
               detail_m: float = DETAIL_M):
    """The outline's three Sentinel-2 panels, its outline drawn on each: true colour around
    it, its native 10 m pixels close in, false colour (SWIR, NIR, red). Also returns its
    representative point, its extent in metres and the context panels' width. Shared with
    scripts/maproulette_review.py."""
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
    return panels, rep, extent, side


def _render(geom, comp_dir: Path, origin, epoch: str, out: Path, esri: bool = False,
            context_min_m: float = CONTEXT_MIN_M, detail_m: float = DETAIL_M,
            esri_min_m: float | None = None) -> tuple[bool, None]:
    """One outline's three Sentinel-2 panels as a 2 x 2 JPEG, the fourth quarter blank (for
    scripts/validate_steep_lead_screen.py). Until 2026-11-19 the fourth was Esri World
    Imagery, fetched and saved here; Esri's terms allow no saving of its imagery, so it is
    gone, and `esri` and `esri_min_m` are ignored. The review pages show Sentinel-2 alone
    since 2026-11-20."""
    from PIL import Image

    panels, *_ = _s2_panels(geom, comp_dir, origin, epoch, context_min_m, detail_m)
    panels.append(_caption(Image.new("RGB", (PANEL, PANEL), (40, 40, 40)),
                           "high-resolution imagery: see the links"))
    sheet = Image.new("RGB", (2 * PANEL, 2 * PANEL))
    for i, p in enumerate(panels):
        sheet.paste(p, ((i % 2) * PANEL, (i // 2) * PANEL))
    sheet.save(out, "JPEG", quality=86)
    return True, None


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


def _merge_page_verdicts(rev, verdicts: Path, unsure_as: str | None, reviewer: str):
    """The page's export (`code,imagery_date,verdict,note`) into review.csv's rows. Only an
    export of a Sentinel-2 page is taken: every verdict in it must carry `S2_ONLY` in its
    `imagery_date` (owner, 2026-11-20: the project uses no verdict drawn from imagery it may not
    use, and the pages before showed Esri World Imagery). review.csv's `imagery` records it."""
    import numpy as np
    import pandas as pd

    v = pd.read_csv(verdicts, dtype=str).fillna("").set_index("code")
    v = v.reindex(rev.code).fillna("")
    given = v["verdict"].ne("")
    imagery = v["imagery_date"] if "imagery_date" in v.columns else pd.Series("", index=v.index)
    other = given & ~imagery.str.startswith(S2_ONLY)
    if other.any():
        raise SystemExit(
            f"{verdicts}: {int(other.sum())} of its {int(given.sum())} verdicts come from a page "
            "that showed more than Sentinel-2 (pages drawn before 2026-11-20 had an Esri World "
            "Imagery panel), and the project uses no verdict drawn from imagery it is not "
            "licensed to use for that. Draw the page again (`package --page`), which shows "
            "Sentinel-2 alone, and judge there; or map the installations in OpenStreetMap "
            "(`apply --josm`).")
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
    # What the verdict was read from; blank for the verdicts applied before 2026-11-20.
    rev["imagery"] = np.where(fresh, S2_ONLY, _text(rev, "imagery").to_numpy())
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
        q.add_argument("--page", action=argparse.BooleanOptionalAction, default=None,
                       help="write the Sentinel-2 page as well as the JOSM layer (default: yes "
                            "for the blob review; for the large review, which is done in JOSM, "
                            "only where a Sentinel-2 page was drawn before)")
        q.add_argument("--force", action="store_true", help="render the Sentinel-2 panels again")
        q.add_argument("--workers", type=int, default=4)
        q.add_argument("--include-judged", action="store_true",
                       help="keep outlines already settled on the page and in the JOSM layer, "
                            "to judge them again")
    p = sub.choices["apply"]
    p.add_argument("--review", type=Path, default=None)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--verdicts", type=Path, default=None,
                     help="the Sentinel-2 page's export (code,imagery_date,verdict,note); an "
                          "export of a page that showed other imagery is refused")
    src.add_argument("--josm", type=Path, default=None,
                     help="the JOSM review layer, saved after setting earthpv:review on its "
                          "outlines (mapped, not_pv, bright_roof, unsure)")
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
