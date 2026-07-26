# Capacity density

The density stage answers a different question from the detector. Instead of "where is
each array", it asks "how much photovoltaic capacity is on this building, in this grid
cell, in this district". That is the quantity an energy-system model consumes, and it is
the only defensible way to account for installations below the per-object detection floor.

It reuses artifacts already on disk (probability rasters, `candidates.parquet`, VIDA
footprints). No GPU, no retraining, roughly two hours single-process for all of Pakistan,
resumable per cell.

## Why there are four metrics

The detector is deliberately recall-first, so no single number is unconditionally honest.
Each metric states its own bias.

**Detected** (`*_det`) is the area of thresholded, merged candidate polygons lying on the
footprint, taken at face value. It has raw-candidate floor semantics: it includes false
positives and is blind to everything below threshold, which in practice means blind to
most residential PV.

**Calibrated** (`*_cal`) is the same area with each candidate weighted by a measured
`P(real | size, glint)`. This is the **headline** capacity number. It equals `*_det` when
no calibration table exists, and it remains dependent on the 0.3 polygonization threshold.

**Recall-corrected** (`*_rc`, cell and region level only) divides the calibrated candidate
area by the model's measured recall in that size bin, floored at 0.05. That is a
Horvitz-Thompson estimate of the whole population at or above the detection floor, missed
installations included, with 90 percent credible bands propagated from the calibration
posteriors.

**Expected** (`*_exp`) is probability-weighted area: the sum over the footprint of
per-pixel probability times 100 m<sup>2</sup>, above a small noise floor. It integrates
sub-threshold signal and is an upper-leaning ceiling, because false-positive probability
mass gets summed too.

!!! note "Reading the recall correction correctly"
    `*_rc` lives on the candidate population, so it is comparable to the `*_total`
    columns, not to the footprint-intersected `*_roof` ones. There is no per-building
    version, because the missed installations sit on other, unknown buildings. Two
    honesty caveats: the recall reference skews toward visible, mappable installations,
    which makes recall optimistic and the correction conservative; and a mapped
    installation counts as detected if any candidate lies within 100 m, which is generous
    in dense clusters. The two biases partially offset.

## The recall curve

![Measured model recall by installation size against a pre-pipeline OpenStreetMap reference, rising from about 3 percent below 100 square metres to 100 percent above 50,000, with credible intervals.](../assets/figures/model_recall_bins.svg#only-light)
![Measured model recall by installation size against a pre-pipeline OpenStreetMap reference, rising from about 3 percent below 100 square metres to 100 percent above 50,000, with credible intervals.](../assets/figures/model_recall_bins.dark.svg#only-dark)

Recall is measured, not assumed: it is the fraction of installations in a
**pipeline-independent** mapped reference that any candidate matched within 100 m. The
reference is deliberately a pre-pipeline OpenStreetMap snapshot rather than a fresh
Overpass pull, because a fresh pull would contain this pipeline's own validated leads and
would confirm its recall upward.

The area-dominant bins above 5,000 m<sup>2</sup> are already nearly fully recalled, which
is why the national recall correction adds a modest amount over the calibrated total
rather than transforming it.

## Outputs

Three layers plus an atlas land in `data/predictions/<aoi>/density/`:

| File | Grain | Contents |
| --- | --- | --- |
| `buildings.geoparquet` | building | `roof_area_m2`, `pv_area_{det,cal,exp}_m2`, `pv_ratio_{det,exp}`, `est_kwp_{det,cal,exp}`, `pv_placement`, region and district |
| `grid.geoparquet`, `grid.csv` | 0.1 degree cell | roof and PV area, densities in m<sup>2</sup> per km<sup>2</sup>, `est_mwp_{det,cal,exp}`, `est_mwp_rc` with `_lo` and `_hi` |
| `regions.geoparquet`, `.csv`, `.geojson` | province, or ADM2 | additive totals, ratios recomputed from sums, bands re-derived from summed draws |
| `<aoi>_pv_atlas.html` | country | the self-contained interactive [capacity atlas](../results/capacity.md) |

Capacity is `est_kwp = pv_area x --kwp-per-m2`, default **0.18 kWp per m<sup>2</sup>**.

Double counting is prevented at the source. Adjacent rasters overlap by a few pixels, so
each building is assigned to exactly one cell by its representative point, and each cell's
raster sum is cropped to the canonical 0.1 degree box.

Province polygons come from **geoBoundaries** (open, CC-BY), because Overture's divisions
endpoint times out from the development machine. Override with `--regions-file`.

## Running it

```bash
# once, and again whenever new validation evidence lands
pixi run earthpv calibrate-candidates --aoi pakistan

pixi run earthpv density --aoi pakistan --districts
pixi run earthpv atlas --aoi pakistan          # standalone atlas regeneration
```

## How the estimate got here

Each step exists because the previous one had a measurable gap.

1. **Detected-area floor.** Precision-honest, blind below threshold.
2. **Probability-weighted expectation.** Integrates sub-threshold signal. Together the two
   bracket the truth.
3. **Fraction-regression head.** A second head predicting per-pixel PV *coverage fraction*,
   trained on OpenStreetMap polygons burned at 10x supersampling and block-averaged to
   10 m. Individually noisy, with only about 4.5 percent per-installation recall in the
   0 to 250 m<sup>2</sup> range, but unbiased in aggregate: chip-sum R<sup>2</sup> of 0.60 on
   held-out Germany, and a municipal Spearman correlation against the legally complete
   MaStR register of **0.740** across all German Gemeinden, versus 0.499 for the
   segmentation baseline. Aggregate density is exactly what energy models need, and this
   is the purpose-built estimator for it.
4. **Calibration anchors.** Germany's MaStR register established a stable 2.4 to 2.5 times
   aggregate over-prediction, consistent from chip level to municipality level and
   therefore correctable. Pakistan was cross-checked against TransitionZero's 27.5 GW
   distributed-solar study with a coverage-share-disentangled calibration, separating
   scale error inside imaged cells from cells never imaged at all.
5. **Coverage expansion.** That comparison showed the missing-coverage term dominated.
   Cell selection had used the Overture set of buildings above 500 m<sup>2</sup>, which
   undercounts small and informal structures by two to three orders of magnitude in rural
   Pakistan. Switching to VIDA's 76.5 million footprints grew the compose target from 122
   to about 4,460 cells.
6. **Precision calibration.** `P(real | size, glint)` per size bin, from OpenStreetMap
   mapped fractions, glint inversion and manual high-resolution review. See
   [Calibration](calibration.md).
7. **Recall correction and credible intervals**, deployed 2026-07-23. Everything before
   this was precision-only: `est_mwp_cal` down-weighted false positives, but nothing
   credited installations the model missed, so even the headline was structurally a floor.

Open next steps are the OpenStreetMap flywheel producing enough in-domain positives for a
retrain, NEPRA net-metering totals as a Pakistani MaStR analogue, and per-epoch density
estimates turning `est_mwp` into a time series so the 2022 to 2026 boom becomes measurable
per district.
