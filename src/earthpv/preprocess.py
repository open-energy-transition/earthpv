"""Preprocessing variants of the composite, for measuring whether any of them help.

Nothing here is in the shipped pipeline. Each function is an alternative way of turning
the same downloaded pixels into per-building reflectance, offered to `roofclf` through
`building_table(preprocess=...)` so the leave-one-quadrat-out harness can price it against
the production table. See docs/experiments.md.

The motivating measurement (2026-09-19): the shipped classifier's largest coefficients sit
on SWIR. `b11_mean` is +4.33, `swir_vis_ratio` -3.92, `ndbi` +3.65 and `b12_mean` -3.23,
against +2.78 for the largest native-10 m band. But B05-B07, B8A, B11 and B12 are NATIVE
20 m, and `odc.stac.load(resolution=10)` replicates them nearest-neighbour: measured on
cell 0122_0077, B11 and B12 are constant across 2x2 blocks in 100.0% of the raster against
0.0% for B02 and B08. So the model leans hardest on bands carrying no independent
information at the grid it is scored on, and a 100 m2 building's SWIR value is one 20 m
observation shared with three neighbouring pixels.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

# Indices into BAND_NAMES / the composite's band axis.
NATIVE_20M = (3, 4, 5, 7, 8, 9)   # B05 B06 B07 B8A B11 B12
NATIVE_10M = (0, 1, 2, 6)         # B02 B03 B04 B08


def block_phase(band: np.ndarray) -> tuple[int, int] | None:
    """Offset (row, col) in {0,1}^2 at which `band`'s 2x2 replication blocks start.

    A composite window is cut at an arbitrary pixel, so the 20 m blocks are not guaranteed
    to start on an even index. Returns None when the band is not block-constant at any
    phase, i.e. it is genuinely 10 m (or has already been sharpened), which is the signal
    to leave it alone rather than to coarsen it by accident.
    """
    best, best_off = 0.0, None
    for oy in (0, 1):
        for ox in (0, 1):
            a = band[oy:, ox:]
            h, w = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
            if h < 2 or w < 2:
                continue
            b = a[:h, :w].reshape(h // 2, 2, w // 2, 2)
            frac = float(np.mean(b.max(axis=(1, 3)) == b.min(axis=(1, 3))))
            if frac > best:
                best, best_off = frac, (oy, ox)
    return best_off if best > 0.95 else None


def _coarse_and_back(band: np.ndarray, off: tuple[int, int], order: int):
    """Take a block-replicated band down to its true 20 m grid and back up smoothly."""
    from scipy.ndimage import zoom

    oy, ox = off
    a = band[oy:, ox:]
    h, w = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
    coarse = a[:h:2, :w:2]
    up = zoom(coarse, 2, order=order, grid_mode=True, mode="nearest")
    out = np.array(band, dtype="float32")
    out[oy:oy + up.shape[0], ox:ox + up.shape[1]] = up
    return out


def sharpen_20m(arr: np.ndarray, method: str = "regress") -> np.ndarray:
    """Replace nearest-replicated 20 m bands with a sharper estimate at 10 m.

    `method="interp"` only removes the blockiness: the band is taken back to its true 20 m
    grid and bilinearly resampled. It adds no information, but nearest replication is a
    pure artefact and misregisters the SWIR contribution against a footprint by up to 10 m,
    which matters when the footprint is one pixel.

    `method="regress"` is regression-based sharpening (the ATPRK family, minus the kriged
    residual). Each 20 m band is regressed on the four native-10 m bands, the fit is
    evaluated at 10 m to get structure, and the part of the coarse band the regression does
    not explain is added back smoothly so the band's coarse content is preserved:

        sharp = (a . X10 + c) + smooth(B - (a . X20 + c))

    **This can hurt, and that is the point of measuring it.** The injected structure comes
    from the visible and NIR bands, so if PV is spectrally distinctive precisely because
    its SWIR behaves unlike its visible, the prior is wrong. `interp` is the control that
    separates "sharpening helps" from "not being blocky helps".
    """
    from scipy.ndimage import uniform_filter

    out = np.array(arr, dtype="float32", copy=True)
    x10 = arr[list(NATIVE_10M)].reshape(len(NATIVE_10M), -1).T  # (P, 4)
    sharpened = 0
    for bi in NATIVE_20M:
        band = arr[bi]
        off = block_phase(band)
        if off is None:
            continue  # already 10 m, or already sharpened: do not touch it
        if method == "interp":
            out[bi] = _coarse_and_back(band, off, order=1)
            sharpened += 1
            continue
        y = band.reshape(-1)
        ok = np.isfinite(y) & np.isfinite(x10).all(axis=1)
        if ok.sum() < 100:
            continue
        design = np.column_stack([x10[ok], np.ones(ok.sum(), dtype="float32")])
        coef, *_ = np.linalg.lstsq(design, y[ok], rcond=None)
        pred = (x10 @ coef[:-1] + coef[-1]).reshape(band.shape).astype("float32")
        # The coarse part the regression missed, smoothed at the 20 m scale so it carries
        # no 10 m structure of its own.
        resid = uniform_filter(band - pred, size=2, mode="nearest")
        out[bi] = pred + resid
        sharpened += 1
    if sharpened:
        log.info("sharpen_20m(%s): sharpened %d of %d native-20 m bands",
                 method, sharpened, len(NATIVE_20M))
    return out


# --- Footprint-constrained spatial unmixing -------------------------------------------
#
# A zonal mean over a building's pixels is a mean of MIXTURES: a 100 m2 roof is one 10 m
# pixel it shares with road, yard and neighbours. Blind two-endmember unmixing was measured
# at 0.659 AUC and rejected (docs/experiments.md). This is a different problem, and a
# well-posed one, because the abundances are KNOWN: the footprints say what fraction of
# every pixel belongs to which building. That turns "separate the mixture" into a linear
# inverse problem,
#
#     y_p = sum_j A_pj r_j + (1 - sum_j A_pj) b_p
#
# with y the observed pixel, A the footprint coverage fractions, r the per-building
# reflectance we want and b a local background, and it is solved for all buildings in a
# quadrat at once.
SUBPIX = 4              # subpixel factor when measuring coverage fractions
BG_BLOCK = 20           # pixels per side of the background estimation block
BG_MAX_FRAC = 0.05      # a pixel counts as background below this building coverage
RIDGE = 0.05            # pull toward the zonal mean, in units of the design matrix


def coverage_matrix(bu_utm, shape, transform, subpix: int = SUBPIX):
    """Sparse (pixels x buildings) matrix of each building's area fraction of each pixel.

    One rasterisation at `subpix` times the resolution, not one per building: each
    subpixel is labelled with the building index covering it, then counted per pixel. At
    subpix=4 a 10 m pixel resolves coverage to 1/16, which is finer than the footprint
    accuracy of an imagery-derived layer like VIDA.
    """
    import rasterio.features
    from scipy import sparse

    h, w = shape
    fine = rasterio.Affine(transform.a / subpix, transform.b, transform.c,
                           transform.d, transform.e / subpix, transform.f)
    lab = rasterio.features.rasterize(
        ((g, i) for i, g in enumerate(bu_utm.geometry, start=1)),
        out_shape=(h * subpix, w * subpix), transform=fine, fill=0, dtype="int32",
    )
    # Fold each pixel's subpixel block into (pixel, building) counts.
    pix = (np.repeat(np.arange(h), subpix)[:, None] * w
           + np.tile(np.repeat(np.arange(w), subpix), (h * subpix, 1)))
    flat_lab, flat_pix = lab.reshape(-1), pix.reshape(-1)
    keep = flat_lab > 0
    rows, cols = flat_pix[keep], flat_lab[keep] - 1
    data = np.full(rows.size, 1.0 / (subpix * subpix), dtype="float32")
    A = sparse.coo_matrix((data, (rows, cols)),
                          shape=(h * w, len(bu_utm))).tocsr()
    A.data = np.minimum(A.data, 1.0)
    return A


def _background(band: np.ndarray, bldg_frac: np.ndarray, block: int = BG_BLOCK):
    """Per-pixel background reflectance: block median over near-building-free pixels."""
    from scipy.ndimage import zoom

    h, w = band.shape
    bh, bw = max(h // block, 1), max(w // block, 1)
    ys = np.linspace(0, h, bh + 1).astype(int)
    xs = np.linspace(0, w, bw + 1).astype(int)
    coarse = np.full((bh, bw), np.nan, dtype="float32")
    free = bldg_frac < BG_MAX_FRAC
    for i in range(bh):
        for j in range(bw):
            sl = (slice(ys[i], ys[i + 1]), slice(xs[j], xs[j + 1]))
            v = band[sl][free[sl]]
            if v.size:
                coarse[i, j] = np.median(v)
    if np.isnan(coarse).all():
        return np.full_like(band, float(np.median(band)))
    # Fill empty blocks with the global background before smoothing them outwards.
    coarse = np.where(np.isnan(coarse), np.nanmedian(coarse), coarse)
    return zoom(coarse, (h / bh, w / bw), order=1, grid_mode=True, mode="nearest")[:h, :w]


def unmix_buildings(bu_utm, arr: np.ndarray, transform, zonal_means: np.ndarray,
                    ridge: float = RIDGE) -> np.ndarray:
    """Per-building reflectance (bands x buildings) by solving the mixture directly.

    `zonal_means` is the ordinary per-footprint mean, used two ways: as the ridge target,
    so an under-determined building falls back to it rather than to noise, and as the
    answer for any building the solve cannot see at all (NaN in, NaN out, which
    `building_table` then drops exactly as it does today).

    Ill-conditioning is real and expected in dense residential quadrats, where neighbouring
    footprints share every pixel and no amount of algebra separates them. The ridge is what
    keeps that from producing confident nonsense, and it is why this is worth measuring per
    quadrat rather than pooled.
    """
    from scipy import sparse
    from scipy.sparse.linalg import lsmr

    nb, h, w = arr.shape
    n = len(bu_utm)
    A = coverage_matrix(bu_utm, (h, w), transform)
    bldg_frac = np.asarray(A.sum(axis=1)).reshape(h, w)
    bldg_frac = np.clip(bldg_frac, 0.0, 1.0)
    touched = np.asarray((A > 0).sum(axis=0)).ravel() > 0
    rows = np.asarray(A.sum(axis=1)).ravel() > 0        # pixels with any building
    Ap = A[rows]
    out = np.array(zonal_means, dtype="float64", copy=True)
    if Ap.shape[0] == 0 or not touched.any():
        return out

    reg = sparse.identity(n, format="csr") * np.sqrt(ridge)
    for bi in range(nb):
        band = arr[bi]
        bg = _background(band, bldg_frac)
        # Observed minus the background's share of each pixel.
        y = (band - (1.0 - bldg_frac) * bg).reshape(-1)[rows]
        target = np.where(np.isfinite(zonal_means[bi]), zonal_means[bi], 0.0)
        M = sparse.vstack([Ap, reg], format="csr")
        rhs = np.concatenate([np.nan_to_num(y), np.sqrt(ridge) * target])
        sol = lsmr(M, rhs, atol=1e-6, btol=1e-6, maxiter=500)[0]
        # Only overwrite buildings the solve actually saw; keep NaN semantics otherwise.
        keep = touched & np.isfinite(zonal_means[bi])
        out[bi, keep] = np.clip(sol[keep], 0.0, 2.0)
    return out
