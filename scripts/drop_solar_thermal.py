#!/usr/bin/env python
"""Remove solar-THERMAL features from a country's OSM solar labels.

`overpass.fetch_solar_overpass` keeps every `generator:source=solar` / `plant:source=solar`
element and never reads the method tag, so concentrated-solar plants (heliostat and
parabolic-trough fields) and rooftop solar water heaters enter the labels as PV. Both
matter: France's hand-mapped communes carry 381 thermal collectors in 3,335 features
(docs/methods/france-validation.md), and a single CSP complex such as Noor Ouarzazate
(Morocco) or the Northern Cape plants (South Africa) covers several km2, which the atlas
would convert at the ground-mount land constant into PV that does not exist, and which
training would teach the model to call PV.

Rule: drop an element whose `generator:method` or `plant:method` names `thermal` (or whose
`generator:type` is a CSP collector type) UNLESS the same tag also names `photovoltaic` --
a hybrid perimeter (thermal;photovoltaic) is kept, since part of it is PV. Matching is by
OSM id against the labels' `id` column (`osm-<type>/<id>`). The original file is kept as
`<name>_overpass_solar.with_thermal.parquet` and the dropped ids are written next to it.
Idempotent: a second run finds nothing to drop.

`--candidates` applies the same exclusion to the MODEL's side, after postprocess: a
checkpoint that has learned (from earlier corpora) to read a mirror field as PV would
otherwise put the CSP plant back into Best as a ground-mount detection. Candidates whose
area lies at least half inside a dropped thermal polygon are removed from
data/predictions/<aoi>/candidates.parquet (kept as candidates.with_thermal.parquet).
Run it before `density`, whose cached partials are fingerprinted against that file.

    python scripts/drop_solar_thermal.py --aoi morocco [--dry-run]
    python scripts/drop_solar_thermal.py --aoi morocco --candidates
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from earthpv.config import Settings  # noqa: E402
from earthpv.overpass import _run_query  # noqa: E402

CSP_TYPES = "heliostat|parabolic_trough|solar_power_tower|fresnel_reflector|dish"


def thermal_ids(bbox, timeout: int = 300, tile_deg: float = 5.0) -> dict[str, dict]:
    """Country-sized boxes are split into tiles of at most `tile_deg`: one query over
    India's 29 x 30 degree box failed on every mirror (2026-10-10)."""
    import math
    xmin, ymin, xmax, ymax = bbox
    nx, ny = math.ceil((xmax - xmin) / tile_deg), math.ceil((ymax - ymin) / tile_deg)
    out: dict[str, dict] = {}
    for i in range(nx):
        for j in range(ny):
            tb = (xmin + i * (xmax - xmin) / nx, ymin + j * (ymax - ymin) / ny,
                  xmin + (i + 1) * (xmax - xmin) / nx, ymin + (j + 1) * (ymax - ymin) / ny)
            # One tile failing on every mirror used to abort the whole country, and with
            # a dozen tiles that happened on most ticks during the 2026-10-11 outage.
            for attempt in range(3):
                try:
                    out.update(_thermal_ids_tile(tb, timeout))
                    break
                except RuntimeError:
                    if attempt == 2:
                        raise
                    time.sleep(90)
    return out


def _thermal_ids_tile(bbox, timeout: int) -> dict[str, dict]:
    xmin, ymin, xmax, ymax = bbox
    b = f"({ymin},{xmin},{ymax},{xmax})"
    q = f"""[out:json][timeout:{timeout}];
(
  nwr["generator:source"="solar"]["generator:method"~"thermal"]{b};
  nwr["generator:source"="solar"]["generator:type"~"{CSP_TYPES}"]{b};
  nwr["plant:source"="solar"]["plant:method"~"thermal"]{b};
);
out tags;"""
    data = _run_query(q, timeout)
    out = {}
    for e in data.get("elements", []):
        t = e.get("tags", {})
        method = (t.get("generator:method", "") + ";" + t.get("plant:method", "")).lower()
        if "photovoltaic" in method:
            continue   # hybrid: keep
        out[f"osm-{e['type']}/{e['id']}"] = {
            k: t[k] for k in ("name", "power", "generator:method", "plant:method",
                              "generator:type", "plant:output:electricity") if k in t
        }
    return out


def filter_candidates(aoi: str, labels_dir: Path) -> int:
    record = labels_dir / f"{aoi}_solar_thermal_dropped.json"
    backup = labels_dir / f"{aoi}_overpass_solar.with_thermal.parquet"
    cpath = REPO / f"data/predictions/{aoi}/candidates.parquet"
    if not record.exists() or not backup.exists():
        print(f"{aoi}: no solar-thermal labels were dropped; candidates unchanged")
        return 0
    ids = set(json.loads(record.read_text()))
    th = gpd.read_parquet(backup)
    th = th[th["id"].isin(ids) & th.geom_type.isin(["Polygon", "MultiPolygon"])]
    cands = gpd.read_parquet(cpath)
    if th.empty or cands.empty:
        print(f"{aoi}: nothing to filter ({len(th)} thermal polygons, {len(cands)} candidates)")
        return 0
    crs = cands.estimate_utm_crs()
    zone = th.to_crs(crs).union_all()
    cm = cands.to_crs(crs)
    inter = cm.geometry.intersection(zone).area
    frac = inter / cm.geometry.area.clip(lower=1e-9)
    hit = (frac >= 0.5).to_numpy()
    print(f"{aoi}: {int(hit.sum())} of {len(cands)} candidates lie >= 50% inside "
          f"{len(th)} solar-thermal polygons ({cands.loc[hit, 'area_m2'].sum() / 1e6:.3f} km2)")
    if not hit.any():
        return 0
    keep = cpath.with_name("candidates.with_thermal.parquet")
    if not keep.exists():
        cands.to_parquet(keep)
    cands[~hit].to_parquet(cpath)
    print(f"wrote {cpath} ({len(cands) - int(hit.sum())} candidates); backup {keep.name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--labels-dir", type=Path, default=REPO / "data/labels")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    ap.add_argument("--candidates", action="store_true",
                    help="filter model candidates against the already-dropped thermal polygons")
    a = ap.parse_args()
    if a.candidates:
        return filter_candidates(a.aoi, a.labels_dir)
    cfg = Settings.load().aois[a.aoi]
    path = a.labels_dir / f"{a.aoi}_overpass_solar.parquet"
    lab = gpd.read_parquet(path)
    th = thermal_ids(cfg["bbox"])
    hit = lab["id"].isin(th)
    print(f"{a.aoi}: {len(th)} solar-thermal elements in the bbox, {int(hit.sum())} of "
          f"{len(lab)} label features match")
    if not hit.any():
        return 0
    dropped = lab[hit]
    area = float(dropped["area_m2"].fillna(0).sum()) if "area_m2" in dropped else float("nan")
    print(f"dropping {int(hit.sum())} features, {area / 1e6:.3f} km2 "
          f"({dict(dropped['placement'].value_counts()) if 'placement' in dropped else ''})")
    for i in dropped.sort_values("area_m2", ascending=False)["id"].head(10):
        print("  ", i, th.get(i, {}))
    if a.dry_run:
        return 0
    backup = path.with_name(f"{a.aoi}_overpass_solar.with_thermal.parquet")
    if not backup.exists():
        lab.to_parquet(backup)
    record = path.with_name(f"{a.aoi}_solar_thermal_dropped.json")
    prev = json.loads(record.read_text()) if record.exists() else {}
    prev.update({i: th[i] for i in dropped["id"]})
    record.write_text(json.dumps(prev, indent=1, ensure_ascii=False))
    lab[~hit].to_parquet(path)
    print(f"wrote {path} ({len(lab) - int(hit.sum())} features); backup {backup.name}, ids {record.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
