# How it works

[Workflow](#workflow) tells the human story: how a Sentinel-2 pixel becomes a verified
OpenStreetMap feature. [Architecture](#architecture) is the technical complement: what
actually reads what, stage by stage, including [the main workflow and what's
optional](#the-main-workflow-and-whats-optional) -- the project's default pipeline
(segmentation for arrays &ge; 400 m², `roofclf` for everything smaller, combined into
the evidence atlas) versus everything else, kept but not required.
[Methods](#methods) links out to the deep-dive reference pages for each stage.
[Experiments](#experiments) is the honest record of what was tried, including everything
that did not work.

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
  flywheel, the thing the pipeline's own output eventually feeds back into.
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
| **Segmentation raster** (`infer`) | **Yes -- the &ge; 400 m² half** | Yes, the primary one | per-pixel PV probability; the only instrument with a polygon and a defended ≥ 400 m² floor |
| **roofclf** | **Yes -- the < 400 m² half** | No, a separate lightweight classifier | per-building "does this roof carry PV," trained on exhaustively mapped calibration quadrats |
| **SPPI** | Partially -- cross-checks roofclf for the evidence atlas's Verified tier | No, a fixed spectral formula | a zero-training index, cross-validated against the same ground truth as roofclf |
| **Glint matched filter** | Optional -- boosts the leads ranking only | No | specular-flash geometry consistent with one fixed panel plane; a physical corroboration, not a probability |
| **Fraction head** | Optional, not promoted (see below) | Yes, a separately trained checkpoint | per-pixel PV *coverage fraction*; drops the polygon, aims at sub-400 m² signal a segmentation threshold cannot see |

Glint and SPPI need no model fit at all. roofclf is trained, but on a different, much
smaller, hand-labelled corpus (the calibration quadrats), not on the segmentation
checkpoint. This matters for how much to trust agreement between instruments: two
signals that share no training data corroborating each other is real evidence; two
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
- SPPI beats roofclf on nothing (median AUC 0.823 vs. 0.874) and adds nothing as a
  roofclf feature, but an AND-gate (roofclf **and** SPPI agreeing) raises precision by
  4 points at matched recall in the three quadrats where roofclf alone overestimates.
  That AND-gate is exactly what the Verified tier of [the evidence
  atlas](#the-main-workflows-output-the-evidence-atlas) uses -- SPPI's one load-bearing
  role in the main workflow, short of being a standalone instrument in it.

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
  [Capacity density](methods/density.md). This is the **main workflow's ≥ 400 m² half**;
  below that floor the recall correction cannot rescue what was never detected.
- **`roof-classifier` → `roofclf-score-national` → `sub400-capacity`** is the **main
  workflow's < 400 m² half**: fit `roofclf` on the calibration quadrats, score every
  VIDA building nationally, then restrict to the ~93 cells whose building density
  matches the quadrats and intersect roofclf with SPPI, explicitly refusing to rescale
  that figure to a national total. It is a separate module (`sub400_capacity.py`), not
  merged into `density.py`, but both feed the same evidence atlas.
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
  tiers by *standard of proof* rather than point estimates on one scale: **Verified**
  (hand-mapped OSM plus the roofclf-and-SPPI agreement set) and **Best estimate**
  (recall-corrected ≥ 400 m² detections plus roofclf-alone density, OSM overlap removed
  rather than double-counted). A third tier, **Ceiling** (a flat-precision, uncalibrated
  upper bound), was removed 2026-08-06: a later roofclf refit's lower deployment
  threshold roughly doubled it with no accompanying validation, so it had stopped being
  a meaningful bound.
- **PyPSA-Earth grid CSV** (a byproduct of the main workflow's `density` stage, no extra
  computation). No human in the loop, so every candidate is reweighted by a *measured*
  probability of being real (`configs/calibration/`) before its area counts. See
  [Calibration](methods/calibration.md).
- **Optional extras, same artifacts, not required for the above**: the plain segmentation-
  only capacity atlas (`earthpv atlas` with no `--sub400-*` flags, what a country with no
  mapped quadrats yet gets), the older Low/Central/High/All-PV bracket atlas, the
  rooftop potential/saturation atlas, and the retired config-driven national dashboard
  bundle (kept working, no longer built by this site -- see CLAUDE.md's "National
  dashboards" note).

### Where each stage is documented in depth

| Stage | Main workflow? | Module | Read next |
| --- | --- | --- | --- |
| Labels, buildings | Yes | `labels.py`, `overture.py`, `buildings.py` | [Scale to a new country](reproduce.md#scale-to-a-new-country) |
| Chips, train, infer | Yes -- ≥ 400 m² half | `chips.py`, `train.py`, `infer.py` | [Detection model](methods/detection.md) |
| postprocess, export | Yes -- ≥ 400 m² half | `postprocess.py`, `export.py` | [Mapping leads](results/leads.md) |
| density, calibration | Yes -- ≥ 400 m² half | `density.py`, `capacity_calibration.py` | [Capacity density](methods/density.md), [Calibration](methods/calibration.md) |
| roofclf, SPPI | Yes -- < 400 m² half | `roofclf.py`, `sub400_capacity.py` | [Calibration quadrats](methods/calibration-quadrats.md), [Roof classifier national deployment](issues/roofclf-national-deployment-and-temporal-features.md) |
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

## Experiments

Most of what has been tried here did not work. That is worth writing down, because the
negative results are the map of where the 10 m resolution limit actually is, and because
every one of them cost real compute that nobody else needs to spend again.

Every experiment below has runnable code in the repository. Nothing was removed on
failure.

### Summary

| Experiment | Outcome | One line |
| --- | --- | --- |
| In-domain Pakistani training chips | <span class="outcome works">deployed</span> | Tripled large-array recall in Punjab. The single biggest lever found. |
| Building prior from VIDA Open Buildings | <span class="outcome works">deployed</span> | Makes "no building nearby" a usable false-positive signal. |
| Solar-glint corroboration | <span class="outcome works">deployed</span> | Calibrated likelihood ratios per size bucket, reward-only. |
| Tile-major glint fetching | <span class="outcome works">deployed</span> | 22x faster, numerically identical output. |
| Pre-boom epoch check | <span class="outcome works">deployed</span> | Persistent 2021 signal demotes a candidate. |
| Vegetation veto | <span class="outcome works">deployed</span> | 596 of 5,132 leads vetoed, and specifically the right ones. |
| Fraction-regression head | <span class="outcome works">deployed</span> | Municipal correlation 0.740 against MaStR, versus 0.499 for segmentation. |
| Recall correction and credible intervals | <span class="outcome works">deployed</span> | Turned a structural floor into an estimate with a stated interval. |
| Per-pixel glint amplitude trim | <span class="outcome mixed">narrow win</span> | Moves pixel IoU slightly; threshold gating by glint does not. |
| Glint as a direct detector | <span class="outcome mixed">mixed</span> | About 9 percent on model leads, about 1 percent on random buildings. |
| Ground-truth calibration quadrats | <span class="outcome open">in progress</span> | Five boxes mapped of a planned 25 to 35. |
| Two-season 20-band stacking | <span class="outcome negative">negative</span> | No recall gain anywhere; slightly worse on large arrays. |
| Sentinel-1 corner reflector | <span class="outcome negative">negative</span> | Backscatter enhancement indistinguishable from speckle. |
| Cell-aggregate glint density | <span class="outcome negative">negative</span> | Wrong statistic; a per-pixel version is the untried follow-up. |
| Missed-installation glint recovery | <span class="outcome negative">negative</span> | Control false-validation rate exceeded the recovery rate. |
| Roof-axis orientation prior | <span class="outcome negative">negative</span> | Flat concrete roofs do not constrain a tilt frame's azimuth. |
| Standard-pose matched filter | <span class="outcome negative">not recommended</span> | The densest pose bin covers under 10 percent of installations. |
| Super-resolution, three variants | <span class="outcome negative">negative</span> | No gain, and hallucination risk on the detection task. |
| Time-series step detection below 400 m<sup>2</sup> | <span class="outcome mixed">partial</span> | First non-zero recall under 500 m<sup>2</sup>, but the capacity claim failed its control. |
| Epoch jump as a recall signal | <span class="outcome open">designed</span> | Uses the unused positive half of the epoch comparison. |

### What worked

#### In-domain training chips

Training on Germany alone gave 0.18 per-installation recall at or above 1,000 m<sup>2</sup>
in Punjab. Adding 274 Punjabi chips, merged with `scripts/merge_chip_index.py` and
oversampled twice so Germany's larger chip count does not swamp them, took that to 0.55.
Nothing else tried has moved the domain gap comparably, which is the empirical argument
for the [mapping flywheel](#workflow): more verified Pakistani installations are worth
more than any architectural change tested here.

#### The vegetation veto, and why the obvious version fails

Manual review of countryside leads found many green fields flagged as PV. Measuring NDVI
on the composite the model actually read does **not** separate them: 150 suspect leads had
a median NDVI of 0.10 there, statistically indistinguishable from confirmed PV's 0.04.
The field a validator sees as green today was dark fallow, harvested or flooded paddy soil
when the dry-season median was built. This is a season mismatch, not a spectral confusion
the model could have avoided.

The instrument that does discriminate is the annual vegetation cycle: every crop field
greens up at some point in the year and a panel never does. A free interim version takes
the maximum NDVI across every composite epoch already on disk; the thorough version,
`scripts/veg_annual_ndvi.py`, samples a year of scenes per lead and reports the 95th
percentile. A positive control on ten leads the free version had already flagged found
eight crossing 0.3 within the year, confirming the catches are real vegetation.

### What did not work

#### Two-season stacking

A 20-band two-season stack (dry-season base plus a contrast season per cell) was built to
push detection below 1,000 m<sup>2</sup>, on the theory that PV is spectrally stable across
seasons while vegetation and roofs swing. The full path is wired and TerraMind duplicates
its pretrained patch embedding into both season slots.

On the same Punjab validation installations, recall for the 1,000+, 500 to 1,000 and 250 to
500 m<sup>2</sup> buckets was 0.51, 0.17 and 0.14 seasonal, versus 0.55, 0.16 and 0.14 for
the production 10-band model. Small buckets unchanged within noise, large slightly worse.
Likely causes: too few in-domain chips to learn a temporal signal, the tiny backbone's
capacity, and post-monsoon versus dry season simply not differing enough in arid Pakistan.

#### Sentinel-1 corner reflection

A tilted PV row over flat ground forms a dihedral corner reflector, which should produce
strong radar backscatter, persistently, since Sentinel-1's orbit geometry is fixed
year-round and radar is not blocked by cloud. Tested on 17 glint-validated installations
spanning the full observed azimuth range, pulling two years of Sentinel-1 RTC.

Median enhancement rate was 3.2 percent (VV) and 1.7 percent (VH) of scenes, within plain
speckle noise. Critically, ascending and descending passes gave near-identical rates,
1.7 versus 1.8 percent, with no correlation to the implied row axis. A real corner
reflector should show sharp asymmetry between orbit headings, and its absence says this
is not a usable channel at these sites through a simple per-footprint aggregate.

A lighter use of Sentinel-1 remains untried and is **not** ruled out by this: multi-temporal
backscatter *variance* separates permanent structures from seasonally changing fields, and
greenhouse metal frames give a bright return, the opposite of PV, making radar a cheap
post-hoc false-positive filter.

#### Two glint routes to density, both negative

**Cell-aggregate spike counting.** Small residential arrays are individually sub-pixel and
rarely glint alone, so the hypothesis was that a dense neighbourhood of independently
oriented arrays would union their narrow glint windows into a high combined spike count.
Tested against a fully mapped Lahore cluster with up to 120 separately mapped generators in
a single 300 m block: zero-PV control cells averaged 1.0 spike, PV-bearing cells 1.45,
medians tied at 1.0, and the 120-installation hotspot showed one spike in two years.
This is probably a methodology failure rather than a physics one. A 90th-percentile
statistic over a whole cell only moves if roughly 10 percent of the cell brightens at once,
and even every installation in the busiest hotspot glinting simultaneously covers under
half of that. The correct next test is a per-pixel anomaly count, each pixel against its
own baseline, which was not attempted.

**Recovering missed installations.** Find real mapped installations the thresholded mask
misses entirely, glint-validate them, and add their area back. Tested on 43 missed German
and 208 missed Lahore installations against matched non-PV controls. Both fail the one
thing this needs to do: Germany's control false-validation rate of 20.8 percent is
uncomfortably close to the 37.2 percent rate on missed installations, and Lahore's control
rate of 8.7 percent is *higher* than its 5.3 percent missed rate, which is worse than
chance. Recovered area was 10.8 percent of the Lahore gap even before accounting for that.

#### Super-resolution

Three feasibility tests, run in sequence by `scripts/run_sr_experiments.sh`: guided fusion
of the 20 m bands to 10 m, multi-image super-resolution from repeated overpasses, and
internal-learning single-image super-resolution. None improved detection, and the last
carries an obvious hallucination risk on a task whose whole output is "is there a panel
here". Scripts are kept for future reference.

### The partial result worth watching

#### Time-series step detection below the floor

The Lahore calibration box contains 1,034 mapped installations with a median area near
50 m<sup>2</sup>, at which the trained model reads 0.000 probability on 99.8 percent of true
footprints and glint validates zero of 1,021. Static appearance is exhausted. But
*appearance in time* is a different signal: a panel installed in 2023 is a step change in a
dense per-pixel Sentinel-2 series, even if no single scene shows it.

`scripts/pv_step_signal.py` removes common-mode atmosphere against reference pixels, guards
co-registration by phase correlation, learns the PV installation change vector spectrally
rather than assuming a fixed index, deseasonalises with annual harmonics and per-orbit
offsets, and scans for the best breakpoint per pixel.

**The good part.** Area under the ROC curve of 0.875 and 0.74 on held-out halves, against
0.50 for the model on the same footprints. That is the first non-zero discrimination
anyone here has achieved below 500 m<sup>2</sup>.

**The part that failed.** Converting that into a city-scale unmapped-capacity number was
**rejected by its own control**. The method's estimate of unmapped area per built-up pixel
sat inside the false-area floor measured on two PV-free cropland control cubes, so
`usable_for_unmapped_total` is false and nothing in the totals block is quotable as
capacity. What survives is the ranking: step-leads are defensible as a lead ordering, and
recovery on *known* PV is licensed separately.

Two landmines are documented for anyone continuing: a propensity confound (the households
that install panels differ systematically from those that do not, in ways visible from
space) and duplicated Sentinel-2 baseline products that silently double-count dates.

### Open opportunities

Ranked by expected value over cost.

1. **Keep turning the flywheel.** More human-verified Pakistani installations, retrain,
   measure. Everything in the "worked" column above is smaller than this.
2. **Finish the quadrat programme.** Five of a planned 25 to 35 boxes are mapped. Enough
   quadrats replace optimistic snapshot recall with measured recall, which is currently the
   widest term in the capacity interval. Multan is the highest-priority target: confirmed
   solar-dense, with zero OpenStreetMap solar features.
3. **Manual review of the small bins.** In 100 to 500 m<sup>2</sup>, `p_real` is only pinned
   to [0.10, 0.89]. Twenty verdicts per bin collapse that.
4. **[Epoch jump as a recall signal](issues/epoch-jump-recall-signal.md).** The pre-boom
   comparison is currently only used to demote. A building below the candidate threshold
   today whose PV probability genuinely rose since 2021 is stronger evidence than either
   epoch alone, and the imagery already exists at zero extra network cost.
5. **Per-pixel glint anomaly counting**, the statistic the cell-aggregate test should have
   used.
6. **Sentinel-1 backscatter variance** as a false-positive filter, distinct from the
   corner-reflector idea that failed.
7. **Per-locality pose calibration**, fitting a local panel pose from whatever
   installations a subdivision already has, rather than assuming a national standard pose.
8. **Growth as a product.** Per-epoch density estimates make capacity a time series, so the
   2022 to 2026 boom becomes measurable per district and independently checkable against
   NEPRA net-metering registrations and customs import series.
