---
hide:
  - navigation
---
# earthpv

<div class="hero" markdown>

**The mission of EarthPV is to provide cost-effective, verifiable, open data on
photovoltaic (PV) capacity, growth and orientation for every country worldwide.**
{ .lede }

</div>

!!! warning "Active development"
    EarthPV is still a research prototype. It is actively experimenting with new solar
    detection methods, and its detectors, calibration and headline numbers are still being
    tested and revised rather than settled.

EarthPV fine-tunes the open **TerraMind** geospatial foundation model, developed by IBM and ESA and accessed through TerraTorch, using **Sentinel-2** imagery. Sentinel-2 provides free, global coverage with imagery refreshed every five days. Each model detection is then presented to **OpenStreetMap** mappers for verification, and the verified results are fed back into subsequent rounds of training. The model, code, training labels, and capacity estimates are all openly available, and every input is derived from globally accessible datasets. As a result, the approach does not depend on imagery, proprietary licences, or data sources that are restricted to any single country.

**Pakistan is the first pilot, not the destination.** It is where four methods below were
built and measured; the plan is to run the same pipeline everywhere Sentinel-2 flies. See
[Scaling worldwide](#scaling-worldwide).

[![The earthpv evidence atlas: Pakistan's rooftop solar capacity, best estimate 18,827 MWp (90 percent range 16,022 to 24,358) -- a night-lights style map of estimated capacity per 0.1 degree cell concentrated in the Punjab corridor and the Karachi industrial belt.](assets/figures/pakistan_evidence_atlas.png)](results/capacity.md)

*This project's own highest defensible figure, not a bare point estimate: hand-mapped
OpenStreetMap installations, the model's own recall-corrected detections, and a
per-building density estimate for small rooftops, with a 90 percent range attached.
[Open the interactive version](results/capacity.md).*

## The Main Workflow

This is earthpv's default pipeline and its primary output. Two detectors, each
measured against hand-mapped ground truth, are combined into a single evidence atlas.
What each one covers is split by installation placement and by how far the calibration
reaches, not by a hard size cutoff: `roofclf` started as the sub-400 m<sup>2</sup>
rooftop detector but now also handles larger rooftops in the cells where the
calibration supports it.

![The evidence atlas workflow: Sentinel-2 imagery, OpenStreetMap solar mapping and VIDA building footprints feed two detectors, TerraMind segmentation for arrays of 400 square metres and above plus all ground-mount, and the per-building roofclf classifier cross-checked with SPPI. Both are calibrated against 30 hand-mapped ground-truth quadrats, then combined one best instrument per component with overlaps removed and each cell floored at hand-mapped OSM plus roofclf-and-SPPI agreement, producing the published evidence atlas: Best estimate 18,827 MWp with a 90 percent range of 16,022 to 24,358.](assets/figures/evidence_workflow.svg#only-light)
![The evidence atlas workflow: Sentinel-2 imagery, OpenStreetMap solar mapping and VIDA building footprints feed two detectors, TerraMind segmentation for arrays of 400 square metres and above plus all ground-mount, and the per-building roofclf classifier cross-checked with SPPI. Both are calibrated against 30 hand-mapped ground-truth quadrats, then combined one best instrument per component with overlaps removed and each cell floored at hand-mapped OSM plus roofclf-and-SPPI agreement, producing the published evidence atlas: Best estimate 18,827 MWp with a 90 percent range of 16,022 to 24,358.](assets/figures/evidence_workflow.dark.svg#only-dark)

### Segmentation

A fine-tuned TerraMind-tiny model detects and outlines rooftop and ground-mounted
PV installations above roughly 400 m<sup>2</sup>. These detections are the mapping
leads used throughout earthpv, and they are the sole basis for ground-mounted
capacity at every size.

### Roof-level classification

`roofclf` covers the rooftops segmentation cannot resolve. At Sentinel-2's 10 m
resolution a 100 m<sup>2</sup> array spans only a handful of mixed pixels: too few to
trace a reliable outline, but often enough to tell whether the building carries PV at
all.

`roofclf` is a per-building classifier trained on 30 exhaustively mapped ground-truth
quadrats. It reaches an AUC of 0.879, or 0.834 once roof size is controlled for, on the
same small buildings where the segmentation raster performs close to chance. Its
predictions are cross-checked against SPPI, a zero-training five-band spectral index
from He et al. (2026): on SPPI's own nine-quadrat evaluation, SPPI scored 0.823 and
`roofclf` scored 0.874 on the same buildings.

![Three instruments and the installation-size range each one covers, on a logarithmic area axis: aggregate density estimation from about 20 square metres upward, individual polygon detection from 400 square metres, and glint pose confirmation from 1000 square metres.](assets/figures/size_spectrum.svg#only-light)
![Three instruments and the installation-size range each one covers, on a logarithmic area axis: aggregate density estimation from about 20 square metres upward, individual polygon detection from 400 square metres, and glint pose confirmation from 1000 square metres.](assets/figures/size_spectrum.dark.svg#only-dark)

### Building the evidence atlas

The two detection streams are combined into a single capacity estimate:

- `density` aggregates the segmentation detections at or above 400 m<sup>2</sup>,
  rooftop and ground-mounted, across every cell.
- `roof-classifier` → `roofclf-score-national` → `sub400-capacity` estimates rooftop
  capacity below 400 m<sup>2</sup>.
- `ge400-roof-capacity` is the `roofclf`-based rooftop estimate above 400 m<sup>2</sup>,
  inside the calibrated cells only.
- `earthpv atlas` merges these into the Best estimate, this project's highest
  defensible national figure.

The Best estimate is built from hand-mapped OpenStreetMap installations,
recall-corrected model detections, and the `roofclf`/SPPI per-building estimate. Where
an OSM installation and a model detection describe the same array, one is dropped so it
is not counted twice, and the national total is reported with a 90% uncertainty range.

Full command sequence: [The full pipeline](reproduce.md#the-full-pipeline).

### But why are two detectors necessary?

Registration in Germany's MaStR is mandatory, so it is a near-complete reference
rather than a sample. Measured against it, 65.5% of German rooftop capacity sits below
the 400 m<sup>2</sup> segmentation floor (97.2% of installations by count).

Segmentation alone, working only above that floor, would therefore see roughly
one-third of the capacity a national "rooftop solar" figure implies. That gap is why
there is a second, building-level detector.

As of 2026-08-31 that register also supports an end-to-end national check, covering 99.75% of
German rooftop capacity, and it cuts both ways: it turned one estimator from unusable into
better-bounded and showed that another was overstating the truth threefold. See
[Validation against MaStR](methods/mastr-validation.md) and
[Germany capacity and validation](results/germany.md).

### Interpreting the national estimate

The national total is a modelled estimate, not a meter reading. At 10 m resolution the
sub-400 m<sup>2</sup> installations are a mixed-pixel problem rather than traceable
shapes, so `roofclf` estimates their contribution instead of outlining them.

That estimate is deliberately capped: it only runs in cells whose building density
matches the hand-mapped calibration quadrats the classifier was tested on. Staying
inside that range keeps the sub-400 m<sup>2</sup> numbers defensible, but it also means
the national total rests partly on how far the calibration reaches, not on a direct
count of every installation. Hence the 90% range on the headline figure.

As a spatial cross-check, the atlas is compared against an independent national
rooftop-solar dataset. The two cannot be compared in absolute terms, so both are
reduced to each spatial unit's share of the national total. Across 3,303 units the
median difference is 0.005 percentage points, with a rank correlation of 0.75 to 0.84.

Where they disagree is on how much weight the largest sites carry: a handful of hotspot
cells account for most of the gap, always in the same direction. earthpv treats its
handling of very large sites as an explicit limitation of the current estimate.

See [Capacity map](results/capacity.md) for the full comparison, and
`scripts/pv_reference_share_comparison.py` to reproduce it.

### Optional, supplementary instruments

These support, extend, or test the main workflow. None of them is an alternative to it.

#### Glint

Glint is an independent, physical confirmation that PV is present, and it can also
recover panel tilt and orientation. A glass-fronted panel acts partly as a mirror,
flashing in Sentinel-2 imagery on the dates the Sun-panel-satellite geometry predicts.
Two or more flashes on geometrically consistent dates raise confidence that the target
is real PV. In the main workflow glint only boosts lead ranking; it is never needed to
build the evidence atlas.

[![High-resolution basemap imagery of a rooftop PV array caught mid-glint: the panels saturate fully white and the overload spills off the roof as a rainbow smear of detector-blooming artifacts across the neighbouring buildings.](assets/figures/glint_example.jpg){ width=&#34;50%&#34; }](glint_examples.md)

*The physical event the glint check looks for, caught in sub-metre commercial imagery: the array's specular reflection is so intense it saturates the sensor outright, blooming into a rainbow smear across the neighbouring rooftops. At Sentinel-2's 10 m the same event is a single bright pixel-cluster on one predictable date. More examples in the [glint image gallery](glint_examples.md).*

#### Growth

Growth dates installations by running the pipeline twice: once on a pre-boom 2021/22
Sentinel-2 composite, once on the current one. Segmentation and SPPI are each run
independently on both epochs, so deployment can be tracked over time rather than only
counted as it stands today. On this measure Pakistan's rooftop solar stock has roughly
doubled since 2021/22. See [Growth](results/growth.md).

#### Other evaluated instruments

The repository also keeps a fraction-head expected-area model, SPPI as a standalone
detector, an earlier Low/Central/High/All-PV bracket atlas, and a rooftop potential and
saturation atlas. Each was measured; none was promoted into the main workflow. See
[Experiments](experiments.md) for what was tried and why the final pipeline looks the
way it does.

## Scaling worldwide

Nothing in the pipeline is Pakistan-specific. All four inputs are global open datasets:

| Input      | Source                                   | Coverage                           |
| ---------- | ---------------------------------------- | ---------------------------------- |
| Imagery    | Copernicus Sentinel-2 L2A                | global, every five days, free      |
| Labels     | OpenStreetMap, live Overpass or Overture | global, wherever mappers have been |
| Footprints | VIDA Open Buildings                      | global, imagery-derived            |
| Boundaries | geoBoundaries, CC-BY                     | global, ADM1 and ADM2              |

Three commands set up a region that has never been touched. The first is read-only and
tells you within a couple of minutes whether the data is actually there.

```bash
pixi run python scripts/new_region.py check --bbox 98.5,7.8,101.0,10.2 --iso3 THA
pixi run python scripts/new_region.py add   --aoi surat_thani --bbox 98.5,7.8,101.0,10.2 --iso3 THA
pixi run python scripts/new_region.py plan  --aoi surat_thani
```

`check` probes OpenStreetMap label density, VIDA availability, geoBoundaries, Sentinel-2
cloud cover in your composite window, and the compose budget. `add` writes the AOI block.
`plan` prints the ordered runbook with the region's name filled in.

A first candidate set needs no local training data: the existing checkpoint runs
unchanged. What closes the domain gap afterwards is local mapping, which is why the guide
starts by telling you to find a mapping community before you run anything. **Programme
targets are Mexico, Japan, Korea, Indonesia, India, Brazil, South Africa and Nigeria**;
Gujarat is already registered as a worked template, with a first full,
segmentation-only capacity estimate (812.6 MWp, &ge; 400 m<sup>2</sup>, no calibration
quadrats yet) at [Gujarat capacity map](results/gujarat.md).

Full guide, including what to expect by starting condition and what genuinely differs
from Pakistan (climate windows, roof type, latitude-dependent glint geometry,
installation-size distribution): [Setup a new country](reproduce.md).

## Pakistan: the pilot, in numbers

Pakistan's installed solar capacity is reported anywhere between
[6.8 GW officially and 47 GW by NGO estimates](https://ember-energy.org/latest-insights/the-solarisation-of-pakistans-energy-economy/).
Nobody can check those numbers, because the maps behind them are built on commercial
high-resolution imagery that cannot be shared and that most licences forbid processing
with AI. earthpv's own numbers come from
[the main workflow](#the-main-workflow) above:

|                             |                                                                                                                                                    |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **18,827 MWp**        | Best estimate: this project's own highest defensible figure (90% range 16,022&ndash; 24,358)                                                       |
| **15,642**            | individual installations hand-mapped in OpenStreetMap (deduplicated -- see below)                                                                  |
| **400 m<sup>2</sup>** | size below which segmentation is trained blind; roofclf/SPPI cover it, and roofclf also replaces segmentation above it inside its calibrated cells |
| **65.5%**             | of Germany's rooftop capacity sits*below* that floor, measured against its complete MaStR register                                               |

The headline figure carries a 90% uncertainty range based on priors for the area-to-capacity constants, measured segmentation precision and recall by installation size, and the sensitivity of the coverage ratio to the mapped calibration quadrats. The range is intentionally wide: recalibration has repeatedly shifted the estimate by 20 to 35% within days, most recently as calibration coverage widened again in August 2026.

It is not a design-based margin of error. The quadrats are hand-picked, not randomly sampled, and the range does not capture the mismatch between where the roofclf coverage correction is calibrated and where it is applied. As of the current fit, roughly 5% of Best is still priced by a multiplier derived from quadrats several times denser than the cells it estimates -- down sharply from about half in mid-August 2026 as calibration coverage widened. See [Calibration density mismatch](issues/roofclf-calibration-density-mismatch.md) for details. The full uncertainty derivation is provided in [Capacity map](results/capacity.md#how-confident-should-you-be-in-this), while [Validation against MaStR](methods/mastr-validation.md) explains what comparison with a legally complete register can and cannot establish.

Every number above carries the same caveat: **this is a screening and estimation layer,
not a register**. No human has validated most of it at scale, and the sub-400 m
<sup>2</sup> share of Best estimate in particular is restricted to a small,
density-matched slice of the country, not a national measurement. See
[Capacity map](results/capacity.md) for how the estimate is derived and what it does and
does not claim.

## The OpenStreetMap mapping loop

The technical novelty is not one model. It is a loop that combines free low-resolution
imagery, an open foundation model, and human mappers working inside OpenStreetMap with
the high-resolution imagery they are already licensed to look at.

![The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.](assets/figures/osm_ai_flywheel.svg#only-light)
![The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.](assets/figures/osm_ai_flywheel.dark.svg#only-dark)

Two licences pull in opposite directions, and the loop is what resolves them. Sentinel-2
is free and global but coarse; Esri, Bing and Mapbox resolve individual panels but only
allow a *person* to trace from them inside the OpenStreetMap editor. So the machine only
ever reads Sentinel-2, people only ever read the high-resolution layers, and the verified
installations they map are ordinary, openly licensed OpenStreetMap features that are
legitimate training data for the next model. Full description:
[Workflow](how-it-works.md#workflow).

[![The glint pose survey page: a polar plot of fitted tilt and azimuth for 290 Pakistani installations, clustered between east-southeast and due south at tilts of roughly 5 to 20 degrees.](assets/figures/pakistan_pv_pose.png)](results/pv-pose.md)

*Panel pose recovered from Sentinel-2 glint for 290 Pakistani installations, out of 2,000
checked. [Open the interactive version](results/pv-pose.md).*

## Quickstart

```bash
pixi install              # data pipeline: DuckDB, geopandas, rasterio, odc-stac
pixi install -e ml        # adds PyTorch cu126 (Pascal-safe) and TerraTorch
pixi run -e ml gpu-check

# minutes-long smoke test through every GPU stage
pixi run earthpv labels --aoi freiburg
pixi run earthpv chips  --aoi freiburg --limit 50
pixi run -e ml earthpv train --config configs/terramind_pv.yaml --smoke
pixi run -e ml earthpv evaluate --aoi freiburg --checkpoint data/models/last.ckpt
```

The main workflow is `labels → chips → train → evaluate → compose → infer → postprocess → export` to produce every mapping lead and, via
`density → check-density`, segmentation's own &ge; 400 m<sup>2</sup> capacity; then
`roof-classifier → roofclf-score-national → sub400-capacity` for roofclf's
< 400 m<sup>2</sup> population and `ge400-roof-capacity` for its &ge; 400 m<sup>2</sup>
rooftop replacement inside the calibrated cells; `atlas` combines all of it into the
evidence atlas -- this project's primary output. Every stage is resumable and safe to
re-run. The full runbook, including how to bring up a country that has never been
touched, is in [Setup a new country](reproduce.md#the-full-pipeline).

## What did not work

Most of what was tried here failed, and the negative results are documented because they
map where the 10 m resolution limit actually is: two-season band stacking (including a
retry stacking the actual pre-boom epoch instead of a weather season), Sentinel-1 corner
reflection, two separate routes from glint to density, roof-axis orientation priors,
three super-resolution variants, spectral unmixing, temporal features for the roof
classifier, and two retrains aimed at known failure modes that won in-sample and lost on
held-out data. Every one has runnable code in `scripts/`.

The full register, with a verdict and the measurement behind each, is
[Experiments](experiments.md); what is still undecided is
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

earthpv is developed by [Open Energy Transition](https://openenergytransition.org) as the
software half of the **TraceTheSun** pilot. The concept was conceived by
[Muhammad Awais](https://www.linkedin.com/in/awais307/) and Tobias; the Pakistani mapping,
validation and ground-truth work is carried out by a student team at the
[Centre for Water Informatics and Technology (WIT)](https://wit.lums.edu.pk/), Lahore
University of Management Sciences, working in close coordination with Open Energy
Transition. See [Community](#community) for the full contributor list, including every
named student mapper, and the
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

The Pakistani side of earthpv is a collaboration with the
[Centre for Water Informatics and Technology (WIT)](https://wit.lums.edu.pk/) at the Lahore
University of Management Sciences. TraceTheSun was conceived by Muhammad Awais and Tobias,
and a team of WIT students has worked alongside Open Energy Transition since the pilot
began, taking earthpv from a trained model to a working rooftop solar mapping pipeline.
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

For WIT, earthpv is both a research dataset and a shared design exercise. Co-developing the
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
