## Fraction-head retrain, roofclf national deployment, epoch-jump/step-change features (2026-07-29)

Implementation of last turn's three recommendations: (1) retrain with the 9 calibration
quadrats' positives, (2) deploy `roofclf` beyond evaluation, (3) fold epoch-jump/
step-change into `roofclf` as features. See the approved plan at the time
(`/home/tobi/.claude/plans/expressive-gathering-dragon.md`) for the full design; this
entry records what was actually measured.

### 1. Retrain: fraction head, 8 quadrats pooled + 1 held out

Literal 9-fold LOQO retraining of the deep model would cost 9-80+ GPU hours (measured:
past retrains here took 47 min to 8h38min each) — no precedent in this codebase and not
a responsible single-session use of the GPU. Compromise: train once on 8 quadrats'
fraction chips pooled into the existing Germany+Pakistan corpus (oversampled 20x train
each via `scripts/merge_fraction_chip_index.py`), holding one out for one honest
before/after check. **Held-out quadrat changed mid-session from
`karachi_coast_calib_700m` to `lahore_calib_1km`** (the first run, ~30 min in with
`karachi_coast` held out, was stopped and restarted with `lahore_calib_1km` held out
instead, per direct instruction) -- `karachi_coast_calib_700m`'s chips are now in the
training mix, `lahore_calib_1km`'s are not.

**Found and fixed while rebuilding the chip mix**: `chips.py` had no equivalent of
`roofclf._newest_solar`'s "newest dated pull wins" convention -- it always read the
bare `<aoi>_overpass_solar.parquet`, which for several quadrats is the STALE file (a
completeness pass writes a new dated file alongside it, per
`docs/calibration-mapping-protocol.md`'s iterative-mapping process). Measured impact:
faisalabad 53 vs 84 features, sundar 22 vs 49, karachi_coast 136 vs 165 -- the bare
file was silently missing up to half the real installations for three of the
training quadrats. Fixed with a new `chips._newest_overpass_path` helper (same glob +
lexicographic-newest logic as `roofclf._newest_solar`), used at both call sites in
`chips.py`; `_overpass_labels` also hardened to tolerate a `placement`-less raw pull
(a freshness-check re-fetch can predate `classify_placement`) rather than crash.
faisalabad/sundar/karachi_coast's chips were rebuilt with the fix before this retrain
launched. `lahore_calib_1km`'s own two files (1042 vs 1034) are not affected by this
fix's outcome since Lahore is now held out of training entirely.

Also corrected from last turn's looser framing: **only the fraction head was retrained**,
not segmentation. `chips.py`'s `_burn_mask` always burns sub-400 m² arrays as `ignore`
regardless of how many small positives are added, so a segmentation retrain would not
serve the stated "small rooftop solar" goal at all.

New `configs/aoi.yaml` entries for the 9 quadrats point at `data/composites/pakistan`'s
already-composed cells via a symlink trick (`data/composites/<quadrat>/composites/<cell>`
-> the national compose output) rather than `pakistan_500`'s own composites, which
**only cover Balochistan, not Punjab** despite the name (confirmed empirically: the
first chip-build attempt on a Punjab quadrat returned 0 labels in coverage until this
was fixed) -- no new imagery, reuses tiles the `compose` stage already built.

Training launched as `earthpv-retrain-fraction-v2` (systemd unit,
`configs/terramind_pv_fraction_pakistan_v2.yaml`, checkpoint_dir
`data/models/fraction_pakistan_v2`); GPU was concurrently shared with another
project's process during this run. Completed 2026-07-30 06:11, 23:54:54 -> 06:11:02
= **6h16m**, early-stopped at epoch 25 (`patience=8`), best checkpoint epoch 17
(`terramind-pv-epoch=17-step=12636.ckpt`). One transient slowdown around epoch 11
(74 min for one epoch vs. the steady ~14.5 min/epoch elsewhere) was investigated live
-- process confirmed genuinely computing (100%+ CPU, `R` state, no OOM/crash in
`journalctl`), not hung; resolved on its own by the next check.

### Held-out validation: negative result, checkpoint not promoted

Inferred the new checkpoint restricted to `lahore_calib_1km`'s cell (`--tiles
0135_0077`) and compared against the production checkpoint
(`fraction_pakistan_v1/terramind-pv-epoch=29-step=19680.ckpt`), both scored against
Lahore's exhaustive ground truth (1,938 buildings, 583 with PV, 47,118.6 m<sup>2</sup>
true PV area) via the same `zonal_mean_max` sampling `roofclf.building_table` uses.
Confirmed not a loading bug first: the new checkpoint's raw probability raster has a
normal, varying distribution (0-253 range, 59.6% nonzero pixels), not degenerate.

| | production (v1, epoch 29) | retrained (v2, epoch 17, Lahore held out) |
| --- | ---: | ---: |
| predicted PV area | 24,506.6 m² | **9,267.5 m²** |
| scale (pred/true) | 0.520 | **0.197** |
| Pearson r (pred vs. true per-building fraction) | 0.136 | **0.070** |
| AUC (pred vs. has_pv) | 0.589 | **0.553** |

**The retrained checkpoint is worse than production on every metric measured, on the
exact quadrat it was held out to test.** Not promoted -- `fraction_pakistan_v1`
remains the checkpoint used for Phase 5, and no national fraction inference is run
with `fraction_pakistan_v2`.

**Why, as far as can be said without further experiments:** the 8 training quadrats
(oversampled 20x each, ~1,600 chip-repeats total) are dominated by industrial/arid
context once Lahore -- the single densest, most residential quadrat -- is removed;
the densest remaining quadrat is Mardan (11.2 m vs. Lahore's 7.2 m). Oversampling a
handful of unique chips 20x each risks the model memorizing per-quadrat idiosyncrasy
(specific roof materials, background reflectance) rather than a transferable PV
spectral signature, and training from scratch (this project's only supported mode --
there is no `ckpt_path`/fine-tune-resume anywhere in `train.py`) gives the new
quadrat data equal footing with the whole national corpus rather than a gentle
nudge. Both are plausible contributors; neither is confirmed by a further ablation
here. **This does not mean adding quadrat data as training positives is a bad idea in
general** -- it means *this specific* 8-quadrat, 20x-oversampled, train-from-scratch
recipe did not improve on production for the one quadrat withheld to check it, and
that result should be trusted over the a priori expectation that more real small-array
labels must help.

**Consequence for Phase 5**: "rerun over Pakistan" proceeds with the roofclf national
deployment (validated, kept) and the *existing* segmentation/fraction instruments
(unchanged, since the fraction retrain did not improve on them) -- not with a new
national fraction inference pass using `fraction_pakistan_v2`.

### 2. `roofclf` national deployment

Fixed the blocker found during planning: `building_table` rebuilt a full
`CompositeIndex` (opening ~4,474 tiles) on every call; reused once per national cell
this would cost ~6x10^7 file opens. Fix: `local_source.composite_index()` (an
existing `lru_cache`d factory nothing previously called) now also takes `layers`, and
`building_table` routes through it -- construction happens once per run regardless of
call count. Re-running `earthpv roof-classifier` after the fix took **1m27s** (down
from the 9x-redundant-rebuild cost the unfixed version would have paid).

New: `roofclf.save_model`/`load_model` (persist a `fit_logistic` result + feature
list as JSON) and `roofclf.score_buildings_national` -- one composite tile = one
national cell, `fetch_vida_buildings` per cell (same pattern `density.process_cell`
already proves tractable at 4,463 cells), `zonal_mean_max` for the composite-band
features (no prob-raster read needed -- `MODEL_FEATURES` doesn't use `seg_mean`/
`frac_mean`, ablation-excluded since before this session), `predict_proba` with the
persisted model, resumable per-cell parquet output.

`run_roof_classifier` now also fits ONE pooled model on all 9 labelled quadrats
(distinct from the 9 LOQO folds, which remain for honest skill measurement only) and
picks a deployment threshold via `sppi._precision_threshold` (reused directly --
this session's SPPI validation already established that a precision-targeted
threshold is the right criterion for a capacity-contributing detector, not Youden's
J) on the pooled out-of-fold scores:

```
deployment_threshold: 0.4555
n_flagged: 1188 / 22,044 buildings, precision=0.50, recall=0.25 (honest LOQO number)
```

National scoring launched (`earthpv-roofclf-national`, background) over all ~4,463
composite cells / tens of millions of VIDA buildings. **Trust in this run's precision
is bounded by the LOQO number above, carried forward as an extrapolation** -- there is
no ground truth outside the 9 quadrats to verify it directly, the same honesty this
project already applies to `exp_scale`/`rate_ratio`.

**Completed 2026-07-30 01:41** (started 23:24, ~2h17m). All 4,473 cells scored,
**81,762,684 VIDA buildings** total, **898,593 flagged** at the deployment threshold
(0.4555), totalling **222,012,609 m² of flagged roof area** -- output at
`data/roofclf_national/pakistan/prob/*.parquet` (6.6 GB), spot-checked for valid
probability ranges and geometry. **This is the raw flagged count, not a capacity
number** -- it is not yet deduped against existing segmentation candidates (only
buildings segmentation *misses* should count as incremental) and not yet
precision-weighted (the 0.4555 threshold's own precision is 0.50, so roughly half of
this flagged area is expected to be real) -- both steps are part of Phase 5, not done
yet.

### 3. Epoch-jump: tested, does not survive LOQO in either form

Two variants, both added as opt-in `building_table` parameters
(`include_epoch_jump`, `preboom_prob_dir`), neither added to the default
`MODEL_FEATURES`:

- **Raw reflectance delta** (`composite_1` via `CompositeIndex(layers=2)`, zero new
  inference -- `composite_1` is already ~complete nationally). Result: median LOQO AUC
  **0.8736 -> 0.8608** (worse). Helps 8/9 quadrats individually but **collapses
  `karachi_coast` from 0.8831 to 0.7304** -- a -0.15 crash on exactly the quadrat this
  project treats as its most trustworthy. Composite_1 data itself looks fine (checked
  directly: full nonzero coverage, no reflectance anomaly), so this reads as a genuine
  confound/noise problem in that specific dense-residential-coastal context, not a data
  bug. Net effect on the project's headline (median across folds): negative.
- **Probability-jump** (the design doc's proposed version --
  `current_seg_max - preboom_max`, needing a targeted inference pass): the design
  doc assumed a multi-hour country-wide re-inference cost, which is stale --
  `infer.py` already has `--resume`/`--tiles`, so the actual gap was 8 cells, done in
  **37 seconds**. Result: median LOQO AUC **0.8736 -> 0.8736** (unchanged),
  within-size **0.8422 -> 0.8424** (negligible). Statistically neutral, consistent
  with this project's existing pattern for other candidate features (SPPI-as-feature,
  seg/frac-as-feature: "adds nothing").

**Neither variant is added to the default model.** `docs/issues/epoch-jump-recall-signal.md`'s
proposal remains a documented, tested idea, not a shipped one.

### 4. Step-change: tested on 5 quadrats, a size confound, not extended

Per the user's decision, tested on the 5 quadrats with already-cached time-series
cubes (`lahore`, `sundar`, `site_karachi`, `multan`, `faisalabad`) before deciding on
the other 4 (`mardan`, `quetta`, `sialkot`, `karachi_coast`, ~1hr of sequential STAC
pulls each).

The cached `data/step/<box>/buildings_scored.parquet` artifacts (rich, 238-column,
from an earlier session) turned out to be from an unmerged branch's version of the
pipeline with an incompatible building population (a larger box, not the calibration
quadrat's own extent -- e.g. `lahore_box`: 4,480 buildings vs `roofclf`'s own 1,938 for
that quadrat) and no shared geometry key, so rather than reverse-engineer that
artifact, `scripts/pv_step_signal.py` (**current `main`, unmodified**) was re-run fresh
against the already-cached cubes (~20s/quadrat) into `data/step_v2/`, then aggregated
into `roofclf`'s own building geometries via `zonal_mean_max` (the same rasterize-and-
bincount helper every other per-building feature in this module uses) -- a genuinely
new, `main`-branch-only piece of aggregation code, not a port of the other branch's.

Restricted to the 5 covered quadrats (the fair comparison -- pooling in the other 4 at
zero-imputed step features just adds noise and was not used to judge the feature):

| | median AUC | median AUC within size band |
| --- | ---: | ---: |
| default | 0.8819 | 0.8518 |
| default + step features | **0.8946** | **0.8397** |

Raw AUC improves (+0.0127). **AUC within size band gets worse (-0.0121).** Per this
project's own standing rule ("Quote the conditional number as the imagery's
contribution" -- `roofclf.py`'s module docstring), the size-controlled number is the
honest one, and it declined. The most likely explanation: the step signal is itself
noisier on smaller buildings (fewer, weaker pixels to estimate a breakpoint from), so
its apparent AUC gain is partly riding the same size-adoption correlation
`auc_within_size` exists specifically to strip out -- not new discrimination at fixed
roof size.

**Not extended to the other 4 quadrats.** Per the plan's own checkpoint ("if it doesn't
measurably help, stop here"), this result is borderline-negative on the metric that
matters, so the ~1hr additional STAC pull is not spent chasing it further this pass.
`data/step_v2/` (fresh, `main`-branch-compatible) is kept for a future attempt with a
confound-aware aggregation (e.g. an explicit size term in the step estimator itself,
not just in the classifier that consumes it).

### Capacity fold-in: negative result, not promoted

The plan's last step was to fold `roofclf`'s nationally-flagged buildings into
capacity: buildings scored `>= 0.4555` (the LOQO precision-0.50 deployment threshold)
with no existing segmentation candidate within 30 m counted as incremental,
non-double-counted population, weighted by the flat LOQO precision (0.50) rather than
`p_roofclf` itself (`roofclf_capacity.py`, new this session).

Run against the real national output (`data/roofclf_national/pakistan/prob/`,
4,473 cells): 898,593 buildings flagged nationally (1.10% of 81.76M scored), 872,730
of them (97.1%) incremental. At 0.18 kWp/m² x 0.50 precision that is **18,063 MWp of
incremental capacity** -- not added to density, for one decisive reason: the
country's entire current recall-corrected total (`density`'s unchanged, segmentation +
`fraction_pakistan_v1` output, `data/predictions/pakistan/density/meta.json`) is
**5,078 MWp all-placement, 2,230 MWp roof-only**. A single uncorrected proxy signal
proposing to add 3.5-8x the country's existing total on top is not a result to
publish, it is the signature of the extrapolation itself failing.

Diagnosed the mechanism rather than just distrusting the headline number. Three cells
(`0054_0047`, `0138_0086`, `0124_0107`) are flagged at 94.7-99.8% of every building in
the cell (vs. 1.10% nationally, 0.078 mean `p_roofclf` nationally) -- `predict_proba`
output for these cells is pinned at `p ~ 0.999999...` (one cell even spans both
saturation extremes, `4e-11` to `1.0`), the textbook signature of a standardized
logistic model handed a covariate far outside its training range: the linear score
blows up and the sigmoid saturates. These three cells are a real, distinct QA issue
(some composite/reflectance value there is degenerate -- not yet root-caused pixel by
pixel) but they are **not** the main story: excluding them entirely only takes the
total from 18,063 to 17,334 MWp (they are 11.9% of flagged buildings but only 4.0% of
flagged area, since they are dense-small-building cells). The other 96% of the number
is unremarkable-looking, distributed, ordinary-magnitude flagging across thousands of
cells -- and it is *still* 3.4x the country's current roof-only total.

The root cause is the same one already on record for `roofclf` elsewhere in this repo
(invariant (c), "ranking transfers, absolute rates do not" -- `rate_ratio` spans
0.235-4.833 across the 9 training quadrats, and the model predicts 0.137 for
residential Lahore against a true 0.301). A flat national precision weight assumes the
9 quadrats' base rate (2,376/22,044 buildings = 10.8% PV prevalence, chosen to span
strata but still skewed toward urban/industrial/known-solar areas) generalizes to
81.76M buildings covering the whole country, most of which are rural/informal/
agricultural with a much lower true base rate. Precision at a fixed score threshold is
base-rate-dependent (PPV falls as prevalence falls even at constant TPR/FPR), so this
was always the likely failure mode for exactly the reason CLAUDE.md already flags: "a
per-stratum intercept is required before publishing any adoption rate or capacity from
it," and none exists yet.

**Decision: `roofclf`'s national output is not folded into `density.py` or the
published capacity atlas.** It remains valid for what it was actually validated to do
-- per-building LOQO ranking/classification within a stratum, feeding
`packing_density`/`auc_within_size` diagnostics, and (like glint) as a lead-generation
signal for human-validated mapping -- but converting its raw national flag count into
an addable MWp figure needs a per-stratum (or continuous covariate, e.g.
building-density or nightlight-based) intercept correction first, which is future
work, not something to invent under this task. `earthpv check-density --aoi pakistan`
was run against the existing, unchanged density output (segmentation +
`fraction_pakistan_v1`, `roofclf` not folded in) as the closing gate: **0 fail, 3
suspect of 7 regions**, the same already-documented pattern (Gilgit-Baltistan exempted,
Khyber Pakhtunkhwa/Balochistan/Azad Kashmir suspect on the ground:rooftop ratio check)
-- nothing regressed, because nothing about the published capacity numbers changed
this phase.

### Summary

| addition | kept? | effect |
| --- | --- | --- |
| Retrain (fraction head, 8 quadrats + national corpus, Lahore held out) | **no** | held-out Lahore: scale 0.520 -> 0.197, r 0.136 -> 0.070, AUC 0.589 -> 0.553 (worse on every metric) |
| `roofclf` national deployment | yes -- complete (4,473 cells, 81.76M buildings, 898,593 flagged) | n/a (extrapolated from LOQO) |
| `roofclf` capacity fold-in | **no** | 18,063 MWp incremental vs. country's existing 5,078 MWp total (3.5-8x) -- flat national precision weight does not survive the base-rate shift from 9 training quadrats to 81.76M buildings; not folded into density |
| Epoch-jump, reflectance delta | no | 0.8736 -> 0.8608 (worse, one quadrat crashes) |
| Epoch-jump, probability delta | no | 0.8736 -> 0.8736 (no effect) |
| Step-change (5/9 quadrats) | no | 0.8819 -> 0.8946 raw, but 0.8518 -> 0.8397 within-size (confound) |
