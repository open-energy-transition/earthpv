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

![Six capacity estimates for Pakistan from the same model, ranging from 2.7 GWp for calibrated rooftop capacity to 6.1 GWp for recall-corrected capacity across all PV including ground-mount farms, with 90 percent credible intervals on the corrected estimates.](../assets/figures/capacity_estimators.svg#only-light)
![Six capacity estimates for Pakistan from the same model, ranging from 2.7 GWp for calibrated rooftop capacity to 6.1 GWp for recall-corrected capacity across all PV including ground-mount farms, with 90 percent credible intervals on the corrected estimates.](../assets/figures/capacity_estimators.dark.svg#only-dark)

| Estimator | Pakistan | What it means |
| --- | ---: | --- |
| Detected, rooftop | 4.9 GWp | Thresholded candidate polygons on building footprints, at face value. Includes false positives, misses everything below threshold. A raw floor, not an estimate. |
| **Calibrated, rooftop** | **2.7 GWp** | Every candidate weighted by its measured probability of being real PV. The conservative headline for rooftop capacity. |
| Expected, rooftop | 5.4 GWp | Probability-weighted area with no threshold at all. Leans high because false-positive probability mass is summed too, and it is blind below the detection floor for the reason given in [Capacity density](../methods/density.md): the segmentation model is trained with sub-400 m<sup>2</sup> arrays burned as ignore. |
| Recall-corrected, rooftop | 4.7 GWp <span style="white-space:nowrap">[3.9 to 6.1]</span> | Calibrated rooftop-placed candidate area divided by the model's measured recall per size bin. An estimate of the whole rooftop population at or above the floor, missed installations included. |
| Calibrated, all PV | 6.0 GWp <span style="white-space:nowrap">[5.0 to 8.1]</span> | The same precision weighting over every candidate, ground-mount farms included, each converted at the constant matching how it is mounted. |
| **Recall-corrected, all PV** | **6.1 GWp** <span style="white-space:nowrap">[5.0 to 8.2]</span> | The fullest defensible estimate **for installations at or above 400 m<sup>2</sup>**. |

Every row covers installations at or above the **400 m<sup>2</sup> detection floor** only.
Germany's legally complete MaStR register puts 72.6 percent of rooftop capacity in systems
of 100 kWp or less, about 555 m<sup>2</sup> of module, so the majority of real rooftop
capacity is very likely below this floor and absent from the table. Do not read these as
national totals for all solar.

Brackets are 90 percent credible intervals propagated from the calibration's measured
binomial counts and from the two area-to-capacity constants, not from model confidence.
Where an instrument barely discriminates, the interval stays honestly wide rather than the
point estimate pretending to precision.

Capacity uses **two** constants, because detected area means two different things. A
rooftop detection outlines the panels, so it converts at 0.18 kWp per square metre, about
5.5 m<sup>2</sup> of crystalline silicon per kWp. A ground-mount detection outlines the
*site* -- the model learns ground PV from OpenStreetMap `power=plant` perimeters, which
enclose access roads and inter-row spacing -- so only its ground-cover ratio is module, and
it converts at 0.07 kWp per square metre of site. Candidates larger than
100,000 m<sup>2</sup> are excluded here entirely; at that size a polygon is a merged
false-positive sheet or a whole plant site, not one installation. See
[Capacity density](../methods/density.md) for both derivations.

!!! warning "This is a screening layer, not a register"
    No human has validated these detections at scale. Compare the number you quote
    against its interval, and state which estimator you used. The corresponding
    human-validated product is the [mapping leads](leads.md), which is a much smaller and
    much cleaner set.

!!! info "Superseded numbers"
    Until 2026-07-26 this page reported 18.3 GWp all-PV and 6.1 GWp rooftop. A method
    review found that ground-mount site area was being converted at the rooftop constant,
    and that nothing bounded polygon size, so 167 merged blobs carrying 47 percent of all
    candidate area were each counted as one installation's panels. Both errors pushed the
    same way and inflated the all-PV total roughly threefold, almost entirely in its
    non-rooftop component. The rooftop-scoped estimates, which the review found sound, moved
    less: 6.1 to 4.7 GWp recall-corrected, after a rebuild that also cleared blob area off
    the footprint-intersected columns. `earthpv check-density` is the gate that now runs
    before these numbers are published, and it fails on the pre-fix output.

    A second bug found in the same review: this page's headline interval was being built by
    summing per-cell credible bounds, which is the error warned against two sections down.
    It read [4,854 to 8,465] against the correct [5,034 to 8,239] from the summed draws.

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
pixi run earthpv check-density --aoi pakistan   # gate: exits non-zero on an implausible region
pixi run earthpv atlas --aoi pakistan
```

The density stage needs no GPU and no retraining; it runs on rasters already on disk in
roughly two hours single-process for all of Pakistan, and is resumable per cell. See
[Setup New Country](../reproduce.md) for the stages that produce those rasters in the first place.
