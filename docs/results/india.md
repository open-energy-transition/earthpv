# India: the merge cap hid the unmapped parks, and the localized detector lost

India was composed and run between 23 September and 11 October 2026, the largest
country this pipeline has attempted: 25,576 cells of 0.1&deg;, about four times Nigeria.
Between 22 and 27 October the compose was widened to every cell within three of that
selection, 29,171 cells in all
([below](#widening-the-compose-away-from-buildings)).
Like [Zambia](zambia.md), [Nigeria](nigeria.md) and [Vietnam](vietnam.md) it started with no
calibration quadrats, no national register and no third-party PV dataset to check against.
It was run under the owner's standing instruction to **localize the segmentation** on the
country's own OpenStreetMap labels and to ship whichever checkpoint scores better on a
held-out region. Here, unlike Vietnam, the localized checkpoint lost, so this page runs on
`v5_combined_france`. It supersedes an earlier state-level Gujarat page.

Interactive: [India PV evidence atlas](../atlas-india.md).

## Headline

| | |
| --- | --- |
| Verified | **70,523.4 MWp** (90% 49,526 to 101,390) |
| Best estimate | **99,541.5 MWp** (90% 80,394 to 128,501) |
| Grid | all 29,171 selected cells of 0.1&deg; (97.1% of India's 30,056), 35 of 36 states and union territories (geoBoundaries) |
| Imagery | Sentinel-2 L2A, November 2025 to March 2026 |
| Model | `v5_combined_france` epoch 25 (the localized `v10_combined_india` lost; see below) |

!!! note "Revised the day it was published"
    This page first went out on 11 October with Best at 75,855.7 MWp (90% 66,332 to
    99,761). Later that day two defects in how mapped park outlines enter Best were
    fixed, both described
    [in the screen section](#the-ground-perimeter-screen-and-the-5-km2-cap): the Khavda
    outlines the screen rejects had come back into Best whole, and 101 park outlines had
    been placed on rooftops. Best fell by 3,584.6 MWp; Verified did not move.

!!! note "Widened on 28 October"
    Until 28 October this page read Best 72,271.1 MWp (90% 63,487 to 98,370) on 25,579
    cells. The compose widening described
    [below](#widening-the-compose-away-from-buildings) raised it by 434.0 MWp. Most of the
    rise is Khavda's park outlines, now imaged whole; about 220 MWp is false positives on
    Himalayan slopes, which the page carries. Verified did not move.

!!! note "Revised on 29 October"
    Until 29 October this page read Best 72,705.1 MWp (90% 63,865 to 98,370) and Verified
    67,592.6 MWp. Two size rules were keeping real installations out. Model outlines above
    the 100,000 m&sup2; merge cap with no mapped solar nearby were excluded, though most
    are solar parks OpenStreetMap does not hold yet; they now count at a reviewed share
    ([below](#parks-the-model-found-that-nobody-has-mapped)), which raised Best by about
    25,400 MWp. Mapped outlines above 5 km&sup2; that fail the ground screen were dropped
    from Verified and came into Best at half their detected share; both tiers now carry
    them at that share ([below](#the-ground-perimeter-screen-and-the-5-km2-cap)), which
    raised Verified by 2,930.8 MWp and Best by about 1,500. Best rose by 26,836.4 MWp in all.
    Against MNRE's state-wise register, ground-mounted Best is now 0.88 of the registered
    capacity ([below](#against-the-mnre-register)), about 0.64 before.

!!! warning "A precision floor, not an estimate"
    India has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    at all below the 400 m&sup2; segmentation floor. It has no glint sample, so
    `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction, except
    for the model outlines above the merge cap, which a manual review prices. Recall
    was deliberately skipped (`--recall-reference none`). For scale, MNRE puts India's
    installed solar at 171.05 GW, of which 125.65 GW is ground-mounted and 33.41 GW
    grid-connected rooftop
    ([MNRE physical progress](https://mnre.gov.in/en/physical-progress/); the page's heading
    says 31 August 2026 and its table 30 September). The household rooftop programme alone
    had installed about 14.07 GW across 39.38 lakh systems by 20 July 2026, about 3.6 kW
    each
    ([Energetica India](https://www.energetica-india.net/news/pm-surya-ghar-crosses-39-38-lakh-rooftop-solar-installations-capacity-reaches-14-07-gw)).
    A 3.6 kW system is about 20 m&sup2; of panel, a fifth of one Sentinel-2 pixel: the same
    size regime in which [France](france.md) showed this sensor cannot see rooftop PV.

## Localizing the detector, and why v5 ships

**Labels.** 24,810 OpenStreetMap solar features inside India (3,751 rooftop, 20,887
ground, 172 unclassified), out of 53,138 in the country's bounding box. Like Vietnam's, the
mapped population is dominated by utility parks.

**Holdout, inherited rather than re-picked.** Gujarat's Surat-Bharuch-Vadodara box (lon 72.7
to 73.9, lat 21.0 to 23.0), 240 cells. v5 held this box out of its own Gujarat corpus, so
both checkpoints are scored out of sample on it, and inheriting it left no free choice.
Training chips in the one-cell ring around it were dropped (13 chips).

**Corpus and recipe.** 5,167 train and 82 val chips (3,872 with PV). India's chips replace
the Gujarat corpus in v5's mix, since they already cover Gujarat, and were weighted x1
(`round(7000 / 5,167)`), giving 29,740 rows with India at 17.7%. The recipe is v5's
verbatim. Best epoch 13, early-stopped at epoch 21, 6.4 hours on the GTX 1060.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 82 held-out chips:

| | v5 | v10 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | **0.938** (241 of 257) | 0.911 (234 of 257) |
| pixel IoU | **0.686** | 0.663 |
| pixel F1 | **0.814** | 0.798 |

The rule compares recall first, and a difference above 0.02 decides: v5 ships. The margin
is seven installations of 257 on one holdout, which is not strong evidence that
localization hurts in India. It is evidence that it did not help: v5 already carries
Gujarat's chips from outside this box, and India's labels are 84% ground-mount, the
population every earlier corpus already covers well. Vietnam's localized checkpoint won on
outline quality (IoU 0.724 to 0.762) with recall tied; India's lost on both.

**The whole-country comparison**, after the atlas (`compare_checkpoints_vs_mapped.py`, both
checkpoints inferred over all 25,576 cells, scored against the 4,010 dissolved mapped
installations of 400 m&sup2; and up that both imaged), finished on 13 October:

| | v5 (ships) | v10 (localized) |
| --- | --- | --- |
| pooled recall over mapped installations | **0.501** (2,011) | 0.441 (1,767) |
| recall, 500 to 50,000 m&sup2; | **0.698** (1,314 of 1,883) | 0.606 (1,141) |
| recall above 50,000 m&sup2;, counting candidates above the cap | 0.937 | 0.936 |
| candidates below the 100,000 m&sup2; merge cap | 92,139 | **33,454** |
| median candidate area | 1,601 m&sup2; | 5,104 m&sup2; |
| total candidate area below the cap | 528.1 km&sup2; | 505.5 km&sup2; |
| candidates above the cap | 3,242 (2,081 km&sup2;) | 4,485 (2,472 km&sup2;) |
| rooftop share below the cap | 35.2% | 30.7% |

The script drops candidates above the merge cap, as `density` does, and India's parks are
mostly found by exactly such candidates, so its own recall for the 2,066 installations above
50,000 m&sup2; reads 0.32 and 0.29. Counting them, both checkpoints find 94% of the parks; the
difference is in the arrays between 500 and 50,000 m&sup2;. **This recall favours v10 and v10
still loses**: it trained on every Indian label outside the Gujarat box, so it is scored here
largely in-sample, while v5's only Indian training data is Gujarat's chips. 338 installations are found by v5
alone against 94 by v10 alone (McNemar p < 0.001). In Vietnam the localized checkpoint drew
fewer, larger candidates and kept its recall; v10 draws 64% fewer candidates at three times
the median area, holds about the same total area below the cap, merges about 1,250 more
model-drawn blobs above it and finds fewer mapped arrays. The diagnostic confirms the
holdout decision rather than qualifying it.

## A compose defect, found here and fixed for every later country

Rewa Ultra Mega Solar (750 MW, fully mapped) came out of the ground-perimeter screen as
**0% imaged**. Its two cells were 87% empty. `annual_composite` kept the twelve scenes with
the lowest `eo:cloud_cover`, a property of the whole MGRS tile, and in India's dry season
dozens of scenes tie at 0.0%. For Rewa's cell all twelve came from tile 44QNM, which covers
11% of the cell, while equally cloud-free 44RNN scenes covering all of it ranked 15th and
below. A second defect shows up in the same composites: about 33,000 failed range requests
during India's compose, silently turned into zeros, left 1.3% of cells with at least one band
entirely missing, and on such a cell the model mostly detects nothing.

On a random sample of 3,000 Indian composites, 1.3% of cells have a tile-edge gap above 5%
and together they lose 0.79% of imaged area. Nationally that is small; for Rewa it removed a
750 MW park from Verified, because the ground cap described below keeps a perimeter above
5 km&sup2; only on imaging evidence. Both defects are fixed in `imagery.py` for every
composite built from 2026-10-10 on, and Rewa's cell recomposed with the fix is 0.0% empty.
**India was not recomposited**; the affected cells are
left for the next rebuild.

## The ground-perimeter screen and the 5 km&sup2; cap

3,481 OSM ground perimeters of 50,000 m&sup2; or more (2,221 km&sup2; together): on average
98.6% of each is imaged, and the model detects PV over a median 98.5% of each. 3,370 screen
as detected, 75 as worth a look, 36 as insufficiently imaged (since the widening; it was
3,365 and 41 before).

56 perimeters exceed the 5 km&sup2; cap (751 km&sup2;). The evidence gate introduced for
Vietnam keeps a feature above the cap only when it is imaged and at least 50% detected: 47
are kept, among them Bhadla (48.3 km&sup2;), Pavagada (42.9), Kurnool (23.9), Ananthapuramu
(20.8) and Charanka (14.8). Nine are dropped, and the gate is visibly doing its job on the
two largest: the Khavda Renewable Energy Park outline (88.3 km&sup2;, tagged 1,000 MW) and
NTPC Khavda (62.0 km&sup2;, 397.7 MW) are 28% and 32% detected now that both are imaged
whole (19% and 22% of what was imaged before the widening), and their own capacity tags
imply 0.011 and 0.006 kWp/m&sup2;, i.e. outlines drawn around a planned zone that is mostly
still desert. So are a third Khavda outline (23.3 km&sup2;, 18% detected) and a 7.9 km&sup2;
outline in Rajasthan with 0.06% detected. The other five are wrong drops, all on imaging rather than on evidence of absence: Rewa's two overlapping
outlines, for the reason above, and three parks of 5.1 to 5.9 km&sup2; that are 76 to 94%
detected where imaged but only 24 to 77% imaged.

**Best now applies the same gate.** As first published, the gate covered Verified only and
its drops came back through the model: `postprocess` substitutes a mapped outline for the
model candidate it matches, and `density` exempts OSM geometry from the 100,000 m&sup2;
cap, so the Khavda RE Park and NTPC Khavda outlines entered Best whole, 3,789 MWp in their
two cells (5.0% of that day's Best) against zero in Verified. `density` now applies the
gate's evidence rule on the model side as well: an outline above 5 km&sup2; that fails it
is credited at its area times the share of its imaged part the model detects, and an
outline with nothing imaged earns nothing. The two Khavda cells fell to **796.4 MWp**
(30.7 of 150.2 km&sup2; credited; **1,122.9 MWp** and 44.6 km&sup2; since the widening
imaged the rest of both outlines) and the Rajasthan outline from 199.4 MWp to zero. The
three partly imaged parks keep 76 to 94% of their area, since an unimaged part is a
compose gap, not evidence of absence. Refusing the exemption outright would have been wrong
the other way: the model's own polygons at Khavda are merged blobs above the cap, so a zone
with several GW operating would have dropped to almost nothing.

**Verified now carries them at the same share (29 October).** The model-side credit was
discounted twice: `density` prices every candidate of its size bin at the bin's `p_real`,
0.503 for the largest ground bin, so the 44.6 km&sup2; detected at Khavda reached Best as
1,122.9 MWp, half of what that area is worth at the land constant. With the outlines absent
from Verified, nothing restored the other half. `prepare_national_osm_solar.py` now keeps
such an outline in Verified at its detected share instead of dropping it, and Best takes it
through its per-cell floor: the two Khavda cells carry **2,230.0 MWp** in both tiers. The
same rule floors the credit at the plants mapped inside an outline, which matters where the
cap's dissolve had merged a 3.1 to 3.8 km&sup2; park into the 5.1 to 5.9 km&sup2; site around
it; for India's three partly imaged parks the detected share is the larger figure anyway.
Seven outlines are credited, 58.6 of 190.3 km&sup2;, adding 2,930.8 MWp to Verified. Only
Rewa still earns nothing, for want of imagery. The detected share is itself a floor at
Khavda: over the dark panel blocks inside both outlines the model lights up the block edges
and not their interiors, so more of each outline is built than 28% and 32%.

**A mapped park outline is never rooftop.** `postprocess` places a candidate by its overlap
with VIDA footprints, and VIDA traces a park's panel rows as buildings, so 101 of the
exempt outlines (50.5 km&sup2;) had been placed `rooftop`, converted at the module
constant and priced at the rooftop `p_real`. They held 2,891 of the 4,109 MWp the model
reported as rooftop, and they had also set the largest rooftop bin's `p_real` (0.318; 0.171
without them). The OSM layer already reclassified a rooftop feature this large as ground;
the candidate side now does the same, and the precision table was re-derived on the
corrected population.

**The land constant holds here.** Of the kept parks above 5 km&sup2;, eleven carry a
capacity tag: 9,658 MW on 214.7 km&sup2;, **0.045 kWp/m&sup2;** pooled (median 0.047, IQR
0.042 to 0.049) against the 0.05 the atlas assumes, which was calibrated on two Pakistani
plants. Indian parks usually quote AC capacity, so the DC figure is somewhat higher, closer
to the constant. This is the measurement Vietnam's page listed as missing; Germany's
register put German plants at 0.081 and Zambia's two measured plants at 0.085, so the
constant is not universal, but it fits the Indian utility-scale fleet.

## Parks the model found that nobody has mapped

`density` keeps model outlines above 100,000 m&sup2; out of capacity
(`postprocess.MAX_CANDIDATE_M2`), because in Pakistan, where the rule was made, such outlines
were merged sheets of false positives on bright bare ground. In India they are mostly solar
parks. On 28 October the outlines above the cap with no mapped solar within 100 m (the
export's own new-lead rule; 1,789 outlines, 659.1 km&sup2;) were checked on imagery:

| | outlines | area | real |
| --- | ---: | ---: | --- |
| census: the 30 largest, 2.5 to 11.7 km&sup2; | 30 | 153.8 km&sup2; | 30 |
| sample: 60 drawn from the rest by area, without replacement | 60 | | 51 |
| of which in the six Himalayan states and territories | 2 | | 0 |

Every sampled outline was judged on the November to March Sentinel-2 composite and on Esri
World Imagery with its capture date, by the owner on the disk review page
(`scripts/oversize_review.py`, four panels per outline). The owner's verdicts agree with the
assistant's first pass on 86 of 90; a joint recheck of the other four kept three as not PV
(a Himalayan slope, ploughed fields on Esri imagery of March 2026, and an outline that reads
as water where Esri is from 2019) and found the assistant wrong on one park. 40 of the 51
parks show panel rows on Esri; 11 show bare or freshly cleared ground on an Esri capture
from 2022 to mid-2025 and panel blocks on the composite, i.e. parks built since. The nine
that are not PV are two Himalayan slopes (one beside a glacial river), rock, the outline
that reads as water, dark ploughed fields twice, grassland and burnt scrub twice. Because
the sample is drawn by area, its share real (51 of 58 outside the Himalaya, 0.879, 90%
0.793 to 0.934) is an area share. The 30 largest Khavda, Bhadla,
Pavagada-sized outlines next to the mapped parks are all real: four of them, 42.1 km&sup2;,
are operating Khavda parks outside both mapped Khavda outlines.

The review is stored in India's calibration table (`oversize_review`, written by
`scripts/oversize_review.py apply` from `results/india_oversize_review/review.csv`), and
`density` now admits these outlines: always as ground, the census at full credit and the
rest at the sample's share, with the share's posterior in the interval and no recall
correction. The six Himalayan states and territories keep the cap, since both outlines drawn
there were terrain. **1,650 outlines are admitted, 626.4 km&sup2; of outline credited as
569.4 km&sup2;, adding 28,468 MWp to the model's estimate and about 25,400 to Best** (the
rest lands in cells Verified already floors). Gujarat's Best rises from 7,800 to 15,601
MWp; the Khavda window holds 4,478 MWp against 1,131 before.

Two things this does not settle. The land constant is applied to the model's outline, which runs about 12% larger
than the mapped perimeter where both exist, so the admitted figure may read up to a tenth
high. And 376 outlines above the cap are still excluded: 139 in the Himalaya and 237 within
100 m of mapped solar, whose mapped part counts from the map but whose unmapped remainder
(about 48 km&sup2;) was not reviewed.

## Widening the compose away from buildings

The first run imaged a cell only if it held at least 1,000 buildings or a mapped solar
feature, so a park built on empty land and not yet mapped could not be seen. On the owner's
request (22 October) `ring_cells: 3` added every cell within three cells (about 33 km) of
that selection: 3,573 cells, composed between 22 and 25 October and run through the same
chain on the same checkpoint, labels, screen rule and imagery window
(`scripts/run_india_ring_chain.sh`). The ring is the only change. Measured before it ran,
97.3% of mapped ground-PV area already sat in selected cells, so the widening was
insurance rather than a known gap.

| | before | after |
| --- | --- | --- |
| cells imaged | 25,579 | **29,171** (97.1% of the country) |
| Verified | 67,592.6 MWp | 67,592.6 MWp |
| Best | 72,271.1 MWp | **72,705.1 MWp** |
| model estimate (`est_mwp_rc`) | 32,868.2 MWp | 32,467.5 MWp |
| candidates | 95,381 | 104,968 |

Best rose by 434.0 MWp, from four sources:

- **Khavda, imaged whole: about +330 MWp.** Six of the eight mapped outline cells left
  uncomposed by the first run were at Khavda, so the RE Park and NTPC Khavda outlines were
  80% and 46% imaged. Both are now fully imaged, the share of them the model detects rose
  from 30.7 to 44.6 km&sup2;, and their two cells went from 796.4 to 1,122.9 MWp (Gujarat's
  Best +307.2 MWp). Every cell touched by a mapped outline now has imagery.
- **Mountain false positives: about +220 MWp.** Of the 249.6 MWp the model finds in the new
  cells, 221.1 MWp lies in six Himalayan states and territories. Their Best moved by:
  Arunachal Pradesh +76.7, Uttarakhand +52.9, Ladakh +42.7, Himachal Pradesh +23.6,
  Jammu and Kashmir +11.1 and Sikkim +9.2 MWp. On every high-scoring mountain cell inspected, the detections
  sit on shaded slopes and snow edges beside masked pixels, not on panels. They are 0.3%
  of Best, inside its interval. The page keeps them, the plausibility gate flags them, and
  no veto is applied yet.
- **New cells elsewhere: about +23 MWp**, mostly small detections in Rajasthan and Gujarat
  (and the parks below, which are leads, not capacity).
- **A slightly lower precision floor everywhere: about -140 MWp.** India's `p_real` is the
  OSM-mapped share of candidates in each size bin, and the 9,572 new candidates are all
  unmapped, so every bin's share fell (the largest ground bin from 0.518 to 0.503). Outside
  Khavda, the model's estimate in the old cells fell by 976.8 MWp. Their Best fell by only
  142.2 MWp, because most of those cells are floored at their Verified value.

The widening also did what it was for. Of the 9,566 new leads in the added cells, 126 are
model outlines above the 100,000 m&sup2; merge cap. Those counted as leads, not capacity,
until 29 October; the ones with no mapped solar nearby now count at the reviewed share
([above](#parks-the-model-found-that-nobody-has-mapped)). Among them are a solar park west of Jaisalmer (70.31&deg;E 27.06&deg;N, a 1.2 km&sup2;
outline with no OpenStreetMap solar feature within 3 km) and a 5.7 km&sup2; outline near
Bikaner (73.23&deg;E 28.33&deg;N) next to a partly mapped park. Both show panel rows on the
composite. They are in `india_pv_new_leads.geojson`, and the Jaisalmer park is now counted.

## Plausibility gate

`earthpv check-density` reports **21 fail and 10 suspect of 35 regions**. All 21 fail the
ground-to-rooftop ratio above 5x, from Haryana (5.5x) to Rajasthan (173x) and Arunachal
Pradesh (625x); nationally the model's estimate is 59,979 MWp ground against 841 MWp
rooftop, 71x (31,555 against 841, 38x, before the unmapped parks were admitted).
MNRE's own split is 3.8x (125.65 GW against 33.41 GW). As in [France](france.md), the gate
is firing on the missing rooftop denominator: the household programme's 3.6 kW systems are
below what this sensor can see, so every regional ratio is inflated. The ratios read worse
than on the first version of this page (12 fail, national 8.1x) because most of what the
model then called rooftop was park outlines (see the screen section above). Arunachal
Pradesh and Himachal Pradesh fail only since the widening, and there the gate is right:
their new ground-mount is mountain false positives
([below](#widening-the-compose-away-from-buildings)).

Two regions also fail the single-cell check, and each flagged cell holds a reviewed park:
Bihar's cell at 86.2&deg;E 25.1&deg;N (36% of the state) is one of the 30 largest unmapped
outlines, all parks, and West Bengal's at 87.1&deg;E 22.7&deg;N (28%) one of the sampled
outlines with panel rows on Esri. The six regions that failed on concentration before
(Pavagada in Karnataka, the Ananthapuramu park in Andhra Pradesh, mapped plants in
Chhattisgarh, Kerala, Assam and Jharkhand) no longer do: the admitted parks spread each
state's total over more cells. The check exists to catch ground-mount false positives on
bright bare land; here the ground area is mapped plant outlines the screen shows detected
over a median 98.5%, and model outlines a review found real. Published with the flags
stated, per this project's precedent for a checked-genuine failure.

## Candidate population

104,968 candidates: 32,575 rooftop, 25,402 ground-adjacent, 46,991 with no building,
median 1,699 m&sup2;. 2,026 model-drawn candidates exceed the 100,000 m&sup2; merge cap.
1,650 of them, with no mapped solar within 100 m and outside the Himalaya, are admitted at
the reviewed share (626.4 km&sup2;, credited as 569.4); the other 376 (11.4% of candidate
area, the largest 30.27 km&sup2;) stay excluded. A further 1,332 oversize candidates carry an
OSM-verified plant geometry and are exempt, all counted as ground, six of them at their
detected share (58.6 of 174.3 km&sup2;). The model's own estimate (`est_mwp_rc`) is
**60,935.1 MWp** (90% 40,222 to 88,581), 843.5 rooftop and 60,091.6 ground; with no recall
reference it equals the precision-weighted `est_mwp_cal_total`. 27.3 GW of it is the
OSM-outline candidates above the cap, each weighted by the largest ground bin's `p_real` of
0.503, and 28.5 GW the admitted outlines. The probability-weighted `est_mwp_exp`, which does
not use the candidate population, is 29,545.4 MWp.

**Verified is almost all ground-mount.** It is the hand-mapped layer at the two constants:
1,389.8 km&sup2; of dissolved ground perimeters (58.6 of them the credited share of the seven
outlines above 5 km&sup2;) against 9.3 km&sup2; of rooftop polygons. Best adds 29,018.1 MWp
on top, model detections outside anything Verified counts, most of it the admitted
unmapped parks.

Solar-thermal is counted as PV on this page. OpenStreetMap tags concentrated-solar plants
and rooftop water heaters with the same `generator:source=solar` the label pull selects,
and India's labels were built before that was noticed (Morocco's, run next, turned out to
be half solar-thermal). It was measured the day after publication, by looking the label
elements up by OSM id (`scripts/drop_solar_thermal.py --by-id`), since the area scans the
other countries use failed on every public mirror at India's size: 253 of the 24,810 label
features are solar-thermal, 9.4 km&sup2; once dissolved, among them the Dhirubhai Ambani
(100 MW), Megha (50 MW) and Godawari (50 MW) concentrated-solar plants. Ten features of the
hand-mapped layer lie mostly inside them and carry 473 MWp at the two constants, about 0.7%
of Verified and of Best. They are not removed on this page: dropping the four model
candidates that sit on the same plants rewrites the candidate file, which rebuilds the
density stage over all 25,576 cells (about 31 hours) for a change well inside either
interval. The widening rebuilt it anyway, and ran the candidate filter, which changed
nothing: it drops candidates inside thermal elements already removed from the labels, and
India's labels never were. Every country run after India filters it
(`scripts/drop_solar_thermal.py`).

## Against the MNRE register

MNRE's state-wise installed solar capacity, republished monthly by MoSPI's eSankhyiki
([macroindicators, product MNRE](https://esankhyiki.mospi.gov.in/macroindicators?product=mnre)),
is India's register for this page: MW per state and month in four categories, ground-mounted,
rooftop (including PM Surya Ghar), the solar part of wind-solar hybrid plants, and
off-grid/KUSUM. `scripts/validate_india_mnre.py` fetches it through MoSPI's own MCP server and
compares it state by state with the atlas (`results/india_mnre_validation/`). The register
grew from 132.8 to 150.3 GW of solar between November 2025 and March 2026, the ends of the
imagery window, so the comparison is made at its centre, January 2026 (140.6 GW).

| | this page | MNRE, January 2026 | ratio |
| --- | ---: | ---: | ---: |
| ground-mounted (+ hybrid solar), Best | 97,560 MWp | 110,619 MW | **0.88** |
| ground-mounted (+ hybrid solar), Verified | 68,789 MWp | 110,619 MW | 0.62 |
| rooftop | 1,830 MWp | 24,297 MW | 0.075 |
| off-grid / KUSUM | not measured | 5,634 MW | |
| all solar, Best | 99,390 MWp | 140,550 MW | 0.71 |

The ground ratio is 0.94 against November's register and 0.82 against March's. Registered
utility capacity in India is mostly quoted AC and this page's in DC: India's own
capacity-tagged parks put site area at 0.045 per AC kW against the 0.05 the page converts at,
so on an AC basis the ground ratio is 0.79. **The ground-mounted figure is about a fifth short,
and it was a third short (about 0.64) before the unmapped parks above the merge cap were
counted.** What remains short is the parks this page does not see: Rewa and the other
unimaged outlines, the Himalayan outlines left out, the unmapped part of the 237 outlines
that touch a mapped park, dark block interiors the model does not light up, and parks
commissioned in the window that the median composite does not yet show.

**The geography holds.** Across the 19 states with at least 100 MW of registered utility PV,
the rank correlation between Best and the register is 0.95, 14 states are within a factor
of 1.5, and the median state is off by 24% (median absolute log ratio 0.22). The four largest
are Rajasthan 31.1 GW against 35.0 (0.89), Gujarat 15.4 against 20.2 (0.76), Karnataka 10.4
against 10.0 (1.05) and Tamil Nadu 8.3 against 10.3 (0.80). The largest shortfalls are in the
Himalaya, where the admitted outlines are left out (Himachal Pradesh 0.25, Uttarakhand 0.62),
and Maharashtra (0.66). The page is high in small states: Punjab 1.45, Haryana 1.56, Bihar
2.09 and, by far, Jharkhand, 244 MWp against 21 MW registered, of which 134 MWp is
hand-mapped outlines; whether those are captive or mislabelled plants, or a gap in the
register, is not settled here.

**Rooftop is where the sensor stops.** The register's 24.3 GW of rooftop is mostly household
systems of a few kW, about 20 m&sup2; of panel each, and this page sees 7.5% of it, the large
commercial roofs. The register does not geolocate units, so unlike Germany's it cannot
measure the precision of individual candidates; it checks totals per state and month.

## Against the old Gujarat page

The earlier Gujarat page reported 812.6 MWp (`est_mwp_rc`) over its bounding box,
of which Gujarat state was 765.0 (168.7 rooftop, 596.3 ground). The same estimator here
gives the state **11,579.8 MWp** (93.3 rooftop, 11,486.5 ground), and the atlas puts it at
Verified 8,587.8 and Best 15,601.4 MWp over 1,617 cells (4,783.7 MWp, Verified 5,852.3 and
Best 7,800.1 before the unmapped parks were admitted on 29 October; 4,554.1 MWp and Best
7,492.9 over 1,423 cells before the widening).

Against the old page, almost all of the rise to 4,783.7 MWp is one rule. The Gujarat run (2026-08-07) excluded every candidate
above 100,000 m&sup2;, including those carrying a mapped plant's outline; `density` began
exempting OSM geometry from the cap three days later. Those 136 candidates (156.3
km&sup2; credited) are about 3.9 GW of the new state figure, 1.1 GW of it the two Khavda
outlines at their detected share. The rest is a different checkpoint (v5, where the old
page used one since deleted) and a national precision table in place of Gujarat's own (the
largest ground bin's `p_real` is 0.518 here against 0.309).

## Operational notes

Compose built 25,576 of 25,590 selected cells between 25 September and 8 October, about 83
cells per hour sustained, with the network hardening described on the
[Vietnam page](vietnam.md#operational-notes) in place from the start. systemd-oomd killed the
compose unit about once a day at its 12 GB cap (20 times in all) and the queue restarted it
each time; a stretch of DNS failures on 1 October (the router's rotating IPv6 resolver) cost
about 1,100 cell attempts that later passes recovered.

Training ran at a milestone (every label cell plus 3,000 density cells composited), and v5
inference then ran every six hours behind the still-running compose, so only the last
cells remained when compose finished. Postprocess needed `--stream-buildings` (per
0.25&deg; chunk instead of a national building table) and took 23.7 hours. The host was
rebooted at 89% of the density stage, 28 hours in; `density` now records its candidate
fingerprint at the start of a first run, so an interrupted run resumes instead of starting
over.

The widening's 3,573 cells were composed between 22 and 25 October, at about 55 cells per
hour, with v5 inference running every three hours behind the compose. A wrapper relaunched
the compose unit after a network stall. Postprocess reused the published building join for
every 0.25&deg; chunk whose candidates had not changed (`--reuse-join`), which brought it
from 23.7 hours to 4.9. The density stage then rebuilt every cell (`--force`, since the
candidate file had changed) in 38.8 hours. The run before the widening is kept outside the
repository for comparison.

## What India needs next

**A calibration quadrat in a rooftop-dense area.** Almost all of India's rooftop capacity is
below this page's floor. Gujarat leads the household programme by state, so a box there is
the obvious first one. Check the imagery date before drawing it; see the
[quadrat protocol](../calibration-mapping-protocol.md).

**Recomposite the affected cells**, Rewa first. Its two outlines (16.0 and 10.5
km&sup2;) are still unimaged; the widening added cells but rebuilt none.

**A terrain veto for model candidates with no building nearby.** The widening's mountain
false positives sit on steep shaded slopes. A slope test like the one the farm ground-PV
detector already applies (12&deg; on Copernicus GLO-90) would likely remove them, but it
is a new rule for every country's segmentation half and needs a full density rebuild.

**The rest of the outlines above the cap.** The 237 that touch mapped solar, whose
unmapped remainder is still uncounted, are the next population to review, and the outline
in Madhya Pradesh priced as water needs a current image.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox 68.0,6.7,97.5,37.1 \
  --iso3 IND --name india --tiles 14x14 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-vn-in-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_vn_in_queue.sh
```

The queue composes India behind Vietnam and hands it to `scripts/run_country_compute.sh
india` (chips at the training milestone, training, the v5 comparison, incremental inference
and the atlas chain, behind marker files). The widening is `ring_cells: 3` in
`configs/aoi.yaml`, a compose run, and then everything downstream of it:

```bash
systemd-run --user --collect --unit=earthpv-india-ring-chain -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=14G bash scripts/run_india_ring_chain.sh
```

The two size rules of 29 October need no rebuild of the cell partials: the review goes into
the calibration table, the OSM layer is rebuilt with its screen, and `density` (without
`--force`) and the atlas re-run:

```bash
pixi run python scripts/oversize_review.py apply --aoi india \
  --exclude-region "Uttarākhand" --exclude-region "Himāchal Pradesh" --exclude-region "Ladākh" \
  --exclude-region "Jammu and Kashmīr" --exclude-region "Sikkim" \
  --exclude-region "Arunāchal Pradesh" --reviewer "..."
pixi run python scripts/prepare_national_osm_solar.py --aoi india \
  --labels data/labels/india_overpass_solar.parquet \
  --keep-detected-screen results/india_osm_ground_screen/screen_full.csv
pixi run earthpv density --aoi india --districts
pixi run earthpv atlas --aoi india --osm-solar data/labels/india_national_osm_solar.parquet \
  --include-offgrid-osm --imagery-date-range "Nov 2025 - Mar 2026"
```
