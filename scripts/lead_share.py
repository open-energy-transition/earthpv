#!/usr/bin/env python
"""How much of a lead file is worth checking: where the real installations sit in it.

Silver asks for a third of a lead file's leads and of its very large outlines (blobs, above
the 100,000 m2 merge cap) to have a verdict before the model is retrained on them
(`atlas.LEAD_SHARE_MIN`, owner 2026-11-01). This measures where in a ranked lead file the
real installations are, in the three places a reference exists:

  * Pakistan: v3's lead file of 2026-07-16 (`data/predictions/pakistan/
    pakistan_pv_new_leads.geojson`), leads against the July pull that are within 100 m of
    OpenStreetMap solar in the 2026-10-25 pull, i.e. mapped since.
  * Yemen: the 2026-10-28 release file, leads mapped between the 2026-10-24 pull (backed up
    before v25) and the 2026-11-01 pull (OSM to 2026-10-31; the owner's week of mapping).
  * Germany: the 2026-11-01b release files, leads with a registered unit inside (MaStR,
    rooftop units >= 30 kWp and every ground unit commissioned by 2025-09-30), which does
    not depend on anyone having worked through the file.

"Mapped since" is a lower bound on real and can lean towards where people looked (in
Yemen, the top of the file); the register cannot. Writes results/lead_share/:
`by_decile.csv` (rank deciles of the leads), `top_share.csv` (share of the real leads in the
top k of the file), `by_size.csv` and `blobs.csv`.

    pixi run python scripts/lead_share.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from earthpv.export import new_lead_mask  # noqa: E402
from earthpv.postprocess import MAX_CANDIDATE_M2  # noqa: E402

OUT = ROOT / "results" / "lead_share"
RELEASE = Path("/home/tobi/earthpv_data")
SIZES = [0, 1_000, 5_000, 10_000, MAX_CANDIDATE_M2, np.inf]
SIZE_LABELS = ["<1k", "1k-5k", "5k-10k", "10k-100k", ">100k (blob)"]


def mapped_since(leads: gpd.GeoDataFrame, before: Path, after: Path) -> pd.Series:
    """True for a lead with no OSM solar within 100 m in `before` but some in `after`."""
    b = gpd.read_parquet(before)[["geometry"]]
    a = gpd.read_parquet(after)[["geometry"]]
    new_b = new_lead_mask(leads, b, min_distance_m=100.0)
    new_a = new_lead_mask(leads, a, min_distance_m=100.0)
    return pd.Series(new_b & ~new_a, index=leads.index)[new_b]


def register_hits(leads: gpd.GeoDataFrame) -> pd.Series:
    from mastr_p_unmapped import DEFAULT_DB, GROUND_ART, ROOFTOP_ART, mastr_points

    pts = pd.concat([mastr_points(DEFAULT_DB, ROOFTOP_ART, 30.0, "2025-09-30"),
                     mastr_points(DEFAULT_DB, GROUND_ART, 0.0, "2025-09-30")]).to_crs(3035)
    poly = leads[["geometry"]].to_crs(3035).reset_index()
    j = gpd.sjoin(poly, pts[["geometry"]], predicate="contains", how="inner")
    return pd.Series(leads.index.isin(j["index"].unique()), index=leads.index)


def sources() -> dict[str, gpd.GeoDataFrame]:
    out = {}
    pk = gpd.read_file(ROOT / "data/predictions/pakistan/pakistan_pv_new_leads.geojson")
    real = mapped_since(pk, ROOT / "data/labels/pakistan_overpass_solar.july2026.parquet",
                        ROOT / "data/labels/pakistan_overpass_solar.parquet")
    out["pakistan, mapped since (v3 file of 2026-07-16)"] = pk.loc[real.index].assign(real=real)
    ye = gpd.read_file(RELEASE / "pv_new_leads_2026-10-28/yemen_pv_new_leads.geojson")
    real = mapped_since(ye, RELEASE / "yemen_PRE_v25_20261101/yemen_overpass_solar.parquet",
                        ROOT / "data/labels/yemen_overpass_solar.parquet")
    out["yemen, mapped since (file of 2026-10-28)"] = ye.loc[real.index].assign(real=real)
    d = RELEASE / "pv_new_leads_2026-11-01b"
    de = pd.concat([gpd.read_file(d / "germany_pv_new_leads.geojson"),
                    gpd.read_file(d / "germany_pv_blob_leads.geojson")], ignore_index=True)
    out["germany, registered unit inside (file of 2026-11-01)"] = de.assign(real=register_hits(de))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    dec, top, size, blob = [], [], [], []
    for name, g in sources().items():
        g = g.copy()
        g["blob"] = g["area_m2"] > MAX_CANDIDATE_M2
        g["size"] = pd.cut(g["area_m2"], SIZES, labels=SIZE_LABELS, right=True)
        size.append(g.groupby("size", observed=True)["real"].agg(n="size", real="sum")
                    .assign(source=name).reset_index())
        b = g[g.blob]
        blob.append({"source": name, "n": len(b), "real": int(b["real"].sum()),
                     "share_real": round(float(b["real"].mean()), 3) if len(b) else None})
        leads = g[~g.blob].sort_values("rank_score", ascending=False).reset_index(drop=True)
        leads["decile"] = pd.qcut(np.arange(len(leads)), 10, labels=range(1, 11))
        dec.append(leads.groupby("decile", observed=True)["real"].agg(n="size", real="sum")
                   .assign(share_real=lambda t: (t.real / t.n).round(3), source=name)
                   .reset_index())
        cum = leads["real"].cumsum() / leads["real"].sum()
        for k in (0.1, 0.2, 0.25, 1 / 3, 0.5):
            i = int(round(k * len(leads)))
            below = leads.iloc[i:]
            top.append({"source": name, "top_share_of_file": round(k, 3),
                        "share_of_real_leads": round(float(cum.iloc[i - 1]), 3),
                        "real_rate_below": round(float(below["real"].mean()), 3),
                        "n_leads": len(leads), "n_real": int(leads["real"].sum())})
    pd.concat(dec).to_csv(OUT / "by_decile.csv", index=False)
    t = pd.DataFrame(top)
    t.to_csv(OUT / "top_share.csv", index=False)
    pd.concat(size).to_csv(OUT / "by_size.csv", index=False)
    rev = pd.read_csv(ROOT / "results/india_oversize_review/review.csv")
    blob.append({"source": "india, judged on imagery (census of the 30 largest and an "
                           "area-weighted sample, 2026-10-29)",
                 "n": len(rev), "real": int((rev["verdict"] == "pv").sum()),
                 "share_real": round(float((rev["verdict"] == "pv").mean()), 3)})
    pd.DataFrame(blob).to_csv(OUT / "blobs.csv", index=False)
    print(t[t.top_share_of_file.round(3) == 0.333].to_string(index=False))
    print(pd.DataFrame(blob).to_string(index=False))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
