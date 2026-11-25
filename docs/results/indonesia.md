# Indonesia: the mapped parks and large roofs of an archipelago, a first iteration

Indonesia was added on the owner's request on 20 November 2026, behind Australia, under the
rules every recent country follows: no calibration quadrats, no register used, the
segmentation **localized** on Indonesia's own OpenStreetMap labels and shipped only if it
beats the general model on a held-out region. The localized ResNet-50 lost, so the page runs
on the general `v28`. It was published on 25 November 2026 as a **first iteration**: neither
review page has been judged yet.

Interactive: [Indonesia under Countries](../atlas-indonesia.md).

## Headline

| | |
| --- | --- |
| Verified | **821.9 MWp** (90% 690 to 1,006) |
| Best estimate | **989.5 MWp** (90% 931 to 1,078) |
| Generation | 1.35 TWh/yr from Best (90% 1.27 to 1.48), 1,369 kWh/kWp |
| Grid | 7,427 cells of 0.1&deg; (7,423 imaged, 4 holding only mapped solar), of the 16,366 that cover the country; 34 provinces (geoBoundaries ADM1, from before the 2022 split of Papua) |
| Imagery | Sentinel-2 L2A, April to October 2026, median scene 4 August 2026 |
| Model | `v28_resnet50_south_africa` (the released general model) at threshold 0.98 |

!!! warning "Small rooftop systems are out of sight here"
    Most of Indonesia's rooftop systems (PLTS Atap) are far below the 400 m&sup2;
    segmentation floor, and Indonesia has **no calibration quadrats**, so there is no
    `roofclf` half. Best is 561.2 MWp rooftop and 428.3 MWp ground. IRENA puts Indonesia's
    solar PV at **1,494 MW** at the end of 2025, from an unofficial source
    ([Renewable Capacity Statistics 2026](https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2026/Mar/IRENA_DAT_RE_Capacity_Statistics_2026.pdf)),
    so Best is about 66% of it. ESDM's statistics and PLN's rooftop figures are not on the
    page yet. Panels imported from China from January 2017 to August 2026 come to
    **5,705 MW** ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), but the
    page does not call that a ceiling: over the same months China shipped Indonesia
    51.7 GW of solar cells, 99% of it since 2024, so Indonesia assembles panels of its own.

None of these figures is ground truth for this map.

## Choosing the detector

The holdout is **East Java**: 377 cells, 110 of the country's 1,079 dissolved positives of
400 m&sup2; and up (10.2%), chosen by `pick_val_region.py` from the label map before training;
West Java, the region with the most (641), is never the holdout.

| Compared at equal pixel precision (0.60) | Local `v48r` epoch 7 | General `v28` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 224) | 0.759 | **0.844** |
| of 1,000 m&sup2; and up (of 143) | 0.853 | **0.958** |
| of 500 to 1,000 m&sup2; (of 81) | 0.531 | **0.691** |
| of 250 to 500 m&sup2; (of 22) | 0.545 | **0.864** |
| Pixel IoU | 0.476 | **0.507** |
| Pixel F1 | 0.646 | **0.666** |

The general model wins in every size class, so it ships
(`results/indonesia_checkpoint_decision.json`). It never falls to the localized model's pixel
precision, so both are compared at the general model's best, 0.60, which it reaches at a
threshold of 0.98 (the local model at 0.1); 0.98 is also the threshold the page runs at. A
matched threshold that high can lose arrays over whole cells (CLAUDE.md, the checkpoint
gotcha), so it may cost Best a little.

## What the page holds

- **Verified** is 9,176 OpenStreetMap features: 1,100 of 400 m&sup2; and up hold 745.7 MWp,
  and 8,076 smaller ones, mostly rooftop arrays mappers have traced, hold 76.2 MWp. The model
  adds 167.6 MWp above them. The per-cell floor lifts Best in 113 cells.
- **By province**: West Java 442.9 MWp, East Java 75.5, East Kalimantan 67.0, Banten 60.3,
  West Nusa Tenggara 43.3, North Sulawesi 31.4 and Central Java 25.8.
- **Cirata**, the floating plant on a reservoir in West Java and the largest mapped outline
  (1.86 km&sup2;), is priced like a park on land at 0.05 kWp per m&sup2; of site: 92.8 MWp
  against its rated 192 MWp. Floating plants pack their panels more densely than parks on land;
  no constant for them is measured yet.
- **Solar thermal**: none. The Geofabrik extract held 241 solar thermal elements, none of them in the atlas's OpenStreetMap file, and no concentrated solar power plant.
- **No surface-water screen** on the leads (`lead_water_screen` is off): floating plants such
  as Cirata would fail it.
- **Mapping leads**: 9,400 leads and 163 blobs, none confirmed yet, so the page links no lead
  file (owner, 2026-11-19); 100 small leads on steep ground were dropped and 99 larger ones
  carry `steep_review`. The polygons file (10,131 model outlines and 9,176 OpenStreetMap
  features) is in release `pv-polygons-2026-11-11`.

## Open

- **Blob review**: 163 model outlines above 100,000 m&sup2; (164.8 km&sup2;), most of their
  area in Jambi (66.2 km&sup2;) and Riau (46.3 km&sup2;) on Sumatra; none counts until mapped or
  judged.
- **Large installation review**: 1,193 leads of 10,000 m&sup2; and up, in JOSM.
- **Plausibility check**: none of the 34 provinces fails; 9 are suspect, all on the
  ground-to-rooftop ratio and all below the check's 50 MWp floor: East Kalimantan, Riau, Jambi,
  Central Kalimantan, Gorontalo, Central Sulawesi, Bangka-Belitung, Bali and Bengkulu. Open-pit
  mines or cleared land could be reading as parks; nobody has looked yet.
- **Clouds**: central and northern Sumatra and the Riau Islands had only a handful of clear
  days in the window (Medan and Pekanbaru 4, Batam 6, on each city's best tile), and no window
  tried was better.
- **Official figures**: ESDM's capacity statistics and PLN's rooftop (PLTS Atap) figures into
  `scripts/official_capacity.py`.
- **Floating PV**: a site constant for floating plants, or a capacity tag on Cirata.
- **Calibration areas**: none drawn yet. The thousands of small rooftop arrays mapped in
  OpenStreetMap may hold areas complete enough to calibrate a rooftop classifier on; nobody
  has checked.
