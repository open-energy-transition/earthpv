"""Fine-tune TerraMind for PV segmentation via TerraTorch's SemanticSegmentationTask."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


def run_training(config: Path, smoke: bool = False) -> Path:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import torch
    from lightning import Trainer
    from lightning.pytorch.callbacks import EarlyStopping, ModelCheckpoint
    from terratorch.tasks import SemanticSegmentationTask

    from earthpv.datamodule import PVDataModule

    cfg = yaml.safe_load(Path(config).read_text())
    torch.set_float32_matmul_precision("medium")

    dm = PVDataModule(**cfg["data"])
    task = SemanticSegmentationTask(**cfg["task"])

    ckpt_dir = Path(cfg.get("checkpoint_dir", "data/models"))
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    callbacks = [
        # Metric keys contain '/', which Lightning can't substitute into a filename
        # template, so keep the filename on epoch/step only.
        ModelCheckpoint(
            dirpath=ckpt_dir, filename="terramind-pv-{epoch:02d}-{step}",
            monitor="val/mIoU", save_top_k=2, mode="max", save_last=True,
        ),
        EarlyStopping(monitor="val/mIoU", patience=cfg.get("patience", 8), mode="max"),
    ]
    trainer_kwargs = dict(cfg.get("trainer", {}))
    if smoke:
        trainer_kwargs.update(max_steps=50, val_check_interval=25, limit_val_batches=4,
                              max_epochs=None)
    trainer = Trainer(
        accelerator="gpu" if torch.cuda.is_available() else "cpu",
        precision="16-mixed",
        callbacks=callbacks,
        log_every_n_steps=5,
        default_root_dir="logs",
        **trainer_kwargs,
    )
    trainer.fit(task, datamodule=dm)
    best = callbacks[0].best_model_path or str(ckpt_dir / "last.ckpt")
    log.info("Best checkpoint: %s", best)
    return Path(best)
