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
<div class="stat"><span class="value">15,004 MWp</span><span class="label">Pakistan pilot, best estimate across every standard of proof</span></div>
<div class="stat"><span class="value">8,220 / 6,785 MWp</span><span class="label">capacity &ge;400 m&sup2; segmentation vs. <400 m&sup2; rooftop classifier </span></div>
<div class="stat"><span class="value">4</span><span class="label">independent detected methods: segmentation, roofclf, SPPI, glint</span></div>
</div>

## Build PV capacity maps for every country

![Pakistan's rooftop solar counted three times over: Verified (hand-mapped or two detectors agree), Best estimate (this project's own defensible figure), and Ceiling (an explicit uncalibrated upper bound), over a night-lights style map of estimated capacity per 0.1 degree cell concentrated in the Punjab corridor between Lahore, Faisalabad and Multan, along the Karachi industrial belt, and around Islamabad and Peshawar.](assets/figures/pakistan_evidence_atlas.png)

/// caption
Three tiers by standard of proof, not by point estimate, for every building carrying PV
signal in the pilot country. The
[interactive version](results/capacity.md) switches tiers and ranks provinces by each.
///

## What is new here

**Detection at every scale, not one model.** No single instrument sees rooftop solar from
utility-scale plants down to a household system, so earthpv runs four, each measured
against ground truth:

- **Segmentation** outlines individual arrays **&ge;400 m<sup>2</sup>** directly -- a
  fine-tuned TerraMind reaching commercial rooftops and large residential arrays, where
  earlier work with free 10 m imagery could only find isolated solar farms.
- **roofclf and SPPI** answer the question below that floor: not "where is the polygon"
  but "does this *building* carry PV." **roofclf**, a per-building classifier trained on
  exhaustively mapped quadrats, reaches 0.874 AUC on roofs under 500 m<sup>2</sup>, where
  segmentation scores 0.50. **SPPI**, a zero-training spectral index, reaches 0.823 AUC
  with no labels at all. See [Capacity density](methods/density.md).
- **Glint** confirms panels physically: a glass-fronted array flashes into Sentinel-2 only
  on the geometry-predictable dates its tilt and azimuth bisect the sun and the sensor, a
  confirmation independent of spectral appearance that also recovers
  [how the panel is mounted](results/pv-pose.md).
- **Growth** diffs a pre-boom (2021/22) composite against the current one -- with
  segmentation and SPPI each run independently on both epochs -- to show where capacity
  actually appeared, not just where it stands today. See [Growth](results/growth.md).

![Three instruments and the installation-size range each one covers, on a logarithmic area axis: aggregate density estimation from about 20 square metres upward, individual polygon detection from 400 square metres, and glint pose confirmation from 1000 square metres.](assets/figures/size_spectrum.svg#only-light)
![Three instruments and the installation-size range each one covers, on a logarithmic area axis: aggregate density estimation from about 20 square metres upward, individual polygon detection from 400 square metres, and glint pose confirmation from 1000 square metres.](assets/figures/size_spectrum.dark.svg#only-dark)

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
| See where solar capacity appeared since the pre-boom epoch | [Growth](results/growth.md) |
| Understand the workflow, architecture, methods and what's been tried | [How it works](how-it-works.md) |
| Know how detection and density actually work | [Detection](methods/detection.md), [Density](methods/density.md) |
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

**Map a quadrat.** Exhaustively mapping every installation inside a 1 km<sup>2</sup> box is
worth far more per hour than scattered mapping, because it measures what the model misses
rather than only confirming what it finds. The protocol is in
[Quadrat mapping protocol](calibration-mapping-protocol.md). Multan is the current highest
priority: confirmed solar-dense, with zero OpenStreetMap solar features today.

**Review a calibration sample.** `earthpv calibrate-sample` emits a stratified sample of
unmapped candidates for human verdicts. Twenty verdicts in the 100 to 500 m<sup>2</sup> bin
would collapse the widest uncertainty in the national capacity estimate.

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
