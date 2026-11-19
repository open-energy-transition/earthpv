# Denmark: the solar parks, and little else

Denmark was added on the owner's request on 8 November 2026, after Italy, under the rules
every recent country follows: no calibration quadrats, no register used, the segmentation
**localized** on Denmark's own OpenStreetMap labels and shipped only if it beats the general
model on a held-out region. It does, on a small holdout. Since 19 November 2026 this page
runs on `v37r_resnet50_denmark`, a ResNet-50 localized the same way, which found more of the
held-out installations than the TerraMind `v37_combined_denmark` it replaced
([below](#the-localized-resnet-v37r-2026-11-19)).

Interactive: [Denmark under Countries](../atlas-denmark.md).

## Headline

| | |
| --- | --- |
| Verified | **2,639.9 MWp** (90% 1,853 to 3,797) |
| Best estimate | **2,683.1 MWp** (90% 2,236 to 3,950) |
| Generation | 2.9 TWh/yr from Best (90% 2.4 to 4.3), 1,093 kWh/kWp |
| Grid | 704 imaged cells of 0.1&deg;, of the 720 that cover the country; 5 regions (geoBoundaries ADM1) |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 9 July |
| Model | `v37r_resnet50_denmark` epoch 10 at threshold 0.95, a localized ResNet-50 (see below) |

!!! warning "A map of the parks, blind to Denmark's rooftops"
    Denmark has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor, and recall was not corrected
    (`--recall-reference none`). The Danish Energy Agency registers **5,468 MW** of
    grid-connected solar on 30 September 2026, the last day of the imagery window
    ([Solcelleudbygningen i Danmark pr. 3. kvartal 2026](https://ens.dk/media/8490/download)),
    so Best is about 49% of the fleet. 3,164 MW of the register is 83 plants with neither
    subsidy nor self-consumption, which is where Denmark's parks are, and 238 MW more is 48
    tendered plants; the rest is some 175,000 mostly small systems. Best is 2,628 MWp ground
    and 55 MWp rooftop, so read it as a map of the parks and of what is mapped. Panels imported
    directly from China, 4.35 GW from January 2017 to August 2026
    ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are a quarter below the
    registered fleet: much of Denmark's supply comes through other EU countries, so the page
    does not call that a ceiling.

The agency's quarterly note gives no regional figures, so the page compares the national
total only. It gives MW without saying whether that is panel (DC) or inverter (AC) capacity.
None of these figures is ground truth for this map.

## Localizing the detector

The holdout is **Nordjylland**: 111 cells, 58 of the country's 476 dissolved positives of
400 m&sup2; and up (12.2%), chosen by `pick_val_region.py` from the label map before
training; the largest region, Syddanmark, is never the holdout. `pick_checkpoint_by_recall.py`
chose epoch 28 at threshold 0.95.

| Compared at equal pixel precision (0.89) | Local `v37` epoch 28 | General `v5` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 98) | **0.531** | 0.459 |
| of 1,000 m&sup2; and up (of 71) | 0.732 | 0.620 |
| of 500 to 1,000 m&sup2; (of 27) | 0.000 | 0.037 |
| Pixel IoU | 0.793 | 0.768 |
| Pixel F1 | 0.880 | 0.862 |

The local model finds 52 of the 98 held-out installations against 45, all of its gain among
arrays of 1,000 m&sup2; and up. At the strict thresholds both need to reach this precision
neither finds arrays below 1,000 m&sup2; in Nordjylland, and a holdout of 98 installations
cannot separate the two models by much.

### The localized ResNet (v37r), 2026-11-19

`v37r_resnet50_denmark` is the released v28's model, a ResNet-50 pretrained on SSL4EO-S12,
trained on `v37`'s corpus with `v37`'s recipe, so the architecture is the only difference
(`scripts/run_resnet_local.sh`, `configs/terramind_pv_v37r_resnet50_denmark.yaml`). Epoch 10
was kept. On the same Nordjylland holdout, at the threshold both ship at:

| At threshold 0.95 | ResNet `v37r` | TerraMind `v37` |
| --- | ---: | ---: |
| Pixel precision | **0.927** | 0.894 |
| Pixel recall | **0.903** | 0.876 |
| Mapped arrays of 400 m&sup2; and up found (of 120) | **77** | 52 |
| rooftop, 400 to 5,000 m&sup2; (of 24) | **17** | 2 |
| ground, 400 m&sup2; and up (of 96) | **60** | 50 |

It finds 26 arrays the TerraMind misses and misses 1 it finds
(`results/fair_score/resnet_local/denmark/`). Against the general `v5` at `v5`'s best pixel
precision, 0.90, it finds 59 of the 98 installations of 500 m&sup2; and up against 44, pixel
IoU 0.835 against 0.768, so it passes the same rule `v37` did
(`results/denmark_checkpoint_decision.json`). The owner moved the page to it on 19 November
2026. Nationally it draws 1,305 outlines against 543; the calibration table prices its size
bins lower, so Best moved from 2,695.1 to 2,683.1 MWp, and Verified, which is the map, did
not move. No outline of the TerraMind run had been judged, so no verdict was carried over.

## Plausibility gate

`earthpv check-density` compares each region's ground-mounted capacity with its rooftop
capacity. Four fail and one is suspect:

| Region | Rooftop (MWp) | Ground (MWp) | Ratio | Status |
| --- | ---: | ---: | ---: | --- |
| Syddanmark | 2.26 | 728.5 | 322.5 | fail |
| Sjælland | 1.04 | 276.8 | 266.6 | fail |
| Midtjylland | 2.57 | 640.0 | 249.0 | fail |
| Nordjylland | 0.88 | 198.2 | 225.8 | fail |
| Hovedstaden | 0.88 | 21.0 | 23.8 | suspect |

The same pattern as [Belgium](belgium.md) and the [Netherlands](netherlands.md): the model
sees almost no rooftop arrays, so the denominator is tiny. One cell in Syddanmark also holds
25% of that region's model capacity. Whether the model's ground outlines are themselves right
has **not been checked by eye in Denmark**.

## Solar heating fields

Denmark has more large solar thermal collector fields, feeding district heating, than any
other country, and from orbit they look like solar parks. The OSM scan found 684 solar
thermal elements; the 54 model outlines lying at least half inside one of the 674 mapped
thermal polygons (2.32 km&sup2;) were dropped before pricing. A heating field nobody has
mapped stays in, counted as photovoltaics. One plant named a solar heating plant, Høng
solvarmeanlæg, carries `plant:output:electricity=yes`, so the page counts it as a solar
thermal power plant of 1.7 MW priced from its 0.06 km&sup2; site; it is probably mis-tagged.
Twelve thermal plants without electric output are not counted.

## What is counted

- **OpenStreetMap:** 3,875 reference features inside the border, placed as 2,093 rooftop,
  1,728 ground and 54 unknown; 606 of them are 400 m&sup2; and up and hold 2,605.3 MWp.
  Verified is all mapped capacity.
- **Model:** 1,251 candidates after the solar heating filter. Best adds only 43.2 MWp over
  Verified: in 181 cells the model's priced figure fell below the mapped capacity and Best
  is floored at Verified. 14 outlines above the 100,000 m&sup2; merge cap (16.2% of candidate
  area, the largest 2.39 km&sup2;) are excluded from capacity; 75 OSM-verified oversize
  candidates (37.60 km&sup2;) are exempt. 80 priced candidates, 12.3 MWp, lie beyond the
  border in cells kept whole.
- **Waiting for a person:** 58 leads from 1 ha up to the cap (1.0 km&sup2;) on the large
  installation review, none judged yet. The solar farm review is empty: of the 14 outlines
  above the cap, 12 lie within 100 m of mapped solar and 2 outside the country's regions (at
  sea or across the border).
- **Footprints:** VIDA, with 158,905 OSM buildings filling 3,881 empty 0.01&deg; blocks
  (4.2% of 3,739,916).

## What Denmark needs next

**A rooftop instrument.** Areas mapped panel by panel would start a small-installation half;
some 175,000 registered systems are below what the model sees.

**The review.** 58 large leads wait on the large installation review.

**The steps still owed.** Look at a sample of the model's unmapped ground outlines on
high-resolution imagery for heating fields, publish the mapping leads, and propose
calibration areas.

## Reproducing

Denmark follows [Scale to a new country](../reproduce.md), with the AOI in
`configs/aoi.yaml` and the model in `configs/terramind_pv_v37r_resnet50_denmark.yaml` (the
TerraMind it replaced: `configs/terramind_pv_v37_denmark.yaml`). The run is in
`data/predictions_resnet_20261119/` (`release_leads.py` `SOURCES`). The last step:

```bash
pixi run earthpv atlas --aoi denmark --pred-dir data/predictions_resnet_20261119 \
  --osm-solar data/labels/denmark_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/denmark_pv_evidence_atlas.html
```
