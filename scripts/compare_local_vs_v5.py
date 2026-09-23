"""Decide which checkpoint ships for a country: its localized retrain, or v5 zero-shot.

The owner's rule (2026-09-23): **whichever scores better on the held-out local region**,
with a tie going to the localized model. Both checkpoints are scored by
`earthpv.evaluate.evaluate` on the SAME val chips -- the country's `val_tiles`, chosen
from geography before training -- against the SAME Overpass labels. v5 has never seen
those chips (Vietnam is in no corpus; India's holdout is Gujarat's old Surat-Bharuch-
Vadodara val box, which v5 held out too), so neither side is scored in-sample.

Decision, in order:
  1. Pooled per-installation recall over installations >= 500 m2 (evaluate's 500-1000 and
     1000-inf buckets; its bucket edges do not fall at the 400 m2 chip threshold). A
     difference above RECALL_TIE decides it. Recall first because the whole product is
     recall-first (CLAUDE.md): a detector that misses mapped arrays cannot be rescued
     downstream, while a false positive is priced by `calibrate-candidates`.
  2. Otherwise pixel IoU, which does see false positives, if it differs by more than
     IOU_TIE.
  3. Otherwise the localized model.

Writes `results/<aoi>_checkpoint_decision.json` and prints the chosen checkpoint path as
the LAST line of stdout, so a shell caller can capture it with `tail -1`.

    python scripts/compare_local_vs_v5.py --aoi vietnam --local <ckpt> [--v5 <ckpt>]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

V5 = "data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt"
RECALL_TIE = 0.02
IOU_TIE = 0.01


def _summary(report) -> dict:
    big = report[report.bucket.isin(["500-1000", "1000-inf"])]
    n, d = int(big.installations.sum()), int(big.detected.sum())
    return {
        "pixel_iou": round(float(report.attrs["pixel_iou"]), 4),
        "pixel_f1": round(float(report.attrs["pixel_f1"]), 4),
        "installations_ge500": n,
        "detected_ge500": d,
        "recall_ge500": round(d / n, 4) if n else None,
        "by_bucket": report.to_dict(orient="records"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--local", required=True, help="the localized checkpoint")
    ap.add_argument("--v5", default=V5)
    a = ap.parse_args()

    from earthpv.evaluate import evaluate

    scores = {}
    for name, ckpt in (("local", a.local), ("v5", a.v5)):
        rep = evaluate(aoi=a.aoi, checkpoint=Path(ckpt), chips_dir=Path("data/chips"))
        scores[name] = {"checkpoint": ckpt, **_summary(rep)}
        print(f"{name}: {json.dumps({k: v for k, v in scores[name].items() if k != 'by_bucket'})}",
              flush=True)

    L, V = scores["local"], scores["v5"]
    if L["recall_ge500"] is None or V["recall_ge500"] is None:
        rule, winner = "no >=500 m2 installations in the val chips; IoU only", None
    else:
        dr = L["recall_ge500"] - V["recall_ge500"]
        if abs(dr) > RECALL_TIE:
            winner = "local" if dr > 0 else "v5"
            rule = f"recall_ge500 differs by {dr:+.4f} (> {RECALL_TIE})"
        else:
            winner, rule = None, f"recall_ge500 tied ({dr:+.4f})"
    if winner is None:
        di = L["pixel_iou"] - V["pixel_iou"]
        if abs(di) > IOU_TIE:
            winner = "local" if di > 0 else "v5"
            rule += f"; pixel IoU differs by {di:+.4f} (> {IOU_TIE})"
        else:
            winner = "local"
            rule += f"; pixel IoU tied ({di:+.4f}); tie goes to the localized model"

    out = {
        "aoi": a.aoi, "decided_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rule": "owner 2026-09-23: whichever scores better on the held-out local region; "
                "tie -> localized",
        "reason": rule, "winner": winner, "chosen_checkpoint": scores[winner]["checkpoint"],
        "scores": scores,
    }
    path = REPO / "results" / f"{a.aoi}_checkpoint_decision.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    print(f"winner={winner}: {rule} -> {path}", flush=True)
    print(scores[winner]["checkpoint"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
