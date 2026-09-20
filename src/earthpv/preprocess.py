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
from pathlib import Path

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


# --- Temporal unmixing ------------------------------------------------------------------
#
# The third unmixing attempt, and the one that uses neither the footprint nor the marginal
# distribution. Its constraint is that a PV array's AREAL FRACTION of a pixel is constant
# over time while the background's reflectance is not:
#
#     y_p(t) = f_p . r_PV + (1 - f_p) . b_p(t)
#
# Take the temporal spread of both sides. `r_PV` is constant, so it contributes none, and
#
#     spread(y_p) = (1 - f_p) . spread(b_p)
#
# which makes `f_p` estimable WITHOUT knowing either endmember's spectrum, as one minus the
# ratio of a pixel's temporal spread to its local background's. That is the property worth
# having: it is self-normalising against roof colour, where absolute reflectance is not,
# and a dark roof and a panel look alike in a median composite but move differently through
# a season.
#
# Distinct from what has already been rejected here. Static two-endmember unmixing (0.659
# AUC) needed both endmember spectra. Footprint-constrained spatial unmixing (-0.0323 AUC
# within size band) needed the footprint to be exact, which VIDA is not. The temporal
# STATISTICS block (+0.0003) gave roofclf absolute spread, `{b}_tstd`, with no local
# reference -- so it could not tell "this pixel is unusually still" from "this whole
# neighbourhood is still", which is the entire content of the estimator below.
#
# WHERE IT MUST FAIL, stated before measuring: the denominator. Identifiability needs a
# background that moves. A concrete yard beside a concrete roof gives spread(b) ~ 0 and the
# ratio is noise over noise, so `background_amplitude` is emitted alongside every damping
# feature as the validity term, and the per-quadrat analysis conditions on it.
TU_WINDOW = 15          # pixels across the local-background window (~150 m)
TU_MIN_OBS = 5          # a pixel needs this many cloud-free looks to have a spread at all
TU_MIN_AMP = 20.0       # DN: below this the local background is too still to divide by


def _robust_spread(stack: np.ndarray) -> np.ndarray:
    """Median absolute deviation over time, per band and pixel: (band, y, x).

    MAD rather than a standard deviation because a residual unmasked cloud or shadow is a
    large single-date excursion, and this quantity is a denominator.
    """
    with np.errstate(invalid="ignore"):
        med = np.nanmedian(stack, axis=0)
        mad = np.nanmedian(np.abs(stack - med[None]), axis=0)
    return mad.astype("float32")


def _local_reference(a: np.ndarray, background: np.ndarray | None = None,
                     window: int = TU_WINDOW) -> np.ndarray:
    """Local background spread for a (band, y, x) field of per-pixel spreads.

    `background` (see `_local_reference`) is a boolean mask of pixels that may be used as reference. **Excluding the
    buildings themselves is not a refinement, it is the difference between measuring the
    background and measuring the roof.** A median filter over a 150 m window centred on a
    large roof is mostly that roof, so the reference collapses toward the pixel it is meant
    to normalise and damping goes to zero -- systematically for exactly the large buildings
    that carry PV. Measured on faisalabad before this was fixed, PV roofs read LOWER damping
    than PV-free ones, the opposite of what the mixture model predicts.

    Block median over `window`-sized cells of the allowed pixels, bilinearly expanded, so
    the reference varies at the scale of a neighbourhood rather than a footprint.
    """
    from scipy.ndimage import zoom

    nb, h, w = a.shape
    if background is None:
        background = np.ones((h, w), dtype=bool)
    bh, bw = max(h // window, 1), max(w // window, 1)
    ys = np.linspace(0, h, bh + 1).astype(int)
    xs = np.linspace(0, w, bw + 1).astype(int)
    out = np.empty_like(a)
    for i in range(nb):
        coarse = np.full((bh, bw), np.nan, dtype="float32")
        for r in range(bh):
            for c in range(bw):
                sl = (slice(ys[r], ys[r + 1]), slice(xs[c], xs[c + 1]))
                v = a[i][sl][background[sl] & np.isfinite(a[i][sl])]
                if v.size >= 4:
                    coarse[r, c] = np.median(v)
        if np.isnan(coarse).all():
            out[i] = np.nanmedian(a[i])
            continue
        coarse = np.where(np.isnan(coarse), np.nanmedian(coarse), coarse)
        out[i] = zoom(coarse, (h / bh, w / bw), order=1, grid_mode=True, mode="nearest")[:h, :w]
    return out


def temporal_unmix_fields(stack: np.ndarray, background: np.ndarray | None = None
                          ) -> dict[str, np.ndarray]:
    """Per-pixel damping fields from a (time, band, y, x) cloud-masked stack.

    Returns, per band, `damping` = 1 - spread(pixel) / spread(local background), which is
    the areal PV fraction the model above implies, plus the two terms needed to read it
    honestly: `background_amplitude` (the denominator, in DN) and `n_obs`.

    Damping is clipped to [-1, 1] rather than [0, 1]. A pixel that moves MORE than its
    surroundings is evidence against a constant component, and truncating that at zero
    would throw away the negative half of the discriminator.
    """
    n_obs = np.isfinite(stack[:, 0]).sum(axis=0).astype("float32")
    spread = _robust_spread(stack)                      # (band, y, x)
    ref = _local_reference(spread, background)          # (band, y, x)
    with np.errstate(invalid="ignore", divide="ignore"):
        damping = 1.0 - spread / np.maximum(ref, 1e-6)
    damping = np.clip(damping, -1.0, 1.0).astype("float32")
    # Where the background is too still, or the pixel too rarely seen, the ratio means
    # nothing. Emit NaN rather than a plausible-looking number and let the caller decide.
    invalid = (ref < TU_MIN_AMP) | (n_obs[None] < TU_MIN_OBS)
    damping[invalid] = np.nan
    return {"damping": damping, "background_amplitude": ref, "n_obs": n_obs}


STACK_DIR = "stacks"


def load_scene_stack(composites, stem: str):
    """Read a quadrat's saved scene stack back, restoring NaN from the 0 fill."""
    npz = Path(composites) / STACK_DIR / f"{stem}.npz"
    if not npz.exists():
        return None
    z = np.load(npz, allow_pickle=False)
    stack = z["stack"].astype("float32")
    # 0 means masked or unread, the same convention the composites use. A real reflectance
    # of exactly 0 does not occur after the baseline offset.
    stack[stack == 0] = np.nan
    import rasterio

    return stack, rasterio.Affine(*z["transform"]), str(z["crs"])


def temporal_unmix_features(bu_utm, composites, stem: str, zonal_shape: int
                            ) -> dict[str, np.ndarray] | None:
    """Per-building temporal-unmixing features, or None when the stack is missing.

    `{b}_tdamp` is the estimated PV areal fraction from that band's damping, averaged over
    the footprint. `t_damp_vis` / `t_damp_swir` group it the way the physics suggests, and
    `t_bg_amp` carries the DENOMINATOR so the model can discount a building whose
    surroundings never moved -- without it, a damping of 0.4 measured against a still
    background is indistinguishable from one measured against a field.

    `t_damp_valid` is the share of the footprint where the ratio was computable at all.
    """
    from earthpv.roofclf import BAND_NAMES, zonal_mean_max

    loaded = load_scene_stack(composites, stem)
    if loaded is None:
        return None
    stack, transform, crs = loaded
    bu = bu_utm.to_crs(crs)
    # Every footprint is excluded from the background reference, not just the one being
    # measured: a neighbouring roof is no more "background" than this one.
    import rasterio.features

    built = rasterio.features.rasterize(
        ((g, 1) for g in bu.geometry), out_shape=stack.shape[-2:], transform=transform,
        fill=0, dtype="uint8",
    ).astype(bool)
    fields = temporal_unmix_fields(stack, background=~built)
    damping, bg, n_obs = fields["damping"], fields["background_amplitude"], fields["n_obs"]

    # zonal_mean_max cannot carry NaN through its bincount, so the validity mask is taken
    # separately and the NaN cells are zero-filled for the mean -- which is why the share
    # of valid pixels is reported alongside rather than folded in silently.
    valid = np.isfinite(damping).astype("float32")
    filled = np.nan_to_num(damping, nan=0.0)
    dmean, _ = zonal_mean_max(bu, filled, transform)
    vmean, _ = zonal_mean_max(bu, valid, transform)
    bmean, _ = zonal_mean_max(bu, bg, transform)
    nmean, _ = zonal_mean_max(bu, n_obs[None], transform)
    # Re-normalise: the mean of (damping x valid) over the footprint divided by the share
    # valid is the mean over the valid pixels only.
    with np.errstate(invalid="ignore", divide="ignore"):
        dmean = np.where(vmean > 0.2, dmean / np.maximum(vmean, 1e-6), np.nan)

    idx = {b: i for i, b in enumerate(BAND_NAMES)}
    out = {f"{b}_tdamp": dmean[i] for i, b in enumerate(BAND_NAMES)}
    out["t_damp_vis"] = np.nanmean([dmean[idx[b]] for b in ("b02", "b03", "b04", "b08")], axis=0)
    out["t_damp_swir"] = np.nanmean([dmean[idx[b]] for b in ("b11", "b12")], axis=0)
    out["t_bg_amp"] = np.nanmean(bmean, axis=0)
    out["t_damp_valid"] = vmean.mean(axis=0)
    out["t_stack_obs"] = nmean[0]
    return out


TEMPORAL_UNMIX_FEATURES = (
    [f"{b}_tdamp" for b in ("b02", "b03", "b04", "b05", "b06", "b07", "b08", "b8a",
                            "b11", "b12")]
    + ["t_damp_vis", "t_damp_swir", "t_bg_amp", "t_damp_valid", "t_stack_obs"]
)
TEMPORAL_UNMIX_COMPACT = ["t_damp_vis", "t_damp_swir", "t_bg_amp", "t_damp_valid"]


def medoid_composite(stack: np.ndarray) -> np.ndarray:
    """Per-pixel MEDOID of a (time, band, y, x) stack: one real scene's whole spectrum.

    `annual_composite` reduces with `median(dim="time")` on a Dataset, so each band's
    median is taken INDEPENDENTLY. Pixel p's B02 can come from January and its B11 from
    March, and the result is a spectrum no scene ever observed. That is harmless for a band
    in isolation and not harmless for a RATIO between bands -- and the classifier's largest
    coefficients are ratios: `swir_vis_ratio` -3.92, `ndbi` +3.65, `blue_red_ratio` -1.56.
    A panel's signature is its band-to-band shape, and a band-wise median corrupts exactly
    that.

    The medoid picks, per pixel, the single date whose full spectrum is closest to the
    per-band median, and takes all ten of its bands. Spectrally coherent by construction,
    at the cost of being noisier than a median (it is one observation, not an average of
    twelve), which is the trade this measures.

    Distances are normalised per band by that band's spread over the stack, so SWIR's
    larger absolute values do not dominate the choice. A date with any band missing at a
    pixel cannot be that pixel's medoid. Pixels with no complete observation fall back to
    the per-band median, which is what the shipped composite would have given anyway.
    """
    med = np.nanmedian(stack, axis=0)                       # (band, y, x)
    scale = np.nanmedian(np.abs(stack - med[None]), axis=(0, 2, 3))
    scale = np.where(np.isfinite(scale) & (scale > 1e-6), scale, 1.0)[None, :, None, None]
    d = np.sum(((stack - med[None]) / scale) ** 2, axis=1)  # (time, y, x)
    # A date missing any band is not a candidate.
    d = np.where(np.isfinite(stack).all(axis=1), d, np.inf)
    best = np.argmin(np.where(np.isfinite(d), d, np.inf), axis=0)
    nb = stack.shape[1]
    out = np.take_along_axis(stack, best[None, None], axis=0)[0]
    complete = np.isfinite(d).any(axis=0)
    for b in range(nb):
        out[b] = np.where(complete, out[b], med[b])
    return out.astype("float32")


# --- Multi-frame super-resolution ---------------------------------------------------------
#
# The non-learned counterpart to SEN2SR, and the one that can actually add information.
# Single-image SR redistributes the content of one 10 m frame using learned priors; measured
# 2026-09-20 it COSTS 0.0367 AUC within size band (6 of 30 folds, p=0.002), which is what
# invented texture diluting real contrast looks like. Multi-frame fusion is different in
# kind: N frames that sample the ground at different sub-pixel phases jointly carry
# information above the single-frame Nyquist limit, and recovering it is arithmetic on real
# observations rather than a prior.
#
# Shift-and-add with bilinear splatting: every output sample is a weighted mean of real
# pixels, so nothing can be hallucinated. Gaps, where no frame contributed, fall back to the
# upsampled reference.
#
# WHAT THE PRECONDITION SAYS (measured 2026-09-19, `scripts/measure_subpixel_shifts.py`):
# median inter-acquisition shift is 0.122 px (1.22 m) and the sub-pixel phase offsets sit at
# roughly a quarter of the uniform-spread ideal, with only about 3 of 12 frames usefully
# displaced. So 2x is the realistic ceiling here, not the 4x a well-sampled stack would
# support, and Google's 32-acquisition budget is doing real work in their version.
MFSR_SCALE = 2


def mfsr_shift_and_add(stack: np.ndarray, shifts: np.ndarray, scale: int = MFSR_SCALE
                       ) -> np.ndarray:
    """Fuse a (time, band, y, x) stack onto a `scale`x finer grid using per-frame shifts.

    `shifts` is (time, 2) of (dy, dx) in source pixels, as returned by phase correlation
    against the reference frame. Each observed pixel is splatted bilinearly to where it
    actually fell on the ground, so a frame offset by half a pixel contributes between the
    output samples rather than on top of them -- which is the entire mechanism.
    """
    nt, nb, h, w = stack.shape
    H, W = h * scale, w * scale
    acc = np.zeros((nb, H, W), dtype="float64")
    wgt = np.zeros((H, W), dtype="float64")
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    for t in range(nt):
        dy, dx = float(shifts[t, 0]), float(shifts[t, 1])
        # Where this frame's samples truly sit on the reference grid, in output pixels.
        oy = (yy - dy + 0.5) * scale - 0.5
        ox = (xx - dx + 0.5) * scale - 0.5
        y0 = np.floor(oy).astype(int)
        x0 = np.floor(ox).astype(int)
        fy, fx = oy - y0, ox - x0
        finite = np.isfinite(stack[t]).all(axis=0)
        for ddy, ddx, wf in ((0, 0, (1 - fy) * (1 - fx)), (0, 1, (1 - fy) * fx),
                             (1, 0, fy * (1 - fx)), (1, 1, fy * fx)):
            ty, tx = y0 + ddy, x0 + ddx
            ok = finite & (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W) & (wf > 0)
            if not ok.any():
                continue
            ti, tj, tw = ty[ok], tx[ok], wf[ok]
            np.add.at(wgt, (ti, tj), tw)
            for b in range(nb):
                np.add.at(acc[b], (ti, tj), stack[t, b][ok] * tw)
    out = np.full((nb, H, W), np.nan, dtype="float32")
    filled = wgt > 1e-6
    for b in range(nb):
        out[b][filled] = acc[b][filled] / wgt[filled]
    # Gaps: fall back to a plain upsample of the temporal median, so the raster is complete
    # and any difference against the baseline comes from the fused samples, not from holes.
    with np.errstate(invalid="ignore"):
        med = np.nanmedian(stack, axis=0)
    for b in range(nb):
        up = np.repeat(np.repeat(med[b], scale, axis=0), scale, axis=1)[:H, :W]
        gap = ~filled & np.isfinite(up)
        out[b][gap] = up[gap]
    return out
