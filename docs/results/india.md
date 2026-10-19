# India: the localized detector lost, and a compose defect hid a 750 MW park

India was composed and run between 23 September and 11 October 2026, the largest
country this pipeline has attempted: 25,576 cells of 0.1&deg;, about four times Nigeria.
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
| Verified | **67,592.6 MWp** (90% 47,486 to 97,145) |
| Best estimate | **72,271.1 MWp** (90% 63,487 to 98,370) |
| Grid | 25,576 of 25,590 selected cells of 0.1&deg;, 35 of 36 states and union territories (geoBoundaries) |
| Imagery | Sentinel-2 L2A, November 2025 to March 2026 |
| Model | `v5_combined_france` epoch 25 (the localized `v10_combined_india` lost; see below) |

!!! note "Revised the day it was published"
    This page first went out on 11 October with Best at 75,855.7 MWp (90% 66,332 to
    99,761). Later that day two defects in how mapped park outlines enter Best were
    fixed, both described
    [in the screen section](#the-ground-perimeter-screen-and-the-5-km2-cap): the Khavda
    outlines the screen rejects had come back into Best whole, and 101 park outlines had
    been placed on rooftops. Best fell by 3,584.6 MWp; Verified did not move.

!!! warning "A precision floor, not an estimate"
    India has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    at all below the 400 m&sup2; segmentation floor. It has no glint sample, so
    `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction. Recall
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

3,481 OSM ground perimeters of 50,000 m&sup2; or more (2,221 km&sup2; together): 98.5% of
their area is imaged, and the model detects PV over a median 98.5% of each. 3,365 screen as
detected, 75 as worth a look, 41 as insufficiently imaged.

56 perimeters exceed the 5 km&sup2; cap (751 km&sup2;). The evidence gate introduced for
Vietnam keeps a feature above the cap only when it is imaged and at least 50% detected: 47
are kept, among them Bhadla (48.3 km&sup2;), Pavagada (42.9), Kurnool (23.9), Ananthapuramu
(20.8) and Charanka (14.8). Nine are dropped, and the gate is visibly doing its job on the
two largest: the Khavda Renewable Energy Park outline (88.3 km&sup2;, tagged 1,000 MW) and
NTPC Khavda (62.0 km&sup2;, 397.7 MW) are 19% and 22% detected, and their own capacity tags
imply 0.011 and 0.006 kWp/m&sup2;, i.e. outlines drawn around a planned zone that is mostly
still desert. So are a third Khavda outline (23.3 km&sup2;, 16% detected) and a 7.9 km&sup2;
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
outline with nothing imaged earns nothing. The two Khavda cells fall to **796.4 MWp**
(30.7 of 150.2 km&sup2; credited) and the Rajasthan outline from 199.4 MWp to zero. The
three partly imaged parks keep 76 to 94% of their area, since an unimaged part is a
compose gap, not evidence of absence. Refusing the exemption outright would have been wrong
the other way: the model's own polygons at Khavda are merged blobs above the cap, so a zone
with several GW operating would have dropped to almost nothing.

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

## Plausibility gate

`earthpv check-density` reports **17 fail and 9 suspect of 35 regions**. Sixteen of the
seventeen fail the ground-to-rooftop ratio above 5x, from Punjab (7.8x) to Rajasthan
(108x); nationally the model's estimate is 32,025 MWp ground against 843 MWp rooftop, 38x.
MNRE's own split is 3.8x (125.65 GW against 33.41 GW). As in [France](france.md), the gate
is firing on the missing rooftop denominator: the household programme's 3.6 kW systems are
below what this sensor can see, so every regional ratio is inflated. The ratios read worse
than on the first version of this page (12 fail, national 8.1x) because most of what the
model then called rooftop was park outlines (see the screen section above).

Six regions also fail the single-cell check, and each flagged cell holds a mapped plant:
Pavagada in Karnataka (26% of the state), the Ananthapuramu park at NP Kunta in Andhra
Pradesh (30%, 44.3 km&sup2; of OSM outline), and mapped plants in Chhattisgarh, Kerala,
Assam and Jharkhand (1.3 to 5.1 km&sup2; each). Jharkhand fails on concentration alone.
Gujarat no longer does: the Khavda outlines were 29% of the state before they were
credited at their detected share. The check exists to catch ground-mount false positives
on bright bare land; here 1,073 of the 1,433 km&sup2; of capacity-relevant ground candidate
area is a mapped plant's outline, and the screen above shows the model detecting PV over a
median 98.5% of those perimeters. Published with the flags stated, per this project's
precedent for a checked-genuine failure.

## Candidate population

95,381 candidates: 32,541 rooftop, 25,214 ground-adjacent, 37,626 with no building, median
1,798 m&sup2;. 1,911 model-drawn candidates exceed the 100,000 m&sup2; merge cap and are
excluded from capacity: 33.7% of candidate area, the largest 30.27 km&sup2;. A further 1,331
oversize candidates carry an OSM-verified plant geometry and are exempt, all counted as
ground, six of them at their detected share (44.7 of 174.3 km&sup2;). The model's own
estimate (`est_mwp_rc`) is 32,868.2 MWp (90% 21,838 to 47,921), 843.0 rooftop and
32,025.3 ground; with no recall reference it equals the precision-weighted
`est_mwp_cal_total`. 27.8 GW of it is the 1,331 OSM-outline candidates, each weighted by the
largest ground bin's `p_real` of 0.518. The probability-weighted `est_mwp_exp`, which
does not use the candidate population, is 29,520.5 MWp.

**Verified is almost all ground-mount.** It is the hand-mapped layer at the two constants:
1,331 km&sup2; of dissolved ground perimeters against 9.3 km&sup2; of rooftop polygons. Best
adds 4,678.5 MWp on top, model detections outside anything Verified counts, 796.4 MWp of
it at Khavda (see the screen section above).

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
interval. Every country run after India filters it (`scripts/drop_solar_thermal.py`).

## Against the old Gujarat page

The earlier Gujarat page reported 812.6 MWp (`est_mwp_rc`) over its bounding box,
of which Gujarat state was 765.0 (168.7 rooftop, 596.3 ground). The same estimator here
gives the state **4,554.1 MWp** (93.3 rooftop, 4,460.9 ground), and the atlas puts it at
Verified 5,852.3 and Best 7,492.9 MWp over 1,423 cells.

Almost all of the rise is one rule. The Gujarat run (2026-08-07) excluded every candidate
above 100,000 m&sup2;, including those carrying a mapped plant's outline; `density` began
exempting OSM geometry from the cap three days later. Those 135 candidates (142.1
km&sup2; credited) are about 3.7 GW of the new state figure, 0.8 GW of it the two Khavda
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

## What India needs next

**A calibration quadrat in a rooftop-dense area.** Almost all of India's rooftop capacity is
below this page's floor. Gujarat leads the household programme by state, so a box there is
the obvious first one. Check the imagery date before drawing it; see the
[quadrat protocol](../calibration-mapping-protocol.md).

**Recomposite the affected cells**, Rewa first.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox 68.0,6.7,97.5,37.1 \
  --iso3 IND --name india --tiles 14x14 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-vn-in-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_vn_in_queue.sh
```

The queue composes India behind Vietnam and hands it to `scripts/run_country_compute.sh
india` (chips at the training milestone, training, the v5 comparison, incremental inference
and the atlas chain, behind marker files).
