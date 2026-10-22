"""Read the owner's review of `results/aef_ground_review/review.geojson` back out of OSM.

The review was done by mapping every validated array into OpenStreetMap (JOSM, Esri World
Imagery) rather than by filling in a verdict column, so the verdict is whatever is in OSM
now and was not in the 2026-07-18 snapshot the candidates were called "unmapped" against.
Per candidate:

  * `pv`: a solar feature within 100 m (the precision table's `min_distance_m`) that is new
    since the snapshot.
  * `no_pv`: nothing new, on Esri imagery from `--recent` or later, where an installation the
    composite shows would have been visible.
  * `unknown`: nothing new, on older imagery, which cannot rule an installation out.

All 0.25-degree clusters go into one union query, pulled twice; both answers must hold the same
element ids and come from a mirror whose data base is newer than `--min-base`,
since mirrors have returned truncated or months-stale answers without an error before.

    pixi run python scripts/aef_review_from_osm.py
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.roofclf import auc

log = logging.getLogger("aef_review_osm")

REVIEW = Path("results/aef_ground_review/review.geojson")
META = Path("results/aef_ground_review/review_meta.json")
SNAPSHOT = Path("data/labels/pakistan_overpass_solar.parquet")
SNAPSHOT_DATE = "2026-07-18"
OUT = Path("results/aef_ground_review")
UTM = "EPSG:32642"
MATCH_M = 100.0
PAD_DEG = 0.003


def _query(bboxes, timeout: int = 180) -> str:
    from earthpv.overpass import _SELECTORS

    clauses = "\n".join(f'  nwr{sel}({s},{w},{n},{e});'
                        for (w, s, e, n) in bboxes for sel in _SELECTORS)
    return f"[out:json][timeout:{timeout}];\n(\n{clauses}\n);\nout meta geom;"


def _fetch(query: str, min_base: str, rounds: int = 6) -> tuple[dict, str]:
    """One answer from any mirror whose data is at least `min_base` (UTC ISO). A mirror once
    lagged three months, which here would read every fresh edit as "no PV"."""
    import requests

    from earthpv.overpass import _HEADERS, OVERPASS_ENDPOINTS

    for k in range(rounds):
        for url in OVERPASS_ENDPOINTS:
            try:
                r = requests.post(url, data={"data": query}, headers=_HEADERS, timeout=(30, 240))
                r.raise_for_status()
                d = r.json()
                base = d.get("osm3s", {}).get("timestamp_osm_base", "")
                if d.get("remark"):
                    log.warning("%s partial: %s", url, d["remark"])
                elif base < min_base:
                    log.warning("%s data base %s is older than %s", url, base, min_base)
                else:
                    return d, f"{url} @ {base}"
            except Exception as e:  # noqa: BLE001 -- next mirror
                log.warning("%s failed: %s", url, str(e)[:120])
        time.sleep(60 * (k + 1))
    raise RuntimeError("no Overpass mirror answered with fresh, complete data")


def _to_gdf(data: dict) -> gpd.GeoDataFrame:
    from earthpv.overpass import _element_geometry

    rows = []
    for el in data.get("elements", []):
        g = _element_geometry(el)
        if g is None or g.is_empty:
            continue
        rows.append({"id": f"osm-{el['type']}/{el['id']}", "osm_timestamp": el.get("timestamp"),
                     "osm_user": el.get("user"), "tags": json.dumps(el.get("tags", {})),
                     "geometry": g})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)


def pull(bboxes, min_base: str) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Two agreeing answers to one union query over every review cluster."""
    q = _query(bboxes)
    (a, src_a), (b, src_b) = _fetch(q, min_base), _fetch(q, min_base)
    ia = {(e["type"], e["id"]) for e in a["elements"]}
    ib = {(e["type"], e["id"]) for e in b["elements"]}
    if ia != ib:
        raise RuntimeError(f"two pulls disagree: {len(ia)} vs {len(ib)} elements")
    return _to_gdf(a), [src_a, src_b]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recent", default="2025-01-01")
    ap.add_argument("--min-base", required=True,
                    help="UTC ISO time the Overpass data must be at least as new as, i.e. "
                         "after the last upload of the review edits")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    r = gpd.read_file(REVIEW)
    r = r[r.obj_id.notna() & (r.obj_id != "")].copy()
    for c in ("learned", "change", "area_m2"):
        r[c] = r[c].astype(float)
    r["imagery_recent"] = r.imagery_recent.astype(str).str.lower() == "true"
    rp = r.geometry.representative_point()
    r["cluster"] = (np.floor(rp.x * 4).astype(int).astype(str) + "_"
                    + np.floor(rp.y * 4).astype(int).astype(str))
    bboxes = []
    for _, g in r.groupby("cluster"):
        b = g.total_bounds
        bboxes.append((b[0] - PAD_DEG, b[1] - PAD_DEG, b[2] + PAD_DEG, b[3] + PAD_DEG))
    osm, sources = pull(bboxes, args.min_base)
    log.info("%d solar elements over %d clusters from %s", len(osm), len(bboxes), sources)
    snap = set(pd.read_parquet(SNAPSHOT, columns=["id"]).id)
    osm["new"] = ~osm.id.isin(snap)
    osm.to_parquet(OUT / "osm_pull_review_areas.parquet")
    log.info("%d solar elements, %d new since %s", len(osm), int(osm.new.sum()), SNAPSHOT_DATE)

    ru = r.to_crs(UTM)
    ou = osm.to_crs(UTM)
    for col, sub in (("n_new", ou[ou.new]), ("n_old", ou[~ou.new])):
        j = gpd.sjoin(gpd.GeoDataFrame(geometry=ru.buffer(MATCH_M), crs=UTM), sub[["geometry"]],
                      predicate="intersects")
        r[col] = r.index.map(j.groupby(level=0).size()).fillna(0).astype(int)
    r["owner"] = np.where(r.n_new > 0, "pv", np.where(r.imagery_recent, "no_pv", "unknown"))

    meta = json.loads(META.read_text())
    pop = meta["stratum_population"]
    out = {"n": int(len(r)), "n_new_elements": int(osm.new.sum()), "overpass": sources,
           "candidates_with_old_osm_within_100m": int((r.n_old > 0).sum()),
           "by_stratum": {}, "real_share": {}}
    tab = pd.crosstab(r.stratum, r.owner)
    out["by_stratum"] = tab.to_dict(orient="index")

    def share(mask, unknown_as):
        """Stratified (Horvitz-Thompson) real share over the unmapped ground population.
        `unknown_as` None drops undecidable candidates from their stratum's rate; 0 or 1
        counts them as no PV or PV, which brackets it."""
        num = den = 0.0
        for st, n_pop in pop.items():
            g = r[(r.stratum == st) & mask]
            if unknown_as is None:
                g = g[g.owner != "unknown"]
            if not len(g):
                continue
            pv = (g.owner == "pv").sum() + (unknown_as or 0.0) * (g.owner == "unknown").sum()
            num += n_pop * pv / len(g)
            den += n_pop
        return round(num / den, 3) if den else None

    every = np.ones(len(r), bool)
    big = r.bin.isin(["1k-5k", "5k-50k", ">50k"]).to_numpy()
    for lab, m in (("all_sizes", every), ("ge_1000m2", big)):
        out["real_share"][lab] = {"unknown_excluded": share(m, None),
                                  "unknown_as_no_pv": share(m, 0.0),
                                  "unknown_as_pv": share(m, 1.0)}
    d = r[r.owner != "unknown"]
    y = (d.owner == "pv").to_numpy()
    out["auc_learned_vs_owner"] = round(auc(y, d.learned.to_numpy()), 3)
    out["auc_change_vs_owner"] = round(auc(y, d.change.to_numpy()), 3)
    out["n_decided"], out["n_decided_pv"] = int(len(d)), int(y.sum())
    r.drop(columns="geometry").to_csv(OUT / "owner_verdicts.csv", index=False)
    (OUT / "owner_review_summary.json").write_text(json.dumps(out, indent=2, default=int))
    print(json.dumps(out, indent=2, default=int))


if __name__ == "__main__":
    main()
