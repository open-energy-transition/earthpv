"""Audit each training source's labels for unmapped PV that a chip would train as background.

A chip burns every mapped installation as 1 and everything else as 0. Where a source maps only
some of its PV, the rest is taught as "not PV", and the cost lands on rooftops: v18, which
pooled every country, lost 10 points of rooftop recall at matched precision, and most of the
rows it added came from sources whose mapped installations are 3-19% rooftop (docs/experiments.md,
"One segmentation model for every country? v18 pooled"). This measures that per source before
a new corpus is built:

    run       one fixed detector (v14, released) over each source's chips: per chip, the share
              of mapped PV it finds (its sensitivity there) and every confident blob of 400 m2
              or more no label or ignore region touches (`blobs.parquet`, `chips.parquet`).
              Chips within one chip width of a v14 training chip are skipped: there v14 has
              learned to output 0 on whatever the labels left out.
    buildings each blob's share on a VIDA footprint: an unlabelled blob on a roof is either
              unmapped rooftop PV or a rooftop false positive, the class pooling hurt.
    mastr     Germany only: the register geolocates units of 30 kWp and more, so (a) how many
              unlabelled blobs carry a registered unit (the detector is right, the label is
              missing) and (b), with no model at all, how many registered rooftop units of
              72 kWp and more (about 400 m2) sit on pixels a chip trains as background.
    mastr-null the chance term for (a): undetected, unlabelled footprints of the same size in
              the same chips (large German roofs carry registered PV often).
    summary   one row per source (`results/label_audit/summary.csv`).

An unlabelled blob is unmapped PV or a false positive; outside Germany nothing here separates
the two, so `review` draws a random sample of roof blobs per source onto Esri imagery.

    pixi run python scripts/label_audit.py run          # GPU, ~30 min
    pixi run python scripts/label_audit.py buildings    # CPU, VIDA per country
    pixi run python scripts/label_audit.py mastr
    pixi run python scripts/label_audit.py mastr-null   # chance term for the blob match
    pixi run python scripts/label_audit.py summary
    pixi run python scripts/label_audit.py review       # Esri crops, data/label_audit/review/
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

log = logging.getLogger("label_audit")

OUT = REPO / "data" / "label_audit"
RESULTS = REPO / "results" / "label_audit"
V14 = REPO / "data/models/release/earthpv_segmentation_v14.ckpt"
V14_CORPUS = REPO / "data/chips/combined_south_africa/index.parquet"
SOURCES = [  # (source, chip index, VIDA iso3)
    ("france", "data/chips/combined_pooled_v18/index.parquet", "FRA"),
    ("south_africa", "data/chips/combined_pooled_v18/index.parquet", "ZAF"),
    ("germany", "data/chips/combined_pooled_v18/index.parquet", "DEU"),
    ("germany_national", "data/chips/combined_pooled_v18/index.parquet", "DEU"),
    ("pakistan_fresh", "data/chips/combined_pooled_v18/index.parquet", "PAK"),
    ("punjab", "data/chips/combined_pooled_v18/index.parquet", "PAK"),
    ("gujarat", "data/chips/combined_pooled_v18/index.parquet", "IND"),
    ("india", "data/chips/combined_pooled_v18/index.parquet", "IND"),
    ("poland", "data/chips/combined_pooled_v18/index.parquet", "POL"),
    ("vietnam", "data/chips/combined_pooled_v18/index.parquet", "VNM"),
    ("morocco", "data/chips/combined_pooled_v18/index.parquet", "MAR"),
    ("egypt", "data/chips/combined_pooled_v18/index.parquet", "EGY"),
    ("yemen", "data/chips/combined_pooled_v18/index.parquet", "YEM"),
    ("nigeria", "data/chips/combined_pooled_v18/index.parquet", "NGA"),
    ("zambia", "data/chips/combined_pooled_v18/index.parquet", "ZMB"),
    ("namibia", "data/chips/namibia/index.parquet", "NAM"),
]
CHIP_M = 2240.0  # chip edge; a chip centre closer than this to a v14 train chip overlaps it
MIN_BLOB_PX = 4  # 400 m2 at 10 m
LABEL_HALO_PX = 3  # a blob within 30 m of a label or ignore region is that label's spill
ROOF_FRAC = 0.25  # blob share on a footprint that makes it a roof blob
MASTR_DB = Path.home() / ".open-MaStR/data/sqlite/open-mastr.db"
MASTR_CUTOFF = "2025-04-01"  # start of Germany's compose window (2025-04-01 to 2025-09-30)
MASTR_MATCH_M = 30.0
ROOF_UNIT_MIN_KWP = 72.0  # ~400 m2 of module at 0.18 kWp/m2


def _xy_m(lon, lat, lat0):
    """Equirectangular metres, adequate for a nearest-chip test at the 2 km scale."""
    k = 111_320.0
    return np.column_stack([np.asarray(lon) * k * np.cos(np.radians(lat0)), np.asarray(lat) * k])


def select_chips(per_source: int, seed: int) -> pd.DataFrame:
    from scipy.spatial import cKDTree

    v14 = pd.read_parquet(V14_CORPUS)
    v14 = v14[v14.split == "train"]
    rows = []
    for src, idx, iso3 in SOURCES:
        d = pd.read_parquet(REPO / idx)
        key = next((k for k in ("source", "aoi") if k in d.columns), None)
        if key:  # a single-country index (namibia) carries neither column
            d = d[d[key] == src]
        d = d.drop_duplicates("chip_id").copy()  # the pooled index repeats small sources
        d["source"], d["iso3"] = src, iso3
        n_all = len(d)
        # nearest v14 train chip, in metres around this source's own latitude
        lat0 = float(d.lat.median())
        tree = cKDTree(_xy_m(v14.lon, v14.lat, lat0))
        dist, _ = tree.query(_xy_m(d.lon, d.lat, lat0))
        d["v14_dist_m"] = dist
        d = d[d.v14_dist_m >= CHIP_M]
        log.info("%s: %d chips, %d clear of v14's training chips", src, n_all, len(d))
        if len(d) > per_source:
            d = d.sample(per_source, random_state=seed)
        d["n_source_chips"], d["n_clear_of_v14"] = n_all, int((dist >= CHIP_M).sum())
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


def cmd_run(a) -> None:
    import rasterio
    import rasterio.features
    import torch
    from scipy import ndimage
    from shapely.geometry import shape

    from earthpv.infer import load_model

    OUT.mkdir(parents=True, exist_ok=True)
    chips = select_chips(a.per_source, a.seed)
    task, device, _ = load_model(Path(a.ckpt), task_type="auto")
    eight = np.ones((3, 3), bool)
    chip_rows, blob_rows = [], []
    t0 = time.time()
    for i, row in enumerate(chips.itertuples(index=False)):
        with rasterio.open(row.image) as src:
            arr = src.read().astype("float32")
            transform, crs = src.transform, src.crs
        with rasterio.open(row.mask) as src:
            mask = src.read(1).astype("int16")
        x = torch.from_numpy(arr / 10000.0)[None].to(device)
        with torch.no_grad(), torch.autocast(device_type=device, enabled=device == "cuda"):
            out = task(x)
            logits = out.output if hasattr(out, "output") else out
            prob = torch.softmax(logits.float(), 1)[0, 1].cpu().numpy()
        pred = prob >= a.threshold

        lab, n_lab = ndimage.label(mask == 1, structure=eight)
        hit = np.unique(lab[pred & (lab > 0)])
        near = ndimage.binary_dilation(mask != 0, structure=eight, iterations=LABEL_HALO_PX)
        comp, n_comp = ndimage.label(pred, structure=eight)
        touching = set(np.unique(comp[near & (comp > 0)]).tolist())
        sizes = np.bincount(comp.ravel(), minlength=n_comp + 1)
        keep = [c for c in range(1, n_comp + 1) if sizes[c] >= MIN_BLOB_PX and c not in touching]
        if keep:
            sel = np.isin(comp, keep)
            for geom, cid in rasterio.features.shapes(comp.astype("int32"), mask=sel,
                                                      connectivity=8, transform=transform):
                cid = int(cid)
                px = comp == cid
                blob_rows.append(dict(
                    source=row.source, iso3=row.iso3, chip_id=row.chip_id, kind=row.kind,
                    split=row.split, crs=crs.to_string(), blob=cid, area_px=int(sizes[cid]),
                    max_prob=float(prob[px].max()), mean_prob=float(prob[px].mean()),
                    geometry=shape(geom)))
        chip_rows.append(dict(
            source=row.source, iso3=row.iso3, chip_id=row.chip_id, kind=row.kind,
            split=row.split, lon=row.lon, lat=row.lat, mask=row.mask, v14_dist_m=row.v14_dist_m,
            n_source_chips=row.n_source_chips, n_clear_of_v14=row.n_clear_of_v14,
            label_px=int((mask == 1).sum()), ignore_px=int((mask == -1).sum()),
            label_px_found=int((pred & (mask == 1)).sum()), n_labels=int(n_lab),
            n_labels_found=int((hit > 0).sum()), pred_px=int(pred.sum()),
            blobs=len(keep), blob_px=int(sum(sizes[c] for c in keep))))
        if (i + 1) % 500 == 0:
            log.info("%d/%d chips, %.0f s", i + 1, len(chips), time.time() - t0)

    pd.DataFrame(chip_rows).to_parquet(OUT / "chips.parquet")
    if blob_rows:
        b = pd.DataFrame(blob_rows)
        # each chip has its own UTM grid: reproject per CRS, then store in lon/lat
        parts = [gpd.GeoDataFrame(g, geometry="geometry", crs=c).to_crs("EPSG:4326")
                 for c, g in b.groupby("crs")]
        gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326").to_parquet(
            OUT / "blobs.parquet")
    log.info("wrote %s (%d chips, %d blobs) in %.0f s", OUT, len(chip_rows), len(blob_rows),
             time.time() - t0)


def cmd_buildings(a) -> None:
    from earthpv import overture
    from earthpv.buildings import fetch_vida_near

    blobs = gpd.read_parquet(OUT / "blobs.parquet")
    con = overture.connect()
    out = []
    for iso3, g in blobs.groupby("iso3"):
        t0 = time.time()
        bld = fetch_vida_near(g.geometry, iso3, buffer_m=50.0, con=con, progress=False)
        utm = g.estimate_utm_crs()
        gm = g.to_crs(utm)
        g = g.copy()
        g["roof_frac"], g["largest_roof_m2"] = 0.0, 0.0
        if len(bld):
            bm = bld.to_crs(utm)
            pairs = gpd.sjoin(gm[["geometry"]], bm[["geometry"]], predicate="intersects")
            for bi, grp in pairs.groupby(level=0):
                roofs = bm.geometry.loc[grp.index_right.to_numpy()]
                inter = gm.geometry.loc[bi].intersection(roofs.union_all()).area
                g.loc[bi, "roof_frac"] = inter / gm.geometry.loc[bi].area
                g.loc[bi, "largest_roof_m2"] = float(roofs.area.max())
        g["roof"] = g.roof_frac >= ROOF_FRAC
        log.info("%s: %d blobs, %d buildings, %d on a roof (%.0f s)", iso3, len(g), len(bld),
                 int(g.roof.sum()), time.time() - t0)
        out.append(g)
    gpd.GeoDataFrame(pd.concat(out), crs="EPSG:4326").to_parquet(OUT / "blobs.parquet")


def _mastr(art: str | None, min_kwp: float) -> gpd.GeoDataFrame:
    import sqlite3

    con = sqlite3.connect(MASTR_DB)
    try:
        where = "AND ArtDerSolaranlage = ?" if art else ""
        params = ([art] if art else []) + [MASTR_CUTOFF, min_kwp]
        df = pd.read_sql(
            f"""SELECT Laengengrad AS lon, Breitengrad AS lat, Bruttoleistung AS kwp,
                       ArtDerSolaranlage AS art
                FROM solar_extended
                WHERE Laengengrad IS NOT NULL AND Breitengrad IS NOT NULL {where}
                  AND Inbetriebnahmedatum <= ? AND Bruttoleistung >= ?""",
            con, params=params)
    finally:
        con.close()
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")


def cmd_mastr(a) -> None:
    import rasterio
    from scipy import ndimage

    units = _mastr(None, 30.0)
    log.info("%d geolocated MaStR units >= 30 kWp commissioned by %s", len(units), MASTR_CUTOFF)
    utm = "EPSG:32632"
    um = units.to_crs(utm)

    blobs = gpd.read_parquet(OUT / "blobs.parquet")
    de = blobs.iso3 == "DEU"
    bm = blobs[de].to_crs(utm)
    near = gpd.sjoin_nearest(bm[["geometry"]], um[["geometry", "kwp"]], how="left",
                             max_distance=MASTR_MATCH_M, distance_col="mastr_dist_m")
    near = near[~near.index.duplicated()]
    blobs["mastr_unit"] = pd.NA
    blobs.loc[de, "mastr_unit"] = near.mastr_dist_m.notna().to_numpy()
    blobs.to_parquet(OUT / "blobs.parquet")

    # Model-free: registered rooftop units >= 72 kWp inside each audited German chip, by the
    # mask value under them (label / ignore / background clear of any label).
    chips = pd.read_parquet(OUT / "chips.parquet")
    roof_units = units[(units.art == "Gebäudesolaranlage") & (units.kwp >= ROOF_UNIT_MIN_KWP)]
    eight = np.ones((3, 3), bool)
    rows = []
    for c in chips[chips.iso3 == "DEU"].itertuples(index=False):
        with rasterio.open(c.mask) as src:
            mask = src.read(1).astype("int16")
            t, crs, bounds = src.transform, src.crs, src.bounds
        pts = roof_units.to_crs(crs).cx[bounds.left:bounds.right, bounds.bottom:bounds.top]
        if pts.empty:
            continue
        halo = ndimage.binary_dilation(mask != 0, structure=eight, iterations=LABEL_HALO_PX)
        for p, kwp in zip(pts.geometry, pts.kwp):
            r, col = rasterio.transform.rowcol(t, p.x, p.y)
            if not (0 <= r < mask.shape[0] and 0 <= col < mask.shape[1]):
                continue
            v = int(mask[r, col])
            where = ("label" if v == 1 else "ignore" if v == -1
                     else "near_label" if halo[r, col] else "background")
            rows.append(dict(source=c.source, chip_id=c.chip_id, kind=c.kind, kwp=kwp,
                             under=where))
    pd.DataFrame(rows).to_parquet(OUT / "mastr_roof_units.parquet")
    log.info("%d registered rooftop units >= %.0f kWp inside audited German chips", len(rows),
             ROOF_UNIT_MIN_KWP)


NULL_BINS = [400, 1000, 2000, 5000, 10000, np.inf]  # building m2


def cmd_mastr_null(a) -> None:
    """The chance term for `mastr`'s blob match: large German roofs carry registered PV often,
    so a roof blob near a unit is partly coincidence. Land-use matched, as
    scripts/mastr_p_unmapped.py does it: footprints in the SAME chips as the roof blobs, the
    same size bin, that no blob touches and that lie clear of every label and ignore region
    (the blobs' own condition). The size bin of a blob is its largest roof. Corrected share
    (obs - f) / (1 - f), a lower bound."""
    import rasterio
    import rasterio.features
    from scipy import ndimage
    from shapely.geometry import box, shape
    from shapely.ops import transform as sh_transform
    from pyproj import Transformer

    from earthpv import overture
    from earthpv.buildings import fetch_vida_near

    units = _mastr(None, 30.0)
    blobs = gpd.read_parquet(OUT / "blobs.parquet")
    de = blobs[blobs.iso3 == "DEU"]
    roof = de[de.roof.fillna(False)].copy()
    chips = pd.read_parquet(OUT / "chips.parquet")
    keys = set(zip(roof.source, roof.chip_id))
    chips = chips[[k in keys for k in zip(chips.source, chips.chip_id)]]

    eight = np.ones((3, 3), bool)
    meta, foot = [], []
    for c in chips.itertuples(index=False):
        with rasterio.open(c.mask) as src:
            mask = src.read(1).astype("int16")
            t, crs, bnd = src.transform, src.crs, src.bounds
        halo = ndimage.binary_dilation(mask != 0, structure=eight, iterations=LABEL_HALO_PX)
        hshapes = [shape(g) for g, v in rasterio.features.shapes(
            halo.astype("uint8"), mask=halo, transform=t) if v == 1]
        meta.append((c.source, c.chip_id, crs, box(*bnd), hshapes))
        to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
        foot.append(sh_transform(to_ll, box(*bnd)))
    log.info("%d German chips hold the %d roof blobs", len(meta), len(roof))
    bld = fetch_vida_near(gpd.GeoSeries(foot, crs="EPSG:4326"), "DEU", buffer_m=0.0,
                          con=overture.connect(), progress=False)
    log.info("%d VIDA footprints in those chips", len(bld))

    rows = []
    for src_name, chip_id, crs, cbox, hshapes in meta:
        b = bld.to_crs(crs)
        b = b[b.geometry.centroid.within(cbox)]
        b = b[b.geometry.area >= NULL_BINS[0]]
        cb = de[(de.source == src_name) & (de.chip_id == chip_id)].to_crs(crs)
        drop = b.geometry.intersects(cb.geometry.union_all()) if len(cb) else False
        if hshapes:
            drop = drop | b.geometry.intersects(gpd.GeoSeries(hshapes, crs=crs).union_all())
        b = b[~drop]
        if b.empty:
            continue
        u = units.to_crs(crs).cx[cbox.bounds[0] - 50:cbox.bounds[2] + 50,
                                 cbox.bounds[1] - 50:cbox.bounds[3] + 50]
        hit = np.zeros(len(b), bool)
        if len(u):
            j = gpd.sjoin(gpd.GeoDataFrame(geometry=b.geometry.buffer(MASTR_MATCH_M).values,
                                           crs=crs), u[["geometry"]], predicate="intersects")
            hit[np.unique(j.index.to_numpy())] = True
        rows.append(pd.DataFrame(dict(source=src_name, chip_id=chip_id,
                                      area_m2=b.geometry.area.to_numpy(), mastr_unit=hit)))
    null = pd.concat(rows, ignore_index=True)
    null["bin"] = pd.cut(null.area_m2, NULL_BINS, right=False)
    roof["bin"] = pd.cut(roof.largest_roof_m2, NULL_BINS, right=False)
    roof["mastr_unit"] = roof.mastr_unit.astype(bool)
    out = []
    for src_name in sorted(roof.source.unique()):
        r = roof[roof.source == src_name]
        n = null[null.source == src_name]
        per = (pd.DataFrame(dict(
            blobs=r.groupby("bin", observed=False).size(),
            obs=r.groupby("bin", observed=False).mastr_unit.mean(),
            null_roofs=n.groupby("bin", observed=False).size(),
            f=n.groupby("bin", observed=False).mastr_unit.mean())))
        per = per[per.blobs > 0]
        w = per.blobs / per.blobs.sum()
        f = float((w * per.f.fillna(0)).sum())
        obs = float(r.mastr_unit.mean())
        out.append(dict(source=src_name, roof_blobs=len(r), null_roofs=len(n), obs=round(obs, 3),
                        chance=round(f, 3), corrected=round((obs - f) / (1 - f), 3)))
        log.info("%s by size bin:\n%s", src_name, per.round(3).to_string())
    s = pd.DataFrame(out)
    s.to_csv(OUT / "mastr_null.csv", index=False)
    print(s.to_string(index=False))


def cmd_summary(a) -> None:
    chips = pd.read_parquet(OUT / "chips.parquet")
    blobs = gpd.read_parquet(OUT / "blobs.parquet")
    if "roof" not in blobs.columns:
        blobs["roof"] = pd.NA
    rows = []
    for src, c in chips.groupby("source", sort=False):
        b = blobs[blobs.source == src]
        n = len(c)
        r = dict(
            source=src, chips_in_source=int(c.n_source_chips.iloc[0]),
            clear_of_v14=int(c.n_clear_of_v14.iloc[0]), audited=n,
            labels=int(c.n_labels.sum()),
            label_recall=round(c.n_labels_found.sum() / max(c.n_labels.sum(), 1), 3),
            label_px_recall=round(c.label_px_found.sum() / max(c.label_px.sum(), 1), 3),
            unlabelled_blobs=len(b),
            roof_blobs=int(b.roof.fillna(False).sum()),
            roof_blobs_per_100_chips=round(100 * b.roof.fillna(False).sum() / n, 1),
            offroof_blobs_per_100_chips=round(100 * (~b.roof.fillna(False)).sum() / n, 1),
            # unlabelled blobs per mapped installation: how much of what the detector calls
            # PV here the map does not hold (inflated where the detector is imprecise)
            roof_blobs_per_label=round(b.roof.fillna(False).sum() / max(c.n_labels.sum(), 1), 3),
            blobs_per_label=round(len(b) / max(c.n_labels.sum(), 1), 3),
            # divided by the detector's own sensitivity on this source's mapped PV
            roof_blobs_per_label_sens_adj=round(
                b.roof.fillna(False).sum() / max(c.n_labels_found.sum(), 1), 3),
        )
        if "mastr_unit" in b.columns and b.mastr_unit.notna().any():
            r["blobs_with_register_unit"] = round(float(b.mastr_unit.dropna().astype(bool).mean()), 3)
            rb = b[b.roof.fillna(False)]
            if len(rb):
                r["roof_blobs_with_register_unit"] = round(
                    float(rb.mastr_unit.dropna().astype(bool).mean()), 3)
        rows.append(r)
    nf = OUT / "mastr_null.csv"
    null = pd.read_csv(nf).set_index("source") if nf.exists() else None
    s = pd.DataFrame(rows)
    if null is not None:
        s = s.merge(null[["chance", "corrected"]].add_prefix("roof_blob_register_"),
                    left_on="source", right_index=True, how="left")
    mu = OUT / "mastr_roof_units.parquet"
    if mu.exists():
        u = pd.read_parquet(mu)
        share = u.groupby("source").under.value_counts(normalize=True).unstack(fill_value=0)
        counts = u.groupby("source").size().rename("register_roof_units_ge72kwp")
        s = s.merge(counts, left_on="source", right_index=True, how="left")
        s = s.merge(share.add_prefix("register_roof_units_on_").round(3), left_on="source",
                    right_index=True, how="left")
    RESULTS.mkdir(parents=True, exist_ok=True)
    s.to_csv(RESULTS / "summary.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(s.T.to_string())


def cmd_review(a) -> None:
    """A RANDOM sample of unlabelled roof blobs per source on Esri imagery: one montage per
    source for a quick read, and the shared review page for verdicts. Random, not the most
    confident, so the share that is PV estimates the source's unlabelled-blob precision. Esri
    may predate the composite, so "no panel on Esri" is not proof of a false positive."""
    from PIL import Image, ImageDraw

    sys.path.insert(0, str(REPO / "scripts"))
    from build_review_page import write_page
    from oversize_review import _esri

    blobs = gpd.read_parquet(OUT / "blobs.parquet")
    roof = blobs[blobs.roof.fillna(False)]
    # shuffle once, then the first n per source (groupby.apply drops the key column here)
    sample = roof.sample(frac=1.0, random_state=a.seed).groupby("source").head(a.per_source)
    rdir = OUT / "review"
    rdir.mkdir(parents=True, exist_ok=True)
    items, rows, thumb = [], [], 240
    for src, g in sample.groupby("source"):
        sheet = Image.new("RGB", (4 * thumb, ((len(g) + 3) // 4) * (thumb + 18)), "white")
        for k, (_, b) in enumerate(g.iterrows()):
            code = f"{src}_{k:02d}"
            im, date = _esri(b.geometry, b.geometry.centroid, a.side_m)
            if im is None:  # Esri's export 500s past the deepest zoom it holds there
                im, date = _esri(b.geometry, b.geometry.centroid, 2 * a.side_m)
            rows.append(dict(code=code, source=src, chip_id=b.chip_id, kind=b.kind,
                             lon=b.geometry.centroid.x, lat=b.geometry.centroid.y,
                             area_px=b.area_px, mean_prob=b.mean_prob, roof_frac=b.roof_frac,
                             esri_date=date, fetched=im is not None))
            if im is None:
                continue
            im.save(rdir / f"{code}.jpg", quality=88)
            items.append(dict(code=code, img=f"{code}.jpg", date=date,
                              lon=b.geometry.centroid.x, lat=b.geometry.centroid.y))
            x, y = (k % 4) * thumb, (k // 4) * (thumb + 18)
            sheet.paste(im.resize((thumb, thumb)), (x, y + 18))
            ImageDraw.Draw(sheet).text((x + 4, y + 3), f"{k:02d}  {date or '?'}", fill="black")
        sheet.save(rdir / f"montage_{src}.jpg", quality=85)
        log.info("%s: %d crops", src, len(g))
    pd.DataFrame(rows).to_csv(RESULTS / "review_sample.csv", index=False)
    write_page(rdir / "index.html", "Unlabelled roof detections by training source", items,
               guide="<p>Each crop is a confident v14 detection on a building that no OSM label "
                     "in its training chip covers (yellow outline). <b>pv</b>: panels on the "
                     "roof inside or touching the outline; <b>no_pv</b>: no panels; "
                     "<b>unsure</b>: imagery too old or too coarse. A dated Esri capture "
                     "earlier than the composite can miss new PV.</p>")
    log.info("wrote %d crops and %s", len(items), rdir / "index.html")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--ckpt", default=str(V14))
    r.add_argument("--per-source", type=int, default=1500)
    r.add_argument("--threshold", type=float, default=0.5)
    r.add_argument("--seed", type=int, default=20261030)
    sub.add_parser("buildings")
    sub.add_parser("mastr")
    sub.add_parser("mastr-null")
    sub.add_parser("summary")
    v = sub.add_parser("review")
    v.add_argument("--per-source", type=int, default=12)
    v.add_argument("--side-m", type=float, default=240.0)
    v.add_argument("--seed", type=int, default=20261030)
    a = ap.parse_args()
    {"run": cmd_run, "buildings": cmd_buildings, "mastr": cmd_mastr, "mastr-null": cmd_mastr_null,
     "summary": cmd_summary,
     "review": cmd_review}[a.cmd](a)


if __name__ == "__main__":
    main()
