---
title: PVscope
hide:
  - navigation
  - toc
---

<div class="page-full-bleed embed fit" markdown>
<iframe src="../../assets/interactive/pvscope.html" title="PVscope: Sentinel-2 pixels and mapped rooftop PV as a 3D band cube and in spectral space" allow="fullscreen"></iframe>
</div>

Interactive: drag to orbit, scroll to zoom, click a pixel to pin it.
[Open full screen](../assets/interactive/pvscope.html). The per-pixel picture here is a best
case; the [rooftop classifier](roofclf.md) reads a whole footprint instead, and its measured
limits are in the experiments register under
[the spectral SNR budget](../experiments.md#the-spectral-snr-budget-and-why-the-domain-is-exhausted-2026-09-19).
Rebuild with `scripts/build_pvscope.py`, then `pixi run docs-figures`.
{ .embed-note }
