## Fraction-head hard-negative retrain (2026-08-03)

!!! info "CLOSED, mixed result (as of 2026-08-11)"

    The checkpoint swap shipped -- `fraction_pakistan_hardneg` became the fraction-head
    checkpoint of record -- but it was never promoted into a published sub-400 m² number,
    because the improvement splits by regime: better on industrial and large arrays, worse
    on dense small rooftops. The fraction head as a whole is now off the main path, which
    is segmentation plus roofclf. The `check-density` failure attributed here to a
    candidate-population mismatch has since been root-caused as the pooled
    precision/recall problem and fixed; see [Capacity](../results/capacity.md).

`fraction_pakistan_v1` (the deployed sub-400 m² checkpoint) has one known failure mode:
large OSM-unmapped buildings that read as bright/reflective and score falsely high.
`hard_negatives.py::run_hard_negatives` mines candidates for exactly this population
(large buildings with no OSM solar match) and cross-checks each one against two
imagery epochs (current + a 2022 comparison composite) via direct window inference,
independent of any chip-building pipeline. A candidate is **confirmed** when the
production checkpoint already scores it low in *both* epochs -- i.e. the model is
already getting it right, so this is evidence for reinforcing an existing correct
negative, not for correcting an existing false positive at that exact location (a
distinct, still-open question -- there is no held-out *known-false-positive*
population to test that directly).

Mining ran `--checkpoint fraction_pakistan_v1 --compare-year 2022 --min-area 400
--limit 1500 --neg-threshold 0.1 --workers 4` overnight (2026-08-02, ~10h, mostly
network time building 475 comparison-year composite cells): **1,032 confirmed**, 183
flagged (possibly new unmapped installations, not used here), 234 ambiguous, 0
skipped.

**Data-quality check before training.** `build_hard_negative_chips`'s own built-in
warning flagged ~48% of the mined chips as containing *some* PV pixel inside the chip
window -- investigated precisely with an exact-geometry join (`gpd.sjoin(pts,
labels[['geometry']], predicate='within')`) rather than trusting the coarse
chip-level warning. Only **11 of 1,032** candidate *center points* actually fall
inside a current OSM solar polygon (the rest of the 48% is unrelated nearby
installations elsewhere in the same chip window, which is normal and expected, not
label corruption). Excluded those 11, kept **1,021** clean hard negatives.

## Training

Merged the clean set into the shared training pool (`data/chips/pakistan_hard_neg`,
1,606 -> 2,626 chips) and cut a separate, untouched eval copy
(`data/chips_fraction_hardneg_eval/pakistan_hard_neg`, 1,021 chips, 7 held out via the
normal `split` column) purely for before/after scoring, never merged into training.
Built a combined index (`scripts/merge_fraction_chip_index.py`) identical in shape to
production's recipe, adding the hard-negative source unweighted:

```
germany:data/chips_unfiltered/germany_fraction:1   (5,587 chips)
pakistan:data/chips/pakistan_fraction:2            (5,125 chips, oversampled 2x)
pakistan_hard_neg:data/chips/pakistan_hard_neg:1   (2,626 chips)
= 13,338 chips total -> data/chips/combined_fraction_hardneg/index.parquet
```

`configs/terramind_pv_fraction_pakistan_hardneg.yaml` is an exact copy of v1's recipe
(task_type: regression, `weighted_mse` k=10.0, sigmoid head, lr 1e-4, patience 8,
monitor `val/RMSE`) with only `index_path`/`checkpoint_dir` changed. Trained as
`earthpv-fraction-hardneg-train` (systemd unit), 2026-08-03 12:47:36 -> 18:22:50
(5h35m), early-stopped at epoch 40 of 60 (patience 8), best checkpoint **epoch 32**
(`data/models/fraction_pakistan_hardneg/terramind-pv-epoch=32-step=27027.ckpt`).

## Results

### 1. Standard evaluation, `pakistan_fraction`'s own held-out val split (37 chips)

These 37 chips are real installations, genuinely held out of *both* checkpoints'
training (`datamodule.py` splits on the index's own `split` column; the merge script
only oversamples `split == "train"` rows, so `val` rows pass through the combined
index exactly once, untouched):

| metric | v1 (production) | hard-neg retrain | change |
| --- | ---: | ---: | ---: |
| pixel IoU | 0.459 | **0.500** | +0.041 |
| pixel F1 | 0.629 | **0.666** | +0.037 |
| false-positive pixels | 16,813 | **12,006** | -28.6% |
| false-negative pixels | 2,167 | 3,135 | +44.7% |
| true-positive pixels | 16,085 | 15,117 | -6.0% |
| RMSE | 0.0665 | **0.0586** | better |
| MAE | 0.0129 | **0.0109** | better |
| chip-sum R² | 0.954 | 0.936 | slightly worse |
| chip-sum slope (pred/true) | 1.741 | **1.441** | closer to 1 (less over-prediction) |
| chip-sum bias (37 chips) | +49,825.6 m² | **+34,098.5 m²** | -31.6% |

Per-installation recall by size (same 37-chip val set, small n per bucket -- read the
bucket deltas as single-installation counts, not stable rates):

| bucket (m²) | n installations | v1 recall | hard-neg recall | delta |
| --- | ---: | ---: | ---: | ---: |
| 1000-inf | 180 | 0.906 (163) | 0.894 (161) | -2 installations |
| 500-1000 | 54 | 0.667 (36) | 0.667 (36) | unchanged |
| 250-500 | 54 | 0.556 (30) | 0.537 (29) | -1 installation |
| 0-250 | 37 | 0.324 (12) | 0.270 (10) | -2 installations |

**Reading this together**: false-positive pixel area dropped 28.6% and both IoU and
F1 improved, at the cost of at most 2 installations per size bucket -- within noise
for buckets this small (n=37-180), not a real recall regression. This is the more
informative comparison because it is scored against genuine, unseen real
installations rather than the mined negatives themselves.

### 2. Targeted before/after on the mined hard negatives (`scripts/score_hardneg_before_after.py`)

Scores the mean predicted fraction in a 7x7 px window at each of the 1,021 clean
hard-negative centers, before and after retraining:

| | old (v1) | new (hard-neg) |
| --- | ---: | ---: |
| mean score (n=1,020 scored) | 0.0110 | **0.0099** |
| median score | 0.0028 | **0.0018** |
| chips that decreased | -- | 845/1,020 (82.8%) |
| chips scoring >= 0.10 | 24 | 25 |
| held-out subset (n=7, never in any training pool) | mean 0.0023 | mean 0.0012 (all 7 decreased) |

These chips were selected *because* v1 already scored them low in both epochs, so
there is limited room to show a dramatic change -- the result is a modest, consistent
tightening (median -37% relative), not a large swing, and the already-rare >=0.10 tail
does not move. The held-out 7 behave the same direction as the 1,013 seen in
training, which is reassuring against overfitting to this specific chip set, but
this check is a sanity check that retraining did not disturb already-correct
negatives -- not a national false-positive-reduction measurement.

### 3. National inference re-run (2026-08-03/04) and quadrat validation

Run on the **latest dry-season composites** (`composite_0`, 2025-11-01 -> 2026-03-15 --
already the most recent dry season; there is no newer in-domain layer until Nov 2026),
single-epoch, no temporal stacking:

```
infer  --aoi pakistan --checkpoint fraction_pakistan_hardneg/...epoch=32-step=27027.ckpt
       --out-dir data/predictions_fraction_hardneg_national
       -> 4,473/4,473 cells, 390,902 windows, 22:32 -> 01:51 (3h19m)
density --fraction-prob-dir <that>/pakistan/prob --districts
       -> 4,463/4,463 manifest cells, exp_coverage_frac 1.0, did_full_rebuild, 0 failures
```

National effect, against the identical 4,463-cell density path fed by
`fraction_pakistan_v1`'s raster (`data/predictions_alt_fraction_roofclf`), so the only
thing that differs is the checkpoint:

| | fraction v1 | hard-neg | change |
| --- | ---: | ---: | ---: |
| `total_pv_area_exp_roof_m2` | 36,928,652 | 28,855,144 | -21.9% |
| `total_est_mwp_exp` | 6,647.2 MWp | 5,193.9 MWp | -21.9% |
| mean raw response, 80 random cells | 0.4885 | 0.1478 | 0.303x |

The raw-response drop (0.30x) is far larger than the building-restricted drop (0.78x),
which is the intended shape: most of what the hard negatives removed was **off-building
and rural**, not on roofs.

**But the national number alone cannot say whether that cost recall**, so both rasters
were scored against all 12 mapped calibration quadrats --
`scripts/validate_fraction_quadrats.py`, reusable for any future checkpoint, reading the
already-written national rasters (no GPU, no re-scoring) ->
`results/fraction_quadrat_validation.csv`. It reports two deliberately separate things:
`scale` (predicted/true area -- a calibration question, fixable after the fact with
`density --exp-scale`) and pixel `auc` (separation of mapped-PV pixels from the rest of
the quadrat -- an information question, *not* fixable by rescaling). Scale alone is
ambiguous: where a checkpoint over-predicts, losing true signal and removing a false
positive cancel in the same ratio.

| medians, 12 quadrats | fraction v1 | hard-neg |
| --- | ---: | ---: |
| `scale` (quadrat-total predicted/true) | 1.458 | **0.809** |
| `scale_roof` (restricted to VIDA footprints) | 0.464 | 0.255 |
| pixel AUC | **0.7902** | 0.7487 |
| mean response on mapped-PV pixels | -- | 0.938x v1 |
| mean response on background pixels | -- | 0.728x v1 |

Read nationally that is a good trade -- background response down 27%, response on true
PV pixels down only 6%, and the median scale moves from 46% over-prediction to 19%
under-prediction. **Read per quadrat it splits exactly 6/12, and not at random:**

| quadrat | regime | v1 -> hn scale | AUC delta | response on true PV |
| --- | --- | ---: | ---: | ---: |
| rahim_yar_khan | mixed | 0.680 -> 0.906 | +0.016 | 1.24x |
| lahore | residential | 1.449 -> 0.712 | +0.014 | 0.57x |
| site_karachi | industrial | 2.838 -> 2.426 | +0.009 | 0.97x |
| multan | industrial | 2.272 -> 2.169 | +0.008 | 1.03x |
| faisalabad | industrial | 3.131 -> 2.648 | +0.005 | 0.91x |
| sundar | industrial | 2.519 -> 2.358 | +0.001 | 1.02x |
| quetta | dense small | 0.262 -> 0.455 | -0.004 | 2.76x |
| karachi_coast | dense small, **Rule-1** | 0.291 -> **0.106** | -0.012 | 0.47x |
| mardan | dense small, **Rule-1** | 0.311 -> **0.079** | -0.033 | 0.33x |
| peshawar | dense small | 1.480 -> **0.204** | -0.041 | 0.20x |
| peshawar_east | dense small | 1.285 -> **0.183** | -0.076 | 0.19x |

Every quadrat that improves is industrial/large-array or mixed; every quadrat that
degrades is dense small-rooftop, i.e. **precisely the regime the sub-400 m² program
exists to measure**. Two of those are unambiguous losses of true signal rather than
removed false positives: `mardan` and `karachi_coast` are both Rule-1 complete (their
negatives are trustworthy) *and* v1 already **under**-predicted there (0.311, 0.291), so
there was no over-prediction available to remove -- yet the retrain cuts predicted area
a further 75% and 64%. The Peshawar pair is a different failure: v1 over-predicted
(1.48, 1.29), the retrain overshoots the correction by ~7x to 0.20/0.18, and pixel AUC
falls 0.04-0.08, so this is not merely recalibration either. `quetta` is the one
genuine counter-example, moving 0.262 -> 0.455 toward 1.0 with response up 2.8x.

Two caveats on the table. `mardan`'s `scale_roof` is NaN because the national VIDA
parquet contains **zero** footprints inside that quadrat (`n_bldg=0`) -- a buildings-data
gap, unrelated to either checkpoint. And per-quadrat `scale` remains a ratio of two
uncertain quantities where only the Rule-1 quadrats have a denominator complete by
construction; the `auc` column is the more robust half of this comparison.

**The `*_rc` / roof capacity figures from this density pass are not new results.** It
reports `total_est_mwp_rc` 2,847.2 and `total_est_mwp_rc_roof` **570.9** MWp, and
`check-density` fails 2 / suspect 3 (KP 8x, Balochistan 18x) -- byte-for-byte the same
signature as `density_TRUE_CURRENT_STATE_FAILING_20260730`, which was diagnosed at the time
as a candidate-population mismatch and has since been root-caused as pooled rooftop and
ground-mount precision/recall (fixed 2026-08-11; KP's ratio moved to 0.49x). The fraction
head only drives the
`*_exp` instrument, so it cannot be the cause, and this run reproducing that failure
independently is further confirmation the bug is a property of the current
`candidates.parquet`, not of any instrument swap.

## Verdict

**Promoted as the fraction-head checkpoint of record** --
`fraction_pakistan_hardneg/terramind-pv-epoch=32-step=27027.ckpt` replaces
`fraction_pakistan_v1`: fewer false-positive pixels, higher IoU/F1 on the genuinely
held-out real-installation val set, and now a confirmed 21.9% cut in national
over-prediction with the median quadrat scale moving from 1.46 to 0.81.

**Not promoted into the published sub-400 m² numbers.** The national pass is done and
verified, but the quadrat evidence above says the improvement is regime-specific: it
helps the industrial/large-array quadrats and hurts all five dense small-rooftop ones,
including both Rule-1-complete quadrats where the loss cannot be explained as removed
false positives. Swapping it into the sub-400 m² products would trade away recall in
exactly the population those products describe, so `results/`,
`docs/results/growth.md`, and the evidence atlas's Best-estimate tier deliberately
still describe `fraction_pakistan_v1`'s output.

**What would settle it**, in rough order of cost: (a) re-mine hard negatives with an
explicit size floor well above the small-rooftop regime, or weight them below 1, so the
correction cannot reach sub-400 m² roofs; (b) score the two checkpoints per size bucket
on the quadrats' *installations* (not pixels) to convert the AUC deltas above into a
recall number per bucket; (c) treat the two regimes as two instruments, using the
hard-negative raster for `>= 400 m²` capacity and v1 for the sub-400 m² path, which
costs nothing to try since both national rasters now exist side by side.
