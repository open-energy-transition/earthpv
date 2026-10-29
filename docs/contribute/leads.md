# Map the leads with JOSM

Every country's atlas on the [PV Atlas](../atlas.md) tab links a file of **mapping leads**:
places where the segmentation model outlined a solar array in Sentinel-2 imagery more than
100 m from every solar installation in OpenStreetMap when the file was made. Most are arrays
of 400 m<sup>2</sup> and more, the size the model is trained and measured on: factory and
warehouse roofs, ground-mounted parks, large pump arrays.

Mapping them does two things. The next time the country's atlas is rebuilt, each
installation you add is counted as hand-mapped solar. And the next time the country's model
is trained, it learns from that country's own OpenStreetMap solar, because every country's
model is fine-tuned on its own labels: each large installation you map is a new example
from exactly the landscape the model has to work in. Mapped leads become labels, the labels
make a better model, and the better model finds the next leads
([how it works](../how-it-works.md#workflow)).

Unlike a [calibration area](index.md#the-one-rule-map-everything-inside-the-line), leads
come with no completeness rule: map as many as you like, in any order, and stop when you
want.

This guide combines three JOSM plugins the way Open Energy Transition's
[MapYourGrid](https://mapyourgrid.org/strategies/) uses them for its hint layers:
**OpenData** to read lead lists, the **Todo list** to step through them one at a time, and
**continuous download** to have the OpenStreetMap data ready wherever you land.

!!! warning "Leads, not data"
    Every lead is an unverified outline drawn from 10 m pixels, typically about twice the
    area of the panels it found, and some are not solar at all: bright or dark roofs,
    greenhouses, artificial turf, ploughed fields, rock, water, substations, swimming pools
    and the rectangular basins and sludge drying beds of wastewater treatment plants (many
    of Egypt's leads are these last two). **Never upload a lead and never copy its
    outline.** Check each one on high-resolution imagery and trace what you see there.

## 1. Get the lead file

1. Open the country's atlas from the [PV Atlas](../atlas.md) tab and scroll to **Download
   the data behind this atlas**. The first card, *Mapping leads: solar arrays the model found
   that OpenStreetMap does not have yet*, links the country's file,
   `<country>_pv_new_leads.geojson`, and its release notes.
2. Note the date on the card. Leads are checked against OpenStreetMap as of that day, so an
   installation mapped since can still be in the file; continuous download (step 5) shows
   you when it is.
3. The file is sorted most promising first. JOSM shows each lead's properties as tags:

| property | what it tells you |
| --- | --- |
| `candidate_id` | the lead's id, the same in the country's other exports |
| `rank_score` | the model's confidence times a building prior; the sort order |
| `confidence` | mean model probability inside the outline |
| `area_m2` | the outline's area; the panels are usually about half of it |
| `placement` | `rooftop` (on a building), `ground_adjacent` (next to one) or `no_building` (open land) |
| `oversize` | `true` for an outline above 100,000 m<sup>2</sup>: often a whole unmapped park, sometimes a merged sheet of false alarms |
| `lon`, `lat` | a point inside the outline |

Large countries have large files: India's holds about 100,000 leads (91 MB). Work one region
at a time (step 3). France's leads are a separate,
[audited release](https://github.com/open-energy-transition/earthpv/releases/tag/france-osm-leads-2026-10-22)
with priority tiers and one file per d&eacute;partement.

## 2. Set up JOSM and the three plugins

Set JOSM up as in [Map with JOSM](josm.md#1-set-up-josm-once): install it and log in. Remote
Control is not needed for leads. Then:

1. **Install the plugins.** *Edit &rarr; Preferences* (`F12`) &rarr; **Plugins**: search for
   each of these, tick it, press OK and restart JOSM.
    - `opendata` reads lead lists as CSV, spreadsheets (ODS, XLS), KML/KMZ or Shapefile.
      JOSM opens the GeoJSON lead file without it; you need it for a list you cut down
      yourself (step 3).
    - `todo` is the **Todo list**: it steps you through a list of objects and remembers which
      ones you have done.
    - `continuosDownload` (spelled that way) downloads the OpenStreetMap data around wherever
      you look.
2. **Set continuous download's limits** on its own preferences tab, **Download Settings**.
   MapYourGrid uses *Max download boxes* 4, *Wait time (milliseconds)* 100, *Extra download
   area* 1 and *Max download area* 1. Stay zoomed in to a lead or two: zooming far out over a
   city asks the server for a great deal of data.
3. **Turn on expert mode** (*View &rarr; Expert Mode*). Step 3 needs it to protect the leads
   layer.
4. **Optional, from MapYourGrid:** give the Todo list's *Mark* its own key. It is `]` by
   default (and `[` passes over a lead); under *Preferences &rarr; Keyboard Shortcuts*,
   search for "Mark", untick *Use default* and choose a key such as `F1`.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-leads-plugins.png`

**Show:** JOSM's Preferences dialog on the Plugins tab, filtered so that *opendata*, *todo*
and *continuosDownload* are listed, all three ticked.
</div>

## 3. Open the leads as a hint layer

1. **Open the file**: *File &rarr; Open* (`Ctrl+O`) and pick the `.geojson`, or drag it onto
   the JOSM window. The leads appear as outlines in a new layer named after the file.
2. **Protect it from upload**: right-click the leads layer in the *Layers* panel and choose
   **Discourage upload**. JOSM then asks before it would upload that layer. It cannot block
   a GeoJSON layer outright, so treat the leads layer as read-only: never draw, move or tag
   anything in it, and undo (`Ctrl+Z`) anything that lands there by accident.

**A big country: cut out your region.** JOSM is comfortable with a few thousand leads. For
more, either:

- **In JOSM.** With the leads layer active, zoom to your district, open *Search* (`Ctrl+F`)
  and search for `inview`, which selects the leads in view. The search can filter on the
  lead properties too, for example `inview rank_score>0.9` or
  `inview area_m2>1000 placement=no_building`. Add only that selection to the Todo list in
  step 4.
- **Before JOSM, with OpenData.** Cut the file down to a CSV of the leads you want and open
  that instead. The OpenData plugin reads a semicolon-separated CSV, places each row at its
  `latitude` and `longitude` columns, and keeps the other columns as tags. In
  [QGIS](https://qgis.org): add the GeoJSON as a vector layer, select the leads in your area,
  then *Export &rarr; Save Selected Features As*, format *Comma Separated Value [CSV]*, with
  *SEPARATOR* set to *SEMICOLON*. Rename the `lat` and `lon` columns to `latitude` and
  `longitude` in any spreadsheet and save it again as a semicolon CSV. With
  [GDAL](https://gdal.org) installed, one command does both, here for the leads of
  1,000 m<sup>2</sup> and more in a box around Sana'a:

    ```bash
    ogr2ogr -f CSV -lco SEPARATOR=SEMICOLON -spat 44.10 15.25 44.35 15.50 \
      -sql "SELECT candidate_id, rank_score, area_m2, placement, lat AS latitude, lon AS longitude FROM yemen_pv_new_leads WHERE area_m2 >= 1000" \
      sanaa_leads.csv yemen_pv_new_leads.geojson
    ```

    Open the CSV with *File &rarr; Open*: each lead becomes a point. Discourage its upload as
    in point 2.

## 4. Load the Todo list, then switch layers

1. Make the **leads layer active** (click it in the *Layers* panel) and select the leads you
   want to work: `Ctrl+A` for all of them, or your search from step 3.
2. Open *Windows &rarr; Todo list* (`Ctrl+Shift+T`) and press **Add**.
3. **Make an OpenStreetMap data layer the active one.** On a fresh start there is none yet:
   select the first lead in the Todo list and press **Zoom**, then download that area
   (*File &rarr; Download data*, `Ctrl+Shift+Down`) with **Download as new layer** ticked.
   Click the new *Data Layer* in the *Layers* panel.

JOSM puts downloaded data into whichever data layer is active, and the leads layer is a data
layer too. OpenStreetMap data downloaded into the leads layer, and then uploaded from it, is
how a lead ends up in OpenStreetMap. Keep the OpenStreetMap layer active from here on.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-leads-todo.png`

**Show:** JOSM over Esri World Imagery with a lead's outline on a large roof, the *Todo list*
panel listing leads with the first one selected, and the *Layers* panel showing the leads
layer and *Data Layer 1*, the data layer highlighted as active.
</div>

## 5. Turn on continuous download

*File &rarr; Download OSM data continuously*. From now on JOSM fetches the OpenStreetMap data
around whatever you look at, into the active layer. Stepping through the Todo list leaves
the active layer as it was, so the OpenStreetMap layer stays active. If you click the leads
layer to search or add more leads, click back to the OpenStreetMap layer before you move on.

## 6. Work through the leads

For each lead, which the Todo list zooms to:

1. **Look before you map.** Switch between imagery layers as in
   [Map with JOSM, step 3](josm.md#3-check-the-imagery-and-add-more-layers): Esri World
   Imagery, Esri World Imagery (Clarity), Bing, Mapbox Satellite and any national layer. One
   layer may predate an installation that another shows.
2. **Decide what it is.**
    - **Already in OpenStreetMap**, mapped after the file was made: nothing to do.
    - **Not solar**: nothing to do. Do not map the lead, and do not change anything else to
      "explain" it.
    - **Solar on a roof**: trace the panels, not the roof, as in
      [Map with JOSM, step 4](josm.md#4-map-every-panel): `power=generator` with
      `location=roof`, one way per contiguous group of panels.
    - **A ground-mounted park or plant**: draw the site, along the fence or the edge of the
      panel field, and tag it as a plant:

        ```
        power=plant
        plant:source=solar
        plant:method=photovoltaic
        plant:output:electricity=yes
        ```

        Add `name` and `operator` only from a source you may use. If you have time, trace the
        panel blocks inside as `power=generator` ways too (the step 4 tags without
        `location=roof`); the plant outline alone is already useful.
    - **Smaller panels around the lead**: map them as well. The leads are about the large
      installations, but every installation counts.
3. **Trace from the imagery, never from the lead.** The outline is a coarse sketch from
   10 m pixels; the installation is in the photograph.
4. **Mark** it done in the Todo list (`]`, or your own key from step 2): JOSM moves to the
   next lead and zooms to it. **Pass** (`[`) leaves a lead in the list to come back to.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-leads-plant.png`

**Show:** a ground-mounted solar park in JOSM over high-resolution imagery, with the lead's
coarse outline from the leads layer and, on the data layer, the newly drawn `power=plant`
outline following the fence, its tags open in the tag editor.
</div>

## 7. Validate and upload

As in [Map with JOSM, step 6](josm.md#6-validate-and-upload), with three differences:

1. **Upload the OpenStreetMap data layer only.** If JOSM warns that uploading the layer is
   discouraged, it is about to upload the leads: cancel, and make the OpenStreetMap layer
   active.
2. **Write the changeset comment yourself**, since nothing fills it in for leads, for
   example `Map solar PV found by EarthPV mapping leads #tracethesun #earthpv`, and put the
   imagery you traced from in `source`.
3. **Upload every few dozen installations**, so each changeset stays easy to review.

## What happens to what you map

- **The atlas.** The next time the country's atlas is built, your installations are in its
  hand-mapped layer and in *Verified*, and the leads they answer drop out of the next lead
  file, since they are now within 100 m of OpenStreetMap solar.
- **The model.** The next time the country's model is trained, they are training labels.
  Arrays below 400 m<sup>2</sup> are left out of the model's training, because it cannot
  resolve them from 10 m pixels, so the large installations are the ones that teach it; the
  small ones still count in the atlas.
- **The false alarms.** Nothing records a lead you skipped as wrong. If a whole kind of lead
  is wrong where you map, greenhouses or a particular roof material, say so in an
  [issue](https://github.com/open-energy-transition/earthpv/issues): it is the cheapest way
  to tell the next model what to ignore.
