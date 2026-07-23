"""Estimate PV panel orientation (tilt + azimuth) for all Pakistan leads, at zero
extra network cost, by reusing the year-long B04/B08 scene series already pulled
for the vegetation NDVI veto (`scripts/veg_annual_ndvi.py pull` ->
`data/veg/<aoi>/<candidate_id>.parquet`).

Why this works with no new pull: `glint.spike_fit`/`annotate_spikes` are fully
band-name-parameterized — they need `sun_zen`/`sun_az`/`view_zen`/`view_az`
(per-scene sun/view geometry, always fetched regardless of which reflectance bands
were requested) plus whatever `p98_<band>`/`ring_<band>` columns exist. The NDVI
pull requested B04/B08 (red/NIR, for NDVI) instead of the glint default B03/B08
(green/NIR), but the physics `spike_fit` runs — MAD-based per-band spike detection
against each series' own clear-day baseline, then the specular geometric
consistency fit (`required_orientation`/`misalignment_deg`) — depends only on sun
zenith/azimuth and view zenith/azimuth, not on which visible band supplied the
reflectance. B04 (665 nm) shows the same specular brightening a real glint event
produces as B03 (560 nm) would; substituting it costs nothing and needed no
separate design.

Runs BOTH spike criteria on the same downloaded series (no extra reads) and keeps
whichever gets more mutually-consistent spike dates: the default spatial ring
check (works everywhere it has discrimination) and the self-referenced check
(`self_referenced=True`, verified needed for dense urban blocks where a spatial
ring is never meaningfully darker than the roof it surrounds — see README's
"Solar-glint corroboration" section).

Expectation to set, not hide: glint absence is common even for real arrays (~30%
of confirmed installations show zero spikes over 2 years — wrong orientation for
this geometry, cloud cover, or simply too small/dim). An orientation/tilt estimate
is only possible for the subset that DOES glint consistently; this script reports
that fraction explicitly rather than implying universal coverage.

Resumable/incremental by construction: it only reads whatever series already
exist under data/veg/<aoi>/, so re-running later as the still-in-progress annual
pull (`veg_annual_ndvi.py pull`) covers more leads picks up more without
recomputing anything already done — recomputation here is a few ms per lead in
pure pandas, so there's no reason to cache partials.

Usage:
  .pixi/envs/default/bin/python scripts/glint_orientation_pakistan.py \
      --aoi pakistan --pred-dir data/predictions_pk16085
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import typer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthpv import glint  # noqa: E402
from earthpv.capacity_calibration import BIN_LABELS, bin_index  # noqa: E402
from earthpv.config import DATA_DIR  # noqa: E402

log = logging.getLogger("glint_orientation")
app = typer.Typer(pretty_exceptions_show_locals=False)

BANDS = ("B04", "B08")  # matches veg_annual_ndvi.py's pull — see module docstring
TOL_DEG = 3.0
MIN_CONSISTENT = 2  # a single spike can't be checked for self-consistency


def _fit_one(df: pd.DataFrame) -> dict:
    """Best-of-both-criteria orientation fit for one lead's already-pulled series."""
    default = glint.spike_fit(df, bands=BANDS, tol_deg=TOL_DEG, self_referenced=False)
    selfref = glint.spike_fit(df, bands=BANDS, tol_deg=TOL_DEG, self_referenced=True)
    if default["n_consistent"] >= selfref["n_consistent"]:
        best, criterion = default, "default"
    else:
        best, criterion = selfref, "self_referenced"
    return {
        "n_scenes": best["n_scenes"], "n_clear": best["n_clear"],
        "n_spikes_default": default["n_spikes"], "n_spikes_selfref": selfref["n_spikes"],
        "fit_tilt": best["fit_tilt"], "fit_az": best["fit_az"],
        "n_consistent": best["n_consistent"],
        "criterion": criterion if best["n_consistent"] >= MIN_CONSISTENT else "none",
    }


@app.command()
def analyze(
    aoi: str = typer.Option("pakistan"),
    pred_dir: Path = typer.Option(Path("data/predictions_pk16085")),
    leads_file: Path = typer.Option(
        None, help="Leads to join area/placement metadata from (default "
        "<pred_dir>/<aoi>/<aoi>_pv_new_leads_clean.geojson)"
    ),
    out: Path = typer.Option(
        None, help="Output parquet (default <pred_dir>/<aoi>/glint_orientation.parquet)"
    ),
):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    series_dir = DATA_DIR / "veg" / aoi
    files = sorted(series_dir.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no series under {series_dir} — run "
                          f"`scripts/veg_annual_ndvi.py pull --aoi {aoi}` first")

    leads_path = leads_file or Path(pred_dir) / aoi / f"{aoi}_pv_new_leads_clean.geojson"
    leads = gpd.read_file(leads_path) if leads_path.exists() else None
    meta_cols = ["candidate_id", "area_m2", "placement", "rank_score"]
    meta = (leads[meta_cols].set_index("candidate_id") if leads is not None
            else pd.DataFrame(columns=meta_cols[1:]))

    rows = []
    for f in files:
        cid = f.stem
        d = pd.read_parquet(f)
        r = {"candidate_id": cid}
        if d.empty:
            r.update(n_scenes=0, n_clear=0, n_spikes_default=0, n_spikes_selfref=0,
                      fit_tilt=np.nan, fit_az=np.nan, n_consistent=0, criterion="no_scenes")
        else:
            r.update(_fit_one(d))
        rows.append(r)
    out_df = pd.DataFrame(rows)
    if leads is not None:
        reps = leads.set_index("candidate_id").geometry.representative_point()
        out_df = out_df.join(meta, on="candidate_id").join(
            pd.DataFrame({"lon": reps.x, "lat": reps.y}), on="candidate_id"
        )

    dst = out or Path(pred_dir) / aoi / "glint_orientation.parquet"
    out_df.to_parquet(dst)

    n = len(out_df)
    fitted = out_df[out_df.criterion != "none"]
    log.info("Processed %d leads (of %d leads total, %s pull still filling in the rest) "
             "-> %s", n, len(leads) if leads is not None else "?", "in progress"
             if leads is not None and n < len(leads) else "complete", dst)
    log.info("Orientation recovered for %d/%d (%.1f%%) — n_consistent >= %d on either "
             "criterion; the rest never glinted consistently in a year of scenes "
             "(expected: absence of glint is common even for real PV)",
             len(fitted), n, 100 * len(fitted) / n if n else 0, MIN_CONSISTENT)
    log.info("Criterion split among fitted: %s", fitted.criterion.value_counts().to_dict())

    if "area_m2" in out_df.columns and out_df.area_m2.notna().any():
        out_df["bucket"] = pd.Categorical.from_codes(
            bin_index(out_df["area_m2"].fillna(0).to_numpy()), categories=list(BIN_LABELS)
        ).astype(str)
        by_bucket = out_df.groupby("bucket", sort=False).apply(
            lambda g: pd.Series({
                "n": len(g), "n_fitted": int((g.criterion != "none").sum()),
                "pct_fitted": round(100 * (g.criterion != "none").mean(), 1),
                "median_tilt": round(g.loc[g.criterion != "none", "fit_tilt"].median(), 1),
                "median_az": round(g.loc[g.criterion != "none", "fit_az"].median(), 1),
            }), include_groups=False,
        ).reindex(list(BIN_LABELS)).dropna(how="all")
        log.info("By size bucket:\n%s", by_bucket.to_string())
    if "placement" in out_df.columns and out_df.placement.notna().any():
        by_place = out_df.groupby("placement").criterion.apply(
            lambda s: f"{(s != 'none').sum()}/{len(s)} ({100*(s != 'none').mean():.1f}%)"
        )
        log.info("By placement:\n%s", by_place.to_string())
    if len(fitted):
        log.info("fit_az distribution (deg from north) p10/p50/p90: %s",
                  fitted.fit_az.quantile([.1, .5, .9]).round(0).tolist())
        log.info("fit_tilt distribution (deg from horizontal) p10/p50/p90: %s",
                  fitted.fit_tilt.quantile([.1, .5, .9]).round(0).tolist())


if __name__ == "__main__":
    app()
