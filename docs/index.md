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

**Free, Open and Global Mapping of Photovoltaic Systems Above 10 kWp - Including Capacity, Growth and Orientation**
{ .lede }

</div>

</div>

!!! warning "Active development"
    EarthPV is still a research prototype. It is actively experimenting with new solar
    detection methods, and its detectors, calibration and headline numbers are still being
    tested and revised rather than settled.

EarthPV fine-tunes the open **TerraMind** geospatial foundation model, developed by IBM and ESA and accessed through TerraTorch, using **Sentinel-2** imagery. Sentinel-2 provides free, global coverage with imagery refreshed **every five days**. Each model detection is then presented to **OpenStreetMap** mappers for verification, and the verified results are fed back into subsequent rounds of training. The model, code, training labels, and capacity estimates are all openly available, and every input is derived from globally accessible datasets. As a result, the approach does not depend on imagery, proprietary licences, or data sources that are restricted to any single country.

Pakistan is the first pilot, not the final destination. It is where EarthPV was initially built and developed.

[![The EarthPV evidence atlas: Pakistan's rooftop solar capacity, best estimate 24,330 MWp (90 percent range 20,822 to 33,582) -- a night-lights style map of estimated capacity per 0.1 degree cell concentrated in the Punjab corridor and the Karachi industrial belt.](assets/figures/pakistan_evidence_atlas.png)](atlas.md)

*Pakistan PV Capacity Estimate 
[Open the interactive version](results/capacity.md).*

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

![The evidence atlas workflow: Sentinel-2 imagery, OpenStreetMap solar mapping and VIDA building footprints feed two detectors, TerraMind segmentation for arrays of 400 square metres and above plus all ground-mount, and the per-building roofclf classifier cross-checked with SPPI. Both are calibrated against 30 hand-mapped ground-truth quadrats, then combined one best instrument per component with overlaps removed and each cell floored at hand-mapped OSM plus roofclf-and-SPPI agreement, producing the published evidence atlas: Best estimate 24,330 MWp with a 90 percent range of 20,822 to 33,582.](assets/figures/evidence_workflow.svg#only-light)
![The evidence atlas workflow: Sentinel-2 imagery, OpenStreetMap solar mapping and VIDA building footprints feed two detectors, TerraMind segmentation for arrays of 400 square metres and above plus all ground-mount, and the per-building roofclf classifier cross-checked with SPPI. Both are calibrated against 30 hand-mapped ground-truth quadrats, then combined one best instrument per component with overlaps removed and each cell floored at hand-mapped OSM plus roofclf-and-SPPI agreement, producing the published evidence atlas: Best estimate 24,330 MWp with a 90 percent range of 20,822 to 33,582.](assets/figures/evidence_workflow.dark.svg#only-dark)

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

Four things qualify that, and they matter more than the exact percentages.

## What did not work

Most of what was tried here failed, and the negative results are documented because they
map where the 10 m resolution limit actually is: band stacking, Sentinel-1 corner
reflection, two routes from glint to density, roof-axis orientation priors, three
super-resolution variants, spectral unmixing, and two retrains that won in-sample and lost
on held-out data. Every one has runnable code in `scripts/`.

The register with a verdict and the measurement behind each:
[Experiments](experiments.md). What is still undecided:
[Open questions](open-questions.md).

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

### TraceTheSun

TraceTheSun is an emerging community bringing together the most prominent open-source
projects in PV detection and the most skilled PV mappers in OpenStreetMap, to address
tagging and mapping solar worldwide in an open, verifiable and cost-effective way.

Currently forming, it includes:

* **[Open Energy Transition](https://openenergytransition.org)**, which runs EarthPV and
  funds the Pakistan pilot. Led by [Tobias Auspurger](https://www.linkedin.com/in/tobias-augspurger/)
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
