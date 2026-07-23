"""Export PV candidates for OSM validation workflows.

Outputs:
- candidates.geoparquet / candidates.geojson — full attribute set
- maproulette.geojson — line-delimited FeatureCollections (one task per candidate)
  with imagery links, ready to upload as a MapRoulette challenge.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np

log = logging.getLogger(__name__)


def _epoch_note(row, has_epoch: bool) -> str:
    """Human-readable pre-boom/post-boom note for the MapRoulette instruction text.

    `epoch_prior`/`preboom_prob` (postprocess.add_epoch_prior) already feed rank_score,
    but silently — a mapper doing the actual validation never saw why a candidate was
    ranked where it was. Only speaks up when `epoch_checked` is True (a pre-boom raster
    actually covered this candidate); otherwise the pre-/post-boom contrast is unknown,
    not confirmed either way, so saying nothing is more honest than a false "new" claim.
    """
    if not has_epoch or not bool(row.get("epoch_checked", False)):
        return ""
    if row.epoch_prior < 0.5:
        return (" Note: this location was already bright in pre-2022 imagery -- may be "
                "a persistent non-PV feature (bright roof/soil/water), not new PV.")
    if row.epoch_prior >= 0.9:
        return " Appears new since the 2021-22 solar-import boom (dim before, bright now)."
    return ""


def _imagery_links(lon: float, lat: float) -> dict[str, str]:
    return {
        "osm": f"https://www.openstreetmap.org/edit#map=19/{lat:.5f}/{lon:.5f}",
        "bing": f"https://www.bing.com/maps?cp={lat:.5f}~{lon:.5f}&lvl=19&style=a",
        "google": f"https://www.google.com/maps/@{lat:.5f},{lon:.5f},200m/data=!3m1!1e3",
    }


def _load_mapped_reference(aoi: str, cfg: dict, settings) -> gpd.GeoDataFrame | None:
    """Every already-known OSM solar polygon for this AOI — the rooftopsenti-cached
    snapshot (source_region/osm/*.parquet) plus any fresher Overpass-fetched labels
    (data/labels/*_overpass_solar.parquet) sitting in the same country. Used to hold
    back candidates that are already mapped, so a human-validation queue only ever
    surfaces genuinely new leads."""
    from earthpv.local_source import load_solar_labels

    parts = []
    source_region = cfg.get("source_region")
    if source_region:
        region_dir = Path(settings.raw["local_root"]) / source_region
        cached = load_solar_labels(region_dir)
        if cached is not None and not cached.empty:
            parts.append(cached[["geometry"]])
    for p in sorted(Path("data/labels").glob("*_overpass_solar.parquet")):
        fresh = gpd.read_parquet(p)
        if not fresh.empty:
            parts.append(fresh[["geometry"]])
    if not parts:
        return None
    import pandas as pd

    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:4326")


def filter_new_leads(
    cands: gpd.GeoDataFrame, mapped: gpd.GeoDataFrame, min_distance_m: float = 0.0
) -> gpd.GeoDataFrame:
    """Drop candidates within `min_distance_m` of an already-mapped OSM solar feature."""
    if cands.empty or mapped.empty:
        return cands
    return cands[new_lead_mask(cands, mapped, min_distance_m)].reset_index(drop=True)


def new_lead_mask(
    cands: gpd.GeoDataFrame, mapped: gpd.GeoDataFrame, min_distance_m: float = 0.0
) -> np.ndarray:
    """Boolean mask: True where a candidate is NOT near an already-mapped feature.

    `min_distance_m=0` is the original zero-buffer `intersects` convention (a
    candidate must literally overlap the mapped geometry) — same as the Lahore
    recall check, but it misses candidates whose model-drawn footprint is offset
    from a mapped feature that is just a point (a common OSM `generator:source=solar`
    node), which never "intersects" a polygon that doesn't happen to contain it. A
    positive `min_distance_m` catches those as the same already-mapped installation.
    Works in local-UTM 1-degree chunks, the same pattern as
    `postprocess._join_buildings_chunked`, so it holds up at country scale.
    Also reused (inverted) by `capacity_calibration` as the "certainly real" mapped
    fraction per size bin.
    """
    if cands.empty or mapped.empty:
        return np.ones(len(cands), dtype=bool)
    if min_distance_m <= 0:
        sindex = mapped.sindex
        return np.array(
            [len(sindex.query(g, predicate="intersects")) == 0 for g in cands.geometry]
        )

    cands = cands.reset_index(drop=True)
    reps = cands.geometry.representative_point()
    chunk_deg = 1.0
    keys = list(zip(
        np.floor(reps.x.to_numpy() / chunk_deg).astype(int).tolist(),
        np.floor(reps.y.to_numpy() / chunk_deg).astype(int).tolist(),
    ))
    is_new = np.ones(len(cands), dtype=bool)
    # Pad each chunk's mapped-feature lookup by the distance threshold (+ margin)
    # in degrees, so a mapped feature just outside the chunk still gets caught.
    buf = min_distance_m / 111_000 + 0.02
    for key in sorted(set(keys)):
        mask = np.array([k == key for k in keys])
        sub = cands[mask]
        minx, miny, maxx, maxy = sub.total_bounds
        near = mapped.cx[minx - buf : maxx + buf, miny - buf : maxy + buf]
        if near.empty:
            continue
        lon, lat = (minx + maxx) / 2, (miny + maxy) / 2
        epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1
        su = sub.to_crs(epsg)
        mu = near.to_crs(epsg).reset_index(drop=True)
        sindex = mu.sindex
        idx, d = sindex.nearest(su.geometry.values, return_all=False, return_distance=True)
        dist = np.full(len(sub), np.inf)
        for k in range(idx.shape[1]):
            dist[int(idx[0, k])] = float(d[k])
        is_new[np.where(mask)[0]] = dist > min_distance_m
    log.info("Distance-filtered (>%.0f m) new-lead check across %d spatial chunks", min_distance_m, len(set(keys)))
    return is_new


def run_export(
    aoi: str, pred_dir: Path, exclude_mapped: bool = False, min_distance_m: float = 0.0,
    epoch_clean: bool = False, epoch_fp_max_prior: float = 0.5,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pred_dir = Path(pred_dir) / aoi
    cands = gpd.read_parquet(pred_dir / "candidates.parquet")
    if cands.empty:
        log.warning("No candidates to export for %s", aoi)
        return
    # rank_score blends model confidence with the building prior (postprocess); it
    # puts on-/near-building detections at the top of the validation queue while
    # keeping every candidate. Fall back to raw confidence for older outputs.
    sort_col = "rank_score" if "rank_score" in cands.columns else "confidence"
    cands = cands.sort_values(sort_col, ascending=False).reset_index(drop=True)
    cands["candidate_id"] = [f"{aoi}-pv-{i:06d}" for i in range(len(cands))]

    gpq = pred_dir / f"{aoi}_pv_candidates.geoparquet"
    cands.to_parquet(gpq)
    gj = pred_dir / f"{aoi}_pv_candidates.geojson"
    cands.to_file(gj, driver="GeoJSON")

    if exclude_mapped or epoch_clean:
        from earthpv.config import Settings
        from earthpv.labels import resolve_aoi

        settings = Settings.load()
        _, cfg = resolve_aoi(aoi, settings)
        mapped = _load_mapped_reference(aoi, cfg, settings)
        if mapped is None or mapped.empty:
            log.warning("No already-mapped OSM reference found for %s; new_leads == candidates", aoi)
            leads = cands
        else:
            leads = filter_new_leads(cands, mapped, min_distance_m=min_distance_m)
        log.info(
            "New leads (not already mapped, >%.0fm): %d / %d candidates",
            min_distance_m, len(leads), len(cands),
        )
        if exclude_mapped:
            nl = pred_dir / f"{aoi}_pv_new_leads.geojson"
            leads.to_file(nl, driver="GeoJSON")

    if epoch_clean:
        # Precision-leaning EXTRA artifact — the only export that drops candidates.
        # A lead that was already bright in the pre-boom (2021/22) epoch is most
        # likely a persistent non-PV feature (bright roof/soil/water), the same
        # judgement _epoch_note surfaces to mappers; here it becomes a hard filter
        # so a validation queue can skip those entirely. Never-checked candidates
        # (no pre-boom raster coverage) are kept — absence of evidence is not a
        # verdict. Caveat: PV that already existed pre-boom is dropped along with
        # the false positives, so this file trades a little real (old, unmapped)
        # PV for a much cleaner queue; the default new_leads file keeps everything.
        if not {"epoch_checked", "epoch_prior"} <= set(leads.columns):
            log.warning(
                "epoch-clean requested but candidates carry no epoch columns — rerun "
                "`earthpv postprocess` with --preboom-prob-dir first; file not written"
            )
        else:
            checked = leads["epoch_checked"].astype(bool).to_numpy()
            fp = checked & (leads["epoch_prior"].to_numpy(float) < epoch_fp_max_prior)
            clean = leads[~fp]
            ec = pred_dir / f"{aoi}_pv_new_leads_epochclean.geojson"
            clean.to_file(ec, driver="GeoJSON")
            log.info(
                "Epoch-clean leads: dropped %d likely pre-boom FPs (epoch_prior < %.2f) "
                "of %d checked; kept %d never-checked; %d / %d leads -> %s",
                int(fp.sum()), epoch_fp_max_prior, int(checked.sum()),
                int((~checked).sum()), len(clean), len(leads), ec.name,
            )

    # MapRoulette: newline-delimited FeatureCollections (RFC 7464-style, MR "lineByLine")
    mr = pred_dir / f"{aoi}_pv_maproulette.geojson"
    has_epoch = "epoch_prior" in cands.columns and "epoch_checked" in cands.columns
    with mr.open("w") as f:
        for _, row in cands.iterrows():
            c = row.geometry.centroid
            props = {
                "candidate_id": row.candidate_id,
                "confidence": round(float(row.confidence), 3),
                "rank_score": round(float(row.rank_score), 3) if "rank_score" in cands else None,
                "building_dist_m": (
                    round(float(row.building_dist_m), 1) if "building_dist_m" in cands else None
                ),
                "area_m2": round(float(row.area_m2), 1),
                "placement": row.placement,
                "epoch_checked": bool(row.epoch_checked) if has_epoch else None,
                "epoch_prior": round(float(row.epoch_prior), 3) if has_epoch else None,
                "instruction": (
                    f"Possible solar PV array (~{row.area_m2:.0f} m2, "
                    f"confidence {row.confidence:.2f}, {row.placement}). "
                    "Check imagery; if confirmed, map power=generator + "
                    "generator:source=solar + generator:method=photovoltaic"
                    + (" + location=roof" if row.placement == "rooftop" else "")
                    + _epoch_note(row, has_epoch)
                ),
                **_imagery_links(c.x, c.y),
            }
            fc = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": row.geometry.__geo_interface__,
                        "properties": props,
                    }
                ],
            }
            f.write(json.dumps(fc) + "\n")
    log.info("Exported %d candidates -> %s, %s, %s", len(cands), gpq.name, gj.name, mr.name)
