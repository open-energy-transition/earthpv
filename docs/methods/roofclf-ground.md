# Farm ground PV (roofclf_ground)

!!! note "PARTIAL (2026-10-23): built and measured, not yet in any atlas"

    The detector, its national scoring, its capacity step and the farm calibration areas
    it needs all exist and were run on Yemen. No published figure uses it yet: its
    capacity calibration rests on one completely mapped area, which covers 12 of Yemen's
    810 imaged cells. Three or more mapped farm areas are what move it into an atlas.

Small solar arrays beside fields, most of them powering irrigation pumps, are a large and
fast-growing class in arid countries, and neither of the project's two instruments sees
them. `roofclf` asks whether a roof carries PV, and these arrays have no roof. The
segmentation model ignores everything below 400 m<sup>2</sup> and, in the area measured
here, found almost none of them above it either. `roofclf_ground` is the third
instrument: it reads pixels rather than buildings, and is trained on farm areas rather than
on rooftop quadrats.

## Why the other instruments miss these arrays

The evidence comes from a test ground in 'Amran, Yemen (43.93 to 44.02 E, 16.21 to 16.33 N,
about 130 km<sup>2</sup>), where every array visible in Esri World Imagery from June 2025
was traced around its panels and mapped in OpenStreetMap: 306 arrays, median
581 m<sup>2</sup>.

- **No roof to score.** Only 6.6% of the mapped array area lies on a VIDA building
  footprint, and 73% of the arrays touch no footprint at all. The arrays stand next to
  fields and wells, not on houses.
- **Segmentation does not fire.** Of the first 283 arrays, the shipped Yemeni model (v13)
  touched none and v5 touched 4.

## Why the pixels can see them anyway

Measured against a 30 m ring of land around each array, the pixels inside are darker in the
visible and near infrared and almost unchanged in the shortwave infrared:

| Band | B02 | B03 | B04 | B05 | B06 | B07 | B08 | B8A | B11 | B12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Inside vs ring, median | -7% | -12% | -13% | -8% | -12% | -13% | -21% | -12% | 0% | -4% |

The near-infrared drop is the panel absorption described in
[How roofclf sees panels](roofclf-physics.md). The flat shortwave infrared is partly a
resolution effect: B11 and B12 are 20 m bands, so a few hundred square metres of panels is
mixed with bright soil. That combination is what the SPPI index measures, and on its own,
with no training, SPPI separates PV pixels from the rest of the test ground at AUC 0.93.

## The Tihama labels, and why the Yemeni model learned nothing

Yemen's segmentation model was trained, at eight times weight, on 1,697 OpenStreetMap
arrays in the Tihama plain, and its results page put the failure down to the sensor. That
explanation was wrong. The Tihama arrays are the same size class as 'Amran's (median
617 m<sup>2</sup>), but they are mapped as four-corner rectangles drawn around the plot, and
averaged over the rectangle the panels disappear: the rectangles read slightly *brighter*
than their surroundings in the visible bands, and SPPI scores 0.25 to 0.58 against them.

The rectangles still contain the arrays. Read as **bags**, each one known to hold PV
somewhere inside, their most PV-like pixel stands out: against the same shapes moved 300 m
to 2 km into nearby land, a model trained only in 'Amran separates them at AUC 0.78, the
117 mapped nodes at 0.92 and 56 panel-traced polygons at 0.98. So the labels were usable;
training them as masks was not.

## How the detector works

**Features.** Twenty per pixel, from the composite the rest of the pipeline uses: the log
of the ten bands, NDVI, NDBI, SPPI, and, for five bands, SPPI and NDVI, the pixel minus the
median of its 70 m neighbourhood ("darker than what surrounds it").

**Two kinds of training area.**

- **Clean areas**: farm calibration areas and any boundary passed as `--clean-region`, in
  which every visible panel is traced. Pixels at least half covered by panels are positives,
  pixels more than 20 m from any PV are negatives. Only clean areas give precision, the
  detection threshold and the capacity calibration.
- **Weak areas** (`--weak-region`): ordinary OpenStreetMap, oversized polygons and nodes
  included. Each label is a bag whose two most PV-like pixels become positives, re-chosen
  over three refits that start from SPPI (multiple-instance learning). Negatives keep
  100 m from any label. Weak areas only ever train.

The model is a balanced logistic regression, the same fitting code as `roofclf`. Skill is
reported leave-one-strip-out (each area cut into four strips, every fold holding one strip
out of every area) and, when there is more than one area, leave-one-area-out, which is the
figure that says what a new country should expect.

**Blobs and the threshold.** Pixels above the threshold join into 8-connected blobs. The
threshold is a logit, chosen as the lowest one at which the clean areas' held-out blobs
reach a precision of 0.5. Logits rather than probabilities, because a balanced fit puts
every strong detection at a probability that rounds to 1.0 and ties the leads a reviewer
should see first.

**Three vetoes**, each measured against reviewed leads in 'Amran:

| Veto | Rule | Measured |
| --- | --- | --- |
| Paved road | 30% or more of a blob within 8 m of an OSM motorway, trunk, primary, secondary or tertiary centreline, or an asphalt way | Removed the 9 leads on 'Amran's trunk road and none of the 11 leads the reviewer confirmed. A plain road buffer would have removed real arrays 0 to 5 m from roads. |
| Water | The blob's B11 more than 20% darker than its ring | Water-harvesting ponds are dark in the visible like panels, but also in the shortwave infrared. Removed 11 leads, including all six read as ponds on imagery, and 0 of 301 mapped arrays. A water index does not work: in a dry-season median the ponds read dry. |
| Outside the region of interest | No pixel within 50 m of a VIDA building, a WorldCover cropland pixel or a green pixel (NDVI 0.25 or more) | 96% of 'Amran's arrays lie inside it, in 28% of the land. It bought only 3 to 6 points of precision there; its purpose is dark rock and shadowed slopes far from any field. |

The road veto is applied in the capacity step, as a vector overlap on the blobs, so the
national scoring pass never waits on Overpass.

## From blobs to capacity

`roofclf-ground-capacity` prices only what the atlas does not already count, the same rule
every component follows:

1. Kept blobs (vetoes, region of interest) more than 20 m from any OpenStreetMap solar
   feature, which is counted from the map, and from any segmentation candidate whose
   figure the atlas uses.
2. Times a ratio measured on the clean areas: true mapped PV area divided by detected blob
   area, the same idea as `roofclf`'s coverage ratio. Its uncertainty is a bootstrap over
   clean areas, never over pixels or blobs, and with fewer than three areas no interval is
   reported.
3. Times 0.18 kWp/m<sup>2</sup>, the module constant, because farm arrays are traced around
   their panels.

**Below 400 m<sup>2</sup> by default.** The ratio's numerator counts only arrays smaller
than `--max-array-m2` (400 m<sup>2</sup>, the project's segmentation floor), so the estimand
matches `roofclf`'s. In 'Amran that is 12% of the mapped array area: the other 88% is in
larger arrays, which segmentation misses there too. `--max-array-m2 0` prices farm arrays of
every size.

**A calibration domain.** The headline counts only cells whose cropland share and building
density lie within 25% of the range the clean areas span, the same rule `roofclf` applies
with its building-density band. Everything else is reported separately, as an
extrapolation. This was added after the first national test: on the first 60 cells of western
Yemen the detector priced 46.5 MWp, most of it in Al Hudaydah city and its shore at 0 to 4%
cropland, with a ratio measured on highland farms. 'Amran alone (6.6% cropland,
46 buildings per km<sup>2</sup>) makes 12 of Yemen's 810 cells in domain.

## Farm calibration areas

Rooftop quadrats are the wrong ground truth for this instrument, and the instrument's
ground truth is wrong for the rooftop one. Farm areas therefore have their own sampler and
their own name.

```bash
pixi run calib-candidates -- --aoi yemen --farmland --dry-run
pixi run calib-candidates -- --aoi yemen --farmland
```

`--farmland` runs the recipe of [automated quadrat selection](../calibration-mapping-protocol.md#automated-quadrat-selection)
on cropland instead of buildings: the country's imaged cells are cut into eight bands of
equal cropland area by their ESA WorldCover cropland share, one cell is drawn per band
weighted by cropland, a 3 km box (farm PV is sparse, about two arrays per km<sup>2</sup> in
'Amran) is placed where its own cropland share is within 25% of the cell's, and the same
Esri imagery check applies. For Yemen it drew eight boxes from 5.6% to 85% cropland, all
under 2025 imagery. The three samplers (building strata, start-here boxes, farm boxes) each
redraw only their own candidates.

A farm area is registered with `new_calibration_quadrat.py --farm`, which puts
`_farm_calib_` in its name. `roofclf` skips those areas: a ground array would mark the
farmhouse beside it as carrying PV, the problem that keeps Kalat Rural out of Pakistan's
refits. Overlap checks and `calib-publish` still see them. Mappers should map all solar in a
farm area, ground and rooftop, and trace the panels rather than the fence.

## Running it

```bash
pixi run earthpv roofclf-ground --aoi yemen \
    --clean-region data/labels/agripv_testground.geojson \
    --weak-region data/labels/Yemen-mixed-labels.geojson
pixi run earthpv roofclf-ground-score-national --aoi yemen      # about 10 s per cell, resumable
pixi run earthpv roofclf-ground-capacity --aoi yemen --osm-solar <national OSM solar pull>
```

Registered farm areas are found automatically. Region labels are pulled from Overpass once
and cached under `data/roofclf_ground/<aoi>/areas/`, and paved roads per whole degree under
`data/roads/<aoi>/`; a chunk Overpass cannot deliver leaves its blobs marked
`road_checked=False`, counted in the summary. Outputs land in `data/roofclf_ground/<aoi>/`:
the model and its evaluation tables, one blob file per cell, and in `capacity/` the per-cell
figures, the incremental blobs and `ground_leads.geojson`, ranked for review in JOSM.

## Yemen: the first run

| | Result |
| --- | --- |
| 'Amran, held-out pixel AUC | 0.983 |
| 'Amran, objects at the threshold | precision 0.63 at 62% of arrays found; 0.48 at 71% one step lower |
| 'Amran, trained on Tihama only | pixel AUC 0.937, precision 0.40, 55% of arrays found |
| Tihama, held-out bag AUC | 0.934 (0.812 trained on 'Amran only) |
| Mapped sub-400 m<sup>2</sup> area per detected m<sup>2</sup> | 0.23, and 0.19 to 0.30 across 'Amran's four strips |

Precision in 'Amran is a floor. Reviewing the leads turned up arrays that were not yet
mapped, and a Sentinel-2 time series of the leads (two clear dates a month, 2023 to 2026)
dated eight unmapped ones to July to November 2025: they darkened after the June 2025 Esri
capture, so the reviewer's imagery could not show them. Random control spots showed no such
step (0 of 150).

The leads work as a mapping tool. In Tihama the reviewer confirmed and traced 88 of the 150
strongest leads more than 50 m from any mapped feature (59%), adding 104 arrays. Among the
leads were two utility-scale plants that are not in OpenStreetMap at all.

## Limits

- **One clean area.** Every capacity figure rests on 'Amran alone, which is why nothing is
  published and the domain is 12 cells. The eight farm candidates exist to fix that.
- **Transfer is the open question.** Highland 'Amran and lowland Tihama behave differently,
  and the Tihama-only model found 'Amran's arrays at lower precision than plain SPPI. A new
  country should be read through its own leave-one-area-out figures, not Yemen's.
- **Rule 1 is relative to the imagery's date** here as everywhere (see
  [roofclf](roofclf.md)): arrays built after the mapping imagery are present in the
  composite and absent from the labels, so precision is a lower bound.
- **Not yet part of the atlas.** The component is incremental by construction (deduplicated
  against OpenStreetMap and segmentation), but its uncertainty has not been added to the
  atlas's interval composition.
