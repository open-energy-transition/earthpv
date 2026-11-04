# Türkiye: factory roofs the map is missing, and dark ground read as panels

Türkiye was added on the owner's request on 29 October 2026, under the same rules as every
country since the Morocco-Egypt-Yemen-South Africa queue: no calibration quadrats, no
register used, the segmentation **localized** on Türkiye's own OpenStreetMap labels and
shipped only if it beats the general model on a held-out region. The localized model ties
the general one on installation recall and draws tighter outlines, and under the tie rule
this page runs on `v19_combined_turkiye`.

Interactive: [Türkiye PV evidence atlas](../atlas-turkiye.md).

## Headline

| | |
| --- | --- |
| Verified | **10,709.1 MWp** (90% 8,031 to 14,642) |
| Best estimate | **13,103.0 MWp** (90% 11,524 to 15,872) |
| Grid | 5,534 imaged cells of 0.1&deg;, of the 8,319 that cover the country; 81 provinces (geoBoundaries) |
| Imagery | Sentinel-2 L2A, May to September 2026; median scene 31 July, middle half 9 July to 27 August |
| Model | `v19_combined_turkiye` epoch 12, localized (tied `v5_combined_france` on holdout recall, better outlines; see below) |

!!! warning "A floor below 400 m&sup2;, very large outlines not yet judged, and an overcount on open ground"
    Türkiye has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor, where household and most commercial rooftop
    systems sit. It has no glint sample, so `p_unmapped` is 0 and `p_real` collapses to the
    OpenStreetMap-mapped fraction, and recall was deliberately skipped
    (`--recall-reference none`). **774 model outlines above 100,000 m&sup2; (175 km&sup2;)
    wait for a person's judgement** and count nothing until then. **On open ground, above
    all in the east, most of what the model adds is not solar** (below). For comparison,
    TEİAŞ, the transmission operator, reports 25,926.7 MW of solar installed at the end of
    2025, licensed and unlicensed, and 6,222 MWp of panels were imported directly from China
    from January 2017 to August 2026
    ([Ember](https://ember-energy.org/data/china-solar-exports-data/)). That is not a ceiling
    here: China shipped Türkiye about six times as much capacity in cells, which Turkish
    factories assemble into modules. Neither figure is ground truth for the map.

## Localizing the detector

**Labels.** 28,485 OpenStreetMap solar features inside Türkiye after the solar-thermal
filter, which removed two plant outlines in Mersin: 799 plant outlines and 27,686
generators. 24,254 of the generators are panel rows traced inside plant outlines, almost all
by one mapper; most of the others are whole plants of about 1 MW mapped as a single
generator (median 16,800 m&sup2;), which the land constant fits. Dissolved, they make 4,306
installations, 3,790 of them 400 m&sup2; and up.

**Holdout.** Picked from the label map by `scripts/pick_val_region.py` before training:
Gaziantep, 63 cells, with 219 of the country's 3,771 dissolved positives of 400 m&sup2;
and up (5.8%). Konya, with 341, is the largest region and never the holdout. 164 val
chips.

**Corpus and recipe.** 4,787 train chips, 2,704 of all Türkiye's chips holding PV, at
weight 1 (`round(7000 / 4787)`), joined to v5's corpus (Germany, Punjab, Pakistan, Gujarat,
France) for 30,244 chips; the recipe is v5's verbatim. Training waited for the GPU behind
other jobs, and its first two attempts were cut off by machine crashes, the second after
epoch 18. The third, from scratch, reached its best at epoch 12 (val/mIoU 0.785) and
early-stopped after epoch 20, about two and a half hours on the GTX 1060;
`scripts/pick_best_checkpoint.py` compared the best checkpoints of both surviving runs and
kept it.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 164 held-out chips. An
installation is counted once per chip it appears in, and most are panel rows inside
Gaziantep's plants:

| | v5 | v19 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | **0.970** (2,116 of 2,181) | 0.968 (2,111) |
| of which 1,000 m&sup2; and up | **0.953** (584 of 613) | 0.951 (583) |
| of which 500 to 1,000 m&sup2; | **0.977** (1,532 of 1,568) | 0.974 (1,528) |
| 250 to 500 m&sup2; (reported, not decisive) | **0.997** (1,455 of 1,460) | 0.996 (1,454) |
| pixel IoU | 0.548 | **0.581** |
| pixel F1 | 0.708 | **0.735** |

Both models find nearly every mapped array in Gaziantep. The recall difference, 0.002, is
far inside the 0.02 tie band, and a tie goes to the localized model; v19 also draws the
better outlines (pixel IoU +0.033). The holdout separates the checkpoints only weakly: its
installations are large, well-mapped parks.

## The ground-perimeter screen

All 859 mapped ground perimeters of 50,000 m&sup2; and up (181.4 km&sup2;) are at least 90%
imaged, 851 of them at least 98%, and the median one is 99% detected; 13 are under half
detected. Three exceed the 5 km&sup2; cap. Karapınar in Konya (20.3 km&sup2;, 96% detected)
and an 8.5 km&sup2; park in Mardin (98%) are kept whole as parks. A 6.5 km&sup2; outline on
the Konya-Karaman plain, mapped in August 2026, is not detected at all; it earns nothing and is
dropped.

## Plausibility gate

`earthpv check-density` fails 21 of the 81 provinces and marks 36 **suspect**. Most fail the
ground-mount to rooftop ratio of the model's estimate (1,312 MWp rooftop against 5,059 MWp
ground): the missing rooftop denominator of every segmentation-only country, on top of a
fleet that really is mostly ground-mounted. Seven fail single-cell concentration. In Konya
(51% in one cell) and Mardin (83%) that cell holds the two mapped parks above, so the
concentration is real; Niğde, Gaziantep, Hatay, Karaman and Kırşehir sit between 27% and
45%. Published as for every segmentation-only country: stated, not waived.

## What the model adds beyond the map

Best exceeds Verified by 2,393.9 MWp: 827.7 on rooftops and 1,566.2 on the ground. It is
spread thinly, the largest single cell adding 19.8 MWp; by province Ankara adds 117.7,
Bursa 92.2, Manisa 90.3, Adana 88.1 and Van 80.5.

The two largest unmapped outlines below the merge cap in each of the ten cells adding most
were looked at on Esri World Imagery (a quick look, not a review). **On rooftops the gap is
partly real**: three of five are factory roofs covered edge to edge in panels, in Manisa's,
Bursa's and Ankara's industrial estates, that nobody has mapped yet; two are bare white
roofs at Esri's capture date (Uşak, Adana). **On open ground none of ten was solar**: lava
and rocky outcrops north of Lake Van, shaded mountain slopes in the eastern highlands, and
dark or ploughed fields in Thrace and around Kahramanmaraş. Esri's capture dates are not
all known, so a park built on a field since then would be missed; lava and slopes do not
change.

They reach Best through the precision table. With no glint sample, `p_real` is the mapped
fraction of each size bin, and Türkiye's many mapped parks make that fraction high for large
ground outlines: 37.5% above 50,000 m&sup2; and 12.8% from 5,000 to 50,000 m&sup2;. Every
unmapped outline of that size is priced at that share of its area, lava or not. The page
states the problem in its caveats; no filter removes these outlines yet. Verified, which
counts only mapped installations, is not affected.

## Candidate population

27,886 candidates: 6,189 rooftop, 5,302 ground-adjacent, 16,395 with no building, median
6,005 m&sup2;. 2,654 carry a mapped OpenStreetMap geometry. 1,164 exceed the 100,000
m&sup2; merge cap: 311 of them mapped (108.1 km&sup2;) and exempt, **853 model-drawn and
excluded from capacity**, 30.4% of all candidate area, the largest 8.1 km&sup2;. The solar
farm review page (`scripts/oversize_review.py`) holds the 774 that pass the lead screens
(174.9 km&sup2;); none has been judged yet, so they count nothing.

The model's own estimate is **6,427.1 MWp** (`est_mwp_rc`, 90% 4,656 to 8,909), 5,084.1 of
it ground; without a recall reference it equals the precision-weighted `est_mwp_cal`.

**Verified is the hand-mapped layer at the two constants.** 4,307 reference features after
dissolving: 8,773.7 MWp of ground and 1,935.4 of rooftop. 3,085 of them are matched by a
candidate. Best is floored at Verified in 976 cells.

| Province | Verified (MWp) | Best (MWp) |
| --- | ---: | ---: |
| Konya | 1,918.0 | 1,997.2 |
| Şanlıurfa | 871.5 | 933.6 |
| Gaziantep | 576.1 | 626.0 |
| Mardin | 485.2 | 500.7 |
| Ankara | 380.7 | 498.4 |
| İzmir | 333.0 | 404.2 |
| Niğde | 363.2 | 386.1 |
| Kayseri | 333.5 | 382.8 |
| Manisa | 284.8 | 375.1 |
| Kahramanmaraş | 310.7 | 359.9 |
| Diyarbakır | 252.0 | 300.4 |
| Eskişehir | 261.7 | 291.7 |
| Afyonkarahisar | 193.3 | 259.1 |
| Mersin | 207.3 | 235.8 |
| Malatya | 206.2 | 229.6 |

These fifteen of the 81 provinces hold 59% of Best; the page lists all of them.

## Mapping leads and calibration areas

**15,003 mapping leads and 774 very large outlines**, the model's outlines more than 100 m
from any solar feature in OpenStreetMap as of 27 October 2026, are in the release
[`pv-new-leads-2026-11-02`](https://github.com/open-energy-transition/earthpv/releases/tag/pv-new-leads-2026-11-02)
(`turkiye_pv_new_leads.geojson`, most promising first, and `turkiye_pv_blob_leads.geojson`,
largest first), and the atlas links them. The usual screens took out 1,230 small outlines on
ground steeper than 15&deg; and 7,757 open-ground outlines whose peak probability stays below
0.9; 2,141 larger outlines on steep ground are kept and marked `steep_review`, since a
mountainside can carry a solar farm but more often casts a shadow. The surface-water screen
is off for Türkiye. Check every lead against recent imagery before mapping it: on open ground
in the east most are the dark rock and slopes above.

**Eighteen calibration candidates**, none mapped yet, all with Esri imagery at 0.34 m from
May 2025 or later at their centre and corners:

- eight 2 km boxes drawn at random across eight bands of building density, from Kulu in
  Konya to Başakşehir in İstanbul;
- two purposive 1 km start-here boxes, the most large-roof area in the densest quarter:
  Menderes in İzmir, the atlas's starred area, and Aksu in Antalya;
- eight 3 km farm boxes across bands of cropland share, from Gemlik in Bursa to Viranşehir in
  Şanlıurfa, for small arrays beside fields.

98 draws were screened out on older imagery. Six to ten complete areas would start a
small-installation half for Türkiye.

## Operational notes

The queue pulled the labels on 29 October, with Overpass overloaded most of the day, and
composed 5,534 cells (every cell with at least 1,000 buildings, plus every cell holding a
mapped solar feature), done on 2 November. Training then waited for the GPU and survived two
machine crashes, finishing on 3 November. Inference over the 5,534 cells took four hours,
and everything from postprocessing to the atlas under three, more than half of that spent rendering
the solar farm review page.

## What Türkiye needs next

**Judge the solar farm review.** Türkiye has many unmapped parks, and each of the 774
outlines above the merge cap needs one look on the imagery the model saw before it can
count. It is the cheapest capacity on this page to verify.

**Map the factory roofs and parks the model already finds**, from the lead file: the
industrial estates of Manisa, Bursa and Ankara first.

**A filter for dark open ground in the east.** Hard negatives cut on mapped lava fields and
bare rock, or pricing low-confidence open-ground outlines apart, before the model's
ground figure there can be read as solar.

**Calibration areas, mapped panel by panel**, to start a small-installation half below
400 m&sup2;, where most Turkish rooftop systems sit.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=25.6,35.8,44.9,42.2 \
  --iso3 TUR --name turkiye --tiles 10x4 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-country-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_country_queue.sh
```

The queue pulls the labels, runs the solar-thermal filter, composes Türkiye, picks the
holdout and hands the country to `scripts/run_country_compute.sh turkiye` (chips, training,
the v5 comparison, inference and the atlas chain, behind marker files).
