# earthpv

<div class="hero" markdown>

![earthpv](assets/figures/earthpv-logo-mark.png#only-light){ .hero-logo }
![earthpv](assets/figures/earthpv-logo-mark-white.png#only-dark){ .hero-logo }

**Open, global photovoltaic mapping from free satellite imagery.**
{ .lede }

</div>

> **EarthPV demonstrates how free Sentinel-2 imagery, an open foundation model, and
> human-in-the-loop validation in OpenStreetMap can make global photovoltaic mapping more
> scalable, verifiable, and cost-effective than existing methods.**

EarthPV fine-tunes the open **TerraMind** geospatial foundation model (IBM and ESA, through
TerraTorch) on **Sentinel-2** imagery, which is free, global and refreshed every five days,
and puts every detection in front of **OpenStreetMap** mappers for verification. The
verified result becomes the next round of training data. Model, code, training labels and
capacity numbers are all open, and every input is a global dataset -- nothing here is built
on imagery or licences that only exist in one country.

**Pakistan is the first pilot, not the destination.** It is where four methods below were
built and measured; the plan is to run the same pipeline everywhere Sentinel-2 flies. See
[Scaling worldwide](#scaling-worldwide).

## The main workflow: two detectors, split by placement and calibration coverage, one evidence atlas

This is earthpv's default pipeline and primary output. No single instrument covers
rooftop solar at every scale, so it runs two, each measured against ground truth, and
combines them into one product. The split is **not** a clean size boundary: roofclf's
reach now extends past its original sub-400 m<sup>2</sup> floor into large rooftops too,
wherever it has been calibrated to do so.

**Segmentation, the source of every mapping lead, and of ground-mount capacity at any
size.** A fine-tuned TerraMind-tiny outlines panels directly detects ground based and rooftop solar for >400 m<sup>2</sup> PV installations. 

**roofclf, for every rooftop below 400 m<sup>2</sup> -- and, where calibrated, for large
rooftops too.** At 10 m pixel size of Sentinel 2 imagery, a 100 m<sup>2</sup> array is a handful of mixed
pixels -- not enough to draw a polygon around, but enough to ask whether a *building*
carries PV. **roofclf** is a per-building classifier trained on 27 exhaustively mapped
ground-truth quadrats (0.879 AUC, 0.834 with roof size controlled for, where the
segmentation raster scores close to chance on the same small buildings), cross-checked
against **SPPI**, a zero-training five-band spectral index (He et al. 2026) that needs no
labels at all (0.823 AUC in its own nine-quadrat evaluation, where roofclf scored 0.874
on the identical buildings). 

![Three instruments and the installation-size range each one covers, on a logarithmic area axis: aggregate density estimation from about 20 square metres upward, individual polygon detection from 400 square metres, and glint pose confirmation from 1000 square metres.](assets/figures/size_spectrum.svg#only-light)
![Three instruments and the installation-size range each one covers, on a logarithmic area axis: aggregate density estimation from about 20 square metres upward, individual polygon detection from 400 square metres, and glint pose confirmation from 1000 square metres.](assets/figures/size_spectrum.dark.svg#only-dark)

**Both instruments converge on the evidence atlas.** `density` aggregates segmentation's
&ge; 400 m<sup>2</sup> detections (rooftop and ground-mount, every cell);
`roof-classifier` → `roofclf-score-national` → `sub400-capacity` builds
roofclf's < 400 m<sup>2</sup> population, and `ge400-roof-capacity` builds its &ge; 400
m<sup>2</sup> rooftop replacement inside the calibrated cells; `earthpv atlas` combines
all of it into **Best estimate**, this project's own highest defensible figure,
hand-mapped OpenStreetMap installations plus the model's own recall-corrected detections
plus roofclf/SPPI's per-building density estimate -- with the overlap between OSM and
detections removed rather than double-counted, and a 90% range on the total. Full command
sequence: [The full pipeline](reproduce.md#the-full-pipeline).

**Why two detectors, checked against a complete register.** Germany's MaStR register is
legally mandatory, so it is ground truth rather than a sample. Measured against it,
**65.5% of German rooftop capacity sits below the 400 m<sup>2</sup> detection floor**
(97.2% of installations). An instrument that only sees above that floor is describing
roughly a third of what a "rooftop solar" headline implies, which is the whole argument
for the second detector. See [Validation against MaStR](methods/mastr-validation.md).

**The absolute total is a modelled estimate, not a metered figure -- Sentinel-2's 10 m
pixels make that unavoidable.** An individual array below roughly 400 m<sup>2</sup> is a
mixed-pixel problem rather than a shape the segmentation model can outline, so everything
under that floor comes from `roofclf` instead, restricted to cells whose building density
resembles the hand-mapped calibration quadrats it was measured on. That restriction keeps
the sub-400 m<sup>2</sup> numbers honest, but it also means the total tracks calibration
coverage, not a direct count, which is why the headline figure carries a 90% range rather
than one bare number. Checked against that limitation directly: an independent,
separately produced national rooftop-solar estimate agrees closely with this project's on
**where** capacity concentrates -- normalizing both to percent of national total per
spatial unit (their absolute magnitudes aren't comparable), the median difference across
3,303 spatial units is 0.005 percentage points and rank correlation is 0.75-0.84. It
disagrees more on how much weight the very largest sites deserve (a handful of hotspot
cells drive most of the remaining gap, consistently in the same direction), which is a
real, stated limitation, not a hidden one. See [Capacity map](results/capacity.md) for the
full comparison and `scripts/pv_reference_share_comparison.py` to reproduce it.

### Optional, supplementary instruments

Everything below is evidence toward the main workflow, a secondary product built from the
same detections, or a documented negative result -- not a competing main path.

**Glint, for tilt and orientation.** A glass-fronted panel is partly a mirror, so it
flashes into Sentinel-2 only on the geometry-predictable dates when its tilt and azimuth
bisect the sun and the sensor. Two or more mutually consistent flashes are a physical
confirmation that PV is present, independent of spectral appearance, and recover how the
panel is mounted. Folds into the main workflow's leads ranking as a boost-only signal;
never required to produce the evidence atlas.

**Growth, for when installations appeared.** Diffing a pre-boom (2021/22) Sentinel-2
composite against the current one -- with both the segmentation model and SPPI run
independently on each epoch -- shows where solar capacity actually landed, not just where
it stands today. Pakistan's own rooftop stock roughly doubled since 2021/22 by this
measure. See [Growth](results/growth.md).

A fraction-head expected-area instrument, SPPI as a standalone (not cross-checked)
detector, an older Low/Central/High/All-PV bracket atlas and a rooftop
potential/saturation atlas exist too, each measured and each kept in the repository
whether or not it was promoted -- see [Experiments](experiments.md) for what was tried
and why the main workflow above is what shipped.

[![The earthpv evidence atlas: Pakistan's rooftop solar capacity, best estimate 19,746 MWp (90 percent range 16,051 to 23,520) -- a night-lights style map of estimated capacity per 0.1 degree cell concentrated in the Punjab corridor and the Karachi industrial belt.](assets/figures/pakistan_evidence_atlas.png)](results/capacity.md)

*This project's own highest defensible figure, not a bare point estimate: hand-mapped
OpenStreetMap installations, the model's own recall-corrected detections, and a
per-building density estimate for small rooftops, with a 90 percent range attached.
[Open the interactive version](results/capacity.md).*

## Scaling worldwide

Nothing in the pipeline is Pakistan-specific. All four inputs are global open datasets:

| Input | Source | Coverage |
| --- | --- | --- |
| Imagery | Copernicus Sentinel-2 L2A | global, every five days, free |
| Labels | OpenStreetMap, live Overpass or Overture | global, wherever mappers have been |
| Footprints | VIDA Open Buildings | global, imagery-derived |
| Boundaries | geoBoundaries, CC-BY | global, ADM1 and ADM2 |

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
[the main workflow](#the-main-workflow-two-detectors-split-by-placement-and-calibration-coverage-one-evidence-atlas)
above:

| | |
| --- | --- |
| **19,746 MWp** | Best estimate: this project's own highest defensible figure (90% range 16,051 &ndash; 23,520) |
| **15,642** | individual installations hand-mapped in OpenStreetMap (deduplicated -- see below) |
| **400 m<sup>2</sup>** | size below which segmentation is trained blind; roofclf/SPPI cover it, and roofclf also replaces segmentation above it inside its calibrated cells |
| **65.5%** | of Germany's rooftop capacity sits *below* that floor, measured against its complete MaStR register |

The headline figure carries a 90% range as of 2026-08-11, composed from the
area-to-capacity constants' priors, segmentation's measured precision and recall by
installation size, and the coverage ratio's sensitivity to which calibration quadrats
happen to have been mapped. The range is wide on purpose: this figure moved by 20-35%
five times in a single week from recalibration alone, and reporting it bare had been
hiding that. It is not a design-based margin of error -- the quadrats behind it are
hand-picked, not randomly sampled, and it does not cover the gap between where the
roofclf coverage-ratio correction is fit and where it is applied: about half of Best is
priced by a multiplier measured on quadrats several times denser than most of the cells
it prices (see [Calibration density mismatch](issues/roofclf-calibration-density-mismatch.md)).
See [Capacity map](results/capacity.md) for the derivation and
[Validation against MaStR](methods/mastr-validation.md) for what a legally complete
register can and cannot settle.

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

The main workflow is `labels → chips → train → evaluate → compose
→ infer → postprocess → export` to produce every mapping lead and, via
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

| If you want to | Read |
| --- | --- |
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
