# Spain: parks mapped one by one, and 324 km&sup2; of outlines still to judge

Spain was added on the owner's request on 2 November 2026, under the same rules as every
country since the Morocco-Egypt-Yemen-South Africa queue: no calibration quadrats, no register
used, the segmentation **localized** on Spain's own OpenStreetMap labels and shipped only if it
beats the general model on a held-out region. It does, clearly, and this page runs on
`v26_combined_spain`. Spain's ground-mounted fleet is unusually well mapped, so Verified is
already most of Best.

Interactive: [Spain PV evidence atlas](../atlas-spain.md).

## Headline

| | |
| --- | --- |
| Verified | **39,379.3 MWp** (90% 28,162 to 55,883) |
| Best estimate | **41,776.7 MWp** (90% 37,232 to 56,235) |
| Generation at Best | 65.0 TWh a year (90% 57.9 to 87.5), at a PVGIS yield of 1,556 kWh/kWp |
| Grid | 5,712 imaged cells of 0.1&deg;, of the 5,752 that cover the country; 17 regions (geoBoundaries) |
| Imagery | Sentinel-2 L2A, May to September 2026; median scene 2 August, middle half 7 July to 2 September |
| Model | `v26_combined_spain` epoch 21, localized (beat `v5_combined_france` on the held-out region; see below) |

Both tiers include Spain's 43 concentrated solar power plants, 2,383 MW at their electric
rating ([solar thermal power plants](../methods/solar-thermal.md)). Without them Verified is
36,996 MWp and Best 39,394 MWp of photovoltaics.

!!! warning "A floor below 400 m&sup2;, and very large outlines not yet judged"
    Spain has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor, where household and most commercial rooftop
    systems sit: the page's rooftop figure is 254 MWp. It has no glint sample, so `p_unmapped`
    is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction, and recall was deliberately
    skipped (`--recall-reference none`), so the model's figures are a precision floor.
    **998 model outlines above 100,000 m&sup2; (324.4 km&sup2;) wait for a person's verdict and
    count for nothing until then** (below). At the land constant they would be 16,220 MWp if
    every one were solar; in the countries judged so far the solar share of outlines has run
    from none (Namibia) to 87% (India). **On open ground most of what the model adds is not
    solar** (below).

    For comparison, Red Eléctrica reports
    [almost 50 GW of solar PV](https://www.ree.es/sites/default/files/2026-03/1103_NP_ISE_2025.pdf)
    at the end of 2025 (33.1% of a 150.8 GW mix), self-consumption included; UNEF, the industry
    association, puts self-consumption at
    [9.3 GW](https://www.unef.es/en/comunicacion/comunicacion-post/solar-self-consumption-in-spain-reaches-93-gw-of-installed-capacity)
    that same date. 59,329 MWp of panels were imported directly from China from January 2017 to
    August 2026 ([Ember](https://ember-energy.org/data/china-solar-exports-data/)). None of these
    is ground truth for the map. REE's regional notes do not give a capacity total for the
    largest PV regions and its data API returned errors on 8 November, so the page draws no
    regional comparison.

## Two things specific to Spain

**The building footprints have holes.** VIDA is the footprint source everywhere else, but in
Spain 3,022 of the 5,803 cells touching the country were empty and 9 of 21 city centres tested
held no building at all, Seville, Valencia and Málaga among them; the Canaries are fine, the
mainland is Microsoft-only with block-shaped gaps. `scripts/fill_vida_from_osm.py` keeps every
VIDA row and adds OpenStreetMap buildings only in 0.01&deg; blocks holding no VIDA footprint:
2.99 million buildings added, 9.37 million in all, and cells with any footprint up from 2,781 to
5,709. OpenStreetMap is itself incomplete in places, so rooftop and ground placement is less
even here than the map suggests.

**A wider net.** The standing rule images cells with at least 1,000 buildings plus every cell
holding mapped solar. On the owner's decision Spain images every cell with at least one building
(5,712 cells rather than about 1,900), because the unmapped parks of a ground-mount country sit
on thinly built land.

## Localizing the detector

**Labels.** 78,421 OpenStreetMap solar features inside the bounding box after the solar-thermal
filter (3,317 plant outlines and 75,104 generators, 9,000 of them nodes). The generator polygons
are small, median 135 m&sup2;, and two mappers last edited most of the features. The filter's last
pass removed 1,409 features, among them Alvarado II and 281 PV-tagged rows inside thermal plants.
Dissolved, the country holds 4,081 installations of 400 m&sup2; and up.

**Holdout.** Picked from the label map by `scripts/pick_val_region.py` before training:
Castilla-La Mancha, 824 cells, with 664 of the 4,081 (16.3%). Castilla y León, with 809, is the
largest region and never the holdout. 1,028 val chips, and a one-cell buffer took 139 chips out
of training.

**Corpus and recipe.** 5,956 Spanish chips (3,856 with PV), 4,789 of them train, at weight 1,
joined to v5's corpus (Germany, Punjab, Pakistan, Gujarat, France) for 31,194 chips; the recipe
is v5's verbatim. Training took just under four hours on the GTX 1060 and stopped after epoch
29 with its best at epoch 21. `scripts/pick_checkpoint_by_recall.py` then scored eleven epoch
snapshots and the best-and-last average against that checkpoint at its own precision: none
reached it, so epoch 21 stands, at the threshold of 0.3.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 1,028 held-out chips, both models
at pixel precision 0.84 (v5 never reaches the localized model's own precision, so they meet at
v5's best, the localized model at 0.3 and v5 at 0.98):

| | v5 | v26 (localized) |
| --- | --- | --- |
| recall, installations at or above 500 m&sup2; | 0.787 (7,557 of 9,604) | **0.863** (8,290) |
| pixel IoU | 0.546 | **0.712** |

By size, with both models at 0.3, where v5's precision is lower (0.814): 1,000 m&sup2; and up
0.577 against **0.749**; 500 to 1,000 m&sup2; 0.879 against **0.909**; 250 to 500 m&sup2;, not
decisive, 0.978 against 0.981. The recall gap, 0.076, is well outside the 0.02 tie band.

## The ground-perimeter screen

All 2,253 mapped ground perimeters of 50,000 m&sup2; and up (844.4 km&sup2;) are at least 90%
imaged, 2,204 of them at least 98%, and the median one is 96% detected; 399 are under half
detected. Eight exceed the 5 km&sup2; cap (60.8 km&sup2;). All eight are imaged whole and at
least 82% detected, so they are kept as parks.

## Plausibility gate

`earthpv check-density` fails 13 of the 17 regions and marks the other 4 **suspect**. Every
failure is the ground-mount to rooftop ratio of the model's estimate (62 MWp rooftop against
13,612 MWp ground): the missing rooftop denominator of every segmentation-only country, on top
of a fleet that really is mostly ground-mounted. Región de Murcia also fails single-cell
concentration: one cell holds 29% of the region and a mapped 8.5 km&sup2; park sits in it.
Published as for every segmentation-only country: stated, not waived.

## Greenhouses do not read as panels

Almería's and Murcia's plastic greenhouses are bright, regular sheets, a plausible
false-positive class, so this was measured before the page was shown
(`scripts/spain_greenhouse_check.py`). The five main districts hold 422 of the model's unmapped
outlines and 68.5 of the 3,126.4 MWp priced on such outlines nationally (2.2%), which is a
ceiling on any confusion because real parks count too. The Campo de Dalías, Spain's largest
greenhouse district, holds 22 outlines and 2.2 MWp.

| District | Outlines | km&sup2; | Priced (MWp) | Review outlines |
| --- | ---: | ---: | ---: | ---: |
| Campo de Dalías | 22 | 0.25 | 2.2 | 0 |
| Níjar | 27 | 1.46 | 3.4 | 1 |
| Campo de Cartagena | 134 | 7.87 | 26.1 | 7 |
| Águilas and Mazarrón | 65 | 1.32 | 11.2 | 2 |
| Huelva coast | 174 | 8.69 | 25.5 | 18 |

Each district's three highest-priced outlines below the merge cap were looked at on Esri World
Imagery (a quick look by the assistant, on the sheet the script draws).
Of the 15, nine are solar, two of those on roofs, and none is a greenhouse; the others are a
truck park, a quarry, a dry gully, a field among greenhouses, forest and an evaporation pond.

Footprints are another matter: greenhouses are traced as buildings. Asked for the most
large-roof area in the densest quarter, the sampler for start-here calibration boxes chose two
windows wholly under plastic in the Campo de Dalías (below).

## What the model adds beyond the map

Best exceeds Verified by 2,397.4 MWp: 53.4 on rooftops and 2,344.0 on the ground, spread over
3,165 cells, the largest adding 10.5 MWp. By region Castilla y León adds 775.3, Andalucía 379.2,
Castilla-La Mancha 373.2, Extremadura 167.2 and Aragón 134.4.

The two largest unmapped outlines below the merge cap in each of the ten cells adding most were
looked at on Esri World Imagery (a quick look, not a review). **Of 20, three are solar parks**
(two near 4.4&deg; W, 42.6&deg; N in Palencia, one in the Campo de Cartagena), one is unclear,
and **16 are not**: bare rock outcrops in the woodlands of Cáceres and Toledo and in the
Pyrenees, arable fields in Palencia and around Seville, and quarries. Esri's capture dates are
not all known, so a park built on a field since then would be missed; rock does not change.

They reach Best through the precision table. With no glint sample, `p_real` is the mapped
fraction of each size bin, and Spain's many mapped parks make that high for large ground
outlines: 39.2% above 50,000 m&sup2; and 8.0% from 5,000 to 50,000 m&sup2;. Every unmapped
outline of that size is priced at that share of its area, rock or not. The page says so in
its caveats; no filter removes these outlines yet. Verified, which counts only mapped
installations, is not affected.

## Candidate population

27,703 candidates: 2,601 rooftop, 3,477 ground-adjacent, 21,625 with no building, median
6,601 m&sup2;. 1,883 carry a mapped OpenStreetMap geometry. 2,049 exceed the 100,000 m&sup2;
merge cap: 701 of them mapped (513.4 km&sup2;) and exempt, and **1,348 model-drawn outlines
(496.0 km&sup2;, the largest 5.6 km&sup2;, 35.8% of all candidate area) excluded from capacity**.
Of those, 1,109 lie more than 100 m from any mapped solar feature, and 998 pass the lead screens
and are in the solar farm review (`data/oversize_review/spain/index.html`). Nobody has judged
them yet.

The model's own estimate is **13,741.6 MWp** (`est_mwp_rc`), 13,674.7 of it ground. Without a
recall reference it equals the precision-weighted `est_mwp_cal`.

**Verified is the hand-mapped layer at the two constants, plus the thermal plants.** 19,428
reference features after dissolving, 4,083 of them 400 m&sup2; and up: 36,795.8 MWp of ground,
200.5 of rooftop and 2,383.0 of solar thermal. 7,505 of them are matched by a candidate. Best is
floored at Verified in 964 cells.

| Region | Verified (MWp) | Best (MWp) | of which solar thermal (MW) |
| --- | ---: | ---: | ---: |
| Extremadura | 10,919.5 | 11,086.7 | 1,009.9 |
| Castilla-La Mancha | 8,114.2 | 8,487.4 | 315.2 |
| Andalucía | 7,677.1 | 8,056.3 | 960.0 |
| Castilla y León | 4,169.7 | 4,945.0 | 0 |
| Aragón | 4,296.4 | 4,430.8 | 0 |
| Región de Murcia | 1,960.3 | 2,000.4 | 30.0 |
| Comunidad Foral de Navarra | 586.3 | 616.7 | 0 |
| Cataluña | 369.4 | 490.8 | 18.1 |
| Comunitat Valenciana | 343.6 | 445.3 | 49.8 |
| La Rioja | 323.9 | 347.1 | 0 |
| Illes Balears | 253.6 | 269.9 | 0 |
| Comunidad de Madrid | 137.9 | 195.3 | 0 |
| Canarias | 128.2 | 134.0 | 0 |
| Galicia | 15.8 | 69.9 | 0 |
| Principado de Asturias | 12.4 | 48.1 | 0 |
| País Vasco | 19.2 | 33.9 | 0 |
| Cantabria | 4.0 | 13.6 | 0 |

## Mapping leads and calibration areas

**11,929 mapping leads and 998 very large outlines**, the model's outlines more than 100 m from
any solar feature in OpenStreetMap as of 2 November 2026, are in the release
[`pv-new-leads-2026-11-02`](https://github.com/open-energy-transition/earthpv/releases/tag/pv-new-leads-2026-11-02)
(`spain_pv_new_leads.geojson`, most promising first, and `spain_pv_blob_leads.geojson`, largest
first), and the atlas links them. The usual screens took out 1,872 small outlines on ground
steeper than 15&deg; and 10,038 open-ground outlines whose peak probability stays below 0.9;
3,282 larger outlines on steep ground are kept and marked `steep_review`. The surface-water
screen is off for Spain. Check every lead against recent imagery before mapping it: on open
ground most are the rock and fields above.

**Eighteen calibration candidates**, none mapped yet, all with Esri imagery from May 2025 or
later at their centre and corners:

- eight 2 km boxes drawn at random across eight bands of building density, from Zaragoza to
  Valencia;
- two purposive 1 km start-here boxes, the most large-roof area in the densest quarter: Vigo's
  car plant, the atlas's starred area, and a dense neighbourhood of Palma. The rule first chose two windows of plastic
  greenhouses in Almería and then central Madrid, whose blocks are traced as single large
  buildings, so those districts were left out by hand, as each box's selection note records;
- eight 3 km farm boxes across bands of cropland share, from Lleida to Cuenca, for small arrays
  beside fields.

Six to ten complete areas would start a small-installation half for Spain.

## Operational notes

The queue pulled the labels on 2 and 3 November and composed 5,712 cells, paused three times on
the owner's request and slowed by disk and network limits, done on 7 November. With Spain given
the GPU first (`scripts/gpu_priority.py`), training took four hours and inference over the 5,712
cells another four, and everything from postprocessing to the first atlas two more. The solar
farm review's first draw died on a timed-out elevation download, and being non-fatal it left its
marker behind; it was redrawn the same morning.

## What Spain needs next

**Judge the 998 very large outlines** at `data/oversize_review/spain/index.html`. This is the
largest open quantity on the page, and the cheapest to settle.

**Map the leads**, starting with the parks the model already outlines in Palencia and the Campo
de Cartagena.

**A filter for bare rock and arable land.** Hard negatives on rock outcrops and fields, or
pricing low-confidence open-ground outlines apart, before the model's ground figure can be read
as solar.

**Calibration areas, mapped panel by panel**, to start a small-installation half below
400 m&sup2;, where almost all of the 9.3 GW of self-consumption sits.

**A regional register.** REE publishes installed capacity by autonomous community through its
data service; once that answers, the page can draw the regions beside the atlas.

## Reproducing

```bash
pixi run python scripts/overpass_labels_chunked.py --bbox=-18.2,27.6,4.4,43.9 \
  --iso3 ESP --name spain --tiles 12x9 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-spain-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G --setenv=QUEUE_ONLY=spain \
  bash scripts/run_country_queue.sh
```

The queue pulls the labels, runs the solar-thermal filter, composes Spain, picks the holdout and
hands the country to `scripts/run_country_compute.sh spain` (chips, training, the v5 comparison,
inference and the atlas chain, behind marker files).
