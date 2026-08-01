# Architecture

[Workflow](workflow.md) tells the human story: OpenStreetMap labels a model, the model
proposes leads, mappers dispose of them, and verified installations become the next
round of labels. This page is the technical complement: what actually reads what, stage
by stage, from raw Sentinel-2 pixels to the two published products. Each box below is a
real module or CLI stage; the [Reproduce](reproduce.md) runbook runs them in this order.

![How raw data becomes a mapping lead and a capacity number: Sentinel-2 composites and OpenStreetMap labels train a TerraMind checkpoint; five inference instruments (segmentation, the fraction head, glint, SPPI, roofclf) read the same imagery; postprocess, density and the sub-400 square metre bracket combine their outputs; a plausibility gate checks the capacity numbers; and four outputs follow: MapRoulette leads back to OpenStreetMap, a capacity atlas, a PyPSA-Earth grid CSV, and an evidence atlas.](assets/figures/architecture.svg#only-light)
![How raw data becomes a mapping lead and a capacity number: Sentinel-2 composites and OpenStreetMap labels train a TerraMind checkpoint; five inference instruments (segmentation, the fraction head, glint, SPPI, roofclf) read the same imagery; postprocess, density and the sub-400 square metre bracket combine their outputs; a plausibility gate checks the capacity numbers; and four outputs follow: MapRoulette leads back to OpenStreetMap, a capacity atlas, a PyPSA-Earth grid CSV, and an evidence atlas.](assets/figures/architecture.dark.svg#only-dark)

## Raw data, once

Three inputs, each reused everywhere downstream rather than re-fetched per stage:

- **Sentinel-2 L2A** — 10-band dry-season composites (`local_source.py`'s
  `CompositeIndex` where a sibling project already downloaded a tile, otherwise
  `compose.py` builds one on demand from Planetary Computer STAC). Every instrument in
  the inference lane reads from this same set of rasters.
- **OSM / Overture solar labels** — mapped installations from Overture's periodic
  snapshot, or a live Overpass pull for a region being freshly mapped
  (`earthpv overpass-labels`). This is both the training signal and, through the
  flywheel, the thing the pipeline's own output eventually feeds back into.
- **VIDA / Overture buildings** — imagery-derived footprints (`buildings.py`), which
  matter because they include small, unmapped structures OpenStreetMap does not yet
  have. Buildings feed three downstream consumers directly: `postprocess`'s building
  join, `roofclf`'s per-building features, and the sub-400 m² bracket's domain
  restriction. The diagram omits those three arrows to stay legible; the dependency is
  real in all three places.

## Train once, then five instruments read the same pixels

`chips` cuts jittered training windows and burns label polygons into per-pixel masks;
`train` fine-tunes `terramind_v1_tiny` through TerraTorch into a checkpoint that
monitors validation mIoU. See [Detection model](methods/detection.md) for the model
internals and the two invariants (chip jitter, Hann-tapered overlap-add) that keep
inference from tiling into a grid of false positives.

From there, five instruments read the same Sentinel-2 composites, but they are not
five versions of the same thing — they differ in what they need to exist first:

| Instrument | Needs the trained checkpoint? | What it outputs |
| --- | --- | --- |
| **Segmentation raster** (`infer`) | Yes, the primary one | per-pixel PV probability; the only instrument with a polygon and a defended ≥ 400 m² floor |
| **Fraction head** | Yes, a separately trained checkpoint | per-pixel PV *coverage fraction*; drops the polygon, aims at sub-400 m² signal a segmentation threshold cannot see |
| **Glint matched filter** | No | specular-flash geometry consistent with one fixed panel plane; a physical corroboration, not a probability |
| **SPPI** | No, a fixed spectral formula | a zero-training index, cross-validated against the same ground truth as roofclf |
| **roofclf** | No, a separate lightweight classifier | per-building "does this roof carry PV," trained on exhaustively mapped calibration quadrats |

Glint and SPPI need no model fit at all. roofclf is trained, but on a different, much
smaller, hand-labelled corpus (the calibration quadrats), not on the segmentation
checkpoint. This matters for how much to trust agreement between instruments: two
signals that share no training data corroborating each other is real evidence; two
heads of the same checkpoint agreeing is not.

## Two independent instruments never get promoted past "evidence"

The fraction head and SPPI are marked in the diagram as auxiliary, not because they
scored badly, but because each promotion attempt broke something else:

- The fraction head scores far better than segmentation in the residential quadrat
  where it matters most (predicted/true ratio 0.520 vs. 0.023), but forcing it through
  `density.py`'s current candidate population broke `check-density` for reasons traced
  to a pre-existing ground-mount aggregation issue, not the fraction head itself. It is
  not in the published atlas.
- SPPI beats roofclf on nothing (median AUC 0.823 vs. 0.874) and adds nothing as a
  roofclf feature, but an AND-gate (roofclf **and** SPPI agreeing) raises precision by
  4 points at matched recall in the three quadrats where roofclf alone overestimates.
  That AND-gate is exactly what the Verified tier of the [evidence atlas](#the-two-published-products) uses.

Glint is the one instrument in the "boosts only" lane: it can raise `rank_score`, never
lower it, because a missing glint on a real array (bad viewing geometry, wrong season)
is common, while a glint on something that is not PV is rare. See
[Solar glint](methods/glint.md) and [Panel pose from glint](results/pv-pose.md).

## Combine, rank, and gate

- **`postprocess`** polygonizes the segmentation raster, joins each candidate to a
  building footprint, and computes `rank_score` — the ranking the leads queue is sorted
  by. Glint corroboration boosts this score; nothing here demotes a candidate to zero,
  because a false positive on this path costs a mapper seconds and a miss is invisible
  forever.
- **`density`** aggregates the same candidates into per-building, per-cell and
  per-region MWp using three metrics (`*_det`, `*_exp`, `*_cal`) described in
  [Capacity density](methods/density.md). This is the ≥ 400 m² product; below that floor
  the recall correction cannot rescue what was never detected.
- **the sub-400 m² bracket** (`sub400_capacity.py`) is a separate, domain-restricted
  product: it intersects roofclf and SPPI over the ~93 cells whose building density
  matches the calibration quadrats, explicitly refusing to rescale that figure to a
  national total. It is not merged into `density.py`.
- **`check-density`** (`plausibility.py`) is the only automated check between `density`
  and publishing: a ground-mount-to-rooftop capacity ratio per region and a
  single-cell concentration check, both tuned so the pre-fix 18.3 GWp Pakistan run
  (Gilgit-Baltistan 166 MWp of ground-mount against 0.8 MWp of rooftop) fails and the
  current run passes. It has no CI hook — `data/` is gitignored, so a human must run it.

## The two published products

Everything converges on four outputs, split by tolerance for false positives:

- **MapRoulette leads → OpenStreetMap.** Every candidate, ranked, with a human
  verifying each one before it becomes a map edit. False positives are cheap here.
- **Capacity atlas / national dashboard**, **PyPSA-Earth grid CSV.** No human in the
  loop, so every candidate is reweighted by a *measured* probability of being real
  (`configs/calibration/`) before its area counts. See
  [Calibration](methods/calibration.md).
- **Evidence atlas.** The newest output (2026-08-01), and the place the sub-400 m²
  bracket and the ≥ 400 m² total actually meet. It reports three tiers by *standard of
  proof* rather than three point estimates on one scale: **Verified** (hand-mapped OSM
  plus the roofclf-and-SPPI agreement set), **Best estimate** (recall-corrected
  ≥ 400 m² detections plus roofclf-alone density, OSM overlap removed rather than
  double-counted), and **Ceiling** (a flat-precision, uncalibrated upper bound, with the
  known ≥ 400 m² total added on top rather than shown alone).

## Where each stage is documented in depth

| Stage | Module | Read next |
| --- | --- | --- |
| Labels, buildings | `labels.py`, `overture.py`, `buildings.py` | [Scale to a new country](scale.md) |
| Chips, train, infer | `chips.py`, `train.py`, `infer.py` | [Detection model](methods/detection.md) |
| Glint | `glint.py` | [Solar glint](methods/glint.md), [Panel pose](results/pv-pose.md) |
| roofclf, SPPI | `roofclf.py` | [Calibration quadrats](methods/calibration-quadrats.md), [Roof classifier national deployment](issues/roofclf-national-deployment-and-temporal-features.md) |
| postprocess, export | `postprocess.py`, `export.py` | [Mapping leads](results/leads.md) |
| density, calibration | `density.py`, `capacity_calibration.py` | [Capacity density](methods/density.md), [Calibration](methods/calibration.md) |
| Plausibility gate | `plausibility.py` | this page's [Combine, rank, and gate](#combine-rank-and-gate) section |
| Atlas, dashboard | `atlas.py`, `dashboard.py` | [Capacity map](results/capacity.md), [Dashboards](dashboards/index.md) |
