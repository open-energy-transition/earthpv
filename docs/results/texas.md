# Texas: the solar parks, mapped and priced by area

Texas was added on the owner's request on 10 November 2026, with California and Mexico, as
the first state run as an AOI of its own (`division.subtype: region`): its regions are its
254 counties, and the hand-mapped solar is clipped to the state's own outline rather than the
country's. Otherwise it follows the rules every recent country follows: no calibration
quadrats, no register used to calibrate, the segmentation **localized** on Texas's own
OpenStreetMap labels and shipped only if it beats the general model on a held-out region. It
ties on recall and wins on pixel IoU. Since 20 November 2026 this page runs on
`v39r_resnet50_texas`, a ResNet-50 localized the same way, which found more of the held-out
installations than the TerraMind `v39_combined_texas` it replaced
([below](#the-localized-resnet-v39r-2026-11-20)).

Interactive: [Texas under Countries](../atlas-texas.md).

## Headline

| | |
| --- | --- |
| Verified | **45,712.0 MWp** (90% 31,832 to 66,151) |
| Best estimate | **51,488.0 MWp** (90% 43,229 to 70,405) |
| Generation | 79.8 TWh/yr from Best (90% 67.0 to 109.2), 1,551 kWh/kWp |
| Grid | 1,863 imaged cells of 0.1&deg;, of the 6,077 that cover the state; 239 of its 254 counties hold an imaged cell |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 7 August |
| Model | `v39r_resnet50_texas` epoch 18 at threshold 0.3, a localized ResNet-50 (see below) |

!!! warning "A map of the parks, in panel capacity"
    Texas has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor, and recall was not corrected
    (`--recall-reference none`). Best is 51,314.5 MWp ground and 173.5 MWp rooftop: the
    rooftop systems the U.S. Energy Information Administration estimates at **3,529.6 MW**
    are almost all missing. EIA counts **37,200.5 MW** of solar PV in Texas at the end of
    August 2026, 33,670.9 MW of it utility-scale
    ([Electric Power Monthly, table 6.2.B](https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_6_02_b)),
    and its generator inventory lists 34,978.8 MW of utility-scale PV in 251 plants at the end
    of September
    ([EIA-860M](https://www.eia.gov/electricity/data/eia860m/)). Those are **inverter (AC)**
    figures; this page counts **panels (DC)**, and where EIA-860M reports both, Texas's plants
    carry 1.29 times as much panel as inverter capacity, about 45 GW DC for the utility-scale
    fleet. Read Best's 138% of EIA's total with that in mind, and with the parks EIA does not
    list (below).

The page compares the state total with both EIA figures, and the counties with EIA-860M's
utility-scale plants summed by county (101 counties; Yoakum County's 300 MW lies in a cell
that was not imaged). Over those 101 counties Best and EIA rank the counties at Spearman
0.79, and Best is 0.9 to 1.8 times EIA's AC figure in the ten counties with the most
capacity, 0.7 to 1.4 in DC terms. None of these figures is ground truth for this map. Ember's
customs data are national, so this page has no import ceiling.

## Localizing the detector

The holdout is **Bexar County**: 32 cells, 54 of the state's 655 dissolved positives of
400 m&sup2; and up (8.2%), chosen by `pick_val_region.py` from the label map before training;
the largest county, Travis, is never the holdout. `pick_checkpoint_by_recall.py` kept the
val/mIoU pick, epoch 36 at threshold 0.3: the holdout has too few installations of
400 m&sup2; and up to choose among epochs on recall (324 and 44 on its two halves, 50 each
needed).

| Compared at equal pixel precision (0.91) | Local `v39` epoch 36 | General `v5` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 355) | **0.851** | 0.845 |
| of 1,000 m&sup2; and up (of 320) | 0.944 | 0.931 |
| of 500 to 1,000 m&sup2; (of 35) | 0.000 | 0.086 |
| Pixel IoU | **0.816** | 0.761 |
| Pixel F1 | 0.899 | 0.865 |

Recall ties (302 against 300 of 355) and the local model wins on pixel IoU by 0.055, so it
ships under the tie rule. Neither finds arrays below 1,000 m&sup2; in Bexar County at this
precision.

### The localized ResNet (v39r), 2026-11-20

`v39r_resnet50_texas` is the released v28's model, a ResNet-50 pretrained on SSL4EO-S12,
trained on `v39`'s corpus with `v39`'s recipe, so the architecture is the only difference
(`scripts/run_resnet_local.sh`, `configs/terramind_pv_v39r_resnet50_texas.yaml`). Epoch 18
was kept. On the same Bexar County holdout, at the threshold both ship at:

| At threshold 0.3 | ResNet `v39r` | TerraMind `v39` |
| --- | ---: | ---: |
| Pixel precision | **0.929** | 0.906 |
| Pixel recall | **0.914** | 0.891 |
| Mapped arrays of 400 m&sup2; and up found (of 368) | **329** | 302 |
| rooftop, 400 to 5,000 m&sup2; (of 21) | 7 | 6 |
| ground, 400 m&sup2; and up (of 343) | **318** | 292 |

It finds 27 arrays the TerraMind misses and misses none it finds
(`results/fair_score/resnet_local/texas/`). Against the general `v5`, both at pixel precision
0.93 or more, it finds 320 of the 355 installations of 500 m&sup2; and up against 298, pixel
IoU 0.854 against 0.751 (`results/texas_checkpoint_decision.json`).

Bexar County holds few large parks, and California's localized ResNet, which won its own
holdout too, misses much of that state's largest parks
([California](california.md#a-localized-resnet-v38r-built-and-not-shipped-2026-11-20)). So
Texas's was also checked on the parks mapped across the state, with the OSM ground screen run
on its rasters: over the 119 mapped parks above 3 km&sup2; (814 km&sup2;) it detects 726
km&sup2; against `v39`'s 777 (median share of each outline 0.944 against 0.978), and 10 of
the 204 parks above 0.3 km&sup2; are less than half detected, against 2; smaller parks are
detected equally. That is a small loss beside its gains, and it draws far fewer large false
outlines: 3,188 outlines against 7,560, 398 above the cap against 1,109. The owner asked on
19 November for the page to move to it. Best moved from 52,249.8 to 51,488.0 MWp, and
Verified, which is the map, did not move: the page keeps the OSM ground screen run on
`v39`'s rasters.

## Checked against EIA's plants

Texas's plants are in a public inventory with coordinates, so three things could be checked
that no other atlas can check this way:

- **The land constant.** Ground capacity is mapped site area times 0.05 kWp/m&sup2;, measured
  on parks in Pakistan, India and South Africa. In the 86 OSM outlines that hold an EIA-860M
  plant reporting panel capacity for every generator (15,536 MW DC on 330.3 km&sup2;), the
  mapped site holds **0.047 kWp/m&sup2;** pooled, 0.048 median (interquartile 0.041 to
  0.056). The constant holds in Texas, though a single park can differ from it either way.
- **What OSM covers.** 72% of EIA's utility-scale AC capacity has an OSM ground outline within
  2 km of its plant point (62% within 500 m); most of the rest went into operation in 2024 to
  2026. 84.6% of it lies in imaged cells.
- **What OSM has that EIA does not.** 168 km&sup2; of mapped ground outlines (8.4 GWp at the
  land constant) lie more than 2 km from any plant EIA lists as operating in September 2026,
  160 km&sup2; of it in 32 outlines above 1 km&sup2;. They are not phantoms: the TerraMind
  run (`v39`), whose OSM ground screen the page keeps, finds panels over 97% of their area
  in the May to September imagery. They are probably
  newer than EIA's inventory, or EIA places them elsewhere. About 1.8 GWp of Verified lies in
  four counties with no operating plant in EIA-860M (Matagorda, Crockett, Callahan, Garza).

## Plausibility gate

`earthpv check-density` fails 72 counties and flags 74 as suspect of the 239 on the page
(71 and 104 under `v39`),
all on the ground-mounted to rooftop ratio and the share of one cell. The same pattern as
[Denmark](denmark.md) and [Italy](italy.md): the model sees almost no rooftop arrays, so the
denominator is tiny, and a county with one large park has most of its capacity in one cell.
Under `v39`, the review of 18 November added eight such fails (63 before), each a park
judged solar that then held most of its county. Of the ResNet run's unmapped outlines of
1 ha and up, the verdicts carried over from that review settle 347 of 744 (below); the
smaller ones have not been judged, and the EIA comparison above is their only check.

## What is counted

- **OpenStreetMap:** 12,948 reference features inside the state's outline (19,730 of the bbox
  pull lie outside it), placed as 10,818 rooftop, 1,016 ground and 1,114 unknown; 666 of them
  are 400 m&sup2; and up and hold 45,651.3 MWp. Verified is all mapped capacity, almost all
  of it the 1,016 ground outlines (912 km&sup2;).
- **Model:** 3,188 candidates (7,560 under `v39`); none lies inside a mapped solar-thermal
  outline. Best adds 5,776.0 MWp over Verified: in 240 cells the model's priced figure fell
  below the mapped capacity and Best is floored at Verified. Of the 398 outlines above the
  100,000 m&sup2; merge cap (29.5% of candidate area, the largest 8.14 km&sup2;), the 63
  judged solar count whole; the other 335 stay out of capacity, 94 judged not solar, 93 not
  judged yet and 148 never on the review page (near mapped solar, or left out by the lead
  screens). 198 OSM-verified oversize candidates (864.8 km&sup2;) are exempt. 106 priced
  candidates, 114.1 MWp, lie beyond the state's outline in cells kept whole.
- **Judged by a person** (the owner, 18 November 2026, on the `v39` run's two disk review
  pages, carried over to the ResNet run on 20 November): an outline of the new run takes a
  verdict when at least half of it lies inside outlines the owner judged solar, or not solar
  (`scripts/carry_review_verdicts.py`). Of its 250 outlines above the cap, **63 are parks**,
  107.6 km&sup2;, and each counts whole as ground; 94 are not (42.0 km&sup2;, 1 bright
  roof), and 93 (28.9 km&sup2;) are outlines nobody judged, which count nothing until they
  are. Of its 494 leads from 1 ha up to the cap, 48 are solar (1.61 km&sup2; of outline) and
  142 not (5.8 km&sup2;); 304 (11.2 km&sup2;) wait and keep their size bin's price. The
  owner had judged 841 of `v39`'s 845 outlines above the cap (51 parks, 122.9 km&sup2;; 790
  not) and 842 of its 875 large leads (83 solar, 759 not). In that review, against EIA-860M, 19 of the 21 blobs within
  500 m of a solar plant were judged parks, against 32 of the 824 elsewhere; 17 of the
  parks (42.4 km&sup2;, about 2.1 GWp) lie more than 5 km from any plant EIA lists, like
  the mapped outlines EIA lacks (above).
- **Mapping leads:** 1,559 leads and 93 outlines above the cap, none checked, and the 111
  outlines judged solar that mappers get, in release `pv-new-leads-2026-11-02`, linked from
  the page's Downloads.
- **Solar thermal:** none counted. EIA lists no solar thermal capacity in Texas, the OSM scan
  (read from the Geofabrik extract of 11 November, since Overpass refused the area scan) finds
  no concentrated solar power plant, and 4 heating plants without electric output are not
  counted.
- **Footprints:** VIDA, with 26,674 OSM buildings filling 6,013 empty 0.01&deg; blocks across
  the California and Texas boxes (0.09% of 30.2 million). `data/vida/USA.parquet` holds those
  two states only.

## What Texas needs next

**The parks judged solar, mapped.** Mapping the 63 parks judged solar in OpenStreetMap
would move them from Best into Verified.

**The new outlines judged.** 93 outlines above the cap and 304 large leads of the ResNet
run wait on the review pages.

**A rooftop instrument.** Areas mapped panel by panel would start a small-installation half
for the 3.5 GW EIA estimates on rooftops.

**The steps still owed.** Look at a sample of the model's unmapped ground outlines on
high-resolution imagery, and propose calibration areas.

## Reproducing

Texas follows [Scale to a new country](../reproduce.md), with the AOI in `configs/aoi.yaml`
(`division: {subtype: region, iso3: USA}`) and the model in
`configs/terramind_pv_v39r_resnet50_texas.yaml` (the TerraMind it replaced:
`configs/terramind_pv_v39_texas.yaml`). The run is in `data/predictions_resnet_20261119/`
(`release_leads.py` `SOURCES`). The last step:

```bash
pixi run earthpv atlas --aoi texas --pred-dir data/predictions_resnet_20261119 \
  --osm-solar data/labels/texas_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/texas_pv_evidence_atlas.html
```
