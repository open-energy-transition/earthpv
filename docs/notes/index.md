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

For the conclusions these notes fed into, see [Experiments](../experiments.md).
