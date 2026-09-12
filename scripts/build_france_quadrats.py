#!/usr/bin/env python
"""Turn the hand-mapped French commune PV surveys into earthpv calibration quadrats.

`data/labels/calibration_france/<commune>.geojson` holds one polygon per mapped solar
installation, drawn on IGN sub-metre aerial imagery. Each feature carries a `tag`
distinguishing real PV from solar-thermal collectors, and an `imageDate` recording the
imagery epoch it was drawn against -- which the Pakistani quadrats never had, and which
is what makes Rule-1 completeness checkable here rather than merely asserted.

Two things separate these from the Pakistani quadrats, and both are load-bearing:

1. **`tag` is not decoration.** 381 of 3,335 features are `thermal` -- solar hot-water
   collectors, which look like PV to a mapper and to a 10 m multispectral sensor but
   generate no electricity. Booking them as PV would inflate every capacity number
   downstream. `false` (12) is a mapper-retracted feature. Both are dropped. `unknown`
   (84) and `missing` (181) are genuinely ambiguous, so they are excluded from the
   primary label set and written to a parallel `--sensitivity-dir` instead, letting the
   calibration be re-run against the wider definition without either set silently
   becoming ground truth.

2. **The quadrat boundary is the commune**, not a drawn box. `metadata.json` records a
   `surface` per commune matching the official INSEE commune area, so the mapper's unit
   of work was the whole commune. Mapping does spill past the commune edge (up to 23% of
   features), so features are clipped to the contour: what is certified complete is the
   inside, and area-normalised quantities (density, base rate) must use the same
   denominator the labels do.

Placement comes from VIDA footprint overlap rather than a tag, matching how
`postprocess` classifies its own candidates, so `parcel_pv_area`'s ground/overhang rule
sees the same distinction it does in Pakistan.

    pixi run python scripts/build_france_quadrats.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import make_valid
from shapely.geometry import shape

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from earthpv.labels import dissolve_overlapping, geodesic_area_m2  # noqa: E402

UA = {"User-Agent": "earthpv-france-quadrats/1.0 (research tool; contact via repo issues)"}
GEO_API = "https://geo.api.gouv.fr/communes/{code}?fields=nom,code,surface,contour&format=json&geometry=contour"

# Tag semantics, from the mapper's own vocabulary.
PV_TAGS = {"normal", "redrawn"}          # a real PV installation
AMBIGUOUS_TAGS = {"unknown", "missing"}  # kept only for the sensitivity variant
DROP_TAGS = {"thermal", "false"}         # solar thermal, and mapper-retracted features

# Two files have no metadata.json entry; resolved by name against geo.api.gouv.fr.
EXTRA_INSEE = {"toussieu": "69298", "st-gely(unfinished)": "34255"}

# Mapped but explicitly incomplete -- excluded from the calibration set, since Rule-1
# (every visible panel mapped) is exactly what it does not satisfy.
INCOMPLETE = {"st-gely(unfinished)"}

log = logging.getLogger("france-quadrats")


def _median_image_date(g) -> str | None:
    """Median `imageDate` across a commune's mapped features, as an ISO date string."""
    if "imageDate" not in g.columns:
        return None
    d = pd.to_datetime(g["imageDate"], errors="coerce").dropna()
    return None if d.empty else d.median().strftime("%Y-%m-%d")


def slug(stem: str) -> str:
    """ASCII slug that keeps French names readable: Chambery, not chamb_ry.

    Accents have to be folded rather than replaced, or every accented commune loses a
    letter from its quadrat stem and `roofclf.quadrat_label` reports a fold under a name
    nobody can match back to a place.
    """
    folded = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")


def size_tag(km2: float) -> str:
    return f"{km2:.2f}".replace(".", "p") + "km2"


def commune_contour(code: str) -> tuple[str, object, float]:
    """(name, valid EPSG:4326 geometry, area km2) for an INSEE commune code."""
    req = urllib.request.Request(GEO_API.format(code=code), headers=UA)
    d = json.load(urllib.request.urlopen(req, timeout=90))
    return d["nom"], make_valid(shape(d["contour"])), d["surface"] / 100.0


def load_buildings(bounds, iso3: str) -> gpd.GeoDataFrame:
    from earthpv.buildings import fetch_vida_buildings

    return fetch_vida_buildings(tuple(bounds), iso3)


def build(args: argparse.Namespace) -> int:
    src = Path(args.source)
    meta = json.load(open(src / "metadata.json"))
    insee = {k: v["INSEE"] for k, v in meta.items()} | EXTRA_INSEE

    out = Path(args.out_dir)
    sens = Path(args.sensitivity_dir)
    for d in (out, sens):
        d.mkdir(parents=True, exist_ok=True)

    rows = []
    for path in sorted(src.glob("*.geojson")):
        stem = path.stem
        code = insee.get(stem)
        if code is None:
            log.warning("no INSEE code for %s; skipped", stem)
            continue
        nom, contour, km2 = commune_contour(code)

        g = gpd.read_file(path).to_crs("EPSG:4326")
        n_raw = len(g)
        n_invalid = int((~g.geometry.is_valid).sum())
        g["geometry"] = g.geometry.apply(make_valid)
        g["tag"] = g["tag"].astype(str).str.strip().str.lower()

        # Clip to the commune: the inside is what the mapper certified.
        g = g[g.geometry.intersects(contour)].copy()
        g["geometry"] = g.geometry.intersection(contour)
        g = g[~g.geometry.is_empty & g.geometry.geom_type.isin(("Polygon", "MultiPolygon"))]

        n_thermal = int((g.tag == "thermal").sum())
        n_false = int((g.tag == "false").sum())
        n_amb = int(g.tag.isin(AMBIGUOUS_TAGS).sum())

        pv = g[g.tag.isin(PV_TAGS)].copy()
        pv_wide = g[g.tag.isin(PV_TAGS | AMBIGUOUS_TAGS)].copy()
        for frame in (pv, pv_wide):
            frame["area_m2"] = [geodesic_area_m2(x) for x in frame.geometry]

        bldg = load_buildings(contour.bounds, args.iso3)
        stem_out = f"{slug(nom)}_calib_{size_tag(km2)}"

        for frame, target in ((pv, out), (pv_wide, sens)):
            if frame.empty:
                continue
            f = frame.copy()
            if bldg is not None and not bldg.empty:
                hit = gpd.sjoin(
                    f[["geometry"]], bldg[["geometry"]], how="left", predicate="intersects"
                )
                on_roof = hit.groupby(hit.index)["index_right"].apply(lambda s: s.notna().any())
                f["placement"] = ["rooftop" if on_roof.get(i, False) else "ground" for i in f.index]
            else:
                f["placement"] = "rooftop"
            f["kind"] = "generator"
            f["class"] = "generator"
            f["generator_source"] = "solar"
            f["plant_source"] = None
            f["generator_place"] = f["placement"]
            f["osm_location"] = None
            f["osm_timestamp"] = f.get("lastEdited")
            f["image_date"] = f.get("imageDate")
            f["label_tag"] = f["tag"]
            f["id"] = [f"fr-{slug(nom)}-{i}" for i in range(len(f))]
            f["geom_type"] = f.geometry.geom_type
            f = f[[
                "id", "class", "generator_source", "plant_source", "generator_place",
                "osm_location", "osm_timestamp", "geometry", "kind", "placement",
                "area_m2", "geom_type", "label_tag", "image_date",
            ]]
            f = dissolve_overlapping(gpd.GeoDataFrame(f, crs="EPSG:4326"))
            f.to_parquet(target / f"{stem_out}_overpass_solar.parquet")

        boundary = gpd.GeoDataFrame(
            [{
                "quadrat_id": stem_out,
                "stratum": meta.get(stem, {}).get("type", "unknown"),
                "location": nom,
                "province": f"dept-{meta.get(stem, {}).get('dpt', code[:2])}",
                "size_km2": round(km2, 4),
                "center": None,
                "shape": "commune",
                "source_geojson": str(path),
                "n_vertices": None,
                "insee": code,
                "pv_density_note": meta.get(stem, {}).get("pv_density"),
                "grd": meta.get(stem, {}).get("GRD"),
                # Prefer the median imageDate of the features themselves over
                # metadata.json's single date: every feature carries the epoch it was
                # actually drawn against, two communes have no metadata entry at all, and
                # a couple were mapped across two flights. This is the date the register
                # is read back to, so getting it from the labels rather than a side file
                # is what keeps the epoch match honest.
                "mapping_date": _median_image_date(g) or meta.get(stem, {}).get("date"),
                "geometry": contour,
            }],
            crs="EPSG:4326",
        )
        for d in (out, sens):
            boundary.to_file(d / f"{stem_out}_boundary.geojson", driver="GeoJSON")

        n_bldg = 0 if bldg is None else int(bldg.geometry.intersects(contour).sum())
        rows.append(dict(
            commune=nom, insee=code, stem=stem_out, km2=round(km2, 2), raw=n_raw,
            invalid=n_invalid, pv=len(pv), thermal=n_thermal, false=n_false, ambiguous=n_amb,
            pv_m2=round(float(pv["area_m2"].sum()), 0),
            pv_m2_sub200=round(float(pv.loc[pv.area_m2 < 200, "area_m2"].sum()), 0),
            bldg=n_bldg, bldg_km2=round(n_bldg / km2, 1),
            incomplete=stem in INCOMPLETE,
        ))

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    df.to_csv(REPO / "results" / "france_quadrats_summary.csv", index=False)
    print(f"\nwrote {len(df)} quadrats -> {out}  (sensitivity variant -> {sens})")
    if any(df.incomplete):
        print("NOTE: rows with incomplete=True are NOT Rule-1 complete and must be "
              "excluded from any calibration fit (pass --quadrat explicitly).")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="data/labels/calibration_france")
    p.add_argument("--out-dir", default="data/labels/france")
    p.add_argument("--sensitivity-dir", default="data/labels/france_sensitivity")
    p.add_argument("--iso3", default="FRA")
    return build(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
