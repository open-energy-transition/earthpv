# Poland: a strong holdout, a clear localization win, and parks the map has not caught up with

Poland was added on the owner's request on 19 October 2026 and run under the same rules as
the Morocco-Egypt-Yemen-South Africa queue: no calibration quadrats, no register used, the
segmentation **localized** on Poland's own OpenStreetMap labels and shipped only if it beats
the general model on a held-out region. It does, on a large holdout, and this page runs on
`v15_combined_poland`.

Interactive: [Poland PV evidence atlas](../atlas-poland.md).

## Headline

| | |
| --- | --- |
| Verified | **6,604.3 MWp** (90% 4,618 to 9,528) |
| Best estimate | **7,780.9 MWp** (90% 6,411 to 10,398) |
| Grid | 3,948 cells of 0.1&deg;, 16 voivodeships (geoBoundaries) |
| Imagery | Sentinel-2 L2A, May to September 2026 |
| Model | `v15_combined_poland` epoch 27, localized (beat `v5_combined_france` on the holdout; see below) |

!!! warning "A precision floor, and blind to most of Poland's solar"
    Poland has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor. It has no glint sample, so `p_unmapped` is 0 and
    `p_real` collapses to the OpenStreetMap-mapped fraction, and recall was deliberately
    skipped (`--recall-reference none`). Poland had about 21.8 GW installed by February 2025
    ([Wikipedia](https://en.wikipedia.org/wiki/Solar_power_in_Poland)), most of it household
    systems far below the floor. Panels imported directly from China, 21.8 GW from January
    2017 to August 2026 ([Ember](https://ember-energy.org/data/china-solar-exports-data/)),
    are not a ceiling here: the installed fleet already exceeded them in early 2025, because
    much of Poland's Chinese supply arrives through other EU countries.

## Localizing the detector

**Labels.** 67,110 OpenStreetMap solar features inside Poland, of which 131 are
solar-thermal collectors (0.13 km&sup2;), removed before chips were cut. That leaves 66,979
(36,998 ground, 21,963 rooftop, 8,018 unclassified). Every Overpass mirror failed the
filter's usual country-wide scan, so it ran as 66 one-degree tiles.

**Holdout.** Picked from the label map by `scripts/pick_val_region.py`: Lublin
Voivodeship, 301 cells, with 359 of the country's 4,267 dissolved positives of 400 m&sup2;
and up (8.4%). Greater Poland, with 640, stays in training. **Because of a grid-origin
mismatch fixed after the run (below), the held-out cells are Lublin's shifted one 0.1&deg;
column east.** Holdout, buffer ring and training set all use the same cell names, so the
split stays clean: it is a contiguous region 7 km east of the one intended. 706 val chips,
361 of them with PV, 7.3% of Poland's labelled PV pixels.

**Corpus and recipe.** 7,666 train chips, weighted x1 (`round(7000 / 7,666)`), giving 8,515
of 33,753 corpus rows (25.2%). The recipe is v5's verbatim. The first training run was
killed by `systemd-oomd` at epoch 8, when another session's jobs filled memory; the restart
reached its best at epoch 27 (val/mIoU 0.804) and early-stopped at epoch 35, 12 hours 35
minutes on the GTX 1060.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 706 held-out chips:

| | v5 | v15 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | 0.927 (3,192 of 3,444) | **0.960** (3,306) |
| of which 1,000 m&sup2; and up | 0.826 (683 of 827) | **0.917** (758) |
| of which 500 to 1,000 m&sup2; | 0.959 (2,509 of 2,617) | **0.974** (2,548) |
| 250 to 500 m&sup2; (reported, not decisive) | 0.836 (744 of 890) | **0.954** (849) |
| pixel IoU | 0.571 | **0.645** |
| pixel F1 | 0.727 | **0.784** |

Recall decides first, and the difference, 0.033, is above 0.02: v15 ships, ahead in every
size band and on outline quality.

**A checkpoint-selection bug, caught before publication.** The killed run's checkpoints
stayed in the run directory, and Lightning wrote the restarted run's state to
`last-v1.ckpt`. `scripts/pick_best_checkpoint.py` read only `last.ckpt` and picked the dead
run's epoch 7 (0.776); the decision, inference and postprocessing all ran on it before this
was noticed at the density step. The picker now reads every run's state (South Africa's and
Morocco's picks are unchanged), and the chain was rerun from the pick. On the wrong
checkpoint the holdout read recall 0.965 against v5's 0.927 but pixel IoU 0.571 against
0.571; epoch 27 trades a little recall for much better outlines.

## The ground-perimeter screen

All 436 mapped ground perimeters of 50,000 m&sup2; and up (72.5 km&sup2;, the largest 3.1
km&sup2;) are fully imaged, and 432 are detected, at a median 99% of their area. The four
with nothing detected are 0.05 to 0.11 km&sup2;. No perimeter exceeds the 5 km&sup2; cap.

**The screen first read every Polish perimeter from the wrong file.** `compose` snaps the
grid to the country's own lower-left corner, and Poland's border starts at 14.12&deg;E, so
its cells are named from 14.1&deg;E, not the configured 14.0. `density` replicates that;
the screen and the holdout picker used the configured origin, read each perimeter from
the neighbouring cell's composite, and called 398 of 436 "insufficient imagery". Both now
use `density._grid_origin`. No other published country is affected (their snapped and
configured origins agree), and no Polish total moves, since the screen only changes
capacity for perimeters above 5 km&sup2;.

## Plausibility gate

`earthpv check-density` fails **all 16 voivodeships** on the ground-mount to rooftop ratio
of the model's estimate: 5 MWp of rooftop against 4,709 MWp of ground. That is the missing
rooftop denominator seen in [France](france.md) and [India](india.md): Poland's household
arrays are far below what the sensor resolves.

## Candidate population

8,995 candidates after four inside solar-thermal outlines were removed: 823 rooftop, 2,616
ground-adjacent, 5,556 with no building, median 13,608 m&sup2;. 155 oversize candidates
carry a mapped plant outline and are exempt from the 100,000 m&sup2; merge cap. **168
model-drawn ones exceed it and are excluded from capacity** (39.7 km&sup2;, 18% of candidate
area, the largest 1.31 km&sup2;), and in Poland most of them are real: all eight of the
largest and at least seven of the eight around rank 40 are solar parks on the composite, six
of the largest eight with no mapped solar within 100 m. At the land constant they would be
about 2 GWp. The cap is kept, as for every country, because it is what removes the rock,
fields and pits elsewhere; these parks are in the exported mapping leads
(`poland_pv_new_leads.geojson`, 5,793 leads) and enter Verified once mapped.

The model's own estimate is **4,741.9 MWp** (`est_mwp_rc`, 90% 3,124 to 6,969), nearly all
of it ground and about half of it (2.2 GWp) the 155 mapped outlines it reproduces; thresholded and
unweighted, its own outlines below the cap are 385 MWp (`est_mwp_det`).

**Verified is the hand-mapped layer at the two constants.** 44,551 reference features after
dissolving (14,613 ground, 21,920 rooftop, 8,018 unclassified): 6,522.8 MWp of ground and
81.5 of rooftop. Best is floored at Verified in 1,166 cells.

| Voivodeship | Verified (MWp) | Best (MWp) |
| --- | ---: | ---: |
| Greater Poland | 1,462.4 | 1,608.6 |
| West Pomeranian | 620.6 | 667.4 |
| Pomeranian | 551.9 | 651.5 |
| Lubusz | 489.8 | 561.4 |
| Masovian | 377.6 | 553.4 |
| Lublin | 474.0 | 526.3 |
| Lower Silesian | 464.2 | 512.0 |
| Warmian-Masurian | 394.1 | 491.4 |
| Kuyavian-Pomeranian | 342.4 | 411.1 |
| Podlaskie | 309.2 | 359.8 |
| Lodz | 210.2 | 317.3 |
| Subcarpathian | 274.3 | 308.0 |
| Swietokrzyskie | 174.8 | 214.8 |
| Opole | 162.9 | 209.3 |
| Silesian | 124.6 | 171.3 |
| Lesser Poland | 111.3 | 139.8 |

## Operational notes

Compose built 3,948 cells (3,793 by building density, 2,847 holding a mapped solar
feature, the two overlapping) from 19 October 09:57 to 21 October 06:33, at 60 to 110 cells
an hour. The holdout pick then failed every queue tick for 15 hours, because
`pick_val_region.py --write` only fills an empty `val_tiles: []` and `new_region.py add`
never wrote one; it does now. Inference over 3,948 cells took 2 hours 13 minutes,
`density` 43 minutes.

## What Poland needs next

**Map the parks the model already outlines.** `scripts/park_leads.py --aoi poland` writes
them as a verification package: 351 model detections of 5 ha and up with no mapped solar
within 100 m, about 2.4 GWp at the land constant, largest first, with iD and JOSM links,
suggested tags, a MapRoulette file and a contact sheet. Of the 24 largest, 23 are solar
parks on the composite and one is a quarry. Each needs a person to confirm it against
high-resolution imagery and trace the site; the model outlines only mark the place.

**A rooftop instrument.** Poland's household systems are the bulk of its fleet and
all below the floor; an area mapped panel by panel would be the start of a
small-installation half.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=14.0,49.0,24.2,54.9 \
  --iso3 POL --name poland --tiles 5x4 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-country-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_country_queue.sh
```

The queue pulls the labels, runs the solar-thermal filter, composes Poland, picks the
holdout and hands the country to `scripts/run_country_compute.sh poland` (chips, training,
the v5 comparison, inference and the atlas chain, behind marker files).
