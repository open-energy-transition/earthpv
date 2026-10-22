"""Glint panel-pose survey for any country: fitted tilt and azimuth for every mapped
installation above a size floor.

Pakistan's survey (`glint_orientation_country2000.py`) was a size-stratified SAMPLE with
its source, dates and output paths hard-coded. This is the same measurement
(`glint_validation.analyze_point`, tol_deg=3, the default spatial spike criterion) over a
whole population, parameterised by `--name`, so France is one invocation and the next
country another:

    python scripts/glint_pose_survey.py targets --name france \
        --source data/labels/france_osm_20261022/france_overpass_solar.parquet --min-area 1000
    python scripts/glint_pose_survey.py pull    --name france --start 2024-10-01 --end 2026-10-01
    python scripts/glint_pose_survey.py analyze --name france

Three differences from the Pakistan script, all about scale:

1. **Targets are dissolved first** (`labels.dissolve_overlapping`, per placement). A
   `power=plant` perimeter with nested `power=generator` ways is one installation, and
   fitting it three times would triple-count one pose.
2. **Chunks are geographic, not random.** `tile_scene_series_batch` does one STAC search
   and one asset open per scene per 1-degree group, shared by every member. A chunk drawn
   at random from the whole country spreads ~150 targets over dozens of groups with a
   handful each; sorting by group first fills each chunk from as few groups as possible,
   so the per-scene cost is shared by many targets instead of paid again for each.
3. **Each chunk is capped in targets, not in groups, and starts on a fresh token.**
   `planetary_computer` caches a 45-minute SAS token and only replaces it with under 60 s
   left, so a chunk can start on a token with minutes to live and lose every read after
   it expires -- the staleness behind docs/issues/glint-tile-batched-coverage.md. The
   cache is cleared before each chunk, and ~30 targets keep a chunk near 25 minutes.
4. **One read per acquisition** (`tile_scene_series_batch(dedupe_items=True)`).
   Neighbouring MGRS tiles each deliver a copy of the same acquisition, and their granule
   sensing times differ by ~14 s, so the minute-keyed dedupe keeps both whenever they
   straddle a minute. The France pilot read 308 items for 126 dates. Worse, a glint seen
   twice counts as two consistent spikes: 10 of Pakistan's 346 validated fits rested on one
   acquisition counted twice. `glint.annotate_spikes` now collapses rows sharing a day and
   a view azimuth before anything is fitted, so a series pulled the old way is safe too.

Per-target series are cached to `data/glint/<name>_pose/series/<pid>.parquet` as each
chunk lands, so a killed pull resumes. A target that returned no scenes at all is NOT
cached (an outage would otherwise read as "never glints" forever); `analyze` reports how
many are missing.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402
from glint_validation import analyze_point  # noqa: E402 (shared spike/fit logic)

log = logging.getLogger("glint_pose_survey")
app = typer.Typer(pretty_exceptions_show_locals=False)

BANDS = ("B03", "B08")
TILE_DEG = 1.0
BINS = [0, 1000, 5000, 50000, np.inf]
LABELS = ["<1k", "1k-5k", "5k-50k", ">50k"]


def _dir(name: str) -> Path:
    return DATA_DIR / "glint" / f"{name}_pose"


def _utc(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


@app.command()
def targets(
    name: str = typer.Option(...),
    source: Path = typer.Option(..., help="solar polygons (parquet or GeoJSON) with an id "
                                "column and, ideally, placement"),
    min_area: float = typer.Option(1000.0, help="dissolved footprint floor, m2"),
    id_col: str = typer.Option("id"),
):
    """Dissolve the source per placement and keep every polygon at or above `min_area`."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from earthpv.labels import dissolve_overlapping

    g = gpd.read_parquet(source) if source.suffix == ".parquet" else gpd.read_file(source)
    g = g[g.geometry.geom_type.isin(("Polygon", "MultiPolygon"))].reset_index(drop=True)
    if "placement" not in g.columns:
        g["placement"] = "unknown"
    if "kind" not in g.columns:
        g["kind"] = "unknown"
    n_raw = len(g)
    g = dissolve_overlapping(g, group_col="placement")
    log.info("%d polygons -> %d after dissolving overlaps", n_raw, len(g))
    g = g[g.area_m2 >= min_area].reset_index(drop=True)
    reps = g.geometry.representative_point()
    out = gpd.GeoDataFrame({
        "src_id": g[id_col].astype(str).values,
        "kind": g["kind"].astype(str).values,
        "placement": g["placement"].astype(str).values,
        "area_m2": g["area_m2"].round(1).values,
        "n_dissolved": g["n_dissolved"].values,
        "lon": reps.x.round(6).values,
        "lat": reps.y.round(6).values,
    }, geometry=g.geometry.values, crs="EPSG:4326")
    # Geographic order: the pull chunks this frame in order, so neighbours share groups.
    key = np.floor(out.lon / TILE_DEG).astype(int) * 10_000 + np.floor(out.lat / TILE_DEG).astype(int)
    out = out.assign(_k=key).sort_values(["_k", "lat", "lon"]).drop(columns="_k").reset_index(drop=True)
    out.insert(0, "pid", [f"{name[:2]}p_{i:05d}" for i in range(len(out))])
    d = _dir(name)
    d.mkdir(parents=True, exist_ok=True)
    out.to_parquet(d / "targets.parquet")
    log.info("wrote %s: %d targets >= %.0f m2 (%s)", d / "targets.parquet", len(out), min_area,
             out.placement.value_counts().to_dict())


@app.command()
def pull(
    name: str = typer.Option(...),
    start: str = typer.Option(..., help="YYYY-MM-DD"),
    end: str = typer.Option(..., help="YYYY-MM-DD"),
    chunk_size: int = typer.Option(30),
    max_workers: int = typer.Option(16),
    limit: int = typer.Option(0, help="pull at most this many targets (a pilot)"),
):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    d = _dir(name)
    series_dir = d / "series"
    series_dir.mkdir(parents=True, exist_ok=True)
    t = gpd.read_parquet(d / "targets.parquet")
    todo = t[~t.pid.map(lambda p: (series_dir / f"{p}.parquet").exists())].reset_index(drop=True)
    if limit:
        todo = todo.head(limit)
    log.info("%d targets, %d to pull", len(t), len(todo))
    import planetary_computer.sas as pc_sas

    n_chunks = -(-len(todo) // chunk_size)
    prev_groups: set = set()
    for i in range(n_chunks):
        chunk = todo.iloc[i * chunk_size:(i + 1) * chunk_size]
        groups = {glint._tile_key(x, y, TILE_DEG) for x, y in zip(chunk.lon, chunk.lat)}
        if not groups & prev_groups:
            glint._tile_angles_cache.clear()  # unbounded per-item cache; a new area never reuses it
        prev_groups = groups
        pc_sas.TOKEN_CACHE.clear()
        t0 = datetime.now()
        try:
            series = glint.tile_scene_series_batch(
                chunk, _utc(start), _utc(end), bands=BANDS, tile_deg=TILE_DEG,
                max_workers=max_workers, dedupe_items=True,
            )
        except Exception as e:  # noqa: BLE001 - one bad chunk must not kill the pull
            log.warning("chunk %d/%d FAILED: %s -- retried on the next run", i + 1, n_chunks, e)
            continue
        counts = [len(s) for s in series.values()]
        n_empty = sum(c == 0 for c in counts)
        for pid, s in series.items():
            if not s.empty:
                s.to_parquet(series_dir / f"{pid}.parquet")
        minutes = (datetime.now() - t0).total_seconds() / 60
        log.info("chunk %d/%d: %d targets in %.1f min, scenes median %.0f (min %d), %d empty "
                 "(not cached, retried next run)", i + 1, n_chunks, len(chunk), minutes,
                 np.median(counts) if counts else 0, min(counts, default=0), n_empty)
        if minutes > 40:
            log.warning("chunk %d took %.0f min, close to the 45-min token life: late reads "
                        "may have failed; lower --chunk-size", i + 1, minutes)
    log.info("PULL_DONE")


@app.command()
def analyze(name: str = typer.Option(...), tol_deg: float = 3.0):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    d = _dir(name)
    t = gpd.read_parquet(d / "targets.parquet")
    rows = []
    for r in t.itertuples():
        p = d / "series" / f"{r.pid}.parquet"
        if not p.exists():
            continue
        res, _ = analyze_point(pd.read_parquet(p), tol_deg)
        rows.append(dict(pid=r.pid, src_id=r.src_id, kind=r.kind, placement=r.placement,
                         area_m2=r.area_m2, lon=r.lon, lat=r.lat, **res))
    s = pd.DataFrame(rows)
    s["detected"] = s.n_spikes >= 1
    s["validated"] = s.n_consistent >= 2
    s["bucket"] = pd.cut(s.area_m2, bins=BINS, labels=LABELS)
    s.to_csv(d / "summary.csv", index=False)
    log.info("%d of %d targets have a series (%d missing) -> %s",
             len(s), len(t), len(t) - len(s), d / "summary.csv")

    def agg(g):
        fit = g[g.validated]
        return pd.Series({
            "n": len(g), "med_scenes": g.n_scenes.median(), "med_clear": g.n_clear.median(),
            "pct_detected": 100 * g.detected.mean(), "pct_validated": 100 * g.validated.mean(),
            "med_tilt": fit.fit_tilt.median(), "med_az": fit.fit_az.median(),
        })

    for col in ("placement", "bucket"):
        tab = s.groupby(col, observed=True).apply(agg, include_groups=False).round(1)
        tab.to_csv(d / f"stats_by_{col}.csv")
        print(f"\n=== by {col} ===\n{tab.to_string()}")


@app.command()
def export(
    name: str = typer.Option(...),
    country: str = typer.Option(..., help="display name for the pose page"),
    out_dir: Path = typer.Option(Path("results")),
):
    """Validated poses as GeoJSON (one polygon per installation) plus the pose survey page."""
    from earthpv.pose import build_pose_survey_page

    d = _dir(name)
    s = pd.read_csv(d / "summary.csv")
    t = gpd.read_parquet(d / "targets.parquet")[["pid", "geometry"]]
    fit = t.merge(s[s.validated], on="pid")
    fit = fit[["pid", "src_id", "placement", "kind", "area_m2", "fit_tilt", "fit_az",
               "n_consistent", "n_spikes", "n_clear", "geometry"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    gj = out_dir / f"{name}_glint_pose.geojson"
    gpd.GeoDataFrame(fit, geometry="geometry", crs="EPSG:4326").to_file(gj, driver="GeoJSON")
    build_pose_survey_page(d / "summary.csv", out_dir / f"{name}_pv_pose.html", country=country)
    log.info("%d validated poses of %d analysed -> %s", len(fit), len(s), gj)


if __name__ == "__main__":
    app()
