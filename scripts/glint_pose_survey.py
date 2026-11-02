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
    python scripts/glint_pose_survey.py osm-tags --summary data/glint/france_pose/summary.csv
    python scripts/glint_pose_survey.py parts-pull --summary data/glint/france_pose/summary.csv \
        --start 2025-10-01 --end 2026-10-01
    python scripts/glint_pose_survey.py parts-analyze --summary data/glint/france_pose/summary.csv

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

from earthpv import glint, pose_parts  # noqa: E402
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
    sample: int = typer.Option(0, help="draw this many instead of keeping every polygon "
                               "(equal per size bucket, spread across 2-degree cells)"),
    seed: int = typer.Option(20261029),
):
    """Dissolve the source per placement and keep every polygon at or above `min_area`.

    `--sample N` draws N of them instead (India, 2026-10-29): an equal share per size bucket
    (`BINS`; a bucket with too few gives its remainder to the others), and within a bucket
    one polygon per 2-degree cell per pass, cells in random order, so a country whose parks
    cluster in a few states is still read across its whole map. A sample is a spread of
    poses, not a population estimate: the page shows points, never a weighted share."""
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
    if sample and sample < len(g):
        g = _spread_sample(g, sample, seed)
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


def _spread_sample(g: gpd.GeoDataFrame, n: int, seed: int, cell_deg: float = 2.0) -> gpd.GeoDataFrame:
    """`targets --sample`: equal per size bucket, round-robin over cells within each."""
    rng = np.random.default_rng(seed)
    bucket = pd.cut(g.area_m2, bins=BINS, labels=LABELS).astype(str).to_numpy()
    rep = g.geometry.representative_point()
    cell = (np.floor(rep.x / cell_deg).astype(int) * 1000 + np.floor(rep.y / cell_deg).astype(int)).to_numpy()
    present = [b for b in LABELS if (bucket == b).any()]
    sizes = {b: int((bucket == b).sum()) for b in present}
    quota = {b: 0 for b in present}
    left = n
    while left > 0:  # equal shares, a small bucket's remainder going to the rest
        open_ = [b for b in present if quota[b] < sizes[b]]
        if not open_:
            break
        share = max(left // len(open_), 1)
        for b in open_:
            add = min(share, sizes[b] - quota[b], left)
            quota[b] += add
            left -= add
    picked: list[int] = []
    for b in present:
        idx = np.flatnonzero(bucket == b)
        by_cell = {c: list(rng.permutation(idx[cell[idx] == c])) for c in np.unique(cell[idx])}
        order = list(rng.permutation(list(by_cell)))
        got: list[int] = []
        while len(got) < quota[b]:
            for c in order:
                if by_cell[c] and len(got) < quota[b]:
                    got.append(int(by_cell[c].pop()))
        picked += got
        log.info("sample %s: %d of %d over %d cells of %.0f deg", b, len(got), sizes[b],
                 len({cell[i] for i in got}), cell_deg)
    return g.iloc[sorted(picked)].reset_index(drop=True)


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


@app.command("parts-pull")
def parts_pull(
    summary: Path = typer.Option(..., help="an `analyze` summary CSV; its targets table "
                                 "(`pose.survey_sidecar`) supplies the outlines"),
    start: str = typer.Option(..., help="YYYY-MM-DD, the survey's own window"),
    end: str = typer.Option(..., help="YYYY-MM-DD"),
    min_area: float = typer.Option(pose_parts.PARTS_MIN_M2, help="read installations of at "
                                   "least this many m2 in parts"),
    cell_m: float = typer.Option(pose_parts.CELL_M),
    chunk_size: int = typer.Option(10, help="installations per chunk"),
    max_workers: int = typer.Option(16),
):
    """Per-cell glint series for every large installation (`pose_parts`): one window per
    installation per scene, every cell against the installation's surroundings. Resumable
    per installation, like `pull`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    warnings.filterwarnings("ignore", message=".*initial implementation of Parquet.*")
    logging.getLogger("earthpv.glint").setLevel(logging.ERROR)  # per-cell "too few clear"
    from earthpv.pose import survey_sidecar

    t = gpd.read_parquet(survey_sidecar(summary, "targets.parquet"))
    big = t[t.area_m2 >= min_area].reset_index(drop=True)
    parts_path = survey_sidecar(summary, "parts.parquet")
    if parts_path.exists():  # a resumed pull must read the cells it started with
        parts = gpd.read_parquet(parts_path)
    else:
        parts = pd.concat([pose_parts.split_into_parts(r.geometry, cell_m).assign(pid=r.pid)
                           for r in big.itertuples()], ignore_index=True)
        parts = gpd.GeoDataFrame(parts, geometry="geometry", crs="EPSG:4326")
        parts.to_parquet(parts_path)
    series_dir = survey_sidecar(summary, "parts")
    series_dir.mkdir(exist_ok=True)
    todo = big[~big.pid.map(lambda p: (series_dir / f"{p}.parquet").exists())]
    todo = todo[todo.pid.isin(parts.pid)].reset_index(drop=True)
    log.info("%d installations >= %.0f m2 in %d cells; %d to pull", len(big), min_area,
             len(parts), len(todo))
    import planetary_computer.sas as pc_sas

    n_chunks = -(-len(todo) // chunk_size)
    for i in range(n_chunks):
        chunk = todo.iloc[i * chunk_size:(i + 1) * chunk_size]
        cells = parts[parts.pid.isin(chunk.pid)]
        pmap = {pid: [(pose_parts.part_id(pid, r.part), r.geometry) for r in g.itertuples()]
                for pid, g in cells.groupby("pid")}
        glint._tile_angles_cache.clear()
        pc_sas.TOKEN_CACHE.clear()
        t0 = datetime.now()
        try:
            series = glint.tile_scene_series_batch(
                chunk[["pid", "geometry", "lon", "lat"]], _utc(start), _utc(end), bands=BANDS,
                tile_deg=TILE_DEG, max_workers=max_workers, dedupe_items=True, parts=pmap,
            )
        except Exception as e:  # noqa: BLE001 - one bad chunk must not kill the pull
            log.warning("chunk %d/%d FAILED: %s -- retried on the next run", i + 1, n_chunks, e)
            continue
        n_empty = 0
        for pid, members in pmap.items():
            frames = [series[q].assign(part=int(q.rsplit("#", 1)[1]))
                      for q, _ in members if not series[q].empty]
            if frames:
                pd.concat(frames, ignore_index=True).to_parquet(series_dir / f"{pid}.parquet")
            else:
                n_empty += 1
        minutes = (datetime.now() - t0).total_seconds() / 60
        log.info("chunk %d/%d: %d installations, %d cells in %.1f min, %d empty (retried next "
                 "run)", i + 1, n_chunks, len(chunk), len(cells), minutes, n_empty)
    log.info("PARTS_PULL_DONE")


@app.command("parts-analyze")
def parts_analyze(
    summary: Path = typer.Option(...),
    tol_deg: float = 3.0,
    group_deg: float = typer.Option(pose_parts.GROUP_DEG),
    min_parts: int = typer.Option(pose_parts.MIN_GROUP_PARTS),
):
    """Fit every cell, group cells into orientations (`pose_parts.group_orientations`), and
    write `<survey>parts_fit.csv` (one row per cell), `<survey>parts_farms.csv` (one row per
    installation read in parts) and `<survey>orientations.csv` (one row per orientation),
    which `pose.compute_pose_survey_data` picks up."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("earthpv.glint").setLevel(logging.ERROR)
    from earthpv.pose import survey_sidecar

    parts = gpd.read_parquet(survey_sidecar(summary, "parts.parquet"))
    series_dir = survey_sidecar(summary, "parts")
    fit_rows, farm_rows, ori_frames = [], [], []
    for pid, cells in parts.groupby("pid"):
        p = series_dir / f"{pid}.parquet"
        if not p.exists():
            continue
        s = pd.read_parquet(p)
        fits, spike_times = [], set()
        for part, g in s.groupby("part"):
            series = g.drop(columns="part")
            fits.append(dict(part=part, **pose_parts.fit_part(series, tol_deg)))
            ann = glint.annotate_spikes(series)
            spike_times |= set(pd.to_datetime(ann.loc[ann.spike, "time"]).dt.strftime("%Y%m%d%H%M"))
        f = cells.drop(columns="geometry").merge(pd.DataFrame(fits), on="part", how="left")
        fit_rows.append(f)
        ori = pose_parts.group_orientations(f.fillna({"n_consistent": 0}),
                                            float(cells.area_m2.sum()), group_deg, min_parts)
        ori_frames.append(ori.assign(pid=pid))
        farm_rows.append(dict(pid=pid, n_cells=len(cells), cells_area_m2=round(cells.area_m2.sum(), 1),
                              n_cells_read=int(f.n_scenes.notna().sum()),
                              n_cells_spiking=int((f.n_spikes > 0).sum()),
                              n_cells_fitted=int((f.n_consistent >= 2).sum()),
                              n_spike_dates=len(spike_times), n_orientations=len(ori)))
    if not farm_rows:
        log.warning("no installation has a parts series yet; run parts-pull first")
        return
    pd.concat(fit_rows).to_csv(survey_sidecar(summary, "parts_fit.csv"), index=False)
    farms = pd.DataFrame(farm_rows)
    farms.to_csv(survey_sidecar(summary, "parts_farms.csv"), index=False)
    ori = pd.concat(ori_frames, ignore_index=True)
    ori = ori[["pid", *[c for c in ori.columns if c != "pid"]]]
    ori.to_csv(survey_sidecar(summary, "orientations.csv"), index=False)
    log.info("%d installations read in parts: %d with one orientation, %d with two or more, %d "
             "with none (%d of those still spiked on two or more dates)", len(farms),
             (farms.n_orientations == 1).sum(), (farms.n_orientations >= 2).sum(),
             (farms.n_orientations == 0).sum(),
             ((farms.n_orientations == 0) & (farms.n_spike_dates >= 2)).sum())


@app.command("osm-tags")
def osm_tags(
    summary: Path = typer.Option(..., help="an `analyze` summary CSV (any survey, e.g. "
                                 "data/glint/country2000_summary.csv)"),
    all_targets: bool = typer.Option(False, help="look up every target, not only fitted ones"),
):
    """Cache OSM `name`/`operator` of the surveyed installations beside the summary, so the
    atlas can say which installation a pose belongs to without calling Overpass itself."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    from earthpv.overpass import element_tags_by_id
    from earthpv.pose import osm_tags_path, parts_outcome, pose_locations

    s = pd.read_csv(summary)
    if not all_targets:  # an installation only the parts read posed has no whole-outline fit
        s = s[(s.n_consistent >= 2) | parts_outcome(s, summary)[0]]
    ids = pose_locations(s, summary).osm_id.dropna().unique()
    tags = element_tags_by_id([f"osm-{i}" for i in ids])
    out = osm_tags_path(summary)
    tags.to_parquet(out)
    log.info("%d of %d elements returned (%d named, %d with an operator) -> %s", len(tags),
             len(ids), tags.osm_name.notna().sum(), tags.osm_operator.notna().sum(), out)
    if len(tags) < len(ids):
        log.warning("%d elements missing: deleted since the survey, or a truncated mirror "
                    "response; re-run to retry", len(ids) - len(tags))


@app.command()
def export(
    name: str = typer.Option(...),
    country: str = typer.Option(..., help="display name for the pose page"),
    out_dir: Path = typer.Option(Path("results")),
    page: bool = typer.Option(True, help="also write the standalone pose page; its colours and "
                              "histograms assume OSM generator/plant kinds, which a dissolved "
                              "survey (France) does not keep, so pass --no-page there"),
):
    """Validated poses as GeoJSON and CSV (one row per installation, with its OSM id, link,
    name and coordinates) plus the standalone pose survey page."""
    from earthpv.pose import build_pose_survey_page, pose_locations

    d = _dir(name)
    s = pd.read_csv(d / "summary.csv")
    t = gpd.read_parquet(d / "targets.parquet")[["pid", "geometry"]]
    fit = pose_locations(s[s.validated], d / "summary.csv")
    fit["osm_url"] = "https://www.openstreetmap.org/" + fit.osm_id
    fit = t.merge(fit, on="pid")
    keep = ["pid", "osm_id", "osm_url", "name", "operator", "lon", "lat", "placement", "kind",
            "area_m2", "fit_tilt", "fit_az", "n_consistent", "n_spikes", "n_clear", "geometry"]
    fit = fit[[c for c in keep if c in fit.columns]]
    out_dir.mkdir(parents=True, exist_ok=True)
    gj = out_dir / f"{name}_glint_pose.geojson"
    gpd.GeoDataFrame(fit, geometry="geometry", crs="EPSG:4326").to_file(gj, driver="GeoJSON")
    fit.drop(columns="geometry").to_csv(gj.with_suffix(".csv"), index=False)
    if page:
        build_pose_survey_page(d / "summary.csv", out_dir / f"{name}_pv_pose.html", country=country)
    log.info("%d validated poses of %d analysed -> %s", len(fit), len(s), gj)


if __name__ == "__main__":
    app()
