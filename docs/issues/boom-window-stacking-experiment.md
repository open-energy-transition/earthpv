# Boom-window (2021 vs current) stacking experiment — inconclusive, not a repeat of the seasonal negative

## Motivation

The two-season stacking experiment (`docs/how-it-works.md`'s "Two-season stacking"
section, `configs/terramind_pv_seasonal.yaml`) stacked a **same-year** weather contrast
(dry season vs post-monsoon, both 2025) into a 20-band TerraMind input and found no
recall improvement. That result does not test whether stacking the model input helps in
general — it tests whether it helps when there is essentially **no real adoption change**
between the two layers, since both are from the same year. Pakistan's rooftop PV stock is
dominated by a post-2022 import boom (fitted onsets cluster 2022-2024,
`docs/issues/small-pv-step-signal.md`), so a **2021-vs-current** stack has a real change
signal to learn from that the seasonal pair never had. This experiment re-runs the same
architecture with only the contrast window changed, to isolate that variable.

## Setup

New AOI `punjab_boom` (`configs/aoi.yaml`), same bbox/division/source_region/val_tiles as
`punjab`, `stack_window: ["2021-10-01", "2022-01-24"]` (the actual pre-boom window, matching
the country-wide pre-boom compose already used for `postprocess.add_epoch_prior`).
Composites live in their own tree, `data/composites/punjab_boom`, **not**
`data/composites/punjab`: the latter's `composite_1.tif` is the seasonal experiment's
stale post-monsoon-2025 layer, and both trees use the same filename convention, so
reusing punjab's tree directly would have silently trained on the wrong window. Built by
`scripts/build_punjab_boom_composites.py`: `composite_0` symlinked from punjab's existing
65 cells (current epoch, unaffected by the radiometric bug below) plus 9 freshly-fetched
cells to give full val_tiles coverage (74 cells total... 73 with usable scenes);
`composite_1` freshly built at the boom window for all of them, using the current
`imagery.py`, which **postdates** the 2026-07-26 Collection-1 baseline-offset fix — so
unlike the segmentation growth map and SPPI epoch-diff below, this run's pre-boom
composites do not carry that radiometric caveat.

Deliberately Punjab-only, not merged with Germany (no equivalent pre-boom epoch exists
there) — keeps the comparison to the seasonal result apples-to-apples on the one thing
that changed, at the cost of a small (332-chip) training set.

`configs/terramind_pv_boom.yaml`: identical architecture/hyperparameters to the seasonal
config (terramind_v1_tiny, 20-band patch-embed duplication, UNet decoder, dice loss,
class_weights [0.25, 0.75], lr 1e-4, patience 8).

## Result: not usable, and not because the hypothesis is false

`earthpv chips --aoi punjab_boom` produced 332 chips (269 with PV, 133 val — val is ~40%
of the set here, a higher fraction than train, an artifact of how few cells this AOI has,
not a deliberate split ratio). Training early-stopped at epoch 15 (best: epoch 7, ~3
minutes wall clock on a dataset this small). Evaluating that checkpoint on its own val
split:

```
Pixel IoU=0.018 F1=0.035 (tp=75944 fp=4162093 fn=6917)
Per-installation recall by size (m2):
  bucket  installations  detected  recall
1000-inf           1170          1169   0.999
500-1000            338           328   0.970
 250-500             49            49   1.000
```

Read naively, the recall numbers look like a large win over both v2 (0.554/0.161/0.138)
and the seasonal 20-band model (0.509/0.169/0.138). **They are not trustworthy.** The
pixel metrics show why: `fp=4,162,093` against `tp=75,944` is a ~55:1 false-positive-to-
true-positive ratio at the pixel level — the model is flagging the large majority of
val-chip pixels as PV, not resolving panel outlines. Per-installation recall as measured
here only checks whether *any* pixel under a mapped footprint was flagged; a model that
flags almost everything trivially "detects" every installation regardless of whether it
learned anything about what PV actually looks like. This is a training collapse, not
evidence the boom-window signal works — consistent with the training set being far
smaller (332 chips, ~199 train) than what any production checkpoint in this repo was
built on (thousands of chips, `germany` + `punjab` combined for the seasonal run).

## What this does and doesn't tell us

- **Does not confirm** the seasonal experiment's conclusion generalizes to a real
  change window — that question is still open.
- **Does not confirm** the user's hypothesis (real boom signal > same-year weather
  noise) either — the run as executed can't distinguish "stacking the real boom window
  helps" from "15 epochs on 332 chips isn't enough data for this architecture regardless
  of what the second layer is."
- **Rules out** treating the raw recall-by-size numbers above as a result. They should not
  be quoted or compared to v2/seasonal without the pixel F1 alongside them, and as
  reported here the pair should be read as "inconclusive," not "boom-stacking wins."

## What a real test would need

Substantially more in-domain training data before the recall comparison means anything:
either a much larger cell footprint (this run used the seasonal experiment's original
65-cell scope + 9 cells for val coverage, not the full ~133-cell Punjab OSM-solar-label
population identified during setup — see `populated_cells('punjab', ..., min_buildings=10**9)`,
which found 133 label-cells against the 65 actually composited), more training epochs
with stronger regularization/early-stopping patience tuned for a small-data regime, or
folding in the already-existing `karachi_coast`/`sialkot`/`mardan`/`quetta`/etc.
calibration quadrats (`docs/methods/calibration-quadrats.md`) as additional boom-window
training chips if their own pre-boom composites were built. None of this was attempted in
this session; the checkpoint (`data/models/terramind-pv-epoch=07-step=104.ckpt`) and
chip set (`data/chips/punjab_boom`) are kept for a follow-up rather than deleted.
