# Feed glint-validated candidates back as training labels (active learning)

**Labels:** enhancement, model, glint, active-learning

## Problem

The model's training positives come from OSM mapping, which lags reality badly in
the target regions (that gap is the project's reason to exist). The human
validation loop (MapRoulette) closes it slowly and at human cost. Meanwhile the
glint check produces a stream of *physically corroborated* candidates — ≥2
mutually-consistent spike dates recovering a single panel orientation — whose
false-validation floor is **measured**: 8.7% on 69 no-PV control buildings
(`results/glint_validation_pakistan/REPORT.md` + the corroboration experiment's
controls). That is high-precision evidence sitting unused as supervision.

## Proposal

Treat glint-validated candidates as auto-confirmed positives for the next
training round, without waiting for human validation:

1. After a `postprocess --check-glint` run, select candidates with
   `glint_consistent >= 2` and a roof-plausible fitted orientation
   (`glint_fit_tilt`/`glint_fit_az` — e.g. tilt < ~35° for rooftop placement,
   any tilt for ground candidates).
2. Restrict to area buckets where the calibrated likelihood ratio is
   meaningful (≥ 500 m², matching `postprocess._GLINT_BUCKET_EDGES_M2` /
   `min_lr` — below that the 8.7% floor eats the signal).
3. Burn these polygons into the chip set as positives via the existing chips
   machinery (same path as OSM labels), tagged with a `source=glint` column so
   they can be weighted, audited, or ablated separately.
4. Retrain; compare against the OSM-only baseline on the held-out val split.

The inverse direction is also open, through the *existing hard-negatives
review path* (never auto-demotion, matching the reward-only contract):
candidates showing persistent bright spikes with **geometrically inconsistent**
dates over many scenes look like specular noise sources (water, greenhouses,
metal roofs) and are good seeds for the `hard-negatives` stage's human review
queue.

## Design constraints

- **Label noise budget:** the 8.7% false floor means ~1 in 12 auto-positives is
  wrong. That's comparable to OSM noise in fast-growing regions, but it should
  be (a) measured per training run (fraction of glint-sourced chips), and
  (b) ablatable — keep `source=glint` all the way into the chip index.
- **No circularity:** glint-sourced positives must be excluded from any val/test
  split used to evaluate the retrained model (they were selected *by* the
  pipeline being evaluated). Spatial holdout as usual (`val_tiles`).
- **Ordering:** most valuable after tile-batched coverage
  (docs/issues/glint-tile-batched-coverage.md) multiplies how many validated
  candidates exist per run; a few hundred queried candidates yield too few
  confirmations (validation rates are 16–31%) to move an 8k-chip training set.
- The training positive threshold (`MIN_PV_AREA` in chips.py) still applies —
  glint positives below it would be burned as ignore, which is fine.
