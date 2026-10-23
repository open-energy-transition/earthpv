#!/usr/bin/env python
"""Source data for the docs' "How roofclf sees panels" page: what panels do to a roof's spectrum.

Reads the gitignored roofclf building table (`data/roofclf/buildings.geoparquet`, the
production refit) and writes one small tracked file that `scripts/build_docs_figures.py`
turns into the `roofclf_covered_spectra` figure. Same arrangement as
`detection_domain_examples.py`: the docs CI cannot read `data/`, so the CSV is the
interface to the site.

Output
  results/roofclf_covered_roof_spectra.csv   one row per band:
    free_q25/free_med/free_q75   PV-free roofs, resampled to the covered group's roof-size
                                 mix (so the gap is not a size effect in disguise)
    covered_med                  roofs whose mapped PV covers at least 60% of the footprint
    fit_bare/fit_full            band mean regressed on the roof's PV cover fraction f over
                                 every building: the linear-mixing endmembers at f = 0 and
                                 f = 1 (f = 1 is still a footprint average, not a bare module)
    free_sd                      standard deviation between PV-free roofs, i.e. the noise
    n_free/n_covered/median_cover_pv   sample sizes and the median PV roof's cover fraction

Cover fraction uses `pv_area_roof_m2` (mapped PV on the footprint itself), not the parcel
label's yard-inclusive `pv_area_true_m2`, because the question is what the roof pixels see.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "data" / "roofclf" / "buildings.geoparquet"
OUT = ROOT / "results" / "roofclf_covered_roof_spectra.csv"

BANDS = ("b02", "b03", "b04", "b05", "b06", "b07", "b08", "b8a", "b11", "b12")
# Nominal Sentinel-2 centre wavelengths, as in detection_domain_examples.WAVELENGTH_NM.
WAVELENGTH_NM = {
    "b02": 490, "b03": 560, "b04": 665, "b05": 705, "b06": 740,
    "b07": 783, "b08": 842, "b8a": 865, "b11": 1610, "b12": 2190,
}
# Native resolution at the sensor; the 20 m bands average in more of the surroundings.
NATIVE_M = {"b02": 10, "b03": 10, "b04": 10, "b08": 10,
            "b05": 20, "b06": 20, "b07": 20, "b8a": 20, "b11": 20, "b12": 20}
COVERED_MIN = 0.6


def weighted_quantile(v: np.ndarray, w: np.ndarray, q: float) -> float:
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(np.interp(q, c / c[-1], v[o]))


def main() -> None:
    cols = ["has_pv", "roof_area_m2", "pv_area_roof_m2"] + [f"{b}_mean" for b in BANDS]
    t = pd.read_parquet(TABLE, columns=cols).dropna(subset=[f"{b}_mean" for b in BANDS])
    cover = (t.pv_area_roof_m2.fillna(0.0) / t.roof_area_m2).clip(0.0, 1.0)
    free = t[t.has_pv == 0]
    covered = t[(t.has_pv == 1) & (cover >= COVERED_MIN)]

    # Resample PV-free roofs to the covered group's roof-size deciles.
    edges = np.quantile(covered.roof_area_m2, np.linspace(0, 1, 11))[1:-1]
    fb = np.digitize(free.roof_area_m2, edges)
    share = np.bincount(np.digitize(covered.roof_area_m2, edges), minlength=10) / len(covered)
    w = share[fb] / np.bincount(fb, minlength=10)[fb]

    f = cover.to_numpy()
    design = np.column_stack([np.ones(len(t)), f])
    med_cover = float(cover[t.has_pv == 1].median())

    rows = []
    for b in BANDS:
        c = f"{b}_mean"
        v = free[c].to_numpy(float)
        intercept, slope = np.linalg.lstsq(design, t[c].to_numpy(float), rcond=None)[0]
        rows.append({
            "band": b.upper(), "wavelength_nm": WAVELENGTH_NM[b], "native_m": NATIVE_M[b],
            "free_q25": weighted_quantile(v, w, 0.25), "free_med": weighted_quantile(v, w, 0.5),
            "free_q75": weighted_quantile(v, w, 0.75),
            "covered_med": float(covered[c].median()),
            "fit_bare": float(intercept), "fit_full": float(intercept + slope),
            "free_sd": float(v.std()),
            "n_free": len(free), "n_covered": len(covered), "median_cover_pv": med_cover,
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        for r in rows:
            wr.writerow({k: (f"{x:.4f}" if isinstance(x, float) else x) for k, x in r.items()})
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
