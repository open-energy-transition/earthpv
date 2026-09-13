"""Screen large OSM `power=plant` ground perimeters for whether an array was ever built.

**Why this exists.** Zambia's mapped OSM solar population is 221 features, but 20.2 of its
20.6 km2 of ground area sits in sixteen perimeters of 0.3-2.8 km2, eleven of them added in a
single mapping pass on 2026-08-04. Converted at `DEFAULT_KWP_PER_M2_LAND` that population
alone implies ~1,089 MWp against a real Zambian fleet of roughly 100-150 MW. It feeds the
evidence atlas's Verified tier directly, and `chips` burns every OSM polygon at or above
`MIN_PV_AREA` as a positive training mask -- so an announced-but-unbuilt project site is
both booked as capacity and taught to the model as the appearance of PV.

**What it measures.** For each ground feature above `--min-area-m2`, over EVERY composited
cell the polygon intersects (not just the cell its representative point falls in -- these
polygons routinely straddle a 0.1 deg boundary):

  imaged_frac  fraction of the polygon's pixels that have composite data at all
  det_frac     fraction of the IMAGED pixels above `--threshold` in the probability raster
  p_max        the single highest probability anywhere inside it

**How to read it, and the circularity.** `det_frac` is the model's opinion about the labels
the model is trained on, so it cannot settle anything by itself. It is a SCREEN: it ranks
which perimeters to look at, and the verdict comes from looking. Two things make the screen
trustworthy enough to be worth looking at. The same checkpoint, in the same country and the
same imagery epoch, covers Bangweulu and Itimpi at 98.8-99.7% of their imaged area, so it is
demonstrably not blind to Zambian ground-mount. And a `p_max` of exactly 0.00 over a square
kilometre is a different kind of statement from a low mean -- there is no pixel anywhere in
it that the model finds even slightly PV-like.

Screening is restricted to LARGE GROUND features on purpose. A built solar park is
unmistakable at 10 m GSD and the model finds real ones; small rooftop arrays are exactly
where segmentation is a known weak instrument (see CLAUDE.md on the 400 m2 floor), so
nothing below the threshold is judged here.

**Output.** A review CSV, and -- with `--write-filtered` -- a copy of the labels parquet
with the ids listed in `--exclude` removed. That list is meant to be HAND-AUDITED against
the imagery first: `--png-dir` writes an RGB crop of every screened polygon for that
purpose. Re-run it after `compose` finishes, when `imaged_frac` reaches 1.0 and a verdict
withheld for coverage can finally be taken.

    python scripts/screen_osm_ground_perimeters.py --aoi zambia \\
        --labels data/labels/zambia_overpass_solar.parquet \\
        --prob-dir data/predictions/zambia/prob \\
        --out results/zambia_osm_ground_screen.csv --png-dir results/zambia_osm_ground_screen
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

CELL_DEG = 0.1


def cells_for(geom, origin_lon: float, origin_lat: float) -> list[str]:
    """Every 0.1 deg cell the polygon's bounds touch, in compose's naming."""
    minx, miny, maxx, maxy = geom.bounds
    i0 = int(np.floor((minx - origin_lon) / CELL_DEG))
    i1 = int(np.floor((maxx - origin_lon) / CELL_DEG))
    j0 = int(np.floor((miny - origin_lat) / CELL_DEG))
    j1 = int(np.floor((maxy - origin_lat) / CELL_DEG))
    return [f"{i:04d}_{j:04d}" for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]


def _window(path: Path, geom_wgs84) -> tuple[np.ndarray, object] | None:
    if not path.exists():
        return None
    with rasterio.open(path) as src:
        g = gpd.GeoSeries([geom_wgs84], crs="EPSG:4326").to_crs(src.crs).iloc[0]
        try:
            arr, _ = rio_mask(src, [g], crop=True, filled=True, nodata=0)
        except ValueError:
            return None  # no overlap with this cell
    return arr, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--prob-dir", type=Path, required=True)
    ap.add_argument("--composite-dir", type=Path, default=None,
                    help="default data/composites/<aoi>/composites")
    ap.add_argument("--min-area-m2", type=float, default=200_000.0)
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--placements", default="ground,unknown")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--png-dir", type=Path, default=None)
    ap.add_argument("--exclude", type=Path, default=None,
                    help="text file of OSM ids, one per line, to drop from the labels")
    ap.add_argument("--write-filtered", type=Path, default=None)
    a = ap.parse_args()

    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi

    settings = Settings.load()
    _, cfg = resolve_aoi(a.aoi, settings)
    origin = cfg.get("grid_origin") or cfg["bbox"][:2]
    comp_dir = a.composite_dir or REPO / "data" / "composites" / a.aoi / "composites"

    labels = gpd.read_parquet(a.labels)
    keep = labels["placement"].isin([p.strip() for p in a.placements.split(",")])
    big = labels[keep & (labels["area_m2"] >= a.min_area_m2)].copy()
    print(f"{len(big)} ground features at or above {a.min_area_m2:,.0f} m2")

    if a.png_dir:
        a.png_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for _, f in big.sort_values("area_m2", ascending=False).iterrows():
        imaged_px = total_px = det_px = 0
        p_max = 0.0
        rgb_parts = []
        for cell in cells_for(f.geometry, origin[0], origin[1]):
            comp = _window(Path(comp_dir) / cell / "composite_0.tif", f.geometry)
            if comp is None:
                continue
            carr = comp[0]
            valid = carr[:4].sum(axis=0) > 0
            imaged_px += int(valid.sum())
            total_px += int(valid.size)
            if a.png_dir is not None and valid.any():
                rgb_parts.append(carr)
            pr = _window(Path(a.prob_dir) / f"{cell}.tif", f.geometry)
            if pr is None:
                continue
            p = pr[0][0].astype("float32") / 255.0
            n = min(p.size, valid.size)
            pv, vv = p.ravel()[:n], valid.ravel()[:n]
            if vv.any():
                det_px += int((pv[vv] > a.threshold).sum())
                p_max = max(p_max, float(pv[vv].max()))
        # `total_px` counts each intersecting cell's crop, which overlaps between cells;
        # the polygon's own geodesic area is the honest denominator.
        area_px = f.area_m2 / 100.0
        imaged_frac = min(imaged_px / area_px, 1.0) if area_px else 0.0
        det_frac = det_px / imaged_px if imaged_px else float("nan")
        rows.append({
            "id": f.id, "area_m2": round(f.area_m2), "area_km2": round(f.area_m2 / 1e6, 3),
            "imaged_frac": round(imaged_frac, 3), "det_frac": round(det_frac, 4)
            if imaged_px else "", "p_max": round(p_max, 3),
            "osm_timestamp": f.get("osm_timestamp"),
            # Deliberately not a verdict. "look" means the screen found nothing and the
            # polygon is imaged enough that looking at it will settle the question.
            "screen": ("look" if imaged_frac >= 0.3 and p_max == 0.0
                       else "detected" if det_px else "insufficient-imagery"),
        })
        if a.png_dir is not None and rgb_parts:
            _write_png(rgb_parts, a.png_dir / f"{str(f.id).replace('/', '_')}.png")

    import pandas as pd

    df = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(df.to_string(index=False))
    print(f"\nwrote {a.out}")
    print(df["screen"].value_counts().to_dict())

    if a.write_filtered:
        if not a.exclude:
            print("--write-filtered needs --exclude (the hand-audited id list)")
            return 1
        drop = {ln.strip() for ln in a.exclude.read_text().splitlines()
                if ln.strip() and not ln.startswith("#")}
        out = labels[~labels["id"].isin(drop)].reset_index(drop=True)
        dropped_km2 = labels.loc[labels["id"].isin(drop), "area_m2"].sum() / 1e6
        print(f"dropping {len(labels) - len(out)} of {len(labels)} features "
              f"({dropped_km2:.2f} km2)")
        a.write_filtered.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(a.write_filtered)
        print(f"wrote {a.write_filtered}")
    return 0


def _write_png(parts: list[np.ndarray], path: Path) -> None:
    from PIL import Image

    arr = max(parts, key=lambda p: (p[:4].sum(axis=0) > 0).sum())
    rgb = np.stack([arr[2], arr[1], arr[0]]).astype("float32")
    sel = rgb > 0
    lo, hi = np.percentile(rgb[sel], (2, 98)) if sel.any() else (0.0, 1.0)
    img = np.clip((rgb - lo) / max(hi - lo, 1e-6), 0, 1)
    im = Image.fromarray((img.transpose(1, 2, 0) * 255).astype("uint8"))
    w, h = im.size
    s = max(1, min(4, 700 // max(w, h, 1)))
    if s > 1:
        im = im.resize((w * s, h * s), Image.NEAREST)
    im.save(path)


if __name__ == "__main__":
    raise SystemExit(main())
