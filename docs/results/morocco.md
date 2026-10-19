# Morocco: the parks the map holds, a tie at the top, and most of the fleet out of sight

Morocco was composed on 10 and 11 October 2026 and run on 18 and 19 October, the last
country of the Morocco-Egypt-Yemen-South Africa queue. It started like the others, with no
calibration quadrats, no national register and no third-party PV dataset to check against,
and it was run under the owner's standing instruction to **localize the segmentation** on
the country's own OpenStreetMap labels and to ship whichever checkpoint scores better on a
held-out region. Both checkpoints found almost everything in the held-out region; the tie
goes to the localized `v11_combined_morocco` under that rule, and this page runs on it.

Interactive: [Morocco PV evidence atlas](../atlas-morocco.md).

## Headline

| | |
| --- | --- |
| Verified | **380.4 MWp** (90% 265 to 550) |
| Best estimate | **411.2 MWp** (90% 361 to 554) |
| Grid | 703 cells of 0.1&deg;, north of 27&deg;40&prime; N, 11 regions (geoBoundaries) |
| Imagery | Sentinel-2 L2A, April to September 2026 |
| Model | `v11_combined_morocco` epoch 24, localized (tied with `v5_combined_france` on the holdout; see below) |

!!! warning "A precision floor, and a small part of Morocco's solar fleet"
    Morocco has **no calibration quadrats**, so there is no `roofclf` half and no
    instrument below the 400 m&sup2; segmentation floor. It has no glint sample, so
    `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction, and
    recall was deliberately skipped (`--recall-reference none`). For scale, the utility
    ONEE puts Morocco's utility-scale PV at **1,285 MW** after 204 MW were added in 2025,
    plus 534 MW of concentrating solar power, and researchers estimate **more than 3 GWp**
    of commercial, pumping and household systems from import data
    ([pv magazine, 26 February 2026](https://www.pv-magazine.com/2026/02/26/morocco-installs-204-mw-of-utility-scale-solar-in-2025/)).
    Part of the utility-scale gap is parks that are not in OpenStreetMap at all: nothing is
    mapped at Noor Midelt. Part is plants south of 27&deg;40&prime; N, which this page does
    not cover. The household and commercial fleet is mostly below the segmentation floor.

## Localizing the detector

**Labels.** 3,440 OpenStreetMap solar features inside the run's area, of which **1,697 are
solar-thermal**: the Noor Ouarzazate complex's trough and tower plants (Noor I to III) and
collectors tagged `generator:method=thermal`. `scripts/drop_solar_thermal.py` removes them
before chips are cut, leaving 1,743 PV features (1,540 ground, 179 rooftop, 24
unclassified). Morocco is where that filter was written: the first v11 was trained on the
unfiltered file, and three quarters of its holdout's PV pixels were CSP mirrors (fixed
2026-10-11, commit 37668a4).

**Holdout.** Picked from the label map before training by `scripts/pick_val_region.py`:
Drâa-Tafilalet, 5 cells, holding 8 of the country's 39 dissolved positives of 400 m&sup2;
and up. Its 539 mapped polygons (4.1 km&sup2;) are three parks: Noor IV, the 72 MW
photovoltaic plant of the Ouarzazate complex (1.4 km&sup2;, mapped as one outline plus its
blocks, 500 polygons in its cell; its OpenStreetMap name says "CSP", its
`plant:method` says photovoltaic), and Noor Erfoud and Noor Zagora, 40 MW and about 0.6
km&sup2; each. None of them touches a filtered thermal element.

**Corpus and recipe.** 49 train and 19 val chips (47 with PV), weighted x8, the cap, giving
411 of 25,649 corpus rows (1.6%). 49 is one below the chain's floor of 50 training chips;
**the owner accepted it on 18 October** rather than shrink the holdout. The recipe is v5's
verbatim. Best epoch 24 on the pooled validation set (val/mIoU 0.816), early-stopped at
epoch 32, 8 hours 16 minutes on the GTX 1060.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 19 held-out chips:

| | v5 | v11 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | 0.994 (1,798 of 1,809) | 0.992 (1,794) |
| pixel IoU | 0.938 | 0.935 |
| pixel F1 | 0.968 | 0.966 |

Both differences are inside the 0.02 margin, so the rule calls a tie and gives it to the
localized model. **The comparison says the two checkpoints are equally good at large
parks and nothing else**: the holdout has no installation between 250 and 500 m&sup2;, its
1,809 "installations" are Noor IV's mapped blocks counted once per overlapping chip, and a
park this size is the case every corpus already covers. Yemen's holdout tied at zero; this
one ties near one, and for the opposite reason.

## The ground-perimeter screen

All 22 mapped ground perimeters of 50,000 m&sup2; and up are imaged. 19 are detected, at
98 to 100% of their area, including Noor IV, Noor Erfoud, Noor Zagora and the Benguérir
plant. Two small ones
(0.20 km&sup2; west of Marrakesh, 0.11 km&sup2; near El Jadida) show nothing at all and one
(0.09 km&sup2;) only a faint signal; none is above the 5 km&sup2; cap, so all count in Verified.

## Plausibility gate

`earthpv check-density` reports **0 fail and 10 suspect of 11 regions**. The model's own
estimate is entirely ground-mount, so every region with any of it trips the ground to
rooftop ratio, and none reaches the 50 MWp of ground-mount at which the ratio counts as a
failure.

## Candidate population

709 candidates: 83 rooftop, 135 ground-adjacent, 491 with no building, median 4,096
m&sup2;. None lay inside a filtered solar-thermal outline. 50 model-drawn candidates exceed
the 100,000 m&sup2; merge cap and are excluded from capacity (14.6 km&sup2;, 52.8% of
candidate area, the largest 1.55 km&sup2;); none of them touches a mapped installation, and
the eight largest are dark ploughed fields in the Gharb plain, a burnt hillside near Tangier
and the Merja Zerga lagoon, not parks. A further 8 oversize candidates carry a mapped plant
outline and are exempt.

The rest, priced by the precision table, are **87.7 MWp** (`est_mwp_rc`, 90% 51 to 163),
all ground: no rooftop candidate matches a mapped rooftop array, so every rooftop bin prices
at `p_real` 0, and ground candidates price at 0 to 0.19.

**Verified is the hand-mapped layer at the two constants.** 978 reference features after
dissolving (775 ground, 179 rooftop, 24 unclassified): 377.8 MWp of ground and 2.6 MWp of
rooftop. Best adds the model's detections where they exceed the mapped value and is floored
at Verified in 16 cells.

| Region | Verified (MWp) | Best (MWp) |
| --- | ---: | ---: |
| Drâa-Tafilalet | 129.5 | 129.6 |
| Béni Mellal-Khénifra | 86.4 | 86.7 |
| Marrakech-Safi | 78.1 | 79.7 |
| Fez-Meknes | 33.8 | 40.8 |
| Tangier-Tetouan-Al Hoceima | 36.7 | 40.2 |
| Rabat-Salé-Kenitra | 3.1 | 19.7 |
| Casablanca-Settat | 6.4 | 7.0 |
| Oriental | 5.0 | 5.2 |
| Souss-Massa | 0.4 | 1.2 |
| Guelmim-Oued Noun | 0.9 | 0.9 |
| Laâyoune-Sakia El Hamra, north of 27&deg;40&prime; N | 0.0 | 0.0 |

The region outlines on the map are clipped to the run's own box, so no region is drawn
south of 27&deg;40&prime; N (`atlas.build_evidence_atlas`, 19 October 2026).

## Operational notes

Compose built 703 cells, 141 of them label cells, with the 10 October compose fixes in
place (scene ranking by coverage, band-dropout check). Inference over 703 cells took 29
minutes and `density` five. The chain stopped for a week at its training-chip floor until
the owner's decision.

## What Morocco needs next

**Map the missing parks.** Noor Midelt and the other recent utility plants are what
separates this page from the national figure, and none of them is in OpenStreetMap.

**A holdout with small arrays.** A region holding only parks cannot tell two checkpoints
apart on the population where they differ.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=-13.2,27.6,-1.0,35.95 \
  --iso3 MAR --name morocco --tiles 4x3 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-country-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_country_queue.sh
```

The queue pulls the labels, runs the solar-thermal filter, composes Morocco, picks the
holdout and hands the country to `scripts/run_country_compute.sh morocco` (chips,
training, the v5 comparison, inference and the atlas chain, behind marker files).
