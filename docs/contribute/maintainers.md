# Register an area (maintainers)

Mappers need nothing from this page: the [iD](id.md) and [JOSM](josm.md) guides and a
[report](report.md) are their whole workflow. This is the other half, which needs a clone
of the repository and its `data/` tree: drawing candidates, registering a mapped area,
declaring it complete, and publishing the boundaries the atlas loads.

## Draw candidates

```bash
pixi run calib-candidates -- --aoi zambia --dry-run   # report the draw, write nothing
pixi run calib-candidates -- --bronze                 # every Bronze atlas
pixi run calib-candidates -- --bronze --priority      # + two start-here boxes each
pixi run calib-candidates -- --aoi yemen --farmland   # farm boxes, stratified by cropland
pixi run calib-publish                                # put them on the atlases
```

`--farmland` draws 3 km farm areas for the
[farm ground-PV detector](../methods/groundclf.md), stratified by cropland rather than
buildings. Register a mapped one with `--farm` added to the command below: its name then
carries `_farm_calib_`. Both kinds of area feed both detectors (since 2026-10-25): a farm
area calibrates the farm detector and the rooftop classifier, a building area calibrates the
rooftop classifier and trains the farm detector. An area whose imagery is too poor to
certify completeness is listed `corroborated`, not `rule1`, and is left out of
calibration with explicit `--quadrat` flags.

`scripts/propose_calibration_candidates.py` cuts a country's density grid into eight bands
of equal building share, draws one cell per band at random, places a box on the buildings
so its own density matches its band, and drops any box whose Esri imagery is too old for
the country's composite. With `--priority` it instead places two 1 km **start-here** boxes
in the densest quarter of the country's buildings, where the roof area in buildings of
1,000 m<sup>2</sup> or more is largest, through the same imagery gate. The details, and what
it does not do, are in
[Automated quadrat selection](../calibration-mapping-protocol.md#automated-quadrat-selection).
On an uncalibrated (Bronze) atlas `calib-publish` also ranks the candidates, start-here
boxes first and then the rest from the densest down, and the first is drawn as a star. The
star moves to the next one by itself once that area is registered.
`calib-publish` writes the public per-area GeoJSON under
`docs/assets/labels/calibration_areas/` that the atlas fetches at run time, so new
candidates need no atlas rebuild. Re-run it after anything below changes an area.

## Register a mapped area

A mapper's report names the area. Run the command from its atlas popup (**Register it**),
which carries the right `--aoi`, the box and the candidate's imagery date. Check the dry run
first:

```bash
python scripts/new_calibration_quadrat.py --aoi zambia --dry-run \
    --name chama_s1 --lat -11.539319 --lon 33.208160 --side-m 2000 \
    --imagery-layer "Esri World Imagery (Vivid)" --imagery-date 2024-09-13
```

or, for a boundary a mapper drew in JOSM (**File -> Save As -> GeoJSON** of a layer holding
only the boundary; see [Draw your own area](draw-area.md)). It arrives pasted into the
report's **Boundary GeoJSON** field: save that block to a file, check the dry run, and reply
on the report before the mapper starts, so a rejected outline costs no mapping:

```bash
python scripts/new_calibration_quadrat.py --aoi zambia --dry-run \
    --name chama_north --geojson ~/drawn/chama_north.geojson \
    --imagery-layer "Esri World Imagery" --imagery-date 2025-03
```

`--dry-run` prints the geometry (area, bounding box, whether it fits one 2.24 km training
chip) and the overlap check against every registered area of that country, and writes
nothing. It refuses an overlap unless `--allow-overlap` is passed, and refuses a box with no
imagery date unless `--imagery-unchecked` is. Pakistan's areas live flat in `data/labels/`;
every other country's in `data/labels/<aoi>/`, so they never join a Pakistani refit.

Drop `--dry-run` to write the boundary and pull the OpenStreetMap solar inside it. This
writes `<stem>_boundary.geojson` (+ `.parquet`) and `<stem>_overpass_solar.parquet`, and
prints a ground-truth profile: size distribution against the 400 m<sup>2</sup> floor,
rooftop/ground split and `roofclf.packing_density`. **A registered box is not complete
because this ran:** it holds whatever OpenStreetMap had at that moment.

A box reported **not mappable** is recorded instead, so nobody re-draws it:

```bash
python scripts/new_calibration_quadrat.py --aoi zambia --name chama_s1 \
    --lat -11.539319 --lon 33.208160 --side-m 2000 \
    --imagery-layer "Esri World Imagery" --imagery-date 2019-11 \
    --reject "imagery predates the composite by six years"
```

## Declare it complete

After the second pass, record next to the boundary: mapper names, completion date, the
imagery layer and its capture date, installation count, and how many the second pass added.
That is what turns a registered box into a **Rule-1 area** ready for the next `roofclf`
refit. `roofclf.discover_quadrats` picks up any boundary + mapped-solar pair automatically,
but nothing folds an area into a fit without a human completeness declaration first (see the
[random-cell validation note](../methods/roofclf-national-validation.md) for why this
matters as much on the deployment side). Then list it in `configs/atlas/<aoi>.yaml`
(`calibration_boxes`, with its status) and re-run `calib-publish`; the next atlas rebuild
draws it as a filled diamond.

## Pakistan: the density gap

A quadrat's *own* building density decides which national cells it can calibrate. As of
2026-08-20, the sparsest quadrat actually feeding `roofclf`'s coverage-ratio/area-recall
correction sits at 124 buildings/km<sup>2</sup>, but 13.5% of the buildings that correction
is applied to nationally sit *sparser* than that (median around 89 buildings/km<sup>2</sup>).
That gap used to be far worse: as measured 2026-08-16, the sparsest supporting quadrat was
872 buildings/km<sup>2</sup> and 84% of buildings sat below it, pricing 54% of the whole
published Best estimate with a correction fit on much denser ground than it was applied to.
See [Calibration density mismatch](../issues/roofclf-calibration-density-mismatch.md).

Pakistan's eight open candidates target exactly that gap. They were picked by hand before
the sampler existed (Box 19 in the
[calibration boxes log](../issues/pakistan-calibration-boxes.md)): each is the centroid of a
~100 km<sup>2</sup> grid cell whose *average* density falls in the gap, a coarse regional
screen rather than a verified settlement. Box 18's quadrats moved from source-grid densities
of 549/250/150 buildings/km<sup>2</sup> to own-measured densities of 895/237/146 once mapped;
expect something similar.

| candidate (boundary) | province | district | source-grid density (bldg/km<sup>2</sup>) |
|---|---|---|---:|
| [`rajanpur_gap_calib_2km`](../assets/labels/calibration_areas/pakistan/rajanpur_gap_calib_2km.geojson) | Punjab | Rajanpur | 54.4 |
| [`kasur_gap_calib_2km`](../assets/labels/calibration_areas/pakistan/kasur_gap_calib_2km.geojson) | Punjab | Kasur | 124.4 |
| [`khairpur_gap_calib_2km`](../assets/labels/calibration_areas/pakistan/khairpur_gap_calib_2km.geojson) | Sindh | Khairpur | 55.3 |
| [`jacobabad_gap_calib_2km`](../assets/labels/calibration_areas/pakistan/jacobabad_gap_calib_2km.geojson) | Sindh | Jacobabad | 107.9 |
| [`deraismailkhan_gap_calib_2km`](../assets/labels/calibration_areas/pakistan/deraismailkhan_gap_calib_2km.geojson) | Khyber Pakhtunkhwa | Dera Ismail Khan | 63.2 |
| [`haripur_gap_calib_2km`](../assets/labels/calibration_areas/pakistan/haripur_gap_calib_2km.geojson) | Khyber Pakhtunkhwa | Haripur | 102.1 |
| [`pishin_gap_calib_2km`](../assets/labels/calibration_areas/pakistan/pishin_gap_calib_2km.geojson) | Balochistan | Pishin | 53.8 |
| [`mastung_gap_calib_2km`](../assets/labels/calibration_areas/pakistan/mastung_gap_calib_2km.geojson) | Balochistan | Mastung | 118.8 |

Once a quadrat is Rule-1 and its density sits inside the gap (or genuinely below the
current calibrated domain floor, 48.5 buildings/km<sup>2</sup>: a different, harder thing to
move safely, because a quadrat only lowers that floor if its *own* measured density is below
it; see [Calibration quadrats](../methods/calibration-quadrats.md#current-quadrats) before
attempting it), it enters the next `earthpv roof-classifier` refit, is rescored nationally,
and is folded into the next evidence-atlas rebuild. The most recent example of that cycle,
three quadrats declared Rule-1 and moving the published headline number the same day, is
[Box 18](../issues/pakistan-calibration-boxes.md#box-18-three-peri-urban-screens-attock-layyah-lodhran-geodesic-squares-400-km2-each-2026-08-19).
