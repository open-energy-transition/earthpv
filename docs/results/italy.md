# Italy: a map of the ground-mounted fleet

Italy was added on the owner's request on 7 November 2026 with Portugal, Belgium, the
Netherlands and Luxembourg, under the rules every recent country follows: no calibration
quadrats, no register used, the segmentation **localized** on Italy's own OpenStreetMap labels
and shipped only if it beats the general model on a held-out region. It does, clearly, and this
page runs on `v34_combined_italy`.

Interactive: [Italy under Countries](../atlas-italy.md).

## Headline

| | |
| --- | --- |
| Verified | **12,175.7 MWp** (90% 8,653 to 17,396) |
| Best estimate | **19,972.6 MWp** (90% 16,017 to 25,645) |
| Generation | 29.6 TWh/yr from Best (90% 23.7 to 38.0), 1,481 kWh/kWp |
| Grid | 3,193 imaged cells of 0.1&deg;, of the 3,551 that cover the country; 5 macro-regions (geoBoundaries ADM1) |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 2 August |
| Model | `v34_combined_italy`, the average of epochs 21 and 29, at threshold 0.7, localized (see below) |

!!! warning "A map of the parks, blind to Italy's rooftops"
    Italy has **no calibration quadrats**, so there is no `roofclf` half and no instrument below
    the 400 m&sup2; segmentation floor, and recall was not corrected
    (`--recall-reference none`). The energy services operator, GSE, counts **43,687 MW** of
    panels in operation at the end of 2025
    ([Rapporto Statistico 2025](https://www.gse.it/documenti_site/Documenti%20GSE/Rapporti%20statistici/Solare%20Fotovoltaico%20-%20Rapporto%20Statistico%202025.pdf)),
    so Best is about 46% of the fleet. Two thirds of that fleet (29,391 MW) is on buildings,
    greenhouses and canopies, and the model outlines little of it: Best is 1,612 MWp rooftop
    (908 MWp more since the large roof leads were judged) and 18,360 MWp ground. GSE's
    ground-mounted part, **14,296 MW**, is the figure to read this page against: Best's
    ground-mount is 128% of it. Read it as a map of Italy's ground-mounted solar and of what
    is mapped. Panels imported directly from China, 17.4 GW from January 2017 to August 2026
    ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are well below the
    fleet: Italy built 19.3 GW before 2017 and buys much of the rest through other EU ports, so
    the page does not call that a ceiling.

## Against GSE, by macro-region

GSE publishes its regions; the page's five ADM1 units are ISTAT's macro-regions, so the
regions are summed into them (Trentino-Alto Adige as its two provinces). GSE also gives each
region's ground-mounted share, which the last column applies, rounded as GSE prints it.

| Macro-region | Verified (MWp) | Best (MWp) | GSE, end of 2025 (MW) | GSE ground-mounted (MW, approx.) | Best as a share of GSE ground |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sud | 3,789.3 | 5,590.6 | 9,115 | 4,056 | 138% |
| Centro | 3,058.9 | 4,350.8 | 8,326 | 3,713 | 117% |
| Isole | 2,054.5 | 3,723.9 | 5,783 | 3,139 | 119% |
| Nord-Est | 1,777.3 | 3,286.9 | 10,769 | 1,988 | 165% |
| Nord-Ovest | 1,270.7 | 2,641.9 | 9,695 | 1,353 | 195% |

Against GSE's totals the ranking runs backwards (Spearman's rho -0.5 on the page): the
north, where 82 to 86% of capacity is on buildings, leads GSE's table and trails this one.
Against the ground-mounted part the order is the same in all five, and Best lies above it
in each, by 17% (Centro) to 95% (Nord-Ovest), since the 297 parks judged on 18 November and
the 2,978 large installations judged solar on 19 November (below) count; it was 75% to 121%
before them. GSE's figures end in December 2025 and the imagery runs to September 2026.
Best also carries 1,612 MWp of rooftop, hand-mapped or judged on the review page, which
weighs most against the ground figure in the north. None of these figures is ground truth
for this map.

## Localizing the detector

The holdout is **Nord-Ovest**: 576 cells, 1,415 of the country's 9,174 dissolved positives
of 400 m&sup2; and up (15.4%), chosen by `pick_val_region.py` from the label map before
training; the largest region, Sud, is never the holdout. The localized run kept a snapshot
of each late epoch, and `pick_checkpoint_by_recall.py` chose the average of epochs 21 and 29
at threshold 0.7.

| Compared at equal pixel precision (0.55) | Local `v34` (epochs 21 + 29) | General `v5` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 3,350) | **0.645** | 0.544 |
| of 1,000 m&sup2; and up (of 1,992) | 0.664 | 0.551 |
| of 500 to 1,000 m&sup2; (of 1,358) | 0.635 | 0.608 |
| Pixel IoU | 0.467 | 0.362 |
| Pixel F1 | 0.632 | 0.533 |

The local model finds 337 more of the held-out installations and draws them better. The
general one needed threshold 0.98 to match its precision.

## Plausibility gate

`earthpv check-density` compares each region's ground-mounted capacity with its rooftop
capacity. Four fail and Nord-Ovest is suspect:

| Macro-region | Rooftop (MWp) | Ground (MWp) | Ratio | Status |
| --- | ---: | ---: | ---: | --- |
| Sud | 117.7 | 3,287.7 | 27.9 | fail |
| Centro | 109.4 | 2,364.4 | 21.6 | fail |
| Isole | 88.9 | 2,341.0 | 26.3 | fail |
| Nord-Est | 339.6 | 1,944.5 | 5.7 | fail |
| Nord-Ovest | 330.5 | 1,504.3 | 4.6 | suspect |

The same pattern as [France](france.md) and the [Netherlands](netherlands.md): the model
sees few rooftop arrays, so the denominator is small. The roof leads judged solar on
19 November raised it from 147 to 986 MWp, which took Nord-Ovest from fail to suspect (all
five failed before). Whether the model's ground outlines are themselves right has been
checked by eye for the unmapped outlines of 1 ha and up that the lead screens put on the
two review pages (below); below 1 ha, the agreement with GSE's ground-mounted figures above is the only check so far.

## What is counted

- **OpenStreetMap:** 28,188 reference features inside the border, placed as 13,880 ground,
  11,292 rooftop and 3,016 unknown; after the solar thermal filter and the dissolve 27,703
  remain, 9,340 of them 400 m&sup2; and up holding 12,040.9 MWp. Verified is all mapped
  capacity.
- **Model:** 18,644 candidates. Best adds 7,796.9 MWp over Verified. Of the 405 outlines
  above the 100,000 m&sup2; merge cap (19.1% of candidate area), the 297 judged solar count
  whole; the other 108 (5.4%, the largest 1.13 km&sup2;) stay out of capacity, 79 judged not
  solar, 1 left unsure and 28 never on the review page (near mapped solar, or left out by
  the lead screens). 307 OSM-verified oversize candidates (70.73 km&sup2;) are
  exempt. 79 priced candidates, 9.4 MWp, lie beyond the border in cells kept whole.
- **Judged by a person** (the owner, on the two disk review pages). On 18 November, 376 of
  the 377 outlines above the cap (76.9 km&sup2;): **297 are parks**, 58.8 km&sup2;, and
  each counts whole as ground; 79 are not (one a bright roof), and 1 left unsure stays out
  and stays on the page. On 19 November, 4,416 of the 4,586 leads from 1 ha up to the cap
  (129.1 km&sup2;): **2,978 solar** (86.2 km&sup2; of outline, 78.4 km&sup2; credited,
  roofs at 1/2.5) and 1,438 not (39.2 km&sup2;, 29 of them bright roofs), which now count
  nothing; 170 left unsure keep their size bin's price. Roof leads were mostly solar (680 of
  754), leads beside buildings mostly so (1,666 of 2,339), leads on open ground about half
  (632 of 1,323); by macro-region the solar share ran from 59% (Isole) to 75% (Nord-Ovest).
- **Solar thermal:** 488 of the 28,188 features were thermal and left the PV count. Three
  plants tagged as solar thermal with electric output count 2.1 MW, priced from their site
  area since none states a capacity; one in central Sardinia is probably Ottana's Fresnel
  plant, the other two are unchecked. Nine thermal plants without electric output are not
  counted.
- **Footprints:** VIDA, with 1,360,247 OSM buildings filling 24,975 empty 0.01&deg; blocks
  (8.0% of 16,924,117).

## What Italy needs next

**A rooftop instrument.** Areas mapped panel by panel would start a small-installation half,
and two thirds of Italy's capacity is on buildings.

**The installations judged solar, mapped.** Mapping the 297 parks and 2,978 large
installations the reviews admitted in OpenStreetMap would move them from Best into
Verified; 170 large leads and one blob left unsure wait on the review pages.

**The steps still owed.** Look at a sample of the model's unmapped ground outlines on
high-resolution imagery, publish the mapping leads, and propose calibration areas.

## Reproducing

Italy follows [Scale to a new country](../reproduce.md), with the AOI in
`configs/aoi.yaml` and the model in `configs/terramind_pv_v34_italy.yaml`. The last step:

```bash
pixi run earthpv atlas --aoi italy \
  --osm-solar data/labels/italy_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/italy_pv_evidence_atlas.html
```
