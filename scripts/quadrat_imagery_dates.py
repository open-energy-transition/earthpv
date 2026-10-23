"""Esri World Imagery capture date (zoom 18) over each calibration quadrat, on a 3x3 grid.

The dates TODAY's Esri layer serves, an upper bound on the imagery a mapper saw;
open question 4, "Stale reference imagery".

    pixi run python scripts/quadrat_imagery_dates.py /home/tobi/earthpv_data/roofclf_untapped/quadrat_imagery_dates.csv
"""
import sys
from pathlib import Path
sys.path.insert(0, "scripts")
import pandas as pd
from propose_calibration_candidates import esri_capture
from earthpv.roofclf import discover_quadrats, load_quadrat, quadrat_label

rows = []
for stem in sorted(discover_quadrats(Path("data/labels"))):
    b, _ = load_quadrat(stem)
    w, s, e, n = b.bounds
    for i, fx in enumerate((0.15, 0.5, 0.85)):
        for j, fy in enumerate((0.15, 0.5, 0.85)):
            x, y = w + fx * (e - w), s + fy * (n - s)
            c = esri_capture(x, y)
            rows.append({"quadrat": quadrat_label(stem), "lon": x, "lat": y,
                         "date": c["date"].isoformat() if c else None,
                         "res_m": c["res_m"] if c else None, "name": c["name"] if c else None})
    print(stem, [r["date"] for r in rows[-9:]], flush=True)
pd.DataFrame(rows).to_csv(sys.argv[1], index=False)
