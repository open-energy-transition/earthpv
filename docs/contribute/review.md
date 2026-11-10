# Judge large installations on your PC

If you run EarthPV yourself, building an atlas on [your own PC](new-atlas.md) or keeping one
up to date, every country's run makes two **review pages**: one picture of each large outline
the model drew where OpenStreetMap has no solar, and a few keys to say what it is. A verdict
takes a few seconds, needs no OpenStreetMap account, and changes the country's capacity
directly. It is the quickest way to make an atlas more right where it matters most, at its
largest installations.

| page | what it shows | what your verdict changes |
|---|---|---|
| **Solar farm review** | outlines above 100,000 m<sup>2</sup> (10 ha) | nothing this size counts until a person judges it solar, so each park you confirm is added whole |
| **Large installation review** | outlines from 10,000 m<sup>2</sup> (1 ha) up to 10 ha, on roofs and on the ground | these already count, each at the share its size class usually turns out real; your verdict replaces that share for this outline: solar counts it as real (on a roof, 1/2.5 of the outline, since the model draws a roof array about 2.5 times its size), not solar counts it as nothing |

Both are drawn by default after a country's `export` step, largest first, and only from
outlines that are still leads: no mapped solar within 100 m, inside the atlas's regions, and
past the screens that take out steep slopes, open ground of low confidence and, where a
country switches it on, water.

## Open a page

`data/oversize_review/index.html` lists every country's solar farm page and
`data/large_review/index.html` every country's large installation page, with how many
outlines are left. Open one in a browser. Nothing is uploaded: the page and its pictures sit
on your disk, and your progress is kept in the browser until you export it.

If a country has no page, draw it:

```bash
pixi run blob-review draw --aoi YOUR_AOI      # the solar farm review
pixi run large-review draw --aoi YOUR_AOI     # the large installation review
```

Drawing a page again keeps every verdict already given.

## How to judge

Each outline is one picture of four panels, with the model's outline in yellow:

- **Sentinel-2 as the model saw it**, in true colour, around the whole outline. This is the
  right date: it shows installations built after the high-resolution imagery was taken.
- **The same at its native 10 m pixels**, close in.
- **A false colour** (shortwave infrared, near infrared, red). Panels read dark purple;
  vegetation bright green; water dark in every panel.
- **Esri World Imagery** with its capture date, for texture: rows of panels, a roof's edge.

Press <kbd>1</kbd> for **PV**, <kbd>2</kbd> for **Not PV**, <kbd>3</kbd> for **unsure**,
<kbd>4</kbd> for **bright roof**, <kbd>&larr;</kbd> <kbd>&rarr;</kbd> to step, <kbd>n</kbd>
for a note.

- **PV**: panels inside or touching the outline. Judge whether solar is there, not how well
  the outline fits it: the model's outline is often larger than the array.
- **Not PV**: something else, and the imagery is recent enough to show panels if they were
  there. The usual look-alikes are dark or blue metal roofs, wet or tarred roofs, greenhouses
  and shade netting, solar water heaters, car parks, dark ploughed fields, water and
  aquaculture ponds, burn scars, rock and shaded slopes.
- **Unsure**: the four panels cannot settle it. Each picture links Google, Bing, Esri Wayback
  and JOSM at that spot; decide there, or leave it unsure. An unsure or skipped outline keeps
  the price it had and comes back on the next page.
- **Bright roof**: not PV, and the outline sits on a very bright roof (white or light metal,
  a reflective coating). It counts exactly as Not PV, but `apply` keeps the label apart
  (`flag` in the country's `review.csv`), so these false alarms can be gathered and studied.
  A bright roof that does carry panels is PV.

A flat grey block in the Sentinel-2 panels is a cell nobody imaged, and a black block that
reads dark red in the false colour is a cell that lost bands. Neither is ground: judge those
parts on Esri.

## Record your verdicts

Stop whenever you like. When you are done for the day, press the **Export** button at the top
of the page and apply the file it saves under your name:

```bash
pixi run large-review apply --aoi YOUR_AOI --reviewer "Your name" \
    --verdicts YOUR_AOI_large_verdicts.csv
pixi run blob-review apply --aoi YOUR_AOI --reviewer "Your name" \
    --verdicts YOUR_AOI_blob_verdicts.csv
```

Any named reviewer's verdict counts. Your name is kept beside every verdict you give, and
when a second person judges an outline again, `apply` reports where the two agree. Then
recompute the country. This is much quicker than its first run, because every cell's cached
result is reused and no imagery is read again:

```bash
pixi run earthpv density --aoi YOUR_AOI --districts
# then the atlas, with the same command that built it
```

`pixi run large-review status` and `pixi run blob-review status` show what is left per
country. An outline you judged leaves the page the next time it is packaged.

## What happens to an outline you judged

- **Mapped later.** Once someone maps it in OpenStreetMap, the map counts it and your verdict
  rests. Mapping a confirmed outline is still worth it: the map gives its real shape, and the
  country's next model learns from it ([map the leads](leads.md)).
- **A new model run.** A new run numbers its outlines afresh, so a review belongs to the run it
  was drawn from; the next run starts a new page.
- **Not solar.** Nothing in OpenStreetMap records a false alarm, so the verdict is the only
  place that knowledge lives: keep the review files with the run.
