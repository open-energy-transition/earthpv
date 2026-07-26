# Community

earthpv is the software half of **TraceTheSun**, a pilot programme run by
[Open Energy Transition](https://openenergytransition.org) to make photovoltaic mapping
cost-effective, verifiable, community-driven and local.

## The problem the community solves

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

## TraceTheSun

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

## The Lahore University of Management Sciences pilot

The LUMS internship is what turned earthpv from a model into a workflow. The interns map
and verify Pakistani installations in OpenStreetMap against high-resolution imagery, add
local knowledge no satellite carries, and build the fully mapped
[ground-truth quadrats](calibration-mapping-protocol.md) that every recall number on this
site is measured against.

Their work is why the Pakistani model exists at all. Detection recall on Punjabi rooftops
went from 0.18 to 0.55 for large arrays purely by adding in-domain training chips that came
out of this loop, and the calibration boxes they map are currently the only instrument that
can tell whether the model's own recall estimate is optimistic.

## How to contribute

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

## What gets released

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

## Licence

Code is MIT. Documentation and derived data are open; imagery comes from Copernicus
Sentinel-2, building footprints from VIDA Open Buildings and Overture Maps, labels from
OpenStreetMap contributors under ODbL, and administrative boundaries from geoBoundaries
under CC-BY.

The full programme description is in the
[TraceTheSun concept note](22072026-Concept-Note-TraceTheSun.md).
