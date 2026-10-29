# Contribute data

EarthPV estimates how much solar is installed in a country, and the ground truth behind
those numbers is OpenStreetMap: solar panels that volunteers have traced from aerial
imagery. Every panel you add makes the estimate better, and you can do it from your
browser. No coding, no data download, no install if you use iD.

![A JOSM window over eastern Lahore. Thousands of small yellow polygons, one per mapped rooftop PV installation, fill two neighbourhoods so densely that the street grid shows through them, and the mapped area stops sharply along a ring road and a railway line, beyond which identical-looking suburbs carry almost no yellow.](../assets/figures/josm-calibration-region-lahore.jpg)

*A finished calibration area in Lahore. Inside the boundary every visible panel is mapped;
outside it nothing is, and the two look the same on imagery. That guarantee is what makes
an area useful, and it stops exactly at the line.*

## What your mapping changes

**Every installation you map is counted.** Each country's atlas adds the solar mapped in
OpenStreetMap to its estimate, at the size you drew it, the next time the country is
rebuilt.

**A complete area calibrates a whole country.** From space, the model reliably sees only
arrays of roughly 400 m<sup>2</sup> and up. Household and small commercial systems, often
most of a country's solar, are estimated by a second instrument that has to be fitted on
small areas where **every** panel is mapped: calibration areas. That is what the atlas
tiers mean:

| tier | what it has | what it needs |
|---|---|---|
| Gold | small installations estimated, calibrated on complete areas or a national register | more areas in the density bands it does not yet cover |
| Silver | large installations only, checked against local ground truth | small-installation calibration that works for its roof sizes |
| Bronze | large installations only, nothing local to check against | its first complete calibration areas |

Six to ten complete areas, spread from sparse villages to dense city centres, are enough to
start calibrating a country. Each one counts.

## The one rule: map everything inside the line

> A calibration area is only usable once **every visible panel inside it** is in
> OpenStreetMap, down to the smallest rooftop unit. A half-mapped area is worse than an
> unmapped one: it silently teaches the calibration that the model overcounts.

If you cannot finish an area, that is fine: [say so](report.md) and it is simply left out.
What matters is never declaring an area complete when it is not.

## How it works

1. **Pick an area on the atlas.** Open a country's atlas from the [PV Atlas](../atlas.md)
   tab. Hollow diamonds are candidate areas nobody has mapped yet, and a **star** marks the
   one to start with (the *Start here* button under the map takes you to it); filled
   diamonds are finished areas, which still welcome a second check. Click one.

    ![Zambia's atlas over satellite imagery of the town of Chipata, with a candidate area's popup open above its hollow diamond. The popup reads Candidate area, not yet mapped, and lists 59 buildings per square kilometre in the box, density stratum 5 of 8, Esri imagery from 2024-12-01 and an area of 4 square kilometres, followed by a short note and the buttons Open in JOSM, Open in iD and GeoJSON, and the links How to map a calibration area and Report progress. The dashed edges of the 2 km box are visible below the popup.](../assets/figures/contribute-atlas-candidate-popup.jpg)

    *A candidate in Zambia. Everything you need to start is in the popup.*

2. **Open it in your editor.** **Open in iD** starts the browser editor;
   **Open in JOSM** sends the area to the desktop editor. Both load the area's exact
   boundary next to the OpenStreetMap data, and both keep the boundary out of your upload.
3. **Check the imagery.** The popup shows when the satellite imagery was captured. If it is
   much older than a year, or the box holds nothing to map, [report it](report.md) as not
   mappable instead of mapping it.
4. **Map every solar panel inside the boundary**, flipping between imagery layers as you go.
   The guides below show how, step by step.
5. **Upload.** The changeset comment and the hashtags `#tracethesun #earthpv #earthpv-calibration` are
   already filled in.
6. **[Report it](report.md)**, so a second mapper can check it and we can add it to the
   calibration.

## Which editor?

| | [iD](id.md) | [JOSM](josm.md) |
|---|---|---|
| install | none, runs in the browser | desktop application (Java) |
| the boundary | read-only overlay, never uploaded | locked layer that refuses upload |
| good for | your first area; sparse candidates with a few hundred buildings | dense areas with thousands of buildings; second passes |
| imagery | Esri, Bing, Mapbox and regional layers | the same, plus filters and paint styles for checking |

Both need a free [OpenStreetMap account](https://www.openstreetmap.org/user/new).

## Where help is needed

Every Bronze country has ten candidate areas, each with Esri imagery recent enough for that
country's satellite data: eight drawn at random across its building-density range rather than
picked by hand, and two start-here boxes in its densest districts with the most large roofs
([how they were chosen](../calibration-mapping-protocol.md#automated-quadrat-selection)).
Pakistan has eight more aimed at the sparse end of its calibration. Yemen, Silver since its
farm areas, has ten town boxes where panels show on rooftops, for its rooftop classifier.

| country | tier | open candidates | box density (bldg/km<sup>2</sup>) | start here (&#9733;) |
|---|---|---:|---|---|
| [Egypt](../atlas-egypt.md) | Bronze | 10 | 150 to 1,085 | Qalyub, Qalyubia |
| [India](../atlas-india.md) | Bronze | 9 | 78 to 2,946 | Surat, Gujarat |
| [Morocco](../atlas-morocco.md) | Bronze | 10 | 36 to 954 | Tangier-Assilah |
| [Nigeria](../atlas-nigeria.md) | Bronze | 10 | 39 to 2,291 | Ikeja, Lagos |
| [South Africa](../atlas-south-africa.md) | Bronze | 10 | 34 to 2,360 | Ekurhuleni, Gauteng |
| [Vietnam](../atlas-vietnam.md) | Bronze | 10 | 106 to 4,196 | Binh Chanh, Ho Chi Minh City |
| [Zambia](../atlas-zambia.md) | Bronze | 10 | 12 to 1,084 | Lusaka |
| [Pakistan](../atlas.md) | Gold | 8 | 54 to 124 (region) | |
| [Yemen](../atlas-yemen.md) | Silver | 12 | 34 to 2,123 | Yafi', Lahij |
| [France](../atlas-france.md) | Silver | none | map any solar you can see | |

**Start at the star.** On a Bronze atlas the candidates are numbered in mapping order: the
start-here boxes first, in the densest districts with the most large roofs, then the sampled
ones from the densest down. Dense districts with large roofs are where solar is most likely,
so a first area there has panels to find and gives the country's calibration its first
positives. The sparse candidates come later and still matter: a calibration only reaches as
far down in density as its sparsest complete area, and they are the quickest to finish.
Yemen's star is chosen by hand instead: of its ten town boxes, Yafi' shows the most panels on
Esri imagery.

Want to suggest an area of your own? The **Propose a calibration area** button on the atlas
(the dashed square under the zoom buttons) drops a 2 km square where you click and checks
it against every existing area. Place it by landscape, never because you can already see
solar there: a sample chosen for its panels is biased before anyone maps it. An area does
not have to be a square: [Draw your own area](draw-area.md) shows how to outline one in JOSM
and send it in as GeoJSON.

## New to OpenStreetMap editing?

You do not need to learn everything first. The [iD guide](id.md) is enough for a first
area. For JOSM, Open Energy Transition's [MapYourGrid](https://mapyourgrid.org/)
campaign has the material already:
[installing JOSM](https://mapyourgrid.org/installation-instructions/), the
[JOSM Starter-Kit](https://mapyourgrid.org/starter-kit/#josm-starter-kit) and its
[Strategies](https://mapyourgrid.org/strategies/) page (filters, `fixme` notes and
pre-upload validation all apply here unchanged). It maps power lines rather than panels, but
the editor skills are the same.

The complete rules (what counts as PV, how to trace it, imagery dating, QA) are in the
[mapping protocol](../calibration-mapping-protocol.md). Maintainers registering areas in the
pipeline: see [Register an area](maintainers.md).
