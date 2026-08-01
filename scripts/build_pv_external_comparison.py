"""Compare our PV estimate against three external, non-imagery-derived proxies:

1. **TransitionZero** (`data/estimated_rooftop_solar_capacity.json`) -- another modelled
   rooftop-solar estimate, in units that don't match ours (confirmed 2026-07-16, see
   `docs/methods/density.md` / memory). Compared as percent-of-national-total per spatial
   unit, which sidesteps the unit mismatch and asks "do the two models agree on where PV
   concentrates" rather than "whose number is bigger."
2. **VIIRS annual nighttime-lights radiance** (2023 composite, 500 m, Zenodo mirror of the
   Earth Observation Group's public-domain product) -- a proxy for electrification/urban
   activity. Solar panels aren't visible in this data; the question is whether PV density
   tracks the same underlying "how built-up and lit is this place" signal.
3. **Meta / Data for Good's Relative Wealth Index** (HDX, ~2.4 km tiles) -- a proxy for
   relative household wealth. Tests whether PV adoption in this model's output tracks
   affordability, an independent (non-satellite-imagery) signal.

Neither nightlights nor RWI existed anywhere in this codebase before this script; both are
fetched fresh from public, no-login sources (Zenodo CC-BY, HDX). This is a standalone,
scratch-style analysis in the spirit of `scripts/pv_density_vs_transitionzero.py` -- not a
pipeline stage -- so it re-downloads/re-derives everything each run rather than caching to
`data/`.

Usage:
  .pixi/envs/default/bin/python scripts/build_pv_external_comparison.py [--skip-download]

Without --skip-download it fetches ~62 MB (VIIRS) + ~20 MB (RWI) into a temp dir; pass
--skip-download to reuse files already placed at the paths printed by a prior run.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds, transform as win_transform
from scipy import stats
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
DENSITY_DIR = ROOT / "data/predictions/pakistan/density"
TZ_PATH = ROOT / "data/estimated_rooftop_solar_capacity.json"
OUT = ROOT / "results" / "pakistan_pv_external_comparison.html"
SIBLING = ROOT / "scripts" / "build_pakistan_pv_overview.py"

VIIRS_URL = ("https://zenodo.org/records/17294744/files/"
             "nightlights.average_viirs.v21_m_500m_s_20230101_20231231_go_epsg4326_v20250904.tif?download=1")
RWI_URL = ("https://data.humdata.org/dataset/76f2a2ea-ba50-40f5-b79c-db95d668b843/resource/"
           "977923ab-c65a-4203-b216-e4b7483d56a5/download/ind_pak_relative_wealth_index.csv")

CACHE_DIR = Path(tempfile.gettempdir()) / "earthpv_external_comparison"
VIIRS_PATH = CACHE_DIR / "viirs_2023_global_500m.tif"
RWI_PATH = CACHE_DIR / "ind_pak_relative_wealth_index.csv"


def fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached: {dest} ({dest.stat().st_size:,} bytes)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url} -> {dest}")
    urllib.request.urlretrieve(url, dest)
    print(f"  got {dest.stat().st_size:,} bytes")


# ---------------------------------------------------------------- data prep

def zonal_ntl(grid: gpd.GeoDataFrame) -> pd.Series:
    minx, miny, maxx, maxy = grid.total_bounds
    pad = 0.05
    with rasterio.open(VIIRS_PATH) as ds:
        win = from_bounds(minx - pad, miny - pad, maxx + pad, maxy + pad, ds.transform)
        win = win.round_offsets().round_lengths()
        arr = ds.read(1, window=win).astype(np.float64)
        crop_transform = win_transform(win, ds.transform)
    means = np.zeros(len(grid))
    inv = ~crop_transform
    for i, row in enumerate(grid.itertuples()):
        c0, r0 = inv * (row.lon0, row.lat0 + 0.1)
        c1, r1 = inv * (row.lon0 + 0.1, row.lat0)
        c0, c1 = sorted((int(round(c0)), int(round(c1))))
        r0, r1 = sorted((int(round(r0)), int(round(r1))))
        c0, r0 = max(c0, 0), max(r0, 0)
        c1, r1 = min(c1, arr.shape[1]), min(r1, arr.shape[0])
        means[i] = float(arr[r0:r1, c0:c1].mean()) if c1 > c0 and r1 > r0 else 0.0
    return pd.Series(means, index=grid.index)


def zonal_rwi(grid: gpd.GeoDataFrame) -> tuple[pd.Series, pd.Series]:
    minx, miny, maxx, maxy = grid.total_bounds
    df = pd.read_csv(RWI_PATH)
    df = df[(df.longitude >= minx - 0.2) & (df.longitude <= maxx + 0.2) &
            (df.latitude >= miny - 0.2) & (df.latitude <= maxy + 0.2)]
    pts = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs="EPSG:4326")
    hits = gpd.sjoin(pts, grid[["geometry"]].reset_index().rename(columns={"index": "grid_idx"}),
                      predicate="within", how="inner")
    agg = hits.groupby("grid_idx").rwi.agg(["mean", "count"])
    return agg["mean"].reindex(grid.index), agg["count"].reindex(grid.index).fillna(0)


def corr_block(x: np.ndarray, y: np.ndarray) -> dict:
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    pear = stats.pearsonr(x, y)
    spear = stats.spearmanr(x, y)
    return {"n": int(len(x)), "pearson": round(float(pear.statistic), 4),
            "spearman": round(float(spear.statistic), 4)}


def partial_corr(y: np.ndarray, x: np.ndarray, z: np.ndarray) -> float:
    Z = np.column_stack([np.ones_like(z), z])
    by, *_ = np.linalg.lstsq(Z, y, rcond=None)
    bx, *_ = np.linalg.lstsq(Z, x, rcond=None)
    r, _ = stats.pearsonr(x - Z @ bx, y - Z @ by)
    return round(float(r), 4)


def simplify_rings(geom, tol: float) -> list:
    """Flatten a (Multi)Polygon to a plain list of rings (each a list of [lon, lat]
    points), which is what the JS ringPath() helper iterates over directly."""
    gi = geom.simplify(tol, preserve_topology=True).__geo_interface__
    if gi["type"] == "Polygon":
        return list(gi["coordinates"])
    if gi["type"] == "MultiPolygon":
        rings = []
        for poly in gi["coordinates"]:
            rings.extend(poly)
        return rings
    return []


def prepare_data() -> dict:
    grid = gpd.read_parquet(DENSITY_DIR / "grid.geoparquet").reset_index(drop=True)
    meta = json.loads((DENSITY_DIR / "meta.json").read_text())
    total_rc = meta["total_est_mwp_rc"]
    grid["our_share_pct"] = grid.est_mwp_rc / total_rc * 100.0

    print("Zonal nightlights...")
    grid["ntl_mean"] = zonal_ntl(grid)
    print("Zonal RWI...")
    rwi_mean, rwi_n = zonal_rwi(grid)
    grid["rwi_mean"] = rwi_mean
    grid["rwi_n"] = rwi_n.fillna(0)

    log_mwp = np.log1p(grid.est_mwp_rc.values)
    log_roof = np.log1p(grid.roof_area_m2.values)
    log_ntl = np.log1p(grid.ntl_mean.values)

    ntl_stats = corr_block(log_ntl, log_mwp)
    ntl_stats["partial_vs_roof_area"] = partial_corr(log_mwp, log_ntl, log_roof)

    covered = grid[grid.rwi_n > 0]
    rwi_stats = corr_block(covered.rwi_mean.values, np.log1p(covered.est_mwp_rc.values))
    rwi_stats["partial_vs_roof_area"] = partial_corr(
        np.log1p(covered.est_mwp_rc.values), covered.rwi_mean.values, np.log1p(covered.roof_area_m2.values))
    rwi_stats["n_covered"] = int(len(covered))
    rwi_stats["n_total"] = int(len(grid))

    print("TransitionZero share-diff...")
    raw = json.loads(TZ_PATH.read_text())
    tz_rows = []
    for r in raw:
        geom = shape(json.loads(r["geojson"]))
        val = float(r["value"][0]) if r["value"] else 0.0
        tz_rows.append({"name": r["name"], "value": val, "geometry": geom})
    tz = gpd.GeoDataFrame(tz_rows, geometry="geometry", crs="EPSG:4326")
    tz["tz_share_pct"] = tz.value / tz.value.sum() * 100.0
    reps = gpd.GeoDataFrame({"our_share_pct": grid.our_share_pct},
                             geometry=gpd.points_from_xy(grid.lon_center, grid.lat_center), crs="EPSG:4326")
    hits = gpd.sjoin(reps, tz[["name", "geometry"]], predicate="within", how="left")
    our_by_hex = hits.dropna(subset=["name"]).groupby("name").our_share_pct.sum()
    tz = tz.set_index("name")
    tz["our_share_pct"] = our_by_hex.reindex(tz.index).fillna(0.0)
    tz["share_diff_pp"] = tz.our_share_pct - tz.tz_share_pct
    matched = int((our_by_hex.reindex(tz.index).fillna(0.0) > 0).sum())
    tz_stats = corr_block(tz.tz_share_pct.values, tz.our_share_pct.values)
    tz_stats.update({"n_hex": len(tz), "matched": matched,
                      "diff_min": round(float(tz.share_diff_pp.min()), 4),
                      "diff_max": round(float(tz.share_diff_pp.max()), 4)})

    regions = gpd.read_parquet(DENSITY_DIR / "regions.geoparquet")
    provinces = regions[regions.level == "region"]

    province_rings = [{"name": row["name"], "rings": simplify_rings(row.geometry, 0.01)}
                       for _, row in provinces.iterrows()]

    cells = [{
        "lon0": round(row.lon0, 4), "lat0": round(row.lat0, 4),
        "mwp": round(float(row.est_mwp_rc), 4), "share": round(float(row.our_share_pct), 6),
        "ntl": round(float(row.ntl_mean), 4),
        "rwi": (round(float(row.rwi_mean), 4) if row.rwi_n > 0 else None),
        "nb": int(row.n_buildings),
    } for row in grid.itertuples()]

    tz_features = [{
        "name": name, "rings": simplify_rings(row.geometry, 0.002),
        "tz_pct": round(float(row.tz_share_pct), 4), "our_pct": round(float(row.our_share_pct), 4),
        "diff_pp": round(float(row.share_diff_pp), 4),
    } for name, row in tz.iterrows()]

    prov_table = [{"name": row["name"], "mwp": round(float(row.est_mwp_rc), 1),
                   "n_buildings": int(row.n_buildings)}
                  for _, row in provinces.sort_values("est_mwp_rc", ascending=False).iterrows()]

    return {
        "bounds": grid.total_bounds.tolist(),
        "total_rc": total_rc,
        "provinces": province_rings,
        "prov_table": prov_table,
        "cells": cells,
        "tz": tz_features,
        "stats": {"tz": tz_stats, "ntl": ntl_stats, "rwi": rwi_stats},
    }


# -------------------------------------------------------------------- HTML

def _slice(text: str, start: str, end: str, what: str) -> str:
    try:
        i = text.index(start)
        j = text.index(end, i)
    except ValueError as exc:  # pragma: no cover - operator-facing
        raise ValueError(f"could not slice {what} out of {SIBLING.name}: markers moved") from exc
    return text[i:j]


def shared_css() -> str:
    src = SIBLING.read_text()
    return _slice(src, "<style>", "</style>", "the CSS block") + "</style>"


TEMPLATE = r"""<meta charset="utf-8">
<title>Pakistan PV vs three external proxies</title>
<script id="data" type="application/json">__DATA_JSON__</script>

__CSS__
<style>
  .scatter text { fill: var(--muted); font-family: var(--font-mono); }
  .scatter .pt { fill: var(--accent); opacity: 0.55; }
  .scatter .axis { stroke: var(--hair); stroke-width: 1; }
  .corrbadge { display: inline-flex; gap: 14px; margin-top: 10px; }
  .corrbadge .c { background: var(--panel-2); border: 1px solid var(--card-ring); border-radius: 10px;
    padding: 8px 12px; }
  .corrbadge .c .v { font-family: var(--font-mono); font-size: 17px; font-weight: 700; color: var(--accent); }
  .corrbadge .c .k { font-family: var(--font-mono); font-size: 9.5px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.05em; margin-top: 2px; }
</style>

<button class="theme-btn" id="themeBtn" type="button" aria-label="Toggle light or dark theme">Dark mode</button>

<div class="wrap">
  <header>
    <p class="eyebrow">EarthPV &middot; Sentinel-2 &middot; TerraMind &middot; TransitionZero &middot; VIIRS &middot; Meta Data for Good</p>
    <h1>Does our PV map agree with everyone else's proxies?</h1>
    <p class="lede">Three external, independently-produced layers, none derived from this
    project's own imagery or model, checked against our per-cell PV capacity
    (<code>est_mwp_rc</code>, the recall-corrected headline metric, &ge;400 m&sup2; scope).
    <b>TransitionZero</b> is another rooftop-solar model &mdash; a check of whether two
    independent models place PV in the same places. <b>Night lights</b> (VIIRS) and
    <b>Relative Wealth Index</b> (Meta) aren't solar products at all &mdash; they're proxies
    for electrification and household wealth, so agreement with them is a plausibility check
    on <em>where PV should be</em>, not a validation of <em>how much</em> is there.</p>
  </header>

  <div class="kpis">
    <div class="kpi"><div class="v" id="kTz">0</div>
      <div class="k">Rank correlation with TransitionZero's own spatial share</div></div>
    <div class="kpi"><div class="v" id="kNtl">0</div>
      <div class="k">Log-log correlation with nighttime-lights radiance</div></div>
    <div class="kpi"><div class="v" id="kRwi">0</div>
      <div class="k">Correlation with Meta's Relative Wealth Index</div></div>
    <div class="kpi"><div class="v" id="kTotal">0<small>MWp</small></div>
      <div class="k">Our national total, recall-corrected (est_mwp_rc)</div></div>
  </div>

  <section class="sec" id="compare">
    <div class="sec-head">
      <div>
        <div class="sec-label">Comparison</div>
        <div class="sec-title">Where our PV estimate agrees, and where it doesn't</div>
      </div>
      <div class="switch" role="group" aria-label="Comparison layer">
        <button class="tab" id="tab0" type="button" data-i="0">
          <span class="tt1">TransitionZero</span><span class="tt2">another rooftop-solar model</span>
        </button>
        <button class="tab" id="tab1" type="button" data-i="1">
          <span class="tt1">Night lights</span><span class="tt2">VIIRS 2023 annual radiance</span>
        </button>
        <button class="tab" id="tab2" type="button" data-i="2">
          <span class="tt1">Wealth index</span><span class="tt2">Meta Relative Wealth Index</span>
        </button>
      </div>
    </div>

    <div class="grid">
      <section class="card map-card">
        <div class="map-head">
          <div class="map-title" id="mapTitle">-</div>
          <div class="map-sub" id="mapSub">&asymp;11 km &times; 11 km cells</div>
        </div>
        <div id="mapmount"></div>
        <div class="legend">
          <div class="lg-col">
            <div class="bar" id="legbar"></div>
            <div class="ticks" id="legticks"></div>
          </div>
          <div class="cap" id="legcap"></div>
          <div class="large-key" id="ringKey" style="display:none">
            <span class="sw"></span>our PV capacity: ring size
          </div>
        </div>
      </section>

      <aside>
        <div class="card">
          <div class="hero-num"><span id="heroNum">0</span></div>
          <div class="hero-label" id="heroLabel">-</div>
          <div class="hero-desc" id="heroDesc"></div>
          <div class="corrbadge" id="corrBadge"></div>
        </div>
        <div class="card" style="margin-top:14px;">
          <div class="hist-title2" id="scatterTitle">Our capacity vs. comparison layer, per cell</div>
          <svg id="scatter" class="posechart scatter" viewBox="0 0 460 320"></svg>
        </div>
      </aside>
    </div>
  </section>

  <section class="sec" id="background">
    <div class="sec-head">
      <div>
        <div class="sec-label">Background</div>
        <div class="sec-title">Sources, units, and what each comparison can and can't show</div>
      </div>
    </div>

    <details class="xdetails">
      <summary><span><span class="xt">TransitionZero: units don't match, so this compares rank, not magnitude</span>
        <span class="xs">percent-of-national-total per hexagon</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>TransitionZero's file (<code>data/estimated_rooftop_solar_capacity.json</code>, 3,303 H3
        resolution-5 hexagons, &asymp;252 km&sup2; each) sums to a value not in comparable absolute
        units or scope to our MWp figure (confirmed 2026-07-16) &mdash; a different methodology
        and, likely, a different definition of what counts as rooftop solar. Diffing raw
        magnitudes would be meaningless, so both datasets are normalized to <b>percent of
        national total per spatial unit</b> before comparing: this asks "do the two models
        agree on <em>where</em> PV concentrates," which is answerable, rather than "whose number
        is bigger," which isn't. Rank (Spearman) correlation is the headline statistic for
        exactly this reason &mdash; it's invariant to any monotonic rescaling either side's
        units might need.</p>
        <p>Only <span id="xTzMatched">-</span> of 3,303 hexagons receive any of our grid cells at
        all: our own compositing only covers building-populated cells (&asymp;54% of the
        country's area), so a large share of the "no overlap" hexagons are a coverage gap, not a
        disagreement &mdash; see <code>docs/methods/density.md</code> for the earlier measurement
        that most of the apparent gap (51.9 of 52.2 percentage points) is cells we <em>have</em>
        inferred but which score near-zero, not cells we've never looked at.</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">Night lights: a proxy for "is this place lit and built-up," not for panels themselves</span>
        <span class="xs">VIIRS VNL v2.1, 2023 annual composite, 500 m</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Source: a Zenodo mirror (CC-BY 4.0, no login) of the Earth Observation Group's Visible
        Infrared Imaging Radiometer Suite (VIIRS) Day/Night Band annual composite, masked and
        cloud-filtered average radiance, rescaled 0&ndash;2000. Nighttime satellite imagery cannot
        see solar panels (they're unlit); this instead answers whether PV density tracks the same
        "urban, electrified, built-up" signal that produces light at night &mdash; roughly, whether
        the model is finding PV where people and infrastructure actually are.</p>
        <p>Correlation is computed on <code>log(1+radiance)</code> vs <code>log(1+MWp)</code>
        (both are heavy-tailed: most cells are dark, a few urban cores are extremely bright, and
        the same shape holds for PV). A large part of this correlation is a shared confound:
        bigger, more built-up cells are both brighter <em>and</em> hold more roof area to put PV
        on. Controlling for each cell's total building footprint area
        (<code>roof_area_m2</code>) via partial correlation drops the coefficient from
        <span id="xNtlRaw">-</span> to <span id="xNtlPartial">-</span> &mdash; still positive and
        far from zero, so nightlights carry information about PV placement beyond "this cell has
        more buildings," but a meaningful share of the raw correlation is that shared confound,
        not new information.</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">Relative Wealth Index: does PV track affordability, not just urban density</span>
        <span class="xs">Meta / Data for Good, via HDX, &asymp;2.4 km tiles</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Source: Meta's Relative Wealth Index (Bing tile resolution, machine-learning estimate
        from satellite imagery, mobile-connectivity, and other covariates &mdash; itself imagery-
        adjacent but not derived from this project's Sentinel-2 pipeline or its PV labels),
        downloaded from HDX's public, no-login mirror. Values are <em>relative</em> within
        India+Pakistan (this file's own scope), centered near <span id="xRwiMedian">-</span> for
        our grid's covered cells, not an absolute wealth measure.</p>
        <p><span id="xRwiCovered">-</span> of <span id="xRwiTotal">-</span> cells have &ge;1 RWI
        tile centroid. Correlation with wealth is real but modest (<span id="xRwiRaw">-</span>
        raw, <span id="xRwiPartial">-</span> after controlling for building footprint area) &mdash;
        weaker than the nightlights relationship, consistent with wealth being a looser proxy for
        "can this household afford solar" than "is this an urban, electrified area" is for "is
        there a roof here at all."</p>
      </div>
    </details>

    <details class="xdetails">
      <summary><span><span class="xt">Data &amp; methods</span>
        <span class="xs">what's under the hood</span></span><span class="xi">+</span></summary>
      <div class="xbody">
        <p>Our own layer: <code>data/predictions/pakistan/density/grid.geoparquet</code>,
        <code>est_mwp_rc</code> per 0.1&deg; cell (the currently-published density run). VIIRS:
        <a href="https://zenodo.org/records/17294744">zenodo.org/records/17294744</a> (Zhao et al.,
        annual VNL v2.1 time series, CC-BY 4.0), 2023 file, zonal-mean radiance per cell via a
        single windowed raster read (no third-party zonal-stats package needed since cells are
        regular 0.1&deg; boxes). RWI:
        <a href="https://data.humdata.org/dataset/relative-wealth-index">HDX Relative Wealth
        Index</a>, India+Pakistan file, point-in-polygon joined to cells, cell mean over all tile
        centroids that fall inside it. TransitionZero: as documented above. All three external
        datasets were fetched fresh for this comparison; none were previously used in this
        codebase.</p>
      </div>
    </details>
  </section>

  <div class="foot" id="foot">Generated by scripts/build_pv_external_comparison.py.
    Our layer: est_mwp_rc, data/predictions/pakistan/density (current published run).
    External sources: TransitionZero (data/estimated_rooftop_solar_capacity.json),
    VIIRS VNL v2.1 2023 (Zenodo 17294744, CC-BY), Meta RWI (HDX, India+Pakistan file).</div>
</div>

<script>
(function () {
  const DATA = JSON.parse(document.getElementById("data").textContent);
  const [b0, b1, b2, b3] = DATA.bounds;
  const lonspan = b2 - b0, latspan = b3 - b1;
  const meanlat = (b1 + b3) / 2, k = Math.cos(meanlat * Math.PI / 180);
  const W = 1000, H = Math.round(W * latspan / (lonspan * k));

  const RAMP_DARK = ["#3c2a12","#7a3f0e","#b5610f","#e07d17","#f5a623","#ffcf5c","#fff1c2"];
  const RAMP_LIGHT = ["#f2e3bf","#eec98a","#e5a24e","#d97f22","#c25e12","#9c4410","#5f2c0a"];
  const DIV_LO = "#4fb2e8", DIV_MID_DARK = "#241f16", DIV_MID_LIGHT = "#e6dcc7", DIV_HI = "#f5a623";

  function proj(lon, lat) { return [(lon - b0) / lonspan * W, (b3 - lat) / latspan * H]; }
  function hex2rgb(h) { return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)]; }
  function lerp(a,b,t) { return a+(b-a)*t; }
  function ramp(t, stops) {
    t = Math.max(0, Math.min(1, t));
    const n = stops.length - 1, f = t * n, i = Math.min(n-1, Math.floor(f)), r = f - i;
    const a = hex2rgb(stops[i]), c = hex2rgb(stops[i+1]);
    return `rgb(${Math.round(lerp(a[0],c[0],r))},${Math.round(lerp(a[1],c[1],r))},${Math.round(lerp(a[2],c[2],r))})`;
  }
  function mix2(c1, c2, t) {
    const a = hex2rgb(c1), b = hex2rgb(c2);
    return `rgb(${Math.round(lerp(a[0],b[0],t))},${Math.round(lerp(a[1],b[1],t))},${Math.round(lerp(a[2],b[2],t))})`;
  }
  function isDark() {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr) return attr === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  const SVGNS = "http://www.w3.org/2000/svg";
  function el(n, a) { const e = document.createElementNS(SVGNS, n); for (const kk in a) e.setAttribute(kk, a[kk]); return e; }
  function ringPath(rings) {
    let d = "";
    for (const ring of rings) {
      for (let i = 0; i < ring.length; i++) {
        const p = proj(ring[i][0], ring[i][1]);
        d += (i === 0 ? "M" : "L") + p[0].toFixed(1) + " " + p[1].toFixed(1);
      }
      d += "Z";
    }
    return d;
  }

  const VIEWS = [
    {
      key: "tz", label: "TransitionZero",
      mapTitle: "Share-of-national-total difference, per TZ hexagon",
      mapSub: `${DATA.stats.tz.n_hex.toLocaleString()} H3 hexagons`,
      legCap: "our share &minus; TZ share (percentage points)",
      heroLabel: "Rank correlation (Spearman)", heroSuffix: "",
      heroDesc: `Positive = we place more of the national share there than TransitionZero does; negative = less. ${DATA.stats.tz.matched.toLocaleString()} of ${DATA.stats.tz.n_hex.toLocaleString()} hexagons received &ge;1 of our grid cells.`,
      corrLabel: ["Pearson (share %)", "Spearman (rank)"],
    },
    {
      key: "ntl", label: "Night lights",
      mapTitle: "VIIRS 2023 annual radiance, per cell",
      mapSub: "0.1&deg; cells &middot; log scale &middot; ring = our MWp",
      legCap: "mean radiance (0&ndash;2000 scale)",
      heroLabel: "Log-log correlation (Pearson)", heroSuffix: "",
      heroDesc: `Correlation between log(1+radiance) and log(1+MWp) per cell. Partial correlation controlling for each cell's building footprint area: ${DATA.stats.ntl.partial_vs_roof_area}.`,
      corrLabel: ["Pearson (log-log)", "Spearman (rank)"],
    },
    {
      key: "rwi", label: "Wealth index",
      mapTitle: "Meta Relative Wealth Index, per cell",
      mapSub: "0.1&deg; cells &middot; ring = our MWp",
      legCap: "relative wealth index (unitless)",
      heroLabel: "Correlation (Pearson)", heroSuffix: "",
      heroDesc: `${DATA.stats.rwi.n_covered.toLocaleString()} of ${DATA.stats.rwi.n_total.toLocaleString()} cells have RWI tile coverage. Partial correlation controlling for building footprint area: ${DATA.stats.rwi.partial_vs_roof_area}.`,
      corrLabel: ["Pearson", "Spearman (rank)"],
    },
  ];
  const hashIdx = { "#tz": 0, "#ntl": 1, "#rwi": 2 }[location.hash];
  let sel = hashIdx !== undefined ? hashIdx : 0;

  function renderMap() {
    const dark = isDark();
    const view = VIEWS[sel];
    const mount = document.getElementById("mapmount");
    mount.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "map", role: "img",
      "aria-label": view.mapTitle });
    svg.appendChild(el("rect", { x: 0, y: 0, width: W, height: H, fill: "var(--map-bg)" }));
    const defs = el("defs", {});
    const filt = el("filter", { id: "bloom", x: "-20%", y: "-20%", width: "140%", height: "140%" });
    filt.appendChild(el("feGaussianBlur", { stdDeviation: "4" }));
    defs.appendChild(filt); svg.appendChild(defs);
    const gLand = el("g", {});
    for (const p of DATA.provinces) gLand.appendChild(el("path", { d: ringPath(p.rings), class: "prov-fill" }));
    svg.appendChild(gLand);

    const cw = (0.1 / lonspan * W) + 0.4, ch = (0.1 / latspan * H) + 0.4;
    const maxMwp = Math.max(1, ...DATA.cells.map(c => c.mwp));

    if (view.key === "tz") {
      const diffMin = DATA.stats.tz.diff_min, diffMax = DATA.stats.tz.diff_max;
      const midColor = dark ? DIV_MID_DARK : DIV_MID_LIGHT;
      const gHex = el("g", {});
      for (const f of DATA.tz) {
        const color = f.diff_pp >= 0
          ? mix2(midColor, DIV_HI, diffMax > 0 ? f.diff_pp / diffMax : 0)
          : mix2(midColor, DIV_LO, diffMin < 0 ? f.diff_pp / diffMin : 0);
        const p = el("path", { d: ringPath(f.rings), fill: color, class: "cell", tabindex: "0" });
        p.addEventListener("pointerenter", (e) => showTip(e, [
          `<b>${f.diff_pp >= 0 ? "+" : ""}${f.diff_pp.toFixed(3)} pp</b>`,
          `our share ${f.our_pct.toFixed(3)}% &middot; TZ share ${f.tz_pct.toFixed(3)}%`]));
        p.addEventListener("pointerleave", hideTip);
        gHex.appendChild(p);
      }
      svg.appendChild(gHex);
      document.getElementById("legbar").style.background = `linear-gradient(to right, ${DIV_LO}, ${midColor}, ${DIV_HI})`;
      document.getElementById("legticks").innerHTML =
        `<span style="left:0%">${diffMin.toFixed(2)}pp</span><span style="left:50%">0</span><span style="left:100%">${diffMax.toFixed(2)}pp</span>`;
      document.getElementById("ringKey").style.display = "none";
    } else {
      const key = view.key === "ntl" ? "ntl" : "rwi";
      const vals = DATA.cells.map(c => c[key]).filter(v => v !== null && v !== undefined);
      const stops = dark ? RAMP_DARK : RAMP_LIGHT;
      const midColor = dark ? DIV_MID_DARK : DIV_MID_LIGHT;
      let tOf, colorOf, legLo, legHi, legMid = null;
      if (key === "ntl") {
        const VMIN = 0.02, VMAX = Math.max(0.1, ...vals);
        const lMin = Math.log(VMIN), lMax = Math.log(VMAX);
        tOf = (v) => (Math.log(Math.max(v, VMIN)) - lMin) / (lMax - lMin);
        colorOf = (v) => ramp(tOf(v), stops);
        legLo = "0"; legHi = VMAX.toFixed(1);
      } else {
        // RWI is signed and dataset-relative, not a magnitude -- a diverging scale
        // centered on this AOI's own median reads "poorer/richer than typical here,"
        // which is what the index actually means, instead of a sequential ramp that
        // would visually merge it with the nightlights tab's unrelated brightness scale.
        const sorted = [...vals].sort((a, b) => a - b);
        const median = sorted[Math.floor(sorted.length / 2)];
        const VMIN = Math.min(...vals), VMAX = Math.max(...vals);
        const below = median - VMIN || 1, above = VMAX - median || 1;
        colorOf = (v) => v >= median ? mix2(midColor, DIV_HI, (v - median) / above)
                                      : mix2(midColor, DIV_LO, (median - v) / below);
        legLo = VMIN.toFixed(2); legHi = VMAX.toFixed(2); legMid = median.toFixed(2);
      }
      const gB = el("g", { filter: "url(#bloom)", opacity: "var(--bloom)" });
      const gC = el("g", {});
      const gR = el("g", {});
      for (const c of DATA.cells) {
        const v = c[key];
        if (v === null || v === undefined) continue;
        const tl = proj(c.lon0, c.lat0 + 0.1);
        const color = colorOf(v);
        if (dark && (key !== "ntl" || v > 0.02)) {
          gB.appendChild(el("rect", { x: tl[0].toFixed(1), y: tl[1].toFixed(1),
            width: cw.toFixed(1), height: ch.toFixed(1), fill: color }));
        }
        const rect = el("rect", { x: tl[0].toFixed(1), y: tl[1].toFixed(1),
          width: cw.toFixed(1), height: ch.toFixed(1), fill: color, class: "cell", tabindex: "0" });
        rect.addEventListener("pointerenter", (e) => showTip(e, [
          `<b>${key === "ntl" ? v.toFixed(3) + " radiance" : v.toFixed(3) + " RWI"}</b>`,
          `our capacity: ${c.mwp.toFixed(2)} MWp`]));
        rect.addEventListener("pointerleave", hideTip);
        gC.appendChild(rect);
        if (c.mwp > 0) {
          const cx = tl[0] + cw / 2, cy = tl[1] + ch / 2;
          const r = 1.2 + 5.2 * Math.sqrt(c.mwp / maxMwp);
          gR.appendChild(el("circle", { cx: cx.toFixed(1), cy: cy.toFixed(1), r: r.toFixed(1), class: "large-dot" }));
        }
      }
      if (dark) svg.appendChild(gB);
      svg.appendChild(gC);
      svg.appendChild(gR);
      document.getElementById("legbar").style.background = legMid !== null
        ? `linear-gradient(to right, ${DIV_LO}, ${midColor}, ${DIV_HI})`
        : `linear-gradient(to right, ${stops.join(",")})`;
      document.getElementById("legticks").innerHTML = legMid !== null
        ? `<span style="left:0%">${legLo}</span><span style="left:50%">median ${legMid}</span><span style="left:100%">${legHi}</span>`
        : `<span style="left:0%">${legLo}</span><span style="left:100%">${legHi}</span>`;
      document.getElementById("ringKey").style.display = "flex";
    }
    mount.appendChild(svg);
    document.getElementById("legcap").innerHTML = view.legCap;
  }

  function showTip(evt, lines) {
    const tip = document.getElementById("tip");
    tip.innerHTML = lines.join("<br>");
    tip.style.left = evt.clientX + "px";
    tip.style.top = evt.clientY + "px";
    tip.style.opacity = 1;
  }
  function hideTip() { document.getElementById("tip").style.opacity = 0; }

  function renderScatter() {
    const view = VIEWS[sel];
    const svg = document.getElementById("scatter");
    svg.innerHTML = "";
    const Wc = 460, Hc = 320, padL = 42, padR = 12, padT = 14, padB = 34;
    const plotW = Wc - padL - padR, plotH = Hc - padT - padB;

    let pts, xLabel, yLabel, logX = true, logY = true;
    if (view.key === "tz") {
      pts = DATA.tz.map(f => [f.tz_pct, f.our_pct]);
      xLabel = "TZ share %"; yLabel = "our share %"; logX = false; logY = false;
    } else if (view.key === "ntl") {
      pts = DATA.cells.map(c => [c.ntl, c.mwp]);
      xLabel = "log(1+radiance)"; yLabel = "log(1+MWp)";
    } else {
      pts = DATA.cells.filter(c => c.rwi !== null).map(c => [c.rwi, c.mwp]);
      xLabel = "RWI"; yLabel = "log(1+MWp)"; logX = false;
    }
    const tx = (v) => logX ? Math.log1p(Math.max(v, 0)) : v;
    const ty = (v) => logY ? Math.log1p(Math.max(v, 0)) : v;
    const xs = pts.map(p => tx(p[0])), ys = pts.map(p => ty(p[1]));
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(...ys), yMax = Math.max(...ys);
    const px = (v) => padL + (v - xMin) / (xMax - xMin || 1) * plotW;
    const py = (v) => padT + plotH - (v - yMin) / (yMax - yMin || 1) * plotH;

    svg.appendChild(el("line", { x1: padL, x2: Wc - padR, y1: padT + plotH, y2: padT + plotH, class: "axis" }));
    svg.appendChild(el("line", { x1: padL, x2: padL, y1: padT, y2: padT + plotH, class: "axis" }));
    for (let i = 0; i < pts.length; i++) {
      svg.appendChild(el("circle", { cx: px(xs[i]).toFixed(1), cy: py(ys[i]).toFixed(1), r: 2, class: "pt" }));
    }
    const lx = el("text", { x: padL + plotW / 2, y: Hc - 8, "font-size": 10.5, "text-anchor": "middle" });
    lx.textContent = xLabel; svg.appendChild(lx);
    const ly = el("text", { x: 12, y: padT + plotH / 2, "font-size": 10.5, "text-anchor": "middle",
      transform: `rotate(-90 12 ${padT + plotH / 2})` });
    ly.textContent = yLabel; svg.appendChild(ly);
  }

  function renderPanel() {
    const view = VIEWS[sel];
    document.getElementById("mapTitle").innerHTML = view.mapTitle;
    document.getElementById("mapSub").innerHTML = view.mapSub;
    document.getElementById("heroLabel").innerHTML = view.heroLabel;
    document.getElementById("heroDesc").innerHTML = view.heroDesc;
    document.getElementById("scatterTitle").innerHTML = `${view.label}: our capacity vs. comparison layer, per cell`;
    const stats = DATA.stats[view.key];
    document.getElementById("heroNum").textContent = view.key === "tz" ? stats.spearman : stats.pearson;
    const badge = document.getElementById("corrBadge");
    badge.innerHTML = "";
    const vals = view.key === "tz" ? [stats.pearson, stats.spearman] : [stats.pearson, stats.spearman];
    view.corrLabel.forEach((lbl, i) => {
      const c = document.createElement("div"); c.className = "c";
      c.innerHTML = `<div class="v">${vals[i]}</div><div class="k">${lbl}</div>`;
      badge.appendChild(c);
    });
    renderMap();
    renderScatter();
  }

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      sel = parseInt(btn.dataset.i, 10);
      document.querySelectorAll(".tab").forEach(b => b.setAttribute("aria-pressed", "false"));
      btn.setAttribute("aria-pressed", "true");
      renderPanel();
    });
  });
  document.getElementById(`tab${sel}`).setAttribute("aria-pressed", "true");

  document.getElementById("kTz").textContent = DATA.stats.tz.spearman;
  document.getElementById("kNtl").textContent = DATA.stats.ntl.pearson;
  document.getElementById("kRwi").textContent = DATA.stats.rwi.pearson;
  document.getElementById("kTotal").innerHTML = `${DATA.total_rc.toLocaleString(undefined, {maximumFractionDigits: 0})}<small>MWp</small>`;

  document.getElementById("xTzMatched").textContent = DATA.stats.tz.matched.toLocaleString();
  document.getElementById("xNtlRaw").textContent = DATA.stats.ntl.pearson;
  document.getElementById("xNtlPartial").textContent = DATA.stats.ntl.partial_vs_roof_area;
  document.getElementById("xRwiCovered").textContent = DATA.stats.rwi.n_covered.toLocaleString();
  document.getElementById("xRwiTotal").textContent = DATA.stats.rwi.n_total.toLocaleString();
  document.getElementById("xRwiRaw").textContent = DATA.stats.rwi.pearson;
  document.getElementById("xRwiPartial").textContent = DATA.stats.rwi.partial_vs_roof_area;
  const rwiVals = DATA.cells.map(c => c.rwi).filter(v => v !== null).sort((a,b) => a-b);
  document.getElementById("xRwiMedian").textContent = rwiVals.length ? rwiVals[Math.floor(rwiVals.length/2)].toFixed(2) : "-";

  renderPanel();

  const btn = document.getElementById("themeBtn");
  function applyTheme(t) {
    if (t) document.documentElement.setAttribute("data-theme", t);
    else document.documentElement.removeAttribute("data-theme");
    btn.textContent = isDark() ? "Light mode" : "Dark mode";
    renderPanel();
  }
  const saved = localStorage.getItem("earthpv-theme");
  if (saved) applyTheme(saved);
  else btn.textContent = isDark() ? "Light mode" : "Dark mode";
  btn.addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    localStorage.setItem("earthpv-theme", next);
    applyTheme(next);
  });
})();
</script>
<div class="tip" id="tip" role="status" aria-live="off" style="opacity:0"></div>
"""


def build_html(data: dict) -> str:
    return (TEMPLATE
            .replace("__CSS__", shared_css())
            .replace("__DATA_JSON__", json.dumps(data)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()

    if not args.skip_download:
        print("Fetching external datasets (cached at", CACHE_DIR, ")...")
        fetch(VIIRS_URL, VIIRS_PATH)
        fetch(RWI_URL, RWI_PATH)
    else:
        print("Skipping download, expecting cached files at", CACHE_DIR)

    data = prepare_data()
    print(json.dumps(data["stats"], indent=2))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = build_html(data)
    OUT.write_text(html)
    print(f"-> {OUT} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
