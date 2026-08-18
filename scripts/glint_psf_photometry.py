"""Solar-glint PSF photometry: fit Sentinel-2's effective point-spread function from
glinting PV installations, then use it as a matched filter to separate true glints from
false spikes.

This supersedes `scripts/glint_psf_prototype.py`, which established the idea and produced
`data/glint/psf_prototype/glint_psf_comparison.png`. That prototype's kernel came out at
roughly 2 px FWHM against a theoretical 1.34 px, visibly non-radial, with a radial profile
that never reached zero -- i.e. not a PSF. Three causes, all addressed here:

1. **Sub-pixel phase was averaged away.** It cropped stamps at `int(round(row))` even
   though it had computed the true sub-pixel centroid. Stacking stamps drawn from
   uniformly-distributed sub-pixel positions convolves the result with a 1 px box, which
   on its own roughly accounts for the 1.34 -> 2 px broadening. Sentinel-2's 10 m PSF is
   *undersampled* (FWHM ~1.34 px, below the 2 px Nyquist floor), so the sampled kernel
   genuinely changes shape with sub-pixel position and no single integer-aligned stack is
   well-defined. Fixed by never resampling the data: the forward model is built on each
   scene's own pixel grid at the target's true position, so phase is carried exactly.
2. **Source extent was confounded with the PSF.** A 100-500 m2 array spans 1-5 px, so its
   stamp is PSF-convolved-with-a-finite-source, not a PSF. Fixed by modelling the known
   polygon explicitly and fitting sigma jointly across targets spanning <100 m2 to
   >50k m2 -- the small targets constrain sigma, the large ones constrain extent, and
   only jointly are the two separable.
3. **Peak normalisation biased the profile.** Dividing each stamp by its own
   noise-selected maximum inflates the wings and flattens the core. Fixed by fitting
   amplitude as a free linear parameter per scene instead of normalising.

The prototype also never produced its headline result: `matched_filter_test.csv` has one
row, because SAS-token expiry killed the reads. Two further bugs contributed and are fixed
here -- the test arm lacked the shape guard the calibration arm had, and it drew its noise
floor from the *same* clear scenes it built the background from, so every noise sample was
correlated with its own background and the null spread came out too small, inflating
significance.

## What this measures

Stage 1 (existing, cheap, already run nationally): the aggregate spike rule in
`glint.annotate_spikes` flags candidate scenes from p98-vs-annulus statistics alone.
Stage 2 (new, this script): for each flagged scene, fit the target's own PSF-convolved
footprint model to the background-subtracted pixel window and report an amplitude and its
significance against a null measured on held-out clear scenes.

The question is whether stage 2 re-ranks stage 1's candidates well enough to separate true
glints from false spikes. That matters because
`docs/issues/glint-spike-rate-density-estimator.md` is blocked on exactly this: below
500 m2 the false-spike rate (8.7-20.3%) equals or exceeds the true detection rate
(8.8-16.2%), so its adoption-rate inversion is undefined in the size regime it exists to
serve.

Usage:
  .pixi/envs/default/bin/python scripts/glint_psf_photometry.py stamps --set positives
  .pixi/envs/default/bin/python scripts/glint_psf_photometry.py psf
  .pixi/envs/default/bin/python scripts/glint_psf_photometry.py stamps --set negatives
  .pixi/envs/default/bin/python scripts/glint_psf_photometry.py score
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import typer
from shapely import wkt as shapely_wkt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("glint_psf_photometry")
app = typer.Typer(pretty_exceptions_show_locals=False)

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
MAX_CLOUD = 80
BAND = "B03"  # 10 m native, no resampling -- matches the prototype and the alignment check
OUT_DIR = DATA_DIR / "glint" / "psf"
STAMP_ROOT = OUT_DIR / "stamps"
RESULTS = Path("results/glint_psf")

N_BACKGROUND = 8   # clear scenes medianed into the per-target background
N_NOISE = 12       # further clear scenes, DISJOINT from the background, forming the null
MIN_CLEAR = 6      # a target with fewer usable clear scenes is dropped
TIME_TOL = timedelta(minutes=20)  # item.datetime vs the series' tile sensing time

SUPERSAMPLE = 10   # fine-grid factor for the forward model: 1 m cells inside a 10 m pixel

# Sentinel-2 10 m-band MTF at Nyquist, ESA's stated design range (SentiWiki). A Gaussian
# PSF has MTF(f) = exp(-2 (pi sigma f)^2), so at f = 0.5 cyc/px:
#   sigma = sqrt(-ln m) * sqrt(2) / pi
MTF_NYQUIST_RANGE = (0.15, 0.30)


def mtf_to_sigma(mtf_at_nyquist: float) -> float:
    return float(np.sqrt(2.0) / np.pi * np.sqrt(-np.log(mtf_at_nyquist)))


SETS = {
    "positives": dict(
        targets=DATA_DIR / "glint" / "country2000_targets.parquet",
        series=DATA_DIR / "glint" / "country2000",
        summary=DATA_DIR / "glint" / "country2000_summary.csv",
        tile_deg=1.0,
    ),
    "negatives": dict(
        targets=DATA_DIR / "glint" / "psfneg_density_targets.parquet",
        series=DATA_DIR / "glint" / "psfneg_density",
        summary=None,
        tile_deg=0.5,
    ),
}


# --------------------------------------------------------------------------------------
# Stamp fetching
# --------------------------------------------------------------------------------------

def _plan_target(series: pd.DataFrame, seed: int) -> dict | None:
    """Which scenes to read for one target, and in what role.

    Background and noise scenes are drawn DISJOINTLY from the clear pool. Sharing them
    (the prototype's bug) makes each noise sample one of the ~8 values its own background
    median was built from, so the null spread is biased low and every significance
    computed against it is inflated.
    """
    d = glint.annotate_spikes(series)
    if d.empty or "spike" not in d.columns:
        return None
    spikes = d[d.spike]
    clear = d[d.clear & ~d.spike]
    if len(clear) < MIN_CLEAR or spikes.empty:
        return None
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(clear))
    bg = clear.iloc[order[:N_BACKGROUND]]
    noise = clear.iloc[order[N_BACKGROUND:N_BACKGROUND + N_NOISE]]
    if len(bg) < 4 or len(noise) < 4:
        return None
    return {"spike": spikes, "background": bg, "noise": noise}


def _wanted_rows(pid: str, plan: dict) -> list[dict]:
    rows = []
    for role, sub in plan.items():
        for r in sub.itertuples():
            rows.append(dict(
                pid=pid, role=role, time=pd.Timestamp(r.time).tz_convert("UTC"),
                a=float(getattr(r, f"a_{BAND}")), r=float(getattr(r, f"r_{BAND}")),
            ))
    return rows


def _assemble(pid: str, target_row, wanted: pd.DataFrame,
              reads: dict[tuple[str, pd.Timestamp], tuple]) -> dict | None:
    """Turn one target's raw window reads into a background-subtracted stamp stack.

    Every scene is required to share the modal (crs, transform, shape). A window's
    position depends only on the target footprint and the scene's own grid, so scenes from
    one MGRS tile agree exactly; a neighbouring tile in a different UTM zone does not, and
    silently stacking across the two would compare different ground pixels.
    """
    got = [(k, v) for k, v in reads.items() if k[0] == pid and v is not None]
    if not got:
        return None
    sigs = {}
    for (_pid, t), (arr, wt, crs) in got:
        sigs.setdefault((str(crs), tuple(np.round(np.array(wt).ravel()[:6], 3)), arr.shape), []).append(t)
    modal = max(sigs, key=lambda k: len(sigs[k]))
    keep_times = set(sigs[modal])
    keep = {k[1]: v for k, v in got if k[1] in keep_times}

    meta = wanted.set_index("time")
    bg_times = [t for t in keep if meta.loc[t, "role"] == "background"]
    if len(bg_times) < 4:
        return None
    background = np.nanmedian(np.stack([keep[t][0] for t in bg_times]), axis=0)

    _arr0, wt, crs = keep[next(iter(keep))]
    geom_native = gpd.GeoSeries([target_row.geometry], crs="EPSG:4326").to_crs(crs).iloc[0]
    col, row = ~wt * (geom_native.centroid.x, geom_native.centroid.y)

    stamps, roles, times, a_vals, r_vals = [], [], [], [], []
    for t, (arr, _wt, _crs) in sorted(keep.items()):
        role = meta.loc[t, "role"]
        if role == "background":
            continue
        excess = glint._refl(arr) - glint._refl(background)
        if not np.isfinite(excess).any():
            continue
        stamps.append(excess.astype("float32"))
        roles.append(role)
        times.append(str(t))
        a_vals.append(float(meta.loc[t, "a"]))
        r_vals.append(float(meta.loc[t, "r"]))
    if not stamps or "spike" not in roles:
        return None

    return dict(
        stamps=np.stack(stamps), roles=np.array(roles), times=np.array(times),
        a=np.array(a_vals), r=np.array(r_vals),
        background=glint._refl(background).astype("float32"),
        row0=float(row), col0=float(col),
        transform=np.array(wt).ravel()[:6].astype(float),
        crs_wkt=str(crs.to_wkt() if hasattr(crs, "to_wkt") else crs),
        geom_native_wkt=geom_native.wkt,
        area_m2=float(getattr(target_row, "area_m2", np.nan)),
        pid=pid,
    )


@app.command()
def stamps(
    set_name: str = typer.Option("positives", "--set", help="positives | negatives"),
    tile_deg: float = typer.Option(0.0, help="Override the set's tile-group size"),
    max_workers: int = typer.Option(6, help="Threads per tile group"),
    limit: int = typer.Option(0, help="Cap the target count (smoke test)"),
    seed: int = typer.Option(11, help="Seed for the background/noise split"),
    shard: int = typer.Option(0, help="This process's shard index"),
    of: int = typer.Option(1, help="Total shards; tile groups split round-robin"),
) -> None:
    """Fetch and cache background-subtracted pixel windows for every scene of interest."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    warnings.filterwarnings("ignore", message=".*Geometry is in a geographic CRS.*")
    cfg = SETS[set_name]
    out_dir = STAMP_ROOT / set_name
    out_dir.mkdir(parents=True, exist_ok=True)

    tgts = gpd.read_parquet(cfg["targets"])
    if "lon" not in tgts.columns:
        tgts["lon"] = tgts.geometry.centroid.x
        tgts["lat"] = tgts.geometry.centroid.y
    series_dir = Path(cfg["series"])

    # Plan first, offline, from the cached per-scene series. Targets with no spike at all
    # cost reads and can contribute to neither the PSF fit nor the matched-filter test.
    plans, wanted_rows = {}, []
    for r in tgts.itertuples():
        path = series_dir / f"{r.pid}.parquet"
        if not path.exists():
            continue
        try:
            s = pd.read_parquet(path)
        except Exception:  # noqa: BLE001 -- a truncated cache file must not kill planning
            continue
        if s.empty:
            continue
        plan = _plan_target(s, seed=abs(hash(r.pid)) % (2**31))
        if plan is None:
            continue
        plans[r.pid] = plan
        wanted_rows.extend(_wanted_rows(r.pid, plan))
    if limit:
        keep = sorted(plans)[:limit]
        plans = {k: plans[k] for k in keep}
        wanted_rows = [w for w in wanted_rows if w["pid"] in keep]
    wanted = pd.DataFrame(wanted_rows)
    log.info("%s: %d targets with >=1 spike and a usable clear pool, %d scene-reads planned",
             set_name, len(plans), len(wanted))
    if wanted.empty:
        return

    todo = [p for p in plans if not (out_dir / f"{p}.npz").exists()]
    log.info("%d targets still to fetch", len(todo))
    if not todo:
        return
    wanted = wanted[wanted.pid.isin(todo)]
    tgts = tgts[tgts.pid.isin(todo)].reset_index(drop=True)

    deg = tile_deg or cfg["tile_deg"]
    keys = [glint._tile_key(lon, lat, deg) for lon, lat in zip(tgts.lon, tgts.lat)]
    tgts = tgts.assign(_key=[str(k) for k in keys], _kx=[k[0] for k in keys], _ky=[k[1] for k in keys])
    groups = list(tgts.groupby("_key"))
    # Across processes, not threads: GDAL decode holds the GIL, so one process saturates
    # roughly one core no matter how many workers it is given. Groups are disjoint.
    if of > 1:
        groups = [g for i, g in enumerate(groups) if i % of == shard]
    log.info("%d tile groups (%.2f deg), shard %d/%d", len(groups), deg, shard, of)

    for gi, (key, grp) in enumerate(groups, 1):
        gx, gy = int(grp._kx.iloc[0]), int(grp._ky.iloc[0])
        bbox = (gx * deg, gy * deg, (gx + 1) * deg, (gy + 1) * deg)
        provider = "planetary-computer"
        try:
            items = glint._search_items_bbox(provider, bbox, *DATE_RANGE, MAX_CLOUD)
        except Exception as e:  # noqa: BLE001
            log.warning("group %s: PC search failed (%s)", key, e)
            items = []
        if not items:
            provider = "earth-search"
            try:
                items = glint._search_items_bbox(provider, bbox, *DATE_RANGE, MAX_CLOUD)
            except Exception as e:  # noqa: BLE001
                log.warning("group %s: Earth Search failed too (%s), skipping", key, e)
                continue
        if not items:
            log.info("[%d/%d] %s: no scenes", gi, len(groups), key)
            continue

        gw = wanted[wanted.pid.isin(set(grp.pid))]
        by_pid = {r.pid: r for r in grp.itertuples()}
        # Which (pid, wanted-time) each item can serve. The series' `time` is the granule
        # sensing time and an item's is its STAC datetime; they differ by minutes at most,
        # far less than the ~5 day revisit, so a tolerance match is unambiguous.
        want_times = pd.DatetimeIndex(gw.time)
        want_pids = gw.pid.to_numpy()
        tol = pd.Timedelta(TIME_TOL)
        item_jobs: list[tuple[object, list[tuple[str, object, float, float]], list[pd.Timestamp]]] = []
        for item in items:
            it_dt = pd.Timestamp(item.datetime).tz_convert("UTC")
            m = (want_times - it_dt).to_series().abs().to_numpy() <= tol
            if not m.any():
                continue
            # One wanted time per pid at most: the revisit is ~5 days, the tolerance 20 min.
            seen: dict[str, pd.Timestamp] = {}
            for p, t in zip(want_pids[m], want_times[m]):
                seen.setdefault(p, t)
            pids = sorted(seen)
            tlist = [seen[p] for p in pids]
            tg = [(p, by_pid[p].geometry, by_pid[p].lon, by_pid[p].lat) for p in pids]
            item_jobs.append((item, tg, tlist))
        log.info("[%d/%d] %s: %d targets, %d items to read (%s)",
                 gi, len(groups), key, len(grp), len(item_jobs), provider)

        reads: dict[tuple[str, pd.Timestamp], tuple] = {}
        lock = threading.Lock()

        def _do(job):
            item, tg, tlist = job
            res = glint._read_targets_from_item(item, BAND, tg, provider, return_array=True)
            out = []
            for (pid, _g, _lo, _la), t in zip(tg, tlist):
                v = res.get(pid)
                if v is None or v[0] is None:
                    continue
                out.append(((pid, t), v))
            return out

        with ThreadPoolExecutor(max_workers) as ex:
            futs = [ex.submit(_do, j) for j in item_jobs]
            for f in as_completed(futs):
                try:
                    got = f.result()
                except Exception as e:  # noqa: BLE001 -- one bad item must not kill the group
                    log.debug("item read failed: %s", e)
                    continue
                with lock:
                    for k, v in got:
                        prev = reads.get(k)
                        # Tile-overlap seams can return two items for one date covering
                        # only partly-overlapping footprints. Keep whichever actually has
                        # data here, matching the series builder's own npx tie-break.
                        if prev is None or np.isfinite(v[0]).sum() > np.isfinite(prev[0]).sum():
                            reads[k] = v

        n_written = 0
        for pid in grp.pid:
            rec = _assemble(pid, by_pid[pid], gw[gw.pid == pid], reads)
            if rec is None:
                continue
            np.savez_compressed(out_dir / f"{pid}.npz", **rec)
            n_written += 1
        log.info("[%d/%d] %s: wrote %d stamp files", gi, len(groups), key, n_written)

    log.info("PSF_STAMPS_DONE set=%s", set_name)


# --------------------------------------------------------------------------------------
# Forward model
# --------------------------------------------------------------------------------------

def _load_stamp(path: Path) -> dict:
    z = np.load(path, allow_pickle=False)
    return {k: z[k] for k in z.files}


def footprint_model(rec: dict, sigma_px: float, supersample: int = SUPERSAMPLE,
                    point: bool = False) -> np.ndarray:
    """The target's own footprint, blurred by a Gaussian PSF of `sigma_px`, on the scene's
    own pixel grid at the target's true sub-pixel position.

    Built by rasterising the polygon on a `supersample`x finer grid, convolving there, and
    block-averaging back down. Nothing is ever resampled or re-centred, so the sub-pixel
    phase that the prototype averaged away is carried exactly -- which is what makes a
    kernel definable at all for a PSF this far below Nyquist.
    """
    from affine import Affine
    from rasterio.features import rasterize
    from scipy.ndimage import gaussian_filter

    h, w = rec["background"].shape
    wt = Affine(*rec["transform"])
    fine = wt * Affine.scale(1.0 / supersample)
    geom = shapely_wkt.loads(str(rec["geom_native_wkt"]))
    if point:
        # A specular glint comes from whichever patch of the array satisfies the mirror
        # condition on that date, not from the whole array uniformly -- which is what the
        # measured rise of fitted sigma with installation area says directly. Modelling
        # the source as a point is the physically honest alternative, and it is what
        # stellar PSF photometry actually does.
        geom = geom.centroid.buffer(1.0)
    mask = rasterize([(geom, 1.0)], out_shape=(h * supersample, w * supersample),
                     transform=fine, dtype="float32", all_touched=False)
    if mask.sum() == 0:  # a footprint far below one fine cell still has to be representable
        mask = rasterize([(geom.centroid.buffer(supersample * 0.5), 1.0)],
                         out_shape=(h * supersample, w * supersample),
                         transform=fine, dtype="float32", all_touched=True)
    blurred = gaussian_filter(mask, sigma=sigma_px * supersample, mode="nearest")
    k = blurred.reshape(h, supersample, w, supersample).mean(axis=(1, 3))
    s = k.sum()
    return k / s if s > 0 else k


def fit_box(rec: dict, pad_px: float = 4.0, lo: int = 6, hi: int = 14) -> tuple[slice, slice]:
    """A local window around the target, sized from its own footprint.

    Fitting over the whole 32-60 px read window would weight hundreds of pixels of
    unrelated neighbourhood against a source occupying a handful, and would let a broad
    kernel earn score from structure nowhere near the target.
    """
    geom = shapely_wkt.loads(str(rec["geom_native_wkt"]))
    minx, miny, maxx, maxy = geom.bounds
    extent_px = max(maxx - minx, maxy - miny) / 10.0
    r = int(np.clip(extent_px / 2 + pad_px, lo, hi))
    h, w = rec["background"].shape
    row0, col0 = float(rec["row0"]), float(rec["col0"])
    r0 = int(np.clip(round(row0) - r, 0, h))
    r1 = int(np.clip(round(row0) + r + 1, 0, h))
    c0 = int(np.clip(round(col0) - r, 0, w))
    c1 = int(np.clip(round(col0) + r + 1, 0, w))
    return slice(r0, r1), slice(c0, c1)


def _crop_kernel(kernel: np.ndarray, box: tuple[slice, slice]) -> np.ndarray:
    """Crop to the fit box and renormalise to unit sum, so a fitted amplitude keeps the
    same meaning (total excess reflectance-area of the source) across targets whose boxes
    differ in size."""
    k = kernel[box]
    s = k.sum()
    return k / s if s > 0 else k


def fit_amplitude(excess: np.ndarray, kernel: np.ndarray) -> tuple[float, float]:
    """Least-squares amplitude of `kernel` in `excess`, plus the residual RMS.

    Amplitude is free rather than normalised away, so the fit is unbiased in the way a
    peak-normalised stack is not.

    A smooth plane (constant + x + y) is fitted alongside and discarded. The background is
    a median over clear dates, so a spike scene differs from it by an illumination and
    atmospheric term that varies gently across the window as well as by the glint. Without
    the plane, that smooth component is available to any kernel, and a *broader* kernel
    absorbs more of it -- which would bias the fitted PSF width up, the exact error being
    corrected here.
    """
    m = np.isfinite(excess) & np.isfinite(kernel)
    if m.sum() < 12:
        return np.nan, np.nan
    h, w = excess.shape
    yy, xx = np.mgrid[0:h, 0:w]
    A = np.column_stack([
        kernel[m].astype(float),
        np.ones(int(m.sum())),
        (xx[m] - xx[m].mean()) / max(w, 1),
        (yy[m] - yy[m].mean()) / max(h, 1),
    ])
    y = excess[m].astype(float)
    if not np.isfinite(A).all():
        return np.nan, np.nan
    try:
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    except np.linalg.LinAlgError:
        return np.nan, np.nan
    resid = y - A @ coef
    return float(coef[0]), float(np.sqrt(np.mean(resid**2)))


def _explained(excess: np.ndarray, kernel: np.ndarray) -> tuple[float, float]:
    """(variance explained by the kernel term, total variance after the nuisance plane).

    Scoring against the plane-only model rather than the raw window is what makes the
    sigma search a test of *shape*: both models see the same smooth term, so the only
    thing separating them is how well the kernel matches the source.
    """
    m = np.isfinite(excess) & np.isfinite(kernel)
    if m.sum() < 12:
        return np.nan, np.nan
    h, w = excess.shape
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.column_stack([
        np.ones(int(m.sum())),
        (xx[m] - xx[m].mean()) / max(w, 1),
        (yy[m] - yy[m].mean()) / max(h, 1),
    ])
    y = excess[m].astype(float)
    try:
        c0, *_ = np.linalg.lstsq(base, y, rcond=None)
        r_base = y - base @ c0
        full = np.column_stack([kernel[m].astype(float), base])
        c1, *_ = np.linalg.lstsq(full, y, rcond=None)
        r_full = y - full @ c1
    except np.linalg.LinAlgError:
        return np.nan, np.nan
    ss_base = float(r_base @ r_base)
    ss_full = float(r_full @ r_full)
    return ss_base - ss_full, ss_base


# --------------------------------------------------------------------------------------
# Step 2: fit the PSF
# --------------------------------------------------------------------------------------

@app.command()
def psf(
    set_name: str = typer.Option("positives", "--set"),
    max_area: float = typer.Option(5000.0, help="Cap on target area for the global fit "
                                   "(above this, only part of an array glints at a time)"),
    sigma_grid: str = typer.Option("0.15,2.20,0.05", help="lo,hi,step in pixels"),
) -> None:
    """Fit the sensor PSF width jointly across targets spanning three orders of magnitude
    in area, and test whether one sigma explains every size bin."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    RESULTS.mkdir(parents=True, exist_ok=True)
    files = sorted((STAMP_ROOT / set_name).glob("*.npz"))
    log.info("%d cached targets", len(files))
    if not files:
        raise SystemExit("no stamps -- run `stamps --set positives` first")

    lo, hi, step = (float(x) for x in sigma_grid.split(","))
    sigmas = np.arange(lo, hi + 1e-9, step)

    recs = []
    for p in files:
        rec = _load_stamp(p)
        spike = rec["roles"] == "spike"
        if not spike.any() or not np.isfinite(rec["area_m2"]):
            continue
        recs.append(rec)
    log.info("%d targets with spikes and a known area", len(recs))

    # For each target and each candidate sigma: the best amplitude fit summed over its
    # spike scenes, scored as variance explained relative to a no-source model. Sigma is
    # then the value maximising the total across targets.
    rows = []
    for rec in recs:
        area = float(rec["area_m2"])
        spike_idx = np.where(rec["roles"] == "spike")[0]
        box = fit_box(rec)
        per_sigma = np.full(len(sigmas), np.nan)
        for si, s in enumerate(sigmas):
            kern = _crop_kernel(footprint_model(rec, s), box)
            tot, base = 0.0, 0.0
            for i in spike_idx:
                expl, tot_var = _explained(rec["stamps"][i][box], kern)
                if not np.isfinite(expl) or not np.isfinite(tot_var):
                    continue
                tot += expl
                base += tot_var
            per_sigma[si] = tot / base if base > 0 else np.nan
        if not np.isfinite(per_sigma).any():
            continue
        best = int(np.nanargmax(per_sigma))
        rows.append(dict(pid=str(rec["pid"]), area_m2=area, n_spike=len(spike_idx),
                         sigma_best=float(sigmas[best]), r2_best=float(per_sigma[best]),
                         profile=per_sigma))

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no usable targets")
    df["bucket"] = pd.cut(df.area_m2, [0, 100, 500, 1000, 5000, 50000, 1e12],
                          labels=["<100", "100-500", "500-1k", "1k-5k", "5k-50k", ">50k"])

    fit_set = df[df.area_m2 <= max_area]
    stack = np.vstack(fit_set.profile.to_numpy())
    total = np.nanmean(stack, axis=0)
    sigma_hat = float(sigmas[int(np.nanargmax(total))])

    # Bootstrap over targets: the spread that matters is between installations, not
    # between scenes of one installation.
    rng = np.random.default_rng(7)
    boots = []
    for _ in range(400):
        idx = rng.integers(0, len(stack), len(stack))
        boots.append(sigmas[int(np.nanargmax(np.nanmean(stack[idx], axis=0)))])
    ci = (float(np.percentile(boots, 5)), float(np.percentile(boots, 95)))

    th_lo, th_hi = mtf_to_sigma(MTF_NYQUIST_RANGE[1]), mtf_to_sigma(MTF_NYQUIST_RANGE[0])
    log.info("global sigma = %.3f px (90%% CI %.3f-%.3f), FWHM %.2f px",
             sigma_hat, *ci, sigma_hat * 2.3548)
    log.info("theory from MTF@Nyquist %.2f-%.2f: sigma %.3f-%.3f px (FWHM %.2f-%.2f px)",
             *MTF_NYQUIST_RANGE, th_lo, th_hi, th_lo * 2.3548, th_hi * 2.3548)

    per_bucket = []
    for b, sub in df.groupby("bucket", observed=True):
        if sub.empty:
            continue
        st = np.vstack(sub.profile.to_numpy())
        s_b = float(sigmas[int(np.nanargmax(np.nanmean(st, axis=0)))])
        per_bucket.append(dict(bucket=str(b), n=len(sub), sigma=s_b,
                               median_area_m2=float(sub.area_m2.median()),
                               median_r2=float(sub.r2_best.median())))
    pb = pd.DataFrame(per_bucket)
    log.info("per-bucket sigma (a flat column means one PSF explains every size):\n%s",
             pb.to_string(index=False))

    df.drop(columns="profile").to_csv(RESULTS / "psf_per_target.csv", index=False)
    pb.to_csv(RESULTS / "psf_by_bucket.csv", index=False)
    np.savez(RESULTS / "psf_profiles.npz", sigmas=sigmas, mean_profile=total,
             stack=stack, areas=fit_set.area_m2.to_numpy())
    (RESULTS / "psf_fit.json").write_text(json.dumps(dict(
        sigma_px=sigma_hat, sigma_ci90=list(ci), fwhm_px=sigma_hat * 2.3548,
        n_targets_fit=int(len(fit_set)), n_targets_total=int(len(df)),
        max_area_m2=max_area, band=BAND,
        theory_sigma_px=[th_lo, th_hi], mtf_nyquist_range=list(MTF_NYQUIST_RANGE),
    ), indent=2))
    log.info("wrote %s", RESULTS / "psf_fit.json")


# --------------------------------------------------------------------------------------
# Steps 1 and 3: matched filter vs the aperture statistic
# --------------------------------------------------------------------------------------

def _score_target(rec: dict, sigma_px: float, fit_shift: float = 0.0,
                  shift_step: float = 0.25, point: bool = False) -> dict | None:
    """Both statistics, each standardised by its OWN null on held-out clear scenes.

    `fit_shift > 0` lets the model slide within +-`fit_shift` px and keeps the best fit.
    Two things displace a glint from the polygon centroid: per-scene co-registration
    error, and the fact that the specular condition is met by whichever part of the array
    has the right tilt on that date, which moves with the sun. Both are real, so a
    position-free filter is the better matched filter -- provided the SAME freedom is
    granted to the null scenes, which it is here. Granting it only to the spikes would
    hand them an extra free parameter and manufacture separation out of nothing.
    """
    box = fit_box(rec, pad_px=6.0 if fit_shift else 4.0)
    kern = _crop_kernel(footprint_model(rec, sigma_px, point=point), box)
    if fit_shift:
        offs = np.arange(-fit_shift, fit_shift + 1e-9, shift_step)
        kerns = [_shifted_model(rec, sigma_px, dy, dx, box, point=point)
                 for dy in offs for dx in offs]
    else:
        kerns = [kern]
    roles = rec["roles"]
    amps, kinds = [], []
    for i in range(len(roles)):
        ex = rec["stamps"][i][box]
        best_amp, best_expl = np.nan, -np.inf
        for k in kerns:
            expl, _tot = _explained(ex, k)
            if np.isfinite(expl) and expl > best_expl:
                a, _rms = fit_amplitude(ex, k)
                best_expl, best_amp = expl, a
        amp = best_amp
        amps.append(amp)
        kinds.append(str(roles[i]))
    amps = np.array(amps, float)
    kinds = np.array(kinds)
    noise = amps[(kinds == "noise") & np.isfinite(amps)]
    spike = amps[(kinds == "spike") & np.isfinite(amps)]
    if len(noise) < 4 or len(spike) == 0:
        return None
    scale = float(np.std(noise, ddof=1))
    centre = float(np.median(noise))
    mf_z = (spike - centre) / scale if scale > 0 else np.full(len(spike), np.nan)

    # The current pipeline statistic, standardised the same way for a like-for-like test.
    ap = rec["a"] - rec["r"]
    ap_noise = ap[(kinds == "noise") & np.isfinite(ap)]
    ap_spike = ap[(kinds == "spike") & np.isfinite(ap)]
    ap_scale = float(np.std(ap_noise, ddof=1)) if len(ap_noise) >= 4 else np.nan
    ap_centre = float(np.median(ap_noise)) if len(ap_noise) >= 4 else np.nan
    ap_z = (ap_spike - ap_centre) / ap_scale if ap_scale and ap_scale > 0 else np.full(len(ap_spike), np.nan)

    per_scene = pd.DataFrame(dict(
        pid=str(rec["pid"]), area_m2=float(rec["area_m2"]),
        mf_amp=spike, mf_z=mf_z,
        ap_stat=ap_spike[: len(spike)] if len(ap_spike) >= len(spike) else np.full(len(spike), np.nan),
        ap_z=ap_z[: len(spike)] if len(ap_z) >= len(spike) else np.full(len(spike), np.nan),
    ))
    summary = dict(
        pid=str(rec["pid"]), area_m2=float(rec["area_m2"]),
        n_spike=int(len(spike)), n_noise=int(len(noise)),
        mf_amp_max=float(np.nanmax(spike)), mf_z_max=float(np.nanmax(mf_z)),
        mf_z_median=float(np.nanmedian(mf_z)),
        ap_z_max=float(np.nanmax(ap_z)) if len(ap_z) else np.nan,
        ap_stat_max=float(np.nanmax(ap_spike)),
        null_scale=scale,
    )
    return summary, per_scene


def _roc_auc(pos: np.ndarray, neg: np.ndarray) -> float:
    pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    allv = np.concatenate([pos, neg])
    ranks = pd.Series(allv).rank().to_numpy()
    r_pos = ranks[: len(pos)].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _false_rate_at(pos: np.ndarray, neg: np.ndarray, tpr: float) -> tuple[float, float]:
    """(threshold, false-positive rate) at the threshold giving `tpr` on positives."""
    pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan, np.nan
    thr = float(np.quantile(pos, 1 - tpr))
    return thr, float((neg >= thr).mean())


@app.command()
def score(
    sigma_px: float = typer.Option(0.0, help="PSF sigma; 0 reads results/glint_psf/psf_fit.json"),
    max_area: float = typer.Option(1000.0, help="Size ceiling for the headline comparison"),
    fit_shift: float = typer.Option(0.0, help="Allow the model to slide +-N px (applied to "
                                    "spike AND null scenes alike); 0 pins it to the centroid"),
    point: bool = typer.Option(False, help="Model the source as a point rather than the "
                              "whole footprint (see footprint_model)"),
    suffix: str = typer.Option("", help="Tag appended to output filenames"),
) -> None:
    """Matched filter vs the aperture statistic, on verified positives and negatives."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not sigma_px:
        sigma_px = json.loads((RESULTS / "psf_fit.json").read_text())["sigma_px"]
    log.info("scoring with sigma = %.3f px, fit_shift = %.2f px", sigma_px, fit_shift)

    frames, scene_frames = {}, {}
    for set_name in ("positives", "negatives"):
        files = sorted((STAMP_ROOT / set_name).glob("*.npz"))
        rows, scenes = [], []
        for p in files:
            try:
                rec = _load_stamp(p)
            except Exception:  # noqa: BLE001
                continue
            got = _score_target(rec, sigma_px, fit_shift=fit_shift, point=point)
            if got:
                rows.append(got[0])
                scenes.append(got[1])
        df = pd.DataFrame(rows)
        df["set"] = set_name
        frames[set_name] = df
        sc = pd.concat(scenes, ignore_index=True) if scenes else pd.DataFrame()
        if not sc.empty:
            sc["set"] = set_name
        scene_frames[set_name] = sc
        log.info("%s: %d scored targets, %d flagged scenes", set_name, len(df), len(sc))

    both = pd.concat(frames.values(), ignore_index=True)
    both.to_csv(RESULTS / f"matched_filter_scores{suffix}.csv", index=False)
    all_scenes = pd.concat([s for s in scene_frames.values() if not s.empty], ignore_index=True)
    if not all_scenes.empty:
        all_scenes.to_csv(RESULTS / f"matched_filter_scenes{suffix}.csv", index=False)
    if frames["negatives"].empty:
        log.warning("no negatives scored yet -- run `stamps --set negatives` once the "
                    "series pull finishes. Reporting positives only.")
        return

    out = []
    for label, lo, hi in (("<100", 0, 100), ("100-500", 100, 500), ("500-1k", 500, 1000),
                          ("1k-5k", 1000, 5000), (f"<{max_area:.0f} (headline)", 0, max_area),
                          ("all", 0, 1e12)):
        p = frames["positives"]
        n = frames["negatives"]
        p = p[(p.area_m2 >= lo) & (p.area_m2 < hi)]
        n = n[(n.area_m2 >= lo) & (n.area_m2 < hi)]
        if len(p) < 5 or len(n) < 5:
            continue
        # Per-scene AUC alongside the per-target one. A per-target max over N flagged
        # scenes rises with N by chance alone, so if the two sets differ in how many
        # scenes the stage-1 rule flags, the per-target comparison is partly measuring
        # that difference. The per-scene view has one trial per row and cannot.
        sp = all_scenes[(all_scenes.set == "positives") & (all_scenes.area_m2 >= lo)
                        & (all_scenes.area_m2 < hi)]
        sn = all_scenes[(all_scenes.set == "negatives") & (all_scenes.area_m2 >= lo)
                        & (all_scenes.area_m2 < hi)]
        row = dict(bin=label, n_pos=len(p), n_neg=len(n),
                   med_spikes_pos=float(p.n_spike.median()),
                   med_spikes_neg=float(n.n_spike.median()),
                   auc_mf=_roc_auc(p.mf_z_max.to_numpy(), n.mf_z_max.to_numpy()),
                   auc_aperture=_roc_auc(p.ap_z_max.to_numpy(), n.ap_z_max.to_numpy()),
                   auc_mf_scene=_roc_auc(sp.mf_z.to_numpy(), sn.mf_z.to_numpy()),
                   auc_ap_scene=_roc_auc(sp.ap_z.to_numpy(), sn.ap_z.to_numpy()))
        for tpr in (0.5, 0.8):
            _t, f_mf = _false_rate_at(p.mf_z_max.to_numpy(), n.mf_z_max.to_numpy(), tpr)
            _t, f_ap = _false_rate_at(p.ap_z_max.to_numpy(), n.ap_z_max.to_numpy(), tpr)
            row[f"fpr_mf@tpr{int(tpr*100)}"] = f_mf
            row[f"fpr_ap@tpr{int(tpr*100)}"] = f_ap
        out.append(row)
    res = pd.DataFrame(out)
    log.info("\n%s", res.round(3).to_string(index=False))
    res.to_csv(RESULTS / f"matched_filter_comparison{suffix}.csv", index=False)
    log.info("wrote %s", RESULTS / f"matched_filter_comparison{suffix}.csv")

    # Robustness: positives drawn from inside the calibration quadrats only, so both sets
    # come from the same landscapes. The main table controls for size but not for place,
    # and background structure is what the false-spike rate is made of -- the documented
    # control false-validation rate is 8.7% in Lahore against 20.8% in Germany, a
    # region dependence larger than most of the effects being measured here.
    memb = DATA_DIR / "glint" / "country2000_quadrat_membership.csv"
    if memb.exists():
        mp = pd.read_csv(memb).set_index("pid")["quadrat"].fillna("")
        p_all = frames["positives"].copy()
        p_all["quadrat"] = p_all.pid.map(mp).fillna("")
        p_q = p_all[p_all.quadrat.astype(str).str.len() > 0]
        n_all = frames["negatives"]
        if len(p_q) >= 10:
            sub = []
            for label, lo, hi in ((f"<{max_area:.0f}", 0, max_area), ("all", 0, 1e12)):
                p = p_q[(p_q.area_m2 >= lo) & (p_q.area_m2 < hi)]
                n = n_all[(n_all.area_m2 >= lo) & (n_all.area_m2 < hi)]
                if len(p) < 5 or len(n) < 5:
                    continue
                r = dict(bin=label, n_pos=len(p), n_neg=len(n),
                         auc_mf=_roc_auc(p.mf_z_max.to_numpy(), n.mf_z_max.to_numpy()),
                         auc_aperture=_roc_auc(p.ap_z_max.to_numpy(), n.ap_z_max.to_numpy()))
                for tpr in (0.5, 0.8):
                    _t, f_mf = _false_rate_at(p.mf_z_max.to_numpy(), n.mf_z_max.to_numpy(), tpr)
                    _t, f_ap = _false_rate_at(p.ap_z_max.to_numpy(), n.ap_z_max.to_numpy(), tpr)
                    r[f"fpr_mf@tpr{int(tpr*100)}"] = f_mf
                    r[f"fpr_ap@tpr{int(tpr*100)}"] = f_ap
                sub.append(r)
            if sub:
                sdf = pd.DataFrame(sub)
                log.info("in-quadrat positives only (same landscapes as the controls):\n%s",
                         sdf.round(3).to_string(index=False))
                sdf.to_csv(RESULTS / f"matched_filter_comparison_inquadrat{suffix}.csv", index=False)


def _shifted_model(rec: dict, sigma_px: float, dy: float, dx: float,
                   box: tuple[slice, slice], point: bool = False) -> np.ndarray:
    """Source model translated by (dy, dx) pixels before blurring."""
    from shapely.affinity import translate
    rec2 = dict(rec)
    geom = shapely_wkt.loads(str(rec["geom_native_wkt"]))
    # Native CRS is metric (UTM) and the grid is 10 m; +row is -northing.
    rec2["geom_native_wkt"] = translate(geom, xoff=dx * 10.0, yoff=-dy * 10.0).wkt
    return _crop_kernel(footprint_model(rec2, sigma_px, point=point), box)


@app.command()
def jitter(
    set_name: str = typer.Option("positives", "--set"),
    sigma_px: float = typer.Option(0.0, help="0 reads results/glint_psf/psf_fit.json"),
    max_area: float = typer.Option(1000.0, help="Small targets only: a big array's glint "
                                   "can genuinely sit off-centre, which is not jitter"),
    search: float = typer.Option(1.2, help="Half-width of the offset search, pixels"),
    step: float = typer.Option(0.15, help="Offset search step, pixels"),
) -> None:
    """How much of the fitted PSF width is per-scene co-registration error?

    The background is a median over eight dates. If a scene's geolocation differs from
    that median by a fraction of a pixel, the difference image carries a shifted source,
    and a fit that holds position fixed can only absorb the shift by widening. Sentinel-2's
    geolocation is specified at roughly 0.3 px after GRI refinement, which is the same
    order as the gap between the fitted sigma and the optical theory range -- so this is
    the first thing to rule in or out, and it decides whether the fitted kernel should be
    read as the sensor PSF or as an effective kernel that already includes registration.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not sigma_px:
        sigma_px = json.loads((RESULTS / "psf_fit.json").read_text())["sigma_px"]
    offs = np.arange(-search, search + 1e-9, step)

    rows = []
    for p in sorted((STAMP_ROOT / set_name).glob("*.npz")):
        rec = _load_stamp(p)
        if not np.isfinite(rec["area_m2"]) or float(rec["area_m2"]) > max_area:
            continue
        box = fit_box(rec, pad_px=6.0)
        cache = {(dy, dx): _shifted_model(rec, sigma_px, dy, dx, box)
                 for dy in offs for dx in offs}
        for i in np.where(rec["roles"] == "spike")[0]:
            ex = rec["stamps"][i][box]
            best = (-np.inf, np.nan, np.nan, np.nan)
            for (dy, dx), k in cache.items():
                expl, tot = _explained(ex, k)
                if np.isfinite(expl) and expl > best[0]:
                    amp, _ = fit_amplitude(ex, k)
                    best = (expl, dy, dx, amp)
            if np.isfinite(best[1]):
                e0, _t = _explained(ex, cache[(0.0, 0.0)] if (0.0, 0.0) in cache
                                    else _shifted_model(rec, sigma_px, 0, 0, box))
                rows.append(dict(pid=str(rec["pid"]), area_m2=float(rec["area_m2"]),
                                 dy=best[1], dx=best[2], amp=best[3],
                                 explained_shifted=best[0], explained_centred=e0))
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no usable spike scenes")
    df["radial"] = np.hypot(df.dy, df.dx)
    df.to_csv(RESULTS / "jitter_offsets.csv", index=False)
    log.info("%d spike scenes across %d targets < %.0f m2", len(df), df.pid.nunique(), max_area)
    log.info("offset: median radial %.2f px, 90th pct %.2f px; dy sd %.2f, dx sd %.2f",
             df.radial.median(), df.radial.quantile(0.9), df.dy.std(), df.dx.std())
    log.info("mean bias (a systematic pointing error rather than jitter): dy %.2f, dx %.2f",
             df.dy.mean(), df.dx.mean())
    gain = (df.explained_shifted - df.explained_centred) / df.explained_centred.abs().clip(1e-9)
    log.info("variance explained gained by allowing the shift: median %.1f%%", 100 * gain.median())
    log.info("NOTE: the search is bounded at +-%.2f px, so the tail is censored, and a "
             "free shift can only ever raise explained variance -- read the median, not the max.",
             search)


@app.command()
def legacy_compare(
    set_name: str = typer.Option("positives", "--set"),
    max_area: float = typer.Option(500.0, help="Match the prototype's <500 m2 calibration set"),
) -> None:
    """Re-run the prototype's kernel estimator on THIS stamp cache.

    The prototype's kernel and this script's differ in both data and method, and only one
    of those is interesting. Rebuilding its estimator -- nearest-integer crop,
    peak-normalise, median-stack -- on the same stamps isolates the method: any change in
    recovered width is attributable to the three fixes, not to which targets were read.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    RESULTS.mkdir(parents=True, exist_ok=True)
    r_stamp = 5  # the prototype's STAMP_R, giving an 11x11 template

    legacy_stamps, phases = [], []
    for p in sorted((STAMP_ROOT / set_name).glob("*.npz")):
        rec = _load_stamp(p)
        if not np.isfinite(rec["area_m2"]) or float(rec["area_m2"]) > max_area:
            continue
        row0, col0 = float(rec["row0"]), float(rec["col0"])
        phases.append((row0 - np.floor(row0), col0 - np.floor(col0)))
        ri, ci = int(round(row0)), int(round(col0))
        h, w = rec["background"].shape
        if ri - r_stamp < 0 or ci - r_stamp < 0 or ri + r_stamp + 1 > h or ci + r_stamp + 1 > w:
            continue
        for i in np.where(rec["roles"] == "spike")[0]:
            st = rec["stamps"][i][ri - r_stamp:ri + r_stamp + 1, ci - r_stamp:ci + r_stamp + 1]
            if not np.isfinite(st).all():
                continue
            peak = np.nanmax(st)
            if peak <= 0:
                continue
            legacy_stamps.append(st / peak)  # peak-normalised: the prototype's step
    if not legacy_stamps:
        raise SystemExit("no usable stamps")
    kern = np.median(np.stack(legacy_stamps), axis=0)
    kern = np.clip(kern, 0, None)
    kern /= kern.max()

    # Radial profile and its half-maximum crossing, the prototype's own width measure.
    r = kern.shape[0] // 2
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    rad = np.sqrt(xx**2 + yy**2)
    bins = np.arange(0, r + 1.5, 1.0)
    idx = np.digitize(rad.ravel(), bins)
    prof = np.array([kern.ravel()[idx == i].mean() for i in range(1, len(bins))])
    half = prof[0] / 2
    below = np.where(prof <= half)[0]
    if len(below) and below[0] > 0:
        j = below[0]
        fwhm = 2 * (bins[j - 1] + (prof[j - 1] - half) / (prof[j - 1] - prof[j]))
    else:
        fwhm = np.nan
    ph = np.array(phases)
    fit = json.loads((RESULTS / "psf_fit.json").read_text()) if (RESULTS / "psf_fit.json").exists() else {}

    log.info("prototype estimator on this cache: %d stamps from targets <%.0f m2",
             len(legacy_stamps), max_area)
    log.info("  radial FWHM = %.2f px  (implied Gaussian sigma %.2f px)", fwhm, fwhm / 2.3548)
    log.info("  wing floor at r>=3 px = %.3f of peak (a true PSF goes to zero)",
             float(np.nanmean(prof[3:])))
    log.info("  sub-pixel phase spread of the stack: row %.2f, col %.2f (uniform would be ~0.29)",
             ph[:, 0].std(), ph[:, 1].std())
    if fit:
        log.info("  this script's forward-model fit: sigma %.2f px (FWHM %.2f px); theory %.2f-%.2f px sigma",
                 fit["sigma_px"], fit["fwhm_px"], *fit["theory_sigma_px"])
    (RESULTS / "legacy_kernel.json").write_text(json.dumps(dict(
        n_stamps=len(legacy_stamps), max_area_m2=max_area,
        fwhm_px=float(fwhm), implied_sigma_px=float(fwhm / 2.3548),
        wing_floor=float(np.nanmean(prof[3:])),
        radial_profile=prof.tolist(),
    ), indent=2))
    np.save(RESULTS / "legacy_kernel.npy", kern)
    log.info("wrote %s", RESULTS / "legacy_kernel.json")


@app.command()
def figure(
    set_name: str = typer.Option("positives", "--set"),
    small_max_m2: float = typer.Option(150.0, help="Area ceiling for the stacked-profile "
                                       "panel: targets small enough to read as points"),
) -> None:
    """Diagnostics: the sigma likelihood against theory, sigma-vs-size flatness, and an
    observed-vs-model radial profile stacked over the smallest targets."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    fit = json.loads((RESULTS / "psf_fit.json").read_text())
    prof = np.load(RESULTS / "psf_profiles.npz")
    pb = pd.read_csv(RESULTS / "psf_by_bucket.csv")
    sigma_hat = fit["sigma_px"]
    th_lo, th_hi = fit["theory_sigma_px"]

    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.3))

    ax = axes[0]
    ax.plot(prof["sigmas"], prof["mean_profile"], "-", color="tab:orange", lw=2)
    ax.axvspan(th_lo, th_hi, color="tab:blue", alpha=0.15,
               label=f"ESA MTF@Nyquist {fit['mtf_nyquist_range'][0]}-{fit['mtf_nyquist_range'][1]}")
    ax.axvline(sigma_hat, color="tab:orange", ls="--",
               label=f"fitted $\\sigma$={sigma_hat:.2f} px")
    ax.set_xlabel("PSF $\\sigma$ (pixels)")
    ax.set_ylabel("fraction of window variance explained")
    ax.set_title(f"Joint PSF fit, n={fit['n_targets_fit']} targets", fontsize=10)
    ax.legend(fontsize=8)

    ax = axes[1]
    ax.axhspan(th_lo, th_hi, color="tab:blue", alpha=0.15, label="theory range")
    ax.plot(pb.median_area_m2, pb.sigma, "o-", color="tab:orange")
    for _i, r in pb.iterrows():
        ax.annotate(f"{r.bucket}\nn={int(r.n)}", (r.median_area_m2, r.sigma),
                    textcoords="offset points", xytext=(0, 8), ha="center", fontsize=7)
    ax.set_xscale("log")
    ax.set_xlabel("median installation area (m$^2$)")
    ax.set_ylabel("fitted $\\sigma$ (pixels)")
    ax.set_title("One PSF for every size?\n(flat = extent and PSF separated)", fontsize=10)
    ax.legend(fontsize=8)

    # Stacked radial profile over the smallest targets, in true sub-pixel offsets.
    ax = axes[2]
    obs_r, obs_v, mod_v = [], [], []
    for p in sorted((STAMP_ROOT / set_name).glob("*.npz")):
        rec = _load_stamp(p)
        if not np.isfinite(rec["area_m2"]) or float(rec["area_m2"]) > small_max_m2:
            continue
        box = fit_box(rec)
        kern = _crop_kernel(footprint_model(rec, sigma_hat), box)
        h, w = kern.shape
        yy, xx = np.mgrid[box[0].start:box[0].stop, box[1].start:box[1].stop]
        rad = np.sqrt((yy + 0.5 - float(rec["row0"]))**2 + (xx + 0.5 - float(rec["col0"]))**2)
        for i in np.where(rec["roles"] == "spike")[0]:
            ex = rec["stamps"][i][box]
            amp, _ = fit_amplitude(ex, kern)
            if not np.isfinite(amp) or amp <= 0:
                continue
            m = np.isfinite(ex)
            obs_r.append(rad[m])
            obs_v.append((ex[m] / amp))
            mod_v.append(kern[m])
    if obs_r:
        r_all = np.concatenate(obs_r)
        o_all = np.concatenate(obs_v)
        m_all = np.concatenate(mod_v)
        bins = np.arange(0, 6.5, 0.5)
        idx = np.digitize(r_all, bins) - 1
        ok = (idx >= 0) & (idx < len(bins) - 1)
        centres = 0.5 * (bins[:-1] + bins[1:])
        o_prof = np.array([np.nanmedian(o_all[ok & (idx == i)]) if (ok & (idx == i)).sum() > 5
                           else np.nan for i in range(len(centres))])
        m_prof = np.array([np.nanmedian(m_all[ok & (idx == i)]) if (ok & (idx == i)).sum() > 5
                           else np.nan for i in range(len(centres))])
        norm = np.nanmax(m_prof)
        ax.plot(centres, o_prof / norm, "o-", color="tab:orange", label="observed (stacked)")
        ax.plot(centres, m_prof / norm, "s--", color="tab:blue",
                label=f"model, $\\sigma$={sigma_hat:.2f} px")
        ax.axhline(0, color="0.6", lw=0.8)
        ax.set_xlabel("radius from true sub-pixel centroid (px)")
        ax.set_ylabel("normalised profile")
        ax.set_title(f"Stacked profile, targets < {small_max_m2:.0f} m$^2$", fontsize=10)
        ax.legend(fontsize=8)
    fig.tight_layout()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "psf_diagnostics.png"
    fig.savefig(out, dpi=150)
    log.info("wrote %s", out)


if __name__ == "__main__":
    app()
