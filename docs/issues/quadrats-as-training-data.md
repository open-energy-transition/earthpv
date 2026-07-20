# Use calibration quadrats as training data, not just post-hoc correction

**Labels:** enhancement, model, calibration

## Problem

The calibration quadrats (`docs/calibration-mapping-protocol.md`: ~25–35
exhaustively mapped 1–4 km² areas across 6 Pakistani landscape strata) are
currently planned for one purpose only: post-hoc correction of the density
model's output per stratum. That under-uses the most expensive data we will
have. Exhaustive mapping means every quadrat building carries a verified
has-PV / has-no-PV label — precisely the supervision the model lacks in its
measured failure regime (<500 m² installations: 6–16% detection).

## Proposal

Train a **per-building PV classifier** on the quadrat labels, as a second
model alongside (not replacing) the segmentation model:

1. **Unit of prediction: the building footprint**, not the pixel. For
   sub-pixel roofs, "does this building have PV?" is a far easier learning
   problem than tracing panel outlines at 10 m.
2. **Features: temporal, not single-composite.** Per-building Sentinel-2
   time-series statistics over ~2 years — the same per-scene machinery the
   glint method uses (`src/earthpv/glint.py`) — e.g. spike counts, reflectance
   percentiles and their stability, NDVI trajectory, plus footprint area and
   stratum covariates. External evidence this direction pays: multi-revisit
   fusion beat single-composite segmentation by 5–17% IoU on the analogous
   substation task (arXiv:2409.17363), and Google reached 79% building mIoU
   from Sentinel-2 by distilling high-res-derived labels (arXiv:2310.11622) —
   the quadrats play exactly that teacher role here.
3. **Output:** per-building PV probability → calibrated adoption rate per
   cell/stratum, complementing `pv_area_det`/`pv_area_exp` from segmentation
   (which remain authoritative for ≥1k m² arrays).

## Design constraints

- **Spatial holdout is mandatory:** train on some quadrats, validate on
  held-out quadrats from the *same stratum in a different province* —
  same-quadrat splits will overfit local roof styles and report fantasy
  accuracy (lesson learned the hard way in the substation project: val
  metrics decoupled from field quality).
- Class balance: quadrats supply verified negatives (every unlabeled building
  in a completed quadrat is a true negative — that's what the completeness
  rule in the mapping protocol buys us).
- Date alignment: building labels are only valid for the imagery window they
  were mapped against; the protocol's imagery-date register field exists for
  this.

## Synergy

Same field effort funds three things: density calibration (original purpose),
this classifier's training set, and the known-negative sample the glint
spike-rate estimator needs (see companion issue
`glint-spike-rate-density-estimator.md`). The two proposed estimators share
the per-building time-series pull — build that data layer once.

## Acceptance

- Per-building classifier trained on ≥4 quadrats/stratum, evaluated on ≥1
  held-out quadrat/stratum in a different province, reporting per-stratum
  precision/recall at the building level.
- Demonstrated improvement over the current centroid-pixel fallback for the
  <500 m² class on the held-out quadrats.

---
🤖 Drafted with [Claude Code](https://claude.com/claude-code)
