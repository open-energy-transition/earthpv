"""Transfer calibration: a sub-400 m2 level for a country with no calibration quadrats.

The quadrat estimator (`sub400_capacity`) prices flagged roof area with a coverage ratio
and an area recall measured on Rule-1-complete quadrats: areas where every visible panel is
mapped, on imagery recent enough to show them. Where the only high-resolution imagery is
years old, such quadrats cannot be drawn (Box 17), and a country without them has had no
sub-400 m2 figure at all.

The classifier itself can be borrowed: ranking transfers across quadrats far better than
absolute rates do. What cannot be borrowed is the level, because the coverage ratio carries
precision and precision carries the local adoption rate, which is the very thing to measure.
This module measures the level from two things such a country still has:

- **Positives.** Buildings carrying OSM-mapped PV, wherever they are. Incomplete mapping is
  fine: only the detection rate AMONG them is used (TPR), never their number. Mapped from
  old imagery is fine too, since an array mapped then is still on the roof now.
- **Negatives from the past.** The same buildings in an earlier, pre-boom Sentinel-2 epoch,
  scored by the same model. Their flag rate then is an upper bound on the false-positive
  rate now (FPR): it includes whatever PV already existed, and the roofs that have adopted
  since were disproportionately the ones that already looked like adopters.

With the current flag rate f, the adjusted count (Forman 2005) gives the share of buildings
carrying PV detectable like the mapped population:

    pi = (f - FPR) / (TPR - FPR)

per roof-size bin, and capacity follows from the mean mapped array per PV building. Both
bias terms it knows about are signed low: an inflated FPR lowers pi, and OSM positives
skewed toward large, easily traced arrays raise TPR, which lowers pi as well. Arrays too
small for the sensor are outside what it can count, as they are for the quadrat estimator.

`scripts/transfer_calibration_pakistan_check.py` validates it against Pakistan's quadrats
before any other country uses it.

**VERDICT (2026-10-20): REJECTED, do not deploy.** The positives half works: with the true
current FPR plugged in, OSM-derived TPR and array size estimate Pakistan's quadrats at a
median 46% error, Spearman 0.96. The negatives half fails. The same roofs in 2021 flag MORE
often than today (0.236 against 0.160, true FPR 0.093), so the adjusted count goes negative,
and normalising the old epoch against today just makes the two flag rates equal. The reason
is the classifier, not the imagery: roofclf's 2021 score predicts TODAY's PV at AUC 0.832
against 0.870 for today's score, when Pakistan had imported 14% of today's panels by then. It
recognises the kind of roof that adopts, so the past is not a negative set for it. See
docs/experiments.md, "A sub-400 m2 level without quadrats".
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Roof-size bins of the sub-400 m2 population. Coarser than the quadrat estimator's deciles
# because TPR has to be measured per bin from OSM positives, of which a country without
# quadrats has hundreds, not tens of thousands.
SIZE_EDGES_M2 = (0.0, 50.0, 100.0, 200.0, 400.0)
N_SIZE_BINS = len(SIZE_EDGES_M2) - 1
# A bin with fewer positives borrows the pooled rate rather than a noisy one of its own.
MIN_POSITIVES_PER_BIN = 30
# Below this TPR - FPR the classifier does not separate PV roofs from the rest in this
# country, and the adjusted count divides by noise: the bin is reported as unidentified.
MIN_SEPARATION = 0.05
# Scenes processed before Sentinel-2 baseline 04.00 (2022-01-25) carry no BOA offset; the
# models are fitted on post-2022 composites, which carry +1000 DN. A pre-boom layer is
# therefore harmonized by this much before scoring. Measured on Pakistan's composite_1
# (2021-10 to 2022-01): its darkest pixels sit 700-1,000 DN below composite_0's in every
# band, where the same water and shadow should read the same.
PRE_BASELINE_DN_OFFSET = 1000.0


def size_bin(roof_area_m2) -> np.ndarray:
    """0 .. N_SIZE_BINS-1 for a sub-400 m2 roof, -1 for anything else (incl. NaN)."""
    a = np.asarray(roof_area_m2, dtype=float)
    b = np.digitize(a, SIZE_EDGES_M2[1:-1])
    b[~np.isfinite(a) | (a >= SIZE_EDGES_M2[-1]) | (a < SIZE_EDGES_M2[0])] = -1
    return b


def label_pv(bu: gpd.GeoDataFrame, pv: gpd.GeoDataFrame, parcel: bool = True) -> pd.DataFrame:
    """Mapped PV area per building and its has-PV flag, built exactly as `building_table`
    builds a quadrat's label (roof term, plus the parcel term when `parcel`), so a TPR
    measured on OSM positives means what the quadrat label means. `bu` needs `area_m2`;
    both frames in EPSG:4326.
    """
    import shapely

    from earthpv.roofclf import MIN_PV_OVERLAP_FRAC, parcel_pv_area, roof_pv_area

    # National VIDA and OSM layers both hold the odd self-intersecting ring, which a quadrat
    # table never met; repair only the invalid ones so every valid footprint is untouched.
    bu, pv = bu.copy(), pv.copy()
    for g in (bu, pv):
        bad = ~g.geometry.is_valid
        if bad.any():
            # buffer(0) keeps the polygonal part of a repaired GeometryCollection.
            g.loc[bad, g.geometry.name] = shapely.buffer(
                shapely.make_valid(g.geometry[bad].to_numpy()), 0)
    total = roof_pv_area(bu, pv)
    if parcel and not pv.empty and len(bu):
        bu_utm = bu.to_crs(bu.estimate_utm_crs())
        ground, overhang, _ = parcel_pv_area(bu, bu_utm, pv)
        total = total + ground + overhang
    roof = bu["area_m2"].to_numpy(float)
    frac = total / np.maximum(roof, 1e-6)
    return pd.DataFrame({"pv_area_m2": total, "has_pv": frac >= MIN_PV_OVERLAP_FRAC},
                        index=bu.index)


def bin_rates(bins: np.ndarray, p: np.ndarray, threshold: float) -> pd.DataFrame:
    """Per size bin: buildings with a score, their flag rate at `threshold`, mean score."""
    df = pd.DataFrame({"bin": np.asarray(bins), "p": np.asarray(p, dtype=float)})
    df = df[(df["bin"] >= 0) & df["p"].notna()]
    df["flag"] = df["p"] >= threshold
    g = df.groupby("bin")
    out = pd.DataFrame({"n": g.size(), "flag_rate": g["flag"].mean(), "mean_p": g["p"].mean()})
    return out.reindex(range(N_SIZE_BINS))


def positive_rates(bins: np.ndarray, p: np.ndarray, pv_area_m2: np.ndarray,
                   threshold: float, min_n: int = MIN_POSITIVES_PER_BIN) -> pd.DataFrame:
    """Per size bin, over PV-carrying buildings: TPR at `threshold`, mean score, and mean
    PV area per PV building. A bin with fewer than `min_n` positives takes the pooled
    values and says so in `pooled`."""
    df = pd.DataFrame({"bin": np.asarray(bins), "p": np.asarray(p, dtype=float),
                       "a": np.asarray(pv_area_m2, dtype=float)})
    df = df[(df["bin"] >= 0) & df["p"].notna()]
    df["flag"] = df["p"] >= threshold
    pooled = {"tpr": df["flag"].mean(), "mean_p": df["p"].mean(), "mean_pv_area_m2": df["a"].mean()}
    g = df.groupby("bin")
    out = pd.DataFrame({"n_pos": g.size(), "tpr": g["flag"].mean(), "mean_p": g["p"].mean(),
                        "mean_pv_area_m2": g["a"].mean()}).reindex(range(N_SIZE_BINS))
    out["n_pos"] = out["n_pos"].fillna(0).astype(int)
    out["pooled"] = out["n_pos"] < min_n
    for c, v in pooled.items():
        out.loc[out["pooled"], c] = v
    return out


def adjusted_share(f, fpr, tpr, min_separation: float = MIN_SEPARATION):
    """The adjusted count's PV share, NaN where TPR - FPR is too small to divide by."""
    f, fpr, tpr = (np.asarray(x, dtype=float) for x in (f, fpr, tpr))
    den = tpr - fpr
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den >= min_separation, (f - fpr) / den, np.nan)


def estimate(cur: pd.DataFrame, pre: pd.DataFrame, pos: pd.DataFrame,
             probabilistic: bool = False) -> pd.DataFrame:
    """Per size bin: PV share, PV buildings and PV area for one population.

    `cur` and `pre` are `bin_rates` of the same buildings in the current and the pre-boom
    epoch, `pos` is `positive_rates`. `probabilistic` uses mean scores instead of flag
    rates (the probabilistic adjusted count), which needs no threshold and is less noisy
    but assumes the scores mean the same thing in both epochs.
    """
    col, pcol = ("mean_p", "mean_p") if probabilistic else ("flag_rate", "tpr")
    out = pd.DataFrame({"n": cur["n"], "f": cur[col], "fpr": pre[col], "tpr": pos[pcol],
                        "mean_pv_area_m2": pos["mean_pv_area_m2"]})
    out["pi"] = adjusted_share(out["f"], out["fpr"], out["tpr"])
    out["n_pv"] = out["pi"] * out["n"]
    out["pv_area_m2"] = out["n_pv"] * out["mean_pv_area_m2"]
    return out


def density_bands(density: np.ndarray, n_buildings: np.ndarray, n_bands: int) -> np.ndarray:
    """Band edges (bldg/km2) cutting cells into `n_bands` of equal BUILDING share, so each
    band holds the same population and a sparse band is not one of three villages."""
    order = np.argsort(density)
    cum = np.cumsum(np.asarray(n_buildings, dtype=float)[order])
    cum /= cum[-1]
    d = np.asarray(density, dtype=float)[order]
    inner = [d[np.searchsorted(cum, k / n_bands)] for k in range(1, n_bands)]
    return np.array([0.0, *inner, np.inf])


def sample_cells(grid: pd.DataFrame, n_bands: int = 6, per_band: int = 20,
                 seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    """Cells to composite the pre-boom epoch for: `per_band` building-weighted random cells
    from each of `n_bands` density bands of equal building share. `grid` needs `cell`,
    `n_buildings` and `density`. Returns the sample (with its `band`) and the band edges."""
    rng = np.random.default_rng(seed)
    g = grid[grid["n_buildings"] > 0].copy()
    edges = density_bands(g["density"].to_numpy(), g["n_buildings"].to_numpy(), n_bands)
    g["band"] = np.clip(np.digitize(g["density"], edges[1:-1]), 0, n_bands - 1)
    picks = []
    for b, gb in g.groupby("band"):
        w = gb["n_buildings"].to_numpy(dtype=float)
        k = min(per_band, len(gb))
        idx = rng.choice(len(gb), size=k, replace=False, p=w / w.sum())
        picks.append(gb.iloc[idx])
    return pd.concat(picks, ignore_index=True), edges
