# earthpv

<div class="hero" markdown>

![earthpv](assets/figures/earthpv-logo-mark.png#only-light){ .hero-logo }
![earthpv](assets/figures/earthpv-logo-mark-white.png#only-dark){ .hero-logo }

**Open, global photovoltaic mapping from free satellite imagery.**
{ .lede }

EarthPV demonstrates how free Sentinel-2 imagery, an open foundation model, and
human-in-the-loop validation in OpenStreetMap can make global photovoltaic mapping more
scalable, verifiable, and cost-effective than existing methods. Pakistan is the first
pilot, not the destination -- see [Scaling worldwide](#scaling-worldwide).

</div>

<div class="stats" markdown>
<div class="stat"><span class="value">18,280 MWp</span><span class="label">Pakistan pilot, best estimate (90% range 14,401 to 21,846)</span></div>
<div class="stat"><span class="value">8,616 / 7,890 MWp</span><span class="label">capacity &ge;400 m&sup2; (roofclf rooftop where calibrated, segmentation rooftop and ground-mount elsewhere) against &lt;400 m&sup2; from roofclf alone</span></div>
</div>

## Build PV capacity maps for every country

This project's primary output is the [Pakistan capacity map](index.md) -- Best estimate
by 0.1&deg; cell, interactive, updated with every pipeline run, and the first thing this
site shows. More countries join the **Capacity Maps** menu above as their own pipelines
are calibrated; see [Scaling worldwide](#scaling-worldwide) for the programme behind
that.

## What is new here

**The main workflow: two detectors, split by placement and calibration coverage, one
evidence atlas.** No single instrument sees rooftop solar from a commercial rooftop down
to a household system, so earthpv's default pipeline runs two, each measured against
ground truth, and combines them into this project's primary output. The split is **not**
a clean size boundary -- roofclf's reach now extends past its original sub-400
m<sup>2</sup> floor into large rooftops too, wherever it has been calibrated to do so:

- **Segmentation** outlines individual arrays **&ge;400 m<sup>2</sup>** directly -- a
  fine-tuned TerraMind reaching commercial rooftops and large residential arrays, where
  earlier work with free 10 m imagery could only find isolated solar farms. Every
  mapping lead comes from this model regardless of building size, and it remains the
  only instrument for ground-mount at any size, since roofclf has no building footprint
  to classify there.
- **roofclf**, cross-checked with **SPPI**, answers a different question: not "where is
  the polygon" but "does this *building* carry PV." **roofclf**, a per-building
  classifier trained on 23 exhaustively mapped ground-truth quadrats, reaches 0.857 AUC
  (0.830 with roof size controlled for), where the segmentation raster scores close to
  chance on the same small buildings -- it covers every rooftop **below** 400
  m<sup>2</sup>, where segmentation is trained blind. **SPPI**, a zero-training spectral
  index, reaches 0.823 AUC with no labels at all; requiring it to *agree* with roofclf
  raises measured precision on held-out quadrats, at the cost of recall. Segmentation's
  blind spot turns out to be *installation*
  size, not building size, so as of 2026-08-07 roofclf's own rooftop estimate (measured
  better, 0.896 AUC against segmentation's 0.73-0.78 on identical buildings) also
  **replaces** segmentation's rooftop total at or above 400 m<sup>2</sup> inside the
  cells its calibration quadrats cover -- outside those cells segmentation's own
  recall-corrected rooftop figure stays authoritative, since it is the only
  evidence-backed number there. See [The rooftop classifier](methods/roofclf.md) for how
  that instrument works end to end, and [Capacity density](methods/density.md) for what
  it adds up to.
- Both instruments converge on the **evidence atlas**: **Best estimate**, this project's
  own highest defensible figure, combining every installation hand-mapped in
  OpenStreetMap, the model's own recall-corrected detections, and roofclf/SPPI's
  per-building density estimate for small rooftops -- with the overlap between OSM and
  detections removed rather than double-counted, and a 90% range covering the conversion
  constants, the model's measured precision and recall, and how much the answer moves if
  a different set of quadrats had been mapped. Command sequence:
  [The full pipeline](reproduce.md#the-full-pipeline).

![Three instruments and the installation-size range each one covers, on a logarithmic area axis: aggregate density estimation from about 20 square metres upward, individual polygon detection from 400 square metres, and glint pose confirmation from 1000 square metres.](assets/figures/size_spectrum.svg#only-light)
![Three instruments and the installation-size range each one covers, on a logarithmic area axis: aggregate density estimation from about 20 square metres upward, individual polygon detection from 400 square metres, and glint pose confirmation from 1000 square metres.](assets/figures/size_spectrum.dark.svg#only-dark)

**Optional, supplementary instruments read the same imagery too**, each measured and each
kept whether or not it was promoted -- evidence toward the main workflow, a secondary
product, or a documented negative result, never a competing main path. **Glint** confirms
panels physically (a glass-fronted array flashes into Sentinel-2 only on the
geometry-predictable dates its tilt and azimuth bisect the sun and the sensor) and also
recovers [how the panel is mounted](results/pv-pose.md); it folds into the main workflow's
leads ranking as a boost-only signal, never required for the evidence atlas. **Growth**
diffs a pre-boom (2021/22) composite against the current one to show where capacity
actually appeared, not just where it stands today -- see [Growth](results/growth.md). A
fraction-head expected-area instrument, SPPI as a standalone detector, an older
Low/Central/High/All-PV bracket atlas and a rooftop potential/saturation atlas exist too.
A [Germany MaStR cross-check](methods/mastr-validation.md) tests the assumptions the whole
chain rests on against a legally complete register, and is why this project runs two
detectors rather than relying on segmentation alone. See [Experiments](experiments.md) for everything that was
tried and why these two detectors are what shipped, and
[Open questions](open-questions.md) for what is still unresolved.

**The map improves itself.** Detections go to mappers as a MapRoulette challenge;
verified installations come back as in-domain training labels. That
[flywheel](how-it-works.md#workflow) is the reason a model trained on Germany now works in Punjab.

**Nothing here is Pakistan-specific.** Every input is a global open dataset: Sentinel-2
for imagery, OpenStreetMap for labels, VIDA Open Buildings for footprints, geoBoundaries
for administrative areas. The model was trained in Germany before it was ever pointed at
Punjab, and it runs on a new country with nothing pre-downloaded. Three commands set an
area up, and the same pipeline follows -- see [Scaling worldwide](#scaling-worldwide).

## Scaling worldwide

Programme targets are **Mexico, Japan, Korea, Indonesia, India, Brazil, South Africa and
Nigeria**; Gujarat in India is already registered as a worked template. A first candidate
set in a new country needs no local training data at all -- the existing checkpoint runs
unchanged -- and what closes the domain gap afterwards is local mapping, which is why
[Setup a new country](reproduce.md#scale-to-a-new-country) starts by asking you to find a
mapping community before running anything.

## Where to go next

| If you want to | Read |
| --- | --- |
| See the capacity numbers and interrogate them | [Capacity map](results/capacity.md) |
| Understand the pipeline as it runs today | [How it works](how-it-works.md) |
| Know how detection and density actually work | [Detection](methods/detection.md), [Density](methods/density.md) |
| Check the method against a legally complete register | [Validation against MaStR](methods/mastr-validation.md) |
| See what was tried and what it cost, including the failures | [Experiments](experiments.md) |
| Know what is still unresolved before you cite a number | [Open questions](open-questions.md) |
| Help by mapping | [Mapping leads](results/leads.md), [Quadrat protocol](calibration-mapping-protocol.md) |
| Run the whole thing yourself, or bring it to another country | [Setup New Country](reproduce.md) |
| Join the effort | [Community](#community) |
| Read the one-page version | the [README](https://github.com/open-energy-transition/earthpv#readme) in the repository |

## Credits

earthpv is developed by [Open Energy Transition](https://openenergytransition.org) as part of
the **TraceTheSun** pilot, with four interns from the **Lahore University of Management
Sciences** doing the Pakistani mapping and validation work. See
[Community](#community) for the full partner list, and the
[TraceTheSun concept note](22072026-Concept-Note-TraceTheSun.md) for the programme behind it.

## Community

earthpv is the software half of **TraceTheSun**, a pilot programme run by
[Open Energy Transition](https://openenergytransition.org) to make photovoltaic mapping
cost-effective, verifiable, community-driven and local.

### The problem the community solves

Pakistan's installed solar capacity is reported anywhere between 6.8 GW officially and
47 GW by NGO estimates. That spread is not a measurement problem so much as a
**verifiability** problem. Existing mapping methods depend on commercial high-resolution
imagery that cannot be shared and that most licences forbid processing with AI. The
consequence is an environment where a single company with imagery access can publish a
distribution dataset that nobody else can reproduce, check or improve. Estimates get bought
again every year, and disagreement between them cannot be resolved.

Making the whole chain open changes the economics. Free imagery, an open model, open
training data and an open mapping platform mean the cost of the next update is close to
zero, the result can be argued about on the evidence, and the people who know the ground
can correct it.

### TraceTheSun

TraceTheSun is an emerging community bringing together the most prominent open-source
projects in PV detection and the most skilled PV mappers in OpenStreetMap, to address
tagging and mapping solar worldwide in an open, verifiable and cost-effective way.

Currently forming, it includes:

* **[Open Energy Transition](https://openenergytransition.org)**, which runs earthpv and
  funds the Pakistan pilot.
* **[Muhammad Awais](https://www.linkedin.com/in/awais307/)** of the **Lahore University of
  Management Sciences** in Pakistan, leading four OET-funded interns doing the Pakistani
  mapping, validation and local-context work that this project's Pakistani results rest on.
* **[Jake Stid](https://www.linkedin.com/in/jake-stid-38bb23131/)** of Michigan State
  University, creator of [GMSEUS](https://github.com/stidjaco/GMSEUS), with a regional
  focus on North America.
* **[Gabriel Kasmi](https://www.linkedin.com/in/gabriel-kasmi/)**, creator of
  [DeepPVMapper](https://github.com/gabrielkasmi/deeppvmapper).

### The Lahore University of Management Sciences pilot

The LUMS internship is what turned earthpv from a model into a workflow. The interns map
and verify Pakistani installations in OpenStreetMap against high-resolution imagery, add
local knowledge no satellite carries, and build the fully mapped
[ground-truth quadrats](calibration-mapping-protocol.md) that every recall number on this
site is measured against.

Their work is why the Pakistani model exists at all. Detection recall on Punjabi rooftops
went from 0.18 to 0.55 for large arrays purely by adding in-domain training chips that came
out of this loop, and the calibration boxes they map are currently the only instrument that
can tell whether the model's own recall estimate is optimistic.

### How to contribute

**Map.** The most valuable contribution is verified installations in OpenStreetMap. Load
the [mapping leads](results/leads.md) into MapRoulette or JOSM, check each against the
high-resolution layers, and map what is real. Tag conventionally
(`generator:source=solar`, or `power=plant` with `plant:source=solar`) so the next label
pull finds it.

**Map a quadrat.** Exhaustively mapping every installation inside a drawn boundary is worth
far more per hour than scattered mapping, because it measures what the model *misses* rather
than only confirming what it finds. 27 quadrats covering 79.9 km<sup>2</sup> exist so far;
the protocol is in [Quadrat mapping protocol](calibration-mapping-protocol.md).

The highest-value next quadrat is a **sparse rural** one. A quadrat only widens the
calibrated domain if its *own* average building density falls below the current floor, and a
boundary traced around a village never does, because it is the farmland between settlements
that pulls the average down. Sizing a box to include that open land on purpose is what took
the calibrated domain from 163 cells to 2,957 (most recently Nasirabad Rural,
2026-08-13, own density 48.5 bldg/km<sup>2</sup>).

**Review a calibration sample.** `earthpv calibrate-sample` emits a stratified sample of
unmapped candidates for human verdicts. Twenty verdicts in the 100 to 500 m<sup>2</sup> bin
would collapse the widest remaining term in the calibration table. Several random-cell
validation batches are also generated and waiting for review, which measures precision
against an unbiased population rather than the curated quadrats: see
[roofclf random-cell validation](methods/roofclf-national-validation.md).

**Run it somewhere new.** [Running on a new region](reproduce.md#running-on-a-new-region)
needs nothing pre-downloaded. Target countries for the programme are Mexico, Japan, Korea,
Indonesia, India, Brazil, South Africa and Nigeria.

**File what you find.** Issues and pull requests at
[open-energy-transition/earthpv](https://github.com/open-energy-transition/earthpv).

### What gets released

1. **Training data** for high-resolution, low-resolution and density estimation, under an
   open licence and, where possible, directly in OpenStreetMap.
2. **Models**, under an open licence, with all preprocessing, training and postprocessing
   code.
3. **Educational and capacity-building material** on building the pipeline end to end,
   including regional workflows, imagery and datasets.
4. **A fully reproducible capacity map**, combining human-verified installations, AI
   detections and estimated density, with the calibrations against import data, surveys and
   net-metered systems documented.

Long-term sustainability rests on keeping maintenance cost near zero and on empowering the
OpenStreetMap community to reuse the tools directly, with new leads pushed to volunteer
platforms such as Rapid, MapRoulette and StreetComplete.

### Licence

Code is MIT. Documentation and derived data are open; imagery comes from Copernicus
Sentinel-2, building footprints from VIDA Open Buildings and Overture Maps, labels from
OpenStreetMap contributors under ODbL, and administrative boundaries from geoBoundaries
under CC-BY.

The full programme description is in the
[TraceTheSun concept note](22072026-Concept-Note-TraceTheSun.md).
