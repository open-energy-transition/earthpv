#!/usr/bin/env python
"""Build each country's mapping-lead file for a GitHub release, and the manifest the
evidence atlases link it from.

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
`<aoi>_pv_new_leads.geojson` keeps the rest, most promising first. Silver needs a third of
each file checked (`atlas.LEAD_SHARE_MIN`). `--resplit` splits files built before this
(every lead in one file) in place, keeping their date, so a lead check made on them still
names them.

**A person's verdict turns an outline into a confirmed lead (2026-11-19).** The solar farm
review (blobs) and the large installation review (leads from 10,000 m2 up to the cap) judge
outlines on the imagery the model saw (scripts/oversize_review.py). Their verdicts, read from
the review blocks of the country's calibration table (`review_table`, as `density` and
scripts/release_polygons.py read them), sort the leads three ways. An outline judged solar
that OpenStreetMap still lacks goes to `<aoi>_pv_confirmed_leads.geojson`, largest first:
every one is solar, so it is the first file a mapper should open. A verdict outranks the
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
`--upload` sends only those countries' files plus README.md and SHA256SUMS (which cover every
country's files, so `--out` must hold them all: the default is the release's own directory).

France is not built here: its leads were audited against IGN aerial imagery and released
on their own (`france-osm-leads-2026-10-22`, scripts/build_france_osm_leads.py, which already
kept its outlines above the cap apart); its manifest entry links those files.

    pixi run python scripts/release_leads.py --out /home/tobi/earthpv_data/pv_new_leads_2026-11-01
    pixi run python scripts/release_leads.py --out ... --upload     # gh release create/upload
    pixi run python scripts/release_leads.py --aoi italy --upload   # one country, default --out
    pixi run python scripts/release_leads.py --out <dir of a published release> --resplit

Writes `<out>/<aoi>_pv_new_leads.geojson`, `<out>/<aoi>_pv_blob_leads.geojson`,
`<out>/<aoi>_pv_confirmed_leads.geojson` (only where a person has judged a lead solar),
`<out>/README.md`, `<out>/SHA256SUMS` and `configs/atlas_leads.json`, which
`atlas.leads_release` reads into `totals.leads` and scripts/patch_atlas_leads.py adds to
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
# and from then on every new atlas (run_country_compute.sh's `leads` step).
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
    return {"file": path.name,
            "url": f"https://github.com/{REPO}/releases/download/{TAG}/{path.name}",
            "n": int(blob.sum()), "size_bytes": path.stat().st_size,
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
        "url": f"https://github.com/{REPO}/releases/download/{TAG}/{path.name}",
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


README = """# EarthPV mapping leads, {date}

Up to three GeoJSON files per country: solar arrays the EarthPV segmentation model outlined in
Sentinel-2 imagery that lie more than {dist} m from every solar installation in OpenStreetMap
when the file was made. `<country>_pv_confirmed_leads.geojson`, where a country has one, holds
the outlines a person has already judged solar on the review pages, largest first: map these
first (see "Judged solar" below). `<country>_pv_new_leads.geojson` holds the other leads up to
{blob_m2} m2, most promising first; `<country>_pv_blob_leads.geojson` holds the other very
large outlines above that, largest first (see "Very large outlines" below). Each country's
files come from the same model run as its published evidence atlas
(https://open-energy-transition.github.io/earthpv/atlas/), which links them.

**Judged solar: the confirmed leads.** Every country's run draws two review pages, one picture
per outline from the imagery the model saw (Sentinel-2 as composited, its false colour, and
Esri World Imagery with its capture date): the solar farm review for outlines above {blob_m2}
m2 and the large installation review for leads from {large_m2} m2 up to that. A named person
gives each one a verdict. Outlines judged solar that OpenStreetMap still lacks are in the
confirmed file, whatever the screens below would say: each is a real installation waiting to
be traced. `review_page` names the page it was judged on. Outlines judged not solar are left
out of all three files, so nobody checks them twice; an outline judged unsure stays in the
leads or blob file with `review_verdict = unsure`. The guide to judging is
https://open-energy-transition.github.io/earthpv/contribute/review/.

**These are leads, not data.** Every feature is an unverified outline drawn from 10 m pixels,
typically about twice the area of the panels it found. Check each one against recent
high-resolution imagery before mapping anything; some will be bright roofs, greenhouses,
dark fields or rock. Nothing here should be imported into OpenStreetMap automatically. The
mapping guide is https://open-energy-transition.github.io/earthpv/contribute/.

**Steep ground.** Shaded hillsides, cliff edges and the shadows below escarpments read like
panels in Sentinel-2. A lead smaller than {steep_area} m2 on ground steeper than
{steep_deg} degrees (Copernicus GLO-90 slope at a point inside the outline) is left out of
these files. Of 89 such leads drawn across twelve countries and checked on imagery none was
solar (86 were not, 3 could not be settled), and the rule would remove 2 of the 22,124
outlines the model drew on solar that is mapped. A larger lead on steep ground
is kept and marked `steep_review = true`: a solar farm can be built on a mountainside, so
someone has to look at it. Above {steep_cap} degrees a lead of any size is left out: shadowed
cliffs again, and none of the 13,344 outlines of 1,000 m2 or more that the model drew on
mapped solar stands that steep. Every lead carries the slope it was judged on (`slope_deg`).

**Open ground at low confidence.** A lead with no building near it whose peak model
probability is below {lowconf_max} is left out at any size: dark fields, riverbeds, shaded
slopes, forest, farm reservoirs. Germany's register, which locates every unit of 30 kW or
more, finds one inside 0-5% of such outlines against 10-38% of the more confident ones,
none of 18 drawn at random was solar on imagery, and leaving them out loses at most 1.5% of
the mapped solar area the model finds. A `steep_review` lead stays whatever its probability.

**Pans and ponds (some countries only).** In countries where it is switched on
({water_aois}), a lead not on a rooftop with at least {water_pct}% of its outline ever
under water since 1984 (JRC Global Surface Water) is left out: seasonal pans, salt pans,
fish and wastewater ponds. Those leads carry `ever_wet_frac`. It stays off where solar
stands on water or wet ground (floating plants, pond PV, salt-marsh parks).

**Very large outlines (blobs).** An outline above {blob_m2} m2 (10 ha) is in the blob file.
Sentinel-2's 10 m pixels merge everything bright and touching into one shape, so a blob is a
solar park OpenStreetMap does not hold yet as often as a sheet of false alarms: pans,
ploughed fields, shadowed slopes. India's reviewed blobs were mostly parks (81 of 90); of
Pakistan's 121 blobs from July only 3 have been mapped since. The atlases never count a
blob's capacity until it is mapped in OpenStreetMap or a person has judged it solar on the
Sentinel-2 imagery the model saw. Map the panels or the park's outline, not the blob.

**How much to check.** A Silver atlas needs about a third of its leads and a third of its
blobs to have a verdict (the real installations mapped in OpenStreetMap, the rest judged not
solar) and the model retrained on what was mapped. Work from the top of
the leads file: in Pakistan the top third held more than two thirds of all the leads people
mapped later, in Yemen almost nine in ten. Work through the blobs largest first.

Features in the leads file are sorted most promising first. Columns:

| column | meaning |
| --- | --- |
| candidate_id | id in the country's candidate and MapRoulette exports |
| rank_score | model confidence times a building prior; the sort key |
| confidence | peak (highest) model probability inside the outline |
| area_m2 | geodesic area of the outline |
| placement | rooftop, ground_adjacent or no_building, from VIDA building footprints |
| building_dist_m, building_overlap_frac, building_prior, building_id | the building join behind placement |
| oversize | outline above {blob_m2} m2: true in the blob file only |
| slope_deg | Copernicus GLO-90 terrain slope in degrees at the lead's point (empty off the DEM) |
| steep_review | true for a lead of {steep_area} m2 or more on ground steeper than {steep_deg} degrees (and not above {steep_cap}): kept for a human, may be shadow on a slope or a mountain solar farm |
| ever_wet_frac | share of the outline ever under water, 1984-2020 (only where the pans-and-ponds screen is on) |
| review_verdict | `pv` in the confirmed file; `unsure` where a person looked on a review page and could not settle it; empty if nobody has judged it |
| review_page | `solar_farm` or `large_installation`: the review page the verdict was given on |
| lon, lat | a point inside the outline |

| country | confirmed | leads | blobs | judged not solar, left out | steep leads left out | steep_review | open ground, low confidence, left out | pans and ponds left out | OpenStreetMap as of |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
{rows}

France's leads are a separate, audited release, its blobs in `france_pv_leads_oversize.geojson`: https://github.com/{repo}/releases/tag/france-osm-leads-2026-10-22

Licence: derived from OpenStreetMap (ODbL 1.0, (c) OpenStreetMap contributors) and contains
modified Copernicus Sentinel-2 data. Released under the ODbL like every EarthPV data output.
"""


def _assets(out: Path, entries) -> list[Path]:
    """The lead, blob and confirmed files of the manifest entries `entries`, in `out`."""
    return [out / (e[k]["file"] if k else e["file"])
            for e in entries for k in (None, "blobs", "confirmed") if k is None or k in e]


def country_name(aoi: str) -> str:
    """The country's English name, as the README gives it (the AOI key `turkiye` is not)."""
    return {"turkiye": "Turkey"}.get(aoi, aoi.replace("_", " ").title())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=RELEASE_DIR,
                    help=f"directory holding every country's release assets ({RELEASE_DIR})")
    ap.add_argument("--aoi", action="append", help="only these AOIs (default: every one)")
    ap.add_argument("--min-distance-m", type=float, default=100.0)
    ap.add_argument("--upload", action="store_true", help=f"create {TAG} and upload the assets")
    ap.add_argument("--resplit", action="store_true",
                    help="split the lead files already in --out (one file per country, from "
                         "before the blob file) into leads and blobs, keeping their date")
    args = ap.parse_args()

    os.chdir(ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"aois": {}}
    for aoi in args.aoi or list(SOURCES):
        manifest["aois"][aoi] = (resplit(aoi, manifest["aois"][aoi], args.out) if args.resplit
                                 else build(aoi, SOURCES.get(aoi, {}), args.out, args.min_distance_m))
    manifest["aois"]["france"] = FRANCE
    manifest["aois"] = dict(sorted(manifest["aois"].items()))
    manifest["release"] = f"https://github.com/{REPO}/releases/tag/{TAG}"

    built = {a: e for a, e in manifest["aois"].items() if a != "france"}
    rows = "\n".join(f"| {country_name(a)} | {e.get('confirmed', {}).get('n', 0):,} | "
                     f"{e['n']:,} | {e.get('blobs', {}).get('n', 0):,} | "
                     f"{sum(e.get('judged_not_pv', {}).values()):,} | "
                     f"{e.get('steep', {}).get('dropped', 0):,} | "
                     f"{e.get('steep', {}).get('review', 0):,} | "
                     f"{e.get('lowconf', {}).get('dropped', 0):,} | "
                     f"{format(e['water']['dropped'], ',') if 'water' in e else 'off'} | "
                     f"{e['osm_as_of']} |"
                     for a, e in built.items())
    made = sorted({e["made"] for e in built.values()})
    (args.out / "README.md").write_text(README.format(
        date=made[-1] if args.resplit else dt.date.today().isoformat(),
        dist=int(args.min_distance_m), rows=rows, repo=REPO, blob_m2=f"{MAX_CANDIDATE_M2:,.0f}",
        large_m2=f"{LARGE_MIN_M2:,.0f}",
        steep_area=f"{STEEP_MAX_AREA_M2:,.0f}", steep_deg=f"{STEEP_SLOPE_DEG:g}",
        steep_cap=f"{STEEP_CAP_DEG:g}", lowconf_max=f"{LOWCONF_MAX_CONFIDENCE:g}",
        water_pct=f"{100 * WATER_EVER_WET_MIN:g}",
        water_aois=", ".join(country_name(a) for a, e in built.items()
                             if "water" in e) or "none yet"))
    files = _assets(args.out, built.values()) + [args.out / "README.md"]
    sums = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in files]
    (args.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)} and {len(files) + 1} assets in {args.out}")

    if args.upload:
        exists = subprocess.run(["gh", "release", "view", TAG, "-R", REPO],
                                capture_output=True).returncode == 0
        # Into an existing release only what changed: these countries' files, and the README
        # and checksums that list every country (also the release's notes).
        sent = (_assets(args.out, [built[a] for a in args.aoi if a in built])
                + [args.out / "README.md"]) if exists and args.aoi else files
        assets = [str(f) for f in sent] + [str(args.out / "SHA256SUMS")]
        if exists:
            subprocess.run(["gh", "release", "upload", TAG, "-R", REPO, "--clobber", *assets],
                           check=True)
            cmd = ["gh", "release", "edit", TAG, "-R", REPO,
                   "--notes-file", str(args.out / "README.md")]
        else:
            cmd = ["gh", "release", "create", TAG, "-R", REPO, "--latest=false",
                   "--title", f"PV mapping leads per country ({dt.date.today().isoformat()})",
                   "--notes-file", str(args.out / "README.md"), *assets]
        subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
