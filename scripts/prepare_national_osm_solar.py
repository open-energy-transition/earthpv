"""Build the placement-classified national OSM solar parquet the evidence atlas needs.

`atlas.build_evidence_atlas` takes `--osm-solar` and reads `placement` and `area_m2` off
it: the Verified tier is the hand-mapped OSM population, converted at the module constant
for rooftop and the land constant for everything else. Pakistan's national pull carries
both columns because it came through `labels.classify_placement`. A raw rooftopsenti pull
(e.g. `germany_500/osm/solar.parquet`) does not -- it has `location_tag` and a `tags` JSON
blob and nothing else -- so the atlas fails with `KeyError: 'placement'`.

This derives the columns from what the project has already computed.
`export.load_mapped_reference_attrs` reconciles the rooftopsenti cache and any Overpass
pulls into `id`/`placement`/`area_m2`/`source`/`osm_timestamp`, so the classification does
not have to be redone -- which matters, because redoing it means a VIDA building-overlap
query per 0.25 degree cell over a 4.3 GB country parquet.

Two corrections are applied to that placement, both measured rather than assumed:

  * **`small` -> `rooftop`.** `local_source.load_solar_labels` uses `small` as a SIZE
    class (sub-`MIN_PV_AREA`), not a placement. Those are residential rooftop arrays, and
    leaving them unmapped would convert 114k features at the land constant, understating
    them roughly 3.6x.
  * **An area cap on `rooftop`.** Germany's reference labels 1,167 features above
    50,000 m2 as rooftop, median 89,264 m2 and largest 4.19 km2. Nine hectares is not a
    rooftop array; these are plant perimeters or multi-building complexes. Converting them
    at the module constant would overstate them by the same 3.6x in the other direction --
    exactly the ground-mount overstatement `density.py` splits placement to avoid. Anything
    above `ROOFTOP_MAX_M2` is therefore treated as ground.

`unknown` is left alone and converts at the land constant, which is the conservative
choice for a feature whose placement nothing in the data establishes.

`panel_traced` marks polygons last edited by an account the AOI names in
`osm_panel_tracers` (configs/aoi.yaml; Yemen's owner-mapper since 2026-10-24). They are
traced around the panels, so the atlas converts them at the module constant even on the
ground, where any other ground polygon is a site at the land constant.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from earthpv.config import Settings
from earthpv.density import OSM_GROUND_MAX_M2, SCREEN_MIN_DET_FRAC, SCREEN_MIN_IMAGED_FRAC
from earthpv.export import load_mapped_reference_attrs
from earthpv.labels import geodesic_area_m2, resolve_aoi
from earthpv.postprocess import MAX_CANDIDATE_M2

log = logging.getLogger(__name__)

# Same cap the candidate population uses. A rooftop PV array larger than this does not
# exist; the largest real single-roof installations are a few hectares.
ROOFTOP_MAX_M2 = MAX_CANDIDATE_M2

# A ground-mount polygon above this is not an installation either, and unlike the rooftop cap
# there is nowhere to reclassify it TO, so it is dropped. Measured against MaStR on 2026-09-13,
# by size band, as the share of German OSM `ground` polygons containing at least one registered
# ground unit (registration is mandatory and 81.2% of ground units carry coordinates):
#
#     0-1 km2   28,471 polygons  438.4 km2   13% corroborated
#     1-5 km2       80 polygons  161.4 km2   28% corroborated
#     5-10 km2      15 polygons   93.5 km2    0% corroborated
#     10+ km2        6 polygons  207.1 km2    0% corroborated
#
# Corroboration collapses to exactly zero above 5 km2 -- not a tuned threshold but the point
# where the population stops being PV at all. Germany's largest real solar park is about 5 km2.
# Those 21 polygons hold 33% of all German OSM ground area and contributed ~15 GWp to the
# atlas's Verified tier, which is why it read 121% of all registered German ground-mount.
# Defined in density.py, whose `capacity_relevant_candidates` applies the same cap and the
# same screen evidence to OSM outlines on the model side (2026-10-11; docs/results/india.md,
# "The ground-perimeter screen and the 5 km2 cap").
GROUND_MAX_M2 = OSM_GROUND_MAX_M2


def prepare(aoi: str, out: Path, rooftop_max_m2: float = ROOFTOP_MAX_M2,
            ground_max_m2: float = GROUND_MAX_M2, labels: Path | None = None,
            clip: bool = True, keep_detected_screen: Path | None = None,
            keep_min_det_frac: float = SCREEN_MIN_DET_FRAC) -> Path:
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    if labels is not None:
        # `load_mapped_reference_attrs` globs `data/labels/*_overpass_solar.parquet`
        # AOI-AGNOSTICALLY (see CLAUDE.md), so for an AOI whose only reference is its own
        # Overpass pull it would dissolve ~700k Pakistani/French/German features to find
        # the few thousand local ones. Reading that one pull directly is the same answer
        # for a fraction of the work -- and it keeps the log's feature count honest.
        import geopandas as gpd

        ref = gpd.read_parquet(labels).reset_index(drop=True)
        if "source" not in ref.columns:
            ref["source"] = "overpass"
        if "osm_timestamp" not in ref.columns:
            ref["osm_timestamp"] = None
        if "placement" not in ref.columns:
            ref["placement"] = "unknown"
        from earthpv.labels import dissolve_overlapping

        raw = ref  # the undissolved features, for the cap's member floor below
        ref = dissolve_overlapping(ref).reset_index(drop=True)
    else:
        raw = None  # already dissolved upstream: no members to recover
        ref = load_mapped_reference_attrs(aoi, cfg, settings).reset_index(drop=True)
    log.info("%s: %d reference features", aoi, len(ref))

    if clip:
        # A "national" OSM pull must actually be national. Two ways it is not, and both were
        # live until 2026-09-15:
        #   * `load_mapped_reference_attrs` globs data/labels/*_overpass_solar.parquet
        #     AOI-AGNOSTICALLY (see CLAUDE.md), so Germany's file spanned lon 5.9-75.4 and
        #     lat 20.8-54.9 -- it reached into Pakistan.
        #   * A bbox-limited pull is not a border-limited one: France's bbox contains
        #     Belgium, Luxembourg, Germany, Switzerland, Italy and Spain.
        # Both were invisible while the atlas dropped OSM outside its density grid. Once
        # `--include-offgrid-osm` keeps that population, every foreign feature becomes a
        # cell and drags the map across a continent.
        from earthpv.buildings import _iso3_for
        from earthpv.density import fetch_geoboundaries

        iso3 = _iso3_for(cfg)
        adm1 = fetch_geoboundaries(iso3, "ADM1") if iso3 else None
        if adm1 is None:
            log.warning("no geoBoundaries ADM1 for %r -- keeping the unclipped pull", iso3)
        else:
            import shapely

            country = adm1.to_crs("EPSG:4326").geometry.union_all()
            rep = ref.geometry.representative_point()
            inside = shapely.contains_xy(country, rep.x.values, rep.y.values)
            log.info(
                "clipped to %s: %d of %d features inside the national boundary (%d dropped)",
                iso3, int(inside.sum()), len(ref), int((~inside).sum()),
            )
            ref = ref[inside].reset_index(drop=True)

    if "area_m2" not in ref.columns or ref["area_m2"].isna().any():
        ref["area_m2"] = [geodesic_area_m2(g) for g in ref.geometry]
    ref["area_m2"] = ref["area_m2"].fillna(0.0)

    ref["placement_raw"] = ref["placement"].astype(object)
    placement = ref["placement"].fillna("unknown").to_numpy().astype(object)
    n_small = int((placement == "small").sum())
    placement[placement == "small"] = "rooftop"

    oversize = (placement == "rooftop") & (ref["area_m2"].to_numpy() > rooftop_max_m2)
    n_oversize = int(oversize.sum())
    if n_oversize:
        med = float(np.median(ref["area_m2"].to_numpy()[oversize]))
        mx = float(ref["area_m2"].to_numpy()[oversize].max())
        log.warning(
            "%d 'rooftop' features above %.0f m2 (median %.0f, max %.0f) reclassified as "
            "ground -- a rooftop array that large does not exist, and converting them at "
            "the module constant would overstate them ~3.6x",
            n_oversize, rooftop_max_m2, med, mx,
        )
    placement[oversize] = "ground"
    ref["placement"] = placement

    # Drop implausible ground polygons. `density.py` deliberately exempts OSM-sourced oversize
    # features from its own cap, on the assumption that a human-mapped footprint is real. An
    # 88 km2 "solar" polygon is where that assumption fails.
    too_big = (ref["placement"].to_numpy() == "ground") & (
        ref["area_m2"].to_numpy() > ground_max_m2)
    # ...unless the model itself sees panels over most of it. The 5 km2 cap is a German
    # measurement (Germany's largest real park is ~5 km2); Vietnam has model-confirmed parks
    # of 5.6-8.3 km2 (2026-09-26: five relations, 92-99% of each area detected, 1.9 GWp at
    # the land constant) and India's largest are tens of km2. The per-perimeter screen
    # (scripts/screen_osm_ground_perimeters.py) is the evidence: a feature is kept when it
    # was imaged and the checkpoint detects PV over at least `keep_min_det_frac` of it.
    #
    # ...and an outline that fails the screen is CREDITED, not dropped (2026-10-28,
    # docs/results/india.md). Dropping it lost two things, both in India:
    #   * the panels the model does see inside it. `density` already credits such an outline
    #     at outline x det_frac on the model side, but there the size bin's p_real halved it
    #     again, so Khavda's two outlines (150 km2, 44.6 km2 detected) came to Best at 1,123
    #     MWp instead of ~2,230. Carried here at the same share, Verified holds it and Best's
    #     per-cell floor takes it whole.
    #   * plants mapped INSIDE it. The cap is applied after `dissolve_overlapping`, so a
    #     3.4 km2 park nested in a 5.1 km2 site outline went out with the site, though alone
    #     it is under the cap. The credit is floored at the union of such members.
    # The credited share lands in `area_m2` (so every consumer that sums area is right) and
    # in `screen_credit` (credited / outline, which `atlas._apply_screen_credit` reapplies
    # after its own dissolve). Only an outline that earns nothing either way is dropped.
    screen_credit = np.ones(len(ref))
    n_credited, credited_km2, outline_km2 = 0, 0.0, 0.0
    if keep_detected_screen is not None and too_big.any():
        scr = pd.read_csv(keep_detected_screen).drop_duplicates("id").set_index("id")
        ok_ids = set(scr.index[(scr["imaged_frac"] >= SCREEN_MIN_IMAGED_FRAC)
                               & (scr["det_frac"] >= keep_min_det_frac)])
        rescued = too_big & ref["id"].isin(ok_ids).to_numpy()
        if rescued.any():
            log.warning(
                "keeping %d 'ground' features above %.0f m2 (%.1f km2) that the screen %s "
                "shows imaged and >= %.0f%% detected -- real parks, not project outlines",
                int(rescued.sum()), ground_max_m2,
                ref["area_m2"].to_numpy()[rescued].sum() / 1e6, keep_detected_screen,
                100 * keep_min_det_frac,
            )
        too_big = too_big & ~rescued
        for i in np.flatnonzero(too_big):
            outline = float(ref["area_m2"].iat[i])
            det = scr["det_frac"].get(ref["id"].iat[i], np.nan)
            credit = outline * (0.0 if pd.isna(det) else float(det))
            members = _sub_cap_member_m2(raw, ref.iloc[i], ground_max_m2)
            credit = min(max(credit, members), outline)
            if credit > 0:
                screen_credit[i] = credit / outline
                too_big[i] = False
                n_credited += 1
                credited_km2 += credit / 1e6
                outline_km2 += outline / 1e6
        if n_credited:
            log.warning(
                "crediting %d 'ground' features above %.0f m2 that fail the screen at the share "
                "the model detects (floored at their nested sub-cap plants): %.1f of %.1f km2",
                n_credited, ground_max_m2, credited_km2, outline_km2,
            )
    n_dropped = int(too_big.sum())
    if n_dropped:
        log.warning(
            "dropping %d 'ground' features above %.0f m2 (%.1f km2, largest %.1f km2) -- none "
            "of the German ones contains a registered ground unit, so they are not "
            "installations",
            n_dropped, ground_max_m2, ref["area_m2"].to_numpy()[too_big].sum() / 1e6,
            ref["area_m2"].to_numpy()[too_big].max() / 1e6,
        )
    ref["screen_credit"] = screen_credit
    ref["area_m2"] = ref["area_m2"].to_numpy(float) * screen_credit
    ref = ref[~too_big].reset_index(drop=True)

    log.info(
        "placement: %s (small->rooftop: %d, rooftop->ground on size: %d)",
        ref["placement"].value_counts().to_dict(), n_small, n_oversize,
    )
    # Polygons the AOI's named mappers traced around the panels (`osm_panel_tracers`): the
    # atlas converts them at the module constant whatever their placement.
    from earthpv.labels import panel_traced

    ref["panel_traced"] = panel_traced(ref, aoi)
    if ref["panel_traced"].any():
        t = ref["panel_traced"].to_numpy() & (ref["placement"].to_numpy() != "rooftop")
        log.info("%d polygons traced around their panels (%d ground, %.0f m2)",
                 int(ref["panel_traced"].sum()), int(t.sum()), float(ref["area_m2"].to_numpy()[t].sum()))
    out.parent.mkdir(parents=True, exist_ok=True)
    ref[["id", "placement", "area_m2", "source", "osm_timestamp", "panel_traced", "screen_credit",
         "geometry"]].to_parquet(out)
    log.info("Wrote %s", out)
    return out


def _sub_cap_member_m2(raw, cluster, cap_m2: float) -> float:
    """Geodesic area of the union of the undissolved features of `cluster`'s own placement
    that lie mostly inside it and are each at or under the cap: the plants mapped inside an
    outline, which the cap would have kept had it run before the dissolve. 0 without `raw`."""
    import shapely

    if raw is None:
        return 0.0
    cand = raw[raw.geometry.geom_type.isin(("Polygon", "MultiPolygon"))
               & (raw["placement"].astype(str) == str(cluster["placement_raw"]))
               & (raw["id"] != cluster["id"])]
    cand = cand[cand.intersects(cluster.geometry)]
    if cand.empty:
        return 0.0
    area = np.array([geodesic_area_m2(g) for g in cand.geometry])
    inside = np.array([geodesic_area_m2(shapely.intersection(g, cluster.geometry))
                       for g in cand.geometry])
    keep = (area <= cap_m2) & (inside >= 0.5 * np.maximum(area, 1e-9))
    if not keep.any():
        return 0.0
    return float(geodesic_area_m2(shapely.union_all(cand.geometry.to_numpy()[keep])))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--rooftop-max-m2", type=float, default=ROOFTOP_MAX_M2)
    ap.add_argument("--ground-max-m2", type=float, default=GROUND_MAX_M2)
    ap.add_argument(
        "--labels", type=Path, default=None,
        help="Read this one placement-classified pull (e.g. "
        "data/labels/<aoi>_overpass_solar.parquet) instead of pooling every "
        "data/labels/*_overpass_solar.parquet in the repo. Use it for an AOI whose only "
        "reference is its own pull; the corrections applied are identical.",
    )
    ap.add_argument(
        "--no-clip", action="store_true",
        help="Keep features outside the AOI's national boundary. Off by default; see the "
        "clip block in `prepare` for the two ways a 'national' pull turns out not to be.",
    )
    ap.add_argument(
        "--keep-detected-screen", type=Path, default=None,
        help="An OSM ground screen CSV (scripts/screen_osm_ground_perimeters.py). Ground "
        "features above --ground-max-m2 are KEPT when that screen shows them imaged and "
        "detected over at least --keep-min-det-frac of their area. Off by default.",
    )
    ap.add_argument("--keep-min-det-frac", type=float, default=SCREEN_MIN_DET_FRAC)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = a.out or Path(f"data/labels/{a.aoi}_national_osm_solar.parquet")
    prepare(a.aoi, out, a.rooftop_max_m2, a.ground_max_m2, labels=a.labels, clip=not a.no_clip,
            keep_detected_screen=a.keep_detected_screen, keep_min_det_frac=a.keep_min_det_frac)


if __name__ == "__main__":
    main()
