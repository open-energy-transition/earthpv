# Map the leads with JOSM

Every country's atlas on the [Countries](../atlas.md) tab links its **confirmed mapping
leads**, `<country>_pv_confirmed_leads.geojson`, largest first: places where the segmentation
model outlined a solar array in Sentinel-2 imagery more than 100 m from every solar
installation in OpenStreetMap, and a person has since judged the outline solar on the
country's [review pages](review.md). They are installations of 1 ha (10,000 m<sup>2</sup>)
and up: factory and warehouse roofs, ground-mounted parks.

**Every outline in it is a real installation**: someone has already looked at it on the
imagery the model saw and on Esri's, so all that is left is to trace it. A country has a
confirmed file once its review pages have been judged; until then its atlas offers no leads.
The model's other outlines are not handed to mappers: drawn from 10 m pixels and unchecked,
many of them are bright roofs, fields or shadows, so they go to the review pages first.

Mapping them does two things. The next time the country's atlas is rebuilt, each
installation you add is counted as hand-mapped solar. And the next time the country's model
is trained, it learns from that country's own OpenStreetMap solar, because every country's
model is fine-tuned on its own labels: each large installation you map is a new example
from exactly the landscape the model has to work in. Mapped leads become labels, the labels
make a better model, and the better model finds the next leads
([how it works](../how-it-works.md#workflow)).

Unlike a [calibration area](calibration-areas.md#the-one-rule-map-everything-inside-the-line), leads
come with no completeness rule: map as many as you like and stop when you want.

**How far to go.** Every confirmed lead is real, so a confirmed file is worth finishing.
Tell us how far you got (the `candidate_id` of the last lead you mapped) in an
[issue](https://github.com/open-energy-transition/earthpv/issues), so it can be recorded.

This guide combines three JOSM plugins the way Open Energy Transition's
[MapYourGrid](https://mapyourgrid.org/strategies/) uses them for its hint layers:
**OpenData** to read lead lists, the **Todo list** to step through them one at a time, and
**continuous download** to have the OpenStreetMap data ready wherever you land.

!!! warning "Leads, not data"
    A confirmed lead is a real installation, but its outline is drawn from 10 m pixels,
    typically about twice the area of the panels it found. **Never upload a lead and never
    copy its outline.** Find each one on high-resolution imagery and trace what you see
    there.

## 1. Get the lead file

1. Open the country's atlas from the [Countries](../atlas.md) tab and scroll to **Download
   the raw data and new OpenStreetMap hints behind this atlas**. The card *Mapping leads:
   solar installations a person has checked that OpenStreetMap does not have yet* links
   `<country>_pv_confirmed_leads.geojson`. A country without the card has no confirmed
   leads yet.
2. Note the date on the card. Leads are checked against OpenStreetMap as of that day, so an
   installation mapped since can still be in the file; continuous download (step 5) shows
   you when it is.
3. The file is sorted largest first. JOSM shows each lead's properties as tags:

| property | what it tells you |
| --- | --- |
| `candidate_id` | the lead's id, the same in the country's other exports |
| `rank_score` | the model's confidence times a building prior |
| `confidence` | the highest model probability inside the outline |
| `area_m2` | the outline's area; the panels are usually about half of it |
| `placement` | `rooftop` (on a building), `ground_adjacent` (next to one) or `no_building` (open land) |
| `oversize` | `true` for an outline above 100,000 m<sup>2</sup> (10 ha), judged on the solar farm review |
| `slope_deg` | the terrain slope at the lead, in degrees (Copernicus 90 m elevation model) |
| `steep_review` | `true` for a lead of 1,000 m<sup>2</sup> or more on ground steeper than 15&deg; (up to 30&deg;): look at the terrain as well as the outline (below) |
| `ever_wet_frac` | share of the outline ever under water since 1984 (only in countries with the pans-and-ponds screen) |
| `review_verdict` | `pv`: a person judged it solar |
| `review_page` | the review page the verdict was given on: `solar_farm` (above 10 ha) or `large_installation` (1 to 10 ha) |
| `lon`, `lat` | a point inside the outline |

**Steep ground.** A lead marked `steep_review` lies on ground steeper than 15&deg;. A person
judged it solar, but shaded hillsides, cliff edges and the shadows under escarpments look
like panels from space, so check whether the dark patch is panels or the slope's own shadow.
Sentinel-2 passes in the mid-morning, so shadows fall to the north-west north of the equator
and to the south-west south of it.

**Very large outlines.** Sentinel-2's 10 m pixels merge everything bright and touching into
one shape, so an outline above 100,000 m<sup>2</sup> (`oversize`) can hold a park and the
fields around it. The reviewer judged it on the Sentinel-2 imagery the model saw: look at
recent Sentinel-2 as well as the high-resolution layers, for example in the
[Copernicus Browser](https://browser.dataspace.copernicus.eu/), since a park built after the
high-resolution capture shows only there. Map the park's outline or its panel blocks from
the high-resolution imagery, never the model's outline. If the high-resolution imagery is
older than the park, say so in an issue instead of mapping it.

Some files are long: India's holds about 1,400 confirmed leads. Work one region at a time
(step 3).

### A few leads in iD

For a handful of leads, the confirmed file of a small country for instance, the browser
editor is enough. Download the file, open [iD](id.md) over the country, and drag the
`.geojson` onto the map (or load it under *Map Data*, *Custom Map Data*). The leads draw as
an overlay iD never uploads; click one to read its properties. Zoom to each in turn and map
it as in step 6 below. iD has no to-do list, so for a long file use JOSM.

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

**A long file: cut out your region.** To work one district at a time, either:

- **In JOSM.** With the leads layer active, zoom to your district, open *Search* (`Ctrl+F`)
  and search for `inview`, which selects the leads in view. The search can filter on the
  lead properties too, for example `inview placement=rooftop` or
  `inview area_m2>50000 placement=no_building`. Add only that selection to the Todo list in
  step 4.
- **Before JOSM, with OpenData.** Cut the file down to a CSV of the leads you want and open
  that instead. The OpenData plugin reads a semicolon-separated CSV, places each row at its
  `latitude` and `longitude` columns, and keeps the other columns as tags. In
  [QGIS](https://qgis.org): add the GeoJSON as a vector layer, select the leads in your area,
  then *Export &rarr; Save Selected Features As*, format *Comma Separated Value [CSV]*, with
  *SEPARATOR* set to *SEMICOLON*. Rename the `lat` and `lon` columns to `latitude` and
  `longitude` in any spreadsheet and save it again as a semicolon CSV. With
  [GDAL](https://gdal.org) installed, one command does both, here for India's confirmed
  leads in a box around Jodhpur:

    ```bash
    ogr2ogr -f CSV -lco SEPARATOR=SEMICOLON -spat 71.5 25.5 74.0 28.0 \
      -sql "SELECT candidate_id, area_m2, placement, lat AS latitude, lon AS longitude FROM india_pv_confirmed_leads" \
      jodhpur_leads.csv india_pv_confirmed_leads.geojson
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
2. **Find the panels.** Every lead has already been judged solar, so the question is only
   where the panels are; if no layer shows them, the installation is newer than the
   imagery: leave it and say so in an issue.
    - **Already in OpenStreetMap**, mapped after the file was made: nothing to do.
    - **Not solar after all**: map nothing, and say so in an issue, naming its
      `candidate_id`. Do not change anything else to "explain" it.
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
  hand-mapped layer and in *Verified*, and the leads they answer drop out of the next
  confirmed file, since they are now within 100 m of OpenStreetMap solar. A very large
  outline you map is counted from your outline, never from the model's.
- **The model.** The next time the country's model is trained, they are training labels.
  Arrays below 400 m<sup>2</sup> are left out of the model's training, because it cannot
  resolve them from 10 m pixels, so the large installations are the ones that teach it; the
  small ones still count in the atlas.
- **The false alarms.** Nothing in OpenStreetMap records a lead that turned out not to be
  solar, so say so in an [issue](https://github.com/open-energy-transition/earthpv/issues),
  as above; a verdict given on a [review page](review.md) is recorded with the run. If a
  whole kind of outline is wrong where you map, greenhouses or a particular roof material,
  say that too: it is the cheapest way to tell the next model what to ignore.
