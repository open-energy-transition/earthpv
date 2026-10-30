"""Lightning datamodule for PV chips (12-band annual S2 composites + binary masks)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import torch
from lightning import LightningDataModule
from torch.utils.data import DataLoader, Dataset

# Chips store reflectance DN (x10000); we feed reflectance in [0, ~1.5]. TerraTorch's
# TerraMind backbones do NOT apply TerraMind's pretraining standardisation: a backbone that
# needs it applies it inside the model (`earthpv.terramind_backbone`, `earthpv.thor_backbone`).
DN_SCALE = 10000.0


def _drop_from_page_cache(path: str) -> None:
    """Tell the kernel this chip's pages need not stay cached. A combined corpus (~20 GB for
    v14's 33k chips) is larger than a training unit's MemoryMax, so each epoch's pass only
    evicts the last one; the cache it builds is charged to the unit, fills the limit, and the
    in-cgroup reclaim that follows is the memory pressure systemd-oomd kills on (the THOR
    comparison run was killed this way twice on 2026-10-22/23). Reads are unchanged."""
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)
    except (OSError, AttributeError):  # AttributeError: no posix_fadvise on this platform
        pass


class PVChipDataset(Dataset):
    def __init__(self, index: pd.DataFrame, augment: bool = False, target: str = "class"):
        self.index = index.reset_index(drop=True)
        self.augment = augment
        self.target = target

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, i: int) -> dict:
        row = self.index.iloc[i]
        # Bracket access: `row.mask` would resolve to the pandas Series.mask method.
        with rasterio.open(row["image"]) as src:
            img = src.read().astype("float32") / DN_SCALE  # (10, H, W) reflectance
        with rasterio.open(row["mask"]) as src:
            mask_dtype = "float32" if self.target == "fraction" else "int64"
            mask = src.read(1).astype(mask_dtype)
        _drop_from_page_cache(row["image"])
        _drop_from_page_cache(row["mask"])
        if self.augment:
            k = np.random.randint(4)
            img, mask = np.rot90(img, k, (1, 2)).copy(), np.rot90(mask, k, (0, 1)).copy()
            if np.random.rand() < 0.5:
                img, mask = img[:, :, ::-1].copy(), mask[:, ::-1].copy()
        return {"image": torch.from_numpy(img), "mask": torch.from_numpy(mask)}


class PVDataModule(LightningDataModule):
    def __init__(
        self,
        index_path: str | Path,
        batch_size: int = 4,
        num_workers: int = 4,
        min_val_chips: int = 8,
        target: str = "class",
    ):
        super().__init__()
        self.index_path = Path(index_path)
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.min_val_chips = min_val_chips
        self.target = target

    def setup(self, stage: str | None = None) -> None:
        index = pd.read_parquet(self.index_path)
        train = index[index.split == "train"]
        val = index[index.split == "val"]
        if len(val) < self.min_val_chips:
            # Smoke tests / small AOIs without held-out regions: random 20% split
            val = train.sample(frac=0.2, random_state=42)
            train = train.drop(val.index)
        self.train_ds = PVChipDataset(train, augment=True, target=self.target)
        self.val_ds = PVChipDataset(val, target=self.target)

    def train_dataloader(self) -> DataLoader:
        return DataLoader(
            self.train_ds, batch_size=self.batch_size, shuffle=True,
            num_workers=self.num_workers, pin_memory=True,
        )

    def val_dataloader(self) -> DataLoader:
        return DataLoader(
            self.val_ds, batch_size=self.batch_size, num_workers=self.num_workers,
            pin_memory=True,
        )
