"""Custom losses for TerraTorch tasks not covered by built-in strings."""

from __future__ import annotations

import torch
from torch import nn


class TargetWeightedMSE(nn.Module):
    """MSE weighted by (1 + k*target), to counter zero-inflation in PV-fraction regression.

    Most pixels have zero PV coverage; without weighting the loss is dominated by getting
    zeros exactly right and the model can collapse to predict-zero. Weighting by the target
    itself (not a fixed class balance) keeps the gradient scaled to how much signal a pixel
    actually carries, without needing a separate positive/negative split.

    PixelwiseRegressionTask uses an nn.Module loss unwrapped (no ignore_index wrapper is
    applied, unlike its built-in string losses), so this module must mask ignore_index itself.
    """

    def __init__(self, k: float = 10.0, ignore_index: float = -1.0):
        super().__init__()
        self.k = k
        self.ignore_index = ignore_index

    def forward(self, output: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        if output.ndim == target.ndim + 1:
            output = output.squeeze(1)
        valid = (target != self.ignore_index).float()
        weight = (1.0 + self.k * target.clamp(min=0)) * valid
        se = (output - target) ** 2 * weight
        return se.sum() / weight.sum().clamp(min=1.0)
