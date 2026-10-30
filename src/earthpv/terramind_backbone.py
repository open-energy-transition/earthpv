"""TerraMind with its own pretraining standardisation applied inside the model.

TerraMind was pretrained on Sentinel-2 L2A standardised per band with fixed statistics
(TerraTorch's `v1_pretraining_mean` / `v1_pretraining_std`), but TerraTorch's TerraMind ViT
backbones (`terramind_v1_tiny` etc.) do not apply them; only its generation and TiM builders
take them. Every earthpv segmentation checkpoint up to v20 therefore saw reflectance (DN /
10000, `datamodule.DN_SCALE`), each band's spread 5-8x narrower than in pretraining.

A frozen-feature probe on v14's corpus (2026-10-30; logistic regression on the four layers the
neck selects, per 16 px token, scored on the val holdouts) measured what that costs the
pretrained encoder before fine-tuning: held-out token average precision 0.469 on DN / 10000,
0.737 standardised with TerraMind's statistics, 0.452 with the corpus's own statistics (what
`thor_backbone` applies), 0.696 with the 1,000 DN BOA offset removed first. Randomly
initialised weights barely move (0.231 against 0.259). Fine-tuning recovers it: v21
(`configs/terramind_pv_v21_tmnorm_south_africa.yaml`, v14's recipe with this backbone) ties
v14 on rooftop recall at matched precision and is slightly behind on ground, so it was not
adopted (docs/experiments.md, "Feeding TerraMind the input it was pretrained on"). It converges
in half the epochs; a lower encoder learning rate is untested.

`earthpv_terramind` wraps a `terramind_v1_*` backbone with those statistics as buffers, in the
units the model receives, so `datamodule`, `infer` and `evaluate` are unchanged, the
statistics travel with the checkpoint, and every existing checkpoint (plain `terramind_v1_*`)
loads and predicts exactly as before. Raw DN is standardised as is, offset included.
"""

from __future__ import annotations

BACKBONE = "earthpv_terramind"
_STATS_KEY = "untok_sen2l2a@224"  # TerraMind's raw S2L2A modality, which `S2L2A` resolves to


def uses_standardized_terramind(model_args: dict) -> bool:
    return model_args.get("backbone") == BACKBONE


def pretraining_stats(bands: list[str]) -> tuple[list[float], list[float]]:
    """TerraMind v1's S2L2A pretraining mean/std for `bands` (TerraMind band names, e.g.
    `config.MODEL_BANDS`), in the units the model receives (DN / DN_SCALE)."""
    from terratorch.models.backbones.terramind.model.terramind_register import (
        PRETRAINED_BANDS,
        v1_pretraining_mean,
        v1_pretraining_std,
    )

    from earthpv.datamodule import DN_SCALE

    order = PRETRAINED_BANDS[_STATS_KEY]
    idx = [order.index(b) for b in bands]
    mean = [v1_pretraining_mean[_STATS_KEY][i] / DN_SCALE for i in idx]
    std = [v1_pretraining_std[_STATS_KEY][i] / DN_SCALE for i in idx]
    return mean, std


def register() -> None:
    """Register `earthpv_terramind` in TerraTorch's backbone registry. Idempotent."""
    if getattr(register, "_done", False):
        return

    import torch
    from terratorch.registry import BACKBONE_REGISTRY, TERRATORCH_BACKBONE_REGISTRY
    from torch import nn

    class _StandardizedTerraMind(nn.Module):
        """(x - mean) / std per band, then the TerraMind encoder."""

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

    def earthpv_terramind(
        pretrained: bool = True,
        variant: str = "terramind_v1_tiny",
        modalities: list[str] | None = None,
        bands: dict[str, list[str]] | None = None,
        **kwargs,
    ):
        if list(modalities or []) != ["S2L2A"] or not bands or list(bands) != ["S2L2A"]:
            raise ValueError("earthpv_terramind takes one modality, S2L2A, with explicit bands")
        encoder = BACKBONE_REGISTRY.build(variant, pretrained=pretrained, modalities=modalities,
                                          bands=bands, **kwargs)
        return _StandardizedTerraMind(encoder, *pretraining_stats(bands["S2L2A"]))

    TERRATORCH_BACKBONE_REGISTRY.register(earthpv_terramind)
    register._done = True
