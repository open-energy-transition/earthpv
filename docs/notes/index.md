# Working notes

Raw notes kept alongside the code: design proposals that have not been implemented,
assessments that concluded "do not build this", and running logs of ground-truth mapping.
They are less polished than the rest of this site and more specific. They are here because
the reasoning behind a decision not to build something is usually harder to reconstruct
later than the code that was built.

| Note | Status |
| --- | --- |
| [Pakistan calibration boxes](../issues/pakistan-calibration-boxes.md) | Live log of every fully mapped ground-truth quadrat, including the visual verification pass and the correction to Box 1. |
| [Epoch jump as a recall signal](../issues/epoch-jump-recall-signal.md) | Designed, not implemented. Uses the unused positive half of the pre-boom epoch comparison to rescue sub-threshold buildings. |
| [Standard-pose matched filter](../issues/standard-pose-matched-filter.md) | Assessed against real data and **not recommended** in its general form. Two narrower versions survive. |
| [Glint spike-rate density estimator](../issues/glint-spike-rate-density-estimator.md) | Proposal behind the cell-aggregate glint test that came back negative. |
| [Glint tile-batched coverage](../issues/glint-tile-batched-coverage.md) | The 22x fetch speedup, the seam-zone bug it exposed, and the equivalence check. |
| [Glint-validated training labels](../issues/glint-validated-training-labels.md) | Using glint confirmations as additional supervision. |
| [Quadrats as training data](../issues/quadrats-as-training-data.md) | Whether exhaustively mapped boxes should also be trained on, not just measured against. |
| [Quadrat-supervised fraction retrain](../issues/quadrat-supervision-fraction-retrain.md) | The pixel-supervision half of that question, run twice with one box held out. A large in-sample win the holdout does not support, so **not promoted**. |
| [Roof classifier cell-edge false positives](../issues/roofclf-cell-edge-false-positives.md) | Raster fill read as imagery along every composite cell boundary was **45.6% of all national roof-classifier flags**. Fixed in code; the national output and everything downstream of it still need re-running. |

For the conclusions these notes fed into, see [Experiments](../how-it-works.md#experiments).
