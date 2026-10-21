---
hide:
  - toc
---

# PVscope

PVscope puts one 640 m window of Sentinel-2 imagery next to the solar panels mapped by hand
inside it, so you can see why most rooftop PV is hard to see from space and what the
[rooftop classifier](roofclf.md) has to work with. The window lies in the Peshawar West
calibration area, where every visible panel has been mapped, and shows the same pixels twice:
stacked by band in space, and moved into spectral space.

<div class="embed fit" markdown>
<iframe src="../../assets/interactive/pvscope.html" title="PVscope: Sentinel-2 pixels and mapped rooftop PV as a 3D band cube and in spectral space" allow="fullscreen" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Drag to orbit, scroll to zoom, click a pixel to pin it.
<a href="../../assets/interactive/pvscope.html" target="_blank">Open full screen</a>.
</p>

## Reading it

- **Image cube.** The top layer is the mapped panels and roofs, drawn at 1 m. Below it sits
  the share of each 10 m pixel the panels cover, then the ten bands from blue (492 nm) down
  to shortwave infrared (2,202 nm). The six bands that are 20 m at the sensor show as 2 by 2
  blocks. Click a pixel to drill a column through every layer, or select an array in the
  list to outline it on all of them. **Peel** lifts layers off so any band can be seen from
  above.
- **Spectral space.** The same pixels, moved to a space whose axes are three bands of your
  choice, measured as contrast to the roofs around them. The amber line is where panels push
  a pixel as their cover grows from none to all of it; the blue ellipses show how far
  PV-free roofs already scatter. A pixel only stands out once it leaves them.
- **Inspector.** The selected pixel's spectrum against nearby roofs, its PV cover on the
  10 m and the 20 m grid, and whether a score combining the bands clears two standard
  deviations of roof-to-roof variation.

## What it shows

Most mapped arrays are smaller than a single pixel: the histogram at the top of the page
counts every array in Pakistan's calibration areas against the 100 m<sup>2</sup> of a 10 m
pixel and the 400 m<sup>2</sup> of a 20 m one. On Peshawar West's concrete roofs, panels are
darker than the roof in every band, but the visible bands barely register it, and combining
all ten bands on the 20 m grid reveals more than the four sharper 10 m bands do.

That is the picture for one pixel. `roofclf` reads a whole footprint instead, averaging every
pixel under it, and the limits that approach runs into are measured in the experiments
register: roof-to-roof variation is twenty to forty times the sensor's noise
([the spectral SNR budget](../experiments.md#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19)),
and most footprints resolve to a single pixel
([most footprints are one pixel](../experiments.md#most-footprints-are-one-pixel-2026-09-20)).
Arrays a fifth of a pixel across, the norm in France, are where this
[stops working altogether](../results/france.md#earthpv-against-france-the-sub-400-m2-instrument-does-not-transfer).

## Limits

Every number on the page is fitted and tested on Peshawar West's own pixels, so it describes
those roofs, not Pakistan. The background each pixel is compared with is built from roofs the
mapping shows to be PV-free, which a deployed model cannot know: panels cluster, so a real
neighbourhood often carries them too. Read the thresholds as a best case for a single pixel.

## Rebuilding it

```bash
pixi run python scripts/build_pvscope.py   # writes results/pakistan_pvscope.html
pixi run docs-figures                      # copies it to docs/assets/interactive/pvscope.html
```

`--quadrat <stem>` points it at another calibration area, and it finds the composite cell
that covers the area unless `--composite` names one. It needs the composites, the VIDA
buildings and the area's mapped solar under `data/`, so it runs locally, not in CI.
