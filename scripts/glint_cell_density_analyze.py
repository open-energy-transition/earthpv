"""Does cell-aggregate glint spike-count correlate with known true PV density?

Reuses `glint.annotate_spikes`'s clear/spike logic (renaming the cell pull's p90_*
columns to the p98_* names it expects -- the exact percentile doesn't matter, only
consistent naming) against each 300m cell's whole-neighbourhood reflectance series
(built by `glint_cell_density_pull.py`, wide 150-450m external ring instead of the
per-installation 30m annulus).

Usage:
  .pixi/envs/default/bin/python scripts/glint_cell_density_analyze.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

OUT_DIR = DATA_DIR / "glint_cell"
SERIES_DIR = OUT_DIR / "series"
CELLS_FILE = OUT_DIR / "cells.parquet"


def cell_spike_stats(d: pd.DataFrame, tol_deg: float = 3.0) -> dict:
    d = d.rename(columns={"p90_B03": "p98_B03", "p90_B08": "p98_B08"})
    ann = glint.annotate_spikes(d)
    if ann.empty:
        return dict(n_scenes=len(d), n_clear=0, n_spikes=0, med_amp=np.nan)
    n_spikes = int(ann.spike.sum())
    amp = np.nan
    if n_spikes:
        base = {b: ann.loc[ann.clear, f"a_{b}"].median() for b in ("B03", "B08")}
        ratios = [ann.loc[ann.spike, f"a_{b}"] / max(base[b], 1e-6) for b in ("B03", "B08")]
        amp = float(pd.concat(ratios).median())
    return dict(n_scenes=len(d), n_clear=int(ann.clear.sum()), n_spikes=n_spikes, med_amp=amp)


def main() -> None:
    cells = gpd.read_parquet(CELLS_FILE)
    rows = []
    for r in cells.itertuples():
        p = SERIES_DIR / f"{r.cid}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty:
            stats = dict(n_scenes=0, n_clear=0, n_spikes=0, med_amp=np.nan)
        else:
            stats = cell_spike_stats(d)
        rows.append(dict(cid=r.cid, stratum=r.stratum, area_m2=r.area_m2,
                         n_install=r.n_install, **stats))
    s = pd.DataFrame(rows)
    s.to_csv(OUT_DIR / "cell_density_summary.csv", index=False)
    print(f"{len(s)} cells analyzed (of {len(cells)} total)")
    print(s.groupby("stratum").agg(
        n=("cid", "count"), med_area=("area_m2", "median"),
        med_scenes=("n_scenes", "median"), med_spikes=("n_spikes", "median"),
        med_amp=("med_amp", "median"),
    ).round(2))

    print("\n=== per-cell detail ===")
    print(s.sort_values("area_m2", ascending=False)
          [["cid", "stratum", "area_m2", "n_install", "n_scenes", "n_clear", "n_spikes", "med_amp"]]
          .to_string(index=False))

    valid = s[s.n_scenes > 0]
    print(f"\nn={len(valid)} cells with usable scene data")
    print("correlation matrix (area_m2, n_install, n_spikes):")
    print(valid[["area_m2", "n_install", "n_spikes"]].corr().round(3))

    log_area = np.log1p(valid.area_m2)
    print(f"\ncorrelation(n_spikes, log1p(area_m2)) = {np.corrcoef(valid.n_spikes, log_area)[0,1]:.3f}")
    print(f"correlation(n_spikes, n_install)      = {np.corrcoef(valid.n_spikes, valid.n_install)[0,1]:.3f}")

    zero = valid[valid.stratum == "zero"]
    nonzero = valid[valid.stratum != "zero"]
    print(f"\nzero-density controls (n={len(zero)}): mean n_spikes={zero.n_spikes.mean():.2f}, "
          f"median={zero.n_spikes.median():.1f}")
    print(f"PV-bearing cells (n={len(nonzero)}): mean n_spikes={nonzero.n_spikes.mean():.2f}, "
          f"median={nonzero.n_spikes.median():.1f}")


if __name__ == "__main__":
    main()
