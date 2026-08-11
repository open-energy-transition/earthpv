# Pakistan growth map

!!! info "A secondary product, not part of the main workflow"

    The [main workflow](../how-it-works.md) answers "how much PV is there now" and produces
    the [capacity map](capacity.md). This page answers a different question, "when did it
    appear", and is built partly on the fraction head, an instrument that was measured and
    deliberately not promoted into any published capacity figure (see
    [Experiments](../experiments.md)). Read it for the direction and the spatial pattern of
    the boom, not for capacity numbers comparable to the evidence atlas's own.

Pakistan's rooftop PV stock is dominated by a post-2022 import boom. Three independent
instruments diff the same pre-boom (2021/22) and current Sentinel-2 imagery to show
where that growth actually landed: a trained segmentation model's own recall-corrected
capacity estimate, that same checkpoint's fraction head reaching below its 400 m²
detection floor, and a model-free spectral index computed directly on each building's
own reflectance.

**The segmentation instrument's absolute numbers below predate the 2026-08-11
ground-mount/placement-split fixes** ([Capacity map](capacity.md) has the current
methodology and numbers) -- this page's "current" epoch was inferred and aggregated
separately, before those fixes, and has not been re-run against them. The *direction*
of the finding (large, boom-driven growth, concentrated in Punjab's urban corridor) is
not expected to change; the absolute MWp figures below should be read as pre-fix and
not compared directly to the evidence atlas's own current total.

<div class="embed" markdown>
<iframe src="../../assets/interactive/pakistan_growth_atlas.html" title="Pakistan PV growth atlas: segmentation, fraction and SPPI epoch-diff" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Switch instrument with the tabs, hover a cell for all three instruments' numbers at once.
<a href="../../assets/interactive/pakistan_growth_atlas.html" target="_blank">Open full screen</a>.
</p>

## The three instruments

**Segmentation growth.** The production TerraMind checkpoint scores a 2021/22
(pre-boom) composite and the current composite separately; each gets its own
candidates, buildings join and recall-corrected capacity estimate. This map is
current minus pre-boom, per cell: **+2,597.5 MWp** nationally (5,077.9 MWp now
against 2,480.4 MWp pre-boom), concentrated in Punjab (+1,834 MWp) and its urban
corridor -- Faisalabad, Sindh, Karachi, Sheikhpura, Lahore. A small number of cells
show an apparent *decrease*, noise from independently re-polygonizing two raster
generations rather than real capacity loss, and are not colour-mapped (only positive
growth is shown).

**Fraction growth.** The same checkpoint's fraction head predicts per-pixel PV
coverage rather than a threshold, so unlike segmentation's own expected-area
instrument it is not trained blind below the 400 m² floor -- it is the only growth
instrument here with real sub-400 m² sensitivity. Scored on both epochs the same way
as segmentation (same mechanics, different instrument): **+2,175.0 MWp** nationally
(6,647.2 MWp now against 4,472.2 MWp pre-boom, +49%), also concentrated in Punjab
(+1,587 MWp). It is **probability-weighted with no precision correction**, unlike
segmentation's recall- and precision-corrected figure, and the fraction head's
absolute scale is not independently established: a German MaStR benchmark found it
2.5 to 13x high depending on how well-mapped the comparison area is. Read the delta
as directional and small-PV-inclusive, not a calibrated capacity number.

**SPPI onset.** SPPI (He et al. 2026) is a fixed five-band spectral formula, not a
trained model; a building "onset" here means its SPPI crossed the has-PV threshold
between the pre-boom and current composite. 815,351 buildings onset nationally, 73.9
km² of roof area. Converting that area to capacity at 0.18 kWp/m² with **no precision
weighting at all** gives an explicit, **uncalibrated ceiling of 13,303.3 MWp** -- not
a validated estimate, the same way this project's other flat-precision ceilings are
not. Its regional spread (meaningful capacity in Balochistan and Gilgit-Baltistan, not
just Punjab) matches SPPI's documented weak spot on bare and arid terrain rather than
a validated finding; read onset numbers outside Punjab's urban core with more
skepticism than inside it.

!!! info "A fourth approach was tried and did not work"
    A natural fourth idea is to give the segmentation model both epochs as input (20
    bands instead of 10) and let it learn the change signal directly, rather than
    differencing two separately-run outputs. Tried on a small Punjab-only training set
    (332 chips): the retrained checkpoint's per-installation recall looked like a large
    win, but its pixel-level F1 was 0.035 (55:1 false-positive ratio) -- the model had
    collapsed to flagging most pixels as PV, not learned anything. A training-collapse
    artifact of too little data, not evidence against the idea itself. Full write-up:
    `docs/issues/boom-window-stacking-experiment.md`.

!!! warning "All three mapped instruments share a radiometric caveat"
    The pre-boom (2021/22) composites all three instruments diff against were built
    between 2026-07-05 and 2026-07-25, one day before a fix to how this pipeline
    normalises the Sentinel-2 Collection-1 processing-baseline BOA offset. Some cells
    therefore carry a spurious ~1000 DN shift in the pre-boom layer relative to the
    current one, cell by cell, not uniformly -- a real, unresolved source of noise in
    all three maps above until the pre-boom composites are rebuilt with the fix in
    place.

## Reproducing this map

```bash
# Pre-boom epoch-diff rescoring already exists via postprocess --preboom-prob-dir;
# this map instead runs a full standalone density pass on the pre-boom epoch and
# diffs it against the current one.
pixi run -e ml earthpv infer --aoi pakistan --checkpoint <segmentation checkpoint> \
    --index 1 --out-dir data/predictions_preboom
pixi run earthpv postprocess --aoi pakistan --pred-dir data/predictions_preboom
pixi run earthpv density --aoi pakistan --pred-dir data/predictions_preboom --districts
python scripts/pv_growth_map.py --aoi pakistan \
    --current-dir data/predictions --preboom-dir data/predictions_preboom

# Fraction growth: same pre-boom composite, fraction-head checkpoint, --fraction-prob-dir
# on both epochs' density runs, then the same diff script against those two runs
pixi run -e ml earthpv infer --aoi pakistan --checkpoint <fraction checkpoint> \
    --index 1 --out-dir data/predictions_fraction_preboom
pixi run earthpv density --aoi pakistan --pred-dir <preboom candidates dir> \
    --fraction-prob-dir data/predictions_fraction_preboom/pakistan/prob
python scripts/pv_growth_map.py --aoi pakistan \
    --current-dir <current fraction density dir> --preboom-dir <preboom fraction density dir>

# SPPI epoch-diff: no model, no GPU, reads both composite layers directly
python -c "from earthpv.sppi import score_buildings_national_growth as f; \
  f(aoi='pakistan', composites='data/composites/pakistan', out_dir='data/sppi_growth/pakistan')"
python scripts/sppi_growth_map.py

# Atlas
python scripts/build_pakistan_pv_growth_atlas.py
```

See [Setup New Country](../reproduce.md) for the stages that produce the underlying
rasters, and [Capacity density](../methods/density.md) for how a single epoch's
capacity number is derived in the first place.
