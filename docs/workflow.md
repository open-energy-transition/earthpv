# The mapping workflow

The technical novelty in earthpv is not one model. It is a loop that combines free
low-resolution imagery, an open foundation model, and human mappers working inside
OpenStreetMap with the high-resolution imagery they are already licensed to look at.

![The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.](assets/figures/osm_ai_flywheel.svg#only-light)
![The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.](assets/figures/osm_ai_flywheel.dark.svg#only-dark)

## Why the loop exists

Two licences pull in opposite directions, and the loop is what resolves them.

Sentinel-2 is free, global, and reprocessed every five days, but at 10 m per pixel a
typical rooftop array is four to twenty pixels. Esri, Bing and Mapbox imagery resolves
individual panels, but their terms allow a person to trace from them inside the
OpenStreetMap editor and do not allow a machine to be trained on them.

So the machine only ever reads Sentinel-2, and people only ever read the high-resolution
layers. The model proposes; a mapper disposes; the disposal is recorded in OpenStreetMap
as an ordinary, openly licensed feature; and that feature is legitimate training data for
the next model. Nothing proprietary crosses into the model, and nothing the model produces
is trusted until a person has looked at it.

## The four steps

### 1. Labels from OpenStreetMap

`earthpv labels` reads solar polygons for an area either from Overture Maps (a periodic
OpenStreetMap snapshot, convenient but lagging) or, for a freshly mapped region,
`earthpv overpass-labels` queries the live Overpass API. Building footprints come from
Overture and from VIDA Open Buildings, which is imagery-derived and therefore includes the
small, unmapped structures that OpenStreetMap in Pakistan does not yet have.

### 2. Train on Sentinel-2

`earthpv chips` cuts training windows out of dry-season Sentinel-2 composites and burns
the label polygons into per-pixel masks. `earthpv train` fine-tunes TerraMind-tiny through
TerraTorch. Training started on Germany, where OpenStreetMap solar mapping is dense and
close to complete, and then added Pakistani chips as the loop produced them. See
[Detection model](methods/detection.md) for what that buys.

### 3. Rank candidates and publish leads

`earthpv infer` writes a probability raster per grid cell; `earthpv postprocess`
polygonizes it, attaches each candidate to a building footprint, and scores it.
The pipeline is deliberately **recall-first**: false positives cost a mapper a few
seconds, whereas a missed installation is invisible forever. Nothing is dropped by the
default export. What the priors do is reorder the queue so mappers hit real installations
first:

| Signal | What it does | Direction |
| --- | --- | --- |
| Building prior | overlap with, or distance to, a VIDA footprint | reorders |
| [Glint corroboration](methods/glint.md) | specular flashes consistent with one panel plane | boosts only |
| Pre-boom epoch check | high probability in 2021 imagery too, so probably not new PV | demotes |
| Vegetation veto | a crop cycle observed over the year, so not a panel | drops, into a separate clean file |

`earthpv export` writes GeoParquet, GeoJSON and a MapRoulette challenge ordered by
`rank_score`.

### 4. People verify, and the labels come back

Mappers open each lead in the OpenStreetMap editor, compare it against the
high-resolution layers, and either map the installation properly or discard the lead.
Local mappers add what no imagery shows: which industrial estate this is, whether the roof
belongs to a factory or a school, whether the array is net-metered.

Verified installations then flow straight back into step 1 through the Overpass label path.
The label-driven compose run in Punjab unlocked roughly 2,500 in-domain Pakistani
positives this way, and adding them tripled large-array recall in Punjab compared with the
Germany-only model.

## Two products fall out of one model

![Two products from one model: Sentinel-2 composites feed TerraMind, whose probability raster splits into a leads product of polygons for human review, which flows to OpenStreetMap through a MapRoulette challenge, and a capacity product of megawatts peak per building and grid cell, which flows to PyPSA-Earth as a grid CSV.](assets/figures/two_products.svg#only-light)
![Two products from one model: Sentinel-2 composites feed TerraMind, whose probability raster splits into a leads product of polygons for human review, which flows to OpenStreetMap through a MapRoulette challenge, and a capacity product of megawatts peak per building and grid cell, which flows to PyPSA-Earth as a grid CSV.](assets/figures/two_products.dark.svg#only-dark)

The split matters because the two products have opposite tolerances. On the leads path a
false positive is cheap and a miss is expensive, so the model runs hot. On the capacity
path there is no human in the loop at all, so every candidate is reweighted by a
**measured** probability of being real before its area is counted. Same rasters, different
accounting, documented in [Calibration](methods/calibration.md).

## Reproducing the loop

Every step above is a CLI command that is resumable and safe to re-run. The full runbook,
including how to start on a region with no pre-existing data, is in
[Reproduce](reproduce.md).
