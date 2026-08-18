"""Build and pull the VERIFIED-negative control sample for the glint PSF/matched-filter
study (`scripts/glint_psf_photometry.py` step 3).

Why this sample and not the existing one: `docs/issues/glint-spike-rate-density-estimator.md`
measured the instrument's false-spike floor at 8.7-20.3% on Lahore controls, which is
equal to or above its own true-detection rate below 500 m2 -- the reason the spike-rate
density inversion is undefined exactly where it matters. But those controls were only
*model*-negative (the segmentation model did not flag them), so real unmapped PV among
them inflates the measured false rate by an unknown amount, and that doc's own next step
is to re-measure against verified negatives.

Those now exist. All 27 calibration quadrats are Rule-1 complete (every visible panel
mapped), so a quadrat building with `has_pv == 0` in `data/roofclf/buildings.geoparquet`
is a building a human looked at and found no panel on. That is the strongest negative
this project can produce.

Two sampling choices that matter:

- **Size-stratified to the positives' polygon-area distribution.** The glint statistic's
  window size, pixel count and detection probability all scale with the read polygon's
  area, so an unmatched control set measures size, not PV. Positives are read on their PV
  polygon and negatives on their roof footprint; those are different quantities on the
  same building, and matching is on the polygon actually read.
- **Isolated from mapped PV by `--min-sep-m`.** The annulus and the read window both
  extend past the footprint, so a PV-free roof sharing a wall with a panelled one can
  catch a real neighbouring glint and be scored as a false positive. That would measure
  the wrong thing. Separation is to the nearest *mapped-PV* building in the same quadrat.

Rule-1 is epoch-relative (it certifies completeness against the mapping imagery's own
capture date, not the Sentinel-2 composite's), so a control carrying an installation built
after its quadrat was mapped still counts as a false spike here. That biases the measured
false rate UP, which makes a pass trustworthy and a marginal fail inconclusive.

Usage:
  .pixi/envs/default/bin/python scripts/glint_psf_negatives.py sample
  .pixi/envs/default/bin/python scripts/glint_psf_negatives.py pull
"""

from __future__ import annotations

import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("glint_psf_negatives")
app = typer.Typer(pretty_exceptions_show_locals=False)

REGION = "psfneg"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
MAX_CLOUD = 80
BANDS = ("B03", "B08")

BUILDINGS = Path("data/roofclf/buildings.geoparquet")
TARGETS_FILE = DATA_DIR / "glint" / f"{REGION}_density_targets.parquet"
SERIES_DIR = DATA_DIR / "glint" / f"{REGION}_density"

# Quotas per polygon-area bucket. Weighted toward the sub-500 m2 regime because that is
# where the estimator is undefined; the two larger buckets are the positive control, a
# regime where the instrument is already known to work (validated 16-31% vs 8.7% false).
BUCKETS: tuple[tuple[str, float, float, int], ...] = (
    ("<100", 0.0, 100.0, 200),
    ("100-500", 100.0, 500.0, 200),
    ("500-1k", 500.0, 1000.0, 100),
    ("1k-5k", 1000.0, 5000.0, 100),
)


def _round_robin(pool: pd.DataFrame, quota: int, group_col: str, rng) -> pd.DataFrame:
    """Draw `quota` rows spread as evenly as availability allows across `group_col`.

    A plain uniform draw would hand most of a bucket to whichever quadrat happens to be
    biggest (Lahore and Sanghar alone hold a third of the sub-100 m2 pool), and a control
    set concentrated in one city measures that city's roofscape, not the country's.
    """
    order = {g: rng.permutation(idx.to_numpy()) for g, idx in pool.groupby(group_col).groups.items()}
    picked: list[int] = []
    cursor = {g: 0 for g in order}
    groups = sorted(order)
    while len(picked) < quota:
        progressed = False
        for g in groups:
            if len(picked) >= quota:
                break
            c = cursor[g]
            if c < len(order[g]):
                picked.append(int(order[g][c]))
                cursor[g] = c + 1
                progressed = True
        if not progressed:  # every quadrat exhausted before the quota was met
            break
    return pool.loc[picked]


@app.command()
def sample(
    n_per_bucket: str = typer.Option("", help="Override quotas, e.g. '200,200,100,100'"),
    min_sep_m: float = typer.Option(50.0, help="Minimum distance to the nearest mapped-PV "
                                    "building in the same quadrat"),
    seed: int = typer.Option(20260816, help="RNG seed"),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    rng = np.random.default_rng(seed)

    g = gpd.read_parquet(BUILDINGS)
    log.info("%d quadrat buildings, %d Rule-1 verified negatives",
             len(g), int((g.has_pv == 0).sum()))

    # Separation to the nearest mapped-PV building, computed per quadrat in a local UTM
    # projection so the distance is metric rather than degrees.
    keep_idx: list[int] = []
    for quad, sub in g.groupby("quadrat"):
        pos = sub[sub.has_pv == 1]
        neg = sub[sub.has_pv == 0]
        if neg.empty:
            continue
        if pos.empty:  # a confirmed-zero quadrat: every building is separated by definition
            keep_idx.extend(neg.index.tolist())
            continue
        utm = neg.estimate_utm_crs()
        neg_u = neg.to_crs(utm)
        pos_u = pos.to_crs(utm)
        d = neg_u.geometry.apply(lambda geom: pos_u.sindex.nearest(geom, return_all=False)[1][0])
        dist = np.array([neg_u.geometry.iloc[i].distance(pos_u.geometry.iloc[j])
                         for i, j in enumerate(d)])
        keep_idx.extend(neg_u.index[dist >= min_sep_m].tolist())
    pool = g.loc[keep_idx]
    log.info("after >=%.0f m separation from mapped PV: %d candidates", min_sep_m, len(pool))

    quotas = [int(x) for x in n_per_bucket.split(",")] if n_per_bucket else [b[3] for b in BUCKETS]
    picks = []
    for (name, lo, hi, _default), quota in zip(BUCKETS, quotas):
        sub = pool[(pool.roof_area_m2 >= lo) & (pool.roof_area_m2 < hi)]
        got = _round_robin(sub, quota, "quadrat", rng)
        got = got.assign(bucket=name)
        log.info("bucket %-8s quota %3d -> %3d drawn from %d candidates across %d quadrats",
                 name, quota, len(got), len(sub), got.quadrat.nunique())
        picks.append(got)

    out = pd.concat(picks).reset_index(drop=True)
    out = gpd.GeoDataFrame(
        {
            "pid": [f"neg_{i:04d}" for i in range(len(out))],
            "kind": "verified_negative",
            "quadrat": out.quadrat.to_numpy(),
            "bucket": out.bucket.to_numpy(),
            "area_m2": out.roof_area_m2.to_numpy(),
            "bf_confidence": out.bf_confidence.to_numpy(),
            "geometry": out.geometry.to_numpy(),
        },
        crs=out.crs,
    )
    out["lon"] = out.geometry.centroid.x
    out["lat"] = out.geometry.centroid.y
    TARGETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(TARGETS_FILE)
    log.info("wrote %s (%d targets, %d quadrats)", TARGETS_FILE, len(out), out.quadrat.nunique())


@app.command()
def pull(
    tile_deg: float = typer.Option(0.5, help="Spatial bin size (degrees) per fetch chunk"),
    max_workers: int = typer.Option(6, help="Threads per tile group"),
    shard: int = typer.Option(0, help="This process's shard index"),
    of: int = typer.Option(1, help="Total shards; groups are split round-robin between them"),
) -> None:
    """Chunked, resumable scene-series pull.

    `glint_density_pull.py` runs one `tile_scene_series_batch` over every target and only
    writes when the whole call returns, so a multi-hour run that dies at hour three keeps
    nothing. This drives the same function one tile group at a time and writes after each,
    which is what makes it restartable -- the relevant failure mode here, since the batch
    path has no cross-group checkpointing and a Planetary Computer outage mid-run is a
    documented event in this project.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    tgts = gpd.read_parquet(TARGETS_FILE)
    SERIES_DIR.mkdir(parents=True, exist_ok=True)

    keys = [glint._tile_key(lon, lat, tile_deg) for lon, lat in zip(tgts.lon, tgts.lat)]
    tgts = tgts.assign(_key=pd.Series(keys, index=tgts.index).astype(str))
    groups = list(tgts.groupby("_key"))
    # One process saturates about one core (GDAL decode holds the GIL), so the useful
    # parallelism is across processes, not more threads inside one. Groups are disjoint
    # and each writes only its own targets' files, so shards never contend.
    if of > 1:
        groups = [g for i, g in enumerate(groups) if i % of == shard]
    log.info("%d targets in %d tile groups (%.2f deg), shard %d/%d",
             len(tgts), len(groups), tile_deg, shard, of)

    for gi, (key, grp) in enumerate(groups, 1):
        todo = grp[~grp.pid.map(lambda p: (SERIES_DIR / f"{p}.parquet").exists())]
        if todo.empty:
            log.info("[%d/%d] %s: already done", gi, len(groups), key)
            continue
        log.info("[%d/%d] %s: pulling %d targets", gi, len(groups), key, len(todo))
        targets = pd.DataFrame({
            "pid": todo.pid.to_numpy(),
            "geometry": todo.geometry.to_numpy(),
            "lon": todo.lon.to_numpy(),
            "lat": todo.lat.to_numpy(),
        })
        try:
            series = glint.tile_scene_series_batch(
                targets, DATE_RANGE[0], DATE_RANGE[1], bands=BANDS, max_cloud=MAX_CLOUD,
                tile_deg=tile_deg, max_workers=max_workers,
            )
        except Exception as e:  # noqa: BLE001 -- one bad group must not kill the run
            log.warning("[%d/%d] %s FAILED: %s", gi, len(groups), key, e)
            continue
        n_ok = 0
        for pid in todo.pid:
            df = series.get(pid, pd.DataFrame())
            df.to_parquet(SERIES_DIR / f"{pid}.parquet")
            n_ok += int(not df.empty)
        log.info("[%d/%d] %s: wrote %d/%d non-empty", gi, len(groups), key, n_ok, len(todo))

    log.info("PSF_NEG_PULL_DONE")


if __name__ == "__main__":
    app()
