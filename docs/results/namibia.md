# Namibia: a decisive localization win, and pans the model reads as panels

Namibia was added on the owner's request on 28 October 2026 as a first iteration, under
the same rules as every country since the Morocco-Egypt-Yemen-South Africa queue: no
calibration quadrats, no register used, the segmentation **localized** on Namibia's own
OpenStreetMap labels and shipped only if it beats the general model on a held-out region.
It does, by a wide margin, and this page runs on `v17_combined_namibia`.

Interactive: [Namibia PV evidence atlas](../atlas-namibia.md).

## Headline

| | |
| --- | --- |
| Verified | **464.3 MWp** (90% 336 to 657) |
| Best estimate | **530.2 MWp** (90% 480 to 664) |
| Grid | 459 imaged cells of 0.1&deg;, of the 7,260 that cover the country; 13 regions (geoBoundaries) |
| Imagery | Sentinel-2 L2A, May to September 2026 |
| Model | `v17_combined_namibia` epoch 24, localized (beat `v5_combined_france` on the holdout; see below) |

!!! warning "A precision floor below 400 m&sup2;, and an overcount in the north"
    Namibia has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor, where household, farm and lodge systems sit.
    It has no glint sample, so `p_unmapped` is 0 and `p_real` collapses to the
    OpenStreetMap-mapped fraction, and recall was deliberately skipped
    (`--recall-reference none`). **Most of what the model adds in the Cuvelai basin is
    seasonal pans, not panels** (below): about 54 of the 66 MWp by which Best exceeds
    Verified. For comparison, IRENA puts Namibia at 389 MW of solar PV at the end of 2025
    (IRENA's own estimate), and 1,498 MWp of panels were imported directly from China from
    January 2017 to August 2026 ([Ember](https://ember-energy.org/data/china-solar-exports-data/)).
    Neither is ground truth for the map.

## Localizing the detector

**Labels.** 7,005 OpenStreetMap solar features inside Namibia: 5,889 ground, 1,110
rooftop, 6 unclassified, and no solar-thermal collectors. Most of the ground features are
panel rows: Namibian mappers traced the rows of about a hundred plants one by one inside
the plant outline.

**Holdout.** Picked from the label map by `scripts/pick_val_region.py`: Erongo, 20 cells,
with 38 of the country's 234 dissolved positives of 400 m&sup2; and up (16.2%). Khomas,
with 118, stays in training. 36 val chips, a thin holdout like Morocco's.

**Corpus and recipe.** 120 train chips, weighted x8 (`round(7000 / 120)`, capped at 8),
giving 960 of 27,872 train rows (3.4%). South Africa's chips join at weight 1 (3,546 train
rows), as the nearest landscape with a large label set: arid Northern Cape parks and Karoo
towns that no other corpus row resembles. The rest is v5's corpus, and the recipe is v5's
verbatim. Training queued behind the pooled v18 run for the GPU; its first attempt was
killed by `systemd-oomd` at epoch 6, when other jobs filled memory; the restart, from
scratch, reached its best at epoch 24 (val/mIoU 0.804) and early-stopped after epoch 32,
4 hours 6 minutes on the GTX 1060.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 36 held-out chips. An
installation is counted once per chip it appears in, and most are panel rows inside a few
Erongo plants:

| | v5 | v17 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | 0.766 (723 of 944) | **0.952** (899) |
| of which 1,000 m&sup2; and up | 0.179 (20 of 112) | **0.795** (89) |
| of which 500 to 1,000 m&sup2; | 0.845 (703 of 832) | **0.974** (810) |
| 250 to 500 m&sup2; (reported, not decisive) | 0.035 (12 of 346) | **0.618** (214) |
| pixel IoU | 0.456 | **0.662** |
| pixel F1 | 0.626 | **0.797** |

Recall decides first, and the difference, 0.186, is far above 0.02: v17 ships, ahead in
every size band and on outline quality. Before v17 was trained, a preview of the atlas on
the released v14 was built and not published (Best 518.7 MWp); it showed the same pans.

## The ground-perimeter screen

All 31 mapped ground perimeters of 50,000 m&sup2; and up (9.05 km&sup2;, the largest 2.30
km&sup2;) are at least 98% imaged, and the median one is 97% detected. Three are mostly
missed: a 0.23 km&sup2; outline with nothing detected, and two of 0.13 km&sup2; at 1% and
27%. No perimeter exceeds the 5 km&sup2; cap, so the screen changes no total.

## Plausibility gate

`earthpv check-density` fails no region and marks 10 of 13 **suspect** on the ground-mount
to rooftop ratio of the model's estimate: 4 MWp of rooftop against 136 MWp of ground, with
every region below the 50 MWp floor that turns a suspect ratio into a failure. That is the
missing rooftop denominator seen in every segmentation-only country: Namibia's household
arrays are far below what the sensor resolves. Khomas, Omaheke and Kunene pass.

## The Cuvelai pans

Best exceeds Verified by 65.9 MWp. By region, 53.7 MWp of that sits in the four regions of
the Cuvelai basin: Omusati 29.2, Ohangwena 18.0, Oshikoto 5.3 and Oshana 1.2. 553 of the
965 candidates lie there, 492 of them with no building nearby. Ten of them were checked on
Esri World Imagery: the six largest below the merge cap and four further down the ranking.
**All ten are oshanas, pans and ponds, flooded or dried, or a bare clearing; none is a
solar array.** The flat, bright floors and standing water of the oshanas look like
ground-mounted panels to the model.

They reach Best through the precision table. With no glint sample, `p_real` is the mapped
fraction of each size bin, and in the largest ground bin (above 50,000 m&sup2;) Namibia's
mapped plants make 21 of 101 candidates real, so every unmapped outline of that size is
priced at about a fifth of its area. The page states the problem in its caveats; no filter
removes the pans yet. Verified, which counts only mapped installations, is not affected.

## Candidate population

965 candidates: 111 rooftop, 117 ground-adjacent, 737 with no building, median 3,803
m&sup2;. 69 carry a mapped OpenStreetMap geometry, 20 of them above the 100,000 m&sup2;
merge cap and exempt from it. **63 model-drawn outlines exceed the cap and are excluded
from capacity** (15.0 km&sup2;); 52 of them (12.3 km&sup2;, up to 1.2 km&sup2; each) lie in
Omusati and Ohangwena, the same oshana country. The disk review page for them (`scripts/oversize_review.py`) was drawn, not
judged, so the cap stands as for every country without a review.

The model's own estimate is **143.1 MWp** (`est_mwp_rc`, 90% 87 to 231), 137.5 of it
ground; thresholded and unweighted, its own outlines below the cap are 35.5 MWp
(`est_mwp_det`).

**Verified is the hand-mapped layer at the two constants.** 1,254 reference features after
dissolving (172 ground, 1,076 rooftop, 6 unclassified): 422.4 MWp of ground and 42.0 of
rooftop. Best is floored at Verified in 34 cells.

| Region | Verified (MWp) | Best (MWp) |
| --- | ---: | ---: |
| Karas | 159.9 | 160.3 |
| Erongo | 111.6 | 111.9 |
| Hardap | 65.1 | 66.1 |
| Otjozondjupa | 53.5 | 53.7 |
| Omusati | 3.3 | 32.5 |
| Khomas | 27.0 | 28.4 |
| Oshikoto | 22.1 | 27.4 |
| Omaheke | 17.9 | 18.0 |
| Ohangwena | 0.0 | 18.0 |
| Caprivi | 1.2 | 4.4 |
| Kavango | 0.0 | 3.2 |
| Oshana | 0.0 | 1.2 |
| Kunene | 0.3 | 0.5 |

## Mapping leads and a calibration area

**848 mapping leads**, the model's outlines more than 100 m from any mapped solar feature,
are in the release [`pv-new-leads-2026-10-28`](https://github.com/open-energy-transition/earthpv/releases/tag/pv-new-leads-2026-10-28)
(`namibia_pv_new_leads.geojson`), and the atlas links them. In the north most of them are
the pans above: check each against imagery before mapping anything.

**One calibration candidate passes the imagery gate**, a 2 km box at Rosh Pinah in Karas
(`karas_s2_calib_2km`), the atlas's starred area. The gate needs Esri imagery at zoom 18,
the level panels are traced at, captured no more than 12 months before the imagery
window. Across most of Namibia Esri serves its sharp imagery (0.3 to 0.5 m, some from
January 2026) only to zoom 17, so 786 of 842 draws, and both purposive start-here boxes,
were screened out. **geoBoundaries' Namibian districts (ADM2) carry the wrong names**
(Rosh Pinah falls in "Omuthiyagwipundi", Oshakati in "Otjinene"); the regions (ADM1),
which the atlas draws, are correct, and the candidate sampler names a Namibian box after
its region alone.

## Operational notes

The queue pulled the labels on 28 October and composed 459 cells (409 with at least 1,000
buildings, plus every cell holding a mapped solar feature) overnight, done at 05:48 on 29
October. Training then waited about nine hours for the GPU. Inference over the 459 cells
took 25 minutes, and everything from postprocessing to the atlas 9 minutes.

## What Namibia needs next

**A filter for the Cuvelai pans.** Hard negatives cut on OpenStreetMap water and wetland in
the north, as Egypt's are cut on mapped pools and wastewater basins, or a seasonal-water
test, before the model's figure there can be read as solar.

**Map the parks and rows the model already finds**, from the lead file, and the Rosh
Pinah box, panel by panel. Six to ten complete areas start a small-installation half,
which needs areas with zoom-18 imagery.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=11.7,-29.0,25.3,-16.9 \
  --iso3 NAM --name namibia --tiles 4x4 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-country-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_country_queue.sh
```

The queue pulls the labels, runs the solar-thermal filter, composes Namibia, picks the
holdout and hands the country to `scripts/run_country_compute.sh namibia` (chips, training,
the v5 comparison, inference and the atlas chain, behind marker files).
