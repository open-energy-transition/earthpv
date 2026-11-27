"""Bring a country's OSM solar labels up to date with given changesets, from the OSM API.

When every Overpass mirror fails and the newest Geofabrik extract predates the mapping that
matters (Indonesia, 2026-11-26: the owner mapped from the leads released 2026-11-25, the
extract is from 11-24 and the mirrors 502 or refuse connections), the changesets themselves
are the freshest record. This reads each changeset's osmChange from the main OSM API, takes
every solar element it created, modified or deleted (`generator:source=solar` or
`plant:source=solar`, as Overpass's selectors), fetches the current geometry of the created and
modified ones (`/way/<id>/full`, `/relation/<id>/full`, nodes from the change itself), and
applies them to a base label file: deleted ids out, created and modified ids replaced. The rows
go through the same steps as `overpass_labels_chunked.py` (`overpass.solar_elements_to_gdf`,
national clip, `labels.classify_placement` on VIDA, geodesic area). Thermal elements are
dropped with `drop_solar_thermal._classify`, as `labels_from_pbf.py` does.

Edits by other people since the base pull are not seen; a full pull replaces this file when
the mirrors answer again. `--osmcha-since` finds the changesets with OSMCha (token in
~/.config/earthpv/osmcha_token, comment search `--comment`, inside the AOI's bbox).

    pixi run python scripts/osm_changeset_labels.py --aoi indonesia --iso3 IDN \\
        --base data/labels/indonesia_overpass_solar.parquet --osmcha-since 2026-11-21 \\
        --out data/labels/indonesia_pull_20261126/indonesia_overpass_solar.parquet
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

API = "https://api.openstreetmap.org/api/0.6"
UA = {"User-Agent": "earthpv-labels/1.0"}


def _get(url: str, params=None) -> requests.Response:
    for attempt in range(5):
        r = requests.get(url, params=params, headers=UA, timeout=120)
        if r.status_code == 200:
            return r
        if r.status_code in (404, 410):
            return r
        time.sleep(5 * (attempt + 1))
    r.raise_for_status()
    return r


def is_solar(tags: dict) -> bool:
    return tags.get("generator:source") == "solar" or tags.get("plant:source") == "solar"


def _tags(el) -> dict:
    return {t.get("k"): t.get("v") for t in el.findall("tag")}


def changeset_osmcha(since: str, bbox, comment: str) -> list[int]:
    tok = Path("~/.config/earthpv/osmcha_token").expanduser().read_text().strip()
    r = requests.get("https://osmcha.org/api/v1/changesets/",
                     headers={"Authorization": f"Token {tok}"},
                     params={"date__gte": since, "in_bbox": ",".join(map(str, bbox)),
                             "area_lt": 10, "comment": comment, "page_size": 500}, timeout=120)
    r.raise_for_status()
    return sorted(int(f["id"]) for f in r.json().get("features", []))


def read_changes(cs: list[int]) -> tuple[dict, set]:
    """(type, id) -> action for solar elements in the changesets (last action wins), and
    the (type, id) deleted in them (a delete carries no tags, so any deleted id counts)."""
    touched, deleted = {}, set()
    for c in cs:
        root = ET.fromstring(_get(f"{API}/changeset/{c}/download").content)
        for block in root:
            for el in block:
                key = (el.tag, int(el.get("id")))
                if block.tag == "delete":
                    deleted.add(key)
                    touched.pop(key, None)
                elif is_solar(_tags(el)):
                    touched[key] = block.tag
                    deleted.discard(key)
    return touched, deleted


def element(typ: str, oid: int) -> dict | None:
    """The element as an Overpass `out meta geom` dict, from the API's current version."""
    if typ == "node":
        r = _get(f"{API}/node/{oid}")
        if r.status_code != 200:
            return None
        n = ET.fromstring(r.content).find("node")
        if n is None or n.get("visible") == "false":
            return None
        return {"type": "node", "id": oid, "lon": float(n.get("lon")), "lat": float(n.get("lat")),
                "tags": _tags(n), "timestamp": n.get("timestamp"), "user": n.get("user"),
                "version": int(n.get("version"))}
    r = _get(f"{API}/{typ}/{oid}/full")
    if r.status_code != 200:
        return None
    root = ET.fromstring(r.content)
    nodes = {int(n.get("id")): {"lat": float(n.get("lat")), "lon": float(n.get("lon"))}
             for n in root.findall("node")}
    ways = {int(w.get("id")): [nodes.get(int(nd.get("ref"))) for nd in w.findall("nd")]
            for w in root.findall("way")}
    me = root.find(f"{typ}[@id='{oid}']")
    meta = {"tags": _tags(me), "timestamp": me.get("timestamp"), "user": me.get("user"),
            "version": int(me.get("version"))}
    if typ == "way":
        return {"type": "way", "id": oid, "geometry": ways.get(oid, []), **meta}
    members = []
    for m in me.findall("member"):
        mem = {"type": m.get("type"), "ref": int(m.get("ref")), "role": m.get("role")}
        if m.get("type") == "way":
            mem["geometry"] = [p for p in ways.get(int(m.get("ref")), []) if p]
        members.append(mem)
    return {"type": "relation", "id": oid, "members": members, **meta}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--iso3", required=True)
    ap.add_argument("--base", type=Path, required=True, help="the label file to bring up to date")
    ap.add_argument("--changeset", type=int, nargs="*", default=[])
    ap.add_argument("--osmcha-since", help="YYYY-MM-DD: add the changesets OSMCha finds since")
    ap.add_argument("--comment", default="earthpv")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    from earthpv import overture
    from earthpv.config import Settings
    from earthpv.density import fetch_geoboundaries
    from earthpv.labels import classify_placement, geodesic_area_m2, resolve_aoi
    from earthpv.overpass import solar_elements_to_gdf

    settings = Settings.load()
    _, cfg = resolve_aoi(a.aoi, settings)
    cs = list(a.changeset)
    if a.osmcha_since:
        cs = sorted(set(cs) | set(changeset_osmcha(a.osmcha_since, cfg["bbox"], a.comment)))
    if not cs:
        raise SystemExit("no changesets")
    touched, deleted = read_changes(cs)
    print(f"{len(cs)} changesets: {len(touched)} solar elements created or modified, "
          f"{len(deleted)} elements deleted", flush=True)

    els = []
    for (typ, oid) in sorted(touched):
        e = element(typ, oid)
        if e is not None and is_solar(e["tags"]):
            els.append(e)
        time.sleep(0.2)  # the API's usage policy: be gentle
    spec = importlib.util.spec_from_file_location("dst", REPO / "scripts" / "drop_solar_thermal.py")
    dst = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dst)
    hot = dst._classify(els)  # {"osm-<type>/<id>": tags} of the thermal ones
    thermal = [e for e in els if f"osm-{e['type']}/{e['id']}" in hot]
    els = [e for e in els if f"osm-{e['type']}/{e['id']}" not in hot]
    new = solar_elements_to_gdf(els)
    adm1 = fetch_geoboundaries(a.iso3, "ADM1")
    country = adm1.to_crs("EPSG:4326").geometry.union_all()
    new = new[new.geometry.representative_point().within(country)].reset_index(drop=True)
    if len(new):
        new = classify_placement(new, overture.connect(), settings,
                                 settings.rooftop_overlap_frac, iso3=a.iso3)
        new["area_m2"] = [geodesic_area_m2(g) for g in new.geometry]
        new["geom_type"] = new.geom_type

    base = gpd.read_parquet(a.base)
    gone = {f"osm-{t}/{i}" for t, i in deleted} | set(new["id"]) \
        | {f"osm-{e['type']}/{e['id']}" for e in thermal}
    kept = base[~base["id"].isin(gone)]
    out = gpd.GeoDataFrame(pd.concat([kept, new[[c for c in base.columns if c in new.columns]]],
                                     ignore_index=True), crs=base.crs)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(a.out)
    rec = dict(aoi=a.aoi, base=str(a.base), changesets=cs, made=time.strftime("%F %T"),
               solar_touched=len(touched), deleted=len(deleted), thermal_dropped=len(thermal),
               added_or_replaced=len(new), removed_from_base=int(len(base) - len(kept)),
               rows=len(out), new_placement=new["placement"].value_counts().to_dict()
               if len(new) else {}, new_area_m2_sum=float(new["area_m2"].sum()) if len(new) else 0)
    a.out.with_suffix(".json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
