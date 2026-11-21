# Check the large installations on your PC

If you run EarthPV yourself, building an atlas on [your own PC](new-atlas.md) or keeping one
up to date, every country's run sets up two **reviews** of the large outlines the model drew
where OpenStreetMap has no solar. They are the quickest way to make an atlas more right where
it matters most, at its largest installations, and they are stage 3 of the
[mapping flywheel](index.md).

| review | what it holds | how it is checked | what it changes |
|---|---|---|---|
| **Solar farm review** | outlines above 100,000 m<sup>2</sup> (10 ha) | on a page of Sentinel-2 pictures, a few keys per outline | nothing this size counts until a person judges it solar or it is mapped, so each park you confirm is added whole |
| **Large installation review** | outlines from 10,000 m<sup>2</sup> (1 ha) up to 10 ha, on roofs and on the ground | in JOSM, mapping the real installations into OpenStreetMap | these already count, each at the share its size class usually turns out real; an installation you map counts from the map instead, at its real shape |

Both are drawn by default after a country's `export` step, largest first, and only from
outlines that are still leads: no mapped solar within 100 m, inside the atlas's regions, and
past the screens that take out steep slopes, open ground of low confidence and, where a
country switches it on, water.

## Which imagery a verdict may come from

**A verdict EarthPV uses rests on Sentinel-2 alone, or it is an installation mapped in
OpenStreetMap.** Sentinel-2 is free Copernicus data that anyone may use for anything. The
high-resolution imagery in Google, Bing, Esri and Mapbox is not: their terms allow it, in an
editor, for tracing features into OpenStreetMap, and not for checking a dataset like this
one. So the solar farm page shows Sentinel-2 and nothing else, and `apply` refuses the export
of a page drawn before 20 November 2026, which showed Esri World Imagery beside it. The large
installations, too small to settle at 10 m, are reviewed where that imagery may be used: in
JOSM, mapping what is there into OpenStreetMap, from where EarthPV counts it like any other
mapped solar. Verdicts given before 20 November 2026 stand as they were given.

## The solar farm review: judge on Sentinel-2

`data/oversize_review/index.html` lists every country's page, with how many outlines are
left. Open one in a browser. Nothing is uploaded: the page and its pictures sit on your disk,
and your progress is kept in the browser until you export it. If a country has no page, or
its page is older than 20 November 2026, draw it:

```bash
pixi run blob-review draw --aoi YOUR_AOI
```

Drawing a page again keeps every verdict already given.

Each outline is three panels of the Sentinel-2 composite the model saw, the model's outline
in yellow:

- **True colour**, around the whole outline. This is the right date: it shows parks built
  after any high-resolution capture.
- **The same at its native 10 m pixels**, close in.
- **A false colour** (shortwave infrared, near infrared, red). Panels read dark purple;
  vegetation bright green; water dark in every panel.

Press <kbd>1</kbd> for **PV**, <kbd>2</kbd> for **Not PV**, <kbd>3</kbd> for **unsure**,
<kbd>4</kbd> for **bright roof**, <kbd>&larr;</kbd> <kbd>&rarr;</kbd> to step, <kbd>n</kbd>
for a note.

- **PV**: a solar park inside the outline: blocks of even dark blue-grey with straight edges,
  a grid of access roads, small bright inverter pads. Judge whether a park is there, not how
  well the outline fits it.
- **Not PV**: something else. The usual look-alikes are dark ploughed fields (dark only in
  true colour), water and aquaculture ponds (dark in every panel), burn scars, rock, shaded
  slopes, snow, riverbeds and greenhouses.
- **Unsure**: 10 m pixels cannot settle it. It does not count and comes back on the next
  page. If you map in OpenStreetMap, the outline's **Map it in JOSM** link opens the spot
  there: a park you map counts from the map.
- **Bright roof**: not PV, and the outline sits on very bright roofs (white or light metal, a
  reflective coating). It counts exactly as Not PV, but `apply` keeps the label apart
  (`flag` in the country's `review.csv`), so these false alarms can be gathered and studied.

Judge on the three panels alone. The links under them open only free data: Sentinel-2 on
other dates in the Copernicus Browser, to watch a park being built, and the OpenStreetMap map.
A flat grey block is a cell nobody imaged, and a black block that reads dark red in the false
colour is a cell that lost bands; neither is ground.

When you are done for the day, press **Export** at the top of the page and apply the file
under your name:

```bash
pixi run blob-review apply --aoi YOUR_AOI --reviewer "Your name" \
    --verdicts YOUR_AOI_blob_verdicts.csv
```

## The large installation review: review in JOSM while mapping

An outline of 1 to 10 ha is often a roof, and 10 m pixels cannot tell a roof full of panels
from a dark metal one. So these are reviewed in [JOSM](josm.md), on the imagery it offers
for mapping, and the real ones mapped into OpenStreetMap. The review and the mapping are one
step: an installation you map is the verdict.

### 1. Get the review layer

```bash
pixi run large-review draw --aoi YOUR_AOI
```

writes `data/large_review/YOUR_AOI/YOUR_AOI_large_review.osm` (and `data/large_review/index.html`
lists every country's layer). It holds the leads still open, largest first, each tagged
`earthpv:code`, its size, placement and region, and `earthpv:review=todo`. JOSM refuses to
upload it or to download into it: it is a list of places to look, never data.

### 2. Set up JOSM

Set JOSM up as in [Map the leads with JOSM](leads.md#2-set-up-josm-and-the-three-plugins):
the **Todo list** to step through the leads and **continuous download** to have the
OpenStreetMap data ready wherever you land (OpenData is not needed here).

### 3. Open the layer and load the Todo list

1. *File &rarr; Open* (`Ctrl+O`) the `.osm` file. With it active, select the leads you want
   to work (`Ctrl+A`, or *Search* `inview` for those in view, `earthpv:review=todo` for those
   still open), open *Windows &rarr; Todo list* and press **Add**.
2. Download the OpenStreetMap data at the first lead as a new layer (*File &rarr; Download
   data*, **Download as new layer** ticked), make that layer active, and turn on *File
   &rarr; Download OSM data continuously*.

### 4. Work through the leads

For each lead the Todo list zooms to, switch between the imagery layers as in
[Map with JOSM, step 3](josm.md#3-check-the-imagery-and-add-more-layers), then:

- **Solar there**: map it in the OpenStreetMap layer, never by copying the lead's outline:
  the panels on a roof as `power=generator` with `location=roof`, a park as a `power=plant`
  outline, as in [Map the leads, step 6](leads.md#6-work-through-the-leads). Then **Mark** it
  in the Todo list. Nothing else to record: the next OpenStreetMap pull finds it.
- **Already in OpenStreetMap**: Mark it.
- **No solar**, on imagery recent enough to show it: click the review layer, set the lead's
  `earthpv:review` to `not_pv`, click back to the OpenStreetMap layer, and Mark it. The usual
  look-alikes are dark or blue metal roofs, wet or tarred roofs, greenhouses and shade
  netting, solar water heaters, car parks, water and dark fields.
- **Cannot tell**, or the imagery is older than the installation could be: Pass (`[`) and
  leave it `todo`, or set `unsure`. It comes back in the next layer.

### 5. Upload, save, record

1. Upload the OpenStreetMap layer as in [Map with JOSM, step 6](josm.md#6-validate-and-upload),
   with a comment such as `Map solar PV found by the EarthPV large installation review
   #tracethesun #earthpv #earthpv-large-review` and the imagery you traced from in `source`.
2. Save the review layer (`Ctrl+S`; it stays an `.osm` file) and record its marks under your
   name:

    ```bash
    pixi run large-review apply --aoi YOUR_AOI --reviewer "Your name" \
        --josm data/large_review/YOUR_AOI/YOUR_AOI_large_review.osm
    ```

### What each lead becomes

- **Mapped**: once the country's OpenStreetMap solar is pulled again, the lead leaves the
  review and the installation counts from the map at its real shape, in *Verified* as well as
  *Best*; the model's coarser outline of it is not counted on top. It is also a training example
  for the country's next model.
- **Not solar** (`not_pv`): it leaves the review and keeps the share its size class turns
  out real. The judgement was made on imagery licensed only for mapping into OpenStreetMap, so
  EarthPV takes nothing from it but the fact that someone looked.
- **Unsure or not reached**: it comes back the next time the layer is drawn.

### A Sentinel-2 page for the large leads, too

Where 10 m pixels can settle a lead, mostly a park on open ground, the large installations
can also be judged on a page like the solar farm one: `pixi run large-review package --aoi
YOUR_AOI --page` draws it into `data/large_review/YOUR_AOI/index.html`. A verdict there
replaces the lead's share for that lead alone: solar counts it as real (on a roof, 1/2.5 of
the outline, since the model draws a roof array about 2.5 times its size), not solar counts
it as nothing. Leave a roof you cannot tell at 10 m unsure, and the JOSM review takes it up.
Apply the export with `--verdicts YOUR_AOI_large_verdicts.csv` in place of `--josm`.

## Then recompute the country

Any named reviewer counts, and your name is kept beside every verdict and mark you give;
when a second person judges an outline again, `apply` reports where the two agree. After a
mapping session, pull the country's OpenStreetMap solar again (the `overpass_labels_chunked.py`
and `drop_solar_thermal.py` commands of [a new atlas](new-atlas.md)) and apply once more with
the new pull, so the leads mapped since leave the review:

```bash
pixi run large-review apply --aoi YOUR_AOI --reviewer "Your name" \
    --labels data/labels/YOUR_AOI_overpass_solar.parquet
```

Then recompute the country. This is much quicker than its first run, because every cell's
cached result is reused and no imagery is read again:

```bash
pixi run earthpv density --aoi YOUR_AOI --districts
# then the atlas, with the same command and the new pull as --osm-solar
```

Verdicts also decide which leads mappers get the next time the lead files are made, a step of
every run after the atlas (`scripts/release_leads.py`): an outline judged solar on Sentinel-2
that OpenStreetMap still lacks becomes a **confirmed lead**, the only kind the atlas offers
mappers, and one judged not solar there leaves the lead files. Maintainers publish them with
`pixi run python scripts/release_leads.py --aoi YOUR_AOI --upload` and then
`scripts/patch_atlas_leads.py` on the atlas. `pixi run blob-review status` and
`pixi run large-review status` show what is left per country.

## What happens to an outline you judged

- **Judged solar on Sentinel-2: a confirmed lead.** Until someone maps it, it is in the
  country's `<country>_pv_confirmed_leads.geojson`, largest first ([lead guide](leads.md)). A
  person's verdict outranks the lead screens, so it stays there whatever its slope or model
  probability. It counts in the atlas from your verdict once the country is recomputed;
  mapping it gives it its real shape.
- **Judged not solar on Sentinel-2.** It is dropped from the lead files for good and counts
  nothing.
- **Mapped.** Once someone maps it in OpenStreetMap, the map counts it and any verdict rests.
  The country's next model learns from it.
- **Unsure, or skipped.** It stays unconfirmed, so no mapper is sent to it, and comes back.
- **A new model run.** A new run numbers its outlines afresh, so a review belongs to the run it
  was drawn from; the next run starts a new one.
- **Not solar, on record.** Nothing in OpenStreetMap records a false alarm, so the review
  files are the only place that knowledge lives: keep them with the run. The country's
  polygon release carries every verdict beside its outline (`review_verdict`).
