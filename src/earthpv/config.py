"""Shared configuration loading and constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
CONFIG_PATH = REPO_ROOT / "configs" / "aoi.yaml"

# Bands present in the local rooftopsenti composites (10-band uint16 COGs), in file order.
LOCAL_BANDS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]

# TerraMind's pretrained S2L2A modality bands (12), in model order. We drop the two
# 60 m atmospheric bands the composites lack (B01 COASTAL_AEROSOL, B09 WATER_VAPOR),
# which carry no PV signal, and let TerraTorch subset the patch-embed accordingly.
TERRAMIND_S2L2A_BANDS = [
    "COASTAL_AEROSOL", "BLUE", "GREEN", "RED", "RED_EDGE_1", "RED_EDGE_2",
    "RED_EDGE_3", "NIR_BROAD", "NIR_NARROW", "WATER_VAPOR", "SWIR_1", "SWIR_2",
]
# TerraMind band name for each of our LOCAL_BANDS (same order as LOCAL_BANDS).
LOCAL_TO_TERRAMIND = {
    "B02": "BLUE", "B03": "GREEN", "B04": "RED", "B05": "RED_EDGE_1",
    "B06": "RED_EDGE_2", "B07": "RED_EDGE_3", "B08": "NIR_BROAD",
    "B8A": "NIR_NARROW", "B11": "SWIR_1", "B12": "SWIR_2",
}
MODEL_BANDS = [LOCAL_TO_TERRAMIND[b] for b in LOCAL_BANDS]  # 10 TerraMind band names

# Backwards-compatible alias used by imagery.py's Planetary-Computer fallback path.
S2_BANDS = LOCAL_BANDS

# One full year of observations, starting after winter snow season.
SEASONS = {
    "spring": ("2025-03-01", "2025-05-31"),
    "summer": ("2025-06-01", "2025-08-31"),
    "autumn": ("2025-09-01", "2025-11-30"),
    "winter": ("2025-12-01", "2026-02-28"),
}

CHIP_SIZE = 224  # pixels @ 10 m -> 2.24 km, 14x14 ViT patches
CHIP_RES = 10.0  # metres


@dataclass
class Settings:
    """Runtime settings loaded from configs/aoi.yaml with sane defaults."""

    overture_release: str = "2026-05-21.0"
    aois: dict = field(default_factory=dict)
    min_roof_area_m2: float = 200.0
    rooftop_overlap_frac: float = 0.5
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or CONFIG_PATH
        raw = yaml.safe_load(path.read_text()) if path.exists() else {}
        return cls(
            overture_release=raw.get("overture_release", cls.overture_release),
            aois=raw.get("aois", {}),
            min_roof_area_m2=raw.get("min_roof_area_m2", cls.min_roof_area_m2),
            rooftop_overlap_frac=raw.get("rooftop_overlap_frac", cls.rooftop_overlap_frac),
            raw=raw,
        )
