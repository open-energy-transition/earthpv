#!/usr/bin/env python
"""Score-level review: do roofclf's scores sum to the number of PV roofs where Best leans on
them hardest?

Since 2026-10-25 every in-domain building counts by its `p_roofclf` (open question
"Probability-weighted roofclf capacity is published but untested where it adds most"). The
coverage ratio fitted on the calibration quadrats absorbs any score bias the quadrats share,
so what the national figure trusts is that the score's LEVEL -- the score sum per real PV
roof -- is the same in national cells as in the quadrats that priced them. Nothing has
measured that. This draws the sample that does, and scores the review once it is done.

**Population.** Every scored building in density-grid cells of `--cell-density` (default
100-1,000 bldg/km2, where 80% of the probability-weighting gain sits and the quadrats are
thinnest), minus the buildings inside any registered calibration area, split by roof size
(< 400 m2: the sub-400 central component; >= 400 m2: the >= 400 m2 rooftop replacement).

**Design.** Stratified random sampling by score bin within each size class. Most roofs score
near zero, but there are so many of them that the low bins carry two thirds of the score sum
in Pakistan's mid-density cells, so they get most of the sample: Neyman allocation with the
bin's mean score as the prior prevalence, `--min-per-stratum` everywhere. A drawn roof whose
Esri World Imagery capture predates `--window-start` minus `--max-imagery-lag-months` (the
quadrat sampler's own gate) cannot confirm or refute recent PV, so it is screened out and
the next draw from the same bin takes its place; the per-bin pass rate is recorded.

**Blind.** The review layer carries a roof outline, its 20 m yard ring (the parcel label's
`YARD_RING_M`), a `sample_id` and the imagery date, nothing else. Scores, strata and cells are
in `key_open_after_review.csv`. Sample ids are in random order, so reviewing 1..k and stopping
early is still a random subsample of every bin.

**Reference.** The same quantity in the quadrats whose coverage ratio prices the population:
out-of-fold `p_oof` summed over the parcel label's PV roofs (`has_pv`) in the density band of
`--pricing-summary` that contains the population, read at draw time and written into
`design.json` with the decision rule, before any verdict exists.

    python scripts/roofclf_level_review.py draw --aoi pakistan \\
        --grid data/predictions/pakistan/density/grid.geoparquet --window-start 2025-11-01
    python scripts/roofclf_level_review.py analyze --aoi pakistan \\
        --verdicts results/pakistan_roofclf_level_review/review_done.osm
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

DO_NOT_UPLOAD = "earthpv review layer, NOT OSM data -- never upload"
SIZE_CLASSES = ("<400", ">=400")
SIZE_FLOOR_M2 = 400.0
DEFAULT_SEED = 20261028
MAX_DRAW_FACTOR = 8          # draws per accepted roof before a bin is reported short
ESRI_WORKERS = 6
MIN_DECIDED = 3              # yes/no verdicts per bin before an estimate is reported
N_BOOT = 2000
# Declared 2026-10-28, before any verdict, from open question 1's own revert band.
RULE = {
    "statistic": "f = reference level / national level, level = score sum per real PV roof "
                 "(count); f < 1 means national scores overstate PV relative to the quadrats",
    "consistent": "the 90% interval of f contains 1",
    "biased": "the 90% interval excludes 1 and the point lies in [0.5, 2]: report f, the owner "
              "decides whether to apply it",
    "fails": "the point lies outside [0.5, 2]: revert to `--weighting threshold` (open question "
             "'Probability-weighted roofclf capacity is published but untested where it adds "
             "most')",
    "applies_to": "each size class separately: < 400 m2 prices sub400 central, >= 400 m2 the "
                  "ge400 rooftop replacement",
    "status": "proposed 2026-10-28 -- confirm before reviewing",
}

MAPCSS = """\
/* earthpv roofclf score-level review. JOSM: Preferences -> Map Paint Styles -> + */
way[earthpv=review_roof] { color: #ffffff; width: 2; fill-color: #ffffff; fill-opacity: 0.08;
    text: tag("sample_id"); font-size: 14; text-color: #ffffff; z-index: 10; }
way[earthpv=review_roof][pv=yes] { color: #2ecc71; fill-color: #2ecc71; fill-opacity: 0.3; }
way[earthpv=review_roof][pv=no] { color: #95a5a6; fill-color: #95a5a6; fill-opacity: 0.3; }
way[earthpv=review_roof][pv=unclear] { color: #f39c12; fill-color: #f39c12; fill-opacity: 0.3; }
way[earthpv=yard_ring] { color: #ffffff; width: 1; dashes: 4,4; opacity: 0.7; }
"""


def score_edges(text: str, threshold: float) -> np.ndarray:
    vals = [threshold if v.strip().upper() == "THR" else float(v) for v in text.split(",")]
    edges = np.array(vals, dtype=float)
    if not (np.all(np.diff(edges) > 0) and edges[0] == 0.0 and edges[-1] == 1.0):
        raise SystemExit(f"--score-edges must rise strictly from 0 to 1, got {edges.tolist()}")
    return edges


def strata_labels(edges: np.ndarray) -> list[str]:
    return [f"[{lo:g},{hi:g}{']' if i == len(edges) - 2 else ')'}"
            for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:]))]


def assign_bin(p: np.ndarray, edges: np.ndarray) -> np.ndarray:
    return np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)


def neyman(n_h: np.ndarray, mean_p: np.ndarray, total: int, floor: int) -> np.ndarray:
    """Neyman allocation of `total` for estimating a count, with `mean_p` as each bin's prior
    prevalence, at least `floor` per bin and never more than the bin holds."""
    n_h = n_h.astype(float)
    alloc = np.minimum(np.full(len(n_h), floor, float), n_h)
    weight = n_h * np.sqrt(np.clip(mean_p, 1e-6, 1 - 1e-6) * (1 - np.clip(mean_p, 1e-6, 1 - 1e-6)))
    rest = max(total - alloc.sum(), 0)
    share = rest * weight / weight.sum() if weight.sum() else np.zeros_like(weight)
    out = alloc + np.floor(share)
    extra = int(total - out.sum())
    for i in np.argsort(-(share - np.floor(share)))[: max(extra, 0)]:
        out[i] += 1
    return np.minimum(out, n_h).astype(int)


def utm_epsg(lon: float, lat: float) -> int:
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1


def reference_levels(model_dir: Path, quadrats: list[str]) -> dict:
    """Score sum per parcel-label PV roof (and per m2 of PV roof), out of fold, per size class,
    pooled over `quadrats` -- the quantity the national review is compared with."""
    b = pd.read_parquet(model_dir / "buildings.geoparquet",
                        columns=["quadrat", "roof_area_m2", "has_pv", "p_oof"])
    b = b[b["quadrat"].isin(quadrats)]
    missing = sorted(set(quadrats) - set(b["quadrat"]))
    if missing:
        raise SystemExit(f"{model_dir}/buildings.geoparquet lacks quadrats {missing}")
    out = {}
    for cls, part in (("<400", b[b.roof_area_m2 < SIZE_FLOOR_M2]),
                      (">=400", b[b.roof_area_m2 >= SIZE_FLOOR_M2])):
        pv = part["has_pv"].astype(bool)
        out[cls] = {
            "n_buildings": int(len(part)), "n_pv_roofs": int(pv.sum()),
            "sum_p_oof": round(float(part["p_oof"].sum()), 2),
            "level_count": round(float(part["p_oof"].sum() / pv.sum()), 4),
            "level_area": round(float((part["p_oof"] * part["roof_area_m2"]).sum()
                                      / part.loc[pv, "roof_area_m2"].sum()), 4),
        }
    return out


def pricing_band(summary_path: Path, lo: float, hi: float) -> dict:
    """The coverage-ratio density band that prices cells of density [lo, hi)."""
    s = json.loads(summary_path.read_text())
    fit = s["calibration_coverage_ratio_by_size_and_density"]
    for band in fit["bands"]:
        b_lo = -math.inf if band["density_lo"] is None else float(band["density_lo"])
        b_hi = math.inf if band["density_hi"] is None else float(band["density_hi"])
        if b_lo <= lo and hi <= b_hi:
            return {"density_lo": b_lo, "density_hi": b_hi, "quadrats": band["quadrats"]}
    raise SystemExit(f"cells of {lo:g}-{hi:g} bldg/km2 straddle a coverage-ratio band edge "
                     f"({fit['band_edges']}): pass a --cell-density inside one band")


class CellGeoms:
    """Footprint geometry by (cell, row), one parquet read per cell."""

    def __init__(self, roofclf_dir: Path):
        self.dir, self.cache = roofclf_dir, {}

    def get(self, cell: str, row: int):
        if cell not in self.cache:
            import geopandas as gpd
            self.cache[cell] = gpd.read_parquet(self.dir / f"{cell}.parquet",
                                                columns=["geometry"]).geometry.to_numpy()
        return self.cache[cell][row]


def build_frame(args, cells: pd.DataFrame, exclusion) -> tuple[pd.DataFrame, dict]:
    import geopandas as gpd

    parts, n_missing, n_nan, n_inside = [], 0, 0, 0
    for i, cell in enumerate(cells["cell"]):
        p = args.roofclf_dir / f"{cell}.parquet"
        if not p.exists():
            n_missing += 1
            continue
        d = pd.read_parquet(p, columns=["p_roofclf", "roof_area_m2"])
        keep = d["p_roofclf"].notna().to_numpy().copy()
        n_nan += int((~keep).sum())
        if exclusion is not None and cells.geometry.iloc[i].intersects(exclusion):
            g = gpd.read_parquet(p, columns=["geometry"]).geometry
            inside = g.representative_point().within(exclusion).to_numpy()
            n_inside += int((inside & keep).sum())
            keep &= ~inside
        rows = np.flatnonzero(keep)
        parts.append(pd.DataFrame({
            "cell_i": np.full(len(rows), i, np.int32), "row": rows.astype(np.int32),
            "p": d["p_roofclf"].to_numpy(np.float32)[rows],
            "area": d["roof_area_m2"].to_numpy(np.float32)[rows]}))
    frame = pd.concat(parts, ignore_index=True)
    return frame, {"cells_missing_scoring": n_missing, "buildings_unscored_nan": n_nan,
                   "buildings_inside_calibration_areas": n_inside}


def draw(args) -> int:
    import geopandas as gpd
    from shapely.geometry import LineString, mapping
    from shapely.ops import unary_union

    from earthpv.roofclf import YARD_RING_M, discover_quadrats, load_boundary
    from propose_calibration_candidates import esri_capture

    win0 = date.fromisoformat(args.window_start)
    months = win0.year * 12 + win0.month - 1 - args.max_imagery_lag_months
    earliest = date(months // 12, months % 12 + 1, 1)
    model_summary = json.loads((args.model_dir / "summary.json").read_text())
    threshold = float(model_summary["deployment_threshold"])
    edges = score_edges(args.score_edges, threshold)
    labels = strata_labels(edges)
    lo, hi = args.cell_density
    band = pricing_band(args.pricing_summary, lo, hi)
    ref = reference_levels(args.model_dir, band["quadrats"])

    grid = gpd.read_parquet(args.grid)
    cells = grid[(grid.bldg_density_km2 >= lo) & (grid.bldg_density_km2 < hi)].reset_index(drop=True)
    stems = discover_quadrats(args.labels_dir)
    exclusion = unary_union([load_boundary(args.labels_dir / f"{s}_boundary.geojson")
                             for s in stems]) if stems else None
    print(f"{len(cells):,} cells of {lo:g}-{hi:g} bldg/km2; excluding {len(stems)} "
          f"calibration areas")
    frame, frame_notes = build_frame(args, cells, exclusion)
    frame["size_i"] = (frame["area"] >= SIZE_FLOOR_M2).astype(np.int8)
    frame["bin"] = assign_bin(frame["p"].to_numpy(), edges).astype(np.int8)
    print(f"{len(frame):,} buildings in the frame ({frame_notes})")

    rng = np.random.default_rng(args.seed)
    rows, strata, screened = [], [], []
    with ThreadPoolExecutor(ESRI_WORKERS) as pool:
        geoms = CellGeoms(args.roofclf_dir)
        for size_i, cls in enumerate(SIZE_CLASSES):
            sub = frame[frame["size_i"] == size_i]
            grp = sub.groupby("bin")
            n_h = grp.size().reindex(range(len(labels)), fill_value=0).to_numpy()
            mean_p = grp["p"].mean().reindex(range(len(labels)), fill_value=0).to_numpy()
            target = neyman(n_h, mean_p, args.n_small if size_i == 0 else args.n_large,
                            args.min_per_stratum)
            for k, label in enumerate(labels):
                members = sub.index[sub["bin"] == k].to_numpy()
                order = rng.permutation(members)
                got, tried, pos = [], 0, 0
                while len(got) < target[k] and pos < len(order) and pos < MAX_DRAW_FACTOR * max(target[k], 1):
                    batch = order[pos: pos + max(4, 2 * (target[k] - len(got)))]
                    pos += len(batch)
                    recs = frame.loc[batch]
                    pts = [geoms.get(cells.cell.iloc[r.cell_i], int(r.row)).centroid
                           for r in recs.itertuples()]
                    caps = list(pool.map(lambda pt: esri_capture(pt.x, pt.y), pts))
                    for r, pt, cap in zip(recs.itertuples(), pts, caps):
                        if len(got) == target[k]:
                            break   # later draws were never needed: not counted either way
                        tried += 1
                        if cap is None or cap["date"] < earliest:
                            screened.append({
                                "size": cls, "stratum": label, "cell": cells.cell.iloc[r.cell_i],
                                "row": int(r.row), "lat": round(pt.y, 6), "lon": round(pt.x, 6),
                                "reason": (f"Esri imagery from {cap['date']} predates {earliest}"
                                           if cap else "no Esri imagery date at zoom 18"),
                                "imagery_date": cap["date"].isoformat() if cap else ""})
                            continue
                        got.append({"frame_idx": int(r.Index), "size": cls, "stratum": label,
                                    "cell": cells.cell.iloc[r.cell_i], "row": int(r.row),
                                    "lat": round(pt.y, 7), "lon": round(pt.x, 7),
                                    "roof_area_m2": round(float(r.area), 1),
                                    "p_roofclf": round(float(r.p), 6),
                                    "imagery_date": cap["date"].isoformat(),
                                    "imagery_layer": f"Esri World Imagery ({cap['name']})"
                                    if cap["name"] else "Esri World Imagery",
                                    "imagery_res_m": cap["res_m"]})
                rows.extend(got)
                part = sub[sub["bin"] == k]
                strata.append({
                    "size": cls, "stratum": label, "N": int(len(part)),
                    "sum_p": round(float(part["p"].sum()), 3),
                    "mean_p": round(float(part["p"].mean()), 6) if len(part) else 0.0,
                    "sum_area_m2": round(float(part["area"].sum()), 1),
                    "sum_p_area_m2": round(float((part["p"] * part["area"]).sum()), 1),
                    "n_target": int(target[k]), "n_drawn": len(got), "n_tried": tried,
                    "imagery_pass_rate": round(len(got) / tried, 4) if tried else None})
                print(f"  {cls:>5} {label:<14} N {len(part):>11,}  sum_p {part['p'].sum():>12,.1f}"
                      f"  drawn {len(got):>3}/{target[k]:<3} imagery pass {len(got)}/{tried}")
                if len(got) < target[k]:
                    print(f"    SHORT: {len(got)} of {target[k]} after {pos} draws")

    sample = pd.DataFrame(rows)
    sample = sample.iloc[rng.permutation(len(sample))].reset_index(drop=True)
    sample.insert(0, "sample_id", np.arange(1, len(sample) + 1))
    shapes = [geoms.get(c, r) for c, r in zip(sample["cell"], sample["row"])]
    shapes = [max(s.geoms, key=lambda g: g.area) if s.geom_type == "MultiPolygon" else s
              for s in shapes]
    rings = []
    for s in shapes:
        crs = utm_epsg(s.centroid.x, s.centroid.y)
        g = gpd.GeoSeries([s], crs=4326).to_crs(crs).buffer(YARD_RING_M).exterior.to_crs(4326)
        rings.append(g.iloc[0])

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    meta = {"aoi": args.aoi, "warning": DO_NOT_UPLOAD, "n_roofs": len(sample),
            "instructions": "see README.md: pv=yes|no|unclear on each review_roof"}
    feats = []
    for (_, r), s, ring in zip(sample.iterrows(), shapes, rings):
        props = {"sample_id": int(r.sample_id), "imagery_date": r.imagery_date,
                 "do_not_upload": DO_NOT_UPLOAD}
        feats.append({"type": "Feature", "properties": {"earthpv": "review_roof", **props},
                      "geometry": mapping(s)})
        feats.append({"type": "Feature", "properties": {"earthpv": "yard_ring", **props},
                      "geometry": mapping(LineString(ring.coords))})
    (out / "review.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "earthpv": meta, "features": feats}) + "\n")
    write_osm(out / "review.osm", sample, shapes, rings)
    (out / "review.mapcss").write_text(MAPCSS)
    with (out / "review_sheet.csv").open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["sample_id", "lat", "lon", "imagery_date", "id_link", "pv", "notes"])
        for r in sample.itertuples():
            wr.writerow([r.sample_id, r.lat, r.lon, r.imagery_date,
                         f"https://www.openstreetmap.org/edit?editor=id#map=20.00/{r.lat}/{r.lon}"
                         "&background=EsriWorldImagery", "", ""])
    sample.drop(columns="frame_idx").to_csv(out / "key_open_after_review.csv", index=False)
    pd.DataFrame(strata).to_csv(out / "strata.csv", index=False)
    pd.DataFrame(screened).to_csv(out / "screened_out.csv", index=False)
    design = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aoi": args.aoi, "seed": args.seed, "grid": str(args.grid),
        "roofclf_dir": str(args.roofclf_dir), "model_dir": str(args.model_dir),
        "pricing_summary": str(args.pricing_summary),
        "cell_density_bldg_km2": [lo, hi], "n_cells": int(len(cells)), **frame_notes,
        "n_frame_buildings": int(len(frame)),
        "calibration_areas_excluded": stems,
        "score_edges": edges.tolist(), "deployment_threshold": threshold,
        "imagery_gate": {"window_start": args.window_start, "earliest": earliest.isoformat(),
                         "max_lag_months": args.max_imagery_lag_months},
        "pricing_band": band, "reference": ref, "rule": RULE,
        "yard_ring_m": YARD_RING_M,
        "n_target": {"<400": args.n_small, ">=400": args.n_large},
        "n_drawn": {c: int((sample["size"] == c).sum()) for c in SIZE_CLASSES},
    }
    (out / "design.json").write_text(json.dumps(design, indent=1) + "\n")
    print(f"wrote {len(sample)} roofs to {out} ({len(screened)} draws screened on imagery)")
    return 0


def write_osm(path: Path, sample: pd.DataFrame, shapes, rings) -> None:
    """A JOSM data layer that cannot be uploaded (`upload="never"`)."""
    lines = ["<?xml version='1.0' encoding='UTF-8'?>",
             "<osm version='0.6' generator='earthpv roofclf_level_review' upload='never'>"]
    nid, wid, ways = -1, -1_000_000, []
    for r, shape, ring in zip(sample.itertuples(), shapes, rings):
        for kind, coords in (("review_roof", list(shape.exterior.coords)),
                             ("yard_ring", list(ring.coords))):
            refs = []
            for x, y in coords[:-1]:
                lines.append(f"  <node id='{nid}' lat='{y:.7f}' lon='{x:.7f}'/>")
                refs.append(nid)
                nid -= 1
            tags = {"earthpv": kind, "sample_id": str(r.sample_id),
                    "imagery_date": r.imagery_date, "note": DO_NOT_UPLOAD}
            ways.append((wid, refs + refs[:1], tags))
            wid -= 1
    for wid, refs, tags in ways:
        lines.append(f"  <way id='{wid}'>")
        lines += [f"    <nd ref='{n}'/>" for n in refs]
        lines += [f"    <tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items()]
        lines.append("  </way>")
    lines.append("</osm>")
    path.write_text("\n".join(lines) + "\n")


VERDICTS = {"yes": "yes", "y": "yes", "1": "yes", "true": "yes", "pv": "yes",
            "no": "no", "n": "no", "0": "no", "false": "no",
            "unclear": "unclear", "?": "unclear", "unknown": "unclear"}


def read_verdicts(paths: list[Path]) -> pd.Series:
    """sample_id -> yes/no/unclear from a JOSM-saved .osm, a .geojson or the sheet CSV."""
    got: dict[int, str] = {}
    for path in paths:
        pairs = []
        if path.suffix == ".osm":
            for way in ET.parse(path).getroot().iter("way"):
                t = {tag.get("k"): tag.get("v") for tag in way.iter("tag")}
                if t.get("earthpv") == "review_roof" and t.get("pv"):
                    pairs.append((t["sample_id"], t["pv"]))
        elif path.suffix == ".geojson":
            for f in json.loads(path.read_text())["features"]:
                p = f.get("properties") or {}
                if p.get("earthpv") == "review_roof" and p.get("pv"):
                    pairs.append((p["sample_id"], p["pv"]))
        else:
            pairs = [(r["sample_id"], r["pv"]) for r in csv.DictReader(path.open()) if r.get("pv")]
        for sid, v in pairs:
            key = VERDICTS.get(str(v).strip().lower())
            if key is None:
                raise SystemExit(f"{path}: sample {sid} has verdict {v!r}; use yes/no/unclear")
            sid = int(sid)
            if sid in got and got[sid] != key:
                raise SystemExit(f"sample {sid}: conflicting verdicts {got[sid]!r} and {key!r}")
            got[sid] = key
    return pd.Series(got, name="pv", dtype=object)


def estimate(strata: pd.DataFrame, rev: pd.DataFrame) -> dict:
    """Stratified estimates of PV roofs and PV roof area for one size class."""
    t_count = t_area = 0.0
    for s in strata.itertuples():
        d = rev[rev["stratum"] == s.stratum]
        y = (d["pv"] == "yes").to_numpy(float)
        t_count += s.N * y.mean()
        t_area += s.N * (y * d["roof_area_m2"].to_numpy(float)).mean()
    sp, spa = strata["sum_p"].sum(), strata["sum_p_area_m2"].sum()
    return {"pv_roofs": t_count, "pv_roof_area_m2": t_area,
            "level_count": sp / t_count if t_count else math.inf,
            "level_area": spa / t_area if t_area else math.inf}


def analyze(args) -> int:
    out = args.out_dir
    design = json.loads((out / "design.json").read_text())
    key = pd.read_csv(out / "key_open_after_review.csv")
    strata = pd.read_csv(out / "strata.csv")
    verdicts = read_verdicts(args.verdicts)
    unknown = sorted(set(verdicts.index) - set(key["sample_id"]))
    if unknown:
        raise SystemExit(f"verdicts for sample ids not in this draw: {unknown[:10]}")
    key = key.merge(verdicts.rename_axis("sample_id").reset_index(), on="sample_id", how="left")
    decided = key[key["pv"].isin(["yes", "no"])]
    rng = np.random.default_rng(design["seed"])
    result = {"n_drawn": int(len(key)), "n_reviewed": int(key["pv"].notna().sum()),
              "n_unclear": int((key["pv"] == "unclear").sum()), "rule": design["rule"],
              "classes": {}}
    rows = []
    for cls in SIZE_CLASSES:
        st = strata[strata["size"] == cls]
        rev = decided[decided["size"] == cls]
        per = rev.groupby("stratum")["pv"].agg(n_decided="size",
                                               n_yes=lambda v: int((v == "yes").sum()))
        st = st.merge(per, left_on="stratum", right_index=True, how="left").fillna(
            {"n_decided": 0, "n_yes": 0})
        rows.append(st.assign(pv_share=lambda d: d.n_yes / d.n_decided.where(d.n_decided > 0)))
        ref = design["reference"][cls]
        entry = {"reference": ref, "n_decided": int(len(rev)),
                 "n_yes": int((rev["pv"] == "yes").sum())}
        short = st[st["n_decided"] < MIN_DECIDED]
        if len(short):
            entry["status"] = (f"incomplete: {len(short)} of {len(st)} score bins have fewer "
                               f"than {MIN_DECIDED} yes/no verdicts")
            result["classes"][cls] = entry
            continue
        point = estimate(st, rev)
        boots = []
        for _ in range(N_BOOT):
            parts = [g.iloc[rng.integers(0, len(g), len(g))] for _, g in rev.groupby("stratum")]
            boots.append(estimate(st, pd.concat(parts)))
        b = pd.DataFrame(boots)
        f = ref["level_count"] / point["level_count"]
        f_boot = ref["level_count"] / b["level_count"]
        lo, hi = np.percentile(f_boot, [5, 95])
        status = ("fails" if not 0.5 <= f <= 2 else "consistent" if lo <= 1 <= hi else "biased")
        thr = design["deployment_threshold"]
        above = st[st["stratum"].map(lambda s: float(s[1:].split(",")[0]) >= thr)]
        below = st.drop(above.index)
        entry.update({
            "pv_roofs": round(point["pv_roofs"]), "sum_p": round(float(st["sum_p"].sum()), 1),
            "level_count": round(point["level_count"], 4),
            "level_count_ci90": [round(float(x), 4) for x in np.percentile(b["level_count"], [5, 95])],
            "level_area": round(point["level_area"], 4),
            "level_area_ci90": [round(float(x), 4) for x in np.percentile(b["level_area"], [5, 95])],
            "f": round(f, 4), "f_ci90": [round(float(lo), 4), round(float(hi), 4)],
            "f_area": round(ref["level_area"] / point["level_area"], 4),
            "precision_above_threshold": round(float((above.N * above.n_yes / above.n_decided).sum()
                                                     / above.N.sum()), 4),
            "share_of_pv_roofs_below_threshold": round(float(
                (below.N * below.n_yes / below.n_decided).sum() / point["pv_roofs"]), 4)
            if point["pv_roofs"] else None,
            "status": status,
        })
        result["classes"][cls] = entry
    pd.concat(rows).to_csv(out / "strata_result.csv", index=False)
    (out / "result.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["classes"], indent=1))
    print(f"{result['n_reviewed']} of {result['n_drawn']} reviewed ({result['n_unclear']} unclear)"
          f"; wrote {out / 'result.json'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("draw", "analyze"):
        p = sub.add_parser(name)
        p.add_argument("--aoi", default="pakistan")
        p.add_argument("--out-dir", type=Path, default=None,
                       help="default results/<aoi>_roofclf_level_review/")
    d = sub.choices["draw"]
    d.add_argument("--grid", type=Path, default=None,
                   help="density grid (default data/predictions/<aoi>/density/grid.geoparquet)")
    d.add_argument("--roofclf-dir", type=Path, default=None,
                   help="national scoring (default data/roofclf_national_with_sppi/<aoi>/prob)")
    d.add_argument("--model-dir", type=Path, default=Path("data/roofclf"),
                   help="`roof-classifier` output: summary.json and buildings.geoparquet (p_oof)")
    d.add_argument("--pricing-summary", type=Path, default=None,
                   help="sub400-capacity's sub400_central_summary.json, for the coverage-ratio "
                        "density bands (default data/roofclf_national_with_sppi/<aoi>/density/)")
    d.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    d.add_argument("--cell-density", type=float, nargs=2, default=(100.0, 1000.0),
                   metavar=("LO", "HI"), help="cell building density band, bldg/km2")
    d.add_argument("--score-edges", default="0,0.01,0.02,0.05,0.1,THR,0.5,1",
                   help="score bin edges; THR is the model's deployment threshold")
    d.add_argument("--n-small", type=int, default=300, help="roofs below 400 m2")
    d.add_argument("--n-large", type=int, default=100, help="roofs of 400 m2 or more")
    d.add_argument("--min-per-stratum", type=int, default=4)
    d.add_argument("--window-start", required=True,
                   help="composite window start the imagery gate measures against")
    d.add_argument("--max-imagery-lag-months", type=int, default=12)
    d.add_argument("--seed", type=int, default=DEFAULT_SEED)
    a = sub.choices["analyze"]
    a.add_argument("--verdicts", type=Path, nargs="+", required=True,
                   help="JOSM-saved .osm, .geojson or the filled review_sheet.csv")
    args = ap.parse_args()
    args.out_dir = args.out_dir or Path("results") / f"{args.aoi}_roofclf_level_review"
    if args.cmd == "draw":
        args.grid = args.grid or Path(f"data/predictions/{args.aoi}/density/grid.geoparquet")
        args.roofclf_dir = args.roofclf_dir or Path(f"data/roofclf_national_with_sppi/{args.aoi}/prob")
        args.pricing_summary = args.pricing_summary or Path(
            f"data/roofclf_national_with_sppi/{args.aoi}/density/sub400_central_summary.json")
        return draw(args)
    return analyze(args)


if __name__ == "__main__":
    sys.exit(main())
