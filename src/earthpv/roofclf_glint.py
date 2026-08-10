"""Glint as a roofclf FEATURE, not just a standalone detector -- creative idea #1 from
the 2026-08-09 precision-improvement discussion, implemented the same day.

Every existing roofclf feature (`SPECTRAL_FEATURES`, `SHAPE_FEATURES`,
`LOCAL_CONTRAST_FEATURES`) is angle-agnostic: a per-pixel mean or a footprint shape
computed once, blind to sun/view geometry. Glint is a physically distinct signal --
a glass-fronted PV panel is partly a specular reflector, and glints only when its tilt
bisects the sun and view vectors, a narrow geometric condition that varies scene to scene
(`glint.py`'s module docstring). The bright-roof false-positive mode (cell `0061_0012`'s
six buildings, scored 0.98-1.00 by roofclf and mostly uncaught by SPPI too) is bright for
a diffuse reason with no such geometric structure -- glint is the one signal in this
project that could tell the two apart on physical grounds rather than just reflectance
level. It has been run as a standalone detector (`scripts/glint_direct_detect.py`, ~9%
recall on the model's own new_leads) but never folded back into `roofclf.building_table`.

**This is NETWORK-BOUND and slow, unlike every other roofclf feature.** Cost scales with
(number of Sentinel-2 scenes in the date range) x (number of distinct ~1deg tiles the
buildings span) -- `glint.tile_scene_series_batch` opens each scene's band asset ONCE and
shares it across every building in that tile, so it does NOT scale with building count.
But per-tile cost is still real: `glint_direct_detect.py`'s own Lahore pilot (one tile)
took "2.5+ hours under degraded Planetary Computer conditions" for 198 candidates -- the
building count barely mattered, the tile's own scene count did. Computing this for all 13
density-calibrated quadrats (~10-13 distinct tiles) is a multi-hour-to-day pull, not
something to run inline in `building_table`/`score_buildings_national` by default --
call `glint_score_features` explicitly and expect it to take a while, exactly like
`hard_negatives.run_hard_negatives`'s own network-bound mining pass.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Matches `scripts/glint_direct_detect.py`'s own window: recent enough that Sentinel-2
# scenes and consistent PV installation are both plausible, ~2 years for enough revisits
# to fit an orientation from >= 2 self-consistent spikes.
DEFAULT_DATE_RANGE = (
    datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 14, tzinfo=timezone.utc),
)

GLINT_FEATURES = ["glint_n_consistent", "glint_spike_rate"]


def glint_score_features(
    buildings: gpd.GeoDataFrame,
    date_range: tuple[datetime, datetime] = DEFAULT_DATE_RANGE,
    tile_deg: float = 1.0,
    max_workers: int = 20,
) -> pd.DataFrame:
    """Two per-building glint features, indexed to match `buildings`:

    - `glint_n_consistent`: how many detected spikes across the time series fit ONE
      shared panel orientation within tolerance (`glint.fit_best_orientation`'s own
      output) -- 0 for no evidence, 1 for a single unconfirmed spike, 2+ for the same
      standard the standalone detector uses to call a building "validated". Given to the
      model as a continuous count rather than thresholded, so it can weigh partial
      evidence instead of losing it to a binary cutoff.
    - `glint_spike_rate`: n_spikes / n_scenes -- how often ANY glint-like brightness
      spike appears, looser than `n_consistent` (does not require self-consistency), so
      it still carries signal for a building with too few scenes to fit an orientation.

    A building with zero Sentinel-2 scenes in range (`tile_scene_series_batch` found
    nothing) gets 0.0 for both, not NaN -- "no glint evidence found" is a legitimate,
    common value here (most roofs, PV or not, will show it), and this module's own
    scores must never introduce NaN into `design_matrix`, unlike a composite read that can
    legitimately have no valid pixel at all.
    """
    from earthpv import glint

    targets = pd.DataFrame({
        "pid": buildings.index.astype(str).to_numpy(),
        "geometry": buildings.geometry.to_numpy(),
        "lon": buildings.geometry.centroid.x.to_numpy(),
        "lat": buildings.geometry.centroid.y.to_numpy(),
    })
    log.info(
        "glint_score_features: %d buildings, date range %s to %s (network-bound, one "
        "STAC search + band reads per ~%.1f deg tile group, expect minutes to hours)",
        len(targets), date_range[0].date(), date_range[1].date(), tile_deg,
    )
    series_by_pid = glint.tile_scene_series_batch(
        targets, *date_range, tile_deg=tile_deg, max_workers=max_workers,
    )

    n_consistent = np.zeros(len(targets))
    spike_rate = np.zeros(len(targets))
    n_no_scenes = 0
    for i, pid in enumerate(targets.pid):
        df = series_by_pid.get(pid, pd.DataFrame())
        if df.empty:
            n_no_scenes += 1
            continue
        res = glint.spike_fit(df, self_referenced=True)
        n_consistent[i] = res["n_consistent"]
        spike_rate[i] = res["n_spikes"] / max(res["n_scenes"], 1)
    log.info(
        "glint_score_features: %d/%d buildings had no scenes in range (score 0.0), "
        "%d with n_consistent >= 2", n_no_scenes, len(targets), int((n_consistent >= 2).sum()),
    )
    return pd.DataFrame(
        {"glint_n_consistent": n_consistent, "glint_spike_rate": spike_rate},
        index=buildings.index,
    )
