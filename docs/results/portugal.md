# Portugal: a well-mapped fleet of parks, and the rooftops still to come

Portugal was added on the owner's request on 7 November 2026 with Belgium, the Netherlands,
Luxembourg and Italy, under the rules every recent country follows: no calibration quadrats,
no register used, the segmentation **localized** on Portugal's own OpenStreetMap labels and
shipped only if it beats the general model on a held-out region. It does, clearly, and this
page runs on `v30_combined_portugal`. The Azores and Madeira are included, as Spain includes
the Canaries.

Interactive: [Portugal under Countries](../atlas-portugal.md). The map opens on the mainland; the
Azores and Madeira are on it too, a pan to the west, and in every figure.

## Headline

| | |
| --- | --- |
| Verified | **5,830.5 MWp** (90% 4,094 to 8,383) |
| Best estimate | **6,193.6 MWp** (90% 5,342 to 8,490) |
| Generation | 9.9 TWh/yr from Best (90% 8.5 to 13.6), 1,600 kWh/kWp |
| Grid | 948 imaged cells of 0.1&deg;, of the 1,042 that cover the country; 20 regions (18 districts and the two autonomous regions, geoBoundaries) |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 6 August |
| Model | `v30_combined_portugal` epoch 19, localized (see below) |

!!! note "Large installations judged before publication"
    On 10 November the owner judged, on the [large installation review](../contribute/review.md),
    299 of the 309 unmapped model outlines from 1 ha up to the 10 ha merge cap that the lead
    screens keep: 153 are solar and 146 are not. A lead judged solar counts as real (a roof
    outline at 1/2.5 of its area, since the model draws about 2.5 times the array) and one
    judged not solar counts nothing; the ten left blank keep their size class's share. Best
    rose from 6,147.9 to 6,193.6 MWp; Verified did not move.

!!! warning "Mostly the parks: the small rooftops are not measured"
    Portugal has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor, and recall was deliberately not corrected
    (`--recall-reference none`). The energy directorate DGEG counts **7,396 MW** of solar PV
    at the end of September 2026
    ([Estatísticas rápidas das renováveis, n.º 262](https://www.dgeg.gov.pt/pt/estatistica/energia/publicacoes/estatisticas-rapidas-das-renovaveis/),
    provisional), so Best is about 84% of it. That share is high for a Bronze page because
    Portugal's fleet is mostly power plants and OpenStreetMap maps them well: Verified alone
    is 79% of DGEG. Of DGEG's figure, 2,626 MW are self-consumption units (UPAC), mostly on
    roofs and mostly below what this page sees. Panels imported directly from China, 21.6 GW
    from February 2017 to August 2026
    ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are about three times
    the installed fleet, so they are a loose ceiling.

## Against DGEG

DGEG's September bulletin splits its 7,396 MW into 3,936 MW of conventional plants, 2,626 MW
of self-consumption (UPAC), 649 MW of small production units (UPP), 167 MW of micro and mini
generation and 18 MW of concentrating PV. It gives the capacity in MW, without saying whether
that is panel (DC) or inverter (AC) capacity.

Its regions are NUTS II, which the districts on this page do not nest in, so the page compares
the national figure only. Three regions coincide one to one:

| Region | Verified (MWp) | Best (MWp) | DGEG (MW) |
| --- | ---: | ---: | ---: |
| Algarve (the district of Faro) | 685.0 | 692.9 | 725 |
| Região Autónoma da Madeira | 26.6 | 28.0 | 31 |
| Região Autónoma dos Açores | 9.7 | 11.4 | 11 |
| **Portugal** | **5,830.5** | **6,193.6** | **7,396** |

Best's ground-mounted part, 5,978.0 MWp, is above DGEG's conventional plants and small
production units together (4,585 MW). Two things bear on that and neither has been measured in
Portugal: mapped parks convert at the land constant (0.05 kWp per m&sup2; of site), and
licensed capacity in MW may be the inverter rating, below the panels'. None of these figures is
ground truth for this map.

## Localizing the detector

The holdout is the **district of Lisbon**: 28 cells, 125 of the country's 1,255 dissolved
positives of 400 m&sup2; and up (10.0%), picked from the label map before training by
`scripts/pick_val_region.py`; Santarém, the largest, is never the holdout.

| Compared at equal pixel precision (0.90) | Local `v30` epoch 19 | General `v5` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up | **0.915** (1,217 of 1,330) | 0.805 (1,071) |
| of which 1,000 m&sup2; and up | **0.889** | 0.661 |
| Pixel IoU | **0.714** | 0.450 |
| Pixel F1 | **0.833** | 0.619 |

The local model wins by 0.110 on recall, well past the 0.02 tie band, and on every other
measure. It ships at threshold 0.3 (v5 matched it at 0.2).

## Plausibility gate

`earthpv check-density` fails 14 of the 20 regions and flags the other six, all on the ratio of
ground-mounted to rooftop capacity: segmentation finds 18 MWp on roofs against 2,968 MWp on
the ground. As in [Belgium](belgium.md) and [Spain](spain.md), rooftop systems are mostly below
what the sensor resolves, so the rooftop denominator is small. Several districts also fail
single-cell concentration (one cell holds 65% of Lisbon's total, 65% of Bragança's and 56% of
Viseu's). Whether the
model's unmapped ground outlines are themselves right has **not been checked by eye in
Portugal**; Best adds 363.1 MWp over Verified.

## What is counted

- **OpenStreetMap:** 8,156 reference features inside the border after the solar thermal
  filter, 1,315 of them 400 m&sup2; and up. Verified is all mapped capacity.
- **Model:** 2,100 candidates. 150 outlines above the 100,000 m&sup2; merge cap (31.4% of
  candidate area, the largest 2.92 km&sup2;) are excluded from capacity until judged; 110 of
  them wait on the solar farm review, none judged yet. 150 OSM-verified oversize parks
  (77.45 km&sup2;) are exempt.
- **Border cells are kept whole:** 27 priced candidates (15.1 MWp recall-corrected) lie in
  Spain, in cells the page keeps whole, and its total counts them. A combined atlas does not.
- **Solar thermal:** one concentrated solar plant, the &Eacute;vora Molten Salt Platform,
  3.4 MW from its tag.
- **Footprints:** VIDA, with 154,865 OSM buildings filling 3,586 empty 0.01&deg; blocks (2.6% of
  6.03 million).
- **Region names:** geoBoundaries garbles the accents of six district names (UTF-8 read as
  Latin-1); `density._repair_mojibake` restores them.

## What Portugal needs next

**A rooftop instrument.** An area mapped panel by panel would start a small-installation half,
and DGEG's UPAC count says where it matters.

**The steps still owed.** Judge the 110 outlines on the solar farm review, publish the mapping
leads, and propose calibration areas.

## Reproducing

Portugal follows [Scale to a new country](../reproduce.md), with the AOI in `configs/aoi.yaml`
and the model in `configs/terramind_pv_v30_portugal.yaml`. The last step:

```bash
pixi run earthpv atlas --aoi portugal \
  --osm-solar data/labels/portugal_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/portugal_pv_evidence_atlas.html
```
