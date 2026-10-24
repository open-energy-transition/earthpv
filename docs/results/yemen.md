# Yemen: solar irrigation the old labels hid, and parks that are not on the map

Yemen was composed and run on 11 and 12 October 2026, the second country of the
Morocco-Egypt-Yemen-South Africa queue to reach a page. Like [Egypt](egypt.md) it started
with no calibration quadrats, no national register and no third-party PV dataset to check
against, and it was run under the owner's standing instruction to **localize the
segmentation** on the country's own OpenStreetMap labels and to ship whichever checkpoint
scores better on a held-out region. Neither checkpoint scored anything on the holdout, the
tie goes to the localized `v13_combined_yemen` under that rule, and this page runs on it.
**Read it as a map of what OpenStreetMap holds, not as an estimate of Yemen's PV.**

Interactive: [Yemen PV evidence atlas](../atlas-yemen.md).

## Headline

| | |
| --- | --- |
| Verified | **65.9 MWp** (90% 46 to 95) |
| Best estimate | **99.8 MWp** (90% 76 to 149); 67.1 before 2026-10-24 |
| of which farm ground PV, < 400 m&sup2; | **32.7 MWp** (90% 16 to 65, a stated judgement), 12 cells; [below](#farm-ground-pv-added-2026-10-24) |
| Grid | 810 cells of 0.1&deg;, 22 governorates (geoBoundaries) |
| Imagery | Sentinel-2 L2A, October 2025 to March 2026 |
| Model | `v13_combined_yemen` epoch 28, localized (tied with `v5_combined_france` at zero on the holdout; see below) |

!!! warning "A precision floor above 400 m&sup2;, and one small-array component in a few cells"
    Yemen has **no `roofclf` half**: its one registered calibration area (Al Wehdah,
    2026-10-23) has not been fitted, so nothing prices rooftop PV below the 400 m&sup2;
    segmentation floor. Below that floor only the farm ground-PV detector counts, and only
    in the 12 cells like its one calibration area ([below](#farm-ground-pv-added-2026-10-24)).
    It has no glint sample, so `p_unmapped` is 0
    and `p_real` collapses to the OpenStreetMap-mapped fraction, which in Yemen is zero in
    every size bin (next sections). Recall was deliberately skipped
    (`--recall-reference none`). For scale, IRENA counts **456 MW of operational PV at the
    end of 2025**, and the 120 MW Aden plant, in operation since July 2024, is being
    doubled to 240 MW
    ([pv magazine, 8 September 2026](https://www.pv-magazine.com/2026/09/08/yemens-largest-solar-plant-set-to-double-to-240-mw/)).
    That plant is not in OpenStreetMap, and this page does not count it.

## Localizing the detector

**Labels.** 1,892 OpenStreetMap solar features inside Yemen (1,733 ground, 29 rooftop, 130
unclassified points), 1.31 km&sup2; in all, median 655 m&sup2;. The largest is 0.022
km&sup2;. The solar-thermal filter found no solar-thermal element in the country's bounding
box. **1,713 of the features sit in the Tihama plain of Al Hudaydah between 14 and 15&deg;N,
and 1,697 of those were last edited in May to August 2023**: rectangles of four corners and a
median 617 m&sup2;, scattered across irrigated fields, the pattern of solar-powered
irrigation pumps.

**Holdout.** Picked from the label map before training by `scripts/pick_val_region.py`:
'Amran Governorate, 47 cells, holding 21 of the country's 1,465 dissolved positives of 400
m&sup2; and up (1.4%). Al Hudaydah, with 1,434, is the core and stays in training. The 21
lie near 43.95&deg;E 16.27&deg;N, were all last edited on 23 or 24 February 2024, and are
450 to 1,755 m&sup2;, 18 of them ground.

**Corpus and recipe.** 233 train and 13 val chips (190 with PV), weighted x8, the cap,
giving 1,877 of 27,115 corpus rows (6.9%). The recipe is v5's verbatim. Best epoch 28 on the
pooled validation set (val/mIoU 0.790, over every country's held-out chips, of which Yemen's
are 13), early-stopped at epoch 36, 9 hours 44 minutes on the GTX 1060.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 13 held-out chips:

| | v5 | v13 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | 0.000 (0 of 25) | 0.000 (0 of 25) |
| pixel IoU | 0.000 (0 true, 5 false positive pixels) | 0.000 (0 true, 0 false positive pixels) |

Both measures tie, and the rule gives a tie to the localized model. **The comparison carries
no information**: neither checkpoint finds a single held-out pixel.

**The whole-country comparison**, after the atlas (`compare_checkpoints_vs_mapped.py`,
both checkpoints over all 810 cells, scored against the 1,465 dissolved mapped
installations of 400 m&sup2; and up), finished on 19 October, confirms the holdout:
**v5 finds 6 of them and v13 2**, the two parks between 5,000 and 50,000 m&sup2; for both
(McNemar p = 0.13). v13 draws 2,304 candidates below the merge cap against v5's 3,609,
larger at the median (1,799 against 1,201 m&sup2;) and over about the same area (9.2
against 9.8 km&sup2;), and 29 above it (11.2 km&sup2;) against v5's 13 (4.3 km&sup2;),
the dark-rock blobs and the three unmapped parks described below.

## Why neither model sees Yemen's mapped PV

!!! note "Revised 2026-10-23: the labels' geometry, not the sensor"

    The explanation below says the Tihama arrays are too small for Sentinel-2. A test ground
    in 'Amran, where 306 arrays of the same size class were traced around their panels,
    shows they are not: those arrays read 8 to 21% darker than their ring in the visible and
    near infrared. The Tihama labels are rectangles drawn around plots, and averaged over a
    rectangle the panels disappear. Read as bags that hold PV somewhere, the same
    rectangles do carry the signal, and a pixel detector trained on them finds the arrays.
    See [Farm ground PV](../methods/roofclf-ground.md). The measurements below stand; the
    conclusion drawn from them does not.

The held-out arrays are not the exception. Scoring v13's own national inference against
every mapped feature of 400 m&sup2; and up, as the ground screen does, it lights up **2 of
1,466**, including the Tihama arrays it was trained on. The cause is in the imagery, not
the model:

- **The arrays barely differ from what surrounds them.** Across the 181 Yemeni training
  chips with at least three PV pixels, the mean reflectance inside the mapped outlines
  differs from a 30 m ring around them by a median 1.6 to 2.6% per band. The same
  measurement gives 8 to 18% in Egypt's chips and 6 to 25% in Vietnam's. A 617 m&sup2;
  pump array is about six Sentinel-2 pixels of panels and gaps on a field.
- **It is not a misregistration.** Shifting the masks up to 60 m in every direction finds
  no offset at which the outlines turn dark in the red-edge and near-infrared bands; Egypt's
  chips, the same test, peak at zero shift.

So the localized model trained, at eight times weight, on labels it cannot resolve. It is
shipped because the rule says so, not because it learned Yemen.

## What the model does find: three parks the map lacks

v13 draws 2,333 candidates. Only two of them touch a mapped installation, so the precision
table prices every size bin, rooftop and ground, at a `p_real` of 0 to 0.006, and the model
adds almost nothing to either tier (next section). The detections that matter are the
largest. 29 exceed the 100,000 m&sup2; merge cap, 11.2 km&sup2; in all, and were each
inspected against the composite:

- **Three are solar parks, none in OpenStreetMap**: the Aden plant (44.88&deg;E
  12.88&deg;N, 1.31 km&sup2;, its panel blocks outlined almost exactly), a park of two blocks
  beside the power station at Mocha (43.26&deg;E 13.37&deg;N, 0.64 km&sup2;) and a fenced
  grid on the Red Sea coast north of Al Hudaydah (42.93&deg;E 14.99&deg;N, 0.38 km&sup2;).
  Together 2.33 km&sup2;, about 117 MWp at the land constant.
- **The other 26 are dark rock**, basalt outcrops and shadowed hillsides, most of them in
  Sa'dah, the largest 2.54 km&sup2;.

The cap excludes all 29 from capacity, since only an outline carrying an OpenStreetMap plant
geometry is exempt. That removes the rock and the parks together. All three parks are in the
exported mapping leads (`yemen_pv_new_leads.geojson`, Aden and the Red Sea park about
300th of 2,331, Mocha about 670th); once mapped, they enter Verified at the land constant.

## Plausibility gate

`earthpv check-density` reports **0 fail and 18 suspect of 22 governorates**. The model's
estimate is 1.2 MWp, all of it ground, so every governorate holding any of it trips the
ground-to-rooftop ratio, and none comes near the 50 MWp of ground-mount at which the ratio
counts as a failure. The gate checks the model's estimate, and here there is almost nothing
to check.

## Candidate population

2,333 candidates: 480 rooftop, 510 ground-adjacent, 1,343 with no building, median 1,801
m&sup2;. The 29 above the merge cap are 54.8% of candidate area; none carries an
OpenStreetMap plant geometry, since nothing that large is mapped in Yemen. The rest,
thresholded and unweighted, would be 191.9 MWp (`est_mwp_det`). Priced by the precision
table they are **1.2 MWp** (`est_mwp_rc`, all ground, 90% upper bound 11.3), because two of
2,333 candidates match a mapped installation. In this floor a detection the map has never
confirmed counts for nothing, whether it is a real array nobody has mapped or a bright
hillside.

**Verified is the hand-mapped layer at the two constants, and 93% of it is Al Hudaydah.**
1,891 reference features inside the border, none overlapping: 1.30 km&sup2; of ground (65.1
MWp) and 0.004 km&sup2; of rooftop (0.8 MWp); the 130 unclassified points carry no area. The
Tihama irrigation arrays are 61.4 MWp of the 65.9. Best adds the model's 1.2 MWp of ground
on top and, since 2026-10-24, 32.7 MWp of farm ground PV below 400 m&sup2;, and is floored at
Verified in two cells.

## Operational notes

Compose built 810 cells and finished at 04:06 on 12 October, with no provider hand-offs and
the 10 October and 12 October compose fixes in place (scene ranking by coverage,
band-dropout check, label cells covering a whole outline; see [India](india.md#a-compose-defect-found-here-and-fixed-for-every-later-country)). Inference
over 810 cells took 43 minutes. **The ground screen crashed on its first run**: Yemen has no
mapped ground perimeter of 50,000 m&sup2; or more, and the screen wrote an empty table and
then failed reading its own `screen` column. It now writes the column header regardless, so
`density` reads an empty screen; the queue's three launches had all stopped at that step,
and the chain was relaunched at 15:51 once it was fixed.

## Farm ground PV (added 2026-10-24)

Small arrays beside fields, mostly solar irrigation pumps, are counted by the
[farm ground-PV detector](../methods/roofclf-ground.md), a pixel model trained on a fully
traced test ground in 'Amran (306 arrays) and on the Tihama rectangles read as bags. It
enters Best as its own component, beside where rooftop PV below 400 m&sup2; will sit once
`roofclf` is fitted here:

| | |
| --- | --- |
| In Best | **32.7 MWp**, arrays below 400 m&sup2; |
| 90% interval | 16 to 65 MWp, a stated judgement (a factor of two either way), because it rests on one mapped farm area; a bootstrap over areas replaces it from the third |
| Where | the 12 of 810 cells whose cropland share (5.3 to 8.3%) and building density (37 to 58 per km&sup2;) are within 25% of 'Amran's |
| Not counted | 2,555 MWp if the same ratio were applied to every cell, which would put Yemen near its 2,848 MWp import ceiling for all solar since 2017: cities, coast and desert are not 'Amran |

It is incremental: detections within 20 m of a feature in the OpenStreetMap pull this page
counts (12 October), or of a segmentation candidate Best uses, are left to those. The
arrays traced in 'Amran since then are not in that pull, so the detector prices them
rather than the map; once Yemen's OpenStreetMap layer is refreshed they move into Verified
and out of this figure. The eight farm calibration candidates on the map, drawn across
Yemen's cropland strata, are what widen the 12 cells into a national estimate.

## Calibration areas

**Al Wehdah, Sana'a (registered 2026-10-23, Rule-1).** The first of Yemen's two start-here
boxes (`calib-candidates --priority`: 1 km in the densest quarter of the country's
buildings, where the most roof area sits in buildings of 1,000 m<sup>2</sup> or more), so a
purposive sample that runs at a higher PV rate than the country. Mapped panel by panel and
declared complete by the project owner on 2026-10-23, against Esri World Imagery (Vivid
Mosaic Metro) captured 2025-12-29, inside the composite's October 2025 to March 2026
window. It holds **87 installations**, 83 rooftop and 4 ground, 14,611 m<sup>2</sup> in
all, median 78 m<sup>2</sup>; 78 of them (90%) are below the 400 m<sup>2</sup> segmentation
floor and 51 below 100 m<sup>2</sup>. The pull was confirmed against a second Overpass
query (88 elements both times). No second mapping pass is recorded. It is not yet used by
any figure on this page: one quadrat fits `roofclf` but cannot measure its skill, which
needs leave-one-quadrat-out folds.

## What Yemen needs next

**Map the farm calibration areas.** `calib-candidates -- --farmland` drew eight 3 km farm
boxes across Yemen's cropland strata (2026-10-23). Three or more of them, completely
mapped, are what the [farm ground-PV detector](../methods/roofclf-ground.md) needs before
its estimate of solar irrigation can enter this page; its leads are usable for mapping now.

**Map the three parks.** They are the largest PV the model sees in the country and the one
change that would move Verified materially.

**A holdout the sensor can resolve.** Every held-out installation here is a small array in
farmland or on a hillside. A holdout that cannot be detected by either checkpoint cannot
decide between them; until Yemen has a mapped park of its own, the ship rule here is a coin
toss with a fixed outcome.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=41.8,12.1,54.6,19.0 \
  --iso3 YEM --name yemen --tiles 4x3 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-country-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_country_queue.sh
```

The queue pulls the labels, runs the solar-thermal filter, composes Yemen, picks the
holdout and hands the country to `scripts/run_country_compute.sh yemen` (chips, training,
the v5 comparison, inference and the atlas chain, behind marker files).
