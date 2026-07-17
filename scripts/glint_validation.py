"""Empirical test: are PV glints visible in Sentinel-2 L2A time series, and do
spike dates match the specular geometry predicted by earthpv.glint?

For each test array (OSM-confirmed PV polygons; Germany rooftops + ground
farms, Lahore rooftops + ground), pulls ~2 years of per-scene statistics:
  - p98 reflectance inside the polygon (B03 green + B08 NIR, both 10 m),
  - median reflectance of a surrounding annulus (cloud/shadow discriminator:
    a glint brightens only the array, a cloud brightens the neighbourhood),
  - per-point sun/view angles from the granule MTD_TL.xml grids.

Then flags spikes (bright in both bands, annulus stable) and checks whether
their dates are consistent with a single panel orientation (tilt, azimuth)
via the specular condition.

Usage:
  python scripts/glint_validation.py pull --region lahore
  python scripts/glint_validation.py pull --region germany
  python scripts/glint_validation.py analyze
"""

from __future__ import annotations

import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
import typer

from earthpv import glint
from earthpv.config import DATA_DIR

log = logging.getLogger("glint_validation")
app = typer.Typer(pretty_exceptions_show_locals=False)

OUT_DIR = DATA_DIR / "glint"
DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
MAX_CLOUD = 80
BANDS = ("B03", "B08")
TARGET_THREADS = 4    # targets pulled concurrently
SCENE_THREADS = 8     # scenes-per-target concurrency (passed to glint.scene_series)


# ---------------------------------------------------------------- targets

def _pts(df: gpd.GeoDataFrame, tag: str) -> list[dict]:
    reproj = df.geometry.to_crs("EPSG:6933").centroid.to_crs("EPSG:4326")
    return [
        dict(pid=f"{tag}_{i}", osm_id=str(r[0]), placement=tag.split("-")[1],
             area_m2=float(r[1]), lon=float(p.x), lat=float(p.y), geometry=r[2])
        for i, (r, p) in enumerate(zip(df[[df.columns[0], "area_m2", "geometry"]].values, reproj))
    ]


def targets(region: str) -> list[dict]:
    if region == "lahore":
        g = gpd.read_parquet(DATA_DIR / "labels" / "lahore_overpass_solar.parquet")
        g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])]
        roof = g[(g.placement == "rooftop") & (g.area_m2 >= 1000)].nlargest(8, "area_m2")
        ground = g[(g.placement == "ground")].nlargest(4, "area_m2")
        return _pts(roof.reset_index()[["id", "area_m2", "geometry"]], "lahore-rooftop") + \
               _pts(ground.reset_index()[["id", "area_m2", "geometry"]], "lahore-ground")
    if region == "germany":
        g = gpd.read_parquet(
            "/run/media/tobi/aidisc/rooftopsenti/data/germany_500/osm/labels.parquet"
        )
        roof = g[(g.on_building) & (g.area_m2.between(2500, 30000))].nlargest(8, "area_m2")
        ground = g[g.area_m2 > 5e5].nlargest(4, "area_m2")
        return _pts(roof.reset_index()[["osm_id", "area_m2", "geometry"]], "germany-rooftop") + \
               _pts(ground.reset_index()[["osm_id", "area_m2", "geometry"]], "germany-ground")
    raise typer.BadParameter(f"unknown region {region}")


# ---------------------------------------------------------------- pull

def _pull_target(tgt: dict) -> pd.DataFrame:
    df = glint.scene_series(
        tgt["geometry"], DATE_RANGE[0], DATE_RANGE[1],
        bands=BANDS, max_cloud=MAX_CLOUD, n_threads=SCENE_THREADS,
    )
    if not df.empty:
        df = df.assign(pid=tgt["pid"])
    log.info("%s: %d scenes", tgt["pid"], len(df))
    return df


@app.command()
def pull(region: str = typer.Option(...)):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tgts = targets(region)
    log.info("%s: %d targets", region, len(tgts))

    frames = []
    with ThreadPoolExecutor(TARGET_THREADS) as ex:
        futs = {ex.submit(_pull_target, tgt): tgt for tgt in tgts}
        for f in as_completed(futs):
            frames.append(f.result())

    df = pd.concat(frames, ignore_index=True).sort_values(["pid", "time"])
    meta = pd.DataFrame([{k: v for k, v in t.items() if k != "geometry"} for t in tgts])
    df = df.merge(meta[["pid", "placement", "area_m2", "lon", "lat", "osm_id"]], on="pid")
    out = OUT_DIR / f"raw_{region}.parquet"
    df.to_parquet(out)
    log.info("wrote %s (%d rows)", out, len(df))


# ---------------------------------------------------------------- analyze

def analyze_point(d: pd.DataFrame, tol_deg: float = 3.0) -> tuple[dict, pd.DataFrame]:
    """Spike detection + geometry consistency for one target's time series.

    Thin wrapper around `earthpv.glint.annotate_spikes`/`fit_best_orientation` that
    adds the two diagnostics only this validation script cares about (spike
    brightness multiple, and how many clear scenes the fitted orientation predicts
    should glint) — `postprocess.py`'s `add_glint_prior` uses the shared
    `glint.spike_fit` directly since it doesn't need these for plotting.
    """
    d = glint.annotate_spikes(d, bands=BANDS)
    if d.empty:
        # All scenes lacked usable reflectance stats (e.g. sub-pixel target under the
        # old strict mask) — report zeros instead of crashing on missing columns.
        return dict(n_scenes=0, n_clear=0, n_spikes=0, base_B08=np.nan,
                    fit_tilt=np.nan, fit_az=np.nan, n_consistent=0, n_predicted=0,
                    med_spike_amp=np.nan), d
    base_b08 = d.loc[d.clear, "a_B08"].median() if d.clear.any() else np.nan
    res = dict(n_scenes=len(d), n_clear=int(d.clear.sum()) if len(d) else 0,
               n_spikes=int(d.spike.sum()) if len(d) else 0,
               base_B08=round(base_b08, 3) if pd.notna(base_b08) else np.nan,
               fit_tilt=np.nan, fit_az=np.nan, n_consistent=0, n_predicted=0,
               med_spike_amp=np.nan)
    if d.empty:
        return res, d
    sp = d[d.spike]
    if len(sp):
        res["med_spike_amp"] = round(float((sp["a_B08"] / max(base_b08, 1e-3)).median()), 1)
    fit = glint.fit_best_orientation(d, tol_deg)
    if fit is not None:
        tilt, az, n_consistent = fit
        res["fit_tilt"], res["fit_az"], res["n_consistent"] = round(tilt, 1), round(az, 1), n_consistent
        mis_all = glint.misalignment_deg(
            d.sun_zen.to_numpy(), d.sun_az.to_numpy(), d.view_zen.to_numpy(), d.view_az.to_numpy(),
            tilt, az,
        )
        d["mis_fit"] = mis_all
        res["n_predicted"] = int((d.clear & (mis_all <= tol_deg)).sum())
    return res, d


@app.command()
def analyze(tol_deg: float = 3.0, plots: bool = True):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    frames = [
        pd.read_parquet(p) for p in sorted(OUT_DIR.glob("raw_*.parquet"))
    ]
    df = pd.concat(frames, ignore_index=True)
    summaries, detail = [], []
    for pid, d in df.groupby("pid"):
        res, dd = analyze_point(d, tol_deg)
        res = dict(pid=pid, placement=d.placement.iloc[0],
                   area_m2=int(d.area_m2.iloc[0]), **res)
        summaries.append(res)
        detail.append(dd)
    summary = pd.DataFrame(summaries).sort_values("pid")
    detail = pd.concat(detail, ignore_index=True)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    detail.to_parquet(OUT_DIR / "detail.parquet")
    print(summary.to_string(index=False))
    if plots:
        _plots(detail, summary)


def _plots(detail: pd.DataFrame, summary: pd.DataFrame):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pdir = OUT_DIR / "plots"
    pdir.mkdir(exist_ok=True)
    for pid, d in detail.groupby("pid"):
        s = summary[summary.pid == pid].iloc[0]
        d = d.sort_values("time")
        fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1]})
        ax = axes[0]
        clear = d[d.clear]
        ax.plot(d.time, d.a_B08, ".", color="0.8", ms=4, label="all scenes")
        ax.plot(clear.time, clear.a_B08, ".", color="tab:blue", ms=5, label="annulus-stable")
        sp = d[d.spike]
        ax.plot(sp.time, sp.a_B08, "r*", ms=14, label="spike")
        ax.plot(d.time, d.r_B08, "-", color="tab:green", lw=0.7, alpha=0.6, label="annulus B08")
        ax.set_ylabel("B08 refl (p98 in-polygon)")
        ax.set_title(f"{pid}  {s.placement}  {s.area_m2} m²   spikes={s.n_spikes} "
                     f"fit tilt/az={s.fit_tilt}/{s.fit_az}")
        ax.legend(fontsize=8, ncol=4)
        ax2 = axes[1]
        if "mis_fit" in d and d.mis_fit.notna().any():
            ax2.plot(d.time, d.mis_fit, ".-", lw=0.5, ms=3, color="tab:purple")
            ax2.axhline(3, color="r", lw=0.7, ls="--")
            ax2.set_ylabel("misalign (deg)\nfor fit orientation")
            ax2.set_ylim(0, 60)
        fig.tight_layout()
        fig.savefig(pdir / f"{pid}.png", dpi=110)
        plt.close(fig)
    log.info("plots -> %s", pdir)


if __name__ == "__main__":
    app()
