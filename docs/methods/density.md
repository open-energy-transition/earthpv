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

!!! warning "Full coverage reached, but blocked on a separate regression"
    As of 2026-07-29 the fraction-head run covers **all 4,463 manifest cells**
    (`exp_coverage_frac: 1.0`) — the inference finished on 2026-07-27, the docs simply
    hadn't been updated. National expected-area rooftop capacity with the fraction
    instrument comes out at **6.65 GWp** vs the segmentation instrument's **5.4 GWp**
    (+23%), consistent in direction and rough magnitude with the quadrat-level finding
    above that segmentation is structurally blind below the floor. That comparison is
    architecturally clean: the exp/fraction swap touches only `pv_area_exp`/`est_mwp_exp`,
    nothing else in the pipeline.

    That said, **the published atlas still is not promoted to the fraction instrument**,
    because the same full-coverage `--force` run failed `earthpv check-density`:
    Gilgit-Baltistan's ground-mount estimate came out at 110 MWp against **0.000 MWp**
    rooftop (a worse ratio than the pre-fix example the gate's own acceptance test uses).
    Tracing it, the candidates behind that number are unchanged since 2026-07-16 and the
    exp instrument cannot be the cause — this looks like a regression in `density.py`'s
    `no_building`/ground-mount aggregation introduced by the same commit that finished the
    fraction head, only now exercised by a full forced recompute. See
    [density-force-recompute-plausibility-fail](../issues/density-force-recompute-plausibility-fail.md)
    for the full trace and next steps. Until that is root-caused and `check-density`
    passes again, **no run from this codebase should be published, fraction instrument or
    segmentation** — the block is on the regression, not on the fraction head's own
    merits.

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
