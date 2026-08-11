# Experiments: what was tried, and what it cost

Most of what has been tried in this project did not ship. That is worth writing down for two
reasons: the negative results are the map of where Sentinel-2's 10 m resolution limit
actually sits, and every one of them cost real compute that nobody else needs to spend
again.

This page is the register. It covers everything that was measured, whether it ended up in
[the pipeline](how-it-works.md) or not. Every experiment has runnable code in the
repository; nothing was deleted on failure. For things that are still genuinely undecided,
see [Open questions](open-questions.md).

**How to read the verdicts.** <span class="outcome works">shipped</span> means it is in the
main workflow today. <span class="outcome mixed">partial</span> means it produced a real
measured signal that was not enough to promote. <span class="outcome negative">rejected</span>
means it was measured and beaten by the alternative, or failed its own control.
<span class="outcome open">superseded</span> means it shipped once and has since been
replaced, so its own write-up describes a pipeline that no longer exists.

## The register

| Experiment | Verdict | One line |
| --- | --- | --- |
| In-domain Pakistani training chips | <span class="outcome works">shipped</span> | Tripled large-array recall in Punjab, 0.18 to 0.55. The single biggest lever found. |
| Building prior from VIDA Open Buildings | <span class="outcome works">shipped</span> | Makes "no building nearby" a usable false-positive signal. |
| Quadrats as training data, not just correction | <span class="outcome works">shipped</span> | Became `roofclf`, now half the main workflow. |
| roofclf, a per-building classifier | <span class="outcome works">shipped</span> | 0.857 AUC (0.830 within size band) on 23 quadrats where segmentation scores near chance. |
| SPPI as a corroborating second opinion | <span class="outcome works">shipped</span> | Zero-training spectral index; agreement with roofclf defines the Verified tier. |
| Coverage ratio stratified by size and density | <span class="outcome works">shipped</span> | Replaced precision as the multiplier, and a flat ratio with a measured per-stratum one. |
| Placement-split precision and recall | <span class="outcome works">shipped</span> | Unpooling rooftop from ground-mount moved both, in opposite directions. |
| OSM geometry dissolve and closest-match dedup | <span class="outcome works">shipped</span> | Nested `plant`/`generator` ways were double-counting real installations. |
| Recall correction and credible intervals | <span class="outcome works">shipped</span> | Turned a structural floor into an estimate with a stated interval. |
| Quadrat-bootstrap uncertainty on the atlas | <span class="outcome works">shipped</span> | Both headline tiers now carry a 90% range. |
| Solar-glint corroboration | <span class="outcome works">shipped</span> | Calibrated likelihood ratios per size bucket, reward-only, never demoting. |
| Tile-major glint fetching | <span class="outcome works">shipped</span> | 22x faster, numerically identical output. |
| Pre-boom epoch check | <span class="outcome works">shipped</span> | A persistent 2021 signal demotes a candidate. |
| Vegetation veto | <span class="outcome works">shipped</span> | 596 of 5,132 leads vetoed, and specifically the right ones. |
| Hard-negative mining for segmentation | <span class="outcome works">shipped</span> | Bi-temporal confirmed negatives cut false-positive pixels 28.6%. |
| Fraction-regression head | <span class="outcome mixed">partial</span> | Beats segmentation on small arrays by 23x in the residential quadrat, never promoted into a published number. |
| Time-series step detection below 400 m² | <span class="outcome mixed">partial</span> | First non-zero recall under 500 m², but the capacity claim failed its own control. |
| Glint as a direct detector | <span class="outcome mixed">partial</span> | About 9% on model leads against about 1% on random buildings. |
| Per-pixel glint amplitude trim | <span class="outcome mixed">partial</span> | Moves pixel IoU slightly; threshold gating by glint does not. |
| roofclf hard-negative retrain from known false positives | <span class="outcome negative">rejected</span> | n=6 is not enough signal; oversampling trades overall skill for it. |
| Quadrat-supervised fraction retrain | <span class="outcome negative">rejected</span> | A large in-sample win the holdout does not support. |
| Two-season 20-band stacking | <span class="outcome negative">rejected</span> | No recall gain anywhere; slightly worse on large arrays. |
| Boom-window (2021 vs current) stacking | <span class="outcome negative">rejected</span> | Inconclusive: training collapsed on 332 chips. |
| Sentinel-1 corner reflection | <span class="outcome negative">rejected</span> | Backscatter enhancement indistinguishable from speckle. |
| Cell-aggregate glint density | <span class="outcome negative">rejected</span> | Wrong statistic for the question. |
| Missed-installation glint recovery | <span class="outcome negative">rejected</span> | Control false-validation rate exceeded the recovery rate. |
| Roof-axis orientation prior | <span class="outcome negative">rejected</span> | Flat concrete roofs do not constrain a tilt frame's azimuth. |
| Standard-pose matched filter | <span class="outcome negative">rejected</span> | The densest pose bin covers under 10% of installations. |
| Super-resolution, three variants | <span class="outcome negative">rejected</span> | No gain, and hallucination risk on a detection task. |
| Two-endmember spectral unmixing | <span class="outcome negative">rejected</span> | 0.659 AUC, worse than both SPPI and roofclf, with a 92x scale spread. |
| Epoch jump / step change as roofclf features | <span class="outcome negative">rejected</span> | Measured at exactly zero effect, and worse in the reflectance variant. |
| SPPI as a roofclf input feature | <span class="outcome negative">rejected</span> | 0.8736 to 0.8734 AUC. It helps by disagreeing, not by being a column. |
| OSM as a complete reference in Germany | <span class="outcome negative">rejected</span> | 3.6% complete by unit count; implied kWp/m² unstable by more than the constant itself. |
| Unrestricted national roofclf capacity | <span class="outcome open">superseded</span> | 18 to 37 GWp, rejected as miscalibrated; replaced by the domain-restricted estimate. |
| Low/Central/High/All-PV bracket atlas | <span class="outcome open">superseded</span> | Replaced by the two-tier evidence atlas, which sorts by standard of proof instead. |
| The Ceiling tier | <span class="outcome open">superseded</span> | A threshold change roughly doubled it with no new validation, so it stopped bounding anything. |
| National dashboard bundle | <span class="outcome open">superseded</span> | Replaced by plain per-artifact result pages; the CLI still works. |

## What worked, and why

### In-domain training chips

Training on Germany alone gave 0.18 per-installation recall at or above 1,000 m² in Punjab.
Adding 274 Punjabi chips, merged with `scripts/merge_chip_index.py` and oversampled twice so
Germany's larger chip count does not swamp them, took that to 0.55. Nothing else tried has
moved the domain gap comparably, which is the empirical argument for the
[mapping flywheel](how-it-works.md#workflow): more verified Pakistani installations are
worth more than any architectural change tested here.

### A per-building classifier instead of a better segmenter

The decisive finding of this project is that below roughly 400 m² the question has to change.
Segmentation asks "where is the polygon", and at 10 m ground sampling distance a 50 m²
rooftop array does not have one. `roofclf` asks "does this *building* carry PV", which turns
an unresolvable localisation problem into a per-footprint classification problem with a
strong size prior and reflectance features. On the 23 mapped quadrats it reaches **0.857
AUC**, and **0.830** with roof size controlled for, where the segmentation raster scores
close to chance on the same buildings. That gap, not any architectural change to the
segmenter, is why the pipeline now runs two detectors.

### Requiring two detectors to agree

`SPPI` is a zero-training spectral index from the literature. As a standalone capacity
instrument it is unusable (an 18x scale spread across quadrats, 4.7x over-prediction in arid
Quetta), and as an extra column in `roofclf` it does nothing at all (0.8736 to 0.8734 AUC).
What it is good for is **disagreeing**: requiring roofclf and SPPI to agree lifts precision
from 0.496 to 0.540 at matched recall, and the gain concentrates in exactly the low-adoption
places where roofclf alone is known to over-predict. That is why agreement between the two
defines the Verified tier rather than either model on its own.

### The vegetation veto, and why the obvious version fails

Manual review of countryside leads found many green fields flagged as PV. Measuring NDVI on
the composite the model actually read does **not** separate them: 150 suspect leads had a
median NDVI of 0.10 there, statistically indistinguishable from confirmed PV's 0.04. The
field a validator sees as green today was dark fallow, harvested or flooded paddy soil when
the dry-season median was built. This is a season mismatch, not a spectral confusion the
model could have avoided.

The instrument that does discriminate is the annual vegetation cycle: every crop field greens
up at some point in the year and a panel never does. `scripts/veg_annual_ndvi.py` samples a
year of scenes per lead and reports the 95th percentile. A positive control on ten leads the
free version had already flagged found eight crossing 0.3 within the year, confirming the
catches are real vegetation.

## What did not work

### Two-season stacking

A 20-band two-season stack (dry-season base plus a contrast season per cell) was built to
push detection below 1,000 m², on the theory that PV is spectrally stable across seasons
while vegetation and roofs swing. The full path is wired and TerraMind duplicates its
pretrained patch embedding into both season slots.

On the same Punjab validation installations, recall for the 1,000+, 500 to 1,000 and 250 to
500 m² buckets was 0.51, 0.17 and 0.14 seasonal, against 0.55, 0.16 and 0.14 for the
production 10-band model. Small buckets unchanged within noise, large slightly worse. Likely
causes: too few in-domain chips to learn a temporal signal, the tiny backbone's capacity, and
post-monsoon versus dry season simply not differing enough in arid Pakistan. A later
variant using a 2021 pre-boom epoch instead of a contrast season
([boom-window stacking](issues/boom-window-stacking-experiment.md)) was inconclusive rather
than negative: training collapsed on only 332 usable chips, so it did not test the
hypothesis either way.

### Sentinel-1 corner reflection

A tilted PV row over flat ground forms a dihedral corner reflector, which should produce
strong radar backscatter, persistently, since Sentinel-1's orbit geometry is fixed year-round
and radar is not blocked by cloud. Tested on 17 glint-validated installations spanning the
full observed azimuth range, pulling two years of Sentinel-1 RTC.

Median enhancement rate was 3.2% (VV) and 1.7% (VH) of scenes, within plain speckle noise.
Critically, ascending and descending passes gave near-identical rates, 1.7 against 1.8%, with
no correlation to the implied row axis. A real corner reflector should show sharp asymmetry
between orbit headings, and its absence says this is not a usable channel at these sites
through a simple per-footprint aggregate.

A lighter use of Sentinel-1 remains untried and is **not** ruled out by this: multi-temporal
backscatter *variance* separates permanent structures from seasonally changing fields, and
greenhouse metal frames give a bright return, the opposite of PV, making radar a cheap
post-hoc false-positive filter.

### Two glint routes to density, both negative

**Cell-aggregate spike counting.** Small residential arrays are individually sub-pixel and
rarely glint alone, so the hypothesis was that a dense neighbourhood of independently
oriented arrays would union their narrow glint windows into a high combined spike count.
Tested against a fully mapped Lahore cluster with up to 120 separately mapped generators in a
single 300 m block: zero-PV control cells averaged 1.0 spike, PV-bearing cells 1.45, medians
tied at 1.0, and the 120-installation hotspot showed one spike in two years. This is probably
a methodology failure rather than a physics one. A 90th-percentile statistic over a whole cell
only moves if roughly 10% of the cell brightens at once, and even every installation in the
busiest hotspot glinting simultaneously covers under half of that.

**Recovering missed installations.** Find real mapped installations the thresholded mask
misses entirely, glint-validate them, and add their area back. Tested on 43 missed German and
208 missed Lahore installations against matched non-PV controls. Both fail the one thing this
needs to do: Germany's control false-validation rate of 20.8% is uncomfortably close to the
37.2% rate on missed installations, and Lahore's control rate of 8.7% is *higher* than its
5.3% missed rate, which is worse than chance.

### Super-resolution

Three feasibility tests, run in sequence by `scripts/run_sr_experiments.sh`: guided fusion of
the 20 m bands to 10 m, multi-image super-resolution from repeated overpasses, and
internal-learning single-image super-resolution. None improved detection, and the last carries
an obvious hallucination risk on a task whose whole output is "is there a panel here".
Scripts are kept for reference.

### Temporal features for roofclf

Two candidate features were tested against the quadrats and neither was kept. **Epoch jump**,
the change in the same classifier's score between two imagery epochs, measured at 0.8736 to
0.8736 AUC in its probability form (exactly zero effect) and 0.8736 to 0.8608 in its cheaper
reflectance-delta form, with one quadrat failing outright. **Step change**, per-building
aggregation of the pixel-level time-series signal below, did not survive a within-size-band
control. An [older design note](issues/epoch-jump-recall-signal.md) proposed using the epoch
comparison as a recall *rescue* rather than a feature; that specific plumbing was never built,
and the measurement above is the reason it was not pursued.

### Retraining on known failures

Two retrains aimed at documented failure modes, both negative in an instructive way.

The **fraction-head quadrat-supervised retrain** beat the production checkpoint in 13 of 13
quadrats in-sample and collapsed the scale dispersion from 11.95x to 2.48x, which looks
decisive until the held-out quadrat comes back at 0.461 against an in-sample band of 1.878 to
3.684. A paired spatial block bootstrap puts the held-out AUC gain at -0.009 to +0.061,
one-sided p 0.062. One quadrat and 797 labelled pixels is the binding constraint, so more
holdout folds, not more analysis, is what would settle it.

The **roofclf hard-negative retrain** took the one concretely locatable confirmed false
positive on record (six very bright roofs that both detectors flag) and folded them in as
negatives. Six rows against 104,423 moved their own scores by 0.0001 to 0.003 and changed
nothing else. Oversampling them 20x, 100x and 500x does eventually suppress them, but
`median_fold_auc` falls 0.8824 to 0.8811 to 0.8726 to 0.839 on the way, so the model is
learning to distrust one tiny neighbourhood of feature space at the expense of everything
else. No factor tested threads that needle. The fix this actually recommends is mining more
examples of the same bright-roof pattern nationally, for which no roofclf-side mining tool
exists yet.

## The partial result worth watching

### Time-series step detection below the floor

At a median installation area near 50 m², the trained model reads 0.000 probability on 99.8%
of true footprints and glint validates zero of 1,021. Static appearance is exhausted. But
*appearance in time* is a different signal: a panel installed in 2023 is a step change in a
dense per-pixel Sentinel-2 series, even if no single scene shows it.

`scripts/pv_step_signal.py` removes common-mode atmosphere against reference pixels, guards
co-registration by phase correlation, learns the PV installation change vector spectrally
rather than assuming a fixed index, deseasonalises with annual harmonics and per-orbit
offsets, and scans for the best breakpoint per pixel.

**The good part.** Area under the ROC curve of 0.875 and 0.74 on held-out halves, against
0.50 for the model on the same footprints. That is the first non-zero discrimination anyone
here has achieved below 500 m².

**The part that failed.** Converting that into a city-scale unmapped-capacity number was
**rejected by its own control**. The method's estimate of unmapped area per built-up pixel sat
inside the false-area floor measured on two PV-free cropland control cubes, so nothing in its
totals block is quotable as capacity. What survives is the ranking: step-leads are defensible
as a lead ordering.

Two landmines are documented for anyone continuing: a propensity confound (the households
that install panels differ systematically from those that do not, in ways visible from space)
and duplicated Sentinel-2 baseline products that silently double-count dates.

## Deeper write-ups

These pages hold the full tables and derivations behind the rows above. Each one carries a
status banner stating where it now stands relative to the current pipeline, because several of
them were written before the thing they describe was replaced.

| Write-up | Subject |
| --- | --- |
| [Calibration boxes](issues/pakistan-calibration-boxes.md) | The running log of every ground-truth area, how each was mapped and what it changed |
| [roofclf national deployment and temporal features](issues/roofclf-national-deployment-and-temporal-features.md) | The first national scoring run, and the epoch-jump and step-change feature tests |
| [roofclf cell-edge false positives](issues/roofclf-cell-edge-false-positives.md) | Two compounding bugs that made 45.6% of national flags artifacts, and both fixes |
| [Quadrat-supervised fraction retrain](issues/quadrat-supervision-fraction-retrain.md) | The in-sample win, the holdout that did not support it, and the block bootstrap |
| [Fraction-head hard-negative retrain](issues/fraction-head-hard-negative-retrain.md) | A regime-specific win: better on large arrays, worse on dense small rooftops |
| [SPPI spectral index evaluation](issues/sppi-spectral-index-evaluation.md) | What SPPI can and cannot do, and why it is used only as a second opinion |
| [Boom-window stacking](issues/boom-window-stacking-experiment.md) | Why the 2021-versus-current retrain is inconclusive rather than negative |
| [Standard-pose matched filter](issues/standard-pose-matched-filter.md) | Assessed against real pose data and not recommended |
| [Glint spike-rate estimator](issues/glint-spike-rate-density-estimator.md) | Glint as a statistical density estimator, and the floor it hits |
| [Glint tile-batched coverage](issues/glint-tile-batched-coverage.md) | The 22x speedup, and the silent scene-loss bug it uncovered |
| [Glint-validated training labels](issues/glint-validated-training-labels.md) | A proposal to feed corroborated detections back as labels |
| [Quadrats as training data](issues/quadrats-as-training-data.md) | The proposal that became `roofclf` |
| [Calibration imagery dating](issues/calibration-imagery-dating.md) | Why ground-truth completeness is relative to an imagery date, and what closing that costs |
