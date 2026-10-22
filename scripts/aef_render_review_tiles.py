"""Blind contact sheets of ground candidates on Esri World Imagery, for the AEF mixture check.

`aef_large_array_change.py` reads the unmapped ground candidates' AlphaEarth scores as a
mixture of real arrays and false positives that change like the land around them. The
weak point is the second half: a false positive that LOOKS like PV may also score like PV.
This draws, seeded, unmapped ground candidates (1,000 m2 and up, where the mixture says the
real share is not zero) above and below the score threshold, plus mapped arrays and
displaced controls as checks on the reviewer, shuffles them, and renders each under a
random code with only its imagery capture date shown. The key goes to a separate file, to
be joined only after the verdicts are written down.

    pixi run python scripts/aef_render_review_tiles.py
"""

from __future__ import annotations

import io
import math
import sys
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from propose_calibration_candidates import esri_capture  # noqa: E402

SCORES = Path("results/aef_large_array_change_scores.csv")
POP = Path("results/aef_large_array_change_population.parquet")
OUT = Path("results/aef_ground_review/blind")
TILE = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
SEED = 20261023
N = {"unmapped_above": 24, "unmapped_below": 24, "mapped": 6, "control": 6}
BINS = ("1k-5k", "5k-50k", ">50k")
PANEL = 480


def _tile_xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def render(geom, code: str, date: str) -> Image.Image:
    minx, miny, maxx, maxy = geom.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = max(maxx - minx, (maxy - miny) / math.cos(math.radians(cy))) * 0.8 + 0.0008
    w, s, e, n = cx - half, cy - half * math.cos(math.radians(cy)), cx + half, cy + half * math.cos(math.radians(cy))
    z = 18
    while z > 12:
        x0, y0 = _tile_xy(w, n, z)
        x1, y1 = _tile_xy(e, s, z)
        if (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1) <= 16:
            break
        z -= 1
    x0, y0 = _tile_xy(w, n, z)
    x1, y1 = _tile_xy(e, s, z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    mos = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (40, 40, 40))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            req = urllib.request.Request(TILE.format(z=z, y=ty, x=tx),
                                         headers={"User-Agent": "earthpv-review/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    mos.paste(Image.open(io.BytesIO(r.read())).convert("RGB"),
                              ((tx - tx0) * 256, (ty - ty0) * 256))
            except Exception:  # noqa: BLE001 -- a missing tile stays grey
                pass

    def px(lon, lat):
        x, y = _tile_xy(lon, lat, z)
        return (x - tx0) * 256, (y - ty0) * 256

    d = ImageDraw.Draw(mos)
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for p in polys:
        d.line([px(*c) for c in p.exterior.coords], fill=(255, 230, 0), width=2)
    (a, b), (c, e2) = px(w, n), px(e, s)
    img = mos.crop((int(a), int(b), int(c), int(e2))).resize((PANEL, PANEL))
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    d.rectangle([0, 0, PANEL, 16], fill=(0, 0, 0))
    span_m = (e - w) * 111320 * math.cos(math.radians(cy))
    d.text((4, 2), f"{code}   imagery {date}   width {span_m:.0f} m", fill=(255, 255, 255), font=font)
    return img


def main() -> None:
    s = pd.read_csv(SCORES)
    pop = gpd.read_parquet(POP)[["obj_id", "geometry"]]
    g = s[(s.placement2 == "ground") & s.bin.isin(BINS)].copy()
    thr = {b: np.nanpercentile(g[(g.bin == b) & (g.role == "control")].learned_level, 95) for b in BINS}
    g["above"] = g.learned_level > g.bin.map(thr)
    rng = np.random.default_rng(SEED)
    pools = {
        "unmapped_above": g[(g.role == "unmapped") & g.above],
        "unmapped_below": g[(g.role == "unmapped") & ~g.above],
        "mapped": g[(g.role == "real") & (g.source == "candidate")],
        "control": g[g.role == "control"],
    }
    pick = pd.concat([p.loc[rng.choice(p.index.to_numpy(), size=N[k], replace=False)].assign(stratum=k)
                      for k, p in pools.items()])
    pick = pick.sample(frac=1, random_state=SEED).reset_index(drop=True)
    pick["code"] = [f"R{i:02d}" for i in range(len(pick))]
    pick = pick.merge(pop, on="obj_id")
    OUT.mkdir(parents=True, exist_ok=True)
    key = pick[["code", "obj_id", "stratum", "bin", "area_m2", "learned_level", "change"]].copy()
    dates = []
    imgs = []
    for _, r in pick.iterrows():
        p = r.geometry.representative_point()
        cap = esri_capture(p.x, p.y)
        dates.append(cap["date"].isoformat() if cap else "unknown")
        imgs.append(render(r.geometry, r.code, dates[-1]))
    key["imagery_date"] = dates
    key.to_csv(OUT.parent / "blind_key_DO_NOT_OPEN_BEFORE_VERDICTS.csv", index=False)
    pd.DataFrame({"code": pick.code, "imagery_date": dates, "verdict": "", "note": ""}).to_csv(
        OUT / "verdicts.csv", index=False)
    for k in range(0, len(imgs), 6):
        sheet = Image.new("RGB", (PANEL * 3, PANEL * 2), (0, 0, 0))
        for j, im in enumerate(imgs[k:k + 6]):
            sheet.paste(im, ((j % 3) * PANEL, (j // 3) * PANEL))
        sheet.save(OUT / f"sheet_{k // 6:02d}.png")
    print(f"{len(imgs)} panels in {math.ceil(len(imgs) / 6)} sheets under {OUT}")


if __name__ == "__main__":
    main()
