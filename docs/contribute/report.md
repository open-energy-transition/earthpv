# Report and verify an area

Mapping is done in OpenStreetMap, but nothing there tells us an area is finished. A short
report does: it lets a second mapper check the area, and a maintainer add it to the
calibration.

## Report your progress

Open a **[calibration area report](https://github.com/open-energy-transition/earthpv/issues/new?template=calibration-area.yml)**
on GitHub (free account). From the atlas it is quicker: the **Report progress** link in an
area's popup opens the form with the area and country filled in.

Report at any of these points; each is useful:

| status | when |
|---|---|
| Started | you begin an area, so nobody else duplicates the first pass |
| Finished | every visible panel inside the boundary is mapped |
| Second pass done | you re-checked someone else's finished area, independently |
| Not mappable | the imagery is too old or clouded, or the box holds nothing to map |
| Stopped part way | you cannot finish; the area is left out, no harm done |

Please include your OpenStreetMap username, the imagery you traced from with its capture
date, and your changesets (your OpenStreetMap profile lists them; they carry the hashtags
`#tracethesun` and `#earthpv-calibration`, which is also how we find them across every
country).

**"Not mappable" is a result, not a failure.** Recording it stops the next person from
trying the same box, and it keeps the set of finished areas honest: areas that survive only
where the imagery happened to be good would bias the calibration.

## The second pass

One person's "I mapped everything" becomes a calibration area only once a second mapper has
swept it independently. Pick a finished area (filled diamond on the atlas, or a report
marked *Finished*), open it the same way, sweep it on every imagery layer, add what is
missing, and report how many you added. That number is itself a measure of how complete the
first pass was.

## What happens next

1. A maintainer [registers the area](maintainers.md): its boundary goes into the pipeline
   and the solar you mapped is pulled from OpenStreetMap.
2. After the second pass, the area is declared complete (Rule 1) and enters the next fit of
   the small-installation classifier.
3. The country's atlas is rebuilt with it. Once a country has enough complete areas across
   its density range, its atlas gains an estimate of its small installations and moves up a
   tier.

You can follow this on the report itself. On the atlas, an area you finished turns from a
hollow into a filled diamond once it is registered and the country's atlas is rebuilt.
