"""Self-tests for `scripts/propose_calibration_candidates.py`'s building blocks.

The sampler itself needs a country's density grid, its VIDA file and Esri's metadata
service, so these pin the three pieces whose answers are known in advance: the density
bands hold equal shares of buildings, stems are clean place names, and the window count
finds a synthetic settlement where it was put.

Run with `pixi run -e default python -m pytest tests/ -q` (pytest is not currently a
declared dependency; these are written to also run as a plain script).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "propose_calibration_candidates", ROOT / "scripts" / "propose_calibration_candidates.py")
pcc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pcc)


def test_bands_hold_equal_building_shares():
    rng = np.random.default_rng(0)
    density = np.exp(rng.normal(4, 1.5, 5000))            # long-tailed, like a real country
    cells = pd.DataFrame({"bldg_density_km2": density, "n_buildings": density * 100})
    edges = pcc.strata_edges(cells, 8)
    assert len(edges) == 9 and edges[0] == 0 and np.isinf(edges[-1])
    band = np.searchsorted(edges, cells["bldg_density_km2"], side="right") - 1
    share = cells.groupby(band)["n_buildings"].sum() / cells["n_buildings"].sum()
    assert len(share) == 8 and np.allclose(share, 1 / 8, atol=0.01), share.round(3).tolist()


def test_stems_are_clean_place_names():
    assert pcc.slug("Province de Nador إقليم الناظور") == "nador"
    assert pcc.slug("City of Johannesburg") == "johannesburg"
    assert pcc.slug("Prefecture of Salé") == "sale"
    assert pcc.slug("Qantara Gharb, al-") == "qantara_gharb_al"
    assert pcc.slug("Hà Nội") == "ha_noi"
    assert pcc.slug("Larache Province") == "larache"


def test_window_count_finds_the_settlement():
    # 400 buildings in a 1 km square centred 3 km east and 4 km north of the cell's corner,
    # plus a thin rural scatter; the best 1 km window must sit on the square.
    rng = np.random.default_rng(1)
    cell = pd.Series({"lon0": 30.0, "lat0": -15.0})
    lat_c = -14.95
    m_lat = 111_132.954 - 559.822 * np.cos(2 * np.radians(lat_c))
    m_lon = 111_412.84 * np.cos(np.radians(lat_c))
    cx, cy = 30.0 + 3000 / m_lon, -15.0 + 4000 / m_lat
    lon = np.r_[cx + rng.uniform(-500, 500, 400) / m_lon, 30.0 + rng.uniform(0, 0.1, 50)]
    lat = np.r_[cy + rng.uniform(-500, 500, 400) / m_lat, -15.0 + rng.uniform(0, 0.1, 50)]
    w = pcc.window_densities(lon, lat, cell, 1000.0)
    best = w[np.argmax(w[:, 2])]
    # Windows sit on a quarter-side (200 m) grid, so the best one can be 100 m off on each
    # axis: at least 0.9 x 0.9 of the square, never the whole of it by construction.
    assert best[2] >= 0.81 * 400 - 10, best
    assert abs(best[0] - cx) * m_lon < 300 and abs(best[1] - cy) * m_lat < 300, best


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
