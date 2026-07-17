"""Does glint corroboration recover density-relevant PV area at an acceptable
false-positive cost?

`glint_density_targets.py` split each region into `missed` (true OSM/GT installations
the production model's own thresholded mask does not overlap -- exactly the gap between
density.py's pv_area_det floor and the true regional total) and `control` (real
buildings with no PV at all, same footprint-size range). This pulls each group's glint
scene series (`glint_density_pull.py`) and asks: does `glint_consistent >= 2`
(the same "validated" criterion the 500-target country study calibrated) fire far more
on `missed` (real, undetected PV) than on `control` (no PV) -- and if applied as a rule
("add the missed installation's area to pv_area_det when validated"), how much of the
missing area would be recovered vs. how much phantom area would be added from control
false-positives?

Usage:
  .pixi/envs/default/bin/python scripts/glint_density_analyze.py lahore
  .pixi/envs/default/bin/python scripts/glint_density_analyze.py germany
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from earthpv.config import DATA_DIR  # noqa: E402
from glint_validation import analyze_point  # noqa: E402

log = logging.getLogger("glint_density_analyze")
app = typer.Typer(pretty_exceptions_show_locals=False)


@app.command()
def main(region: str = typer.Argument(...), tol_deg: float = 3.0):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tgts = gpd.read_parquet(DATA_DIR / "glint" / f"{region}_density_targets.parquet")
    series_dir = DATA_DIR / "glint" / f"{region}_density"

    rows = []
    for r in tgts.itertuples():
        p = series_dir / f"{r.pid}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        if d.empty:
            res = dict(n_scenes=0, n_clear=0, n_spikes=0, n_consistent=0)
        else:
            res, _ = analyze_point(d, tol_deg)
        rows.append(dict(pid=r.pid, kind=r.kind, area_m2=r.area_m2,
                         n_scenes=res["n_scenes"], n_spikes=res["n_spikes"],
                         n_consistent=res["n_consistent"]))
    s = pd.DataFrame(rows)
    s["detected"] = s.n_spikes >= 1
    s["validated"] = s.n_consistent >= 2
    s.to_csv(DATA_DIR / "glint" / f"{region}_density_summary.csv", index=False)

    missed, control = s[s.kind == "missed"], s[s.kind == "control"]
    print(f"\n=== {region}: glint corroboration rates ===")
    print(f"missed (n={len(missed)}): detected={100*missed.detected.mean():.1f}%  "
          f"validated={100*missed.validated.mean():.1f}%")
    print(f"control (n={len(control)}): detected={100*control.detected.mean():.1f}%  "
          f"validated={100*control.validated.mean():.1f}%")

    true_missed_area = missed.area_m2.sum()
    recovered_area = missed.loc[missed.validated, "area_m2"].sum()
    n_control_fp = int(control.validated.sum())
    control_fp_rate = control.validated.mean() if len(control) else float("nan")

    print(f"\nMissed area total: {true_missed_area:,.0f} m2")
    print(f"Recovered (validated-missed) area: {recovered_area:,.0f} m2 "
          f"({100*recovered_area/max(true_missed_area,1):.1f}% of the gap)")
    print(f"Control false-validation rate: {100*control_fp_rate:.1f}% "
          f"({n_control_fp}/{len(control)} non-PV buildings would spuriously validate)")

    bins = [0, 500, 1000, 5000, 50000, np.inf]
    labels = ["<500", "500-1k", "1k-5k", "5k-50k", ">50k"]
    missed = missed.copy()
    missed["bucket"] = pd.cut(missed.area_m2, bins=bins, labels=labels)
    by_bucket = missed.groupby("bucket", observed=True).agg(
        n=("pid", "count"), area=("area_m2", "sum"),
        pct_detected=("detected", lambda x: round(100 * x.mean(), 1)),
        pct_validated=("validated", lambda x: round(100 * x.mean(), 1)),
        area_recovered=("area_m2", lambda x: x[missed.loc[x.index, "validated"]].sum()),
    )
    print(f"\n=== {region}: missed installations by size bucket ===")
    print(by_bucket.to_string())

    meta = dict(
        region=region, n_missed=len(missed), n_control=len(control),
        true_missed_area_m2=round(float(true_missed_area), 1),
        recovered_area_m2=round(float(recovered_area), 1),
        recovery_pct=round(100 * recovered_area / max(true_missed_area, 1), 2),
        control_fp_rate_pct=round(100 * float(control_fp_rate), 2),
        n_control_fp=n_control_fp,
    )
    (DATA_DIR / "glint" / f"{region}_density_summary.json").write_text(
        pd.Series(meta).to_json(indent=2)
    )
    print(f"\n-> {DATA_DIR / 'glint' / f'{region}_density_summary.csv'}")


if __name__ == "__main__":
    app()
