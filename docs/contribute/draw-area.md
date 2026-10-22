# Draw your own calibration area

The candidate areas on the atlas were placed by rule: drawn at random across each country's
building-density range, plus two start-here boxes in its densest districts with the most large
roofs. They are the first choice, because nobody picked them for the solar they contain. Drawing your
own is worth it when no candidate covers a kind of place the country still lacks, when a
candidate turns out not to be mappable, or when you know a place well enough to outline it
properly.

A drawn area does not have to be a square. An outline that follows the edge of a suburb, an
industrial estate or a village is often **better** than a box, which clips arbitrary halves
of whatever it lands on. This page shows how to draw one in JOSM, save it as GeoJSON and send
it in.

## Before you draw

- **Pick by landscape, never by panels.** Choose the kind of place first (a dense old town,
  a planned suburb, a farming village) and look at the solar second. An area chosen because
  you can already see panels there biases the calibration before anyone maps it.
- **Keep it one kind of place.** Do not mix planned housing with informal settlement, or an
  industrial estate with the houses next to it. A free outline makes this easy: follow the
  real edge.
- **For a sparse area, include the ground between the houses.** An outline traced tightly
  around a village's built-up edge is denser than the village's surroundings, and density is
  what decides which part of the country an area can calibrate. If the point is to reach the
  sparse end, take in the fields and gardens on purpose.
- **Not around a solar farm.** Ground-mounted parks are measured by the satellite model; an
  area sited to include one teaches the small-installation calibration the wrong thing.
- **Size.** Aim for 1 to 4 km<sup>2</sup>, with the whole outline fitting inside a square of
  about 2.2 km: that is one satellite training window. A larger area still works but counts
  for less per panel mapped; a long thin shape is better sent as two or three areas.
- **No overlap** with an existing area or candidate. Two overlapping areas count the shared
  panels twice.

## 1. Check the imagery date

A calibration area certifies every panel visible *on the imagery you map from*. If that
imagery is much older than the satellite data the model reads, the area cannot be used, no
matter how carefully it is mapped. Check before you draw:

1. Open the place in [iD](https://www.openstreetmap.org/edit?editor=id), choose **Esri World
   Imagery** as the background and press `Ctrl+Shift+B` (`Cmd+Shift+B` on a Mac). The
   background panel shows the imagery's capture date for the spot you are looking at.
   [Esri Wayback](https://livingatlas.arcgis.com/wayback/) shows the same dates and the
   history behind them.
2. Compare it with the Sentinel-2 dates shown under the headline figure of the country's
   atlas. If the oldest imagery over
   your area is more than about a year older than the start of that window, pick another
   place.

## 2. Draw the boundary on its own layer

1. In JOSM, **File -> New Layer** (`Ctrl+N`). The new, empty layer becomes the active one.
   Drawing the boundary here, rather than on the OpenStreetMap data layer, keeps it out of
   what you map.
2. Add **Esri World Imagery** from the **Imagery** menu and zoom to your area.
3. Press `A` (draw) and click around the area, putting the corners on things a second mapper
   can see: roads, canals, walls, field edges. **Close the outline** by clicking the first
   point again, then press `Esc`.
4. Leave it untagged. The outline needs no tags, and one file may hold several pieces: they
   are treated as one area.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-josm-draw-boundary.png`

**Show:** JOSM over Esri World Imagery with a hand-drawn closed outline following roads and
a canal around a neighbourhood, and the Layers panel listing the new boundary layer as the
active layer, separate from any *OSM data* layer.
</div>

**Starting from a square.** The atlas's **Propose a calibration area** button drops a 2 km
square and checks it against every existing area. Press **GeoJSON** in its popup, open the
file in JOSM with **File -> Open**, and move the corners to fit the area. (Its **Open in
JOSM** button loads the square locked, which is right for mapping but not for reshaping.)

!!! warning "Never upload the boundary"
    The outline is not an OpenStreetMap feature. JOSM still treats the new layer as a data
    layer, so never press Upload while it is selected. Map on the separate OSM data layer,
    and check the layer name in the upload dialog before you confirm.

## 3. Save it as GeoJSON

1. With the boundary layer still active, **File -> Save As...** (`Ctrl+Shift+S`).
2. In the file-type dropdown choose **GeoJSON**, and give the file a short name, e.g.
   `chipata_north.geojson`.

JOSM saves the whole active layer, so a layer holding only your outline gives a clean file.
The Measurement panel (**Windows -> Measurement**) shows the area of the selected outline if
you want to check the size first.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-josm-save-geojson.png`

**Show:** JOSM's Save As dialog with the file-type dropdown set to GeoJSON and a file name
such as `chipata_north.geojson` entered.
</div>

Any other tool that saves a polygon as GeoJSON in longitude/latitude works too, such as QGIS
or [geojson.io](https://geojson.io). iD cannot save one.

## 4. Check it against the existing areas

Drop the file onto the country's atlas map (or use **Layers -> Add a layer**). It appears as
your own layer next to every calibration area and candidate, so an overlap or a near-miss is
visible at once. The file stays in your browser; nothing is uploaded.

## 5. Send it in, then map

Send the boundary **before** you start mapping, and do not reshape it afterwards: a boundary
redrawn around what you found is biased in the same way as one placed where panels were
visible.

1. Open a **[calibration area report](https://github.com/open-energy-transition/earthpv/issues/new?template=calibration-area.yml)**.
2. **Area**: `drawn: ` plus the file name, e.g. `drawn: chipata_north`. **Status**: *Started*.
3. Open the `.geojson` file in a text editor and paste its whole content into **Boundary
   GeoJSON**.
4. Add the imagery you checked and its capture date.

A maintainer checks the outline (size, overlap, district) and answers on the report. Then map
it like any other area, following the [JOSM guide](josm.md#4-map-every-panel) from step 4,
with your boundary layer open beside the OSM data layer, and
[report it](report.md) when every panel inside is mapped. If you do have to change the
boundary, post the new file on the same report before mapping on.

Maintainers: a drawn boundary is registered with `--geojson`, see
[Register an area](maintainers.md#register-a-mapped-area). The full rules behind this page
are in the [mapping protocol](../calibration-mapping-protocol.md#drawing-the-boundary-in-josm).
