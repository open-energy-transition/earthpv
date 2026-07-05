# earthpv — rooftop solar detection from Sentinel-2

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

# 5. Candidates: threshold -> polygons -> building join
pixi run earthpv postprocess --aoi punjab --threshold 0.3

# 6. Export GeoParquet / GeoJSON / MapRoulette challenge
pixi run earthpv export --aoi punjab
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

The detector targets **large rooftop arrays (≥ 1000 m²)** — `MIN_PV_AREA` in
`chips.py` sets the positive threshold; smaller arrays are burned as *ignore*.
Per-installation recall on held-out German MGRS tiles (threshold 0.3, recall-first):

| array size (m²) | recall |
|-----------------|--------|
| ≥ 1000 (target) | 0.79   |
| 500 – 1000      | 0.93   |
| 250 – 500       | 0.97   |

Pixel IoU 0.54, F1 0.70. A high FP rate is expected and acceptable — candidates are
human-validated against high-res imagery in OSM. The signature learned on ≥1000 m²
arrays transfers to smaller ones, but sub-500 m² detection is unreliable in practice
(Sentinel-2's 10 m floor); use PlanetScope/VHR if small residential rooftops matter.
Lower `MIN_PV_AREA` and switch the loss to Focal-Tversky to push smaller.

## Punjab inference result

The local `rooftopsenti` composites cover Balochistan/Sindh, **not** Punjab, so Punjab
imagery is built on demand with `earthpv compose` (Sentinel-2 dry-season median, ~12
least-cloudy scenes per 0.1° cell). Rooftop PV only exists where there are roofs, so
`compose` targets the building-populated cells (61 cells with ≥1000 buildings cover
every major Punjab city). Compositing is network-bound (~2 min/cell on a clear link).

A run over 45 composited cells (Multan/Bahawalpur up to the Rawalpindi belt, covering
Lahore, Faisalabad, Gujranwala, Multan, Sargodha) produced **999 candidate arrays, 880
of them ≥ 1000 m²** (median 3300 m², median confidence 0.98); the highest-confidence
detections are large factory-roof arrays in Faisalabad's textile belt. The high
`no_building` share is expected — the local building set is sparse for Punjab, and
unmapped roofs are exactly the target. Outputs: `data/predictions/punjab/punjab_pv_*.{geoparquet,geojson}`
plus a MapRoulette challenge. To extend to all 61 city cells, re-run `compose` (it skips
finished cells) then `infer → postprocess → export`.

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

## Notes

- 500 m² ≈ 5 Sentinel-2 pixels: evaluation reports per-installation recall bucketed
  by array size; tune the postprocess threshold on the German validation states for
  the recall you need.
- GTX 1060 (Pascal, sm_61) requires PyTorch cu126 wheels — CUDA 13 dropped Pascal.
- Chips store the annual median (12 bands); pass `--seasonal` for 4-season 60-band
  chips (disk-heavy) to experiment with explicit temporal stacks.
