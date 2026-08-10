"""Small CNN on raw building-crop pixels, LOQO-evaluated against roofclf's own
logistic-regression baseline -- design rationale, staged plan, and go/no-go rule are in
`/home/tobi/.claude/plans/soft-wondering-hopper.md` (2026-08-09).

Bounded experiment: no `cli.py` wiring, no national-scale scoring. The only question this
answers is whether removing roofclf's building-level mean-pooling (`zonal_mean_max`
collapses every pixel inside a building's footprint to one scalar per band) recovers
signal that a same-methodology gradient-boosted-tree swap already proved isn't hiding in
the classifier choice alone (`HistGradientBoostingClassifier` under-performed the existing
logistic regression at every one of 6 hyperparameter settings tried, same LOQO protocol,
same features). TerraMind is deliberately NOT the backbone here: its patch-16 tokenization
(160 m/token) is itself a mean-pool coarser than the one this experiment removes -- see the
plan file for the full argument. `SmallRoofCNN` below uses small-stride, small-kernel
convolutions specifically so pixel-adjacency survives past the first few layers.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.warp

from earthpv.chips import _chip_bbox
from earthpv.roofclf import BAND_NAMES, COMPOSITE_FILL, REFL_SCALE, auc, auc_within_size

log = logging.getLogger(__name__)

CHIP_PX_DEFAULT = 64
CHIP_M_DEFAULT = 640.0
N_BANDS = len(BAND_NAMES)
N_CHANNELS = N_BANDS + 1  # + 1 validity-mask channel, see build_building_chips


def _extract_chip(
    arr: np.ndarray, transform: rasterio.Affine, lon: float, lat: float,
    crs, chip_px: int,
) -> np.ndarray:
    """A `chip_px`-square window of `arr` (bands, H, W) centred on (lon, lat), projected
    into `arr`'s own CRS via `transform`. Out-of-bounds edges are zero-padded (consistent
    with `COMPOSITE_FILL=0.0` already meaning "no data" everywhere else in this project).
    Mirrors `chips._crop`'s pad convention, but centred on an arbitrary point rather than
    the array's own centre -- `_crop` alone can't do that, since a building far from a
    quadrat's centroid needs its OWN centre, not the quadrat window's.
    """
    x, y = rasterio.warp.transform("EPSG:4326", crs, [lon], [lat])
    col, row = ~transform * (x[0], y[0])
    col, row = int(round(col)), int(round(row))
    half = chip_px // 2
    r0, r1 = row - half, row - half + chip_px
    c0, c1 = col - half, col - half + chip_px
    out = np.zeros((arr.shape[0], chip_px, chip_px), dtype=arr.dtype)
    ar0, ar1 = max(r0, 0), min(r1, arr.shape[1])
    ac0, ac1 = max(c0, 0), min(c1, arr.shape[2])
    if ar1 <= ar0 or ac1 <= ac0:
        return out
    out[:, ar0 - r0 : ar1 - r0, ac0 - c0 : ac1 - c0] = arr[:, ar0:ar1, ac0:ac1]
    return out


def build_building_chips(
    buildings_path: Path,
    composites: Path,
    chip_px: int = CHIP_PX_DEFAULT,
    chip_m: float = CHIP_M_DEFAULT,
    out_dir: Path = Path("data/roofclf_cnn"),
) -> Path:
    """One-time cache: a `chip_px`-square, `N_CHANNELS`-band (10 reflectance + 1 validity
    mask) crop per building in `buildings_path`, centred on each building's own
    `representative_point()` (the same point `zonal_mean_max`'s sub-pixel fallback
    already uses, so this experiment's chip centre agrees with roofclf's own zonal-stat
    centre for the identical building).

    Reads ONE padded window per quadrat (matching `roofclf.building_table`'s own
    per-quadrat read, not per-building -- a `read_window` call per one of 91,840
    buildings would be far slower for no benefit, since a quadrat's buildings all share
    the same underlying composite tile) and crops each building's chip out of that single
    in-memory array via `_extract_chip`.

    Writes `<out_dir>/chips_<chip_px>px.npy` (memmapped, shape `(n, N_CHANNELS, chip_px,
    chip_px)`, `int16` DN scale -- same convention `datamodule.PVChipDataset` already
    uses, `REFL_SCALE`-divisible back to reflectance) and
    `<out_dir>/chips_<chip_px>px_index.parquet` (row-aligned `quadrat`, `has_pv`,
    `roof_area_m2`, `bf_confidence`, `building_id`). Returns `out_dir`.
    """
    from earthpv.local_source import composite_index

    buildings = gpd.read_parquet(buildings_path)
    n = len(buildings)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chips_path = out_dir / f"chips_{chip_px}px.npy"
    index_path = out_dir / f"chips_{chip_px}px_index.parquet"

    chips = np.lib.format.open_memmap(
        chips_path, mode="w+", dtype="int16", shape=(n, N_CHANNELS, chip_px, chip_px),
    )
    comp_idx = composite_index(str(composites))
    rows_out = []
    pad_deg = chip_m / 111320.0  # generous pad; exact per-lat correction not needed here

    write_i = 0
    for name, group in buildings.groupby("quadrat"):
        pts = group.geometry.representative_point()
        lons, lats = pts.x.to_numpy(), pts.y.to_numpy()
        minx, maxx = lons.min() - pad_deg, lons.max() + pad_deg
        miny, maxy = lats.min() - pad_deg, lats.max() + pad_deg
        res = comp_idx.read_window((minx, miny, maxx, maxy))
        if res is None:
            log.warning("quadrat %s: no composite coverage, skipping %d buildings", name, len(group))
            write_i += len(group)
            continue
        arr, transform, crs = res
        arr = arr[:N_BANDS].astype("float32") / REFL_SCALE
        valid = (~np.all(arr == COMPOSITE_FILL, axis=0))[None, :, :].astype("float32")
        full = np.concatenate([arr, valid], axis=0)

        for i, (_, b) in enumerate(group.iterrows()):
            chip = _extract_chip(full, transform, lons[i], lats[i], crs, chip_px)
            chips[write_i] = np.round(chip * REFL_SCALE).astype("int16")
            rows_out.append({
                "quadrat": name, "has_pv": int(b.has_pv), "roof_area_m2": float(b.roof_area_m2),
                "bf_confidence": float(b.bf_confidence) if pd.notna(b.bf_confidence) else np.nan,
                "building_id": write_i,
            })
            write_i += 1
        log.info("quadrat %s: %d chips built", name, len(group))

    chips.flush()
    index = pd.DataFrame(rows_out)
    index.to_parquet(index_path)
    log.info("Wrote %d chips -> %s (%s) + %s", write_i, chips_path, chips.shape, index_path)
    return out_dir


class BuildingChipDataset:
    """Row-indexes the `chips_<px>px.npy` memmap; `augment=True` applies the same
    rot90/flip convention `datamodule.PVChipDataset` uses (a chip has no privileged
    orientation, unlike a scene with a fixed north-up frame that matters elsewhere)."""

    def __init__(self, chips_path: Path, index: pd.DataFrame, augment: bool = False):
        import numpy as _np

        self.chips = _np.load(chips_path, mmap_mode="r")
        self.index = index.reset_index(drop=True)
        self.augment = augment
        # Matches roofclf.design_matrix's own fillna convention (median of the SAME
        # split this dataset was constructed from, not a global constant).
        self._bf_fallback = (
            float(self.index.bf_confidence.median())
            if self.index.bf_confidence.notna().any() else 0.0
        )

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, i: int):
        import torch

        row = self.index.iloc[i]
        chip = self.chips[int(row.building_id)].astype("float32") / REFL_SCALE
        if self.augment:
            k = np.random.randint(4)
            chip = np.rot90(chip, k, (1, 2)).copy()
            if np.random.rand() < 0.5:
                chip = chip[:, :, ::-1].copy()
        y = float(row.has_pv)
        # Always computed (cheap) so a caller can enable `fuse_scalars` without a second
        # dataset variant; a pixel-only run just never reads the second return element.
        bf = row.bf_confidence
        bf = self._bf_fallback if pd.isna(bf) else bf
        scalars = np.array([np.log10(max(row.roof_area_m2, 1.0)), bf], dtype="float32")
        return torch.from_numpy(chip), torch.from_numpy(scalars), torch.tensor(y, dtype=torch.float32)


def _make_model(fuse_scalars: bool):
    import torch
    import torch.nn as nn

    class SmallRoofCNN(nn.Module):
        def __init__(self, fuse_scalars: bool = False):
            super().__init__()
            self.fuse_scalars = fuse_scalars
            self.stem = nn.Sequential(
                nn.Conv2d(N_CHANNELS, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
                nn.Conv2d(32, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            )
            self.block1 = nn.Sequential(
                nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
                nn.Conv2d(64, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            )
            self.block2 = nn.Sequential(
                nn.Conv2d(64, 128, 3, stride=2, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
                nn.Conv2d(128, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            )
            self.block3 = nn.Sequential(
                nn.Conv2d(128, 256, 3, stride=2, padding=1), nn.BatchNorm2d(256), nn.ReLU(inplace=True),
            )
            self.gap = nn.AdaptiveAvgPool2d(1)
            head_in = 256 + (2 if fuse_scalars else 0)
            self.head = nn.Sequential(
                nn.Linear(head_in, 64), nn.ReLU(inplace=True), nn.Dropout(0.3), nn.Linear(64, 1),
            )

        def forward(self, x, scalars=None):
            x = self.stem(x)
            x = self.block1(x)
            x = self.block2(x)
            x = self.block3(x)
            x = self.gap(x).flatten(1)
            if self.fuse_scalars:
                x = torch.cat([x, scalars], dim=1)
            return self.head(x).squeeze(1)

    return SmallRoofCNN(fuse_scalars=fuse_scalars)


def train_one_fold(
    chips_path: Path,
    index_path: Path,
    test_quadrat: str,
    fuse_scalars: bool = False,
    max_epochs: int = 40,
    patience: int = 6,
    batch_size: int = 256,
    val_frac: float = 0.18,
    seed: int = 0,
) -> np.ndarray:
    """Trains one CNN holding `test_quadrat` fully out (never seen in training or
    validation). Returns predicted probabilities for `test_quadrat`'s own rows, in the
    same row order they appear in `index_path` (i.e. directly comparable to
    `roofclf.evaluate`'s per-fold `p`)."""
    import torch
    from torch.utils.data import DataLoader

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    index = pd.read_parquet(index_path)
    is_test = (index.quadrat == test_quadrat).to_numpy()
    train_pool = index[~is_test].reset_index(drop=True)
    test_idx = index[is_test].reset_index(drop=True)

    val_mask = rng.random(len(train_pool)) < val_frac
    train_idx = train_pool[~val_mask].reset_index(drop=True)
    val_idx = train_pool[val_mask].reset_index(drop=True)

    train_ds = BuildingChipDataset(chips_path, train_idx, augment=True)
    val_ds = BuildingChipDataset(chips_path, val_idx, augment=False)
    test_ds = BuildingChipDataset(chips_path, test_idx, augment=False)
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=2)
    val_dl = DataLoader(val_ds, batch_size=batch_size, num_workers=2)
    test_dl = DataLoader(test_ds, batch_size=batch_size, num_workers=2)

    p_bar = float(train_idx.has_pv.mean())
    pos_weight = torch.tensor([(1 - p_bar) / max(p_bar, 1e-6)], device=device)
    model = _make_model(fuse_scalars).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    def _forward(xb, sb):
        sb = sb.to(device) if fuse_scalars else None
        return model(xb.to(device), sb)

    best_val_auc, best_state, bad_epochs = -1.0, None, 0
    for epoch in range(max_epochs):
        model.train()
        for xb, sb, yb in train_dl:
            yb = yb.to(device)
            opt.zero_grad()
            logits = _forward(xb, sb)
            loss = loss_fn(logits, yb)
            loss.backward()
            opt.step()

        model.eval()
        val_p, val_y = [], []
        with torch.no_grad():
            for xb, sb, yb in val_dl:
                logits = _forward(xb, sb)
                val_p.append(torch.sigmoid(logits).cpu().numpy())
                val_y.append(yb.numpy())
        val_p, val_y = np.concatenate(val_p), np.concatenate(val_y)
        val_auc = auc(val_y.astype(bool), val_p)
        if val_auc > best_val_auc:
            best_val_auc, best_state, bad_epochs = val_auc, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            bad_epochs += 1
        log.info("fold=%s epoch=%d val_auc=%.4f (best=%.4f)", test_quadrat, epoch, val_auc, best_val_auc)
        if bad_epochs >= patience:
            break

    model.load_state_dict(best_state)
    model.eval()
    test_p = []
    with torch.no_grad():
        for xb, sb, _ in test_dl:
            logits = _forward(xb, sb)
            test_p.append(torch.sigmoid(logits).cpu().numpy())
    return np.concatenate(test_p)


def loqo_evaluate_cnn(
    chips_path: Path,
    index_path: Path,
    quadrats: list[str] | None = None,
    **train_kwargs,
) -> tuple[pd.DataFrame, dict, np.ndarray]:
    """Same return shape as `roofclf.evaluate`: `(folds_df, summary, oof)`. `quadrats`
    restricts which quadrats get their own held-out fold (e.g. `["mardan", "lahore"]`
    for the Stage 1 pilot); `None` runs every quadrat present in `index_path` (Stage 2),
    skipping any fold with fewer than 2 classes in its own labels exactly like
    `roofclf.evaluate` already does for its synthetic hard-negative fold.
    """
    index = pd.read_parquet(index_path)
    names = quadrats if quadrats is not None else sorted(index.quadrat.unique())
    oof = np.full(len(index), np.nan)
    rows = []
    for name in names:
        y_test = index.loc[index.quadrat == name, "has_pv"]
        if y_test.nunique() < 2:
            log.warning("skipping fold %s: fewer than 2 classes in test rows", name)
            continue
        p = train_one_fold(chips_path, index_path, name, **train_kwargs)
        test_mask = (index.quadrat == name).to_numpy()
        oof[test_mask] = p
        y = index.loc[test_mask, "has_pv"].to_numpy()
        roof = index.loc[test_mask, "roof_area_m2"].to_numpy()
        within, _ = auc_within_size(y, p, roof)
        rows.append({
            "quadrat": name, "n": int(test_mask.sum()), "n_pv": int(y.sum()),
            "auc": round(auc(y.astype(bool), p), 4), "auc_within_size": round(within, 4),
        })
        log.info("fold %s done: auc=%.4f auc_within_size=%.4f", name, rows[-1]["auc"], rows[-1]["auc_within_size"])
    folds = pd.DataFrame(rows)
    summary = {
        "n_folds": len(folds),
        "median_auc": round(float(folds.auc.median()), 4) if len(folds) else None,
        "median_auc_within_size": round(float(folds.auc_within_size.median()), 4) if len(folds) else None,
    }
    return folds, summary, oof
