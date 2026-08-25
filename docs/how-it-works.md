# How it works

This page describes the pipeline as it runs today: **two detectors, split by placement
and calibration coverage rather than by size alone, combined into one evidence atlas**.
[Workflow](#workflow) tells the human story of how a
Sentinel-2 pixel becomes a verified OpenStreetMap feature. [Architecture](#architecture) is
the technical complement, covering what reads what, stage by stage, and
[what is optional](#the-main-workflow-and-whats-optional) alongside the default path.
[Methods](#methods) links out to the deep-dive reference page for each stage.
[Comparison](#comparison-with-other-pakistan-solar-capacity-estimates) sets the resulting
figure against every other public estimate of Pakistan's solar fleet.

Two things deliberately live elsewhere, so that this page stays a description of the working
pipeline rather than a history of the project: [Experiments](experiments.md) is the record of
everything that was tried, including the majority that did not ship, and
[Open questions](open-questions.md) is what is still genuinely unresolved.

## Workflow

The technical novelty in earthpv is not one model. It is a loop that combines free
low-resolution imagery, an open foundation model, and human mappers working inside
OpenStreetMap with the high-resolution imagery they are already licensed to look at.

![The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.](assets/figures/osm_ai_flywheel.svg#only-light)
![The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.](assets/figures/osm_ai_flywheel.dark.svg#only-dark)

### Why the loop exists

Two licences pull in opposite directions, and the loop is what resolves them.

Sentinel-2 is free, global, and reprocessed every five days, but at 10 m per pixel a
typical rooftop array is four to twenty pixels. Esri, Bing and Mapbox imagery resolves
individual panels, but their terms allow a person to trace from them inside the
OpenStreetMap editor and do not allow a machine to be trained on them.

So the machine only ever reads Sentinel-2, and people only ever read the high-resolution
layers. The model proposes; a mapper disposes; the disposal is recorded in OpenStreetMap
as an ordinary, openly licensed feature; and that feature is legitimate training data for
the next model. Nothing proprietary crosses into the model, and nothing the model produces
is trusted until a person has looked at it.

### The four steps

#### 1. Labels from OpenStreetMap

`earthpv labels` reads solar polygons for an area either from Overture Maps (a periodic
OpenStreetMap snapshot, convenient but lagging) or, for a freshly mapped region,
`earthpv overpass-labels` queries the live Overpass API. Building footprints come from
Overture and from VIDA Open Buildings, which is imagery-derived and therefore includes the
small, unmapped structures that OpenStreetMap in Pakistan does not yet have.

#### 2. Train on Sentinel-2

`earthpv chips` cuts training windows out of dry-season Sentinel-2 composites and burns
the label polygons into per-pixel masks. `earthpv train` fine-tunes TerraMind-tiny through
TerraTorch. Training started on Germany, where OpenStreetMap solar mapping is dense and
close to complete, and then added Pakistani chips as the loop produced them. See
[Detection model](methods/detection.md) for what that buys.

#### 3. Rank candidates and publish leads

`earthpv infer` writes a probability raster per grid cell; `earthpv postprocess`
polygonizes it, attaches each candidate to a building footprint, and scores it.
The pipeline is deliberately **recall-first**: false positives cost a mapper a few
seconds, whereas a missed installation is invisible forever. Nothing is dropped by the
default export. What the priors do is reorder the queue so mappers hit real installations
first:

| Signal | What it does | Direction |
| --- | --- | --- |
| Building prior | overlap with, or distance to, a VIDA footprint | reorders |
| [Glint corroboration](methods/glint.md) | specular flashes consistent with one panel plane | boosts only |
| Pre-boom epoch check | high probability in 2021 imagery too, so probably not new PV | demotes |
| Vegetation veto | a crop cycle observed over the year, so not a panel | drops, into a separate clean file |

`earthpv export` writes GeoParquet, GeoJSON and a MapRoulette challenge ordered by
`rank_score`.

#### 4. People verify, and the labels come back

Mappers open each lead in the OpenStreetMap editor, compare it against the
high-resolution layers, and either map the installation properly or discard the lead.
Local mappers add what no imagery shows: which industrial estate this is, whether the roof
belongs to a factory or a school, whether the array is net-metered.

Verified installations then flow straight back into step 1 through the Overpass label path.
The label-driven compose run in Punjab unlocked roughly 2,500 in-domain Pakistani
positives this way, and adding them tripled large-array recall in Punjab compared with the
Germany-only model.

### Two ways to see a panel in a 10 m pixel

The pipeline runs two detectors, and the reason is not organisational, it is optical. A
Sentinel-2 pixel is 10 by 10 metres, and everything depends on how an array compares to
that square:

![The same Sentinel-2 10 metre pixel grid over three solar arrays. A 2,000 square metre array covers 20 pixels mostly with panel and has a clear shape to outline. A 400 square metre array, the segmentation floor, mostly covers only 3 pixels. A 100 square metre array covers no pixel even half way, peaking at 54 percent of one mixed pixel, leaving only a shifted spectral signature.](assets/figures/pixel_grid.svg#only-light)
![The same Sentinel-2 10 metre pixel grid over three solar arrays. A 2,000 square metre array covers 20 pixels mostly with panel and has a clear shape to outline. A 400 square metre array, the segmentation floor, mostly covers only 3 pixels. A 100 square metre array covers no pixel even half way, peaking at 54 percent of one mixed pixel, leaving only a shifted spectral signature.](assets/figures/pixel_grid.dark.svg#only-dark)

- **Above roughly 400 m<sup>2</sup> an array has a shape**, so detection works in the
  **spatial domain**: the fine-tuned TerraMind model labels each pixel and its outline
  becomes a candidate polygon. The [detection model page](methods/detection.md) walks
  through this on real installations, from a utility plant the model cannot miss to a
  715 m<sup>2</sup> rooftop it usually does.
- **Below the floor an array is a fraction of one mixed pixel**, so detection moves to
  the **spectral domain**: a panel-covered roof is a few percent darker than the same
  roof without panels, deepest in red and near-infrared, with a slight blue tint and a
  relative SWIR excess. No outline exists, so
  [the rooftop classifier](methods/roofclf.md) scores whole buildings on that signature
  instead, and its skill is measured on exhaustively mapped calibration quadrats.

Neither domain proves an individual roof. The spatial detector tolerates false positives
because a person reviews every lead; the spectral detector is never read per building at
all, only summed into calibrated adoption rates. Both of those design choices follow from
the physics in the figure above.

### Two products fall out of one model

![Two products from one model: Sentinel-2 composites feed TerraMind, whose probability raster splits into a leads product of polygons for human review, which flows to OpenStreetMap through a MapRoulette challenge, and a capacity product of megawatts peak per building and grid cell, which flows to PyPSA-Earth as a grid CSV.](assets/figures/two_products.svg#only-light)
![Two products from one model: Sentinel-2 composites feed TerraMind, whose probability raster splits into a leads product of polygons for human review, which flows to OpenStreetMap through a MapRoulette challenge, and a capacity product of megawatts peak per building and grid cell, which flows to PyPSA-Earth as a grid CSV.](assets/figures/two_products.dark.svg#only-dark)

The split matters because the two products have opposite tolerances. On the leads path a
false positive is cheap and a miss is expensive, so the model runs hot. On the capacity
path there is no human in the loop at all, so every candidate is reweighted by a
**measured** probability of being real before its area is counted. Same rasters, different
accounting, documented in [Calibration](methods/calibration.md).

### Reproducing the loop

Every step above is a CLI command that is resumable and safe to re-run. The full runbook,
including how to start on a region with no pre-existing data, is in
[Setup New Country](reproduce.md).

## Architecture

[Workflow](#workflow) tells the human story: OpenStreetMap labels a model, the model
proposes leads, mappers dispose of them, and verified installations become the next
round of labels. This section is the technical complement: what actually reads what, stage
by stage, from raw Sentinel-2 pixels to the two published products. Each box below is a
real module or CLI stage; the [Setup New Country](reproduce.md) runbook runs them in this order.

![How raw data becomes a mapping lead and a capacity number: Sentinel-2 composites and OpenStreetMap labels train a TerraMind checkpoint; five inference instruments (segmentation, the fraction head, glint, SPPI, roofclf) read the same imagery; postprocess, density and the sub-400 square metre bracket combine their outputs; a plausibility gate checks the capacity numbers; and four outputs follow: MapRoulette leads back to OpenStreetMap, a capacity atlas, a PyPSA-Earth grid CSV, and an evidence atlas.](assets/figures/architecture.svg#only-light)
![How raw data becomes a mapping lead and a capacity number: Sentinel-2 composites and OpenStreetMap labels train a TerraMind checkpoint; five inference instruments (segmentation, the fraction head, glint, SPPI, roofclf) read the same imagery; postprocess, density and the sub-400 square metre bracket combine their outputs; a plausibility gate checks the capacity numbers; and four outputs follow: MapRoulette leads back to OpenStreetMap, a capacity atlas, a PyPSA-Earth grid CSV, and an evidence atlas.](assets/figures/architecture.dark.svg#only-dark)

### Raw data, once

Three inputs, each reused everywhere downstream rather than re-fetched per stage:

- **Sentinel-2 L2A** -- 10-band dry-season composites (`local_source.py`'s
  `CompositeIndex` where a sibling project already downloaded a tile, otherwise
  `compose.py` builds one on demand from Planetary Computer STAC). Every instrument in
  the inference lane reads from this same set of rasters.
- **OSM / Overture solar labels** -- mapped installations from Overture's periodic
  snapshot, or a live Overpass pull for a region being freshly mapped
  (`earthpv overpass-labels`). This is both the training signal and, through the
  flywheel, the destination the pipeline's own output eventually feeds back into.
- **VIDA / Overture buildings** -- imagery-derived footprints (`buildings.py`), which
  matter because they include small, unmapped structures OpenStreetMap does not yet
  have. Buildings feed three downstream consumers directly: `postprocess`'s building
  join, `roofclf`'s per-building features, and the sub-400 m² bracket's domain
  restriction. The diagram omits those three arrows to stay legible; the dependency is
  real in all three places.

### The main workflow and what's optional

`chips` cuts jittered training windows and burns label polygons into per-pixel masks;
`train` fine-tunes `terramind_v1_tiny` through TerraTorch into a checkpoint that
monitors validation mIoU. See [Detection model](methods/detection.md) for the model
internals and the two invariants (chip jitter, Hann-tapered overlap-add) that keep
inference from tiling into a grid of false positives.

From there, five instruments can read the same Sentinel-2 composites, but only two of
them are the **main workflow** -- everything else is optional, kept as evidence, a
secondary product, or a documented negative result:

| Instrument | Part of the main workflow? | Needs the trained checkpoint? | What it outputs |
| --- | --- | --- | --- |
| **Segmentation raster** (`infer`) | **Yes -- every mapping lead; all ground-mount capacity; rooftop &ge; 400 m² outside roofclf's calibrated cells** | Yes, the primary one | per-pixel PV probability; the only instrument with a polygon and a defended ≥ 400 m² floor |
| **[roofclf](methods/roofclf.md)** | **Yes -- every rooftop < 400 m², plus rooftop &ge; 400 m² inside its calibrated cells, where it replaces segmentation** | No, a separate lightweight classifier | per-building "does this roof carry PV," trained on exhaustively mapped calibration quadrats |
| **SPPI** (spectral PV probability index) | Partially -- cross-checks roofclf as an internal floor for the evidence atlas | No, a fixed spectral formula | a zero-training index, cross-validated against the same ground truth as roofclf |
| **Glint matched filter** | Optional -- boosts the leads ranking only | No | specular-flash geometry consistent with one fixed panel plane; a physical corroboration, not a probability |
| **Fraction head** | Optional, not promoted (see below) | Yes, a separately trained checkpoint | per-pixel PV *coverage fraction*; drops the polygon, aims at sub-400 m² signal a segmentation threshold cannot see |

Glint and SPPI need no model fit at all. roofclf is trained, but on a different, much
smaller, hand-labelled corpus (the calibration quadrats), not on the segmentation
checkpoint. This matters for how much to trust agreement between instruments: two
signals that share no training data corroborating each other constitutes real evidence; two
heads of the same checkpoint agreeing is not.

### Two optional instruments never got promoted past "evidence"

The fraction head and standalone SPPI are marked in the diagram as auxiliary, not
because they scored badly, but because each promotion attempt broke something else --
neither is part of the main workflow, and the main workflow does not need them to be:

- The fraction head scores far better than segmentation in the residential quadrat
  where it matters most (predicted/true ratio 0.520 vs. 0.023), but forcing it through
  `density.py`'s current candidate population broke `check-density` for reasons traced
  to a pre-existing ground-mount aggregation issue, not the fraction head itself. It is
  not in the published atlas.
- SPPI beats roofclf on nothing (median AUC 0.823 against 0.874 on the same nine-quadrat
  evaluation; roofclf reaches 0.879 on the full 27-quadrat set it is fitted on) and adds nothing as a
  roofclf feature, but an AND-gate (roofclf **and** SPPI agreeing) raises precision by
  4 points at matched recall in the three quadrats where roofclf alone overestimates.
  That AND-gate is what [the evidence
  atlas](#the-outputs-leads-the-evidence-atlas-and-what-else-comes-out) uses as an internal
  floor so the headline figure never reads below what a person has actually mapped plus
  that stricter population -- SPPI's one load-bearing role in the main workflow, short of
  being a standalone instrument in it.

Glint is the one instrument in the "boosts only" lane: it can raise `rank_score`, never
lower it, because a missing glint on a real array (bad viewing geometry, wrong season)
is common, while a glint on something that is not PV is rare. It is optional -- the
leads queue and the evidence atlas both work without it -- but costs nothing to leave on.
See [Solar glint](methods/glint.md) and [Panel pose from glint](results/pv-pose.md).

### Combine, rank, and gate

- **`postprocess`** polygonizes the segmentation raster, joins each candidate to a
  building footprint, and computes `rank_score` -- the ranking the leads queue is sorted
  by. Glint corroboration boosts this score; nothing here demotes a candidate to zero,
  because a false positive on this path costs a mapper seconds and a miss is invisible
  forever.
- **`density`** aggregates the same candidates into per-building, per-cell and
  per-region MWp using three metrics (`*_det`, `*_exp`, `*_cal`) described in
  [Capacity density](methods/density.md). This is segmentation's own **≥ 400 m² total**,
  rooftop and ground-mount; below that floor the recall correction cannot rescue what
  was never detected, and `ge400-roof-capacity` below supersedes its rooftop component
  wherever roofclf has been calibrated.
- **`roof-classifier` → `roofclf-score-national` → `sub400-capacity`** fits `roofclf` on
  the calibration quadrats, scores every VIDA building nationally, then restricts to the
  2,957 of 4,463 cells whose building density matches the quadrats and intersects
  roofclf with SPPI, explicitly refusing to rescale that figure to a national total. It
  covers roofclf's **< 400 m² population**, a separate module (`sub400_capacity.py`) not
  merged into `density.py`.
- **`ge400-roof-capacity`** applies the same domain restriction and coverage-ratio
  conversion to buildings roofclf flags at **or above** 400 m², and its output
  *replaces* `density`'s own rooftop estimate for those buildings, inside those same
  cells only -- measured better there (0.896 AUC against segmentation's 0.73-0.78 on
  identical buildings). Outside the calibrated cells, and for every ground-mount
  candidate, `density`'s own segmentation-based figure stays authoritative. Both
  functions feed the same evidence atlas.
  [The rooftop classifier](methods/roofclf.md) walks the whole path, from a hand-mapped
  square kilometre to the atlas numbers, with a flow chart.
- **`check-density`** (`plausibility.py`) is the only automated check between `density`
  and publishing: a ground-mount-to-rooftop capacity ratio per region and a
  single-cell concentration check, both tuned so the pre-fix 18.3 GWp Pakistan run
  (Gilgit-Baltistan 166 MWp of ground-mount against 0.8 MWp of rooftop) fails and the
  current run passes. It has no CI hook -- `data/` is gitignored, so a human must run it.

### The outputs: leads, the evidence atlas, and what else comes out

Everything converges on the main workflow's two outputs, plus optional extras built from
the same underlying artifacts:

- **MapRoulette leads → OpenStreetMap** (main workflow). Every candidate, ranked, with a
  human verifying each one before it becomes a map edit. False positives are cheap here.
- **The evidence atlas** (main workflow, and this project's **primary output**). Reports
  **Best estimate**, this project's own highest defensible figure: hand-mapped OSM
  installations, plus segmentation's ground-mount detections, plus rooftop &ge; 400 m²
  from roofclf inside its calibrated cells and from segmentation elsewhere, plus
  roofclf-alone density below 400 m², plus a smaller roofclf-and-SPPI extension outside
  the calibrated cells -- OSM overlap removed rather than double-counted throughout, and
  floored per cell at what a person has actually mapped plus the stricter
  roofclf-and-SPPI agreement population. An earlier, looser tier,
  **Ceiling** (a flat-precision, uncalibrated upper bound), was removed on 2026-08-06: a
  later roofclf refit's lower deployment threshold roughly doubled it with no
  accompanying validation, so it had stopped being a meaningful bound.
- **PyPSA-Earth grid CSV** (a byproduct of the main workflow's `density` stage, no extra
  computation). No human in the loop, so every candidate is reweighted by a *measured*
  probability of being real (`configs/calibration/`) before its area counts. See
  [Calibration](methods/calibration.md).
- **Optional extras, same artifacts, not required for the above**: the plain segmentation-
  only capacity atlas (`earthpv atlas` with no `--sub400-*` flags, what a country with no
  mapped quadrats yet gets), the older Low/Central/High/All-PV bracket atlas, the
  rooftop potential/saturation atlas, and the retired config-driven national dashboard
  bundle (`earthpv dashboard`, kept working but no longer built by this site -- Results
  links directly to each standalone artifact page instead).

### Where each stage is documented in depth

| Stage | Main workflow? | Module | Read next |
| --- | --- | --- | --- |
| Labels, buildings | Yes | `labels.py`, `overture.py`, `buildings.py` | [Scale to a new country](reproduce.md#scale-to-a-new-country) |
| Chips, train, infer | Yes -- the segmentation checkpoint every polygon comes from | `chips.py`, `train.py`, `infer.py` | [Detection model](methods/detection.md) |
| postprocess, export | Yes -- every mapping lead, any size | `postprocess.py`, `export.py` | [Segmentation & the building map](methods/segmentation.md) |
| density, calibration | Yes -- segmentation's ≥ 400 m² total, rooftop and ground-mount | `density.py`, `capacity_calibration.py` | [Capacity density](methods/density.md), [Calibration](methods/calibration.md) |
| roofclf, SPPI | Yes -- < 400 m² rooftop, plus ≥ 400 m² rooftop inside the calibrated cells | `roofclf.py`, `sub400_capacity.py`, `roofclf_ge400_capacity.py` | [The rooftop classifier](methods/roofclf.md), [Calibration quadrats](methods/calibration-quadrats.md) |
| Plausibility gate | Yes | `plausibility.py` | this page's [Combine, rank, and gate](#combine-rank-and-gate) section |
| Atlas | Yes -- the evidence atlas, the primary output | `atlas.py` | [Capacity map](results/capacity.md), [Growth](results/growth.md) |
| Glint | Optional -- boosts leads ranking only | `glint.py` | [Solar glint](methods/glint.md), [Panel pose](results/pv-pose.md) |

## Methods

The stages above have their own deep-dive reference pages, kept separate from this
narrative overview because several of them (capacity density especially) are
substantial technical documents in their own right:

| Page | What it covers |
| --- | --- |
| [Detection model](methods/detection.md) | The TerraMind fine-tune, chip jitter and the tiling invariants that keep inference from gridding into false positives |
| [Capacity density](methods/density.md) | The four capacity metrics, recall correction and credible intervals, the sub-400 m² bracket, and the plausibility gate |
| [Solar glint](methods/glint.md) | The physical glint-corroboration signal, with an [image gallery](glint_examples.md) |
| [Calibration](methods/calibration.md) | How raw candidate area becomes a defended, probability-weighted capacity number |
| [Calibration quadrats overview](methods/calibration-quadrats.md) | Current status of every hand-mapped ground-truth quadrat |
| [Quadrat protocol](calibration-mapping-protocol.md) | How to map a new calibration quadrat to the standard the others were held to |

## Comparison with other Pakistan solar-capacity estimates

EarthPV is not the only attempt to size Pakistan's PV fleet, and it is not built to match
any of the others -- it corroborates against OpenStreetMap and MaStR precisely because the
country has no legally complete register of its own. The table below sets the published
**Best estimate** against every other public national estimate found, ordered as in the
project's own writing: by how far a reader can walk each number back to primary data,
not by size.

| Source | Reference period | Capacity estimate | What it covers | Method | Main data sources | Uncertainty / limitations | Traceability |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| **[EarthPV -- Best estimate](results/capacity.md)** | Sentinel-2 composites, mainly Oct 2025 to Jun 2026; atlas snapshot 2026-08-20 | **18.83 GWp** (90% range 16.02 &ndash; 24.36 GWp) | National PV evidence atlas: rooftop and ground-mounted PV the pipeline can detect or infer. Explicitly a modelled screening/estimation layer, not a register. | Hybrid EO pipeline. TerraMind segmentation supplies every ground-mount detection and out-of-domain rooftop ≥400 m². [roofclf](methods/roofclf.md) (a per-building classifier, cross-checked against the zero-training SPPI index) supplies in-domain rooftop ≥400 m² and all rooftop <400 m². Hand-mapped OSM installations are added and overlaps removed. Current Best is about 9% OSM, 8% segmentation, 83% roofclf. | Copernicus Sentinel-2 L2A; OpenStreetMap/Overture solar labels; VIDA Open Buildings; geoBoundaries; the open TerraMind/TerraTorch model stack. Human OSM mappers verify each lead against licensed high-resolution basemaps, but the machine pipeline itself only ever reads open Sentinel-2 (see [Why the loop exists](#why-the-loop-exists)). | The 90% range composes measured uncertainty in the area-to-capacity constants, segmentation precision/recall, and coverage-ratio sensitivity to which calibration quadrats were mapped. **Not a design-based sampling interval** -- the 30 calibration quadrats are purposively hand-picked, not randomly drawn (see [Validity and limitations](methods/validity.md)). roofclf's calibrated domain currently covers 66.3% of national cells, 94.7% of buildings. | Very high. Code, model, training labels, CLI commands, every derived capacity product and a dated release are published; the figure is inspectable down to individual cells and rerunnable (see [Setup New Country](reproduce.md)). The one closed input is the high-resolution imagery human mappers verify against -- it cannot be redistributed, though the model itself never reads it. |
| **[TransitionZero](https://www.transitionzero.org/shedding-light-on-pakistans-distributed-solar-revolution) -- satellite/sampling estimate** | 2025; methodology updated 2025-10-20. Sample imagery had to be under 12 months old, so there is no single national observation date. | **27.5 GW distributed** (range 22.57 &ndash; 32.49 GW, ±18.2%); +1.5 GW TZ-SAM utility-scale ≈ 29 GW total | Distributed rooftop and small ground-mounted PV; utility-scale added separately from TZ-SAM. | Samples 1,038 H3 cells (≈0.1 km² each) from 0.3 m imagery, labels ≈27,000 PV objects with ML plus manual review, then extrapolates rooftop deployment from building size/region/urban class and ground-mounted deployment from agricultural land coverage. | Commercial Pléiades Neo/Airbus 0.3 m imagery; Google Open Buildings; Dynamic World cropland; PRIED local knowledge. Capacity conversion assumes 21% panel efficiency (urban) / 17% (non-urban), a 1.16 tilt correction and a 0.75 panel-coverage factor ([technical methodology](https://blog.transitionzero.org/hubfs/Data%20Products/TZ-RAM/Estimating%20Distributed%20Solar%20in%20Pakistan%20-%20Technical%20Methodology.pdf)). | Sampling and extrapolation, not national detection. Stated major uncertainties: labelling confidence, imagery availability/sampling bias, panel efficiency, external datasets, tilt. Some regions lack recent PNEO coverage. | Medium. The methodology and assumptions are unusually well documented, but the decisive 0.3 m imagery is proprietary, so the full sampled-imagery/label corpus behind the 27.5 GW figure cannot be independently rerun. |
| **PRIED -- national survey estimate** | 2025 study, published 2025-10 | **33.35 GW distributed**; +0.68 GW utility-scale ≈ 34 GW total ([TransitionZero](https://www.transitionzero.org/shedding-light-on-pakistans-distributed-solar-revolution)) | Residential, commercial, industrial and agricultural PV, including net-metered, behind-the-meter and off-grid systems. | National stratified random survey: 5,320 respondents across the four provinces and Islamabad, sectoral and rural/urban quotas, system size and installation year self-reported, results weighted and extrapolated nationally. | Primary household/business/agricultural survey; the 2023 Pakistan Bureau of Statistics census for the sampling frame; Kobo Toolbox, GPS verification and field validation. | Stated 95% confidence level on the sampling design, but no published national GW confidence interval around 33.35 GW. Survey reporting, system-size recall and national expansion weights are error sources distinct from satellite mapping. | Medium. Sampling and field procedures are described and sectoral results are published, but the respondent-level microdata and full estimation pipeline are not exposed in the cited material. |
| **[Renewables First / Ember](https://uploads.renewablesfirst.org/The%20solarisation%20of%20Pakistan%E2%80%99s%20energy%20economy.pdf) -- triangulated estimate** | 2025-06-30, end of FY25; report published 2026-06-25 | **≈38 GW distributed PV**; ≈27 GW of it added between FY23 and FY25 | Distributed customer-owned solar: about 44% residential, 26% industry, 21% agriculture, 9% commercial. | Bottom-up triangulation across field information, market consultations and national statistics, explicitly weighing TransitionZero's independent 27.5 GW satellite estimate and PRIED's ≈33 GW survey estimate alongside its own inputs. | Renewables First CORE fieldwork; the TransitionZero and PRIED estimates above; Ember's Chinese customs/module-export data; market consultations and national statistics. Generation calculations additionally assume a 16.71% capacity factor and 10% curtailment for behind-the-meter/off-grid systems. | No published statistical uncertainty interval for the 38 GW figure, and the exact transformation from its inputs to 38 GW is less transparent than the TransitionZero or EarthPV pipelines. Better read as an evidence-synthesis judgement than a directly observed map. | Medium-low for reproducing the number, good for source attribution. The constituent evidence is named and mostly public, but an independent analyst cannot reconstruct 38 GW end to end from the report alone. |
| **[Ember](https://ember-energy.org/latest-insights/the-solarisation-of-pakistans-energy-economy/) -- Chinese module-export benchmark** | Cumulative to 2025-06 (47 GW); ≈50 GW by 2025-08 | **47 &ndash; 50 GW of panels imported into Pakistan -- not installed capacity** | Physical module trade entering the country: panels that may since have been installed, stored, held in transit, or used to replace failed units. | Aggregation of Chinese solar-module export/customs statistics. | Ember's Chinese solar export/customs dataset. | An upper-bound market-flow benchmark, not a map or a measurement of operational PV. Not every imported panel has necessarily been installed yet. | High for the trade statistic itself; low as evidence of installed capacity. The underlying customs data is straightforward and auditable, but converting imports to operational MW needs assumptions about inventory and installation lag that this benchmark does not supply. |
| **Pakistan official registered/on-grid figures** | ≈2025 | **≈6.7 GW** (≈6 GW net-metered + 0.68 GW utility-scale, [TransitionZero](https://www.transitionzero.org/shedding-light-on-pakistans-distributed-solar-revolution)) | Registered net-metered consumer PV plus identified utility-scale projects. Excludes unregistered behind-the-meter and off-grid systems, which every row above suggests is most of the fleet. | Administrative/regulatory reporting. | Pakistan Ministry of Energy / PPIB and net-metering records. | High confidence for what is registered, very incomplete coverage of national deployment. An administrative lower bound, not a competing total. | High for individual registered systems, low as a measure of national PV stock -- the system definition deliberately excludes most of the disputed distributed-solar population. |

Read across the rows, the three methods built independently of EarthPV (TransitionZero's
satellite sample, PRIED's household survey, and the Renewables First/Ember triangulation
that folds in both) cluster in a 27.5 to 38 GW distributed range -- five to six times the
≈6.7 GW that is actually registered, and consistent with Chinese customs data showing tens
of gigawatts of panels imported. EarthPV's own 18.83 GWp (90% range 16.02 to 24.36) sits
below that cluster rather than inside it: its upper bound approaches TransitionZero's lower
bound but does not reach PRIED's or Renewables First's central estimates. [Validity and
limitations](methods/validity.md) gives the two most likely structural reasons, rather than
a reconciliation: roofclf drives about 83% of Best, and Rule-1 completeness on its
calibration quadrats is epoch-relative, so the newest installations are structurally
under-counted regardless of mapping effort; and the coverage-ratio fit is itself resampled
over 30 purposively selected quadrats whose predicted-to-true adoption ratio has
historically spanned 0.2x to 5x, an uncertainty the published 90% range does not fully
price because it cannot measure bias in the sampling frame itself. None of the methods in
this table was designed to reproduce another, so the more informative comparison is not
which number is largest but which one a reader can walk back to primary data -- the
Traceability column, not the Capacity estimate column, is where EarthPV's own contribution
actually sits.

## Experiments and open questions

Most of what has been tried in this project did not ship, and the negative results are the
map of where Sentinel-2's 10 m resolution limit actually sits. That record has its own page
rather than a section here:

- **[Experiments](experiments.md)** -- the full register, with a verdict on each and the
  measurement behind it. Everything from the in-domain training chips that tripled recall to
  the three super-resolution variants that did nothing, plus links to every deep write-up.
- **[Open questions](open-questions.md)** -- what is unresolved, ranked by expected value
  over cost, and the known defects that are carried on purpose rather than pending.
