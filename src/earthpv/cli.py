"""Typer CLI exposing the pipeline stages: labels, chips, train, infer, postprocess, export."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.command()
def labels(
    aoi: str = typer.Option(..., help="AOI name from configs/aoi.yaml (e.g. germany, freiburg)"),
    out_dir: Path = typer.Option(Path("data/labels"), help="Output directory"),
) -> None:
    """Extract Overture buildings + OSM solar labels for an AOI."""
    from earthpv.labels import build_labels

    build_labels(aoi=aoi, out_dir=out_dir)


@app.command("overpass-labels")
def overpass_labels(
    place: str = typer.Option(
        None, help="OSM area name to query directly, e.g. 'Lahore' (Overpass area[name=...] match)"
    ),
    bbox: str = typer.Option(
        None, help="Explicit 'minlon,minlat,maxlon,maxlat' bbox, alternative to --place"
    ),
    out_dir: Path = typer.Option(Path("data/labels")),
    name: str = typer.Option(None, help="Output file stem (default: slugified --place)"),
    timeout: int = typer.Option(180, help="Overpass query timeout (seconds)"),
    iso3: str = typer.Option(
        None, help="Use the local VIDA building parquet (data/vida/<ISO3>.parquet) for "
        "placement classification instead of Overture's remote S3 (which times out "
        "from this machine) — needed for countries without a rooftopsenti cache"
    ),
) -> None:
    """Fetch fresh OSM solar-PV mappings directly via Overpass (bypasses Overture's
    periodic-snapshot lag — use for a region that was just hand-mapped)."""
    from earthpv.overpass import build_overpass_labels

    parsed_bbox = tuple(float(x) for x in bbox.split(",")) if bbox else None
    build_overpass_labels(
        out_dir=out_dir, bbox=parsed_bbox, place=place, name=name, timeout=timeout,
        iso3=iso3,
    )


@app.command()
def chips(
    aoi: str = typer.Option(..., help="AOI name"),
    labels_dir: Path = typer.Option(Path("data/labels")),
    out_dir: Path = typer.Option(Path("data/chips")),
    limit: int = typer.Option(0, help="Cap number of chips (0 = no cap, use for smoke tests)"),
    seasonal: bool = typer.Option(False, help="Also write 4-season 48-band chips (disk-heavy)"),
    fraction: bool = typer.Option(
        False, help="Burn continuous PV-coverage-fraction masks (regression target) "
        "instead of binary class masks; writes to a parallel <aoi>_fraction/ tree"
    ),
    max_positives: int = typer.Option(
        0, help="Cap positive-chip count before near-negative/background mixing (0 = no cap; "
        "fraction mode with small arrays included can seed tens of thousands)"
    ),
    region_filter: Path = typer.Option(
        None, help="Parquet of polygons (e.g. calibrate's well_mapped.parquet) restricting all "
        "chip centres to well-OSM-mapped areas"
    ),
) -> None:
    """Sample training chips: download S2 composites and burn PV label masks."""
    from earthpv.chips import build_chips

    build_chips(
        aoi=aoi, labels_dir=labels_dir, out_dir=out_dir, limit=limit, seasonal=seasonal,
        fraction=fraction, max_positives=max_positives, region_filter=region_filter,
    )


@app.command()
def compose(
    aoi: str = typer.Option(..., help="AOI name (e.g. punjab)"),
    out_dir: Path = typer.Option(Path("data/composites")),
    min_buildings: int = typer.Option(1000, help="Composite cells with >= this many buildings"),
    limit: int = typer.Option(0, help="Cap number of cells (0 = all)"),
    window: str = typer.Option("", help="Date range 'YYYY-MM-DD:YYYY-MM-DD' (default: dry season)"),
    index: int = typer.Option(0, help="Layer index; >0 writes composite_<i>.tif on the base grid"),
    workers: int = typer.Option(1, help="Concurrent cells (I/O-bound; 4-6 is a good range)"),
    label_cells: bool = typer.Option(
        True, "--label-cells/--no-label-cells",
        help="Also composite cells containing OSM solar labels (in-domain training positives)",
    ),
    use_vida: bool = typer.Option(
        False, help="Force VIDA Open Buildings for cell selection even if the AOI has a "
        "source_region — the local Overture-only set (>=500 m2) undercounts small/unmapped "
        "buildings by orders of magnitude in some regions"
    ),
) -> None:
    """Build S2 composites for building-populated cells of an AOI (STAC, resumable)."""
    from earthpv.compose import run_compose

    win = tuple(window.split(":")) if window else None
    run_compose(aoi=aoi, out_dir=out_dir, min_buildings=min_buildings, limit=limit,
                window=win, index=index, workers=workers, include_labels=label_cells,
                use_vida=use_vida)


@app.command()
def train(
    config: Path = typer.Option(Path("configs/terramind_pv.yaml")),
    smoke: bool = typer.Option(False, help="50-step smoke run"),
) -> None:
    """Fine-tune TerraMind for PV segmentation via TerraTorch."""
    from earthpv.train import run_training

    run_training(config=config, smoke=smoke)


@app.command()
def evaluate(
    aoi: str = typer.Option("germany", help="AOI with a val split"),
    checkpoint: Path = typer.Option(..., help="Trained model checkpoint"),
    chips_dir: Path = typer.Option(Path("data/chips")),
    threshold: float = typer.Option(0.3),
    task_type: str = typer.Option("auto", help="auto|segmentation|regression"),
    chips_name: str = typer.Option(
        None, help="Chip subdir under chips_dir if not <aoi> (e.g. germany_fraction)"
    ),
) -> None:
    """Report pixel IoU/F1 and per-installation recall by array size."""
    from earthpv.evaluate import evaluate as _eval

    _eval(
        aoi=aoi, checkpoint=checkpoint, chips_dir=chips_dir, threshold=threshold,
        task_type=task_type, chips_name=chips_name,
    )


@app.command()
def infer(
    aoi: str = typer.Option(..., help="AOI name (e.g. punjab)"),
    checkpoint: Path = typer.Option(..., help="Trained model checkpoint"),
    out_dir: Path = typer.Option(Path("data/predictions")),
    only_built: bool = typer.Option(True, help="Skip chips without buildings >= min roof area"),
    limit: int = typer.Option(0, help="Cap number of chips (0 = all)"),
    task_type: str = typer.Option("auto", help="auto|segmentation|regression"),
    tiles: str = typer.Option(
        "", help="Comma-separated cell/tile names to restrict inference to (0 = all cells)"
    ),
    index: int = typer.Option(
        0, help="Composite layer to run inference on (e.g. 1 for a pre-boom/contrast epoch "
        "built by `compose --index 1`); use a distinct --out-dir per layer"
    ),
) -> None:
    """Tiled inference over an AOI, writing probability GeoTIFFs."""
    from earthpv.infer import run_inference

    run_inference(
        aoi=aoi, checkpoint=checkpoint, out_dir=out_dir, only_built=only_built, limit=limit,
        task_type=task_type, tiles=[t.strip() for t in tiles.split(",") if t.strip()] or None,
        index=index,
    )


@app.command()
def postprocess(
    aoi: str = typer.Option(...),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    threshold: float = typer.Option(0.3, help="Probability threshold (recall-oriented)"),
    max_building_dist: float = typer.Option(
        0.0, help="Drop candidates farther than this from the nearest building, in metres "
        "(0 = disabled; only applies where a real distance was resolved)"
    ),
    preboom_prob_dir: Path = typer.Option(
        None, help="Probability rasters from a pre-boom/contrast epoch (e.g. "
        "data/predictions_preboom/<aoi>/prob) — candidates already bright there get "
        "down-weighted in rank_score as likely persistent false positives, not dropped"
    ),
    check_glint: bool = typer.Option(
        False, help="Physics-based corroborator: pull each top candidate's Sentinel-2 "
        "time series and check for solar-glint spikes consistent with one fixed panel "
        "orientation (see earthpv.glint). Reward-only (never down-weights); network-bound "
        "so only applied to the top --glint-top-n candidates by rank_score."
    ),
    glint_top_n: int = typer.Option(
        300, help="How many eligible candidates to run the glint check on (matches "
        "--check-glint; ignored otherwise)"
    ),
    glint_skip_top: int = typer.Option(
        100, help="Skip the this-many highest-ranked candidates before spending the "
        "glint budget — they reach human validation regardless, so the check adds "
        "nothing there; 0 restores the old check-from-the-top behavior"
    ),
) -> None:
    """Threshold, polygonize, join with Overture buildings."""
    from earthpv.postprocess import run_postprocess

    run_postprocess(
        aoi=aoi, pred_dir=pred_dir, threshold=threshold, max_building_dist_m=max_building_dist,
        preboom_prob_dir=preboom_prob_dir, check_glint=check_glint, glint_top_n=glint_top_n,
        glint_skip_top=glint_skip_top,
    )


@app.command()
def export(
    aoi: str = typer.Option(...),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    exclude_mapped: bool = typer.Option(
        False, help="Also write <aoi>_pv_new_leads.geojson: candidates that don't "
        "intersect any already-mapped OSM solar polygon (cached source_region + any "
        "data/labels/*_overpass_solar.parquet)"
    ),
    min_distance_m: float = typer.Option(
        0.0, help="With --exclude-mapped, drop candidates within this many metres of "
        "an already-mapped OSM solar feature, not just ones that literally overlap it "
        "— catches candidates offset from a mapped point (a common generator:source=solar "
        "node) that would otherwise never 'intersect' and wrongly surface as new"
    ),
) -> None:
    """Export candidates as GeoParquet/GeoJSON + MapRoulette challenge."""
    from earthpv.export import run_export

    run_export(aoi=aoi, pred_dir=pred_dir, exclude_mapped=exclude_mapped, min_distance_m=min_distance_m)


@app.command("hard-negatives")
def hard_negatives(
    aoi: str = typer.Option(..., help="AOI name (e.g. pakistan)"),
    checkpoint: Path = typer.Option(..., help="Trained model checkpoint used for the bi-temporal check"),
    compare_year: str = typer.Option("2022", help="Older year to confirm PV absence against"),
    window: str = typer.Option(
        "", help="Older-year date range 'YYYY-MM-DD:YYYY-MM-DD' (default: all of --compare-year)"
    ),
    composites_dir: Path = typer.Option(Path("data/composites")),
    out_dir: Path = typer.Option(Path("data/predictions")),
    min_area: float = typer.Option(400.0, help="Minimum building area (m2) to be a candidate"),
    limit: int = typer.Option(300, help="Cap number of candidate buildings"),
    neg_threshold: float = typer.Option(
        0.1, help="Predicted-probability ceiling for 'the model sees nothing here'"
    ),
    workers: int = typer.Option(4, help="Concurrent cells for the older-year composite build (I/O-bound)"),
) -> None:
    """Mine hard negatives: large buildings with no OSM solar match, confirmed by
    checking the model sees no PV signal in EITHER the current composite or an older
    year's -- screens out buildings that likely got an unmapped recent installation."""
    from earthpv.hard_negatives import run_hard_negatives

    win = tuple(window.split(":")) if window else None
    run_hard_negatives(
        aoi=aoi, checkpoint=checkpoint, compare_year=compare_year, window=win,
        composites_dir=composites_dir, out_dir=out_dir, min_area_m2=min_area, limit=limit,
        neg_prob_threshold=neg_threshold, workers=workers,
    )


@app.command("hard-negative-chips")
def hard_negative_chips(
    aoi: str = typer.Option(..., help="AOI name (e.g. pakistan)"),
    centers: Path = typer.Option(
        None, help="hard_negatives_confirmed.parquet (default: data/predictions/<aoi>/...)"
    ),
    labels_dir: Path = typer.Option(Path("data/labels")),
    out_dir: Path = typer.Option(Path("data/chips")),
) -> None:
    """Cut real training chips at hard-negatives' confirmed centers, into `<aoi>_hard_neg/`
    (add it to `scripts/merge_chip_index.py`'s AOI list to include it in training)."""
    from earthpv.chips import build_hard_negative_chips

    centers = centers or Path("data/predictions") / aoi / "hard_negatives_confirmed.parquet"
    build_hard_negative_chips(aoi=aoi, centers_path=centers, labels_dir=labels_dir, out_dir=out_dir)


@app.command()
def density(
    aoi: str = typer.Option(..., help="AOI name (e.g. pakistan)"),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    threshold: float = typer.Option(0.3, help="Matches the postprocess threshold (metadata only)"),
    kwp_per_m2: float = typer.Option(0.18, help="kWp per m2 of detected panel area (~5.5 m2/kWp)"),
    min_prob: float = typer.Option(0.05, help="Pixel-probability noise floor for expected-area sums"),
    min_building_exp_m2: float = typer.Option(10.0, help="Keep a building row if expected PV >= this"),
    limit: int = typer.Option(0, help="Cap number of cells (0 = all; use for smoke tests)"),
    districts: bool = typer.Option(False, help="Also aggregate to Overture county (district) level"),
    regions_file: Path = typer.Option(None, help="Local region polygons (skip Overture S3)"),
    force: bool = typer.Option(False, help="Recompute cells even if partials exist"),
) -> None:
    """Per-building PV density + 0.1-deg-grid and admin-region aggregates (PyPSA-ready)."""
    from earthpv.density import run_density

    run_density(
        aoi=aoi, pred_dir=pred_dir, threshold=threshold, kwp_per_m2=kwp_per_m2,
        min_prob=min_prob, min_building_exp_m2=min_building_exp_m2, limit=limit,
        districts=districts, regions_file=regions_file, force=force,
    )


@app.command()
def pv_yield(
    aoi: str = typer.Option(..., help="AOI name (e.g. pakistan); needs `density` already run"),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    kwp_per_m2: float = typer.Option(
        None, help="Override density's assumed kWp/m2 (default: reuse density.py's constant)"
    ),
) -> None:
    """pvlib double-check: CEC module-database sanity check + PVGIS-modelled annual
    yield per region, converting est_mwp to expected GWh/yr for cross-checking against
    known generation figures (NEPRA net-metering, TransitionZero)."""
    from earthpv.pv_capacity import run_pv_capacity_check

    run_pv_capacity_check(aoi=aoi, pred_dir=pred_dir, kwp_per_m2=kwp_per_m2)


@app.command()
def mastr(
    out_dir: Path = typer.Option(Path("data/calibration")),
    cutoff: str = typer.Option("2025-09-30", help="Keep units commissioned on/before this date"),
    refresh: bool = typer.Option(False, help="Re-download even if a local extract exists"),
) -> None:
    """Download MaStR (open-mastr) and aggregate rooftop/ground PV capacity per Gemeinde."""
    from earthpv.mastr import run_mastr

    run_mastr(out_dir=out_dir, cutoff=cutoff, refresh=refresh)


@app.command()
def calibrate(
    aoi: str = typer.Option("germany", help="German AOI (calibration is DE-only for now)"),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    mastr_path: Path = typer.Option(Path("data/calibration/mastr_gemeinden.parquet")),
    min_prob: float = typer.Option(0.05, help="Pixel noise floor (use ~0.02 for fraction rasters)"),
    kwp_per_m2: float = typer.Option(0.18, help="kWp per m2 of panel area (~5.5 m2/kWp)"),
    completeness_threshold: float = typer.Option(0.6, help="OSM/MaStR ratio to call a Gemeinde well-mapped"),
    min_mastr_kw: float = typer.Option(50.0, help="Minimum MaStR rooftop kW to consider a Gemeinde"),
    limit: int = typer.Option(0, help="Cap number of Gemeinden processed (0 = all; smoke tests)"),
    out_dir: Path = typer.Option(Path("data/calibration")),
) -> None:
    """Zonal-join prob rasters to Gemeinden and calibrate/validate against MaStR."""
    from earthpv.calibrate import run_calibrate

    run_calibrate(
        aoi=aoi, pred_dir=pred_dir, mastr_path=mastr_path, min_prob=min_prob,
        kwp_per_m2=kwp_per_m2, completeness_threshold=completeness_threshold,
        min_mastr_kw=min_mastr_kw, limit=limit, out_dir=out_dir,
    )


if __name__ == "__main__":
    app()
