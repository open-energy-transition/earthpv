# Pakistan capacity map

How much rooftop solar does Pakistan actually have? The honest answer depends on how much
proof you require, so this atlas gives three, not one: what a person has actually drawn in
OpenStreetMap, this project's own best defensible estimate, and an explicit, uncalibrated
ceiling. All three read the same underlying detections -- a segmentation model for
individual arrays 400 m<sup>2</sup> and larger, plus two independent per-building
instruments (**roofclf**, **SPPI**) for everything smaller that the segmentation model is
trained blind to.

<div class="embed" markdown>
<iframe src="../../assets/interactive/pakistan_evidence_atlas.html" title="Pakistan PV evidence atlas: Verified, Best estimate and Ceiling" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Switch tier with the tabs, hover a cell for its value.
<a href="../../assets/interactive/pakistan_evidence_atlas.html" target="_blank">Open full screen</a>.
</p>

## Three tiers, one country

| Tier | Pakistan | What it admits as evidence |
| --- | ---: | --- |
| Verified | 7,685 MWp | Every installation a person has drawn in OpenStreetMap (16,085 of them), plus sub-400 m<sup>2</sup> buildings where **roofclf and SPPI both agree** -- two independent detectors, not one model trusted alone. |
| **Best estimate** | **15,004 MWp** | Verified, plus the segmentation model's own recall-corrected detections **&ge;400 m<sup>2</sup>** (5,078 MWp, precision- and recall-corrected), plus the roofclf per-building density estimate inside the cells checked against ground-truth quadrats -- the project's own pick. |
| Ceiling | 42,251 MWp | Swaps the small-PV side for roofclf at a flat, un-tuned national precision (no density restriction), plus the same &ge;400 m<sup>2</sup> total on top. An outer bound on plausibility, not a measurement. |

Every tier folds in the same &ge;400 m<sup>2</sup> segmentation total; what changes between
them is how much of the sub-400 m<sup>2</sup> population each is willing to trust, and at
what precision. None of them double-count: OpenStreetMap-mapped installations are matched
by location and removed from the model-detected side before summing.

!!! warning "This is a research methodology under active validation, not a finished census"
    Only 4 of the 13 ground-truth calibration quadrats are **Rule-1 complete** (every
    visible panel independently verified), and the density-matched calibration only
    covers 245 of Pakistan's 4,463 grid cells. roofclf's own measured skill varies
    sharply by quadrat (AUC 0.50 to 0.96) and its predicted rate does not reliably
    separate well-calibrated cells from over-predicting ones -- see
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

## Using it in an energy model

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

```bash
pixi run earthpv calibrate-candidates --aoi pakistan
pixi run earthpv density --aoi pakistan --districts
pixi run earthpv check-density --aoi pakistan   # gate: exits non-zero on an implausible region

# Evidence atlas (Verified / Best estimate / Ceiling): needs the OSM solar pull and the
# roofclf/SPPI sub-400 m2 building parquets alongside the density run above.
pixi run earthpv atlas --aoi pakistan \
    --osm-solar data/labels/pakistan_overpass_solar.parquet \
    --sub400-low-cells     data/roofclf_national_with_sppi/pakistan/density/sub400_low_incremental_buildings.parquet \
    --sub400-central-cells data/roofclf_national_with_sppi/pakistan/density/sub400_central_incremental_buildings.parquet \
    --sub400-high-cells    data/roofclf_national_with_sppi/pakistan/density/sub400_high_incremental_buildings.parquet
```

The density stage needs no GPU and no retraining; it runs on rasters already on disk in
roughly two hours single-process for all of Pakistan, and is resumable per cell. See
[Setup New Country](../reproduce.md) for the stages that produce those rasters in the
first place, and [Capacity density](../methods/density.md) for how `roofclf`/SPPI and the
OSM pull that feed the evidence atlas are themselves built.
