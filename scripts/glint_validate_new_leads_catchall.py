"""Catch-all pass for glint_validate_new_leads.py: after the hand-picked city/town
list, the observed ~8% validation rate meant even 22 cities' worth of candidates
(~1300) wouldn't clear 200 leads. Rather than keep guessing more town names, process
every remaining new_lead directly -- `tile_scene_series_batch` groups by actual
1-degree location internally, so no city bbox is needed at all; this just closes the
gap with whatever's left of the country-wide new_leads pool.

Writes into the SAME output dir as glint_validate_new_leads.py so main()'s final
`combined.csv` aggregation (if re-run) picks this up too.

Usage:
  .pixi/envs/default/bin/python scripts/glint_validate_new_leads_catchall.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

DATE_RANGE = (datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc))
NEW_LEADS = Path("data/predictions_pk16085/pakistan/pakistan_pv_new_leads.geojson")
OUT_DIR = DATA_DIR / "glint" / "new_leads_validate"
CHUNK_SIZE = 400  # checkpoint every N candidates, not just at the very end


def already_done() -> set[str]:
    done = set()
    for p in OUT_DIR.glob("*.csv"):
        if p.stem in ("combined", "catchall"):
            continue
        try:
            done |= set(pd.read_csv(p, usecols=["pid"]).pid)
        except Exception:  # noqa: BLE001
            pass
    for p in sorted(OUT_DIR.glob("catchall_chunk*.csv")):
        try:
            done |= set(pd.read_csv(p, usecols=["pid"]).pid)
        except Exception:  # noqa: BLE001
            pass
    return done


def score_chunk(chunk: gpd.GeoDataFrame) -> pd.DataFrame:
    targets = pd.DataFrame({
        "pid": chunk["candidate_id"].to_numpy(),
        "geometry": chunk.geometry.to_numpy(),
        "lon": chunk.geometry.centroid.x.to_numpy(),
        "lat": chunk.geometry.centroid.y.to_numpy(),
    })
    series_by_pid = glint.tile_scene_series_batch(
        targets, *DATE_RANGE, tile_deg=1.0, max_workers=20,
    )
    rows = []
    for pid, area, conf, rank in zip(chunk["candidate_id"], chunk.area_m2, chunk.confidence,
                                      chunk.rank_score):
        df = series_by_pid.get(pid, pd.DataFrame())
        if df.empty:
            continue
        res = glint.spike_fit(df, self_referenced=True)
        rows.append(dict(
            pid=pid, city="catchall", area_m2=float(area), confidence=float(conf),
            rank_score=float(rank), n_scenes=res["n_scenes"], n_spikes=res["n_spikes"],
            n_consistent=res["n_consistent"], fit_tilt=res["fit_tilt"], fit_az=res["fit_az"],
        ))
    out = pd.DataFrame(rows)
    if not out.empty:
        out["validated"] = out.n_consistent >= 2
        out = out.merge(
            chunk[["candidate_id", "geometry"]].rename(columns={"candidate_id": "pid"}),
            on="pid", how="left",
        )
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    leads = gpd.read_file(NEW_LEADS)
    done = already_done()
    remaining = leads[~leads.candidate_id.isin(done)].reset_index(drop=True)
    # Highest rank_score first -- most likely real, and gets us to 200 fastest if we
    # have to stop partway through.
    remaining = remaining.sort_values("rank_score", ascending=False).reset_index(drop=True)
    print(f"{len(leads)} total new_leads, {len(done)} already scored, "
          f"{len(remaining)} remaining (highest rank_score first)")

    n_chunks = (len(remaining) + CHUNK_SIZE - 1) // CHUNK_SIZE
    total_validated = 0
    for p in OUT_DIR.glob("*.csv"):
        if p.stem == "combined":
            continue
        d = pd.read_csv(p)
        if "validated" in d.columns:
            total_validated += int(d.validated.sum())
    for i in range(n_chunks):
        marker = OUT_DIR / f"catchall_chunk{i:03d}.csv"
        if marker.exists():
            continue
        chunk = remaining.iloc[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        print(f"chunk {i}/{n_chunks}: scoring {len(chunk)} candidates...")
        try:
            out = score_chunk(chunk)
        except Exception as e:  # noqa: BLE001 -- one bad chunk must not kill the run
            print(f"chunk {i}: FAILED ({e.__class__.__name__}: {e})")
            continue
        out.to_csv(marker, index=False)
        n_val = int(out.validated.sum()) if not out.empty else 0
        total_validated += n_val
        print(f"chunk {i}: {len(out)} scored, {n_val} validated "
              f"(running total across all batches: {total_validated})")
        if total_validated >= 200:
            print(f"Reached {total_validated} validated leads -- target met, stopping early.")
            break
    print("CATCHALL_DONE")


if __name__ == "__main__":
    main()
