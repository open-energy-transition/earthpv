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

Nothing is filtered for precision. Leads are unverified 10 m outlines, recall-first like
every candidate file, and the README asset says so.

France is not built here: its leads were audited against IGN aerial imagery and released
on their own (`france-osm-leads-2026-10-22`, scripts/build_france_osm_leads.py); its
manifest entry links that file.

    pixi run python scripts/release_leads.py --out /home/tobi/earthpv_data/pv_new_leads_2026-10-28
    pixi run python scripts/release_leads.py --out ... --upload     # gh release create/upload

Writes `<out>/<aoi>_pv_new_leads.geojson`, `<out>/README.md`, `<out>/SHA256SUMS` and
`configs/atlas_leads.json`, which `atlas.leads_release` reads into `totals.leads` and
scripts/patch_atlas_leads.py adds to published pages.
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
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from earthpv import atlas  # noqa: E402
from earthpv.export import new_lead_mask  # noqa: E402

REPO = "open-energy-transition/earthpv"
MANIFEST = ROOT / "configs" / "atlas_leads.json"
TAG = "pv-new-leads-2026-10-28"

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
    "india": {}, "vietnam": {}, "zambia": {}, "egypt": {}, "yemen": {},
    "south_africa": {}, "morocco": {}, "poland": {},
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
}
COLUMNS = ["candidate_id", "rank_score", "confidence", "area_m2", "placement",
           "building_dist_m", "building_overlap_frac", "building_prior", "building_id",
           "oversize", "lon", "lat"]


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
    leads["lon"], leads["lat"] = rep.x.round(6), rep.y.round(6)
    for c in ("rank_score", "confidence", "building_prior", "building_overlap_frac"):
        if c in leads:
            leads[c] = leads[c].astype(float).round(4)
    for c in ("area_m2", "building_dist_m"):
        if c in leads:
            leads[c] = leads[c].astype(float).round(1)
    leads = leads[[c for c in COLUMNS if c in leads.columns] + ["geometry"]]

    path = out / f"{aoi}_pv_new_leads.geojson"
    path.unlink(missing_ok=True)
    leads.to_file(path, driver="GeoJSON", layer_options={"COORDINATE_PRECISION": "7"})
    export_file = pred / f"{aoi}_pv_new_leads.geojson"
    export_n = len(gpd.read_file(export_file, columns=[])) if export_file.exists() else None
    print(f"  {aoi:13s} {len(leads):7,d} leads of {len(cands):7,d} candidates "
          f"({n_outside:,} outside the page's regions dropped; export file: "
          f"{export_n if export_n is not None else '-'}) -> {path.stat().st_size / 1e6:.1f} MB")
    return {
        "file": path.name,
        "url": f"https://github.com/{REPO}/releases/download/{TAG}/{path.name}",
        "n": len(leads),
        "size_bytes": path.stat().st_size,
        "osm_as_of": _osm_as_of(frames, paths),
        "min_distance_m": int(min_distance_m),
        "made": dt.date.today().isoformat(),
    }


README = """# EarthPV mapping leads, {date}

One GeoJSON per country: solar arrays the EarthPV segmentation model outlined in Sentinel-2
imagery that lie more than {dist} m from every solar installation in OpenStreetMap when the
file was made. Each country's file comes from the same model run as its published evidence
atlas (https://open-energy-transition.github.io/earthpv/atlas/), which links it.

**These are leads, not data.** Every feature is an unverified outline drawn from 10 m pixels,
typically about twice the area of the panels it found. Check each one against recent
high-resolution imagery before mapping anything; some will be bright roofs, greenhouses,
dark fields or rock. Nothing here should be imported into OpenStreetMap automatically. The
mapping guide is https://open-energy-transition.github.io/earthpv/contribute/.

Features are sorted most promising first. Columns:

| column | meaning |
| --- | --- |
| candidate_id | id in the country's candidate and MapRoulette exports |
| rank_score | model confidence times a building prior; the sort key |
| confidence | mean model probability inside the outline |
| area_m2 | geodesic area of the outline |
| placement | rooftop, ground_adjacent or no_building, from VIDA building footprints |
| building_dist_m, building_overlap_frac, building_prior, building_id | the building join behind placement |
| oversize | outline above 100,000 m2: excluded from the atlas's capacity, often a real unmapped park |
| lon, lat | a point inside the outline |

| country | leads | OpenStreetMap as of |
| --- | ---: | --- |
{rows}

France's leads are a separate, audited release: https://github.com/{repo}/releases/tag/france-osm-leads-2026-10-22

Licence: derived from OpenStreetMap (ODbL 1.0, (c) OpenStreetMap contributors) and contains
modified Copernicus Sentinel-2 data. Released under the ODbL like every EarthPV data output.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="directory for the release assets")
    ap.add_argument("--aoi", action="append", help="only these AOIs (default: every one)")
    ap.add_argument("--min-distance-m", type=float, default=100.0)
    ap.add_argument("--upload", action="store_true", help=f"create {TAG} and upload the assets")
    args = ap.parse_args()

    import os
    os.chdir(ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"aois": {}}
    for aoi in args.aoi or list(SOURCES):
        manifest["aois"][aoi] = build(aoi, SOURCES[aoi], args.out, args.min_distance_m)
    manifest["aois"]["france"] = FRANCE
    manifest["aois"] = dict(sorted(manifest["aois"].items()))
    manifest["release"] = f"https://github.com/{REPO}/releases/tag/{TAG}"

    built = {a: e for a, e in manifest["aois"].items() if a != "france"}
    rows = "\n".join(f"| {a.replace('_', ' ').title()} | {e['n']:,} | {e['osm_as_of']} |"
                     for a, e in built.items())
    (args.out / "README.md").write_text(README.format(
        date=dt.date.today().isoformat(), dist=int(args.min_distance_m), rows=rows, repo=REPO))
    files = [args.out / e["file"] for e in built.values()] + [args.out / "README.md"]
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
