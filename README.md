# earthpv - rooftop solar detection from Sentinel-2

Detects rooftop solar PV arrays (target ≥ ~500 m², smaller where possible) from
Sentinel-2 L2A imagery by fine-tuning the open-source **TerraMind** geospatial
foundation model (IBM/ESA, 2025) with **TerraTorch**. Labels come from
OpenStreetMap solar mapping via **Overture Maps** (`source_tags` on the
base/infrastructure layer); building footprints and admin boundaries also come
from Overture. Designed to be recall-oriented: candidates are meant to be
human-validated against imagery in OSM workflows (MapRoulette export included).

- **Training region:** Germany (dense OSM solar labels, geographic train/val split by state)
- **Inference target:** Punjab, Pakistan (building-screened chip grid)
- **Imagery:** multi-temporal cloud-free composites (2025-03 → 2026-02), 12 S2L2A bands, 10 m,
  from Microsoft Planetary Computer

## Setup

```bash
pixi install          # data pipeline env
pixi install -e ml    # + PyTorch cu126 (Pascal-safe) + TerraTorch
pixi run -e ml gpu-check
```

## Pipeline

```bash
# 1. Labels: Overture buildings + OSM solar tags
pixi run earthpv labels --aoi germany

# 2. Chips: S2 composites + burned PV masks
pixi run earthpv chips --aoi germany

# 3. Fine-tune TerraMind (smoke: --smoke)
pixi run -e ml earthpv train --config configs/terramind_pv.yaml

# 3b. Evaluate: pixel IoU/F1 + per-installation recall by array size
pixi run -e ml earthpv evaluate --aoi germany --checkpoint data/models/<best>.ckpt

# 3c. Punjab has no local imagery — composite building-populated cells via STAC first
#     (resumable; cities first). Skip for regions that already have local composites.
pixi run -e ml earthpv compose --aoi punjab --min-buildings 1000

# 4. Inference over Punjab (uses data/composites/punjab if present; building-screened)
pixi run -e ml earthpv infer --aoi punjab --checkpoint data/models/<best>.ckpt

# 5. Candidates: threshold -> polygons -> building join + prior re-ranking.
#    On first run, pulls VIDA Open Buildings (dense, imagery-derived) around the
#    candidates and caches them under data/predictions/<aoi>/buildings/; falls back
#    to the local Overture footprints when the AOI's country is unknown.
pixi run earthpv postprocess --aoi punjab --threshold 0.3

# 6. Export GeoParquet / GeoJSON / MapRoulette challenge (queue ordered by rank_score)
pixi run earthpv export --aoi punjab

# 7. (optional) PV density per building + PyPSA-ready grid/region aggregates
pixi run earthpv density --aoi pakistan
```

AOIs and parameters: `configs/aoi.yaml`. Model/training: `configs/terramind_pv.yaml`.

## Data provenance

To avoid re-downloading terabytes, chips and inference read the Sentinel-2 composite
COGs and OSM/Overture label + building parquets already produced by the sibling
`rooftopsenti` project, via `local_root` in `configs/aoi.yaml`
(`src/earthpv/local_source.py`). The Overture (`src/earthpv/overture.py`) and
Planetary-Computer (`src/earthpv/imagery.py`) fetchers are the fallback for regions
with no local artifacts. Composites are 10-band (B02–B12 minus the 60 m atmospheric
bands); TerraMind's S2L2A patch-embed is subset to those 10 bands at load time.

## Result (TerraMind-tiny, GTX 1060)

The detector targets **arrays ≥ 400 m²** — `MIN_PV_AREA` in `chips.py` sets the
positive threshold (~4 Sentinel-2 pixels, the practical floor for per-pixel
supervision at 10 m GSD); smaller arrays are burned as *ignore*. Training combines
Germany (3189 chips) with Punjab, Pakistan (274 chips from the composed cells +
`pakistan_500` OSM labels), merged by `scripts/merge_chip_index.py`.
Per-installation recall (threshold 0.3, recall-first, checkpoint
`v2_combined/terramind-pv-epoch=39`):

| array size (m²) | Germany val | Punjab val |
|-----------------|-------------|------------|
| ≥ 1000          | 0.83        | 0.55       |
| 500 – 1000      | 0.84        | 0.16       |
| 250 – 500       | 0.95        | 0.14       |

Germany pixel IoU 0.51, F1 0.68; Punjab 0.29/0.45. A high FP rate is expected and
acceptable — candidates are human-validated against high-res imagery in OSM. The
Punjab numbers, while much weaker, are ~3× the Germany-only model (0.18 at ≥1000 m²):
in-domain chips matter. The residual Punjab misses look imagery-limited (smog-season
composites, mixed pixels, OSM label noise) — the model outputs near-zero probability
on them even at threshold 0.05, and oversampling Punjab 4× did not help. Sub-500 m²
detection remains unreliable at Sentinel-2's 10 m floor; use PlanetScope/VHR if small
residential rooftops matter.

## Pakistan inference result (country-wide)

The local `rooftopsenti` composites cover Balochistan/Sindh, **not** the populated
east, so imagery is built on demand with `earthpv compose` (Sentinel-2 dry-season
median, ~12 least-cloudy scenes per 0.1° cell). Rooftop PV only exists where there
are roofs, so `compose` targets building-populated cells; the `pakistan` AOI covers
**122 cells (≥1000 buildings each) spanning every major city in the country**. Its
cell grid is anchored to punjab's via `grid_origin` in `configs/aoi.yaml`, so the 64
cells composited for the earlier Punjab run were reused by hardlinking (only 58 new
downloads). Compositing is network-bound (~1 min/cell on a clear link).

The country-wide run (checkpoint `v2_combined/terramind-pv-epoch=39`, threshold 0.3)
produced **1836 candidates: 1261 rooftop, 424 ground-adjacent, 151 no-building**
(median merged-blob area ~11 500 m², median confidence 0.99). Spread: ~1200 in Punjab,
470 around Karachi/Sindh, 119 Peshawar/KP, 103 Islamabad/Rawalpindi, 21 Quetta. 26 %
intersect already-mapped OSM solar (a good sanity check); **~1360 are new leads** for
validation. Outputs: `data/predictions/pakistan/pakistan_pv_*.{geoparquet,geojson}`
plus a MapRoulette challenge. The VIDA building join uses a one-time 9.3 GB local
download (`data/vida/PAK.parquet`) — country-scale candidate sets make remote
row-group scans impractical (~5 h vs ~4 min locally).

## Two-season stacking experiment (negative result)

A 20-band **two-season stack** (dry-season base + a contrast season per cell:
post-monsoon for Pakistan, winter for Germany) was implemented to push detection below
1000 m² — the idea being that PV is spectrally stable across seasons while vegetation
and roofs swing. The full path is wired (`imagery.annual_composite(geobox=…)`,
`CompositeIndex(layers=2)`, `compose --window/--index/--workers`, per-AOI `stack_window`,
`configs/terramind_pv_seasonal.yaml`) and TerraMind duplicates its pretrained S2L2A
patch-embed into both season slots.

**It did not improve the target.** On the clean Punjab val set (same installations),
per-installation recall for ≥1000 / 500–1000 / 250–500 m² was **0.51 / 0.17 / 0.14**
(seasonal) vs **0.55 / 0.16 / 0.14** (10-band v2) — small buckets unchanged within
noise, large slightly worse. So **`v2_combined/epoch=39` (10-band) stays production**
and the validated country-wide candidate set above is unchanged; the seasonal
checkpoint is kept at `data/models/v4_seasonal/` for future iteration. Likely causes:
too few in-domain Punjab chips (274) to learn the temporal signal, the tiny backbone's
capacity, and post-monsoon vs dry season not differing enough spectrally in arid
Pakistan. The strongest remaining lever is retraining on **human-validated candidates**
(a larger, cleaner in-domain signal than a second season).

## Planned: two-epoch change detection — the 2022–2026 solar boom as signal

Pakistan's rooftop PV stock is dominated by the post-2022 boom: panel imports jumped
to double-digit GW per year (~13 GW+ imported in 2024 alone), driven by grid tariffs,
load shedding and net metering. The consequence for detection: **almost every real
rooftop array visible in 2026 imagery did not exist in the 2021/22 dry season** — a
temporal prior that no single-epoch optical model can exploit. The plumbing to use it
already exists from the seasonal experiment (`annual_composite(geobox=…)`,
`CompositeIndex(layers=2)`, `compose --index/--window`):

1. Compose a **pre-boom epoch** onto the exact same 0.1° grid:
   `compose --aoi pakistan --index 1 --window 2021-10-01:2022-01-24 --use-vida`
   (same cost profile as the current-epoch run: ~4.4k cells, resumable, network-bound).
2. Run the **unchanged production model** on both epochs. Unlike the two-season stack
   above — which fed both seasons to the model as extra input bands and needed a
   retrain — this is two independent inference passes with no training at all.
3. **Difference the probability surfaces** and re-score candidates:
   - *Persistent false positives cancel.* Bright riverbeds, rock outcrops, industrial
     roofs, greenhouses existed pre-boom too, so they fire in both epochs and Δ≈0;
     new PV fires only in the current epoch. This attacks exactly the countryside-FP
     class that building-distance filtering cannot (a bright outcrop near a village
     survives the 2 km filter; it cannot survive the epoch difference).
   - *"Already present in 2021" is a negative prior in Pakistan* — the opposite of
     Germany, where old installations dominate. Detections with high pre-boom
     probability get down-ranked per candidate.
4. The difference is also a product in itself: **ΔMWp 2022→2026 per cell and district
   is the rooftop-density development over the boom**, independently checkable against
   NEPRA net-metering registrations (a grid-tied lower bound, per DISCO) and the
   customs panel-import series — a second calibration anchor besides TransitionZero,
   and a spatially-resolved growth map of the boom.

Caveats to design around: the Sentinel-2 processing-baseline change (04.00, Jan 2022)
shifts the DN convention by +1000 mid-window — the suggested pre-boom window ends
2022-01-24 to stay on one baseline; epoch-to-epoch atmosphere/phenology differences
are mitigated by differencing model *outputs* rather than reflectances; and the model
has only ever seen current-epoch spectra, so spot-check pre-boom composites over
installations known to predate 2022 (e.g. Quaid-e-Azam Solar Park) before trusting
the pass.

## Avoiding tiling artefacts

Two things previously produced a regular grid of false positives at the sliding-window
spacing, both now fixed:
- **Training centre-bias (the dominant cause).** Positive chips must be *jittered* so the
  installation lands anywhere in the frame (`sample_chip_centers`, ±900 m). Without it the
  model learns "PV is in the middle" and fires once per window at inference. Diagnostic:
  nearest-neighbour distance between detections spikes at the window stride (was 60% of
  detections one stride apart; ~7% after the fix).
- **Window seams.** `infer.py` overlap-adds windows with a 2D Hann taper into one seamless
  raster per cell, and uses a stride that is *not* a multiple of the 16 px ViT patch size so
  patch-edge effects decorrelate between neighbours.

## Building prior & candidate re-ranking

`postprocess` classifies each candidate against a footprint set in the candidates'
local UTM zone, recording `building_overlap_frac` (share of the polygon sitting on a
roof) and `building_dist_m` (gap to the nearest footprint). These feed a
`building_prior` and a `rank_score = confidence × (0.5 + 0.5·prior)`; `export` orders
the GeoParquet and the MapRoulette queue by `rank_score`. It stays recall-first —
**nothing is dropped**, and a high-confidence detection with no nearby building (an
unmapped roof or a ground-mount farm) still surfaces; the prior only re-orders triage
so validators hit on-building detections first.

The footprint set is **VIDA Google+Microsoft Open Buildings** (`src/earthpv/buildings.py`),
which — unlike the Overture ≥ 500 m² local set — is imagery-derived and includes small,
unmapped structures, so "no building within ~30 m" becomes a usable false-positive
signal. It's fetched once per AOI, windowed to the candidate-containing 0.1° cells
(the country file is ~76 M rows) and cached. Note: for a candidate set dominated by
*large* arrays on already-mapped buildings, VIDA and the Overture set attribute nearly
identically; VIDA's advantage shows most once `MIN_PV_AREA` is lowered to admit small
residential roofs.

## Solar-glint corroboration (rank_score)

![Solar-glint validation geometry: a matched panel tilt reflects the sun straight into Sentinel-2's near-nadir sensor, a mismatched tilt sends it elsewhere, and the resulting time series shows a reflectance spike on the geometry-predicted date while the surrounding annulus stays flat.](docs/glint_geometry.svg)

A glass-fronted PV panel is partly a specular reflector: Sentinel-2 views near-nadir,
so a fixed panel only glints into the sensor when its tilt/azimuth happens to bisect
the sun and the sensor at the ~10:30 local overpass — a narrow, geometry-predictable
condition (`src/earthpv/glint.py`). Validated against known German and Punjab
installations (skyfield-propagated sun/view geometry cross-checked against real
MTD_TL.xml granule angles): arrays that glint do so on dates that self-consistently
recover a single panel orientation, cleanly separable from cloud/cropland brightening
by requiring the surrounding annulus to stay stable. But real arrays frequently
**don't** glint at all — about 30% of confirmed installations in the validation set
showed zero spikes over 2 years, simply because their orientation never lines up
with this specific overpass geometry — so absence of glint is not evidence against a
candidate.

`postprocess --check-glint` pulls each of the current top `--glint-top-n` (default
300) candidates' ~2-year Sentinel-2 time series and checks for spikes consistent with
one fixed orientation (`postprocess.py::add_glint_prior`). This is **reward-only**:
candidates with fewer than 2 mutually-consistent spike dates are left unchanged;
confirmed ones get a `rank_score` bonus scaling up to ×1.2 at 4+ consistent dates.
Nothing is dropped, matching the recall-first `building_prior`/`epoch_prior` re-ranking
contract above.

This is a network-bound per-candidate scene pull (dozens to hundreds of Sentinel-2
reads each, ~1-2 min/candidate), so it's opt-in and bounded to the top-N by
`rank_score` rather than run over a whole country-scale candidate set. Like
`imagery.py`'s composite fetcher, it tries Planetary Computer first and falls back to
Earth Search (AWS Open Data, no auth/tokens, a different failure domain) if PC returns
no scenes at all for a candidate — individual PC scene-read failures during a 503
storm are already tolerated per-scene, so only a total PC miss triggers the fallback.

## PV density per building (energy-model / PyPSA export)

`density` (`src/earthpv/density.py`) turns the same probability rasters into
building-level PV density and area/region aggregates — the shape energy-system models
(PyPSA / PyPSA-Earth) consume, rather than a validation queue. It runs on existing
artifacts (rasters + `candidates.parquet` + the VIDA footprints); no GPU, no retraining.

Two PV-area metrics are reported per building because the model is deliberately
recall-first and neither is unconditionally honest:

- **detected** (`*_det`) — area of the thresholded, merged candidate polygons on the
  footprint. The precision-honest **floor**; use `est_mwp_det` as an existing-rooftop-
  capacity seed per bus region.
- **expected** (`*_exp`) — probability-weighted area (Σ per-pixel probability × 100 m²
  over the footprint, above a small noise floor). Integrates sub-threshold signal; an
  **upper-leaning** expectation for sensitivity bands. The truth is bracketed between them.

Three layers land in `data/predictions/<aoi>/density/`:

- `buildings.geoparquet` — one row per building carrying PV signal: `roof_area_m2`,
  `pv_area_det_m2` / `pv_area_exp_m2`, `pv_ratio_{det,exp}` (≤ 1), `est_kwp_{det,exp}`,
  `pv_placement`, `region`/`district`.
- `grid.geoparquet` + `grid.csv` — one row per 0.1° cell (the pipeline's native grid):
  roof area, PV area (both metrics), densities (m²/km²) and `est_mwp_{det,exp}`. The CSV
  `lon_center`/`lat_center` map straight onto atlite/PyPSA-Earth cutout grids or Voronoi
  bus regions.
- `regions.geoparquet` + `.csv` + `.geojson` — per Overture/geoBoundaries province (and
  `--districts` for ADM2), additive totals with ratios recomputed from sums.

Capacity uses `est_kwp = pv_area × --kwp-per-m2` (default **0.18 kWp/m²**, ≈ 5.5 m²
of c-Si module per kWp). Double counting is avoided at the source: adjacent rasters
overlap by a few pixels, so each building is assigned to exactly one cell by its
representative point and each cell's raster sum is cropped to the canonical 0.1° box.
The run is resumable (per-cell partials under `density/cells/`), ~1.5–2.5 h single-process
for all of Pakistan. Province polygons come from **geoBoundaries** (open, CC-BY) because
Overture's S3 divisions endpoint times out from this machine; pass `--regions-file` to
override, or the cached `data/labels/<aoi>_regions.parquet` is reused.

### How the density estimate developed

The density product went through several validated iterations; each step exists
because the previous one had a measurable gap:

1. **Detected-area floor** — thresholded candidate polygons joined to footprints
   (`est_mwp_det`). Precision-honest but blind to everything below the threshold and
   below the ~1000 m² detection size, i.e. to most residential PV.
2. **Probability-weighted expectation** (`est_mwp_exp`) — Σ per-pixel probability
   × 100 m² over each footprint. Integrates sub-threshold signal; together the two
   metrics bracket the truth.
3. **Fraction-regression track** — a second model head trained to predict per-pixel
   PV *coverage fraction* (OSM polygons burned at 10× supersampling, block-averaged
   to 10 m). Individually noisy (0–250 m² per-installation recall is only ~4.5 %) but
   **unbiased-in-aggregate**: chip-sum R² 0.60 on held-out Germany, and municipal
   Spearman ρ vs the legally-complete MaStR register of **0.740** across all German
   Gemeinden — vs 0.499 for the segmentation baseline. Aggregate density is the
   quantity energy models need, and this head is the purpose-built estimator for it.
4. **Calibration anchors** — Germany: MaStR per-Gemeinde totals established a stable
   ~2.4–2.5× aggregate over-prediction (consistent from chip level to municipality
   level, i.e. correctable). Pakistan: cross-checked against TransitionZero's 27.5 GW
   distributed-solar study with a coverage-share-disentangled single-point calibration
   — separating "scale error inside imaged cells" from "cells never imaged at all".
5. **Coverage expansion** — that comparison showed the missing-coverage term dominated:
   cell selection had used the local Overture ≥500 m² building set, which undercounts
   small/informal structures by 200–1000× in rural Pakistan. Switching selection to
   VIDA Open Buildings (76.5 M footprints) grew Pakistan's compose target from 122 to
   ~4 460 cells — the country-wide imagery runs feeding the current estimates.
6. **Next** — the OSM flywheel (leads validated into OSM become in-domain Pakistani
   training positives via the Overpass label path; a retrain is pending), NEPRA
   net-metering totals as a Pakistani MaStR analogue, and the two-epoch ΔMWp above as
   the growth axis: per-epoch density estimates make `est_mwp` a **time series**, so
   the boom itself becomes measurable per district rather than a single snapshot.
7. **Cell-aggregate glint calibration** (tested, inconclusive) — small residential
   arrays are individually sub-pixel and rarely glint on their own (~1–4% of dates,
   each on its own orientation-specific window), so the hypothesis was that a dense
   neighbourhood of many independently-oriented small arrays would union those narrow
   windows into a far higher combined spike-count than any single installation shows
   alone. Tested against a fully OSM-mapped Lahore residential cluster (below — up to
   120 separately-mapped generators inside a single 300 m block) by gridding it into
   cells with known true PV area and regressing each cell's aggregate reflectance-
   spike count (p90 of the whole cell against a wide 150–450 m external ring, not the
   per-installation 30 m annulus, since a tight ring risks comparing panels against
   neighbouring panels) against that density. **Result: no signal** — zero-PV control
   cells averaged 1.0 spike, PV-bearing cells 1.45 (median tied at 1.0 for both), and
   even the 120-installation hotspot cell showed only 1 spike over 2 years. Likely a
   methodology problem rather than a physics one: p90-of-the-whole-cell only moves if
   ~10% of the cell (~90 of 900 pixels) brightens at once, but even every installation
   in the busiest hotspot glinting simultaneously covers under half that — a per-pixel
   anomaly-count statistic (each pixel against its own baseline) would be the correct
   next test, not attempted here.

   <img src="docs/pv_density_test_area.png" alt="JOSM view of the Lahore calibration test area: yellow building footprints densely packed with mapped solar-generator icons, illustrating the many-small-installations-per-block pattern the cell-aggregate test targets." width="480">

8. **Missed-installation glint recovery** (tested, negative) — a different idea from
   #7: rather than aggregating over a cell, find real OSM-confirmed installations the
   model's own thresholded mask completely misses (`pv_area_det`'s recall gap made
   concrete) and check whether glint-validating them could safely add their area back.
   Tested on 43 missed German installations (from the val split) and 208 missed
   Lahore installations, each against a matched sample of confirmed non-PV buildings.
   **Both regions fail the one thing this needs to do**: Germany's control
   false-validation rate (20.8%) is uncomfortably close to its missed-installation
   validated rate (37.2%); Lahore's control rate (8.7%) is *higher* than its missed
   rate (5.3%) — worse than chance at telling real missed PV apart from ordinary
   buildings. Recovered area was a modest 10.8% of the Lahore gap even before
   accounting for that false-positive risk. Not safe to deploy as a blanket density
   correction in either region tested.


**Sentinel-1 corner-reflector test (negative result).** A tilted PV row over flat
ground forms a dihedral corner reflector — hypothesis: this should show up as strong
SAR backscatter, and (unlike optical glint) persistently, since S1's orbit geometry
is fixed year-round rather than season-dependent, and it isn't blocked by cloud.
Tested on 17 glint-validated installations spanning the full observed azimuth range,
pulling ~2 years of Sentinel-1 RTC (VV/VH) and checking for backscatter enhancement
inside each footprint vs. a wide external ring, split by ascending/descending pass.
**No signal**: median enhancement rate ~3.2% (VV) / 1.7% (VH) of scenes — in the range
of plain speckle noise — and critically, ascending vs. descending rates were nearly
identical (1.7% vs. 1.8% median) with no correlation to the panel's implied row axis.
A real corner-reflector effect should show a sharp asymmetry between orbit headings;
its absence suggests this isn't a usable detection channel at these sites, at least
not via a simple per-footprint aggregate.

Wiring S1 into the *model itself* remains a separate, larger idea: TerraMind-tiny
ships pretrained S1 patch embeddings, but using them needs S1 RTC compositing, a
modality-dict input path, neck reconfiguration and a retrain gated against v3 on the
Multan validation split. A lighter-weight use needs no model change at all:
multi-temporal backscatter *variance* at candidate locations separates permanent
structures (PV: static, low, flat backscatter) from seasonally-changing fields, and
greenhouses' metal frames act as corner reflectors (bright return — opposite to PV),
making S1 a cheap post-hoc false-positive filter — untested, but distinct from the
per-footprint corner-reflector idea above and not ruled out by its negative result.

## Notes

- 500 m² ≈ 5 Sentinel-2 pixels: evaluation reports per-installation recall bucketed
  by array size; tune the postprocess threshold on the German validation states for
  the recall you need.
- GTX 1060 (Pascal, sm_61) requires PyTorch cu126 wheels — CUDA 13 dropped Pascal.
- Chips store the annual median (12 bands); pass `--seasonal` for 4-season 60-band
  chips (disk-heavy) to experiment with explicit temporal stacks.
