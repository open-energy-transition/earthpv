"""Correlate each quadrat's PV density against how well the detectors do there.

The project has asserted a density-vs-detection-quality relationship in several places
(`packing_density`'s r=0.70-0.82, the `rate_ratio` "crossing point" at ~12% base rate).
This computes all of them from the artifacts on disk in one pass, so the numbers in
`docs/methods/density.md` are reproducible rather than remembered, and so a new quadrat
updates them instead of invalidating them.

Two things are deliberately kept apart, because conflating them is how "denser is better"
gets asserted:

- **Discrimination** (`*_auc*`): can the instrument tell a PV pixel/building from a
  non-PV one *within* this quadrat. Scale-free, and what you want if you are ranking.
- **Bias** (`*scale*`, `rate_ratio`): does the instrument predict the right *amount*.
  A quadrat can rank perfectly and still be 3x high.

A correlation with one says nothing about the other. Reported with n, Spearman (rank,
robust at this sample size) alongside Pearson, and a partial correlation controlling for
median installation size -- because size regime and density are entangled across these
quadrats (industrial estates are simultaneously large-array, sparsely packed and
high-AUC), so an unconditional correlation cannot say which one is doing the work.

    python scripts/quadrat_correlations.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

QUADRATS = Path("results/calibration_quadrats.csv")
FRACTION = Path("results/fraction_quadrat_validation.csv")
# The 9-quadrat LOQO run is the widest fold table on disk; `data/roofclf/` currently
# holds the later 7-quadrat (no-Quetta, no-KP) re-fit, which is a smaller sample.
FOLDS = Path("data/roofclf_with_quetta_20260730/folds.csv")
ANCHOR = Path("data/roofclf_with_quetta_20260730/exp_scale_anchor.csv")

# Density/geometry measures. `nn_median_m` is inverse density (bigger = sparser), so a
# sign flip is expected against the others -- do not read it as a contradiction.
DENSITY = {
    "base_rate": "share of buildings carrying PV",
    "pv_area_per_km2": "mapped PV area per km²",
    "installs_per_km2": "mapped installations per km²",
    "nn_median_m": "packing distance, m (INVERSE density)",
    "median_install_m2": "median installation size, m² (size regime, not density)",
    "frac_sub400": "share of installations below the 400 m² floor",
}

QUALITY = {
    # discrimination
    "auc_seg_baseline": ("discrimination", "segmentation raster, per building"),
    "auc_frac_baseline": ("discrimination", "fraction head, per building"),
    "auc_within_size_seg": ("discrimination", "segmentation, within size band"),
    "auc": ("discrimination", "roofclf LOQO"),
    "auc_within_size": ("discrimination", "roofclf, within size band"),
    "v1_auc": ("discrimination", "fraction v1, pixel-level"),
    "hn_auc": ("discrimination", "fraction hard-neg, pixel-level"),
    # bias
    "scale_seg": ("bias", "segmentation predicted/true area"),
    "scale_frac": ("bias", "fraction head predicted/true area"),
    "v1_scale": ("bias", "fraction v1 predicted/true, pixel integral"),
    "hn_scale": ("bias", "fraction hard-neg predicted/true"),
    "rate_ratio": ("bias", "roofclf predicted/true adoption rate"),
}


def load() -> pd.DataFrame:
    q = pd.read_csv(QUADRATS)
    q["pv_area_per_km2"] = q.total_pv_area_m2 / q.area_km2
    q["installs_per_km2"] = q.n_installations / q.area_km2
    df = q[["quadrat", "label", "area_km2", "base_rate", "nn_median_m",
            "median_install_m2", "frac_sub400", "pv_area_per_km2",
            "installs_per_km2", "rule1_complete"]].copy()

    if FOLDS.exists():
        f = pd.read_csv(FOLDS).rename(columns={"quadrat": "label"})
        keep = ["label", "auc", "auc_small", "auc_within_size", "auc_seg_baseline",
                "auc_frac_baseline", "auc_within_size_seg", "rate_ratio"]
        df = df.merge(f[[c for c in keep if c in f.columns]], on="label", how="left")

    if ANCHOR.exists():
        a = pd.read_csv(ANCHOR).rename(columns={"quadrat": "label"})
        wide = a.pivot_table(index="label", columns="instrument", values="scale")
        wide.columns = [f"scale_{c}" for c in wide.columns]
        df = df.merge(wide.reset_index(), on="label", how="left")

    if FRACTION.exists():
        fr = pd.read_csv(FRACTION)
        keep = ["quadrat", "v1_scale", "hn_scale", "v1_auc", "hn_auc"]
        df = df.merge(fr[[c for c in keep if c in fr.columns]], on="quadrat", how="left")
    return df


def _partial(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple[float, int]:
    """Pearson r between x and y with z linearly removed from both. Returns NaN below
    n=5, where a partial correlation on one control has essentially no residual df."""
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    if ok.sum() < 5:
        return float("nan"), int(ok.sum())
    xr = x[ok] - np.polyval(np.polyfit(z[ok], x[ok], 1), z[ok])
    yr = y[ok] - np.polyval(np.polyfit(z[ok], y[ok], 1), z[ok])
    return float(stats.pearsonr(xr, yr)[0]), int(ok.sum())


def correlate(df: pd.DataFrame, control: str = "median_install_m2") -> pd.DataFrame:
    rows = []
    for dname in DENSITY:
        if dname not in df:
            continue
        for qname, (kind, qdesc) in QUALITY.items():
            if qname not in df:
                continue
            sub = df[[dname, qname]].apply(pd.to_numeric, errors="coerce").dropna()
            n = len(sub)
            if n < 4:
                continue
            x, y = sub[dname].to_numpy(), sub[qname].to_numpy()
            r, rp = stats.pearsonr(x, y)
            rho, sp = stats.spearmanr(x, y)
            pr, pn = (float("nan"), 0) if dname == control else _partial(
                df[dname].to_numpy(dtype="float64"),
                pd.to_numeric(df[qname], errors="coerce").to_numpy(dtype="float64"),
                df[control].to_numpy(dtype="float64"),
            )
            rows.append({
                "density_measure": dname, "quality_measure": qname, "kind": kind,
                "quality_desc": qdesc, "n": n,
                "pearson_r": round(float(r), 3), "pearson_p": round(float(rp), 4),
                "spearman_rho": round(float(rho), 3), "spearman_p": round(float(sp), 4),
                f"partial_r_given_{control}": (None if np.isnan(pr) else round(pr, 3)),
                "partial_n": pn or None,
            })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/quadrat_detection_correlations.csv")
    ap.add_argument("--control", default="median_install_m2")
    args = ap.parse_args()

    df = load()
    print("per-quadrat inputs:")
    cols = ["label", "area_km2", "base_rate", "installs_per_km2", "pv_area_per_km2",
            "nn_median_m", "median_install_m2", "auc_seg_baseline", "auc_within_size",
            "scale_frac", "hn_auc", "rate_ratio"]
    print(df[[c for c in cols if c in df]].round(3).to_string(index=False))

    cor = correlate(df, args.control)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cor.to_csv(args.out, index=False)

    pcol = f"partial_r_given_{args.control}"
    for kind in ("discrimination", "bias"):
        k = cor[cor.kind == kind]
        print(f"\n=== density vs {kind.upper()} (|rho| descending) ===")
        show = k.reindex(k.spearman_rho.abs().sort_values(ascending=False).index)
        print(show[["density_measure", "quality_measure", "n", "pearson_r",
                    "spearman_rho", "spearman_p", pcol]].head(18).to_string(index=False))

    print(f"\n{len(cor)} pairs -> {args.out}")
    print(f"\nn is 7-13 per pair and {len(cor)} pairs were tested, so an individual p "
          "below 0.05 is not evidence on its own -- read the pre-registered hypotheses "
          "(packing distance, base rate vs bias) and treat the rest as exploratory.")


if __name__ == "__main__":
    main()
