# California: the solar parks, mapped and priced by area

California was added on the owner's request on 10 November 2026, with Texas and Mexico, and
is the second state run as an AOI of its own (`division.subtype: region`): its regions are
its counties, and the hand-mapped solar is clipped to the state's own outline rather than the
country's, which keeps the parks around Las Vegas, inside California's bounding box, off the
page. Otherwise it follows the rules every recent country follows: no calibration quadrats,
no register used to calibrate, the segmentation **localized** on California's own
OpenStreetMap labels and shipped only if it beats the general model on a held-out region. It
wins, and this page runs on `v38_combined_california`.

Interactive: [California under Countries](../atlas-california.md).

## Headline

| | |
| --- | --- |
| Verified | **27,118.1 MWp** (90% 19,382 to 38,488) |
| Best estimate | **27,553.6 MWp** (90% 23,451 to 39,056) |
| Generation | 51.2 TWh/yr from Best (90% 43.6 to 72.6), 1,859 kWh/kWp |
| Grid | 1,405 imaged cells of 0.1&deg;, of the 4,203 that cover the state; 57 of its 58 counties hold an imaged cell (not Alpine) |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 29 July |
| Model | `v38_combined_california`, the average of epochs 32 and 40, at threshold 0.95, localized (see below) |

!!! warning "A map of the parks, in panel capacity"
    California has **no calibration quadrats**, so there is no `roofclf` half and no
    instrument below the 400 m&sup2; segmentation floor, and recall was not corrected
    (`--recall-reference none`). Best is 26,587.4 MWp ground (concentrated solar power
    included) and 966.2 MWp rooftop, 883.6 MWp of it hand-mapped: the small-scale systems
    the U.S. Energy Information Administration estimates at **21,240.1 MW**, close to half of
    the state's solar, are almost all missing. EIA counts **46,334.9 MW** of solar power in
    California at the end of August 2026: 24,177.0 MW of utility-scale PV, 917.8 MW of solar
    thermal and those small-scale systems
    ([Electric Power Monthly, table 6.2.B](https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_6_02_b)).
    Its generator inventory lists 25,621.3 MW of utility-scale solar (PV and thermal) at the
    end of September ([EIA-860M](https://www.eia.gov/electricity/data/eia860m/)). Those are
    **inverter (AC)** figures; this page counts **panels (DC)**, and where EIA-860M reports
    both, California's PV plants carry 1.275 times as much panel as inverter capacity (941
    of 984 plants), about 32 GW DC for the utility-scale fleet. Best is 59% of EIA's total
    and about 0.85 of the utility-scale fleet in DC terms.

The page compares the state total with both EIA figures, and the counties with EIA-860M's
utility-scale plants summed by county (44 counties; EIA writes one Kern County row as KERN,
matched to Kern). Over those 44 counties Best and EIA rank the counties at Spearman 0.91.
Best is 0.6 to 1.8 times EIA's AC figure in the ten counties with the most capacity: high in
San Luis Obispo (1.78), Kings (1.39), Los Angeles (1.28) and Kern (1.20), low in the
desert counties, Riverside (0.57), Imperial (0.61) and San Bernardino (0.71); in Riverside
21 km&sup2; of unjudged blobs lie next to EIA plants (below). None of these figures is
ground truth for this map. Ember's customs data are national, so this page has no import
ceiling.

## Localizing the detector

The holdout is **Santa Clara County**: 22 cells, 615 of the state's 6,014 positives (10.2%),
chosen by `pick_val_region.py` from the label map before training; the largest county, Los
Angeles, is never the holdout. Santa Clara is mostly built-up, so it tests rooftop arrays
more than parks. `pick_checkpoint_by_recall.py` chose the average of the val/mIoU pick
(epoch 32) and the last epoch (40), at threshold 0.95: installation recall of 400 m&sup2; and
up 0.589 against epoch 32's 0.507 on the half it chose on, 0.475 against 0.450 on the half
that confirmed it, at epoch 32's pixel precision.

| Compared at equal pixel precision (0.55) | Local `v38` average | General `v5` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 1,254) | **0.554** | 0.499 |
| of 1,000 m&sup2; and up (of 370) | 0.568 | 0.578 |
| of 500 to 1,000 m&sup2; (of 884) | 0.536 | 0.517 |
| Pixel IoU | **0.339** | 0.274 |
| Pixel F1 | 0.504 | 0.444 |

`v5` never reaches the local model's precision, so both are compared at `v5`'s best (0.553,
`v5` at 0.98, the local model at 0.1). The local model finds 695 against 626 installations,
a margin beyond the tie band, and ships at its own threshold, 0.95. That threshold is the
matched one, and for an averaged checkpoint a matched threshold this high can lose arrays
over whole cells (the averaging note in `CLAUDE.md`); the published page uses it as chosen.

## Checked against EIA's plants

EIA-860M lists California's plants with coordinates, so the same three checks as in
[Texas](texas.md) could be run:

- **The land constant.** Ground capacity is mapped site area times 0.05 kWp/m&sup2;,
  measured on parks in Pakistan, India and South Africa. In the 305 dissolved OSM ground
  outlines that hold an EIA-860M PV plant reporting panel capacity for every generator
  (12,580.6 MW DC on 290.2 km&sup2;), the mapped site holds **0.043 kWp/m&sup2;** pooled,
  0.047 median (interquartile 0.038 to 0.061). The constant reads a little high in
  California, by up to about 15% pooled, so the hand-mapped parks may be counted somewhat
  high; the pooled figure is itself a low reading wherever a plant's EIA point falls outside
  the outline that holds its panels.
- **What OSM covers.** 79% of EIA's utility-scale PV capacity (AC) has an OSM ground outline
  within 2 km of its plant point (63% within 500 m); most of the rest went into operation
  from 2023 on. 90.5% of it lies in imaged cells.
- **What OSM has that EIA does not.** 49 mapped ground outlines of 5 ha and up, 38.8 km&sup2;
  (1.9 GWp at the land constant), lie more than 2 km from any plant EIA lists as operating in
  September 2026; the largest, 11.9 km&sup2;, is 7 km from the nearest. They are not phantoms:
  the model finds panels over 83% of their area in the May to September imagery. They are
  probably newer than EIA's inventory, or EIA places them elsewhere. The rest of the
  outlines that far from an EIA plant are small (11.3 km&sup2; in outlines below 5 ha), as
  expected of systems below EIA's 1 MW floor.

## Plausibility gate

`earthpv check-density` fails 18 counties and flags 33 as suspect of the 57 on the page,
all on the ground-mounted to rooftop ratio and the share of one cell. The same pattern as
[Texas](texas.md), [Denmark](denmark.md) and [Italy](italy.md): the model sees almost no
rooftop arrays, so the denominator is tiny, and a county with one large park has most of its
capacity in one cell. Whether the model's ground outlines are themselves right has **not been
checked by eye in California**; the EIA comparison above is the check so far.

## What is counted

- **OpenStreetMap:** 44,476 reference features inside the state's outline (42,034 of the
  bbox pull lie outside it), placed as 21,172 ground, 21,158 rooftop and 2,146 unknown;
  6,254 of them are 400 m&sup2; and up and hold 26,850.4 MWp. Verified is all mapped
  capacity, almost all of it the ground outlines (506 km&sup2; dissolved); 24 outlines above
  5 km&sup2; (223.1 km&sup2;) are kept because the ground screen finds them imaged and at
  least half detected.
- **Solar thermal:** five concentrated solar power plants count at their tagged rating,
  922.0 MW: Mojave Solar (280), Genesis (250) and Ivanpah 1 to 3 (126, 133, 133). EIA-860M
  lists the same seven generators at 922.8 MW nameplate (917.8 MW net summer). No PV outline
  lies inside a plant's mirror field.
- **Model:** 5,308 candidates. Best adds 435.5 MWp over Verified: in 479 cells the model's
  priced figure fell below the mapped capacity and Best is floored at Verified. 188 outlines
  above the 100,000 m&sup2; merge cap (35.5% of candidate area, the largest 19.5 km&sup2;)
  are excluded from capacity until judged; 217 OSM-verified oversize candidates
  (348.0 km&sup2;) are exempt. 37 priced candidates, 7.4 MWp, lie beyond the state's outline
  in cells kept whole.
- **Waiting for a person:** 124 outlines above the cap (94.0 km&sup2;) on the solar farm
  review and 1,176 leads from 1 ha up to the cap (29.7 km&sup2;) on the large installation
  review. None is judged yet. Unlike Texas's, many of the blobs are probably real: 29 of them
  (53.0 km&sup2;, over half the blob area) lie within 500 m of a plant in EIA-860M (37
  plants, 2.8 GW AC), led by Riverside (21.4 km&sup2;) and Kern (19.6 km&sup2;).
- **Mapping leads and polygons:** 3,368 leads and 124 blobs in release
  `pv-new-leads-2026-11-02`, and every model outline (5,270) with the 44,481 OSM features
  in `pv-polygons-2026-11-11`, both linked from the page's Downloads.
- **Footprints:** VIDA, with OSM buildings filling its empty 0.01&deg; blocks across the
  California and Texas boxes (see [Texas](texas.md)). `data/vida/USA.parquet` holds those
  two states only.

## What California needs next

**The reviews.** 124 outlines above the cap and 1,176 large leads wait on the review pages.
A judged park enters Best, and with half the blob area near an EIA plant this is likely the
largest single gain on the page.

**A rooftop instrument.** Areas mapped panel by panel would start a small-installation half
for the 21.2 GW EIA estimates on small systems, the largest gap of any atlas so far.

**The steps still owed.** Look at a sample of the model's unmapped ground outlines on
high-resolution imagery, and propose calibration areas.

## Reproducing

California follows [Scale to a new country](../reproduce.md), with the AOI in
`configs/aoi.yaml` (`division: {subtype: region, iso3: USA}`) and the model in
`configs/terramind_pv_v38_california.yaml`. The last step:

```bash
pixi run earthpv atlas --aoi california \
  --osm-solar data/labels/california_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/california_pv_evidence_atlas.html
```
