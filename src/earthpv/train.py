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
    task_args = dict(cfg["task"])
    task_type = cfg.get("task_type", "segmentation")
    if task_type == "regression":
        from terratorch.tasks import PixelwiseRegressionTask

        if task_args.get("loss") == "weighted_mse":
            # Counters the zero-inflation of a fraction target; see earthpv.losses. Like
            # the tversky branch below, PixelwiseRegressionTask accepts a loss nn.Module.
            from earthpv.losses import TargetWeightedMSE

            wa = task_args.pop("weighted_mse_args", None) or {}
            task_args["loss"] = TargetWeightedMSE(
                k=wa.get("k", 10.0), ignore_index=task_args.get("ignore_index", -1)
            )
        task = PixelwiseRegressionTask(**task_args)
    else:
        if task_args.get("loss") == "tversky":
            # TerraTorch has no built-in Tversky loss, but SemanticSegmentationTask accepts a
            # loss nn.Module. Tversky with beta>alpha penalises false negatives (missed PV)
            # harder than false positives -> recall-first. With a module loss the task's
            # class_weights is inactive (alpha/beta do the class weighting), so drop it.
            import segmentation_models_pytorch as smp

            ta = task_args.pop("tversky_args", None) or {}
            task_args.pop("class_weights", None)
            task_args["loss"] = smp.losses.TverskyLoss(
                mode="multiclass",
                ignore_index=task_args.get("ignore_index", -1),
                alpha=ta.get("alpha", 0.3),
                beta=ta.get("beta", 0.7),
                gamma=ta.get("gamma", 1.0),
            )
        task = SemanticSegmentationTask(**task_args)

    ckpt_dir = Path(cfg.get("checkpoint_dir", "data/models"))
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    # Recall-first: monitor balanced (macro) recall = val/Accuracy (MulticlassAccuracy
    # macro is mean per-class recall) instead of mIoU. Overridable via config.
    monitor = cfg.get("monitor", "val/mIoU")
    mode = cfg.get("monitor_mode", "max")
    callbacks = [
        # Metric keys contain '/', which Lightning can't substitute into a filename
        # template, so keep the filename on epoch/step only.
        ModelCheckpoint(
            dirpath=ckpt_dir, filename="terramind-pv-{epoch:02d}-{step}",
            monitor=monitor, save_top_k=2, mode=mode, save_last=True,
        ),
        EarlyStopping(monitor=monitor, patience=cfg.get("patience", 8), mode=mode),
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
