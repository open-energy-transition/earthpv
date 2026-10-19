# South Africa: the parks are mapped and the localized detector wins, but the roofs are below the floor

South Africa was composed and run on 12 to 14 October 2026, the third country of the
Morocco-Egypt-Yemen-South Africa queue to reach a page. Like [Egypt](egypt.md) and
[Yemen](yemen.md) it started with no calibration quadrats, no national register and no
third-party PV dataset to check against, and it was run under the owner's standing
instruction to **localize the segmentation** on the country's own OpenStreetMap labels and to
ship whichever checkpoint scores better on a held-out region. Unlike theirs, South Africa's
holdout is large enough to decide the question, and the localized `v14_combined_south_africa`
wins it clearly.

Interactive: [South Africa PV evidence atlas](../atlas-south-africa.md).

## Headline

| | |
| --- | --- |
| Verified | **9,393.8 MWp** (90% 7,078 to 12,787) |
| Best estimate | **9,755.6 MWp** (90% 8,789 to 12,875) |
| Grid | 3,647 cells of 0.1&deg;, 9 provinces (geoBoundaries) |
| Imagery | Sentinel-2 L2A, April to September 2026 |
| Model | `v14_combined_south_africa` epoch 41, localized (beat `v5_combined_france` on the held-out Western Cape; see below) |

!!! warning "A precision floor, and blind to most of the country's rooftop solar"
    South Africa has **no calibration quadrats**, so there is no `roofclf` half and no
    instrument below the 400 m&sup2; segmentation floor. It has no glint sample, so
    `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction, and
    recall was deliberately skipped (`--recall-reference none`). For scale, the industry
    association SAPVIA reported **10.12 GW** of installed solar PV in July 2026
    ([SAPVIA](https://sapvia.co.za/south-africas-solar-pv-industry-surpasses-10-gw-milestone/)),
    and the transmission operator's estimate of rooftop capacity alone had passed 8 GW the
    month before
    ([Engineering News, 19 June 2026](https://www.engineeringnews.co.za/article/capacity-of-rooftop-solar-installed-in-south-africa-has-passed-8gw-mark-2026-06-19)).
    This page puts 2.2 GWp on roofs (1.8 hand-mapped, 0.3 from the model). The two published
    figures do not reconcile with each other either: more than 8 GW of rooftop inside 10.12 GW
    would leave about 2 GW for every park in the country, while the 86 capacity-tagged parks in
    OpenStreetMap alone carry 4.8 GW (below). This page does not try to match its total to
    either.

## Localizing the detector

**Labels.** 69,359 OpenStreetMap solar features inside South Africa (36,328 rooftop, 32,985
ground, 46 unclassified), about 241 km&sup2; in all, after the solar-thermal filter dropped
514 elements: 506 unnamed ones and the seven named concentrating solar plants of the Northern
Cape (Khi Solar One, KaXu, Xina, Bokpoort, Karoshoek, Kathu and Redstone). South Africa is the
best-mapped country of this queue by an order of magnitude, with rooftop arrays mapped in
the cities and many utility parks mapped with their capacity.

**Holdout.** Picked from the label map before training by `scripts/pick_val_region.py`:
Western Cape, 250 cells, holding 1,221 of the country's 6,973 dissolved positives of 400
m&sup2; and up (17.5%). Gauteng, with 2,626, is the core and stays in training. The Western
Cape holds 1,742 mapped polygons of 400 m&sup2; and up, 1,014 rooftop and 728 ground, among
them 40 parks of 50,000 m&sup2; and up (16.3 km&sup2;, Grootfontein at 5.8 km&sup2; the
largest). That is 452 positive val chips and 9.7% of South Africa's labelled PV pixels,
against seven chips in Egypt's holdout and nine in Yemen's. One caveat: the compose window,
April to September, is the Western Cape's wet winter.

**Corpus and recipe.** 3,546 train and 636 val chips (2,813 with PV), weighted x2
(`round(7000 / 3,546)`), giving 7,766 of 33,004 corpus rows (23.5%). The recipe is v5's
verbatim. Best epoch 41 on the pooled validation set (val/mIoU 0.811), early-stopped at epoch
49, 16 hours 8 minutes on the GTX 1060.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 636 held-out chips:

| | v5 | v14 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | 0.744 (2,594 of 3,486) | **0.794** (2,769) |
| of which 1,000 m&sup2; and up | 0.708 (1,030 of 1,455) | **0.858** (1,249) |
| of which 500 to 1,000 m&sup2; | **0.770** (1,564 of 2,031) | 0.748 (1,520) |
| 250 to 500 m&sup2; (reported, not decisive) | **0.794** (964 of 1,214) | 0.753 (914) |
| pixel IoU | 0.364 | **0.671** |
| pixel F1 | 0.534 | **0.803** |

Recall decides first and the difference, 0.050, is above 0.02: v14 ships. This is the first
decisive localization win of the queue, and it is not close on outline quality: v14's pixel
IoU is nearly twice v5's. The gain is concentrated in the larger arrays. Below 1,000
m&sup2; v5 finds slightly more, at half the pixel agreement, which is what a detector that
paints generously around small arrays looks like on this measure.

**The whole-country comparison**, after the atlas (`compare_checkpoints_vs_mapped.py`, both
checkpoints inferred over all 3,647 cells, scored against the 7,160 dissolved mapped
installations of 400 m&sup2; and up), finished on 19 October:

| | v5 | v14 (localized, ships) |
| --- | --- | --- |
| pooled recall over mapped installations | 0.612 (4,381) | 0.608 (4,354) |
| recall, 100 to 1,000 m&sup2; | **0.626** (2,855 of 4,558) | 0.598 (2,724) |
| recall, 1,000 to 50,000 m&sup2; | 0.608 (1,488 of 2,449) | **0.656** (1,606) |
| candidates below the 100,000 m&sup2; merge cap | 10,587 | 10,372 |
| median candidate area | 1,500 m&sup2; | 1,700 m&sup2; |
| total candidate area below the cap | 49.6 km&sup2; | 45.1 km&sup2; |
| candidates above the cap | 227 (141.6 km&sup2;) | 406 (286.4 km&sup2;) |
| rooftop share below the cap | 53.0% | 39.9% |

Nationally the two tie (564 installations found by v14 alone against 591 by v5 alone,
McNemar p = 0.44), and v14 is scored largely in-sample here, since it trained on every
province but the Western Cape. The split by size repeats the holdout's: v14 finds more of
the arrays above 1,000 m&sup2;, v5 slightly more of the small ones. **The script's recall
for the 153 parks above 50,000 m&sup2; is not usable here** (0.16 for v14 and 0.25 for v5,
0.63 and 0.65 counting candidates above the cap). Of the 57 parks with no v14 candidate
within 100 m, the probability rasters light 52 over at least half their outline, most of
them completely: where parks stand side by side, `postprocess` merges them into one blob
and then swaps in the outline of a single mapped park, so the cluster's other parks lose
their candidate. One cell near 19.55&deg;E 28.85&deg;S holds 19 mapped parks and two
candidates. Their capacity is not lost, since every mapped park counts in Verified, but
the candidate-based recall understates both checkpoints on clustered parks.

## The ground-perimeter screen and the parks' own capacity tags

`scripts/screen_osm_ground_perimeters.py` scored all **420 mapped ground perimeters of
50,000 m&sup2; and up** (195.4 km&sup2;) against v14's probability rasters. All are fully
imaged; 416 are detected, at a median 100% of their imaged area. The four with nothing
detected were inspected against the composite:

- a 14.2 km&sup2; outline with no name and no panels inside it, beside a real array: dropped
  by the 5 km&sup2; ground cap, as intended;
- Soitec's Touws River plant (36 MW, 1.6 km&sup2;), real, but built from widely spaced
  dual-axis concentrator trackers the model has no example of: kept;
- Teraco Sediba (120 MW, 1.0 km&sup2;), mapped in July 2026 and still a construction site in
  the composite: kept, see below;
- a 6 ha outline offset from a real array next to it: kept.

Three parks above 5 km&sup2; pass the screen and stay in Verified: the Mulilo Total Hydra
Storage project (216 MW, 6.4 km&sup2;), Mooi Plaats (240 MW, 6.4 km&sup2;) and Grootfontein
(225 MW, 5.8 km&sup2;), 91 to 98% detected.

**The land constant holds here too.** 86 of the screened parks carry a
`plant:output:electricity` tag. Together they sum to 4,817 MW on 106.3 km&sup2;, **0.045
kWp/m&sup2;** (median 0.048, interquartile 0.040 to 0.060) against the 0.05 the pipeline
assumes, the same as India's 0.045. The tags are mostly AC contract capacity, so the DC
density is somewhat higher.

**Mapped is not the same as built.** Verified counts a mapped perimeter whether or not panels
stood on it when the imagery was taken; only perimeters above 5 km&sup2; are checked. Three
parks mapped in July and September 2026 were largely construction sites in the April to
September composite: Teraco Sediba (0% detected), Ukuqala Solar (105 MW, 0.5%) and Sonvanger
(100 MW, 25%). Together they put about 260 MWp into Verified at their full outlines.

## Plausibility gate

`earthpv check-density` reports **6 fail and 0 suspect of 9 provinces**. Five fail the
ground-mount to rooftop ratio of the model's own estimate: Northern Cape 116x, Free State 15x,
North West 14x, Limpopo 10x and Western Cape 4.3x, against 325 MWp of rooftop and 2,793 MWp of
ground nationally. That is the missing rooftop denominator seen in [France](france.md) and
[India](india.md): most South African rooftop systems are below what the sensor resolves.
Four provinces fail the single-cell concentration check, and each flagged cell is one mapped
and detected plant: Grootfontein in the Western Cape (41% of the province), Dreunberg in the
Eastern Cape (40%), the three Selema parks in North West (28%) and Zondereinde in Limpopo
(26%). Published with that stated, under the project's precedent for a checked-genuine
failure.

## Candidate population

10,778 candidates after 7 that lay inside solar-thermal outlines were removed: 4,141
rooftop, 2,425 ground-adjacent, 4,212 with no building, median 1,898 m&sup2;. 335
model-drawn candidates exceed the 100,000 m&sup2; merge cap and are excluded from capacity:
178.1 km&sup2;, 53.7% of candidate area, the largest 4.78 km&sup2;. A further 71 oversize
candidates carry an OpenStreetMap plant geometry and are exempt. Of the 24 largest
model-drawn ones, four overlap a mapped park and outrun its outline, one is a park that is
not mapped (26.63&deg;E 26.73&deg;S, 2.6 km&sup2;, in the exported mapping leads at about
rank 1,560 of 8,484), and nineteen are an open-pit mine near Kathu, dark rock, salt pans,
grassland and irrigated fields.

The rest, priced by the precision table, are **3,128.5 MWp** (`est_mwp_rc`, 90% 2,168 to
4,457): 332.5 rooftop and 2,795.9 ground. The table is the first in this queue with real
precision in it: rooftop candidates below 1,000 m&sup2; match a mapped array 57 to 85% of
the time, rooftop candidates above 5,000 m&sup2; 7%, ground candidates 1 to 18% below 50,000
m&sup2; and 45% above it.

**Verified is the hand-mapped layer at the two constants.** 38,049 reference features
inside the border after dissolving, 35,071 rooftop and 2,932 ground: 1,825.3 MWp of rooftop
(90% 1,539 to 2,138) and 7,568.6 MWp of ground (90% 5,264 to 10,962). The Northern Cape,
where most parks of the procurement rounds stand, is 4,710 MWp of it. Best adds the model's
detections where they exceed the mapped value and is floored at Verified in 591 cells,
which is why it sits only 362 MWp higher.

| Province | Verified (MWp) | Best (MWp) |
| --- | ---: | ---: |
| Northern Cape | 4,710.1 | 4,743.1 |
| Western Cape | 980.1 | 1,027.9 |
| Gauteng | 898.0 | 923.4 |
| Free State | 823.7 | 850.5 |
| North West | 775.3 | 798.0 |
| Limpopo | 643.8 | 674.3 |
| KwaZulu-Natal | 187.8 | 268.1 |
| Eastern Cape | 205.7 | 254.1 |
| Mpumalanga | 124.8 | 167.5 |

## Operational notes

Compose built 3,647 cells (3,259 by building density, 1,144 holding a mapped solar
feature, the two overlapping) from 12 October 04:06 to 14 October 00:48, with the 10
October and 12 October compose fixes in place (scene ranking by coverage, band-dropout
check, label cells covering a whole outline; see [India](india.md#a-compose-defect-found-here-and-fixed-for-every-later-country)). The machine's WiFi lost
DNS for about 80 minutes on the evening of 13 October; every remaining cell failed fast, the
compose loop exited cleanly, and the queue booked an unproductive round and a one-hour
cooldown, which was cut short by hand once DNS was back. Inference over 3,647 cells took 2
hours 47 minutes, `postprocess` with the streamed building join 14 minutes and `density` an
hour.

## What South Africa needs next

**A rooftop instrument.** By the transmission operator's estimate most of the country's PV
is on roofs, and almost all of it is below the 400 m&sup2; floor. Rooftop mapping is dense
in parts of Cape Town and Gauteng; an area there mapped panel by panel would be the first
calibration quadrat outside Pakistan and give `roofclf` something to fit against.

**Map the unmapped park and recheck the 2026 construction sites.** One park the model
outlines is not in OpenStreetMap, and three mapped in 2026 were not yet built in the
imagery; a composite from the next dry season would settle them.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=16.4,-34.9,32.9,-22.1 \
  --iso3 ZAF --name south_africa --tiles 8x6 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-country-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_country_queue.sh
```

The queue pulls the labels, runs the solar-thermal filter, composes South Africa, picks the
holdout and hands the country to `scripts/run_country_compute.sh south_africa` (chips,
training, the v5 comparison, inference and the atlas chain, behind marker files).
