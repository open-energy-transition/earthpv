# Validity and limitations

An assessment of two questions any reader should ask before citing this project's numbers:
does the pipeline measure a physical signal or statistical noise, and does the approach
scale beyond the Pakistan pilot. Written 2026-08-18 against the published Best estimate of
19,745.9 MWp (90% range 16,051 to 23,520); updated 2026-08-20 for the Best estimate's move to
**24,330.0 MWp (90% range 20,822 to 33,582)**, then 24,438.3 (20,894 to 33,666) after two 2026-10-20 corrections to how OSM, segmentation and roofclf are combined, and since 2026-10-25 34,588.8 (29,308 to 41,736) with roofclf's components priced by score rather than by a threshold (see "Where the uncertainty concentrates"), after three peri-urban calibration quadrats
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
  solar dataset (Spearman 0.87 per reference hexagon, see [Capacity
  map](../results/capacity.md#what-this-map-cannot-tell-you-and-what-an-independent-estimate-confirms-it-can)),
  with VIIRS night-lights (r = 0.75, dropping to 0.48 once building density is controlled
  for), and with the Meta Relative Wealth Index (r = 0.75, dropping to 0.45) -- see
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

Roughly 92% of the Best estimate (the sub-400 m&sup2; central component at 24,206.3 MWp
plus the &ge;400 m&sup2; roofclf rooftop replacement at 7,503.2 MWp) flows through
roofclf's coverage-ratio and area-recall calibration chain, fit on 30 purposively
selected quadrats on which the predicted-to-true adoption ratio has historically spanned
0.2x to 5x. The classifier's discrimination is real but moderate (see
[The rooftop classifier](roofclf.md) for the measured AUCs), and a per-building
classifier at that level plausibly learns some amount of *propensity* -- building type
and neighbourhood context correlated with adoption -- alongside the spectral signature of
panels themselves. The same confound surfaced explicitly in the step-change experiment.
The SPPI cross-check exists specifically as a defence here: SPPI is a zero-training,
purely spectral index, and the OSM-plus-agreement population (6,994.1 MWp) is therefore
the hardest number in the atlas.

Since 2026-10-25 that chain prices every roof by its score rather than counting the roofs
above a threshold ([roofclf](roofclf.md#count-every-roof-by-its-score)). Held out by quadrat
it is far more accurate, but it moves the weak point: the figure now leans on the score's
level being right in sparse villages, where no quadrat has tested it, rather than on a
threshold that undercounts there by design. The floor is untouched, since it stays
thresholded.

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

## Official and published figures

Each atlas draws its own total and its own provinces beside the figures a reader is likely
to know, in a section of its own ("Against official and published figures"): the national
total as points with their intervals, and, where a source publishes provinces, one row per
province with the atlas and the source side by side and their rank agreement (Spearman).
`scripts/official_capacity.py` writes the figures into
`configs/external/official_capacity.yaml`; each was checked against a fresh download of its
source, and the vintage nearest the end of the atlas's imagery window was used.

| Country | Source | As of | MW | Provinces |
| --- | --- | --- | ---: | --- |
| Pakistan | [TransitionZero](https://www.transitionzero.org/shedding-light-on-pakistans-distributed-solar-revolution), satellite-sampling estimate, distributed plus utility-scale | Oct 2025 | 29,030 (24,070 to 33,990) | 7, distributed only |
| Germany | [MaStR](https://www.marktstammdatenregister.de/MaStR/Datendownload) register, building and ground-mounted | 30 Sep 2025 | 111,961 | 16 Länder |
| France | [ODRE](https://odre.opendatasoft.com/explore/dataset/registre-national-installation-production-stockage-electricite-agrege-311224/) register, metropolitan France | 31 Dec 2024 | 24,433 | 13 regions |
| India | [MNRE](https://esankhyiki.mospi.gov.in/macroindicators?product=mnre) state-wise register | Jan 2026 | 140,602 | 35 states and territories |
| South Africa | [NTCSA (Eskom)](https://www.ntcsa.co.za/wp-content/uploads/2026/10/Weekly_System_Status_Report_2026_w43.pdf), contracted utility PV plus its estimate of all other PV | Sep 2026 | 12,210 | 9, estimate only |
| Poland | [ARE](https://www.are.waw.pl/badania-statystyczne/energetyka-w-liczbach) monthly statistics | Aug 2026 | 27,106 | none |
| Poland | [URE](https://www.ure.gov.pl/download/9/16535/MAPAOZEna30092026nastroneURE.xlsx) installation list, above 50 kW | 30 Sep 2026 | 13,440 | 16 voivodeships |
| Egypt, Morocco, Nigeria, Vietnam, Yemen, Zambia | [IRENA Renewable Capacity Statistics 2026](https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2026/Mar/IRENA_DAT_RE_Capacity_Statistics_2026.pdf) | end of 2025 | 3,247; 546; 285; 19,252; 456; 328 | none |

**None of them is ground truth for the map, and the atlas is not scored against them.** A
register counts what was registered by its date, in MW as declared (often the inverter
rating for large plants, below the module capacity the atlas counts); TransitionZero's is
another estimate with its own method; South Africa's is mostly Eskom's demand-side estimate,
which its report calls unverified; URE's list leaves out Poland's prosumer installations; and
IRENA flags its figure for each country as coming from an official source (Egypt), an
unofficial one (Vietnam, Yemen) or its own estimate (Morocco, Nigeria, Zambia). IRENA stands
in only where no national figure was found. Every Bronze and Silver atlas misses most
installations below about 400 m&sup2;, which a complete register counts, so the gap to a
register says as much about that floor as about the satellite count.

## An upper ceiling from customs data

Each atlas also shows, in the same section as the official figures above, how much
solar-panel capacity its country imported from China, from January 2017 to the end of the
atlas's imagery window. The figures come from
[Ember's China solar export data](https://ember-energy.org/data/china-solar-exports-data/)
(China's customs records, module capacity derived from export value and the month's
average price, CC-BY-4.0), summed by `scripts/ember_import_ceiling.py` into
`configs/external/ember_china_panel_imports.yaml`. Where almost every panel comes from China
and the fleet was built after 2017, that is a ceiling on what any atlas could count: some
imported panels sit in warehouses, are re-exported or are not installed yet, and none
imported later can be on the imagery.

| Country | Best estimate (MWp) | Imported from China (MWp) | Period | Best as share of it |
| --- | ---: | ---: | --- | ---: |
| Pakistan | 34,589 | 57,609 | Jan 2017 to Jun 2026 | 60% |
| Vietnam | 8,860 | 31,116 | Jan 2017 to Aug 2026 | 28% |
| South Africa | 9,756 | 18,533 | Jan 2017 to Aug 2026 | 53% |
| Egypt | 3,379 | 9,106 | Jan 2017 to Aug 2026 | 37% |
| Nigeria | 121 | 5,663 | Jan 2017 to Mar 2026 | 2% |
| Morocco | 411 | 4,817 | Jan 2017 to Aug 2026 | 9% |
| Yemen | 67 | 2,848 | Jan 2017 to Mar 2026 | 2% |
| Zambia | 526 | 827 | Jan 2017 to Oct 2025 | 64% |
| India | 99,542 | 95,060 | Jan 2017 to Mar 2026 | not a ceiling |
| Germany | 84,473 | 29,906 | Jan 2017 to Aug 2026 | not a ceiling |
| France | 13,368 | 16,196 | Jan 2017 to Sep 2024 | not a ceiling |
| Poland | 7,781 | 21,769 | Jan 2017 to Aug 2026 | not a ceiling |

**It is not a ceiling for India, Germany, France or Poland**, and those atlases say so
instead: India makes a large share of its own panels, much of Germany's and France's fleets
predate 2017, and much of the EU's Chinese supply arrives through the Netherlands and other
member states rather than directly. Poland had about 21.8 GW installed by February 2025
([Wikipedia](https://en.wikipedia.org/wiki/Solar_power_in_Poland)), against 15.3 GW of
panels imported directly from China by then. Where it is a ceiling, the gap is mostly what this project cannot see: no
Bronze or Silver atlas counts installations below about 400 m&sup2;, and the countries at
2% (Nigeria, Yemen) are ones whose solar is overwhelmingly small household and pumping
systems.

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
