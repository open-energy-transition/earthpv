# Validity and limitations

An assessment of two questions any reader should ask before citing this project's numbers:
does the pipeline measure a physical signal or statistical noise, and does the approach
scale beyond the Pakistan pilot. Written 2026-08-18 against the published Best estimate of
19,745.9 MWp (90% range 16,051 to 23,520); updated 2026-08-20 for the Best estimate's move to
**18,826.7 MWp (90% range 16,022 to 24,358)** after three peri-urban calibration quadrats
were folded into a `roofclf` refit (see [Calibration boxes](../issues/pakistan-calibration-boxes.md)'s
Box 18) -- the analysis below is otherwise unchanged, since the move is a quadrat-composition
shift of the kind this page already discusses, not a new source of uncertainty. The short
answer to both questions is qualified: the signal is physical, but the certainty is unevenly
distributed across the pipeline, and the two halves of the workflow scale very differently.

## Evidence that the signal is physical

The evidence is strongest at the large end of the size distribution, on several
independent grounds:

- **Pixel support.** A multi-hectare ground-mount plant at Sentinel-2's 10 m ground
  sample distance covers hundreds of pixels of spectrally distinctive material. The
  land-area conversion constant is anchored to two real plants with known nameplate
  capacity (Quaid-e-Azam and Sukkur), not assumed -- see
  [Capacity density](density.md).
- **Glint follows physics.** The specular-glint detection rate rises monotonically from
  about 6% to about 73% with installation size, under sun and view geometry that is
  predictable from orbital mechanics. A monotonic, geometry-conditioned response is the
  behaviour of a real optical signal; fitted noise does not produce it. See
  [Solar glint](glint.md).
- **External correlations.** The atlas correlates with an independently produced rooftop
  solar dataset (Spearman 0.84 at cell level, see [Capacity
  map](../results/capacity.md#what-this-map-cannot-tell-you-and-what-an-independent-estimate-confirms-it-can)),
  with VIIRS night-lights (r = 0.76, dropping to 0.55 once building density is controlled
  for), and with the Meta Relative Wealth Index (r = 0.66, dropping to 0.35) -- see
  [Experiments](../experiments.md#external-corroboration-from-nightlights-and-a-wealth-index)
  for the partial-correlation caveat on the latter two. These are corroborating rather than
  conclusive, but a noise process would not produce them jointly.
- **A record of rejected instruments.** Seasonal band stacking, deep super-resolution,
  SPPI as a standalone detector, glint-date boosting, and a promising step-change signal
  (rejected by its own cropland control) were all tested and not shipped -- see
  [Experiments](../experiments.md). A pipeline converting noise into signal would be
  expected to have shipped at least some of these.

## Where the uncertainty concentrates

The distinction that matters is between *detection* and *magnitude*, and the place to
direct scrutiny is the small end of the size distribution.

Roughly 83% of the Best estimate (the sub-400 m&sup2; central component at 8,922.7 MWp
plus the &ge;400 m&sup2; roofclf rooftop replacement at 6,747.3 MWp) flows through
roofclf's coverage-ratio and area-recall calibration chain, fit on 30 purposively
selected quadrats on which the predicted-to-true adoption ratio has historically spanned
0.2x to 5x. The classifier's discrimination is real but moderate (see
[The rooftop classifier](roofclf.md) for the measured AUCs), and a per-building
classifier at that level plausibly learns some amount of *propensity* -- building type
and neighbourhood context correlated with adoption -- alongside the spectral signature of
panels themselves. The same confound surfaced explicitly in the step-change experiment.
The SPPI cross-check exists specifically as a defence here: SPPI is a zero-training,
purely spectral index, and the OSM-plus-agreement population (5,856.8 MWp) is therefore
the hardest number in the atlas.

Two structural limits on the published 90% range should be stated plainly:

- The interval prices sampling uncertainty *within* the calibration frame (quadrat
  bootstrap, conversion-constant priors, measured precision and recall). It cannot price
  the frame itself: resampling 27 purposive quadrats does not measure what happens if
  purposive selection is biased relative to the country.
- Rule-1 completeness is epoch-relative (see
  [Calibration quadrats](calibration-quadrats.md)), so measured precision and base rates
  are lower bounds and the newest installations are structurally missed. The direction of
  this bias is known; its size is not.

The domain restriction is itself a stated limitation rather than a hidden one: the
roofclf components apply only inside the density-calibrated band, currently about
two-thirds of national grid cells (covering roughly 95% of national buildings), and the
out-of-domain extrapolation was withdrawn from the published atlas on 2026-08-15 because
it was the one component not measured where it was applied.

One external anchor sits outside the calibration chain entirely. Trade-data reporting on
Pakistan's solar boom (customs and export records analysed by, among others, Ember) put
panel imports at well over ten gigawatts in 2024 alone, against an officially registered
grid-connected fleet an order of magnitude smaller. A cumulative behind-the-meter stock
near 20 GWp in 2026 is consistent with that record, and arguably conservative. The
pipeline does not use this figure anywhere; its value is precisely that it is
independent.

## Does the approach scale worldwide

The question splits the same way the pipeline does.

**The segmentation half travels as-is.** Free global imagery, an open foundation model,
open labels and building footprints, consumer-grade hardware, and an OSM validation loop
mean a new country costs roughly its compose stage. This is in line with published
facility-scale work (for example Kruitwagen et al. 2021 and Global Renewables Watch),
with the difference that the full stack here is open and reproducible. Gujarat already
demonstrates the mode: a segmentation-only atlas with no local calibration.

**The roofclf half scales in code but not in calibration.** Ranking transfers across
quadrats; absolute adoption rates do not (the measured 0.2x to 5x spread above), so each
new country needs its own quadrat set, each quadrat needs Rule-1 exhaustive mapping by an
experienced mapper, and the current gate on widening the calibrated domain is reference
imagery age -- a constraint that cannot be bought down with mapping effort (see
[Roofclf random-cell validation](roofclf-national-validation.md)). Tens of quadrats per
country, for every country, is a per-country research effort rather than a turnkey
method.

That constraint reflects the sensor, not a fixable design flaw: a 100 m&sup2; residential
array is roughly one Sentinel-2 pixel, and Germany's legally complete register shows
65.5% of rooftop capacity sits below this pipeline's 400 m&sup2; segmentation floor (see
[Validation against MaStR](mastr-validation.md)). No calibration chain turns one pixel
into a measurement; it turns it into a statistical estimate with honest intervals, which
is what this pipeline publishes. It is plausible that the sub-400 m&sup2; half is
eventually displaced -- by openly licensed sub-metre aerial imagery where it exists, by
commercial high-resolution imagery, or by fusion with administrative and trade data --
rather than by fitting quadrats in every country.

The architectural decisions are the part most likely to outlast any single number: two
instruments split at the physical detectability floor, domain-restricted estimators that
refuse to extrapolate beyond their calibration, and uncertainty that is composed from
measured sources rather than asserted. A defensible reading of the project is that its
lasting contribution is less any one national total than a demonstrated method for
stating how wrong a free-imagery estimate can be.
