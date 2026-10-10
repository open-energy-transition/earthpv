"""Random-sample scan of composites for the two compose defects fixed 2026-10-10.

Per cell (decimated 4x): all_empty = share of pixels zero in every band; n_dead_bands =
bands at least 99% zero; edge_frac = share of the all-empty pixels lying in raster rows or
columns that are at least 98% empty. Compose grids each cell in its centre's UTM zone,
where MGRS tile edges are rows or columns, so a high edge_frac marks a scene-footprint gap
(the ranking defect) rather than scattered SCL masking of cloud, snow or salt flats. See
docs/open-questions.md, item 22.

    python scripts/scan_composite_defects.py <composites dir> <out.csv> <n cells> <workers>

Run it in a memory-capped unit (systemd-run -p MemoryHigh=1G): it streams gigabytes of
composites and otherwise evicts the page cache a concurrent density run depends on
(measured 2026-10-10: density slowed from 6.2 to 10.3 s per cell).
"""
import sys, glob, os, random
from concurrent.futures import ProcessPoolExecutor
import numpy as np, rasterio

def one(p):
    cell = os.path.basename(os.path.dirname(p))
    try:
        with rasterio.open(p) as s:
            a = s.read()[:, ::4, ::4]
        z = a == 0
        per = z.reshape(z.shape[0], -1).mean(axis=1)
        za = z.all(axis=0)
        n = int(za.sum())
        if n:
            line = (za.mean(axis=1) >= 0.98)[:, None] | (za.mean(axis=0) >= 0.98)[None, :]
            edge = float((za & line).sum() / n)
        else:
            edge = 0.0
        return cell, float(za.mean()), int((per >= 0.99).sum()), edge
    except Exception:
        return cell, -1.0, -1, -1.0

if __name__ == "__main__":
    root, out, n, workers = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    paths = sorted(glob.glob(os.path.join(root, "*", "composite_0.tif")))
    random.Random(20261010).shuffle(paths)
    paths = paths[:n]
    with ProcessPoolExecutor(workers) as ex, open(out, "w", buffering=1) as f:
        f.write("cell,all_empty,n_dead_bands,edge_frac\n")
        for c, ae, nd, ed in ex.map(one, paths, chunksize=16):
            f.write(f"{c},{ae:.4f},{nd},{ed:.4f}\n")
    print("done", len(paths))
