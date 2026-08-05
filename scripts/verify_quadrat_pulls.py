"""Verify that each calibration quadrat's OSM pull is whole, not a silent partial answer.

Overpass can answer a query with HTTP 200, valid JSON and *fewer elements than exist* -- no
error, sometimes not even a `remark`. Measured 2026-08-05 on the Lahore DHA-5 box: one pull
returned 68 installations where the truth is ~5,700, inside a box already known to hold
1,034. A quadrat registered from such a pull looks perfectly normal on disk and quietly
poisons every negative in it, so "is this pull whole?" needs to be answerable at any time,
not only at registration.

Two independent checks, and which ones apply depends on the quadrat:

1. **Containment** (no network). If a retired predecessor exists in `data/labels/retired/`
   whose boundary the current one covers, then every installation the old pull held inside
   the old boundary must appear in the new pull -- OSM does not lose features, and the new
   box contains the old ground. This is the strongest check available and it costs nothing,
   which is the reason to prefer *extending* a quadrat over redrawing it from scratch.
2. **Live count** (network). Re-query the bbox and compare against the rows on disk,
   counting only elements that yield a geometry so the comparison is like-for-like. Takes
   the max over several attempts, since a single query is unreliable in both directions.

A brand-new quadrat has no predecessor, so check 2 is its only guard -- and when Overpass is
unavailable, it has none, which this reports as UNVERIFIABLE rather than as a pass.

    python scripts/verify_quadrat_pulls.py                 # all quadrats
    python scripts/verify_quadrat_pulls.py --quadrat sukkur_calib_2p63km2 --attempts 4
    python scripts/verify_quadrat_pulls.py --offline       # containment only, no network
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from earthpv.roofclf import _newest_solar, discover_quadrats, load_boundary  # noqa: E402

LABELS = Path("data/labels")
RETIRED = LABELS / "retired"


def live_count(bbox, attempts: int, timeout: int) -> int:
    """Max geometry-yielding element count over `attempts` queries; 0 if none succeeded."""
    from earthpv.overpass import _element_geometry, _query_bbox, _run_query

    q, best = _query_bbox(bbox, timeout), 0
    for _ in range(attempts):
        try:
            els = _run_query(q, timeout).get("elements", [])
            best = max(best, sum(1 for el in els
                                 if (g := _element_geometry(el)) is not None and not g.is_empty))
        except Exception:  # noqa: BLE001 -- an unavailable endpoint is not a failed check
            pass
    return best


def predecessors(stem: str) -> list[str]:
    """Retired quadrat stems sharing this one's place prefix (everything before `_calib_`)."""
    place = stem.split("_calib_")[0]
    return sorted({p.name.split("_boundary")[0]
                   for p in RETIRED.glob(f"{place}_calib_*_boundary.geojson")})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quadrat", action="append", default=[])
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--offline", action="store_true", help="containment check only")
    ap.add_argument("--out", default="results/quadrat_pull_verification.csv")
    args = ap.parse_args()

    stems = args.quadrat or discover_quadrats(LABELS)
    rows = []
    for stem in stems:
        bnd = load_boundary(LABELS / f"{stem}_boundary.geojson")
        pull = _newest_solar(stem, LABELS)
        cur = gpd.read_parquet(pull).to_crs(4326)
        r = {"quadrat": stem, "pull": pull.name, "rows": len(cur)}

        # --- check 1: containment against any retired predecessor
        missing, pred_used = None, ""
        for old_stem in predecessors(stem):
            ob = load_boundary(RETIRED / f"{old_stem}_boundary.geojson")
            op = sorted(RETIRED.glob(f"{old_stem}_overpass_solar*.parquet"))
            if not op or not bnd.covers(ob):
                continue
            old = gpd.read_parquet(op[-1]).to_crs(4326)
            oin = set(old[old.geometry.representative_point().within(ob)]["id"])
            missing = len(oin - set(cur["id"]))
            pred_used = f"{old_stem} ({len(oin)} inst)"
            break
        r["predecessor"] = pred_used
        r["missing_from_predecessor"] = missing

        # --- check 2: live count
        r["live_count"] = 0 if args.offline else live_count(bnd.bounds, args.attempts, args.timeout)
        ratio = (len(cur) / r["live_count"]) if r["live_count"] else None
        r["rows_over_live"] = round(ratio, 4) if ratio is not None else None

        if missing not in (None, 0):
            r["verdict"] = "FAIL_CONTAINMENT"
        elif r["live_count"] and ratio < 0.98:
            r["verdict"] = "FAIL_TRUNCATED"
        elif r["live_count"]:
            r["verdict"] = "OK_LIVE"
        elif missing == 0:
            # No network, but the predecessor check is strictly stronger evidence than a
            # count match anyway -- it identifies features, not just how many there are.
            r["verdict"] = "OK_CONTAINMENT"
        else:
            r["verdict"] = "UNVERIFIABLE"
        rows.append(r)
        print(f"  {stem:34s} {r['verdict']:17s} rows={len(cur):5d} live={r['live_count']:5d} "
              f"missing={missing if missing is not None else '-'}", flush=True)

    df = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print("\n" + df[["quadrat", "verdict", "rows", "live_count",
                     "missing_from_predecessor"]].to_string(index=False))
    bad = df[df.verdict.str.startswith("FAIL")]
    unv = df[df.verdict == "UNVERIFIABLE"]
    print(f"\n{len(df)} quadrats: {len(bad)} failing, {len(unv)} unverifiable -> {args.out}")
    if len(unv):
        print("UNVERIFIABLE means no evidence either way -- re-run when Overpass recovers: "
              + ", ".join(unv.quadrat))
    raise SystemExit(1 if len(bad) else 0)


if __name__ == "__main__":
    main()
