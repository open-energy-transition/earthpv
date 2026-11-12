"""Score segmentation checkpoints without charging them for PV the map does not hold.

`compare_backbones.py` counts every predicted pixel outside an OSM label as a false positive
and compares checkpoints at matched pixel precision. But the holdouts hold unmapped PV too,
above all on roofs (`scripts/label_audit.py`: about 10 unmapped rooftop arrays per mapped one in
Vietnam's chips, and 83% of Germany's registered rooftop units of 72 kWp or more on background
pixels). A model that learns to find them is charged for each one, must raise its threshold to
match the baseline's precision, and loses recall there: the comparison can hide exactly what a
label fix is for. This scores the same holdouts three more ways, from the same probabilities:

    roof-ignore precision  predicted pixels on an unlabelled VIDA building footprint are left out
                           of the false positives, as a corpus that burns those footprints as
                           ignore leaves them out of training. Each checkpoint is also compared at
                           the lowest threshold reaching the baseline's roof-ignore precision.
    roof firing rate       the guard on it: the share of unlabelled roof pixels a checkpoint flags.
                           Leaving roofs out of the precision lets a model that fires on every roof
                           look precise; this number shows it.
    register (Germany)     MaStR geolocates units of 30 kWp and more. Flagged pixels on a footprint
                           carrying a registered rooftop unit count as true (`register_precision`),
                           and registered rooftop units of 72 kWp or more (about 400 m2) are scored
                           as installations, mapped or not (`register recall`, paired McNemar on
                           the unmapped ones: the PV the labels left out, which the map cannot score).

Stages (all resumable; caches under data/fair_score/, a symlink onto /home):

    prep    CPU + network: per holdout chip set, the label mask, unlabelled-roof mask, the
            installations' pixels (as `evaluate` rasterizes them) and, for Germany, the
            registered-roof mask and register units.
    infer   GPU: each checkpoint's float32 PV probability per chip, exactly as `evaluate`
            computes it, cached by checkpoint file, so a later comparison reuses it.
    score   CPU: every metric at any threshold from the caches; writes
            results/fair_score/<name>/{pixels,installations,register_units}.csv, summary.json.

    pixi run python scripts/fair_score.py prep --aois germany france ...
    .pixi/envs/ml/bin/python scripts/fair_score.py infer --ckpt v14=<path> --aois ...
    pixi run python scripts/fair_score.py score --name <name> --ckpt v14=<path> ... --aois ... \\
        --match-aois south_africa france germany pakistan punjab gujarat

The first --ckpt is the baseline, scored at --threshold (0.3); `<chips>@<aoi>` scores a chip set
cut for an AOI under another directory, as in compare_backbones.

**Ensembles and test-time augmentation.** A checkpoint path may be several joined by `+`; score
averages their cached probabilities (no new inference), and infer fills each member's cache. A
member ending `#d4` (or `#flip`) is that checkpoint under test-time augmentation: infer averages
the probabilities over the 8 rotations and flips of each chip (or the 4 flips), mapped back, and
caches them apart from the plain pass. `--ckpt ens=<a>#d4+<b>#d4` is both at once. Verdicts stay with matched
standard precision; the fair rows say whether a verdict depends on what the map leaves out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from compare_backbones import SUBSETS, _bin, mcnemar_exact  # noqa: E402

log = logging.getLogger("fair_score")

CACHE = REPO / "data" / "fair_score"  # -> /home/tobi/earthpv_data/fair_score
RESULTS = REPO / "results" / "fair_score"
ISO3 = {"south_africa": "ZAF", "france": "FRA", "germany": "DEU", "pakistan": "PAK",
        "punjab": "PAK", "gujarat": "IND", "poland": "POL", "vietnam": "VNM", "india": "IND",
        "morocco": "MAR", "egypt": "EGY", "yemen": "YEM", "zambia": "ZMB", "nigeria": "NGA",
        "namibia": "NAM", "turkiye": "TUR", "spain": "ESP",
        "portugal": "PRT", "belgium": "BEL", "netherlands": "NLD", "luxembourg": "LUX",
        "italy": "ITA", "denmark": "DNK", "california": "USA", "texas": "USA", "mexico": "MEX"}
REGISTER_AOIS = {"germany"}
MASTR_MATCH_M = 30.0  # a unit's point is address-geocoded: nearest footprint within this
REG_ROOF_MIN_KWP = 30.0  # the register's coordinate floor
REG_UNIT_MIN_KWP = 72.0  # ~400 m2 of module at 0.18 kWp/m2: segmentation's population
NULL_MIN_M2 = 100.0  # smallest footprint kept for the chance term
NULL_BINS = [0, 400, 1000, 2000, 5000, 10000, np.inf]  # footprint m2
REG_DISC_M = 20.0  # a unit with no footprint is scored on a disc this wide around its point
# Thresholds: compare_backbones' grid plus a log-spaced fill, so matching is not coarse.
GRID = sorted(set(np.round(np.concatenate([
    [0.0003, 0.001, 0.003, 0.01, 0.03, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    np.geomspace(1e-4, 0.95, 61)]), 6).tolist()))


def _spec(x: str) -> tuple[str, str]:
    """`<chips>@<aoi>` -> (chip set, AOI); a bare name is both."""
    chips, _, aoi = x.partition("@")
    return chips, aoi or chips


def _val(chips: str) -> pd.DataFrame:
    index = pd.read_parquet(REPO / "data" / "chips" / chips / "index.parquet")
    val = index[index.split == "val"]
    if val.empty:  # as evaluate does
        val = index.sample(frac=0.2, random_state=42)
    return val.reset_index(drop=True)


def _labels(aoi: str) -> gpd.GeoDataFrame:
    """The labels `evaluate` scores a segmentation checkpoint against (rooftop and ground)."""
    from earthpv.chips import _newest_overpass_path, _overpass_labels
    from earthpv.config import Settings
    from earthpv.labels import resolve_aoi
    from earthpv.local_source import load_solar_labels

    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    path = _newest_overpass_path(aoi, REPO / "data" / "labels")
    if path.exists():
        labels = _overpass_labels(path)
    else:
        labels = load_solar_labels(Path(settings.raw["local_root"]) / cfg["source_region"])
    return labels[labels.placement.isin(["rooftop", "ground"])].reset_index(drop=True)


def _mastr_roof_units(min_kwp: float) -> gpd.GeoDataFrame:
    """Geolocated rooftop units, with their commissioning date: the holdout composites carry
    no acquisition date, so recall by year is what shows a unit built after the imagery."""
    import sqlite3

    from label_audit import MASTR_CUTOFF, MASTR_DB

    con = sqlite3.connect(MASTR_DB)
    try:
        df = pd.read_sql(
            """SELECT Laengengrad AS lon, Breitengrad AS lat, Bruttoleistung AS kwp,
                      Inbetriebnahmedatum AS commissioned
               FROM solar_extended
               WHERE Laengengrad IS NOT NULL AND Breitengrad IS NOT NULL
                 AND ArtDerSolaranlage = 'Gebäudesolaranlage'
                 AND Inbetriebnahmedatum <= ? AND Bruttoleistung >= ?""",
            con, params=[MASTR_CUTOFF, min_kwp])
    finally:
        con.close()
    u = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")
    u["unit"] = np.arange(len(u))
    return u


# ---------------------------------------------------------------------------------- prep

def _region(g, shape, t) -> np.ndarray | None:
    """A footprint's pixels by centre; one smaller than a pixel takes every pixel it touches."""
    import rasterio.features

    for touched in (False, True):
        m = rasterio.features.rasterize([(g, 1)], out_shape=shape, transform=t,
                                        all_touched=touched, dtype="uint8").astype(bool)
        if m.any():
            return m
    return None


def cmd_prep(a) -> None:
    import rasterio
    import rasterio.features
    import rasterio.warp
    from shapely.geometry import box

    from earthpv import overture
    from earthpv.buildings import fetch_vida_near
    from earthpv.labels import geodesic_area_m2

    for spec in a.aois:
        chips, aoi = _spec(spec)
        out = CACHE / "prep" / chips
        if (out / "done").exists() and not a.force:
            log.info("%s: prepared", chips)
            continue
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        val = _val(chips)
        metas = []
        for row in val.itertuples(index=False):
            with rasterio.open(row.mask) as src:
                metas.append((src.read(1).astype("int8"), src.transform, src.crs,
                              box(*rasterio.warp.transform_bounds(src.crs, "EPSG:4326",
                                                                  *src.bounds))))
        masks = np.stack([m[0] for m in metas])
        np.save(out / "masks.npy", masks)
        foot = gpd.GeoSeries([m[3] for m in metas], crs="EPSG:4326")

        fp_path = out / "footprints.parquet"
        if fp_path.exists():
            bld = gpd.read_parquet(fp_path)
        else:
            bld = fetch_vida_near(foot, ISO3[aoi], buffer_m=0.0, con=overture.connect(),
                                  progress=False)
            bld[["geometry"]].to_parquet(fp_path)
        log.info("%s: %d chips, %d VIDA footprints (%.0f s)", chips, len(val), len(bld),
                 time.time() - t0)

        units = _mastr_roof_units(REG_ROOF_MIN_KWP) if aoi in REGISTER_AOIS else None
        labels = _labels(aoi)
        roof = np.zeros(masks.shape, bool)
        reg = np.zeros(masks.shape, bool)
        inst_rows, unit_rows, null_rows = [], [], []
        for i, ((mask, t, crs, geo), row) in enumerate(zip(metas, val.itertuples(index=False))):
            shape = mask.shape
            cbox_m = box(*rasterio.transform.array_bounds(*shape, t))  # chip, in its CRS
            b = bld.iloc[bld.sindex.query(geo, predicate="intersects")].to_crs(crs)
            if len(b):
                # pixel centres, as a corpus burning footprints as ignore would
                roof[i] = rasterio.features.rasterize(
                    [(g, 1) for g in b.geometry], out_shape=shape, transform=t,
                    dtype="uint8").astype(bool)
            # installations exactly as evaluate rasterizes them
            for li, inst in labels.iloc[labels.sindex.query(geo, predicate="intersects")].iterrows():
                poly = gpd.GeoSeries([inst.geometry], crs="EPSG:4326").to_crs(crs).iloc[0]
                m = rasterio.features.rasterize([(poly, 1)], out_shape=shape, transform=t,
                                                all_touched=True, dtype="uint8").astype(bool)
                if not m.any():
                    continue
                area = inst.area_m2 if inst.area_m2 > 0 else geodesic_area_m2(inst.geometry)
                inst_rows.append(dict(chip=i, chip_id=row.chip_id, label_idx=int(li),
                                      area_m2=float(area), placement=inst.placement,
                                      px=np.flatnonzero(m).astype("int32")))
            if units is None:
                continue
            u = units.iloc[units.sindex.query(geo.buffer(0.001), predicate="intersects")]
            bg = b.reset_index(drop=True).geometry
            held = set()
            if len(u):
                u = u.to_crs(crs)
                # each unit to the footprint holding it, else the nearest within MASTR_MATCH_M
                cols = ["unit", "kwp", "commissioned", "geometry"]
                if len(b):
                    j = gpd.sjoin_nearest(u[cols], gpd.GeoDataFrame(geometry=bg, crs=crs),
                                          how="left", max_distance=MASTR_MATCH_M,
                                          distance_col="d")
                    j = j[~j.index.duplicated()]
                else:
                    j = u[cols].assign(index_right=np.nan, d=np.nan)
                held = set(j.index_right.dropna().astype(int).tolist())
                if held:
                    reg[i] = rasterio.features.rasterize(
                        [(bg.iloc[k], 1) for k in held], out_shape=shape, transform=t,
                        dtype="uint8").astype(bool)
                for unit, kwp, when, pt, ir in zip(j.unit, j.kwp, j.commissioned, j.geometry,
                                                   j.index_right):
                    if kwp < REG_UNIT_MIN_KWP:
                        continue
                    r, c = rasterio.transform.rowcol(t, pt.x, pt.y)
                    if not (0 <= r < shape[0] and 0 <= c < shape[1]) and pd.isna(ir):
                        continue
                    if pd.notna(ir):
                        g, how = bg.iloc[int(ir)], "footprint"
                    else:
                        g, how = pt.buffer(REG_DISC_M), "disc"
                    m = _region(g, shape, t)
                    if m is None:
                        continue
                    v = mask[m]
                    unit_rows.append(dict(
                        chip=i, chip_id=row.chip_id, unit=int(unit), kwp=float(kwp),
                        commissioned=str(when)[:10], region=how,
                        roof_m2=float(g.area) if how == "footprint" else np.nan,
                        under="mapped" if (v == 1).any() else "ignore" if (v == -1).any()
                        else "unmapped", px=np.flatnonzero(m).astype("int32")))
            # The chance term: footprints holding no registered unit and no label or ignore
            # pixel, in the same chips, by size (large German roofs often carry PV).
            for k, g in enumerate(bg):
                if k in held or g.area < NULL_MIN_M2 or not cbox_m.contains(g.centroid):
                    continue
                m = _region(g, shape, t)
                if m is None or (mask[m] != 0).any():
                    continue
                null_rows.append(dict(chip=i, chip_id=row.chip_id, roof_m2=float(g.area),
                                      px=np.flatnonzero(m).astype("int32")))
        np.savez_compressed(out / "roofs.npz", roof=np.packbits(roof, axis=-1),
                            reg=np.packbits(reg, axis=-1), shape=np.array(masks.shape))
        pd.DataFrame(inst_rows).to_parquet(out / "installations.parquet")
        if units is not None:
            pd.DataFrame(unit_rows).to_parquet(out / "register_units.parquet")
            pd.DataFrame(null_rows).to_parquet(out / "register_null.parquet")
        (out / "chip_ids.json").write_text(json.dumps(val.chip_id.tolist()))
        (out / "done").write_text(time.strftime("%F %T"))
        unl = roof & (masks != 1) & (masks != -1)
        log.info("%s: %d installations, unlabelled roof %.1f%% of valid pixels%s (%.0f s)",
                 chips, len(inst_rows), 100 * unl.sum() / max((masks != -1).sum(), 1),
                 f", {len(unit_rows)} register units >= {REG_UNIT_MIN_KWP:.0f} kWp"
                 if units is not None else "", time.time() - t0)


# --------------------------------------------------------------------------------- infer

def _ckpt_key(path: str) -> str:
    p = Path(path).resolve()
    st = p.stat()
    return hashlib.sha1(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:12]


TTA = {"d4": [(k, f) for f in (False, True) for k in range(4)],  # 8 rotations x flips
       "flip": [(0, False), (0, True), (2, False), (2, True)]}  # identity, h/v/hv flips


def _members(path: str) -> list[tuple[str, str]]:
    """`a+b#d4` -> [(a, ""), (b, "d4")]: an ensemble's checkpoints and each one's TTA."""
    out = []
    for m in path.split("+"):
        p, _, tta = m.partition("#")
        if tta and tta not in TTA:
            raise SystemExit(f"unknown test-time augmentation {tta!r} in {path!r}")
        out.append((p, tta))
    return out


def _cache_dir(p: str, tta: str) -> Path:
    return CACHE / "probs" / (_ckpt_key(p) + (f"_{tta}" if tta else ""))


LOGIT_CLIP = 1e-6  # float32 softmax saturates at exactly 0 or 1


def _load_prob(path: str, chips: str, mean: str = "prob") -> np.ndarray:
    """A checkpoint's cached probabilities, or an ensemble's mean of its members'.

    `mean="logit"` averages log-odds and maps back: members whose probabilities saturate near 0
    and 1 otherwise average onto a few plateaus (0, 1/n, ..., 1), and a threshold between two of
    them can only pick "k of n members fire", which makes matching a precision target coarse."""
    acc = None
    members = _members(path)
    for p, tta in members:
        x = np.asarray(np.load(_cache_dir(p, tta) / f"{chips}.npy", mmap_mode="r"), "float32")
        if mean == "logit" and len(members) > 1:
            x = np.clip(x, LOGIT_CLIP, 1 - LOGIT_CLIP)
            x = np.log(x) - np.log1p(-x)
        acc = x.copy() if acc is None else acc + x
    if len(members) == 1:
        return acc
    acc /= np.float32(len(members))
    return (1.0 / (1.0 + np.exp(-acc))).astype("float32") if mean == "logit" else acc


def _forward_tta(task, x, tta: str):
    """Mean PV probability over the TTA views of one chip (1, C, H, W), mapped back."""
    import torch

    views = TTA[tta]
    batch = []
    for k, f in views:
        v = torch.flip(x, dims=[3]) if f else x
        batch.append(torch.rot90(v, k, dims=[2, 3]))
    shapes = {tuple(b.shape) for b in batch}
    if len(shapes) > 1:  # a non-square chip: one view at a time
        outs = [task(b) for b in batch]
        probs = [torch.softmax(o.output if hasattr(o, "output") else o, 1)[:, 1] for o in outs]
    else:
        o = task(torch.cat(batch))
        probs = list(torch.softmax(o.output if hasattr(o, "output") else o, 1)[:, 1])
    acc = 0
    for (k, f), pr in zip(views, probs):
        pr = pr.reshape(1, 1, *pr.shape[-2:])
        pr = torch.rot90(pr, -k, dims=[2, 3])
        acc = acc + (torch.flip(pr, dims=[3]) if f else pr)
    return (acc / len(views))[0, 0]


def cmd_infer(a) -> None:
    import rasterio
    import torch

    from earthpv.infer import load_model

    jobs = [(f"{label}:{p}" + (f"#{t}" if t else ""), p, t)
            for label, spec in (c.split("=", 1) for c in a.ckpt) for p, t in _members(spec)]
    for label, path, tta in jobs:
        d = _cache_dir(path, tta)
        d.mkdir(parents=True, exist_ok=True)
        (d / "checkpoint.txt").write_text(str(Path(path).resolve()) + (f"#{tta}" if tta else ""))
        todo = [s for s in a.aois if not (d / f"{_spec(s)[0]}.npy").exists()]
        if not todo:
            log.info("%s: cached in %s", label, d)
            continue
        task, device, task_type = load_model(Path(path), task_type="auto")
        if task_type == "regression":
            raise SystemExit(f"{label}: a regression checkpoint; this scores segmentation")
        for spec in todo:
            chips, _ = _spec(spec)
            t0 = time.time()
            val = _val(chips)
            probs = None
            for i, row in enumerate(val.itertuples(index=False)):
                with rasterio.open(row.image) as src:
                    arr = src.read().astype("float32")
                if probs is None:
                    probs = np.zeros((len(val), *arr.shape[1:]), "float32")
                # evaluate's own forward pass, so a pixel's probability is the one it scores
                x = torch.from_numpy(arr / 10000.0)[None].to(device)
                with torch.no_grad(), torch.autocast(device_type=device,
                                                     enabled=device == "cuda"):
                    if tta:
                        probs[i] = _forward_tta(task, x, tta).float().cpu().numpy()
                    else:
                        out = task(x)
                        logits = out.output if hasattr(out, "output") else out
                        probs[i] = torch.softmax(logits, 1)[0, 1].cpu().numpy()
            tmp = d / f"{chips}.tmp.npy"
            np.save(tmp, probs)
            tmp.rename(d / f"{chips}.npy")
            log.info("%s %s: %d chips (%.0f s)", label, chips, len(val), time.time() - t0)
        del task
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# --------------------------------------------------------------------------------- score

def _counts_by_threshold(p: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Pixels with probability >= each threshold."""
    s = np.sort(p)
    return len(s) - np.searchsorted(s, grid, side="left")


def _maxprob(prob: np.ndarray, rows: pd.DataFrame) -> np.ndarray:
    flat = prob.reshape(len(prob), -1)
    return np.array([flat[c, px].max() for c, px in zip(rows.chip, rows.px)], dtype="float32")


def _precision(tp, fp):
    return round(float(tp) / max(float(tp + fp), 1.0), 4)


def _match(curve: pd.DataFrame, target: float, col: str) -> tuple[float, float, bool]:
    """Lowest threshold whose pooled `col` precision reaches `target`."""
    ok = curve[curve[col] >= target]
    r = ok.iloc[0] if len(ok) else curve.iloc[-1]
    return float(r.thr), float(r[col]), bool(len(ok))


def _chance(units: pd.DataFrame, null: pd.DataFrame, t: float) -> dict:
    """Flag rate on unmapped registered roofs against unregistered unlabelled roofs of the same
    size in the same chips; corrected share (obs - f) / (1 - f), as label_audit's mastr-null."""
    ub = pd.cut(units.roof_m2, NULL_BINS, right=False)
    nb = pd.cut(null.roof_m2, NULL_BINS, right=False)
    f_bin = (null.maxprob >= t).groupby(nb, observed=False).mean()
    w = ub.value_counts(normalize=True, sort=False)
    f = float((w * f_bin.reindex(w.index).fillna(0)).sum())
    obs = float(units.detected.mean())
    return dict(n_units=len(units), n_null=len(null), obs=round(obs, 4), chance=round(f, 4),
                corrected=round((obs - f) / (1 - f), 4) if f < 1 else None)


def _paired(new: pd.Series, base: pd.Series) -> dict:
    only_new, only_base = int((new & ~base).sum()), int((~new & base).sum())
    return dict(n=len(new), recall_new=round(float(new.mean()), 4) if len(new) else None,
                recall_base=round(float(base.mean()), 4) if len(new) else None,
                only_new=only_new, only_base=only_base,
                p_mcnemar=round(mcnemar_exact(only_new, only_base), 4))


def cmd_score(a) -> None:
    ckpts = [c.split("=", 1) for c in a.ckpt]
    base = ckpts[0][0]
    grid = np.array(sorted(set(GRID) | {a.threshold}))
    out = RESULTS / a.name
    out.mkdir(parents=True, exist_ok=True)
    px_rows, inst_rows, unit_rows, null_rows = [], [], [], []
    for spec in a.aois:
        chips, aoi = _spec(spec)
        pdir = CACHE / "prep" / chips
        masks = np.load(pdir / "masks.npy")
        r = np.load(pdir / "roofs.npz")
        shp = tuple(r["shape"])
        roof = np.unpackbits(r["roof"], axis=-1, count=shp[-1]).astype(bool)
        reg = np.unpackbits(r["reg"], axis=-1, count=shp[-1]).astype(bool)
        valid, pos = masks != -1, masks == 1
        neg = valid & ~pos
        cats = {"pos": pos, "neg_off": neg & ~roof, "neg_roof": neg & roof & ~reg,
                "neg_roof_reg": neg & roof & reg}
        inst = pd.read_parquet(pdir / "installations.parquet")
        upath = pdir / "register_units.parquet"
        units = pd.read_parquet(upath) if upath.exists() else None
        npath = pdir / "register_null.parquet"
        nulls = pd.read_parquet(npath) if npath.exists() else None
        for label, path in ckpts:
            prob = _load_prob(path, chips, a.mean)
            n = {k: _counts_by_threshold(prob[m], grid) for k, m in cats.items()}
            tot = {k: int(m.sum()) for k, m in cats.items()}
            for ti, t in enumerate(grid):
                px_rows.append(dict(aoi=chips, ckpt=label, thr=float(t), tp=int(n["pos"][ti]),
                                    fn=tot["pos"] - int(n["pos"][ti]),
                                    fp_off=int(n["neg_off"][ti]), fp_roof=int(n["neg_roof"][ti]),
                                    fp_roof_reg=int(n["neg_roof_reg"][ti]),
                                    roof_px=tot["neg_roof"] + tot["neg_roof_reg"]))
            if len(inst):
                inst_rows.append(inst.drop(columns="px").assign(
                    aoi=chips, ckpt=label, maxprob=_maxprob(prob, inst)))
            if units is not None and len(units):
                unit_rows.append(units.drop(columns="px").assign(
                    aoi=chips, ckpt=label, maxprob=_maxprob(prob, units)))
            if nulls is not None and len(nulls):
                null_rows.append(nulls.drop(columns="px").assign(
                    aoi=chips, ckpt=label, maxprob=_maxprob(prob, nulls)))
            log.info("%s %s scored", chips, label)

    px = pd.DataFrame(px_rows)
    px["fp"] = px.fp_off + px.fp_roof + px.fp_roof_reg
    inst = pd.concat(inst_rows, ignore_index=True)
    inst["size_bin"] = inst.area_m2.map(_bin)
    units = pd.concat(unit_rows, ignore_index=True) if unit_rows else pd.DataFrame()
    nulls = pd.concat(null_rows, ignore_index=True) if null_rows else pd.DataFrame()
    px.to_csv(out / "pixels.csv", index=False)
    inst.to_csv(out / "installations.csv", index=False)
    if len(units):
        units.to_csv(out / "register_units.csv", index=False)

    match = a.match_aois or [_spec(s)[0] for s in a.aois]
    pooled = px[px.aoi.isin(match)].groupby(["ckpt", "thr"], as_index=False)[
        ["tp", "fp", "fp_off", "fp_roof", "fp_roof_reg", "roof_px"]].sum()
    pooled["standard"] = pooled.tp / (pooled.tp + pooled.fp).clip(lower=1)
    pooled["roof_ignore"] = pooled.tp / (pooled.tp + pooled.fp_off).clip(lower=1)
    b0 = pooled[(pooled.ckpt == base) & np.isclose(pooled.thr, a.threshold)].iloc[0]
    targets = {"standard": float(b0.standard), "roof_ignore": float(b0.roof_ignore)}
    ops = {}
    for label, _ in ckpts:
        curve = pooled[pooled.ckpt == label].sort_values("thr")
        ops[label] = {"production": dict(thr=a.threshold, reached=True)}
        for kind, target in targets.items():
            if label == base:
                ops[label][kind] = dict(thr=a.threshold, precision=round(target, 4), reached=True)
            else:
                t, p, ok = _match(curve, target, kind)
                ops[label][kind] = dict(thr=t, precision=round(p, 4), reached=ok)

    def hits(df, label, t):
        d = df[df.ckpt == label].copy()
        d["detected"] = d.maxprob >= t
        return d

    key = ["aoi", "chip_id", "label_idx"]
    summary = dict(name=a.name, baseline=base, checkpoints=dict(ckpts),
                   production_threshold=a.threshold, match_aois=match,
                   precision_targets={k: round(v, 4) for k, v in targets.items()},
                   operating_points=ops, aois={})
    for agg in [*[_spec(s)[0] for s in a.aois], "ALL"]:
        spx = px if agg == "ALL" else px[px.aoi == agg]
        sinst = inst if agg == "ALL" else inst[inst.aoi == agg]
        block = {}
        bh = hits(sinst, base, a.threshold).set_index(key)
        for label, _ in ckpts:
            block[label] = {}
            for kind in ("production", "standard", "roof_ignore"):
                t = ops[label][kind]["thr"]
                c = spx[(spx.ckpt == label) & np.isclose(spx.thr, t)].sum(numeric_only=True)
                h = hits(sinst, label, t)
                w = h.set_index(key)[["placement", "size_bin", "detected"]].join(
                    bh[["detected"]].rename(columns={"detected": "base"}), how="inner")
                tests = {name: _paired(w.loc[sel(w), "detected"].astype(bool),
                                       w.loc[sel(w), "base"].astype(bool))
                         for name, sel in SUBSETS.items()}
                block[label][kind] = dict(
                    thr=t, standard_precision=_precision(c.tp, c.fp),
                    roof_ignore_precision=_precision(c.tp, c.fp_off),
                    pixel_recall=_precision(c.tp, c.fn),
                    roof_firing_rate=round(float(c.fp_roof + c.fp_roof_reg)
                                           / max(float(c.roof_px), 1.0), 5),
                    paired_vs_base=tests)
                if agg in REGISTER_AOIS and len(units):
                    block[label][kind]["register_precision"] = _precision(
                        c.tp + c.fp_roof_reg, c.fp - c.fp_roof_reg)
                    su = units[units.aoi == agg]
                    if len(su):
                        u_new = hits(su, label, t).set_index(["aoi", "chip_id", "unit"])
                        u_base = hits(su, base, a.threshold).set_index(["aoi", "chip_id", "unit"])
                        uw = u_new[["under", "detected"]].join(
                            u_base[["detected"]].rename(columns={"detected": "base"}))
                        block[label][kind]["register_recall"] = {
                            under: _paired(g.detected.astype(bool), g.base.astype(bool))
                            for under, g in uw.groupby("under")}
                        sn = nulls[(nulls.aoi == agg) & (nulls.ckpt == label)]
                        fu = hits(su[(su.region == "footprint") & (su.under == "unmapped")],
                                  label, t)
                        if len(sn) and len(fu):
                            block[label][kind]["register_chance"] = _chance(fu, sn, t)
        summary["aois"][agg] = block
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    _print(summary)
    print(f"\n-> {out}")


def _print(s: dict) -> None:
    print(f"precision targets (baseline {s['baseline']} at {s['production_threshold']}, pooled "
          f"over {s['match_aois']}): {s['precision_targets']}")
    allb = s["aois"]["ALL"]
    print(f"\n{'ckpt':12s} {'match':12s} {'thr':>8s} {'std P':>6s} {'roofP':>6s} {'fire':>7s} "
          f"{'roof 400-5k':>18s} {'ground':>18s}")
    for label, kinds in allb.items():
        for kind, r in kinds.items():
            rt, gr = r["paired_vs_base"]["rooftop_400_5000"], r["paired_vs_base"]["ground_ge400"]
            print(f"{label:12s} {kind:12s} {r['thr']:8.4g} {r['standard_precision']:6.3f} "
                  f"{r['roof_ignore_precision']:6.3f} {r['roof_firing_rate']:7.4f} "
                  f"{rt['recall_new']:.3f} (+{rt['only_new']}/-{rt['only_base']}) "
                  f"{gr['recall_new']:.3f} (+{gr['only_new']}/-{gr['only_base']})")
    for aoi in sorted(REGISTER_AOIS & set(s["aois"])):
        print(f"\n{aoi}, against the register (rooftop units >= {REG_UNIT_MIN_KWP:.0f} kWp)")
        print(f"{'ckpt':12s} {'match':12s} {'thr':>8s} {'std P':>6s} {'regP':>6s} "
              f"{'unmapped':>22s} {'mapped':>22s}  chance-corrected (obs/chance)")
        for label, kinds in s["aois"][aoi].items():
            for kind, r in kinds.items():
                rr = r.get("register_recall", {})
                cell = {k: (f"{v['recall_new']:.3f} n={v['n']} (+{v['only_new']}/-"
                            f"{v['only_base']})") for k, v in rr.items()}
                print(f"{label:12s} {kind:12s} {r['thr']:8.4g} {r['standard_precision']:6.3f} "
                      f"{r.get('register_precision', float('nan')):6.3f} "
                      f"{cell.get('unmapped', ''):>22s} {cell.get('mapped', ''):>22s}  "
                      + (f"{r['register_chance']['corrected']:.3f} "
                         f"({r['register_chance']['obs']:.3f}/{r['register_chance']['chance']:.3f})"
                         if "register_chance" in r else ""))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("--aois", nargs="+", required=True)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("infer")
    p.add_argument("--ckpt", action="append", required=True, help="label=path")
    p.add_argument("--aois", nargs="+", required=True)
    p = sub.add_parser("score")
    p.add_argument("--name", required=True)
    p.add_argument("--ckpt", action="append", required=True, help="label=path; first is baseline")
    p.add_argument("--aois", nargs="+", required=True)
    p.add_argument("--match-aois", nargs="+", default=None)
    p.add_argument("--threshold", type=float, default=0.3)
    p.add_argument("--mean", choices=["prob", "logit"], default="prob",
                   help="how an ensemble (a+b) averages its members")
    a = ap.parse_args()
    {"prep": cmd_prep, "infer": cmd_infer, "score": cmd_score}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
