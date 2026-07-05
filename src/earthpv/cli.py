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


@app.command()
def chips(
    aoi: str = typer.Option(..., help="AOI name"),
    labels_dir: Path = typer.Option(Path("data/labels")),
    out_dir: Path = typer.Option(Path("data/chips")),
    limit: int = typer.Option(0, help="Cap number of chips (0 = no cap, use for smoke tests)"),
    seasonal: bool = typer.Option(False, help="Also write 4-season 48-band chips (disk-heavy)"),
) -> None:
    """Sample training chips: download S2 composites and burn PV label masks."""
    from earthpv.chips import build_chips

    build_chips(aoi=aoi, labels_dir=labels_dir, out_dir=out_dir, limit=limit, seasonal=seasonal)


@app.command()
def compose(
    aoi: str = typer.Option(..., help="AOI name (e.g. punjab)"),
    out_dir: Path = typer.Option(Path("data/composites")),
    min_buildings: int = typer.Option(1000, help="Composite cells with >= this many buildings"),
    limit: int = typer.Option(0, help="Cap number of cells (0 = all)"),
) -> None:
    """Build S2 composites for building-populated cells of an AOI (STAC, resumable)."""
    from earthpv.compose import run_compose

    run_compose(aoi=aoi, out_dir=out_dir, min_buildings=min_buildings, limit=limit)


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
) -> None:
    """Report pixel IoU/F1 and per-installation recall by array size."""
    from earthpv.evaluate import evaluate as _eval

    _eval(aoi=aoi, checkpoint=checkpoint, chips_dir=chips_dir, threshold=threshold)


@app.command()
def infer(
    aoi: str = typer.Option(..., help="AOI name (e.g. punjab)"),
    checkpoint: Path = typer.Option(..., help="Trained model checkpoint"),
    out_dir: Path = typer.Option(Path("data/predictions")),
    only_built: bool = typer.Option(True, help="Skip chips without buildings >= min roof area"),
    limit: int = typer.Option(0, help="Cap number of chips (0 = all)"),
) -> None:
    """Tiled inference over an AOI, writing probability GeoTIFFs."""
    from earthpv.infer import run_inference

    run_inference(
        aoi=aoi, checkpoint=checkpoint, out_dir=out_dir, only_built=only_built, limit=limit
    )


@app.command()
def postprocess(
    aoi: str = typer.Option(...),
    pred_dir: Path = typer.Option(Path("data/predictions")),
    threshold: float = typer.Option(0.3, help="Probability threshold (recall-oriented)"),
) -> None:
    """Threshold, polygonize, join with Overture buildings."""
    from earthpv.postprocess import run_postprocess

    run_postprocess(aoi=aoi, pred_dir=pred_dir, threshold=threshold)


@app.command()
def export(
    aoi: str = typer.Option(...),
    pred_dir: Path = typer.Option(Path("data/predictions")),
) -> None:
    """Export candidates as GeoParquet/GeoJSON + MapRoulette challenge."""
    from earthpv.export import run_export

    run_export(aoi=aoi, pred_dir=pred_dir)


if __name__ == "__main__":
    app()
