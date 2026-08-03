# Pakistan growth map

Pakistan's rooftop PV stock is dominated by a post-2022 import boom. Two independent
instruments diff the same pre-boom (2021/22) and current Sentinel-2 imagery to show
where that growth actually landed: a trained segmentation model's own recall-corrected
capacity estimate, and a model-free spectral index computed directly on each
building's own reflectance.

<div class="embed" markdown>
<iframe src="../../assets/interactive/pakistan_growth_atlas.html" title="Pakistan PV growth atlas: segmentation and SPPI epoch-diff" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Switch instrument with the tabs, hover a cell for both instruments' numbers at once.
<a href="../../assets/interactive/pakistan_growth_atlas.html" target="_blank">Open full screen</a>.
</p>

## The two instruments

**Segmentation growth.** The production TerraMind checkpoint scores a 2021/22
(pre-boom) composite and the current composite separately; each gets its own
candidates, buildings join and recall-corrected capacity estimate. This map is
current minus pre-boom, per cell: **+2,597.5 MWp** nationally (5,077.9 MWp now
against 2,480.4 MWp pre-boom), concentrated in Punjab (+1,834 MWp) and its urban
corridor -- Faisalabad, Sindh, Karachi, Sheikhpura, Lahore. A small number of cells
show an apparent *decrease*, noise from independently re-polygonizing two raster
generations rather than real capacity loss, and are not colour-mapped (only positive
growth is shown).

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

!!! info "A third approach was tried and did not work"
    A natural third idea is to give the segmentation model both epochs as input (20
    bands instead of 10) and let it learn the change signal directly, rather than
    differencing two separately-run outputs. Tried on a small Punjab-only training set
    (332 chips): the retrained checkpoint's per-installation recall looked like a large
    win, but its pixel-level F1 was 0.035 (55:1 false-positive ratio) -- the model had
    collapsed to flagging most pixels as PV, not learned anything. A training-collapse
    artifact of too little data, not evidence against the idea itself. Full write-up:
    `docs/issues/boom-window-stacking-experiment.md`.

!!! warning "Both mapped instruments share a radiometric caveat"
    The pre-boom (2021/22) composites both instruments diff against were built between
    2026-07-05 and 2026-07-25, one day before a fix to how this pipeline normalises the
    Sentinel-2 Collection-1 processing-baseline BOA offset. Some cells therefore carry a
    spurious ~1000 DN shift in the pre-boom layer relative to the current one, cell by
    cell, not uniformly -- a real, unresolved source of noise in both maps above until
    the pre-boom composites are rebuilt with the fix in place.

## Reproducing this map

```bash
# Pre-boom epoch-diff rescoring already exists via postprocess --preboom-prob-dir;
# this map instead runs a full standalone density pass on the pre-boom epoch and
# diffs it against the current one.
pixi run -e ml earthpv infer --aoi pakistan --checkpoint <checkpoint> \
    --index 1 --out-dir data/predictions_preboom
pixi run earthpv postprocess --aoi pakistan --pred-dir data/predictions_preboom
pixi run earthpv density --aoi pakistan --pred-dir data/predictions_preboom --districts
python scripts/pv_growth_map.py --aoi pakistan \
    --current-dir data/predictions --preboom-dir data/predictions_preboom

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
