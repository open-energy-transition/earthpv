"""THOR (ESA Phi-lab / NR, Apache-2.0) as a TerraTorch backbone for PV segmentation.

THOR accepts any patch size at inference, which TerraMind's fixed 16 px patch embedding
cannot: at 10 m a 16 px token is 160 m across and a 400 m2 array is 1/64 of it. This module
exists to test whether a finer token grid recovers the compact rooftop arrays the current
segmentation misses (see the backbone-comparison entry in docs/experiments.md).

Three things the upstream plugin (`thor_terratorch_ext`) does not do and this wrapper does:

* **Input standardisation.** THOR's wrapper only resamples; it does not normalise. Our chips
  and inference windows arrive as reflectance (DN / 10000, `datamodule.DN_SCALE`), so the
  per-band mean/std measured on the training corpus are applied inside the model. That keeps
  `datamodule`, `infer` and `evaluate` unchanged, and the statistics travel with the checkpoint.
* **Pascal (sm_61) support.** THOR wraps its ALiBi builder in `torch.compile`, which needs
  Triton, and Triton refuses compute capability < 7.0, so compilation is disabled on such a
  GPU. And PyTorch's default SDPA kernel there (memory-efficient) is ~15x slower in fp16 than
  the plain math kernel (measured on the GTX 1060: 269 against 18 ms per layer, 980 tokens),
  so `train` and `infer.load_model` select the math kernel for it (`earthpv.attention`).
  Disabling compilation applies only when a THOR backbone is in use.
* **Import from a checkout.** THOR pins `terratorch==1.2.5` (we run 1.2.8), so it is not a
  pixi dependency. The two repositories are read from `EARTHPV_THOR_PATHS` (os.pathsep-separated)
  or from `third_party/THOR` and `third_party/thor_terratorch_ext` next to the repo root.

Importing `thor` patches timm's Attention/Block forward to accept an ALiBi bias. With no bias
the patched forward is ordinary attention, and TerraMind does not use timm's blocks.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
_DEFAULT_PATHS = [REPO / "third_party" / "THOR", REPO / "third_party" / "thor_terratorch_ext"]


def _ensure_importable() -> None:
    raw = os.environ.get("EARTHPV_THOR_PATHS")
    paths = [Path(p) for p in raw.split(os.pathsep)] if raw else _DEFAULT_PATHS
    for p in reversed(paths):
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))


def _configure_for_device() -> None:
    import torch

    if not torch.cuda.is_available():
        return
    if torch.cuda.get_device_capability() < (7, 0):
        import torch._dynamo

        torch._dynamo.config.disable = True
        log.info("THOR on a pre-Volta GPU: torch.compile disabled")


def register() -> None:
    """Import THOR, register `earthpv_thor` in TerraTorch's backbone registry. Idempotent."""
    if getattr(register, "_done", False):
        return
    _ensure_importable()
    _configure_for_device()

    import torch
    from terratorch.registry import TERRATORCH_BACKBONE_REGISTRY
    from torch import nn

    import thor_terratorch_ext  # noqa: F401  (registers thor_v1_* and patches timm)
    from thor_terratorch_ext.models.backbones.thor_vit import load_thor_model

    class _StandardizedTHOR(nn.Module):
        """(x - mean) / std per band, then the THOR encoder wrapper."""

        def __init__(self, encoder: nn.Module, mean: list[float], std: list[float]):
            super().__init__()
            self.encoder = encoder
            self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32).view(1, -1, 1, 1))
            self.register_buffer("std", torch.tensor(std, dtype=torch.float32).view(1, -1, 1, 1))

        @property
        def out_channels(self):
            return self.encoder.out_channels

        def forward(self, x, **kwargs):
            return self.encoder((x - self.mean) / self.std, **kwargs)

    def earthpv_thor(
        pretrained: bool = True,
        variant: str = "thor_v1_tiny",
        model_bands: list[str] | None = None,
        band_mean: list[float] | None = None,
        band_std: list[float] | None = None,
        **kwargs,
    ):
        if model_bands is None or band_mean is None or band_std is None:
            raise ValueError("earthpv_thor needs model_bands, band_mean and band_std")
        if not (len(model_bands) == len(band_mean) == len(band_std)):
            raise ValueError("model_bands, band_mean and band_std must have equal length")
        encoder = load_thor_model(variant, model_bands=model_bands, pretrained=pretrained, **kwargs)
        return _StandardizedTHOR(encoder, band_mean, band_std)

    TERRATORCH_BACKBONE_REGISTRY.register(earthpv_thor)
    register._done = True


def uses_thor(model_args: dict) -> bool:
    return "thor" in str(model_args.get("backbone", ""))
