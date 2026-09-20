"""Super-resolve the quadrat composites 10 m -> 2.5 m with SEN2SR, for measurement.

ESAOpenSR's SEN2SRLite (CC0-1.0) takes exactly this project's ten bands in this order and
upsamples 4x. This runs it over each calibration quadrat's composite window and writes a
2.5 m raster, so `roofclf` can be refitted on it and the difference measured.

**This is SINGLE-IMAGE super-resolution, i.e. the super-resolve-then-classify pipeline that
this register already rejected once (2026-07) and that Google's Open Buildings 2.5D Temporal
explicitly avoids in favour of fusing frames inside the task model.** It is worth
re-measuring anyway because SEN2SR is a far better model than the three variants tried then,
and because the earlier objection -- hallucination risk on a detection task -- is exactly
what a leave-one-quadrat-out ablation can price: invented texture that is not correlated
with PV cannot raise held-out AUC.

Runs in a separate venv (`/home/tobi/earthpv_data/sen2sr_venv`) built with
--system-site-packages off the `ml` environment, so the tracked pixi env is untouched.

    /home/tobi/earthpv_data/sen2sr_venv/bin/python scripts/sen2sr_quadrats.py
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import rasterio
import torch

from earthpv.local_source import composite_index
from earthpv.roofclf import BAND_NAMES, discover_quadrats, load_quadrat

log = logging.getLogger("sen2sr")
SCALE = 4
REFL = 10_000.0


def _sr_tiled(x: torch.Tensor, model, tile: int = 128, overlap: int = 16) -> torch.Tensor:
    """Super-resolve a (bands, H, W) tensor in tiles, keeping only each tile's core.

    `sen2sr.predict_large` raised an index-out-of-bounds CUDA assertion on windows whose
    size is not a multiple of its tile, so the tiling is done here instead. Each tile's
    outer `overlap` is discarded rather than blended, which removes seam artefacts at the
    cost of running slightly more tiles: the model sees context on every side of the pixels
    that are kept.
    """
    nb, h, w = x.shape
    step = tile - 2 * overlap
    pad_h = (-(h - 2 * overlap)) % step + 2 * overlap
    pad_w = (-(w - 2 * overlap)) % step + 2 * overlap
    xp = torch.nn.functional.pad(x[None], (overlap, pad_w, overlap, pad_h), mode="reflect")[0]
    out = torch.zeros((nb, h * SCALE, w * SCALE), dtype=torch.float32, device=x.device)
    with torch.no_grad():
        for yy in range(0, h, step):
            for xx in range(0, w, step):
                patch = xp[:, yy:yy + tile, xx:xx + tile]
                if patch.shape[1] != tile or patch.shape[2] != tile:
                    patch = torch.nn.functional.pad(
                        patch[None], (0, tile - patch.shape[2], 0, tile - patch.shape[1]),
                        mode="reflect")[0]
                sr = model(patch[None]).squeeze(0)
                core = sr[:, overlap * SCALE:(tile - overlap) * SCALE,
                          overlap * SCALE:(tile - overlap) * SCALE]
                oy, ox = yy * SCALE, xx * SCALE
                ch = min(core.shape[1], out.shape[1] - oy)
                cw = min(core.shape[2], out.shape[2] - ox)
                out[:, oy:oy + ch, ox:ox + cw] = core[:, :ch, :cw]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--composites", type=Path, default=Path("data/composites/pakistan"))
    ap.add_argument("--labels-dir", type=Path, default=Path("data/labels"))
    ap.add_argument("--model", type=Path,
                    default=Path("/home/tobi/earthpv_data/sen2sr_model/SEN2SRLite"))
    ap.add_argument("--tile", type=int, default=128)
    ap.add_argument("--overlap", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    import mlstac

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = mlstac.load(str(args.model)).compiled_model(device=dev).to(dev).eval()
    log.info("SEN2SRLite on %s, %.1fM params", dev,
             sum(p.numel() for p in model.parameters()) / 1e6)

    out_dir = args.composites / "sen2sr"
    out_dir.mkdir(parents=True, exist_ok=True)
    names = discover_quadrats(args.labels_dir)
    todo = [n for n in names if not (out_dir / f"{n}.tif").exists()]
    if args.limit:
        todo = todo[: args.limit]
    log.info("%d quadrats, %d to super-resolve", len(names), len(todo))

    idx = composite_index(str(args.composites), layers=1)
    done = failed = 0
    for i, stem in enumerate(todo, start=1):
        t0 = time.time()
        try:
            boundary, _ = load_quadrat(stem, args.labels_dir)
            res = idx.read_window(boundary.bounds)
            if res is None:
                log.warning("%s: no composite coverage", stem)
                failed += 1
                continue
            arr, transform, crs = res
            arr = arr[: len(BAND_NAMES)].astype("float32") / REFL
            x = torch.from_numpy(arr).float().to(dev)
            y = _sr_tiled(x, model, tile=args.tile, overlap=args.overlap)
            sr = (y.clamp(0, 6.5).cpu().numpy() * REFL).astype("uint16")
            # The 4x finer grid: same origin, quarter pixel size.
            tr = rasterio.Affine(transform.a / SCALE, transform.b, transform.c,
                                 transform.d, transform.e / SCALE, transform.f)
            dst = out_dir / f"{stem}.tif"
            tmp = dst.with_suffix(".tif.tmp")
            with rasterio.open(tmp, "w", driver="GTiff", width=sr.shape[2],
                               height=sr.shape[1], count=sr.shape[0], dtype="uint16",
                               crs=crs, transform=tr, compress="deflate",
                               predictor=2) as d:
                d.write(sr)
                d.descriptions = tuple(b.upper() for b in BAND_NAMES)
                d.update_tags(earthpv_sr="SEN2SRLite", earthpv_sr_scale=str(SCALE))
            tmp.rename(dst)
            done += 1
            log.info("[%d/%d] %s: %dx%d -> %dx%d, %.0fs", i, len(todo), stem,
                     arr.shape[2], arr.shape[1], sr.shape[2], sr.shape[1], time.time() - t0)
        except Exception as e:  # noqa: BLE001 - one bad quadrat must not kill the run
            log.warning("%s failed: %s", stem, e)
            failed += 1
    log.info("Super-resolved %d quadrats, %d failed", done, failed)


if __name__ == "__main__":
    main()
