"""India's evidence atlas against the MNRE register, state by state.

MNRE's state-wise installed solar capacity, republished monthly by MoSPI's eSankhyiki
(https://esankhyiki.mospi.gov.in/macroindicators?product=mnre, dataset MNRE), is India's
official register for this page: MW per state and month since 2020, in four categories
(ground-mounted, rooftop including PM Surya Ghar, the solar component of hybrid plants,
off-grid/KUSUM). It is fetched through MoSPI's own MCP server (`mcp.mospi.gov.in`, the access
route the portal documents for machines; the portal's REST API needs TLS legacy renegotiation).

    python scripts/validate_india_mnre.py fetch      # -> results/india_mnre_validation/
    python scripts/validate_india_mnre.py compare

What is compared with what, because the two do not count the same things:

  * **Ground**: the atlas's Best (and Verified) minus its rooftop part, against registered
    ground-mounted plus the hybrid plants' solar component, both utility PV on the ground.
  * **Rooftop**: the atlas's rooftop part (mapped OSM rooftop counted from the map, plus the
    model's rooftop arrays) against registered rooftop. Most registered rooftop is household
    systems of a few kW, below what a 10 m pixel can see, so this is a coverage figure.
  * **Off-grid/KUSUM** is shown apart: solar pumps of a few kW are invisible, KUSUM-A plants of
    0.5 to 2 MW on farmland are not.

The register is dated by month and the imagery is a November to March median, so the
comparison is made at the window's centre (January 2026) and bracketed by its ends. Registered
utility capacity in India is mostly quoted AC; the atlas converts site area at 0.05 kWp/m2,
which India's own capacity-tagged parks put at 0.045 per AC kW, so a ratio near 1.1 on ground
is agreement, not overstatement.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "results" / "india_mnre_validation"
MCP = "https://mcp.mospi.gov.in/"
SOLAR = 1
CATEGORY = {1: "ground", 2: "rooftop", 3: "hybrid_solar", 4: "offgrid_kusum", 5: "total"}
# Pre-merger union territories the register still lists, and its unallocated row.
DROP_STATES = {"All India", "Dadar and Nagar Haveli", "Daman and Diu", "Others"}
CENTRE, BRACKET = (2026, 1), ((2025, 11), (2026, 3))
# India's capacity-tagged parks: site area per AC kW (docs/results/india.md, the land constant).
KWP_LAND_PER_KWAC = 0.05 / 0.045


def _mcp(tool: str, arguments: dict) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": arguments}}).encode()
    req = urllib.request.Request(MCP, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "User-Agent": "earthpv (research; github.com earthpv)"})
    raw = urllib.request.urlopen(req, timeout=180).read().decode()
    msg = next(json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: "))
    if "error" in msg:
        raise RuntimeError(msg["error"])
    text = "".join(c.get("text", "") for c in msg["result"]["content"])
    return json.loads(text)


def cmd_fetch(a) -> int:
    import pandas as pd

    # One year per query, 100 rows a page: the upstream API answers 400 to a larger page or a
    # list of years.
    rows = []
    for year in a.years.split(","):
        page = 1
        while True:
            r = _mcp("get_data", {"dataset": "MNRE", "filters": {
                "type_of_renewable_energy_code": SOLAR, "year": year, "limit": 100, "page": page}})
            if "error" in r:
                raise RuntimeError(f"{year} page {page}: {r['error']}")
            rows += r.get("data") or []
            if page >= int(r.get("meta_data", {}).get("totalPages", 1)):
                break
            page += 1
    df = pd.DataFrame(rows)
    df["category"] = df["category"].str.strip()
    df["value_mw"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.drop(columns=["value"])
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "mnre_solar_state_monthly.csv", index=False)
    (OUT / "mnre_source.json").write_text(json.dumps({
        "source": "MNRE via MoSPI eSankhyiki (dataset MNRE, type_of_renewable_energy_code 1)",
        "url": "https://esankhyiki.mospi.gov.in/macroindicators?product=mnre",
        "access": f"MCP server {MCP}, tool get_data", "years": a.years,
        "fetched": pd.Timestamp.now().isoformat(timespec="seconds"), "n_rows": int(len(df)),
        "unit": "MW installed capacity", "frequency": "monthly"}, indent=2))
    print(f"{len(df)} rows ({df.year.min()}-{df.year.max()}, {df.state.nunique()} states) -> "
          f"{OUT / 'mnre_solar_state_monthly.csv'}")
    return 0


def _key(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def register_at(df, year: int, month: int):
    """One column per category, one row per state, at the end of `month`."""
    import calendar

    m = df[(df.year == year) & (df.month == calendar.month_name[month])]
    t = m.pivot_table(index="state", columns="category", values="value_mw", aggfunc="sum")
    names = {"Ground Mounted Solar Power": "ground", "Rooftop Solar Power (including PM Surya Ghar Yojna)":
             "rooftop", "Hybrid Solar Component": "hybrid_solar", "Off-Grid Solar Power/KUSUM":
             "offgrid_kusum", "Solar Power Total": "total"}
    t = t.rename(columns=names).reindex(columns=list(names.values())).fillna(0.0)
    t["utility_ground"] = t["ground"] + t["hybrid_solar"]
    return t


def atlas_by_state(aoi: str = "india"):
    """Verified, Best and their rooftop part per state, from the published page and its inputs."""
    import re

    import geopandas as gpd
    import numpy as np
    import pandas as pd

    from earthpv import capacity_calibration as cc
    from earthpv.atlas import _apply_screen_credit, osm_match_distance_m
    from earthpv.density import capacity_relevant_candidates, load_osm_screen, load_oversize_admission
    from earthpv.export import new_lead_mask
    from earthpv.labels import dissolve_overlapping

    page = (REPO / f"results/{aoi}_pv_evidence_atlas.html").read_text()
    data = json.loads(re.search(r'<script id="pv" type="application/json">(.*?)</script>',
                                page, re.S).group(1))
    prov = pd.DataFrame(data["provinces"]).set_index("name")[["mwp_verified", "mwp_best", "mwp_large"]]

    dens = REPO / f"data/predictions/{aoi}/density"
    regions = gpd.read_parquet(dens / "regions.geoparquet")
    regions = regions[regions.level == "region"][["name", "est_mwp_rc_roof", "geometry"]]
    table = cc.load_table(cc.default_table_path(aoi))
    cands = gpd.read_parquet(REPO / f"data/predictions/{aoi}/candidates.parquet")
    cands, _ = capacity_relevant_candidates(cands, osm_screen=load_osm_screen(aoi),
                                            oversize_admission=load_oversize_admission(aoi, cands, table))
    osm = _apply_screen_credit(dissolve_overlapping(
        gpd.read_parquet(REPO / f"data/labels/{aoi}_national_osm_solar.parquet"), group_col="placement"))
    roof = osm[osm.placement == "rooftop"].copy()
    roof["mw"] = roof.area_m2 * cc.DEFAULT_KWP_PER_M2_MODULE / 1000.0
    roof["matched"] = ~new_lead_mask(roof, cands, min_distance_m=osm_match_distance_m(table))
    pts = gpd.GeoDataFrame(roof[["mw", "matched"]], geometry=roof.geometry.representative_point(),
                           crs=roof.crs)
    j = gpd.sjoin(pts, regions[["name", "geometry"]], predicate="within", how="left")
    osm_roof = j.groupby("name")["mw"].sum()
    osm_roof_unmatched = j[~j.matched].groupby("name")["mw"].sum()
    seg_roof = regions.set_index("name")["est_mwp_rc_roof"]
    out = prov.join(pd.DataFrame({"osm_roof": osm_roof, "osm_roof_unmatched": osm_roof_unmatched,
                                  "seg_roof": seg_roof}), how="left").fillna(0.0)
    # Best's rooftop part, as `build_evidence_atlas` composes it before its per-cell floor:
    # rooftop OSM no candidate found, counted from the map, plus the model's rooftop arrays;
    # never below the mapped rooftop that Verified already holds.
    out["best_roof"] = np.maximum(out.osm_roof, out.osm_roof_unmatched + out.seg_roof)
    out["best_ground"] = out.mwp_best - out.best_roof
    out["verified_ground"] = out.mwp_verified - out.osm_roof
    return out


def cmd_compare(a) -> int:
    import numpy as np
    import pandas as pd
    from scipy.stats import spearmanr

    df = pd.read_csv(OUT / "mnre_solar_state_monthly.csv")
    centre = register_at(df, *CENTRE)
    lo, hi = (register_at(df, *ym) for ym in BRACKET)
    ours = atlas_by_state()
    reg = centre[~centre.index.isin(DROP_STATES)].copy()
    reg["key"] = [_key(n) for n in reg.index]
    ours["key"] = [_key(n) for n in ours.index]
    m = ours.reset_index().merge(reg.reset_index().rename(columns={"state": "register_state"}),
                                 on="key", how="outer", indicator=True)
    unmatched = m[m._merge != "both"]
    if len(unmatched):
        print("names matched on one side only:", unmatched[["name", "register_state"]].to_dict("records"))
    m = m[m._merge == "both"].drop(columns="_merge")
    for col, src in (("utility_ground_nov", lo), ("utility_ground_mar", hi)):
        m[col] = m.register_state.map(src["utility_ground"])
    m["ratio_ground_best"] = m.best_ground / m.utility_ground.replace(0, np.nan)
    m["ratio_ground_verified"] = m.verified_ground / m.utility_ground.replace(0, np.nan)
    m["ratio_roof"] = m.best_roof / m.rooftop.replace(0, np.nan)
    m["ratio_total_best"] = m.mwp_best / m.total.replace(0, np.nan)
    cols = ["name", "mwp_verified", "mwp_best", "verified_ground", "best_ground", "best_roof",
            "utility_ground", "utility_ground_nov", "utility_ground_mar", "ground", "hybrid_solar",
            "rooftop", "offgrid_kusum", "total", "ratio_ground_best", "ratio_ground_verified",
            "ratio_roof", "ratio_total_best"]
    m = m[cols].sort_values("utility_ground", ascending=False)
    m.round(3).to_csv(OUT / "comparison_by_state.csv", index=False)

    nat = {k: float(m[k].sum()) for k in ("mwp_verified", "mwp_best", "verified_ground", "best_ground",
                                          "best_roof", "utility_ground", "utility_ground_nov",
                                          "utility_ground_mar", "ground", "hybrid_solar", "rooftop",
                                          "offgrid_kusum", "total")}
    all_india = centre.loc["All India"] if "All India" in centre.index else None
    big = m[m.utility_ground >= a.min_state_mw]
    rho_g = spearmanr(big.best_ground, big.utility_ground).statistic
    rho_v = spearmanr(big.verified_ground, big.utility_ground).statistic
    logerr = np.abs(np.log(big.ratio_ground_best.clip(lower=1e-3)))
    summary = {
        "register_month": f"{CENTRE[0]}-{CENTRE[1]:02d}", "bracket": [f"{y}-{mo:02d}" for y, mo in BRACKET],
        "national_mw": {k: round(v, 1) for k, v in nat.items()},
        "register_all_india_row": None if all_india is None else {k: round(float(v), 1) for k, v in all_india.items()},
        "ratio_ground_best": round(nat["best_ground"] / nat["utility_ground"], 3),
        "ratio_ground_best_ac": round(nat["best_ground"] / KWP_LAND_PER_KWAC / nat["utility_ground"], 3),
        "ratio_ground_verified": round(nat["verified_ground"] / nat["utility_ground"], 3),
        "ratio_roof": round(nat["best_roof"] / nat["rooftop"], 3),
        "ratio_total_best": round(nat["mwp_best"] / nat["total"], 3),
        "states_compared": int(len(big)), "min_state_mw": a.min_state_mw,
        "spearman_ground_best": round(float(rho_g), 3), "spearman_ground_verified": round(float(rho_v), 3),
        "median_abs_log_ratio_ground": round(float(np.median(logerr)), 3),
        "states_within_x1p5": int(((big.ratio_ground_best > 1 / 1.5) & (big.ratio_ground_best < 1.5)).sum()),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    pd.set_option("display.width", 200)
    print(m[["name", "verified_ground", "best_ground", "utility_ground", "ratio_ground_verified",
             "ratio_ground_best", "best_roof", "rooftop", "ratio_roof"]].round(2).head(25).to_string(index=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--years", default="2025,2026")
    c = sub.add_parser("compare")
    c.add_argument("--min-state-mw", type=float, default=100.0,
                   help="states with at least this much registered utility ground PV enter the "
                        "rank correlation and the error spread")
    a = ap.parse_args()
    return cmd_fetch(a) if a.cmd == "fetch" else cmd_compare(a)


if __name__ == "__main__":
    raise SystemExit(main())
