# Tutorial: your first run

This walks through running the pipeline once, start to finish, on a tiny example
region. It takes a few minutes, not hours, and confirms your setup works before you
commit to a real run. It does not produce a usable map. That is not the point.

## Before you start

Follow [Install](reproduce.md#install) first. You need `pixi install` (the base
environment) and `pixi install -e ml` (adds PyTorch and TerraTorch, needed for
training). Confirm your GPU is visible:

```bash
pixi run -e ml gpu-check
```

If that does not report a GPU, stop here and fix that first. Nothing below will work
without one.

## Step 1: labels

```bash
pixi run earthpv labels --aoi freiburg
```

This fetches building footprints and mapped solar installations for Freiburg, a tiny
test area. It takes seconds. This step does not touch the GPU.

## Step 2: chips

```bash
pixi run earthpv chips --aoi freiburg --limit 50
```

A "chip" is a small window of satellite imagery with the solar labels burned in as a
mask. This is what the model actually trains on. `--limit 50` caps this run at 50
chips so it finishes in about a minute. A real training run uses thousands.

## Step 3: train

```bash
pixi run -e ml earthpv train --config configs/terramind_pv.yaml --smoke
```

This fine-tunes the model on the chips from step 2. `--smoke` runs only 50 optimizer
steps: enough to confirm the model loads, your GPU is used, and a checkpoint file
gets written. It is nowhere near enough training to detect anything real, so poor
numbers here are normal, not a bug.

## Step 4: evaluate

```bash
pixi run -e ml earthpv evaluate --aoi freiburg --checkpoint data/models/last.ckpt
```

This scores the checkpoint from step 3 against the labels from step 1. Because step 3
was a smoke run, treat these numbers as a check that the pipeline runs end to end, not
as a real result.

## What you just confirmed

If all four commands finished without errors, your environment is set up correctly:
GPU, PyTorch, and every data path in between. You are ready to run something real.

## Next steps

This tutorial stopped after training and evaluation. The full pipeline has more
stages after this: inference, postprocessing, export, and capacity estimation. See
[The full pipeline](reproduce.md#the-full-pipeline) for all sixteen steps in order,
with the exact commands and what each one produces.

If you want to point the pipeline at a new country instead of an existing test area,
see [Scale to a new country](reproduce.md#scale-to-a-new-country). It covers
everything from checking that a new region has usable data, through to publishing
results on this site.