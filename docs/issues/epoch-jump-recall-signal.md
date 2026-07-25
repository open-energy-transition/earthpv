# Epoch-jump as a recall signal for density (draft, not yet implemented)

## Motivation

`postprocess.add_epoch_prior` already runs the trained segmentation checkpoint over
a pre-boom composite (`composite_1`, window `2021-10-01:2022-01-24`) at every
candidate, purely as a **negative** signal: a candidate bright in both epochs is
almost certainly a persistent non-PV feature (bright roof, concrete, sand), and its
`rank_score` gets downweighted accordingly. That comparison is never used
positively. The unused half is exactly what would help the recall gap surfaced
comparing our recall-corrected 18.3 GWp against Ember/import-derived Pakistan solar
estimates (best current read: real, mostly attributable to (a) standalone
agricultural/ground-mount solar in cells that never get composited at all -- see
`compose.py`'s `min_buildings=1000` gate -- and (b) weak recall on small distributed
rooftop, exactly the size class this session's Lahore calibration box measured the
model at ~0.000 probability on 99.8% of true footprints).

**The idea:** a building whose current-epoch probability is *below* the candidate
threshold but that shows a genuine appearance of PV-like signal since 2021-22 is
stronger, more specific evidence of a real (missed) installation than either epoch
alone. Sentinel-2 country-wide pre-boom coverage now exists (4,187/4,473 cells;
backfill of the remaining 286 in progress, `earthpv-preboom-compose-backfill` unit)
at zero extra network cost for the imagery -- only a GPU inference pass and some
new aggregation logic are needed.

## Why this is more attribution-safe than a raw brightness/NDVI difference

`preboom_prob` and `current_prob` are both **the same trained PV classifier's own
probability outputs**, not raw reflectance. A "jump" here means *the model itself
increasingly thinks this looks like PV over time*, not merely "this pixel got
brighter" -- which already rules out most of the generic confounders (new
construction, roof repainting, land clearing) that would fool a naive spectral
difference, since none of those necessarily push the *PV-probability* channel up
without also having some PV-like texture/spectral signature. It is not immune to
false positives (a new bright rooftop with panel-like polygon texture could still
score both epochs' classifier highly on epoch 2 alone) -- see validation plan below.

## Proposed mechanism

1. **New per-building metric**, computed in `process_cell` alongside the existing
   `pv_area_det_m2`/`pv_area_exp_m2`: for every building already read via the
   current-epoch raster, also sample the pre-boom raster over the same footprint
   (same VIDA polygon, same window) and compute
   `jump = max(0, current_max_prob - preboom_max_prob)`
   (or a probability-weighted-area analogue of `pv_area_exp_m2`, run on the delta
   raster instead of the raw current one -- reuse the exact same windowed-read/
   rasterize code path, just called twice per cell with two raster sources).
2. **Recall rescue for sub-threshold buildings.** Today, `_candidate_uncertainty`'s
   Horvitz-Thompson recall correction (`density.py:449`) only ever sees buildings
   already in `candidates.parquet` (i.e. that crossed the *current-epoch* detection
   threshold somewhere), and its recall weight (`capacity_calibration.candidate_recall`)
   is purely a function of size bin -- blind to any per-building corroborating
   evidence. Buildings that never crossed threshold currently contribute nothing
   beyond the blanket size-based recall multiplier applied to *other* (detected)
   candidates in their bin.

   Proposal: for buildings with `current_prob` between a low floor (e.g. 0.05 --
   "some signal, not nothing") and the candidate threshold (0.3), with
   `jump` above a validated cutoff, promote them into a parallel population
   (`source="jump_rescue"`) that feeds the *same* `_candidate_uncertainty` machinery
   (own `p_real`/`recall` weights from a **separate** calibration table fit
   specifically on jump-rescued cases -- do not reuse the detected-candidate
   calibration table for a population selected on a different signal without
   re-measuring precision on it). Their contribution surfaces as a **new, explicit**
   metric (`pv_area_jump_m2` / `est_mwp_jump`, plus a `_jump` credible interval),
   additive to but visually and numerically separate from `est_mwp_rc` in the atlas
   and meta.json -- never silently folded into the headline number.

## Validation plan (required before touching any headline number)

Exactly the discipline this project already applies to glint and calibration boxes
-- report an honest number either way, don't round up:

- **Calibration boxes** ([[earthpv-calibration-box-recall]]): do jump-rescued
  buildings in Lahore/Multan/Sundar/etc. actually correspond to the boxes' known,
  fully-mapped installations? This is the cleanest possible check -- real counted
  ground truth, not another inference.
- **Glint cross-check**: does `jump_rescue` status predict `glint_consistent` at a
  higher rate than a random sub-threshold building of the same size? Two
  independent physical/temporal channels agreeing is strong evidence; neither
  alone is proof.
- **False-positive stress test**: run the same jump computation over a sample of
  buildings known to be non-PV (e.g. hard-negative centers from this session's
  bi-temporal/vegetation/road mining) and confirm the jump rate there is low --
  otherwise the "attribution-safe" argument above is wrong in practice, not just
  in theory.

## Cost

- Compose: zero extra (pre-boom imagery backfill already in flight for unrelated
  reasons -- epoch-clean FP rescoring).
- Inference: one more GPU pass over the pre-boom composites is already required
  anyway (`infer --index 1`, not currently resumable per-cell, so it reruns all
  ~4,473 cells regardless of how many are new -- a few hours on the GTX 1060,
  same order as the original pre-boom run).
- New code: a windowed-read helper reused from the existing `pv_area_exp_m2` path
  (small), a new calibration table fit for the jump-rescue population (needs a
  labeled validation sample -- the calibration boxes are a ready-made start), and
  new aggregation columns in `density.py`/`atlas.py` (moderate, mirrors the
  existing `*_rc` plumbing closely).

## Status

Draft only. Do not implement the recall-rescue promotion or touch `est_mwp_rc`
until the validation plan above has run against real ground truth and the false-
positive stress test comes back clean.
