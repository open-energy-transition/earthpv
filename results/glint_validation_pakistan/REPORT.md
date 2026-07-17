# Solar glint validation on OSM-confirmed Pakistan PV

**Date:** 2026-07-17
**Scripts:** `scripts/glint_validate_pakistan.py` (sample / pull / analyze),
`scripts/glint_validation.py` (shared spike-detection and orientation-fit logic),
`src/earthpv/glint.py` (core method)

## Question

How often does the specular-glint method confirm a *known, human-mapped* PV
installation — and how does that rate depend on installation size? This calibrates
what a glint hit (or its absence) on a model candidate is actually worth.

## Method

- **Sample:** 500 installations drawn from a fresh OSM export of Pakistan solar
  features (`data/osm_pk_solar_160726.geojson`, 2026-07-16), stratified across six
  geodesic-area buckets so small rooftop generators and utility-scale plants are all
  represented. The >50k m² bucket has only ~93 features country-wide; all were taken.
- **Data:** ~2 years of Sentinel-2 L2A per-scene statistics per target
  (2024-07-01 → 2026-07-14, bands B03 + B08, scene cloud cover ≤ 80%), pulled via
  Planetary Computer STAC. Per-scene stats are the p98 reflectance inside the
  polygon vs. a 30 m annulus around it. Sub-pixel polygons fall back to an
  `all_touched` mask so even <100 m² features read their brightest touched pixel.
- **Detected:** ≥ 1 spike — simultaneously bright in B03 and B08 inside the polygon
  while the surrounding annulus stays stable (rules out haze/cloud brightening).
- **Validated:** a single fixed panel orientation (tilt, azimuth) explains ≥ 2 spike
  dates via the specular reflection condition — i.e. the spikes are geometrically
  consistent with one glass plane, not random brightening.

## Results

499 of 500 targets analyzed (one target yielded no usable scenes).

### By size bucket

| Size (m²) | n | median area (m²) | median clear scenes | % detected | % validated | median spikes when detected | median amplitude |
|---|---|---|---|---|---|---|---|
| <100 | 80 | 49 | 118 | 6.2 | 2.5 | 1.0 | 2.3× |
| 100–500 | 80 | 230 | 114 | 16.2 | 8.8 | 2.0 | 2.5× |
| 500–1k | 80 | 738 | 142 | 22.5 | 16.2 | 3.5 | 3.1× |
| 1k–5k | 85 | 2,130 | 142 | 44.7 | 30.6 | 5.0 | 2.6× |
| 5k–50k | 82 | 10,754 | 138 | 52.4 | 29.3 | 3.0 | 2.8× |
| >50k | 92 | 107,273 | 136 | 72.8 | 26.1 | 2.0 | 2.2× |

### By OSM feature kind

| Kind | n | median area (m²) | % detected | % validated |
|---|---|---|---|---|
| generator (`generator:source=solar`) | 250 | 242 | 22.4 | 12.4 |
| plant (`power=plant`) | 249 | 6,412 | 51.4 | 26.1 |

## Interpretation

1. **Detection scales cleanly and monotonically with size** — 6% for sub-100 m²
   rooftops up to 73% for utility plants. For this project's target class
   (≥ 1000 m²), roughly half or more of real installations produce at least one
   glint spike in two years of Sentinel-2.
2. **Geometric validation plateaus at ~26–31% for everything ≥ 1k m²** instead of
   growing with size. Utility plants (>50k) are the easiest to detect but validate
   *no better* than mid-size arrays — expected, since large plants mix multiple
   orientations and often track the sun, which a single-plane fit cannot explain.
   The orientation fit is therefore a **rooftop / fixed-tilt confirmation tool**,
   not a utility-scale one.
3. **Spike amplitude is roughly constant across sizes** (median 2.2–3.1× baseline).
   Larger arrays mostly get more *chances* at a glint, not brighter ones.

## Implication for the detection pipeline

A glint spike on a model candidate is strong **positive** evidence and may boost
`rank_score`. The **absence** of glint must never demote a candidate: at 10 m
resolution the method misses about half of true 1k–5k m² arrays and still misses
27% of utility-scale plants.

## Caveats

- OSM polygons in Pakistan vary in quality; a mapped feature whose polygon misses
  the actual panels reads as a non-detection, so the true rates are lower bounds.
- Detection requires clear-sky scenes at the right sun geometry; two years is the
  budget here. Shorter windows will detect proportionally less.
- The spike criterion was tuned on the earlier European point checks
  (`scripts/glint_validation.py`); thresholds were not re-tuned on this sample.

## Files

- `pakistan_summary.csv` — one row per target: scene/spike counts, best-fit tilt
  and azimuth, consistency counts, detected/validated flags.
- `pakistan_stats_by_size.csv`, `pakistan_stats_by_kind.csv` — the aggregate tables
  above, unrounded.
- Per-target scene series (~500 parquets) stay in `data/glint/pakistan/` (gitignored).

## Reproduce

```bash
pixi run python scripts/glint_validate_pakistan.py sample   # 500-target stratified sample
pixi run python scripts/glint_validate_pakistan.py pull     # ~2y of scene stats per target (resumable)
pixi run python scripts/glint_validate_pakistan.py analyze  # summary + aggregate CSVs
```

The 2026-07-16→17 pull survived a Planetary Computer outage (Azure Front Door 504
storm) followed by a hung connection: the per-target-file resume design meant the
run was killed, relaunched, and lost nothing.
