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

The chain from detected to recall-corrected, worked on one real candidate with its own
bin's measured corrections:

![Waterfall of three bars for one real 3,400 square metre rooftop candidate. Detected, 612 kilowatts peak, the polygon at face value including false positives. An arrow labelled times P real equals 0.60, measured for rooftop candidates of 1,000 to 5,000 square metres, leads down to calibrated at 366 kilowatts peak, the headline accounting. A second arrow labelled divided by recall equals 0.46, measured against pre-pipeline OpenStreetMap, leads up to recall-corrected at 795 kilowatts peak, the population estimate with misses included.](../assets/figures/capacity_metrics.svg#only-light)
![Waterfall of three bars for one real 3,400 square metre rooftop candidate. Detected, 612 kilowatts peak, the polygon at face value including false positives. An arrow labelled times P real equals 0.60, measured for rooftop candidates of 1,000 to 5,000 square metres, leads down to calibrated at 366 kilowatts peak, the headline accounting. A second arrow labelled divided by recall equals 0.46, measured against pre-pipeline OpenStreetMap, leads up to recall-corrected at 795 kilowatts peak, the population estimate with misses included.](../assets/figures/capacity_metrics.dark.svg#only-dark)

Both corrections come from the same tracked
[calibration table](calibration.md), and neither is a fudge factor: the first divides the
candidate population into what is probably real, the second scales the survivors up to
stand for the installations the model verifiably misses at that size. The two run in
opposite directions on purpose -- a pipeline whose corrections only ever raised the number
would deserve suspicion.

!!! note "Reading the recall correction correctly"
    `*_rc` lives on the candidate population, so it is comparable to the `*_total`
    columns, not to the footprint-intersected `*_roof` ones. There is no per-building
    version, because the missed installations sit on other, unknown buildings. Two
    honesty caveats: the recall reference skews toward visible, mappable installations,
    which makes recall optimistic and the correction conservative; and a mapped
    installation counts as detected if any candidate lies within 100 m, which is generous
    in dense clusters. The two biases partially offset.

## Area is not capacity until you know how it was mounted

Detected area means two different things depending on where the array sits, so the stage
carries two conversion constants rather than one.

A **rooftop** detection outlines the panel field on a roof, which is close to module area:
about 5.5 m<sup>2</sup> of crystalline silicon per kWp, so **0.18 kWp per m<sup>2</sup>**.
`earthpv pv-yield` grounds that figure against pvlib's CEC datasheet database.

A **ground-mount** detection outlines the *site*, not the modules. The ground-PV training
labels are OpenStreetMap `power=plant` perimeters, which enclose access roads, inter-row
spacing and substations, so the model is taught to fill the fence line. Only the
ground-cover ratio of that polygon is module -- **0.05 kWp per m<sup>2</sup> of site**,
calibrated against two named-plant ground-mount boxes
(`docs/issues/pakistan-calibration-boxes.md`) rather than reasoned from a GCR assumption
alone: Quaid-e-Azam Solar Park (400 MW / 8,904,839 m<sup>2</sup> dissolved OSM footprint)
implies 0.0449 kWp/m<sup>2</sup>, the Sukkur solar farm (150 MW combined, three phases /
2,606,013 m<sup>2</sup>) implies 0.0576 -- geometric mean 0.0509, rounded to 0.05.
Converting site area at the rooftop constant would overstate ground-mount capacity by
roughly 3.5 to 4 times.

Every all-PV estimator is therefore split by placement before conversion, and both
constants carry lognormal priors (90 percent ranges of 0.15 to 0.21 for the module
constant and 0.035 to 0.075 for the land constant, kept wide since n=2 real plants does
not support a tight posterior and other sites plausibly use tracking or different row
spacing) so the conversion propagates into the credible intervals instead of being
treated as exact.

## Blobs are excluded, not converted

The polygonizer merges every touching thresholded pixel with no upper bound, so a connected
sheet of false positives -- a dry riverbed, salt flat, bare rock, snow -- becomes a single
multi-square-kilometre "installation" whose confidence is the maximum over millions of
pixels, which is to say 1.0. On the Pakistan country run 167 candidates exceeded
100,000 m<sup>2</sup> and carried **47 percent of all candidate area**; the ten largest
carried 27 percent, so the national total was effectively a handful of objects.

Candidates above that size are excluded from capacity. They are only *flagged* in
`candidates.parquet`, so they survive in the [mapping leads](../results/leads.md), where a
human validates every candidate and a coarse polygon is still a usable lead. The density
stage is what drops them, because it has no human in the loop. Set
`--max-candidate-m2 0` to disable the filter, and note that the per-building layer only
reflects it after a `--force` rebuild; `meta.json` records
`oversize_stale_partials` when it does not.

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
| `grid.geoparquet`, `grid.csv` | 0.1 degree cell | roof and PV area, densities in m<sup>2</sup> per km<sup>2</sup>, `est_mwp_{det,cal,exp}`, `est_mwp_rc` with `_lo`, `_hi` and its `_roof` / `_ground` split |
| `regions.geoparquet`, `.csv`, `.geojson` | province, or ADM2 | additive totals, ratios recomputed from sums, bands re-derived from summed draws |
| `plausibility.csv` | province | the gate's per-region verdict, see below |
| `<aoi>_pv_atlas.html` | country | the self-contained interactive [capacity atlas](../results/capacity.md) |

Rooftop capacity is `est_kwp = pv_area x --kwp-per-m2-module` (default 0.18); the
ground-mount part of every all-PV column uses `--kwp-per-m2-land` (default 0.05). The
`*_roof` and `*_ground` columns are exported separately so the split is auditable rather
than buried in a total.

Double counting is prevented at the source. Adjacent rasters overlap by a few pixels, so
each building is assigned to exactly one cell by its representative point, and each cell's
raster sum is cropped to the canonical 0.1 degree box.

### `buildings.geoparquet`'s rooftop sum is not the region total's rooftop component

**These are two different accounting methods over the same candidates, and they are not
expected to agree.** The region/national rooftop total (`est_mwp_rc_roof`,
`pv_area_det_roofcand_m2` in `grid.geoparquet`/`meta.json`) sums each rooftop-placed
candidate's **full polygon area**, exactly once. `buildings.geoparquet`'s per-building
`pv_area_det_m2` instead sums, for each building, only the **geometric intersection**
between it and every candidate that touches it (`density.per_building_detected`), capped
at that building's own roof area. Whatever part of a rooftop-classified candidate's own
polygon does *not* sit on any building -- gaps between the buildings it spans, general
polygonize-and-merge over-draw beyond a roof's edge -- is counted in the first total and
silently absent from the second.

![Schematic of one rooftop-classified candidate polygon spanning two building footprints. The two intersection areas are marked as credited to building A's row, capped at A's roof area, and to building B's row. The larger remaining polygon area between and beyond the roofs is marked as off any roof: in the region total, in nobody's per-building row.](../assets/figures/attribution_gap.svg#only-light)
![Schematic of one rooftop-classified candidate polygon spanning two building footprints. The two intersection areas are marked as credited to building A's row, capped at A's roof area, and to building B's row. The larger remaining polygon area between and beyond the roofs is marked as off any roof: in the region total, in nobody's per-building row.](../assets/figures/attribution_gap.dark.svg#only-dark)

This is not a rounding difference: of 21,506,014 m<sup>2</sup> of rooftop-placed
candidate area nationally, only 11,527,028 m<sup>2</sup> (53.6%) is attributed to any
building in `buildings.geoparquet` -- a **46.4% gap (9,978,986 m<sup>2</sup>)**. The
mechanism is exactly what it looks like: `postprocess._join_buildings_metric` only
requires >= 30% of a candidate's own area to sit on *some* building before calling it
`rooftop` (`NEAR_BUILDING_M`'s sibling threshold), and the mean `building_overlap_frac`
across rooftop-classified candidates is only **58.8%** -- multiplying that shortfall
through (`sum(area * (1 - overlap_frac))`) predicts a 9,781,295 m<sup>2</sup> gap,
matching the measured figure to within 2%. Ground-mount is not involved: both sides of
this comparison are already restricted to `placement == "rooftop"` candidates before
summing.

Practical consequence: **`buildings.geoparquet`'s summed rooftop capacity understates the
region/national rooftop total by roughly half**, structurally, not as a bug to patch --
the per-building table is answering "how much PV sits on this specific building," which is
a stricter and smaller question than "how much rooftop-placed candidate area exists in
this region." Any PyPSA-style per-building disaggregation built from `buildings.geoparquet`
should be read as a conservative, roof-anchored floor, not as a decomposition that sums
back to `grid.geoparquet`'s own `est_mwp_rc_roof`. A `building_overlap_frac` above 1.0 was
also observed on a handful of candidates (VIDA building footprints occasionally overlap
each other, double-counting a candidate's own intersection area across two overlapping
buildings) -- a minor, secondary data-quality note, not the driver of the gap above.

Province polygons come from **geoBoundaries** (open, CC-BY), because Overture's divisions
endpoint times out from the development machine. Override with `--regions-file`.

### Completeness confidence (segmentation runs only)

Every estimator on this page (`det`/`cal`/`exp`/`rc`) is floored at >= 400 m<sup>2</sup> and
its recall correction was measured on hand-mapped calibration quadrats currently spanning
553-5,258 buildings/km<sup>2</sup>. Outside that settlement-density range there is no
calibration evidence either way -- not "the estimate is worse there", just "untested". A
segmentation `density` run therefore carries a `density_confidence` column on
`grid.csv`/`regions.csv` (values `below_calibrated_range` / `in_calibrated_range` /
`above_calibrated_range`, alongside the raw `bldg_density_km2`), plus
`n_cells_{below,in,above}_calibrated_density` in `meta.json`. It is a **flag, not a
correction** -- it changes no number, it only tells a reader which totals rest on measured
ground and which do not (most of rural Pakistan is below the range, since every calibration
quadrat is an urban or peri-urban box).

This column is deliberately computed **only when `exp_source == "segmentation"`** -- a
fraction-head run is a different instrument with its own (separately tracked) calibration
gaps, and sharing one flag across both would imply a validation that was never done for the
one that didn't get it.

## Below the detection floor: the sub-400 m² instruments

The recall correction above has a hard limit that no amount of better calibration
reaches: it scales up what was detected, so `1/recall x ~0` is still ~0. Measured on the
Pakistan run, the entire sub-500 m<sup>2</sup> class contributes **8.2 MWp** to this
stage's national estimate, about 0.2 percent of the rooftop total, while a single
exhaustively mapped square kilometre of residential Lahore holds **3.3 times more
sub-100 m<sup>2</sup> PV area than this instrument finds in all of Pakistan**. A size
class the segmentation detector never sees cannot be recovered by reweighting the classes
it does see -- it needs a different estimator entirely.

That estimator is `roofclf`, a per-building classifier, cross-checked against the
zero-training SPPI spectral index: see [The rooftop classifier](roofclf.md) for how it is
built, calibrated and converted to capacity, and [the capacity map](../results/capacity.md)
for the current national figures it produces. The rest of this section keeps three
findings from the road to that instrument that are still useful diagnostics today.

**Packing distance is a cheap, measured proxy for stratum.** `roofclf.packing_density` is
the median distance from each sub-400 m<sup>2</sup> installation to its nearest neighbour
of any size. It correlates with how a quadrat's calibration numbers behave (r=0.70-0.82
with various instrument scale/skill measures) mostly because it is a continuous stand-in
for **installation size regime**, not density as such: controlling for median
installation size, packing distance's relationship with segmentation skill collapses from
0.82 to -0.16, while its relationship with the *fraction head's* per-building AUC survives
the same control (0.93 unconditional, 0.81 partial), because that is the one place a
sub-pixel spacing effect should appear independent of array size. It is a standing column
in every fold report (`nn_median_m`), useful for sizing a new calibration quadrat, but is
not (yet) a per-building model feature.

**Discrimination tracks installation size, not density.** Every density measure
correlates strongly with segmentation skill across quadrats, and every one of those
correlations disappears once installation size is held constant. Median installation size
alone predicts whether the segmentation raster works at all (Pearson r=0.99): a quadrat
whose installations are mostly small scores near chance because `chips.MIN_PV_AREA` burns
everything below 400 m<sup>2</sup> as `ignore`{.python} during training, not because
density itself hurts detection. `frac_sub400` (the share of a quadrat's PV below the
detection floor) is the one bias relationship that is not mechanical: it predicts how much
area the fraction-head instrument misses, which is the sub-400 m<sup>2</sup> blindness
measured directly.

**A pooled classifier without a per-stratum intercept produces a `rate_ratio` that is
mechanically `constant / base_rate`.** An early national scoring pass found the deployment
threshold badly distorted by pooling every quadrat's precision target together: the
lowest-base-rate quadrat in the set was forcing the cut far higher than the rest of the
population needed. Re-fitting without that one outlier stratum recovered a large,
measured recall gain at the same precision target -- the clearest illustration that a
single pooled operating point is fragile to whichever stratum happens to be most extreme,
which is why `roofclf`'s domain restriction (below) rather than a single national rate is
the shipped design. Full diagnosis:
[roofclf national deployment](../issues/roofclf-national-deployment-and-temporal-features.md).

## Total capacity as a pipeline input

Every number above is this project's own estimate of the total. `earthpv
redistribute-capacity` (`capacity_redistribution.py`) answers a different question:
given a total from an independent, possibly more-trusted source (for example Pakistan's
NEPRA net-metering register), how should that total be spread across cells, regions or
buildings, using this project's own measured *relative* shape rather than its absolute
number: `share = row's est_mwp_* value / (national or per-region) sum`,
`distributed = share x external_total`. It reads `density/`'s finished outputs and writes
its own sibling file, never touching `grid.geoparquet`/`regions.geoparquet` in place.

Two caveats worth stating plainly: an external total necessarily includes small
(< 400 m²) PV, so distributing it by the &ge; 400 m² shape this project can actually
validate assumes small-PV's spatial distribution tracks large-PV's, which is not
established; and the transform is point-estimate only, since `est_mwp_rc`'s posterior
credible interval is not currently propagated through it.

```bash
earthpv redistribute-capacity --aoi pakistan --total-capacity 5800 --scope national
```

`--scope region` (one total per region, each spread by that region's own local shape) is
built and wired the same way, but has no real companion data yet -- no provincial NEPRA
breakdown exists in this project's sources today, only the national scalar above.

## Rooftop potential and saturation

Everything above answers "how much PV is already there." `earthpv atlas
--potential-buildings <path>` (`atlas.py::build_potential_atlas`,
`potential.py::large_roof_buildings`) answers a different, forward-looking question:
where are large, currently-uncovered roofs that would make good candidates for *future*
rooftop solar, and where is existing adoption already dense vs. sparse. It is a two-tab
atlas, not a new capacity estimator, kept deliberately separate from every number above.

**Potential.** Every VIDA building nationally with `roof_area_m2 >= 200` is pulled from
`roofclf.score_buildings_national`'s existing per-cell output, reusing only that table's
building-footprint geometry, never its PV-presence scores -- this instrument only measures
building footprint size, so none of `roofclf`'s calibration/precision caveats apply here.
From each cell's total large-roof area, the segmentation model's own probability-weighted
expected PV area is subtracted to get an **uncovered** large-roof area, which converts to
peak capacity at the usual 0.18 kWp/m<sup>2</sup> module constant and then to annual
energy via a PVGIS-modelled specific yield. 200 m<sup>2</sup>, not the 400 m<sup>2</sup>
detection floor, is the cutoff because it reaches further into the realistic
rooftop-opportunity space (roughly where Germany's MaStR register shows most rooftop
capacity actually sits) rather than merely restating the population already above the
detection floor -- with the caveat that the segmentation model has no discriminating
signal at all in the 200-400 m<sup>2</sup> band, so that band's "potential" reads as
almost entirely uncovered regardless of whether PV is actually there.

**Saturation.** This tab adds no new computation: `pv_ratio_det`/`pv_ratio_exp` (PV area
over roof area) are already computed per cell and region and land unconditionally on
`grid.geoparquet`/`regions.geoparquet`. The tab exists purely to give that existing ratio
its own choropleth view.

**Leads.** `scripts/build_potential_leads.py` (`pixi run potential-leads`) ranks
individual large, uncovered roofs by `roof_area_m2 * kwh_per_kwp_yr` at the building's own
cell, drops anything within 30 m of an existing detected candidate or hand-mapped OSM
solar feature, and caps at 6 per 0.1 deg cell, for a human to spot-check the
highest-opportunity roofs before treating any of this as validated.

## The plausibility gate

The leads product has a human on every candidate. The capacity atlas has nobody, so a
false-positive mode that survives the precision weighting reaches the published number
silently: a province total simply comes out too large, and nothing in the pipeline
objects. `earthpv check-density` is that objection, and it runs between `density` and
publishing. It exits non-zero on a failure and 2 if the stage has not run, so it can gate
a pipeline; the docs CI cannot run it, because the density outputs it reads are gitignored
and live next to the rasters.

Two independent per-region checks, both computed from layers the stage already wrote:

**Ground-mount against rooftop.** Detections off a building are the dominant
false-positive mode, and unlike a rooftop detection nothing constrains them to a plausible
host. A region whose ground-mount estimate dwarfs its rooftop estimate is claiming
utility-scale solar that would be independently documented if it existed. Suspect above
three times, failing above five, with a 50 MWp floor so a tiny region's ratio is not
noise.

**Single-cell concentration.** One 0.1 degree cell holding more than a quarter of a
region's capacity means that region's total is one object, not a population, and no
amount of per-bin calibration turns it into a statistic.

!!! note "Current published state: 3 flagged regions, checked and published anyway"
    The published run fails the single-cell-concentration check for Khyber Pakhtunkhwa,
    Balochistan and Islamabad Capital Territory. All three flagged cells are the
    calibration quadrats' own cities (Peshawar, Quetta, Islamabad), which naturally
    dominate otherwise sparse regions once an earlier ground-mount overstatement (fixed by
    splitting rooftop and ground-mount calibration by placement) stopped masking that
    concentration. Gilgit-Baltistan is separately exempted from the ratio check via
    `RATIO_CHECK_EXEMPT_REGIONS`, because its real rooftop base rate is near zero and the
    ratio is structurally uninformative there. Published anyway, per this project's
    precedent for a checked-genuine plausibility failure. See
    [Open questions](../open-questions.md#known-defects-carried-on-purpose).

## Running it

```bash
# once, and again whenever new validation evidence lands
pixi run earthpv calibrate-candidates --aoi pakistan

pixi run earthpv density --aoi pakistan --districts
pixi run earthpv check-density --aoi pakistan  # gate the numbers before publishing them
pixi run earthpv atlas --aoi pakistan          # standalone atlas regeneration
```

Changing the expected-area instrument or `--exp-scale` only reaches the per-building and
`*_roof` columns on a `--force` re-run, since those live in the cached cell partials. For
the sub-400 m<sup>2</sup> instruments (`roof-classifier`, `roofclf-score-national`,
`sub400-capacity`, `ge400-roof-capacity`), see [The rooftop classifier](roofclf.md) and
[the capacity map's reproduction steps](../results/capacity.md#reproducing-this-map).

This system reached its current shape through several rounds of measurement against
Germany's MaStR register and an independent Pakistani distributed-solar study, most
notably the recall correction, the mounting-split conversion, and the plausibility gate
itself, each added after a method review found the previous step alone was not enough.
The full account of what was tried, what it cost, and what did not work (a fraction-
regression head, a Low/Central/High bracket atlas, two-endmember spectral unmixing among
them) is in [Experiments](../experiments.md); concrete open items are in
[Open questions](../open-questions.md).
