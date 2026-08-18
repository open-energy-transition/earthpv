"""Export PV candidates for OSM validation workflows.

Outputs:
- candidates.geoparquet / candidates.geojson - full attribute set
- maproulette.geojson - line-delimited FeatureCollections (one task per candidate)
  with imagery links, ready to upload as a MapRoulette challenge.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _epoch_note(row, has_epoch: bool) -> str:
    """Human-readable pre-boom/post-boom note for the MapRoulette instruction text.

    `epoch_prior`/`preboom_prob` (postprocess.add_epoch_prior) already feed rank_score,
    but silently - a mapper doing the actual validation never saw why a candidate was
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
    """Every already-known OSM solar polygon for this AOI - the rooftopsenti-cached
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


def load_mapped_reference_attrs(aoi: str, cfg: dict, settings) -> gpd.GeoDataFrame:
    """Attribute-preserving twin of `_load_mapped_reference`, for callers that need to
    know WHICH mapped feature matched (geometry replacement), not just whether one
    exists nearby. Same two sources (rooftopsenti cache + `data/labels/*_overpass_solar
    .parquet`), reconciled to a common schema: `id`, `placement`, `area_m2`, `source`,
    `osm_timestamp`, `geometry`. Empty GeoDataFrame (not None) when neither source has
    anything, so callers can treat "no reference" and "reference with 0 rows"
    identically.

    `osm_timestamp` (the mapped feature's last OSM edit, from `overpass.py`'s `out
    meta`) is a proxy for how current the polygon is -- OSM mapping passes lag
    real-world installation growth (`docs/calibration-mapping-protocol.md`), so an
    older polygon may under- or over-represent what is actually there today. `NaT` for
    the rooftopsenti-cached source (no edit metadata available) and any Overpass pull
    predating this field -- absence, not evidence of freshness.
    """
    from earthpv.local_source import load_solar_labels

    cols = ["id", "placement", "area_m2", "source", "osm_timestamp", "geometry"]
    parts = []
    source_region = cfg.get("source_region")
    if source_region:
        region_dir = Path(settings.raw["local_root"]) / source_region
        cached = load_solar_labels(region_dir)
        if cached is not None and not cached.empty:
            c = cached.rename(columns={"osm_id": "id"})
            # rooftopsenti's osm_id is int64; Overpass's id is already a "osm-{type}/{n}"
            # string -- normalise to string so the merged column has one dtype (a mixed
            # int/str object column fails to_parquet's arrow conversion).
            c["id"] = c["id"].astype(str)
            c["source"] = "rooftopsenti"
            c["osm_timestamp"] = pd.NaT
            parts.append(c[cols])
    for p in sorted(Path("data/labels").glob("*_overpass_solar.parquet")):
        fresh = gpd.read_parquet(p)
        if fresh.empty:
            continue
        # Ad hoc Overpass pulls vary in vintage/schema (e.g. lahore_city10k/city4k predate
        # `classify_placement` being wired in) -- only `id`/`geometry` are load-bearing for
        # matching; backfill the rest rather than dropping the whole file's ground truth.
        f = fresh.copy()
        if "id" not in f.columns:
            log.warning("%s has no `id` column -- skipped", p.name)
            continue
        if "placement" not in f.columns:
            f["placement"] = "unknown"
        if "area_m2" not in f.columns:
            from earthpv.labels import geodesic_area_m2
            f["area_m2"] = [geodesic_area_m2(g) for g in f.geometry]
        if "osm_timestamp" not in f.columns:
            f["osm_timestamp"] = pd.NaT  # pull predates `out meta` (see overpass.py)
        f["source"] = "overpass"
        parts.append(f[cols])
    if not parts:
        return gpd.GeoDataFrame({c: [] for c in cols}, geometry="geometry", crs="EPSG:4326")
    out = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    out["id"] = out["id"].astype(str)  # belt-and-suspenders: one dtype regardless of source
    # Pooling the rooftopsenti cache with every `data/labels/*_overpass_solar.parquet`
    # pull (the national pull AND every calibration quadrat's own pull, which can cover
    # overlapping ground) means the SAME real installation can arrive as more than one
    # feature -- an OSM `power=plant` perimeter with a nested `power=generator` way, two
    # duplicate ways from independent mapping passes, or a quadrat pull re-covering
    # ground the national pull already has. `replace_with_osm_geometry`'s nearest-match
    # then has no way to prefer the correct footprint over a smaller nested fragment
    # (measured 2026-08-10: Sukkur solar farm matched a 44,948 m2 fragment, 1.7% of its
    # true 2.6 km2 footprint, because of 21 overlapping un-dissolved elements at that
    # site -- see labels.dissolve_overlapping's docstring). Dissolving here, before any
    # matching happens, removes the fragments rather than leaving downstream code to
    # pick among them.
    from earthpv.labels import dissolve_overlapping

    out = dissolve_overlapping(out, group_col="placement")
    return out


def match_mapped_polygons(
    cands: gpd.GeoDataFrame, mapped: gpd.GeoDataFrame, max_distance_m: float = 30.0,
) -> pd.DataFrame:
    """Nearest mapped-OSM polygon match per candidate, for geometry replacement.

    Unlike `new_lead_mask` (a boolean "is anything nearby"), this returns WHICH mapped
    feature matched and how far, so the caller can substitute the real OSM geometry for
    the model's coarse polygonized blob. Only polygon/multipolygon mapped features are
    considered - a point can't replace an area. Same chunked local-UTM nearest-neighbor
    pattern as `new_lead_mask`/`postprocess._join_buildings_chunked` (proven at country
    scale), kept as its own function rather than a shared refactor of `new_lead_mask`
    itself, since that function is load-bearing for the published recall/precision
    calibration and this session leaves it untouched on purpose.

    Returns a DataFrame positionally aligned to `cands` with columns `matched_id`
    (mapped's `id` where a polygon is within `max_distance_m`, else `None`), `dist_m`
    (else `NaN`), `timestamp` (the matched feature's last OSM edit if `mapped` carries
    an `osm_timestamp` column, else `NaT` -- see `load_mapped_reference_attrs`), and
    `geometry` (the matched mapped polygon, else `None`).
    """
    n = len(cands)
    out = pd.DataFrame({
        "matched_id": pd.array([None] * n, dtype="object"),
        "dist_m": np.full(n, np.nan),
        "timestamp": pd.Series([pd.NaT] * n, dtype="object"),
        "geometry": [None] * n,
    })
    poly = mapped[mapped.geometry.geom_type.isin(("Polygon", "MultiPolygon"))]
    if cands.empty or poly.empty:
        return out

    cands = cands.reset_index(drop=True)
    reps = cands.geometry.representative_point()
    chunk_deg = 1.0
    keys = list(zip(
        np.floor(reps.x.to_numpy() / chunk_deg).astype(int).tolist(),
        np.floor(reps.y.to_numpy() / chunk_deg).astype(int).tolist(),
    ))
    buf = max_distance_m / 111_000 + 0.02
    for key in sorted(set(keys)):
        mask = np.array([k == key for k in keys])
        sub_positions = np.where(mask)[0]
        sub = cands[mask]
        minx, miny, maxx, maxy = sub.total_bounds
        near = poly.cx[minx - buf: maxx + buf, miny - buf: maxy + buf]
        if near.empty:
            continue
        lon, lat = (minx + maxx) / 2, (miny + maxy) / 2
        epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) / 6) + 1
        su = sub.to_crs(epsg)
        mu = near.to_crs(epsg).reset_index(drop=True)
        sindex = mu.sindex
        idx, d = sindex.nearest(su.geometry.values, return_all=False, return_distance=True)
        # idx[0] = input (candidate-within-chunk) position, idx[1] = tree (mapped) position
        # -- verified against geopandas' own STRtree.nearest contract, not assumed.
        for k in range(idx.shape[1]):
            dist = float(d[k])
            if dist > max_distance_m:
                continue
            cand_pos = sub_positions[int(idx[0, k])]
            tree_pos = int(idx[1, k])
            matched_row = near.iloc[tree_pos]
            out.at[cand_pos, "matched_id"] = matched_row["id"]
            out.at[cand_pos, "dist_m"] = dist
            if "osm_timestamp" in near.columns:
                out.at[cand_pos, "timestamp"] = matched_row["osm_timestamp"]
            out.at[cand_pos, "geometry"] = matched_row.geometry
    log.info(
        "OSM-polygon match (<=%.0f m): %d/%d candidates matched across %d spatial chunks",
        max_distance_m, out["matched_id"].notna().sum(), n, len(set(keys)),
    )
    return out


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
    candidate must literally overlap the mapped geometry) - same as the Lahore
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
    veg_max_ndvi: float | None = None,
    annual_ndvi: Path | None = None, annual_ndvi_max: float = 0.4,
    s1_composites_dir: Path | None = None, s1_vh_max_db: float | None = None,
    sppi_veto: bool = False, sppi_min: float | None = None,
    worldcover_veto: bool = False, ensemble_veto: bool = False,
    sppi_rescue_min: float | None = None,
    min_area_m2: float = 0.0,
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

    any_filter = (
        epoch_clean or veg_max_ndvi is not None or annual_ndvi is not None
        or s1_composites_dir is not None or sppi_veto
        or worldcover_veto or ensemble_veto
    )
    if exclude_mapped or any_filter:
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

    if any_filter:
        # Precision-leaning EXTRA artifact - the only export that drops candidates.
        # The default new_leads file keeps the recall-first contract; this cleaned
        # queue trades a little real PV for far fewer wasted validations. Every
        # veto requires positive evidence - a lead no instrument could check is
        # always kept (absence of evidence is not a verdict).
        leads = leads.reset_index(drop=True)
        drop = np.zeros(len(leads), dtype=bool)
        reason = np.array([""] * len(leads), dtype=object)

        def _veto(mask: np.ndarray, tag: str) -> None:
            fresh = mask & ~drop
            reason[fresh] = tag
            drop[mask] = True

        if epoch_clean:
            # Bright already in the pre-boom (2021/22) epoch -> likely a persistent
            # non-PV feature (the judgement _epoch_note shows mappers, made hard).
            # Caveat: genuinely old unmapped PV is dropped too.
            if not {"epoch_checked", "epoch_prior"} <= set(leads.columns):
                log.warning(
                    "epoch-clean requested but candidates carry no epoch columns - rerun "
                    "`earthpv postprocess` with --preboom-prob-dir first; veto skipped"
                )
            else:
                checked = leads["epoch_checked"].astype(bool).to_numpy()
                fp = checked & (leads["epoch_prior"].to_numpy(float) < epoch_fp_max_prior)
                _veto(fp, "epoch_persistent")
                log.info("Epoch veto: %d of %d checked (epoch_prior < %.2f)",
                         int(fp.sum()), int(checked.sum()), epoch_fp_max_prior)

        if veg_max_ndvi is not None:
            # Green in ANY composite epoch on disk -> vegetation, not PV. Two
            # dry-season medians undersample the crop cycle; the annual instrument
            # below is the thorough version of the same physics.
            from earthpv.vegetation import composite_max_ndvi

            nd = composite_max_ndvi(leads.geometry, aoi, cfg, settings)
            leads["veg_max_ndvi"] = np.round(nd, 3)
            fp = np.nan_to_num(nd, nan=-1.0) > veg_max_ndvi
            _veto(fp, "veg_composite")
            log.info("Composite-NDVI veto: %d of %d covered (max NDVI > %.2f)",
                     int(fp.sum()), int(np.isfinite(nd).sum()), veg_max_ndvi)

        if annual_ndvi is not None:
            # Year-long scene sampling (scripts/veg_annual_ndvi.py): a p95 NDVI
            # above the threshold means the footprint greened up at some point -
            # a crop cycle, which PV never shows.
            tbl = pd.read_parquet(annual_ndvi) if str(annual_ndvi).endswith(".parquet") \
                else pd.read_csv(annual_ndvi)
            p95 = leads["candidate_id"].map(
                tbl.set_index("candidate_id")["ndvi_p95"]).to_numpy(float)
            leads["annual_ndvi_p95"] = np.round(p95, 3)
            fp = np.nan_to_num(p95, nan=-1.0) > annual_ndvi_max
            _veto(fp, "veg_annual")
            log.info("Annual-NDVI veto: %d of %d sampled (p95 NDVI > %.2f)",
                     int(fp.sum()), int(np.isfinite(p95).sum()), annual_ndvi_max)

        if s1_composites_dir is not None:
            # Bare-terrain false positives (dry riverbed, salt flat, bare rock, snow)
            # backscatter darker than real/built PV in both S1 polarizations -- see
            # sar.py's module docstring for the measured cost/catch numbers. Optional:
            # an AOI with no local S1 composites (the common case) never reaches here.
            from earthpv import sar

            vh_max = s1_vh_max_db if s1_vh_max_db is not None else sar.DEFAULT_S1_VH_MAX_DB
            vv, vh = sar.s1_backscatter(leads.geometry, s1_composites_dir)
            leads["s1_vv_db"] = np.round(vv, 2)
            leads["s1_vh_db"] = np.round(vh, 2)
            fp = np.nan_to_num(vh, nan=np.inf) < vh_max
            _veto(fp, "s1_bare_terrain")
            log.info("S1 backscatter veto: %d of %d covered (VH < %.1f dB)",
                     int(fp.sum()), int(np.isfinite(vh).sum()), vh_max)

        if sppi_veto:
            # SPPI (He et al. 2026, sppi.py) scored directly on the candidate's own
            # footprint rather than a building -- a new, unvalidated use of the
            # instrument (see candidate_sppi's docstring). Needs no extra data beyond
            # this AOI's own composites, unlike the S1 check above.
            from earthpv import sppi as sppi_mod

            thresh = sppi_min if sppi_min is not None else sppi_mod.DEFAULT_SPPI_MIN
            sp = sppi_mod.candidate_sppi(leads.geometry, aoi, cfg, settings)
            leads["sppi"] = np.round(sp, 4)
            fp = np.nan_to_num(sp, nan=np.inf) < thresh
            _veto(fp, "sppi_bare_terrain")
            log.info("SPPI veto: %d of %d covered (SPPI < %.4f)",
                     int(fp.sum()), int(np.isfinite(sp).sum()), thresh)

        if worldcover_veto:
            # ESA WorldCover (worldcover.py): directly checks candidates against an
            # existing, independently-trained land-cover classifier rather than a
            # spectral proxy. Strong on bare/mountain terrain, weak on vegetation/
            # epoch-type FP (those correctly read as cropland, not bare) -- see the
            # module docstring. Real cost is concentrated in legitimate ground-mount
            # arrays sited on bare land; prefer --ensemble-veto if that cost is a
            # concern.
            from earthpv import worldcover

            wc, fp = worldcover.candidate_worldcover_veto(leads.geometry)
            leads["wc_class"] = wc
            _veto(fp, "worldcover_bare_terrain")
            log.info("WorldCover veto: %d of %d covered (class in %s)",
                     int(fp.sum()), int(np.isfinite(wc).sum()), worldcover.DEFAULT_VETO_CLASSES)

        if ensemble_veto:
            # ensemble.py: WorldCover's bare/water/snow flag, gated behind SPPI so a
            # candidate is only dropped when SPPI ALSO reads non-PV-like -- roughly
            # halves WorldCover's real-PV cost while keeping most of its catch power
            # on the desert/mountain false-positive class. See ensemble.py's module
            # docstring for the measured cost/catch curve and why simple voting
            # across S1/SPPI/WorldCover was tried and rejected (it either costs too
            # much real PV or throws away WorldCover's catch entirely).
            from earthpv import ensemble

            rescue = (
                sppi_rescue_min if sppi_rescue_min is not None
                else ensemble.DEFAULT_SPPI_RESCUE_MIN
            )
            fp, wc, sp = ensemble.combined_bare_terrain_veto(
                leads.geometry, aoi, cfg, settings, sppi_rescue_min=rescue
            )
            leads["wc_class"] = wc
            leads["sppi"] = np.round(sp, 4)
            _veto(fp, "ensemble_bare_terrain")
            log.info("Ensemble (WorldCover gated by SPPI) veto: %d flagged "
                     "(SPPI rescue threshold %.4f)", int(fp.sum()), rescue)

        clean = leads[~drop]
        cl = pred_dir / f"{aoi}_pv_new_leads_clean.geojson"
        clean.to_file(cl, driver="GeoJSON")
        log.info("Clean leads: %d / %d kept (dropped: %s) -> %s",
                 len(clean), len(leads),
                 ", ".join(f"{t}={int((reason == t).sum())}"
                           for t in ("epoch_persistent", "veg_composite", "veg_annual",
                                     "s1_bare_terrain", "sppi_bare_terrain",
                                     "worldcover_bare_terrain", "ensemble_bare_terrain")
                           if (reason == t).any()) or "none",
                 cl.name)

        # Vegetation-vetoed leads are near-conclusive non-PV (a crop cycle is
        # positive evidence, unlike epoch persistence, which old real PV also
        # shows) -> hard-negative training centers for the next retrain, in the
        # lon/lat schema `earthpv hard-negative-chips --centers` consumes.
        veg_fp = leads[np.isin(reason, ("veg_composite", "veg_annual"))]
        if not veg_fp.empty:
            reps = veg_fp.geometry.representative_point()
            hn = veg_fp.drop(columns="geometry").assign(
                lon=reps.x.to_numpy(), lat=reps.y.to_numpy(),
                evidence=reason[np.isin(reason, ("veg_composite", "veg_annual"))],
            )
            keep_cols = [c for c in ("candidate_id", "lon", "lat", "evidence", "area_m2",
                                     "veg_max_ndvi", "annual_ndvi_p95") if c in hn.columns]
            hn_path = pred_dir / "hard_negatives_veg.parquet"
            pd.DataFrame(hn[keep_cols]).to_parquet(hn_path)
            log.info("Wrote %d vegetation hard-negative centers -> %s "
                     "(feed to `earthpv hard-negative-chips --centers`)",
                     len(hn), hn_path.name)

        # S1-vetoed leads are a coarser signal than the vegetation veto (see sar.py --
        # the two distributions overlap substantially), so kept as a separate hard-
        # negative file rather than folded into hard_negatives_veg.parquet's evidence.
        s1_fp = leads[reason == "s1_bare_terrain"]
        if not s1_fp.empty:
            reps = s1_fp.geometry.representative_point()
            hn = s1_fp.drop(columns="geometry").assign(
                lon=reps.x.to_numpy(), lat=reps.y.to_numpy(), evidence="s1_bare_terrain",
            )
            keep_cols = [c for c in ("candidate_id", "lon", "lat", "evidence", "area_m2",
                                     "s1_vv_db", "s1_vh_db") if c in hn.columns]
            hn_path = pred_dir / "hard_negatives_s1.parquet"
            pd.DataFrame(hn[keep_cols]).to_parquet(hn_path)
            log.info("Wrote %d S1 hard-negative centers -> %s "
                     "(feed to `earthpv hard-negative-chips --centers`)",
                     len(hn), hn_path.name)

        # Same rationale as the S1 hard-negative file above -- kept separate since the
        # measured cost/catch profile differs (see candidate_sppi's docstring).
        sppi_fp = leads[reason == "sppi_bare_terrain"]
        if not sppi_fp.empty:
            reps = sppi_fp.geometry.representative_point()
            hn = sppi_fp.drop(columns="geometry").assign(
                lon=reps.x.to_numpy(), lat=reps.y.to_numpy(), evidence="sppi_bare_terrain",
            )
            keep_cols = [c for c in ("candidate_id", "lon", "lat", "evidence", "area_m2",
                                     "sppi") if c in hn.columns]
            hn_path = pred_dir / "hard_negatives_sppi.parquet"
            pd.DataFrame(hn[keep_cols]).to_parquet(hn_path)
            log.info("Wrote %d SPPI hard-negative centers -> %s "
                     "(feed to `earthpv hard-negative-chips --centers`)",
                     len(hn), hn_path.name)

        # WorldCover and ensemble vetoes are the two `--worldcover-veto`/`--ensemble-
        # veto` flags -- mutually exclusive in normal use (the latter is a refinement
        # of the former), but kept as separate hard-negative files regardless since
        # each records a different confirming instrument.
        for tag, cols, path_name in (
            ("worldcover_bare_terrain", ("candidate_id", "lon", "lat", "evidence",
                                         "area_m2", "wc_class"), "hard_negatives_worldcover.parquet"),
            ("ensemble_bare_terrain", ("candidate_id", "lon", "lat", "evidence",
                                       "area_m2", "wc_class", "sppi"), "hard_negatives_ensemble.parquet"),
        ):
            sub = leads[reason == tag]
            if sub.empty:
                continue
            reps = sub.geometry.representative_point()
            hn = sub.drop(columns="geometry").assign(
                lon=reps.x.to_numpy(), lat=reps.y.to_numpy(), evidence=tag,
            )
            keep_cols = [c for c in cols if c in hn.columns]
            hn_path = pred_dir / path_name
            pd.DataFrame(hn[keep_cols]).to_parquet(hn_path)
            log.info("Wrote %d hard-negative centers -> %s "
                     "(feed to `earthpv hard-negative-chips --centers`)",
                     len(hn), hn_path.name)

    if min_area_m2 > 0:
        # The segmentation model's own trained positive-class floor is MIN_PV_AREA
        # (chips.py), but polygonize_chips does not enforce it on its OUTPUT -- small
        # blobs below that floor still surface as candidates (near-chance noise, per
        # the model's own training regime). This is a separate, explicit filter for
        # whoever wants a validation queue scoped to the project's stated detection
        # floor, applied to the most-processed lead set already computed above.
        base = clean if any_filter else (leads if exclude_mapped else cands)
        scoped = base[base.area_m2 >= min_area_m2]
        sp = pred_dir / f"{aoi}_pv_new_leads_ge{int(min_area_m2)}m2.geojson"
        scoped.to_file(sp, driver="GeoJSON")
        log.info("Area-scoped leads (>= %.0f m2): %d / %d kept -> %s",
                 min_area_m2, len(scoped), len(base), sp.name)

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
