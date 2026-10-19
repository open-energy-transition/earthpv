"""Upper ceiling per country from Ember's China solar-panel export data.

**Why.** Almost every solar panel installed since 2017 outside China, India and the United
States was made in China, and China's customs (GACC) publishes exports by destination
every month. Ember turns them into module capacity (value in USD divided by the month's
average module price) and publishes the result under CC-BY-4.0. Panels imported into a
country from January 2017 up to the end of an atlas's imagery window are therefore a
ceiling on what that atlas could have counted as built since 2017: some imported panels
sit in warehouses, are re-exported or have not been installed yet, and none imported later
can be on the imagery.

**Where it is not a ceiling**, and the atlas says so instead of calling it one:
countries whose fleet largely predates 2017 or is not supplied from China (India's
domestic manufacturing, Germany's and France's pre-2017 fleets and EU imports routed
through the Netherlands). `NOT_A_CEILING` carries the reason shown on the page.

    python scripts/ember_import_ceiling.py \\
        --csv data/external/ember_20261019/mart_solar_exports_full_release_monthly.csv

Writes configs/external/ember_china_panel_imports.yaml, which `atlas.build_evidence_atlas`
reads (one entry per AOI). Source:
https://ember-energy.org/data/china-solar-exports-data/
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "configs" / "external" / "ember_china_panel_imports.yaml"
URL = ("https://files.ember-energy.org/public-downloads/customs/outputs/"
       "mart_solar_exports_full_release_monthly.csv")

# AOI -> Ember's area name, where they differ from the AOI's division name.
EMBER_AREA = {"vietnam": "Viet Nam", "germany": "Germany"}
# Imagery window end for AOIs whose configs/aoi.yaml has no compose_window: Pakistan's
# published atlas states "Oct 2025 - Jun 2026"; Germany's carries no date at all.
CUTOFF_OVERRIDE = {"pakistan": "2026-06"}
NOT_A_CEILING = {
    "germany": "most of Germany's fleet was built before 2017, and much of the EU's "
               "Chinese supply arrives through the Netherlands",
    "france": "a large part of France's fleet was built before 2017, and much of the EU's "
              "Chinese supply arrives through the Netherlands",
    "india": "India makes a large share of its own panels and restricts Chinese ones for "
             "public projects",
    # Installed ~21.8 GW by Feb 2025 against 15.3 GW of direct imports from China by then.
    "poland": "much of Poland's Chinese supply arrives through other EU countries, and its "
              "installed fleet already exceeded its direct imports from China in early 2025",
}


def _cutoff(aoi: str, cfg: dict, data_end: str) -> str:
    if aoi in CUTOFF_OVERRIDE:
        end = CUTOFF_OVERRIDE[aoi]
    elif cfg.get("compose_window"):
        end = str(cfg["compose_window"][1])[:7]
    else:
        end = data_end
    return min(end, data_end)


def main() -> int:
    from earthpv.config import Settings

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", type=Path, required=True, help=f"Ember's monthly file ({URL})")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()

    d = pd.read_csv(a.csv)
    d = d[(d["Commodity type"] == "Panels") & (d["Area type"] == "Country or economy")]
    d["month"] = d["Date"].str[:7]
    data_end = d["month"].max()

    aois = Settings.load().aois
    out = {}
    for aoi, cfg in sorted(aois.items()):
        div = (cfg or {}).get("division") or {}
        if div.get("subtype") != "country":
            continue
        area = EMBER_AREA.get(aoi, div.get("name"))
        s = d[d["Area"] == area]
        if s.empty:
            print(f"  {aoi}: no Ember area named {area!r}, skipped")
            continue
        to = _cutoff(aoi, cfg, data_end)
        mwp = float(s.loc[s["month"] <= to, "Capacity (MW)"].sum())
        entry = {"ember_area": area, "from": s["month"].min(), "to": to,
                 "mwp": round(mwp, 1), "ceiling": aoi not in NOT_A_CEILING}
        if aoi in NOT_A_CEILING:
            entry["why_not"] = NOT_A_CEILING[aoi]
        out[aoi] = entry
        print(f"  {aoi:13s} {area:13s} {entry['from']}..{to}  {mwp:10,.0f} MWp  "
              f"{'ceiling' if entry['ceiling'] else 'NOT a ceiling'}")

    doc = {
        "source": "Ember, China's Solar PV Exports (China customs, GACC), CC-BY-4.0",
        "url": "https://ember-energy.org/data/china-solar-exports-data/",
        "data_through": data_end,
        "retrieved": datetime.date.today().isoformat(),
        "method": "Sum of Ember's monthly panel capacity (MW, export value / average module "
                  "price) to each country from the first month of the record to the end of "
                  "the atlas's imagery window.",
        "aois": out,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("# Written by scripts/ember_import_ceiling.py; do not edit by hand.\n"
                     + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
