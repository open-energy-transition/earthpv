# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`earthpv` detects individual large rooftop solar PV arrays (target > 400 m², the practical
floor for per-pixel supervision at Sentinel-2's 10 m GSD) from Sentinel-2 L2A imagery by
fine-tuning the open-source **TerraMind** geospatial foundation model (IBM/ESA, via
**TerraTorch**). Labels come from OpenStreetMap solar mapping (through Overture Maps);
building footprints classify detections as rooftop/ground. It is **recall-first**:
candidates are meant to be human-validated against high-res imagery in OSM workflows, so
false positives are tolerated. Installations below the 400 m² floor are not targeted by
detection at all, and -- measured, 2026-07-26 -- the `density` stage does **not** rescue them
either: the whole sub-500 m² class is 8.2 MWp of the Pakistan total (~0.2%), and on the one
Rule-1-complete quadrat the segmentation raster predicts *zero* PV area (AUC 0.500). Every
published capacity figure is therefore scoped **≥ 400 m²**, while Germany's complete MaStR
register puts 72.6% of rooftop capacity in units ≤100 kWp (~≤555 m² of module). Closing that
gap is the open front: see "Sub-400 m² instruments" below. Trained on Germany, inferred on
Punjab, Pakistan. Read
`README.md` for the narrative and the current result numbers.

## Main workflow (default pipeline, primary output)

**As of 2026-08-06, this is the project's default, documented workflow, and the evidence
atlas is its primary output.** Two detectors, one per size regime, combined into one
product:

- **Segmentation** (`infer` → `postprocess` → `density`) for individual arrays
  **≥ 400 m²** -- the TerraMind fine-tune, outlining panels directly.
- **`roofclf`** (`roof-classifier` → `roofclf-score-national` → `sub400-capacity`) for
  every building **< 400 m²** -- a per-building "does this roof carry PV?" classifier,
  cross-checked with the zero-training **SPPI** spectral index for the atlas's Verified
  tier (roofclf AND SPPI agreeing).
- **`atlas.build_evidence_atlas`** (`earthpv atlas --sub400-central-cells
  --sub400-low-cells --osm-solar`) combines both into two tiers by *standard of proof*
  -- **Verified** (hand-mapped OSM, or roofclf+SPPI agreement) and **Best estimate**
  (recall-corrected ≥ 400 m² detections plus roofclf-alone density) -- de-duplicated
  against each other and against OSM so nothing is counted twice.

The end-to-end command sequence is in `docs/reproduce.md`'s "The full pipeline"; the
short version:

```bash
earthpv labels --aoi <aoi>       && earthpv chips --aoi <aoi>
earthpv train  --config configs/terramind_pv.yaml
earthpv infer  --aoi <aoi> --checkpoint <ckpt>
earthpv postprocess --aoi <aoi> --threshold 0.3
earthpv export --aoi <aoi>
earthpv density --aoi <aoi> --districts && earthpv check-density --aoi <aoi>

earthpv roof-classifier --aoi <aoi>                 # needs mapped calibration quadrats
earthpv roofclf-score-national --aoi <aoi>          # long: hours at country scale

# ESSENTIAL, not optional -- run after every national scoring pass. See
# docs/methods/roofclf-national-validation.md.
pixi run roofclf-tiles -- --random-cells 20 --seed <fresh int> --mapcss

earthpv sub400-capacity --aoi <aoi> --osm-solar <national OSM solar pull>
earthpv atlas --aoi <aoi> \
  --sub400-central-cells data/roofclf_national_with_sppi/<aoi>/density/sub400_central_incremental_buildings.parquet \
  --sub400-low-cells     data/roofclf_national_with_sppi/<aoi>/density/sub400_low_incremental_buildings.parquet \
  --osm-solar <national OSM solar pull>
```

**Random-cell manual validation (2026-08-06) is part of this workflow, not an optional
extra.** The 17 calibration quadrats are curated and industrial-leaning; a `roofclf`
that scores well only there is not evidence it works on the un-curated rest of the
country. `scripts/tile_roofclf_detections_geojson.py --random-cells N --seed S` draws N
cells uniformly at random from the national scoring output (only cells with >=1 flagged
building by default; `--include-empty-cells` to sample true-negative regions too),
excludes anything already inside a calibration quadrat, and writes the same
complete-per-region JOSM GeoJSON tiles `--all-quadrats` already produces, into
`results/<aoi>_roofclf_validation/`. Reviewed in JOSM the same way as the quadrat tiles;
results get logged to `results/roofclf_random_validation_log.csv` (create it with a
header row on first use) so precision against this unbiased population accumulates
across batches instead of being re-eyeballed from scratch each time. Full protocol:
`docs/methods/roofclf-national-validation.md`. First batch: 20 cells, seed 1, in
`results/pakistan_roofclf_validation/`.

**Everything else in this file is optional, supplementary, or experimental**, kept
because it is either evidence toward the main workflow (calibration, quadrat protocol),
a real but secondary product (the growth map, panel-pose survey, PyPSA-Earth grid CSV,
potential/saturation atlas), or a documented negative/inconclusive result (the fraction
head, SPPI as a standalone instrument, the older Low/Central/High/All-PV bracket atlas,
Germany MaStR calibration, dashboards, every entry under "Sub-400 m² instruments" that
was tried and not promoted). None of it is required to produce the evidence atlas, and
none of it should be read as a competing main path -- if a change here conflicts with
producing the evidence atlas correctly, the evidence atlas wins. A country with no
mapped calibration quadrats yet gets the ≥ 400 m² segmentation-only atlas
(`earthpv atlas --aoi <aoi>`, no `--sub400-*`) until quadrats exist to fit `roofclf` --
that is still this workflow's output for that country, just missing its sub-400 m² half.

## Environments & commands

Managed with **pixi**. Two environments share one solve-group, plus an independent docs env:
- `default` -- the data pipeline (DuckDB, geopandas, rasterio, odc-stac). No PyTorch.
- `ml` -- adds `torch`/`torchvision` (**cu126 wheels**) and `terratorch`.
- `docs` -- mkdocs-material only (`no-default-feature`), so a docs edit never waits on a solve.

```bash
pixi install            # default env
pixi install -e ml      # + torch cu126 + terratorch (multi-GB solve)
pixi install -e docs    # mkdocs-material
pixi run -e ml gpu-check # verify torch.cuda + device name
```

Run pipeline stages via the CLI (Typer). Long GPU stages should use the `ml` env; to
avoid pixi's per-invocation overhead you can call the interpreter directly:

```bash
pixi run earthpv labels --aoi germany            # default env is fine for data stages
.pixi/envs/ml/bin/python -m earthpv.cli train --config configs/terramind_pv.yaml
.pixi/envs/ml/bin/python -m earthpv.cli infer  --aoi punjab --checkpoint data/models/<best>.ckpt
```

CLI stages (`src/earthpv/cli.py`): `labels → chips → train → evaluate → infer →
postprocess → export`, plus `compose` (build imagery for AOIs with no local composites).
`train --smoke` runs 50 steps; `chips --limit N` caps the chip count for quick runs.
For capacity, **this is the main workflow** (see above): `density → check-density` for
the ≥ 400 m² segmentation half, `roof-classifier → roofclf-score-national →
sub400-capacity` for the < 400 m² roofclf half, then `atlas --sub400-central-cells
--sub400-low-cells --osm-solar` to combine both into the evidence atlas.
`roofclf-score-national` is the long pole (hours at country scale) and is resumable
per-cell like `density`.

**There is no test suite and no lint task wired.** Ruff is configured (line-length 100)
but run manually. The practical "does it work" check is a small end-to-end run:
`chips --aoi germany --limit 500` → `train --smoke` → `evaluate`.

## Architecture

### Data reuse -- the load-bearing design decision

To avoid re-downloading terabytes, imagery and labels are **reused from a sibling
`rooftopsenti` project** on the same drive, pointed at by `local_root` in
`configs/aoi.yaml` and each AOI's `source_region`. `src/earthpv/local_source.py` reads
that project's per-MGRS-tile Sentinel-2 composite COGs (`CompositeIndex`) and its
OSM/Overture label + building parquets (`load_solar_labels`, `load_buildings`). The
Overture (`overture.py`) and Planetary-Computer (`imagery.py`) fetchers are **fallbacks**
for AOIs with no local artifacts. **Direct Overture S3 queries time out from this machine
-- prefer the local/VIDA paths.**

Consequence: an AOI is only fully usable where the `source_region` actually has composites.
`germany` uses `germany_500`; `punjab` uses `pakistan_500` for *buildings* but that region's
composites cover **Balochistan, not Punjab** -- so Punjab imagery is built on demand by the
`compose` stage (see below) into `data/composites/punjab/`, which `infer` prefers over the
`source_region`.

### Bands & the TerraMind model

Local composites are **10-band** (B02–B12 minus the two 60 m atmospheric bands B01/B09).
TerraMind's pretrained S2L2A patch-embed is 12-band; at load, `configs/terramind_pv.yaml`
passes `backbone_bands: {S2L2A: [10 names]}` so TerraTorch **subsets the patch-embed** to
exactly those 10 bands (`config.py` holds `LOCAL_BANDS` / `MODEL_BANDS` and the mapping).
The backbone is `terramind_v1_tiny` (fits a 6 GB GPU); it's a plain ViT, so a UNet decoder
needs a feature pyramid built by the neck stack `SelectIndices → ReshapeTokensToImage →
LearnedInterpolateToPyramidal`. Training (`train.py`) is a TerraTorch
`SemanticSegmentationTask` via Lightning; checkpoints monitor `val/mIoU`.

### Adding a new AOI

`scripts/new_region.py` is the front door for a region with no local data: `check`
preflights the four open sources (Overpass label count, VIDA parquet for the ISO3,
geoBoundaries ADM1/ADM2, Sentinel-2 cloud cover in the compose window) read-only, `add`
appends the AOI block to `configs/aoi.yaml` and re-parses to catch a bad insert, `plan`
prints the runbook. **New AOIs must carry `division.iso3`** -- `buildings._iso3_for`
prefers it and the ISO2 fallback map only covers PK/DE/IN, so an AOI without it fails at
the density stage rather than at setup. `source.coop` 403s any request without a
User-Agent header, which reads exactly like "no such country". Guide:
`docs/reproduce.md`'s "Scale to a new country" section.

### Compose stage (imagery for AOIs without local composites)

`compose.py` builds Sentinel-2 composites on demand via Planetary Computer STAC
(`imagery.annual_composite`: dry-season median of the ~12 least-cloudy scenes per 0.1°
cell). It only composites **building-populated cells** (rooftop PV needs roofs), prioritized
by density, so "full Punjab" reduces to the ~60 cells covering its cities. Output mirrors
the rooftopsenti COG layout (`<cell>/composite_0.tif`) so `CompositeIndex`/`infer` read it
unchanged. It is **resumable** (skips finished cells) and **network-bound** (~2 min/cell).

### Postprocess & ranking

`postprocess.py` polygonizes probability rasters, then joins candidates to building
footprints for a rooftop/ground/no-building `placement` and a metric-based `rank_score`
(confidence × building prior). Footprints come from `buildings.py::load_dense_buildings` --
**VIDA Open Buildings** (Google+Microsoft, imagery-derived, includes small/unmapped roofs),
fetched windowed-and-cached per AOI; the local Overture ≥500 m² set is the fallback.
`export.py` sorts by `rank_score` and writes GeoParquet/GeoJSON + a MapRoulette challenge.
This candidate-polygon path is the > 400 m² individual-detection product; it is not
extended down to smaller installations -- `density.py` covers those instead (see below).

### Density stage (aggregation into PyPSA-ready shapes)

`density.py` reuses the same per-cell probability rasters (no GPU, no retraining) to
report *aggregate* PV capacity per building/grid-cell/region rather than individual
candidate polygons. It aggregates the **≥ 400 m²** population into PyPSA-ready shapes; it is
*not* the answer below that floor (see the measured blindness above). It reports three area
metrics per building: `*_det` (thresholded candidate polygons on the footprint -- the
precision-honest floor, blind to sub-threshold/sub-400 m² signal), `*_exp`
(probability-weighted area integrating sub-threshold signal, an upper-leaning ceiling),
and `*_cal` (`*_det` re-weighted by a measured P(real | size, glint) from
`configs/calibration/<aoi>_candidate_precision.yaml` -- the headline capacity number).
See README's "PV density per building" section for the full metric derivation.

**Area → capacity uses two constants, never one.** A rooftop detection is ~module area
(`DEFAULT_KWP_PER_M2_MODULE = 0.18`); a ground-mount detection is *site* area, because the
ground-PV training labels are OSM `power=plant` perimeters, so only the ground-cover ratio
is module (`DEFAULT_KWP_PER_M2_LAND = 0.07`). Both live in `capacity_calibration.py` with
lognormal priors (`kwp_draws`), so the conversion propagates into the credible intervals
instead of being treated as exact. Every all-PV estimator is split by `placement` before
conversion (`_ratios`, `_composed_mwp_draws`); the roof-scope ones are footprint
intersections and convert at the module constant throughout. Applying the module constant
to site area overstates ground-mount by 2-3x -- that regression is what the split prevents.

`density` also **excludes candidates over `postprocess.MAX_CANDIDATE_M2` (100k m²)** from
capacity. `polygonize_chips` merges every touching thresholded pixel with no upper bound,
so a connected sheet of false positives becomes one multi-km² "installation" with
`confidence` 1.0 (it is the *max* over the polygon). On the Pakistan country run 167 such
candidates carried 47% of all candidate area. `postprocess` only flags them (`oversize`);
they stay in the leads product, where a human validates every candidate. Because cell
partials cache the per-building/`*_roof` columns, the filter only reaches those on a
`--force` re-run -- `meta.json`'s `oversize_stale_partials` records when it did not, and
the candidate-population columns (`_CAND_COLS`) are rederived from the candidate frame
every run by `candidate_cell_totals` precisely so they never go stale.

### Sub-400 m² instruments (the recall correction cannot reach here)

`est_mwp_rc` scales up what was detected, so `1/recall × ~0 ≈ 0`. Measured: the whole
sub-500 m² class is **8.2 MWp** of the Pakistan estimate (~0.2% of rooftop), while one
fully-mapped km² of residential Lahore holds **3.3× more sub-100 m² PV area than the model
finds nationally**. Germany's MaStR (legally complete) puts **72.6% of rooftop capacity in
units ≤100 kWp** (≈ ≤555 m² of module), so this is very likely the majority of the quantity
the rooftop headline claims to describe.

**Of everything below, `roofclf` (with SPPI cross-validation) is the one promoted into
the [main workflow](#main-workflow-default-pipeline-primary-output)'s evidence atlas.**
The fraction head, SPPI as a standalone instrument, and every retrain variant discussed
below were tried, measured, and NOT promoted -- kept here as the record of what was
tried and why it did not replace `roofclf`, not as alternative main paths.

**All instruments below are rooftop/building-scoped -- small ground-mounted installations
below 400 m² have no instrument at all, at any confidence level.** `roofclf` and SPPI are
both per-*building* classifiers (they score a VIDA footprint); the fraction head is the
only one of the three not tied to a building, but it still runs on the same segmentation
input trained with everything below `chips.MIN_PV_AREA` burned as `ignore`, so a small
free-standing ground array gets no more signal there than a small roof does. There is
no building footprint to hang a classifier off for ground-mount the way there is for
rooftop, so the partial mitigations below do not generalize to it even in principle --
this is a distinct, currently open gap, not a smaller version of the rooftop one. Two
instruments, both rooftop-only and both dropping the polygon:

- **Fraction-head expected area** -- `density --fraction-prob-dir <run>/prob [--exp-scale k]`
  swaps the `*_exp` instrument from segmentation class probability to per-pixel PV coverage.
  Quadrat-measured predicted/true ratio in the *residential* quadrat: segmentation **0.023**
  vs fraction **0.520** (≈23× better); comparable in the four industrial quadrats. As of
  2026-07-29 the fraction run reached **full coverage** (4,463/4,463 cells,
  `exp_coverage_frac: 1.0`; inference had actually finished 2026-07-27, docs just lagged)
  and the national rooftop expected-area number moved 5.4 → 6.65 GWp (+23%), matching the
  quadrat-level direction. **Still not promoted to the published atlas** -- that same full
  `--force` run failed `earthpv check-density` (Gilgit-Baltistan: 110 MWp ground-mount
  against 0.000 MWp rooftop), traced to a `density.py` regression in `no_building`
  candidate aggregation that is **confirmed** architecturally unrelated to the
  exp/fraction swap itself -- an isolating segmentation-instrument rerun (2026-07-29
  23:07, same pre-existing candidates) reproduced the identical 0.000/109.982 MWp
  numbers -- see `docs/issues/density-force-recompute-plausibility-fail.md`.
  `plausibility.py` now exempts Gilgit-Baltistan from check 1 specifically
  (`RATIO_CHECK_EXEMPT_REGIONS` -- its real rooftop base rate is near zero, so the ratio
  is structurally uninformative there), so `check-density` passes again (0 fail, 3
  suspect) on both instruments. That unblocks the gate; it does **not** confirm the
  110 MWp ground-mount figure is correct -- locating the exact cause in `density.py`/
  `postprocess.py`'s aggregation code is still open.
  **Retrain attempt, 2026-07-30: negative, not promoted.** `fraction_pakistan_v2`
  (8 of 9 quadrats oversampled 20x into the national corpus, `lahore_calib_1km` held
  out for validation) scored *worse* than production on every metric measured against
  Lahore's own ground truth (scale 0.520→0.197, correlation 0.136→0.070, AUC
  0.589→0.553) -- training-from-scratch on the current recipe should not be assumed to
  transfer just because more real small-array labels were added. See
  `docs/issues/roofclf-national-deployment-and-temporal-features.md`.
  **Hard-negative retrain, 2026-08-03: positive, promoted.**
  `hard_negatives.py::run_hard_negatives` mined 1,032 large OSM-unmapped buildings the
  production checkpoint already scores correctly-low in two imagery epochs
  (reinforcement of existing correct negatives, not a fix to a known false positive);
  after excluding 11 whose center falls inside a current OSM solar polygon, the
  remaining 1,021 clean chips were folded into the training pool (2,626 total,
  unweighted) alongside the same Germany+Pakistan corpus v1/v2 used.
  `fraction_pakistan_hardneg/terramind-pv-epoch=32-step=27027.ckpt` (5h35m, early-stopped
  epoch 40 of 60) scores better than v1 on `pakistan_fraction`'s own genuinely
  held-out val split: pixel IoU 0.459→0.500, F1 0.629→0.666, false-positive pixels
  -28.6%, at a per-installation recall cost of at most 2 installations per size
  bucket (noise, given n=37-180 per bucket) -- a real reduction in false positives
  without a real loss of recall on *that* split. **`fraction_pakistan_hardneg` is now
  the fraction-head checkpoint of record**, replacing `fraction_pakistan_v1`.
  **National inference re-run 2026-08-03/04 and validated against the quadrats --
  a regime-specific win, so still NOT promoted into the published sub-400 m² numbers.**
  Ran on the latest dry-season composites (`composite_0`, 2025-11-01→2026-03-15, the
  most recent in-domain layer; there is no newer one until Nov 2026), single-epoch:
  4,473/4,473 cells in 3h19m, then `density --fraction-prob-dir` at full coverage.
  It cuts national rooftop expected area 21.9% (6,647→5,194 MWp) and off-building raw
  response to 0.30x, and the median quadrat scale (predicted/true) improves from 1.458
  to 0.809. But scoring both rasters against all 12 mapped quadrats
  (`scripts/validate_fraction_quadrats.py`, no GPU -- it reads the finished national
  rasters; `results/fraction_quadrat_validation.csv`) splits **exactly 6/12 and not at
  random**: every quadrat that improves is industrial/large-array, every one that
  degrades is dense small-rooftop -- median pixel AUC 0.790→0.749, with Peshawar
  0.840→0.799 and Peshawar-east 0.852→0.776. In `mardan` and `karachi_coast` -- both
  Rule-1 complete, and both places v1 already *under*-predicted (0.311, 0.291) -- the
  retrain cuts predicted area a further 75%/64%, which cannot be removed false
  positives because there was no over-prediction to remove. So the sub-400 m² products
  (`results/`, `docs/results/growth.md`, the evidence atlas's Best-estimate tier)
  deliberately still describe `fraction_pakistan_v1`. Both national rasters now exist
  side by side, which makes "hard-neg raster for ≥400 m², v1 for sub-400 m²" cheap to
  test next. Note also that this pass's `*_rc`/roof figures (2,847 / 570.9 MWp,
  `check-density` 2 fail) reproduce the documented candidate-population mismatch
  byte-for-byte and are not new results -- the fraction head only drives `*_exp`. See
  `docs/issues/fraction-head-hard-negative-retrain.md`.
  **Quadrat-supervised retrain, 2026-08-04/05: a large in-sample win that the holdout
  does not support, so still NOT promoted.** Two runs of v1's exact recipe differing only
  in corpus -- `fraction_pakistan_quadrats` (all 13 quadrats as pixel supervision, x8) and
  `fraction_pakistan_quadrats_holdout_karachi` (12 quadrats, `karachi_coast_calib_700m`
  held out, and the one national chip covering 16.3% of that box excluded too). Unlike
  the failed v2 quadrat attempt, `earthpv quadrat-chips` confines supervision to the
  mapped ground (v2 trained on a ~81%-unmapped chip mixture at 20x, which taught
  suppression of the very signal the quadrats supply). In-sample this reverses v2
  decisively: pixel AUC beats v1 in **13 of 13** quadrats (median +0.0615) and, more
  importantly, `scale` dispersion collapses from **11.95x** (geo-SD 2.447; v1 ranged
  0.262 Quetta to 3.131 Faisalabad) to **2.48x** (geo-SD 1.313) -- a uniform ~2x
  over-prediction is one `--exp-scale` constant from corrected, an 11.95x spread is not
  correctable at all. **That consistency is fitted, which is why it is not promoted.** On
  the held-out box the model reverts to `scale` 0.461 -- outside the tight 1.878-3.684
  band it holds on trained-on quadrats, and only ~10% of the way from v1's 0.291 to the
  in-sample 1.963 -- so a national `--exp-scale` derived from the in-sample band would
  push the estimate the wrong way everywhere unlike the 13. Discrimination transfers
  better but is not established: +0.0265 AUC out-of-sample vs +0.0650 in-sample (~41%),
  and a paired spatial block bootstrap (`scripts/quadrat_auc_block_bootstrap.py`, blocks
  resampled rather than pixels, since a 10 m raster gives many pixels per installation)
  puts the held-out gain at **-0.009 to +0.061, one-sided p 0.062** at 50 m blocks,
  degrading monotonically to p 0.102 at 120 m, while the in-sample gain clears zero at
  every block size. n=1 quadrat, 797 labelled pixels, is the binding constraint -- more
  LOQO folds, not more analysis of these rasters, is what would resolve it. One
  standing hypothesis was killed on the way: the ~2x over-prediction is **not** stale
  labels. Running the same checkpoint on the pre-boom composite
  (`scripts/fraction_stale_label_audit.py`) attributes only **5.8%** of apparent
  false-positive pixels to candidate post-mapping installations, moving pooled precision
  0.435 → 0.450. Reading note: a quadrat can show near-zero thresholded `tp` and `scale`
  ~1.7 at once (Mardan) -- its predictions are diffuse (mean fraction 0.036) and rarely
  cross 0.2, while `scale` integrates sub-threshold coverage, which is how `*_exp` uses
  the raster. Both checkpoints' quadrat-cell rasters are kept in both epochs
  (`data/predictions_quad{13,ho}_quadcells{,_preboom}/`) so further scoring needs no GPU.
  Full tables: `docs/issues/quadrat-supervision-fraction-retrain.md`.
- **`roofclf.py` / `earthpv roof-classifier`** -- **the sub-400 m² half of the main
  workflow** (see "Main workflow" above), per-building "does this roof carry PV?",
  trained on the exhaustively mapped quadrats (the only source where a no-PV building is a
  real negative).
  **Read this before trusting any national roofclf number below (2026-08-06).** A JOSM
  review found detections lining the straight edges of the 0.1 deg composite cells. Cause:
  `CompositeIndex.read_window` round-trips a tile's UTM bounds through a lat/lon envelope
  and back, which inflates the requested window past the tile (50-70 m in Punjab, up to
  357 m at the worst tile), and `rasterio.merge.merge(..., nodata=0)` fills the excess with
  **zeros**. Zero reflectance is darker than any real roof and PV is dark, so the fitted
  model scores an all-fill footprint at p=0.735 (100 m2) against 0.100 for a typical roof,
  and 0.484 even at 30 m2 -- above the 0.2407 deployment threshold at every size.
  Nationally: **2.86M all-fill building rows, 95.4% of them flagged, 45.6% of every flagged
  building in the country**; within 25 m of a cell edge the flag rate was 65.3% against
  5.9% in the interior. Training was near-clean (only sialkot 1.0% and sukkur 0.45% of
  their windows are fill, the other 15 quadrats none), which is exactly why it went
  unnoticed -- a train/deploy skew, not a modelling error. Fixed by
  `zonal_mean_max(..., nodata=COMPOSITE_FILL)`: fill pixels are excluded from the zonal
  statistics and a footprint with no valid pixel gets NaN (row kept, score NaN, so
  `potential.large_roof_buildings` and building counts stay complete while nothing
  unscored can clear a threshold). **Padding the read was tried and measured worse** --
  composite tiles overlap by ~150 m strips, `merge`'s "first wins" precedence is filename
  order rather than the cell's own tile, and the bounds are off the source pixel grid, so
  padding re-sources the whole border strip from a differently-composited neighbour: it
  leaves Lahore's sub-50 m edge at 10.1% against a 5.95% interior, and moves an isolated
  cell's *interior* rate 3.86 -> 4.68%. Masking alone gives 5.06% vs 5.95% and leaves
  interior buildings bit-identical.
  A **second, independent bug** surfaced during the same testing, in two forms. The
  severe form: composite cell bboxes overlap where Pakistan's own grid is only
  *phase*-anchored to an earlier Punjab-only compose run's grid (mod 0.1 deg), not
  index-anchored to it, so the same ground can carry two valid-looking canonical names
  (e.g. Lahore is `0134_0078` under Pakistan's grid, `0219_0117` under Punjab's) -- 3
  canonical cells nationally (all in Lahore) were claimed by both grids, 783,563
  duplicated building instances. The shallow, universal form: ordinary composite tiles
  are deliberately ~1% oversized so `read_window` never gaps at a seam (`density.py`
  crops this away before summing; `score_buildings_national` did not), so a building in
  that buffer strip was legitimately "inside" two neighbouring tiles at once -- measured
  0.5-3% shared rows on ordinary (non-Lahore) neighbour pairs. **Both fixed** the same
  way (`roofclf.canonical_composite_manifest`, reusing `density.cell_manifest`'s existing
  dedup convention): both scoring loops now iterate a deduped, canonical 0.1 deg grid and
  use each cell's exact non-overlapping box for both ownership and the raster read.
  **A full re-run (refit -> national scoring -> sub-400 capacity -> evidence atlas,
  `scripts/run_roofclf_edge_fix_repipeline.sh`) completed 2026-08-06, ~2h23m.** National
  building rows fell 81,762,684 -> 75,703,524 (-6.0%, both bugs combined, confirmed pure
  double-counting: every one of the 4,461 differing cells went down, none up). The
  evidence atlas moved in the predicted direction: Verified 13,697.1 -> **10,634 MWp**
  (-22.4%), Best-estimate 21,354.8 -> **18,879 MWp** (-11.6%). Pre-fix atlas backed up to
  `results/pakistan_pv_evidence_atlas_PRE_edge_overlap_fix_20260806_backup.html`. New
  canonical "current" paths (used by `scripts/build_small_pv_josm_leads.py` and any
  future refresh): `data/roofclf/` (refit) and
  `data/roofclf_national_with_sppi/pakistan/prob/` (national scoring) --
  `data/roofclf_national_20260805/` is now superseded and should not be read by anything
  new. Full writeup, tables and both fix mechanisms:
  `docs/issues/roofclf-cell-edge-false-positives.md`.
  Updated 2026-07-29 to **9 quadrats, 22,044 buildings, 2,376 with PV**
  (added Sialkot, Mardan, Quetta). Leave-one-quadrat-out median AUC **0.874** (was 0.879 at
  6 quadrats), **0.842 conditional on roof-size band** (was 0.845), against the
  segmentation raster's conditional median, which **dropped from 0.707 to 0.501** -- chance
  -- now that 5 of 9 quadrats are non-industrial and segmentation scores ~0.50 in four of
  those five. Ablation set the default feature set: size-only 0.715, reflectance-only
  0.841, size+reflectance **0.874**; adding the seg/frac rasters as features now comes out
  roughly neutral on small roofs (0.856 → 0.858, a reversal of the old "hurts small roofs"
  reading, but small enough either way to be noise) -- they stay off by default regardless,
  the case for including them was never strong. Two more candidate features tested
  2026-07-29, neither kept: epoch-jump (both a free reflectance-delta version and a
  probability-delta version needing a targeted `infer --index 1 --tiles` pass) and
  step-change (per-building aggregation of `pv_step_signal.py`'s pixel output, tested on
  5 of 9 quadrats) -- see
  `docs/issues/roofclf-national-deployment-and-temporal-features.md` for why each failed
  (one quadrat crash, no effect, and a within-size-band confound respectively).
  **Deployed beyond evaluation for the first time 2026-07-29**: `roofclf
  .score_buildings_national` fits one pooled model on all 9 quadrats, picks a
  precision-targeted deployment threshold (0.4555, precision 0.50/recall 0.25 on
  pooled LOQO scores -- reuses `sppi._precision_threshold`), and scores every VIDA
  building nationally via the same per-cell pattern `density.process_cell` already
  proves tractable (`local_source.composite_index()`'s `lru_cache`, previously unused,
  now avoids rebuilding the ~4,474-tile composite index once per call).
  **Capacity fold-in tried 2026-07-30, rejected**: folding the 898,593 nationally-flagged
  buildings (97.1% with no existing segmentation candidate) into capacity at the flat
  LOQO precision (0.50) gives 18,063 MWp incremental -- 3.5-8x the country's entire
  existing recall-corrected total (5,078 MWp all-placement, 2,230 MWp roof-only). Not a
  result, a miscalibration: PPV at a fixed threshold falls as true prevalence falls, and
  extrapolating a 9-quadrat precision (10.8% PV base rate, urban/industrial-skewed) to
  81.76M mostly-rural buildings nationally is exactly the "absolute rates don't transfer"
  failure already on record just below (rate_ratio 0.235–4.833). Three cells also show
  textbook logistic-saturation (`p_roofclf` pinned ~0.999999, a covariate outside training
  range) but are a minor, secondary artifact (4% of flagged area). **Not folded into
  `density.py`**; `roofclf`'s national output stands as a per-building ranking/lead-gen
  signal only, pending a per-stratum precision correction that doesn't exist yet. See
  `docs/issues/roofclf-national-deployment-and-temporal-features.md`.
  **Quetta-exclusion recalibration, 2026-07-30 -- a genuine, measured win.** Quetta is the
  lowest-base-rate quadrat by a wide margin (3.0% vs next-lowest 5.7%) and the one place
  SPPI's own detector collapsed to 10.5% precision; it was forcing the pooled 9-quadrat
  threshold up to 0.4555 to hold 0.50 precision, catching only 25% recall. Re-fit on the
  other 8 quadrats (`quetta_calib_1km` excluded; old 9-quadrat outputs kept at
  `data/roofclf_with_quetta_20260730/`) relaxes the threshold to **0.3064** and recall at
  the same 0.50 precision rises to **39.6%** -- median fold AUC dips slightly (0.874→0.861,
  expected, since Quetta's own raw AUC was fine at 0.852; it was the threshold-transfer
  side that broke) and Mardan stays the worst fold (0.743) unchanged, confirming Mardan's
  problem is unrelated to Quetta. This is a clean illustration of the "ranking transfers,
  absolute rates do not" lesson: one outlier stratum, not nine ordinary ones, was setting
  the whole country's operating point. `model_full.json` now reflects the 8-quadrat fit;
  national re-scoring with it is a separate, larger step (does not, by itself, fix the
  capacity fold-in rejection above -- a lower threshold flags *more* buildings, so the
  incremental-capacity number is expected to grow, not shrink, until a real per-stratum
  correction exists).
  **SPPI cross-validation, 2026-07-30 -- a genuine, measured, but uneven win.** SPPI (He
  et al. 2026, zero-training spectral index) scored on the exact same held-out ground
  truth roofclf uses: median AUC 0.823/0.828 (within size band) vs roofclf's
  0.874/0.842 -- roofclf wins but not by much for something needing no training. Adding
  SPPI as a roofclf *feature* does nothing (0.8736→0.8734 AUC, already known). But an
  **AND-gate** (roofclf ≥ 0.3064 **and** SPPI above a matched-recall threshold, sub-400
  m² buildings, 8 quadrats no-Mardan) lifts precision from 0.496 (roofclf alone) to
  0.540 at matched recall (0.445) -- roofclf-alone precision at that same recall is only
  0.498, so this is a real +4pp gain from agreement, not just a stricter cutoff. Per
  quadrat the gain concentrates almost entirely in Multan (+10.7pp), Sialkot (+5.5pp),
  Sundar (+5.1pp) -- exactly the three low-base-rate quadrats already excluded from the
  density-stratified precision fit below for overestimating 2x+. Coherent story: SPPI
  agreement specifically catches roofclf's overconfidence in the regime already known
  miscalibrated, not a uniform improvement (Faisalabad/Karachi coastal: -0.7/-0.9pp).
  **Tested nationally the same day: does not help the domain-restricted sub-400 figure.**
  `score_buildings_national` now saves `sppi` (zero extra cost); re-ran nationally
  (`data/roofclf_national_with_sppi/`). Applying the AND-gate to the SAME 93
  domain-restricted cells the 6,628 MWp figure uses: precision on those three calibration
  quadrats is flat (0.5501→0.5499) while the AND-gate cuts flagged buildings 31%
  (496,122→343,032) and the capacity figure 29% (6,628→4,690 MWp) for zero precision
  gain -- confirms the per-quadrat table's own prediction (SPPI helps in the low-density
  quadrats the domain restriction already excludes, so stacking it on an
  already-restricted population only removes recall for free). **Not adopted** for the
  domain-restricted figure, which stays at 6,628 MWp (roofclf-only). Full writeup:
  `docs/methods/density.md`'s "SPPI cross-validation" subsection.
  **Density-stratified capacity, 2026-07-30 -- a partial fix, deliberately kept out of
  `density.py`.** `sub400_capacity.py` (new module) answers "how much does restricting to
  the calibration-covered density regime change the rejected 18-37 GWp national number,"
  and the answer is nuanced: precision alone does not fix it (0.499→0.5495 pooled
  precision from restricting to the 3 quadrats whose `rate_ratio` is within 2x either
  direction -- faisalabad, karachi_coast, site_karachi, base_rate 12.5-18.5% -- makes the
  *unrestricted* national number worse, 37,197→40,879 MWp, since 0.5495>0.5). The
  relationship between `rate_ratio` and `base_rate` is not "higher density is better" --
  it is a crossing point: quadrats below ~12% base rate overestimate 2x+, the one quadrat
  well above it (lahore, 30%) underestimates instead, and mardan is a separate,
  already-documented bad fold. What actually moves the number is restricting the
  *population*, not the weight: intersecting the density-regime precision with the
  pre-existing building-density domain restriction (93 of 4,473 national cells matching
  the 8 quadrats' 737-4750 bldg/km² range) AND excluding buildings whose own footprint is
  already ≥400 m² (a `new_lead_mask` 30 m-radius matching gap, not real sub-400 signal --
  13.4% of the domain-restricted incremental buildings, 49% of its area) gives **6,628
  MWp**, the same order of magnitude as the country's entire existing
  segmentation-based total (5,078 MWp) for the first time. This number describes ONLY
  those 93 cells (19.1% of national buildings) -- rescaling it by the domain's cell/building
  share to estimate a country total (~implies 315 GWp) is exactly the failure this module
  exists to avoid, and `domain_restricted_capacity`'s returned summary says so explicitly.
  The 93 cells concentrate in Karachi, Lahore, Peshawar, Mardan, Faisalabad, Islamabad,
  Sialkot, Multan, Gujranwala, Charsadda, Sheikhpura, Rawalpindi and Quetta -- i.e. Pakistan's
  largest cities, matched against the building-density (not PV-density) proxy, the only one
  that survived testing (existing candidate density anti-correlates with true small-PV rate;
  roofclf's own predicted rate does not separate calibrated from miscalibrated quadrats
  either -- both tested and rejected as national selection proxies this session). Kept as a
  **separate product**, never merged into `density.py`'s `total_est_mwp_rc`: the fraction-head
  promotion attempt into `density.py` itself (below) broke `check-density` for an unrelated
  reason, and stacking two shaky corrections into one pipeline path is how that happened.
  `density.py` itself gained one small, safe, segmentation-only addition instead: a
  `density_confidence` flag (`below`/`in`/`above_calibrated_range`, from the same 737-4750
  bldg/km² range) on `grid.csv`/`regions.csv`, which states where the ≥400 m² recall
  correction has no calibration evidence either way -- it does not correct anything, and it
  is deliberately never computed for a fraction-head run (`aggregate`'s `exp_source` gate),
  so it cannot be read as validating a different instrument's numbers.
  **Fraction-head promotion into `density.py`, attempted and reverted the same day.**
  Forcing `density --fraction-prob-dir` through the *current* (post-OSM-replace) candidate
  population broke `check-density` (2 regions failing vs. the passing 0-fail baseline) --
  root cause: a disproportionate 46% collapse in roof-intersected candidate area vs. 29%
  overall, most likely the same never-fully-root-caused `density.py`/`postprocess.py`
  ground-mount aggregation issue as the Gilgit-Baltistan case above, now exposed by the
  first *forced* full recompute against the OSM-corrected candidates. Reverted to the
  passing segmentation-based backup; the fraction head is not promoted, and the sub-400
  products above are its replacement path -- evidence-bearing but explicitly out-of-band.
  **Generalized the same day, by accident and worth recording**: a plain, non-`--force`
  `earthpv density --aoi pakistan --districts` re-run (adding only the `density_confidence`
  flag, segmentation instrument, no fraction involved) reproduced the identical failure
  (2 fail, 3 suspect; `total_est_mwp_rc_roof` 2,229.9→570.9). Cause: `_CAND_COLS` is
  *always* rederived from whatever `candidates.parquet` is current, every run, force or
  not, while the cached cell partials' per-building/`*_roof` columns only refresh on
  `--force` -- so the two now permanently disagree, because `candidates.parquet` was
  OSM-geometry-replaced (2026-07-29, oversize 233→149) after the partials were last built.
  **The fraction head was never the cause -- any run against the current candidate
  population breaks the gate, segmentation included.** The published `density/` is
  therefore pinned to the pre-OSM-replace candidate snapshot (`n_oversize_excluded=233`,
  restored from `density_segmentation_pre_fraction_promote_20260730/`) until someone does
  a `--force` rebuild AND separately root-causes the roof-candidate collapse that a
  `--force` rebuild triggers -- both are still open. The broken re-run is preserved at
  `density_STALE_PARTIALS_VS_CURRENT_CANDIDATES_20260730/`. Consequence: the
  `density_confidence` completeness flag is implemented and correct but not yet present
  on the published output, since publishing it requires a run this bug currently blocks.
  A `--force` rebuild against the current candidates was relaunched the same day to get
  the true consistent state and check whether the KP/Balochistan ratio failure is a
  genuine finding (their large `no_building` candidates share Gilgit-Baltistan's exact
  low-OSM-match, remote-terrain profile, circumstantial but not proof) or a further
  aggregation bug.
  **Result: confirmed genuine, not a further bug.** The 2-hour `--force` rebuild
  completed cleanly (4,463/4,463 cells, zero failures, fingerprint written) but crashed
  at meta.json on the exact `stale_partials` NameError described above -- the running
  process had the pre-fix code loaded in memory, editing the file mid-run couldn't
  reach it. Cheap fix: re-running `density` (no `--force`) with the now-fixed code
  skipped every cached cell and finished in seconds, producing the same numbers.
  `check-density` on this true, fingerprint-verified current state **still fails
  identically** (KP 8x, Balochistan 18x, 2 fail/3 suspect) -- proving the ratio failure is
  a real property of the current candidate population (uneven OSM-replace correction:
  rooftop candidates got dramatically smaller/more precise via frequent OSM matching,
  `no_building`/ground-mount candidates rarely match OSM and mostly kept their original,
  possibly-inflated size), not an artifact of any bug introduced this session. **Not
  published** -- restored the passing pre-replace backup again pending investigation;
  the true-but-failing state is preserved at
  `density_TRUE_CURRENT_STATE_FAILING_20260730/` for whoever root-causes it next. This is
  now the actual, non-speculative version of task substance in
  `docs/issues/density-force-recompute-plausibility-fail.md` -- that doc should be updated
  to match before anyone treats the KP/Balochistan question as still open-ended.
  **A tenth quadrat was added 2026-07-30**: `peshawar_calib_1km`, centered at the
  user-supplied (34.0199854, 71.5505752), built as an exact geodesic 1 km² square
  (`pyproj.Geod.fwd`, not hand-drawn). **Re-pulled twice more the same day** as the user
  added missing OSM labels: 290→353→360 installations (+63, then +7 -- a shrinking
  increment, suggestive of convergence but not proof of completeness). 358/360 (99.4%)
  below the 400 m² floor, 265/360 (73.6%) below 100 m², packing distance 15.7 m (same
  tightly-packed cluster as Karachi coastal/Quetta/Sialkot) -- the densest sub-floor haul
  of any quadrat registered so far. All three pulls kept, none overwritten: bare
  `peshawar_calib_1km_overpass_solar.parquet` (290), dated `..._20260730.parquet` (353),
  `..._20260730_v2.parquet` (360, current) -- `_newest_solar`/`_newest_overpass_path` both
  pick the `_v2` file, verified. **Still not Rule-1 verified** -- repeated re-pulls are
  not a substitute for a human completeness pass with a second-mapper sign-off; treat it
  like Boxes 2-5 (usable as a `roofclf` training quadrat, not as a source of trustworthy
  negatives) until that happens. `roofclf.discover_quadrats()` picks it up automatically
  (globs `*_calib_*_boundary.geojson`); not yet folded into a retrained `model_full.json`
  -- the next `earthpv roof-classifier` run will include it with no flag needed.
  Registered as Box 9 in `docs/issues/pakistan-calibration-boxes.md`.
  **An eleventh quadrat, `peshawar_east_calib_1km`, was added the same day and
  WITHDRAWN 2026-08-05 as wrong** (owner's instruction; files retired to
  `data/labels/retired/`, removed from `results/calibration_quadrats.csv`, the JOSM
  validation layer and `atlas.py::CALIBRATION_BOXES`). It was created at a second
  user-suggested center (34.0242579, 71.5600512) -- checked for overlap *before* creation
  (per the new procedure this added to the mapping protocol): ~995 m from Box 9's center,
  sharing 6.56% of its area as one corner. Added on the user's confirmation. **That
  overlap was denser than its area share suggests**: 42/131 (32.1%) of the box's
  installations sat inside the shared 6.56% corner, so pooling both Peshawar quadrats into
  `roofclf` training without deduplication would double-count those ~42
  installations/buildings and break LOQO's fold-independence assumption for that pair.
  **Removal is what resolved that -- no deduplication code was ever written**, so
  `new_calibration_quadrat.py`'s pre-creation overlap check remains the only guard; do not
  pass `--allow-overlap` without a plan for the shared ground. Its other numbers, now
  history: 131 installations, 100% below the 400 m² floor, median 44.9 m², base_rate 3.7%
  (126/3,382 buildings) -- notably lower than Box 9's 16.5% despite being 995 m away in
  the same city, and on 60% more buildings over a similar-sized box, which was a concrete,
  fine-grained illustration that `base_rate` cannot be pooled even between adjacent
  quadrats. Was Box 10. **Its removal makes every pooled `roofclf`/fraction number that
  included it stale in the same way the Lahore and Sundar replacements do** -- see the
  staleness note below.
  Both Peshawar boxes and this overlap caveat are in the new
  `docs/methods/calibration-quadrats.md` overview page (added the same day, in direct
  response to the user not being able to find a table of quadrat status anywhere on the
  site) -- that page, not this narrative log, is the place to look for current per-quadrat
  numbers going forward; this file keeps the dated history of how each number changed.
  **Box 12, `peshawar_west_calib_1500m`, was added 2026-08-04** and is the first quadrat
  created by a script rather than by hand: `scripts/new_calibration_quadrat.py` builds the
  geodesic square, runs the overlap check *before writing anything* (refusing a hit
  without `--allow-overlap`), pulls OSM solar and prints the profile. Use it for the next
  one. It is 1.5 km on a side (**2.25 km², the largest in the set** -- do not assume 1 km²
  anywhere), 11.95 km from Box 9 so it carries no dedup debt, Peshawar district/KP, and
  its value is that it is *unlike* Boxes 9/10: 163 installations, 48.5% sub-floor by count
  but only **7.7% sub-floor by area** (92.3% of mapped area is ≥400 m², 38 installations
  ≥1,000 m²), so it is the first Peshawar quadrat that can score the segmentation model at
  all rather than only the sub-400 m² instruments. `n_pv_buildings` (415) exceeding
  `n_installations` (163) is expected here, not a bug -- `building_table` flags by overlap
  share and arrays this large span several VIDA footprints. Two consequences worth
  carrying: (a) its `nn_median_m` of 34.0 m, plus Box 11's 20.3 m, **fill the 20-40 m
  packing gap** that `docs/methods/calibration-quadrats.md` and the mapping protocol both
  described as empty with "nothing in between" -- the bimodality was an artifact of the
  original nine purposive boxes, so rely on `packing_density`'s r=0.70-0.82 correlation,
  not on a two-regime cluster label; and (b) **a mirror can answer an Overpass query with
  zero elements instead of erroring** when `overpass-api.de` 504s and `_run_query` fails
  over -- measured on this box, two consecutive pulls of the same bbox gave 0 then 167, so
  the new script treats an empty response as retryable and no 0-installation quadrat
  should ever be registered from a single attempt. Box 11's base rate was also corrected
  from an estimated 8.7% to its exact matched **10.3%** in the same pass, and both boxes
  are now in `results/calibration_quadrats.csv` and the overview table (13 rows).
  **Quadrat completeness passes are done from one exported layer, not one file at a time
  (2026-08-04).** `pixi run calib-export`
  (`scripts/export_calibration_quadrats_geojson.py`) writes every quadrat into
  `results/calibration_quadrats_validation.geojson` -- 13 `quadrat_boundary` boxes plus
  3,353 `mapped_solar` polygons -- with a sibling `.mapcss` JOSM paint style, because an
  imported GeoJSON otherwise renders in one flat colour and "which line is the boundary"
  is the whole point. Re-run it after adding a quadrat or refreshing any
  `_overpass_solar` pull; it reads `discover_quadrats` + `_newest_solar` so it cannot show
  a stale pull. Three non-obvious things baked in: (a) the layer is **reference geometry
  that must never be uploaded** -- the boxes are not OSM features and the solar polygons
  are copies of ones that are, so every feature carries a `do_not_upload` tag and the doc
  says to edit only in the OSM layer; (b) edge-straddling installations (representative
  point outside the box, footprint reaching in -- 59 of 3,353) are **exported and
  flagged, not dropped**, since a panel visibly inside the line with no polygon on it
  reads as unmapped and re-mapping it would duplicate an existing OSM feature, so each
  box reports both `n_mapped_solar` (matches the docs table) and `n_inside_box`; and
  (c) the five oldest pulls (Faisalabad, Lahore, Multan, SITE Karachi, Sundar) carry **no
  `placement` column at all**, so a missing placement there means absent, not "rooftop".
  Workflow documented at
  `docs/calibration-mapping-protocol.md`'s "Validating every quadrat in one pass".

**A sub-400 m² capacity bracket was assembled 2026-07-31**, replacing the single rejected
18-37 GWp point estimate with an explicit range plus two non-imagery anchors. Domain-
restricted (93 cells only, `sub400_capacity.py`, NOT a national figure): 6,628 MWp
roofclf-alone, **2,651 MWp** for a new roofclf-AND-SPPI AND-gate
(`domain_restricted_and_gate_capacity`, promoted out of an unsaved prior script that had
reported 4,690 MWp under a different, non-reproducible SPPI threshold, and that number is
superseded). Unrestricted national ceiling, refreshed at the current 0.3064 threshold:
**37,197 MWp** (matches the figure already on record; supersedes the older 18,063 MWp run
at the prior pre-Quetta-exclusion 0.4555 threshold), explicitly uncalibrated per the
user's go-ahead to publish an upper bound that doesn't need full validation. Two
independent, non-imagery anchors pulled in for the first time: Pakistan's NEPRA
net-metering register (5.3 GW registered by April 2025, 283k consumers, 18.7 kWp/consumer
average, well under the model's 72 kWp floor, so this register is itself dominated by
the sub-400 m² population, and it is a floor since it excludes unregistered/off-grid
solar) and Chinese customs import data (16.91 GW in 2024 alone, ~50 GW cumulative by
August 2025 per trade press, a much looser, all-market ceiling). A Germany MaStR-shape
transfer applied to this project's own current ≥400 m² total (2,229.9 MWp roof,
recall-corrected, summed fresh from `grid.geoparquet`; an earlier draft of this note
misread `regions.csv`, which carries both province- and district-level rows each
summing to the national total, and summed across both, doubling it to 4,457; corrected
2026-07-31) implies roughly 5.9 GWp sub-400 m², landing close to the domain-restricted
central figure rather than between it and the unrestricted ceiling. Full derivation,
caveats and a table:
`docs/methods/density.md`'s "A sub-400 m² capacity bracket" section.

**The bracket is resolved per cell in an interactive atlas** (added the same day,
extended 2026-07-31): `results/pakistan_pv_sub400_bracket_atlas.html`
(`atlas.build_sub400_bracket_atlas`). Low and Central fold large rooftop PV into their
reported total (large PV nationwide plus small PV inside the checked cells); High
stays small-PV-only on purpose, since it is an explicit, uncalibrated ceiling and
combining it with the project's main validated number would blur that distinction. A
fourth view, All-PV, was added on request the same day: Central's small-PV component
plus large PV across every placement, ground-mount farms included, giving 11,706 MWp
nationally. This is deliberately not folded into Central itself: ground-mount is a
different asset class (site-area, not module-area, conversion) and the pipeline's most
bug-prone component (the ground-mount-to-rooftop ratio check in `plausibility.py`
exists because of it), so adding it does not raise certainty, it adds a different kind
of risk under what would otherwise read as a rooftop number. Two next steps
identified as harder than another modeling pass: probability-sampled (not purposive)
calibration quadrats for a design-based national variance estimate (not started, needs
new field/OSM mapping, not code, outside what this agent can do itself), and per-cell
sub-pixel unmixing self-calibrated against each cell's own ≥400 m² detections. The
second was tried the same day (`src/earthpv/unmixing.py`, two-endmember linear mixture,
LOQO-evaluated on the 8 quadrats): **negative in this form**, median AUC 0.659/0.664
(within size), worse than SPPI (0.823/0.828) and roofclf (0.874/0.842), and a 92x scale
spread across quadrats, the worst of any instrument on this page. The LOQO test pools
endmembers across quadrats, though, which is exactly the cross-quadrat transfer this
page's other proxies already fail at; it does not test the actually-novel claim
(fitting a cell's endmembers from that cell's own confirmed detections), which needs
national grid-cell scale, not a 1 km² quadrat, to have enough of its own large
detections to calibrate against. That version (`unmixing.cell_selfcheck_ratio`,
implemented, unexercised) is still open. Full table and discussion:
`docs/methods/density.md`, item 10 under "How the estimate got here."

**The bracket atlas was superseded by a three-tier evidence atlas, 2026-08-01.**
`atlas.build_evidence_atlas` + `templates/pv_evidence_atlas.html` replaces
Low/Central/High/All-PV (a menu of point estimates on one scale) with **Verified / Best
estimate / Ceiling** -- three different *standards of proof* over the same underlying
numbers: Verified is the hand-mapped OSM population plus buildings where roofclf and
SPPI both agree (no single model trusted alone); Best estimate adds the recall-corrected
&ge;400 m² detections plus roofclf-alone density, with the OSM/detection overlap removed
via `osm_matched_id` rather than summed twice; Ceiling keeps the old High figure (flat
0.5 precision, thresholded, national) and, per explicit request, adds the known
&ge;400 m² total on top rather than showing small-PV alone -- landing at **42,251 MWp**
(37,173.0 High-only + 5,077.9 large-PV -- note: differs from a same-day standalone-script
computation of 42,274.5 by 23.6 MWp, because this pipeline version aggregates the three
building-level parquets via `_join_buildings_to_grid_cells`'s spatial join instead of a
plain `cell`-id string match, correctly excluding ~4,565 buildings whose id came from a
manifest this run's grid does not cover, rather than guessing their coordinates back from
the id). This is now the `earthpv atlas` CLI's recommended path (`--osm-solar` alongside
the pre-existing three `--sub400-*-cells` flags) and what `configs/aoi.yaml`'s Pakistan
`dashboard:` block embeds; see "Results-page house style" above for the page-shell side
of this change. `build_sub400_bracket_atlas` and its template are unchanged and still
work for anyone invoking the CLI without `--osm-solar`.

**Size is a confounder -- report `auc_within_size`.** Adoption rises with house size (mappers
report large houses packed with PV, small ones much less), so footprint area *alone* scores
~0.72. `auc_within_size` scores inside `_SIZE_BANDS` and n-weights, removing size as a
discriminator. It costs the classifier ~3 points (0.874 → 0.842). It used to cost the
segmentation raster ~3 points too (0.734 → 0.707 at 6 quadrats); at 9 quadrats segmentation
has so little unconditional skill left (median AUC **0.511**) that the within-size control
barely moves it further (→ 0.501) -- there is almost nothing left to remove. Quote the
conditional number as the imagery's contribution.

**Three invariants here.** (a) Skill must be read per quadrat, never pooled -- 4 of 9 are
industrial estates, 5 are not (Karachi coastal, Lahore, Sialkot, Mardan, Quetta), and they
are not one population; Mardan is the weakest fold measured so far (AUC 0.743) and the
first non-industrial, non-Rule-1 quadrat in the set, which reads as the estimate getting
more honest with more evidence rather than the method degrading. (b)
**Ranking transfers, absolute rates do not**: `rate_ratio` now spans **0.235–4.833** across
nine quadrats (was 0.47–1.89 at six -- the three new quadrats widened it, Quetta and Mardan
are the extremes), and the model predicts 0.137 for residential Lahore where truth is
0.301. A per-stratum intercept is required before publishing any adoption rate or capacity
from it. (c) **Rule-1 complete requires the mapper's own completeness declaration** (every
visible panel mapped). Four quadrats carried it as of 2026-07-29 --
`karachi_coast_calib_700m` (2026-07-26, the first), `sialkot_calib_1km`, `mardan_calib_1km`,
and `quetta_calib_1km` (all 2026-07-29, owner-mapped, registered in
`docs/issues/pakistan-calibration-boxes.md`) -- so these were the only quadrats whose
negatives are trustworthy and the only ones where a low score cannot be blamed on missing
labels. None had a separately recorded independent second-mapper sweep; the owner's own
declaration is what "Rule-1 complete" means in this repo, per the `karachi_coast_calib_700m`
precedent. **As of 2026-08-05 all seventeen quadrats carry Rule-1: the owner declared
completeness for the whole current set.** Coverage went 3 of 12 to 17 of 17 in one step
(earlier the same day it had briefly dropped to three, when Rule-1 was withdrawn from Karachi
coastal as its boundary was extended -- that withdrawal is superseded). This is what makes
precision, false-positive rate and `base_rate` meaningful anywhere outside the old three, and
it is the first time the dense small-rooftop coastal, capital-territory and Sukkur regimes
have trustworthy negatives at all. Two caveats nothing in the data expresses: five of the
seventeen were first pulled from OSM the same day they were declared complete, and **no
quadrat in this repo has a recorded independent second-mapper sweep** (true since the first
one, not new) -- so these negatives are owner-attested, which is a real standard of evidence
but not an independently verified one.
**Rule-1 does not carry forward to new ground automatically -- it must be re-asserted, and
here it was.** Multan was extended the same day, after the blanket declaration (1 km² →
3.92 km², `multan_calib_3p92km2`, 40 → 164 installations, 0 lost). Rule-1 was initially
withheld (the declaration covered the boundaries that existed when it was made, and the
added 2.92 km² was ground the owner had not yet looked at), then the owner explicitly
declared Rule-1 for the extended area the same day, so it now reads `rule1_complete: yes`
like the other sixteen. The general rule for the *next* extension is unchanged: never infer
Rule-1 from a predecessor's declaration, always re-assert it explicitly.
**Rule-1 is epoch-relative and that qualification is load-bearing** (owner, 2026-08-05):
mapping is done against OSM's background imagery (Esri/Bing/Maxar), whose capture date does
not match the Sentinel-2 composite and is generally older, so the freshest installations
cannot be mapped at all. Rule-1 certifies completeness *as of the mapping imagery* and only
becomes a statement about the model's own epoch once contemporaneous imagery is acquired and
swept. Known bias directions: **precision is a lower bound** (a correct detection of
unmapped-but-real PV scores as a false positive), **`base_rate` a lower bound** and therefore
**`rate_ratio` an upper bound**, while recall over mapped installations is unaffected (it only
divides by labels that exist). The magnitude is measurable without new mapping via
`scripts/fraction_stale_label_audit.py` (same checkpoint, two epochs): pooled over 13 quadrats
it is only 5.8% of apparent false positives (precision 0.435 → 0.450), but that pooled figure
is dominated by industrial quadrats with large FP pixel counts, and **per quadrat it dominates
exactly where the sub-400 m² work lives** -- 68.4% in `karachi_coast` (0.570 → 0.807), 23.7%
in Quetta, 11.7% in Lahore. `results/calibration_quadrats.csv` now carries `imagery_layer` /
`imagery_date` columns for this; they are **empty for all seventeen**, which is why the
per-quadrat magnitude is unknown rather than merely unstated
(`docs/issues/calibration-imagery-dating.md`). **All three new boxes are now folded into the
roof-classifier's LOQO training/eval and the fraction-head quadrat table above** (re-run
2026-07-29 -- `roofclf.discover_quadrats` auto-globs every `*_calib_*_boundary.geojson`
with a matching mapped-solar file, so a bare `earthpv roof-classifier` picked up all nine
with no `--quadrat` flag needed). `karachi_coast_calib_700m` was the hardest and most
diagnostic of the four: median installation 86 m², 98.8% below the detection floor, and
there the segmentation raster scores **exactly 0.500** and predicts **0.0 m² of PV against
13,964 m² mapped** -- all measured on the retired 0.49 km² boundary, so these figures now
describe `data/labels/retired/karachi_coast_calib_700m_*` rather than a current quadrat. **None of the quadrats record when their reference imagery was
captured** -- the mapping protocol asks for it but the field has never been filled in
(`docs/issues/calibration-imagery-dating.md`), so stale background imagery missing
recently-installed PV is an untested, plausible contributor to the documented
overestimation in low-base-rate quadrats, alongside the already-verified false-positive
mechanisms -- not yet measured either way. Quadrat file naming is size-agnostic
(`*_calib_*_boundary.geojson`,
newest dated `_overpass_solar*` pull wins) -- do not re-hardcode `_calib_1km_`.

**Quadrats are also shape-agnostic as of 2026-08-05: a boundary can be drawn in JOSM and
imported with `new_calibration_quadrat.py --geojson`, not only generated as a geodesic
square.** Every consumer already masked and rasterised the real geometry, so this was
mostly a matter of removing three ways it could fail *silently*, and those are the parts
worth not regressing. (a) `chips.quadrat_chips` and `roofclf.load_quadrat` read only
`geometry.iloc[0]` while every evaluation script reads all features
(`rio_mask(s, list(gs.geometry))`, `union_all()`) -- a multi-part hand-drawn boundary would
have trained on one piece and been scored on all of them. Both now go through
`roofclf.load_boundary`, the single normaliser: unions every feature, converts a **closed
`LineString` to a Polygon** (JOSM exports a closed way as a polygon only if it carries area
tags, and a LineString boundary rasterises to a one-pixel outline and matches zero
buildings -- zero supervision, no error), `make_valid`s a self-intersecting ring and drops
Z. (b) A boundary whose bbox exceeds one **2,240 m** chip (`CHIP_SIZE` 224 @ 10 m) used to
have the excess mapped ground fall outside every chip window and vanish;
`chips.quadrat_chip_centers` now tiles such a boundary across covering windows, logs the
covered share, and records `boundary_covered_frac` on every chip row. Verified that all 13
existing quadrats produce **byte-identical chip centres** under the new code path, so no
existing corpus changes. (c) `roofclf`'s seg/frac raster features looked up their cell by
`boundary.centroid`, which for a concave polygon can be outside it -- now
`representative_point()`, and it warns when the chosen cell does not cover the whole
boundary. `side_m` is written and exported only for actual squares (sqrt(area) of a drawn
shape is a dimension that does not exist); a drawn quadrat is named by geodesic area
(`..._calib_1p24km2`) and carries `shape: drawn` + `source_geojson`. Mapper-facing
instructions, including the close-the-way and ~2.2 km bbox constraints:
`docs/calibration-mapping-protocol.md`'s "Drawing the boundary in JOSM".

**First use of that path, same day: Box 1 (Lahore) was replaced by a drawn 6.61 km² boundary
(`lahore_calib_6p61km2`, from `data/labels/calibration_boundaries/DH5.geojson`), retiring the
1 km² square to `data/labels/retired/`.** It fully contains the old square, which is what
made the swap checkable: all 1,014 old installations are present in the new pull (0 lost),
and the added 5.61 km² is mapped at 831 installations/km² against the core's 1,034, so it is
an extension rather than a dilution with unmapped ground. Now 5,688 installations, 13,500
buildings, base rate 25.4% (was 30.1%), median 29.0 m², 99.0% sub-400 m², packing 6.8 m --
**the largest sub-400 m² ground-truth population in the project**, 5,631 sub-floor
installations against 5,688 for all twelve other quadrats combined. Still not Rule-1.
Three consequences worth carrying:
- **A non-empty Overpass truncation mode exists and nearly poisoned this box.** A mirror
  returned HTTP 200, valid JSON, **no `remark`**, and a partial element list: the first pull
  wrote **68** installations where the answer is ~5,700, and would have been accepted. Four
  consecutive raw queries of the same bbox gave 5,983/5,983/5,983/**72**, so it is
  intermittent and one query is untrustworthy in either direction. `_run_query` now rejects
  any `remark`ed response (`OverpassTruncated`) and fails over; the quadrat script
  cross-checks each pull against the **max** of three confirming queries (max, because
  truncation only loses elements) and retries below 98%. But what actually caught it was the
  containment invariant -- **prefer replacing a quadrat by extension**, so "cannot hold fewer
  than the box it contains" is available as a check.
- **Every model score for Lahore is now stale and is deliberately NOT half-refreshed**:
  `roofclf` LOQO folds + `model_full.json`, `results/fraction_quadrat_validation*.csv`, and
  `results/quadrat_detection_correlations.csv` were all measured on the retired boundary.
  Regenerating the correlations was tried and reverted -- it silently produced a *mixture*,
  because `quadrat_correlations.py` joins the folds table on `label` ("lahore", so new ground
  truth paired with old scores at unchanged n, r moved) and the fraction table on the full
  stem (no match, so n dropped 12→11). It now prints which quadrats each model-side join
  failed to cover and when that table was written; that also exposed a pre-existing silent
  gap, the 9-quadrat folds table missing all four post-2026-07-30 boxes.
- Hardcoded references had to move with it or they fail silently/loudly:
  `atlas.py::CALIBRATION_BOXES` (a missing stem is skipped without error, so the box would
  have vanished from the atlas), `configs/aoi.yaml`'s per-box AOI key + bbox (composites
  cached under the old key cover only the old core and are orphaned, not wrong), and three
  scripts' paths (`glint_validate_calibration_box.py`'s `LABELS_FILE` constant, plus
  `pv_step_signal.py`/`pv_ts_cube.py` usage examples).

`roofclf.packing_density` (added 2026-07-29) reports each quadrat's median distance
from a sub-400 m² installation to its nearest neighbour of any size -- a cheap,
model-free number that correlates r=0.70–0.82 with `exp_scale`/`auc_within_size`
across all nine quadrats, and now a standing column (`nn_median_m`) in every
`evaluate()` fold report. See `docs/methods/density.md`'s "Packing distance" section.

**The density↔detection-quality correlation was recomputed and documented 2026-08-04,
and it is two artifacts rather than one landscape effect** --
`scripts/quadrat_correlations.py` / `pixi run quadrat-correlations` →
`results/quadrat_detection_correlations.csv`, written up in `docs/methods/density.md`'s
"Density and detection quality" section. It deliberately separates **discrimination**
(`*_auc*`, scale-free) from **bias** (`scale`, `rate_ratio`), since a quadrat can rank
perfectly and still be 3x high. Two findings, both of which sharpen claims already made
in this file:
- **Discrimination is installation size, not density.** `median_install_m2` vs
  segmentation AUC is **r=0.991** (n=9) -- the 400 m² training floor doing exactly what
  it says. Every density measure's correlation with segmentation skill dies on
  controlling for size: packing distance 0.819 → **-0.155** partial, installations/km²
  rho -0.915 → **+0.201**. Dense quadrats score badly because they are dense in *small*
  arrays. The one survivor is packing distance vs the **fraction head's** AUC (0.931 →
  **0.809** partial), the real 10 m pixel-mixing effect. So `packing_density` is a proxy
  for size regime first, mixing second -- it stays useful, but do not describe it as
  measuring density's effect.
- **`base_rate` vs `rate_ratio` (rho=-0.950, n=9) is arithmetic.** `pred_rate` is
  unrelated to truth (r=-0.167, p=0.67) and nearly flat (mean 0.137, CV 0.31) while
  `base_rate` spans 3.0–30.1% (CV 0.62), so `rate_ratio ≈ const/base_rate`: substituting
  the mean predicted rate reproduces it at r=0.969, median relative error 8.9%, log-log
  slope **-1.133** (-1.0 = purely mechanical). The "~12% crossing point" is just where
  the flat predicted rate meets truth (**12.3%**, next to the training quadrats' own mean
  12.8%) -- refit elsewhere and it moves, having learned nothing. This is confirmation
  that the missing **per-stratum intercept** is the whole problem, not a new obstacle.
  Mardan is the lone misfit (`pred_rate` 0.032), consistent with it being the weakest
  fold anyway. One non-mechanical bias result worth keeping: `frac_sub400` vs the
  fraction head's predicted/true area, r=-0.945 / **-0.691** partial (n=12) -- sub-400 m²
  blindness measured directly. n is 7-13 per pair over 72 pairs, so no single p-value
  carries weight; both headline results were pre-registered by earlier claims and have a
  mechanism predicting sign and magnitude in advance.

### Plausibility gate (`plausibility.py`, `earthpv check-density`)

The leads product has a human on every candidate; the capacity atlas has nobody, so a
false-positive mode that survives `p_real` reaches the headline number silently. Two
per-region checks, both from artifacts `density` already wrote: **ground-mount:rooftop
capacity ratio** (bare ground, riverbed, salt flat, rock and snow read bright and nothing
constrains them to a plausible host) and **single-cell concentration** (one 0.1° cell over
25% of a region means that region's total is one blob, not a population). Both need
`mwp_ground >= 50` so a tiny region's ratio is not noise. Exit 1 = a region failed, 2 =
`density` has not run. **Run it between `density` and publishing** -- the docs CI *cannot*,
since `data/` is gitignored, so this gate is only as good as the operator invoking it.

Acceptance test for any change here: the pre-fix Pakistan output (18.3 GWp,
Gilgit-Baltistan 166 MWp against 0.8 MWp of rooftop) must **fail** (4 of 7 provinces did),
the current one must pass.

### Invariants that prevent tiling artifacts (do not regress)

Naive sliding-window inference produced a regular grid of false positives. Two fixes must
stay in place:
- **Positive chips are jittered** (`chips.py::sample_chip_centers`, ±900 m) so the PV array
  is *not* centered in the frame. Without jitter the model learns a center bias and fires
  once per window at inference → a grid at the stride spacing. Diagnostic: nearest-neighbor
  distance between detections spikes at the window stride.
- **`infer.py` overlap-adds windows with a 2D Hann taper** into one seamless raster per
  cell, with a **stride that is not a multiple of the 16 px ViT patch size** (currently 104)
  so patch-edge effects decorrelate between neighbors.

### Documentation site

`mkdocs.yml` + `docs/` build the MkDocs Material site published to GitHub Pages by
`.github/workflows/docs.yml` on every push to `main` that touches docs, results or the
figure script. **Every figure and embedded interactive page under `docs/assets/` is
generated** by `scripts/build_docs_figures.py` (`pixi run docs-figures`), which reads its
numbers from tracked files (`results/*.csv`, the atlas HTML's embedded JSON, the
calibration YAML) so the site cannot drift from them -- edit the sources, not the SVGs.
Charts are written twice (`x.svg` / `x.dark.svg`) for Material's `#only-light` /
`#only-dark` suffixes. The logo variants and favicon are derived from
`docs/assets/earthpv-logo.png` (a black mark on transparency, invisible on the dark
header) by the same script. Local preview:
`pixi run docs-figures && pixi run -e docs docs-serve`. The build runs `--strict`, so a
broken internal link fails CI. Docs prose in this repo avoids em dashes and emoji.

**The site chrome is the same design system as the pages it embeds (2026-08-03).** The
site used to be navy-and-white Material with a warm-amber "night lights" atlas pasted
into an iframe in the middle of it; now `docs/assets/stylesheets/extra.css` defines the
atlas's own tokens as `--pv-*` (a verbatim copy of `templates/pv_evidence_atlas.html`'s
values, kept in sync by eye for the reason given under "Results-page house style") and
maps them onto Material's variables, in both schemes. `theme.font: false` plus
`--md-text-font`/`--md-code-font` put both sides on the same system-ui/ui-monospace
stacks. Consequences worth knowing before editing any of it:

- **Both dark modes have to agree at runtime, not just on paper.** Material's toggle
  writes `data-md-color-scheme` on `<body>`; each result page has its own toggle reading
  `data-theme` off its own `<html>`, defaulting to `prefers-color-scheme`. They desync
  the moment a reader uses the site toggle without changing the OS preference.
  `docs/assets/javascripts/embed-theme.js` drives the frames from the site's scheme; it
  **clicks each frame's `#themeBtn`** rather than setting the attribute, because the
  atlas pages recolour their SVG map inside that click handler and only the pose page
  observes the attribute. Verified 2026-08-03 by rendering a slate-scheme page under a
  light-OS Firefox profile.
- **`color-scheme` alone does not fix the frame's scrollbar** (measured, Firefox): it
  computes correctly on the frame root and the scrollbar still paints light down the
  side of the panel. `scrollbar-color` is what works. Both are declared in the
  templates *and* set by the sync script, since the docs site copies whatever artifact
  is on disk and the built `results/*.html` predate the template change.
- Admonitions keep Material's per-type icon and title tint but lose the coloured ring
  (the atlas never rings a card in a second hue). That rule needs a `[class]`
  specificity bump to outrank Material's own `.md-typeset .admonition.info`.
- `scripts/build_docs_figures.py`'s `LIGHT`/`DARK` themes carry the same values, so the
  generated charts sit on the page surface rather than on their own near-white canvas.
  Series slots are now the atlas's three hues (amber / blue / aqua), slot 1 primary.
- `docs/glint_geometry.svg` is hand-drawn, not generated, and switches on
  `prefers-color-scheme` internally rather than being an `#only-light`/`#only-dark`
  pair -- so it is the one asset that still follows the OS instead of the site toggle.
  Recoloured, not split; splitting means hand-maintaining two copies.

`scripts/screenshot_pages.py` (`pixi run docs-screenshots`) renders the interactive HTML
pages to PNG for the README, which cannot embed an iframe. It is **not** in CI because
it needs a browser. Pass output stems as arguments to re-render a subset. **Snap-packaged
Firefox can only read a non-hidden directory under `$HOME`** -- `/tmp`, the external drive
holding this repo, and even `~/.cache` all fail, and the failure mode is a silent hang
rather than an error, so the script stages pages in `~/earthpv-screenshots/` and sets the
subprocess cwd there. It also pins `ui.systemUsesDarkTheme` in a throwaway profile: the
committed PNGs are the dark rendering, and without the pin the output silently follows
the operator's desktop theme.

### National dashboards (bundle CLI kept, no longer used by the site)

Added 2026-07-31: `earthpv dashboard --aoi <name>` combines an AOI's existing,
independently-built HTML pages (the sub-400 m² bracket atlas, a glint panel-pose
survey) into one tabbed page, rather than any of them being recomputed. It is a
thin shell for a reason -- each source page already carries its own `:root`
CSS-variable palette, theme toggle and `prefers-color-scheme` handling, and merging
their markup into one DOM would collide on those variable names; instead
`src/earthpv/dashboard.py`'s `build_national_dashboard` copies each panel's HTML
into a self-contained bundle directory (`results/<aoi>_pv_dashboard/{index.html,
<panel-key>.html}`) and wires them behind lazy-loaded `<iframe>`s, so every panel
keeps working exactly as it does standalone. The panel list is config, not code:
each AOI's `dashboard:` block in `configs/aoi.yaml` (title + an ordered
`{key, label, sublabel, src, note}` list) is what `dashboard --aoi` reads.
`src/earthpv/pose.py::build_pose_survey_page` is the same pull-out applied
to the panel-pose page itself (previously a one-off script,
`scripts/build_pv_pose_country2000.py` is now a thin wrapper around it), so a
second country's glint survey doesn't need its own copy of that template either --
that part is unrelated to the dashboard bundle and still used.

**Retired from the docs site 2026-08-03.** The site's own "Dashboards" nav section
(`docs/dashboards/index.md`, `docs/dashboards/pakistan.md`, a tab-switching iframe
page) was merged into **Results**, which now just lists direct links to each
standalone page (`docs/results/capacity.md`, `results/growth.md`,
`results/pv-pose.md`, `results/leads.md`) -- no iframe, no bundle directory, no
config-driven generator, one page per artifact. Keeping the bundle in sync (the
directory copy, the `INTERACTIVE_DIRS` sync step, the full-bleed page shell) turned
out to cost more than the plain pages it replaced now cost. `earthpv dashboard`,
`dashboard.py`, `configs/aoi.yaml`'s per-AOI `dashboard:` blocks, and
`build_docs_figures.py::sync_interactive_dirs`/`INTERACTIVE_DIRS` all still exist
and still work -- nothing was deleted -- they are simply not part of the current
site build. See `docs/reproduce.md`'s "Step 7: publish it on this site" for the
pattern that replaced it (add the new page's source to `INTERACTIVE`, write a short
hand-authored `docs/results/<name>.md`, add a nav entry).

### Results-page house style (default for reporting and presentation)

As of 2026-08-01, this interactive HTML "night lights" style is the **default** for any
new results/presentation page -- not just the density atlas. Reference implementations:
`results/pakistan_pv_sub400_bracket_atlas.html` introduced it; `results/
pakistan_pv_evidence_overview.html` (built by `scripts/
build_pakistan_pv_evidence_overview.py`) is currently the tightest example of the full
pattern: an eyebrow + H1 + lede header, a KPI strip of 4-5 headline numbers, a tab
switcher over a dark glowing choropleth map with a hero stat beside it, and
`<details class="xdetails">` "Background" sections below the fold carrying methodology
and caveats instead of a wall of prose up front. Every page supports a light theme via
`:root[data-theme]` + `prefers-color-scheme`, toggled by the same `#themeBtn` script.
This supersedes static PNG/PDF figures (e.g. `pakistan_pv_density_scientific.png/pdf`)
as the default for anything meant to be read interactively; static figures stay
appropriate only for the docs site's embedded `<img>`s (`scripts/build_docs_figures.py`)
and anywhere print/export is the actual requirement.

The CSS design system (palette, `.kpi`/`.card`/`.tab`/`.xdetails` classes, the choropleth
SVG helpers) originated in `build_pakistan_pv_overview.py` as a standalone-script proof
of concept. `src/earthpv/templates/pv_evidence_atlas.html` (below) is now a second,
independent copy of the same system inside the actual pipeline -- the two are not sliced
from one shared source, since a static `.html` template has no mechanism to slice from a
`.py` file at pipeline run time the way `build_pakistan_pv_evidence_overview.py` slices
CSS from its sibling script. Keep the two in sync by eye when the palette changes; a
`third` reuse point (a real templating layer shared between the standalone scripts and
`src/earthpv/templates/`) is worth building once keeping them in sync by eye actually
starts to hurt, not before. A new **standalone script** still either slices the CSS
wholesale -- `_slice`/`_shared_fragments` in `build_pakistan_pv_evidence_overview.py` is
the pattern to copy, matched by exact string markers that fail loudly rather than
silently drift -- or copies the `<style>` block outright. A section that deliberately
diverges between pages should be written directly in the new page instead of forced
through a shared slice: `build_pakistan_pv_evidence_overview.py`'s
`POSE_SECTION_HTML`/`POSE_SECTION_JS` stopped slicing the sibling's orientation section
the moment its chart selection and layout diverged (fewer charts, different placement).

**The atlas is generated by the pipeline itself, not only by standalone scripts.**
`src/earthpv/atlas.py::build_evidence_atlas` + `src/earthpv/templates/
pv_evidence_atlas.html` is the pipeline-native version of this style: tiers by
**standard of proof** rather than by point estimate (Verified / Best estimate -- see
"Sub-400 m² instruments" below for what each tier means and how the numbers were
arrived at), promoted 2026-08-01 to the `earthpv atlas` CLI's recommended path,
superseding `build_sub400_bracket_atlas`'s older Low/Central/High/All-PV framing (kept,
undocumented as the default, for AOIs that only have the older bracket inputs). Invoke it
with `--sub400-low-cells`/`--sub400-central-cells` (the bracket atlas's own three
`--sub400-{low,central,high}-cells` flags still exist for that older path, but the
evidence atlas ignores `--sub400-high-cells` now -- see below), plus
`--osm-solar <national OSM/Overpass solar parquet>` -- passing that flag is what selects
the evidence atlas over the bracket atlas; the run's own `candidates.parquet` is found
automatically. `density`'s own end-of-run auto-atlas-call deliberately still writes the
plain `build_atlas` (grid/regions only) rather than guessing at these extra paths -- see
the comment above that call in `density.py` for why guessing would be unsafe. Regenerate
the atlas explicitly once the OSM pull, `earthpv roof-classifier`, and the
`sub400_capacity.py`/`roofclf_capacity.py` building parquets exist for an AOI;
`configs/aoi.yaml`'s Pakistan `dashboard:` block already points its `capacity` panel at
the regenerated atlas. **Its canonical location is `docs/assets/interactive/pakistan_
evidence_atlas.html` (2026-08-06), not `results/`** -- this is the project's primary
output, so the docs site and the README screenshot read it directly with no separate
`results/` original to sync from; `earthpv atlas --out` should point there directly.

**A third tier, Ceiling, was removed 2026-08-06 at the owner's explicit request.**
Ceiling combined roofclf flagged nationwide at a flat 0.5 precision weight
(`roofclf_capacity.incremental_capacity`, unrestricted, explicitly uncalibrated) with
every known large-PV installation. The 2026-08-05 17-quadrat roofclf refit (see "roofclf
national deployment" below) lowered the deployment threshold from 0.3064 to 0.2407,
which roughly doubled this tier with no accompanying validation (small-PV component
37,173 -> 79,221 MWp, Ceiling total 42,251 -> 84,298 MWp) -- it had stopped being a
meaningful bound. `build_evidence_atlas` no longer takes a `high_buildings_path`
argument; `roofclf_capacity.incremental_capacity` and `--sub400-high-cells` are
unaffected and still serve `build_sub400_bracket_atlas`'s own High view, a separate,
already-superseded atlas type this change does not touch.

**A real double-counting gap between the sub-400 m² instrument and hand-mapped OSM was
found and fixed 2026-08-06.** `sub400_capacity.domain_restricted_capacity`/
`domain_restricted_and_gate_capacity` deduplicate roofclf/SPPI-flagged buildings against
`candidates.parquet` (existing segmentation candidates, via `new_lead_mask` + a 400 m²
contamination filter) -- but until this fix, NOT against the national OSM solar pull.
`score_buildings_national` scores every VIDA building with no OSM awareness at all, so a
building OSM had already mapped but segmentation missed entirely (no candidate anywhere
near it, so it flows into the atlas's `osm_mwp_unmatched`) would very plausibly also get
flagged by roofclf, since it is genuinely real PV -- and get counted a second time in
`small_central`/`small_low`. Measured directly against the then-current outputs before
fixing it: 26,839/975,785 buildings (2.8%, 437.6 of 13,416.4 MWp, 3.3%) in `small_central`
and 20,418/683,523 (3.0%, 343.2 of 9,006.4 MWp, 3.8%) in `small_low` sat within 30 m of an
OSM feature. Both functions now take an optional `osm_solar_path` -- when given, a second
`new_lead_mask` check against it is ANDed with the existing segmentation-candidate check
before the contamination filter, and `summary["n_excluded_near_osm"]`/
`summary["osm_dedup_applied"]` record how many buildings that step actually dropped so the
fix's effect is auditable, not just asserted. It is optional rather than required only
because some non-evidence-atlas callers may not have a national OSM pull handy; every call
feeding the evidence atlas passes it, and the CLI/callers that don't were not changed.
Rebuilt `data/sub400_20260806/sub400_{central,low}.parquet` with it: central
13,416.4 -> **12,978.8 MWp** (36,035 buildings excluded near OSM), low
9,006.4 -> **8,663.2 MWp** (26,007 excluded) -- exactly matching the pre-fix measurement.
Evidence atlas republished: Verified 14,040.2 -> **13,697.1 MWp**, Best estimate
21,792.4 -> **21,354.8 MWp**. Old atlas backed up to
`results/pakistan_pv_evidence_atlas_PRE_osm_dedup_fix_20260806_backup.html`.

### Small-PV JOSM validation leads (`pixi run small-pv-leads`)

`scripts/build_small_pv_josm_leads.py`, added 2026-08-01 as a **regular, repeatable
task** (`pixi run small-pv-leads` in `pixi.toml`, alongside `docs-figures`) rather than
a one-off script -- re-run it whenever national roofclf/SPPI scoring or the OSM solar
pull is refreshed. It writes three GeoJSON files for manual review in JOSM, answering a
narrower question than any capacity number: does the sub-400 m² instrument actually
point at real, previously unmapped installations when a human looks at the imagery?

- `results/pakistan_small_pv_josm_leads.geojson` -- the **AND-gate** population
  (roofclf AND SPPI both agree, `sub400_low_incremental_buildings.parquet`, the
  evidence atlas's Verified tier).
- `results/pakistan_small_pv_josm_leads_roofclf_only.geojson` -- **roofclf alone**
  (`sub400_central_incremental_buildings.parquet`, the Best-estimate tier).
- `results/pakistan_small_pv_josm_leads_sppi_only.geojson` -- **SPPI alone**, gated at
  its own pooled precision-targeted threshold (`sppi.pooled_precision_threshold`, same
  93-cell domain and incremental/contamination filters as the other two) with no
  roofclf condition -- derived fresh by the script each run, not a pre-built artifact,
  since SPPI was never adopted as its own deployable capacity instrument in this
  project (see the SPPI cross-validation notes above). Its `est_kwp` is explicitly
  **uncalibrated** (raw area × the module constant, no measured precision weight).

All three exclude buildings within 30 m of an existing OSM solar feature
(`export.filter_new_leads`) so the files test genuinely untested leads rather than
re-confirming known installations, rank by the model's own confidence score (recovered
for the two pre-built populations by an exact-geometry join back to the per-cell
probability parquets, not a proxy like roof area -- an earlier, roof-area-ranked
revision of this file was replaced the same day after a first human-reviewed batch came
back "promising but still lots of false positives"), and cap at 6 leads per 0.1° cell so
the sample spans the checked area instead of clustering into whichever cell scores
highest. All three exist specifically so a human can compare their false-positive rates
against each other in JOSM.

**A specific false-positive mode found by that comparison, 2026-08-01**: cell
`0061_0012`'s roofclf-only leads are very bright white buildings -- and checking them
against the AND-gate threshold shows **SPPI does not catch this one**: all six
buildings score `sppi` 0.05–0.10, comfortably above the AND-gate's −0.0144 cutoff, so
they pass both detectors together. This is a shared blind spot, not something
roofclf-vs-SPPI disagreement resolves -- worth targeted hard-negative labeling (bright
non-PV roofs specifically) rather than expecting the AND-gate to fix it.

**A known, measured limitation surfaced by this exercise, not a bug**: in JOSM, a
flagged building's polygon sometimes sits *among* several real installations rather
than exactly on the one carrying the panels. This matches `roofclf.packing_density`'s
own finding that the densest quadrats (Karachi coastal, Quetta, Sialkot) have a median
15–17 m spacing between neighboring small installations -- at or below Sentinel-2's
10 m pixel size, so per-building attribution is a real sensor-resolution ceiling in
those areas, not a training defect. Not yet addressed in the leads file: flagging
leads whose nearest neighbor sits inside that ~15–20 m band as "dense cluster, exact
attribution uncertain" instead of pointing at one specific polygon (discussed, not yet
implemented as of this writing).

### Rooftop potential & saturation atlas (`earthpv atlas --potential-buildings`)

A forward-looking counterpart to everything above: not "how much PV is already there,"
but where large, currently-uncovered roofs and high modelled irradiance overlap -- a
siting signal for *future* rooftop solar, plus a saturation view of where PV adoption is
already dense vs. sparse. `potential.py::large_roof_buildings` pulls every VIDA building
nationally with `roof_area_m2 >= 200` from `roofclf.score_buildings_national`'s existing
per-cell output, using **only that table's footprint geometry, never `p_roofclf`/
`sppi`** -- this is what keeps the feature outside every calibration/precision problem
documented in "Sub-400 m² instruments" above, all of which arise from converting a
PV-*presence probability* into capacity, which this never does. `atlas.py::
build_potential_atlas` subtracts each cell's `pv_area_exp_roof_m2` (upper-leaning, so a
roof with any sub-threshold signal is conservatively excluded from "opportunity") to get
an uncovered large-roof area, converts it to capacity at the usual module constant, then
to annual energy via a coarse, cached PVGIS-modelled specific-yield probe grid
(`pv_capacity.py::grid_specific_yield`/`interpolate_yield`, reusing
`specific_yield_kwh_per_kwp` unchanged; interpolation is plain inverse-distance-weighted
numpy, since `scipy` is not a project dependency). 200 m² (not the segmentation model's
400 m² detection floor) is a deliberate choice reaching further into the realistic
rooftop-opportunity space; the 200–400 m² slice specifically gets no discriminating
signal from the segmentation-based subtraction (trained with everything below
`chips.MIN_PV_AREA` burned as `ignore`), so it reads as almost entirely uncovered
regardless of ground truth -- expected, documented in `docs/methods/density.md`, not a
bug. The Saturation tab adds no new computation: it's `pv_ratio_det`/`pv_ratio_exp`,
already computed unconditionally by `density.py::_ratios`, given its own choropleth.
`scripts/build_potential_leads.py` (`pixi run potential-leads`) is the leads-generation
counterpart, same shape as `build_small_pv_josm_leads.py`: ranks individual roofs by
size × modelled yield, drops anything near an existing candidate or OSM solar feature,
caps per cell for a human to spot-check before treating any of it as validated.

## Conventions & gotchas

- **GPU:** the target card is a **GTX 1060 (Pascal, sm_61)** → PyTorch must be **cu126**
  wheels (CUDA 13 dropped Pascal). Pinned in `pixi.toml`.
- **`data/` is gitignored** and lives on the external drive
  (`/run/media/tobi/aidisc/earthpv/data/`): `chips/`, `composites/`, `models/`,
  `predictions/`. Files there are invisible to git/IDE explorers that hide ignored files.
- **`row.mask` / `row.image` on a pandas row:** use bracket access (`row["mask"]`) -- `.mask`
  resolves to the `Series.mask` method, a bug hit more than once here.
- **Training positive threshold** is `MIN_PV_AREA` in `chips.py` (arrays below it are burned
  as `ignore = -1`, not negatives). Changing it requires rebuilding chips and retraining.
- **Geographic val split** uses `val_tiles` in `configs/aoi.yaml`; these must be MGRS tiles
  the `source_region` actually downloaded, or the val set ends up empty (datamodule then
  falls back to a random 20% split).
- **Areas are geodesic** (`labels.geodesic_area_m2`), never `.area` on lat/lon geometries.
- Long GPU/network stages are run detached (`nohup … &`) and polled; the rich progress bar
  does not flush cleanly to a redirected log, so watch checkpoint files / cell counts to
  gauge progress rather than parsing the log.
- **`nohup setsid` alone does not survive a session logout on this machine.** systemd-logind
  kills a whole session's cgroup (all processes in it, `setsid` or not) when the session ends
  unless lingering is enabled. Run `loginctl show-user "$USER" | grep Linger` -- if `Linger=no`,
  `loginctl enable-linger "$USER"` once (no sudo needed for your own account) before launching
  anything multi-hour, or it can silently die with no error/traceback partway through.
