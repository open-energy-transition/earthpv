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
| Verified | **151.3 MWp** (90% 128 to 184); 130.9 until 2026-10-30, 65.9 before the 2026-10-24 OpenStreetMap refresh |
| Best estimate | **324.7 MWp** (90% 230 to 493); 302.1 until 2026-10-30, 67.1 on 2026-10-12, 99.8 on the morning of 2026-10-24 |
| of which farm ground PV, < 400 m&sup2; | **169.1 MWp** (90% 77 to 327), 34 cells, calibrated on seven farm areas; [below](#farm-ground-pv-added-2026-10-24) |
| OpenStreetMap | pulled late on 2026-10-24, 3,315 installations in the grid after dissolving overlaps (2,723 in the page before, 1,892 on 2026-10-10) |
| Grid | 810 cells of 0.1&deg;, 22 governorates (geoBoundaries) |
| Imagery | Sentinel-2 L2A, October 2025 to March 2026 |
| Model | `v13_combined_yemen` epoch 28, localized (tied with `v5_combined_france` at zero on the holdout; see below) |

!!! warning "Household rooftops below 400 m&sup2; are not estimated"
    Yemen has **no `roofclf` half**: it was fitted on Yemen's nine building boxes and
    fourteen farm areas on 2026-10-25 and left off, because only four boxes hold rooftop PV
    and its leads were mostly greenhouses and sheds
    ([below](#rooftop-pv-below-400-m2-borrowing-pakistans-classifier-2026-10-28)), so nothing
    prices rooftop PV below the 400 m&sup2; segmentation floor. Below that floor only the farm ground-PV detector counts, and only in
    the 34 cells whose cropland, buildings and elevation resemble its farm areas
    ([below](#farm-ground-pv-added-2026-10-24)). The segmentation model has no glint sample,
    so `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction, under
    0.01 in every size bin (next sections). Recall was deliberately skipped
    (`--recall-reference none`). For scale, IRENA counts **456 MW of operational PV at the
    end of 2025**, and the 120 MW Aden plant, in operation since July 2024, is being
    doubled to 240 MW
    ([pv magazine, 8 September 2026](https://www.pv-magazine.com/2026/09/08/yemens-largest-solar-plant-set-to-double-to-240-mw/)).
    That plant is not in OpenStreetMap, and this page does not count it.

!!! note "Revised 2026-10-24: OpenStreetMap refreshed, the owner's traces counted as panels, seven farm areas"
    The OpenStreetMap layer was pulled again (2,746 features against 1,892), the segmentation
    precision table and density re-derived from it, and the farm ground-PV detector refitted
    on seven completely mapped farm areas. Polygons the project's owner traced around the
    panels (869 in Yemen) now convert at the module constant, as panels, where any other
    mapped ground polygon converts at the land constant, as a site: about 42 MWp of
    Verified's rise. Earlier figures in the sections below are marked with their date.

!!! note "Rebuilt 2026-10-30: the late 2026-10-24 OpenStreetMap pull"
    The page now counts the OpenStreetMap pull made late on 2026-10-24, after the page was
    built, with the segmentation precision table and density re-derived from it: Verified
    130.9 to 151.3 MWp, Best 302.1 to 324.7. The farm ground-PV figure is unchanged, the
    published seven-area fit (`/home/tobi/earthpv_data/yemen_7areas_20261024`); it was
    deduplicated against the earlier pull, so an array mapped in between can count in both.
    The fourteen-area refits of 2026-10-25 (449 to 891 MWp depending on the slope veto and
    the roofclf deduplication) stay unpublished. The page also gained the size chart.

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
    See [Farm ground PV](../methods/groundclf.md). The measurements below stand; the
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

**Verified is the hand-mapped layer at the two constants** (2026-10-12: 1,891 features,
1.30 km&sup2; of ground at 65.1 MWp and 0.8 MWp of rooftop, 61.4 MWp of it the Tihama
irrigation arrays). On the first 2026-10-24 pull it was 130.9 MWp: 122.6 MWp of ground and 8.3 of
rooftop. On the late pull of that day it is **151.3 MWp**: 135.8 of ground and 15.5 of rooftop,
and Best adds the model's 7.1 MWp and the same 169.1 of farm ground PV, floored at Verified in
four cells. The figures that follow are the earlier page's.

847 of the polygons are the owner's panel traces (`osm_panel_tracers` in
`configs/aoi.yaml`), 629 of them on the ground with 326,065 m&sup2;, which count at the module
constant: 58.7 MWp, against 16.3 had they been priced as sites. Best adds the model's
4.2 MWp (`est_mwp_rc`, up from 1.2 because a few candidates now match newly mapped arrays) and
169.1 MWp of farm ground PV below 400 m&sup2;, and is floored at Verified in two cells.

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
[farm ground-PV detector](../methods/groundclf.md), a pixel model, and enter Best as
their own component, beside where rooftop PV below 400 m&sup2; will sit once `roofclf` is
fitted here. It was first added on 2026-10-24 calibrated on 'Amran alone (32.7 MWp in 12
cells, a stated judgement interval), and recalibrated the same day on seven farm areas:

| | |
| --- | --- |
| In Best | **169.1 MWp**, arrays below 400 m&sup2;: 166.5 in 32 lowland cells at Tihama's ratio, 2.6 in two highland cells at 'Amran's |
| 90% interval | 77 to 327 MWp: a bootstrap over the six Tihama areas, and a stated x/÷2 judgement for 'Amran's single area |
| Where | cells whose cropland share, building density and elevation lie within 25% of one region's areas: Tihama 24 to 85% cropland, 49 to 617 buildings per km&sup2;, 54 to 295 m; 'Amran 5.3 to 8.3%, 37 to 58, 1,516 to 2,369 m |
| Not counted | every other cell; detections inside the seven areas (counted from the map) |

**Why the figure is per region.** The detector finds 60% of 'Amran's arrays but 6 to 50% of
each Tihama area's, so the ratio of mapped panel area to detected area is 0.17 in 'Amran and
1.19 in Tihama: each detection there stands for more panel than it shows. Priced with one
ratio over one box around all seven areas, the figure was 3,532 MWp in 289 cells, mostly
highland terraces in Ibb, Sana'a and Ta'izz that resemble Tihama only in cropland and
buildings, and more than the 2,848 MWp of panels Yemen has imported in total since 2017.
Elevation separates the two landscapes (Tihama's areas lie at 68 to 236 m, 'Amran's at
1,895 m), and each cell now takes only the ratio of the region it resembles.

**The figure is Tihama's hotspot ratio applied to the lowland.** The owner's Tihama region
was drawn around a known concentration of solar irrigation. The 32 cells priced with its
ratio hold 205 m&sup2; of detections per km&sup2;, under half the calibration areas' 452,
which is consistent with fewer pumps elsewhere; the ratio itself is the hotspot's. It is
incremental: detections within 20 m of a feature in the OpenStreetMap layer this page counts,
or of a segmentation candidate Best uses, are left to those.

## Rooftop PV below 400 m&sup2;: borrowing Pakistan's classifier (2026-10-28)

`roofclf` was fitted on Yemen's 23 areas on 2026-10-25 and left off this page: a median
fold AUC of 0.83, but the rooftop leads it weighted most, reviewed by hand, were greenhouse
tunnels and long poultry sheds. Yemen's mapped rooftop arrays are not too small for the
sensor (median 78 m&sup2; in Al Wehdah and 51 m&sup2; in Sayun, against 44 m&sup2; in
Pakistan's quadrats), so Pakistan's classifier, fitted on 30 quadrats and 17,151 PV roofs,
was tested on the same Yemeni building tables
(`scripts/roofclf_transfer_yemen.py`):

| Training | Median AUC, the 4 building boxes with PV | Median AUC, all 16 areas with PV |
| --- | --- | --- |
| Yemen alone, leave one area out | 0.813 | 0.833 |
| Pakistan's model, unchanged | 0.809 | 0.724 |
| Pakistan and Yemen, each half the likelihood | 0.818 | 0.800 |
| Pakistan and Yemen, every row weighted 1 | 0.815 | 0.762 |

Pakistan's model ranks Yemen's roofs as well as Yemen's own. It does worse in the farm
areas, whose positives are mostly irrigation arrays credited to the nearest farmhouse, and
pooling the two countries adds about 0.01 on roofs (`roof-classifier --extra-table` does
this pooling). Ranking is not what keeps rooftop PV off this page.

Where the high scores land is. Pakistan's model was run over all 808 cells, and the 24
one-kilometre windows holding the most household roofs in its national top 5% were looked
at on Esri imagery, nine top-scored roofs each. Six showed panels, all towns: Ibb, Yarim,
Yafi', Khamir, Al Makhadir and Sa'dah. Thirteen showed none: eleven rural hamlets of stone
and mud houses scored above 0.9, Ghayl Bawazir's roofless concrete shells (its top 683
roofs), greenhouse tunnels at Sahar, and the shadows of Thula's tower houses. Sana'a's
windows away from Al Wehdah, where most roofs in view carry panels, hold 45 to 78 roofs in
that top 5%, against 119 to 683 in the 24.
Yemen's own model scores household roofs higher in its sparsest cells than in Sana'a's
(mean 0.019 to 0.023 against 0.013) and puts 67% of its score-weighted roof area in cells
under 100 buildings per km&sup2;. None of this is measured, because only four of the nine
building boxes hold PV and none is a rural hamlet with a false-positive cluster.

**The first measured level: Yafi' and Qa'tabah town (2026-10-29).** The first two PV-rich
town boxes to be mapped ([below](#calibration-areas)) are the first Yemeni test of where
the scores sit, not only how they rank. Against roofclf's own parcel label (`roof_pv_area`
plus `parcel_pv_area`, a roof with PV on 5% of it), Pakistan's unchanged model, read from
its national Yemen scoring (`data/roofclf_transfer/yemen_pk/prob`):

| Roofs | Buildings | With PV | AUC | Score sum per PV roof | Precision of the top-5% flag |
| --- | --- | --- | --- | --- | --- |
| Yafi', below 400 m&sup2; | 932 | 29 (3.1%) | 0.79 | 4.15 | 0.10, at recall 0.69 |
| Yafi', 400 m&sup2; and up | 40 | 6 | 0.69 | 3.28 | 0.20 |
| Qa'tabah town, below 400 m&sup2; | 826 | 18 (2.2%) | 0.89 | 2.74 | 0.25, at recall 0.28 |
| Qa'tabah town, 400 m&sup2; and up | 70 | 10 | 0.81 | 1.42 | 0.28 |
| Pakistan's quadrats, below / at or above 400 m&sup2; | | | | 1.115 / 1.270 | |

It ranks the two towns' roofs as well as it ranks the other boxes, and better in Qa'tabah,
but on household roofs its scores sum to 3.6 per PV roof across the two (170 over 47),
about 3.2 times what they sum to in Pakistan. The boxes were picked for their high scores,
and a window picked that way is partly picked for its scoring errors, which pushes the
ratio up. Qa'tabah town is the least affected of the ten (the fewest high-scoring roofs,
20) and still reads 2.5 times. Everything above inferred the level from where the high
scores land; these two measure it.

## Calibration areas

**Ten PV-rich town boxes (candidates, 2026-10-28; Yafi' and Qa'tabah town mapped
2026-10-29).** Drawn with
`calib-candidates -- --aoi yemen --pv-rich`: 1 km windows of at least 800 buildings per
km&sup2; with the most household roofs Pakistan's classifier scores in its national top 5%,
every window's top-scored roofs looked at on Esri imagery and kept only where panels show
(`data/labels/yemen/candidate_quadrats/pv_rich_review.csv`). Purposive, and chosen on a PV
signal: they add rooftop positives to the fit, and their own adoption runs high by
construction. Sana'a: Ma'in, As Sab'in, Sanhan and Bani Hushaysh; Ibb: Adh Dhihar (Ibb city)
and Yarim; Khamir ('Amran), Sa'dah, Yafi' (Lahij) and Qa'tabah town (Ad Dali'). Esri
imagery from 2024-10 to 2025-12 over every box.

**Yafi', Lahij (registered 2026-10-29, Rule-1).** The first PV-rich box mapped, starred on
the atlas that morning by hand rather than by the classifier: Adh Dhihar in Ibb city holds
the most roofs Pakistan's model scores as likely (439, against Yafi's 196), but on Esri
imagery at the same zoom over the central 600 m of all ten boxes, Yafi' showed the most
distinct rooftop arrays and Adh Dhihar few among cluttered roofs. Mapped panel by panel and
declared finished by the owner the same day (changesets 191180704 and 191180806), against
Esri Vivid imagery of 2025-10-13, inside the composite's window. It holds **40
installations**, 22 rooftop and 18 ground by their overlap with VIDA footprints,
2,519 m<sup>2</sup> in all, median 52 m<sup>2</sup>, every one below 400 m<sup>2</sup> and
34 below 100 m<sup>2</sup>; 35 of its 972 VIDA buildings carry PV under roofclf's parcel
label. The pull was confirmed against a second Overpass query (40 both times). Not yet used
by any figure on this page. With Yafi' registered the star moved on by the default order, to
Adh Dhihar; Yafi' showed that order is a weak guide to PV, since one in ten of the roofs it
counts carried panels.

**Qa'tabah town, Ad Dali' (registered 2026-10-29, Rule-1).** The second PV-rich box mapped,
the town itself, 9.7 km from the rural `qa_tabah_s6` box (which holds no PV). Declared
finished by the owner the same day (changesets 191181245 and 191181493), against Esri Vivid
imagery of 2025-03-21. It holds **31 installations**, 23 rooftop and 8 ground,
2,142 m<sup>2</sup> in all, median 52 m<sup>2</sup>, every one below 400 m<sup>2</sup> and
25 below 100 m<sup>2</sup>; 28 of its 896 VIDA buildings carry PV. Confirmed by a second
Overpass query (31). Not yet used by any figure on this page.

**Ghayl Bawazir, Hadhramaut (registered 2026-10-31, Rule-1, no PV).** The false-alarm
town box (`calib-candidates --false-alarm`), starred on the atlas from 2026-10-30. Swept by
the owner against Esri Vivid imagery of 2025-03-05, within the year before the composite
window: no PV, ground or rooftop. OSM's live API (552 elements, newest edit 2025-10-09, no
power feature) and an Overpass query against the live database (OSM base 2026-10-31
08:17 UTC, 384 elements in the box, none solar) agree, so it is registered with an empty
label file, a confirmed zero. Its 951 VIDA buildings, 933 of them below 400 m<sup>2</sup>,
make it the first town box that measures the classifier's scores on roofs without solar.
Not yet used by any figure on this page. With it registered the star would have moved
on by the default order, to Adh Dhihar; the owner removed Yemen's star instead
(`start_here: none`, 2026-10-31).

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

**Seven farm areas (registered 2026-10-24, Rule-1), behind the farm ground-PV figure.**

- **'Amran** (Huth, 129.5 km&sup2;, Esri imagery June to October 2025): the test ground, 306
  arrays, every one traced around its panels by the owner.
- **Tihama**, six areas, 331.6 km&sup2;, 1,100 installations: the owner's region near Zabid,
  in which every installation was checked by hand. Esri's imagery there runs from August
  2021 to April 2025, so the region was cut to where it shows a capture from 1 October 2024 on
  (12 months before the composite window), then along the 0.1&deg; grid: At Tuhayta (104.2
  km&sup2;), Al Jarrahi west, centre, east and south (53.3, 17.9, 93.3 and 32.6), and Zabid
  (30.3). The other 199 km&sup2; trains the detector and calibrates nothing.

238 of Tihama's installations are the owner's panel traces; most of the rest are rectangles
mapped in 2023 around whole sites, which count at the land constant's share of their area
(owner decision). On Esri's April 2025 imagery, a random sample of 12 rectangles all hold
panels, two to four small groups covering roughly 10 to 25% of each. Every pull was
confirmed by a second Overpass query; Al Jarrahi east's first pull came back 16 features
short and was retried.

## What Yemen needs next

**Map the six town boxes drawn at random, in their order.** `calib-candidates -- --towns`
(2026-10-31) drew a building at random from every building in Yemen's density grid and kept
the 1 km box around it if it holds at least 800 buildings: As Sab'in (Sana'a city), Az
Zaydiah, Dhamar city, Bani Hushaysh, Al Marawi'ah and Bayt al Faqih, 821 to 2,471 buildings
each, under Esri imagery from 2025-04 to 2025-12. No classifier score went into the draw, so
mapped complete they say what Yemen's towns hold, with or without solar; 60 of the 74
buildings drawn lay outside towns, so about one Yemeni building in five sits in one. They
lead the atlas's mapping order.

**The PV-rich town boxes come after them.** Yafi' and Qa'tabah town added
63 PV roofs to the 132 a `roofclf` fit saw in building boxes (Al Wehdah, Sayun, Bani Al
Harith and Huth), and the eight candidates left would add several times that. The two
measured the level in towns where panels show; a box in a place the classifier gets wrong
measures the false positives at the other end. That box was drawn and starred on the atlas
(2026-10-30) and mapped with no PV on 2026-10-31 ([above](#calibration-areas)):
`ghayl_bawazir_fa1_calib_1km`, written by `calib-candidates --false-alarm` at the first
window the PV-rich review marked `no_pv`. Pakistan's model puts 683 of its 966
buildings among Yemen's top 5% of household roofs; on Esri imagery of 2025-03-05 its nine
top-scored roofs are roofless or unfinished concrete shells, none with a panel. Its share
of roofs with solar runs low by design, as the PV-rich boxes' runs high.

**Map farm areas outside the two regions.** `calib-candidates -- --farmland` drew eight 3 km
farm boxes across Yemen's cropland strata (2026-10-23). The farm figure rests on 'Amran and
one Tihama region; boxes in the highland terraces of Ibb and Ta'izz, and in the lowland away
from the Zabid hotspot, are what would let it reach the rest of Yemen's farmland, and a
second highland area would replace 'Amran's judgement interval with a measured one.

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

The 2026-10-24 refresh, on top of that (farm areas registered with
`new_calibration_quadrat.py --aoi yemen --farm --geojson <area>`):

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=41.8,12.1,54.6,19.0 \
  --iso3 YEM --name yemen --tiles 4x3 --timeout 300 --retries 8   # after moving the tile cache aside
pixi run python scripts/drop_solar_thermal.py --aoi yemen --by-id
# screen, calibrate-candidates, density, check-density, prepare_national_osm_solar.py: as in
# run_country_compute.sh
pixi run earthpv groundclf --aoi yemen \
  --weak-region data/labels/yemen/tihama_stale_imagery_region.geojson \
  --osm data/labels/yemen_overpass_solar.parquet
pixi run earthpv groundclf-score-national --aoi yemen
pixi run earthpv groundclf-capacity --aoi yemen --osm-solar data/labels/yemen_national_osm_solar.parquet
pixi run earthpv atlas --aoi yemen --osm-solar data/labels/yemen_national_osm_solar.parquet \
  --include-offgrid-osm --imagery-date-range "Oct 2025 - Mar 2026" \
  --ground-cells data/groundclf/yemen/capacity/ground_cells.parquet
```
