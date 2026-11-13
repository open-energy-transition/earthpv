#!/usr/bin/env python
"""Build a country's solar polygon file for a GitHub release: every outline the
segmentation model drew behind its published evidence atlas, and every OpenStreetMap solar
feature the atlas counts, in one compressed GeoParquet, plus the manifest the atlas's
Downloads section links it from.

**Model rows** (`source = "model"`) are the candidates of the run behind the page
(`release_leads.SOURCES`: `data/predictions/<aoi>/candidates.parquet` unless named), every
size and placement, matched or not, numbered with `earthpv export`'s `candidate_id` (sorted
by `rank_score`), so an id is the one in the country's lead file. A candidate whose
representative point falls outside the regions the page draws is left out, as in the lead
file: a composited cell can reach across a border. Where postprocess matched a candidate to
a mapped installation it carries that installation's outline (`geometry_source = "osm"`),
so the same outline then appears as an OSM row too. `osm_within_100m` is the lead rule
inverted (`export.new_lead_mask` against the raw OSM pull at 100 m): false is a lead.
`review_verdict` is a person's verdict on the imagery the model saw, from the solar farm
review (outlines above the 100,000 m2 merge cap) and the large installation review (leads
from 10,000 m2), where the country's calibration table records one.

**OSM rows** (`source = "osm"`) are the atlas's `--osm-solar` file
(`data/labels/<aoi>_national_osm_solar.parquet`: clipped to the border, solar thermal out),
as it is, before the atlas merges overlapping outlines, plus the country's concentrating
solar power plants (`technology = "csp"`, `data/labels/<aoi>_csp_plants.parquet`), which
the atlas counts at their electric rating, never as PV.

The file is sorted along a Hilbert curve, carries a GeoParquet 1.1 `bbox` covering column
and is written in row groups of `ROW_GROUP` rows with zstd, so a reader that filters by
area (DuckDB, GDAL >= 3.9, GeoPandas `bbox=`) reads only the row groups it needs.
OpenStreetMap coordinates keep their own 7 decimals; model outlines are rounded to 6
(about 10 cm, against a 10 m pixel), which takes India's file from 24 to 18 MB.

**Every atlas gets its file by default (owner, 2026-11-13)**, like its lead files:
scripts/run_country_compute.sh runs `--aoi <aoi> --upload` after the `leads` step, then
scripts/patch_atlas_polygons.py on the page. Into an existing release `--upload` sends only
the named countries' files plus README.md and SHA256SUMS, which list every country, so
`--out` must hold them all: the default is the release's own directory. The OSM rows are the
atlas's own `--osm-solar` file: the one `earthpv atlas` recorded in
`<pred>/density/evidence_atlas_inputs.json` (since 2026-11-07), else `ATLAS_OSM_SOLAR`, else
`data/labels/<aoi>_national_osm_solar.parquet`; `--osm-solar` overrides all three.

    pixi run python scripts/release_polygons.py --aoi india
    pixi run python scripts/release_polygons.py --aoi italy --upload   # default --out

Writes `<out>/<aoi>_pv_polygons.parquet`, `<out>/README.md`, `<out>/SHA256SUMS` and
`configs/atlas_polygons.json`, which `atlas.polygons_release` reads into
`totals.polygons` and scripts/patch_atlas_polygons.py adds to a published page.
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
import shapely
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from earthpv import atlas  # noqa: E402
from earthpv.export import new_lead_mask  # noqa: E402
from earthpv.postprocess import MAX_CANDIDATE_M2  # noqa: E402
from release_leads import PAGES, REPO, SOURCES, _osm_as_of, _page_data, country_name  # noqa: E402

MANIFEST = ROOT / "configs" / "atlas_polygons.json"
TAG = "pv-polygons-2026-11-11"
# Every country's file as uploaded under TAG: README.md and SHA256SUMS cover them all.
RELEASE_DIR = Path(os.environ.get(
    "EARTHPV_POLYGONS_DIR",
    Path.home() / "earthpv_data" / f"pv_polygons_{TAG.removeprefix('pv-polygons-')}"))
# Runs the lead release's table does not describe. France's leads were released apart
# (scripts/build_france_osm_leads.py), from the v5 run and the 2026-10-22 pull its solar farm
# review also used (oversize_review.FRANCE).
# Germany's lead release also names germany_national_osm_solar_PRE_ground_cap.parquet, which
# is no longer on disk (2026-11-13): here the national file alone is the mapped reference, so
# a model outline near one of the ground outlines above 5 km2 that file drops can read as a
# lead in `osm_within_100m` although the lead file left it out.
POLY_SOURCES = {"france": {"pred": "data/predictions_v5/france",
                           "osm": ["data/labels/france_mapped_20261022.parquet"]},
                "germany": {"osm": ["data/labels/germany_national_osm_solar.parquet"]}}
# The atlas's --osm-solar where `earthpv atlas` did not record it: Pakistan's page counts the
# 25 October 2026 pull (31,835 features, 31,186 after the atlas's dissolve), as its leads do.
ATLAS_OSM_SOLAR = {"pakistan": "data/labels/pakistan_overpass_solar.parquet"}
MIN_DISTANCE_M = 100.0
ROW_GROUP = 16_384
ZSTD_LEVEL = 19  # 22 is no smaller; reading is as fast either way

COLUMNS = ["source", "id", "technology", "placement", "area_m2",
           # model rows
           "confidence", "rank_score", "building_overlap_frac", "building_dist_m",
           "geometry_source", "osm_matched_id", "osm_match_dist_m", "osm_within_100m",
           "oversize", "review_verdict",
           # osm rows
           "osm_timestamp", "screen_credit", "csp_mw", "name"]


def _round_coords(geoms: gpd.GeoSeries, decimals: int) -> gpd.GeoSeries:
    return gpd.GeoSeries(shapely.transform(geoms.to_numpy(), lambda c: np.round(c, decimals)),
                         index=geoms.index, crs=geoms.crs)


def review_verdicts(aoi: str, cands: gpd.GeoDataFrame) -> pd.Series:
    """`pv` / `not_pv` / `bright_roof` per candidate where the country's calibration table
    records a review (`oversize_review`, `lead_review`), matched by `candidate_index` (a
    label of the candidate file's own index, which the solar thermal filter left with gaps)
    and checked by area, as `density.load_oversize_admission` does. Unsure and blank are
    None, and so is a verdict on a candidate the file no longer holds (a `pv` one is an
    error, as in density)."""
    out = pd.Series(None, index=cands.index, dtype=object)
    table = ROOT / "configs" / "calibration" / f"{aoi}_candidate_precision.yaml"
    if not table.exists():
        return out
    t = yaml.safe_load(table.read_text()) or {}
    for key in ("oversize_review", "lead_review"):
        block = t.get(key) or {}
        if not block.get("review_csv"):
            continue
        r = pd.read_csv(ROOT / block["review_csv"])
        r = r[r["verdict"].isin(["pv", "not_pv"])]
        known = r["candidate_index"].isin(cands.index)
        if not known[r["verdict"] == "pv"].all():
            raise ValueError(f"{aoi}: {block['review_csv']} judges solar a candidate the "
                             "file lacks (another candidate file?)")
        r = r[known]
        got = cands.loc[r["candidate_index"], "area_m2"].to_numpy(float)
        if not np.allclose(got, r["area_m2"].to_numpy(float), rtol=1e-6, atol=1.0):
            raise ValueError(f"{aoi}: {block['review_csv']} describes another candidate file")
        flag = r["flag"].fillna("") if "flag" in r else pd.Series("", index=r.index)
        out.loc[r["candidate_index"].to_numpy()] = np.where(flag.eq("bright_roof"),
                                                            "bright_roof", r["verdict"])
        print(f"  {key}: {len(r):,} verdicts ({int((r['verdict'] == 'pv').sum()):,} solar; "
              f"{int((~known).sum())} on candidates no longer in the file)")
    return out


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def atlas_osm_solar(aoi: str) -> Path:
    """The OSM file the published atlas counted (see the module docstring)."""
    pred = ROOT / {**SOURCES, **POLY_SOURCES}.get(aoi, {}).get("pred", f"data/predictions/{aoi}")
    rec = pred / "density" / "evidence_atlas_inputs.json"
    if rec.exists():
        d = json.loads(rec.read_text())
        osm = (d.get("inputs") or d).get("osm_solar")
        if osm:
            return Path(osm) if Path(osm).is_absolute() else ROOT / osm
    return ROOT / ATLAS_OSM_SOLAR.get(aoi, f"data/labels/{aoi}_national_osm_solar.parquet")


def model_rows(aoi: str, src: dict) -> tuple[gpd.GeoDataFrame, dict]:
    pred = ROOT / src.get("pred", f"data/predictions/{aoi}")
    cands = gpd.read_parquet(pred / "candidates.parquet")
    cands["review_verdict"] = review_verdicts(aoi, cands)
    # export.run_export's ranking and numbering, call for call (as release_leads.build).
    sort_col = "rank_score" if "rank_score" in cands.columns else "confidence"
    cands = cands.sort_values(sort_col, ascending=False).reset_index(drop=True)
    cands["id"] = [f"{aoi}-pv-{i:06d}" for i in range(len(cands))]

    paths = [ROOT / p for p in src.get("osm", [f"data/labels/{aoi}_overpass_solar.parquet"])]
    frames = [gpd.read_parquet(p) for p in paths]
    mapped = gpd.GeoDataFrame(pd.concat([f[["geometry"]] for f in frames], ignore_index=True),
                              geometry="geometry", crs="EPSG:4326")
    mapped = mapped[mapped.geometry.notna() & ~mapped.geometry.is_empty]
    cands["osm_within_100m"] = ~new_lead_mask(cands, mapped, MIN_DISTANCE_M)

    regions = atlas._page_regions(aoi, pred / "density" / "regions.geoparquet")
    page = ROOT / PAGES.get(aoi, f"results/{aoi}_pv_evidence_atlas.html")
    shown = sorted(p["name"] for p in _page_data(page).get("provinces", []))
    if shown != sorted(map(str, regions.name)):
        raise ValueError(f"{aoi}: {pred} does not hold the regions {page.name} draws")
    inside = cands.geometry.representative_point().within(regions.geometry.union_all())
    n_all = len(cands)
    cands = cands[inside.to_numpy()].copy()
    cands["source"], cands["technology"] = "model", "pv"
    if "oversize" not in cands:
        cands["oversize"] = cands["area_m2"] > MAX_CANDIDATE_M2
    stats = {"n_candidates": n_all, "n_outside": int(n_all - len(cands)),
             "pred": _rel(pred), "raw_osm": [_rel(p) for p in paths],
             "raw_osm_as_of": _osm_as_of(frames, paths)}
    return cands, stats


def osm_rows(aoi: str, osm_solar: Path) -> tuple[gpd.GeoDataFrame, dict]:
    osm = gpd.read_parquet(osm_solar)
    osm = osm[osm.geometry.notna() & ~osm.geometry.is_empty].copy()
    osm["source"], osm["technology"] = "osm", "pv"
    osm["placement"] = osm["placement"].replace({"small": "rooftop"})
    stats = {"osm_solar": _rel(osm_solar), "n_pv": len(osm),
             "osm_as_of": _osm_as_of([osm], [osm_solar])}
    csp_path = ROOT / "data" / "labels" / f"{aoi}_csp_plants.parquet"
    if csp_path.exists():
        csp = gpd.read_parquet(csp_path)
        csp = csp.assign(source="osm", technology="csp", placement="ground",
                         csp_mw=csp["mw"].astype(float))
        stats["n_csp"], stats["csp_mw"] = len(csp), round(float(csp["mw"].sum()), 1)
        osm = pd.concat([osm, csp], ignore_index=True)
    return gpd.GeoDataFrame(osm, geometry="geometry", crs="EPSG:4326"), stats


def build(aoi: str, out: Path, osm_solar: Path) -> dict:
    model, mstats = model_rows(aoi, {**SOURCES, **POLY_SOURCES}.get(aoi, {}))
    osm, ostats = osm_rows(aoi, osm_solar)
    gdf = gpd.GeoDataFrame(pd.concat([model, osm], ignore_index=True), geometry="geometry",
                           crs="EPSG:4326")
    for c in COLUMNS:
        if c not in gdf:
            gdf[c] = None
    gdf = gdf[COLUMNS + ["geometry"]]
    for c in ("confidence", "rank_score", "building_overlap_frac", "screen_credit"):
        gdf[c] = gdf[c].astype(float).round(4)
    for c in ("area_m2", "building_dist_m", "osm_match_dist_m", "csp_mw"):
        gdf[c] = gdf[c].astype(float).round(1)
    for c in ("osm_within_100m", "oversize"):
        gdf[c] = gdf[c].astype("boolean")
    gdf["osm_timestamp"] = pd.to_datetime(gdf["osm_timestamp"], utc=True, errors="coerce")
    for c in ("source", "technology", "placement", "geometry_source", "review_verdict"):
        gdf[c] = gdf[c].astype("category")
    is_model = (gdf["source"] == "model").to_numpy()
    geoms = gdf.geometry.copy()
    geoms[is_model] = _round_coords(geoms[is_model], 6)
    geoms[~is_model] = _round_coords(geoms[~is_model], 7)
    # Rounding can pinch a valid outline into a self-touching ring (India: 37 of 103,619):
    # those keep their coordinates unrounded, so no row is less valid than its source.
    broke = (~geoms.is_valid & gdf.geometry.is_valid).to_numpy()
    geoms[broke] = gdf.geometry[broke]
    gdf["geometry"] = geoms
    # Spatial order: neighbours share row groups, so a bbox filter reads few of them and
    # zstd sees similar coordinates side by side.
    gdf = gdf.iloc[np.argsort(gdf.geometry.hilbert_distance(), kind="stable")].reset_index(drop=True)

    path = out / f"{aoi}_pv_polygons.parquet"
    path.unlink(missing_ok=True)
    gdf.to_parquet(path, compression="zstd", compression_level=ZSTD_LEVEL,
                   row_group_size=ROW_GROUP, write_covering_bbox=True, schema_version="1.1.0")
    back = gpd.read_parquet(path)
    # Every row is as valid as its source: an outline already invalid there (an OpenStreetMap
    # polygon mapped self-intersecting, Pakistan: a few) is kept as it is, never repaired.
    valid = gdf.geometry.is_valid.to_numpy()
    assert len(back) == len(gdf) and (back.geometry.is_valid.to_numpy() == valid).all(), \
        "invalid geometry written"
    if broke.any():
        print(f"  {int(broke.sum())} outlines kept unrounded (rounding made them invalid)")
    if not valid.all():
        bad = gdf.loc[~valid, "source"].value_counts().to_dict()
        print(f"  {int((~valid).sum())} outlines invalid in their source, kept as they are: {bad}")
    n_model, n_osm = int((gdf["source"] == "model").sum()), int((gdf["source"] == "osm").sum())
    print(f"  {aoi}: {n_model:,} model outlines ({mstats['n_outside']:,} outside the page's "
          f"regions left out) + {n_osm:,} OSM features ({ostats.get('n_csp', 0)} CSP) -> "
          f"{path.stat().st_size / 1e6:.1f} MB")
    m = gdf[gdf["source"] == "model"]
    return {
        "file": path.name,
        "url": f"https://github.com/{REPO}/releases/download/{TAG}/{path.name}",
        "size_bytes": path.stat().st_size,
        "format": "GeoParquet 1.1, zstd",
        "made": dt.date.today().isoformat(),
        "n_model": n_model,
        "n_model_leads": int((~m["osm_within_100m"].astype(bool)).sum()),
        "n_model_reviewed": int(m["review_verdict"].notna().sum()),
        "n_osm": n_osm,
        "n_osm_csp": int(ostats.get("n_csp", 0)),
        "osm_as_of": ostats["osm_as_of"],
        "min_distance_m": int(MIN_DISTANCE_M),
        "sources": {**mstats, **{k: v for k, v in ostats.items() if k in ("osm_solar",)}},
    }


README = """# EarthPV solar polygons, {date}

One GeoParquet file per country holding every solar outline behind its evidence atlas
(https://open-energy-transition.github.io/earthpv/atlas/): the outlines the EarthPV
segmentation model drew in Sentinel-2 imagery, and the solar installations in
OpenStreetMap the atlas counts. `source` tells them apart.

**Model outlines are not data.** Each is drawn from 10 m pixels, typically about twice the
area of the panels it found, and the model is recall-first: some are bright roofs,
greenhouses, dark fields or rock. The atlas prices them by measured precision and recall
per size bin rather than counting each outline whole. Nothing here should be imported into
OpenStreetMap automatically; to map from them, use the lead files
(https://github.com/{repo}/releases/tag/pv-new-leads-2026-11-02) and the mapping guide
(https://open-energy-transition.github.io/earthpv/contribute/).

| country | model outlines | of them leads (no OSM solar within {dist} m) | judged by a person | OpenStreetMap features | of them CSP plants | OpenStreetMap as of | size |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
{rows}

Columns:

| column | rows | meaning |
| --- | --- | --- |
| source | all | `model` (a segmentation outline) or `osm` (an OpenStreetMap feature) |
| id | all | `<country>-pv-NNNNNN` for a model outline, its id in the country's lead and MapRoulette files (France's audited lead release numbers its leads by département instead); `osm-way/...` or `osm-relation/...` for OpenStreetMap |
| technology | all | `pv`, or `csp` for a concentrating solar power plant (counted at its electric rating, never as PV) |
| placement | all | model: `rooftop`, `ground_adjacent` or `no_building`, from VIDA building footprints; osm: `rooftop`, `ground` or `unknown` |
| area_m2 | all | geodesic area of the outline (0 for an OpenStreetMap node, which is a point) |
| confidence | model | peak model probability inside the outline |
| rank_score | model | confidence times a building prior; the lead files' sort key |
| building_overlap_frac, building_dist_m | model | the building join behind placement |
| geometry_source | model | `osm` where the outline was replaced by the mapped installation it matched (that outline is also an `osm` row), else `model` |
| osm_matched_id, osm_match_dist_m | model | the OpenStreetMap feature it was matched to, and how far |
| osm_within_100m | model | an OpenStreetMap solar feature lies within {dist} m; false is a mapping lead |
| oversize | model | above {blob_m2} m2, the merge cap: the atlas counts it only once it is mapped or a person judged it solar |
| review_verdict | model | `pv`, `not_pv` or `bright_roof` (not PV, a very bright roof): a person's verdict on the Sentinel-2 imagery the model saw and Esri imagery, where one was given |
| osm_timestamp | osm | last edit of the feature |
| screen_credit | osm | share of the outline the atlas credits: below 1 only for outlines above 5 km2 that the model imaged but mostly did not see as panels |
| csp_mw, name | osm (csp) | the plant's electric rating in MW and its name |

Model outlines are those of the run behind the published atlas whose representative point
lies inside the regions the atlas draws. OpenStreetMap rows are the atlas's own input:
power=generator and power=plant solar features clipped to the national border, solar
water heating and concentrating solar mirror fields taken out, kept as mapped (the atlas
merges overlapping outlines before counting them, so its feature count is a little lower).

Coordinates are WGS84. Model outlines are rounded to 6 decimals (about 10 cm, against a
10 m pixel); OpenStreetMap features keep their own 7. The file is sorted along a Hilbert
curve and carries a GeoParquet 1.1 `bbox` column, so area queries read only part of it.
Examples:

    # Python
    import geopandas as gpd
    gdf = gpd.read_parquet("india_pv_polygons.parquet", bbox=(72.0, 18.8, 73.2, 19.4))

    -- DuckDB
    INSTALL spatial; LOAD spatial;
    SELECT source, placement, count(*), sum(area_m2) FROM 'india_pv_polygons.parquet'
    GROUP BY ALL;

QGIS 3.36 and later opens it directly (Layer > Add Vector Layer).

Licence: derived from OpenStreetMap (ODbL 1.0, (c) OpenStreetMap contributors) and contains
modified Copernicus Sentinel-2 data; building footprints from VIDA (Google and Microsoft
Open Buildings). Released under the ODbL like every EarthPV data output.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", action="append", required=True)
    ap.add_argument("--out", type=Path, default=RELEASE_DIR,
                    help=f"directory holding every country's release assets (default {RELEASE_DIR})")
    ap.add_argument("--osm-solar", type=Path,
                    help="the atlas's --osm-solar file (default: the one the atlas recorded, "
                         "see the module docstring; one --aoi only)")
    ap.add_argument("--upload", action="store_true", help=f"create {TAG} and upload the assets")
    args = ap.parse_args()

    os.chdir(ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.osm_solar and len(args.aoi) > 1:
        ap.error("--osm-solar names one country's file")
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"aois": {}}
    for aoi in args.aoi:
        osm = ROOT / args.osm_solar if args.osm_solar else atlas_osm_solar(aoi)
        print(f"  {aoi}: OSM rows from {_rel(osm)}")
        manifest["aois"][aoi] = build(aoi, args.out, osm)
    manifest["aois"] = dict(sorted(manifest["aois"].items()))
    manifest["release"] = f"https://github.com/{REPO}/releases/tag/{TAG}"

    entries = manifest["aois"]
    rows = "\n".join(
        f"| {country_name(a)} | {e['n_model']:,} | {e['n_model_leads']:,} | "
        f"{e['n_model_reviewed']:,} | {e['n_osm']:,} | {e['n_osm_csp']:,} | {e['osm_as_of']} | "
        f"{e['size_bytes'] / 1e6:.1f} MB |" for a, e in entries.items())
    (args.out / "README.md").write_text(README.format(
        date=dt.date.today().isoformat(), rows=rows, repo=REPO, dist=int(MIN_DISTANCE_M),
        blob_m2=f"{MAX_CANDIDATE_M2:,.0f}"))
    files = [args.out / e["file"] for e in entries.values() if (args.out / e["file"]).exists()]
    files.append(args.out / "README.md")
    sums = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in files]
    (args.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)} and {len(files) + 1} assets in {args.out}")

    if args.upload:
        exists = subprocess.run(["gh", "release", "view", TAG, "-R", REPO],
                                capture_output=True).returncode == 0
        # Into an existing release only what changed: these countries' files, and the README
        # and checksums that list every country (also the release's notes).
        sent = ([args.out / entries[a]["file"] for a in args.aoi] + [args.out / "README.md"]
                if exists else files)
        assets = [str(f) for f in sent] + [str(args.out / "SHA256SUMS")]
        if exists:
            subprocess.run(["gh", "release", "upload", TAG, "-R", REPO, "--clobber", *assets],
                           check=True)
            cmd = ["gh", "release", "edit", TAG, "-R", REPO,
                   "--notes-file", str(args.out / "README.md")]
        else:
            cmd = ["gh", "release", "create", TAG, "-R", REPO, "--latest=false",
                   "--title", f"PV polygons per country: model outlines and OpenStreetMap "
                              f"({dt.date.today().isoformat()})",
                   "--notes-file", str(args.out / "README.md"), *assets]
        subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
