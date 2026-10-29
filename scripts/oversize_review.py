"""Review the model outlines above the merge cap, and price them by that review.

`postprocess.MAX_CANDIDATE_M2` (100,000 m2) keeps model outlines above it out of capacity:
in Pakistan they were merged false-positive sheets. In India most are solar parks that
OpenStreetMap does not hold yet (2026-10-28, docs/results/india.md). This measures, per
country, what share of those outlines is real, and writes the result into the country's
calibration table as `oversize_review`, which is what makes `density` and the atlas admit
them (`density.load_oversize_admission`). A country without the block keeps the cap.

The population is the export's own: model-drawn outlines above the cap that are new leads
(`export.new_lead_mask`, no mapped solar within `--min-distance-m`). Two strata:

  * a CENSUS of the `--census-n` largest outlines, every one reviewed;
  * a SAMPLE of `--sample-n` drawn from the rest with probability proportional to area and
    without replacement, so the share found real is an AREA share, the weight a per-outline
    area estimate needs.

    python scripts/oversize_review.py draw --aoi india     # review.csv + the review package
    # open data/oversize_review/india/index.html, judge every outline (keys 1 / 2 / 3),
    # export verdicts.csv into results/india_oversize_review/, then:
    python scripts/oversize_review.py apply --aoi india --verdicts \\
        results/india_oversize_review/verdicts.csv --reviewer "<name>" \\
        --exclude-region "Uttarākhand" --exclude-region "Ladākh" ...

**The review is done on disk, from the imagery the model saw** (`package`, run by `draw`,
2026-10-29). Each outline gets one image of four panels in
`data/oversize_review/<aoi>/crops/`: the Sentinel-2 composite of the imagery window in true
colour around the whole outline, the same at native 10 m pixels over 1.3 km, a false colour
(SWIR, NIR, red), and Esri World Imagery with its capture date. `index.html` beside them is
`build_review_page.py`'s page: one outline at a time, PV / not PV / unsure, a note, links to
Google, Bing, Esri Wayback and JOSM for an outline the panels cannot settle. The composite
is the right epoch: 11 of the 50 parks of India's sample were built after their Esri capture.
Its limit is 10 m: 9 of India's 60 sampled outlines needed the Esri panel to decide, and
`apply` accepts no unsure verdict (resolve it on the linked imagery, or pass
`--unsure-as not_pv` to price it as absent). The page shows no model score, and nothing
from an earlier verdict, so a second reviewer judges blind; `apply` reports agreement.
`review.geojson` holds the same outlines for JOSM.

`--exclude-region` (ADM1 names) keeps the cap in regions where the review found terrain, not
parks: their sample rows are reported apart and nothing there is admitted. The review is a
human reading of imagery (Sentinel-2 composite, Esri World Imagery and its capture date):
record who reviewed it in `--reviewer`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

VERDICTS = ("pv", "not_pv")


def population(aoi: str, labels: Path, min_distance_m: float):
    """New-lead model outlines above the cap, with their ADM1 region."""
    import geopandas as gpd

    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings
    from earthpv.density import fetch_geoboundaries
    from earthpv.export import new_lead_mask
    from earthpv.labels import resolve_aoi
    from earthpv.postprocess import MAX_CANDIDATE_M2

    c = gpd.read_parquet(REPO / f"data/predictions/{aoi}/candidates.parquet")
    src = c["geometry_source"].fillna("model") if "geometry_source" in c.columns else "model"
    pool = c[(c["area_m2"] > MAX_CANDIDATE_M2) & (src != "osm")]
    ref = gpd.read_parquet(labels)[["geometry"]]
    pool = pool[new_lead_mask(pool, ref, min_distance_m=min_distance_m)].copy()
    _, cfg = resolve_aoi(aoi, Settings.load())
    adm1 = fetch_geoboundaries(_iso3_for(cfg), "ADM1").to_crs(4326)
    rp = gpd.GeoDataFrame(geometry=pool.geometry.representative_point(), crs=4326)
    j = gpd.sjoin(rp, adm1[["name", "geometry"]], how="left", predicate="within")
    pool["region"] = j.groupby(level=0)["name"].first().reindex(pool.index)
    pool["lon"] = rp.geometry.x.round(5)
    pool["lat"] = rp.geometry.y.round(5)
    pool["candidate_index"] = pool.index
    return pool


def cmd_draw(a) -> int:
    import numpy as np
    import pandas as pd

    path = a.out / "review.csv"
    if path.exists() and not a.redraw:
        print(f"{path} exists; packaging it as drawn (--redraw draws a new sample)")
        return cmd_package(a)
    pool = population(a.aoi, a.labels, a.min_distance_m)
    if pool.empty:
        print(f"no model outline above the cap is a new lead in {a.aoi}; nothing to review")
        return 0
    rng = np.random.default_rng(a.seed)
    census = pool.sort_values("area_m2", ascending=False).head(a.census_n)
    rest = pool.drop(census.index)
    pick = rng.choice(rest.index, size=min(a.sample_n, len(rest)), replace=False,
                      p=rest["area_m2"] / rest["area_m2"].sum())
    sample = rest.loc[pick]
    cols = ["candidate_index", "lon", "lat", "area_m2", "region"]
    out = pd.concat([census[cols].assign(stratum="census", k=range(len(census))),
                     sample[cols].assign(stratum="sample", k=range(len(sample)))])
    out["code"] = [f"{s[0]}{k:02d}" for s, k in zip(out.stratum, out.k)]
    out["verdict"] = ""
    out["evidence"] = ""
    a.out.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    print(f"{len(pool)} outlines above the cap with no mapped solar within "
          f"{a.min_distance_m:.0f} m ({pool.area_m2.sum() / 1e6:.1f} km2); census {len(census)} "
          f"({census.area_m2.sum() / 1e6:.1f} km2), sample {len(sample)} by area, seed {a.seed} "
          f"-> {path}")
    return cmd_package(a)


def cmd_apply(a) -> int:
    import numpy as np
    import pandas as pd

    from earthpv import capacity_calibration as cc
    from earthpv.postprocess import MAX_CANDIDATE_M2

    rev = pd.read_csv(a.review)
    if a.verdicts is not None:
        rev = _merge_page_verdicts(rev, a.verdicts, a.unsure_as, a.reviewer)
        rev.to_csv(a.review, index=False)
    bad = sorted(set(rev["verdict"].fillna("")) - set(VERDICTS))
    if bad:
        raise SystemExit(f"{a.review}: verdicts must be {VERDICTS}, found {bad} (blank = unreviewed)")
    pool = population(a.aoi, a.labels, a.min_distance_m)
    missing = set(rev["candidate_index"]) - set(pool["candidate_index"])
    if missing:
        raise SystemExit(f"{len(missing)} reviewed outlines are not in the current population "
                         f"(candidates.parquet changed since the draw?): {sorted(missing)[:5]}")
    excluded = set(a.exclude_region)
    unknown = excluded - set(pool["region"].dropna())
    if unknown:
        raise SystemExit(f"--exclude-region names no outline's region: {sorted(unknown)}")
    rev["real"] = rev["verdict"] == "pv"
    rev["excluded"] = rev["region"].isin(excluded)
    census = rev[rev.stratum == "census"]
    if census["excluded"].any():
        raise SystemExit("a census outline lies in an excluded region; the strata would overlap")
    sample = rev[(rev.stratum == "sample") & ~rev.excluded]
    ex = rev[(rev.stratum == "sample") & rev.excluded]
    block = {
        "derived": date.today().isoformat(),
        "reviewer": a.reviewer,
        "review_csv": str(a.review),
        "population": "model-drawn outlines above max_candidate_m2 with no mapped solar within "
                      "min_distance_m of them (export.new_lead_mask)",
        "max_candidate_m2": float(MAX_CANDIDATE_M2),
        "min_distance_m": float(a.min_distance_m),
        "mapped_reference": str(a.labels),
        "census_min_area_m2": float(census["area_m2"].min()),
        "census_n": int(len(census)),
        "census_real": int(census["real"].sum()),
        "sample_design": f"probability proportional to area, without replacement, seed {a.seed}, "
                         "from the outlines below the census",
        "sample_n": int(len(sample)),
        "sample_real": int(sample["real"].sum()),
        "excluded_regions": sorted(excluded),
        "excluded_sample_n": int(len(ex)),
        "excluded_sample_real": int(ex["real"].sum()),
    }
    p = cc.oversize_review_p_real(block)
    d = cc.oversize_review_draws(block, 4000)
    block["p_real_census"] = round(p["census"], 4)
    block["p_real_sample"] = round(p["sample"], 4)
    lo, hi = np.percentile(d["sample"], cc.CI_PCT)
    block["p_real_sample_lo"], block["p_real_sample_hi"] = round(float(lo), 4), round(float(hi), 4)
    path = cc.default_table_path(a.aoi)
    table = cc.load_table(path)
    table[cc.OVERSIZE_REVIEW_KEY] = block
    cc.write_table(table, path)
    adm = pool[~pool["region"].isin(excluded)]
    big = adm["area_m2"] >= block["census_min_area_m2"]
    km2 = adm.loc[big, "area_m2"].sum() / 1e6 * p["census"] + adm.loc[~big, "area_m2"].sum() / 1e6 * p["sample"]
    print(f"census {block['census_real']}/{block['census_n']} real; sample {block['sample_real']}/"
          f"{block['sample_n']} = {p['sample']:.3f} (90% {lo:.3f}-{hi:.3f}); excluded regions "
          f"{block['excluded_sample_real']}/{block['excluded_sample_n']} real. Admits {len(adm)} of "
          f"{len(pool)} outlines, {km2:.1f} km2 credited -> {path}")
    return 0


# --------------------------------------------------------------------------------------
# The review package: four panels per outline on disk, and the page to judge them in
# --------------------------------------------------------------------------------------
PANEL = 480
CONTEXT_MIN_M = 1500.0  # the context panels show at least this much ground
DETAIL_M = 1280.0       # the detail panel: native 10 m pixels around the outline's centre
# A FIXED reflectance stretch (L2A DN minus the 1,000 BOA offset, over 10,000), so a panel
# block reads as dark on every crop. India's first review used a per-crop percentile stretch,
# under which dark ploughed fields and burn scars looked like panels.
TRUE_RGB = (("B04", 0.30), ("B03", 0.28), ("B02", 0.26))
FALSE_RGB = (("B12", 0.45), ("B08", 0.50), ("B04", 0.30))
YELLOW = (255, 214, 0)

GUIDE = r"""      <ul>
        <li><b>PV</b>: a solar park inside the yellow outline. On the composite, blocks of
          even dark blue-grey with straight edges, a grid of access roads and small bright
          inverter pads; dark purple in the false colour; rows of panels on Esri. The outline
          is the model's and may be ragged or leave gaps: judge whether a park is there, not
          how well it is traced.</li>
        <li><b>Not PV</b>: something else, typically dark ploughed fields, water or aquaculture
          ponds, burn scars, rock, a shaded slope, snow, a riverbed or greenhouses. Fields are
          dark only in true colour; water is dark in every panel.</li>
        <li><b>Unsure</b>: these four panels cannot settle it. Open the links, decide, and
          change the verdict; an outline left unsure cannot be priced.</li>
      </ul>
      <p>The composite is the imagery the model read, so it shows parks built after the Esri
        capture: panels on the composite and bare or freshly cleared ground on an older Esri
        image is a park built since. Keys: <kbd>1</kbd> PV, <kbd>2</kbd> Not PV,
        <kbd>3</kbd> unsure, <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step, <kbd>n</kbd> note.</p>
      <p>When done, export <code>verdicts.csv</code> into
        <code>results/__AOI___oversize_review/</code> and run
        <code>oversize_review.py apply --verdicts</code>. Progress also stays in this browser.</p>"""


def cmd_package(a) -> int:
    """Render every row of review.csv and write the page, the JOSM GeoJSON and the codes."""
    import geopandas as gpd
    import pandas as pd

    sys.path.insert(0, str(REPO / "scripts"))
    from build_review_page import write_page

    from earthpv.config import Settings
    from earthpv.density import _grid_origin

    path = a.out / "review.csv"
    rev = pd.read_csv(path)
    if "code" not in rev.columns:
        rev.insert(0, "code", [f"{s[0]}{k:02d}" for s, k in zip(rev.stratum, rev.k)])
        rev.to_csv(path, index=False)
    cands = gpd.read_parquet(REPO / f"data/predictions/{a.aoi}/candidates.parquet",
                             columns=["geometry"])
    geoms = cands.geometry.loc[rev.candidate_index].to_numpy()
    s = Settings.load()
    cfg = s.aois[a.aoi]
    origin = _grid_origin(a.aoi, cfg, s)
    window = cfg.get("compose_window")
    epoch = (f"{_month(window[0])} to {_month(window[1])}" if window else "the imagery window")
    pkg = REPO / "data" / "oversize_review" / a.aoi
    (pkg / "crops").mkdir(parents=True, exist_ok=True)
    comp = REPO / f"data/composites/{a.aoi}/composites"
    items, dates = [], []
    for r, g in zip(rev.itertuples(), geoms):
        jpg = pkg / "crops" / f"{r.code}.jpg"
        meta = pkg / "crops" / f"{r.code}.esri"
        if a.force or not jpg.exists():
            esri_date = _render(g, comp, origin, epoch, jpg, esri=not a.no_esri)
            meta.write_text(esri_date or "")
        esri_date = meta.read_text().strip() if meta.exists() else ""
        dates.append(esri_date)
        w, so, e, n = g.bounds
        p = g.representative_point()
        items.append({
            "code": r.code, "img": f"crops/{r.code}.jpg", "date": esri_date,
            "date_label": (f"{r.area_m2 / 1e4:,.0f} ha · {r.region} · Esri "
                           f"{esri_date or 'not fetched'}"),
            "lon": round(p.x, 6), "lat": round(p.y, 6),
            "bbox": [round(w - 0.002, 6), round(so - 0.002, 6), round(e + 0.002, 6),
                     round(n + 0.002, 6)],
        })
    page = write_page(pkg / "index.html", f"{a.aoi}_oversize_review", items,
                      guide=GUIDE.replace("__AOI__", a.aoi))
    rev["esri_date"] = dates
    gj = gpd.GeoDataFrame({
        "name": [f"{c} {v}" if isinstance(v, str) and v else c for c, v in zip(rev.code, rev.verdict)],
        "review_verdict": rev.verdict, "review_evidence": rev.evidence, "esri_date": rev.esri_date,
        "stratum": rev.stratum, "k": rev.k, "area_ha": (rev.area_m2 / 1e4).round(1),
        "region": rev.region, "candidate_index": rev.candidate_index,
    }, geometry=geoms, crs="EPSG:4326")
    gj.to_file(a.out / "review.geojson", driver="GeoJSON")
    print(f"{len(items)} outlines -> {page} (crops in {pkg / 'crops'}); JOSM layer "
          f"{a.out / 'review.geojson'}. Do not upload that layer: the outlines are the model's.")
    return 0


def _month(day: str) -> str:
    from datetime import date as _d

    return _d.fromisoformat(day).strftime("%b %Y")


def _render(geom, comp_dir: Path, origin, epoch: str, out: Path, esri: bool = True) -> str | None:
    """One outline's four panels as a 2 x 2 JPEG. Returns the Esri capture date, if fetched."""
    from PIL import Image
    from pyproj import Transformer

    rep = geom.representative_point()
    utm = f"EPSG:{(32600 if rep.y >= 0 else 32700) + int((rep.x + 180) // 6) + 1}"
    to_utm = Transformer.from_crs("EPSG:4326", utm, always_xy=True)
    gu = _transform(geom, to_utm)
    x0, y0, x1, y1 = gu.bounds
    side = max(CONTEXT_MIN_M, 1.25 * max(x1 - x0, y1 - y0))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = to_utm.transform(rep.x, rep.y)
    bands = sorted({b for b, _ in TRUE_RGB + FALSE_RGB})
    ctx, ctx_tf = _s2_window(comp_dir, origin, utm, cx, cy, side, bands)
    det, det_tf = _s2_window(comp_dir, origin, utm, rx, ry, DETAIL_M, bands)
    km = f"{side / 1000:.1f} km across"
    panels = [
        _caption(_outline(_rgb(ctx, bands, TRUE_RGB), gu, ctx_tf), f"Sentinel-2 {epoch}, {km}"),
        _caption(_outline(_rgb(det, bands, TRUE_RGB), gu, det_tf),
                 f"10 m pixels, {DETAIL_M / 1000:.1f} km across"),
        _caption(_outline(_rgb(ctx, bands, FALSE_RGB), gu, ctx_tf),
                 "false colour: SWIR, NIR, red"),
    ]
    esri_date = None
    if esri:
        im, esri_date = _esri(geom, rep, side)
        panels.append(_caption(im, f"Esri World Imagery {esri_date or '(no capture date)'}"
                               if im is not None else "Esri imagery unavailable"))
    if len(panels) < 4 or panels[3] is None:
        panels = panels[:3] + [_caption(Image.new("RGB", (PANEL, PANEL), (40, 40, 40)),
                                        "Esri not fetched")]
    sheet = Image.new("RGB", (2 * PANEL, 2 * PANEL))
    for i, p in enumerate(panels):
        sheet.paste(p, ((i % 2) * PANEL, (i // 2) * PANEL))
    sheet.save(out, "JPEG", quality=86)
    return esri_date


def _transform(geom, tr):
    from shapely.ops import transform

    return transform(lambda x, y, z=None: tr.transform(x, y), geom)


def _s2_window(comp_dir: Path, origin, utm: str, cx: float, cy: float, side: float, bands):
    """The composite cells under a square window, mosaicked onto one PANEL x PANEL grid in
    the outline's own UTM zone (a window can cross cells, and cells can sit in other zones)."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject, transform_bounds

    from earthpv.config import LOCAL_BANDS

    res = side / PANEL
    tf = from_origin(cx - side / 2, cy + side / 2, res, res)
    out = np.zeros((len(bands), PANEL, PANEL), "float32")
    w, s, e, n = transform_bounds(utm, "EPSG:4326", cx - side / 2, cy - side / 2,
                                  cx + side / 2, cy + side / 2)
    ox, oy = origin
    rs = Resampling.nearest if res <= 10.0 else Resampling.average
    for i in range(int((w - ox) // 0.1), int((e - ox) // 0.1) + 1):
        for j in range(int((s - oy) // 0.1), int((n - oy) // 0.1) + 1):
            f = comp_dir / f"{i:04d}_{j:04d}" / "composite_0.tif"
            if not f.exists():
                continue
            with rasterio.open(f) as src:
                for k, b in enumerate(bands):
                    tmp = np.zeros((PANEL, PANEL), "float32")
                    reproject(rasterio.band(src, LOCAL_BANDS.index(b) + 1), tmp, src_nodata=0,
                              dst_nodata=0, dst_transform=tf, dst_crs=utm, resampling=rs)
                    out[k] = np.where(out[k] == 0, tmp, out[k])
    return out, tf


def _rgb(arr, bands, spec):
    import numpy as np
    from PIL import Image

    chans = []
    for b, top in spec:
        dn = arr[bands.index(b)]
        refl = np.clip((dn - 1000.0) / 10000.0, 0.0, None)
        chans.append(np.where(dn > 0, np.clip(refl / top, 0, 1) * 255, 40))
    return Image.fromarray(np.stack(chans, -1).astype("uint8"))


def _outline(im, geom_utm, tf):
    from PIL import ImageDraw

    d = ImageDraw.Draw(im)
    inv = ~tf
    for part in getattr(geom_utm, "geoms", [geom_utm]):
        for ring in [part.exterior, *part.interiors]:
            d.line([inv * xy for xy in ring.coords], fill=YELLOW, width=2)
    return im


def _caption(im, text: str):
    from PIL import ImageDraw, ImageFont

    if im is None:
        return None
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=15)
    d.rectangle([0, PANEL - 24, PANEL, PANEL], fill=(0, 0, 0))
    d.text((6, PANEL - 21), text, fill=(255, 255, 255), font=font)
    return im


def _esri(geom, rep, side: float):
    """Esri World Imagery over the context window (Web Mercator, so the crop is square), the
    outline drawn on it, and the capture date at the outline's centre (the calibration
    sampler's own query). (None, None) on any network failure."""
    import io
    import math
    import urllib.request

    from PIL import Image, ImageDraw
    from pyproj import Transformer

    sys.path.insert(0, str(REPO / "scripts"))
    from propose_calibration_candidates import esri_capture

    to_m = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    gm = _transform(geom, to_m)
    x0, y0, x1, y1 = gm.bounds
    half = side / math.cos(math.radians(rep.y)) / 2
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bbox = (cx - half, cy - half, cx + half, cy + half)
    url = ("https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
           f"?bbox={','.join(f'{v:.2f}' for v in bbox)}&bboxSR=3857&imageSR=3857"
           f"&size={PANEL},{PANEL}&format=jpg&f=image")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "earthpv-oversize-review"})
        im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=60).read())).convert("RGB")
    except Exception:  # noqa: BLE001 -- the panel says it is missing; the review goes on
        return None, None
    d = ImageDraw.Draw(im)
    scale = PANEL / (2 * half)
    for part in getattr(gm, "geoms", [gm]):
        for ring in [part.exterior, *part.interiors]:
            d.line([((x - bbox[0]) * scale, (bbox[3] - y) * scale) for x, y in ring.coords],
                   fill=YELLOW, width=2)
    cap = esri_capture(rep.x, rep.y)
    return im, (cap["date"].isoformat() if cap else None)


def _merge_page_verdicts(rev, verdicts: Path, unsure_as: str | None, reviewer: str):
    """The page's export (`code,imagery_date,verdict,note`) into review.csv's rows."""
    import pandas as pd

    v = pd.read_csv(verdicts, dtype=str).fillna("").set_index("code")
    missing = sorted(set(rev.code) - set(v.index[v.verdict != ""]))
    if missing:
        raise SystemExit(f"{len(missing)} outlines have no verdict in {verdicts}: {missing[:8]}")
    page = v.loc[rev.code, "verdict"].map({"pv": "pv", "no_pv": "not_pv", "unsure": "unsure"})
    unsure = list(rev.code[(page == "unsure").to_numpy()])
    if unsure and unsure_as is None:
        raise SystemExit(f"{len(unsure)} outlines are unsure ({unsure[:8]}): settle them on the "
                         "linked imagery, or pass --unsure-as not_pv to price them as absent")
    page = page.replace("unsure", unsure_as or "unsure").to_numpy()
    prev = rev["verdict"].fillna("").to_numpy()
    judged = prev != ""
    if judged.any():
        agree = (prev[judged] == page[judged]).sum()
        print(f"{reviewer} agrees with the earlier verdicts on {agree} of {judged.sum()} outlines; "
              f"they differ on {', '.join(rev.code[judged & (prev != page)]) or 'none'}")
        rev["verdict_prev"] = prev
    rev["verdict"] = page
    note = v.loc[rev.code, "note"].to_numpy()
    rev["evidence"] = [f"{reviewer}: {n}" if n else f"{reviewer}" for n in note]
    for c in unsure:
        rev.loc[rev.code == c, "evidence"] += f" (unsure, priced as {unsure_as})"
    return rev

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("draw", "package", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--aoi", required=True)
        p.add_argument("--labels", type=Path, default=None,
                       help="the mapped reference (default data/labels/<aoi>_overpass_solar.parquet)")
        p.add_argument("--min-distance-m", type=float, default=100.0)
        p.add_argument("--seed", type=int, default=20261028)
    d = sub.choices["draw"]
    d.add_argument("--census-n", type=int, default=30)
    d.add_argument("--sample-n", type=int, default=60)
    d.add_argument("--redraw", action="store_true",
                   help="draw a new sample over an existing review.csv (its verdicts are lost)")
    for name in ("draw", "package"):
        q = sub.choices[name]
        q.add_argument("--out", type=Path, default=None)
        q.add_argument("--no-esri", action="store_true", help="leave the Esri panel out (offline)")
        q.add_argument("--force", action="store_true", help="re-render crops that exist")
    p = sub.choices["apply"]
    p.add_argument("--review", type=Path, default=None)
    p.add_argument("--verdicts", type=Path, default=None,
                   help="the review page's export (code,imagery_date,verdict,note)")
    p.add_argument("--unsure-as", choices=VERDICTS, default=None,
                   help="price an outline left unsure as this verdict (default: refuse)")
    p.add_argument("--exclude-region", action="append", default=[])
    p.add_argument("--reviewer", required=True)
    a = ap.parse_args()
    a.labels = a.labels or Path(f"data/labels/{a.aoi}_overpass_solar.parquet")
    if a.cmd in ("draw", "package"):
        a.out = a.out or REPO / "results" / f"{a.aoi}_oversize_review"
        return cmd_draw(a) if a.cmd == "draw" else cmd_package(a)
    a.review = a.review or Path(f"results/{a.aoi}_oversize_review/review.csv")
    return cmd_apply(a)


if __name__ == "__main__":
    raise SystemExit(main())
