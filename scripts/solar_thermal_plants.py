#!/usr/bin/env python
"""Take solar thermal out of a country's PV inputs and write its CSP plant table.

The atlas counts concentrated solar power plants in Verified and Best at their electric
rating (`earthpv.solar_thermal`, owner 2026-11-07) and never as PV. For that, three things
must hold for every country, which this script makes true in one pass:

1. The OSM file the atlas counts (`--osm-solar`, the published page's own input) holds no
   solar thermal element: every element whose tags say thermal (`drop_solar_thermal`'s rule,
   with `solar_thermal_collector` and `KNOWN_THERMAL` since 2026-11-07) is dropped. The file
   is rewritten in place so every page's build command stays as it is. So is a feature lying
   at least half inside a CSP plant's outline whatever its tags: mappers often draw a plant's
   mirror rows with the photovoltaic preset (South Africa: 50 such rows, 13.4 km2, all seven
   plants), and a mirror field is never PV. Those go to `<aoi>_pv_tagged_inside_csp.csv` for
   fixing in OSM. The original is kept
   beside it (`<stem>_PRE_thermal_<date>.parquet`, or for a country's labels file the usual
   `<aoi>_solar_labels_with_thermal.parquet` plus the dropped-id record).
2. `data/labels/<aoi>_csp_plants.parquet` lists the country's CSP plants (border-clipped,
   parts of a larger plant dropped, MW by `solar_thermal.plant_capacity`). Written even when
   empty, which is how a page tells "checked, none" from "not checked".
3. No model candidate stands on a solar thermal outline (`--candidates`): a candidate at least
   half inside one is removed (same rule as `drop_solar_thermal.py --candidates`), so a
   mirror field is not counted again as ground-mount PV. A changed candidate file means
   `density` must run again before the atlas.

Tags come from one Overpass area scan for thermal tags (`--by-id` looks up every element of
the inputs instead; the one that works at India's size), merged with the tags the country's
earlier `drop_solar_thermal.py` run recorded for what it dropped. Geometry comes from the
inputs before filtering, the labels and their backup, and any `--geom-source`.

Reports go to `results/solar_thermal/<aoi>_*`: the plants, what was left out and why, and
thermal plants with no electric output (heating plants, or a CSP plant missing its tag: look
at those before trusting the table).

    python scripts/solar_thermal_plants.py --aoi south_africa \\
        --osm-solar data/labels/south_africa_national_osm_solar.parquet \\
        --candidates data/predictions/south_africa/candidates.parquet [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from drop_solar_thermal import (  # noqa: E402
    KNOWN_THERMAL, _classify, thermal_ids, thermal_ids_by_id,
)
from earthpv import solar_thermal as st  # noqa: E402
from earthpv.config import Settings  # noqa: E402

log = logging.getLogger("solar_thermal_plants")
TODAY = dt.date.today().strftime("%Y%m%d")


def _read(p: Path) -> gpd.GeoDataFrame:
    g = gpd.read_parquet(p)
    return g.to_crs("EPSG:4326") if g.crs is not None and g.crs.to_epsg() != 4326 else g


def _border(aoi: str):
    """The country's ADM1 union, or a state or province AOI's own polygon
    (`density.aoi_border`), so California's table does not take Nevada's plants."""
    from earthpv.density import aoi_border

    settings = Settings.load()
    return aoi_border(aoi, settings.aois[aoi], settings)


_HSTORE = None


def thermal_ids_pbf(pbf: Path) -> dict[str, dict]:
    """Thermal elements from a Geofabrik extract, read with GDAL's OSM driver (no osmium
    here), classified by the same rule as an Overpass answer. A closed `power` way is a line
    to the driver (power is not in its polygon list), so lines are read too."""
    import re
    import pyogrio

    global _HSTORE
    _HSTORE = _HSTORE or re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')
    pyogrio.set_gdal_config_options({"CPL_TMPDIR": str(Path(pbf).resolve().parent)})
    where = ("other_tags LIKE '%\"generator:source\"=>\"solar\"%' "
             "OR other_tags LIKE '%\"plant:source\"=>\"solar\"%'")
    elements = []
    for layer in ("points", "lines", "multipolygons"):
        df = pyogrio.read_dataframe(pbf, layer=layer, where=where, read_geometry=False)
        log.info("%s: %d solar elements in layer %s", pbf.name, len(df), layer)
        for r in df.itertuples(index=False):
            tags = dict(_HSTORE.findall(r.other_tags or ""))
            if getattr(r, "name", None):
                tags["name"] = r.name
            if layer == "multipolygons":
                way = getattr(r, "osm_way_id", None)
                typ, oid = ("way", way) if way not in (None, "") and not pd.isna(way) else ("relation", r.osm_id)
            else:
                typ, oid = ("node" if layer == "points" else "way"), r.osm_id
            elements.append({"type": typ, "id": int(float(oid)), "tags": tags})
    return _classify(elements)


def collect_tags(aoi: str, ids: set[str], labels_dir: Path, by_id: bool,
                 record_only: bool = False, cache: Path | None = None,
                 tile_deg: float = 5.0, pbf: Path | None = None) -> dict[str, dict]:
    tags: dict[str, dict] = {}
    record = labels_dir / f"{aoi}_solar_thermal_dropped.json"
    if record.exists():
        tags.update(json.loads(record.read_text()))
    if record_only:
        fresh = {}
    elif cache is not None and cache.exists():
        fresh = json.loads(cache.read_text())
        log.info("%s: thermal tags from %s", aoi, cache)
    else:
        fresh = (thermal_ids_pbf(pbf) if pbf is not None
                 else thermal_ids_by_id(sorted(ids)) if by_id
                 else thermal_ids(Settings.load().aois[aoi]["bbox"], tile_deg=tile_deg))
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(fresh, ensure_ascii=False))
    tags.update(fresh)
    for i, entry in KNOWN_THERMAL.items():
        if i in ids:
            tags[i] = {k: v for k, v in entry.items() if k != "note"}
    log.info("%s: %d thermal elements (%d from this scan, %d recorded earlier)",
             aoi, len(tags), len(fresh), len(tags) - len(fresh))
    return tags


def inside_csp(g: gpd.GeoDataFrame, table: gpd.GeoDataFrame) -> np.ndarray:
    """Rows of `g` at least half inside a CSP plant of `table`."""
    if table.empty or g.empty:
        return np.zeros(len(g), bool)
    utm = table.estimate_utm_crs()
    zone = table.to_crs(utm).geometry.buffer(0).union_all()
    gg = (g.to_crs(utm) if g.crs is not None else g.set_crs("EPSG:4326").to_crs(utm)).geometry
    with np.errstate(invalid="ignore", divide="ignore"):
        return (gg.intersection(zone).area / gg.area).fillna(0.0).to_numpy() >= 0.5


def filter_file(path: Path, aoi: str, tags: dict[str, dict], table: gpd.GeoDataFrame,
                dry: bool, out_dir: Path) -> dict:
    thermal = set(tags)
    g = gpd.read_parquet(path)
    by_tag = g["id"].isin(thermal).to_numpy()
    by_place = inside_csp(g, table) & ~by_tag
    hit = by_tag | by_place
    if by_place.any():
        pv = g.loc[by_place, ["id", "area_m2"]].copy()
        rp = g.loc[by_place].geometry.representative_point()
        pv["lon"], pv["lat"] = rp.x.round(5), rp.y.round(5)
        pv.to_csv(out_dir / f"{aoi}_pv_tagged_inside_csp__{path.stem}.csv", index=False)
        log.info("%s: %d features (%.3f km2) lie inside CSP plants without a thermal tag",
                 path.name, by_place.sum(), float(g.loc[by_place, "area_m2"].sum()) / 1e6)
    area = float(g.loc[hit, "area_m2"].fillna(0).sum()) if "area_m2" in g else float("nan")
    rep = {"file": str(path), "n": int(len(g)), "dropped": int(hit.sum()), "dropped_km2": area / 1e6,
           "dropped_inside_csp": int(by_place.sum())}
    log.info("%s: %d of %d features are solar thermal (%.3f km2)", path.name, hit.sum(), len(g), area / 1e6)
    if dry or not hit.any():
        return rep
    if path.name == f"{aoi}_overpass_solar.parquet":
        backup = path.with_name(f"{aoi}_solar_labels_with_thermal.parquet")
        rec = path.with_name(f"{aoi}_solar_thermal_dropped.json")
        prev = json.loads(rec.read_text()) if rec.exists() else {}
        prev.update({i: tags.get(i, {"reason": "inside a CSP plant"}) for i in g.loc[hit, "id"]})
        rec.write_text(json.dumps(prev, indent=1, ensure_ascii=False))
    else:
        backup = path.with_name(f"{path.stem}_PRE_thermal_{TODAY}.parquet")
    if not backup.exists():
        g.to_parquet(backup)
    g[~hit].to_parquet(path)
    rep["backup"] = str(backup)
    return rep


def filter_candidates(cpath: Path, polys: gpd.GeoDataFrame, aoi: str, dry: bool) -> dict:
    cands = gpd.read_parquet(cpath)
    if polys.empty or cands.empty:
        return {"file": str(cpath), "removed": 0}
    crs = cands.estimate_utm_crs()
    zone = polys.to_crs(crs).geometry.buffer(0).union_all()
    cm = cands.to_crs(crs)
    frac = cm.geometry.intersection(zone).area / cm.geometry.area.clip(lower=1e-9)
    hit = (frac >= 0.5).to_numpy()
    rep = {"file": str(cpath), "n": int(len(cands)), "removed": int(hit.sum()),
           "removed_km2": float(cands.loc[hit, "area_m2"].sum()) / 1e6}
    log.info("%s: %d of %d candidates lie >= 50%% inside solar thermal outlines (%.3f km2)",
             cpath, hit.sum(), len(cands), rep["removed_km2"])
    # A removed candidate a person judged solar would make `density` refuse the review.
    from earthpv import capacity_calibration as cc
    tp = cc.default_table_path(aoi)
    block = (cc.load_table(tp) or {}).get("oversize_review") if tp.exists() else None
    if block and hit.any():
        rev = pd.read_csv(block["review_csv"])
        pv = rev[(rev["verdict"].fillna("") == "pv") & rev["candidate_index"].isin(cands.index[hit])]
        rep["judged_pv_removed"] = pv["candidate_index"].tolist()
        if len(pv):
            log.warning("%s: %d removed candidates carry a `pv` verdict in %s: %s -- the owner "
                        "judged a solar thermal outline as solar; decide before running density",
                        aoi, len(pv), block["review_csv"], pv["candidate_index"].tolist())
    if dry or not hit.any():
        return rep
    keep = cpath.with_name("candidates.with_thermal.parquet")
    if not keep.exists():
        cands.to_parquet(keep)
    else:  # an earlier thermal filter kept the original; keep this state too
        cands.to_parquet(cpath.with_name(f"candidates_PRE_thermal_{TODAY}.parquet"))
    cands[~hit].to_parquet(cpath)
    rep["written"] = True
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--osm-solar", type=Path, action="append", required=True,
                    help="an OSM file the atlas counts (repeatable)")
    ap.add_argument("--geom-source", type=Path, action="append", default=[],
                    help="extra files to take plant outlines from (not filtered)")
    ap.add_argument("--candidates", type=Path, action="append", default=[])
    ap.add_argument("--labels-dir", type=Path, default=REPO / "data/labels")
    ap.add_argument("--by-id", action="store_true")
    ap.add_argument("--pbf", type=Path, help="read tags from this Geofabrik extract, not Overpass")
    ap.add_argument("--tile-deg", type=float, default=5.0,
                    help="area scan tile size; smaller tiles are lighter queries for a busy server")
    ap.add_argument("--no-clip", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-cache", action="store_true",
                    help="scan Overpass again even when this scan's tags are cached in --out-dir")
    ap.add_argument("--record-only", action="store_true",
                    help="no Overpass: only the tags the earlier drop_solar_thermal run recorded (tests)")
    ap.add_argument("--out-dir", type=Path, default=REPO / "results/solar_thermal")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    aoi, L = a.aoi, a.labels_dir

    pool_paths = list(dict.fromkeys(
        [*a.osm_solar, *a.geom_source,
         L / f"{aoi}_overpass_solar.parquet", L / f"{aoi}_solar_labels_with_thermal.parquet"]))
    pool = [(_read(p), p) for p in pool_paths if p.exists()]
    ids = set().union(*[set(g["id"]) for g, _ in pool]) if pool else set()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    mode = "pbf" if a.pbf else "byid" if a.by_id else "scan"
    cache = None if a.no_cache else a.out_dir / f"{aoi}_thermal_tags_{mode}.json"
    tags = collect_tags(aoi, ids, L, a.by_id, a.record_only, cache, a.tile_deg, a.pbf)
    thermal = set(tags)

    # Outlines of every thermal element we hold, before anything is filtered.
    frames = [g[g["id"].isin(thermal)][["id", "geometry"]] for g, _ in pool]
    polys = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    polys = polys[polys.geom_type.isin(["Polygon", "MultiPolygon"])].drop_duplicates("id")

    csp_ids = [i for i, t in tags.items() if st.is_csp_plant(t)]
    heat_ids = [i for i, t in tags.items()
                if str(t.get("power", "")) == "plant" and i not in csp_ids
                and "photovoltaic" not in str(t.get("plant:method", "")).lower()]
    cand = polys[polys["id"].isin(csp_ids)].copy()
    missing = sorted(set(csp_ids) - set(cand["id"]))
    cand["name"] = [tags[i].get("name:en") or tags[i].get("name") for i in cand["id"]]
    cand["mw_tag_raw"] = [tags[i].get("plant:output:electricity") for i in cand["id"]]
    clipped_out = []
    if not a.no_clip and len(cand):
        border = _border(aoi)
        if border is not None:
            import shapely
            rp = cand.geometry.representative_point()
            inside = shapely.contains_xy(border, rp.x.values, rp.y.values)
            clipped_out = cand.loc[~inside, "id"].tolist()
            cand = cand[inside]
    table, left = st.build_table(cand)

    reports = {"aoi": aoi, "made": dt.date.today().isoformat(), "tags_from": mode,
               "pbf": str(a.pbf) if a.pbf else None,
               "n_thermal_elements": len(thermal), "files": [], "candidates": []}
    for p in a.osm_solar:
        reports["files"].append(filter_file(p, aoi, tags, table, a.dry_run, a.out_dir))
    labels = L / f"{aoi}_overpass_solar.parquet"
    if labels.exists() and labels.resolve() not in {q.resolve() for q in a.osm_solar}:
        reports["files"].append(filter_file(labels, aoi, tags, table, a.dry_run, a.out_dir))
    for c in a.candidates:
        reports["candidates"].append(filter_candidates(c, polys, aoi, a.dry_run))

    t = table.copy()
    rp = t.geometry.representative_point() if len(t) else gpd.GeoSeries(dtype="geometry")
    t["lon"], t["lat"] = (rp.x.round(5), rp.y.round(5)) if len(t) else ([], [])
    t.drop(columns="geometry").to_csv(a.out_dir / f"{aoi}_csp_plants.csv", index=False)
    if len(left):
        left.to_csv(a.out_dir / f"{aoi}_csp_left_out.csv", index=False)
    heat = pd.DataFrame([{"id": i, **tags[i]} for i in heat_ids])
    if len(heat):
        heat.to_csv(a.out_dir / f"{aoi}_thermal_plants_without_electric_output.csv", index=False)
    reports.update({
        "n_csp_plants": int(len(table)), "csp_mw": round(float(table["mw"].sum()), 1) if len(table) else 0.0,
        "csp_mw_by_source": table.groupby("mw_source")["mw"].sum().round(1).to_dict() if len(table) else {},
        "csp_without_outline": missing, "csp_outside_border": clipped_out,
        "n_thermal_plants_without_electric_output": len(heat_ids),
        "n_left_out": int(len(left)),
    })
    if not a.dry_run:
        table.to_parquet(st.table_path(aoi, L))
        reports["table"] = str(st.table_path(aoi, L))
    (a.out_dir / f"{aoi}_summary.json").write_text(json.dumps(reports, indent=1, ensure_ascii=False))
    log.info("%s: %d CSP plants, %.1f MW %s; %d thermal plants without electric output; "
             "%d CSP ids without an outline", aoi, len(table), reports["csp_mw"],
             reports["csp_mw_by_source"], len(heat_ids), len(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
