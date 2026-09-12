# France: a second register, and the first external check on the module constant

Germany answered the question above the 400 m&sup2; floor and was structurally silent below
it. France is the opposite case, and it is the more useful one for the half of this
project that had no external check at all.

Three things make it so. Its national register is complete, like Germany's. It publishes
**dated year-end vintages** of that register going back to 2017, so the reference can be
read back to the epoch a label was drawn against instead of compared across a multi-year
gap. And fourteen communes have been **swept exhaustively by hand** on sub-metre IGN
aerial imagery, with solar-thermal collectors tagged separately from PV, which is ground
truth of a kind no Pakistani quadrat and no German OSM extract can supply.

Set against that there is a fourth dataset,
[OpenPVMapper](https://doi.org/10.5281/zenodo.21534856) (Kasmi 2026, CC-BY-4.0): 1.14
million rooftop PV polygons with area and estimated capacity, covering mainland France.
It is a model output, not truth, and this page treats it as one.

Interactive: [France PV comparison atlas](../assets/interactive/france_pv_comparison_atlas.html)
and [France evidence atlas](../assets/interactive/france_pv_evidence_atlas.html).

## The headline: 0.150 kWp/m&sup2;, measured

`DEFAULT_KWP_PER_M2_MODULE = 0.18` converts detected module area into capacity in every
capacity number this project publishes. It was calibrated independently and has never been
checked against an external reference, because the one attempt to do so
[failed in Germany](germany.md): only about 3.6% of registered German rooftop units are
mapped in OSM at all, and the well-mapped tail's implied kWp/m&sup2; swings between 0.02 and
0.99 on mapper convention alone.

France supports the measurement directly. The register censors units below 36 kW into
per-commune aggregates, and 36 kW is 200 m&sup2; of module at 0.18 kWp/m&sup2;, so the
aggregate band and the mapped installations under 200 m&sup2; describe the same population.
Dividing one by the other, with the register interpolated back to each commune's own
mapping date:

| Quantity | Value |
| --- | --- |
| Pooled, epoch-matched | **0.150 kWp/m&sup2;** |
| Pooled, sensitivity variant (ambiguous tags counted as PV) | 0.147 kWp/m&sup2; |
| Pooled, **without** the epoch correction | 0.230 kWp/m&sup2; |
| Median commune (IQR) | 0.149 (0.129 to 0.273) |
| Project constant | 0.180 kWp/m&sup2; |
| Ratio measured / assumed | **0.83** |
| Communes used | 11 of 14 |

Two readings of this matter more than the point value.

**The epoch correction is not optional.** Taking today's register against imagery flown in
2021 to 2024 gives 0.230 kWp/m&sup2;, 53% higher, purely because France added roughly 10 GWp
of PV between the flights and the current snapshot. Any comparison of a mapped area to a
register that skips this step measures growth and reports it as physics. This is the same
epoch-staleness bias that makes Rule-1 completeness relative in Pakistan, except that here
it is measurable and has been removed.

**0.18 looks about 17% high for French residential PV, not wrong.** The measurement lands
at 0.150 with a wide per-commune spread (0.053 at Toussieux to 0.343 at Macon), and it is
a lower bound in one direction and an upper bound in another: mapping misses arrays under
tree cover or shadow, which pushes the ratio up, while the register's small band contains
units the mapper saw no trace of on an older flight, which also pushes it up. It is a
France-specific number and it does not transfer to Pakistan on its own. What it does
establish is that the constant is the right order of magnitude and biased in a knowable
direction, which is more than was known before.

Three communes are excluded and the reasons are recorded rather than absorbed:
Saint-Gely-du-Fesc is marked unfinished by the mapper and is not Rule-1 complete; Langoat
and Saulny have mapped installations but no sub-36 kW aggregate in the register at their
mapping epoch, which is a hole in the reference rather than a commune without PV.

### Why 0.150 and not 0.19, and why that is the number this project actually wants

A modern crystalline module runs about 0.20 kWp per square metre of module, an early-2010s
one nearer 0.15. The registered small band grew from 1.87 GWp at the end of 2020 to 5.97
GWp now, so it is majority-modern, and pure module physics would put the ratio above the
0.150 measured here.

The gap is the difference between **module area and mapped-polygon area**. A person tracing
an array on aerial imagery draws its outline, which includes inter-panel gaps, mounting rails
and the margin at the roof edge. That polygon is larger than the modules inside it, so
capacity divided by it is lower than capacity divided by module area.

That is the useful part. `DEFAULT_KWP_PER_M2_MODULE` is applied in this pipeline to
**detected polygon area**, which has the same property, so the France measurement is
comparable to the way the constant is actually used rather than to a datasheet. Read that
way it says the pipeline's 0.18 is roughly 20% high for converting a traced or detected
outline into capacity, not that anyone's panels are unusual.

It remains a French measurement. Array packing density, roof geometry and installation
vintage all differ by country, and nothing here licenses moving Pakistan's constant.

## What share sits below the floor, and why it is not Germany's number

| Denominator | Capacity below 72 kWp |
| --- | --- |
| France, all registered PV | 17.3% |
| France, low-voltage connections only | 31.1% |
| Germany, rooftop (measured directly) | 65.5% |

**These are not the same measurement, and the gap is mostly a real difference between the
two countries' fleets.** France's register carries no rooftop/ground attribute, so no
French figure can be restricted to rooftop the way Germany's is. All registered PV is a
firm lower bound, since ground-mount is essentially all above the floor. Low-voltage only
is a rooftop-leaning upper bound, since utility-scale farms connect at HTA or above. The
rooftop truth lies between them, and even the upper bound is less than half Germany's.

France has 35.0 GWp of registered PV against 19.1 GWp on low-voltage connections: a much
more ground-mount-heavy fleet than Germany's. So the practical consequence of the 400
m&sup2; floor is genuinely smaller here. This is direct evidence for something
[Germany's page](germany.md) argued from dispersion alone: the below-floor share is not a
transferable constant. Measured in two complete registers it differs by a factor of two to
four.

The count share tells the opposite story and is the one that is easy to quote misleadingly:
**92.0% of French PV installations are below the floor**, at a mean of 5.09 kW each across
1,093,774 registered small units. Quote the capacity share.

## What France cannot do that Germany could

The register publishes **no coordinates at any size**. Germany's `p_unmapped` precision
instrument works by testing whether a registered unit's address point falls inside an
unmapped candidate polygon; with no coordinates there is no French counterpart, and this
project does not substitute one. Nor can shares below 36 kW be recovered: the censoring
rule means unit sizes under that threshold do not exist in the data, so the 10 and 30 kWp
brackets Germany reports are returned as censored rather than modelled.

## OpenPVMapper against the register

Scoring the reference before using it as one, per commune, across 22,157 communes:

| Comparison | slope | median ratio | Spearman | total ratio |
| --- | --- | --- | --- | --- |
| vs all registered PV | 0.477 | 0.389 | 0.681 | 0.405 |
| vs low-voltage only | 0.500 | 0.434 | 0.681 | 0.735 |
| **vs below 72 kWp, both sides cut at the floor** | **0.792** | **0.800** | **0.789** | **0.910** |

The third row is the like-for-like one, and it is a good result: restricted to the
population it targets, OpenPVMapper accounts for **91% of the register's sub-72 kWp
low-voltage capacity**, with rank correlation 0.79 across communes. The first two rows
mostly measure the fact that OpenPVMapper claims rooftop only while the register counts
everything.

One discrepancy is worth recording. OpenPVMapper's own implied capacity density, its total
kWp over its total polygon area, is **0.129 kWp/m&sup2;**, against the 0.150 measured here
from the register and hand-mapped area, and the 0.18 this project assumes. All three are
attempts at the same physical constant and they span a factor of 1.4.

## OpenPVMapper against ground truth

Inside the fourteen hand-mapped communes both error directions are measurable, which the
dataset's own stratified precision estimate cannot do:

- **Count recall 0.667, area recall 0.670** against 2,622 hand-mapped PV installations.
- **Raw precision 0.555** against 2,976 OpenPVMapper polygons, rising to 0.582 once
  solar-thermal confusions are removed from the denominator.

Of 1,325 OpenPVMapper polygons with no mapped PV underneath, **137 sit on solar-thermal
collectors**, 8 on features the mapper retracted, and 1,180 are unexplained. Two things
inflate that last number and neither is necessarily an error: OpenPVMapper's IGN flight
vintage postdates the mapping in several communes, so some are genuinely newer arrays, and
the truth set deliberately excludes the mapper's ambiguous tags.

**Solar thermal is the systematic confusion, and it is invisible to any validation that
does not carry the tag.** 381 of the 3,335 mapped features are hot-water collectors: black
glazed rectangles on south-facing roofs that produce no electricity. Grenoble alone has
121 of them, and 91 of its 264 unexplained OpenPVMapper polygons sit on one.

Recall by installation size, in module area, against a 100 m&sup2; Sentinel-2 pixel:

| Installation | n | area recall |
| --- | --- | --- |
| 0 to 20 m&sup2; | 1,397 | 0.660 |
| 20 to 50 m&sup2; | 873 | 0.785 |
| 50 to 100 m&sup2; | 112 | 0.557 |
| 100 to 200 m&sup2; | 112 | 0.604 |
| 200 to 400 m&sup2; | 84 | 0.585 |
| 400 m&sup2; and above | 44 | 0.718 |

There is no clean size gradient. At sub-metre resolution detection is not
resolution-limited over this range, which is the expected result and the useful contrast
with earthpv, whose whole difficulty is that the modal French array here is 20 m&sup2;,
a fifth of one Sentinel-2 pixel.

**These communes are not independent of OpenPVMapper.** They are its manual-correction
layer, so its rows inside them have been corrected toward this ground truth and the
precision measured here is an optimistic bound on precision elsewhere. Recall is the half
that transfers.

## earthpv against France, measured against the register

France is the second country whose numbers can be scored against a complete register, and
unlike Germany it was scored **twice**: once with a model that had never seen a French roof,
and once after retraining with French data. Both runs cover the same 20,501 communes and
93.0% of registered capacity, so they are directly comparable.

| estimator | zero-shot slope | **retrained slope** | zero-shot &rho; | **retrained &rho;** | Germany slope | Germany &rho; |
| --- | --- | --- | --- | --- | --- | --- |
| `est_mwp_det` | 0.127 | **0.160** | 0.262 | **0.446** | 0.340 | 0.661 |
| `est_mwp_exp` | 0.162 | **0.170** | 0.290 | **0.449** | 0.388 | 0.656 |

**Rank correlation rose from 0.29 to 0.45, closing about half the gap to Germany.** That is
the result that matters. Spearman is scale-free, so unlike slope it cannot be explained by
conversion constants or by France's proxy denominator: it says the retrained model puts
capacity in substantially the right communes, and the zero-shot one did not. Slope moved
much less (det +25%, exp +5%), and total recovered capacity went from 26% to 34% of
registered above-floor low-voltage capacity.

Quote `est_mwp_det` and `est_mwp_exp` for France. `est_mwp_cal` and `est_mwp_rc_roof` sit
near 0.02 for both models because France has no glint sample, so `p_unmapped` is 0 and
`p_real` collapses to the OSM-mapped fraction, booking every real-but-unmapped candidate as
false. Germany shows the same collapse in `est_mwp_cal` (0.167) and is rescued by a recall
correction France does not have.

### What retraining actually changed

The candidate population changed character rather than simply growing:

| | zero-shot | retrained |
| --- | --- | --- |
| candidates | 13,419 | 39,462 |
| rooftop share | 26.9% | 50.3% |
| median area | 8,301 m&sup2; | 1,400 m&sup2; |
| total area | 364.0 km&sup2; | 255.3 km&sup2; |
| blobs &ge; 10,000 m&sup2; | 6,036 | 2,076 |

Three times as many objects, six times smaller each, **less** total area, and two thirds of
the large blobs gone. `polygonize_chips` merges touching thresholded pixels with no upper
bound, so a sheet of weak false positives becomes one multi-hectare "installation"; losing
two thirds of those while doubling the rooftop share is the signature of a detector matched
to a fleet of small rooftop arrays rather than to Pakistani and German industrial roofs.

### The caveat on this number

**France is 73.6% of the retrained corpus** (18,577 French chips against 6,661 from Germany,
Pakistan, Punjab and Gujarat combined). The improvement therefore confounds "French data is
present" with "the corpus is 3.8x larger". A France-capped run of about 3,200 chips, matching
Germany's share, would separate the two and has not been run. The checkpoint
(`v5_combined_france`, epoch 25) is applied to **France only**; Pakistan and Germany keep
v4 and their published figures are untouched.

## The sub-400 m&sup2; instrument still does not transfer

This is the result the whole exercise was for, and it is negative.

`roofclf` was fitted on 13 of the 14 communes (44,314 VIDA buildings, 1,231 carrying PV, a
2.78% base rate), with the parcel label, leave-one-quadrat-out:

| | France | Pakistan (30 quadrats) |
| --- | --- | --- |
| Median fold AUC | **0.710** | 0.857 |
| Median fold AUC, **within size band** | **0.627** | ~0.834 |
| Size-only baseline | 0.673 | |
| Spectral-only | 0.672 | |
| Segmentation baseline | 0.500 | ~0.50 to 0.78 |
| Precision 0.5 threshold | recall **0.0065** | usable |

**Spectral reflectance adds about 0.037 AUC over building footprint size alone** (0.673 to
0.710), and within a size band, where size can no longer help, it reaches 0.627. At a
threshold tuned for 50% precision the model flags 16 buildings out of 44,314. That is not a
deployable instrument.

Segmentation scores **exactly 0.500 in every one of the 13 folds**, which is the expected
control and worth stating plainly: at French residential scale the &ge; 400 m&sup2; detector
is not weak, it is blind.

**The cause is physical, not a modelling failure.** The median mapped French installation is
20 m&sup2;. One Sentinel-2 pixel is 100 m&sup2;. The array occupies a fifth of a pixel that
also contains roof tile, and the spectral contrast that `roofclf` reads in Pakistan, where
quadrats include far larger arrays on far larger roofs, is diluted below what a 10 m
multispectral sensor resolves. [OpenPVMapper](#openpvmapper-against-ground-truth) recalls the
same installations at 0.67 from sub-metre aerial imagery with no size gradient across this
range, which isolates the difference to the sensor rather than to the annotation or the task.

### Was it just too few labels? No

The obvious objection to all of the above is that 1,231 hand-mapped positives is simply too
small a training set, and that the sensor argument is being asked to explain what a bigger
corpus would fix. That is testable, because
[OpenPVMapper](https://doi.org/10.5281/zenodo.21534856) supplies 1.13M rooftop polygons
nationally, and it was tested.

`scripts/build_opvm_pseudo_quadrats.py` synthesizes roofclf quadrats over 90 PV-dense
communes whose labels come from OpenPVMapper instead of a human, and
`scripts/build_opvm_roofclf_table.py` runs the same `building_table` the real fit uses, so
the only thing that differs is the label source. The fourteen hand-mapped communes are
excluded by INSEE, because they are OpenPVMapper's own manual-correction layer and training
on them would leak in both directions. The training communes match the target regime: their
median array is 16.8 m&sup2; against the hand-mapped set's 19.2.

That gives **386,565 buildings and 16,435 carrying PV, 13.4 times the supervision**, over 87
communes disjoint from every evaluation commune. Scored on the same hand-mapped truth:

| | Training positives | AUC | Within size band |
| --- | --- | --- | --- |
| Hand-mapped baseline, leave-one-quadrat-out | 1,231 | 0.710 | 0.627 |
| **OpenPVMapper-trained** | **16,435** | **0.706** | **0.617** |
| Control: same model on held-out OpenPVMapper labels | 16,435 | 0.683 | 0.608 |

**Thirteen times the labels moves nothing** (-0.005 AUC, -0.010 within size band). The
control is the more informative row. If the model had learned OpenPVMapper's biases rather
than the world, it would score well on held-out OpenPVMapper labels and badly on hand-mapped
truth. It scores **0.683** on its own label source, essentially the same as on the human
one. The features do not separate roofs with PV from roofs without, whatever the labels say.

**This is a lower bound, and the direction is the safe one.** OpenPVMapper recalls 0.67 of
hand-mapped truth, so some of its negatives are real positives, and that mislabelling
attenuates measured AUC. But the control evaluation carries the same noise and lands in the
same place, and no plausible amount of label noise turns 0.706 into a deployable instrument.
Three of the 90 communes produced no table, having no VIDA buildings or no composite
coverage.

**This does not invalidate the Pakistani `roofclf`.** It bounds where the instrument works.
The honest reading is that the sub-400 m&sup2; half of this project's method is calibrated on
a population of installations that are small relative to the 400 m&sup2; segmentation floor
but still large relative to a Sentinel-2 pixel, and French residential PV sits below even
that. Pakistan's own sparse-stratum coverage ratio, already the least well supported part of
the atlas, should be read with this in mind.

Segmentation over the same 31 cells produced 119 candidates, median area 10,507 m&sup2;, of
which 112 are at or above the floor: industrial roofs and ground-mount, exactly the
population it is built for and no part of the population France's register censors.

### The evidence atlas

National, over all 5,473 composited cells and 13 regions: **Verified 11,163 MWp
(90% 8,547-14,887), Best estimate 11,995 MWp (90% 10,301-15,797)**, against a registered
34.6 GWp. Built on the retrained v5 checkpoint.

It is the **segmentation-only** form, for two independent reasons. France has no calibration
quadrats outside the fourteen mapped communes, which is this project's documented rule for
that state; and on the evidence below, `roofclf` would not be worth adding even if it did.

**The capacity figures are a strict precision floor, not a recall-corrected estimate.**
France has no glint sample, so `p_unmapped` stays at 0 and `p_real` collapses to the
OSM-mapped fraction, which books every real-but-unmapped candidate as false. Recall was
deliberately skipped (`--recall-reference none`) rather than measured against the hand-mapped
communes: those are a sub-400 m&sup2; ground truth and segmentation's population is above the
floor, so pooling them would have manufactured a large and badly-determined correction against
the 20x `DEFAULT_RECALL_FLOOR` clamp.

### Caveats on these numbers

`rate_ratio` (predicted over true adoption rate) spans 0.37 to 6.91 across the 13 communes,
so several would fail `select_calibrated_quadrats`'s precision-trust gate and no
coverage-ratio fit should be built on the set as it stands.

Four communes (Langoat 2021, Saulny and Eaunes 2022, Gannay 2022-23) were mapped before the
2024 composite window, so their labels understate what the imagery shows and their folds are
biased toward false positives.

`roofclf` ran **without** the segmentation-probability features: those are read from a single
0.1 degree cell and seven of the fourteen communes straddle two to four, so the feature would
have been correct in some folds and zero in others. Given segmentation scores exactly chance
here, nothing was lost.

The ablation rows that involve `brightness_zscore` are unreliable for France: that feature is
NaN for 31% of French buildings. It is not in the production feature set, so the headline
numbers above are unaffected.

## Reproducing this

```bash
# Register: current snapshot plus year-end vintages for the epoch correction
bash scripts/fetch_odre_vintages.sh 20 21 22 23 24 25

# Quadrats from the hand-mapped communes (tag filter, commune clip, VIDA placement)
pixi run python scripts/build_france_quadrats.py

# Commune polygons for the per-commune joins
pixi run python scripts/fetch_france_communes.py

# The validation itself; register blocks run with no imagery present
pixi run earthpv validate-france --opvm data/openpvmapper/enriched_national.parquet

# National imagery, then the zero-shot baseline
pixi run earthpv compose --aoi france --min-buildings 1000 --workers 4   # see the note below
pixi run -e ml earthpv infer --aoi france --checkpoint <v4 ckpt>
pixi run earthpv postprocess --aoi france --threshold 0.3
pixi run earthpv calibrate-candidates --aoi france --recall-reference none --by-placement
pixi run earthpv density --aoi france --districts
pixi run earthpv validate-france --opvm data/openpvmapper/enriched_national.parquet

# Retrain with France in the corpus, then score it again
pixi run earthpv chips --aoi france
pixi run python scripts/merge_chip_index.py germany punjab pakistan gujarat france
pixi run -e ml earthpv train --config configs/terramind_pv_v5_france.yaml
bash scripts/run_france_v5_compare.sh

# The atlases
bash scripts/rebuild_france_atlases_v5.sh
```

`compose` at country scale must be run through
`scripts/run_france_national_compose.sh`, not invoked directly: it leaks file descriptors and
degrades badly before it dies, so each pass is capped by wall clock and restarted. See
[the method page](../methods/france-validation.md#running-a-country-scale-compose).

Full method: [France validation](../methods/france-validation.md).
