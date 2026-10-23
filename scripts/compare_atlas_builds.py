"""Side-by-side totals of evidence-atlas builds, read from each page's own `pv` data block.

    pixi run python scripts/compare_atlas_builds.py published=<a.html> soft=<b.html> ...
"""

from __future__ import annotations

import json
import re
import sys


def load(path: str) -> dict:
    html = open(path).read()
    m = re.search(r'<script[^>]*id="pv"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1))["totals"]


def main() -> None:
    builds = dict(a.split("=", 1) for a in sys.argv[1:])
    tot = {k: load(v) for k, v in builds.items()}
    rows = [("Best estimate", "mwp_best"), ("  90% CI", "mwp_best_ci"),
            ("Verified (floor)", "mwp_verified"), ("  90% CI", "mwp_verified_ci"),
            ("sub-400 roofclf (Best)", "small_central"), ("sub-400 AND-gate (floor)", "small_low"),
            ("rooftop, all", "mwp_roof"), ("ground-mount, all", "mwp_ground"),
            ("cells where roofclf replaces seg. rooftop", "n_domain_cells"),
            ("cells floored at Verified", "n_cells_best_floored")]
    comps = sorted({c for t in tot.values() for c in t["uncertainty"]["components"]})
    w = max(len(k) for k in builds) + 2
    print(f"{'':44}" + "".join(f"{k:>{max(w, 16)}}" for k in builds))
    for lab, key in rows:
        vals = []
        for t in tot.values():
            v = t.get(key)
            vals.append(f"{v[0]:,.0f}-{v[1]:,.0f}" if isinstance(v, list) else f"{v:,.1f}"
                        if isinstance(v, float) else f"{v}")
        print(f"{lab:44}" + "".join(f"{v:>{max(w, 16)}}" for v in vals))
    print("\nBest components (MWp, from the uncertainty block):")
    for c in comps:
        vals = [t["uncertainty"]["components"].get(c, {}).get("mwp", float("nan")) for t in tot.values()]
        print(f"  {c:42}" + "".join(f"{v:>{max(w, 16)},.1f}" for v in vals))
    ic = next(iter(tot.values())).get("import_ceiling", {}).get("mwp")
    if ic:
        print(f"\nBest as share of the {ic:,.0f} MWp import ceiling: " + ", ".join(
            f"{k} {100 * t['mwp_best'] / ic:.0f}%" for k, t in tot.items()))


if __name__ == "__main__":
    main()
