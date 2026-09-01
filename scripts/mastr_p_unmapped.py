"""Measure `p_unmapped` per placement and size bin for Germany from geolocated MaStR units.

`p_unmapped` is P(candidate is real | candidate has no OSM match) -- the term that turns
the OSM-mapped fraction into `p_real`. Germany's table shipped `p_unmapped = 0.0`
("interim-mapped-only"), an honest floor that priced every unmapped candidate at zero and
drove `est_mwp_cal` to an OLS slope of 0.038 against MaStR (2026-08-31 validation run).

MaStR publishes per-unit coordinates only for units >= 30 kWp -- 0.00% of the 4.17M units
below that carry one, which is a privacy policy rather than missing data. Above the cliff
(99.7% at >= 72 kWp, the 400 m2 x 0.18 kWp/m2 segmentation floor) a registered
installation's address point falling INSIDE an unmapped candidate polygon is direct
evidence that the candidate is real.

What this reports is a chance-corrected LOWER BOUND, not a point estimate:

    p_unmapped >= (obs_b - f_b) / (1 - f_b)

  obs_b  share of unmapped candidates in bin b containing a geolocated MaStR unit
  f_b    the chance of that happening with no true array present. Measured, not assumed,
         and it must be land-use matched -- see the next paragraph, which is the single
         easiest thing to get wrong here.

It is a lower bound in two ways that both push the same direction: a real installation
whose address point is geocoded just off the roof outline counts as a miss, and a real
installation below 30 kWp has no coordinate to match at all.

THE CHANCE TERM MUST BE LAND-USE MATCHED. A first version used only the displaced control
and put f at 0.003-0.023 for rooftop. That is wrong, and measurably so: displacing a
polygon 500-1000 m can move it off the built-up area entirely, into farmland where no
rooftop unit could be registered, so it measures the density of the countryside rather than
the chance of a false positive capturing a neighbour's unit. The right null is the base rate
among buildings the model did NOT detect, in the same imaged cells and the same size bin:
0.100 for 1k-5k m2 (n=7,704) and 0.126 for 5k-50k (n=617), i.e. large German roofs carry
registered PV often enough that containment alone is weak evidence. Candidates still run
2.8-4.6x above that null, so the signal is real, but using the displaced rate as f
overstated p_unmapped by roughly a quarter. `--base-rate-cells` measures the matched null;
the displaced control is kept as a fallback for bins where too few undetected buildings of
that size exist (>50k m2, where VIDA footprints that large barely occur) and is still
reported for both, so the difference stays visible.

With a land-use-matched f the inversion is the two-component mixture rather than a
subtraction, `p_unmapped = (obs - f) / (1 - f)`, which assumes only that a real array's
address point lands inside its own polygon (S = 1). Since S < 1 in reality, this remains a
lower bound.

WHY THERE IS NO SENSITIVITY DIVISION. The natural next step -- divide by a positive
control S_b (match rate among OSM-mapped, i.e. corroborated-real, candidates) the way
`capacity_calibration` inverts the glint instrument -- was measured and REJECTED here.
For ground it behaves (S=0.589 vs obs=0.069 in 5k-50k), but for rooftop it inverts:
S=0.435 on 200 candidates against obs=0.599 on 4,417, and the >50k "control" is 16
candidates. The cause is structural. German OSM covers only ~3.6% of registered rooftop
units and skews to small enthusiast-mapped residential arrays, which are sub-30 kWp and so
carry no MaStR coordinate by policy -- the control is contaminated by exactly the
suppression it was meant to absorb. Dividing by it would clip nearly every rooftop bin to
p_unmapped = 1.0. The raw controls are written alongside the result so this stays checkable.

Usage:
    pixi run python scripts/mastr_p_unmapped.py            # writes the CSV + controls
    earthpv calibrate-candidates --aoi germany \
        --mastr-p-unmapped results/germany_mastr_p_unmapped.csv
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.affinity import translate as shp_translate

from earthpv import capacity_calibration as cc
from earthpv.config import Settings
from earthpv.density import capacity_relevant_candidates
from earthpv.export import _load_mapped_reference, new_lead_mask
from earthpv.labels import geodesic_area_m2, resolve_aoi
from earthpv.postprocess import MAX_CANDIDATE_M2

log = logging.getLogger(__name__)

DEFAULT_DB = Path.home() / ".open-MaStR/data/sqlite/open-mastr.db"
# Coordinates are published >= 30 kWp (0.00% below, a hard policy cliff). Below this a
# real rooftop installation cannot match, which is what makes the result a lower bound.
ROOFTOP_MIN_KWP = 30.0
DISPLACE_M = (500.0, 1000.0)
SEED = 20260901
ROOFTOP_ART = "Gebäudesolaranlage"
GROUND_ART = "Freiflächensolaranlage"


def mastr_points(db: Path, art: str, min_kwp: float, cutoff: str) -> gpd.GeoDataFrame:
    """Geolocated MaStR solar units of one `ArtDerSolaranlage`, commissioned by `cutoff`."""
    con = sqlite3.connect(db)
    try:
        df = pd.read_sql(
            """SELECT Laengengrad AS lon, Breitengrad AS lat, Bruttoleistung AS kwp
               FROM solar_extended
               WHERE ArtDerSolaranlage = ? AND Inbetriebnahmedatum <= ?
                 AND Laengengrad IS NOT NULL AND Breitengrad IS NOT NULL
                 AND Bruttoleistung >= ?""",
            con, params=(art, cutoff, min_kwp),
        )
    finally:
        con.close()
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")


def _nearest_m(polys: gpd.GeoDataFrame, pts: gpd.GeoDataFrame) -> np.ndarray:
    """Metres to the nearest point, one value per polygon (both already projected)."""
    polys = polys.reset_index(drop=True)
    j = gpd.sjoin_nearest(polys[["geometry"]], pts[["geometry"]], how="left", distance_col="d_m")
    # sjoin_nearest emits one row per tied neighbour; collapse to the closest
    return j.groupby(j.index)["d_m"].min().reindex(range(len(polys))).to_numpy()


def _hits_by_bin(d: np.ndarray, idx: np.ndarray) -> dict[str, tuple[int, int]]:
    """{bin_label: (n, n_containing_a_unit)} at radius 0 (point inside the polygon)."""
    out = {}
    for b, label in enumerate(cc.BIN_LABELS):
        in_b = idx == b
        n = int(in_b.sum())
        if n:
            out[label] = (n, int((d[in_b] <= 0.0).sum()))
    return out


MIN_BASE_RATE_N = 100  # below this the matched null is too thin; fall back to displaced


def base_rate_null(
    aoi: str, cands: gpd.GeoDataFrame, pts_wgs: gpd.GeoDataFrame,
    pred_dir: Path, n_cells: int, iso3: str = "DEU",
) -> dict[str, tuple[int, int]]:
    """{bin_label: (n_buildings, n_containing_a_unit)} for buildings the model did NOT detect.

    The land-use-matched chance term: if a large German roof carries registered PV anyway,
    a MaStR unit inside a candidate polygon is that much weaker as evidence. Sampled from
    the density grid's own cells, so it is restricted to imaged coverage by construction.
    """
    from earthpv.buildings import fetch_vida_buildings

    grid_path = pred_dir / aoi / "density/grid.geoparquet"
    if not grid_path.exists():
        log.warning("%s absent -- cannot measure the matched null, using displaced only", grid_path)
        return {}
    grid = gpd.read_parquet(grid_path)
    cells = grid.sample(min(n_cells, len(grid)), random_state=SEED)
    log.info("matched null: sampling %d of %d density cells", len(cells), len(grid))

    frames = []
    for i, (_, cell) in enumerate(cells.iterrows(), 1):
        try:
            blds = fetch_vida_buildings(cell.geometry.bounds, iso3)
        except Exception as e:  # noqa: BLE001 -- one bad cell must not lose the whole null
            log.warning("  cell %d: VIDA fetch failed (%s)", i, e)
            continue
        if blds is None or blds.empty:
            continue
        blds = blds.reset_index(drop=True)
        blds["area_m2"] = [geodesic_area_m2(g) for g in blds.geometry]
        blds = blds[blds.area_m2 >= 500.0].reset_index(drop=True)
        if blds.empty:
            continue
        # undetected only -- a building the model DID flag is not a null
        cs = cands[cands.geometry.intersects(cell.geometry)]
        if not cs.empty:
            hit = gpd.sjoin(blds, cs[["geometry"]], how="left", predicate="intersects")
            keep = hit.groupby(hit.index)["index_right"].apply(lambda s: s.isna().all())
            blds = blds[keep.reindex(range(len(blds)), fill_value=True).to_numpy()]
            blds = blds.reset_index(drop=True)
        if blds.empty:
            continue
        j = gpd.sjoin(blds, pts_wgs[["geometry"]], how="left", predicate="contains")
        has = j.groupby(j.index)["index_right"].apply(lambda s: s.notna().any())
        frames.append(pd.DataFrame({
            "area_m2": blds.area_m2.to_numpy(),
            "has": has.reindex(range(len(blds)), fill_value=False).to_numpy(),
        }))
        if i % 25 == 0:
            log.info("  %d/%d cells, %d buildings", i, len(cells),
                     sum(len(f) for f in frames))
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)
    idx = cc.bin_index(df.area_m2.to_numpy())
    out = {}
    for b, label in enumerate(cc.BIN_LABELS):
        in_b = idx == b
        n = int(in_b.sum())
        if n:
            out[label] = (n, int(df.has.to_numpy()[in_b].sum()))
    return out


def measure(aoi: str, db: Path, cutoff: str, pred_dir: Path,
            base_rate_cells: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)

    raw = gpd.read_parquet(pred_dir / aoi / "candidates.parquet")
    # Same population `density` prices and `calibrate-candidates` calibrates against.
    cands, _ = capacity_relevant_candidates(raw, MAX_CANDIDATE_M2)
    cands = cands.reset_index(drop=True)
    mapped = _load_mapped_reference(aoi, cfg, settings)
    unmapped = new_lead_mask(cands, mapped, min_distance_m=100.0)
    idx_all = cc.bin_index(cands["area_m2"].to_numpy())
    # `_placement_group`'s own rooftop/ground collapse, so bins line up with the
    # placement tables these numbers feed.
    grp_all = cc._placement_group(cands["placement"].to_numpy())
    log.info("candidates %d | unmapped %d | OSM-mapped %d",
             len(cands), int(unmapped.sum()), int((~unmapped).sum()))

    pts = {
        "rooftop": mastr_points(db, ROOFTOP_ART, ROOFTOP_MIN_KWP, cutoff).to_crs(3035),
        "ground": mastr_points(db, GROUND_ART, 0.0, cutoff).to_crs(3035),
    }
    log.info("MaStR geolocated: rooftop>=%gkWp %d | ground %d",
             ROOFTOP_MIN_KWP, len(pts["rooftop"]), len(pts["ground"]))

    base_rate: dict[str, tuple[int, int]] = {}
    if base_rate_cells:
        roof_wgs = mastr_points(db, ROOFTOP_ART, ROOFTOP_MIN_KWP, cutoff)
        base_rate = base_rate_null(aoi, cands, roof_wgs, pred_dir, base_rate_cells)
        for lab, (n, k) in sorted(base_rate.items()):
            log.info("  matched null [%s]: %d/%d = %.4f", lab, k, n, k / n)

    ctl_rows, res_rows = [], []
    for pl in ("rooftop", "ground"):
        P = pts[pl]
        pops: dict[str, dict[str, tuple[int, int]]] = {}
        for pop, mask in (("unmapped", unmapped & (grp_all == pl)),
                          ("mapped", (~unmapped) & (grp_all == pl))):
            sub = cands[mask].to_crs(3035).reset_index(drop=True)
            if sub.empty:
                continue
            pops[pop] = _hits_by_bin(_nearest_m(sub, P), idx_all[mask])
            if pop == "unmapped":
                for dist in DISPLACE_M:
                    th = rng.uniform(0, 2 * np.pi, len(sub))
                    shifted = sub.copy()
                    # GeoSeries.translate takes scalars only, so shift per geometry
                    shifted["geometry"] = gpd.GeoSeries(
                        [shp_translate(g, xoff=dist * np.cos(t), yoff=dist * np.sin(t))
                         for g, t in zip(sub.geometry.to_numpy(), th)],
                        crs=sub.crs,
                    )
                    pops[f"displaced{dist:g}"] = _hits_by_bin(
                        _nearest_m(shifted, P), idx_all[mask]
                    )
        for pop, per_bin in pops.items():
            for label, (n, hit) in per_bin.items():
                ctl_rows.append({"placement": pl, "pop": pop, "bin_label": label,
                                 "n": n, "hit": hit, "rate": round(hit / n, 4)})
        for label in cc.BIN_LABELS:
            if label not in pops.get("unmapped", {}):
                continue
            n, hit = pops["unmapped"][label]
            obs = hit / n
            f_vals = [pops[f"displaced{d:g}"][label][1] / pops[f"displaced{d:g}"][label][0]
                      for d in DISPLACE_M if label in pops.get(f"displaced{d:g}", {})]
            f_disp = float(np.mean(f_vals)) if f_vals else 0.0
            # Prefer the land-use-matched null; fall back to displaced where it is too thin.
            # Only rooftop has one: the null is "an undetected BUILDING of this size", which
            # is not the right comparison for a ground-mount candidate.
            br = base_rate.get(label) if pl == "rooftop" else None
            if br and br[0] >= MIN_BASE_RATE_N:
                f, f_src, f_n = br[1] / br[0], "undetected-buildings", br[0]
            else:
                f, f_src, f_n = f_disp, "displaced", n
            # two-component mixture with S = 1 (a real array's point lands in its own
            # polygon); S < 1 in reality, so this stays a lower bound
            floor = float(np.clip((obs - f) / (1.0 - f), 0.0, 1.0)) if f < 1.0 else 0.0
            res_rows.append({
                "placement": pl, "bin_label": label, "n": n, "n_confirmed": hit,
                "obs": round(obs, 4), "f_chance": round(f, 4), "f_source": f_src,
                "f_n": f_n, "f_displaced": round(f_disp, 4),
                "p_unmapped": round(floor, 4),
                # chance-corrected successes, so the Beta posterior in
                # `capacity_calibration.posterior_draws` is centred on the floor while
                # keeping the real sample size for its width
                "n_real": int(round(floor * n)),
            })
    return pd.DataFrame(res_rows), pd.DataFrame(ctl_rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", default="germany")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="open-mastr sqlite")
    ap.add_argument("--cutoff", default="2025-09-30", help="commissioning cutoff")
    ap.add_argument("--pred-dir", type=Path, default=Path("data/predictions"))
    ap.add_argument("--base-rate-cells", type=int, default=150,
                    help="density cells to sample for the land-use-matched chance term "
                         "(0 disables it and falls back to the displaced control, which "
                         "overstates p_unmapped -- see the module docstring)")
    ap.add_argument("--out", type=Path, default=Path("results/germany_mastr_p_unmapped.csv"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not a.db.exists():
        raise SystemExit(f"{a.db} not found -- run earthpv.mastr.download_mastr() first")
    res, ctl = measure(a.aoi, a.db, a.cutoff, a.pred_dir, a.base_rate_cells)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(a.out, index=False)
    ctl_path = a.out.with_name(a.out.stem + "_controls.csv")
    ctl.to_csv(ctl_path, index=False)
    pd.set_option("display.width", 200)
    print(res.to_string(index=False))
    print(f"\nwrote {a.out}\nwrote {ctl_path}  (positive/negative controls, see module docstring)")


if __name__ == "__main__":
    main()
