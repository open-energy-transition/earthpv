# Farm ground PV (groundclf)

!!! note "SHIPPED (2026-10-24): in Yemen's Best estimate, inside its calibration domain"

    Built and measured 2026-10-23, and since 2026-10-24 a standard field on every evidence
    atlas: **farm ground PV below 400 m<sup>2</sup>**, beside rooftop PV below 400
    m<sup>2</sup>. Every other atlas shows the field as "not measured" until the detector is
    run there. **Recalibrated the same day on seven farm areas** ('Amran and six cut from a
    Tihama region): Yemen's atlas now carries 169.1 MWp of it (90% 77 to 327), in 34 cells,
    with each landscape priced by its own areas (see
    [a calibration domain per region](#a-calibration-domain-per-region)).

Small solar arrays beside fields, most of them powering irrigation pumps, are a large and
fast-growing class in arid countries, and neither of the project's two instruments sees
them. `roofclf` asks whether a roof carries PV, and these arrays have no roof. The
segmentation model ignores everything below 400 m<sup>2</sup> and, in the area measured
here, found almost none of them above it either. `groundclf` is the third
instrument: it reads pixels rather than buildings, and is trained on farm areas rather than
on rooftop quadrats. Its population is small farm arrays, not ground-mount PV at every size,
which segmentation covers. (It was called `roofclf_ground` until 2026-10-25.)

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
  which every visible installation is mapped. Pixels at least half covered by a traced
  array are positives, pixels more than 20 m from any PV are negatives. Only clean areas
  give precision, the detection threshold and the capacity calibration. A complete area may
  still hold coarse shapes: a `power=plant` outline drawn around a site, or a node, trains
  as a bag (below) and is priced as described under
  [what a mapped polygon is worth](#what-a-mapped-polygon-is-worth).
- **Weak areas** (`--weak-region`): ordinary OpenStreetMap, oversized polygons and nodes
  included. Each label is a bag whose two most PV-like pixels become positives, re-chosen
  over three refits that start from SPPI (multiple-instance learning). Negatives keep
  100 m from any label. Weak areas only ever train.

The model is a balanced logistic regression, the same fitting code as `roofclf`. Skill is
reported leave-one-strip-out (each area cut into four strips, every fold holding one strip
out of every area) and, when there is more than one region, leave-one-region-out, which is
the figure that says what a new country should expect. Areas cut from one mapped region
carry the same `region` property on their boundary and are left out together: a
neighbouring piece of the same farmland is no test of transfer.

**Blobs and the threshold.** Pixels above the threshold join into 8-connected blobs. The
threshold is a logit, chosen as the lowest one at which the clean areas' held-out blobs
reach a precision of 0.5. Logits rather than probabilities, because a balanced fit puts
every strong detection at a probability that rounds to 1.0 and ties the leads a reviewer
should see first.

**Five vetoes**, three measured against reviewed leads in 'Amran and two on Yemen's national
runs:

| Veto | Rule | Measured |
| --- | --- | --- |
| Paved road | 30% or more of a blob within 8 m of an OSM motorway, trunk, primary, secondary or tertiary centreline, or an asphalt way | Removed the 9 leads on 'Amran's trunk road and none of the 11 leads the reviewer confirmed. A plain road buffer would have removed real arrays 0 to 5 m from roads. |
| Water | The blob's B11 more than 20% darker than its ring | Water-harvesting ponds are dark in the visible like panels, but also in the shortwave infrared. Removed 11 leads, including all six read as ponds on imagery, and 0 of 301 mapped arrays. A water index does not work: in a dry-season median the ponds read dry. |
| Outside the region of interest | No pixel within 50 m of a VIDA building, a WorldCover cropland pixel or a green pixel (NDVI 0.25 or more) | 96% of 'Amran's arrays lie inside it, in 28% of the land. It bought only 3 to 6 points of precision there; its purpose is dark rock and shadowed slopes far from any field. |
| Size | A blob over 25,000 m<sup>2</sup> | 87% of Yemen's detected area was in blobs of 5,000 m<sup>2</sup> and more, most of it in desert cells under 1% cropland (lava fields and dark rock), the largest 61 km<sup>2</sup>. The largest installation mapped in the seven farm areas is 22,231 m<sup>2</sup> and the largest detection in them 16,000 m<sup>2</sup>, so the cap touches no calibration blob. |
| Slope | Copernicus DEM (90 m) slope over 12&deg; at the blob | Highland cliff shadows and dark rock read like panels. Before this veto the two highland cells the farm figure leaned on most (Ad Dali' and Ta'izz) held 2.2 km<sup>2</sup> of detections, and 0 of 18 sampled blobs there were panels on Esri imagery. Steeper than 12&deg; lie 0.2% of the mapped highland array area (352 arrays), none of Tihama's, 4.6% of the detected area inside the highland farm areas and 51% of it in the highland cells the figure prices. A rugged farm area does not protect against it: As Sawd's median slope is 25&deg;, its arrays sit on terraces at 2.6&deg;, and its detections at 31&deg;. |

The road veto is applied in the capacity step, as a vector overlap on the blobs, so the
national scoring pass never waits on Overpass.

## From blobs to capacity

`groundclf-capacity` prices only what the atlas does not already count, the same rule
every component follows:

1. Kept blobs (vetoes, region of interest) more than 20 m from any OpenStreetMap solar
   feature, which is counted from the map, and from any segmentation candidate whose
   figure the atlas uses.
2. Times a ratio measured on the clean areas: true mapped PV area divided by detected blob
   area, the same idea as `roofclf`'s coverage ratio, taken from the calibration region the
   cell resembles (below). Its uncertainty is a bootstrap over that region's areas, never
   over pixels or blobs; a region with fewer than three areas carries a stated factor of two
   either way instead.
3. Times 0.18 kWp/m<sup>2</sup>, the module constant, because farm arrays are traced around
   their panels.

Detections inside a registered farm area count nothing: the area is completely mapped, so its
PV is counted from the map, and a detection no mapped feature explains is a false positive or
postdates the imagery (387 blobs in Yemen).

**Below 400 m<sup>2</sup> by default.** The ratio's numerator counts only arrays smaller
than `--max-array-m2` (400 m<sup>2</sup>, the project's segmentation floor), so the estimand
matches `roofclf`'s. In 'Amran that is 12% of the mapped array area: the other 88% is in
larger arrays, which segmentation misses there too. `--max-array-m2 0` prices farm arrays of
every size.

### A calibration domain per region

The headline counts only cells that resemble a calibration region, and each such cell is
priced with that region's ratio only. A cell resembles a region when its cropland share, its
building density **and** its median elevation (Copernicus DEM) each lie within 25% of the
range that region's areas span, the rule `roofclf` applies with its building-density band.
A region is a landscape: areas share one when their boundaries carry the same `region`
property, and an area without one stands alone. A region whose areas hold no detection at
all has no ratio and prices no cell. Everything else is reported separately, as an
extrapolation.

Both rules before this one failed on Yemen, and each failure is the reason for a part of it:

- **No domain at all.** On the first 60 cells of western Yemen the detector priced 46.5 MWp,
  most of it in Al Hudaydah city and its shore at 0 to 4% cropland, with a ratio measured on
  highland farms.
- **One box around every area.** With 'Amran alone (6.6% cropland, 46 buildings per
  km<sup>2</sup>) the box held 12 cells. With the six Tihama areas added it spanned 5 to 85%
  cropland and held 289 cells, mostly highland terraces in Ibb, Sana'a and Ta'izz that
  resemble Tihama in cropland and buildings only. They received Tihama's ratio, 1.19 mapped
  m<sup>2</sup> per detected m<sup>2</sup> against 'Amran's 0.17, and the total came to
  3,532 MWp, more than the 2,848 MWp of panels Yemen imported from China in total since
  2017. A box per region without elevation still gave 2,366 MWp. Those cells hold 1.8 times
  the detected area per km<sup>2</sup> of the Tihama areas, which is terraces, trees and
  dark soil, not pumps.

Elevation is what separates the landscapes: Tihama's areas lie at 68 to 236 m, 'Amran's at
1,895 m. With it, Tihama's ratio reaches 32 lowland cells (Al Hudaydah, the Tihama plain of
Hajjah, one in Al Mahwit and one on the Abyan coast) and 'Amran's two highland cells.

The third failure came with the seven sampled farm boxes (2026-10-25). Grouped by landscape,
three joined Tihama and three joined 'Amran as a highland region. Its four areas span 1,574
to 2,296 m, 7 to 27% cropland and 31 to 120 buildings per km<sup>2</sup>, and its domain
(25% wider each way) reaches most of the populated highlands: 163 cells and 574 MWp, of 891 MWp in all. On Esri imagery the two
highland cells it leaned on most held cliff shadows and dark rock, 0 of 18 sampled blobs
panels, and a random blob from each of nine other highland cells was a panel at most once.
No cell-level variable separates them, because a mapped highland farm area can itself be
rugged (As Sawd, median slope 25&deg;). Its arrays are not: they sit on terraces at a median
2.6&deg;, its detections at 31&deg;. Hence the slope veto above, which is per blob.

## In the atlas

`earthpv atlas --ground-cells data/groundclf/<aoi>/capacity/ground_cells.parquet`
adds the component; the `summary.json` beside it supplies the calibration. It is shown the
same way on every country's page, so a reader can always find it:

- **Its own line.** A fourth headline tile, "satellite farm ground &lt;400 m&sup2;", beside
  the rooftop one, so the four tiles still sum to Best; a map quantity; a row in each map
  cell's hover; a province column; a composition row and an uncertainty row. Its colour is
  green, the one hue left that stays distinct from the other four methods in both themes
  (OKLab distance 19.7 and 22.0 from the nearest, 13 under deuteranopia), and it is always
  hatched, since it is always ground-mount.
- **"Not measured", never zero.** A page built without it states that the detector has not
  been run for the country (`totals.small_ground_status.measured: false`). Pages published
  before the field existed were moved onto the new template by
  `scripts/retemplate_atlas.py`, with their figures byte for byte unchanged.
- **In Best, inside the domain only.** Only cells inside the detector's own calibration
  domain count, the rule `roofclf`'s other components follow.
- **Its interval.** The module-constant draw shared with every module-area component, times
  the replicates `groundclf-capacity` writes: per calibration region, a bootstrap over
  that region's farm areas once it has three or more (`groundclf.BOOT_MIN_AREAS`), and
  below that a stated judgement, a lognormal factor of two either way at 90%
  (`groundclf.JUDGEMENT_CI90`). The page says which applies to which region: leaving
  the term out would make the interval narrowest where the calibration is thinnest.
- **Incremental, against what the page counts.** Run `groundclf-capacity` with the
  same `--osm-solar` file the atlas uses, and with `--roofclf-buildings` where the country
  has a `roofclf` half: a detection within 20 m of a building roofclf priced is that
  building's yard array, which roofclf already counts.
- **The size chart** (countries with `roofclf`'s &ge; 400 m<sup>2</sup> half) adds it to the
  ground-mount total unbinned: a ratio estimate has an area but no per-array size.

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
Esri imagery check applies. Eight boxes each were drawn on 2026-10-23 for Yemen, Egypt,
Morocco, India, Pakistan and South Africa, the countries where solar irrigation is common,
and published to their atlases, where they rank after the building boxes. Pakistan's
configuration records no composite window, so its draw took `--window-start 2025-11-01`, the
compose default when its composites were built. The three samplers (building strata, start-here boxes, farm boxes) each
redraw only their own candidates.

### What a mapped polygon is worth

The capacity calibration needs each mapped installation's panel area, and OpenStreetMap
polygons are not all panels. `groundclf.panel_area_factor` reads it from the tag:

- **`power=generator`**: the array itself, counted at its area.
- **`power=plant`**: the site around it, counted at the land constant's share of its area
  (0.05 / 0.18, about 28%), the rule the atlas's Verified tier applies to every mapped
  ground outline (owner decision, 2026-10-24). A plant outline that contains a generator
  counts nothing: its generators carry its panels.
- **Nodes** have no area and count nothing, so a node-heavy area understates its PV.
- **A named mapper's polygons are arrays whatever their tag.** A country lists, in
  `configs/aoi.yaml`, the OpenStreetMap accounts whose solar polygons are traced around the
  panels (`osm_panel_tracers`; Yemen names its owner-mapper). The same list makes the atlas
  price those polygons at the module constant in Verified (`labels.panel_traced`, written as
  `panel_traced` by `prepare_national_osm_solar.py`). It is matched on the last editor: 868
  of that account's 869 Yemeni polygons are their first version, so the edit history and
  the authorship agree.

Tihama's 2023 rectangles show why the outline rule is needed. On Esri imagery from April
2025, a random sample of 12 (nine the detector missed, three it found) all hold panels: two to
four small groups of perhaps 30 to 60 m<sup>2</sup> each inside a rectangle of 600 to
1,000 m<sup>2</sup>, so panels cover roughly 10 to 25% of it, a little under the land
constant's share. Taken as panel outlines the rectangles would overstate Tihama's panel area
about fourfold.

### Yemen's fourteen farm areas

Seven registered 2026-10-24 from the owner's two boundaries:

- **'Amran** (`amran_huth_farm_calib_129p53km2`): the whole test ground, 306 arrays, every
  one traced around its panels, on Esri imagery from June to October 2025.
- **Tihama**, six areas, 331.6 km<sup>2</sup>, 1,100 installations: the owner's region near
  Zabid, where every installation was checked by hand. Esri's imagery there is a patchwork
  from August 2021 to April 2025, and Rule 1 is only as good as the imagery's date, so the
  region was cut to where Esri shows a capture from 1 October 2024 on (12 months before the
  composite window, the candidate gate; Esri shows the newest capture at any spot, checked on
  552 points), then cut along the 0.1&deg; grid, with pieces under 15 km<sup>2</sup> merged
  into a neighbour. The remaining 199 km<sup>2</sup>, on 2021 to mid-2024 imagery, trains as
  a weak region (`data/labels/yemen/tihama_stale_imagery_region.geojson`) and never
  calibrates. 238 of the 1,100 installations are the owner's panel traces; most of the rest
  are the 2023 rectangles.

And seven of Yemen's eight sampled farm candidates (`calib-candidates --farmland`: 3 km
boxes, one per cropland stratum, drawn at random), mapped by the owner on 2026-10-24 and 25.
Each boundary names its landscape:

| Area | Governorate | Region | Mapped arrays | Elevation |
| --- | --- | --- | --- | --- |
| Abs north (`abs_f7`) | Hajjah | Tihama | 3 | 107 m |
| Abs (`abs_f8`) | Hajjah | Tihama | none | 132 m |
| Az Zaydiah (`az_zaydiah_f6`) | Al Hudaydah | Tihama | 48 | 56 m |
| As Sawd (`as_sawd_f1`) | 'Amran | Highlands | 6 | 1,736 m |
| Jihanah (`jihanah_f2`) | Sana'a | Highlands | 40 | 2,296 m |
| As Saiyani (`as_saiyani_f4`) | Ibb | Highlands | none | 1,574 m |
| Lawdar (`lawdar_f3`) | Abyan | alone; prices nothing | 1 | 857 m |

A box with no PV calibrates as much as one with PV: As Saiyani's detections (2,600
m<sup>2</sup>, none on a panel) pull the highland ratio down where the detector fires on
nothing.

A farm area is registered with `new_calibration_quadrat.py --farm`, which puts
`_farm_calib_` in its name. Mappers map every installation in it, ground and rooftop, and
trace the panels rather than the fence, as in a building area.

**Every area feeds both detectors (owner, 2026-10-25).** A farm area also calibrates the
rooftop classifier. It was kept out before because a ground array would mark the farmhouse
beside it as carrying PV, the problem that keeps Kalat Rural out of Pakistan's refits;
`roofclf` now ignores ground-placed installations of 400 m<sup>2</sup> or more on a roof, and
its yard term already stopped at that size. A building area trains this detector, as kind
`train`: its pixels enter the fit, above all as examples of towns without PV, but it sets
neither the threshold nor a ratio nor a domain, so the figure stays one for land that
resembles the farm areas (the owner's choice). Detections inside any registered area, of
either kind, count nothing.

## Running it

```bash
pixi run earthpv groundclf --aoi yemen \
    --weak-region data/labels/yemen/tihama_stale_imagery_region.geojson \
    --osm data/labels/yemen_overpass_solar.parquet      # region labels from the national pull
pixi run earthpv groundclf-score-national --aoi yemen      # about 10 s per cell, resumable
pixi run earthpv groundclf-capacity --aoi yemen --osm-solar <national OSM solar pull>
pixi run earthpv atlas --aoi yemen --osm-solar <the same pull> \
    --ground-cells data/groundclf/yemen/capacity/ground_cells.parquet
```

Registered farm areas are found automatically. Region labels are pulled from Overpass once
and cached under `data/groundclf/<aoi>/areas/`, and paved roads per whole degree under
`data/roads/<aoi>/`; a chunk Overpass cannot deliver leaves its blobs marked
`road_checked=False`, counted in the summary. Outputs land in `data/groundclf/<aoi>/`:
the model and its evaluation tables, one blob file per cell, and in `capacity/` the per-cell
figures, the incremental blobs and `ground_leads.geojson`, ranked for review in JOSM.

## Yemen

| | 'Amran only (2026-10-23) | Seven farm areas (2026-10-24) |
| --- | --- | --- |
| Areas | 1, 306 traced arrays | 7: 'Amran and six Tihama areas, 1,406 installations |
| Held-out pixel AUC, 'Amran | 0.983 | 0.978 |
| Trained without 'Amran, on 'Amran | pixel AUC 0.937 | pixel AUC 0.939, precision 0.43, 58% of arrays found |
| Trained without Tihama, on Tihama | bag AUC 0.812 | pixel AUC 0.96 to 1.00, but 2 to 33% of arrays found |
| Threshold (logit) | 9.57 | 9.17: precision 0.55 at 39% of arrays, pooled |
| Mapped sub-400 m<sup>2</sup> area per detected m<sup>2</sup> | 0.23 | 'Amran 0.17; Tihama 1.19 (0.14 to 8.4 by area, 90% bootstrap 0.56 to 2.15) |
| Domain | 12 cells | 34 cells: 32 Tihama-like, 2 'Amran-like |
| In Best | 32.7 MWp (x/÷2 judgement) | **169.1 MWp** (90% 77 to 327) |

**Tihama's arrays are mostly too small to see.** The detector finds 60% of 'Amran's arrays
but 6 to 50% of each Tihama area's. A sample of 12 of Tihama's 2023 rectangles on Esri's
April 2025 imagery shows why: each holds two to four small panel groups of perhaps 30 to
60 m<sup>2</sup>, often among orchard trees, below one Sentinel-2 pixel each. The ratio
therefore scales up in Tihama, each detected m<sup>2</sup> standing for 1.19 m<sup>2</sup>
of panels, where in 'Amran it scales down to 0.17 because most of 'Amran's PV is in arrays
above the 400 m<sup>2</sup> estimand. A ratio that scales up amplifies false detections
too, which is why the domain matters so much here.

**The Tihama areas were drawn around a solar-irrigation hotspot.** The national cells
priced with their ratio hold 205 m<sup>2</sup> of incremental detections per km<sup>2</sup>
against the areas' 452, consistent with fewer pumps away from it, but the ratio itself is
still the hotspot's. Read the figure as Tihama's lowland calibration applied to the lowland,
not as a measured national total.

Precision in a clean area is a floor. Reviewing 'Amran's leads turned up arrays that were
not yet mapped, and a Sentinel-2 time series of the leads (two clear dates a month, 2023 to
2026) dated eight unmapped ones to July to November 2025: they darkened after the June 2025
Esri capture, so the reviewer's imagery could not show them. Random control spots showed no
such step (0 of 150).

The leads work as a mapping tool. In Tihama the reviewer confirmed and traced 88 of the 150
strongest leads more than 50 m from any mapped feature (59%), adding 104 arrays. Among the
leads were two utility-scale plants that are not in OpenStreetMap at all.

## Limits

- **Two regions.** Every capacity figure rests on 'Amran and one Tihama region. The bootstrap
  over Tihama's six areas says how much the ratio moves between farms of that plain, not
  across a country, and 'Amran's part is still a stated judgement. The farm candidates in
  other strata are what widen it.
- **A ratio that scales up is fragile.** Where the detector finds a quarter of the arrays,
  each detection stands for four times its own panels, and a false detection is multiplied
  the same way. The domain contains it; a random-cell review of detections in the domain
  would measure it.
- **Transfer is the open question.** Highland 'Amran and lowland Tihama behave differently in
  every respect measured here. A new country should be read through its own
  leave-one-region-out figures, not Yemen's.
- **Rule 1 is relative to the imagery's date** here as everywhere (see
  [roofclf](roofclf.md)): arrays built after the mapping imagery are present in the
  composite and absent from the labels, so precision is a lower bound. Tihama's areas are
  cut to imagery from 1 October 2024 on for that reason.
- **Panel area is estimated where the map has outlines.** A rectangle counts at the land
  constant's 28% of its area; the April 2025 sample puts its panels nearer 10 to 25%.
