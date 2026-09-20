---
hide:
  - navigation
---
# EarthPV

<div class="hero hero--lockup" markdown>

<div class="hero-mark" markdown="0">
  <img src="assets/figures/earthpv-logo-mark.png#only-light" alt="" width="512" height="512">
  <img src="assets/figures/earthpv-logo-mark-white.png#only-dark" alt="" width="512" height="512">
</div>

<div class="hero-copy" markdown>

**Mapping every solar system above 10 kWp worldwide: capacity, growth and
orientation, open and verifiable**
{ .lede }

</div>

</div>

**How small? EarthPV finds most rooftop PV above roughly 50 m² of panel, about
10 kWp. Between 20 and 50 m² it is close to a coin flip, and below that it misses most
of what is there.**
[What that is measured on](#how-small-an-installation-does-it-find)
{ .lede }

**Mapping a country we have not reached?** EarthPV is built to be forked per country
and merged back: the aim is a global PV evidence atlas assembled from many countries,
each run and verified by people who know the ground.
[Fork it and add yours](reproduce.md#contribute-your-country-atlas-back)
{ .lede }

!!! warning "Active development"
    EarthPV is still a research prototype. It is actively experimenting with new solar
    detection methods, and its detectors, calibration and headline numbers are still being
    tested and revised rather than settled.

EarthPV fine-tunes the open **TerraMind** geospatial foundation model, developed by IBM and ESA and accessed through TerraTorch, using **Sentinel-2** imagery. Sentinel-2 provides free, global coverage with imagery refreshed every five days. Each model detection is then presented to **OpenStreetMap** mappers for verification, and the verified results are fed back into subsequent rounds of training. The model, code, training labels, and capacity estimates are all openly available, and every input is derived from globally accessible datasets. As a result, the approach does not depend on imagery, proprietary licences, or data sources that are restricted to any single country.

**Pakistan is the first pilot, not the destination.** It is where four methods below were
built and measured; the plan is to run the same pipeline everywhere Sentinel-2 flies. See
[Scaling worldwide](#scaling-worldwide).

[![The EarthPV evidence atlas: Pakistan's rooftop solar capacity, best estimate 18,827 MWp (90 percent range 16,022 to 24,358) -- a night-lights style map of estimated capacity per 0.1 degree cell concentrated in the Punjab corridor and the Karachi industrial belt.](assets/figures/pakistan_evidence_atlas.png)](results/capacity.md)

*This project's own highest defensible figure, not a bare point estimate: hand-mapped
OpenStreetMap installations, the model's own recall-corrected detections, and a
per-building density estimate for small rooftops, with a 90 percent range attached.
[Open the interactive version](results/capacity.md).*

## How small an installation does it find?

Orders of magnitude, not thresholds. Measured on 30 exhaustively hand-mapped Pakistani
calibration areas (123,898 buildings), at the same operating point the published atlas
uses, binned by how much panel actually sits on the roof:

| Panel area on the roof | Roughly | Found |
| --- | --- | --- |
| Above 100 m² | above 20 kWp | 92% rising to over 99% |
| 50 to 100 m² | 10 to 20 kWp | 83% |
| 20 to 50 m² | 4 to 9 kWp | 49% |
| Below 20 m² | below 4 kWp | 22 to 31% |

**In one line: EarthPV finds most rooftop PV above roughly 50 m² of panel, call it 10 kWp,
is close to a coin flip between 20 and 50 m², and misses most of what is smaller.**

Four things qualify that, and they matter more than the exact percentages.

**It is recall-first, not precision-first.** At the same operating point roughly 1 in 10
PV-free buildings is also flagged. Detections are mapping leads meant for human
verification in OpenStreetMap, not a finished inventory.

**Individual panel outlines have a higher floor than the per-building answer.** The
segmentation detector, which is what produces an actual polygon and the only instrument
for ground-mount at any size, targets arrays of about 400 m² and above, near 70 kWp. The
table above is the per-building classifier, which answers "does this roof carry PV" rather
than "where exactly".

**The numbers above need a mapped calibration area in the same country.** They come from
Pakistan, which has 30 of them. A country with a complete public register can substitute
that register; a country with neither gets the segmentation half only.

**Whether any of this transfers is set by national subsidy design, not by geography.** In
France the median mapped rooftop array is 20 m² against Sentinel-2's 100 m² pixel, and the
same pipeline recalls about 1% of installations while the roof classifier does not transfer
at all. A sub-metre-imagery reference reads those same French installations at 67% with no
size gradient, which places the limit in the sensor rather than in the method. Across the
France-Germany border, array size steps by roughly 2x at the line while staying flat for
60 km either side of it. So the question "will this work in my country" is a question about
the size distribution of its installations, and it cannot be answered from a neighbour.

For context on why the small end is worth the trouble at all: Germany's legally complete
register shows **65.5% of rooftop capacity sits below the 400 m² segmentation floor**, in
97.2% of installations by count. An instrument that only saw large arrays would be blind to
about two thirds of the capacity a "rooftop solar" headline implies.

## How it works: two detectors, one atlas

At Sentinel-2's 10 m resolution a large array has a shape you can trace and a small one
does not, so EarthPV runs two instruments and combines them.

- **Segmentation** outlines individual arrays above roughly 400 m². These are the mapping
  leads, and the only instrument for ground-mounted solar at any size.
- **`roofclf`** answers a smaller question for everything below that floor: *does this
  building carry PV?* A 100 m² array is a handful of mixed pixels, too few to outline but
  often enough to classify.

Both are calibrated against small areas where every installation has been hand-mapped, then
combined into the evidence atlas, de-duplicated against OpenStreetMap and each other.

![The evidence atlas workflow: Sentinel-2 imagery, OpenStreetMap solar mapping and VIDA building footprints feed two detectors, TerraMind segmentation for arrays of 400 square metres and above plus all ground-mount, and the per-building roofclf classifier cross-checked with SPPI. Both are calibrated against 30 hand-mapped ground-truth quadrats, then combined one best instrument per component with overlaps removed and each cell floored at hand-mapped OSM plus roofclf-and-SPPI agreement, producing the published evidence atlas: Best estimate 18,827 MWp with a 90 percent range of 16,022 to 24,358.](assets/figures/evidence_workflow.svg#only-light)
![The evidence atlas workflow: Sentinel-2 imagery, OpenStreetMap solar mapping and VIDA building footprints feed two detectors, TerraMind segmentation for arrays of 400 square metres and above plus all ground-mount, and the per-building roofclf classifier cross-checked with SPPI. Both are calibrated against 30 hand-mapped ground-truth quadrats, then combined one best instrument per component with overlaps removed and each cell floored at hand-mapped OSM plus roofclf-and-SPPI agreement, producing the published evidence atlas: Best estimate 18,827 MWp with a 90 percent range of 16,022 to 24,358.](assets/figures/evidence_workflow.dark.svg#only-dark)

Full detail, including the optional glint and growth instruments and everything that was
tried and rejected: [How it works](how-it-works.md).

## Why free imagery, when sharper imagery exists

Two licences pull in opposite directions, and the loop is what resolves them. Sentinel-2 is
free, global and coarse. Esri, Bing and Mapbox resolve individual panels but only allow a
**person** to trace from them inside the OpenStreetMap editor.

So the machine only ever reads Sentinel-2, people only ever read the high-resolution
layers, and the installations they map become ordinary, openly licensed OpenStreetMap
features: legitimate training data for the next model.

![The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.](assets/figures/osm_ai_flywheel.svg#only-light)
![The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.](assets/figures/osm_ai_flywheel.dark.svg#only-dark)

The consequence is that the cost of the next update is close to zero, and anyone can
reproduce, check or improve the result.

## Where it runs

Every atlas carries an **EarthPV Validation Score** saying what evidence is actually under
it. Gold means the sub-400 m² half is calibrated against hand-mapped ground truth; Silver
means above the floor only, validated locally; Bronze means above the floor only, without
local validation, and should be read as a floor rather than an estimate.

| Country | Score | Atlas |
| --- | --- | --- |
| Pakistan | Gold | [Pakistan PV atlas](atlas.md) |
| Germany | Gold | [Germany PV atlas](atlas-germany.md) |
| France | Silver | [France PV atlas](atlas-france.md) |
| Zambia | Bronze | [Zambia PV atlas](atlas-zambia.md) |
| Gujarat, India | Bronze | [Gujarat capacity map](results/gujarat.md) |

Nothing in the pipeline is country-specific. All four inputs are global open datasets:

| Input | Source | Coverage |
| --- | --- | --- |
| Imagery | Copernicus Sentinel-2 L2A | global, every five days, free |
| Labels | OpenStreetMap, live Overpass or Overture | global, wherever mappers have been |
| Footprints | VIDA Open Buildings | global, imagery-derived |
| Boundaries | geoBoundaries, CC-BY | global, ADM1 and ADM2 |

Programme targets are Mexico, Japan, Korea, Indonesia, India, Brazil, South Africa and
Nigeria. Bringing up a country that has never been touched takes three commands, the first
read-only: [Setup a new country](reproduce.md).

## Pakistan, the pilot

Pakistan's installed solar capacity is reported anywhere between
[6.8 GW officially and 47 GW by NGO estimates](https://ember-energy.org/latest-insights/the-solarisation-of-pakistans-energy-economy/).
Nobody can check those numbers, because the maps behind them rest on commercial imagery
that cannot be shared. EarthPV's own figures:

| | |
| --- | --- |
| **18,827 MWp** | Best estimate, this project's highest defensible figure (90% range 16,022 to 24,358) |
| **15,642** | individual installations hand-mapped in OpenStreetMap |
| **400 m²** | the floor below which segmentation is blind, and `roofclf` takes over |
| **65.5%** | of Germany's rooftop capacity sits *below* that floor, measured against its complete register |

The range is deliberately wide: recalibration has repeatedly moved the estimate by 20 to
35% within days. It is **not** a design-based margin of error, because the calibration
areas are hand-picked rather than randomly sampled.

**This is a screening and estimation layer, not a register.** No human has validated most
of it at scale. How the estimate is derived and what it does not claim:
[Capacity map](results/capacity.md).

## What did not work

Most of what was tried here failed, and the negative results are documented because they
map where the 10 m resolution limit actually is: band stacking, Sentinel-1 corner
reflection, two routes from glint to density, roof-axis orientation priors, three
super-resolution variants, spectral unmixing, and two retrains that won in-sample and lost
on held-out data. Every one has runnable code in `scripts/`.

The register with a verdict and the measurement behind each:
[Experiments](experiments.md). What is still undecided:
[Open questions](open-questions.md).

## Where to go next

| If you want to                                               | Read                                                                                   |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| Understand the pipeline as it runs today                     | [How it works](how-it-works.md)                                                         |
| Know how detection and density actually work                 | [Detection](methods/detection.md), [Density](methods/density.md)                         |
| Check the method against a legally complete register         | [Validation against MaStR](methods/mastr-validation.md)                                 |
| See what was tried and what it cost, including the failures  | [Experiments](experiments.md)                                                           |
| Know what is still unresolved before you cite a number       | [Open questions](open-questions.md)                                                     |
| Help by mapping                                              | [Mapping leads](results/leads.md), [Quadrat protocol](calibration-mapping-protocol.md)   |
| Run the whole thing yourself, or bring it to another country | [Setup New Country](reproduce.md)                                                       |
| Join the effort                                              | [Community](#community)                                                                 |
| Follow updates, method notes and field reports               | [Blog](blog/index.md)                                                                   |
| Read the one-page version                                    | the[README](https://github.com/open-energy-transition/earthpv#readme) in the repository |

## Credits

EarthPV is developed by [Open Energy Transition](https://openenergytransition.org) as the
software half of the **TraceTheSun** pilot. The concept was conceived by
[Muhammad Awais](https://www.linkedin.com/in/awais307/) and Tobias; the Pakistani mapping,
validation and ground-truth work is carried out by a student team at the
[Centre for Water Informatics and Technology (WIT)](https://wit.lums.edu.pk/), Lahore
University of Management Sciences, working in close coordination with Open Energy
Transition. See [Community](#community) for the full contributor list, including every
named student mapper, and the
[TraceTheSun concept note](22072026-Concept-Note-TraceTheSun.md) for the programme behind it.

## Add your country: the atlas is meant to be collective

**The goal is a global PV evidence atlas assembled from many countries, each run and
verified by people who know the ground.** Nothing in this pipeline is Pakistan-specific:
every input is a global dataset, so the intended shape of the project is a fork per country
and this repository as the place their results come back together. Pakistan, Germany,
France, Gujarat and Zambia are the first five, not the destination.

What is not built yet, stated plainly: **there is no combiner that merges countries into one
global surface.** What exists is a shared pipeline, a shared atlas format and a shared data
pack layout, which is what makes that step possible later.

The short version of contributing one:

1. Fork the repository and branch as `atlas/<country>`.
2. Preflight and register the area with `scripts/new_region.py`, which prints your runbook.
3. Run the pipeline. Every stage is resumable; `compose` is the long pole. A country with
   mapped calibration areas gets the full two-detector atlas, one with a complete public
   register can substitute that register, and one with neither gets a segmentation-only
   atlas, which is a real result.
4. Draw 20 random cells and check them against high-resolution imagery. This step cannot be
   skipped or automated, and without it a number has no evidence under it.
5. Package the raw numbers with `scripts/build_atlas_data_pack.py`. The per-cell capacity
   table is the product; because `data/` is gitignored it ships as a GitHub Release asset
   with only a manifest committed.
6. Add a short page under `docs/results/` and open the pull request.

Most of this suits a coding agent, and `CLAUDE.md` is the repository's brief for one. The
exceptions are the steps where evidence actually enters: drawing calibration areas,
declaring them complete, and signing off validation.

Full runbook, including the agent prompt and the review checklist:
[Contribute your country atlas back](reproduce.md#contribute-your-country-atlas-back).

## Community

EarthPV is the software half of **TraceTheSun**, a pilot programme run by
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

* **[Open Energy Transition](https://openenergytransition.org)**, which runs EarthPV and
  funds the Pakistan pilot.
* **[Muhammad Awais](https://www.linkedin.com/in/awais307/)** and the student team at the
  **[Centre for Water Informatics and Technology (WIT)](https://wit.lums.edu.pk/)**, Lahore
  University of Management Sciences, who co-designed the pipeline and did the Pakistani
  mapping, validation and local-context work that this project's Pakistani results rest on.
  TraceTheSun was conceived jointly by Muhammad Awais and Tobias.
* **[Jake Stid](https://www.linkedin.com/in/jake-stid-38bb23131/)** of Michigan State
  University, creator of [GMSEUS](https://github.com/stidjaco/GMSEUS), with a regional
  focus on North America.
* **[Gabriel Kasmi](https://www.linkedin.com/in/gabriel-kasmi/)**, creator of
  [DeepPVMapper](https://github.com/gabrielkasmi/deeppvmapper).

### The Centre for Water Informatics and Technology (WIT), LUMS

<div class="partner-logos" markdown="0">
  <a href="https://wit.lums.edu.pk/" title="Centre for Water Informatics and Technology (WIT), LUMS">
    <img src="assets/figures/wit_logo.png" alt="Centre for Water Informatics and Technology (WIT), LUMS">
  </a>
</div>

The Pakistani side of EarthPV is a collaboration with the
[Centre for Water Informatics and Technology (WIT)](https://wit.lums.edu.pk/) at the Lahore
University of Management Sciences. TraceTheSun was conceived by Muhammad Awais and Tobias,
and a team of WIT students has worked alongside Open Energy Transition since the pilot
began, taking EarthPV from a trained model to a working rooftop solar mapping pipeline.
Their contribution runs across the entire workflow: they trace and verify Pakistani solar
installations in OpenStreetMap against high-resolution imagery, contribute the local
context that satellite data alone cannot capture, and build the exhaustively mapped
[ground-truth quadrats](calibration-mapping-protocol.md) against which every recall figure
on this site is measured.

The WIT student contributors are:

* **[Laeeba Hafeez Malik](https://www.linkedin.com/in/laeeba-hafeez-malik-220b63328/)**
  (BS Computer Science)
* **[Tayyiba Shafiq](https://www.linkedin.com/in/tayyiba-shafiq/)** (BS Economics)
* **[Nimra Aamir Ali](https://www.linkedin.com/in/nimra-aamir-ali-417b98249/)**
  (BS Anthropology)
* **[Vania Malik](https://www.linkedin.com/in/vania-malik-799bbb343/)**
  (BS Electrical Engineering)

This work is the reason the Pakistani model performs as well as it does. Adding in-domain
training chips drawn from the mapping loop raised detection recall on Punjabi rooftops from
0.18 to 0.55 for large arrays, and the calibration quadrats the students map remain the
only means of checking whether the model's own recall estimates are too optimistic.

For WIT, EarthPV is both a research dataset and a shared design exercise. Co-developing the
pipeline has given the students involved a practical introduction to open geospatial
machine learning, and the national photovoltaic database it produces already supports the
centre's own research. The longer-term goal is to connect this dataset to energy and
power-system models and to integrated-assessment scenarios, so that an open and
independently verifiable solar capacity map can feed directly into energy planning instead
of remaining a standalone map.

### How to contribute

**Map.** The most valuable contribution is verified installations in OpenStreetMap. Load
the [mapping leads](results/leads.md) into MapRoulette or JOSM, check each against the
high-resolution layers, and map what is real. Tag conventionally
(`generator:source=solar`, or `power=plant` with `plant:source=solar`) so the next label
pull finds it.

**Map a quadrat.** Exhaustively mapping every installation inside a drawn boundary is worth
far more per hour than scattered mapping, because it measures what the model *misses* rather
than only confirming what it finds. 31 quadrats exist so far; the protocol is in
[Quadrat mapping protocol](calibration-mapping-protocol.md).

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

## Licence

Code is MIT. Imagery from Copernicus Sentinel-2; building footprints from VIDA Open
Buildings and Overture Maps; labels from OpenStreetMap contributors under ODbL;
administrative boundaries from geoBoundaries under CC-BY.

**Published data outputs** (the evidence atlas, capacity parquets, raw detections and any
other derived dataset offered for download, e.g. under "Download the underlying data" on
the atlas page or as a GitHub Release asset) are derivative databases of OpenStreetMap's
ODbL-licensed solar labels and, via VIDA Open Buildings, of Microsoft/Google building
footprints. Under ODbL's share-alike clause, **these data releases are themselves
licensed under the [Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/)**,
with attribution to &copy; OpenStreetMap contributors required on any use, alongside VIDA
Open Buildings (CC BY 4.0) for the footprints and, for anything derived from the
Germany/MaStR validation, the Marktstammdatenregister (Bundesnetzagentur,
[Datenlizenz Deutschland -- Namensnennung -- Version 2.0](https://www.govdata.de/dl-de/by-2-0)).

The full programme description is in the
[TraceTheSun concept note](22072026-Concept-Note-TraceTheSun.md).
