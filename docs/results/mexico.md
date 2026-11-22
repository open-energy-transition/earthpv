# Mexico: the solar parks, a first iteration

Mexico was added on the owner's request on 10 November 2026, with California and Texas,
under the rules every recent country follows: no calibration quadrats, no register used, the
segmentation **localized** on Mexico's own OpenStreetMap labels and shipped only if it beats
the general model on a held-out region. It was the first country switched to a ResNet-50
(owner, 2026-11-19): a TerraMind `v40` had trained one epoch when it was stopped. The page
was published on 22 November 2026 as a **first iteration**: neither review page has been
judged yet, so every very large model outline is still out of the total.

Interactive: [Mexico under Countries](../atlas-mexico.md).

## Headline

| | |
| --- | --- |
| Verified | **12,084.9 MWp** (90% 8,424 to 17,475) |
| Best estimate | **12,358.4 MWp** (90% 11,659 to 17,475) |
| Generation | 22.2 TWh/yr from Best (90% 20.9 to 31.4), 1,797 kWh/kWp |
| Grid | 7,008 imaged cells of 0.1&deg;, of the 17,535 that cover the country; 32 states (geoBoundaries ADM1) |
| Imagery | Sentinel-2 L2A, November 2025 to April 2026 (the dry season), median scene 7 February 2026 |
| Model | `v40r_resnet50_mexico` epoch 10 at threshold 0.3, a localized ResNet-50 |

!!! warning "A map of the parks, blind to the rooftops"
    Mexico has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor. Best is 12,306.8 MWp ground and 51.7 MWp
    rooftop. IRENA puts Mexico's solar PV at **12,912 MW** at the end of 2025, from an
    unofficial source ([Renewable Capacity Statistics 2026](https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2026/Mar/IRENA_DAT_RE_Capacity_Statistics_2026.pdf)),
    so Best is about 96% of it, although Mexico's distributed generation, the small systems
    on homes and businesses, is almost all missing here. Three things can each explain that,
    and none is measured yet: IRENA's figure may count inverter (AC) capacity, and Texas's and
    California's parks carry 1.27 to 1.29 times as much panel (DC) as inverter capacity; the mapped parks
    are priced at the land constant (0.05 kWp per m&sup2; of site), which capacity-tagged parks
    elsewhere read at 0.043 to 0.047; and IRENA flags its figure as unofficial. SENER's and
    CRE's own figures, not on the page yet, would settle it. Panels imported from China from
    January 2017 to April 2026, **21,633 MW**
    ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are a ceiling on what
    was built since 2017.

None of these figures is ground truth for this map.

## Localizing the detector

The holdout is **Chihuahua**: 301 cells, 18 of the country's 156 dissolved positives of
400 m&sup2; and up (11.5%), chosen by `pick_val_region.py` from the label map before
training; Sonora, the state with the most, is never the holdout. Mexico's map is thin, so the
holdout is too.

| Compared at equal pixel precision (0.92) | Local `v40r` epoch 10 | General `v28` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 21) | **0.952** | 0.905 |
| of 1,000 m&sup2; and up (of 17) | 0.941 | 0.882 |
| of 500 to 1,000 m&sup2; (of 4) | 1.000 | 1.000 |
| Pixel IoU | **0.863** | 0.825 |
| Pixel F1 | 0.926 | 0.904 |

The local model finds 20 of the 21 held-out installations against 19, which clears the
0.02 rule, so it ships (`results/mexico_checkpoint_decision.json`); a holdout of 21 cannot
separate the two models by much. The general model reaches this precision only at threshold
0.004.

## What the page holds

- **Verified** is 1,749 OpenStreetMap features: 232 of 400 m&sup2; and up hold 12,054.0 MWp,
  and 1,516 smaller ones 30.9 MWp. Best adds 273.5 MWp; the per-cell floor lifts Best in 96
  cells.
- **By state**: Sonora (2,559.3 MWp), Aguascalientes (1,682.3), Coahuila (1,557.8),
  Chihuahua (1,230.5), San Luis Potos&iacute; (798.5) and Zacatecas (658.3) lead.
- **Solar thermal**: one concentrated solar power plant counts at its tagged 12.0 MW, the
  Agua Prieta solar field. Overpass refused the area scan during the run;
  `solar_thermal_plants.py --pbf` read the Geofabrik extract instead, and no mapped PV feature
  turned out to be thermal.
- **Mapping leads**: 7,674 leads and 662 blobs, none confirmed yet, so the page links no lead
  file (owner, 2026-11-19). The polygons file is in release `pv-polygons-2026-11-11`.

## Open

- **Blob review**: 662 model outlines above 100,000 m&sup2; (379.0 km&sup2;), many in the dry
  north (Sonora alone 127 of them, 88.1 km&sup2;). None counts until mapped or judged.
- **Large installation review**: 1,111 leads of 10,000 m&sup2; and up (36.7 km&sup2;), in JOSM.
- **Plausibility check**: 13 states fail and 16 are suspect of 32, on the ground-to-rooftop
  ratio, which has little rooftop capacity to divide by here.
- **Official figures**: SENER's and CRE's capacity by state into
  `scripts/official_capacity.py`.
- **Calibration areas**: none drawn yet, so no rooftop estimate below 400 m&sup2;.
