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
        "orientation (see earthpv.glint). Reward-only (never down-weights); fetched "
        "tile-major (--glint-tile-deg) so --glint-top-n can be set far higher than the "
        "few hundred a per-candidate pull was capped at."
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
    glint_tile_deg: float = typer.Option(
        1.0, help="Spatial bin size (degrees) for batching the glint fetch: one STAC "
        "search + one set of asset opens per bin, shared by every eligible candidate "
        "in it (see docs/issues/glint-tile-batched-coverage.md)"
    ),
    glint_self_referenced: bool = typer.Option(
        False, help="Compare each candidate's surrounding annulus to its OWN history "
        "instead of requiring it to be dim right now — for dense urban blocks where "
        "the annulus is itself lined with similarly-bright rooftops and the default "
        "spatial check never fires (see earthpv.glint.annotate_spikes)"
    ),
) -> None:
    """Threshold, polygonize, join with Overture buildings."""
    from earthpv.postprocess import run_postprocess

    run_postprocess(
        aoi=aoi, pred_dir=pred_dir, threshold=threshold, max_building_dist_m=max_building_dist,
        preboom_prob_dir=preboom_prob_dir, check_glint=check_glint, glint_top_n=glint_top_n,
        glint_skip_top=glint_skip_top, glint_tile_deg=glint_tile_deg,
        glint_self_referenced=glint_self_referenced,
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
    epoch_clean: bool = typer.Option(
        False, help="Veto leads a pre-boom (2021/22) epoch raster confirmed as already "
        "bright (epoch_checked and epoch_prior below --epoch-fp-max-prior). Never-checked "
        "candidates are kept. Needs postprocess --preboom-prob-dir to have run"
    ),
    epoch_fp_max_prior: float = typer.Option(
        0.5, help="With --epoch-clean, drop checked candidates whose epoch_prior "
        "(1 - pre-boom probability) is below this — 0.5 matches the 'likely persistent "
        "FP' judgement shown to MapRoulette mappers"
    ),
    veg_max_ndvi: float = typer.Option(
        None, help="Veto leads whose footprint mean NDVI exceeds this in ANY composite "
        "epoch on disk (green field, not PV). 0.35 measured: catches ~17% of countryside "
        "FP suspects at ~2% cost to confirmed PV. Interim, local-only version of the "
        "annual instrument below"
    ),
    annual_ndvi: Path = typer.Option(
        None, help="annual_ndvi.parquet from scripts/veg_annual_ndvi.py analyze — vetoes "
        "leads whose year-long p95 NDVI exceeds --annual-ndvi-max (a crop cycle; PV "
        "never greens up)"
    ),
    annual_ndvi_max: float = typer.Option(
        0.4, help="With --annual-ndvi, the p95 NDVI veto threshold"
    ),
) -> None:
    """Export candidates as GeoParquet/GeoJSON + MapRoulette challenge.

    Any of the veto flags additionally writes <aoi>_pv_new_leads_clean.geojson (the
    filtered validation queue) and hard_negatives_veg.parquet (vegetation-vetoed
    leads as retraining centers). The default artifacts stay recall-first."""
    from earthpv.export import run_export

    run_export(
        aoi=aoi, pred_dir=pred_dir, exclude_mapped=exclude_mapped,
        min_distance_m=min_distance_m, epoch_clean=epoch_clean,
        epoch_fp_max_prior=epoch_fp_max_prior, veg_max_ndvi=veg_max_ndvi,
        annual_ndvi=annual_ndvi, annual_ndvi_max=annual_ndvi_max,
    )


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
    calibration: Path = typer.Option(
        None,
        help="Candidate-precision table for est_mwp_cal "
        "(default configs/calibration/<aoi>_candidate_precision.yaml if present)",
    ),
    recall_floor: float = typer.Option(
        None,
        help="Clamp per-bin model recall for the Horvitz-Thompson est_mwp_rc "
        "(default capacity_calibration.DEFAULT_RECALL_FLOOR)",
    ),
) -> None:
    """Per-building PV density + 0.1-deg-grid and admin-region aggregates (PyPSA-ready)."""
    from earthpv.density import run_density

    run_density(
        aoi=aoi, pred_dir=pred_dir, threshold=threshold, kwp_per_m2=kwp_per_m2,
        min_prob=min_prob, min_building_exp_m2=min_building_exp_m2, limit=limit,
        districts=districts, regions_file=regions_file, force=force, calibration=calibration,
        recall_floor=recall_floor,
    )


@app.command()
def atlas(
    aoi: str = typer.Option(..., help="AOI name (e.g. pakistan); needs `density` already run"),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    out: Path = typer.Option(None, help="Output HTML (default <pred_dir>/<aoi>/density/<aoi>_pv_atlas.html)"),
) -> None:
    """Regenerate the self-contained HTML capacity atlas from existing density outputs
    (density writes it automatically at the end of every run)."""
    import logging

    from earthpv.atlas import build_atlas

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build_atlas(aoi, Path(pred_dir) / aoi / "density", out=out)


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
def calibrate_candidates(
    aoi: str = typer.Option(..., help="AOI name (e.g. pakistan)"),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    glint_sample: Path = typer.Option(
        None,
        help="Per-bin glint outcomes on unmapped candidates "
        "(scripts/glint_candidate_precision.py analyze); omit for interim mapped-only table",
    ),
    manual_reviews: Path = typer.Option(
        None,
        help="Reviewed calibrate-sample file (CSV/GeoJSON with bin_label + verdict); direct "
        "P(real | unmapped) that takes precedence over glint inversion in its bins",
    ),
    recall_reference: str = typer.Option(
        "snapshot",
        help="Mapped set for per-bin model recall: 'snapshot' = the pre-pipeline rooftopsenti "
        "OSM cache (independent of this pipeline's own OSM contributions), 'all' = every mapped "
        "feature incl. pipeline-validated leads (recall biased up -> smaller correction), "
        "'none' = skip recall (est_mwp_rc degenerates to est_mwp_cal)",
    ),
    min_distance_m: float = typer.Option(100.0, help="Mapped-candidate distance (match export)"),
    out: Path = typer.Option(None, help="Output YAML (default configs/calibration/<aoi>_...)"),
) -> None:
    """Derive the capacity-atlas candidate-precision table (p_real + recall per area bin).

    Combines the mapped-in-OSM fraction with manual review and/or glint inversion on
    the unmapped remainder, measures model recall against a pipeline-independent
    mapped reference restricted to imaged cells, and stores Beta-posterior credible
    intervals for everything. Feeds `density --calibration`; never touches the leads
    product."""
    import logging

    import geopandas as gpd
    import pandas as pd

    from earthpv import capacity_calibration as cc
    from earthpv.config import Settings
    from earthpv.export import _load_mapped_reference
    from earthpv.labels import resolve_aoi

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cands = gpd.read_parquet(Path(pred_dir) / aoi / "candidates.parquet")
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    mapped = _load_mapped_reference(aoi, cfg, settings)
    sample = pd.read_csv(glint_sample) if glint_sample else None
    reviews = _aggregate_manual_reviews(manual_reviews) if manual_reviews else None

    ref = None
    ref_name = "none"
    if recall_reference != "none":
        if recall_reference == "snapshot":
            from earthpv.local_source import load_solar_labels

            source_region = cfg.get("source_region")
            ref = (
                load_solar_labels(Path(settings.raw["local_root"]) / source_region)
                if source_region else None
            )
            ref_name = f"rooftopsenti {source_region} OSM snapshot (pre-pipeline)"
        elif recall_reference == "all":
            ref = mapped
            ref_name = "all mapped features incl. pipeline-validated leads (recall biased up)"
        else:
            raise typer.BadParameter("recall_reference must be snapshot | all | none")
        if ref is None or ref.empty:
            typer.echo(f"recall reference '{recall_reference}' empty — skipping recall")
            ref, ref_name = None, "none"
        else:
            n0 = len(ref)
            ref = cc.coverage_filter(ref, Path(pred_dir) / aoi / "prob")
            typer.echo(f"recall reference: {len(ref)}/{n0} features inside imaged coverage")

    table = cc.derive_table(
        cands, mapped, aoi=aoi, glint_sample=sample, min_distance_m=min_distance_m,
        manual_reviews=reviews, recall_reference=ref, recall_reference_name=ref_name,
    )
    cc.write_table(table, out or cc.default_table_path(aoi))
    for row in table["bins"]:
        rec = "recall=  n/a" if row["recall"] is None else f"recall={row['recall']:.3f}"
        typer.echo(
            f"{row['label']:>8}: n={row['n_candidates']:5d} mapped={row['mapped_frac']:.3f} "
            f"p_u={row['p_unmapped']:.3f} ({row['p_unmapped_source']}) "
            f"p_real={row['p_real']:.3f} [{row['p_real_lo']:.3f},{row['p_real_hi']:.3f}] "
            f"{rec} ({row['recall_source']}, {row['recall_matched']}/{row['recall_n']})"
        )


def _aggregate_manual_reviews(path: Path):
    """Reviewed calibrate-sample file -> per-bin (n, n_real) counts.

    Accepts CSV or anything geopandas reads; needs `bin_label` and `verdict` columns.
    Blank verdicts (unreviewed rows) are skipped; unrecognized ones abort loudly."""
    import geopandas as gpd
    import pandas as pd

    df = pd.read_csv(path) if str(path).endswith(".csv") else gpd.read_file(path)
    verdict = df["verdict"].astype(str).str.strip().str.lower()
    yes = {"yes", "y", "true", "1", "real", "pv"}
    no = {"no", "n", "false", "0", "fp", "not_pv", "nopv"}
    reviewed = df[verdict.isin(yes | no)].assign(real=verdict[verdict.isin(yes | no)].isin(yes))
    bad = df[~verdict.isin(yes | no | {"", "nan", "none"})]
    if len(bad):
        raise typer.BadParameter(
            f"{path}: unrecognized verdicts {sorted(bad['verdict'].astype(str).unique())[:5]} "
            f"(use yes/no)"
        )
    if reviewed.empty:
        raise typer.BadParameter(f"{path}: no reviewed rows (fill the `verdict` column)")
    out = reviewed.groupby("bin_label", as_index=False).agg(
        n=("real", "size"), n_real=("real", "sum")
    )
    typer.echo(f"manual reviews: {out.to_dict('records')}")
    return out


@app.command()
def calibrate_sample(
    aoi: str = typer.Option(..., help="AOI name (e.g. pakistan)"),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    per_bin: int = typer.Option(50, help="Unmapped candidates to sample per bin"),
    bins: str = typer.Option(
        "<100,100-500,500-1k",
        help="Comma-separated bin labels to sample (default: the bins where the glint "
        "instrument has little or no discrimination and only a human verdict works)",
    ),
    min_distance_m: float = typer.Option(100.0, help="Mapped-candidate distance (match export)"),
    seed: int = typer.Option(20260723, help="Sampling seed (keep fixed for resumable review)"),
    out: Path = typer.Option(None, help="Output GeoJSON (default <pred_dir>/<aoi>/calibration_review_sample.geojson)"),
) -> None:
    """Stratified sample of UNMAPPED candidates for manual high-res review.

    Fill the `verdict` property (yes/no) in JOSM/QGIS against current imagery, then
    feed the file back via `earthpv calibrate-candidates --manual-reviews <file>` —
    each bin with >= 20 verdicts gets a directly-measured P(real | unmapped) instead
    of a glint extrapolation. This is the calibration path for the < 1000 m2 bins
    that hold most residential candidates."""
    import logging

    import geopandas as gpd
    import numpy as np
    import pandas as pd

    from earthpv import capacity_calibration as cc
    from earthpv.config import Settings
    from earthpv.export import _load_mapped_reference, new_lead_mask
    from earthpv.labels import resolve_aoi

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cands = gpd.read_parquet(Path(pred_dir) / aoi / "candidates.parquet").reset_index(drop=True)
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    mapped = _load_mapped_reference(aoi, cfg, settings)
    unmapped = cands
    if mapped is not None and not mapped.empty:
        unmapped = cands[new_lead_mask(cands, mapped, min_distance_m=min_distance_m)]

    wanted = [b.strip() for b in bins.split(",") if b.strip()]
    unknown = set(wanted) - set(cc.BIN_LABELS)
    if unknown:
        raise typer.BadParameter(f"unknown bins {sorted(unknown)}; valid: {cc.BIN_LABELS}")
    idx = cc.bin_index(unmapped["area_m2"].to_numpy())
    rng = np.random.default_rng(seed)
    parts = []
    for label in wanted:
        pool = unmapped[idx == cc.BIN_LABELS.index(label)]
        take = pool.sample(n=min(per_bin, len(pool)), random_state=rng.integers(2**32))
        typer.echo(f"{label:>8}: sampled {len(take)}/{len(pool)} unmapped candidates")
        parts.append(take.assign(bin_label=label))
    sample = gpd.GeoDataFrame(pd.concat(parts), crs=cands.crs).reset_index(drop=True)
    reps = sample.geometry.representative_point()
    sample["sample_uid"] = [f"{aoi}_cal_{i:04d}" for i in range(len(sample))]
    sample["lon"], sample["lat"] = reps.x.round(6), reps.y.round(6)
    sample["verdict"] = ""
    cols = ["sample_uid", "bin_label", "area_m2", "lon", "lat", "verdict", "geometry"]
    out = out or Path(pred_dir) / aoi / "calibration_review_sample.geojson"
    sample[cols].to_file(out, driver="GeoJSON")
    typer.echo(
        f"wrote {out} ({len(sample)} candidates) — review `verdict` (yes/no) against "
        f"high-res imagery, then run:\n  earthpv calibrate-candidates --aoi {aoi} "
        f"--manual-reviews {out}"
    )


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
