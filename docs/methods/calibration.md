# Calibration

The leads product tolerates false positives because a person checks every one. The
capacity product has no person in the loop, so it must not inherit them. Calibration is
what separates the two, and it is the reason `density` never reads `rank_score`.

The output is a table at `configs/calibration/<aoi>_candidate_precision.yaml` holding, per
installation-size bin, a measured probability that an unmapped candidate is real PV, the
model's measured recall, and the binomial counts behind both.

```bash
pixi run earthpv calibrate-candidates --aoi pakistan
```

## What goes into P(real | size, glint)

Three instruments, combined in order of directness, each with its own blind spot.

**Mapped fraction.** The share of candidates in a size bin that already intersect
OpenStreetMap solar. Directly observed and free, but only a lower bound on precision:
being unmapped is not evidence of being false.

**Glint inversion.** For unmapped candidates, run the glint check and invert the observed
validation rate through the 500-target study's measured sensitivity curve. This works
between 500 m<sup>2</sup> and utility scale and is **blind below 500 m<sup>2</sup>**, where
sensitivity is indistinguishable from the false floor.

**Manual high-resolution review.** The only instrument that works below 500 m<sup>2</sup>.
`earthpv calibrate-sample` emits a stratified sample of unmapped candidates; a reviewer
fills a `verdict` column in JOSM or QGIS; `--manual-reviews` folds the result back in.
Twenty or more verdicts in a bin replace the glint extrapolation with a directly measured
rate and a correspondingly tight interval.

Without either of the last two, the table is an honest mapped-only lower bound and marks
itself `status: interim-mapped-only`.

## P(real) is also split by placement, and the split is not cosmetic

Since 2026-08-15 the table carries separate bins for rooftop and ground candidates
(`placement_bins`), and the current Pakistan table shows why in one picture:

![Paired bars of measured candidate precision per size bin with 90 percent credible intervals, read from the tracked Pakistan calibration table. Rooftop candidates sit between 0.56 and 0.68 in every size bin. Ground candidates sit between 0.05 and 0.24, an order of magnitude lower in the small bins.](../assets/figures/calibration_placement.svg#only-light)
![Paired bars of measured candidate precision per size bin with 90 percent credible intervals, read from the tracked Pakistan calibration table. Rooftop candidates sit between 0.56 and 0.68 in every size bin. Ground candidates sit between 0.05 and 0.24, an order of magnitude lower in the small bins.](../assets/figures/calibration_placement.dark.svg#only-dark)

A rooftop candidate and a ground candidate of the same size are different objects with
different false-positive populations: a roof-anchored detection is corroborated by
OpenStreetMap two thirds of the time, while a small ground detection is bright bare soil,
riverbed or salt flat far more often than it is a panel. A pooled table averages the two,
which let ground-mount borrow rooftop's corroboration rate in the same bin; the split is
what stopped that, and small ground bins that lack evidence fall back to an honest
`p_unmapped = 0` floor rather than inheriting the pooled value. `density.py` selects each
candidate's own placement subtable wherever one exists, and warns when it loads a table
without one for an AOI whose candidates span both placements. The `placement` column
itself comes from the building join described in
[Segmentation & the building map](segmentation.md).

## Uncertainty is propagated, not asserted

Every rate carries its binomial counts, and 90 percent credible intervals are pushed
through the whole estimator by posterior draws. Directly observed rates use a Jeffreys
Beta. The glint inversion uses a proper binomial-mixture likelihood, which stays honestly
wide where the instrument barely discriminates rather than inheriting the point
inversion's false certainty.

That width is informative. In the 100 to 500 m<sup>2</sup> bin, `p_real` sits somewhere in
[0.10, 0.89]: glint simply cannot pin it down. That interval is the quantified case for
funding the manual-review channel, and it is why the calibrated point estimate for small
bins clips to the conservative end rather than guessing.

## Ground-truth quadrats

The country snapshot is only as complete as OpenStreetMap happens to be in each place. A
**calibration box** is a small area where every real installation is known because someone
mapped all of them exhaustively. The protocol is in
[Quadrat mapping protocol](../calibration-mapping-protocol.md); the boxes mapped so far are
logged in [Calibration boxes](../issues/pakistan-calibration-boxes.md).

`--calibration-box` pools a box's own per-bin counts directly into the snapshot's counts
before the same Beta-posterior machinery runs. No separate code path, no manual override,
so a small quadrat moves the estimate by exactly as much as its sample size honestly
supports.

The first Lahore box did move the small-bin recall estimates down slightly and widened
their intervals, while the national recall-corrected total barely moved, which is the
correct behaviour for a sample that small. The interesting part is the direction: the box's
true recall sat well below the snapshot-based recall in the same bins. Not yet
statistically load-bearing, but it is the signal you would expect if snapshot recall is
optimistic, since a mapper is more likely to have already mapped exactly the installations
a model also finds easiest.

Five boxes exist so far. A visual pass corroborated three, flagged Faisalabad as suspect,
and confirmed Multan as solar-dense despite having zero OpenStreetMap solar features, which
makes it the highest-priority mapping target.

## Independent anchors

**Germany, MaStR.** The Marktstammdatenregister is legally complete, which makes Germany
the calibration bench. `earthpv mastr` downloads and aggregates it, `earthpv calibrate`
does the zonal join, and `earthpv pv-yield` cross-checks modelled generation with pvlib.
The measured 2.4 to 2.5 times aggregate over-prediction is stable from chip level to
municipality level, which is what makes it a correction rather than noise.

**Pakistan, an independent rooftop-solar estimate.** A separately produced 27.5 GW
distributed-solar study is the only comparable independent estimate. The comparison
needs care: the units do not match ours, and what first read as a 52 percentage point
coverage gap turned out to be 99.4 percent already-inferred-zero cells, leaving a true
gap of 0.33 percentage points. See
[`scripts/pv_reference_share_comparison.py`](https://github.com/open-energy-transition/earthpv/blob/main/scripts/pv_reference_share_comparison.py)
for the current version of this comparison, run against the published evidence atlas.

**Trade data.** Panel import volumes, over 13 GW in 2024 alone, bound the national total
from above and are the reason a country-wide estimate in the teens of GWp is plausible at
all.

## Hard-negative mining

Calibration measures error; hard negatives remove it. Two independent sources feed
retraining, and `--centers` merges them into one index so neither clobbers the other.

```bash
# bi-temporal: large unmapped buildings with no PV in either epoch
pixi run -e ml earthpv hard-negatives --aoi pakistan --checkpoint data/models/<run>/<epoch>.ckpt
pixi run earthpv hard-negative-chips --aoi pakistan \
    --centers data/predictions/pakistan/hard_negatives_confirmed.parquet

# vegetation-vetoed leads: the dark fallow and paddy soil class German data never showed
pixi run earthpv hard-negative-chips --aoi pakistan \
    --centers data/predictions/pakistan/hard_negatives_veg.parquet
```
