# Pakistan capacity map

One recall-first model read a year of Sentinel-2 imagery over every building-populated
cell of Pakistan. How much photovoltaic capacity it saw depends on how honestly you count,
and the same probability rasters support six defensible answers. The atlas below lets you
put any of them on the map.

<div class="embed" markdown>
<iframe src="../../assets/interactive/pakistan_capacity_atlas.html" title="Pakistan PV capacity atlas: six estimates, one map" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Switch estimator with the bar chart, hover a cell for its value.
<a href="../../assets/interactive/pakistan_capacity_atlas.html" target="_blank">Open full screen</a>.
</p>

## The six estimates

![Six capacity estimates for Pakistan from the same model, ranging from 3.3 GWp for calibrated rooftop capacity to 18.3 GWp for recall-corrected capacity across all PV including ground-mount farms, with 90 percent credible intervals on the corrected estimates.](../assets/figures/capacity_estimators.svg#only-light)
![Six capacity estimates for Pakistan from the same model, ranging from 3.3 GWp for calibrated rooftop capacity to 18.3 GWp for recall-corrected capacity across all PV including ground-mount farms, with 90 percent credible intervals on the corrected estimates.](../assets/figures/capacity_estimators.dark.svg#only-dark)

| Estimator | Pakistan | What it means |
| --- | ---: | --- |
| Detected, rooftop | 6.1 GWp | Thresholded candidate polygons on building footprints, at face value. Includes false positives, misses everything below threshold. A raw floor, not an estimate. |
| **Calibrated, rooftop** | **3.3 GWp** | Every candidate weighted by its measured probability of being real PV. The conservative headline for rooftop capacity. |
| Expected, rooftop | 5.4 GWp | Probability-weighted area with no threshold at all. Integrates sub-threshold and sub-400 m<sup>2</sup> signal, and leans high because false-positive probability mass is summed too. |
| Recall-corrected, rooftop | 6.1 GWp <span style="white-space:nowrap">[5.6 to 7.3]</span> | Calibrated rooftop area divided by the model's measured recall per size bin. An estimate of the whole detectable rooftop population, missed installations included. |
| Calibrated, all PV | 16.9 GWp <span style="white-space:nowrap">[16.8 to 21.1]</span> | The same precision weighting over every candidate, ground-mount farms included. The scope change, not the correction, is what multiplies the number. |
| **Recall-corrected, all PV** | **18.3 GWp** <span style="white-space:nowrap">[16.9 to 21.5]</span> | The fullest defensible estimate. |

Brackets are 90 percent credible intervals propagated from the calibration's measured
binomial counts, not from model confidence. Where the calibration instrument barely
discriminates, the interval stays honestly wide rather than the point estimate pretending
to precision. Capacity uses 0.18 kWp per square metre of panel area, roughly 5.5 m<sup>2</sup>
of crystalline silicon module per kWp.

!!! warning "This is a screening layer, not a register"
    No human has validated these detections at scale. Compare the number you quote
    against its interval, and state which estimator you used. The corresponding
    human-validated product is the [mapping leads](leads.md), which is a much smaller and
    much cleaner set.

## Where the capacity is

Punjab dominates, which is what the electricity data would predict: the corridor from
Lahore through Faisalabad to Multan carries most of the country's commercial rooftop
stock, with a second concentration along Karachi's industrial belt and a third around
Islamabad and Rawalpindi.

<div class="embed short" markdown>
<iframe src="../../assets/interactive/pakistan_density_map.html" title="Pakistan rooftop PV density per 0.1 degree grid cell" loading="lazy"></iframe>
</div>
<p class="embed-note">
Capacity per 0.1 degree grid cell, the pipeline's native resolution and the shape energy
models consume.
<a href="../../assets/interactive/pakistan_density_map.html" target="_blank">Open full screen</a>.
</p>

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
pixi run earthpv atlas --aoi pakistan
```

The density stage needs no GPU and no retraining; it runs on rasters already on disk in
roughly two hours single-process for all of Pakistan, and is resumable per cell. See
[Reproduce](../reproduce.md) for the stages that produce those rasters in the first place.
