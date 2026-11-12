"""A zero-shot test suite: chips from countries a training corpus never saw, for a baseline model.

The released model is what a country with no local labels starts from, so a candidate baseline
must be judged where it has never been trained. The holdouts `fair_score.py` scores hold only
270 rooftop arrays of 400-5,000 m2 outside v14's corpus, too few to see a three-point change
(2026-11-06: v14's epoch average gains 3 points on in-corpus holdouts and ties on these). But
for a model trained on a corpus, EVERY chip of a country outside it is unseen, not only that
country's val split.

    build   per AOI: its whole chip index, minus any chip within --exclude-km of a corpus chip
            (India's chips around Gujarat, which v14's corpus holds), sampled up to
            --max-chips per AOI stratified by chip kind (seeded), every row marked `val`, into
            data/chips/zs_<aoi>/index.parquet (images and masks stay where they are). Score
            with fair_score.py as `zs_<aoi>@<aoi>`.
    report  pools a fair_score result over the zs_ chip sets: each checkpoint at its matched
            ("standard") operating point against the baseline at its production threshold,
            rooftop 400-5,000 m2 and ground >= 400 m2, paired McNemar, per AOI and pooled.

The suite is zero-shot only for models trained on --corpus (v14, v22, v27 and v28 all train on
combined_south_africa); `build` records the corpus in each set's manifest.

    pixi run python scripts/zero_shot_suite.py build --corpus combined_south_africa
    pixi run python scripts/zero_shot_suite.py report --name zeroshot_suite_vs_v14
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

CHIPS = REPO / "data" / "chips"
DEFAULT_AOIS = ["turkiye", "poland", "vietnam", "india", "morocco", "egypt", "namibia",
                "zambia", "nigeria", "yemen"]
PREFIX = "zs_"
EARTH_KM = 6371.0


def _xyz(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    lo, la = np.radians(lon), np.radians(lat)
    return np.c_[np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]


def cmd_build(a) -> None:
    from scipy.spatial import cKDTree

    corpus = pd.read_parquet(CHIPS / a.corpus / "index.parquet")
    tree = cKDTree(_xyz(corpus.lon.to_numpy(), corpus.lat.to_numpy()))
    chord = 2 * np.sin(a.exclude_km / EARTH_KM / 2)  # great-circle km -> unit-sphere chord
    corpus_images = set(corpus.image)
    for aoi in a.aois:
        idx = pd.read_parquet(CHIPS / aoi / "index.parquet")
        near = np.array([bool(n) for n in tree.query_ball_point(
            _xyz(idx.lon.to_numpy(), idx.lat.to_numpy()), chord)], bool)
        keep = idx[~near & ~idx.image.isin(corpus_images)]
        parts = []
        for kind, g in keep.groupby("kind"):
            n = min(len(g), int(round(a.max_chips * len(g) / max(len(keep), 1))))
            parts.append(g.sample(n=n, random_state=a.seed) if n < len(g) else g)
        out = pd.concat(parts).sort_values("chip_id").assign(split="val").reset_index(drop=True)
        d = CHIPS / f"{PREFIX}{aoi}"
        d.mkdir(parents=True, exist_ok=True)
        out.to_parquet(d / "index.parquet")
        manifest = dict(source=aoi, corpus=a.corpus, built=time.strftime("%F %T"),
                        exclude_km=a.exclude_km, max_chips=a.max_chips, seed=a.seed,
                        n_source=len(idx), n_near_corpus=int(near.sum()), n_chips=len(out),
                        kinds=out.kind.value_counts().to_dict())
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"{PREFIX}{aoi:10s} {len(out):5d} chips of {len(idx)} "
              f"({int(near.sum())} within {a.exclude_km:g} km of the corpus) {manifest['kinds']}")


def _hits(inst: pd.DataFrame, ckpt: str, thr: float) -> pd.Series:
    d = inst[inst.ckpt == ckpt].set_index(["aoi", "chip_id", "label_idx"])
    return d.maxprob >= thr


def cmd_report(a) -> None:
    from compare_backbones import mcnemar_exact

    rdir = REPO / "results" / "fair_score" / a.name
    summary = json.loads((rdir / "summary.json").read_text())
    inst = pd.read_csv(rdir / "installations.csv")
    px = pd.read_csv(rdir / "pixels.csv")
    inst = inst[inst.aoi.str.startswith(PREFIX)]
    px = px[px.aoi.str.startswith(PREFIX)]
    base = summary["baseline"]
    t0 = summary["production_threshold"]
    ref = inst[inst.ckpt == base].set_index(["aoi", "chip_id", "label_idx"])
    roof = (ref.placement == "rooftop") & ref.size_bin.isin(["400-1000", "1000-5000"])
    ground = (ref.placement == "ground") & ref.size_bin.isin(["400-1000", "1000-5000", "5000-inf"])
    b = _hits(inst, base, t0)

    def precision(ckpt, thr, aois=None):
        g = px[(px.ckpt == ckpt) & np.isclose(px.thr, thr)]
        if aois is not None:
            g = g[g.aoi.isin(aois)]
        return float(g.tp.sum() / max(g.tp.sum() + g.fp.sum(), 1))

    out = {"name": a.name, "baseline": base, "zero_shot_sets": sorted(inst.aoi.unique()),
           "checkpoints": {}}
    lines = [f"Zero-shot suite ({', '.join(out['zero_shot_sets'])}), {a.name}",
             f"baseline {base} at {t0}; others at their matched ('standard') threshold"]
    for ckpt in summary["checkpoints"]:
        op = summary["operating_points"][ckpt]["standard"]
        thr = t0 if ckpt == base else op["thr"]
        h = _hits(inst, ckpt, thr).reindex(b.index)
        row = {"threshold": thr, "precision_target_reached": op.get("reached", True),
               "pixel_precision_zero_shot": round(precision(ckpt, thr), 4)}
        for lab, m in (("rooftop_400_5000", roof), ("ground_ge400", ground)):
            gain, loss = int((h & ~b)[m].sum()), int((~h & b)[m].sum())
            row[lab] = dict(n=int(m.sum()), recall=round(float(h[m].mean()), 4),
                            baseline=round(float(b[m].mean()), 4), gained=gain, lost=loss,
                            p=float(mcnemar_exact(gain, loss)))
        row["by_aoi_rooftop"] = {
            aoi: dict(n=int(m.sum()), recall=round(float(h[m].mean()), 3),
                      baseline=round(float(b[m].mean()), 3))
            for aoi in sorted(inst.aoi.unique())
            for m in [roof & (ref.index.get_level_values("aoi") == aoi)] if m.sum()}
        out["checkpoints"][ckpt] = row
        r, g = row["rooftop_400_5000"], row["ground_ge400"]
        lines.append(
            f"{ckpt:14s} thr {thr:<8.4g} P {row['pixel_precision_zero_shot']:.3f}  "
            f"rooftop {r['recall']:.3f} vs {r['baseline']:.3f} (n={r['n']}, +{r['gained']}/"
            f"-{r['lost']}, p={r['p']:.2g})  ground {g['recall']:.3f} vs {g['baseline']:.3f} "
            f"(n={g['n']}, +{g['gained']}/-{g['lost']}, p={g['p']:.2g})"
            + ("" if row["precision_target_reached"] else "  [precision target not reached]"))
    (rdir / "zero_shot_report.json").write_text(json.dumps(out, indent=2))
    (rdir / "zero_shot_report.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--corpus", default="combined_south_africa")
    b.add_argument("--aois", nargs="+", default=DEFAULT_AOIS)
    b.add_argument("--max-chips", type=int, default=1000)
    b.add_argument("--exclude-km", type=float, default=5.0)
    b.add_argument("--seed", type=int, default=20261106)
    r = sub.add_parser("report")
    r.add_argument("--name", required=True)
    a = ap.parse_args()
    {"build": cmd_build, "report": cmd_report}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
