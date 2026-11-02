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

France is not built here: its leads were audited against IGN aerial imagery and released
on their own (`france-osm-leads-2026-10-22`, scripts/build_france_osm_leads.py, which already
kept its outlines above the cap apart); its manifest entry links those files.

    pixi run python scripts/release_leads.py --out /home/tobi/earthpv_data/pv_new_leads_2026-11-01
    pixi run python scripts/release_leads.py --out ... --upload     # gh release create/upload
    pixi run python scripts/release_leads.py --out <dir of a published release> --resplit

Writes `<out>/<aoi>_pv_new_leads.geojson`, `<out>/<aoi>_pv_blob_leads.geojson`,
`<out>/README.md`, `<out>/SHA256SUMS` and `configs/atlas_leads.json`, which
`atlas.leads_release` reads into `totals.leads` and scripts/patch_atlas_leads.py adds to
published pages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from earthpv import atlas  # noqa: E402
from earthpv.postprocess import MAX_CANDIDATE_M2  # noqa: E402
from earthpv.export import (LOWCONF_MAX_CONFIDENCE, STEEP_CAP_DEG,  # noqa: E402
                            STEEP_MAX_AREA_M2, STEEP_SLOPE_DEG, WATER_EVER_WET_MIN,
                            lead_water_screen_enabled, low_confidence_lead_screen,
                            new_lead_mask, steep_lead_screen, water_lead_screen)

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
# their URLs there.
TAG = "pv-new-leads-2026-11-02"

# Per AOI: the candidates behind its published atlas, the OSM pull(s) that count as
# mapped, and the density directory holding the regions the page draws.
SOURCES = {
    "pakistan": {},
    # Germany's national file carries the 52,946 OSM nodes the pre-cap file lacks; the
    # pre-cap file carries the ground outlines above 5 km2 the national file dropped.
    "germany": {"osm": ["data/labels/germany_national_osm_solar.parquet",
                        "data/labels/germany_national_osm_solar_PRE_ground_cap.parquet"]},
    # Nigeria's atlas is the v5 run; data/predictions/nigeria holds the losing checkpoint's.
    "nigeria": {"pred": "data/predictions_v5_nigeria/nigeria"},
    # Yemen's atlas is the v25 run (2026-11-02); data/predictions/yemen holds v13's.
    "yemen": {"pred": "data/predictions_v25/yemen"},
    "india": {}, "vietnam": {}, "zambia": {}, "egypt": {},
    "south_africa": {}, "morocco": {}, "poland": {}, "namibia": {},
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
           "oversize", "slope_deg", "steep_review", "ever_wet_frac", "lon", "lat"]


def _osm_as_of(frames: list[gpd.GeoDataFrame], paths: list[Path]) -> str:
    """The latest edit in the pull, a lower bound on the day it was taken."""
    stamps = [pd.to_datetime(f["osm_timestamp"], utc=True, errors="coerce").max()
              for f in frames if "osm_timestamp" in f]
    stamps = [s for s in stamps if pd.notna(s)]
    if stamps:
        return max(stamps).date().isoformat()
    return dt.date.fromtimestamp(max(p.stat().st_mtime for p in paths)).isoformat()


def _page_data(page: Path) -> dict:
    from retemplate_atlas import extract, read_old_template

    return json.loads(extract(read_old_template("HEAD"), page.read_text())["__PV_DATA_JSON__"])


def _write(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.unlink(missing_ok=True)
    gdf.to_file(path, driver="GeoJSON", layer_options={"COORDINATE_PRECISION": "7"})


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
    # export.run_export's ranking and numbering, call for call, so ids agree with it.
    sort_col = "rank_score" if "rank_score" in cands.columns else "confidence"
    cands = cands.sort_values(sort_col, ascending=False).reset_index(drop=True)
    cands["candidate_id"] = [f"{aoi}-pv-{i:06d}" for i in range(len(cands))]

    paths = [ROOT / p for p in src.get("osm", [f"data/labels/{aoi}_overpass_solar.parquet"])]
    frames = [gpd.read_parquet(p) for p in paths]
    mapped = gpd.GeoDataFrame(pd.concat([f[["geometry"]] for f in frames], ignore_index=True),
                              geometry="geometry", crs="EPSG:4326")
    mapped = mapped[mapped.geometry.notna() & ~mapped.geometry.is_empty]
    leads = cands[new_lead_mask(cands, mapped, min_distance_m)].copy()

    regions = atlas._page_regions(aoi, pred / "density" / "regions.geoparquet")
    page = ROOT / PAGES.get(aoi, f"results/{aoi}_pv_evidence_atlas.html")
    shown = sorted(p["name"] for p in _page_data(page).get("provinces", []))
    if shown != sorted(map(str, regions.name)):
        raise ValueError(f"{aoi}: {pred} does not hold the regions {page.name} draws")
    rep = leads.geometry.representative_point()
    inside = rep.within(regions.geometry.union_all()).to_numpy()
    n_outside = int((~inside).sum())
    leads, rep = leads[inside].copy(), rep[inside]
    slope, steep_drop, steep_review = steep_lead_screen(leads)
    leads["slope_deg"], leads["steep_review"] = slope.round(1), steep_review
    leads, rep = leads[~steep_drop].copy(), rep[~steep_drop]
    lowconf = low_confidence_lead_screen(leads)
    leads, rep = leads[~lowconf].copy(), rep[~lowconf]
    water = None
    if lead_water_screen_enabled(aoi):
        wet, wet_drop = water_lead_screen(leads)
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

    path = out / f"{aoi}_pv_new_leads.geojson"
    blobs = split_blobs(leads, aoi, out)
    export_file = pred / f"{aoi}_pv_new_leads.geojson"
    export_n = len(gpd.read_file(export_file, columns=[])) if export_file.exists() else None
    print(f"  {aoi:13s} {len(leads) - blobs['n']:7,d} leads + {blobs['n']:,} blobs of "
          f"{len(cands):7,d} candidates "
          f"({n_outside:,} outside the page's regions, {int(steep_drop.sum()):,} on "
          f"steep ground dropped; {int(steep_review.sum()):,} steep_review; "
          f"{int(lowconf.sum()):,} open-ground low-confidence dropped; "
          f"{water['dropped'] if water else '-'} on ever-wet ground dropped; export file: "
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
                  "dropped": int(steep_drop.sum()), "review": int(steep_review.sum()),
                  "no_dem": int(np.isnan(slope).sum())},
        "lowconf": {"placement": "no_building", "max_confidence": LOWCONF_MAX_CONFIDENCE,
                    "dropped": int(lowconf.sum())},
        **({"water": water} if water else {}),
        "blobs": blobs,
    }


README = """# EarthPV mapping leads, {date}

Two GeoJSON files per country: solar arrays the EarthPV segmentation model outlined in
Sentinel-2 imagery that lie more than {dist} m from every solar installation in OpenStreetMap
when the file was made. `<country>_pv_new_leads.geojson` holds the leads up to {blob_m2} m2,
most promising first; `<country>_pv_blob_leads.geojson` holds the very large outlines above
that, largest first (see "Very large outlines" below). Each country's files come from the
same model run as its published evidence atlas
(https://open-energy-transition.github.io/earthpv/atlas/), which links them.

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
| lon, lat | a point inside the outline |

| country | leads | blobs | steep leads left out | steep_review | open ground, low confidence, left out | pans and ponds left out | OpenStreetMap as of |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
{rows}

France's leads are a separate, audited release, its blobs in `france_pv_leads_oversize.geojson`: https://github.com/{repo}/releases/tag/france-osm-leads-2026-10-22

Licence: derived from OpenStreetMap (ODbL 1.0, (c) OpenStreetMap contributors) and contains
modified Copernicus Sentinel-2 data. Released under the ODbL like every EarthPV data output.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="directory for the release assets")
    ap.add_argument("--aoi", action="append", help="only these AOIs (default: every one)")
    ap.add_argument("--min-distance-m", type=float, default=100.0)
    ap.add_argument("--upload", action="store_true", help=f"create {TAG} and upload the assets")
    ap.add_argument("--resplit", action="store_true",
                    help="split the lead files already in --out (one file per country, from "
                         "before the blob file) into leads and blobs, keeping their date")
    args = ap.parse_args()

    import os
    os.chdir(ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"aois": {}}
    for aoi in args.aoi or list(SOURCES):
        manifest["aois"][aoi] = (resplit(aoi, manifest["aois"][aoi], args.out) if args.resplit
                                 else build(aoi, SOURCES[aoi], args.out, args.min_distance_m))
    manifest["aois"]["france"] = FRANCE
    manifest["aois"] = dict(sorted(manifest["aois"].items()))
    manifest["release"] = f"https://github.com/{REPO}/releases/tag/{TAG}"

    built = {a: e for a, e in manifest["aois"].items() if a != "france"}
    rows = "\n".join(f"| {a.replace('_', ' ').title()} | {e['n']:,} | "
                     f"{e.get('blobs', {}).get('n', 0):,} | "
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
        steep_area=f"{STEEP_MAX_AREA_M2:,.0f}", steep_deg=f"{STEEP_SLOPE_DEG:g}",
        steep_cap=f"{STEEP_CAP_DEG:g}", lowconf_max=f"{LOWCONF_MAX_CONFIDENCE:g}",
        water_pct=f"{100 * WATER_EVER_WET_MIN:g}",
        water_aois=", ".join(a.replace("_", " ").title() for a, e in built.items()
                             if "water" in e) or "none yet"))
    files = ([args.out / e[k]["file"] if k else args.out / e["file"]
              for e in built.values() for k in (None, "blobs") if k is None or k in e]
             + [args.out / "README.md"])
    sums = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in files]
    (args.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)} and {len(files) + 1} assets in {args.out}")

    if args.upload:
        assets = [str(f) for f in files] + [str(args.out / "SHA256SUMS")]
        exists = subprocess.run(["gh", "release", "view", TAG, "-R", REPO],
                                capture_output=True).returncode == 0
        if exists:
            cmd = ["gh", "release", "upload", TAG, "-R", REPO, "--clobber", *assets]
        else:
            cmd = ["gh", "release", "create", TAG, "-R", REPO, "--latest=false",
                   "--title", f"PV mapping leads per country ({dt.date.today().isoformat()})",
                   "--notes-file", str(args.out / "README.md"), *assets]
        subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
