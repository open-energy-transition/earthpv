"""France: solar arrays >= 400 m2 that earthpv detects and OpenStreetMap does not have yet,
written as mapping leads for JOSM, iD and MapRoulette.

    python scripts/build_france_osm_leads.py \
        --osm data/labels/france_overpass_solar.parquet \
        --osm data/labels/france_national_osm_solar.parquet \
        --osm-json data/labels/france_osm_20261022/newer_maps.mail.ru.json

A lead is a v5 segmentation candidate (`data/predictions_v5/france/candidates.parquet`,
Sentinel-2 May-September 2024) that is

1. at least `--min-area` m2,
2. not itself an OSM outline (`geometry_source != "osm"`, i.e. `replace_with_osm_geometry`
   did not match it),
3. inside metropolitan France. The candidate file covers every composed cell (6,858),
   including the 837 the density stage drops as Spanish, Belgian, Swiss, German, Italian
   or sea; 4,968 of the 34,042 unclipped leads sit there, almost all `no_building`
   because VIDA was only loaded for FRA,
4. more than `--min-distance-m` (default 100, the project convention, `export.
   new_lead_mask`) from every OSM solar feature in the union of `--osm` and `--osm-json`.
   Pass an older full pull plus a `newer:` diff query to get a current reference without
   pulling the whole country again.

Candidates over `postprocess.MAX_CANDIDATE_M2` (100,000 m2) are written to a separate
file: `polygonize_chips` merges touching pixels without an upper bound, so most are
merged false-positive sheets, and an outline that large is no use as a mapping hint.

**Priority tiers come from a visual audit, not from the model's calibration table.**
France's `p_real` is the OSM-mapped fraction (no glint sample, `p_unmapped` = 0), which
says nothing about an unmapped candidate by construction. So 72 leads, six per placement
x confidence (> 0.99) x size (>= 5,000 m2) stratum, were checked against IGN BD ORTHO
(results/france_osm_leads/audit_ign_sample.csv), and the tiers group strata with similar
hit rates. Two independent reads agree on the ordering: the share of leads overlapping an
OpenPVMapper polygon (sub-metre IGN detections, rooftop only) falls the same way in every
stratum. Six per stratum is a coarse instrument; the tiers are an ordering, and the
README quotes their hit rates with that caveat.

    1  confidence > 0.99, or >= 5,000 m2 on or next to a building   audit 33-38 of 48
    2  the rest on or next to a building                             audit  5 of 12
    3  the rest with no building nearby                              audit  1 of 12

`--glint-summary` merges a `glint_pose_survey.py analyze` summary run on these leads
(`src_id` = `lead_id`): a validated glint (two spike dates explained by one panel plane)
is physical evidence of glass, and carries the fitted tilt and azimuth.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import xml.sax.saxutils as su
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from earthpv.export import new_lead_mask  # noqa: E402
from earthpv.postprocess import MAX_CANDIDATE_M2  # noqa: E402

log = logging.getLogger("fr-leads")

DO_NOT_UPLOAD = "earthpv detection, not OSM data: map what the imagery shows, never upload this"
TIER_NOTE = {
    1: "likely real (visual audit 33-38 of 48)",
    2: "possible (visual audit 5 of 12)",
    3: "unlikely (visual audit 1 of 12)",
}
HINT = {
    "rooftop": "panels on this roof",
    "ground_adjacent": "usually a farm/industrial roof missing from the footprints, or carports",
    "no_building": "if real, usually a new barn; else a dark field, rock, water or dark roof",
}
INSTRUCTION = (
    "Possible solar array of about {area:.0f} m2 seen by Sentinel-2 in summer 2024 "
    "({placement}, priority {priority}). Check recent imagery (IGN BD ORTHO). If panels are "
    "there, map them: rooftop or carport -> power=generator + generator:source=solar + "
    "generator:method=photovoltaic + generator:type=solar_photovoltaic_panel + location=roof; "
    "solar park -> power=plant + plant:source=solar + plant:method=photovoltaic around the "
    "fenced site. Typical false alarms: artificial turf, dark slate or membrane roofs, "
    "ploughed fields, scree, water, substations."
)

MAPCSS = """\
/* earthpv France PV leads. JOSM: Preferences -> Map Paint Styles -> + -> this file. */
way[feature_type=earthpv_pv_lead] { color: #b0b0b0; width: 2; fill-color: #b0b0b0; fill-opacity: 0.15; z-index: 100; }
way[feature_type=earthpv_pv_lead][priority=1] { color: #ff2fa0; width: 3; fill-color: #ff2fa0; fill-opacity: 0.20; }
way[feature_type=earthpv_pv_lead][priority=2] { color: #ff9500; width: 2; fill-color: #ff9500; fill-opacity: 0.15; }
way[feature_type=earthpv_pv_lead][glint_validated=yes] { dashes: 6,3; width: 4; }
way[feature_type=earthpv_pv_lead]::label { text: lead_id; font-size: 10; text-color: #ff2fa0; }
"""


def load_reference(parquets: list[Path], jsons: list[Path]) -> gpd.GeoDataFrame:
    from earthpv.overpass import solar_elements_to_gdf

    parts = []
    for p in parquets:
        g = gpd.read_parquet(p)[["geometry"]]
        log.info("reference %s: %d features", p, len(g))
        parts.append(g)
    for p in jsons:
        g = solar_elements_to_gdf(json.loads(Path(p).read_text())["elements"])[["geometry"]]
        log.info("reference %s: %d features", p, len(g))
        parts.append(g)
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry",
                            crs="EPSG:4326")


def priority(placement: pd.Series, confidence: pd.Series, area: pd.Series) -> np.ndarray:
    on_building = placement.isin(["rooftop", "ground_adjacent"]).to_numpy()
    tier1 = (confidence > 0.99).to_numpy() | (on_building & (area >= 5000).to_numpy())
    return np.where(tier1, 1, np.where(on_building, 2, 3))


def links(lon: float, lat: float, geom) -> dict:
    b = geom.bounds
    pad = 0.0015
    return {
        "id_editor": f"https://www.openstreetmap.org/edit?editor=id#map=19/{lat:.6f}/{lon:.6f}",
        "josm_load": (f"http://127.0.0.1:8111/load_and_zoom?left={b[0] - pad:.6f}"
                      f"&right={b[2] + pad:.6f}&top={b[3] + pad:.6f}&bottom={b[1] - pad:.6f}"),
        "geoportail": (f"https://www.geoportail.gouv.fr/carte?c={lon:.6f},{lat:.6f}&z=19"
                       "&l0=ORTHOIMAGERY.ORTHOPHOTOS::GEOPORTAIL:OGC:WMTS(1)&permalink=yes"),
    }


def write_osm(gdf: gpd.GeoDataFrame, path: Path, keys: list[str]) -> None:
    """A JOSM layer that refuses to upload: `upload="never"` on the root element is
    honoured by JOSM, which a GeoJSON opened as a data layer is not."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<osm version="0.6" generator="earthpv" upload="never">']
    nid = 0
    for wid, r in enumerate(gdf.itertuples(), start=1):
        polys = list(r.geometry.geoms) if r.geometry.geom_type == "MultiPolygon" else [r.geometry]
        for k, poly in enumerate(polys):
            refs = []
            for x, y in list(poly.exterior.coords)[:-1]:
                nid += 1
                out.append(f'  <node id="-{nid}" lat="{y:.7f}" lon="{x:.7f}"/>')
                refs.append(nid)
            out.append(f'  <way id="-{wid * 100 + k}">')
            out.extend(f'    <nd ref="-{n}"/>' for n in refs + refs[:1])
            for key in keys:
                v = getattr(r, key)
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    out.append(f'    <tag k="{key}" v={su.quoteattr(str(v))}/>')
            out.append("  </way>")
    out.append("</osm>")
    path.write_text("\n".join(out) + "\n")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--candidates", type=Path,
                    default=REPO / "data/predictions_v5/france/candidates.parquet")
    ap.add_argument("--osm", type=Path, action="append", default=[],
                    help="OSM solar parquet (repeatable); every feature counts as mapped")
    ap.add_argument("--osm-json", type=Path, action="append", default=[],
                    help="saved Overpass `out meta geom` response (repeatable)")
    ap.add_argument("--regions", type=Path, default=REPO / "data/labels/france_regions.parquet")
    ap.add_argument("--departements", type=Path,
                    default=REPO / "data/labels/france_districts.parquet")
    ap.add_argument("--glint-summary", type=Path, default=None)
    ap.add_argument("--min-area", type=float, default=400.0)
    ap.add_argument("--min-distance-m", type=float, default=100.0)
    ap.add_argument("--out-dir", type=Path, default=REPO / "results/france_osm_leads")
    a = ap.parse_args()
    if not a.osm and not a.osm_json:
        ap.error("pass at least one --osm or --osm-json reference")

    c = gpd.read_parquet(a.candidates)
    n0 = len(c)
    c = c[(c.area_m2 >= a.min_area) & (c.geometry_source != "osm")].reset_index(drop=True)
    log.info("%d candidates -> %d model outlines >= %.0f m2", n0, len(c), a.min_area)

    france = gpd.read_parquet(a.regions).to_crs("EPSG:4326").geometry.union_all()
    rep = c.geometry.representative_point()
    inside = shapely.contains_xy(france, rep.x.to_numpy(), rep.y.to_numpy())
    log.info("%d outside metropolitan France dropped", int((~inside).sum()))
    c = c[inside].reset_index(drop=True)

    ref = load_reference(a.osm, a.osm_json)
    new = new_lead_mask(c, ref, a.min_distance_m)
    log.info("%d of %d are > %.0f m from every OSM solar feature (%d reference features)",
             int(new.sum()), len(c), a.min_distance_m, len(ref))
    c = c[new].reset_index(drop=True)

    big = c[c.area_m2 > MAX_CANDIDATE_M2].reset_index(drop=True)
    c = c[c.area_m2 <= MAX_CANDIDATE_M2].reset_index(drop=True)

    dep = gpd.read_parquet(a.departements).to_crs("EPSG:4326")[["id", "geometry"]]

    def enrich(g: gpd.GeoDataFrame, prefix: str) -> gpd.GeoDataFrame:
        g = g.copy()
        g["priority"] = priority(g.placement, g.confidence, g.area_m2)
        g = g.sort_values(["priority", "confidence", "area_m2"],
                          ascending=[True, False, False]).reset_index(drop=True)
        g["lead_id"] = [f"{prefix}-{i:05d}" for i in range(1, len(g) + 1)]
        pts = g.geometry.representative_point()
        g["lon"], g["lat"] = pts.x.round(6), pts.y.round(6)
        j = gpd.sjoin(gpd.GeoDataFrame(geometry=pts, crs="EPSG:4326"), dep,
                      predicate="within", how="left")
        g["departement"] = j.groupby(level=0)["id"].first().str.replace("FR-DEP-", "").values
        return g

    c, big = enrich(c, "fr-lead"), enrich(big, "fr-oversize")

    glint_cols: list[str] = []
    if a.glint_summary is not None:
        s = pd.read_csv(a.glint_summary).set_index("src_id")
        c["glint_checked"] = c.lead_id.isin(s.index).map({True: "yes", False: "no"})
        c["glint_validated"] = c.lead_id.map(s["validated"]).map({True: "yes", False: "no"})
        c["glint_tilt_deg"] = c.lead_id.map(s.loc[s.validated, "fit_tilt"])
        c["glint_azimuth_deg"] = c.lead_id.map(s.loc[s.validated, "fit_az"])
        glint_cols = ["glint_checked", "glint_validated", "glint_tilt_deg", "glint_azimuth_deg"]
        log.info("glint: %d checked, %d validated",
                 int((c.glint_checked == "yes").sum()), int((c.glint_validated == "yes").sum()))

    def props(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        g = g.copy()
        g["feature_type"] = "earthpv_pv_lead"
        g["do_not_upload"] = DO_NOT_UPLOAD
        g["area_m2"] = g.area_m2.round(0).astype(int)
        g["confidence"] = g.confidence.round(3)
        g["building_overlap_frac"] = g.building_overlap_frac.round(2)
        g["tier_note"] = g.priority.map(TIER_NOTE)
        g["hint"] = g.placement.map(HINT)
        lk = pd.DataFrame([links(x, y, geom) for x, y, geom in zip(g.lon, g.lat, g.geometry)],
                          index=g.index)
        return pd.concat([g, lk], axis=1)

    keep = ["lead_id", "priority", "tier_note", "area_m2", "confidence", "placement",
            "building_overlap_frac", "departement", "lon", "lat", *glint_cols, "hint",
            "feature_type", "do_not_upload"]
    link_cols = ["id_editor", "josm_load", "geoportail"]
    c, big = props(c), props(big)
    full = gpd.GeoDataFrame(c[keep + link_cols + ["geometry"]], geometry="geometry",
                            crs="EPSG:4326")
    c = gpd.GeoDataFrame(c[keep + ["geometry"]], geometry="geometry", crs="EPSG:4326")
    big = gpd.GeoDataFrame(big[keep + ["geometry"]], geometry="geometry", crs="EPSG:4326")

    out = a.out_dir
    (out / "by_departement").mkdir(parents=True, exist_ok=True)
    gj = {"driver": "GeoJSON", "COORDINATE_PRECISION": 6}
    c.to_file(out / "france_pv_leads.geojson", **gj)
    big.to_file(out / "france_pv_leads_oversize.geojson", **gj)
    pd.DataFrame(full.drop(columns=["geometry", "feature_type", "do_not_upload"])).to_csv(
        out / "france_pv_leads.csv", index=False)
    (out / "france_pv_leads.mapcss").write_text(MAPCSS)
    osm_keys = [k for k in keep if k != "do_not_upload"]
    for d, g in c.groupby("departement", dropna=False):
        stem = f"dep_{d if isinstance(d, str) else 'unknown'}"
        g.to_file(out / "by_departement" / f"{stem}.geojson", **gj)
        write_osm(g, out / "by_departement" / f"{stem}.osm", osm_keys)
    # MapRoulette "line-by-line": one FeatureCollection per task, one file per tier.
    for tier, g in full.groupby("priority"):
        with (out / f"maproulette_priority{tier}.geojson").open("w") as f:
            for r in g.itertuples():
                p = {k: getattr(r, k) for k in keep + link_cols if k != "do_not_upload"}
                p = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in p.items()}
                p["instruction"] = INSTRUCTION.format(area=r.area_m2, placement=r.placement,
                                                      priority=tier)
                f.write(json.dumps({"type": "FeatureCollection", "features": [{
                    "type": "Feature", "geometry": shapely.geometry.mapping(r.geometry),
                    "properties": p}]}) + "\n")

    summary = (c.groupby(["priority", "placement"]).agg(n=("lead_id", "size"),
               area_km2=("area_m2", lambda s: round(s.sum() / 1e6, 2))).reset_index())
    summary.to_csv(out / "summary_by_priority.csv", index=False)
    print(summary.to_string(index=False))
    log.info("%d leads (+%d oversize) -> %s", len(c), len(big), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
