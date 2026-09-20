# Experiments: what was tried, and what it cost

Most of what has been tried in this project did not ship. That is worth writing down for two
reasons: the negative results are the map of where Sentinel-2's 10 m resolution limit
actually sits, and every one of them cost real compute that nobody else needs to spend
again.

This page is the register. It covers everything that was measured, whether it ended up in
[the pipeline](how-it-works.md) or not. Every experiment has runnable code in the
repository; nothing was deleted on failure. For things that are still genuinely undecided,
see [Open questions](open-questions.md).

#### How to read the verdicts:

- <span class="outcome works">shipped</span> : part of the current main workflow
- <span class="outcome mixed">partial</span> : useful measured signal, but not strong enough to promote
- <span class="outcome negative">rejected</span> : underperformed the alternative or failed its control
- <span class="outcome open">superseded</span>: previously shipped, but since replaced

## The register

| Experiment | Verdict | One line |
| --- | --- | --- |
| In-domain Pakistani training chips | <span class="outcome works">shipped</span> | Tripled large-array recall in Punjab, 0.18 to 0.55. The single biggest lever found. |
| Building prior from VIDA Open Buildings | <span class="outcome works">shipped</span> | Makes "no building nearby" a usable false-positive signal. |
| Quadrats as training data, not just correction | <span class="outcome works">shipped</span> | Became `roofclf`, now half the main workflow. |
| [roofclf, a per-building classifier](methods/roofclf.md) | <span class="outcome works">shipped</span> | 0.879 AUC (0.834 within size band) on 27 quadrats where segmentation scores near chance. |
| SPPI as a corroborating second opinion | <span class="outcome works">shipped</span> | Zero-training spectral index; agreement with roofclf sets an internal floor on the atlas's headline figure. |
| Coverage ratio stratified by size and density | <span class="outcome works">shipped</span> | Replaced precision as the multiplier, and a flat ratio with a measured per-stratum one. |
| Placement-split precision and recall | <span class="outcome works">shipped</span> | Unpooling rooftop from ground-mount moved both, in opposite directions. |
| [End-to-end validation against a complete register](methods/mastr-validation.md) | <span class="outcome works">shipped</span> | Germany ran nationally at last: 99.75% of MaStR capacity covered, and segmentation recovers about a third of what it can see. |
| [p_unmapped from a geolocated register](methods/mastr-validation.md) | <span class="outcome works">shipped</span> | Replaced Germany's `p_unmapped: 0.0` floor with chance-corrected register evidence, split by placement. |
| [Recall measured against any candidate, not the same placement](methods/mastr-validation.md) | <span class="outcome works">shipped</span> | Rooftop recall was understated up to 24x because a big array overruns its footprint and the finder gets labelled ground. |
| [The module constant, measured against a register](methods/france-validation.md) | <span class="outcome works">shipped</span> | France put `DEFAULT_KWP_PER_M2_MODULE` at 0.150 kWp/m<sup>2</sup> against the assumed 0.180. Germany could not do this at all. |
| [Reading a register back to the imagery epoch](methods/france-validation.md) | <span class="outcome works">shipped</span> | Dated ODRE vintages remove a 53% inflation that comes purely from PV installed after the flight. |
| [Localizing the detector by retraining on France](#localizing-the-detector-what-french-chips-bought-2026-09-12) | <span class="outcome works">shipped</span> | Rank correlation against the register 0.29 to 0.45, closing half the gap to Germany. Slope barely moved. |
| [The 400 m<sup>2</sup> floor, measured from outside](#the-detection-floor-measured-against-sub-metre-truth-2026-09-12) | <span class="outcome works">shipped</span> | Recall climbs with size (rho +0.83) while the sub-metre control stays flat (-0.29). Retraining on French data does not move it. |
| [roofclf on French residential PV](results/france.md#earthpv-against-france-the-sub-400-m2-instrument-does-not-transfer) | <span class="outcome negative">rejected</span> | 0.627 AUC within size band against Pakistan's ~0.834. A 20 m<sup>2</sup> array is a fifth of a Sentinel-2 pixel. |
| [13x the roofclf labels, from OpenPVMapper](results/france.md#was-it-just-too-few-labels-no) | <span class="outcome negative">rejected</span> | 16,435 positives against 1,231 moves AUC by -0.005. The model scores 0.683 even on its own label source. |
| [Authoritative footprints instead of VIDA](#authoritative-footprints-the-french-cadastre-against-vida-2026-09-12) | <span class="outcome mixed">partial</span> | VIDA misses 58% of French buildings. Fixing that is worth +0.027 AUC, which is 14% of the gap to Pakistan. |
| [roofclf transfer to Germany](results/germany.md#does-roofclf-transfer-to-germany) | <span class="outcome mixed">partial</span> | A foreign model transfers (0.70-0.72) and it barely matters which country; in-domain German training is worth +0.08. |
| [The sub-400 m<sup>2</sup> estimator against a complete register](results/germany.md#the-sub-400-m2-estimator-against-the-register) | <span class="outcome mixed">partial</span> | Beaten by total roof area in Germany (23% vs 58% error), beats it 3.4x in Pakistan. Regime-specific, and a perfect national total hid 47% per-municipality error. |
| [A register-calibrated German roofclf half](results/germany.md#a-calibrated-german-estimate-and-why-it-is-not-in-the-atlas) | <span class="outcome mixed">partial</span> | 52.37 GWp against a registered 54.29, but still behind a roof-area baseline (48.4% vs 37.8% error), so it is reported beside the atlas rather than inside it. |
| [Register coordinates as roofclf labels](results/germany.md#register-labels-a-better-classifier-that-makes-a-worse-estimate) | <span class="outcome negative">rejected</span> | +0.023 building AUC, 15.5 points WORSE municipal error: the geolocated band is 6.9 of 49.0 GWp, so the estimand and the labels disagree. |
| [Register counts as a known class prior](results/germany.md#calibrating-germany-without-a-mapped-quadrat-the-whole-picture) | <span class="outcome mixed">partial</span> | Fixes the label problem (33.4% against 70.6%) but ties the roof-area baseline on representative municipalities. The 18.2% first result was a PV-dense sample. |
| [Size-stratified adoption intensity](results/germany.md#the-estimator-that-finally-beats-the-baseline-and-what-rid-corrected-about-it) | <span class="outcome works">shipped</span> | First estimator to beat the German roof-area baseline: 35.4% against 37.8%, using the 200-400 m<sup>2</sup> band and no classifier. |
| [Size-dependent OSM rooftop conversion](results/germany.md#reconciling-in-grid-osm-the-overstatement-was-rooftop-not-ground) | <span class="outcome works">shipped</span> | Ground reconciled at 0.91; rooftop was 2.5x over because large polygons are roof outlines (0.051 kWp/m<sup>2</sup>) not arrays (0.200). Germany Verified 38,508 -> 25,921 MWp. |
| [RID as a control on the size relationship](results/germany.md#the-estimator-that-finally-beats-the-baseline-and-what-rid-corrected-about-it) | <span class="outcome mixed">partial</span> | Exhaustive labels confirm the band but refute the mechanism, and price OSM's size bias at +0.729 against a true +0.349. |
| [OpenPVMapper as an external reference](results/france.md) | <span class="outcome mixed">partial</span> | 91% of the register's sub-72 kWp capacity, but 0.67 recall against hand-mapped truth and a model output throughout. |
| [SPPI alone as Germany's sub-400 estimator](#sppi-alone-as-germanys-sub-400-estimator-2026-09-18) | <span class="outcome negative">rejected</span> | Orders German roofs better than the trained classifier does (33.7% against 36.8% municipal error) and still loses to crediting roof area with no classifier at all (31.2%). |
| Dividing register p_unmapped by an OSM positive control | <span class="outcome negative">rejected</span> | The control is contaminated by the same sub-30 kWp coordinate suppression it was meant to absorb. |
| OSM geometry dissolve and closest-match dedup | <span class="outcome works">shipped</span> | Nested `plant`/`generator` ways were double-counting real installations. |
| Recall correction and credible intervals | <span class="outcome works">shipped</span> | Turned a structural floor into an estimate with a stated interval. |
| Recall correction for roofclf, not just segmentation | <span class="outcome works">shipped</span> | The roofclf half was counting only the roofs it flagged; correcting it moved Best 16.6 to 18.3 GWp. |
| Quadrat-bootstrap uncertainty on the atlas | <span class="outcome works">shipped</span> | The headline figure now carries a 90% range. |
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
| [Snow-cover contrast for small rooftop PV](#snow-cover-contrast-and-the-one-commune-that-nearly-sold-it-2026-09-08) | <span class="outcome negative">rejected</span> | Sound physics, wrong calendar: 0.096 usable scenes per commune-winter outside the Alps. |
| Cell-aggregate glint density | <span class="outcome negative">rejected</span> | Wrong statistic for the question. |
| Missed-installation glint recovery | <span class="outcome negative">rejected</span> | Control false-validation rate exceeded the recovery rate. |
| Roof-axis orientation prior | <span class="outcome negative">rejected</span> | Flat concrete roofs do not constrain a tilt frame's azimuth. |
| Standard-pose matched filter | <span class="outcome negative">rejected</span> | The densest pose bin covers under 10% of installations. |
| [Glint PSF matched filter](issues/glint-psf-matched-filter.md) | <span class="outcome negative">rejected</span> | The PSF is real and measured, but every filter variant scores below the aperture statistic it would replace. |
| [Verified-negative false-spike rate](issues/glint-psf-matched-filter.md) | <span class="outcome works">shipped</span> | 2.0% against 8.7-20.3% on model-negative controls, which reopens the spike-rate density estimator. |
| Super-resolution, three variants | <span class="outcome negative">rejected</span> | No gain, and hallucination risk on a detection task. |
| Two-endmember spectral unmixing | <span class="outcome negative">rejected</span> | 0.659 AUC, worse than both SPPI and roofclf, with a 92x scale spread. |
| Epoch jump / step change as roofclf features | <span class="outcome negative">rejected</span> | Measured at exactly zero effect, and worse in the reflectance variant. |
| [Keeping more than the median composite](#keeping-more-than-the-median-composite-2026-09-19) | <span class="outcome negative">rejected</span> | Per-pixel p10/p90/std off the same scenes the median already downloads: +0.0003 AUC, 16 of 30 folds, sign test p=0.57. |
| [Bilinear resampling of the native-20 m bands](#the-20-m-bands-and-what-sharpening-them-costs-2026-09-19) | <span class="outcome works">shipped</span> | The model's biggest coefficients sit on bands replicated nearest-neighbour from 20 m. De-blocking them: +0.0041 AUC within size band, 20 of 30 folds, p=0.061. |
| [Regression sharpening of the 20 m bands](#the-20-m-bands-and-what-sharpening-them-costs-2026-09-19) | <span class="outcome negative">rejected</span> | Predicting SWIR from the visible bands costs 0.0047 AUC, 7 of 30 folds, p=0.008. The SWIR signal is not synthesisable. |
| [Footprint-constrained spatial unmixing](#unmixing-the-pixel-against-a-known-footprint-2026-09-19) | <span class="outcome negative">rejected</span> | Cuts reflectance error 67% on synthetic sub-pixel buildings and loses 0.0323 AUC within size band on real ones, 2 of 30 folds, p=0.000. |
| [Top-of-atmosphere instead of Sen2Cor](#l1c-against-l2a-the-correction-is-not-the-problem-2026-09-19) | <span class="outcome negative">rejected</span> | An exact coin flip, 15 of 30 folds, p=1.00, at triple the fold-to-fold spread. |
| [Temporal unmixing](#temporal-unmixing-the-dry-season-window-removes-its-own-signal-2026-09-19) | <span class="outcome negative">rejected</span> | PV pixels vary as much as PV-free roofs (ratio 1.02), so there is no damping to measure. The gain tracks background dynamism as predicted, at 0.0015 AUC. |
| [Gradient boosting instead of the linear model](#the-model-class-ranking-and-calibration-disagree-2026-09-19) | <span class="outcome mixed">partial</span> | Ranks WORSE (-0.023 within size band, 4 of 30 folds) and calibrates BETTER (per-quadrat rate error 0.031 to 0.017, 20 of 29 quadrats). |
| [Footprint shape as model features](#the-model-class-ranking-and-calibration-disagree-2026-09-19) | <span class="outcome negative">rejected</span> | -0.0001 AUC, 14 of 30 folds, p=1.00. The 0.8593 that made it look best was a difference of medians. |
| [Area-weighted training loss](#aiming-at-the-aggregate-weighting-and-recalibration-2026-09-19) | <span class="outcome negative">rejected</span> | Improves the area ratio it optimises (1.084 to 1.035) and loses on both ranking (-0.0111 AUC) and count calibration (0.0308 to 0.0395). |
| [Post-hoc recalibration of roofclf](#aiming-at-the-aggregate-weighting-and-recalibration-2026-09-19) | <span class="outcome negative">rejected</span> | Recovers 38% of gradient boosting's calibration gain at p=0.069. No monotone map reaches it, so that gain is a reordering. |
| [Medoid instead of band-wise median compositing](#spectral-coherence-and-where-transferability-lives-2026-09-19) | <span class="outcome negative">rejected</span> | A real artifact, but one date's spectrum loses more to noise than it gains in coherence: -0.0074 AUC. |
| [Context-relative spectral features](#spectral-coherence-and-where-transferability-lives-2026-09-19) | <span class="outcome mixed">partial</span> | Within-cell z-scores alone TIE the shipped model's ranking while doubling its rate error: ranking is relative, calibration is absolute. |
| [Local-contrast brightness (`plus_local_contrast`)](#spectral-coherence-and-where-transferability-lives-2026-09-19) | <span class="outcome negative">rejected</span> | Unmeasurable since 2026-08-09 through a NaN bug; fixed and measured at +0.0000 AUC, 13 of 30 folds. |
| [Cell-level brightness as a feature](#the-level-half-of-brightness-does-not-transfer-2026-09-20) | <span class="outcome negative">rejected</span> | Predicted to help calibration; makes it significantly WORSE, closer in 7 of 29 quadrats, p=0.008. |
| [Snow-covered roofs in Germany](#snow-in-germany-the-opportunity-is-real-the-contrast-is-not-concludable-2026-09-20) | <span class="outcome mixed">partial</span> | Answers France's opportunity objection at a 10.3% scene rate; the contrast itself is 6 scenes, bimodal, p=0.39. |
| [The composite reducer: mean, not median](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20) | <span class="outcome works">shipped-pending</span> | +0.0286 AUC within size band, 25 of 30 folds, p=0.0001. Larger than every feature block in this register combined. |
| [Multi-frame super-resolution](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20) | <span class="outcome negative">rejected</span> | Sub-pixel diversity is 1.3 m, a quarter of what fusion needs; applying the shifts is WORSE than not. |
| [SEN2SR single-image super-resolution](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20) | <span class="outcome negative">rejected</span> | -0.0367 AUC within size band, 6 of 30 folds. Invented texture dilutes real contrast. |
| [GlobalBuildingAtlas building height](#the-composite-reducer-is-the-biggest-lever-in-this-register-2026-09-20) | <span class="outcome negative">rejected</span> | d'=+0.651 alone and +0.0006 on top of the model: height is a proxy for footprint area. |
| [The spectral SNR budget](#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19) | <span class="outcome works">shipped</span> | Measured, not argued: the noise is roof heterogeneity at 20-40x the sensor's, and the linear spectral limit is already reached. |
| [Local background conditioning](#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19) | <span class="outcome negative">rejected</span> | Cuts noise 23-43% and signal faster, at every scale from 31 m to 369 m, because PV adoption is spatially clustered. |
| [Glint geometry as a scene-level SNR lever](#sun-geometry-neither-glint-nor-high-sun-raises-the-contrast-2026-09-19) | <span class="outcome negative">rejected</span> | The apparent gain is solar elevation: partialling it out leaves +0.025 (p=0.70). |
| [Compositing in a high-sun window](#sun-geometry-neither-glint-nor-high-sun-raises-the-contrast-2026-09-19) | <span class="outcome negative">rejected</span> | Roofs are 21% brighter pre-monsoon and the contrast is unchanged (0.98x): d-prime is illumination-invariant. |
| [Yard features for small ground-mount](issues/small-ground-mount-instrument.md) | <span class="outcome mixed">partial</span> | The building index brackets 98.5% of the population, but detection lands at 1-2% precision. |
| [Yard-SPPI and roofclf AND-gate for ground-mount](issues/small-ground-mount-instrument.md#making-sppi-and-roofclf-agree-does-not-rescue-it-either) | <span class="outcome negative">rejected</span> | The rooftop floor's construction does not transfer: 2% precision, and the best operating point turns the roofclf side off. |
| [Parcel label for roofclf](methods/roofclf.md#the-parcel-label-parcel-label-2026-08-16) | <span class="outcome works">shipped</span> | Counting PV in the yard, not just on the roof. 80% of what it recovers turns out to be rooftop PV overhanging an undersized footprint, not ground-mount. |
| Yard feature block in the roofclf model | <span class="outcome negative">rejected</span> | Loses to roof-only features even against the parcel label it was built for: 0.8712 against 0.8734. |
| SPPI as a roofclf input feature | <span class="outcome negative">rejected</span> | 0.8736 to 0.8734 AUC. It helps by disagreeing, not by being a column. |
| Glint-date imagery as a roofclf feature | <span class="outcome negative">rejected</span> | Only 7-24% of rooftops can ever glint into a near-nadir view; size-controlled AUC moves 0.7875 to 0.7879. |
| Opportunity-normalised glint sensitivity | <span class="outcome works">shipped</span> | Sensitivity varies ~2x with opportunity inside a size bin; now modelled per target instead of pooled. |
| Glint-mined roofclf hard negatives | <span class="outcome negative">rejected</span> | 126 negatives at 1.2% contamination moved held-out AUC by 0.0003. Quantity, not quality, is the binding constraint. |
| OSM as a complete reference in Germany | <span class="outcome negative">rejected</span> | 3.6% complete by unit count; implied kWp/m² unstable by more than the constant itself. |
| External corroboration: nightlights and a wealth index | <span class="outcome mixed">partial</span> | VIIRS nightlights and Meta's Relative Wealth Index correlate with published capacity (r=0.76, r=0.66), but partial correlation shows most of that tracks the same building-density confound (0.54, 0.35). Kept as a plausibility citation, not promoted to a stratification input. |
| Unrestricted national roofclf capacity | <span class="outcome open">superseded</span> | 18 to 37 GWp, rejected as miscalibrated; replaced by the domain-restricted estimate. |
| Low/Central/High/All-PV bracket atlas | <span class="outcome open">superseded</span> | Replaced by the two-tier evidence atlas, which sorts by standard of proof instead. |
| Out-of-domain AND-gate extrapolation | <span class="outcome open">superseded</span> | Published 2026-08-11 to 2026-08-15, then dropped: the one Best-estimate component not measured where it was applied, and unreviewable by eye under stale imagery. -62 MWp. |
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
strong size prior and reflectance features. On the 27 mapped quadrats it reaches **0.879
AUC**, and **0.834** with roof size controlled for, where the segmentation raster scores
close to chance on the same buildings. That gap, not any architectural change to the
segmenter, is why the pipeline now runs two detectors.

### Requiring two detectors to agree

`SPPI` is a zero-training spectral index from the literature. As a standalone capacity
instrument it is unusable (an 18x scale spread across quadrats, 4.7x over-prediction in arid
Quetta), and as an extra column in `roofclf` it does nothing at all (0.8736 to 0.8734 AUC).
What it is good for is **disagreeing**: requiring roofclf and SPPI to agree lifts precision
from 0.496 to 0.540 at matched recall, and the gain concentrates in exactly the low-adoption
places where roofclf alone is known to over-predict. That is why agreement between the two
sets the internal floor under the evidence atlas's headline figure, rather than either
model on its own.

### One estimator, applied to both halves

The segmentation half already corrects for missed installations: each detection represents 1/recall real installations within its size class. The roofclf half did not. Its coverage ratio was measured only over flagged roofs, effectively assigning zero capacity to PV on missed roofs, even though roofclf contributed roughly four-fifths of the published estimate.

Using the existing labels from 16 trusted quadrats, area recall was estimated as the share of mapped PV area on buildings flagged by roofclf, by roof-size bin and building-density stratum. It is 0.808 below 400 m² and 0.978 at or above 400 m², rising from 0.34 for the smallest PV-carrying roofs to 0.99 for the largest. Area recall is used because missing a 300 m² array matters far more to capacity than missing a 20 m² one.

The correction raised the two roofclf components from 6,372 to 7,890 MWp and from 7,031 to 7,189 MWp, increasing the published Best estimate from 16,609 to 18,280 MWp. The internal floor was left unchanged because it is defined by agreement between two independent detectors and should not extrapolate to installations neither observed.

Coverage ratio and recall are refit within the same bootstrap replicates because they share the same quadrats and labels. The correction also remains conservative, chiefly because mapping completeness is certified only for the imagery epoch, so some recent installations on unflagged roofs can still be missed.

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

### External corroboration from nightlights and a wealth index

Two proxies that had never appeared anywhere in this codebase before -- VIIRS nighttime-lights
radiance and Meta's Relative Wealth Index -- were correlated against the published atlas's
per-cell Best estimate to ask a narrower question than validation: does detected PV track the
same "built-up, electrified, and (for RWI) relatively wealthy" signal an independent,
non-imagery-derived dataset would predict. Neither proxy sees solar panels; agreement is
evidence the estimate is *plausible*, not evidence it is *correct*, and it is cited that way in
[Validity and limitations](methods/validity.md#evidence-that-the-signal-is-physical), not used
as a calibration input.

`scripts/build_pv_external_comparison.py` computes `log(1+radiance)` vs. `log(1+MWp)` and,
separately, RWI vs. `log(1+MWp)`, per 0.1&deg; cell, plus the same correlation after partialling
out each cell's building footprint area (`roof_area_m2`) -- the obvious shared confound, since a
bigger built-up cell is both brighter and has more roof to put PV on. It had run once,
2026-08-12, and was never registered here. Rerun 2026-08-26 against the current 18,826.7 MWp
atlas (14% higher than the 16,441.4 MWp the first run saw): nightlights correlate at
**Pearson 0.761** raw, dropping to **0.545** once roof area is controlled for (n=4,463 cells);
the wealth index at **0.661** raw, dropping to **0.345** (4,428 of 4,463 cells have RWI
coverage). Both partial correlations barely moved between the two runs (0.548 to 0.545 for
nightlights, 0.373 to 0.345 for RWI) despite the 14% shift in the headline total, so the
relationship looks like a property of the estimate's geography rather than an artifact of one
particular refit.

The honest reading is that both proxies carry *some* information about PV placement beyond
"this cell has more buildings" -- the partial correlations are positive and well clear of zero
-- but a majority share of the raw correlation is exactly that confound, not new information.
That is consistent with [Capacity density](methods/density.md)'s own three failed attempts at
finding any coarse per-cell proxy (candidate density, roofclf's predicted rate, SPPI agreement
rate) for which quadrat-regime a cell resembles: neither nightlights nor RWI has been tried in
that specific role, and this result is why they are not expected to do much better than the
three proxies that already failed there (see [Open questions](open-questions.md), item 15).
The same script also recomputes the reference-hex comparison already published on
[the capacity map](results/capacity.md#what-this-map-cannot-tell-you-and-what-an-independent-estimate-confirms-it-can)
via the same grid match, as an internal consistency check rather than a second citation of it.

### A legally-complete register as a precision instrument (2026-09-01)

Germany's own accuracy check had a hole in it: with no instrument for `p_unmapped`, its
calibration table shipped `0.0`, pricing every un-mapped candidate at zero and holding
`est_mwp_cal` to an OLS slope of 0.038 against the register.

MaStR closes it over part of the range. Coordinates are published only at or above 30 kWp
&mdash; zero of the 4.17 million units below that carry one, a privacy policy rather than
missing data, while the fill rate is 99.7% above the 72 kWp / 400 m&sup2; segmentation
floor. So a registered installation's address point falling inside an unmapped candidate is
direct evidence that the candidate is real, for exactly the population segmentation
targets. Measured per placement, the term runs from 0.061 to 0.688 for rooftop and 0.000 to
0.246 for ground, chance-corrected against the same polygons displaced 500-1,000 m.

Two things generalise beyond Germany. The register is **silent below 30 kWp**, which is the
`roofclf` domain, so this improves the instrument that was already working and does nothing
for the one that needed help most &mdash; a register does not remove the need for mapped
quadrats. And the natural refinement, dividing by an OSM-mapped positive control the way
the glint inversion does, **fails here**: German OSM rooftop PV is the 3.6%-complete
enthusiast-mapped tail, which skews below 30 kWp and so carries no coordinates, making the
control contaminated by the very suppression it was meant to absorb. Full derivation and
the rejected control:
[Validating against a complete register](methods/mastr-validation.md).

### The recall denominator, found by fixing something else (2026-09-02)

Correcting Germany's `p_unmapped` moved `est_mwp_cal` the right way and pushed
`est_mwp_rc_roof` from 0.262 to 3.11 against the register &mdash; from understating truth
to overstating it threefold. Two errors had been cancelling, and removing one exposed the
other.

The cause was not either hypothesis first written down. It was that
`derive_placement_tables` restricted **both** sides of the recall measurement by placement:
a rooftop reference installation only counted as found if the finding candidate was itself
classified `rooftop`. Precision and recall are asymmetric here. `mapped_frac` asks "is this
candidate real", so its corroboration must come from references of its own placement.
Recall asks "was this real installation detected at all", and how `postprocess` labelled
the candidate that found it is irrelevant.

Measured on Germany, rooftop recall against same-placement candidates versus against any
candidate:

| Bin | same placement | any candidate | factor |
|---|---|---|---|
| 500-1k m&sup2; | 0.128 | 0.167 | 1.3x |
| 1k-5k | 0.214 | 0.268 | 1.25x |
| 5k-50k | 0.096 | 0.693 | 7.3x |
| &gt;50k | 0.036 | 0.852 | 23.9x |

The mechanism explains why the error grew with size: a large array overruns its
imagery-derived VIDA footprint, `building_overlap_frac` collapses, and the candidate that
correctly found a rooftop installation is classified `ground_adjacent` or `no_building` &mdash;
the same footprint undersizing the parcel label exists to handle. `1/recall` then inflated
those candidates by up to the 20x clamp.

**Pakistan is affected too**, which only a complete register could have revealed: rooftop
recall there moves 0.423 to 0.808 in the 5k-50k bin and 0.065 to 0.952 above 50k, and
ground 0.107 to 0.417 in 500-1k. Its published figures come from the checked-in calibration
table and do not move until that is deliberately re-derived, which needs the glint sample
and calibration boxes. Direction: Pakistan's `est_mwp_rc` is **overstated**.

Two hypotheses were written down first and both were measured and **refuted**: that
oversize `rooftop` reference features deflated the top bin (they recall at 0.841, no
different from the rest), and that count-recall applied to area inflated the estimator
(the area/count ratio is 1.01 to 1.08, negligible). Recorded because the wrong diagnosis
was the plausible one.

### A second register, and what it could measure that the first could not (2026-09-04)

Germany's register settled the question above the 400 m<sup>2</sup> floor and was
structurally silent below it: MaStR publishes no coordinates under 30 kWp, which is
`roofclf`'s entire domain. France's register is censored in the same direction, below
36 kW, but two features of it reach where Germany could not.

**It publishes dated year-end vintages.** Because a small installation cannot be dated
individually inside an aggregate row, the current snapshot cannot be filtered to a past
epoch, but a past snapshot can simply be downloaded. Interpolating per-commune small-PV
capacity between straddling year-ends puts the reference on the same day as the imagery a
label was drawn against. That correction is worth 53%: the same fourteen communes read
0.230 kWp/m<sup>2</sup> against today's register and 0.150 against the register as it stood
when the aerial imagery was flown. The difference is entirely PV France installed in
between, and any comparison that skips the step measures growth and reports it as physics.

**Fourteen communes were swept exhaustively by hand**, on sub-metre imagery, with
solar-thermal collectors tagged separately from PV. That makes the register's small-unit
aggregate and the mapped sub-200 m<sup>2</sup> polygons the same population, and dividing
one by the other measures `DEFAULT_KWP_PER_M2_MODULE` externally for the first time. It
comes out at **0.150 kWp/m<sup>2</sup> against the 0.180 the project assumes**, ratio 0.83,
stable at 0.147 under the widest reasonable definition of what counts as PV. The
[German attempt at the same measurement](methods/mastr-validation.md) failed and was
recorded as a negative result: 3.6% OSM completeness and an implied constant spanning
0.02 to 0.99 on mapper convention.

Two findings fell out of it that were not the point of the exercise.

**The below-floor share is not transferable, now measured twice rather than argued once.**
Germany's page inferred that from dispersion across municipalities. France settles it:
17.3% of all registered French PV capacity sits below 72 kWp, 31.1% of low-voltage-connected
capacity, against Germany's 65.5% of rooftop. France's fleet is far more ground-mount-heavy,
so the practical cost of the floor is genuinely smaller there. Two complete registers differ
by a factor of two to four on the quantity this project once transferred as a constant.

**Solar thermal is a systematic confusion for imagery-based detection, and it is invisible
without the tag.** 381 of 3,335 mapped features are hot-water collectors: black glazed
rectangles on south-facing roofs producing no electricity. 137 OpenPVMapper polygons in
these communes sit on one. Any validation whose ground truth does not separate them books
that as a detection error or, worse, as capacity.

France also cannot do one thing Germany can. Its register carries **no coordinates at any
size**, so the `p_unmapped` precision instrument has no French counterpart, and **no
rooftop/ground attribute**, so every share is bracketed rather than stated.

### Where the sub-400 m2 instrument stops working (2026-09-04)

`roofclf` is the half of this project that has no external check, so France was the place to
get one. It did not survive it.

Fitted on 13 exhaustively hand-mapped French communes (44,314 buildings, 1,231 with PV,
leave-one-quadrat-out, parcel label), it reaches **median fold AUC 0.710 and 0.627 within
size band**, against Pakistan's 0.857 and roughly 0.834. Building footprint size alone gets
0.673, so **spectral reflectance is worth about 0.037 AUC** here. At a threshold tuned for
50% precision it flags 16 buildings out of 44,314. Segmentation scores **exactly 0.500 in
all 13 folds**.

The cause is not the model. The median mapped French installation is **20 m<sup>2</sup>**
against a **100 m<sup>2</sup>** Sentinel-2 pixel, so the array is a fifth of a mixed pixel
that is mostly roof tile. The control that isolates this is OpenPVMapper, which recalls the
same installations at 0.67 from sub-metre aerial imagery with no size gradient across
0 to 400 m<sup>2</sup>: the annotations are findable, the sensor cannot find them.

**This bounds `roofclf` rather than refuting it.** Pakistani quadrats contain installations
that are small relative to the 400 m<sup>2</sup> segmentation floor but still large relative
to a 10 m pixel. French residential PV sits below even that, and the instrument degrades to
little more than a size prior there. The practical consequence for the published Pakistani
atlas is a caution, not a correction: the sparse-density stratum, already the least
well-supported part of the coverage-ratio fit, is the one nearest this regime.

It also answers, negatively, the "independent test of the 400 m<sup>2</sup> floor" that
[open question 4](open-questions.md) asked for. The floor is real, it is a sensor limit, and
below roughly a pixel of module area there is no Sentinel-2 instrument here at all.

### Localizing the detector: what French chips bought (2026-09-12)

France was the first country this project inferred **zero-shot** -- the v4 checkpoint was
trained on Germany, Pakistan, Punjab and Gujarat and had never seen a French roof -- and the
first where a complete register could score that decision both before and after retraining.
Same 20,501 communes, same 93.0% capacity coverage, so the two runs are directly comparable.

| estimator | zero-shot slope | retrained slope | zero-shot &rho; | retrained &rho; | Germany slope | Germany &rho; |
| --- | --- | --- | --- | --- | --- | --- |
| `est_mwp_det` | 0.127 | **0.160** | 0.262 | **0.446** | 0.340 | 0.661 |
| `est_mwp_exp` | 0.162 | **0.170** | 0.290 | **0.449** | 0.388 | 0.656 |

**The gain is in placement, not magnitude.** Spearman rose 55% and closed about half the gap
to in-domain Germany; slope moved 5 to 25% and total recovered capacity went from 26% to 34%
of registered above-floor low-voltage capacity. Spearman is scale-free, so unlike slope it
cannot be explained away by conversion constants or by France's proxy denominator (the
register has no rooftop/ground field, so "above floor, low voltage" still contains
BT-connected ground-mount). The zero-shot model was putting capacity in the wrong communes;
the retrained one largely is not.

**What changed underneath is more interesting than the totals.** The candidate population did
not simply grow, it changed shape: 13,419 candidates became 39,462, the median candidate
shrank from 8,301 to 1,400 m<sup>2</sup>, rooftop share doubled from 26.9% to 50.3%, blobs at
or above 10,000 m<sup>2</sup> fell from 6,036 to 2,076, and **total detected area went down**,
364 to 255 km<sup>2</sup>. `polygonize_chips` merges touching thresholded pixels with no upper
bound, so a sheet of weak false positives becomes one multi-hectare "installation"; a
zero-shot model tuned on Pakistani and German industrial roofs produced exactly that over
France. Three times as many objects, six times smaller, with a third less total area, is the
signature of a detector matched to a fleet of small rooftop arrays.

A prediction recorded before the baseline ran was half right and worth keeping as calibration
on this kind of forecast: the slope band (0.15 to 0.35) was about right for the uncalibrated
estimators but anchored on the wrong comparator, and the rank-correlation collapse -- flagged
in advance as "the more interesting failure" -- was the thing that actually happened, at 0.29
against Germany's 0.66.

**The caveat, stated because it limits the claim.** France is **73.6%** of the retrained
corpus (18,577 chips against 6,661 from every other region combined), so this result confounds
"French data is present" with "the corpus is 3.8x larger". A France-capped run of about 3,200
chips, matching Germany's share, would separate them and has not been run. The checkpoint
(`v5_combined_france`, epoch 25, early-stopped at 33) is applied to **France only**; Pakistan
and Germany keep v4 and their published figures are unaffected.


### The detection floor, measured against sub-metre truth (2026-09-12)

The 400 m&sup2; floor was always an argument from the sensor, four Sentinel-2 pixels, checked
against quadrats labelled off the same class of imagery. The fourteen French communes are
swept on sub-metre IGN orthophotos, so for the first time a missed installation is provably a
miss rather than an annotation gap. `mapped_vs_earthpv` measures recall per size bin against
them.

Recall climbs monotonically with installation size, Spearman **+0.83 (p = 0.042)**, from
0.000 below 20 m&sup2; to 0.095 in the 200 to 400 m&sup2; bin. **OpenPVMapper, reading the
same installations inside the same boundaries from sub-metre imagery, is flat: -0.29
(p = 0.58)**, recalling 0.58 to 0.80 in every bin. That contrast is the whole point of the
measurement. A gradient present in a 10 m detector and absent in a sub-metre one, against
identical truth, is the sensor rather than the mapper.

**The finding survives retraining, across three models.** v4 zero-shot (no French chips),
v6 (3,201) and v5 (17,059) return pooled count recall of 0.0118, 0.0103 and 0.0118, with
gradients of +0.89, +0.89 and +0.83, even though v5 tripled the national candidate count and
cut median candidate area from 8,301 to 1,400 m&sup2;. In these communes only 28 candidates
appear at all, and the median distance from a 400 m&sup2;-plus mapped installation to the
nearest one is 807 m.

This corroborates [roofclf's French result](#where-the-sub-400-m2-instrument-stops-working-2026-09-04)
from the segmentation side, by a fully independent route: the classifier found no signal in
the pixels, and the segmenter finds no polygons in the same places.

**What it does not settle.** The 400 m&sup2;-plus bin holds 44 installations, recall 0.045
with a 95% Wilson interval of 0.013 to 0.151, far too thin to claim earthpv fails above its
own floor. These communes were chosen to be exhaustively mappable, not to hold large arrays.
The transferable result is the gradient against the control, not the level in any one bin,
and it bounds the sensor rather than the method: Pakistani arrays are small against the
400 m&sup2; floor but still large against a 100 m&sup2; pixel.

### Authoritative footprints: the French cadastre against VIDA (2026-09-12)

`roofclf` reads VIDA Open Buildings, which is imagery-derived. That is the right choice where
no authoritative footprint layer exists, which is the case across most of the project's
target geography, but it is not free. Measured over the fourteen hand-mapped French communes
against the DGFiP cadastre published through Etalab:

| | Buildings | PV-bearing | Median footprint | AUC | Within size band |
| --- | --- | --- | --- | --- | --- |
| VIDA | 44,314 | 1,231 | 163 m&sup2; | 0.7103 | 0.6274 |
| Cadastre | 103,697 | 1,759 | 53 m&sup2; | 0.7369 | 0.6548 |

**VIDA finds 43% of the buildings and 70% of the PV-bearing ones.** In Toussieu specifically
it returns 672 footprints where the cadastre returns 3,366, with a median of 146 m&sup2;
against 22 m&sup2;, and 1.9x less total built area. Bad footprints degrade three things at
once: the roof-area feature, which is the single strongest predictor; the zonal spectral
means, which get averaged over the wrong pixels; and the label itself, which is mapped PV
intersected with the footprint.

Fixing all three is worth **+0.027 AUC within size band**, closing 14% of the gap to
Pakistan's 0.821. Real, worth adopting for future French work, and not remotely enough to
make the instrument deployable. The other 86% is
[the sensor](#the-detection-floor-measured-against-sub-metre-truth-2026-09-12).

**Two operational findings came out of this.** Overture carries essentially the same French
footprints (3,826 in the Toussieu bbox against the cadastre's 3,366 inside the boundary) but
costs a global S3 scan at roughly 166 seconds per commune against the cadastre's two, and
Overture prunes its release directory to the last two releases, so `configs/aoi.yaml`'s pinned
`2026-06-17.0` no longer exists and fails as "No files found", which reads like an empty area
rather than an expired release. The cadastre is published per commune keyed by INSEE, which is
already the unit the French quadrats use.

`building_table` gained an optional `buildings` override for this; the default keeps the VIDA
fetch, so no existing caller changed.

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

#### 1. Cell-level spike counting

The idea was that a dense neighbourhood of sub-pixel residential arrays might produce more cell-level glint spikes, even when individual arrays rarely glint strongly enough to detect alone. This was tested on a fully mapped Lahore cluster with up to 120 installations within a 300 m block.

- Zero-PV controls: **1.0** mean spike
- PV-bearing cells: **1.45** mean spikes
- Median for both: **1.0**
- The 120-installation hotspot produced only one spike in two years

The signal was too weak to distinguish PV-rich cells reliably. This likely reflects the statistic rather than the underlying glint physics, since a 90th-percentile cell measure only responds when a large fraction of the cell brightens at once.

#### 2. Recovering missed installations

A second approach tested whether glint could validate real PV installations missed entirely by the segmentation mask, allowing their area to be added back. It was evaluated on 43 missed German installations and 208 missed Lahore installations, each compared with matched non-PV controls.

- **Germany:** 37.2% validation on missed PV vs 20.8% on controls
- **Lahore:** 5.3% validation on missed PV vs 8.7% on controls

The separation is not strong enough for reliable recovery. In Germany, the control false-validation rate remains high, while in Lahore the control rate is actually higher than the missed-PV rate, indicating no useful discriminative signal.

### A measured glint PSF, and the control set that mattered more (2026-08-17)

The astronomical version of the sub-pixel problem: measure the instrument's point-spread
function from strongly-validated glints, then matched-filter against it, the way stellar
photometry pulls faint sources out of noise. Full write-up:
[Glint PSF and matched filtering](issues/glint-psf-matched-filter.md).

The PSF part works. Fitting a forward model (polygon rasterised at 1 m, Gaussian-blurred,
block-averaged onto each scene's own grid at the target's true sub-pixel position) over 68
targets below 500 m2 gives **sigma 0.65 px, 90% CI 0.60 to 0.70**, against an optical theory
range of 0.49 to 0.62 px implied by ESA's stated MTF. The residual excess is covered by a
measured per-scene source displacement of 0.72 px median, so the fitted kernel is an
effective one that already contains co-registration.

The detector part does not. Every variant tested, centroid-pinned, offset-fitted, and
point-source, scores **below** the p98-minus-annulus statistic already in the pipeline
(AUC 0.485 to 0.620 against 0.648 to 0.655), significantly so over all sizes. The reason is
visible in the fit itself: sigma climbs from 0.65 to 2.20 px with installation area while
variance explained collapses from 0.49 to 0.06, because a specular glint comes from whichever
patch satisfies the mirror condition on that date rather than from the whole array. Matched
filtering is optimal for a known shape at a known position and a glint has neither, which is
the one property stars have that makes the analogy work.

The valuable result was the control set built to test it. 600 verified negatives, buildings
inside the 27 Rule-1 complete quadrats carrying `has_pv == 0`, give a false-spike rate of
**2.0%**, against the 8.7 to 20.3% previously measured on merely model-negative controls. An
ablation puts the per-pixel SCL cloud veto at half of that improvement (4.5% with it
disabled) and unmapped real PV in the old controls at the rest. Against true detection rates
the instrument separates by 15x at 100 to 500 m2 and 7.9x below 100 m2, so
[the spike-rate density estimator](issues/glint-spike-rate-density-estimator.md)'s stated
blocker, that false rate equals or exceeds true rate below 500 m2, does not hold against
verified negatives.

### Super-resolution

Three feasibility tests, run in sequence by `scripts/run_sr_experiments.sh`: guided fusion of
the 20 m bands to 10 m, multi-image super-resolution from repeated overpasses, and
internal-learning single-image super-resolution. None improved detection, and the last carries
an obvious hallucination risk on a task whose whole output is "is there a panel here".
Scripts are kept for reference.

### Choosing the imagery date so panels glint

A well-motivated idea that the geometry refuses. `roofclf` reads a dry-season median
composite, and a median is built to suppress exactly the transient specular events that mark
a panel, so reading the dates when panels *should* glint ought to raise the signal-to-noise
ratio, especially in dense blocks where many would brighten at once.

Measured two ways. First the ceiling, from real granule sun and view angles over two years
at all 23 quadrats: because Sentinel-2 views near-nadir, the pose that reflects sunlight into
the sensor is a narrow locus, and only a **median 13.2% of a plausible south-facing installed
population (range 6.7 to 23.6%)** can land on it at all. A textbook south-facing array at
tilt 30 misses by 8.6 degrees on every scene in the archive. The single best date reaches
**1.0 to 1.8%** of rooftops, so the "one optimal date" framing fails specifically.

Then the feature itself, on the Lahore quadrat (13,500 buildings, 3,432 with mapped PV, the
densest ground truth here and exactly the dense-urban case the idea targets). It separates PV
standalone at 0.613 AUC, but **0.528 within roof-size band**, i.e. nearly all of that was
size. Added to `roofclf`'s own features under a spatial holdout, size-controlled AUC moves
**0.7875 to 0.7879**.

Full derivation, the pose-window figure and before/after imagery of the best-case buildings:
[Solar glint](methods/glint.md#can-a-predicted-glint-date-boost-the-roof-classifier). Two
narrower versions survive untouched: per-locality pose calibration, and glint's existing role
corroborating individual large arrays.

### Snow-cover contrast, and the one commune that nearly sold it (2026-09-08)

The physics here is better than the glint idea's, and it targets a weakness this project can
name precisely. Panels are tilted, smooth and dark, so they shed and melt snow faster than
the roof around them: under lying snow a small array stops being a dark patch on a dark slate
roof and becomes a dark patch on a white one. At 10 m, for a 20 m<sup>2</sup> array in a
100 m<sup>2</sup> pixel, that is the difference between a **8% reflectance deficit against a
slate roof, inside BRDF noise**, and a **19% deficit against snow on a brighter, higher-SNR
background** -- roughly 2.4x the signal, and aimed squarely at the dark-roof contrast problem
that makes French rooftops harder than Pakistani ones.

It fails on opportunity, which is the same thing that killed
[choosing the imagery date so panels glint](#choosing-the-imagery-date-so-panels-glint), and
it was measured the same way: not by building a detector, but by counting how many chances a
roof actually gets. `scripts/snow_opportunity.py` reads SCL on its native 20 m grid inside a
rasterised mask of each commune's VIDA footprints -- snow over farmland says nothing about
whether roofs were white -- and counts a scene as an opportunity when snow exceeds 5% of roof
pixels while cloud stays under 20% of them. Both conditions matter, and the cloud one is easy
to forget: in France a snowfall usually arrives with the system that hides it.

Across **1,556 scenes, 14 communes and four winters (2021/22 to 2024/25): 84 opportunities,
of which 79 are in a single commune.** Saint-Martin-de-la-Porte, alpine Maurienne at roughly
1,000 m, returns 19.8 per winter and peaks at 99.7% roof snow. Chambery returns 0.50 per
winter, Grenoble, Langoat and Saulny 0.25 each, and **nine of the fourteen communes return
zero in four winters**. Excluding the one alpine commune leaves **0.096 opportunities per
commune-winter**, about one usable scene per commune per decade.

Three things then compound, and the first is decisive:

- **The signal is where the fleet is not.** On a deliberately generous definition of mountain
  departements (Alps, high Pyrenees, Jura, Vosges, Massif Central), only **10.8% of France's
  34.6 GWp of registered PV** sits there.
- **It would need a retrain, not a processing change.** Snow currently *causes* false
  positives here: `growth.py` records 91 of 155 km<sup>2</sup> of spurious "vanishing" PV
  above latitude 34 as winter snow, and `imagery.py` excludes SCL class 11 from composites by
  design. The contrast could not be harvested by the current model, only by one trained on
  snow-bearing labels that do not exist.
- **Winter geometry adds a false-positive mode.** At 45 N in December the sun sits near 20
  degrees elevation, so shadows become large relative to buildings at 10 m, precisely while
  the method hunts dark patches on bright roofs.

**The methodological lesson is about the pilot, not the physics.** The alpine commune was run
first as a smoke test and on its own it argued the opposite conclusion, roughly 20
opportunities per winter. It is the outlier, not the norm, and a single-site pilot would have
justified building the whole thing. Opportunity has to be counted over the population the
method would be applied to.

One variant survives and is worth stating: **Germany**, which has more reliable lowland snow
and is already the largest region in the training corpus, so the retrain objection is weaker
there. If the snow hypothesis is ever tested properly it should be tested there, not in
France. Raw counts: `results/france_snow_opportunity.csv`.

### The 20 m bands, and what sharpening them costs (2026-09-19)

Six of the ten composite bands are 20 m at the sensor: B05, B06, B07, B8A, B11 and B12.
The composite is written at 10 m, and `odc.stac` was replicating each 20 m value
nearest-neighbour into a 2x2 block. Measured on cell 0122_0077, B11 and B12 are constant
across 2x2 blocks in **100.0%** of the raster, against 0.0% for B02 and B08.

That matters more than it sounds, because of where the classifier's weight sits:

| Coefficient | Value | Native |
| --- | --- | --- |
| `b11_mean` | +4.33 | 20 m |
| `swir_vis_ratio` | -3.92 | uses SWIR |
| `ndvi` | +3.73 | 10 m |
| `ndbi` | +3.65 | uses SWIR |
| `b12_mean` | -3.23 | 20 m |
| `b02_mean` | +2.78 | 10 m |

The four largest are SWIR or SWIR-derived. So the model leans hardest on bands that carry
no independent information at the grid it is scored on, and a 100 m2 building's SWIR value
comes from a 20 m cell whose centre can be 10 m away from it.

Two fixes were measured against the 30 production quadrats, leave-one-quadrat-out, paired
per fold, changing nothing but how the same downloaded pixels reach the 10 m grid:

| Variant | AUC | Within size band | Folds better | Sign test |
| --- | --- | --- | --- | --- |
| Baseline (nearest) | 0.8575 | 0.8206 | -- | -- |
| Bilinear from the true 20 m grid | 0.8574 | **0.8322** | 20 of 30 | p = 0.061 |
| Regression sharpening | 0.8570 | 0.8060 | 7 of 30 | p = 0.008 |

**They point in opposite directions, and that is the finding.** Regression sharpening
predicts each 20 m band from the four native-10 m bands and adds back the residual, and it
**hurts significantly**: -0.0047 AUC, -0.0052 within size band, better in only 7 of 30
folds. The interpretation is the useful part. If SWIR were largely a function of the
visible bands, synthesising its 10 m structure from them would be nearly free; that it
costs skill says **the SWIR signal the classifier uses is genuinely independent of the
visible bands**, and replacing real-but-coarse SWIR with a visible-derived estimate throws
it away. This is a property of PV worth remembering: it is spectrally distinctive in the
shortwave infrared precisely where the visible bands cannot see it coming.

Simply removing the blockiness, by taking each band back to its true 20 m grid and
resampling bilinearly, moves the other way: **+0.0041 AUC within size band, better in 20
of 30 folds, p = 0.061**, with the median within-size AUC going 0.8206 to 0.8322. That is
suggestive rather than established, and it is free. It says the defect worth fixing is the
**misregistration**, not the missing detail.

**Shipped** as `imagery.BAND_RESAMPLING` / `annual_composite(resampling=...)`, default
`"20m-bilinear"`, with `--resampling nearest` to reproduce the old behaviour. Every
composite records which it used in an `earthpv_resampling` tag; a composite with no such
tag predates this and is nearest. **The two must not be mixed within one AOI**: the change
is small but systematic, and a model calibrated on nearest composites and scored on
bilinear ones is a domain shift rather than an improvement. That is enforced rather than
documented -- `compose` inherits an AOI's existing mode and gives only a fresh AOI the new
default, because a country-scale run is a restart loop and the first pass after a default
changes is where silent mixing happens. Pakistan, Germany, France, Zambia and Nigeria
(20,160 cells between them) are all nearest today and stay that way until someone
recomposes one wholesale, which on p=0.061 evidence is not worth the bandwidth.
SCL keeps nearest regardless, because interpolating between class 4 and class 8 invents
class 6.

### Unmixing the pixel against a known footprint (2026-09-19)

A zonal mean over a building's pixels is a mean of MIXTURES: a 100 m2 roof is one 10 m
pixel it shares with road, yard and neighbours. That dilution is the mechanism behind
nearly every negative result in this register. Blind two-endmember unmixing was rejected at
0.659 AUC, but this is a different problem and a better-posed one, because the abundances
are **known**: the footprints say what fraction of each pixel belongs to which building, so

    y_p = sum_j A_pj r_j + (1 - sum_j A_pj) b_p

is a linear inverse problem for the per-building reflectance `r`, solved for a whole
quadrat at once with a ridge toward the zonal mean (`preprocess.unmix_buildings`).

**On synthetic data it works exactly as intended.** With buildings deliberately offset from
the pixel grid and 36 to 196 m2 in size, so the median building fills 38% of its brightest
pixel, unmixing cuts mean reflectance error against truth by **67%** (0.0975 to 0.0319) and
recovers **84% of the true dark/bright contrast** where the zonal mean recovers 28%.

**On real quadrats it is the worst result in this register:** -0.0205 AUC and **-0.0323
within size band**, better in **2 of 30 folds**, sign test p = 0.000. Not noise, not a tie,
a substantial loss.

Two explanations, and the second is the interesting one:

- **The footprints are not that good.** The solve assumes `A` is exact. VIDA is
  imagery-derived and systematically undersized -- this project already measured 117,003 m2
  of mapped rooftop PV overhanging VIDA outlines across 27 quadrats, which is 80% of what
  [the parcel label](methods/roofclf.md#the-parcel-label-parcel-label-2026-08-16) recovers.
  A wrong `A` does not merely fail to help, it attributes the wrong pixels to the building.
- **The mixture is not purely a nuisance.** The parcel label shipped because PV *beside* a
  building counts toward it, and the yard carries label-correlated signal. Unmixing does
  the exact opposite: it strips the surroundings out in order to isolate the roof. Running
  it against a parcel label is close to self-defeating, and the size of the loss suggests
  the context is worth more than the purity.

The honest summary is that **dilution is real but removing it is not the same as
recovering the signal**, and an instrument that assumes its geometry is exact inherits
every error in that geometry. Kept as `roof-classifier`-side machinery behind
`building_table(preprocess="unmix")` for anyone who arrives with authoritative footprints
-- the French cadastre is the obvious candidate, since it already bought +0.027 AUC within
size band over VIDA there -- but off, and not recommended on an imagery-derived layer.

Raw numbers for both: `results/roofclf_preprocess_ablation.json` and
`results/roofclf_preprocess_*_folds.csv`.

### L1C against L2A: the correction is not the problem (2026-09-19)

Sen2Cor's surface-reflectance retrieval assumes a **Lambertian** surface and constrains
aerosol from dark targets. A PV module is specular AND dark, so on the face of it L2A
models the wrong physics over exactly the target of interest, in a geometry-dependent way,
and it clips the saturation a real glint produces. If that costs anything, the fix is free:
use L1C top-of-atmosphere reflectance instead.

Getting the data was the awkward part and is worth recording. Planetary Computer publishes
L2A only, and Earth Search's `sentinel-2-l1c` assets point at ESA's **requester-pays**
`s3://sentinel-s2-l1c`, which needs AWS credentials. Google's `gcp-public-data-sentinel-2`
mirrors the same SAFE archives and is anonymously readable, so `imagery.l1c_composite`
runs discovery on STAC and reads pixels as JP2 over HTTPS from GCS, on the parent
composite's own pixel grid. L1C carries no usable cloud mask (QA60 is empty from baseline
04.00), so the mask comes from the L2A scenes of the same solar days. Serially this costs
about 12 minutes a quadrat, nearly all of it JP2 opens; a thread pool over the 120
(scene, band) reads brings it to 108 s.

The composite validates against L2A exactly as atmospheric physics requires: TOA/BOA is
**1.42 in the blue, 1.19 green, 1.09 red, 0.97 NIR, 0.93 and 0.89 in the SWIR** -- strong
Rayleigh path radiance at short wavelengths giving way to absorption at long ones.

**And it makes no difference.** Over the same 30 quadrats, same rows, same features:

| | AUC | Within size band |
| --- | --- | --- |
| L2A (shipped) | 0.8575 | 0.8206 |
| L1C | 0.8429 | 0.8102 |
| Paired delta | +0.0004, **15 of 30 folds, p = 1.00** | -0.0039, 12 of 30, p = 0.46 |

Fifteen folds each way is as null as a result can be, so **the Lambertian objection, while
physically real, costs the classifier nothing measurable.**

The interesting part is the spread rather than the centre. The paired median is zero while
the median AUC drops 0.0146, and the fold-to-fold IQR is about three times the other
variants tested here (-0.0274 to +0.0128 within size band, against -0.0007 to +0.008 for
bilinear resampling). A few quadrats get much worse under L1C while the typical one is
unchanged. That is what an absent atmospheric correction should look like in a
leave-one-quadrat-out design: path radiance varies with aerosol and geometry BETWEEN
quadrats, so removing the correction adds cross-quadrat variance without touching
per-building discrimination. **The correction earns its place in transferability, not in
contrast** -- which is precisely the property a model trained on some quadrats and applied
to a whole country depends on.

Kept as `building_table(preprocess="l1c")` plus `scripts/compose_l1c_quadrats.py`, because
the reader is the reusable part: it is the project's only route to TOA reflectance, and
glint work has a standing interest in saturation that L2A discards.

### Temporal unmixing: the dry-season window removes its own signal (2026-09-19)

The third and last unmixing attempt, and the only one that needs neither the footprint nor
a known endmember spectrum. Its constraint is that a PV array's AREAL FRACTION of a pixel
is constant while the background's reflectance is not, so taking the temporal spread of

    y_p(t) = f_p . r_PV + (1 - f_p) . b_p(t)

gives `spread(y_p) = (1 - f_p) . spread(b_p)`, and `f_p` is one minus the ratio of a
pixel's temporal spread to its local background's. That is self-normalising against roof
colour, where absolute reflectance is not: a dark roof and a panel look alike in a median
composite, and the claim is that they move differently through a season.

**On synthetic data the estimator is near-unbiased**, recovering 0.492 for a true fraction
of 0.50 and 0.247 for 0.25, and refusing (100% NaN) when the background is held still.

**On real quadrats the premise is simply false.** `scripts/pv_temporal_invariance.py`
compares per-pixel temporal MAD inside mapped PV against PV-free roof pixels in the same
quadrat, which tests the assumption directly and needs no classifier:

| | Median across 22 quadrats | Range |
| --- | --- | --- |
| PV pixels / PV-free roof pixels | **1.02** | 0.89-1.23 |
| Open background / roof pixels | **1.12** | 0.91-2.02 |

A PV pixel varies over time **exactly as much as the roof beside it**, so there is no
damping to measure; and the open background moves only 12% more than a roof, so there is
barely a denominator to divide by. Only 1 quadrat of 22 has a background moving more than
1.5x a roof. At 70-150 DN of MAD against 2,000-2,800 DN of reflectance, what is being
measured is a common floor of per-scene radiometric residual and BRDF, not surface
dynamics, and a floor is added AFTER mixing so it is not attenuated by `f` at all.

The ablation agrees, over 30 quadrats leave-one-quadrat-out: **+0.0003 AUC (17 of 30
folds, p=0.46)** and +0.0011 within size band (18 of 30, p=0.26). Damping plus size alone
reaches 0.7388 / 0.5863, against a size-only baseline of 0.7441 / 0.5773.

**The conditional test is what makes this more than another null.** Registered before the
run: if the mechanism is real but starved, the gain should rise with how much a quadrat's
background actually moves. It does. Spearman between the within-size gain and
`open_over_roof` is **+0.401 (p = 0.071, n = 21 folds)**, and splitting at the median:

| | Gain within size band | Folds better |
| --- | --- | --- |
| Dynamic half (open/roof >= 1.13) | +0.0015 | **9 of 11** |
| Still half (open/roof < 1.13) | -0.0001 | 4 of 10 |

So the physics is visible in the structure of the result and worth nothing in its
magnitude. Treat that cautiously: n is 21, p = 0.071, and the single most dynamic quadrat
(malok, open/roof 2.02) runs against the trend at -0.0013, so the relationship is not
driven by its own extreme.

**The most useful thing here is why the denominator is missing, because it is
self-inflicted.** `annual_composite` takes a DRY-SEASON window of the twelve least-cloudy
scenes, chosen precisely to suppress phenological and atmospheric variation and produce a
stable composite. That is the right choice for everything else the pipeline does, and it
removes exactly the background dynamics this estimator needs. The honest next test is a
full-year stack including the monsoon, where cropland actually swings; that is different
data, not a different estimator, and it is filed in
[Open questions](open-questions.md). Until then this is rejected for the window the
project actually composites.

A methodological note worth keeping: the first precondition check measured temporal
amplitude over WHOLE quadrats and looked ample (median 148 DN, all 31 quadrats clearing
the bar). The denominator that matters is the background near a BUILDING, which is other
roofs and pavement, and measuring that population gave 1.12. Checking the precondition on
the wrong population is the same error the
[snow-cover experiment](#snow-cover-contrast-and-the-one-commune-that-nearly-sold-it-2026-09-08)
records, in a different costume.

Artifacts: `results/pv_temporal_invariance.json`, `results/roofclf_temporal_unmix.json`,
`results/roofclf_temporal_unmix_folds.csv`.

### The model class: ranking and calibration disagree (2026-09-19)

Every feature block this project has measured -- SPPI, glint, the yard, epoch jump,
temporal statistics, temporal unmixing, sharpening, spatial unmixing, L1C -- was priced
against `fit_logistic`, an L2-regularised LINEAR model. A linear score cannot express a
conjunction, and "is this a PV roof?" reads like one: dark AND spectrally flat across the
visible AND the right SWIR drop AND large AND in a dense-adoption area. Six blocks landing
within 0.005 of each other is consistent with the functional form being the constraint
rather than the features, so it is worth testing directly.

Two declared `HistGradientBoostingClassifier` configurations, conservative and larger,
fixed in the script rather than selected on the held-out folds, on the same 30 quadrats
and the same table.

| Model and features | AUC | Within size band | Median per-quadrat rate error |
| --- | --- | --- | --- |
| Logistic (shipped) | 0.8574 | **0.8206** | 0.0308 |
| Logistic + shape | 0.8593 | 0.8196 | 0.0309 |
| GBM small | 0.8582 | 0.8006 | 0.0204 |
| GBM large | 0.8526 | 0.7979 | 0.0177 |
| GBM large + shape | 0.8618 | 0.7921 | **0.0165** |

**On ranking the linear model wins, and not marginally.** Paired per fold, every GBM
variant loses: -0.0089 to -0.0121 AUC and -0.0163 to -0.0231 within size band, better in
only 4 to 6 of 30 folds, p <= 0.002. The larger configuration is worse than the smaller
one, which is the signature of a flexible model learning each quadrat's idiosyncrasy
rather than what transfers between them. Note that `gbm_large_shape` has the highest median
AUC in the table (0.8618) while losing on 25 of 30 folds: a difference of medians is not a
paired gain, which is the same trap the shape block below fell into.

**So the linear model is not the bottleneck, and the feature experiments were fair.** That
is worth having established, because it is the assumption every one of them rested on.

**On calibration the answer reverses, and for this project that matters.** The atlas
consumes an aggregate adoption rate, not a ranking, and the register already records that
ranking transfers across quadrats while absolute rates do not -- which is why the
coverage-ratio-by-size-and-density machinery exists at all. Measured per quadrat, GBM
predicts the adoption rate substantially better: median absolute error **0.0308 to 0.0165**,
closer to truth in **20 of 29 quadrats for `gbm_large` (Wilcoxon p = 0.006)** and 21 of 29
with shape (sign test p = 0.024).

The obvious objection is that a model can tighten `rate_ratio` by hedging toward the global
mean, which would be worthless. It is not doing that: the spread of predicted rates across
quadrats is 0.0806 against a true 0.0798, and the correlation with the true rate RISES from
0.776 to 0.869. It keeps the dispersion and gets the level right more often.

**The two objectives genuinely disagree, and nobody had noticed because only AUC was
reported.** Nothing is being swapped on the strength of one run: the lead product and the
precision-thresholded population that feeds the coverage ratio both depend on per-building
ranking, where the linear model is better, while the capacity half depends on the rate,
where it is not. The honest next step is to price a GBM end to end through
`sub400-capacity` against the same quadrats, not to change the classifier.

#### Footprint shape, settled

`plus_shape` had scored 0.8593 against the shipped 0.8574 in the ablation table and had sat
unadopted since 2026-08-09, the best-looking block never promoted. Given the paired test
every rejected idea got, it is **noise: -0.0001 AUC, 14 of 30 folds, p = 1.00**, and
-0.0003 within size band. The apparent gain was a difference of medians across folds rather
than a per-fold improvement. Closed.

Artifacts: `results/roofclf_model_class.json`, `results/roofclf_model_class_folds.csv`.

### Aiming at the aggregate: weighting and recalibration (2026-09-19)

The [model-class test](#the-model-class-ranking-and-calibration-disagree-2026-09-19) found
that gradient boosting ranks worse and predicts per-quadrat adoption rates better. Two
cheap interventions follow from it, neither touching the feature set, both aimed at the
aggregate the atlas consumes rather than at AUC.

| Variant | AUC | Within size band | Median per-quadrat rate error | Area ratio |
| --- | --- | --- | --- | --- |
| Baseline (shipped) | **0.8574** | **0.8206** | 0.0308 | 1.084 |
| Area-weighted loss | 0.8506 | 0.8046 | 0.0395 | **1.035** |
| Isotonic, global | 0.8570 | 0.8199 | 0.0268 | 1.095 |
| Isotonic, by size tercile | 0.8560 | 0.8166 | **0.0253** | 1.128 |
| Platt | 0.8574 | 0.8206 | 0.0287 | 1.070 |
| Gradient boosting, for reference | 0.8526 | 0.7979 | *0.0165* | -- |

**Area weighting does what it promises, and that is not what the product needs.** Capacity
is area-weighted while the fit treats a 30 m2 shed and a 390 m2 warehouse as equally
important rows, so weighting the likelihood by roof area is the obvious correction. It
improves the quantity it optimises -- the predicted-over-true flagged roof AREA moves 1.084
to 1.035 -- and it is worse at everything else: -0.0111 AUC, -0.0160 within size band, and
a COUNT rate error that rises 0.0308 to 0.0395. Trading the population that carries the
labels against the aggregate loses more than it gains at this sample size. Available as
`fit_logistic(sample_weight=...)`, off by default, and `None` reproduces the unweighted fit
bit-for-bit.

**The calibration gain is not recoverable by recalibration, which is the useful half.** A
monotone map cannot change a ranking, so if gradient boosting were merely a better-calibrated
version of the same score, isotonic or Platt would capture it for free. They do not. The best
variant, isotonic fitted within roof-area terciles, cuts the median per-quadrat rate error
0.0308 to 0.0253 and is closer in 19 of 29 quadrats, but at **Wilcoxon p = 0.069** it is not
significant, and it recovers only **38% of the gradient-boosted improvement** (which reached
0.0165 at p = 0.006). Platt moved AUC by exactly 0.0000 in 0 of 30 folds, which is the clean
check that a strictly monotone map reorders nothing; isotonic moves it by 0.0002 only because
it creates ties.

So **gradient boosting's advantage is a genuine reordering of buildings, not a calibration
curve**, and it cannot be had cheaply. That sharpens
[open question 20](open-questions.md): if the aggregate matters more than the ranking for
the capacity half, the GBM has to be deployed properly, plumbing and all, rather than
approximated by post-processing the linear model.

Calibrators were fitted NESTED -- inside each leave-one-quadrat-out fold the 29 training
quadrats were split into five blocks by quadrat, and the calibrator was fitted on the inner
out-of-fold scores. Fitting on in-sample scores would be optimistic in exactly the direction
being measured. Artifacts: `results/roofclf_weighting_calibration.json`,
`results/roofclf_weighting_calibration_folds.csv`.

### Spectral coherence, and where transferability lives (2026-09-19)

Two more attempts at the features the classifier leans hardest on, both using data already
on disk.

| Variant | AUC | Within size band | Median rate error | Paired vs shipped |
| --- | --- | --- | --- | --- |
| Baseline (shipped) | 0.8574 | **0.8206** | 0.0308 | -- |
| Medoid composite | 0.8415 | 0.7896 | 0.0280 | -0.0074, 9 of 30 |
| Plus context features | 0.8540 | 0.8166 | 0.0291 | -0.0003, 14 of 30 |
| **Context features ONLY** | 0.8595 | 0.8189 | **0.0569** | **-0.0011, 14 of 30** |
| Medoid plus context | 0.8546 | 0.7982 | 0.0287 | -0.0070, 9 of 30 |

**The band-wise median really does invent a spectrum, and fixing it does not pay.**
`annual_composite` reduces with `median(dim="time")` over a Dataset, so each band's median
is taken independently: a pixel's B02 can come from January and its B11 from March, and the
result is a spectrum no scene observed. That is harmless for one band and not harmless for a
RATIO, which is what the model weights most (`swir_vis_ratio` -3.92, `ndbi` +3.65,
`blue_red_ratio` -1.56). A medoid -- the single date per pixel whose whole spectrum is
closest to the median -- is coherent by construction, and verified to equal exactly one real
date where the band-wise median equals none. It scores **-0.0074 AUC and -0.0102 within size
band**. The trade is visible in the construction: a medoid is ONE observation, so it forfeits
the twelve-scene median's noise averaging, and that costs more than incoherent ratios do. It
does improve the rate error slightly (0.0308 to 0.0280), which is consistent with the
diagnosis rather than with the medoid being simply worse.

**The result worth keeping is the context-only row.** `local_zscore` re-centres a building
against its own quadrat or cell, and ships applied to `brightness` alone, one feature of
fifteen. Extended to every spectral feature, added alongside the absolute ones it changes
nothing (-0.0003, 14 of 30). But **replacing them entirely ties the shipped model**
(-0.0011, 14 of 30, p = 1.00) while nearly doubling the rate error, 0.0308 to 0.0569.

That separates two things this project had confounded:

- **Ranking is relative.** Which building in a cell carries PV is fully answerable from
  within-cell contrast; the absolute reflectance level adds nothing to it.
- **Calibration is absolute.** Z-scoring removes the level that says one quadrat is more
  PV-dense than another, and the aggregate collapses.

For scaling that is a useful thing to know in both directions. The ranking half -- the leads
product, and the precision-thresholded population the coverage ratio is fitted on -- should
transfer to a new country robustly, because it is immune to the cross-quadrat level shifts
that atmospheric and seasonal differences produce. The aggregate half depends on absolute
reflectance being comparable between places, which is exactly why removing atmospheric
correction in [the L1C test](#l1c-against-l2a-the-correction-is-not-the-problem-2026-09-19)
tripled the fold-to-fold spread without touching the median.

**A footnote that turned out to be a defect.** `brightness_zscore` re-centres a building's
brightness against its own quadrat or cell and has shipped as an available block,
`plus_local_contrast`, since 2026-08-09. It had never actually been measured: `local_zscore`
used `np.median` rather than `np.nanmedian`, and it runs inside `building_table` BEFORE the
fill/edge rows are dropped, so a single building whose footprint has no valid pixel turned
the entire quadrat's z-scores into NaN. That was 21% of rows and 5 of 30 quadrats entirely
NaN -- among them sialkot and sukkur, the two quadrats already recorded here as carrying
composite fill. One NaN poisons a logistic fit, so every fold trained on those quadrats
returned NaN and `pivot_table` silently dropped the block from the ablation output. Fixed
2026-09-19 (NaN-safe, and bit-identical on clean input), after which the block measures
**+0.0000 AUC, 13 of 30 folds** and is rejected on its merits rather than by accident.

Neither is adopted. The context block is kept as `roofclf.CONTEXT_FEATURES` /
`add_context_features`, the medoid as `preprocess.medoid_composite` and
`building_table(preprocess="medoid")`. One caveat on the medoid comparison: its table has 36
more rows than the baseline (123,903 against 123,867), because a scene stack covers the
quadrat geobox plus margin rather than the boundary bbox. At 0.03% that cannot carry the
result, but the two are not row-identical the way the earlier preprocessing comparisons were.

Artifacts: `results/roofclf_medoid_context.json`,
`results/roofclf_medoid_context_*_folds.csv`.

### The spectral SNR budget, and why the domain is exhausted (2026-09-19)

After a run of null preprocessing results it is worth asking what the spectral signal
actually IS, rather than trying another representation of it. Detection here is a mixture,
`y = f.r_PV + (1 - f).r_bg`, so the signal is `f.(r_PV - r_bg)` and the question is what
each term is worth. Measured on the 30-quadrat table, in B08, the highest-contrast band:

| Term | Value |
| --- | --- |
| Panel-minus-roof contrast at full cover | 0.0579 reflectance = **1.34 background sd** |
| Median fill fraction on a PV roof | 0.309 |
| Typical available signal | **0.41 sd** |
| Background sd between PV-free roofs | 0.0431 reflectance |
| Sentinel-2 radiometric noise at this level | ~0.001-0.002 reflectance |

The mixture model holds tightly: B08 falls linearly with fill fraction
(`B08 = 0.3142 - 0.0579 x f`), and the separation grows with it exactly as predicted --
d' of -0.25, -0.36, -0.54, -0.83 across fill-fraction bands averaging 0.08, 0.15, 0.29 and
0.65.

**The noise is not the sensor, and this rules out a whole class of ideas by arithmetic.**
Roof-to-roof heterogeneity is twenty to forty times Sentinel-2's radiometric noise. Every
intervention aimed at measurement quality -- more scenes, a better atmospheric correction,
denoising, spectral coherence -- is tuning a term worth about 2% of the variance. That is
the retrospective explanation for
[temporal statistics](#keeping-more-than-the-median-composite-2026-09-19),
[L1C](#l1c-against-l2a-the-correction-is-not-the-problem-2026-09-19),
[the medoid](#spectral-coherence-and-where-transferability-lives-2026-09-19) and
[sharpening](#the-20-m-bands-and-what-sharpening-them-costs-2026-09-19) all landing at zero.

**The linear spectral limit is already reached.** The Mahalanobis separation across all ten
bands is d' = 1.226, an implied AUC of **0.807**, while `spectral_only` measures **0.8333**
in leave-one-quadrat-out -- the shipped model is at or past the Gaussian linear bound,
exceeding it because the hand-made ratios are nonlinear in the raw bands. Whitening buys
1.95x over the best single band (0.629, B08) and the model already has it. With 79.3% of
band variance in the first principal component and a maximum inter-band correlation of
0.984, there are roughly two effective dimensions here. **No new index, matched filter or
whitening of these bands can add meaningful signal.** (The bound is in-sample and assumes
Gaussian classes, so read it as an order of magnitude, not a decimal.)

**That leaves shrinking the denominator, which fails for an interesting reason.** Since the
noise IS roof diversity, estimating a background per building from its nearest neighbours
should raise SNR directly, and roofing material is spatially clustered so the neighbours are
the right reference. It does cut the noise: the PV-free standard deviation falls **23 to 43%**
across bands. It cuts the signal faster. Median d' falls to **0.36x**, B11 even changes sign,
and the multivariate separation drops 1.226 to 0.904.

The cause is a property this project already documents: **PV adoption is spatially
clustered**, which is why `nn_median_m` exists. A PV roof's neighbours disproportionately
carry PV, so the local median is itself pulled toward the panel spectrum and subtracting it
cancels the contrast. Sweeping the neighbourhood scale shows there is no escape:

| Neighbours | Median radius | Mahalanobis d' | Against raw |
| --- | --- | --- | --- |
| 10 | 31 m | 0.717 | 0.58x |
| 50 | 78 m | 0.904 | 0.74x |
| 200 | 169 m | 0.980 | 0.80x |
| 800 | 369 m | 1.022 | 0.83x |
| none | -- | **1.226** | 1.00x |

Monotone, and asymptotic toward not conditioning at all. This also explains why the
quadrat-scale version
([context features](#spectral-coherence-and-where-transferability-lives-2026-09-19)) merely
TIED rather than helped or hurt: at 1-4 km2 the group is large enough that adoption
clustering does not dominate its median, so it neither cancels signal nor removes much
heterogeneity.

**Conclusion: the spectral domain is exhausted for this sensor.** The remaining term in the
budget is fill fraction, which no amount of processing changes -- it is set by pixel size
against array size, and it is the same quantity that
[makes France fail and Pakistan work](results/france.md#earthpv-against-france-the-sub-400-m2-instrument-does-not-transfer).
Kept as `roofclf.add_neighbour_features` for anyone who wants to re-measure. Panels are
strongly polarising, which would be a nearly background-free channel, but no free satellite
measures it.

### Sun geometry: neither glint nor high sun raises the contrast (2026-09-19)

Two follow-ups to [the SNR budget](#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19),
asking whether some sun-sensor geometry gives a better look at the same panels.

**Glint is not a scene-level lever.** A glass-fronted panel is specular, so on a date when
the sun-panel-sensor geometry approaches the mirror condition it should stand out. Scored
over 239 scenes in 22 quadrats, using each scene's own sun and view angles and the **192
poses fitted from real Pakistani installations** rather than an assumed one, near-specular
scenes do show 34% more contrast: d' -0.549 in the nearest quartile of misalignment (1.17
deg) against -0.409 in the farthest (8.54 deg).

It is not glint. Misalignment and solar zenith are collinear at +0.475 by construction, and
partialling out the sun kills the geometry term while the sun survives:

| | Spearman | p |
| --- | --- | --- |
| d' vs misalignment | +0.101 | 0.12 |
| d' vs solar zenith | +0.204 | 0.0015 |
| **d' vs misalignment, controlling for solar zenith** | **+0.025** | **0.70** |
| d' vs solar zenith, controlling for misalignment | +0.161 | 0.013 |

The sign was wrong for glint from the start: PV gets DARKER relative to the roof near
specular, not brighter. And glint could not work as a scene selector even if it were real,
because **93.7% of scenes already have some pose within 10 deg of specular** (median 3.77
deg) -- the condition almost never discriminates between observations. What this does NOT
test is per-target glint on individual installations, which is how `glint.py` uses it and
where it does work: no scene has more than half the pose population glinting, so a narrow
lobe on a few panels is diluted by pixel-averaging across a quadrat.

**And a high-sun window does not help either, which refutes a prediction made here.** The
winter fit was `d' = -1.296 + 0.0145 x sun_zenith`, which extrapolated to roughly double the
contrast at summer sun angles and suggested the dry-season compose window might be costing
signal. Measured against pre-monsoon May-June scenes over 10 quadrats:

| | Pre-monsoon | Dry season |
| --- | --- | --- |
| Median d' | -0.601 | -0.672 |
| Roof brightness | **3,064 DN** | 2,532 DN |

**Gain 0.98x, better in 5 of 10 quadrats, Wilcoxon p = 0.77.** The first half of the
mechanism happened exactly as predicted -- roofs really are 21% brighter under high sun --
and the contrast did not move, because d' is a NORMALISED quantity: illumination scales the
panel, the roof and the between-roof spread together, so numerator and denominator grow in
step and the ratio is invariant to first order.

That means the within-window correlation the prediction rested on was not illumination
scaling at all; more likely seasonal surface change (moisture, dust, vegetation) tracking
date across a narrow 37-59 deg span. **The compose window is not costing contrast**, and
acting on the extrapolation would have meant recompositing a country onto a worse epoch for
no gain. Artifacts: `results/glint_geometry_snr.json`,
`results/summer_window_contrast.json` and their per-scene CSVs.

### The level half of brightness does not transfer (2026-09-20)

`absolute = cell_mean + deviation`, and `roofclf` sees only `absolute`, which confounds
"this building is bright" with "this cell is bright". Handing it the cell mean adds one
degree of freedom per feature. The motivation was the measured split reported above:
within-cell z-scores alone tie the shipped ranking while doubling the rate error, so ranking
is relative and calibration is absolute. The level half looked like the unexploited part.

Registered before measuring: a cell-constant feature adds the same number to every
building's logit inside a held-out quadrat, so it cannot reorder them, and any AUC movement
can only come from refitting the other coefficients. That half held -- the single cell-mean
moved AUC by **+0.0001**.

The substantive half failed, and significantly.

| Block | AUC | Within size band | Rate error | Rate ratio |
| --- | --- | --- | --- | --- |
| Baseline | 0.8574 | 0.8206 | **0.0308** | 1.061 |
| Plus brightness cell-mean | 0.8571 | 0.8220 | 0.0309 | 1.056 |
| Plus all 15 cell-means | 0.8494 | 0.8229 | 0.0430 | 1.012 |

Calibration gets **worse**: the per-quadrat adoption rate is closer to truth in only **7 of
29 quadrats, sign test p = 0.008, Wilcoxon p = 0.002**. The 15-feature version pushes median
rate error 0.0308 to 0.0430 while pulling the ratio to 1.012, which is the signature of
centring the level and widening its spread.

The reason is this register's own finding, turned against the idea. A cell-constant feature
is fitted across 29 quadrats and then extrapolated to an unseen one, so the model learns a
BETWEEN-quadrat relationship between brightness and adoption rate -- and between-quadrat
absolute rates are exactly what does not transfer. Adding the level as a feature does not
give the model the level; it gives it a spurious slope to extrapolate along. Kept as
`roofclf.CELL_LEVEL_FEATURES` / `add_cell_level_features` for re-measurement.

### Snow in Germany: the opportunity is real, the contrast is not concludable (2026-09-20)

[Snow-cover contrast](#snow-cover-contrast-and-the-one-commune-that-nearly-sold-it-2026-09-08)
was rejected for France on opportunity, 0.096 usable scenes per commune-winter outside the
Alps, and that entry named the one variant worth testing: Germany, which has more reliable
lowland snow. Tested over the 8 densest PV cells in the German OSM rooftop layer, three
winters, with SCL class 11 deliberately KEPT (the shipped mask drops classes outside 4-7 and
would discard every observation under test) and snow measured over building footprints
rather than over the cell.

**The opportunity objection is answered.** 6 snow scenes out of 58 low-cloud scenes, a
**10.3% rate**, against France's 0.096 per commune-winter. Observations of snow-covered roofs
genuinely exist in Germany.

**The contrast is not.** Six scenes, Mann-Whitney **p = 0.39**, and bimodal:

| Cell | Snow on roofs | Roof DN | PV DN | d' |
| --- | --- | --- | --- | --- |
| 137_515 | 61% | 2,035 | 1,146 | -2.40 |
| 137_515 | 100% | 3,806 | 2,405 | -1.72 |
| 149_513 | 20% | 1,647 | 829 | -1.03 |
| 149_513 | 100% | 4,333 | 1,702 | -1.74 |
| 60_508 | 100% | 3,250 | **8,143** | **+3.84** |
| 60_508 | 84% | 3,524 | **5,588** | **+2.48** |

Four scenes behave as the physics predicts. The two that inverted are explained by array
size rather than by snow: cell 60_508's mapped arrays have a **median area of 126 m2**,
about 1.3 pixels at 10 m, against 338 and 320 m2 in the two well-behaved cells. At roughly
1.2 PV pixels per array the mask is mostly snow-covered ROOF, which reads brighter than a
roof average that includes shadowed and wet surfaces. The project's central limitation,
array size against pixel size, reappears here amplified rather than relieved.

The headline ratio of 15.9x is not usable either: it divides by a bare-season baseline of
**-0.087**, i.e. German OSM rooftop PV barely separates from PV-free roofs in bare winter at
all, which is consistent with a control contaminated by the 96.4% of German rooftop PV that
OSM does not map. A near-zero denominator makes any ratio large.

What would settle it is more cells and a restriction to arrays large enough to own a pixel.
Recorded as partial rather than shipped or rejected, because the half that killed the French
version is genuinely answered and the half that matters is untested at this sample size.
Artifacts: `results/germany_snow_contrast.json`, `results/germany_snow_contrast_scenes.csv`.

### The composite reducer is the biggest lever in this register (2026-09-20)

Chasing Google's Open Buildings 2.5D Temporal, which fuses up to 32 Sentinel-2 acquisitions
to reach an effective ~4 m, produced the largest single improvement measured anywhere in
this register -- and it turned out to have nothing to do with super-resolution.

`annual_composite` reduces the scene stack with a per-pixel **median**. Replacing it with a
**mean** gains **+0.0286 AUC within size band, 25 of 30 leave-one-quadrat-out folds,
p = 0.0001**, at 10 m, with no change to resolution, features or model.

The decomposition that isolates it:

| Variant | AUC | Within size band | Folds better |
| --- | --- | --- | --- |
| Baseline, median at 10 m | 0.8575 | 0.8206 | -- |
| **Mean at 10 m** | 0.8756 | **+0.0286** | 25 of 30 |
| Mean at 5 m | 0.8789 | +0.0313 | 25 of 30 |
| Multi-frame fusion at 5 m | 0.8767 | +0.0273 | 26 of 30 |
| Area-weighted zonal means at 10 m | 0.8588 | +0.0113 | 25 of 30 |
| Median at 5 m, nearest | 0.8623 | +0.0058 | 23 of 30 |
| SEN2SR single-image at 2.5 m | 0.8402 | **-0.0367** | 6 of 30 |

So **91% of the effect is the estimator**, about 9% is the finer grid, and the fusion itself
is NEGATIVE: applying measured sub-pixel shifts scores below not applying them.

Why the mean wins is not mysterious once separated out. SCL masking already removes cloud,
shadow and snow, so the median's robustness is largely redundant, and at twelve samples a
median carries about 1.57x the variance of a mean. Less feature noise, better separation,
and it helps most for the sub-pixel footprints whose single pixel is noisiest.

**The route there was three wrong mechanisms in a row, which is worth recording.** The gain
first looked like multi-frame fusion; a zero-shift control beat the fused version, so it
looked like resolution; plain upsampling recovered only a fifth of it, so it looked like
footprint sampling; exact area-weighted zonal means recovered a third. Only the mean
explains it, and `tmean_up2` reproduces the shift-and-add control to four decimals, which is
the consistency check that the accumulator had been computing a mean all along.

**Why fusion cannot work here, measured rather than assumed.** Multi-frame super-resolution
needs frames that sample the ground at different sub-pixel phases. Measured across 298 frame
pairs in 30 quadrats, the median inter-acquisition shift is **0.122 px (1.22 m)**, with phase
offsets at roughly a quarter of the uniform-spread ideal and only about 3 frames in 12
usefully displaced. Re-measured from **native granules** with no reprojection or resampling,
to rule out our own loading path as the cause: **0.132 px (1.32 m)**, essentially identical.
The diversity really is that small. A synthetic check puts the consequence precisely: with
ideal phases shift-and-add recovers +0.166 of correlation against an upsample, and at the
diversity Sentinel-2 actually provides, +0.015 -- about 9% of the achievable gain.

**And single-image super-resolution actively hurts.** SEN2SRLite (CC0-1.0, runs in 0.31 GB on
a GTX 1060) produces a faithful 2.5 m raster -- downsampled it correlates 0.9976 with the
original and it genuinely adds high-frequency energy, 0.688 to 0.918. It still costs
**-0.0367 AUC within size band, 6 of 30 folds**, because it cannot add information: it
redistributes 10 m content using learned priors, and texture uncorrelated with PV dilutes
real contrast. That is the 2026-07 rejection reproduced with a much better model, and it
answers the hallucination objection empirically rather than by assertion.

**Building height, from GlobalBuildingAtlas, is redundant.** Height alone separates PV from
PV-free roofs at d' = +0.651 (median 6.74 m against 4.03 m), comparable to the best single
spectral band. On top of the model it is worth **+0.0006 within size band, 6 of 9 folds,
p = 0.51**, and height-plus-size alone scores 0.173 BELOW baseline: tall buildings are large
buildings, and `log_roof_area` already carries it. Measured on the 5 quadrats where GBA
covers more than half our footprints, a biased subsample. GBA heights are CC BY-NC 4.0 in any
case, which would have blocked deployment.

**The mean's weakness is real, and a trimmed mean is the answer.** The median is there to
reject residual cloud that SCL missed, and a mean cannot: with one unmasked cloud pixel among
twelve frames, a clean value near 100 reads 100.7 under the median, 100.2 under a 20%-trimmed
mean, and **924.4 under a plain mean**. Measured on the quadrats, the trimmed mean keeps most
of the gain:

| Reducer | Within size band | Folds better | One unmasked cloud |
| --- | --- | --- | --- |
| Median (current) | -- | -- | 100.7 |
| **Trimmed mean (drop top and bottom decile)** | **+0.0200** | 25 of 30 | **100.2** |
| Mean | +0.0286 | 25 of 30 | 924.4 |

So **the trimmed mean is the one to ship**: 70% of the gain, and robustness indistinguishable
from the median on the failure mode the median exists for.

Wired as `imagery.REDUCERS` / `annual_composite(reducer=...)` / `compose --reducer`, with the
default left at "median" and `run_compose` inheriting an AOI's existing reducer, exactly as
for the resampling change and for the same reason: a model calibrated on medians and scored
on means is a domain shift. Every existing AOI -- Pakistan, Germany, France, Nigeria, Zambia
-- inherits "median". Shipping it nationally means recompositing, which
[open question 18](open-questions.md) prices at roughly 2 TB of transfer per country, so it
is free for the next country and expensive for the existing ones.

Artifacts: `results/roofclf_preprocess_ablation.json`, `results/subpixel_shifts.json`,
`results/native_shifts.json`, `results/roofclf_gba_height.json`.

### Keeping more than the median composite (2026-09-19)

The composite reduces about twelve cloud-masked scenes to their per-pixel median
(`imagery.annual_composite`). A median is the maximum-robustness central estimator, so it
deletes the tail by construction, and the tail is where a specular surface at a fixed tilt
should put its information. The scenes are already downloaded and then discarded, so the
cheapest possible version of "use the time dimension" is to keep more of that distribution
and ask whether it helps.

`compose --stats` now writes a `temporal_stats` sidecar beside each composite: per-pixel
p10, p50, p90 and standard deviation for all ten bands, plus a valid-observation count.
No extra network traffic, which matters because this stage is bandwidth-bound. What
`roofclf` gets per building is the bright tail (p90 - p50, a free proxy for the glint that
otherwise needs bespoke per-target scene pulls), the dark tail (p50 - p10, which should
separate dark-and-static PV from dark-and-moving shadow), the temporal spread, and
`n_obs`, without which spread is unreadable: std = 0 means "stable" at twelve looks and
"one look" at one.

The measurement is a leave-one-quadrat-out ablation on the 30 production quadrats, and it
reproduces the shipped fit exactly (123,867 buildings, 17,150 positives, median fold AUC
0.8574, 0.8206 within size band, min fold 0.4964), so the block is the only variable.

| Feature block | AUC | Within size band |
| --- | --- | --- |
| Size only | 0.7441 | 0.5773 |
| Size + temporal | 0.7311 | 0.5868 |
| Median composite only | 0.8333 | -- |
| Size + spectral (shipped) | 0.8574 | 0.8206 |
| Shipped + temporal (compact, 6 columns) | 0.8579 | 0.8232 |
| Shipped + temporal (full, 31 columns) | 0.8576 | 0.8262 |

**It buys nothing.** Paired per fold, the compact block moves AUC by a median **+0.0003**
(IQR -0.0013 to +0.0016), improving **16 of 30 folds**, sign test p=0.57; within size band
+0.0006 (IQR -0.0018 to +0.0033), 16 of 30, p=0.71. Widening from 6 columns to 31 does not
rescue it, so the compact grouping is not what threw the signal away.

The `temporal_only` row is the part worth keeping, because it distinguishes "adds nothing
new" from "says nothing". On its own the block sits at 0.5868 within size band against a
0.5773 size-only baseline: a trace above chance, not nothing, but nothing that survives
having the median composite in the model. So the distribution's higher moments are close
to redundant with its centre for this task, at this resolution.

Two things make this a fair test rather than a plumbing failure. The sidecar stores its own
p50, and that band is **bit-identical to `composite_0.tif`'s median on 100% of valid
pixels**, so the temporal features and the existing reflectance features describe the same
twelve scenes and no epoch confound is possible. And the block has real dynamic range
rather than being flat: for B02 the median pixel spans 129 DN between p50 and p90, 183 DN
between p10 and p50, with a standard deviation of 148 DN, against roof reflectances of
order 1,000 to 3,000 DN.

The likeliest reason it fails is the same sensor ceiling that
[the 400 m2 floor](#the-detection-floor-measured-against-sub-metre-truth-2026-09-12) and
[the French transfer result](results/france.md#earthpv-against-france-the-sub-400-m2-instrument-does-not-transfer)
keep returning: a sub-400 m2 array is a minority of a 100 m2 pixel, so whatever anisotropy
it has is diluted by a roof that does not share it, in every statistic equally. Twelve
dry-season scenes also give little specular opportunity, which is the ceiling
[glint](methods/glint.md) already documents from the other direction.

Kept behind flags (`compose --stats`, `roof-classifier --temporal-features`), off by
default, because re-measuring costs one afternoon and no retraining. Cost if it were ever
wanted nationally: about 4x the per-cell composite disk, roughly 215 GB for Pakistan's
4,473 cells. Raw numbers: `results/roofclf_temporal_ablation.csv` (median per block) and
`results/roofclf_temporal_ablation_folds.csv` (per fold, which is what the paired test
above is computed from).

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

### SPPI alone as Germany's sub-400 estimator (2026-09-18)

Germany's published sub-400 m<sup>2</sup> half uses no classifier: it prices roof area in the
200-400 m<sup>2</sup> band at a register-fitted constant, because that beat both `roofclf` and
total roof area. The obvious thing left untried was the other detector. SPPI is a
zero-training spectral index, it is already computed for every scored German building, and it
is the corroborating half of Pakistan's AND-gate, so if any classifier were going to help
here it is the one that needs no labels.

It does not. All four estimators below were run through
`scripts/validate_sub400_against_mastr.py` on identical data, the same cells, the same
municipalities and the same five-fold cross-validation, with only the weighting changed:

| estimator | Gemeinden | median municipal error | best stratified | Spearman | slope |
| --- | --- | --- | --- | --- | --- |
| roof area only (published) | 10,589 | **31.2%** | 28.8% | 0.942 | 0.888 |
| SPPI percentile rank | 10,588 | 33.7% | 31.0% | 0.922 | 0.845 |
| roofclf probability | 10,005 | 36.8% | 34.9% | 0.855 | 0.333 |
| SPPI top decile | 10,209 | 49.9% | 48.8% | 0.824 | 0.498 |

Two formulations, because SPPI is a spectral index in roughly [-2.6, 0.07] rather than a
probability and cannot be multiplied in raw. **Percentile rank** weights each roof by where
its SPPI falls in the national distribution, the analogue of probability weighting.
**Top decile** credits only roofs above the 90th percentile, the analogue of thresholding and
the way SPPI is used in Pakistan's AND-gate.

The interesting half of the result is that SPPI ranks German roofs *better than the trained
classifier does*, on both error and slope, while needing no labels at all. The decisive half
is that neither beats doing nothing. This is the same finding as the roof-area baseline, from
a third direction: where PV is near-ubiquitous, capacity is close to proportional to roof area
by construction, so an instrument that concentrates credit on a subset discards more real
capacity than it correctly withholds. Thresholding is worst precisely because it discards the
most.

The baselines here read 31.2% and 36.8% where
[Germany's page](results/germany.md) records 35.4% and 48.4%, because the grid was rebuilt
without the building-density filter (4,871 cells against 4,657) after those were measured.
The ordering is unchanged and the within-run comparison is what the table is for.

**A NaN trap worth recording**, because it produced a confident wrong answer rather than an
error. The first top-decile run reported zero municipalities and zero capacity. 2,660 of
6.2M buildings, 0.043%, carry no SPPI value; `np.quantile` returns NaN if any input is NaN,
and `x >= NaN` is False for every row, so the threshold flagged nothing and the harness
dutifully reported zeros all the way through. The harness is now NaN-safe and logs how many
buildings lack a value.

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

**The good part:** Area under the ROC curve of 0.875 and 0.74 on held-out halves, against
0.50 for the model on the same footprints. That is the first non-zero discrimination anyone
here has achieved below 500 m².

**The part that failed:** Converting that into a city-scale unmapped-capacity number was
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
| [Glint PSF and matched filtering](issues/glint-psf-matched-filter.md) | The measured Sentinel-2 glint PSF, why filtering on it loses to the aperture statistic, and the verified-negative false-spike rate |
| [Glint spike-rate estimator](issues/glint-spike-rate-density-estimator.md) | Glint as a statistical density estimator, and the floor it hits |
| [Glint tile-batched coverage](issues/glint-tile-batched-coverage.md) | The 22x speedup, and the silent scene-loss bug it uncovered |
| [Glint-validated training labels](issues/glint-validated-training-labels.md) | A proposal to feed corroborated detections back as labels |
| [Quadrats as training data](issues/quadrats-as-training-data.md) | The proposal that became `roofclf` |
| [Calibration imagery dating](issues/calibration-imagery-dating.md) | Why ground-truth completeness is relative to an imagery date, and what closing that costs |
