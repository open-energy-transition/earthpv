# Pretrained model

EarthPV's segmentation model is published as a GitHub release, so a new country can be
run without training anything first. It is a fine-tuned TerraMind, 33 MB, and it is the
checkpoint that scored best on held-out regions in eleven countries (see
[How it was chosen](#how-it-was-chosen)).

**[Download from the release](https://github.com/open-energy-transition/earthpv/releases/tag/segmentation-model-v14-2026-10-23)**
&nbsp;·&nbsp; `earthpv_segmentation_v14.ckpt` &nbsp;·&nbsp; SHA-256 `d39d38a8...`

## Set up EarthPV with it

```bash
git clone https://github.com/open-energy-transition/earthpv.git
cd earthpv
pixi install              # data pipeline
pixi install -e ml        # adds PyTorch (cu126) and TerraTorch, a multi-GB solve
pixi run -e ml gpu-check  # should print your GPU
pixi run fetch-model      # -> data/models/release/earthpv_segmentation_v14.ckpt, checksum verified
```

`fetch-model` uses the standard library only, keeps an existing file whose checksum
matches, and never leaves a half-downloaded checkpoint where `infer` would load it. To do it
by hand:

```bash
mkdir -p data/models/release && cd data/models/release
curl -fLO https://github.com/open-energy-transition/earthpv/releases/download/segmentation-model-v14-2026-10-23/earthpv_segmentation_v14.ckpt
curl -fLO https://github.com/open-energy-transition/earthpv/releases/download/segmentation-model-v14-2026-10-23/SHA256SUMS
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
pixi run -e ml earthpv infer --aoi <aoi> --checkpoint data/models/release/earthpv_segmentation_v14.ckpt
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

task, device, task_type = load_model("data/models/release/earthpv_segmentation_v14.ckpt")
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
| Backbone | TerraMind 1.0 tiny (`terramind_v1_tiny`, IBM and ESA), fine-tuned end to end through TerraTorch |
| Decoder | UNet, channels 256-128-64-32, on a feature pyramid from ViT blocks 2, 5, 8 and 11 |
| Parameters | 8.2 million |
| Input | 224 &times; 224 px at 10 m (2.24 km), 10 bands as above |
| Output | Two classes, background and PV; production threshold 0.3 |
| Training labels | 29,458 chips of 2.24 km, cut around OpenStreetMap solar polygons and from background in Germany (3,189), Pakistan (2,712, Punjab included), India (Gujarat, 760), France (18,577) and South Africa (4,220) |
| Training | Tversky loss (alpha 0.3, beta 0.7, which penalises a missed array more than a false one), AdamW at 10<sup>-4</sup>, batch 8 with 2-step accumulation; best epoch 41 of 49 by validation mIoU (0.811) on geographic holdouts, 16 hours on a GTX 1060 |
| Training config | [`configs/terramind_pv_v14_south_africa.yaml`](https://github.com/open-energy-transition/earthpv/blob/main/configs/terramind_pv_v14_south_africa.yaml) |
| Licence | [Apache-2.0](#licence-and-attribution), weights only |

It is built for **arrays of roughly 400 m&sup2; and up, and ground-mount at any size**.
Anything smaller is burned into the training mask as `ignore`, so the model is not trained
to find a household system, and mostly does not. Small rooftop PV is the
[rooftop classifier](methods/roofclf.md)'s job, which needs local calibration and is not
part of this release.

## How it was chosen

Seven checkpoints were scored on 2026-10-23 on the same held-out chips in eleven regions:
`v5_combined_france`, the generalist every localized model
was compared against, and the six models localized to one more country each, all trained
with the same recipe. A held-out chip is one the checkpoint never trained on. An
installation of 400 m&sup2; or more counts as found when the model marks any of its pixels at
threshold 0.3.

**On the six holdouts that are in every training corpus and held out of all of them**, the
only comparison fair to all seven:

| Checkpoint | Installations found | Rooftop, 400-5,000 m&sup2; | Ground-mount | Pixel precision | Pixel IoU |
| --- | ---: | ---: | ---: | ---: | ---: |
| **v14, South Africa (released)** | **65.6%** | **51.5%** | **78.2%** | 0.74 | 0.61 |
| v15, Poland | 63.7% | 48.0% | 77.7% | 0.77 | 0.62 |
| v5, the generalist | 63.3% | 48.3% | 76.6% | 0.77 | 0.61 |
| v9, Vietnam | 60.1% | 42.6% | 75.9% | 0.76 | 0.62 |
| v11, Morocco | 56.4% | 38.7% | 72.2% | 0.76 | 0.61 |
| v12, Egypt | 54.6% | 34.2% | 73.2% | 0.75 | 0.60 |
| v10, India | 48.9% | 29.2% | 66.5% | 0.74 | 0.59 |

That is 4,270 installations in France, Germany, Pakistan, Punjab and the Surat-Bharuch-Vadodara
box in Gujarat, the last scored on both the Gujarat and the national India chips.

**Head to head against v5, leaving out South Africa** (v14's own country), v14 finds 84.4%
of 10,882 held-out installations against 81.5%: 496 found only by v14, 179 only by v5
(paired McNemar p < 10<sup>-30</sup>). On rooftop arrays of 400-5,000 m&sup2;, the hardest class,
it is 52.3% against 49.1% (p = 6 &times; 10<sup>-5</sup>). With Poland left out as well, where its
gain is largest, it still finds more (76.9% against 75.4%, p = 7 &times; 10<sup>-7</sup>).

| Region | Holdout | Installations | Found, v5 | Found, v14 | Pixel precision, v5 | Pixel precision, v14 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| France | in corpus, held out | 2,217 | 48% | 51% | 0.81 | 0.76 |
| Germany | in corpus, held out | 495 | 90% | 89% | 0.73 | 0.66 |
| Pakistan | in corpus, held out | 420 | 71% | 75% | 0.61 | 0.61 |
| Punjab (Pakistan) | in corpus, held out | 577 | 64% | 66% | 0.50 | 0.50 |
| Gujarat (India) | in corpus, held out | 290 | 94% | 95% | 0.80 | 0.78 |
| India, same box | in corpus, held out | 271 | 94% | 96% | 0.77 | 0.75 |
| Poland | never seen | 4,334 | 91% | 96% | 0.79 | 0.69 |
| Vietnam | never seen | 446 | 97% | 97% | 0.76 | 0.72 |
| Morocco | never seen | 1,809 | 99% | 99% | 0.98 | 0.67 |
| Egypt | never seen | 23 | 4% | 4% | 0.59 | 0.82 |
| South Africa | v14's own, held out | 4,700 | 76% | 78% | 0.64 | 0.78 |

**What it costs is precision.** v14 marks more pixels: outside South Africa its pixel
precision is 0.72 against v5's 0.79. In Morocco it spreads beyond the parks into the desert
around them, 38,572 false-positive pixels against v5's 1,862, while finding the same 99% of
installations. A higher threshold buys back little: at 0.8 it still finds 83.8% outside
South Africa, at precision 0.73. Pixel precision here treats OpenStreetMap as complete, which
it is nowhere, so every figure in that column is a lower bound.

**Why recall decides.** EarthPV is recall-first: every detection goes to a person, and a
missed array is simply missing from the map. The ship rule the project applies to every
localized model is the same one, installation recall first and pixel IoU only on a tie.
If your country is mostly desert ground-mount, or you need clean outlines more than you need
every lead, v15 is the most precise checkpoint in the set (pixel precision 0.79 and IoU 0.66
outside South Africa, at 83.6% recall). It is not part of this release.

Every row behind these tables, per region and checkpoint, is in
[`results/release_model_benchmark.csv`](https://github.com/open-energy-transition/earthpv/blob/main/results/release_model_benchmark.csv).

## Limits

- **A new country is a domain shift.** Every number above on a country outside the training
  set is a zero-shot transfer, and it varies widely: on the four countries it never saw it finds 96% of held-out installations in Poland, 97% in Vietnam, 99% in Morocco and 4% in Egypt. Fine-tuning on a
  country's own OpenStreetMap labels is what moved South Africa's pixel IoU from 0.36 to
  0.67. Starting `train` from the released weights is not wired in yet; localizing means
  training from TerraMind on your chips plus whatever corpus you have
  ([Step 5](reproduce.md#step-5-retrain-in-domain)).
- **Precision is a property of the place.** Bright bare ground, salt flats and greenhouses
  produce false positives at different rates in different landscapes. Every detection is a
  lead for a person to check against high-resolution imagery, not a confirmed installation.
- **Arrays Sentinel-2 cannot separate from their surroundings stay invisible.** Yemen's
  ~600 m&sup2; solar irrigation arrays differ from the farmland around them by about 2% per
  band and no checkpoint finds them.

## Licence and attribution

**The model weights are released under the
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)**, the same licence as
[TerraMind 1.0](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-tiny), from which
they derive. The release carries the licence text as `LICENSE` and the attributions as
`NOTICE`. Keep `NOTICE` with the weights if you redistribute them or a fine-tune of them.

Credit TerraMind (IBM and ESA), &copy; OpenStreetMap contributors (the training labels,
ODbL 1.0) and Copernicus Sentinel-2 when you publish results made with it, and cite this
repository. The licence covers the weights only. Detections and capacity tables made with
them are derivative of OpenStreetMap and fall under ODbL, like the project's other data
outputs (see the [README](https://github.com/open-energy-transition/earthpv#licence)).
