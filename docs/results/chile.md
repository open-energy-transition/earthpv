# Chile: the parks of the north, a first iteration

Chile was added on the owner's request on 13 November 2026, behind Mexico, under the rules
every recent country follows: no calibration quadrats, no register used, the segmentation
**localized** on Chile's own OpenStreetMap labels and shipped only if it beats the general
model on a held-out region. It is the third country trained as a ResNet-50 from the start
(owner, 2026-11-19). The page was published on 22 November 2026 as a **first iteration**:
neither review page has been judged yet, so every very large model outline is still out of
the total.

Interactive: [Chile under Countries](../atlas-chile.md).

## Headline

| | |
| --- | --- |
| Verified | **13,613.7 MWp** (90% 9,503 to 19,666) |
| Best estimate | **13,901.9 MWp** (90% 11,663 to 20,610) |
| Generation | 28.9 TWh/yr from Best (90% 24.2 to 42.8), 2,078 kWh/kWp |
| Grid | 1,590 imaged cells of 0.1&deg;, of the 7,980 that cover the country; 16 regions (geoBoundaries ADM1) |
| Imagery | Sentinel-2 L2A, November 2025 to March 2026 (southern summer), median scene 17 January 2026 |
| Model | `v44r_resnet50_chile` epoch 15 at threshold 0.3, a localized ResNet-50 |

!!! warning "A map of the parks, blind to the rooftops"
    Chile has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor. Best is 13,788.3 MWp ground and 113.6 MWp
    rooftop. IRENA puts Chile's solar PV at **12,032 MW** at the end of 2025, from an official
    source ([Renewable Capacity Statistics 2026](https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2026/Mar/IRENA_DAT_RE_Capacity_Statistics_2026.pdf)),
    and Verified alone, the hand-mapped parks, is above that. Two things can each explain
    it, and neither is measured yet: IRENA's figure may count inverter (AC) capacity, and Texas's and
    California's parks carry 1.27 to 1.29 times as much panel (DC) as inverter capacity; and the
    mapped park outlines are priced at the land constant (0.05 kWp per m&sup2; of site), which
    capacity-tagged parks in India, South Africa, Texas and California read at 0.043 to 0.047.
    Chile's own plant list (CNE, CEN), not on the page yet, would settle both. Panels imported from China from January 2017 to March 2026,
    **18,373 MW** ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are a
    ceiling on what was built since 2017.

None of these figures is ground truth for this map.

## Localizing the detector

The holdout is the **Región del Libertador Bernardo O'Higgins**: 99 cells, 132 of the
country's 809 dissolved positives of 400 m&sup2; and up (16.3%), chosen by
`pick_val_region.py` from the label map before training; the region with the most,
Santiago's Región Metropolitana, is never the holdout.

| Compared at equal pixel precision (0.84) | Local `v44r` epoch 15 | General `v28` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 473) | **0.935** | 0.922 |
| of 1,000 m&sup2; and up (of 463) | 0.952 | 0.940 |
| of 500 to 1,000 m&sup2; (of 10) | 0.100 | 0.100 |
| Pixel IoU | **0.792** | 0.738 |
| Pixel F1 | 0.884 | 0.850 |

Recall ties (a gap of 0.013 against the 0.02 rule) and the local model wins on pixel IoU,
so it ships (`results/chile_checkpoint_decision.json`). Almost every held-out installation
is a park of 1,000 m&sup2; and up; the holdout says nothing about rooftops.

## What the page holds

- **Verified** is 1,248 OpenStreetMap features, 861 of them 400 m&sup2; and up holding
  13,608.0 MWp. Best adds 288.2 MWp; the per-cell floor (Verified plus whatever a person
  judged solar) lifts Best in 332 cells.
- **By region**, Antofagasta (5,190.1 MWp) and Atacama (3,074.2) hold 59% of
  Best, then the Región Metropolitana (1,119.0), Tarapacá (819.6) and Maule (816.5).
- **Solar thermal**: the scan found no concentrated solar power plant tagged with an
  electric output (one thermal plant, El Tesoro, makes hot water), so the page counts no
  CSP. Cerro Dominador's 110 MW tower is therefore not counted as CSP; whether any of its
  site sits in the mapped PV outlines was not checked.
- **Mapping leads**: 2,426 leads and 237 blobs, none confirmed yet, so the page links no lead
  file (owner, 2026-11-19). The polygons file is in release `pv-polygons-2026-11-11`.

## Open

- **Blob review**: 237 model outlines above 100,000 m&sup2; (169.5 km&sup2;), 83% of their area
  in Antofagasta, Tarapacá, Atacama and Arica y Parinacota, where salt flats and evaporation
  ponds can read as panel rows. None counts until mapped or judged.
- **Large installation review**: 387 leads of 10,000 m&sup2; and up (14.9 km&sup2;), in JOSM.
- **Plausibility check**: 11 regions fail and 5 are suspect of 16, on the ground-to-rooftop
  ratio, which has little rooftop capacity to divide by here.
- **Official figures**: CNE/CEN capacity by region into `scripts/official_capacity.py`.
- **Calibration areas**: none drawn yet, so no rooftop estimate below 400 m&sup2;.
