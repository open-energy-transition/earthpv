"""Do Spain's plastic greenhouses read as solar parks?

`configs/atlas/spain.yaml` owed this measurement before the page was shown: greenhouses are
bright, regular sheets, a plausible false-positive class. For the five main greenhouse
districts this reports every model outline (a candidate with no OSM geometry), its area, what
`density` priced it at (`est_kwp_rc`) and how many outlines of the solar farm review fall
there. The priced figure is a ceiling on the confusion, since real parks in a district count
too. The contact sheet holds each district's three highest-priced outlines below the merge cap
on Esri World Imagery, for reading off what they are.

    python scripts/spain_greenhouse_check.py [--no-sheet]
"""

from __future__ import annotations

import argparse
import io
import time
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
PRED = REPO / "data" / "predictions" / "spain"
OUT = REPO / "results" / "spain_greenhouse_check"
# (west, south, east, north)
DISTRICTS = {"Campo de Dalias": (-3.1, 36.65, -2.5, 36.85),
             "Nijar": (-2.3, 36.8, -1.95, 37.05),
             "Campo de Cartagena": (-1.2, 37.6, -0.65, 37.95),
             "Aguilas and Mazarron": (-1.75, 37.35, -1.2, 37.65),
             "Huelva coast": (-7.1, 37.15, -6.4, 37.45)}
ESRI = ("https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export"
        "?bbox={},{},{},{}&bboxSR=4326&imageSR=4326&size=300,300&format=jpg&f=image")
MAX_CANDIDATE_M2 = 100_000


def model_outlines() -> gpd.GeoDataFrame:
    """Candidates with no OSM geometry, priced. `candidate_row` counts the frame `density`
    priced (outlines above the cap removed), not this file, so join on the representative
    point it recorded. An unjudged outline above the cap is priced at nothing."""
    c = gpd.read_parquet(PRED / "candidates.parquet").reset_index(drop=True)
    e = pd.read_parquet(PRED / "density" / "candidate_estimates.parquet")
    rep = c.geometry.representative_point()
    c["lon"], c["lat"] = rep.x, rep.y
    c["x6"], c["y6"] = rep.x.round(6), rep.y.round(6)
    e = e.assign(x6=e["x"].round(6), y6=e["y"].round(6))
    c = c.merge(e[["x6", "y6", "est_kwp_rc"]], on=["x6", "y6"], how="left")
    c["est_kwp_rc"] = c["est_kwp_rc"].fillna(0.0)
    return c[c["geometry_source"].fillna("model") != "osm"]


def inside(d: pd.DataFrame, box: tuple[float, float, float, float]) -> pd.DataFrame:
    w, s, e, n = box
    return d[(d["lon"] >= w) & (d["lon"] < e) & (d["lat"] >= s) & (d["lat"] < n)]


def sheet(model: gpd.GeoDataFrame, path: Path) -> None:
    from PIL import Image, ImageDraw

    picks = [inside(model[model["area_m2"] < MAX_CANDIDATE_M2], box)
             .nlargest(3, "est_kwp_rc").assign(district=k) for k, box in DISTRICTS.items()]
    rows = pd.concat(picks)
    tiles = []
    for r in rows.itertuples():
        x0, _, x1, _ = r.geometry.bounds
        half = max(0.0035, (x1 - x0) * 0.75)
        w, s, e, n = r.lon - half, r.lat - half, r.lon + half, r.lat + half
        req = urllib.request.Request(ESRI.format(w, s, e, n),
                                     headers={"User-Agent": "earthpv-research"})
        for attempt in range(4):
            try:
                raw = urllib.request.urlopen(req, timeout=60).read()
                break
            except OSError:
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"Esri did not answer for {r.lon:.4f},{r.lat:.4f}")
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        draw = ImageDraw.Draw(im)
        polys = [r.geometry] if r.geometry.geom_type == "Polygon" else list(r.geometry.geoms)
        for g in polys:
            pts = [((x - w) / (e - w) * 300, (n - y) / (n - s) * 300) for x, y in g.exterior.coords]
            draw.line(pts + [pts[0]], fill=(255, 40, 40), width=2)
        draw.rectangle([0, 0, 300, 14], fill=(0, 0, 0))
        draw.text((3, 1), f"{r.district}: {r.area_m2 / 1e4:.1f} ha, {r.est_kwp_rc / 1000:.2f} MWp",
                  fill=(255, 255, 255))
        tiles.append(im)
    cols = 4
    out = Image.new("RGB", (cols * 300, int(np.ceil(len(tiles) / cols)) * 300), (30, 30, 30))
    for i, t in enumerate(tiles):
        out.paste(t, ((i % cols) * 300, (i // cols) * 300))
    out.save(path, quality=85)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-sheet", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    model = model_outlines()
    queue = pd.read_csv(REPO / "results" / "spain_oversize_review" / "review.csv")
    rows = []
    for name, box in DISTRICTS.items():
        d, q = inside(model, box), inside(queue, box)
        rows.append({"district": name, "outlines": len(d),
                     "area_km2": round(d["area_m2"].sum() / 1e6, 2),
                     "priced_mwp": round(d["est_kwp_rc"].sum() / 1000, 2),
                     "review_outlines": len(q),
                     "review_km2": round(q["area_m2"].sum() / 1e6, 1)})
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "district_capacity.csv", index=False)
    print(table.to_string(index=False))
    total = model["est_kwp_rc"].sum() / 1000
    print(f"five districts {table['outlines'].sum()} outlines, {table['priced_mwp'].sum():.1f} MWp "
          f"of {total:,.1f} MWp priced on model outlines nationally "
          f"({100 * table['priced_mwp'].sum() / total:.1f}%)")
    if not a.no_sheet:
        sheet(model, OUT / "top_outlines_sheet.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
