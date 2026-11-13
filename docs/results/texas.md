# Texas: the solar parks, mapped and priced by area

Texas was added on the owner's request on 10 November 2026, with California and Mexico, as
the first state run as an AOI of its own (`division.subtype: region`): its regions are its
254 counties, and the hand-mapped solar is clipped to the state's own outline rather than the
country's. Otherwise it follows the rules every recent country follows: no calibration
quadrats, no register used to calibrate, the segmentation **localized** on Texas's own
OpenStreetMap labels and shipped only if it beats the general model on a held-out region. It
ties on recall and wins on pixel IoU, and this page runs on `v39_combined_texas`.

Interactive: [Texas under Countries](../atlas-texas.md).

## Headline

| | |
| --- | --- |
| Verified | **45,712.0 MWp** (90% 31,832 to 66,151) |
| Best estimate | **46,206.4 MWp** (90% 41,310 to 66,432) |
| Generation | 72.2 TWh/yr from Best (90% 64.6 to 103.8), 1,563 kWh/kWp |
| Grid | 1,863 imaged cells of 0.1&deg;, of the 6,077 that cover the state; 239 of its 254 counties hold an imaged cell |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 7 August |
| Model | `v39_combined_texas` epoch 36 at threshold 0.3, localized (see below) |

!!! warning "A map of the parks, in panel capacity"
    Texas has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor, and recall was not corrected
    (`--recall-reference none`). Best is 46,074.5 MWp ground and 132.0 MWp rooftop: the
    rooftop systems the U.S. Energy Information Administration estimates at **3,529.6 MW**
    are almost all missing. EIA counts **37,200.5 MW** of solar PV in Texas at the end of
    August 2026, 33,670.9 MW of it utility-scale
    ([Electric Power Monthly, table 6.2.B](https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_6_02_b)),
    and its generator inventory lists 34,978.8 MW of utility-scale PV in 251 plants at the end
    of September
    ([EIA-860M](https://www.eia.gov/electricity/data/eia860m/)). Those are **inverter (AC)**
    figures; this page counts **panels (DC)**, and where EIA-860M reports both, Texas's plants
    carry 1.29 times as much panel as inverter capacity, about 45 GW DC for the utility-scale
    fleet. Read Best's 124% of EIA's total with that in mind.

The page compares the state total with both EIA figures, and the counties with EIA-860M's
utility-scale plants summed by county (101 counties; Yoakum County's 300 MW lies in a cell
that was not imaged). Over those 101 counties Best and EIA rank the counties at Spearman
0.74, and Best is 0.7 to 1.5 times EIA's AC figure in most of the counties with the most
capacity, about one in DC terms. None of these figures is ground truth for this map. Ember's
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
  160 km&sup2; of it in 32 outlines above 1 km&sup2;. They are not phantoms: the model
  finds panels over 97% of their area in the May to September imagery. They are probably
  newer than EIA's inventory, or EIA places them elsewhere. About 1.8 GWp of Verified lies in
  four counties with no operating plant in EIA-860M (Matagorda, Crockett, Callahan, Garza).

## Plausibility gate

`earthpv check-density` fails 63 counties and flags 133 as suspect of the 239 on the page,
all on the ground-mounted to rooftop ratio and the share of one cell. The same pattern as
[Denmark](denmark.md) and [Italy](italy.md): the model sees almost no rooftop arrays, so the
denominator is tiny, and a county with one large park has most of its capacity in one cell.
Whether the model's ground outlines are themselves right has **not been checked by eye in
Texas**; the EIA comparison above is the check so far.

## What is counted

- **OpenStreetMap:** 12,948 reference features inside the state's outline (19,730 of the bbox
  pull lie outside it), placed as 10,818 rooftop, 1,016 ground and 1,114 unknown; 666 of them
  are 400 m&sup2; and up and hold 45,651.3 MWp. Verified is all mapped capacity, almost all
  of it the 1,016 ground outlines (912 km&sup2;).
- **Model:** 7,560 candidates; none lies inside a mapped solar-thermal outline. Best adds
  494.4 MWp over Verified: in 217 cells the model's priced figure fell below the mapped
  capacity and Best is floored at Verified. 1,109 outlines above the 100,000 m&sup2; merge
  cap (52.4% of candidate area, the largest 15.6 km&sup2;) are excluded from capacity until
  judged; 196 OSM-verified oversize candidates (842.3 km&sup2;) are exempt. 99 priced
  candidates, 94.9 MWp, lie beyond the state's outline in cells kept whole.
- **Waiting for a person:** 845 outlines above the cap (701.1 km&sup2;) on the solar farm
  review and 875 leads from 1 ha up to the cap (29.3 km&sup2;) on the large installation
  review. None is judged yet. Only 20 EIA-860M plants that OSM lacks (2.9 GW AC) lie within
  500 m of one of the blobs, so most of the 701 km&sup2; is probably not solar.
- **Mapping leads:** 2,963 leads and the blob file, in release `pv-new-leads-2026-11-02`,
  linked from the page's Downloads.
- **Solar thermal:** none counted. EIA lists no solar thermal capacity in Texas, the OSM scan
  (read from the Geofabrik extract of 11 November, since Overpass refused the area scan) finds
  no concentrated solar power plant, and 4 heating plants without electric output are not
  counted.
- **Footprints:** VIDA, with 26,674 OSM buildings filling 6,013 empty 0.01&deg; blocks across
  the California and Texas boxes (0.09% of 30.2 million). `data/vida/USA.parquet` holds those
  two states only.

## What Texas needs next

**The reviews.** 845 outlines above the cap and 875 large leads wait on the review pages; a
judged park enters Best, and most of the blobs are probably fields or bare ground.

**A rooftop instrument.** Areas mapped panel by panel would start a small-installation half
for the 3.5 GW EIA estimates on rooftops.

**The steps still owed.** Look at a sample of the model's unmapped ground outlines on
high-resolution imagery, and propose calibration areas.

## Reproducing

Texas follows [Scale to a new country](../reproduce.md), with the AOI in `configs/aoi.yaml`
(`division: {subtype: region, iso3: USA}`) and the model in
`configs/terramind_pv_v39_texas.yaml`. The last step:

```bash
pixi run earthpv atlas --aoi texas \
  --osm-solar data/labels/texas_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/texas_pv_evidence_atlas.html
```
