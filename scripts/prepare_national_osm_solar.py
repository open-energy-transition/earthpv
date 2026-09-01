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
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

from earthpv.config import Settings
from earthpv.export import load_mapped_reference_attrs
from earthpv.labels import geodesic_area_m2, resolve_aoi
from earthpv.postprocess import MAX_CANDIDATE_M2

log = logging.getLogger(__name__)

# Same cap the candidate population uses. A rooftop PV array larger than this does not
# exist; the largest real single-roof installations are a few hectares.
ROOFTOP_MAX_M2 = MAX_CANDIDATE_M2


def prepare(aoi: str, out: Path, rooftop_max_m2: float = ROOFTOP_MAX_M2) -> Path:
    settings = Settings.load()
    _, cfg = resolve_aoi(aoi, settings)
    ref = load_mapped_reference_attrs(aoi, cfg, settings).reset_index(drop=True)
    log.info("%s: %d reference features", aoi, len(ref))

    if "area_m2" not in ref.columns or ref["area_m2"].isna().any():
        ref["area_m2"] = [geodesic_area_m2(g) for g in ref.geometry]
    ref["area_m2"] = ref["area_m2"].fillna(0.0)

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

    log.info(
        "placement: %s (small->rooftop: %d, rooftop->ground on size: %d)",
        ref["placement"].value_counts().to_dict(), n_small, n_oversize,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    ref[["id", "placement", "area_m2", "source", "osm_timestamp", "geometry"]].to_parquet(out)
    log.info("Wrote %s", out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--rooftop-max-m2", type=float, default=ROOFTOP_MAX_M2)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = a.out or Path(f"data/labels/{a.aoi}_national_osm_solar.parquet")
    prepare(a.aoi, out, a.rooftop_max_m2)


if __name__ == "__main__":
    main()
