# Pretrained model

EarthPV's segmentation model is published as a GitHub release, so a new country can be
run without training anything first. It is a ResNet-50 fine-tuned to outline solar arrays,
139 MB, and of eight checkpoints compared at the same pixel precision it found the most
arrays in ten countries none was trained on, tied with one that was never tested over whole
cells (see [How it was chosen](#how-it-was-chosen)).

**[Download from the release](https://github.com/open-energy-transition/earthpv/releases/tag/segmentation-model-v28-2026-11-12)**
&nbsp;·&nbsp; `earthpv_segmentation_v28.ckpt` &nbsp;·&nbsp; SHA-256 `0c2a24b5...`

It replaces the TerraMind model released on 2026-10-23
([`segmentation-model-v14-2026-10-23`](https://github.com/open-energy-transition/earthpv/releases/tag/segmentation-model-v14-2026-10-23)),
which stays downloadable.

## Set up EarthPV with it

```bash
git clone https://github.com/open-energy-transition/earthpv.git
cd earthpv
pixi install              # data pipeline
pixi install -e ml        # adds PyTorch (cu126) and TerraTorch, a multi-GB solve
pixi run -e ml gpu-check  # should print your GPU
pixi run fetch-model      # -> data/models/release/earthpv_segmentation_v28.ckpt, checksum verified
```

`fetch-model` uses the standard library only, keeps an existing file whose checksum
matches, and never leaves a half-downloaded checkpoint where `infer` would load it. To do it
by hand:

```bash
mkdir -p data/models/release && cd data/models/release
curl -fLO https://github.com/open-energy-transition/earthpv/releases/download/segmentation-model-v28-2026-11-12/earthpv_segmentation_v28.ckpt
curl -fLO https://github.com/open-energy-transition/earthpv/releases/download/segmentation-model-v28-2026-11-12/SHA256SUMS
sha256sum -c SHA256SUMS
```

The file loads offline: it carries every weight, so nothing is fetched from Hugging Face.

## Run it on a country

Register the area, build imagery for it, then detect. The released checkpoint replaces the
"train" step entirely:

```bash
pixi run python scripts/new_region.py check --bbox <minlon,minlat,maxlon,maxlat> --iso3 <ISO3>
pixi run python scripts/new_region.py add   --aoi <aoi> --bbox <bbox> --iso3 <ISO3>
pixi run python scripts/new_region.py plan  --aoi <aoi>        # prints the commands below

pixi run earthpv overpass-labels --bbox <bbox> --iso3 <ISO3> --name <aoi>
pixi run earthpv compose --aoi <aoi> --window <START:END>      # hours, network-bound
pixi run -e ml earthpv infer --aoi <aoi> --checkpoint data/models/release/earthpv_segmentation_v28.ckpt
pixi run earthpv postprocess --aoi <aoi> --threshold 0.3 --max-building-dist 30
pixi run earthpv export --aoi <aoi> --exclude-mapped --min-distance-m 100
```

**Pick the compose window for your latitude.** Without `--window` (or a `compose_window`
key on the area in `configs/aoi.yaml`), `compose` uses November to mid-March, the South Asian
dry season the project started in, which is a snowy, low-sun winter in Europe. The European
runs used April or May to September, for example `--window 2026-04-01:2026-09-30`.

`export` writes ranked candidates as GeoParquet, GeoJSON and a MapRoulette challenge: the
first set of mapping leads. Run `compose` detached, as
[Scale to a new country](reproduce.md#step-3-first-pass-no-retraining) describes; it is
the long pole. Capacity (`density`, `atlas`) follows from the same predictions, see
[The full pipeline](reproduce.md#the-full-pipeline).

**Use the composites `compose` builds.** The model reads 10-band Sentinel-2 L2A median
composites (B02, B03, B04, B05, B06, B07, B08, B8A, B11, B12, in that order) as raw
Planetary Computer digital numbers divided by 10,000. For processing baseline 04.00 and
later (every scene since January 2022) that includes the +1000 offset, which must not be
subtracted. A composite on another scale is a domain shift the model was never shown.

## Use it from Python

```python
from earthpv.infer import load_model, predict_window

task, device, task_type = load_model("data/models/release/earthpv_segmentation_v28.ckpt")
prob = predict_window(window, task, device, task_type)
# window: (10, 224, 224) array of digital numbers in the band order above
# prob:   (224, 224) PV probability; the published pipeline thresholds it at 0.3
```

For a whole raster, use `earthpv infer` rather than tiling by hand: it overlap-adds windows
with a Hann taper at a stride of 104 px, which is what keeps the output free of a grid of
false positives at the window spacing.

## What it is

| | |
| --- | --- |
| Backbone | ResNet-50 pretrained by MoCo on SSL4EO-S12 Sentinel-2 (TerraTorch's `ssl4eos12_resnet50_sentinel2_all_moco`, from TorchGeo), its first convolution cut to the 10 bands, fine-tuned end to end |
| Decoder | UNet, channels 256-128-64-32-32, on all five ResNet stages; the finest skip is the 20 m stem, the output 10 m |
| Parameters | 34.6 million |
| Input | 224 &times; 224 px at 10 m (2.24 km), 10 bands as above |
| Output | Two classes, background and PV; production threshold 0.3 |
| Training labels | 29,458 chips of 2.24 km, cut around OpenStreetMap solar polygons and from background in France (18,577), South Africa (4,220), Germany (3,189), Pakistan (2,712, Punjab included) and India (Gujarat, 760): the same corpus as the 2026-10-23 release |
| Training | Tversky loss (alpha 0.3, beta 0.7, which penalises a missed array more than a false one), AdamW at 10<sup>-4</sup> after a 1,000-step warmup, cosine decay to 10<sup>-6</sup>, batch 8 with 2-step accumulation, radiometric jitter; a fixed budget of 42 epochs, and the released weights are the exponential moving average at its end (decay 0.9999), on a GTX 1060 |
| Training config | [`configs/terramind_pv_v28_resnet50_south_africa.yaml`](https://github.com/open-energy-transition/earthpv/blob/main/configs/terramind_pv_v28_resnet50_south_africa.yaml) |
| Licence | [CC BY 4.0](#licence-and-attribution), weights only |

It is built for **arrays of roughly 400 m&sup2; and up, and ground-mount at any size**.
Anything smaller is burned into the training mask as `ignore`, so the model is not trained
to find a household system. It finds about half of isolated rooftop arrays of 700-1,000
m&sup2; and few below 400 m&sup2; ([The floor](#where-it-stops)). Small rooftop PV is the
[rooftop classifier](methods/roofclf.md)'s job, which needs local calibration and is not
part of this release.

## How it was chosen

Eight checkpoints were trained on the same corpus and compared at the same pixel precision,
so a model cannot win by marking more pixels: the released TerraMind (v14), TerraMind Tiny,
Small and Base on a newer recipe, two Tiny variants (a 10 m path into the decoder, a
size-weighted loss), and two ResNet-50s, with and without that loss. An installation counts
as found when the model marks any of its pixels.

**In ten countries no checkpoint was trained on**, 4,746 chips with 2,181 rooftop arrays of
400-5,000 m&sup2; and 22,076 ground-mounted arrays of 400 m&sup2; and up:

| Checkpoint | Rooftop, 400-5,000 m&sup2; | Ground-mount | Pixel precision |
| --- | ---: | ---: | ---: |
| **v28, ResNet-50 (released)** | **85.5%** | **82.1%** | 0.81 |
| v29, TerraMind Tiny, size-weighted loss | 85.4% | 82.2% | 0.83 |
| v27, TerraMind Tiny with a 10 m path | 82.5% | 78.8% | 0.80 |
| v36, TerraMind Base | 80.4% | 79.9% | 0.80 |
| v22, TerraMind Tiny, newer recipe | 77.9% | 79.4% | 0.80 |
| v14, TerraMind Tiny (released 2026-10-23) | 77.7% | 79.6% | 0.78 |
| v41, ResNet-50, size-weighted loss | 73.1% | 79.9% | 0.85 |
| v35, TerraMind Small | 72.8% | 78.1% | 0.80 |

The countries are Egypt, India, Morocco, Namibia, Nigeria, Poland, Turkey, Vietnam, Yemen
and Zambia. Against v14, v28 finds 229 rooftop arrays v14 misses and misses 59 v14 finds
(paired McNemar p < 10<sup>-24</sup>); on ground-mount it is 924 against 363. v29, v35 and v41 stay
more precise than v14 even at threshold 0.95, so they are scored there. v29 ties v28 here,
but finds fewer rooftop arrays on the training countries' holdouts (73.3% against 79.8%), and
the same loss added to the ResNet (v41) doubled its false alarms over whole cells, a test v29
never had.

**On the held-out regions of its own training countries** (France, Germany, Pakistan, Punjab,
Gujarat, South Africa) it finds 79.8% of rooftop arrays of 400-5,000 m&sup2; against v14's
57.3% (1,148 gained, 92 lost), and 91.4% of ground-mount against 90.8%.

**Over whole cells, it finds more with about as many false alarms.** Held-out chips cannot
show the large false sheets a model can draw over farmland, so every candidate also ran over
1,000 whole South African cells and 300 Turkish ones, at the production threshold 0.3:

| At 0.3 | v14 | v28 |
| --- | ---: | ---: |
| South Africa: rooftop arrays found | 66.4% | 85.3% |
| South Africa: ground-mount found | 85.6% | 93.6% |
| South Africa: unmapped objects per 1,000 km&sup2; | 17.9 | 19.3 |
| South Africa: the 5 parks a person judged solar, kept | 5 | 5 |
| South Africa: unmapped sheets of 100,000 m&sup2; and up | v14's 102 gone, 6 new | |
| Turkey (never trained on): rooftop arrays found, of 71 | 73.2% | 95.8% |
| Turkey: ground-mount found | 89.7% | 94.1% |
| Turkey: unmapped objects per 1,000 km&sup2; | 46.7 | 52.7 |

**Against a model localized to one country it usually still finds more.** On each country's
own holdout, at the localized checkpoint's pixel precision, v28 finds more rooftop arrays
than the localized TerraMind in 12 of the 13 countries that have them (Egypt's holdout has
one, which neither finds), and more or as many ground arrays in nine. It finds fewer ground arrays in Namibia (60% against 88%), Morocco (95%
against 99%), Spain (85% against 89%), Turkey (96.9% against 98.2%) and Egypt (22 arrays):
in deserts and on dark open ground a localized model is still the better choice. A ResNet
localized the same way to Denmark found 66% of its holdout's arrays against 43% for
Denmark's localized TerraMind.

The full comparison is in the [experiment register](experiments.md#a-convolutional-network-instead-of-terramind-v28-resnet-50-2026-11-12),
and every row behind these tables is in
[`results/release_model_benchmark_v28.csv`](https://github.com/open-energy-transition/earthpv/blob/main/results/release_model_benchmark_v28.csv).

### Where it stops

Recall of isolated rooftop arrays (no other mapped array within 50 m), at 0.3, in Pakistan's
calibration areas, where every visible panel is mapped, and over 1,000 South African cells:

| Rooftop array | Pakistan, its localized TerraMind (v16) | Pakistan, v28 | South Africa, v14 | South Africa, v28 |
| --- | ---: | ---: | ---: | ---: |
| 100-200 m&sup2; | 0% | 0% | 0% | 2% |
| 200-400 m&sup2; | 2% | 7% | 2% | 16% |
| 400-700 m&sup2; | 29% | 46% | 3% | 31% |
| 700-1,000 m&sup2; | 22% | 56% | 23% | 69% |

The bins hold 9 to 67 arrays each, so read them as a direction. In Pakistan's areas v28
draws no more unmapped objects than v16 (0.17 against 0.21 per km&sup2;).

## Limits

- **A new country is a domain shift.** Every number above on a country outside the training
  set is a zero-shot transfer, and it varies widely by country: rooftop recall runs from 65%
  of 161 arrays in India to 97% in Vietnam. Fine-tuning on a country's own OpenStreetMap
  labels is what each published atlas does. Starting `train` from the released weights is
  not wired in yet; localizing means training from the pretrained backbone on your chips
  plus whatever corpus you have ([Step 5](reproduce.md#step-5-retrain-in-domain)).
- **Deserts and dark ground.** In Namibia and Morocco a TerraMind trained on the same corpus
  finds more ground-mount than this model, so the gap there is the architecture, not the
  missing local training.
- **Precision is a property of the place.** Bright bare ground, salt flats and greenhouses
  produce false positives at different rates in different landscapes. Every detection is a
  lead for a person to check against high-resolution imagery, not a confirmed installation.
- **Arrays Sentinel-2 cannot separate from their surroundings stay invisible.** Yemen's
  ~600 m&sup2; solar irrigation arrays differ from the farmland around them by about 2% per
  band; this model finds 1 of 10 held-out rooftop arrays there.

## Licence and attribution

**The model weights are released under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)**,
the licence of the [SSL4EO-S12](https://github.com/zhu-xlab/SSL4EO-S12) ResNet-50 weights
they are fine-tuned from (Wang et al., 2023, distributed by
[TorchGeo](https://huggingface.co/torchgeo/resnet50_sentinel2_all_moco)). The release carries
the licence text as `LICENSE` and the attributions as `NOTICE`. Keep `NOTICE` with the weights
if you redistribute them or a fine-tune of them.

Credit SSL4EO-S12, &copy; OpenStreetMap contributors (the training labels, ODbL 1.0) and
Copernicus Sentinel-2 when you publish results made with it, and cite this repository. The
licence covers the weights only; the code that loads them is MIT, and TerraTorch is
Apache-2.0. Detections and capacity tables made with them are derivative of OpenStreetMap and
fall under ODbL, like the project's other data outputs (see the
[README](https://github.com/open-energy-transition/earthpv#licence)).
