# Map a calibration area with iD

iD is OpenStreetMap's editor in the browser: nothing to install, and the atlas opens it on
your area with the boundary already drawn. It is the easiest way to map your first area,
especially a sparse candidate with a few hundred buildings. For dense areas with thousands
of buildings, [JOSM](josm.md) is faster.

You need a free [OpenStreetMap account](https://www.openstreetmap.org/user/new). Log in on
openstreetmap.org before you start, so iD opens ready to save.

## 1. Open the area

On a country's atlas, click a candidate (hollow diamond; the **star** marks the one to map
first) or a finished area (filled diamond) and press **Open in iD**. A new tab opens iD:

- centred on the area, at zoom 16;
- with the area's **boundary drawn as a dashed overlay**. It is iD's *Custom Map Data* layer
  (Map Data panel, key `U`), which iD never uploads, so you cannot add the box to
  OpenStreetMap by accident;
- on **Esri World Imagery**, the layer whose capture date the atlas checked;
- with the changeset comment and the hashtags `#tracethesun #earthpv #earthpv-calibration` filled in for
  when you save.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-id-boundary.png`

**Show:** iD right after pressing *Open in iD* on a candidate, at about zoom 17 over Esri
World Imagery. The dashed boundary of the area crosses the view, with a few houses on
either side, and the Map Data panel (key `U`) is open on the right with *Custom Map Data*
ticked. Ideally one or two panels are already traced inside the line.
</div>

The boundary is the whole job: every panel **inside** the line, nothing required outside
it. A panel that straddles the line is still worth mapping; whether it counts is decided
later from its centre.

## 2. Check the imagery date

Press `Ctrl+Shift+B` (macOS: `Cmd+Shift+B`) to open the background info panel. For Esri
World Imagery it shows the capture date of the imagery under the centre of the screen.
Compare it with the date in the atlas popup.

If the imagery is more than about a year older than the date in the popup, or the box sits
on nothing you could map (open desert, water, a quarry), stop here and
[report it as not mappable](report.md). That is a useful result, not a failure.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-id-imagery-date.png`

**Show:** the same area in iD with the Background panel (key `B`) open on the right, listing
the available imagery (Esri World Imagery selected, Bing and Mapbox visible), and the
background info panel at the bottom (`Ctrl+Shift+B`) showing Esri's capture date.
</div>

## 3. Map every panel

1. Zoom in to 18 or 19, so a single panel group is clearly visible.
2. Press `3` (the **Area** tool) and click around the **panels only**, never the whole roof.
   Close the shape by clicking the first point again.
3. In the preset list, type `solar` and pick:
    - **Rooftop Solar Panel** for panels on a building;
    - **Solar Panel** for panels on the ground (fields, yards, pump frames).
4. Press `Q` to square the corners, if the shape is a rectangle.

One area per contiguous group of panels; two separate groups on one roof are two areas.
For a tiny installation where tracing is hopeless (under about 4 m<sup>2</sup>), a point with
the same preset is fine.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-id-preset.png`

**Show:** one traced rooftop panel group selected in iD, with the preset search on the left
after typing `solar`, showing *Rooftop Solar Panel* at the top of the results and
*Solar Panel* below it.
</div>

The presets set the tags the calibration reads:

```
power=generator
generator:source=solar
generator:method=photovoltaic
generator:type=solar_photovoltaic_panel
generator:output:electricity=yes
location=roof                  (Rooftop Solar Panel only)
```

Not solar: water heaters (tubes or a round tank), skylights, blue-painted roofs. If you
really cannot tell at full zoom, map it and add the tag `fixme=possible solar` (in the
tag editor's text view) rather than guessing either way.

## 4. Sweep the whole box

Work through the box in strips, street by street, instead of jumping to what catches your
eye. Then **switch the imagery** (key `B`) and sweep again: Esri World Imagery, Bing, Mapbox
Satellite and any regional layer iD lists for the area. A panel invisible on one layer is
often obvious on the next, because the layers differ in date, sun angle and sharpness.
Mapping against a single layer is the most common reason a "complete" area is not.

## 5. Save

Press `I` to check iD's issues panel, then save (`Ctrl+S`). The comment and hashtags are
already filled in; iD records the imagery you used on its own. Save every hour or so
rather than once at the end: smaller changesets are easier for others to review.

<div class="shot-needed" markdown>
**Screenshot needed** · save as `docs/assets/figures/contribute-id-save.png`

**Show:** iD's save panel before uploading, with the prefilled changeset comment
(*Map rooftop and ground-mounted solar PV in ... (earthpv calibration area)*) and the
hashtags `#tracethesun #earthpv #earthpv-calibration`, and the number of changes visible.
</div>

Then [report your progress](report.md): finished, partly done, or not mappable.

## Your own proposed area

A box from the atlas's **Propose a calibration area** button has no published file yet, so
**Open in iD** only opens at its location. Press **GeoJSON** in the popup to download the
box, then drag the file onto the iD map: it appears as the same never-uploaded overlay.
iD cannot draw and save a boundary of your own; for that, see
[Draw your own area](draw-area.md), which uses JOSM.
