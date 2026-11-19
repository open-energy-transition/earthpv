#!/usr/bin/env python
"""Build each country's mapping-lead files, publish its confirmed leads in a GitHub release,
and write the manifest the evidence atlases read.

**Only the confirmed file is published (owner, 2026-11-19).** The lead and blob files below
are built in `--out` for the review pages and the lead-share analyses, but never uploaded:
they are unchecked model outlines. `--upload` sends each country's confirmed file (outlines
a person judged solar) with README.md and SHA256SUMS, and removes any lead or blob file
still on the release; the manifest carries release links for the confirmed files only.

A lead is a segmentation candidate of the run behind a country's published atlas
(`data/predictions/<aoi>/candidates.parquet`, the file `density` read) that lies more than
`--min-distance-m` (100 m, export's convention) from every OpenStreetMap solar feature in
the country's raw pull, so a mapper's queue only holds installations the map does not have.
The rule, the ranking and the `candidate_id` numbering are `earthpv export`'s own
(`export.new_lead_mask`, sort by `rank_score`), so a lead keeps the id it has in that
country's candidate and MapRoulette exports; where an export lead file exists its count is
printed beside this one as a check. Leads whose representative point falls outside the
regions the atlas draws (`atlas._page_regions`) are dropped: a composited cell can reach
across a border.

Three things are filtered. A lead on ground steeper than
`export.STEEP_SLOPE_DEG` (15 degrees, Copernicus GLO-90 at its representative point) whose
outline is under `export.STEEP_MAX_AREA_M2` (1,000 m2) is left out, because shaded
hillsides, cliff edges and escarpment shadows read like panels. A larger lead on steep
ground stays, marked `steep_review`, since a solar farm can sit on a mountainside and a
mapper has to look at it, unless its ground is steeper than `export.STEEP_CAP_DEG` (30
degrees; owner, 2026-11-01), where a lead of any size is left out. Every lead carries its
`slope_deg`. Validation:
results/leads_steep_screen/ (owner, 2026-10-31 and 2026-11-01). A lead with no building
nearby whose peak model probability is below `export.LOWCONF_MAX_CONFIDENCE` (0.9) is left
out at any size (2026-11-01; results/fp_filter_survey/), unless the steep screen kept it as
`steep_review`, which neither later screen touches. Where a country's
`lead_water_screen` is on in configs/aoi.yaml, a non-rooftop lead at least
`export.WATER_EVER_WET_MIN` of whose outline was ever water in JRC Global Surface Water is
left out too, and every lead carries `ever_wet_frac`. Otherwise leads are unverified 10 m
outlines, recall-first like every candidate file, and the README asset says so.

**Very large outlines go in a file of their own (owner, 2026-11-01).** A lead above
`postprocess.MAX_CANDIDATE_M2` (100,000 m2, the merge cap; `oversize` in the candidates) is a
"blob": a solar park OpenStreetMap does not hold yet as often as a merged sheet of false
alarms. Blobs are written to `<aoi>_pv_blob_leads.geojson`, largest first, and never count
towards capacity until they are mapped in OpenStreetMap or a person has judged them solar on
the imagery the model saw (`scripts/oversize_review.py`, `density.load_oversize_admission`).
`<aoi>_pv_new_leads.geojson` keeps the rest, most promising first. Silver needs a verdict on
a third of the leads of `LARGE_MIN_M2` (1 ha) and up and of the blobs, the populations of the
two review pages (`atlas.LEAD_SHARE_MIN`, owner 2026-11-19). `--resplit` splits files built before this
(every lead in one file) in place, keeping their date, so a lead check made on them still
names them.

**A person's verdict turns an outline into a confirmed lead (2026-11-19).** The solar farm
review (blobs) and the large installation review (leads from 10,000 m2 up to the cap) judge
outlines on the imagery the model saw (scripts/oversize_review.py). Their verdicts, read from
the review blocks of the country's calibration table (`review_table`, as `density` and
scripts/release_polygons.py read them), sort the leads three ways. An outline judged solar
that OpenStreetMap still lacks goes to `<aoi>_pv_confirmed_leads.geojson`, largest first:
every one is solar, and it is the only lead file the atlas offers mappers (owner,
2026-11-19; `atlas.leads_for_page` keeps the other files' counts, never their links). A verdict outranks the
lead screens, so a confirmed lead is kept whatever its slope, confidence or water history.
An outline judged not solar (or bright roof) is left out of every file, since nobody should
check it again; its verdict stays in review.csv and in the polygon release. Unsure and
unjudged outlines stay in the lead and blob files, an unsure one marked `review_verdict =
unsure`. The manifest counts each (`confirmed`, `judged_not_pv`), and `confirmed.mapped_since`
counts the outlines judged solar that OpenStreetMap has gained since (no longer leads). After
a review sitting: `apply`, `density`, the atlas, then `--aoi <aoi> --upload` here and
scripts/patch_atlas_leads.py on the page.

**Every atlas gets its files by default (owner, 2026-11-13).** scripts/run_country_compute.sh
runs `--aoi <aoi> --upload` after `earthpv atlas`, then scripts/patch_atlas_leads.py on the page,
so a new country's page links its leads from the start. A country needs a `SOURCES` entry only
when its atlas came from another run directory or OSM pull than the defaults. With `--aoi`,
`--upload` sends only those countries' confirmed files plus README.md and SHA256SUMS (which
cover every country's confirmed file, so `--out` must hold them all: the default is the
release's own directory). `--refresh` rebuilds nothing and rewrites README.md, SHA256SUMS and
the manifest from the files in `--out`; with `--upload` it re-sends every confirmed file.

France is not built here: its leads were audited against IGN aerial imagery and released
on their own (`france-osm-leads-2026-10-22`, scripts/build_france_osm_leads.py, which already
kept its outlines above the cap apart); its manifest entry links those files.

    pixi run python scripts/release_leads.py --out /home/tobi/earthpv_data/pv_new_leads_2026-11-01
    pixi run python scripts/release_leads.py --out ... --upload     # gh release create/upload
    pixi run python scripts/release_leads.py --aoi italy --upload   # one country, default --out
    pixi run python scripts/release_leads.py --out <dir of a published release> --resplit
    pixi run python scripts/release_leads.py --refresh --upload     # README, sums, no rebuild

Writes `<out>/<aoi>_pv_new_leads.geojson` and `<out>/<aoi>_pv_blob_leads.geojson` (local
only), `<out>/<aoi>_pv_confirmed_leads.geojson` (only where a person has judged a lead solar),
`<out>/README.md`, `<out>/SHA256SUMS` and `configs/atlas_leads.json`, which
`atlas.leads_for_page` reads into `totals.leads` and scripts/patch_atlas_leads.py adds to
published pages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from earthpv import atlas  # noqa: E402
from earthpv.postprocess import MAX_CANDIDATE_M2  # noqa: E402
from earthpv.export import (LOWCONF_MAX_CONFIDENCE, STEEP_CAP_DEG,  # noqa: E402
                            STEEP_MAX_AREA_M2, STEEP_SLOPE_DEG, WATER_EVER_WET_MIN,
                            lead_water_screen_enabled, low_confidence_lead_screen,
                            new_lead_mask, steep_lead_screen, water_lead_screen)
from oversize_review import LARGE_MIN_M2  # noqa: E402

REPO = "open-energy-transition/earthpv"
MANIFEST = ROOT / "configs" / "atlas_leads.json"
# 2026-10-28: the first release. 2026-11-01: the same runs, with the steep-ground screen.
# A new tag rather than a re-upload, so the files earlier lead checks covered stay published.
# The 30-degree cap was added on 2026-11-01 too, before anyone had checked those files, so
# they were replaced under the same tag. Later on 2026-11-01 the open-ground low-probability
# and (per country) surface-water screens: a new tag, so the steep-only files stay published.
# The same day the very large outlines moved to a blob file of their own (`--resplit`): the
# lead files were replaced under the same tag, minus their blobs, keeping their date.
# 2026-11-02: Yemen re-run on v25 (`--aoi yemen`), a new tag holding every country's files,
# the others byte for byte those of pv-new-leads-2026-11-01b, whose manifest entries keep
# their URLs there. 2026-11-04: Turkey's first files added to the same tag; the other
# countries' files untouched, README.md and SHA256SUMS replaced. Spain's likewise 2026-11-08.
# 2026-11-13: Belgium, Denmark, Italy, Luxembourg, the Netherlands and Portugal, the same way,
# and from then on every new atlas (run_country_compute.sh's `leads` step). 2026-11-19: every
# lead and blob file removed from this tag, which holds the confirmed files only (owner); the
# earlier tags still hold theirs.
TAG = "pv-new-leads-2026-11-02"
# Every country's files as uploaded under TAG: README.md and SHA256SUMS cover them all.
RELEASE_DIR = Path(os.environ.get(
    "EARTHPV_LEADS_DIR",
    Path.home() / "earthpv_data" / f"pv_new_leads_{TAG.removeprefix('pv-new-leads-')}"))

# Per AOI: the candidates behind its published atlas, the OSM pull(s) that count as
# mapped, and the density directory holding the regions the page draws. An AOI missing here
# builds from the defaults (data/predictions/<aoi>, data/labels/<aoi>_overpass_solar.parquet).
SOURCES = {
    "pakistan": {},
    # Germany's national file carries the 52,946 OSM nodes the pre-cap file lacks; the
    # pre-cap file carries the ground outlines above 5 km2 the national file dropped.
    # The pre-cap file is gone (2026-11-13), so since 2026-11-19 Germany's leads are held to
    # the candidates its 2026-11-01 files list (`keep_ids_from`, kept in
    # data/leads_reference/): the national file alone would make leads of model outlines at
    # the ground outlines above 5 km2 it dropped, and every lead in those files was declared
    # checked (configs/atlas/germany.yaml). Its screens ran on that file, so the manifest
    # carries that file's counts (`screened`).
    "germany": {"osm": ["data/labels/germany_national_osm_solar.parquet"],
                "screened": {"steep": 209, "lowconf": 2335},
                "keep_ids_from": ["data/leads_reference/germany_20261101/germany_pv_new_leads.geojson",
                                  "data/leads_reference/germany_20261101/germany_pv_blob_leads.geojson"]},
    # Nigeria's atlas is the v5 run; data/predictions/nigeria holds the losing checkpoint's.
    "nigeria": {"pred": "data/predictions_v5_nigeria/nigeria"},
    # Yemen's atlas is the v25 run (2026-11-02); data/predictions/yemen holds v13's.
    "yemen": {"pred": "data/predictions_v25/yemen"},
    "india": {}, "vietnam": {}, "zambia": {}, "egypt": {},
    "south_africa": {}, "morocco": {}, "poland": {}, "namibia": {}, "turkiye": {}, "spain": {},
    "belgium": {}, "denmark": {}, "italy": {}, "luxembourg": {}, "netherlands": {},
    "portugal": {},
}
# The published page each run must match: its provinces are compared with the regions read
# here, so a lead file cannot come from a run other than the page's.
PAGES = {"pakistan": "docs/assets/interactive/pakistan_evidence_atlas.html",
         "germany": "data/predictions/germany/density/germany_pv_evidence_atlas.html"}
# Linked, not rebuilt (see the module docstring).
FRANCE = {
    "file": "france_pv_leads.geojson",
    "url": f"https://github.com/{REPO}/releases/download/france-osm-leads-2026-10-22/france_pv_leads.geojson",
    "n": 28734,
    "size_bytes": 25799723,
    "osm_as_of": "2026-10-22",
    "min_distance_m": 100,
    "made": "2026-10-22",
    "note": (
        "Arrays of 400 m&sup2; and up that the model outlines more than 100 m from any solar "
        "installation in OpenStreetMap as of 22 October 2026, in metropolitan France. Each lead "
        "carries a priority tier set by a visual audit of 72 leads against IGN aerial imagery "
        "(priority 1: 33 confirmed and 5 probable of 48 audited). The release also has the "
        "leads per d&eacute;partement, for JOSM, and as MapRoulette challenges."),
    "blobs": {
        "file": "france_pv_leads_oversize.geojson",
        "url": f"https://github.com/{REPO}/releases/download/france-osm-leads-2026-10-22/"
               "france_pv_leads_oversize.geojson",
        "n": 29, "size_bytes": 104175, "min_area_m2": MAX_CANDIDATE_M2,
    },
}
COLUMNS = ["candidate_id", "rank_score", "confidence", "area_m2", "placement",
           "building_dist_m", "building_overlap_frac", "building_prior", "building_id",
           "oversize", "slope_deg", "steep_review", "ever_wet_frac", "review_verdict",
           "review_page", "lon", "lat"]
# The calibration table's review blocks (scripts/oversize_review.py `apply`) and the page each
# one comes from, as a lead file names it in `review_page`.
REVIEW_BLOCKS = {"oversize_review": "solar_farm", "lead_review": "large_installation"}
JUDGED_NOT_PV = ("not_pv", "bright_roof")


def review_table(aoi: str, cands: gpd.GeoDataFrame) -> pd.DataFrame:
    """A person's verdict per candidate, where the country's calibration table records a
    review (`oversize_review`, `lead_review`): `review_verdict` is `pv`, `not_pv`,
    `bright_roof` (not PV, a very bright roof) or `unsure`, and `review_page` the page it was
    given on; both None for an outline nobody judged. Matched by `candidate_index` (a label
    of the candidate file's own index, which the solar thermal filter left with gaps) and
    checked by area, as `density.load_oversize_admission` does. A verdict on a candidate the
    file no longer holds is skipped, unless it is `pv`, which is an error as in `density`."""
    out = pd.DataFrame({"review_verdict": pd.Series(None, index=cands.index, dtype=object),
                        "review_page": pd.Series(None, index=cands.index, dtype=object)})
    table = ROOT / "configs" / "calibration" / f"{aoi}_candidate_precision.yaml"
    if not table.exists():
        return out
    t = yaml.safe_load(table.read_text()) or {}
    for key, page in REVIEW_BLOCKS.items():
        block = t.get(key) or {}
        if not block.get("review_csv"):
            continue
        r = pd.read_csv(ROOT / block["review_csv"])
        r = r[r["verdict"].isin(["pv", "not_pv", "unsure"])]
        known = r["candidate_index"].isin(cands.index)
        if not known[r["verdict"] == "pv"].all():
            raise ValueError(f"{aoi}: {block['review_csv']} judges solar a candidate the "
                             "file lacks (another candidate file?)")
        r = r[known]
        got = cands.loc[r["candidate_index"], "area_m2"].to_numpy(float)
        if not np.allclose(got, r["area_m2"].to_numpy(float), rtol=1e-6, atol=1.0):
            raise ValueError(f"{aoi}: {block['review_csv']} describes another candidate file")
        flag = r["flag"].fillna("") if "flag" in r else pd.Series("", index=r.index)
        idx = r["candidate_index"].to_numpy()
        out.loc[idx, "review_verdict"] = np.where(flag.eq("bright_roof"), "bright_roof",
                                                  r["verdict"])
        out.loc[idx, "review_page"] = page
        n = r["verdict"].value_counts()
        print(f"  {key}: {int(n.get('pv', 0) + n.get('not_pv', 0)):,} verdicts "
              f"({int(n.get('pv', 0)):,} solar, {int(n.get('unsure', 0)):,} more unsure; "
              f"{int((~known).sum())} on candidates no longer in the file)")
    return out


def _osm_as_of(frames: list[gpd.GeoDataFrame], paths: list[Path]) -> str:
    """The latest edit in the pull, a lower bound on the day it was taken."""
    stamps = [pd.to_datetime(f["osm_timestamp"], utc=True, errors="coerce").max()
              for f in frames if "osm_timestamp" in f]
    stamps = [s for s in stamps if pd.notna(s)]
    if stamps:
        return max(stamps).date().isoformat()
    return dt.date.fromtimestamp(max(p.stat().st_mtime for p in paths)).isoformat()


def _page_data(page: Path) -> dict:
    """The page's data block, read straight from its `<script id="pv">` so that a page built
    from any template revision can be checked (most published pages are on older ones)."""
    html = page.read_text()
    tag = '<script id="pv" type="application/json">'
    start = html.index(tag) + len(tag)
    return json.loads(html[start:html.index("</script>", start)])


def _write(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.unlink(missing_ok=True)
    gdf.to_file(path, driver="GeoJSON", layer_options={"COORDINATE_PRECISION": "7"})


def write_confirmed(confirmed: gpd.GeoDataFrame, aoi: str, out: Path,
                    mapped_since: int) -> dict | None:
    """Write the outlines a person judged solar, largest first, to
    `<aoi>_pv_confirmed_leads.geojson` and return the manifest's `confirmed` entry; None (and
    no file) when there are none."""
    path = out / f"{aoi}_pv_confirmed_leads.geojson"
    if confirmed.empty:
        path.unlink(missing_ok=True)
        return None
    confirmed = confirmed.sort_values("area_m2", ascending=False, kind="stable")
    _write(confirmed, path)
    page = confirmed["review_page"]
    return {"file": path.name,
            "url": f"https://github.com/{REPO}/releases/download/{TAG}/{path.name}",
            "n": len(confirmed), "size_bytes": path.stat().st_size,
            "n_solar_farm": int(page.eq("solar_farm").sum()),
            "n_large_installation": int(page.eq("large_installation").sum()),
            "area_m2": round(float(confirmed["area_m2"].sum()), 1),
            "mapped_since": int(mapped_since)}


def split_blobs(leads: gpd.GeoDataFrame, aoi: str, out: Path) -> dict:
    """Write `leads` as two files: outlines above the merge cap (blobs), largest first, and
    the rest in their own order. Returns the manifest's `blobs` entry; `leads` is written
    without them to `<aoi>_pv_new_leads.geojson`."""
    blob = leads["area_m2"].to_numpy(float) > MAX_CANDIDATE_M2
    blobs = leads[blob].sort_values("area_m2", ascending=False, kind="stable")
    _write(leads[~blob], out / f"{aoi}_pv_new_leads.geojson")
    path = out / f"{aoi}_pv_blob_leads.geojson"
    _write(blobs, path)
    return {"file": path.name, "n": int(blob.sum()), "size_bytes": path.stat().st_size,
            "min_area_m2": MAX_CANDIDATE_M2}


def resplit(aoi: str, entry: dict, out: Path) -> dict:
    """Split a lead file built before the blob file existed, in place: same leads, same
    order, same date, so a check made on it still names it."""
    path = out / entry["file"]
    leads = gpd.read_file(path)
    if "blobs" in entry and (out / entry["blobs"]["file"]).exists() \
            and not (leads["area_m2"] > MAX_CANDIDATE_M2).any():
        print(f"  {aoi:13s} already split")
        return entry
    n0 = len(leads)
    blobs = split_blobs(leads, aoi, out)
    entry = {**entry, "n": n0 - blobs["n"], "size_bytes": path.stat().st_size, "blobs": blobs}
    print(f"  {aoi:13s} {n0:7,d} -> {entry['n']:7,d} leads + {blobs['n']:5,d} blobs")
    return entry


def build(aoi: str, src: dict, out: Path, min_distance_m: float) -> dict:
    pred = ROOT / src.get("pred", f"data/predictions/{aoi}")
    cands = gpd.read_parquet(pred / "candidates.parquet")
    # Verdicts are keyed by the candidate file's own index, so they are read before the
    # ranking below renumbers it.
    cands = cands.join(review_table(aoi, cands))
    # export.run_export's ranking and numbering, call for call, so ids agree with it.
    sort_col = "rank_score" if "rank_score" in cands.columns else "confidence"
    cands = cands.sort_values(sort_col, ascending=False).reset_index(drop=True)
    cands["candidate_id"] = [f"{aoi}-pv-{i:06d}" for i in range(len(cands))]

    paths = [ROOT / p for p in src.get("osm", [f"data/labels/{aoi}_overpass_solar.parquet"])]
    frames = [gpd.read_parquet(p) for p in paths]
    mapped = gpd.GeoDataFrame(pd.concat([f[["geometry"]] for f in frames], ignore_index=True),
                              geometry="geometry", crs="EPSG:4326")
    mapped = mapped[mapped.geometry.notna() & ~mapped.geometry.is_empty]
    is_lead = np.asarray(new_lead_mask(cands, mapped, min_distance_m))
    if "keep_ids_from" in src:
        # Only candidates an earlier, checked lead file listed (same run, same numbering).
        keep = set()
        for f in src["keep_ids_from"]:
            keep |= set(gpd.read_file(ROOT / f, columns=["candidate_id"])["candidate_id"])
        is_lead &= cands["candidate_id"].isin(keep).to_numpy()

    regions = atlas._page_regions(aoi, pred / "density" / "regions.geoparquet")
    page = ROOT / PAGES.get(aoi, f"results/{aoi}_pv_evidence_atlas.html")
    shown = sorted(p["name"] for p in _page_data(page).get("provinces", []))
    if shown != sorted(map(str, regions.name)):
        raise ValueError(f"{aoi}: {pred} does not hold the regions {page.name} draws")
    border = regions.geometry.union_all()
    # Outlines judged solar that OpenStreetMap has gained since: the wheel turning.
    judged_pv = cands[cands["review_verdict"].eq("pv").to_numpy() & ~np.asarray(is_lead)]
    mapped_since = int(judged_pv.geometry.representative_point().within(border).sum())
    leads = cands[is_lead].copy()
    rep = leads.geometry.representative_point()
    inside = rep.within(border).to_numpy()
    n_outside = int((~inside).sum())
    leads, rep = leads[inside].copy(), rep[inside]
    # A person's solar verdict outranks every screen below: the screens stand in for a look.
    sure = leads["review_verdict"].eq("pv").to_numpy()
    slope, steep_drop, steep_review = steep_lead_screen(leads)
    steep_drop = np.asarray(steep_drop) & ~sure
    leads["slope_deg"], leads["steep_review"] = slope.round(1), steep_review
    leads, rep, sure = leads[~steep_drop].copy(), rep[~steep_drop], sure[~steep_drop]
    lowconf = np.asarray(low_confidence_lead_screen(leads)) & ~sure
    leads, rep, sure = leads[~lowconf].copy(), rep[~lowconf], sure[~lowconf]
    water = None
    if lead_water_screen_enabled(aoi):
        wet, wet_drop = water_lead_screen(leads)
        wet_drop = np.asarray(wet_drop) & ~sure
        leads["ever_wet_frac"] = np.round(wet, 3)
        leads, rep = leads[~wet_drop].copy(), rep[~wet_drop]
        water = {"ever_wet_min": WATER_EVER_WET_MIN, "dropped": int(wet_drop.sum()),
                 "no_data": int(np.isnan(wet).sum())}
    leads["lon"], leads["lat"] = rep.x.round(6), rep.y.round(6)
    for c in ("rank_score", "confidence", "building_prior", "building_overlap_frac"):
        if c in leads:
            leads[c] = leads[c].astype(float).round(4)
    for c in ("area_m2", "building_dist_m"):
        if c in leads:
            leads[c] = leads[c].astype(float).round(1)
    leads = leads[[c for c in COLUMNS if c in leads.columns] + ["geometry"]]

    # A person's verdict sorts what is left: solar to the confirmed file, not solar out of
    # every file, unsure and unjudged to the lead and blob files as before.
    verdict = leads["review_verdict"]
    confirmed = write_confirmed(leads[verdict.eq("pv")], aoi, out, mapped_since)
    no = verdict.isin(JUDGED_NOT_PV)
    blob = leads["area_m2"].to_numpy(float) > MAX_CANDIDATE_M2
    judged_not_pv = {"leads": int((no & ~blob).sum()), "blobs": int((no & blob).sum())}
    leads = leads[~verdict.isin(("pv", *JUDGED_NOT_PV))]

    path = out / f"{aoi}_pv_new_leads.geojson"
    blobs = split_blobs(leads, aoi, out)
    export_file = pred / f"{aoi}_pv_new_leads.geojson"
    export_n = len(gpd.read_file(export_file, columns=[])) if export_file.exists() else None
    print(f"  {aoi:13s} {len(leads) - blobs['n']:7,d} leads + {blobs['n']:,} blobs + "
          f"{confirmed['n'] if confirmed else 0:,} confirmed of {len(cands):7,d} candidates "
          f"({n_outside:,} outside the page's regions, {int(steep_drop.sum()):,} on "
          f"steep ground dropped; {int(steep_review.sum()):,} steep_review; "
          f"{int(lowconf.sum()):,} open-ground low-confidence dropped; "
          f"{water['dropped'] if water else '-'} on ever-wet ground dropped; "
          f"{judged_not_pv['leads']:,} leads and {judged_not_pv['blobs']:,} blobs judged not "
          f"solar left out; {mapped_since:,} judged solar and mapped since; export file: "
          f"{export_n if export_n is not None else '-'}) -> {path.stat().st_size / 1e6:.1f} MB")
    return {
        "file": path.name,
        "n": len(leads) - blobs["n"],
        "size_bytes": path.stat().st_size,
        "osm_as_of": _osm_as_of(frames, paths),
        "min_distance_m": int(min_distance_m),
        "made": dt.date.today().isoformat(),
        "steep": {"slope_deg": STEEP_SLOPE_DEG, "max_area_m2": STEEP_MAX_AREA_M2,
                  "cap_deg": STEEP_CAP_DEG,
                  "dropped": src.get("screened", {}).get("steep", int(steep_drop.sum())),
                  "review": int(steep_review.sum()),
                  "no_dem": int(np.isnan(slope).sum())},
        "lowconf": {"placement": "no_building", "max_confidence": LOWCONF_MAX_CONFIDENCE,
                    "dropped": src.get("screened", {}).get("lowconf", int(lowconf.sum()))},
        **({"water": water} if water else {}),
        "blobs": blobs,
        **({"confirmed": confirmed} if confirmed else {}),
        "judged_not_pv": judged_not_pv,
    }


README = """# EarthPV confirmed mapping leads, {date}

One GeoJSON file per country, `<country>_pv_confirmed_leads.geojson`, largest first: solar
installations the EarthPV segmentation model outlined in Sentinel-2 imagery more than {dist} m
from every solar installation in OpenStreetMap, which a person has since judged solar. Each one
is a real installation waiting to be traced. Each country's file comes from the same model run
as its published evidence atlas (https://open-energy-transition.github.io/earthpv/atlas/),
which links it.

**Only checked leads are published (2026-11-19).** The model's other outlines are drawn from
10 m pixels and unchecked, and many are bright roofs, greenhouses, dark fields or rock, so they
are not handed to mappers. They go to two review pages first, one picture per outline from the
imagery the model saw (Sentinel-2 as composited, its false colour, and Esri World Imagery with
its capture date): the solar farm review for outlines above {blob_m2} m2 and the large
installation review for leads from {large_m2} m2 up to that. A named person gives each one a
verdict, and `review_page` names the page it was given on. A verdict outranks the lead screens
(steep ground, open ground at low confidence, pans and ponds), so a confirmed lead is kept
whatever its slope or model probability. The guide to judging is
https://open-energy-transition.github.io/earthpv/contribute/review/. Every model outline,
checked or not, is in the country's polygon file (release pv-polygons-2026-11-11), with any
verdict beside it.

**Trace, never import.** A confirmed outline is drawn from 10 m pixels, typically about twice
the area of the panels it found. Find each installation on recent high-resolution imagery and
trace what you see there; nothing here should be imported into OpenStreetMap automatically.
An outline above {blob_m2} m2 (`oversize`) was judged on Sentinel-2 and can take in the fields
around a park: map the park's outline or its panel blocks, never the model's outline. The
mapping guide is https://open-energy-transition.github.io/earthpv/contribute/leads/.

| column | meaning |
| --- | --- |
| candidate_id | id in the country's candidate and polygon exports |
| rank_score | model confidence times a building prior |
| confidence | peak (highest) model probability inside the outline |
| area_m2 | geodesic area of the outline; the sort key |
| placement | rooftop, ground_adjacent or no_building, from VIDA building footprints |
| building_dist_m, building_overlap_frac, building_prior, building_id | the building join behind placement |
| oversize | outline above {blob_m2} m2, judged on the solar farm review |
| slope_deg | Copernicus GLO-90 terrain slope in degrees at the lead's point (empty off the DEM) |
| steep_review | true on ground steeper than {steep_deg} degrees: check the panels are not the slope's own shadow |
| ever_wet_frac | share of the outline ever under water, 1984-2020 (only where the pans-and-ponds screen is on) |
| review_verdict | `pv`: a person judged it solar |
| review_page | `solar_farm` or `large_installation`: the review page the verdict was given on |
| lon, lat | a point inside the outline |

| country | confirmed leads | above {blob_m2} m2 | {large_m2} m2 up to that | judged not solar | OpenStreetMap as of |
| --- | ---: | ---: | ---: | ---: | --- |
{rows}

No confirmed leads yet: {none}.

Licence: derived from OpenStreetMap (ODbL 1.0, (c) OpenStreetMap contributors) and contains
modified Copernicus Sentinel-2 data. Released under the ODbL like every EarthPV data output.
"""
# Release assets that must never be published again (owner, 2026-11-19): the model's unchecked
# lead and blob files. `--upload` removes any it finds on the release.
UNCHECKED_SUFFIXES = ("_pv_new_leads.geojson", "_pv_blob_leads.geojson")


def _assets(out: Path, entries) -> list[Path]:
    """The confirmed files of the manifest entries `entries`, in `out`: the only lead files
    uploaded (owner, 2026-11-19). The lead and blob files stay local."""
    return [out / e["confirmed"]["file"] for e in entries if "confirmed" in e]


def _unlinked(entry: dict) -> dict:
    """A manifest entry without release links for its unchecked lead and blob files, which are
    no longer published (an entry written before 2026-11-19 carries them)."""
    entry = {k: v for k, v in entry.items() if k != "url"}
    if "blobs" in entry:
        entry["blobs"] = {k: v for k, v in entry["blobs"].items() if k != "url"}
    return entry


def country_name(aoi: str) -> str:
    """The country's English name, as the README gives it (the AOI key `turkiye` is not)."""
    return {"turkiye": "Turkey"}.get(aoi, aoi.replace("_", " ").title())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=RELEASE_DIR,
                    help=f"directory holding every country's release assets ({RELEASE_DIR})")
    ap.add_argument("--aoi", action="append", help="only these AOIs (default: every one)")
    ap.add_argument("--min-distance-m", type=float, default=100.0)
    ap.add_argument("--upload", action="store_true",
                    help=f"create {TAG} or update it: upload the confirmed files, README.md and "
                         "SHA256SUMS, and remove any unchecked lead or blob file from it")
    ap.add_argument("--resplit", action="store_true",
                    help="split the lead files already in --out (one file per country, from "
                         "before the blob file) into leads and blobs, keeping their date")
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild nothing: rewrite README.md, SHA256SUMS and the manifest from "
                         "the files already in --out (with --upload, re-sends every confirmed "
                         "file)")
    args = ap.parse_args()

    os.chdir(ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"aois": {}}
    if not args.refresh:
        for aoi in args.aoi or list(SOURCES):
            manifest["aois"][aoi] = (resplit(aoi, manifest["aois"][aoi], args.out)
                                     if args.resplit else
                                     build(aoi, SOURCES.get(aoi, {}), args.out,
                                           args.min_distance_m))
    manifest["aois"] = {a: (e if a == "france" else _unlinked(e))
                        for a, e in manifest["aois"].items()}
    manifest["aois"]["france"] = FRANCE
    manifest["aois"] = dict(sorted(manifest["aois"].items()))
    manifest["release"] = f"https://github.com/{REPO}/releases/tag/{TAG}"

    built = {a: e for a, e in manifest["aois"].items() if a != "france"}
    rows = "\n".join(f"| {country_name(a)} | {e['confirmed']['n']:,} | "
                     f"{e['confirmed'].get('n_solar_farm', 0):,} | "
                     f"{e['confirmed'].get('n_large_installation', 0):,} | "
                     f"{sum(e.get('judged_not_pv', {}).values()):,} | {e['osm_as_of']} |"
                     for a, e in built.items() if "confirmed" in e)
    none = ", ".join(country_name(a) for a, e in manifest["aois"].items()
                     if "confirmed" not in e) or "none"
    made = sorted({e["made"] for e in built.values()})
    (args.out / "README.md").write_text(README.format(
        date=made[-1] if (args.resplit or args.refresh) else dt.date.today().isoformat(),
        dist=int(args.min_distance_m), rows=rows, none=none, blob_m2=f"{MAX_CANDIDATE_M2:,.0f}",
        large_m2=f"{LARGE_MIN_M2:,.0f}", steep_deg=f"{STEEP_SLOPE_DEG:g}"))
    files = _assets(args.out, built.values()) + [args.out / "README.md"]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise SystemExit(f"--out lacks {', '.join(missing)}: it must hold every country's "
                         "confirmed file")
    sums = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in files]
    (args.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)} and {len(files) + 1} release assets in "
          f"{args.out} (lead and blob files stay local)")

    if args.upload:
        view = subprocess.run(["gh", "release", "view", TAG, "-R", REPO, "--json", "assets"],
                              capture_output=True, text=True)
        exists = view.returncode == 0
        # Into an existing release only what changed: these countries' confirmed files, and
        # the README and checksums that list every country (also the release's notes).
        sent = (_assets(args.out, [built[a] for a in args.aoi if a in built])
                + [args.out / "README.md"]) if exists and args.aoi and not args.refresh else files
        assets = [str(f) for f in sent] + [str(args.out / "SHA256SUMS")]
        title = "Confirmed PV mapping leads per country"
        if exists:
            subprocess.run(["gh", "release", "upload", TAG, "-R", REPO, "--clobber", *assets],
                           check=True)
            subprocess.run(["gh", "release", "edit", TAG, "-R", REPO, "--title", title,
                            "--notes-file", str(args.out / "README.md")], check=True)
            # A confirmed file whose country now has none, and every unchecked lead or blob
            # file, leaves the release.
            keep = {f.name for f in files} | {"SHA256SUMS"}
            stale = [a["name"] for a in json.loads(view.stdout)["assets"]
                     if a["name"] not in keep
                     and (a["name"].endswith(UNCHECKED_SUFFIXES)
                          or a["name"].endswith("_pv_confirmed_leads.geojson"))]
            for name in stale:
                subprocess.run(["gh", "release", "delete-asset", TAG, name, "-R", REPO, "--yes"],
                               check=True)
            print(f"uploaded {len(assets)} assets to {TAG}; removed {len(stale)}")
        else:
            subprocess.run(["gh", "release", "create", TAG, "-R", REPO, "--latest=false",
                            "--title", title, "--notes-file", str(args.out / "README.md"),
                            *assets], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
