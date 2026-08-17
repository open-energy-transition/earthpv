# A measured glint PSF, and why matched filtering on it does not beat the aperture statistic

!!! info "MIXED (as of 2026-08-17)"

    Two separable results from one study. The **PSF is measured** and lands where physics
    says it should: sigma 0.65 px against an optical theory range of 0.49 to 0.62 px. Using
    it as a **matched filter is rejected**: every variant tested scores below the aperture
    statistic already in the pipeline. The study's most useful output is neither of those,
    it is the **verified-negative false-spike rate of 2.0%**, which unblocks
    [the spike-rate density estimator](glint-spike-rate-density-estimator.md).

**Code:** `scripts/glint_psf_photometry.py`, `scripts/glint_psf_negatives.py`.
**Results:** `results/glint_psf/`.
**Supersedes:** `scripts/glint_psf_prototype.py` (2026-07-24), which established the idea
and never produced its headline comparison.

## The idea

Astronomy measures faint unresolved sources by fitting a known point-spread function rather
than summing an aperture, because a star is a point source whose image shape is fixed and
whose only free parameter is amplitude. A sub-pixel PV array glinting into Sentinel-2 looks
superficially like the same problem, so the same machinery should apply: measure the PSF
from strongly-validated glints, then matched-filter against it to pull weaker ones out of
the noise, and count detections against a completeness curve the way stellar densities are
derived from source counts.

The prototype implemented the first half in July 2026. It produced a kernel roughly 2 px
across against a theoretical 1.34 px, visibly non-radial, with a radial profile that never
reached zero, and its matched-filter test wrote exactly one row before Planetary Computer
SAS tokens expired under it.

## What was wrong with the prototype, and what it was not

Four defects, three of them methodological:

1. Stamps were cropped at `int(round(row))` despite the true sub-pixel centroid being
   available. Sentinel-2's 10 m PSF is undersampled (FWHM near 1.34 px, below the 2 px
   Nyquist floor), so its sampled shape genuinely changes with sub-pixel position and an
   integer-aligned stack is not a well-defined object.
2. Source extent was confounded with the PSF. A 100 to 500 m2 array spans 1 to 5 px, so its
   stamp is a PSF convolved with a finite source.
3. Each stamp was divided by its own noise-selected maximum before median stacking, which
   inflates the wings and flattens the core.
4. The test arm drew its noise floor from the *same* clear scenes it built its background
   from, so every null sample was one of the values its own background median contained.
   That biases the null spread low and inflates every significance computed against it. It
   also lacked the array-shape guard its calibration arm had.

The honest attribution matters here, because the obvious story is wrong. Running the
prototype's exact estimator on this study's stamp cache gives a radial FWHM of **1.79 px**,
implied sigma 0.76, against the forward model's **0.65 px** on the same targets. The
methodology fixes are worth about 15%, not the factor of two the original figure suggested.
The rest of the original 2.1 px was its sample, not its method. Its wing floor does mostly
go away (0.022 of peak here, against roughly 0.05 originally), and the phase spread of its
stack is confirmed uniform (0.26 and 0.29 against 0.29 expected), so the mechanism was real
even though its magnitude was not what it looked like.

## Method

Nothing is resampled, re-centred or normalised away. For each target and each scene, the
model is the target's own polygon rasterised at 1 m, convolved with a Gaussian PSF, and
block-averaged back onto **that scene's own pixel grid at the target's true sub-pixel
position**. Amplitude is a free linear parameter, fitted alongside a smooth nuisance plane
(constant plus x plus y) that is then discarded. The plane matters: a spike scene differs
from the clear-date background median by an illumination and atmospheric term that varies
gently across the window, and without absorbing it a broader kernel wins by soaking it up.
Adding the plane moved the fitted sigma from 0.70 to 0.60 px on the first 50 targets and
raised variance explained from 0.24 to 0.41.

Background and null scenes are drawn **disjointly** from each target's clear pool (8 and 12
respectively), which is the fix for defect 4 above.

Sensitivity was checked before trusting the number. Fitted sigma is unchanged at 0.70 px
across fit-box padding of 2, 4 and 6 px and across supersample factors of 5, 10 and 20, so
the fitting choices are not driving it.

## Result 1: the PSF

Fitted on 68 targets below 500 m2, where a source is close enough to a point for extent and
PSF to separate:

| quantity | value |
| --- | --- |
| sigma | **0.65 px** (90% CI 0.60 to 0.70) |
| FWHM | 1.53 px |
| ESA MTF-at-Nyquist 0.15 to 0.30 implies | sigma 0.49 to 0.62 px |

The credible interval's lower bound overlaps the theory range's upper bound. The small
excess is accounted for, and then some, by per-scene source displacement (below).

`results/glint_psf/psf_diagnostics.png` shows the fit, and the stacked observed profile
against the model now falls to zero past 2.5 px rather than sitting on a floor.

## Result 2: one PSF does not explain every size, and that is the informative part

| area bucket | n | fitted sigma (px) | median r2 |
| --- | --- | --- | --- |
| <100 m2 | 13 | 0.65 | 0.49 |
| 100 to 500 m2 | 55 | 0.65 | 0.49 |
| 500 m2 to 1k | 96 | 0.85 | 0.41 |
| 1k to 5k | 108 | 0.80 | 0.27 |
| 5k to 50k | 199 | 0.95 | 0.19 |
| >50k | 70 | 2.20 (grid ceiling) | 0.06 |

Sigma should be flat if the forward model were right, because extent is already in the
model. It is not flat, and variance explained collapses by a factor of eight across the
range. The model assumption that fails is uniform illumination: **a specular glint comes
from whichever patch of an array satisfies the mirror condition on that date, not from the
whole array**. For a small array that distinction barely exists. For a 100,000 m2 plant
perimeter it is the whole story, and broadening is the fit's only way to respond to a
misspecified shape.

This is the same conclusion the amplitude data already carried: spike amplitude is
size-independent (median 2.2 to 3.1x baseline across every bucket, measured in the earlier
500-target study), which is exactly the statement that the glinting area is not the
installation's area.

## Result 3: the source moves between scenes

Fitting a sub-pixel offset per spike scene, over 245 spike scenes across the 68 sub-500 m2
targets:

- median radial offset **0.72 px**, 90th percentile 1.34 px
- per-axis scatter 0.64 and 0.59 px, mean bias 0.16 and 0.12 px

The near-zero mean is the important part: this is scatter, not a systematic pointing error.
Two mechanisms contribute, per-scene co-registration and the moving specular patch of
Result 2, and both displace the source relative to a fixed model. A displacement scatter of
roughly 0.6 px per axis convolved with a 0.55 px optical PSF would give an effective width
above the 0.65 px measured here, so displacement more than covers the gap between the
fitted PSF and optical theory. The fitted kernel should be read as an **effective** kernel
that already contains registration, not as the instrument PSF.

## Result 4 (the useful one): the false-spike floor is 2.0%, not 8.7 to 20.3%

[The spike-rate density estimator](glint-spike-rate-density-estimator.md) has been blocked
since 2026-07-18 on a false-spike rate of 8.7 to 20.3%, measured on Lahore controls that
were only *model*-negative, equal to or above the true detection rate below 500 m2 and
therefore leaving its inversion undefined in the size regime it exists to serve. That doc's
stated next step was to re-measure against verified negatives.

600 verified negatives were drawn for this: buildings inside the 27 Rule-1 complete
calibration quadrats carrying `has_pv == 0`, so a human looked at each and found no panel.
They are size-stratified to the positives' polygon-area distribution and required to sit at
least 50 m from any mapped-PV building, so a neighbour's glint cannot leak into the window.

| condition | targets with at least one spike |
| --- | --- |
| SCL per-pixel cloud veto ON (current pipeline) | **12 / 600 = 2.0%** |
| SCL veto OFF (the pre-2026-08-11 configuration) | 27 / 600 = 4.5% |
| previously documented, model-negative controls | 8.7 to 20.3% |

The veto, shipped after the original measurement, halves the rate. It does not explain the
gap. **Verification does**: the old controls contained real unmapped PV, which is precisely
the confound that made them untrustworthy.

Against true detection rates from the 2,000-target study:

| size | true detection rate | false spike rate | ratio |
| --- | --- | --- | --- |
| <100 m2 | 3.9% | 0.5% | 7.9x |
| 100 to 500 m2 | 14.9% | 1.0% | **14.9x** |
| 500 m2 to 1k | 27.0% | 2.0% | 13.5x |
| 1k to 5k | 33.1% | 7.0% | 4.7x |

The instrument is separable in every bin measured, including the two the estimator was
declared undefined in. The false rate rises with roof size rather than falling, which is
consistent with larger roofs carrying more specular clutter (metal, HVAC plant, water
tanks) and contributing more pixels.

## Result 5: matched filtering is rejected

Two-stage design: stage 1 is the existing cheap aggregate spike rule, already run
nationally; stage 2 fits the PSF model to the pixel window of each flagged scene. Both
statistics are standardised against their own null on the same held-out clear scenes, so
the comparison is like for like.

AUC, positives against verified negatives:

| statistic | <1000 m2 | all sizes |
| --- | --- | --- |
| aperture, p98 minus annulus (existing) | **0.648** | **0.655** |
| PSF matched filter, pinned to the centroid | 0.620 | 0.525 |
| PSF matched filter, offset fitted | 0.551 | 0.496 |
| point-source matched filter, offset fitted | 0.573 | 0.485 |

Bootstrap over targets, 1,500 replicates, difference in AUC against the aperture statistic:

| variant | <1000 m2 | all sizes |
| --- | --- | --- |
| pinned | -0.027 (90% -0.100 to +0.039), P(better) 0.27 | -0.129 (-0.191 to -0.068), P 0.00 |
| offset fitted | -0.097 (-0.172 to -0.020), P 0.01 | -0.158 (-0.223 to -0.102), P 0.00 |
| point source | -0.075 (-0.163 to +0.016), P 0.08 | -0.170 (-0.232 to -0.115), P 0.00 |

Every variant is at or below the incumbent, and significantly below it over all sizes.
Allowing the offset made things **worse**, which is the expected sign when the same freedom
is granted to the null scenes: a free position raises the null's floor faster than it raises
the spikes' scores. Granting it only to the spikes would have manufactured a win.

The reason is Result 2. Matched filtering is the optimal linear detector **for a known
shape at a known position**. A glint has neither: the emitting patch varies in size, shape
and position from date to date. Against an unknown compact brightening, a near-maximum
statistic like p98 is the better detector, and that is what the pipeline already uses. The
astronomical analogy fails at exactly the property that makes stellar PSF photometry work,
which is that a star's image shape is fixed.

## Result 6: can this be inverted into a density estimator?

The natural follow-on, and the reason Result 4 matters, is to count spikes over an area and
invert them into an adoption rate. That is prevalence estimation with an imperfect test, so
the estimator is Rogan-Gladen:

    pi = (p_obs - f) / (d - f)

with `d` the detection rate on PV-bearing targets and `f` the false-spike rate. Separation
(`d > f`) makes it well-posed, which is what Result 4 established. It does not make it
precise. Every quantity below is at a true adoption rate of 10%, near the middle of the
quadrat range:

| size | d (k/n) | f (k/n) | d - f | purity of an observed spike | 90% CI on pi, 5,000 buildings scanned |
| --- | --- | --- | --- | --- | --- |
| <100 m2 | 0.039 (15/382) | 0.005 (1/200) | 0.034 | 0.47 | -61% to +25% |
| 100 to 500 m2 | 0.149 (57/382) | 0.010 (2/200) | 0.139 | 0.62 | -3.1% to +15.9% |
| 500 m2 to 1k | 0.270 (103/381) | 0.020 (2/100) | 0.250 | 0.60 | -4.2% to +15.7% |
| 1k to 5k | 0.331 (126/381) | 0.070 (7/100) | 0.261 | 0.34 | -12.1% to +20.9% |

Two things to read off it. First, **purity is poor even at 15x separation**: at 10% adoption
only a third to two thirds of observed spikes are real, because a low base rate multiplied by
a low sensitivity is comparable to a high base rate multiplied by a small false rate. Spike
counts are not a detection product; they are only ever an input to an inversion.

Second, and decisively, **the binding constraint is the calibration, not the survey**. The
interval above is dominated by uncertainty in `d` and `f`, which rest on 382 positives and
100 to 200 negatives per class, with 1 to 7 spiking negatives. Scanning more buildings in the
target area barely helps, because `f` enters the numerator directly and `d - f` the
denominator:

Half-width of the 90% interval on a 10% adoption rate, in percentage points, for the
100 to 500 m2 class:

| calibration n (pos / neg) | 2,000 scanned | 5,000 | 20,000 | 100,000 |
| --- | --- | --- | --- | --- |
| 382 / 200 (today) | 10.2 | 9.4 | 9.3 | 9.1 |
| 1,000 / 1,000 | 5.5 | 4.6 | 4.0 | 3.8 |
| 3,000 / 3,000 | 4.6 | 3.3 | 2.5 | 2.2 |
| 10,000 / 10,000 | 4.2 | 2.8 | 1.7 | 1.3 |

Going from 5,000 to 100,000 buildings scanned on today's calibration buys 0.3 pp. Going from
today's calibration to 3,000 of each buys 6 pp. The 500 m2 to 1k class behaves the same way,
starting from 6.8 pp and reaching 2.5 pp.

There is also a **stratifier mismatch** to fix before any of this is trustworthy. `d` here is
measured on OSM-mapped installations binned by *PV area*, but a survey bins buildings by
*roof area*, and PV area is the unobserved quantity being estimated. The `d` that belongs in
the inversion is "probability that a PV-bearing building of roof size s produces a spike",
measured on quadrat buildings with `has_pv == 1`. That is the same pull already built for the
negatives, pointed at the positives, and it is the prerequisite for the numbers above being
about the right population.

Restricting the survey to predicted glint windows, the obvious way to cut the pull cost, does
not help here and probably hurts: it lowers `d`, which is already the scarce quantity in the
denominator, and pose is not concentrated enough to target (the densest pose bin holds under
10% of fitted installations, see [standard-pose matched
filter](standard-pose-matched-filter.md)). Windowing raises purity, which is what a
per-target confirmation product wants, and lowers estimator efficiency, which is what a
density product wants.

Where this would nonetheless be worth building: `d` and `f` are **physical** quantities, so
unlike `roofclf` (whose ranking transfers across quadrats but whose absolute adoption rates
do not, `rate_ratio` spanning 0.2 to 5x) a glint-based estimate needs no local training data
and no mapped quadrats. That makes it a candidate independent anchor on absolute adoption in
exactly the place the current pipeline is weakest, and the only instrument here that could
work in a country with no calibration quadrats at all. The region-dependence caveat stands:
German controls showed far higher false rates than Pakistani ones, so `f` must be measured
per deployment region, not transferred.

## Limitations

- **Only 12 negatives ever spike**, so every AUC above rests on 5 to 12 negative targets and
  the per-bin intervals are wide. The detection-level result (2.0%) rests on all 600 and is
  far better constrained than the ranking-level result.
- **The 50 m isolation requirement is selective.** Only 23,852 of 102,525 verified negatives
  (23%) survive it, because in a dense quadrat almost every building is near some PV. The
  controls therefore over-represent isolated buildings. Tested directly, the false rate does
  not rise with quadrat building density (0% in the densest band, n=97; 8.1% in the 300 to
  1k band, n=74), so the selection does not appear to be driving the 2.0%, but it is not
  ruled out either.
- **Rule-1 is epoch-relative.** A control carrying an installation built after its quadrat
  was mapped counts here as a false spike, which biases the measured false rate up. A pass is
  therefore trustworthy and a marginal failure would not be.
- Positives are OSM-mapped installations nationally while negatives are quadrat buildings.
  Size is matched on the polygon actually read, but place is not. The in-quadrat positive
  subset (43 targets with a spike) is reported alongside as a robustness check and does not
  change the conclusion.
- Positives are read on the PV polygon and negatives on the roof footprint, which are
  different quantities on the same building.

## What to do with this

- **Reopen the spike-rate density estimator, but calibrate before surveying.** Its stated
  blocker is resolved: the detection-probability curve it inverts through can now be paired
  with a measured false-spike rate 8 to 15x smaller than the true rate below 500 m2. Result 6
  shows the next bottleneck is the precision of `d` and `f`, not survey size, so the useful
  next pull is roughly 3,000 verified negatives and 3,000 quadrat positives per size class,
  the latter stratified by roof area rather than PV area. That is about 5x the pull already
  done here, which took two and a half hours across four shards.
- **Do not expect a sub-100 m2 estimate.** At 3.9% sensitivity the interval is unbounded on
  the present calibration and stays wide on any realistic one. The 100 m2 to 1k range is
  where this instrument can work.
- **Do not replace the aperture statistic.** It wins, and the reason it wins is structural
  rather than a tuning artefact.
- The measured PSF (sigma 0.65 px effective, 0.49 to 0.62 px optical) is reusable for any
  future work that needs a forward model of how a small bright object lands on Sentinel-2's
  10 m grid, which is not the same claim as it being useful for detection.

---
Drafted with [Claude Code](https://claude.com/claude-code)
