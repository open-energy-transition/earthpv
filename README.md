<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/figures/earthpv-logo-mark-white.png">
  <img src="docs/assets/figures/earthpv-logo-mark.png" width="132" alt="EarthPV logo">
</picture>

# EarthPV

**Free, Open and Global Mapping of Photovoltaic Systems Above 10 kWp**   
**Including Capacity, Growth and Orientation**

[Documentation](https://open-energy-transition.github.io/earthpv/) &nbsp;·&nbsp;
[Setup a new country](https://open-energy-transition.github.io/earthpv/reproduce/) &nbsp;·&nbsp;
[Experiments](https://open-energy-transition.github.io/earthpv/experiments/) &nbsp;·&nbsp;
[Join the Community on Discord](https://discord.gg/T5zh6N24Hv)

</div>

---

> [!WARNING]
> **Active development.** EarthPV is alpha stage: it is actively experimenting
> with new solar detection methods, and its detectors, calibration and headline numbers
> are still being tested and revised rather than settled.

EarthPV fine-tunes the open **TerraMind** geospatial foundation model (IBM and ESA, through.
TerraTorch) on **Sentinel-2** imagery, which is free, global and refreshed every five days,
and puts every detection in front of **OpenStreetMap** mappers for verification. The
verified result becomes the next round of training data. Model, code, training labels and
capacity numbers are all open, and every input is a global dataset - nothing here is built
on imagery or licences that only exist in one country.

<p align="center">
  <a href="https://open-energy-transition.github.io/earthpv/atlas/">
    <img src="docs/assets/figures/pakistan_evidence_atlas.png" width="560"
         alt="The EarthPV evidence atlas: Pakistan's rooftop solar capacity, best estimate 24,330 MWp (90 percent range 20,822 to 33,582) - a night-lights style map of estimated capacity per 0.1 degree cell concentrated in the Punjab corridor and the Karachi industrial belt.">
  </a>
</p>

<p align="center"><em>This project's own highest defensible figure, not a bare point
estimate: hand-mapped OpenStreetMap installations, the model's own recall-corrected
detections, and a per-building density estimate for small rooftops, with a 90 percent
range attached.
<a href="https://open-energy-transition.github.io/earthpv/atlas/">Open the
interactive version</a>.</em></p>

## How small an installation does it find?

Measured on 30 exhaustively hand-mapped Pakistani
calibration areas (123,898 buildings), at the same operating point the published atlas
uses, binned by how much panel actually sits on the roof:

| Panel area on the roof | Roughly | Found |
| -- | -- | -- |
| Above 100 m² | above 20 kWp | 92% rising to over 99% |
| 50 to 100 m² | 10 to 20 kWp | 83% |
| 20 to 50 m² | 4 to 9 kWp | 49% |
| Below 20 m² | below 4 kWp | 22 to 31% |

**In one line: EarthPV finds most rooftop PV above roughly 50 m² of panel, call it 10 kWp,
is close to a coin flip between 20 and 50 m², and misses most of what is smaller.**

Four things qualify that, and they matter more than the exact percentages.

**It is recall-first, not precision-first.** At the same operating point roughly 1 in 10
PV-free buildings is also flagged. Detections are mapping leads meant for human
verification in OpenStreetMap, not a finished inventory.

## The main workflow: two detectors, split by placement and calibration coverage, one evidence atlas

This is EarthPV's default pipeline and primary output. No single instrument covers
rooftop solar at every scale, so it runs two, each measured against ground truth, and
combines them into one product. The split is **not** a clean size boundary: roofclf's
reach now extends past its original sub-400 m² floor into large rooftops too, wherever
it has been calibrated to do so.

<p align="center">
  <img src="docs/assets/figures/evidence_workflow.svg" width="720"
       alt="The evidence atlas workflow: Sentinel-2 imagery, OpenStreetMap solar mapping and VIDA building footprints feed two detectors - TerraMind segmentation for arrays of 400 square metres and above plus all ground-mount, and the per-building roofclf classifier cross-checked with SPPI. Both are calibrated against 30 hand-mapped ground-truth quadrats, then combined one best instrument per component with overlaps removed and each cell floored at hand-mapped OSM plus roofclf-and-SPPI agreement, producing the published evidence atlas: Best estimate 24,330 MWp with a 90 percent range of 20,822 to 33,582.">
</p>

**Segmentation, the source of every mapping lead, and of ground-mount capacity at any
size.** A fine-tuned TerraMind-tiny outlines panels directly, exported as ranked
GeoParquet, GeoJSON and a MapRoulette challenge for human validation, regardless of
array size. Recall on the Germany validation states is 0.83 to 0.95 depending on array
size; recall on Punjab rooftops went from 0.18 to 0.55 once verified in-domain training
data closed the loop. roofclf has no building footprint to classify a ground-mounted
array against, so segmentation remains the only instrument for ground-mount at any size,
and it stays the authoritative *rooftop* instrument too, everywhere roofclf has not been
calibrated (see next).

**roofclf, for every rooftop below 400 m² - and, where calibrated, for large rooftops
too.** At 10 m resolution, a 100 m² array is a handful of mixed pixels - not enough to
draw a polygon around, but enough to ask whether a *building* carries PV. **roofclf** is
a per-building classifier trained on 27 exhaustively mapped ground-truth quadrats (0.879
AUC, 0.834 with roof size controlled for, where the segmentation raster scores close to
chance on the same small buildings), cross-checked against **SPPI**, a zero-training
five-band spectral index (He et al. 2026) that needs no labels at all (0.823 AUC in its
own nine-quadrat evaluation, where roofclf scored 0.874 on the identical buildings). They agree often enough to raise measured precision from 0.53 to 0.63
when both flag a building, and the gain concentrates in exactly the low-adoption places
where roofclf alone is known to over-predict. Segmentation's blind spot turns out not to
be building size but *installation* size - a small array on a large roof is invisible to
it too - so as of 2026-08-07 roofclf's own rooftop estimate (AUC 0.896 vs segmentation's
0.73-0.78 on the identical ≥ 400 m² buildings) also *replaces* segmentation's rooftop
total at or above 400 m² inside the cells its calibration quadrats cover. Outside those
cells segmentation's own recall-corrected rooftop figure stays authoritative, since it is
the only evidence-backed number there. See
[Capacity density](https://open-energy-transition.github.io/earthpv/methods/density/).

**Both instruments converge on the evidence atlas.** `density` aggregates segmentation's
≥ 400 m² detections (rooftop and ground-mount, every cell); `roof-classifier` →
`roofclf-score-national` → `sub400-capacity` builds roofclf's < 400 m² population, and
`ge400-roof-capacity` builds its ≥ 400 m² rooftop replacement inside the calibrated
cells; `earthpv atlas` combines all of it into **Best estimate**, this project's own
highest defensible figure, hand-mapped OpenStreetMap installations plus the model's own
recall-corrected detections plus roofclf/SPPI's per-building density estimate - with
the overlap between OSM and detections removed rather than double-counted, and a 90%
range on the total. Full command sequence:
[The full pipeline](https://open-energy-transition.github.io/earthpv/reproduce/#the-full-pipeline).

**The absolute total is a modelled estimate, not a metered figure - Sentinel-2's 10 m
pixels make that unavoidable.** An individual array below roughly 400 m² is a mixed-pixel
problem rather than a shape the segmentation model can outline, so everything under that
floor comes from `roofclf` instead, restricted to cells whose building density resembles
the hand-mapped calibration quadrats it was measured on. That restriction keeps the
sub-400 m² numbers honest, but it also means the total tracks calibration coverage, not a
direct count, which is why the headline figure carries a 90% range rather than one bare
number.
Checked against that limitation directly: an independent, separately produced national
rooftop-solar estimate agrees closely with this project's on **where** capacity
concentrates - normalizing both to percent of national total per spatial unit (their
absolute magnitudes aren't comparable), the median difference across 3,303 spatial units
is 0.005 percentage points and rank correlation is 0.75-0.84. It disagrees more on how
much weight the very largest sites deserve (a handful of hotspot cells drive most of the
remaining gap, consistently in the same direction), which is a real, stated limitation,
not a hidden one. See
[Capacity map](https://open-energy-transition.github.io/earthpv/results/capacity/) for the
full comparison and `scripts/pv_reference_share_comparison.py` to reproduce it.

### Optional, supplementary instruments

Everything below is evidence toward the main workflow, a secondary product built from
the same detections, or a documented negative result - not a competing main path.

**Glint, for tilt and orientation.** A glass-fronted panel is partly a mirror, so it
flashes into Sentinel-2 only on the geometry-predictable dates when its tilt and azimuth
bisect the sun and the sensor. Two or more mutually consistent flashes are a physical
confirmation that PV is present, independent of spectral appearance, and recover how the
panel is mounted. Folds into the main workflow's leads ranking as a boost-only signal;
never required to produce the evidence atlas.

<p align="center">
  <a href="https://open-energy-transition.github.io/earthpv/glint_examples/">
    <img src="docs/assets/figures/glint_example.jpg" width="280"
         alt="High-resolution basemap imagery of a rooftop PV array caught mid-glint: the panels saturate fully white and the overload spills off the roof as a rainbow smear of detector-blooming artifacts across the neighbouring buildings.">
  </a>
</p>

<p align="center"><em>The physical event the glint check looks for, caught in sub-metre
commercial imagery: the array's specular reflection is so intense it saturates the
sensor outright, blooming into a rainbow smear across the neighbouring rooftops. At
Sentinel-2's 10 m the same event is a single bright pixel-cluster on one predictable
date - more examples in
<a href="https://open-energy-transition.github.io/earthpv/glint_examples/">What solar
glint actually looks like</a>.</em></p>

**Growth, for when installations appeared.** Diffing a pre-boom (2021/22) Sentinel-2
composite against the current one - with both the segmentation model and SPPI run
independently on each epoch - shows where solar capacity actually landed, not just where
it stands today. Pakistan's own rooftop stock roughly doubled since 2021/22 by this
measure. See [Growth](https://open-energy-transition.github.io/earthpv/results/growth/).

A fraction-head expected-area instrument, SPPI as a standalone (not cross-checked)
detector, an older Low/Central/High/All-PV bracket atlas and a rooftop potential/saturation
atlas exist too, each measured and each kept in the repository whether or not it was
promoted - see
[Experiments](https://open-energy-transition.github.io/earthpv/experiments/)
for what was tried and why the main workflow above is what shipped.

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

## Add your country: the atlas is meant to be collective

**The goal is a global PV evidence atlas assembled from many countries, each run and
verified by people who know the ground.** Nothing in this pipeline is Pakistan-specific:
every input is a global dataset, so the intended shape of this project is a fork per
country and this repository as the place their results come back together. Pakistan,
Germany, France, Gujarat and Zambia are the first five, not the destination.

Be straight about what is not built yet: **there is no combiner that merges countries into
one global surface.** What exists is a shared pipeline, a shared atlas format and a shared
data pack layout, which is what makes that step possible later. A contribution that follows
the layout will still be usable when it is written.

```bash
gh repo fork open-energy-transition/earthpv -clone -remote
cd earthpv && git switch -c atlas/<country>

pixi run python scripts/new_region.py check -iso3 <ISO3> -name <country>   # preflight
pixi run python scripts/new_region.py add   -iso3 <ISO3> -name <country>
pixi run python scripts/new_region.py plan  -aoi <country>                  # your runbook
```

Run the pipeline that `plan` prints. Every stage is resumable; `compose` is the long pole,
measured in days on a home connection. A country with exhaustively mapped calibration areas
gets the full two-detector atlas; one with a complete public register can substitute that
register; one with neither gets a **segmentation-only atlas**, which is a real result and is
how Gujarat and Zambia are published here.

Then package the raw numbers. The atlas page is the headline, but **the per-cell capacity
table is the product**, and since `data/` is gitignored these tables ship as GitHub Release
assets with only a manifest committed:

```bash
pixi run python scripts/build_atlas_data_pack.py -aoi <country>
gh release create <country>-atlas-data-$(date +%Y-%m-%d) dist/<country>-atlas-data/* \
    -title "<Country> atlas data" -notes "Point-in-time snapshot"
```

That writes `<country>_capacity_by_cell.parquet` (one row per 0.1 degree cell, the
PyPSA-ready table a global atlas would consume) alongside the per-building and per-region
tables, the roofclf populations, the unreviewed raw detections and the fitted model, plus
`configs/<country>_atlas_downloads.json`. Rebuild the atlas with `-downloads-manifest` and
`-data-release-url` so the page links to them, add a short page under `docs/results/`, and
open the pull request. **Commit the manifest, never the pack.**

One step cannot be skipped and cannot be automated: after national scoring, draw 20 random
cells and check them against high-resolution imagery. Without it a number has no evidence
under it.

**Working with Claude Code or another agent?** `CLAUDE.md` is the repository's agent brief,
and most of this pipeline suits an agent well: preflight, config, babysitting the long
stages, assembling the data pack, drafting the page. Point it at `CLAUDE.md` and
`docs/reproduce.md` and ask it to stop before anything needing human eyes. It must not draw
calibration areas, declare them complete, or sign off validation on its own.

Full runbook, including the agent prompt that works and the review checklist:
[Contribute your country atlas back](https://open-energy-transition.github.io/earthpv/reproduce/#contribute-your-country-atlas-back).

## Community

EarthPV is the software half of **TraceTheSun**, a pilot run by
[Open Energy Transition](https://openenergytransition.org) to make PV mapping
cost-effective, verifiable, community-driven and local, worldwide. The concept was
conceived by [Tobias Augspurger](https://www.linkedin.com/in/tobias-augspurger/) and [Muhammad Awais](https://www.linkedin.com/in/awais307/). The
Pakistani results rest on a student team at the **[Centre for Water Informatics and
Technology (WIT)](https://wit.lums.edu.pk/)**, Lahore University of Management Sciences -
[Laeeba Hafeez Malik](https://www.linkedin.com/in/laeeba-hafeez-malik-220b63328/) (BS
Computer Science), [Tayyiba Shafiq](https://www.linkedin.com/in/tayyiba-shafiq/) (BS
Economics), [Nimra Aamir Ali](https://www.linkedin.com/in/nimra-aamir-ali-417b98249/) (BS
Anthropology) and [Vania Malik](https://www.linkedin.com/in/vania-malik-799bbb343/) (BS
Electrical Engineering) - who coordinated closely
with OET to co-design the pipeline and do the mapping, validation, model development and
ground-truth quadrat work that makes the pilot's numbers checkable. For WIT the effort is
also a step toward linking the resulting national PV database into energy and power-system
models and integrated-assessment scenarios. [Join the Community on Discord](https://discord.gg/T5zh6N24Hv)

## Licence

Code MIT. Imagery from Copernicus Sentinel-2; building footprints from VIDA Open Buildings
and Overture Maps; labels from OpenStreetMap contributors under ODbL; administrative
boundaries from geoBoundaries under CC-BY.

**Published data outputs** (the evidence atlas, capacity parquets, raw detections and any
other derived dataset offered for download, e.g. under "Download the underlying data" on the
atlas page or as a GitHub Release asset) are derivative databases of OpenStreetMap's
ODbL-licensed solar labels and, via VIDA Open Buildings, of Microsoft/Google building
footprints. Under ODbL's share-alike clause, **these data releases are themselves licensed
under the [Open Database License (ODbL) v1.0](https://opendatacommons.org/licenses/odbl/1-0/)**,
with attribution to &copy; OpenStreetMap contributors required on any use, alongside VIDA Open
Buildings (CC BY 4.0) for the footprints and, for anything derived from the Germany/MaStR
validation, the Marktstammdatenregister (Bundesnetzagentur, [Datenlizenz Deutschland - Namensnennung - Version
2.0](https://www.govdata.de/dl-de/by-2-0)).
