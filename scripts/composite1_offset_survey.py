"""Per-cell composite_0 minus composite_1 DN (median and dark tail), by composite_1 build batch.

Found 2026-10-22: the 122 cells whose composite_1 was built 2026-07-05 sit on composite_0's DN
scale; the ~4,345 built from 2026-07-15 on read ~800 DN darker, with a wide spread. A flat
`transfer_calibration.PRE_BASELINE_DN_OFFSET` is therefore wrong for the early batch.

    pixi run python scripts/composite1_offset_survey.py /home/tobi/earthpv_data/roofclf_untapped/c1_offset_survey.csv
"""
import os
import sys
import datetime as dt
import numpy as np
import pandas as pd
import rasterio
root = "/home/tobi/earthpv_composites/pakistan/composites"
cells = sorted(os.listdir(root))
rng = np.random.default_rng(0)
rows = []
early = [c for c in cells if os.path.exists(f"{root}/{c}/composite_1.tif") and
         dt.date.fromtimestamp(os.path.getmtime(f"{root}/{c}/composite_1.tif")) <= dt.date(2026, 7, 5)]
late = [c for c in cells if os.path.exists(f"{root}/{c}/composite_1.tif") and c not in set(early)]
pick = list(rng.choice(early, 40, replace=False)) + list(rng.choice(late, 80, replace=False))
for c in pick:
    with rasterio.open(f"{root}/{c}/composite_0.tif") as a, rasterio.open(f"{root}/{c}/composite_1.tif") as b:
        x = a.read([1, 3, 7, 9]).astype("float32")
        y = b.read([1, 3, 7, 9]).astype("float32")
    ok = ~(x == 0).all(0) & ~(y == 0).all(0)
    if ok.sum() < 1000:
        continue
    d = [float(np.median(x[i][ok]) - np.median(y[i][ok])) for i in range(4)]
    p05 = [float(np.percentile(x[i][ok], 0.5) - np.percentile(y[i][ok], 0.5)) for i in range(4)]
    rows.append({"cell": c, "built": dt.date.fromtimestamp(os.path.getmtime(f"{root}/{c}/composite_1.tif")).isoformat(),
                 "batch": "early" if c in set(early) else "late",
                 "d_b02": d[0], "d_b04": d[1], "d_b08": d[2], "d_b11": d[3], "dark_b02": p05[0]})
df = pd.DataFrame(rows)
df.to_csv(sys.argv[1], index=False)
print(len(early), "early cells,", len(late), "late cells")
print(df.groupby("batch")[["d_b02", "d_b04", "d_b08", "d_b11", "dark_b02"]].describe(percentiles=[.1, .5, .9]).T.round(0).to_string())
