# Detection model

## The model

`terramind_v1_tiny`, the open TerraMind geospatial foundation model from IBM and ESA,
fine-tuned as a semantic segmentation task through TerraTorch and Lightning. Tiny is not a
compromise for its own sake: it fits a 6 GB GTX 1060, which keeps the whole project
reproducible on hardware a university lab already owns.

TerraMind is a plain vision transformer, so a UNet decoder needs a feature pyramid built
for it. The neck stack is `SelectIndices` into `ReshapeTokensToImage` into
`LearnedInterpolateToPyramidal`. Checkpoints monitor validation mIoU.

**Bands.** Local composites carry 10 bands, B02 through B12 minus the two 60 m atmospheric
bands B01 and B09. TerraMind's pretrained Sentinel-2 L2A patch embedding expects 12, so
`configs/terramind_pv.yaml` passes `backbone_bands: {S2L2A: [...]}` and TerraTorch subsets
the patch embedding to exactly those 10. The pretrained weights for the bands in use are
kept; the rest are dropped rather than zero-padded.

**Positive threshold.** `MIN_PV_AREA` in `chips.py` sets the smallest labelled array that
is burned as a positive. Arrays below it are burned as `ignore = -1`, not as negatives, so
the loss never learns that a small real array is background. Changing it means rebuilding
chips and retraining.

## What it recovers

Per-installation recall at threshold 0.3, checkpoint `v2_combined/terramind-pv-epoch=39`,
trained on 3,189 German chips plus 274 Punjabi chips:

![Per-installation detection recall by array size for the combined model: 95, 84 and 83 percent on Germany's validation states for the 250 to 500, 500 to 1000 and 1000 plus square metre buckets, against 14, 16 and 55 percent on the Punjab validation cells.](../assets/figures/recall_by_size.svg#only-light)
![Per-installation detection recall by array size for the combined model: 95, 84 and 83 percent on Germany's validation states for the 250 to 500, 500 to 1000 and 1000 plus square metre buckets, against 14, 16 and 55 percent on the Punjab validation cells.](../assets/figures/recall_by_size.dark.svg#only-dark)

Pixel IoU and F1 are 0.51 and 0.68 on Germany, 0.29 and 0.45 on Punjab.

The Punjab column is much weaker than Germany's, and it is also **three times** what the
Germany-only model achieved on the same cells (0.18 at or above 1,000 m<sup>2</sup>).
In-domain chips are the single biggest lever found so far, which is the empirical case for
the [mapping flywheel](../how-it-works.md#workflow).

The residual Punjab misses look imagery-limited rather than model-limited. The model
outputs near-zero probability on them even at threshold 0.05, and oversampling Punjab four
times did not move it. Smog-season composites, mixed pixels and label noise in the
Pakistani OpenStreetMap extract are the plausible causes.

A high false-positive rate is expected and accepted on this path. Candidates are validated
by people against high-resolution imagery, so a false positive costs seconds and a miss
costs everything.

## Two invariants that must not regress

Naive sliding-window inference produced a regular grid of false positives at the window
spacing. Both causes are fixed, and both fixes are load-bearing.

**Training centre bias, the dominant cause.** Positive chips are jittered by up to 900 m
in `chips.py::sample_chip_centers`, so the installation lands anywhere in the frame. Without
the jitter the model learns that PV is in the middle and fires once per window at
inference. The diagnostic is a spike in nearest-neighbour distance between detections at
exactly the window stride: 60 percent of detections were one stride apart before the fix,
about 7 percent after.

**Window seams.** `infer.py` overlap-adds windows with a 2D Hann taper into one seamless
raster per cell, and uses a stride that is deliberately **not** a multiple of the 16 px
transformer patch size (currently 104) so patch-edge effects decorrelate between
neighbours.

## Imagery

Sentinel-2 L2A dry-season composites, the median of roughly the twelve least-cloudy scenes
per 0.1 degree cell. Where a sibling project already downloaded per-MGRS-tile composites
they are reused; everywhere else `earthpv compose` builds them on demand from Microsoft
Planetary Computer STAC, with Earth Search on AWS Open Data as a fallback with a different
failure domain.

Compose only touches **building-populated cells**, prioritized by building density, because
rooftop PV needs roofs. That reduces "all of Pakistan" from an intractable raster job to
roughly 4,470 cells. It is network-bound at about one to two minutes per cell, and
resumable.

## Candidates and ranking

`postprocess.py` thresholds and polygonizes the probability raster, then joins each
candidate to a building footprint set in the candidates' local UTM zone, recording
`building_overlap_frac` and `building_dist_m`. Those feed a `building_prior` and
`rank_score = confidence x (0.5 + 0.5 x prior)`.

Footprints come from **VIDA Open Buildings** (Google and Microsoft combined), which is
imagery-derived and includes small unmapped structures, so "no building within 30 m"
becomes a usable false-positive signal. The Overture set of buildings above 500 m<sup>2</sup>
is the fallback. For a candidate set dominated by large arrays on already-mapped buildings
the two attribute almost identically; VIDA's advantage appears as soon as `MIN_PV_AREA`
drops toward residential scale.

## Configurations

| File | Purpose |
| --- | --- |
| `configs/terramind_pv.yaml` | production, 10-band segmentation |
| `configs/terramind_pv_fraction.yaml` | per-pixel PV coverage fraction regression |
| `configs/terramind_pv_fraction_pakistan.yaml` | fraction head retrained in domain |
| `configs/terramind_pv_seasonal.yaml` | 20-band two-season stack ([negative result](../experiments.md)) |
| `configs/terramind_pv_v3india.yaml` | Germany plus Pakistan plus India combined |
