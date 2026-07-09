# earthpv - rooftop solar detection from Sentinel-2

⚠️ This is a prototype that is not intended for production or collaboration purposes. If you would like to use this project, please contact the main developer.  ⚠️

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

Sentinel-1 (VV/VH) is a planned follow-up: TerraMind-tiny ships pretrained S1 patch
embeddings, but wiring it needs S1 RTC compositing, a modality-dict input path, neck
reconfiguration and a retrain gated against v3 on the Multan validation split — a
separate phase from this density product.

## Notes

- 500 m² ≈ 5 Sentinel-2 pixels: evaluation reports per-installation recall bucketed
  by array size; tune the postprocess threshold on the German validation states for
  the recall you need.
- GTX 1060 (Pascal, sm_61) requires PyTorch cu126 wheels — CUDA 13 dropped Pascal.
- Chips store the annual median (12 bands); pass `--seasonal` for 4-season 60-band
  chips (disk-heavy) to experiment with explicit temporal stacks.
