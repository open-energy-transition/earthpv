# Australia: the mapped parks of a rooftop country, a first iteration

Australia was added on the owner's request on 14 November 2026, behind Chile, under the rules
every recent country follows: no calibration quadrats, no register used, the segmentation
**localized** on Australia's own OpenStreetMap labels and shipped only if it beats the general
model on a held-out region. The localized ResNet-50 lost, so the page runs on the general
`v28`. It was published on 22 November 2026 as a **first iteration**: neither review page has
been judged yet.

Interactive: [Australia under Countries](../atlas-australia.md).

## Headline

| | |
| --- | --- |
| Verified | **16,596.1 MWp** (90% 11,683 to 23,818) |
| Best estimate | **16,818.4 MWp** (90% 14,402 to 24,199) |
| Generation | 27.4 TWh/yr from Best (90% 23.4 to 39.4), 1,628 kWh/kWp |
| Grid | 1,985 imaged cells of 0.1&deg;, of the 69,746 that cover the country; 9 regions (geoBoundaries ADM1, "Other Territories" included) |
| Imagery | Sentinel-2 L2A, September 2025 to March 2026, median scene 16 December 2025 |
| Model | `v28_resnet50_south_africa` (the released general model) at threshold 0.2 |

!!! warning "Most of Australia's solar is out of sight here"
    Most of Australia's solar capacity is small systems on the roofs of homes and businesses,
    far below the 400 m&sup2; segmentation floor, and Australia has **no calibration
    quadrats**, so there is no `roofclf` half. Best is 16,369.1 MWp ground and 449.3 MWp
    rooftop. IRENA puts Australia's solar PV at **41,065 MW** at the end of 2025, from an
    official source ([Renewable Capacity Statistics 2026](https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2026/Mar/IRENA_DAT_RE_Capacity_Statistics_2026.pdf)),
    so Best is about 41% of it, and the small rooftop systems make up most of the gap. Panels
    imported from China from January 2017 to March 2026, **46,928 MW**
    ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are a ceiling on what
    was built since 2017. The Clean Energy Regulator's small- and large-scale figures by state
    are not on the page yet.

None of these figures is ground truth for this map.

## Choosing the detector

The holdout is **New South Wales**: 440 cells, 149 of the country's 860 dissolved positives
of 400 m&sup2; and up (17.3%), chosen by `pick_val_region.py` from the label map before
training; South Australia, the region with the most, is never the holdout.

| Compared at equal pixel precision (0.94) | Local `v46r` epoch 12 | General `v28` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 3,791) | 0.034 | **0.303** |
| of 1,000 m&sup2; and up (of 145) | **0.800** | 0.779 |
| of 500 to 1,000 m&sup2; (of 3,646) | 0.003 | **0.283** |
| of 250 to 500 m&sup2; (of 16,536) | 0.997 | 0.773 |
| Pixel IoU | 0.695 | 0.673 |
| Pixel F1 | 0.820 | 0.804 |

By the rule's headline figure the general model wins by a wide margin, so it ships
(`results/australia_checkpoint_decision.json`). **The size split is hard to believe**: the local
model finds almost all held-out arrays of 250 to 500 m&sup2; and almost none of 500 to
1,000 m&sup2;, and the holdout counts thousands of installations in a size range where the
label map has few dissolved positives. The size buckets or the way New South Wales's mapped
rooftops dissolve need a look before this decision is taken as final. On the parks of
1,000 m&sup2; and up the two models are close, and the model adds only 222.3 MWp to the
mapped parks here, so the choice moves Best little.

## What the page holds

- **Verified** is 77,767 OpenStreetMap features: 914 of 400 m&sup2; and up hold 16,141.0
  MWp, and 76,851 smaller ones, mostly rooftop arrays mappers have traced, hold 455.1 MWp. The
  mapped park outlines are priced at the land constant (0.05 kWp per m&sup2; of site), which
  capacity-tagged parks elsewhere read at 0.043 to 0.047, so they may read a little high.
  The per-cell floor lifts Best in 290 cells.
- **By state**: New South Wales 7,712.3 MWp, Queensland 5,248.5, Victoria 2,095.9, South
  Australia 836.1, Western Australia 706.6, the Northern Territory 144.6, the ACT 15.9 and
  Tasmania 4.3.
- **Solar thermal**: two concentrated solar power plants count at 4.9 MW, Jemalong's pilot
  plant (1.1 MW, tagged) and an unnamed mirror field near Port Augusta (3.8 MW from its area).
  Overpass refused the area scan during the run; `solar_thermal_plants.py --pbf` read the
  Geofabrik extract instead, and no mapped PV feature turned out to be thermal.
- **Mapping leads**: 10,446 leads and 81 blobs, none confirmed yet, so the page links no lead
  file (owner, 2026-11-19). The polygons file is in release `pv-polygons-2026-11-11`.

## Open

- **Blob review**: 81 model outlines above 100,000 m&sup2; (37.6 km&sup2;); none counts until
  mapped or judged.
- **Large installation review**: 692 leads of 10,000 m&sup2; and up (15.9 km&sup2;), in JOSM.
- **The detector choice** above, and whether a localized model trained differently does better.
- **Plausibility check**: 6 states fail and 1 is suspect of 9, on the ground-to-rooftop ratio,
  which has little rooftop capacity to divide by here.
- **Official figures**: the Clean Energy Regulator's small- and large-scale capacity by state
  into `scripts/official_capacity.py`.
- **Calibration areas**: none drawn yet. Australia's dense rooftop mapping in OpenStreetMap
  may hold areas that are complete enough to calibrate a rooftop classifier on; nobody has
  checked.
