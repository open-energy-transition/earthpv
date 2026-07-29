"""Test the SPPI physics-based PV index (He et al. 2026) against our quadrat ground truth.

Paper: "Spectral-Feature-Driven photovoltaic Detection: A universal Physics-Based index for
rapid Localization", Int. J. Applied Earth Obs. Geoinf. 147 (2026) 105164,
doi:10.1016/j.jag.2026.105164 (todo.md item 12).

    SPPI = (rho_coastal / rho_green)
           * (rho_swir1 - rho_green - |rho_nir - rho_green| - |rho_swir2 - rho_green|)
           / (rho_swir1 + rho_green)

**Band substitution.** SPPI's first term wants B01 (coastal aerosol, 60 m), which earthpv's
10-band composites deliberately exclude (`config.LOCAL_BANDS` drops B01/B09). We use B02
(blue) instead -- the paper's own recommended substitution, which its limitations section
puts at "minimal accuracy loss (+/-2%)". Every term is a ratio or normalized difference, so
the index is invariant to the composites' 1e4 reflectance scaling; no unit handling needed.

**What this measures, and what it does not.** This scores SPPI as a *per-building* signal
over `data/roofclf/buildings.geoparquet` -- the roof-mean reflectance of each footprint,
against exhaustively mapped PV. That is the sub-400 m2 question earthpv actually cares
about, and a harder task than the paper's own validation (pure pixels of utility-scale
plants). It is NOT a replication of the paper's claims: we are asking whether the index
transfers to our regime, not whether it works in theirs.

Run: .pixi/envs/default/bin/python scripts/sppi_index_test.py
Requires `earthpv roof-classifier` to have been run (writes buildings.geoparquet).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from earthpv.roofclf import (
    L2,
    MODEL_FEATURES,
    auc,
    auc_within_size,
    fit_logistic,
    predict_proba,
)
from earthpv.sppi import add_sppi

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "data/roofclf/buildings.geoparquet"
EPS = 1e-6


def add_indices(t: pd.DataFrame) -> pd.DataFrame:
    """SPPI (promoted to `earthpv.sppi.compute_sppi`) plus the two indices the paper
    benchmarks against (SPI, NDPI)."""
    t = add_sppi(t)
    r = t.b04_mean
    n, s1, s2 = t.b08_mean, t.b11_mean, t.b12_mean
    # Tian et al. 2022, as quoted in the paper's eq. 6.
    t["spi"] = ((2 * s1 - (n + s2)) - (n - r).abs() - (n - s2).abs()) / (
        2 * s1 + (n + s2) + EPS
    )
    t["ndpi"] = (s1 - n) / (s1 + n + EPS)
    return t


def per_quadrat(t: pd.DataFrame) -> pd.DataFrame:
    """Raw separability of each index, per quadrat, against the trained-model baselines."""
    rows = []
    for q, gq in t.groupby("quadrat"):
        y, ra = gq.has_pv.to_numpy(), gq.roof_area_m2.to_numpy()
        rec = {"quadrat": q, "n": len(gq), "base_rate": round(float(y.mean()), 3)}
        for k in ("sppi", "spi", "ndpi", "frac_mean", "seg_mean"):
            s = gq[k].to_numpy(float)
            rec[k] = round(auc(y, s), 4)
            rec[f"{k}_ws"] = round(auc_within_size(y, s, ra)[0], 4)
        rows.append(rec)
    return pd.DataFrame(rows)


def area_calibration(t: pd.DataFrame) -> pd.DataFrame:
    """Can SPPI carry *capacity*? Aggregate predicted PV area / true, per quadrat.

    Capacity needs area, and AUC only measures ranking, so this is the test that decides
    whether an SPPI-only density estimator is possible. Same quantity as
    `roofclf.exp_scale_anchor`'s `scale` column, so the numbers are directly comparable to
    the segmentation and fraction-head instruments. Leave-one-quadrat-out linear fit of
    `sppi -> pv_frac_true`, clipped to [0, 1], so the fit never sees the quadrat it scores.
    """
    rows = []
    for q in t.quadrat.unique():
        te = (t.quadrat == q).to_numpy()
        tr = ~te
        A = np.c_[np.ones(tr.sum()), t.loc[tr, "sppi"]]
        coef, *_ = np.linalg.lstsq(A, t.loc[tr, "pv_frac_true"].to_numpy(float), rcond=None)
        pred_frac = np.clip(coef[0] + coef[1] * t.loc[te, "sppi"].to_numpy(float), 0, 1)
        pred = float((pred_frac * t.loc[te, "roof_area_m2"].to_numpy(float)).sum())
        true = float(t.loc[te, "pv_area_true_m2"].sum())
        rows.append({
            "quadrat": q, "pred_m2": round(pred), "true_m2": round(true),
            "scale": round(pred / true, 3) if true > 0 else np.nan,
        })
    return pd.DataFrame(rows).sort_values("scale")


def complementarity(t: pd.DataFrame) -> pd.DataFrame:
    """Does SPPI find PV the fraction head misses, or the same PV?

    Both detectors flag their own top-K buildings, K = the true number of PV buildings in
    that quadrat, so the comparison is at a matched operating point rather than at two
    arbitrary thresholds. Reports the share of true PV *area* each set captures. Note K is
    an oracle here; deployment does not know it, so `union` is an upper bound.
    """
    rows = []
    for q, gq in t.groupby("quadrat"):
        k = int(gq.has_pv.sum())
        tot = float(gq.pv_area_true_m2.sum())
        sp = set(gq.sppi.nlargest(k).index)
        fr = set(gq.frac_mean.nlargest(k).index)
        area = lambda ix: float(gq.loc[list(ix), "pv_area_true_m2"].sum())  # noqa: E731
        rows.append({
            "quadrat": q, "K": k,
            "frac_alone": round(100 * area(fr) / tot, 1),
            "sppi_alone": round(100 * area(sp) / tot, 1),
            "both": round(100 * area(fr & sp) / tot, 1),
            "sppi_only": round(100 * area(sp - fr) / tot, 1),
            "union": round(100 * area(sp | fr) / tot, 1),
        })
    return pd.DataFrame(rows)


def loqo(t: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    """Leave-one-quadrat-out logistic fit, matching roofclf.evaluate's protocol."""
    rows = []
    for q in t.quadrat.unique():
        te = (t.quadrat == q).to_numpy()
        tr = ~te
        model = fit_logistic(
            t.loc[tr, feats].to_numpy(float), t.loc[tr, "has_pv"].to_numpy(float), L2
        )
        p = predict_proba(model, t.loc[te, feats].to_numpy(float))
        y, ra = t.loc[te, "has_pv"].to_numpy(), t.loc[te, "roof_area_m2"].to_numpy()
        rows.append({"quadrat": q, "auc": auc(y, p), "auc_ws": auc_within_size(y, p, ra)[0]})
    return pd.DataFrame(rows)


def main() -> None:
    t = add_indices(gpd.read_parquet(TABLE).copy())
    # roofclf._subset_matrix derives these two inside the model; replicate for loqo().
    t["log_roof_area"] = np.log10(t.roof_area_m2.clip(lower=1.0))
    t["bf_confidence"] = t.bf_confidence.fillna(t.bf_confidence.median())

    pd.set_option("display.width", 250)
    q = per_quadrat(t)
    print("Per-quadrat AUC (_ws = within roof-size band, the honest number):\n")
    print(q.to_string(index=False))
    print("\nMedians:")
    print(q.drop(columns=["quadrat", "n"]).median().round(4).to_string())

    print("\n\nDoes SPPI add anything to the shipped classifier? (leave-one-quadrat-out)\n")
    variants = {
        "default (17 features)": MODEL_FEATURES,
        "default + sppi": MODEL_FEATURES + ["sppi"],
        "log_roof_area + sppi only": ["log_roof_area", "sppi"],
    }
    for label, feats in variants.items():
        d = loqo(t, feats)
        print(f"  {label:28s} auc={d.auc.median():.4f}  auc_within_size={d.auc_ws.median():.4f}")

    print("\n\nCan SPPI carry capacity? Aggregate predicted PV area / true:\n")
    a = area_calibration(t)
    print(a.to_string(index=False))
    print(f"\n  SPPI scale spans {a.scale.min():.3f}-{a.scale.max():.3f} "
          f"({a.scale.max() / a.scale.min():.0f}x). Fraction head, same metric: 0.042-2.077 (49x).")
    print("  Neither is a standalone capacity instrument; note SPPI's worst over-prediction")
    print("  is in the ARID quadrat, which is earthpv's dominant existing false-positive mode.")

    print("\n\nIs SPPI complementary to the fraction head? (% of true PV area captured)\n")
    cm = complementarity(t)
    print(cm.to_string(index=False))
    print("\n  medians: " + "  ".join(
        f"{k}={cm[k].median():.1f}%" for k in ("frac_alone", "sppi_alone", "both", "sppi_only", "union")
    ))


if __name__ == "__main__":
    main()
