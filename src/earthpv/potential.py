"""Large-roof, currently-uncovered rooftop potential -- pure geometry, no PV-presence
probability, deliberately outside every sub-400 m2 calibration debate on record.

`roofclf.score_buildings_national` (roofclf.py) already scored every VIDA building
nationally and wrote one parquet per 0.1 deg cell under
`data/roofclf_national_with_sppi/<aoi>/prob/` with `cell, geometry, roof_area_m2,
p_roofclf, sppi` -- a full-population roof-footprint table. This module reuses only its
`roof_area_m2`/`geometry` columns, never `p_roofclf`/`sppi`: it measures building
footprint size, not predicted PV presence, so none of the precision/calibration
problems documented for the sub-400 m2 instruments
(docs/issues/roofclf-national-deployment-and-temporal-features.md) apply here.

`min_roof_m2` defaults to 200 m2, not the segmentation model's 400 m2 detection floor --
a deliberate choice to cover more of the realistic rooftop-opportunity space (roughly
where Germany's MaStR register shows most rooftop capacity actually sits). Buildings in
the 200-400 m2 sub-band get no discriminating signal from the segmentation-based
"already covered" subtraction downstream in `atlas.py::build_potential_atlas` (the
segmentation model is trained with everything below `chips.MIN_PV_AREA` = 400 m2 burned
as `ignore`), so that sub-band's "potential" reads as almost entirely uncovered
regardless of ground truth -- expected, not a bug, but worth knowing when reading the
map (see docs/methods/density.md).
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_MIN_ROOF_M2 = 200.0
# The segmentation model's own detection floor (chips.MIN_PV_AREA) -- used only to
# split the logged summary into "already-known population" vs. "new below-floor slice",
# not as a filter.
DETECTION_FLOOR_M2 = 400.0


def large_roof_buildings(
    roofclf_dir: Path, min_roof_m2: float = DEFAULT_MIN_ROOF_M2
) -> gpd.GeoDataFrame:
    """Every VIDA building nationally whose footprint is >= `min_roof_m2`, columns
    `cell, geometry, roof_area_m2` only -- `p_roofclf`/`sppi` are dropped even though
    the source files carry them, since this function's whole point is to answer a
    question those scores were never trained to answer.

    Reads every per-cell parquet in `roofclf_dir` (no domain restriction -- there is no
    precision estimate here to protect from an unrepresentative sample, unlike
    `sub400_capacity.domain_restricted_capacity`).
    """
    roofclf_dir = Path(roofclf_dir)
    parts = []
    for p in sorted(roofclf_dir.glob("*.parquet")):
        d = gpd.read_parquet(p, columns=["cell", "geometry", "roof_area_m2"])
        if d.empty:
            continue
        f = d[d.roof_area_m2 >= min_roof_m2]
        if not f.empty:
            parts.append(f)
    if not parts:
        raise ValueError(
            f"No buildings >= {min_roof_m2} m2 found under {roofclf_dir} -- check the "
            "directory holds `score_buildings_national`'s per-cell output"
        )
    buildings = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")

    n_total = len(buildings)
    area_total = float(buildings.roof_area_m2.sum())
    above = buildings.roof_area_m2 >= DETECTION_FLOOR_M2
    n_above, area_above = int(above.sum()), float(buildings.loc[above, "roof_area_m2"].sum())
    n_below, area_below = n_total - n_above, area_total - area_above
    log.info(
        "large_roof_buildings: %d buildings >= %.0f m2 (%.1f km2 total) -- %d/%d "
        "(%.1f/%.1f km2) already >= the %.0f m2 detection floor, %d/%d (%.1f/%.1f km2) "
        "are the new %.0f-%.0f m2 slice below it",
        n_total, min_roof_m2, area_total / 1e6,
        n_above, n_total, area_above / 1e6, area_total / 1e6, DETECTION_FLOOR_M2,
        n_below, n_total, area_below / 1e6, area_total / 1e6,
        min_roof_m2, DETECTION_FLOOR_M2,
    )
    return buildings
