## Quadrat-supervised fraction retrain, and what its holdout says (2026-08-04/05)

!!! info "CLOSED, negative result (as of 2026-08-11)"

    Neither quadrat-supervised checkpoint was promoted; `fraction_pakistan_v1` remains the
    fraction-head checkpoint of record. Two details below are out of date: the warning box
    about `karachi_coast` losing Rule-1 status describes a withdrawal that was itself
    superseded, and all 23 quadrats now carry Rule-1; and the domain restriction quoted as
    93 of 4,473 cells now covers 1,680 cells. Current numbers are on
    [Capacity](../results/capacity.md).

!!! warning "The holdout quadrat was replaced hours after this was written"
    Every number below describes `karachi_coast_calib_700m`, the 0.49 km² box. On
    **2026-08-05** that boundary was replaced by a hand-drawn 2.16 km² one
    (`karachi_coast_calib_2p16km2`, old files at `data/labels/retired/`) and its **Rule-1
    status was withdrawn**. Two things follow, and neither invalidates the *conclusion*:

    - The measurements stand as measurements -- both checkpoints' rasters and the retired
      boundary are still on disk, so they remain reproducible and are still the honest
      answer to "what did the model do on that box". They are simply no longer measurements
      of a *current* quadrat.
    - One stated justification for the choice of holdout is now void: "it is Rule-1
      complete, so its PV-free buildings are trustworthy negatives and precision on it
      means something". Precision figures for this box should now be read with the same
      "absence may be unmapped" caveat as every other non-Rule-1 quadrat.

    The verdict does not move, because it rests on `scale` (predicted/true area over
    *mapped* installations) and pixel AUC, neither of which needs trustworthy negatives --
    both only need the positives to be real, which they are. Re-running the pair on the new
    2.16 km² boundary would give a fresh out-of-sample estimate over ~4.4x the area, which
    is the cheapest way to attack the n=1 problem this document ends on.

The 13 calibration quadrats are the project's only exhaustively mapped ground, and the only
place a sub-400 m² installation is reliably labelled at all. `quadrats-as-training-data.md`
proposed spending them on a per-building classifier; `roofclf.py` did that. This is the
other half of the same idea: spend them as **pixel** supervision for the fraction head, the
instrument that actually produces the sub-400 m² capacity numbers.

An earlier attempt (`fraction_pakistan_v2`, 2026-07-30) did this and scored *worse* than v1
on every metric. Two things were changed rather than repeated:

1. **Supervision is confined to the mapped ground.** `earthpv quadrat-chips` burns
   everything outside a quadrat boundary as `ignore` (-1). A chip is 5.02 km² and a quadrat
   0.49-2.25 km², so an ordinary "quadrat chip" is only ~19% completeness-mapped and ~81%
   surrounding national OSM, where unmapped small PV is burned as 0 -- teaching the model to
   suppress exactly the signal the quadrats exist to supply. v2 oversampled that mixture
   20x. These chips supervise the mapped ground only (21.0% of chip area, 10.9% of
   supervised pixels carrying PV against ~0.35% nationally).
2. **The oversampling factor is chosen by signal mass, not by feel.** At x8 the quadrats
   carry 20.9% of the corpus's total `(1 + k*target)` weight, up from 3.2% at x1; v2's 20x
   would be 39.8%. Deliberately less aggressive, because the ground truth is ~13 km² in 13
   places and overfitting to those places is the live risk.

Everything else is v1's recipe unchanged (`terramind_v1_tiny`, `weighted_mse` k=10.0,
sigmoid head, lr 1e-4, patience 8, monitor `val/RMSE`), so the corpus is the only variable.

## The pair of runs is the experiment

Overfitting to 13 places is not something a national val split can detect -- that split is
≥400 m²-dominated national and Germany chips, and both runs land on essentially the same
value there (best `val/RMSE` 0.04209 vs 0.04222, `val/R2` 0.472 vs 0.468), which measures
nothing about the small-PV regime. So the experiment is two runs of the identical recipe:

| run | corpus | checkpoint | epochs |
|---|---|---|---|
| `quad13` | all 13 quadrats x8 (11,960 chips) | `fraction_pakistan_quadrats/terramind-pv-epoch=56-step=41838.ckpt` | ran to max 60 |
| `quadho` | 12 quadrats x8, `karachi_coast_calib_700m` **held out** (11,862 chips) | `fraction_pakistan_quadrats_holdout_karachi/terramind-pv-epoch=32-step=24024.ckpt` | early-stopped at 40 |

`karachi_coast_calib_700m` is the holdout because it is Rule-1 complete (its PV-free
buildings are trustworthy negatives) and the project's hardest, most diagnostic box: median
installation 86 m², 98.8% below the 400 m² detection floor, where the segmentation raster
scores exactly 0.500 and predicts 0.0 m² against 13,963.6 m² mapped. Cost of that choice:
only 0.488 km² and 797 labelled PV pixels, so the estimate is noisy by construction.

Two leakage paths were closed before training rather than assumed absent: none of the 12
remaining quadrats' chips overlap the held-out boundary, and the **national** Pakistan chip
`150118f0c295` -- which covers 16.3% of the held-out box with full national supervision over
exactly those labels -- was excluded (`data/chips/pakistan_fraction_holdout_karachi`, 2,580
of 2,581 kept). Germany does not overlap, as expected.

## Evaluation

`scripts/eval_fraction_quadrat_model.sh <name> <ckpt>` runs each checkpoint over only the 15
composite cells covering a quadrat (`data/quadrat_cells.txt`; ~45 s per epoch, against 3h19m
for a national pass) in both the current dry-season composite (`--index 0`) and the pre-boom
one (`--index 1`), then scores two ways. `scripts/run_quadrat_supervision_eval.sh` drives
both runs sequentially -- never concurrently, a 6 GB GTX 1060 cannot hold two inference
passes and this project has already lost a multi-hour job to an OOM kill.

Reference rasters are the two national ones already on disk: `v1`
(`fraction_pakistan_v1`, the deployed sub-400 m² checkpoint) and `hn`
(`fraction_pakistan_hardneg`).

### 1. Per-quadrat scale and pixel AUC (`scripts/validate_fraction_quadrats.py`)

`scale` = predicted/true PV area, a *calibration* question, fixable after the fact with
`density --exp-scale`. `auc` = pixel separation of mapped-PV pixels from the rest of the
quadrat, an *information* question, not fixable by rescaling. Reading them together is the
point: a quadrat that over-predicts can lose true signal and still look improved, because
the two errors cancel in one ratio.

`results/fraction_quadrat_validation_quad13.csv`, `..._quadho.csv`:

| quadrat | v1 scale | quad13 scale | quadho scale | v1 AUC | quad13 AUC | quadho AUC |
|---|---|---|---|---|---|---|
| faisalabad_calib_1km | 3.131 | 2.804 | 3.146 | 0.8145 | 0.9168 | 0.8881 |
| **karachi_coast_calib_700m** | **0.291** | **1.963** | **0.461** | **0.7333** | **0.7983** | **0.7598** |
| lahore_calib_1km | 1.449 | 3.167 | 3.306 | 0.6579 | 0.7344 | 0.7395 |
| mardan_calib_1km | 0.311 | 1.735 | 2.384 | 0.6332 | 0.6546 | 0.6828 |
| multan_calib_1km | 2.272 | 1.769 | 2.135 | 0.8887 | 0.9581 | 0.9498 |
| peshawar_calib_1km | 1.480 | 2.581 | 2.858 | 0.8400 | 0.8806 | 0.8719 |
| peshawar_east_calib_1km | 1.285 | 3.636 | 3.625 | 0.8516 | 0.8931 | 0.8782 |
| peshawar_west_calib_1500m | 2.268 | 2.034 | 2.403 | 0.8737 | 0.9352 | 0.9162 |
| quetta_calib_1km | 0.262 | 3.043 | 3.684 | 0.7037 | 0.8410 | 0.8066 |
| rahim_yar_khan_calib_1km | 0.680 | 1.875 | 2.300 | 0.6238 | 0.8260 | 0.7612 |
| sialkot_calib_1km | 1.468 | 1.468 | 1.878 | 0.7658 | 0.7827 | 0.7563 |
| site_karachi_calib_1km | 2.838 | 2.377 | 2.703 | 0.9193 | 0.9477 | 0.9431 |
| sundar_calib_1km | 2.519 | 2.033 | 2.125 | 0.9252 | 0.9677 | 0.9484 |
| **median** | 1.468 | 2.034 | 2.403 | 0.8145 | 0.8806 | 0.8719 |

Note the row for karachi_coast is in-sample for `quad13` and held out for `quadho`; every
other row is in-sample for both.

**In-sample, this is a large and unusually clean win.** `quad13` beats v1 on AUC in
**13 of 13** quadrats, median +0.0615. And the *dispersion* of `scale` collapses -- which
matters more than the median, because a uniform bias is one `--exp-scale` constant away
from corrected and a spread is not correctable at all:

| run | median scale | min | max | max/min | geometric SD |
|---|---|---|---|---|---|
| v1 | 1.468 | 0.262 | 3.131 | 11.95x | 2.447 |
| hn | 0.906 | 0.079 | 2.648 | 33.52x | 3.497 |
| quad13 | 2.034 | 1.468 | 3.636 | **2.48x** | **1.313** |
| quadho | 2.403 | 0.461 | 3.684 | 7.99x | 1.699 |

v1's failure across the quadrats was never mainly a level error -- it was that the level
was unknowable, ranging 11.95x from Quetta (0.262) to Faisalabad (3.131). `quad13` turns
that into a consistent ~2x over-prediction. (`hn` is worse than v1 here on both axes -- 6/13
on AUC, median -0.0036, dispersion 33.52x -- consistent with what
`fraction-head-hard-negative-retrain.md` already records about that checkpoint being a
large-array win and a small-rooftop loss.)

**Out of sample, most of that disappears.** On the held-out box, `quadho` reverts to
`scale` 0.461, far outside the tight 1.878-3.684 band it holds on the 12 quadrats it
trained on, and only ~10% of the way from v1's 0.291 to `quad13`'s in-sample 1.963. Its
`scale` dispersion excluding karachi is 1.250 -- as tight as `quad13`'s -- so the tightness
is a property of *trained-on places*, not of the model. AUC keeps more: +0.0265 of
`quad13`'s +0.0650, about 41%.

### 2. Is the held-out AUC gain real? (`scripts/quadrat_auc_block_bootstrap.py`)

+0.0265 AUC over 797 labelled pixels, and those pixels are not independent -- a 10 m raster
over a rooftop array gives many pixels of one installation, so a per-pixel resample would
report an interval several times too narrow. This resamples square blocks of pixels with
replacement instead, scoring every run on the same resampled set each draw so the
difference is paired. Point estimates reproduce `validate_fraction_quadrats.py` exactly,
which is the harness check. `results/karachi_holdout_auc_bootstrap.csv`, blocks of 5x5
(50 m), 2,000 draws, baseline v1:

| run | AUC | 95% CI | delta vs v1 | 95% CI of delta | one-sided p |
|---|---|---|---|---|---|
| v1 | 0.7333 | 0.694-0.771 | -- | -- | -- |
| hn | 0.7217 | 0.681-0.759 | -0.0116 | -0.052 to +0.030 | 0.73 |
| quadho (**held out**) | 0.7598 | 0.724-0.795 | **+0.0265** | **-0.009 to +0.061** | **0.062** |
| quad13 (in sample) | 0.7983 | 0.767-0.829 | +0.0650 | +0.034 to +0.097 | <0.001 |

Sensitivity to block size is the whole argument, so it was run across it. The in-sample gain
is robust everywhere; the held-out gain crosses zero as soon as blocks are large enough to
respect installation-scale autocorrelation, and its p degrades monotonically:

| block | 2x2 (20 m) | 3x3 | 5x5 | 8x8 | 12x12 (120 m) |
|---|---|---|---|---|---|
| quadho delta CI | +0.002 to +0.050 | -0.003 to +0.056 | -0.009 to +0.061 | -0.013 to +0.067 | -0.013 to +0.072 |
| quadho p | 0.017 | 0.039 | 0.062 | 0.091 | 0.102 |
| quad13 delta CI | +0.043 to +0.087 | +0.035 to +0.092 | +0.034 to +0.097 | +0.028 to +0.103 | +0.030 to +0.105 |
| quad13 p | <0.001 | <0.001 | <0.001 | <0.001 | <0.001 |

So: the out-of-sample discrimination gain is **positive in direction and not established in
magnitude**, from n=1 quadrat. That is the honest reading, and no amount of further analysis
of these two rasters will improve it -- only more held-out quadrats will.

### 3. The over-prediction is genuine, not stale labels (`scripts/fraction_stale_label_audit.py`)

`quad13` over-predicts area ~2x everywhere, and there was a standing hypothesis that this is
partly an artifact: the quadrats were mapped against high-res basemap imagery generally
*older* than the Sentinel-2 composite, so an installation built in between is in the image
and absent from the labels, and a correct prediction scores as a false positive
(`calibration-imagery-dating.md`). Running the same checkpoint on the pre-boom composite as
well separates the two -- predicted now and not pre-boom is consistent with a new
installation; predicted in both epochs is not.

`results/fraction_stale_label_audit_quad13.csv`, threshold 0.2, pooled over 13 quadrats:
recall 0.611, `precision_raw` 0.435 (every unlabelled prediction an error), `precision_upper`
0.450 (candidate new installations not errors). **Only 5.8% of apparent false-positive
pixels are new-installation candidates.** `quadho`: 0.619 / 0.389 / 0.401, 5.1%.

The stale-label mechanism is real but small -- it moves precision by 1.5 points. The ~2x
over-prediction is the model's, and it is not going to be explained away by label age.

One reading note: `mardan` shows `tp` 6 of 1,655 labelled pixels here while its `scale` is
1.735 above. Not a contradiction -- Mardan's predictions are diffuse (mean fraction 0.036)
and almost never cross the 0.2 threshold, while `scale` integrates sub-threshold coverage,
which is exactly how the `*_exp` instrument uses this raster. AUC 0.6546 is the honest
statement about Mardan: still the weakest fold, as it was for `roofclf`.

## Verdict

**Not promoted.** `fraction_pakistan_v1` remains the sub-400 m² checkpoint of record, and
the sub-400 m² products (`results/`, `docs/results/growth.md`, the evidence atlas's
Best-estimate tier) continue to describe it.

The reason is specifically the calibration side, not the discrimination side. What would
license promoting `quad13` into national capacity is the geo-SD 1.313 line in the table
above: a consistent 2x bias corrected by one `--exp-scale` constant. The holdout says that
consistency is fitted -- on the one place the model had not seen, the true scale is 0.461,
not 2.03, so a national `--exp-scale ~0.5` derived from the in-sample band would push the
sub-400 m² estimate the wrong way in every place unlike the 13. This is the same
"ranking transfers, absolute rates do not" result the project already has for `roofclf`
(`rate_ratio` 0.235-4.833 across quadrats), arriving now for the fraction head, and it is
the missing **per-stratum intercept** again rather than a new obstacle.

What the experiment did establish, and is worth carrying:

- Boundary-confined supervision at x8 is the right recipe shape. It reverses v2's outcome
  decisively in-sample (13/13 AUC improvements against v2's across-the-board regression),
  so the v2 failure was the ~81%-unmapped chip mixture and the 20x weight, as diagnosed.
- The quadrats do carry generalising *ranking* information, direction confirmed, magnitude
  ~40% of the in-sample gain and not statistically separable from zero at n=1 quadrat.
- Over-prediction is the model's own, not label age (5.8%).

Cheapest next step that would actually resolve it, in order:

1. **More holdout folds.** One box, 797 labelled pixels, is the binding constraint on every
   number above. Three or four leave-one-quadrat-out runs (~6-7h GPU each) would turn a
   marginal p=0.06 into an estimate with a usable interval, and would say whether the
   out-of-sample `scale` reverts everywhere or only on the hardest box. `roofclf` already
   pays this LOQO cost and it is what makes its numbers trustworthy.
2. **Stratified `--exp-scale`, not a national one.** The per-quadrat scales are not noise:
   they track regime (industrial/large-array quadrats over-predict, dense small-rooftop
   ones under-predict). `roofclf`'s density-domain restriction (93 of 4,473 cells,
   `sub400_capacity.py`) is the existing machinery for saying "only where calibration
   evidence exists" and would apply unchanged.
3. Both `quad13` and `quadho` quadrat-cell rasters are kept
   (`data/predictions_quad{13,ho}_quadcells{,_preboom}/`), so any further scoring of these
   two checkpoints over the quadrats needs no GPU.

---
🤖 Drafted with [Claude Code](https://claude.com/claude-code)
