"""Park-sized mapping leads: large model detections with no mapped solar nearby.

The merge cap (`postprocess.MAX_CANDIDATE_M2`) keeps model outlines above 100,000 m2 out of
capacity, because in most countries those are rock, fields or pits. In Poland (2026-10-22)
most of them are real solar parks that OpenStreetMap does not hold yet. This writes them,
and every other park-sized model detection, as a verification package for human mappers:
nothing here is uploaded anywhere, and nothing should be mapped without checking it
against high-resolution imagery (OpenStreetMap's automated-edits rules apply to model
output, and this project's leads are proposals, not features).

    python scripts/park_leads.py --aoi poland

Writes results/<aoi>_park_leads/: parks.geojson (simplified outlines, largest first),
parks.csv, maproulette.geojson (one task per line) and contact_sheet.png (composite
crops of the largest, for quick triage).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

TAGS = "power=plant + plant:source=solar + plant:method=photovoltaic"
INSTRUCTION = (
    "Is this a solar park? Check it against recent high-resolution imagery. If panels are "
    "there, trace the fenced site as an area tagged power=plant, plant:source=solar, "
    "plant:method=photovoltaic (add plant:output:electricity if a source states it). The "
    "outline here is the satellite model's and only marks the place; do not upload it. If "
    "there are no panels, mark the task as not an issue."
)


def main() -> int:
    import geopandas as gpd
    import numpy as np

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--min-area-m2", type=float, default=50_000.0)
    ap.add_argument("--min-distance-m", type=float, default=100.0,
                    help="drop detections within this distance of any mapped solar feature")
    ap.add_argument("--land-kwp-m2", type=float, default=0.05,
                    help="site-area constant for the rough capacity column (density's default)")
    ap.add_argument("--sheet", type=int, default=24, help="largest N on the contact sheet")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    out = a.out or REPO / "results" / f"{a.aoi}_park_leads"
    out.mkdir(parents=True, exist_ok=True)

    cand = gpd.read_parquet(REPO / f"data/predictions/{a.aoi}/candidates.parquet")
    parks = cand[(cand["geometry_source"] != "osm") & (cand["area_m2"] >= a.min_area_m2)]
    utm = parks.estimate_utm_crs()
    parks = parks.to_crs(utm)
    lab = gpd.read_parquet(REPO / f"data/labels/{a.aoi}_overpass_solar.parquet").to_crs(utm)
    near = gpd.sjoin_nearest(parks[["geometry"]], lab[["geometry"]],
                             max_distance=a.min_distance_m).index.unique()
    n_all = len(parks)
    parks = parks[~parks.index.isin(near)].copy()
    parks["geometry"] = parks.geometry.simplify(5.0)
    parks["est_mwp"] = (parks["area_m2"] * a.land_kwp_m2 / 1000.0).round(1)
    parks = parks.sort_values("est_mwp", ascending=False).to_crs(4326).reset_index(drop=True)
    c = parks.geometry.representative_point()
    parks["lat"], parks["lon"] = c.y.round(5), c.x.round(5)
    b = parks.geometry.bounds
    parks["rank"] = np.arange(1, len(parks) + 1)
    parks["area_ha"] = (parks["area_m2"] / 1e4).round(1)
    parks["above_merge_cap"] = parks["area_m2"] > 100_000
    parks["id_editor"] = [f"https://www.openstreetmap.org/edit?editor=id#map=17/{y}/{x}"
                          for y, x in zip(parks.lat, parks.lon)]
    parks["josm"] = [f"http://127.0.0.1:8111/load_and_zoom?left={r.minx - 0.003:.5f}&right="
                     f"{r.maxx + 0.003:.5f}&top={r.maxy + 0.002:.5f}&bottom={r.miny - 0.002:.5f}"
                     for r in b.itertuples()]
    parks["suggested_tags"] = TAGS
    parks["status"] = "unverified model detection"
    cols = ["rank", "area_ha", "est_mwp", "above_merge_cap", "confidence", "placement",
            "lat", "lon", "id_editor", "josm", "suggested_tags", "status", "geometry"]
    parks = parks[cols]
    parks.to_file(out / "parks.geojson", driver="GeoJSON")
    parks.drop(columns="geometry").to_csv(out / "parks.csv", index=False)
    with open(out / "maproulette.geojson", "w") as f:
        for _, r in parks.iterrows():
            props = {k: (bool(v) if k == "above_merge_cap" else v)
                     for k, v in r.drop("geometry").items()}
            props["instruction"] = INSTRUCTION
            feat = {"type": "Feature", "geometry": json.loads(gpd.GeoSeries([r.geometry]).to_json())
                    ["features"][0]["geometry"], "properties": props}
            f.write(json.dumps({"type": "FeatureCollection", "features": [feat]}) + "\n")

    _contact_sheet(a.aoi, parks.head(a.sheet), out / "contact_sheet.png")
    print(f"{n_all} model detections >= {a.min_area_m2:,.0f} m2; {n_all - len(parks)} within "
          f"{a.min_distance_m:.0f} m of mapped solar; {len(parks)} park leads, "
          f"{parks.est_mwp.sum():,.0f} MWp at {a.land_kwp_m2} kWp/m2 "
          f"({int(parks.above_merge_cap.sum())} above the merge cap) -> {out}")
    return 0


def _contact_sheet(aoi: str, parks, path: Path, tile: int = 260) -> None:
    """Composite crops with the model outline, using the grid origin compose names cells by."""
    import geopandas as gpd
    import numpy as np
    import rasterio
    from PIL import Image, ImageDraw
    from rasterio.features import rasterize
    from rasterio.windows import from_bounds

    from earthpv.config import Settings
    from earthpv.density import _grid_origin

    s = Settings.load()
    ox, oy = _grid_origin(aoi, s.aois[aoi], s)
    tiles = []
    for r in parks.itertuples():
        p = r.geometry.representative_point()
        cell = f"{int((p.x - ox) // 0.1):04d}_{int((p.y - oy) // 0.1):04d}"
        f = REPO / f"data/composites/{aoi}/composites/{cell}/composite_0.tif"
        im = Image.new("RGB", (tile, tile), (40, 40, 40))
        if f.exists():
            with rasterio.open(f) as src:
                g = gpd.GeoSeries([r.geometry], crs=4326).to_crs(src.crs).iloc[0]
                w = from_bounds(*g.buffer(250).bounds, transform=src.transform)
                w = w.round_offsets().round_lengths()
                arr = src.read([3, 2, 1], window=w, boundless=True, fill_value=0).astype("float32")
                edge = rasterize([(g.boundary, 1)], out_shape=arr.shape[1:],
                                 transform=src.window_transform(w))
            sel = arr > 0
            if sel.any():
                lo, hi = np.percentile(arr[sel], (2, 98))
                rgb = np.clip((arr - lo) / max(hi - lo, 1e-6), 0, 1).transpose(1, 2, 0)
                rgb[edge == 1] = [1, 0.2, 0.2]
                im = Image.fromarray((rgb * 255).astype("uint8")).resize((tile, tile))
        ImageDraw.Draw(im).text((6, 4), f"#{r.rank}  {r.area_ha} ha", fill=(255, 255, 0))
        tiles.append(im)
    cols = 6
    sheet = Image.new("RGB", (tile * cols, tile * ((len(tiles) + cols - 1) // cols)))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * tile, (i // cols) * tile))
    sheet.save(path)


if __name__ == "__main__":
    raise SystemExit(main())
