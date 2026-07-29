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
project's process during this run, so wall-clock may exceed the historical ~8h38min
baseline. **Held-out `karachi_coast_calib_700m` validation is pending training
completion** -- the number that actually answers whether this retrain worked.

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

### Summary

| addition | kept? | median AUC effect |
| --- | --- | --- |
| Retrain (fraction head, 8 quadrats + national corpus) | pending held-out check | n/a |
| `roofclf` national deployment | yes -- running | n/a (extrapolated from LOQO) |
| Epoch-jump, reflectance delta | no | 0.8736 -> 0.8608 (worse, one quadrat crashes) |
| Epoch-jump, probability delta | no | 0.8736 -> 0.8736 (no effect) |
| Step-change (5/9 quadrats) | no | 0.8819 -> 0.8946 raw, but 0.8518 -> 0.8397 within-size (confound) |
