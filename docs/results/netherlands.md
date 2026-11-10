# Netherlands: the parks and the largest roofs, in a country of small rooftops

The Netherlands was added on the owner's request on 7 November 2026 with Portugal, Belgium,
Luxembourg and Italy, under the rules every recent country follows: no calibration quadrats,
no register used, the segmentation **localized** on the country's own OpenStreetMap labels and
shipped only if it beats the general model on a held-out region. **It does not**: the general
model finds more of the held-out province's installations, so this page runs on
`v5_combined_france`, at the strict threshold that matches the two models on precision. The
page covers the European Netherlands.

Interactive: [the Netherlands under Countries](../atlas-netherlands.md).

## Headline

| | |
| --- | --- |
| Verified | **3,708.6 MWp** (90% 2,710 to 5,198) |
| Best estimate | **4,567.3 MWp** (90% 3,711 to 6,109) |
| Generation | 4.9 TWh/yr from Best (90% 4.0 to 6.6), 1,077 kWh/kWp |
| Grid | 541 imaged cells of 0.1&deg;, of the 587 that cover the country; 12 provinces (geoBoundaries) |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 10 July |
| Model | `v5_combined_france` epoch 25 at threshold 0.98, general (the localized `v32` lost; see below) |

!!! note "Large installations judged before publication"
    On 10 November the owner judged, on the [large installation review](../contribute/review.md),
    548 of the 549 unmapped model outlines from 1 ha up to the 10 ha merge cap that the lead
    screens keep: 543 are solar and 5 are not. 353 of the solar ones are on roofs, where the
    size class had put the chance of solar near zero. A lead judged solar counts as real (a roof
    outline at 1/2.5 of its area, since the model draws about 2.5 times the array) and one
    judged not solar counts nothing. Best rose from 3,927.2 to 4,567.3 MWp; Verified did not
    move. Dutch roof outlines sit on their footprints more tightly than elsewhere, so 1/2.5,
    measured in Pakistan, may discount them too much.

!!! warning "A precision floor, and blind to most Dutch solar"
    The Netherlands has **no calibration quadrats**, so there is no `roofclf` half and no
    instrument below the 400 m&sup2; segmentation floor, and recall was deliberately not
    corrected (`--recall-reference none`), so the arrays the strict threshold misses are not
    added back. Statistics Netherlands (CBS) counts **29,426.5 MWp** of panels at the end of
    2025 ([85005NED](https://www.cbs.nl/nl-nl/cijfers/detail/85005NED), provisional), so Best
    is about 16% of the fleet. 12.6 GWp of that is in systems of 15 kWp or less. Read this page
    as a map of the parks, the largest roofs and what is mapped, not as an estimate of Dutch
    solar. Panels imported directly from China, 226.7 GW from January 2017 to August 2026
    ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are nearly eight times
    the installed fleet: the Netherlands is the EU's main port of entry for them, so the page
    does not call that a ceiling.

## Against CBS, by province

| Province | Verified (MWp) | Best (MWp) | CBS, end of 2025 (MWp) | Best as a share of CBS |
| --- | ---: | ---: | ---: | ---: |
| Noord-Brabant | 441.3 | 607.4 | 4,998.1 | 12.2% |
| Gelderland | 508.6 | 602.0 | 3,918.7 | 15.4% |
| Zuid-Holland | 178.1 | 318.4 | 3,464.7 | 9.2% |
| Noord-Holland | 209.9 | 303.6 | 2,662.0 | 11.4% |
| Overijssel | 261.8 | 303.9 | 2,395.5 | 12.7% |
| Limburg | 221.1 | 304.3 | 2,222.6 | 13.7% |
| Groningen | 515.3 | 544.4 | 1,984.0 | 27.4% |
| Drenthe | 427.7 | 456.1 | 1,816.1 | 25.1% |
| Utrecht | 74.8 | 120.3 | 1,576.9 | 7.6% |
| Fryslân | 211.3 | 234.8 | 1,470.7 | 16.0% |
| Flevoland | 302.0 | 331.9 | 1,350.2 | 24.6% |
| Zeeland | 227.4 | 255.4 | 1,121.1 | 22.8% |
| **Netherlands** | **3,708.6** | **4,567.3** | **29,426.5** | **15.5%** |

The provinces sum to 3,579.3 MWp Verified and 4,382.5 MWp Best; the rest of the national
totals lies in border cells outside them. CBS assigns 445.9 MWp to no province. The shares are
highest in Groningen, Drenthe, Flevoland and Zeeland, where large ground-mounted systems are
37% to 50% of CBS's figure, and lowest in Utrecht and the two Hollands, where they are 7% to
13%; Spearman's rho between Best and CBS over the twelve is
0.56. CBS splits its national figure into 6,222.2 MWp of large ground-mounted systems,
10,564.4 MWp of large rooftop systems and 12,639.9 MWp of systems up to 15 kWp; Best places
3,636.1 MWp on the ground and 931.2 MWp on roofs. CBS counts panel (DC) capacity. None of
these figures is ground truth for this map.

## Localizing the detector

The holdout is **Zuid-Holland**: 41 cells, 289 of the country's 1,720 dissolved positives of
400 m&sup2; and up (16.8%), picked from the label map before training by
`scripts/pick_val_region.py`; Noord-Brabant, the largest, is never the holdout.

The general model never reaches the local model's precision on this holdout, so the two were
compared at v5's best, which v5 reaches only at threshold 0.98 and the local model at 0.004:

| Compared at equal pixel precision (0.675 to 0.690) | Local `v32` epoch 4 | General `v5` at 0.98 |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up | 0.876 (2,607 of 2,976) | **0.918** (2,731) |
| of which 1,000 m&sup2; and up | 0.882 | **0.950** |
| Pixel IoU | **0.608** | 0.578 |
| Pixel F1 | **0.773** | 0.721 |

The general model finds 0.042 more of the installations, past the 0.02 tie band, so it ships
under the owner's rule, although the local model draws their outlines better. It ships at
threshold 0.98, where a 1 ha lead is 1 ha of near-certain pixels: the owner found only 5 of
the 548 judged large leads not solar, against 8% to 22% in Belgium, which runs its own model at
0.3. The cost is the arrays that do not reach 0.98 anywhere, and recall is not corrected for
them.

## Plausibility gate

`earthpv check-density` fails 11 of the 12 provinces and flags the twelfth, all on the ratio of
ground-mounted to rooftop capacity: segmentation finds 121 MWp on roofs against 2,851 MWp on
the ground. As in [Belgium](belgium.md), rooftop systems are mostly below what the sensor
resolves, so the rooftop denominator is small. Whether the model's unmapped ground outlines are
themselves right has **not been checked by eye in the Netherlands**; Best adds 858.7 MWp over
Verified, most of it the judged large roofs.

## What is counted

- **OpenStreetMap:** 13,882 reference features inside the border after the solar thermal
  filter, 1,875 of them 400 m&sup2; and up. Verified is all mapped capacity.
- **Model:** 5,206 candidates. 25 outlines above the 100,000 m&sup2; merge cap (5.8% of
  candidate area, the largest 1.13 km&sup2;) are excluded from capacity until judged; 7 of
  them wait on the solar farm review, none judged yet. 185 OSM-verified oversize parks
  (44.90 km&sup2;) are exempt.
- **Border cells are kept whole:** 187 priced candidates (34.4 MWp recall-corrected) lie in
  Belgium or Germany, in cells the page keeps whole, and its total counts them. A combined
  atlas does not.
- **Solar thermal:** one plant is tagged as solar thermal with electric output, Zoneiland in
  Almere, and counts 0.5 MW from its site area. Whether it generates electricity rather than
  heat has not been checked.
- **Footprints:** VIDA has large holes in the Netherlands. 2,873,170 OSM buildings fill 7,122
  empty 0.01&deg; blocks, 41% of the 6.96 million footprints used.

## What the Netherlands needs next

**A rooftop instrument.** An area mapped panel by panel would start a small-installation half,
which here is most of the fleet. CBS publishes capacity per municipality, which could calibrate
it as MaStR does Germany's.

**The steps still owed.** Judge the 7 outlines on the solar farm review, publish the mapping
leads, and propose calibration areas.

## Reproducing

The Netherlands follows [Scale to a new country](../reproduce.md), with the AOI in
`configs/aoi.yaml`; the localized model that lost is `configs/terramind_pv_v32_netherlands.yaml`.
Density runs at the shipped threshold, then the atlas:

```bash
pixi run earthpv density --aoi netherlands --districts --threshold 0.98
pixi run earthpv atlas --aoi netherlands \
  --osm-solar data/labels/netherlands_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/netherlands_pv_evidence_atlas.html
```
