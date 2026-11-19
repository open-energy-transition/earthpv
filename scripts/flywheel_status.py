#!/usr/bin/env python
"""Where each country stands in the mapping flywheel, read from its review verdicts: is the
segmentation model's precision on its large new outlines fine, does it have a false-alarm
mode a retrain should target, and are there enough newly verified labels to ask the atlas's
maintainer for a mapping round and a retrain.

The verdicts measure **precision only**: of the model's new outlines (no OpenStreetMap solar
within 100 m) from 1 ha up, how many a person judged solar on the large installation review
page (scripts/oversize_review.py --kind large). They cannot measure recall, since an array
the model missed never becomes an outline to judge; recall is the held-out region's job
(scripts/compare_backbones.py, compare_local_vs_v5.py), and so is the stop rule below.

Per country and placement (rooftop, ground_adjacent, no_building), with at least
`MIN_VERDICTS` verdicts (below that the 90% interval is wider than +-0.15):

* **fine**: the Wilson 90% interval's lower end is at least `PRECISION_FINE` (0.8). At most
  one look in five is wasted, and the best countries sit at 0.9-1.0, so a retrain has little
  to gain on precision.
* **false alarms**: its upper end is below `PRECISION_POOR` (0.5). More than half the looks
  are wasted at the size where the model should be most reliable: a local look-alike it has
  not learned (bright roofs, pans, pools). Mapping cannot fix it, since OpenStreetMap does not
  record "not solar"; a retrain needs the not-solar verdicts as negative examples
  (scripts/verdict_hard_negatives.py, an experiment).
* otherwise **mixed**.

Blob verdicts (solar farm review, above the 100,000 m2 merge cap) are reported but never
decide a call: their share solar mostly reflects how many parks a country has and how bright
ground merges into one shape.

**New labels** are what a retrain would learn from that the last one did not: outlines judged
solar that OpenStreetMap still lacks (the confirmed leads, `release_leads.review_table`;
mapping them is the request) plus installations of `MIN_PV_AREA` and more in the current pull
whose last edit is later than the country's latest local training corpus (`chips_date`: the
chip index of data/chips/<aoi> or combined_<aoi>, or `CORPUS`; an edit to an older feature
counts too, so this leans high). The base is the pull's
installations of that size edited before the chips. At `NEW_LABEL_SHARE` (10%) or more the
call is **map, then retrain**: one retrain's result moves by as much as a backbone change from
epoch choice alone, so a smaller addition would be lost in that noise, and with ties going to
the local model the noise would ship. The 10% is a judgement, not a measurement; the owner
approved it with the 0.8 and 0.5 precision cut-offs on 2026-11-19.

**Stop retraining** when a retrained local model no longer beats the previous one on the
held-out region (installations found at matched pixel precision, paired test) and its
placements read fine here: this report cannot see that half, and says so.

`false alarms / 1,000 cells` estimates the not-solar outlines from 1 ha among the review
queue (judged not solar, plus each unjudged outline at its placement's measured rate) per
1,000 cells the model read: unlike precision it does not fall as a country's mapping fills
in, so it is the fairer number for comparing countries and turns.

    pixi run flywheel-status                 # every country with a review
    pixi run flywheel-status --aoi texas -v  # one country, with the per-placement rows

Writes results/flywheel_status/status.csv and placements.csv.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from earthpv.chips import MIN_PV_AREA  # noqa: E402
from earthpv.export import new_lead_mask  # noqa: E402
from earthpv.labels import geodesic_area_m2  # noqa: E402
from oversize_review import run_source  # noqa: E402
from release_leads import country_name, review_table  # noqa: E402

MIN_VERDICTS = 30
PRECISION_FINE = 0.8
PRECISION_POOR = 0.5
NEW_LABEL_SHARE = 0.10
Z90 = 1.645
PLACEMENTS = ("rooftop", "ground_adjacent", "no_building")
SHORT = {"rooftop": "roof", "ground_adjacent": "beside", "no_building": "open"}
OUT = ROOT / "results" / "flywheel_status"


def wilson(k: int, n: int, z: float = Z90) -> tuple[float, float]:
    """The Wilson score interval for k successes in n."""
    if n == 0:
        return np.nan, np.nan
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def placement_rows(aoi: str) -> list[dict]:
    """Precision on the large installation page, per placement, with its interval and call."""
    path = ROOT / "results" / f"{aoi}_large_review" / "review.csv"
    if not path.exists():
        return []
    r = pd.read_csv(path)
    if "placement" not in r:
        r["placement"] = "all"
    v = r["verdict"].fillna("")
    flag = r["flag"].fillna("") if "flag" in r else pd.Series("", index=r.index)
    rows = []
    for place in sorted(set(r["placement"].astype(str)), key=lambda p: (p not in PLACEMENTS, p)):
        m = r["placement"].astype(str).eq(place)
        pv, no = int((m & v.eq("pv")).sum()), int((m & v.eq("not_pv")).sum())
        n = pv + no
        lo, hi = wilson(pv, n)
        p = pv / n if n else np.nan
        unjudged = int((m & ~v.isin(["pv", "not_pv"])).sum())
        call = ("too few" if n < MIN_VERDICTS else "fine" if lo >= PRECISION_FINE
                else "false alarms" if hi < PRECISION_POOR else "mixed")
        rows.append({"aoi": aoi, "placement": place, "queue": int(m.sum()), "judged": n,
                     "pv": pv, "not_pv": no, "bright_roof": int((m & flag.eq("bright_roof")).sum()),
                     "precision": p, "lo90": lo, "hi90": hi, "call": call,
                     "est_false_alarms": no + unjudged * (1 - p) if n else np.nan})
    return rows


def blob_precision(aoi: str) -> tuple[int, int]:
    path = ROOT / "results" / f"{aoi}_oversize_review" / "review.csv"
    if not path.exists():
        return 0, 0
    v = pd.read_csv(path)["verdict"].fillna("")
    return int(v.eq("pv").sum()), int(v.isin(["pv", "not_pv"]).sum())


# The local training corpus behind a country's published model where it is not the newest of
# data/chips/<aoi> and data/chips/combined_<aoi> (later experiments on the same labels, or a
# model trained outside the country chain).
CORPUS = {"pakistan": "combined_pakistan_v16", "yemen": "combined_yemen_v25"}


def chips_date(aoi: str) -> pd.Timestamp | None:
    """When the country's latest local training corpus was cut (its chip index's mtime), the
    labels the last localization could have seen. A country that ships a general model (the
    Netherlands) is still measured against its local corpus: that is what a retrain adds to."""
    names = [CORPUS[aoi]] if aoi in CORPUS else [aoi, f"combined_{aoi}"]
    stamps = [(ROOT / "data" / "chips" / n / "index.parquet").stat().st_mtime for n in names
              if (ROOT / "data" / "chips" / n / "index.parquet").exists()]
    return pd.Timestamp(max(stamps), unit="s", tz="UTC") if stamps else None


def label_counts(aoi: str, src: dict) -> dict:
    """Installations of MIN_PV_AREA and up in the run's OSM pull, split at the corpus date,
    and the outlines judged solar that the pull still lacks (the confirmed leads)."""
    osm_path = ROOT / src["osm"]
    osm = gpd.read_parquet(osm_path)
    osm = osm[osm.geometry.notna() & ~osm.geometry.is_empty]
    area = (osm["area_m2"].to_numpy(float) if "area_m2" in osm
            else np.array([geodesic_area_m2(g) for g in osm.geometry]))
    big = osm[area >= MIN_PV_AREA]
    ts = (pd.to_datetime(big["osm_timestamp"], utc=True, errors="coerce")
          if "osm_timestamp" in big else pd.Series(pd.NaT, index=big.index))
    when = chips_date(aoi)
    out = {"osm_file": src["osm"], "osm_as_of": ts.max().date().isoformat() if ts.notna().any()
           else "", "chips_date": when.date().isoformat() if when is not None else "",
           "osm_ge_floor": len(big)}
    if when is not None and ts.notna().any():
        out["since_training"] = int((ts > when).sum())
        out["seen_in_training"] = int((ts <= when).sum())
    else:
        out["since_training"], out["seen_in_training"] = np.nan, np.nan

    cands = gpd.read_parquet(ROOT / src["pred"] / "candidates.parquet")
    rev = review_table(aoi, cands)
    pv = cands[rev["review_verdict"].eq("pv").to_numpy()]
    out["judged_solar"] = len(pv)
    out["confirmed"] = int(new_lead_mask(pv, osm[["geometry"]], 100.0).sum()) if len(pv) else 0
    return out


def country_call(rows: list[dict], labels: dict) -> tuple[str, str, float]:
    """The flywheel call and the next step, from the placement calls and the new labels."""
    calls = {r["placement"]: r["call"] for r in rows}
    measured = {p: c for p, c in calls.items() if c != "too few"}
    poor = [SHORT.get(p, p) for p, c in measured.items() if c == "false alarms"]
    base = labels.get("seen_in_training")
    new = labels["confirmed"] + (labels["since_training"]
                                 if not pd.isna(labels.get("since_training")) else 0)
    share = new / base if base and not pd.isna(base) else np.nan
    steps = []
    if not pd.isna(share) and share >= NEW_LABEL_SHARE:
        steps.append(f"map the {labels['confirmed']:,} confirmed leads, then retrain "
                     f"(+{share:.0%} labels)")
    elif labels["confirmed"]:
        steps.append(f"map the {labels['confirmed']:,} confirmed leads (+{share:.0%} labels: "
                     "not yet worth a retrain)" if not pd.isna(share) else
                     f"map the {labels['confirmed']:,} confirmed leads")
    if poor:
        steps.append(f"false alarms {'/'.join(poor)}: retrain needs negatives")
    if not measured:
        call = "unmeasured"
        steps.insert(0, "judge the large installation page (30+ per placement)")
    elif poor:
        call = "false alarms"
    elif all(c == "fine" for c in measured.values()):
        call = "precision fine"
        steps.append("check recall on the held-out region")
    else:
        call = "mixed"
    if not pd.isna(share) and share >= NEW_LABEL_SHARE:
        call += " + retrain"
    return call, "; ".join(steps), share


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--aoi", action="append", help="only these AOIs (default: every reviewed one)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print the per-placement rows")
    a = ap.parse_args()

    aois = a.aoi or sorted({p.parent.name.removesuffix(suffix)
                            for suffix in ("_large_review", "_oversize_review")
                            for p in (ROOT / "results").glob(f"*{suffix}/review.csv")})
    status, placements = [], []
    for aoi in aois:
        src = run_source(aoi)
        if not (ROOT / src["pred"] / "candidates.parquet").exists():
            print(f"  {aoi}: no candidates at {src['pred']}, skipped")
            continue
        rows = placement_rows(aoi)
        placements += rows
        try:
            labels = label_counts(aoi, src)
        except (FileNotFoundError, ValueError) as err:
            print(f"  {aoi}: labels unreadable ({err}), skipped")
            continue
        call, step, share = country_call(rows, labels)
        bpv, bn = blob_precision(aoi)
        prob = ROOT / src["pred"] / "prob"
        cells = len(list(prob.glob("*.tif"))) if prob.is_dir() else 0
        # Only where every placement in the queue has verdicts to estimate its rate from.
        fa = (sum(r["est_false_alarms"] for r in rows)
              if rows and not any(pd.isna(r["est_false_alarms"]) for r in rows) else np.nan)
        status.append({
            "aoi": aoi, "call": call, "next_step": step,
            **{f"precision_{SHORT.get(r['placement'], r['placement'])}":
               (f"{r['precision']:.2f} [{r['lo90']:.2f}-{r['hi90']:.2f}] n={r['judged']}"
                if r["judged"] else "") for r in rows},
            "blob_solar": f"{bpv}/{bn}" if bn else "",
            "false_alarms_per_1000_cells": round(1000 * fa / cells, 1) if cells else np.nan,
            "cells": cells, "new_label_share": share,
            **labels,
        })

    if not status:
        print("no country with a review")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    s = pd.DataFrame(status)
    s.to_csv(OUT / "status.csv", index=False)
    pd.DataFrame(placements).to_csv(OUT / "placements.csv", index=False)

    print(f"Precision of the model's new outlines from 1 ha (large installation review), share "
          f"judged solar with its 90% interval; calls need {MIN_VERDICTS}+ verdicts: fine if "
          f"the interval starts at {PRECISION_FINE} or more, false alarms if it ends below "
          f"{PRECISION_POOR}. New labels: confirmed leads + installations of "
          f"{MIN_PV_AREA:.0f} m2 and up mapped since the training chips, over those before.\n")
    for _, r in s.iterrows():
        prec = "  ".join(f"{SHORT[p]} {r[f'precision_{SHORT[p]}']}" for p in PLACEMENTS
                         if f"precision_{SHORT[p]}" in r and isinstance(
                             r[f"precision_{SHORT[p]}"], str) and r[f"precision_{SHORT[p]}"])
        new = (f"+{r['new_label_share']:.0%}" if not pd.isna(r["new_label_share"])
               else "? (no corpus date or no edit dates in the pull)")
        print(f"{country_name(r['aoi']):13s} {r['call']}")
        print(f"    {prec or 'large installation page not judged'}"
              + (f"; blobs solar {r['blob_solar']}" if r["blob_solar"] else ""))
        print(f"    false alarms from 1 ha per 1,000 cells: "
              f"{r['false_alarms_per_1000_cells'] if not pd.isna(r['false_alarms_per_1000_cells']) else '-'}"
              f"; new labels {new} ({r['confirmed']:,} confirmed + "
              f"{f'{int(r.since_training):,}' if not pd.isna(r['since_training']) else '?'} mapped since "
              f"{r['chips_date'] or '?'}, over {f'{int(r.seen_in_training):,}' if not pd.isna(r['seen_in_training']) else '?'})")
        print(f"    next: {r['next_step'] or '-'}")
    if a.verbose:
        print()
        print(pd.DataFrame(placements).round(2).to_string(index=False))
    print(f"\nRecall is not measured here: before stopping, compare a retrained model with the "
          f"last one on the held-out region. Written {dt.date.today()}: "
          f"{(OUT / 'status.csv').relative_to(ROOT)}, {(OUT / 'placements.csv').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
