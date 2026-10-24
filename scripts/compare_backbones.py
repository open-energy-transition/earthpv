"""Score several segmentation checkpoints on the same held-out chips, paired per installation.

`compare_local_vs_v5.py` is the ship rule for one country: pooled recall >= 500 m2, then IoU.
This asks a different question -- does an architecture change help, and WHERE -- so it
reports per-installation recall by size bin and placement, pixel precision and IoU, and an
exact McNemar test on the installations one checkpoint finds and the other misses. The test
is paired on (val chip, installation), which every checkpoint sees identically, because a
pooled recall difference of a few points is within run-to-run noise on a few hundred
installations.

**Recall is compared at matched precision as well as at the production threshold.** A
detector that marks more pixels finds more installations: a 50-step smoke model that labels
almost everything PV scored recall 0.97 against v14's 0.75 at pixel IoU 0.02. So every
checkpoint is scored at several thresholds from one inference pass, the baseline's pooled
pixel precision at the production threshold is the target, and each other checkpoint is
also compared at the lowest threshold whose pooled pixel precision reaches it.

Every AOI's own `val` split is scored (`data/chips/<aoi>/index.parquet`) against the
Overpass labels `evaluate` always uses. For a fair comparison every checkpoint must have
been trained on a corpus that holds those chips out; AOIs outside every corpus are a
zero-shot transfer test for all of them alike. `--match-aois` (default: every AOI) sets
which AOIs the precision target is pooled over.

    python scripts/compare_backbones.py --name thor_vs_v14 \\
        --ckpt v14=data/models/v14_combined_south_africa/<best>.ckpt \\
        --ckpt thor8=data/models/thor_ps8_combined_south_africa/<best>.ckpt \\
        --aois south_africa france germany pakistan punjab gujarat poland vietnam \\
        --match-aois south_africa france germany pakistan punjab gujarat

Writes `results/backbone_compare/<name>/installations.csv` (checkpoint x threshold x AOI x
installation), `pixels.csv`, `summary.json`, and prints the paired tests. The first --ckpt
is the baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from math import comb
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

SIZE_BINS = [(0, 250), (250, 400), (400, 1000), (1000, 5000), (5000, float("inf"))]
KEY = ["aoi", "chip_id", "label_idx"]
SUBSETS = {
    "all": lambda w: slice(None),
    "ge400": lambda w: w.size_bin.isin(["400-1000", "1000-5000", "5000-inf"]),
    "rooftop_400_5000": lambda w: (w.placement == "rooftop")
    & w.size_bin.isin(["400-1000", "1000-5000"]),
    "ground_ge400": lambda w: (w.placement == "ground")
    & w.size_bin.isin(["400-1000", "1000-5000", "5000-inf"]),
}


def _bin(a: float) -> str:
    for lo, hi in SIZE_BINS:
        if lo <= a < hi:
            return f"{int(lo)}-{'inf' if hi == float('inf') else int(hi)}"
    return "unknown"


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def pixel_stats(px: pd.DataFrame) -> dict:
    tp, fp, fn = (int(px[c].sum()) for c in ("tp", "fp", "fn"))
    return dict(precision=round(tp / max(tp + fp, 1), 4), recall=round(tp / max(tp + fn, 1), 4),
                iou=round(tp / max(tp + fp + fn, 1), 4), tp=tp, fp=fp, fn=fn)


def recall_table(d: pd.DataFrame) -> list[dict]:
    return [dict(placement=p, size_bin=b, n=len(g), detected=int(g.detected.sum()),
                 recall=round(float(g.detected.mean()), 4))
            for (p, b), g in d.groupby(["placement", "size_bin"])]


def paired(inst: pd.DataFrame, new: tuple[str, float], base: tuple[str, float]) -> dict:
    """McNemar per subset between checkpoint/threshold `new` and `base`."""
    a = inst[(inst.ckpt == new[0]) & (inst.thr == new[1])].set_index(KEY)
    b = inst[(inst.ckpt == base[0]) & (inst.thr == base[1])].set_index(KEY)
    w = a[["placement", "size_bin", "detected"]].join(
        b[["detected"]].rename(columns={"detected": "base"}), how="inner")
    w["detected"], w["base"] = w.detected.astype(bool), w.base.astype(bool)
    out = {}
    for name, sel in SUBSETS.items():
        s = w.loc[sel(w)]
        only_new, only_base = int((s.detected & ~s.base).sum()), int((~s.detected & s.base).sum())
        out[name] = dict(n=len(s), recall_new=round(float(s.detected.mean()), 4) if len(s) else None,
                         recall_base=round(float(s.base.mean()), 4) if len(s) else None,
                         only_new=only_new, only_base=only_base,
                         p_mcnemar=round(mcnemar_exact(only_new, only_base), 4))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--ckpt", action="append", required=True, help="label=path; first is baseline")
    ap.add_argument("--aois", nargs="+", required=True)
    ap.add_argument("--match-aois", nargs="+", default=None)
    ap.add_argument("--threshold", type=float, default=0.3, help="production operating point")
    ap.add_argument("--thresholds", type=float, nargs="+",
                    default=[0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    a = ap.parse_args()

    from earthpv.evaluate import evaluate

    ckpts = [c.split("=", 1) for c in a.ckpt]
    base = ckpts[0][0]
    extra = tuple(t for t in a.thresholds if t != a.threshold)
    out_dir = REPO / "results" / "backbone_compare" / a.name
    out_dir.mkdir(parents=True, exist_ok=True)

    inst_rows, px_rows = [], []
    aois = [x for x in a.aois if (REPO / "data" / "chips" / x / "index.parquet").exists()]
    for aoi in aois:
        for label, path in ckpts:
            t0 = time.time()
            rep = evaluate(aoi=aoi, checkpoint=Path(path), chips_dir=REPO / "data" / "chips",
                           threshold=a.threshold, extra_thresholds=extra)
            recs = pd.DataFrame(rep.attrs["installations"],
                                columns=["chip_id", "label_idx", "area_m2", "placement", "detected"])
            for t in (a.threshold, *extra):
                r = recs.copy()
                if t != a.threshold:
                    r["detected"] = rep.attrs["by_threshold"][t]["hits"]
                    px = {k: rep.attrs["by_threshold"][t][k] for k in ("tp", "fp", "fn")}
                else:
                    px = rep.attrs["pixel_counts"]
                r["aoi"], r["ckpt"], r["thr"] = aoi, label, t
                inst_rows.append(r)
                px_rows.append(dict(aoi=aoi, ckpt=label, thr=t, **px))
            print(f"{aoi} {label}: IoU@{a.threshold} {rep.attrs['pixel_iou']:.4f}, "
                  f"{int(recs.detected.sum())}/{len(recs)} installations, {time.time()-t0:.0f} s",
                  flush=True)

    inst = pd.concat(inst_rows, ignore_index=True)
    inst["size_bin"] = inst.area_m2.map(_bin)
    px = pd.DataFrame(px_rows)
    inst.to_csv(out_dir / "installations.csv", index=False)
    px.to_csv(out_dir / "pixels.csv", index=False)

    match_aois = a.match_aois or aois
    pm = px[px.aoi.isin(match_aois)]
    target = pixel_stats(pm[(pm.ckpt == base) & (pm.thr == a.threshold)])["precision"]
    operating = {base: dict(thr=a.threshold, precision=target, reached=True)}
    for label, _ in ckpts[1:]:
        curve = sorted((t, pixel_stats(pm[(pm.ckpt == label) & (pm.thr == t)])["precision"])
                       for t in pm[pm.ckpt == label].thr.unique())
        ok = [(t, p) for t, p in curve if p >= target]
        t, p = ok[0] if ok else curve[-1]
        operating[label] = dict(thr=t, precision=p, reached=bool(ok),
                                curve={str(tt): pp for tt, pp in curve})

    summary = {"name": a.name, "baseline": base, "checkpoints": dict(ckpts),
               "production_threshold": a.threshold, "match_aois": match_aois,
               "precision_target": target, "operating_points": operating, "aois": {}}
    for key in [*aois, "ALL"]:
        sub = inst if key == "ALL" else inst[inst.aoi == key]
        spx = px if key == "ALL" else px[px.aoi == key]
        block = {}
        for label, _ in ckpts:
            t_op = operating[label]["thr"]
            block[label] = {
                f"at_{a.threshold}": dict(
                    pixel=pixel_stats(spx[(spx.ckpt == label) & (spx.thr == a.threshold)]),
                    recall=recall_table(sub[(sub.ckpt == label) & (sub.thr == a.threshold)])),
                "at_matched_precision": dict(
                    thr=t_op, pixel=pixel_stats(spx[(spx.ckpt == label) & (spx.thr == t_op)]),
                    recall=recall_table(sub[(sub.ckpt == label) & (sub.thr == t_op)])),
            }
        block["paired"] = {}
        for label, _ in ckpts[1:]:
            block["paired"][f"{label}_vs_{base}_at_{a.threshold}"] = paired(
                sub, (label, a.threshold), (base, a.threshold))
            block["paired"][f"{label}_vs_{base}_at_matched_precision"] = paired(
                sub, (label, operating[label]["thr"]), (base, a.threshold))
        summary["aois"][key] = block

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nprecision target (baseline {base} @ {a.threshold}, pooled over {match_aois}): {target}")
    for label, op in operating.items():
        print(f"  {label}: threshold {op['thr']} precision {op['precision']} reached={op['reached']}")
    print("\n== paired tests ==")
    for key, block in summary["aois"].items():
        for cmp_name, tests in block["paired"].items():
            for sname, t in tests.items():
                print(f"{key:13s} {cmp_name:38s} {sname:17s} n={t['n']:5d} "
                      f"new={t['recall_new']} base={t['recall_base']} "
                      f"+{t['only_new']}/-{t['only_base']} p={t['p_mcnemar']}")
    print(f"\n-> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
