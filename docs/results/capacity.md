# Pakistan capacity map

How much rooftop solar does Pakistan actually have? The honest answer depends on how much
proof you require, so this atlas gives two, not one: what a person has actually drawn in
OpenStreetMap, and this project's own best defensible estimate. Both read the same
underlying detections -- a segmentation model for individual arrays 400 m<sup>2</sup> and
larger, plus two independent per-building instruments (**roofclf**, **SPPI**) for
everything smaller that the segmentation model is trained blind to. A third, looser
tier (an explicit, uncalibrated ceiling) was published here through early August 2026 and
was retired 2026-08-06: a roofclf refit's lower deployment threshold roughly doubled it
with no accompanying validation, so it had stopped being a meaningful bound.

<div class="embed" markdown>
<iframe src="../../assets/interactive/pakistan_evidence_atlas.html" title="Pakistan PV evidence atlas: Verified and Best estimate" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Switch tier with the tabs, hover a cell for its value.
<a href="../../assets/interactive/pakistan_evidence_atlas.html" target="_blank">Open full screen</a>.
</p>

## Two tiers, one country

| Tier | Pakistan | What it admits as evidence |
| --- | ---: | --- |
| Verified | 13,697 MWp | Every installation a person has drawn in OpenStreetMap (16,085 of them), plus sub-400 m<sup>2</sup> buildings where **roofclf and SPPI both agree** -- two independent detectors, not one model trusted alone. |
| **Best estimate** | **21,355 MWp** | Verified, plus the segmentation model's own recall-corrected detections **&ge;400 m<sup>2</sup>** (5,078 MWp, precision- and recall-corrected), plus the roofclf per-building density estimate inside the cells checked against ground-truth quadrats -- the project's own pick. |

Both tiers fold in the same &ge;400 m<sup>2</sup> segmentation total; what changes between
them is how much of the sub-400 m<sup>2</sup> population each is willing to trust, and at
what precision. Neither double-counts, on either axis: OpenStreetMap-mapped installations
are matched by location and removed from the model-detected side before summing, **and**
(fixed 2026-08-06) the sub-400 m<sup>2</sup> instrument itself drops any building within 30 m
of an OpenStreetMap solar feature, not just those near an existing segmentation candidate --
without that second check, a building OSM had already mapped but segmentation missed
entirely could be counted twice (measured before the fix: 3.3-3.8% of the sub-400 m<sup>2</sup>
component's MWp, 343-438 MWp).

!!! warning "This is a research methodology under active validation, not a finished census"
    All 17 ground-truth calibration quadrats are now **Rule-1 complete** (every
    visible panel independently verified, as of 2026-08-05), and the density-matched
    calibration covers 401 of Pakistan's 4,463 grid cells. roofclf's own measured skill
    still varies by quadrat (AUC 0.76 to 0.94 across the 17) and its predicted rate does
    not reliably separate well-calibrated cells from over-predicting ones -- see
    [Capacity density](../methods/density.md) for what is independently corroborated
    and what is still open.

## Segmentation: the part of this that outlines panels

The &ge;400 m<sup>2</sup> segmentation total (5,078 MWp, [1,841 to 2,930] rooftop-only
credible interval once split by placement) is the one component present in every tier
above. A recall-first TerraMind checkpoint reads a year of Sentinel-2 imagery across every
building-populated cell, and pixels above threshold are polygonized, joined to a building
footprint, and reweighted by a measured probability of being real before their area is
counted. Rooftop and ground-mount candidates convert to capacity at different rates,
because a rooftop detection outlines the panels while a ground-mount detection outlines
the *site* -- see [Capacity density](../methods/density.md) for both derivations, and
[Growth](growth.md) for how this same instrument changed between the 2021/22 pre-boom
epoch and now.

## Using it in an energy model like [PyPSA](https://pypsa.org/)

The density stage writes three layers under `data/predictions/<aoi>/density/`:

* `buildings.geoparquet` -- one row per building carrying PV signal, with roof area,
  PV area under each metric, estimated kWp and rooftop or ground placement.
* `grid.csv` and `grid.geoparquet` -- one row per 0.1 degree cell. The `lon_center` and
  `lat_center` columns map straight onto atlite or PyPSA-Earth cutout grids and Voronoi
  bus regions.
* `regions.*` -- per province, and with `--districts` per ADM2, additive totals with
  credible bands rebuilt from summed posterior draws.

Bin-level uncertainty is fully correlated across cells, so a regional interval must be
built from summed draws. Adding per-cell bounds gives the wrong answer.

## Reproducing this map

This is earthpv's [main workflow](../reproduce.md#the-full-pipeline), end to end: the
&ge;400 m<sup>2</sup> segmentation half, then the < 400 m<sup>2</sup> roofclf half, then
the atlas that combines them.

```bash
# >= 400 m2 segmentation half
pixi run earthpv calibrate-candidates --aoi pakistan
pixi run earthpv density --aoi pakistan --districts
pixi run earthpv check-density --aoi pakistan   # gate: exits non-zero on an implausible region

# < 400 m2 roofclf half -- needs mapped calibration quadrats first, see
# calibration-mapping-protocol.md. roofclf-score-national is the long pole (hours at
# country scale) and is resumable per cell like density.
pixi run earthpv roof-classifier --aoi pakistan
pixi run earthpv roofclf-score-national --aoi pakistan
pixi run earthpv sub400-capacity --aoi pakistan \
    --osm-solar data/labels/pakistan_overpass_solar.parquet

# Evidence atlas (Verified / Best estimate), combining both halves.
# (--sub400-high-cells is no longer accepted here -- the Ceiling tier was removed
# 2026-08-06; it still exists for the older bracket atlas, see build_sub400_bracket_atlas.)
pixi run earthpv atlas --aoi pakistan \
    --osm-solar data/labels/pakistan_overpass_solar.parquet \
    --sub400-low-cells     data/roofclf_national_with_sppi/pakistan/density/sub400_low_incremental_buildings.parquet \
    --sub400-central-cells data/roofclf_national_with_sppi/pakistan/density/sub400_central_incremental_buildings.parquet
```

Neither `density` nor `roofclf-score-national` needs a GPU or retraining; both run on
rasters already on disk, each taking roughly two hours single-process for all of
Pakistan, and both are resumable per cell. See [Setup New
Country](../reproduce.md#the-full-pipeline) for the stages that produce those rasters in
the first place, and [Capacity density](../methods/density.md) for how `roofclf`/SPPI
and the OSM pull that feed the evidence atlas are themselves built.
