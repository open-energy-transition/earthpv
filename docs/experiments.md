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
| Cell-aggregate glint density | <span class="outcome negative">rejected</span> | Wrong statistic for the question. |
| Missed-installation glint recovery | <span class="outcome negative">rejected</span> | Control false-validation rate exceeded the recovery rate. |
| Roof-axis orientation prior | <span class="outcome negative">rejected</span> | Flat concrete roofs do not constrain a tilt frame's azimuth. |
| Standard-pose matched filter | <span class="outcome negative">rejected</span> | The densest pose bin covers under 10% of installations. |
| [Glint PSF matched filter](issues/glint-psf-matched-filter.md) | <span class="outcome negative">rejected</span> | The PSF is real and measured, but every filter variant scores below the aperture statistic it would replace. |
| [Verified-negative false-spike rate](issues/glint-psf-matched-filter.md) | <span class="outcome works">shipped</span> | 2.0% against 8.7-20.3% on model-negative controls, which reopens the spike-rate density estimator. |
| Super-resolution, three variants | <span class="outcome negative">rejected</span> | No gain, and hallucination risk on a detection task. |
| Two-endmember spectral unmixing | <span class="outcome negative">rejected</span> | 0.659 AUC, worse than both SPPI and roofclf, with a 92x scale spread. |
| Epoch jump / step change as roofclf features | <span class="outcome negative">rejected</span> | Measured at exactly zero effect, and worse in the reflectance variant. |
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
