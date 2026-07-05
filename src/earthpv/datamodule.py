"""Lightning datamodule for PV chips (12-band annual S2 composites + binary masks)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import torch
from lightning import LightningDataModule
from torch.utils.data import DataLoader, Dataset

# Chips store reflectance DN (x10000). TerraMind pretraining stats are applied by
# the terratorch backbone when available; we feed reflectance in [0, ~1.5].
DN_SCALE = 10000.0


class PVChipDataset(Dataset):
    def __init__(self, index: pd.DataFrame, augment: bool = False):
        self.index = index.reset_index(drop=True)
        self.augment = augment

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, i: int) -> dict:
        row = self.index.iloc[i]
        # Bracket access: `row.mask` would resolve to the pandas Series.mask method.
        with rasterio.open(row["image"]) as src:
            img = src.read().astype("float32") / DN_SCALE  # (10, H, W) reflectance
        with rasterio.open(row["mask"]) as src:
            mask = src.read(1).astype("int64")
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
    ):
        super().__init__()
        self.index_path = Path(index_path)
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.min_val_chips = min_val_chips

    def setup(self, stage: str | None = None) -> None:
        index = pd.read_parquet(self.index_path)
        train = index[index.split == "train"]
        val = index[index.split == "val"]
        if len(val) < self.min_val_chips:
            # Smoke tests / small AOIs without held-out regions: random 20% split
            val = train.sample(frac=0.2, random_state=42)
            train = train.drop(val.index)
        self.train_ds = PVChipDataset(train, augment=True)
        self.val_ds = PVChipDataset(val)

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
