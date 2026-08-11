"""Re-pull fresh OSM solar data for every registered calibration quadrat.

Mapping is iterative -- OSM keeps gaining new PV installations after a quadrat was
last pulled, and `roofclf._newest_solar` already exists specifically to prefer a
dated re-pull over the file it supersedes (docs/issues/pakistan-calibration-boxes.md:
Peshawar went 290 -> 353 -> 360 installations across three re-pulls the same day).
This script does that re-pull for every active quadrat in one run, instead of one at
a time by hand.

**Never overwrites an existing pull.** Each quadrat's fresh installations are written
to `data/labels/<stem>_overpass_solar_<date>.parquet` -- the ORIGINAL (undated) pull
and any prior dated re-pull are left untouched, so nothing already registered can be
lost to a bad or partial fetch. `roofclf._newest_solar` picks up the new file
automatically (lexicographic sort: the dated file sorts after the undated one).

Retired quadrats (`data/labels/retired/`) are skipped -- they were withdrawn as wrong
(overlap, bad boundary), not merely stale, and re-pulling them would just re-populate
ground truth nobody wants used.

Same robustness the single-quadrat path (`new_calibration_quadrat.py`) already
established: a 0-result or partial-looking response is retried rather than trusted,
and every pull is cross-checked against `confirm_element_count`'s independent query
of the same bbox before being accepted.

Usage:
    .pixi/envs/default/bin/python scripts/refresh_calibration_areas.py
    .pixi/envs/default/bin/python scripts/refresh_calibration_areas.py --quadrat lahore_calib_6p61km2
    .pixi/envs/default/bin/python scripts/refresh_calibration_areas.py --dry-run
"""
from __future__ import annotations

import argparse
import glob
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402

from earthpv.labels import geodesic_area_m2  # noqa: E402
from earthpv.overpass import build_overpass_labels  # noqa: E402
from earthpv.roofclf import _newest_solar, load_boundary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from new_calibration_quadrat import confirm_element_count  # noqa: E402

LABELS = Path("data/labels")


def discover_active_stems() -> list[str]:
    """Every `*_calib_*`/`*_gmcalib_*` boundary under `data/labels/` directly (not
    `data/labels/retired/`), matching `roofclf.discover_quadrats`'s own glob plus the
    two ground-mount boxes it deliberately excludes (see roofclf.py's docstring on
    why `_gmcalib_` is a separate tag)."""
    stems = set()
    for pattern in ("*_calib_*_boundary.geojson", "*_gmcalib_*_boundary.geojson"):
        for p in sorted(glob.glob(str(LABELS / pattern))):
            stems.add(Path(p).stem.removesuffix("_boundary"))
    return sorted(stems)


def refresh_one(stem: str, retries: int, retry_wait_s: float, dry_run: bool) -> dict:
    boundary_path = LABELS / f"{stem}_boundary.geojson"
    poly = load_boundary(boundary_path)
    w, s, e, n = poly.bounds

    prior_path = _newest_solar(stem, LABELS)
    prior_n = len(gpd.read_parquet(prior_path)) if prior_path else 0
    print(f"\n=== {stem} ===")
    print(f"  current pull: {prior_path.name if prior_path else '(none)'} ({prior_n} installations)")
    if dry_run:
        return {"stem": stem, "prior_path": str(prior_path) if prior_path else None,
                "prior_n": prior_n, "new_n": None, "skipped": "dry-run"}

    tmp_out_dir = Path("data/labels/_refresh_tmp")
    tmp_out_dir.mkdir(parents=True, exist_ok=True)
    tmp_stem = f"{stem}_refresh_{date.today().isoformat().replace('-', '')}"

    out = None
    for attempt in range(1, retries + 1):
        try:
            out = build_overpass_labels(tmp_out_dir, bbox=(w, s, e, n), name=tmp_stem, iso3="PAK")
            n_written = len(gpd.read_parquet(out))
            n_confirm = confirm_element_count((w, s, e, n))
            print(f"  attempt {attempt}: wrote {n_written} (bbox) features; "
                  f"confirming query sees {n_confirm}")
            if n_confirm and n_written < 0.98 * n_confirm:
                raise RuntimeError(
                    f"pull looks truncated: {n_written} vs {n_confirm} confirming"
                )
            break
        except RuntimeError as exc:
            print(f"  attempt {attempt}/{retries} failed: {exc}")
            if attempt == retries:
                print(f"  ABORT ({stem}): no usable pull after {retries} attempts -- "
                      "leaving the existing pull untouched.")
                return {"stem": stem, "prior_path": str(prior_path) if prior_path else None,
                        "prior_n": prior_n, "new_n": None, "skipped": "fetch-failed"}
            time.sleep(retry_wait_s)

    sol = gpd.read_parquet(out)
    # Overpass returns anything intersecting the bbox; the quadrat is the polygon --
    # same post-filter new_calibration_quadrat.py's own pull applies.
    sol = sol[sol.geometry.representative_point().within(poly)].reset_index(drop=True)
    if "area_m2" not in sol.columns:
        sol["area_m2"] = [geodesic_area_m2(g) for g in sol.geometry]
    new_n = len(sol)

    final_path = LABELS / f"{stem}_overpass_solar_{date.today().isoformat().replace('-', '')}.parquet"
    if final_path.exists():
        print(f"  {final_path.name} already exists (already refreshed today) -- not overwriting")
    else:
        sol.to_parquet(final_path)
        print(f"  wrote {final_path.name}: {new_n} installations "
              f"({'+' if new_n >= prior_n else ''}{new_n - prior_n} vs prior pull)")
    try:
        Path(out).unlink()
    except OSError:
        pass
    return {"stem": stem, "prior_path": str(prior_path) if prior_path else None,
            "prior_n": prior_n, "new_path": str(final_path), "new_n": new_n, "skipped": None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quadrat", action="append", default=None,
                     help="Refresh only this stem (repeatable); default: every active quadrat")
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--retry-wait-s", type=float, default=60.0)
    ap.add_argument("--sleep-between-s", type=float, default=5.0,
                     help="Pause between quadrats to stay modest on Overpass bandwidth")
    ap.add_argument("--dry-run", action="store_true", help="Report current pulls, fetch nothing")
    args = ap.parse_args()

    stems = args.quadrat or discover_active_stems()
    print(f"Refreshing {len(stems)} calibration area(s): {', '.join(stems)}")

    rows = []
    for i, stem in enumerate(stems):
        rows.append(refresh_one(stem, args.retries, args.retry_wait_s, args.dry_run))
        if not args.dry_run and i < len(stems) - 1:
            time.sleep(args.sleep_between_s)

    df = pd.DataFrame(rows)
    print("\n=== Summary ===")
    print(df.to_string(index=False))
    out_csv = Path("results/calibration_areas_refresh_log.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.assign(date=date.today().isoformat()).to_csv(
        out_csv, mode="a", header=not out_csv.exists(), index=False
    )
    print(f"\nAppended to {out_csv}")


if __name__ == "__main__":
    main()
