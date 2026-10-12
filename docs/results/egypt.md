# Egypt: the localized detector wins a thin holdout, and Benban carries Verified

Egypt was composed and run on 11 and 12 October 2026, the first country of the
Morocco-Egypt-Yemen-South Africa queue to reach a page. Like [India](india.md) and
[Vietnam](vietnam.md) it started with no calibration quadrats, no national register and no
third-party PV dataset to check against. It was run under the owner's standing instruction
to **localize the segmentation** on the country's own OpenStreetMap labels and to ship
whichever checkpoint scores better on a held-out region. The localized checkpoint,
`v12_combined_egypt`, won, so this page runs on it.

Interactive: [Egypt PV evidence atlas](../atlas-egypt.md).

## Headline

| | |
| --- | --- |
| Verified | **3,315.1 MWp** (90% 2,314 to 4,789) |
| Best estimate | **3,378.6 MWp** (90% 3,028 to 4,823) |
| Grid | 946 cells of 0.1&deg;, 27 governorates (geoBoundaries) |
| Imagery | Sentinel-2 L2A, April to September 2026 |
| Model | `v12_combined_egypt` epoch 16, localized (it beat `v5_combined_france` on the holdout; see below) |

!!! warning "A precision floor, not an estimate"
    Egypt has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    at all below the 400 m&sup2; segmentation floor. It has no glint sample, so
    `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction. Recall
    was deliberately skipped (`--recall-reference none`). For scale, GlobalData puts
    Egypt's cumulative solar PV at about 2.9 GW at the end of 2025, up from 2.1 GW a year
    earlier
    ([pv magazine, 11 May 2026](https://www.pv-magazine.com/2026/05/11/egypt-installs-800-mw-of-solar-in-2025/));
    the government's information centre, citing the World Energy Council, counts a
    smaller 2025 addition of 500 MW. This page's imagery is from the following summer.

## Localizing the detector

**Labels.** 2,872 OpenStreetMap solar features inside Egypt (2,329 ground, 523 rooftop, 20
unclassified), 92.7 km&sup2; before dissolving. The solar-thermal filter found 363
solar-thermal elements in the country's bounding box and none among the label features, so
nothing was dropped. The mapped population is utility parks first: Benban alone is 36.9
km&sup2; of outline.

**Holdout.** Picked from the label map before training by `scripts/pick_val_region.py`:
Cairo Governorate, 22 cells, holding 10 of the country's 71 dissolved positives of 400
m&sup2; and up. The governorate with the most positives (Red Sea, 15) is never the holdout,
and Aswan, with Benban, stays in training. One training chip in the ring around the holdout
was relabelled `buffer`.

**Corpus and recipe.** 109 train and 9 val chips (82 of 119 with PV), weighted x8, the
cap, giving 882 of 26,120 corpus rows (3.4%). The recipe is v5's verbatim. Best epoch 16,
early-stopped at epoch 24, 6 hours 20 minutes on the GTX 1060.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 9 held-out chips:

| | v5 | v12 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | 0.043 (1 of 23) | **0.217** (5 of 23) |
| pixel IoU | **0.066** | 0.062 |
| pixel F1 | **0.124** | 0.116 |

The rule compares recall first, and a difference above 0.02 decides: v12 ships. Read it
as a weak result. The holdout is 1,869 PV pixels in seven chips, 0.3% of the PV pixels in
Egypt's chips, and three of the seven frame the same array; the installations are small
ground arrays on the edge of Cairo, and both checkpoints find almost none of them (IoU about
0.06 for both, against 0.69 for v5 on India's holdout). The margin is four installations.
It is enough to satisfy the rule, not to show that localization helps in Egypt by much.

## A compose gap, closed before publication

The first build of this page dropped two mapped parks from Verified, a 10.0 km&sup2;
outline just north of Benban and an 8.8 km&sup2; one at Kharga in New Valley. The model
detected 96 to 98% of each where it had imagery, but only 87% and 69% of them had imagery
at all, and the ground screen keeps an outline above 5 km&sup2; only when at least 90% of
it is imaged. The cause was cell selection: `compose` added a cell for each mapped solar
feature by the feature's representative point, so a park outline crossing a cell edge was
imaged only on one side of it.

`compose._solar_label_cells` now adds every cell an outline intersects. Egypt gained five
cells (946 against 941), the two parks are now fully imaged and 92 to 95% detected, and the
screen keeps them. That moved Verified from 2,374.6 to **3,315.1 MWp** and Best from 2,788.1 to
**3,378.6 MWp**. The same rule adds 21 cells to South Africa, whose compose had not started,
and none to Morocco or Yemen. Of the countries already published, Vietnam, Zambia and
Nigeria have no such cell, and India has eight, six of them at Khavda; see
[open question 22](../open-questions.md#22-composites-built-before-2026-10-10-carry-two-compose-defects-2026-10-10).

## The ground-perimeter screen

62 OSM ground perimeters of 50,000 m&sup2; or more, every one fully imaged after the fix.
61 screen as detected, with the model lighting up a median 100% of each; one, a
0.053 km&sup2; outline, shows nothing and is listed for a look. The three above the 5
km&sup2; cap are Benban (36.9 km&sup2;, 91% detected), the outline north of it (10.0
km&sup2;, 92%) and Kharga (8.8 km&sup2;, 95%), and all three are kept.

**Benban checks the land constant.** Its 36.9 km&sup2; outline at the 0.05 kWp/m&sup2;
the atlas assumes is 1,844 MWp, against a reported capacity of about 1,650 MW, which is
0.045 kWp/m&sup2;. That is the same figure India's eleven capacity-tagged parks gave, and
Benban's capacity is usually quoted AC, so the DC figure sits closer to the constant.

## Plausibility gate

`earthpv check-density` reports **2 fail and 25 suspect of 27 governorates**. Nationally
the model's estimate is 1,193.2 MWp ground against 0.2 MWp rooftop, so every governorate
trips the ground-to-rooftop ratio; 25 of them hold under 50 MWp of ground-mount, below the
floor at which the ratio counts as a failure. The two that fail are the two with large
mapped parks, and each fails the single-cell check as well: Aswan (894 MWp, 78% of it in
Benban's main cell `0080_0024`) and New Valley (188 MWp, 89% in the Kharga park's cell
`0075_0038`). The screen above shows the model detecting 91 to 95% of both outlines, so
these are the plants, not bright desert. The ratio is the missing rooftop denominator, as
in [France](france.md) and [India](india.md), here in an extreme form (next section).
Published with the flags stated, per this project's precedent for a checked-genuine
failure.

## Candidate population

1,218 candidates: 223 rooftop, 461 ground-adjacent, 534 with no building, median 4,249
m&sup2;. 31 model-drawn candidates exceed the 100,000 m&sup2; merge cap and are excluded
from capacity, 26.4% of candidate area, the largest 8.14 km&sup2;. 15 oversize candidates
carry an OSM plant geometry (58.7 km&sup2;) and are exempt, all counted as ground; VIDA
overlap had placed one of them on a roof. The model's own estimate (`est_mwp_rc`) is
1,193.4 MWp (90% 739 to 1,902), 1,193.2 of it ground; with no recall reference it equals
the precision-weighted `est_mwp_cal_total`.

**The model's rooftop estimate is 0.2 MWp.** The 223 rooftop candidates cover 1.7
km&sup2;, but the 176 of them at 1,000 m&sup2; and up match no mapped rooftop installation
at all. With no glint sample and no register, the precision table can only price a
candidate by how often candidates of its kind are mapped, so it prices those bins at zero.
Egypt has 523 mapped rooftop features nationally, 0.15 km&sup2; in all. In this floor a
detection the map has never confirmed counts for nothing, whether it is a real array
nobody has mapped or a bright roof.

**Verified is almost all ground-mount, and mostly three parks.** It is the hand-mapped
layer at the two constants: 687 features once overlapping outlines are dissolved, 65.8
km&sup2; of ground perimeter (3,288.4 MWp) against 0.15 km&sup2; of rooftop (26.7 MWp).
Benban, the outline north of it and Kharga are 55.7 km&sup2; of that ground area, about
2,785 MWp. Best adds 63.5 MWp. The model's ground estimate prices the same parks at the
largest ground bin's `p_real` of 0.379, below the mapped value, so in 48 cells Best is
floored at Verified; what remains on top is model detections and unmatched mapped features
elsewhere.

## Operational notes

Compose built the 941 originally selected cells between 06:19 and 17:57 on 11 October,
about 81 cells per hour, with no provider hand-offs and the 10 October compose fixes in
place from the start (scene ranking by coverage, band-dropout check; see open question 22).
The five outline cells were added on 12 October in eight minutes, and the chain was re-run
from inference: the five new cells were inferred on the CPU in under a minute, since
Yemen's training held the GPU. Postprocess took three minutes and the density stage about
40.

## What Egypt needs next

**A second, larger holdout.** Cairo's nine chips decided the checkpoint on four
installations. Holding out part of Aswan instead would score both checkpoints on utility
parks, which is most of what Egypt has mapped.

**Rooftop mapping or a calibration quadrat.** 523 mapped rooftop features nationally are
too few for the precision table to price a rooftop candidate; see the candidate section.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=24.7,22.0,36.9,31.7 \
  --iso3 EGY --name egypt --tiles 4x4 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-country-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_country_queue.sh
```

The queue pulls the labels, runs the solar-thermal filter, composes Egypt, picks the
holdout and hands the country to `scripts/run_country_compute.sh egypt` (chips, training,
the v5 comparison, inference and the atlas chain, behind marker files).
