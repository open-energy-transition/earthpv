# Contribute

EarthPV estimates how much solar each country has installed, and the ground truth behind
those numbers is OpenStreetMap: solar panels that people have traced from aerial imagery.
The model finds candidates in free satellite imagery; people decide what they are. This page
shows how the two work together, the **mapping flywheel**, where you come in, and how each
turn moves a country's atlas from Bronze to Gold. None of it needs coding, and most of it
needs nothing but a browser.

## The mapping flywheel

![One turn of the mapping flywheel, drawn as six stage cards stacked from top to bottom, with an arrow on the left running from the last back to the first, labelled each turn starts from a more complete map and a more local model. 1, Detect from space, done by the model: the country's own model reads dry-season Sentinel-2 imagery and outlines every array of about 400 square metres and up, classifiers score the roofs and farm plots below that size, and solar glint across the scene archive confirms the larger installations; it hands on model outlines of every size and builds Bronze and Gold. 2, Publish the atlas, done by the model: Verified and Best capacity per 0.1 degree cell with a 90 percent range, the leads people have judged solar and calibration areas to map; it builds Bronze. 3, Check the leads, done by people, in two parts. First, judge on a review page, on your own PC: one picture per outline of 1 hectare and up, keys 1 solar, 2 not solar, 3 unsure, 4 bright roof; the verdicts are counted at the next rebuild, shown by a dashed amber arrow straight back to stage 2, and outlines judged solar go into the confirmed-lead file. Second, map in JOSM or iD: the confirmed leads, largest first, each one judged solar by a person. Stage 3 hands on a third of the large leads checked and builds Silver. 4, Map calibration areas, done by people in iD or JOSM: every visible panel inside a 1 to 3 kilometre box; it builds Silver and Gold. 5, Find local datasets, done by people in a browser: a register, statistics or a study, drawn beside the atlas, and a complete register calibrates it; it builds Gold. 6, Retrain and recalibrate, done by the model and a maintainer: the model is fine-tuned again on the country's OpenStreetMap solar and complete areas refit the small-installation estimate, which people then check on random cells; it builds Silver and Gold. On the right, a tall OpenStreetMap panel receives teal arrows marked mapped from stage 3's mapping and from stage 4, and sends teal arrows out to stage 2, marked counted, and to stage 6, marked labels.](../assets/figures/mapping_flywheel_stages.svg#only-light)
![One turn of the mapping flywheel, drawn as six stage cards stacked from top to bottom, with an arrow on the left running from the last back to the first, labelled each turn starts from a more complete map and a more local model. 1, Detect from space, done by the model: the country's own model reads dry-season Sentinel-2 imagery and outlines every array of about 400 square metres and up, classifiers score the roofs and farm plots below that size, and solar glint across the scene archive confirms the larger installations; it hands on model outlines of every size and builds Bronze and Gold. 2, Publish the atlas, done by the model: Verified and Best capacity per 0.1 degree cell with a 90 percent range, the leads people have judged solar and calibration areas to map; it builds Bronze. 3, Check the leads, done by people, in two parts. First, judge on a review page, on your own PC: one picture per outline of 1 hectare and up, keys 1 solar, 2 not solar, 3 unsure, 4 bright roof; the verdicts are counted at the next rebuild, shown by a dashed amber arrow straight back to stage 2, and outlines judged solar go into the confirmed-lead file. Second, map in JOSM or iD: the confirmed leads, largest first, each one judged solar by a person. Stage 3 hands on a third of the large leads checked and builds Silver. 4, Map calibration areas, done by people in iD or JOSM: every visible panel inside a 1 to 3 kilometre box; it builds Silver and Gold. 5, Find local datasets, done by people in a browser: a register, statistics or a study, drawn beside the atlas, and a complete register calibrates it; it builds Gold. 6, Retrain and recalibrate, done by the model and a maintainer: the model is fine-tuned again on the country's OpenStreetMap solar and complete areas refit the small-installation estimate, which people then check on random cells; it builds Silver and Gold. On the right, a tall OpenStreetMap panel receives teal arrows marked mapped from stage 3's mapping and from stage 4, and sends teal arrows out to stage 2, marked counted, and to stage 6, marked labels.](../assets/figures/mapping_flywheel_stages.dark.svg#only-dark)

Every country turns the same wheel. The model does stages 1, 2 and 6, and **you come in at
3, 4 and 5**. Whatever you map goes into OpenStreetMap, where the next atlas counts it and
the next model learns from it; a verdict on a review page counts even before anyone maps
the outline. Each turn starts from a more complete map and a more local model.
[How it works](../how-it-works.md#workflow) describes the machinery behind each stage.

### Where to start

| you have | do this | guide |
|---|---|---|
| a browser and ten minutes | map a few of a country's confirmed leads in iD | [Map the leads in iD](leads.md#a-few-leads-in-id) |
| an evening and JOSM | work through a country's confirmed leads with the Todo list | [Map the leads with JOSM](leads.md#2-set-up-josm-and-the-three-plugins) |
| a few evenings | map a calibration area completely, starting at the star | [Map a calibration area](calibration-areas.md) |
| EarthPV running on your PC | judge the solar farms on Sentinel-2 and review the large installations in JOSM | [Check large installations](review.md) |
| knowledge of your country | point us to its register, statistics or a study | [Share a local dataset](local-data.md) |
| an NVIDIA or AMD graphics card | build the first atlas for a country that has none | [Build an atlas on your PC](new-atlas.md) |

None of these needs the others first, and every one of them counts.

## The stages

### 1. Detect from space

*Done by the model.* Each country's own segmentation model, fine-tuned on that country's
OpenStreetMap solar, reads dry-season Sentinel-2 imagery and outlines every array it can
see: reliably from about 400 m<sup>2</sup> up, the size at which an array fills enough
10 m pixels to have a shape. Below that, a rooftop classifier scores each building, and
where farm areas calibrate it, a pixel detector looks for small arrays beside the fields.
Sentinel-2's archive also catches **solar glint**, the sun's reflection off a panel on the
few dates when sun, panel and satellite line up, which confirms large installations
independently of the model and of the mappers and measures how their panels are mounted
([Solar glint](../methods/glint.md)). Nothing found here is
trusted yet: an outline is a candidate until a person has looked at it.

### 2. Publish the atlas

*Done by the model.* Each [country atlas](../atlas.md) shows *Verified*, the solar mapped in
OpenStreetMap alone, and *Best*, which adds the model's outlines, each priced by how often
outlines of its size turn out to be real, with a 90% range. The map draws the candidate
calibration areas for stage 4, a star on the one to start with, and the *Download* section
links the **confirmed leads** for stage 3: outlines the model drew more than 100 m from any
solar in OpenStreetMap that a person has since judged solar on a review page, largest first,
in `<country>_pv_confirmed_leads.geojson`. Every one is a real installation waiting to be
traced. The model's other outlines are not handed to mappers: drawn from 10 m pixels and
unchecked, many are false alarms, so they go to the reviews first. A country has a
confirmed file once someone has judged its review pages.

### 3. Check the leads

*Done by people.* A lead is checked when a person has looked at it and either mapped the
installation in OpenStreetMap or found it not solar. There are two ways in, and the first
feeds the second.

**Check the large outlines.** If you run EarthPV on your own PC, building an atlas or keeping
one current, every country's run sets up two reviews. A verdict EarthPV uses rests on free
Sentinel-2 imagery or is an installation mapped in OpenStreetMap: the high-resolution
imagery in Google, Bing, Esri and Mapbox may be used for tracing into OpenStreetMap, not for
checking EarthPV's figures.

| review | what it holds | how | what it changes |
|---|---|---|---|
| **Solar farm review** | outlines above 100,000 m<sup>2</sup> (10 ha) | on a page of three Sentinel-2 pictures per outline, the imagery the model saw | nothing this size counts until it is mapped or a person judges it solar; each park you confirm is added whole |
| **Large installation review** | leads from 10,000 m<sup>2</sup> (1 ha) up to 10 ha, on roofs and on the ground | in JOSM, mapping the real ones into OpenStreetMap | these already count at the share their size usually turns out real; one you map counts from the map, at its real shape |

On the solar farm page, press <kbd>1</kbd> for solar, <kbd>2</kbd> for not solar,
<kbd>3</kbd> for unsure and <kbd>4</kbd> for a bright roof (not solar, kept apart so those
false alarms can be studied). Then:

1. **Export** your verdicts from the page, and apply them under your name. Any named
   reviewer's verdict counts, and your name is kept beside each one:

    ```bash
    pixi run blob-review apply --aoi YOUR_AOI --reviewer "Your name" \
        --verdicts YOUR_AOI_blob_verdicts.csv
    ```

2. **The atlas counts them** when the country is next rebuilt: parks judged solar are
   added, outlines judged not solar drop out.
3. **Mappers get what you confirm.** When the lead files are next made, every outline judged
   solar that OpenStreetMap still lacks moves to the country's **confirmed-lead file**, the
   only lead file the atlas offers mappers, and every one judged not solar is dropped for
   good.

A verdict takes a few seconds and is the quickest way to make an atlas right where it matters
most, at its largest installations. How often a large outline is solar differs by country
more than by anything else: of the large installations judged so far, 543 of 548 were solar
in the Netherlands and 83 of 842 in Texas. For the large installations, open the country's
JOSM review layer, map the solar that is there and mark a lead with none `not_pv`; what you
map counts from the map. [Check large installations](review.md) has the whole guide.

**Map the confirmed leads in JOSM or iD.** Open the country's confirmed-lead file from its
atlas and work through it, largest first. Find each installation on high-resolution imagery,
trace what is really there, and never copy the model's outline. Leads carry no completeness rule: map
as many as you like. Each installation you add is counted at the next rebuild, and becomes a
training example for the country's own model in stage 6.
[Map the leads with JOSM](leads.md) walks through it with the OpenData, Todo list and
continuous download plugins.

**How far to go.** Every confirmed lead is a real installation, so a confirmed file is worth
finishing. Tell us how far you got in an
[issue](https://github.com/open-energy-transition/earthpv/issues), naming the
`candidate_id` of the last lead you mapped.

### 4. Map calibration areas

*Done by people.* Below 400 m<sup>2</sup> no lead finds an array, so the small-installation
estimate is fitted on calibration areas instead: boxes of 1 to 3 km where **every** visible
panel is mapped, down to the smallest rooftop unit. A half-mapped area is worse than none,
because it teaches the calibration that the model overcounts; if you cannot finish one,
[say so](report.md) and it is left out. Six to ten complete areas, from sparse villages to
dense city centres, start a country's calibration.
[Map a calibration area](calibration-areas.md) shows how to pick one on the atlas and open
it in [iD](id.md) or [JOSM](josm.md), and [Report and verify](report.md) how to hand it in.

### 5. Find local datasets

*Done by people.* Most countries already count some of their solar: a register, a
statistics office, a regulator's net-metering list, a study. Each one is drawn beside the
atlas, and a legally complete, geolocated register can calibrate the small installations
the way Germany's does. [Share a local dataset](local-data.md) says what is useful and how
to send it.

### 6. Retrain and recalibrate

*Done by the model and a maintainer.* Mapped installations come back in the next pull from
OpenStreetMap. The country's model is fine-tuned again on them and ships only if it does at
least as well as the general model on a part of the country held back for the test. New complete areas refit
the small-installation estimate. The next turn of stage 1 starts from both
([Register an area](maintainers.md) is the maintainers' side).

## How a country moves up

Every atlas carries a badge, **Bronze**, **Silver** or **Gold**. It says how far its figures
have been checked by people, not how much solar a country has, and it rises as the wheel
turns:

| level | what it means | what gets a country there | stages |
|---|---|---|---|
| **Bronze** | the wheel is set up | a model trained on the country's own OpenStreetMap solar, the mapped solar counted once, the model's large outlines priced by measured precision, blobs counted only once checked, and the mapping leads drawn up | 1, 2 |
| **Silver** | the wheel has turned once | local ground truth (the country's mapped installations as a reference, or complete calibration areas in use), **and** a third of the leads of 1 ha and up reviewed in JOSM and a third of the blobs judged on Sentinel-2, the real ones mapped, followed by a retrain of the model on the result | 3, 6, and 4 |
| **Gold** | the wheel reaches below 400 m<sup>2</sup> | installations below 400 m<sup>2</sup> estimated from complete calibration areas across the density range or a complete national register, the estimate holding up when each area is left out in turn, people checking the rooftop classifier's results on cells drawn at random and on its score for every building, and solar glint measured from space on at least a third of the installations of 1 ha and more mapped in OpenStreetMap (never fewer than 100, and 1,000 suffice) | 4 or 5, then 6, and 1 |

The levels add up: Silver needs everything Bronze has, and Gold everything Silver has. So
the quickest way to move a Bronze country up is stage 3, judging and mapping its leads; the
way to Gold is stage 4, complete calibration areas, or stage 5, a register. Each country's
badge, and what it still lacks, is in the corner of its atlas; every criterion is on
[Quality levels](../atlas-quality-levels.md).

## Help from an LLM assistant

You do not have to work any stage alone. An LLM assistant (a chat assistant, or a coding
agent such as Claude Code in a copy of this repository) is good at the parts around the
mapping: explaining a JOSM or iD step, a plugin error or a validator warning; which tags a
rooftop array, a solar water heater or a fenced park takes; finding and reading a
country's register or statistics; and running the pipeline, for which the repository is
written to be read by an agent, with `CLAUDE.md` as its brief and a
[runbook for agents](../reproduce.md#running-this-with-claude-or-another-coding-agent).

What it must not do is the part only a person can vouch for. **Never let an assistant edit
OpenStreetMap**, draw geometry for upload, judge an outline on a review page or decide that
an area is complete: you trace every panel and give every verdict yourself, from imagery
you have looked at, and OpenStreetMap's
[Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct)
applies to anything else. The same line runs through EarthPV itself: an assistant prepares
candidate areas, review pages and first readings, and a person makes every call that puts
evidence into an estimate.

## New to OpenStreetMap editing?

You do not need to learn everything first. The [iD guide](id.md) is enough for a first lead
or area. For JOSM, Open Energy Transition's [MapYourGrid](https://mapyourgrid.org/) campaign
has the [JOSM Starter-Kit](https://mapyourgrid.org/starter-kit/#josm-starter-kit); it maps
power lines rather than panels, but the editor skills are the same. The complete rules
(what counts as PV, how to trace it, imagery dating, QA) are in the
[mapping protocol](../calibration-mapping-protocol.md).
