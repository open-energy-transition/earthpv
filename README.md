<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/figures/earthpv-logo-mark-white.png">
  <img src="docs/assets/figures/earthpv-logo-mark.png" width="132" alt="earthpv logo">
</picture>

# earthpv

**Open, global photovoltaic mapping from free satellite imagery.**

[Documentation](https://open-energy-transition.github.io/earthpv/) &nbsp;·&nbsp;
[Capacity map](https://open-energy-transition.github.io/earthpv/results/capacity/) &nbsp;·&nbsp;
[Growth](https://open-energy-transition.github.io/earthpv/results/growth/) &nbsp;·&nbsp;
[Workflow](https://open-energy-transition.github.io/earthpv/how-it-works/#workflow) &nbsp;·&nbsp;
[Setup a new country](https://open-energy-transition.github.io/earthpv/reproduce/) &nbsp;·&nbsp;
[Experiments](https://open-energy-transition.github.io/earthpv/how-it-works/#experiments) &nbsp;·&nbsp;
[Community](https://open-energy-transition.github.io/earthpv/#community)

</div>

---

> **EarthPV demonstrates how free Sentinel-2 imagery, an open foundation model, and
> human-in-the-loop validation in OpenStreetMap can make global photovoltaic mapping more
> scalable, verifiable, and cost-effective than existing methods.**

EarthPV fine-tunes the open **TerraMind** geospatial foundation model (IBM and ESA, through
TerraTorch) on **Sentinel-2** imagery, which is free, global and refreshed every five days,
and puts every detection in front of **OpenStreetMap** mappers for verification. The
verified result becomes the next round of training data. Model, code, training labels and
capacity numbers are all open, and every input is a global dataset -- nothing here is built
on imagery or licences that only exist in one country.

**Pakistan is the first pilot, not the destination.** It is where four methods below were
built and measured; the plan is to run the same pipeline everywhere Sentinel-2 flies. See
[Scaling worldwide](#scaling-worldwide).

## The main workflow: two detectors, one per size regime, one evidence atlas

This is earthpv's default pipeline and primary output. No single instrument covers
rooftop solar at every scale, so it runs two, each measured against ground truth, and
combines them into one product:

**Segmentation, for individual arrays ≥ 400 m².** A fine-tuned TerraMind-tiny outlines
panels directly, exported as ranked GeoParquet, GeoJSON and a MapRoulette challenge for
human validation. Recall on the Germany validation states is 0.83 to 0.95 depending on
array size; recall on Punjab rooftops went from 0.18 to 0.55 once verified in-domain
training data closed the loop.

**roofclf, for everything smaller -- and now for large rooftops too.** At 10 m
resolution, a 100 m² array is a handful of mixed pixels -- not enough to draw a polygon
around, but enough to ask whether a *building* carries PV. **roofclf** is a per-building
classifier trained on exhaustively mapped ground-truth quadrats (0.874 AUC on roofs
under 500 m², where segmentation scores 0.50), cross-checked against **SPPI**, a
zero-training five-band spectral index (He et al. 2026) that needs no labels at all
(0.823 AUC on the same quadrats). They agree often enough to raise measured precision
from 0.55 to 0.62 when both flag a building. Segmentation's blind spot turns out not to
be building size but *installation* size -- a small array on a large roof is invisible to
it too -- so as of 2026-08-07 roofclf's own rooftop estimate (AUC 0.896 vs segmentation's
0.73-0.78 on the identical ≥ 400 m² buildings) replaces segmentation's rooftop total
inside the density-matched cells; segmentation remains the only instrument for
ground-mount, which has no building footprint to classify. See
[Capacity density](https://open-energy-transition.github.io/earthpv/methods/density/).

**Both halves converge on the evidence atlas.** `density` aggregates segmentation's
≥ 400 m² detections; `roof-classifier` → `roofclf-score-national` → `sub400-capacity`
does the same for roofclf's < 400 m² population; `earthpv atlas` combines them into two
tiers by *standard of proof* rather than one point estimate -- **Verified** (hand-mapped
OpenStreetMap, or roofclf and SPPI agreeing) and **Best estimate** (this project's own
highest defensible figure) -- with the overlap between OSM and detections removed rather
than double-counted. Full command sequence:
[The full pipeline](https://open-energy-transition.github.io/earthpv/reproduce/#the-full-pipeline).

### Optional, supplementary instruments

Everything below is evidence toward the main workflow, a secondary product built from
the same detections, or a documented negative result -- not a competing main path.

**Glint, for tilt and orientation.** A glass-fronted panel is partly a mirror, so it
flashes into Sentinel-2 only on the geometry-predictable dates when its tilt and azimuth
bisect the sun and the sensor. Two or more mutually consistent flashes are a physical
confirmation that PV is present, independent of spectral appearance, and recover how the
panel is mounted. Folds into the main workflow's leads ranking as a boost-only signal;
never required to produce the evidence atlas.

**Growth, for when installations appeared.** Diffing a pre-boom (2021/22) Sentinel-2
composite against the current one -- with both the segmentation model and SPPI run
independently on each epoch -- shows where solar capacity actually landed, not just where
it stands today. Pakistan's own rooftop stock roughly doubled since 2021/22 by this
measure. See [Growth](https://open-energy-transition.github.io/earthpv/results/growth/).

A fraction-head expected-area instrument, SPPI as a standalone (not cross-checked)
detector, an older Low/Central/High/All-PV bracket atlas, a Germany MaStR cross-check,
and a rooftop potential/saturation atlas exist too, each measured and each kept in the
repository whether or not it was promoted -- see
[Experiments](https://open-energy-transition.github.io/earthpv/how-it-works/#experiments)
for what was tried and why the main workflow above is what shipped.

<p align="center">
  <a href="https://open-energy-transition.github.io/earthpv/results/capacity/">
    <img src="docs/assets/figures/pakistan_evidence_atlas.png" width="560"
         alt="The earthpv evidence atlas: two tiers by standard of proof for Pakistan's rooftop solar capacity -- Verified (7,869 MWp, hand-mapped or two detectors agreeing) and Best estimate (15,843 MWp, the project's own defensible figure) -- above a night-lights style map of estimated capacity per 0.1 degree cell concentrated in the Punjab corridor and the Karachi industrial belt.">
  </a>
</p>

<p align="center"><em>Two tiers by standard of proof, not by point estimate: what a person
mapped or two detectors agree on, and this project's own best defensible figure.
<a href="https://open-energy-transition.github.io/earthpv/results/capacity/">Open the
interactive version</a>.</em></p>

## Scaling worldwide

Nothing in the pipeline is Pakistan-specific. All four inputs are global open datasets:

| Input | Source | Coverage |
| --- | --- | --- |
| Imagery | Copernicus Sentinel-2 L2A | global, every five days, free |
| Labels | OpenStreetMap, live Overpass or Overture | global, wherever mappers have been |
| Footprints | VIDA Open Buildings | global, imagery-derived |
| Boundaries | geoBoundaries, CC-BY | global, ADM1 and ADM2 |

Three commands set up a region that has never been touched. The first is read-only and
tells you within a couple of minutes whether the data is actually there.

```bash
pixi run python scripts/new_region.py check --bbox 98.5,7.8,101.0,10.2 --iso3 THA
pixi run python scripts/new_region.py add   --aoi surat_thani --bbox 98.5,7.8,101.0,10.2 --iso3 THA
pixi run python scripts/new_region.py plan  --aoi surat_thani
```

`check` probes OpenStreetMap label density, VIDA availability, geoBoundaries, Sentinel-2
cloud cover in your composite window, and the compose budget. `add` writes the AOI block.
`plan` prints the ordered runbook with the region's name filled in.

A first candidate set needs no local training data: the existing checkpoint runs unchanged.
What closes the domain gap afterwards is local mapping, which is why the guide starts by
telling you to find a mapping community before you run anything. **Programme targets are
Mexico, Japan, Korea, Indonesia, India, Brazil, South Africa and Nigeria**; Gujarat is
already registered as a worked template, with a first full, segmentation-only capacity
estimate (812.6 MWp, ≥ 400 m², no calibration quadrats yet) at
[Gujarat capacity map](https://open-energy-transition.github.io/earthpv/results/gujarat/).

Full guide, including what to expect by starting condition and what genuinely differs from
Pakistan (climate windows, roof type, latitude-dependent glint geometry, installation-size
distribution): **[Setup a new country](https://open-energy-transition.github.io/earthpv/reproduce/)**.

## Pakistan: the pilot, in numbers

Pakistan's installed solar capacity is reported anywhere between
[6.8 GW officially and 47 GW by NGO estimates](https://ember-energy.org/latest-insights/the-solarisation-of-pakistans-energy-economy/).
Nobody can check those numbers, because the maps behind them are built on commercial
high-resolution imagery that cannot be shared and that most licences forbid processing
with AI. earthpv's own numbers come from
[the main workflow](#the-main-workflow-two-detectors-one-per-size-regime-one-evidence-atlas)
above, with a stated standard of proof:

| | |
| --- | --- |
| **7,869 MWp** | Verified: hand-mapped in OpenStreetMap, or two independent detectors agree |
| **15,843 MWp** | Best estimate: this project's own highest defensible figure |
| **+2,598 MWp** | Rooftop growth measured since the 2021/22 pre-boom epoch (segmentation, recall-corrected) |
| **16,085** | individual installations hand-mapped in OpenStreetMap |
| **400 m²** | per-object segmentation floor at Sentinel-2's 10 m resolution; roofclf/SPPI reach below it |

Every number above carries the same caveat: **this is a screening and estimation layer,
not a register**. No human has validated most of it at scale, and the sub-400 m² share of
Best estimate in particular is restricted to a small, density-matched slice of the
country, not a national measurement. See
[Capacity map](https://open-energy-transition.github.io/earthpv/results/capacity/) for how
each tier is derived and what it does and does not claim.

## The OpenStreetMap mapping loop

The technical novelty is not one model. It is a loop that combines free low-resolution
imagery, an open foundation model, and human mappers working inside OpenStreetMap with the
high-resolution imagery they are already licensed to look at.

<p align="center">
  <img src="docs/assets/figures/osm_ai_flywheel.svg" width="720"
       alt="The mapping flywheel: OpenStreetMap labels train a TerraMind model on Sentinel-2 imagery, the model publishes ranked candidates as mapping leads, local mappers verify each lead against high-resolution imagery in the OpenStreetMap editor, and the verified installations become the next round of training labels.">
</p>

Two licences pull in opposite directions, and the loop is what resolves them. Sentinel-2 is
free and global but coarse; Esri, Bing and Mapbox resolve individual panels but only allow
a *person* to trace from them inside the OpenStreetMap editor. So the machine only ever
reads Sentinel-2, people only ever read the high-resolution layers, and the verified
installations they map are ordinary, openly licensed OpenStreetMap features that are
legitimate training data for the next model. Full description:
[Workflow](https://open-energy-transition.github.io/earthpv/how-it-works/#workflow).

<p align="center">
  <a href="https://open-energy-transition.github.io/earthpv/results/pv-pose/">
    <img src="docs/assets/figures/pakistan_pv_pose.png" width="480"
         alt="The glint pose survey page: a polar plot of fitted tilt and azimuth for 290 Pakistani installations, clustered between east-southeast and due south at tilts of roughly 5 to 20 degrees.">
  </a>
</p>

<p align="center"><em>Panel pose recovered from Sentinel-2 glint for 290 Pakistani
installations, out of 2,000 checked.
<a href="https://open-energy-transition.github.io/earthpv/results/pv-pose/">Open the
interactive version</a>.</em></p>

## Quickstart

```bash
pixi install              # data pipeline: DuckDB, geopandas, rasterio, odc-stac
pixi install -e ml        # adds PyTorch cu126 (Pascal-safe) and TerraTorch
pixi run -e ml gpu-check

# minutes-long smoke test through every GPU stage
pixi run earthpv labels --aoi freiburg
pixi run earthpv chips  --aoi freiburg --limit 50
pixi run -e ml earthpv train --config configs/terramind_pv.yaml --smoke
pixi run -e ml earthpv evaluate --aoi freiburg --checkpoint data/models/last.ckpt
```

The main workflow is `labels → chips → train → evaluate → compose → infer →
postprocess → export` for the ≥ 400 m² segmentation half, `density → check-density` to
turn its detections into capacity, and `roof-classifier → roofclf-score-national →
sub400-capacity → atlas` for the < 400 m² roofclf half and the evidence atlas that
combines both -- this project's primary output. Every stage is resumable and safe to
re-run. The full runbook, including how to bring up a country that has never been
touched, is in
[Setup a new country](https://open-energy-transition.github.io/earthpv/reproduce/#the-full-pipeline).

## What did not work

Most of what was tried here failed, and the negative results are documented because they
map where the 10 m resolution limit actually is: two-season band stacking (including a
retry stacking the actual pre-boom epoch instead of a weather season), Sentinel-1 corner
reflection, two separate routes from glint to density, roof-axis orientation priors, and
three super-resolution variants. Every one has runnable code in `scripts/`. See
[Experiments](https://open-energy-transition.github.io/earthpv/how-it-works/#experiments).

## Community

earthpv is the software half of **TraceTheSun**, a pilot run by
[Open Energy Transition](https://openenergytransition.org) to make PV mapping
cost-effective, verifiable, community-driven and local, worldwide. The Pakistani results
rest on four OET-funded interns at the **Lahore University of Management Sciences**, led by
[Muhammad Awais](https://www.linkedin.com/in/awais307/), who do the mapping, validation,
model development and ground-truth quadrat work that makes the pilot's numbers checkable.

The most valuable contribution is **verified installations in OpenStreetMap**, in any
country. Load the
[mapping leads](https://open-energy-transition.github.io/earthpv/results/leads/) into
MapRoulette or JOSM, check them against the high-resolution layers, and map what is real.
See [Community](https://open-energy-transition.github.io/earthpv/#community) for the
quadrat protocol, the current partner list, and the other ways in.

## Documentation

This README is the short version. The full documentation is at
**<https://open-energy-transition.github.io/earthpv/>** and covers the
[capacity map](https://open-energy-transition.github.io/earthpv/results/capacity/),
[growth map](https://open-energy-transition.github.io/earthpv/results/growth/),
[mapping leads](https://open-energy-transition.github.io/earthpv/results/leads/),
[panel pose](https://open-energy-transition.github.io/earthpv/results/pv-pose/),
the [detection](https://open-energy-transition.github.io/earthpv/methods/detection/),
[density](https://open-energy-transition.github.io/earthpv/methods/density/),
[glint](https://open-energy-transition.github.io/earthpv/methods/glint/) and
[calibration](https://open-energy-transition.github.io/earthpv/methods/calibration/)
methods, the [experiment log](https://open-energy-transition.github.io/earthpv/how-it-works/#experiments),
and the [new-country setup guide](https://open-energy-transition.github.io/earthpv/reproduce/).

Build it locally with `pixi run docs-figures && pixi run -e docs docs-serve`.

## Licence

Code MIT. Imagery from Copernicus Sentinel-2; building footprints from VIDA Open Buildings
and Overture Maps; labels from OpenStreetMap contributors under ODbL; administrative
boundaries from geoBoundaries under CC-BY.
