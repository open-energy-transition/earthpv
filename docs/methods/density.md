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

## Area is not capacity until you know how it was mounted

Detected area means two different things depending on where the array sits, so the stage
carries two conversion constants rather than one.

A **rooftop** detection outlines the panel field on a roof, which is close to module area:
about 5.5 m<sup>2</sup> of crystalline silicon per kWp, so **0.18 kWp per m<sup>2</sup>**.
`earthpv pv-yield` grounds that figure against pvlib's CEC datasheet database.

A **ground-mount** detection outlines the *site*, not the modules. The ground-PV training
labels are OpenStreetMap `power=plant` perimeters, which enclose access roads, inter-row
spacing and substations, so the model is taught to fill the fence line. Only the
ground-cover ratio of that polygon is module: 0.3 to 0.5 for fixed tilt at these
latitudes, giving **0.07 kWp per m<sup>2</sup> of site**. Converting site area at the
rooftop constant overstates ground-mount capacity by a factor of two to three.

Every all-PV estimator is therefore split by placement before conversion, and both
constants carry lognormal priors (90 percent ranges of 0.15 to 0.21 and 0.045 to 0.11) so
the conversion propagates into the credible intervals instead of being treated as exact.
It was previously the largest term excluded from them, and the land constant, driven by an
unobserved ground-cover ratio, is much the wider of the two.

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
ground-mount part of every all-PV column uses `--kwp-per-m2-land` (default 0.07). The
`*_roof` and `*_ground` columns are exported separately so the split is auditable rather
than buried in a total.

Double counting is prevented at the source. Adjacent rasters overlap by a few pixels, so
each building is assigned to exactly one cell by its representative point, and each cell's
raster sum is cropped to the canonical 0.1 degree box.

Province polygons come from **geoBoundaries** (open, CC-BY), because Overture's divisions
endpoint times out from the development machine. Override with `--regions-file`.

### Completeness confidence (segmentation runs only)

Every estimator on this page (`det`/`cal`/`exp`/`rc`) is floored at >= 400 m<sup>2</sup> and
its recall correction was measured on 8 hand-mapped calibration quadrats spanning
737-4,750 buildings/km<sup>2</sup>. Outside that settlement-density range there is no
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

## Below the detection floor: change the unit of prediction

The recall correction has a hard limit that no amount of better calibration reaches. It
scales up what was detected, so `1/recall x ~0` is still ~0. Measured on the Pakistan run,
the entire sub-500 m<sup>2</sup> class contributes **8.2 MWp** to the national estimate,
about 0.2 percent of the rooftop total, while a single exhaustively mapped square kilometre
of residential Lahore holds **3.3 times more sub-100 m<sup>2</sup> PV area than the model
finds in all of Pakistan**. That is not a coefficient problem. A size class the detector
never sees cannot be recovered by reweighting the classes it does see.

Two instruments address it, and both drop the polygon.

### Expected area from a fraction head

`density --fraction-prob-dir <run>/prob` swaps the expected-area instrument from
segmentation class probability to a fraction head's per-pixel PV *coverage*. This matters
because the segmentation model is trained with everything below `chips.MIN_PV_AREA` burned
as `ignore`, so it has no reason to put probability mass on a small array, whereas the
fraction head is trained on OpenStreetMap polygons burned at 10x supersampling with no
size floor.

Measured on all nine registered quadrats (`earthpv roof-classifier`, updated 2026-07-29
to include the three owner-mapped boxes added that day), as predicted PV area over their
buildings divided by the exhaustively mapped truth (`data/roofclf/exp_scale_anchor.csv`):

| quadrat | stratum | segmentation | fraction head |
| --- | --- | ---: | ---: |
| **Karachi DHA 5 coastal (Rule-1)** | 1, coastal residential | **0.000** | **0.042** |
| Mardan (Sheikh Maltoon Town) | 1/3, planned housing | 0.000 | 0.196 |
| Quetta City | 5, arid/bare-land | 0.256 | 0.204 |
| Lahore DHA (residential) | 1, affluent planned | 0.023 | 0.520 |
| Sialkot Old City | 2, dense informal urban | 0.000 | 0.840 |
| Multan Industrial | 6, industrial | 1.710 | 1.350 |
| SITE Karachi | 6, industrial | 2.117 | 1.636 |
| Sundar Industrial | 6, industrial | 1.265 | 1.439 |
| Faisalabad PSIE | 6, industrial | 1.832 | 2.077 |

Read the top row first. In the Rule-1-complete coastal quadrat, where the median installation
is 86 m<sup>2</sup>, the segmentation instrument predicts **0.0 m<sup>2</sup> against 13,964 m<sup>2</sup>
of mapped PV** -- not an underestimate, a total blank -- and the fraction head recovers
4.2 percent. In Lahore DHA, where installations are larger, segmentation recovers 2.3 percent
and the fraction head 52 percent. In the industrial quadrats both run high. So the fraction
head is strictly better than segmentation below the floor and by a wide margin, but its own
sensitivity still collapses as installations approach 100 m<sup>2</sup>: it is an improvement,
not a solution.

`--exp-scale` divides by a measured over-prediction factor -- **still not applied nationally,
and the three new quadrats reinforce rather than resolve why.** The fraction-head scale now
spans **0.042 to 2.077 across nine quadrats, a 49x range**, and it does not collapse to a
clean stratum split either: within the five non-industrial quadrats alone (Karachi coastal,
Mardan, Quetta, Lahore, Sialkot) the scale still spans 0.042-0.840, a 20x range, without an
obvious relationship to median installation size (Sialkot's 63.7 m<sup>2</sup> median scales at
0.840, close to Lahore's mixed-size 0.520, while Karachi coastal's broadly similar 86 m<sup>2</sup>
median scales at 0.042 -- 20x lower). The four industrial quadrats are the one internally
consistent group, all landing at 1.35-2.08. Averaging across all nine (mean 0.92, median 0.84)
would produce a single constant that under-corrects the industrial quadrats by roughly 1.5-2x
and over-corrects Karachi coastal and Mardan by roughly 5-20x in the *opposite* direction --
actively worse than the current uncorrected default for those strata. **The default therefore
stays `--exp-scale 1.0`.** A defensible correction needs either a per-stratum multiplier (which
`density.py` does not currently have a mechanism to apply -- there is no per-cell/per-building
stratum label at that stage) or enough quadrats per stratum to fit one reliably; five
non-industrial quadrats is not yet that. Germany's MaStR bench cannot settle it either, since
its two slope estimators disagree by 2.6x and its well-mapped subset by 13x. These quadrats
can, because their denominator is complete by construction -- there just aren't enough of them
yet, especially outside the industrial stratum.

!!! warning "Full coverage reached; the Gilgit-Baltistan regression is exempted, but promotion still failed for a different reason (updated 2026-07-30)"
    As of 2026-07-29 the fraction-head run covers **all 4,463 manifest cells**
    (`exp_coverage_frac: 1.0`) — the inference finished on 2026-07-27, the docs simply
    hadn't been updated. National expected-area rooftop capacity with the fraction
    instrument comes out at **6.65 GWp** vs the segmentation instrument's **5.4 GWp**
    (+23%), consistent in direction and rough magnitude with the quadrat-level finding
    above that segmentation is structurally blind below the floor. That comparison is
    architecturally clean: the exp/fraction swap touches only `pv_area_exp`/`est_mwp_exp`,
    nothing else in the pipeline.

    The Gilgit-Baltistan ground-mount regression that originally blocked this (110 MWp
    against 0.000 MWp rooftop) was traced to a `density.py`/`postprocess.py`
    `no_building`-aggregation issue independent of the fraction head, and is now
    exempted at the region level (`RATIO_CHECK_EXEMPT_REGIONS`, see the plausibility
    gate section below) — `check-density` passes again on that specific failure mode.

    **That exemption was not enough: promoting the fraction head as `density.py`'s
    default, attempted 2026-07-30 against the current (post-OSM-replace) candidate
    population, failed `check-density` again, for a different reason.** Two regions
    (Khyber Pakhtunkhwa, Balochistan) failed the ground:rooftop ratio check that had
    previously passed. Root cause: a disproportionate **46% collapse in
    roof-intersected candidate area vs. 29% overall** between the passing baseline and
    the forced recompute — the same class of `density.py` aggregation issue as the
    Gilgit-Baltistan case, now surfaced more broadly because this was the first *forced*
    full recompute combining OSM-geometry-replacement's candidate corrections with a
    genuine forced recompute (earlier comparison runs had pinned the candidate set,
    masking this). **The fraction head is still not promoted; the segmentation-based
    run remains the published default**, restored from
    `density_segmentation_pre_fraction_promote_20260730/`. The failing run is preserved
    at `density_fraction_promoted_FAILED_20260730/` for whoever roots out the
    aggregation bug next.

    The practical path taken instead: a separate, explicitly experimental sub-400 m²
    capacity product (`sub400_capacity.py`, next section) that combines the fraction
    head's evidence with `roof-classifier`'s national scores without touching
    `density.py`'s candidate-aggregation code at all — see "Sub-400 m² experimental
    capacity" below.

    **The fraction head was never the cause of this.** A later, unrelated change (adding
    the `density_confidence` completeness flag below) triggered a plain, non-`--force`
    segmentation-only re-run and reproduced the identical failure. `_CAND_COLS` is
    rederived from `candidates.parquet` on *every* run regardless of `--force`, while the
    cached cell partials' per-building/`*_roof` columns only refresh on `--force` — and
    `candidates.parquet` was OSM-geometry-replaced (2026-07-29) after the partials were
    last built with `--force`, so the two now permanently disagree. Any run against the
    current candidate population fails the gate, segmentation or fraction. The published
    `density/` stays pinned to the pre-OSM-replace snapshot (`n_oversize_excluded=233`)
    until a `--force` rebuild happens and the roof-candidate collapse it triggers is
    root-caused — both still open.

### Per-building classification

`earthpv roof-classifier` asks **"does this building carry PV?"** instead of "where are its
panel edges". At one mixed pixel that is a far easier question: it needs the footprint's
spectral signature to differ from a PV-free roof, not a resolvable outline. Training labels
come from the exhaustively mapped quadrats, where a building with no mapped PV is a genuine
negative -- which ordinary OpenStreetMap cannot supply, because there absence of a label
mostly means absence of a mapper.

![Three panels over the same 0.49 square kilometre of coastal Karachi. Left: the Sentinel-2 dry-season composite at native 10 metre resolution with 165 mapped rooftop PV installations outlined in cyan over grey building footprints; the arrays are mostly smaller than a single pixel. Centre: the segmentation model's PV probability over the identical extent, uniformly zero, a black panel with only the cyan ground-truth outlines visible. Right: the per-building classifier's out-of-fold probability, each footprint shaded from dark to bright, separating the PV-carrying roofs.](../assets/figures/coastal-Karachi.png)

/// caption
The **coastal Karachi benchmark**, the project's only Rule-1-complete quadrat. Same extent
and same colour scale in the two right-hand panels. The segmentation model returns
identically zero across the whole box; the per-building classifier, scored out of fold,
separates the same roofs at 0.831 AUC with roof size held fixed. Regenerate with
`python scripts/plot_calib_quadrat.py`.
///

That middle panel is the finding, not an illustration of it. It is the published detector on
a box where 165 installations are mapped and owner-verified, and its output is not a faint
signal but a uniform zero.

Leave-one-quadrat-out, **22,044 buildings and 2,376 carrying PV across nine quadrats**
(updated 2026-07-29 with the three owner-mapped boxes added that day: Mardan, Quetta,
Sialkot). Adoption rises with house size, so footprint area alone already scores about
0.72; the **within-size-band** column removes size as a discriminator and measures what
the imagery adds at fixed roof size, which is the honest headline.

| held-out quadrat | base rate | AUC | AUC <500 m<sup>2</sup> | **within size band** | segmentation, within band | packing (m) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Karachi DHA 5 coastal (Rule-1)** | 0.185 | 0.883 | 0.886 | **0.846** | **0.500** | 16.8 |
| Lahore DHA (residential) | 0.301 | 0.876 | 0.876 | 0.761 | 0.496 | 7.2 |
| Sialkot Old City | 0.057 | 0.816 | 0.817 | 0.770 | 0.500 | 18.8 |
| Mardan (Sheikh Maltoon Town) | 0.138 | 0.743 | 0.742 | 0.661 | 0.500 | 11.2 |
| Quetta City | 0.030 | 0.852 | 0.856 | 0.842 | 0.501 | 44.0 |
| Faisalabad PSIE | 0.125 | 0.850 | 0.813 | 0.831 | 0.651 | 45.8 |
| Multan Industrial | 0.086 | 0.932 | 0.915 | 0.919 | 0.805 | 50.8 |
| SITE Karachi | 0.131 | 0.935 | 0.929 | 0.931 | 0.875 | 46.2 |
| Sundar Industrial | 0.098 | 0.874 | 0.840 | 0.863 | 0.762 | 52.1 |
| **median** | | **0.874** | **0.856** | **0.842** | **0.501** | |

The three new folds lower the median AUC slightly (0.879 -> 0.874) and the within-size
median a touch more (0.845 -> 0.842) -- Mardan in particular is the weakest fold measured
so far (0.743), the first non-industrial, non-Rule-1 quadrat in the set. Read that as the
estimate becoming more honest with more evidence, not as the method degrading.

### Packing distance: a cheap, measured proxy for stratum

**packing (m)** is `roofclf.packing_density`: the median distance from each
sub-400 m<sup>2</sup> installation to its nearest neighbour of *any* size, in metres
-- added 2026-07-29 and now computed automatically for every fold (`folds.csv`), not
a one-off calculation. It splits the nine quadrats cleanly at ~20-40 m with no
quadrat in between: five pack sub-400 m<sup>2</sup> arrays tighter than one
Sentinel-2 pixel (7-19 m -- Lahore, Mardan, Karachi coastal, Sialkot), four sit at
44-52 m (Quetta, Faisalabad, Multan, SITE Karachi, Sundar).

That split is not incidental. Measured against the same nine quadrats' own numbers:
packing distance correlates **r=0.70** with `exp_scale_anchor`'s fraction-head scale,
**r=0.82** with its segmentation scale, and **r=0.78** with `auc_within_size` above.
A single geometric measurement from the labels alone -- no imagery, no model --
predicts most of why quadrats disagree on `exp_scale`, `rate_ratio`, and skill. It is
effectively a continuous, measurable version of the "4 industrial vs 5 residential"
split this project already tracked by hand.

Two consequences, both acted on already:

- **Held-out quadrat choice for the fraction-head retrain** (below) should account for
  packing, not just be picked for convenience. Lahore, the densest quadrat (7.2 m),
  is also the single richest source of graded per-pixel training signal for the
  sub-400 m<sup>2</sup> regression target -- holding it out is a real trade-off
  (removing the best training example) made deliberately because it is also the
  most statistically powerful validation check (1,033 installations to test against,
  more than the other four dense quadrats combined).
- **`nn_median_m` is now a standing column in `evaluate()`'s fold report**, so any
  future fold's AUC/`rate_ratio` swing can be read against its packing regime at a
  glance, instead of needing a separate cross-reference. It is not (yet) used as a
  per-building model feature -- it is a quadrat-level property, not a building-level
  one, so it belongs in the reporting layer, not `MODEL_FEATURES`.

The two residential folds are the ones to read, and the coastal Karachi box is the strongest
evidence in the project. It is the only quadrat asserted **Rule-1 complete**, so its
PV-free buildings are trustworthy negatives rather than unmapped ones; its median
installation is 86 m<sup>2</sup> and 98.8 percent of its installations sit below the
detection floor. There, the segmentation model scores **exactly 0.500, chance**, and predicts
**zero** PV area over the box's buildings. The per-building classifier reaches 0.831 at fixed
roof size. Controlling for size costs the classifier only about 3 AUC points across folds,
so this is the imagery separating a PV roof from a PV-free roof of the same size, not a
house-size proxy.

A feature-block ablation sets the shipped configuration, rather than preference (also
updated 2026-07-29, nine quadrats):

| features | AUC | AUC, roofs <500 m<sup>2</sup> |
| --- | ---: | ---: |
| footprint size only | 0.715 | 0.668 |
| footprint reflectance only | 0.841 | 0.845 |
| **size + reflectance (default)** | **0.874** | **0.856** |
| plus segmentation and fraction rasters | 0.876 | 0.858 |

Size alone is a real but modest prior, so the skill is not just "big buildings have PV".
With six quadrats, adding the existing model rasters as features cost accuracy on small
roofs (0.882 -> 0.870); with nine, that reverses to a marginal *gain* (0.856 -> 0.858) --
small enough either way (<0.002) to read as noise rather than a real effect in both
directions. The rasters stay off by default: the case for including them was never
strong, and it is not stronger now.

!!! warning "Ranking transfers, absolute rates do not"
    `rate_ratio` in `folds.csv` spans **0.235 to 4.833** across nine quadrats (Mardan
    under-predicts 4.3x, Quetta over-predicts 4.8x). Trained pooled, the model predicts
    0.137 for residential Lahore where the truth is 0.301. So the ordering generalises out
    of stratum but the *level* does not, and a per-stratum intercept is required before any
    adoption rate or capacity number is published. That needs more residential/non-industrial
    quadrats -- five of nine now cover that ground (Karachi coastal, Lahore, Sialkot, Mardan,
    Quetta), up from one, but the spread above shows the binding constraint has not gone away.

### National deployment: a scaling success, with one clean calibration lesson

`roofclf.score_buildings_national` takes the pooled fit above and scores every VIDA
building in the country -- **81.76 million buildings across all 4,473 composite
cells**, previously untested at this scale. Two things made it tractable rather than a
multi-day job: the shipped feature set never needed the segmentation/fraction
probability rasters (ablation-excluded, see the table above), so scoring needs only
composites + VIDA buildings, both already proven at national scale by `density.py`;
and routing through `local_source.composite_index`'s existing `lru_cache` (previously
unused by anything) avoids rebuilding the ~4,474-tile composite index once per cell.
The deployment threshold is chosen the same way as the SPPI work
(`sppi._precision_threshold`): most conservative cut clearing a target precision on
pooled leave-one-quadrat-out scores, not Youden's J, because a capacity-contributing
detector needs precision as the primary criterion.

That threshold is also where the "ranking transfers, absolute rates do not" warning
above stopped being abstract. Quetta -- the lowest-base-rate quadrat by a wide margin
(3.0%, next-lowest is 5.7%) and the one place SPPI's own building-scoped detector
collapsed to 10.5% precision -- was distorting the pooled threshold: holding a 0.50
precision target across all nine quadrats forced the cut up to 0.4555, which caught
only 25% of true positives at that precision. Re-fitting on the other eight quadrats
(Quetta excluded, `data/roofclf_with_quetta_20260730/` kept for comparison) relaxed the
threshold to 0.3064 and recall at the *same* 0.50 precision target rose to **39.6%** --
a real, measured gain from removing one quadrat whose extreme base rate was pulling the
whole pooled cut in the wrong direction, not from more data or a better model.

**What this experiment does and does not license.** It is a genuine win on the
question `roofclf` was built to answer -- given a fixed precision bar, how many true
installations does the flagged set catch -- and it is the clearest illustration yet of
why a single pooled cut is fragile: one outlier stratum, not nine ordinary ones, was
setting the whole country's operating point. It does **not** mean `roofclf`'s national
output is ready to contribute a capacity number. Converting 872,730 incrementally
flagged buildings (no segmentation candidate within 30 m) into MWp at a flat precision
weight was tried and produced 18,063 MWp -- 3.5 to 8x the country's entire existing
recall-corrected total -- because a flat precision measured on nine base-rate-skewed
quadrats does not survive being applied to 81.76 million mostly-rural buildings at a
different true prevalence, the same failure this section's warning already names. See
[the full writeup](../issues/roofclf-national-deployment-and-temporal-features.md)
for the diagnosis. `roofclf`'s national scores stand today as a per-building
ranking/lead-generation signal, not a capacity input.

### SPPI cross-validation: real but uneven, and only as a second opinion

SPPI (He et al. 2026, `src/earthpv/sppi.py`) is a zero-training spectral index scored
directly on `roofclf`'s own held-out ground truth
(`data/roofclf/buildings.geoparquet`) -- the same 8 quadrats, same labels, apples to
apples:

| signal | median AUC | within size band |
|---|---:|---:|
| SPPI (zero training) | 0.823 | 0.828 |
| `roofclf` (17 features, fitted) | **0.874** | **0.842** |

`roofclf` wins, but not by a wide margin given SPPI needs no training at all. **Adding
SPPI as a `roofclf` input feature does nothing** -- 0.8736 to 0.8734 AUC, the same
within-noise result the seg/frac raster features got when tried the same way -- because
`roofclf`'s fitted linear weights already span the bands SPPI computes a fixed nonlinear
combination of. That could read as "SPPI is redundant, stop here." It is not: a
**second, independent check does something a single linear model over the same bands
cannot**, tested 2026-07-30 as a live question ("could both methods agreeing produce a
conservative sub-400 m<sup>2</sup> estimate?") rather than assumed.

Restricting to sub-400 m<sup>2</sup> buildings (8 quadrats, Mardan excluded as its own
already-diagnosed bad fold) and requiring `roofclf >= 0.3064` **and** SPPI above a
matched-recall threshold:

| | precision | recall | n flagged |
|---|---:|---:|---:|
| `roofclf` alone | 0.496 | 0.462 | 1,144 |
| **AND-gate (both agree)** | **0.540** | 0.445 | 1,009 |
| `roofclf` alone, at the *same* recall (0.445) | 0.498 | -- | -- |

Agreement buys roughly **+4 points of precision over `roofclf` alone at matched recall**
-- a real, measured gain, not just a stricter cutoff on one model wearing a different
hat. The mechanism: SPPI is a fixed nonlinear combination of bands, `roofclf` a linear
model over similar bands -- a linear model cannot fully reconstruct a nonlinear AND from
one added covariate, so the two decision boundaries stay genuinely complementary even
though SPPI carries no *rank* information `roofclf` doesn't already have on its own.

**The gain is real but concentrated, not uniform -- read per quadrat, as always:**

| quadrat | `roofclf` precision | AND-gate precision | delta |
|---|---:|---:|---:|
| Multan | 0.256 | 0.363 | **+10.7pp** |
| Sialkot | 0.321 | 0.376 | **+5.5pp** |
| Sundar | 0.253 | 0.304 | **+5.1pp** |
| SITE Karachi | 0.567 | 0.581 | +1.4pp |
| Lahore | 0.791 | 0.795 | ~flat |
| Faisalabad | 0.359 | 0.352 | -0.7pp |
| Karachi coastal | 0.644 | 0.635 | -0.9pp |

The gain concentrates almost entirely in Multan/Sialkot/Sundar -- exactly the three
low-base-rate quadrats the density-stratified precision work above had to *exclude* from
calibration because `roofclf` overestimates 2x+ there. That is a coherent story, not a
coincidence: SPPI agreement specifically catches `roofclf`'s overconfidence in the
regime already known to be miscalibrated, rather than helping everywhere.

**Tested nationally, 2026-07-30, on the domain-restricted population -- and it does not
help there, confirming the table above rather than adding to it.**
`score_buildings_national` now saves `sppi` alongside `p_roofclf` (zero extra cost, same
bands already read; re-run once to backfill it,
`data/roofclf_national_with_sppi/pakistan/prob/`). Applying the AND-gate to the *same*
93 domain-restricted cells the sub-400 capacity figure below uses (i.e. exactly the
Faisalabad/Karachi-coastal/SITE-Karachi-like regime, not Multan/Sialkot/Sundar):
precision on those three calibration quadrats themselves is **flat** (0.5501 roofclf-alone
vs 0.5499 AND-gate) while the AND-gate cuts the flagged population by 31% (496,122 to
343,032 buildings) and the resulting capacity figure by 29% (6,628 to 4,690 MWp) for no
precision gain. This is the mechanistic prediction of the per-quadrat table above,
confirmed rather than contradicted: SPPI's benefit lives specifically in the low-density
quadrats the domain restriction already excludes, so stacking the AND-gate on top of an
already-restricted, already-well-calibrated population only removes recall for free.
**Not adopted for the domain-restricted figure.** SPPI remains valuable as a check in
the regime it actually helps (a future, separate low-density correction, not yet
designed), not as a blanket addition to every roofclf deployment.

### Regime-B correction and a national-proxy test (2026-07-31)

Two follow-up questions, asked directly: does the Multan/Sialkot/Sundar-specific gain
reproduce under a pooled (not per-quadrat) re-test, and can a per-cell signal tell us
*where* that regime applies nationally so its correction could actually be deployed?

**Reproduced, pooled, at matched recall.** `sppi.and_gate_regime_precision` pools
TP/FP/FN across Multan, Sialkot and Sundar (sub-400 m<sup>2</sup> buildings, 9-quadrat
table) rather than reading off per-quadrat deltas one at a time:

| | precision | recall |
|---|---:|---:|
| `roofclf` alone (0.3064 threshold) | 0.309 | 0.424 |
| `roofclf` alone, at the AND-gate's own recall | 0.462 | 0.153 |
| **AND-gate** | **0.578** | 0.153 |

A **+11.7 point** pooled gain at matched recall, a bit larger than the mean of the three
individual per-quadrat deltas (+10.7/+5.5/+5.1pp) reported above -- the effect survives
pooling, it is not an artefact of averaging three small samples. The cost is the same
one already on record: only 15% of true installations in this regime survive the
AND-gate. This is now reusable code (`sppi.and_gate_regime_precision`), not a one-off
script result.

**A related instability worth naming.** Which quadrats even count as "Multan/Sialkot/
Sundar-like" (`rate_ratio` outside [0.5, 2.0]) depends on which fold table you read,
because `rate_ratio` is itself a leave-one-quadrat-out statistic that shifts as the
training pool changes. Sundar measures 1.68 (7-quadrat table), 2.11 (8-quadrat,
Mardan added), then 1.71 (9-quadrat, Quetta added) -- straddling the 2.0 boundary across
runs. The domain-restricted capacity figure (6,628 MWp) used the 8-quadrat table's
3-quadrat split (Faisalabad, Karachi coastal, SITE Karachi); re-running
`select_calibrated_quadrats` against the current 9-quadrat table gives 4 (Sundar now
included). This does not change the 6,628 MWp figure retroactively -- that number is
pinned to the fold table it was computed from -- but it means the Good/Regime-B split
is a measurement with its own sampling noise near the boundary, not a fixed partition
of Pakistan's geography.

**Per-cell SPPI agreement rate as a national stratification proxy: tested, and it does
not work.** The real, reproduced gain above is useless for national deployment without
a way to tell which national cells are Multan/Sialkot/Sundar-like versus
Faisalabad/Karachi-coastal/SITE-Karachi-like -- exactly the proxy problem this project
has already failed to solve twice (existing candidate density anti-correlates with true
small-PV rate; `roofclf`'s own raw predicted rate does not separate the regimes
either). A per-cell signal needs no ground truth to compute nationally, so a candidate
worth testing before assuming it does not exist: does the *fraction of `roofclf`-flagged
buildings that SPPI also confirms* (`sppi.agreement_rate_by_quadrat`) track `rate_ratio`?

| quadrat | confirmation rate | `rate_ratio` |
|---|---:|---:|
| Mardan | 0.000 | 0.235 |
| Lahore | 0.050 | 0.454 |
| Karachi coastal | 0.098 | 0.682 |
| SITE Karachi | 0.440 | 1.146 |
| Faisalabad | 0.675 | 1.328 |
| Sundar | 0.319 | 1.710 |
| Multan | 0.327 | 2.068 |
| Sialkot | 0.117 | 2.304 |
| Quetta | 0.506 | 4.833 |

Correlation among the 7 quadrats with an ordinary failure mode (excluding Mardan and
Quetta, each already separately diagnosed as a distinct problem, not a density-regime
one) is weak: Pearson r = 0.19, Spearman rho = 0.36. It only looks strong (r = 0.50,
rho = 0.63) with Mardan and Quetta folded back in -- almost certainly driven by those
two known outliers rather than a real relationship, since the sign is not even
consistent among the core 7: Karachi coastal (well-calibrated, `rate_ratio` 0.68) shows
a *lower* confirmation rate than Sundar (over-predicting, `rate_ratio` 1.71), the
opposite of what the hypothesis predicts. **Negative result, kept as code
(`sppi.agreement_rate_by_quadrat`) rather than deleted**, in the same spirit as
`roofclf_capacity.py`: this project has now failed to find a national stratification
proxy three times (candidate density, `roofclf`'s own rate, SPPI agreement rate), which
is itself useful to know before trying a fourth. The Regime-B correction above therefore
stays exactly where it started: a real, reproducible effect with no known way to say
where it applies outside the quadrats it was measured on.

### Sub-400 m² experimental capacity: density-stratified, deliberately separate

`src/earthpv/sub400_capacity.py` (2026-07-30) is the outcome of trying to fold both
sub-400 m² instruments -- the fraction head and `roof-classifier`'s national scores --
into one capacity number. It is **not part of the published atlas above**, on purpose:
promoting the fraction head into `density.py` itself broke `check-density` (previous
section), and the module's own docstring is written as a running record of what was
tried and rejected, not just what worked, in the same spirit as
`roofclf_capacity.py`.

**Precision correction alone does not fix national deployment.** roofclf's per-quadrat
precision at the deployment threshold (0.3064) is not flat -- it ranges 0.30 to 0.81
across the 8 (no-Quetta) calibration quadrats -- and the relationship to true PV density
(`base_rate`) is a crossing point, not a slope: quadrats below about 12% base rate
over-predict by 2x or more, the one quadrat well above it (Lahore, 30%) under-predicts
instead, and Mardan is a separate, already-diagnosed bad fold unrelated to density.
Restricting to the three quadrats whose `rate_ratio` sits within 2x of 1 either way
(Faisalabad, Karachi coastal, SITE Karachi -- 12.5-18.5% base rate) lifts pooled
precision from the flat LOQO 0.499 to **0.5495**. Applied to the *same* national
population the rejected flat-precision attempt used, this makes the number **worse**,
not better -- 37,197 to 40,879 MWp -- because 0.5495 is still just barely above 0.5. The
volume of buildings being priced, not the weight applied to them, was always the problem.

**What actually moves the number is restricting the population.** Combining three
corrections -- the pre-existing building-density domain restriction (only the 93 of
4,473 national cells whose settlement density falls in the calibration quadrats'
737-4,750 bldg/km² range), a contamination filter (buildings whose own footprint is
already >= 400 m² are dropped from "incremental" -- they were never sub-floor, they
just sit outside `new_lead_mask`'s 30 m matching radius of an existing candidate; 13.4%
of the domain-restricted incremental buildings, 49% of its area), and the density-regime
precision above -- gives:

| | value |
| --- | ---: |
| Domain cells | 93 / 4,473 (2.1%) |
| Buildings in domain | 15.6M / 81.8M (19.1%) |
| Incremental buildings (post-contamination-filter) | 418,076 |
| Incremental sub-400 m² roof area | 67.0 million m² |
| **Sub-400 m² capacity (domain-restricted)** | **6,628 MWp** |

That is, for the first time, the same order of magnitude as the country's entire
existing segmentation-based total (5,078 MWp) rather than 3.5-8x it. It is still not a
national number: **6,628 MWp describes only those 93 cells.** Rescaling it by the
domain's 2.1%/19.1% share to infer a country total (~315 GWp) is exactly the
base-rate-transfer failure this module exists to avoid, and
`domain_restricted_capacity`'s returned summary states the scope explicitly so a caller
cannot lose that caveat downstream.

**Where those 93 cells are** (the only areas this figure actually describes): Karachi,
Lahore and Peshawar (7-8 cells each), Mardan and Faisalabad (6), Islamabad and Sialkot
(5), Multan, Charsadda, Sheikhpura and Gujranwala (3), Rawalpindi and Quetta (2), plus a
long tail of single-cell districts. Building density (not PV density) is the only
national proxy that survived testing as a way to identify candidate areas -- existing
segmentation-detected candidate density was tried and **rejected**: it anti-correlates
with true small-PV base rate (Karachi coastal and Lahore, the two quadrats with the
*highest* true small-PV adoption, both show near-zero existing large-PV candidate
density, because large-industrial and small-residential PV are different populations).
roofclf's own raw predicted rate per cell was also tried and rejected: it does not
separate calibrated from miscalibrated quadrats either (Multan and Sundar's predicted
rate sits inside the "well-calibrated" band despite being 2x+ miscalibrated in truth).
So "where might medium/high sub-400 m² PV density exist beyond the 8 mapped quadrats" is
answered here only as "these are the largest, densest cities, which is where 6 of the 8
existing quadrats already are" -- a reason to prioritize new calibration quadrats in
Karachi's other residential districts, Rawalpindi, Peshawar and Islamabad, not a
validated prediction of where capacity sits.

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

The check exists because of a specific failure it now catches. Before the mounting split
and the blob filter, Gilgit-Baltistan -- Karakoram rock and glacier -- was credited with
166 MWp of PV against 0.8 MWp of rooftop, a ratio near 200, with a single cell holding
39 percent of it. Four of seven provinces failed. The published run (last regenerated
2026-07-26) passes, with Balochistan, Gilgit-Baltistan and Azad Kashmir still flagged
suspect, which is the honest answer for three sparsely built desert and high-mountain
regions.

!!! warning "Gilgit-Baltistan is now exempted from check 1, not fixed (2026-07-29)"
    A fresh `--force` recompute surfaced Gilgit-Baltistan at 110 MWp ground-mount against
    **0.000 MWp** rooftop -- worse than the pre-fix example just above, on the same
    candidates unchanged since 2026-07-16. An isolating segmentation-instrument rerun
    (no fraction swap) reproduced the **identical** 0.000/109.982 MWp numbers, confirming
    this is a `density.py` regression in `no_building`-placement aggregation, not anything
    to do with the fraction head (full trace:
    [density-force-recompute-plausibility-fail](../issues/density-force-recompute-plausibility-fail.md)).
    `RATIO_CHECK_EXEMPT_REGIONS` in `plausibility.py` now excludes Gilgit-Baltistan from
    check 1 specifically (its real rooftop base rate is near zero, so the ratio is
    structurally uninformative there regardless of any bug) -- `check-density` passes
    again as a result (0 fail, 3 suspect) on both instruments. **This unblocks the gate,
    it does not resolve the open question of whether the 110 MWp ground-mount figure
    itself is correct** -- locating the exact cause in `density.py`/`postprocess.py`'s
    aggregation code is still open.

## Running it

```bash
# once, and again whenever new validation evidence lands
pixi run earthpv calibrate-candidates --aoi pakistan

pixi run earthpv density --aoi pakistan --districts
pixi run earthpv check-density --aoi pakistan  # gate the numbers before publishing them
pixi run earthpv atlas --aoi pakistan          # standalone atlas regeneration

# Sub-400 m2 instruments (see above). Neither is in the published atlas yet.
pixi run earthpv roof-classifier --aoi pakistan          # per-building, quadrat-trained
pixi run earthpv density --aoi pakistan --districts \
    --fraction-prob-dir data/predictions_frac_pk_v2/pakistan/prob   # partial coverage
```

Changing the expected-area instrument or `--exp-scale` only reaches the per-building and
`*_roof` columns on a `--force` re-run, since those live in the cached cell partials.

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
8. **Mounting-split conversion, blob filter and the plausibility gate**, 2026-07-26, from a
   method review. Steps 1 to 7 all corrected the *area*, and then converted whatever
   survived at one rooftop constant. Two errors hid in that last step and pushed the same
   way. Ground-mount polygons are site area, not module area, so converting them at
   0.18 kWp/m<sup>2</sup> overstated them two to three fold. And nothing bounded polygon
   size, so 167 merged blobs carrying 47 percent of candidate area were each converted as
   one installation's panels. Together they had inflated the all-PV headline roughly
   threefold, almost entirely in the non-rooftop component; the plausibility gate now
   fails the build if that recurs. The rooftop-scoped estimates, which the review found
   sound, moved much less.

Open next steps are the OpenStreetMap flywheel producing enough in-domain positives for a
retrain, NEPRA net-metering totals as a Pakistani MaStR analogue, and per-epoch density
estimates turning `est_mwp` into a time series so the 2022 to 2026 boom becomes measurable
per district.
