"""Which scaled-dot-product-attention kernel the ViT backbones run on.

On a pre-Volta GPU (compute capability < 7.0, i.e. this project's GTX 1060) PyTorch's
default SDPA choice is the memory-efficient kernel, and in fp16 it is far slower there than
the plain math kernel. Flash attention does not exist on Pascal at all. Measured on the
GTX 1060 (2026-10-24):

* **training** TerraMind-Tiny: 97 against 275 ms per batch of 8; a 50-step smoke run 17
  against 36 s. Worth having, so training uses the math kernel there by default.
* **inference** TerraMind-Tiny, one window at a time: 25 against 29 ms per window, 17%.
  Not worth what it costs: the kernels agree to rounding, not bit for bit, so a cell's
  probability raster differs from the published one in ~0.03% of pixels by 1-2 uint8
  levels (7 of 51,120 detected pixels crossed 0.3 on six South African cells). Inference
  therefore keeps PyTorch's kernel, and every published raster stays reproducible byte for
  byte. THOR is the exception: at 8 px tokens the default kernel is 15x slower, and its
  results were all produced on the math kernel.

Newer GPUs keep PyTorch's own choice everywhere, which is the fast one there.
`EARTHPV_SDPA` overrides the choice for every caller:

* ``auto`` (default): as above;
* ``default``: always PyTorch's choice, which reproduces training as it ran before
  2026-10-24;
* ``math``: the math kernel always, e.g. for a fresh country's inference where nothing has
  been published yet.

The flags are process-global, so call `configure()` before the first forward pass. The
last call wins, which is what lets one process evaluate TerraMind and THOR in turn.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

MODES = ("auto", "default", "math")


def configure(prefer_math: bool) -> str:
    """Set the SDPA backends for this process; returns the kernel in use ("math" or
    "default"). `prefer_math` is the caller's `auto` choice on a pre-Volta GPU: True for
    training and for THOR, False for TerraMind inference."""
    import torch

    mode = os.environ.get("EARTHPV_SDPA", "auto").strip().lower() or "auto"
    if mode not in MODES:
        raise ValueError(f"EARTHPV_SDPA={mode!r}; expected one of {MODES}")
    if not torch.cuda.is_available():
        return "default"
    pre_volta = torch.cuda.get_device_capability() < (7, 0)
    use_math = mode == "math" or (mode == "auto" and pre_volta and prefer_math)
    torch.backends.cuda.enable_mem_efficient_sdp(not use_math)
    torch.backends.cuda.enable_flash_sdp(not use_math)
    kernel = "math" if use_math else "default"
    if getattr(configure, "_logged", None) != kernel:
        log.info("SDPA kernel: %s (EARTHPV_SDPA=%s, %s)", kernel, mode,
                 torch.cuda.get_device_name())
        configure._logged = kernel
    return kernel
