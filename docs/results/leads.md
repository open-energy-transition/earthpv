# Mapping leads

The leads product is the half of earthpv that has a human in the loop. It is a ranked
queue of places where the model thinks there is solar and OpenStreetMap does not yet say
so, exported in the formats mappers already use.

## Pakistan, country-wide

The country-wide run applied the production checkpoint at threshold 0.3, first over 122
densely built cells and then over the full build of roughly 4,470 cells, once cell
selection moved from the Overture set of buildings above 500 m<sup>2</sup> to VIDA Open
Buildings.

| Product | Count | File |
| --- | ---: | --- |
| All candidates | 6,566 | `pakistan_pv_candidates.geoparquet` |
| Rooftop placement | 1,312 | same, `placement == "rooftop"` |
| Ground-adjacent | 448 | same |
| No building within range | 4,806 | same |
| New leads, excluding mapped | 4,602 | `pakistan_pv_new_leads.geojson` |
| New leads after the epoch veto | 4,589 | `pakistan_pv_new_leads_epochclean.geojson` |
| MapRoulette challenge | ranked | `pakistan_pv_maproulette.geojson` |

Thirty percent of the raw candidates fall on solar already mapped in OpenStreetMap, which
is the pipeline's cheapest sanity check. The rest are the queue.

## How the queue is ordered

`rank_score` starts at the model's confidence and is multiplied by a building prior, so a
detection sitting squarely on a roof outranks an equally confident detection in open
country. Two further signals adjust it:

* **[Glint corroboration](../methods/glint.md)** multiplies upward, capped at four times,
  as the count of mutually consistent spike dates saturates. It never demotes.
* **The pre-boom epoch check** demotes. Pakistan's rooftop stock is overwhelmingly
  post-2022, so a candidate that already looked like PV in the 2021 dry-season composite
  is more likely a bright roof, concrete apron or rock outcrop than a new array.

Nothing in the default export is dropped. A high-confidence detection with no building
anywhere near it may be an unmapped roof or a ground-mounted farm, and it still surfaces.

## The one file that does drop things

`--exclude-mapped --epoch-clean --veg-max-ndvi 0.35` writes
`<aoi>_pv_new_leads_clean.geojson`, the single export artifact that removes candidates.
Two vetoes apply, and both require positive evidence: a lead that no instrument could
check is always kept.

**Distance to already-mapped solar.** `--min-distance-m 100` removes candidates within
100 m of an existing OpenStreetMap solar feature, which is not the same as intersecting
one; the intersects-only version missed adjacent-but-offset duplicates.

**Vegetation.** Manual review of countryside leads found a lot of green fields. Measuring
NDVI on the composite the model actually read does not catch them, because those fields
were dark fallow or flooded paddy soil when the dry-season median was built. What does
catch them is the annual cycle: every crop field greens up at some point in the year and a
panel never does. A 0.35 threshold on maximum composite NDVI vetoed 596 of 5,132 leads,
and the split confirms the veto is specific rather than blunt: 20.2 percent of
`no_building` leads, 10.5 percent of `ground_adjacent`, and only 0.3 percent of rooftop.

Vegetation-vetoed leads are written to `hard_negatives_veg.parquet` and fed back as
training negatives. Unlike epoch persistence, which real old PV also shows, an observed
crop cycle is near-conclusive non-PV evidence, and dark fallow soil is a confusion class
that German training data never contained.

## Getting the leads into OpenStreetMap

```bash
pixi run earthpv export --aoi pakistan --exclude-mapped --min-distance-m 100 \
    --epoch-clean --veg-max-ndvi 0.35
```

That writes GeoParquet, GeoJSON and a MapRoulette challenge sorted by `rank_score`. Load
the challenge in MapRoulette, or open the GeoJSON directly in JOSM or QGIS alongside the
Esri and Bing layers.

When mapping a lead, tag it the way the rest of OpenStreetMap does
(`generator:source=solar` on a rooftop generator, `power=plant` with
`plant:source=solar` for a plant) so the next `overpass-labels` run picks it up as
training data. Mapped installations returning through that path are what closes the
[flywheel](../how-it-works.md#workflow).

## Other regions

`results/gujarat_pv_candidates.geojson` and `results/gujarat_pv_new_leads.geojson` hold a
first pass over Gujarat, India, produced with no locally cached data at all. Gujarat is
the worked template for [running on a new region](../reproduce.md#running-on-a-new-region);
see the [Gujarat capacity map](gujarat.md) for its first full capacity estimate
(2026-08-07, segmentation-only -- no calibration quadrats exist there yet).
