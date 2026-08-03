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
detection at all, and — measured, 2026-07-26 — the `density` stage does **not** rescue them
either: the whole sub-500 m² class is 8.2 MWp of the Pakistan total (~0.2%), and on the one
Rule-1-complete quadrat the segmentation raster predicts *zero* PV area (AUC 0.500). Every
published capacity figure is therefore scoped **≥ 400 m²**, while Germany's complete MaStR
register puts 72.6% of rooftop capacity in units ≤100 kWp (~≤555 m² of module). Closing that
gap is the open front: see "Sub-400 m² instruments" below. Trained on Germany, inferred on
Punjab, Pakistan. Read
`README.md` for the narrative and the current result numbers.

## Environments & commands

Managed with **pixi**. Two environments share one solve-group, plus an independent docs env:
- `default` — the data pipeline (DuckDB, geopandas, rasterio, odc-stac). No PyTorch.
- `ml` — adds `torch`/`torchvision` (**cu126 wheels**) and `terratorch`.
- `docs` — mkdocs-material only (`no-default-feature`), so a docs edit never waits on a solve.

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
For capacity: `density → check-density` (the latter gates the numbers, see below).

**There is no test suite and no lint task wired.** Ruff is configured (line-length 100)
but run manually. The practical "does it work" check is a small end-to-end run:
`chips --aoi germany --limit 500` → `train --smoke` → `evaluate`.

## Architecture

### Data reuse — the load-bearing design decision

To avoid re-downloading terabytes, imagery and labels are **reused from a sibling
`rooftopsenti` project** on the same drive, pointed at by `local_root` in
`configs/aoi.yaml` and each AOI's `source_region`. `src/earthpv/local_source.py` reads
that project's per-MGRS-tile Sentinel-2 composite COGs (`CompositeIndex`) and its
OSM/Overture label + building parquets (`load_solar_labels`, `load_buildings`). The
Overture (`overture.py`) and Planetary-Computer (`imagery.py`) fetchers are **fallbacks**
for AOIs with no local artifacts. **Direct Overture S3 queries time out from this machine
— prefer the local/VIDA paths.**

Consequence: an AOI is only fully usable where the `source_region` actually has composites.
`germany` uses `germany_500`; `punjab` uses `pakistan_500` for *buildings* but that region's
composites cover **Balochistan, not Punjab** — so Punjab imagery is built on demand by the
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
prints the runbook. **New AOIs must carry `division.iso3`** — `buildings._iso3_for`
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
(confidence × building prior). Footprints come from `buildings.py::load_dense_buildings` —
**VIDA Open Buildings** (Google+Microsoft, imagery-derived, includes small/unmapped roofs),
fetched windowed-and-cached per AOI; the local Overture ≥500 m² set is the fallback.
`export.py` sorts by `rank_score` and writes GeoParquet/GeoJSON + a MapRoulette challenge.
This candidate-polygon path is the > 400 m² individual-detection product; it is not
extended down to smaller installations — `density.py` covers those instead (see below).

### Density stage (aggregation into PyPSA-ready shapes)

`density.py` reuses the same per-cell probability rasters (no GPU, no retraining) to
report *aggregate* PV capacity per building/grid-cell/region rather than individual
candidate polygons. It aggregates the **≥ 400 m²** population into PyPSA-ready shapes; it is
*not* the answer below that floor (see the measured blindness above). It reports three area
metrics per building: `*_det` (thresholded candidate polygons on the footprint — the
precision-honest floor, blind to sub-threshold/sub-400 m² signal), `*_exp`
(probability-weighted area integrating sub-threshold signal, an upper-leaning ceiling),
and `*_cal` (`*_det` re-weighted by a measured P(real | size, glint) from
`configs/calibration/<aoi>_candidate_precision.yaml` — the headline capacity number).
See README's "PV density per building" section for the full metric derivation.

**Area → capacity uses two constants, never one.** A rooftop detection is ~module area
(`DEFAULT_KWP_PER_M2_MODULE = 0.18`); a ground-mount detection is *site* area, because the
ground-PV training labels are OSM `power=plant` perimeters, so only the ground-cover ratio
is module (`DEFAULT_KWP_PER_M2_LAND = 0.07`). Both live in `capacity_calibration.py` with
lognormal priors (`kwp_draws`), so the conversion propagates into the credible intervals
instead of being treated as exact. Every all-PV estimator is split by `placement` before
conversion (`_ratios`, `_composed_mwp_draws`); the roof-scope ones are footprint
intersections and convert at the module constant throughout. Applying the module constant
to site area overstates ground-mount by 2-3x — that regression is what the split prevents.

`density` also **excludes candidates over `postprocess.MAX_CANDIDATE_M2` (100k m²)** from
capacity. `polygonize_chips` merges every touching thresholded pixel with no upper bound,
so a connected sheet of false positives becomes one multi-km² "installation" with
`confidence` 1.0 (it is the *max* over the polygon). On the Pakistan country run 167 such
candidates carried 47% of all candidate area. `postprocess` only flags them (`oversize`);
they stay in the leads product, where a human validates every candidate. Because cell
partials cache the per-building/`*_roof` columns, the filter only reaches those on a
`--force` re-run — `meta.json`'s `oversize_stale_partials` records when it did not, and
the candidate-population columns (`_CAND_COLS`) are rederived from the candidate frame
every run by `candidate_cell_totals` precisely so they never go stale.

### Sub-400 m² instruments (the recall correction cannot reach here)

`est_mwp_rc` scales up what was detected, so `1/recall × ~0 ≈ 0`. Measured: the whole
sub-500 m² class is **8.2 MWp** of the Pakistan estimate (~0.2% of rooftop), while one
fully-mapped km² of residential Lahore holds **3.3× more sub-100 m² PV area than the model
finds nationally**. Germany's MaStR (legally complete) puts **72.6% of rooftop capacity in
units ≤100 kWp** (≈ ≤555 m² of module), so this is very likely the majority of the quantity
the rooftop headline claims to describe.

**All instruments below are rooftop/building-scoped — small ground-mounted installations
below 400 m² have no instrument at all, at any confidence level.** `roofclf` and SPPI are
both per-*building* classifiers (they score a VIDA footprint); the fraction head is the
only one of the three not tied to a building, but it still runs on the same segmentation
input trained with everything below `chips.MIN_PV_AREA` burned as `ignore`, so a small
free-standing ground array gets no more signal there than a small roof does. There is
no building footprint to hang a classifier off for ground-mount the way there is for
rooftop, so the partial mitigations below do not generalize to it even in principle —
this is a distinct, currently open gap, not a smaller version of the rooftop one. Two
instruments, both rooftop-only and both dropping the polygon:

- **Fraction-head expected area** — `density --fraction-prob-dir <run>/prob [--exp-scale k]`
  swaps the `*_exp` instrument from segmentation class probability to per-pixel PV coverage.
  Quadrat-measured predicted/true ratio in the *residential* quadrat: segmentation **0.023**
  vs fraction **0.520** (≈23× better); comparable in the four industrial quadrats. As of
  2026-07-29 the fraction run reached **full coverage** (4,463/4,463 cells,
  `exp_coverage_frac: 1.0`; inference had actually finished 2026-07-27, docs just lagged)
  and the national rooftop expected-area number moved 5.4 → 6.65 GWp (+23%), matching the
  quadrat-level direction. **Still not promoted to the published atlas** — that same full
  `--force` run failed `earthpv check-density` (Gilgit-Baltistan: 110 MWp ground-mount
  against 0.000 MWp rooftop), traced to a `density.py` regression in `no_building`
  candidate aggregation that is **confirmed** architecturally unrelated to the
  exp/fraction swap itself — an isolating segmentation-instrument rerun (2026-07-29
  23:07, same pre-existing candidates) reproduced the identical 0.000/109.982 MWp
  numbers — see `docs/issues/density-force-recompute-plausibility-fail.md`.
  `plausibility.py` now exempts Gilgit-Baltistan from check 1 specifically
  (`RATIO_CHECK_EXEMPT_REGIONS` — its real rooftop base rate is near zero, so the ratio
  is structurally uninformative there), so `check-density` passes again (0 fail, 3
  suspect) on both instruments. That unblocks the gate; it does **not** confirm the
  110 MWp ground-mount figure is correct — locating the exact cause in `density.py`/
  `postprocess.py`'s aggregation code is still open.
  **Retrain attempt, 2026-07-30: negative, not promoted.** `fraction_pakistan_v2`
  (8 of 9 quadrats oversampled 20x into the national corpus, `lahore_calib_1km` held
  out for validation) scored *worse* than production on every metric measured against
  Lahore's own ground truth (scale 0.520→0.197, correlation 0.136→0.070, AUC
  0.589→0.553) — training-from-scratch on the current recipe should not be assumed to
  transfer just because more real small-array labels were added. `fraction_pakistan_v1`
  remains the deployed checkpoint. See
  `docs/issues/roofclf-national-deployment-and-temporal-features.md`.
- **`roofclf.py` / `earthpv roof-classifier`** — per-building "does this roof carry PV?",
  trained on the exhaustively mapped quadrats (the only source where a no-PV building is a
  real negative). Updated 2026-07-29 to **9 quadrats, 22,044 buildings, 2,376 with PV**
  (added Sialkot, Mardan, Quetta). Leave-one-quadrat-out median AUC **0.874** (was 0.879 at
  6 quadrats), **0.842 conditional on roof-size band** (was 0.845), against the
  segmentation raster's conditional median, which **dropped from 0.707 to 0.501** — chance
  — now that 5 of 9 quadrats are non-industrial and segmentation scores ~0.50 in four of
  those five. Ablation set the default feature set: size-only 0.715, reflectance-only
  0.841, size+reflectance **0.874**; adding the seg/frac rasters as features now comes out
  roughly neutral on small roofs (0.856 → 0.858, a reversal of the old "hurts small roofs"
  reading, but small enough either way to be noise) — they stay off by default regardless,
  the case for including them was never strong. Two more candidate features tested
  2026-07-29, neither kept: epoch-jump (both a free reflectance-delta version and a
  probability-delta version needing a targeted `infer --index 1 --tiles` pass) and
  step-change (per-building aggregation of `pv_step_signal.py`'s pixel output, tested on
  5 of 9 quadrats) — see
  `docs/issues/roofclf-national-deployment-and-temporal-features.md` for why each failed
  (one quadrat crash, no effect, and a within-size-band confound respectively).
  **Deployed beyond evaluation for the first time 2026-07-29**: `roofclf
  .score_buildings_national` fits one pooled model on all 9 quadrats, picks a
  precision-targeted deployment threshold (0.4555, precision 0.50/recall 0.25 on
  pooled LOQO scores — reuses `sppi._precision_threshold`), and scores every VIDA
  building nationally via the same per-cell pattern `density.process_cell` already
  proves tractable (`local_source.composite_index()`'s `lru_cache`, previously unused,
  now avoids rebuilding the ~4,474-tile composite index once per call).
  **Capacity fold-in tried 2026-07-30, rejected**: folding the 898,593 nationally-flagged
  buildings (97.1% with no existing segmentation candidate) into capacity at the flat
  LOQO precision (0.50) gives 18,063 MWp incremental — 3.5-8x the country's entire
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
  **Quetta-exclusion recalibration, 2026-07-30 — a genuine, measured win.** Quetta is the
  lowest-base-rate quadrat by a wide margin (3.0% vs next-lowest 5.7%) and the one place
  SPPI's own detector collapsed to 10.5% precision; it was forcing the pooled 9-quadrat
  threshold up to 0.4555 to hold 0.50 precision, catching only 25% recall. Re-fit on the
  other 8 quadrats (`quetta_calib_1km` excluded; old 9-quadrat outputs kept at
  `data/roofclf_with_quetta_20260730/`) relaxes the threshold to **0.3064** and recall at
  the same 0.50 precision rises to **39.6%** — median fold AUC dips slightly (0.874→0.861,
  expected, since Quetta's own raw AUC was fine at 0.852; it was the threshold-transfer
  side that broke) and Mardan stays the worst fold (0.743) unchanged, confirming Mardan's
  problem is unrelated to Quetta. This is a clean illustration of the "ranking transfers,
  absolute rates do not" lesson: one outlier stratum, not nine ordinary ones, was setting
  the whole country's operating point. `model_full.json` now reflects the 8-quadrat fit;
  national re-scoring with it is a separate, larger step (does not, by itself, fix the
  capacity fold-in rejection above — a lower threshold flags *more* buildings, so the
  incremental-capacity number is expected to grow, not shrink, until a real per-stratum
  correction exists).
  **SPPI cross-validation, 2026-07-30 — a genuine, measured, but uneven win.** SPPI (He
  et al. 2026, zero-training spectral index) scored on the exact same held-out ground
  truth roofclf uses: median AUC 0.823/0.828 (within size band) vs roofclf's
  0.874/0.842 — roofclf wins but not by much for something needing no training. Adding
  SPPI as a roofclf *feature* does nothing (0.8736→0.8734 AUC, already known). But an
  **AND-gate** (roofclf ≥ 0.3064 **and** SPPI above a matched-recall threshold, sub-400
  m² buildings, 8 quadrats no-Mardan) lifts precision from 0.496 (roofclf alone) to
  0.540 at matched recall (0.445) — roofclf-alone precision at that same recall is only
  0.498, so this is a real +4pp gain from agreement, not just a stricter cutoff. Per
  quadrat the gain concentrates almost entirely in Multan (+10.7pp), Sialkot (+5.5pp),
  Sundar (+5.1pp) — exactly the three low-base-rate quadrats already excluded from the
  density-stratified precision fit below for overestimating 2x+. Coherent story: SPPI
  agreement specifically catches roofclf's overconfidence in the regime already known
  miscalibrated, not a uniform improvement (Faisalabad/Karachi coastal: -0.7/-0.9pp).
  **Tested nationally the same day: does not help the domain-restricted sub-400 figure.**
  `score_buildings_national` now saves `sppi` (zero extra cost); re-ran nationally
  (`data/roofclf_national_with_sppi/`). Applying the AND-gate to the SAME 93
  domain-restricted cells the 6,628 MWp figure uses: precision on those three calibration
  quadrats is flat (0.5501→0.5499) while the AND-gate cuts flagged buildings 31%
  (496,122→343,032) and the capacity figure 29% (6,628→4,690 MWp) for zero precision
  gain — confirms the per-quadrat table's own prediction (SPPI helps in the low-density
  quadrats the domain restriction already excludes, so stacking it on an
  already-restricted population only removes recall for free). **Not adopted** for the
  domain-restricted figure, which stays at 6,628 MWp (roofclf-only). Full writeup:
  `docs/methods/density.md`'s "SPPI cross-validation" subsection.
  **Density-stratified capacity, 2026-07-30 — a partial fix, deliberately kept out of
  `density.py`.** `sub400_capacity.py` (new module) answers "how much does restricting to
  the calibration-covered density regime change the rejected 18-37 GWp national number,"
  and the answer is nuanced: precision alone does not fix it (0.499→0.5495 pooled
  precision from restricting to the 3 quadrats whose `rate_ratio` is within 2x either
  direction — faisalabad, karachi_coast, site_karachi, base_rate 12.5-18.5% — makes the
  *unrestricted* national number worse, 37,197→40,879 MWp, since 0.5495>0.5). The
  relationship between `rate_ratio` and `base_rate` is not "higher density is better" —
  it is a crossing point: quadrats below ~12% base rate overestimate 2x+, the one quadrat
  well above it (lahore, 30%) underestimates instead, and mardan is a separate,
  already-documented bad fold. What actually moves the number is restricting the
  *population*, not the weight: intersecting the density-regime precision with the
  pre-existing building-density domain restriction (93 of 4,473 national cells matching
  the 8 quadrats' 737-4750 bldg/km² range) AND excluding buildings whose own footprint is
  already ≥400 m² (a `new_lead_mask` 30 m-radius matching gap, not real sub-400 signal —
  13.4% of the domain-restricted incremental buildings, 49% of its area) gives **6,628
  MWp**, the same order of magnitude as the country's entire existing
  segmentation-based total (5,078 MWp) for the first time. This number describes ONLY
  those 93 cells (19.1% of national buildings) — rescaling it by the domain's cell/building
  share to estimate a country total (~implies 315 GWp) is exactly the failure this module
  exists to avoid, and `domain_restricted_capacity`'s returned summary says so explicitly.
  The 93 cells concentrate in Karachi, Lahore, Peshawar, Mardan, Faisalabad, Islamabad,
  Sialkot, Multan, Gujranwala, Charsadda, Sheikhpura, Rawalpindi and Quetta — i.e. Pakistan's
  largest cities, matched against the building-density (not PV-density) proxy, the only one
  that survived testing (existing candidate density anti-correlates with true small-PV rate;
  roofclf's own predicted rate does not separate calibrated from miscalibrated quadrats
  either — both tested and rejected as national selection proxies this session). Kept as a
  **separate product**, never merged into `density.py`'s `total_est_mwp_rc`: the fraction-head
  promotion attempt into `density.py` itself (below) broke `check-density` for an unrelated
  reason, and stacking two shaky corrections into one pipeline path is how that happened.
  `density.py` itself gained one small, safe, segmentation-only addition instead: a
  `density_confidence` flag (`below`/`in`/`above_calibrated_range`, from the same 737-4750
  bldg/km² range) on `grid.csv`/`regions.csv`, which states where the ≥400 m² recall
  correction has no calibration evidence either way — it does not correct anything, and it
  is deliberately never computed for a fraction-head run (`aggregate`'s `exp_source` gate),
  so it cannot be read as validating a different instrument's numbers.
  **Fraction-head promotion into `density.py`, attempted and reverted the same day.**
  Forcing `density --fraction-prob-dir` through the *current* (post-OSM-replace) candidate
  population broke `check-density` (2 regions failing vs. the passing 0-fail baseline) —
  root cause: a disproportionate 46% collapse in roof-intersected candidate area vs. 29%
  overall, most likely the same never-fully-root-caused `density.py`/`postprocess.py`
  ground-mount aggregation issue as the Gilgit-Baltistan case above, now exposed by the
  first *forced* full recompute against the OSM-corrected candidates. Reverted to the
  passing segmentation-based backup; the fraction head is not promoted, and the sub-400
  products above are its replacement path — evidence-bearing but explicitly out-of-band.
  **Generalized the same day, by accident and worth recording**: a plain, non-`--force`
  `earthpv density --aoi pakistan --districts` re-run (adding only the `density_confidence`
  flag, segmentation instrument, no fraction involved) reproduced the identical failure
  (2 fail, 3 suspect; `total_est_mwp_rc_roof` 2,229.9→570.9). Cause: `_CAND_COLS` is
  *always* rederived from whatever `candidates.parquet` is current, every run, force or
  not, while the cached cell partials' per-building/`*_roof` columns only refresh on
  `--force` — so the two now permanently disagree, because `candidates.parquet` was
  OSM-geometry-replaced (2026-07-29, oversize 233→149) after the partials were last built.
  **The fraction head was never the cause — any run against the current candidate
  population breaks the gate, segmentation included.** The published `density/` is
  therefore pinned to the pre-OSM-replace candidate snapshot (`n_oversize_excluded=233`,
  restored from `density_segmentation_pre_fraction_promote_20260730/`) until someone does
  a `--force` rebuild AND separately root-causes the roof-candidate collapse that a
  `--force` rebuild triggers — both are still open. The broken re-run is preserved at
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
  at meta.json on the exact `stale_partials` NameError described above — the running
  process had the pre-fix code loaded in memory, editing the file mid-run couldn't
  reach it. Cheap fix: re-running `density` (no `--force`) with the now-fixed code
  skipped every cached cell and finished in seconds, producing the same numbers.
  `check-density` on this true, fingerprint-verified current state **still fails
  identically** (KP 8x, Balochistan 18x, 2 fail/3 suspect) — proving the ratio failure is
  a real property of the current candidate population (uneven OSM-replace correction:
  rooftop candidates got dramatically smaller/more precise via frequent OSM matching,
  `no_building`/ground-mount candidates rarely match OSM and mostly kept their original,
  possibly-inflated size), not an artifact of any bug introduced this session. **Not
  published** — restored the passing pre-replace backup again pending investigation;
  the true-but-failing state is preserved at
  `density_TRUE_CURRENT_STATE_FAILING_20260730/` for whoever root-causes it next. This is
  now the actual, non-speculative version of task substance in
  `docs/issues/density-force-recompute-plausibility-fail.md` — that doc should be updated
  to match before anyone treats the KP/Balochistan question as still open-ended.
  **A tenth quadrat was added 2026-07-30**: `peshawar_calib_1km`, centered at the
  user-supplied (34.0199854, 71.5505752), built as an exact geodesic 1 km² square
  (`pyproj.Geod.fwd`, not hand-drawn). **Re-pulled twice more the same day** as the user
  added missing OSM labels: 290→353→360 installations (+63, then +7 — a shrinking
  increment, suggestive of convergence but not proof of completeness). 358/360 (99.4%)
  below the 400 m² floor, 265/360 (73.6%) below 100 m², packing distance 15.7 m (same
  tightly-packed cluster as Karachi coastal/Quetta/Sialkot) — the densest sub-floor haul
  of any quadrat registered so far. All three pulls kept, none overwritten: bare
  `peshawar_calib_1km_overpass_solar.parquet` (290), dated `..._20260730.parquet` (353),
  `..._20260730_v2.parquet` (360, current) — `_newest_solar`/`_newest_overpass_path` both
  pick the `_v2` file, verified. **Still not Rule-1 verified** — repeated re-pulls are
  not a substitute for a human completeness pass with a second-mapper sign-off; treat it
  like Boxes 2-5 (usable as a `roofclf` training quadrat, not as a source of trustworthy
  negatives) until that happens. `roofclf.discover_quadrats()` picks it up automatically
  (globs `*_calib_*_boundary.geojson`); not yet folded into a retrained `model_full.json`
  — the next `earthpv roof-classifier` run will include it with no flag needed.
  Registered as Box 9 in `docs/issues/pakistan-calibration-boxes.md`.
  **An eleventh quadrat, `peshawar_east_calib_1km`, was added the same day** at a second
  user-suggested center (34.0242579, 71.5600512) — checked for overlap *before* creation
  (per the new procedure this added to the mapping protocol): ~995 m from Box 9's center,
  sharing 6.56% of its area as one corner. Added on the user's confirmation. **That
  overlap is denser than its area share suggests**: 42/131 (32.1%) of this box's
  installations sit inside the shared 6.56% corner, so pooling both Peshawar quadrats into
  `roofclf` training without deduplication double-counts those ~42 installations/buildings
  and breaks LOQO's fold-independence assumption for this pair specifically. **Not yet
  deduplicated** — flagged as an open item, not fixed. Otherwise 131 installations, 100%
  below the 400 m² floor, median 44.9 m², base_rate 3.7% (126/3,382 buildings) — notably
  lower than Box 9's 16.5% despite being 995 m away in the same city, and on 60% more
  buildings over a similar-sized box: a concrete, fine-grained illustration that
  `base_rate` cannot be pooled even between adjacent quadrats. Registered as Box 10.
  Both Peshawar boxes and this overlap caveat are in the new
  `docs/methods/calibration-quadrats.md` overview page (added the same day, in direct
  response to the user not being able to find a table of quadrat status anywhere on the
  site) — that page, not this narrative log, is the place to look for current per-quadrat
  numbers going forward; this file keeps the dated history of how each number changed.

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
estimate / Ceiling** — three different *standards of proof* over the same underlying
numbers: Verified is the hand-mapped OSM population plus buildings where roofclf and
SPPI both agree (no single model trusted alone); Best estimate adds the recall-corrected
&ge;400 m² detections plus roofclf-alone density, with the OSM/detection overlap removed
via `osm_matched_id` rather than summed twice; Ceiling keeps the old High figure (flat
0.5 precision, thresholded, national) and, per explicit request, adds the known
&ge;400 m² total on top rather than showing small-PV alone — landing at **42,251 MWp**
(37,173.0 High-only + 5,077.9 large-PV — note: differs from a same-day standalone-script
computation of 42,274.5 by 23.6 MWp, because this pipeline version aggregates the three
building-level parquets via `_join_buildings_to_grid_cells`'s spatial join instead of a
plain `cell`-id string match, correctly excluding ~4,565 buildings whose id came from a
manifest this run's grid does not cover, rather than guessing their coordinates back from
the id). This is now the `earthpv atlas` CLI's recommended path (`--osm-solar` alongside
the pre-existing three `--sub400-*-cells` flags) and what `configs/aoi.yaml`'s Pakistan
`dashboard:` block embeds; see "Results-page house style" above for the page-shell side
of this change. `build_sub400_bracket_atlas` and its template are unchanged and still
work for anyone invoking the CLI without `--osm-solar`.

**Size is a confounder — report `auc_within_size`.** Adoption rises with house size (mappers
report large houses packed with PV, small ones much less), so footprint area *alone* scores
~0.72. `auc_within_size` scores inside `_SIZE_BANDS` and n-weights, removing size as a
discriminator. It costs the classifier ~3 points (0.874 → 0.842). It used to cost the
segmentation raster ~3 points too (0.734 → 0.707 at 6 quadrats); at 9 quadrats segmentation
has so little unconditional skill left (median AUC **0.511**) that the within-size control
barely moves it further (→ 0.501) — there is almost nothing left to remove. Quote the
conditional number as the imagery's contribution.

**Three invariants here.** (a) Skill must be read per quadrat, never pooled — 4 of 9 are
industrial estates, 5 are not (Karachi coastal, Lahore, Sialkot, Mardan, Quetta), and they
are not one population; Mardan is the weakest fold measured so far (AUC 0.743) and the
first non-industrial, non-Rule-1 quadrat in the set, which reads as the estimate getting
more honest with more evidence rather than the method degrading. (b)
**Ranking transfers, absolute rates do not**: `rate_ratio` now spans **0.235–4.833** across
nine quadrats (was 0.47–1.89 at six — the three new quadrats widened it, Quetta and Mardan
are the extremes), and the model predicts 0.137 for residential Lahore where truth is
0.301. A per-stratum intercept is required before publishing any adoption rate or capacity
from it. (c) **Rule-1 complete requires the mapper's own completeness declaration** (every
visible panel mapped); as of 2026-07-29 four quadrats carry it —
`karachi_coast_calib_700m` (2026-07-26, the first), `sialkot_calib_1km`, `mardan_calib_1km`,
and `quetta_calib_1km` (all 2026-07-29, owner-mapped, registered in
`docs/issues/pakistan-calibration-boxes.md`) — so these are the only quadrats whose
negatives are trustworthy and the only ones where a low score cannot be blamed on missing
labels. None of the four have a separately recorded independent second-mapper sweep; the
owner's own declaration is what "Rule-1 complete" means in this repo, per the
`karachi_coast_calib_700m` precedent. **All three new boxes are now folded into the
roof-classifier's LOQO training/eval and the fraction-head quadrat table above** (re-run
2026-07-29 — `roofclf.discover_quadrats` auto-globs every `*_calib_*_boundary.geojson`
with a matching mapped-solar file, so a bare `earthpv roof-classifier` picked up all nine
with no `--quadrat` flag needed). `karachi_coast_calib_700m` remains the hardest and most
diagnostic of the four: median installation 86 m², 98.8% below the detection floor, and
there the segmentation raster scores **exactly 0.500** and predicts **0.0 m² of PV against
13,964 m² mapped**. **None of the quadrats record when their reference imagery was
captured** — the mapping protocol asks for it but the field has never been filled in
(`docs/issues/calibration-imagery-dating.md`), so stale background imagery missing
recently-installed PV is an untested, plausible contributor to the documented
overestimation in low-base-rate quadrats, alongside the already-verified false-positive
mechanisms — not yet measured either way. Quadrat file naming is size-agnostic
(`*_calib_*_boundary.geojson`,
newest dated `_overpass_solar*` pull wins) — do not re-hardcode `_calib_1km_`.

`roofclf.packing_density` (added 2026-07-29) reports each quadrat's median distance
from a sub-400 m² installation to its nearest neighbour of any size — a cheap,
model-free number that correlates r=0.70–0.82 with `exp_scale`/`auc_within_size`
across all nine quadrats, and now a standing column (`nn_median_m`) in every
`evaluate()` fold report. See `docs/methods/density.md`'s "Packing distance" section.

### Plausibility gate (`plausibility.py`, `earthpv check-density`)

The leads product has a human on every candidate; the capacity atlas has nobody, so a
false-positive mode that survives `p_real` reaches the headline number silently. Two
per-region checks, both from artifacts `density` already wrote: **ground-mount:rooftop
capacity ratio** (bare ground, riverbed, salt flat, rock and snow read bright and nothing
constrains them to a plausible host) and **single-cell concentration** (one 0.1° cell over
25% of a region means that region's total is one blob, not a population). Both need
`mwp_ground >= 50` so a tiny region's ratio is not noise. Exit 1 = a region failed, 2 =
`density` has not run. **Run it between `density` and publishing** — the docs CI *cannot*,
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
calibration YAML) so the site cannot drift from them — edit the sources, not the SVGs.
Charts are written twice (`x.svg` / `x.dark.svg`) for Material's `#only-light` /
`#only-dark` suffixes. The logo variants and favicon are derived from
`docs/assets/earthpv-logo.png` (a black mark on transparency, invisible on the navy
header) by the same script. Local preview:
`pixi run docs-figures && pixi run -e docs docs-serve`. The build runs `--strict`, so a
broken internal link fails CI. Docs prose in this repo avoids em dashes and emoji.

`scripts/screenshot_pages.py` (`pixi run docs-screenshots`) renders the interactive HTML
pages to PNG for the README, which cannot embed an iframe. It is **not** in CI because
it needs a browser. **Snap-packaged Firefox can only read a non-hidden directory under
`$HOME`** — `/tmp`, the external drive holding this repo, and even `~/.cache` all fail,
and the failure mode is a silent hang rather than an error, so the script stages pages
in `~/earthpv-screenshots/` and sets the subprocess cwd there.

### National dashboards (bundle CLI kept, no longer used by the site)

Added 2026-07-31: `earthpv dashboard --aoi <name>` combines an AOI's existing,
independently-built HTML pages (the sub-400 m² bracket atlas, a glint panel-pose
survey) into one tabbed page, rather than any of them being recomputed. It is a
thin shell for a reason — each source page already carries its own `:root`
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
second country's glint survey doesn't need its own copy of that template either —
that part is unrelated to the dashboard bundle and still used.

**Retired from the docs site 2026-08-03.** The site's own "Dashboards" nav section
(`docs/dashboards/index.md`, `docs/dashboards/pakistan.md`, a tab-switching iframe
page) was merged into **Results**, which now just lists direct links to each
standalone page (`docs/results/capacity.md`, `results/growth.md`,
`results/pv-pose.md`, `results/leads.md`) — no iframe, no bundle directory, no
config-driven generator, one page per artifact. Keeping the bundle in sync (the
directory copy, the `INTERACTIVE_DIRS` sync step, the full-bleed page shell) turned
out to cost more than the plain pages it replaced now cost. `earthpv dashboard`,
`dashboard.py`, `configs/aoi.yaml`'s per-AOI `dashboard:` blocks, and
`build_docs_figures.py::sync_interactive_dirs`/`INTERACTIVE_DIRS` all still exist
and still work — nothing was deleted — they are simply not part of the current
site build. See `docs/reproduce.md`'s "Step 7: publish it on this site" for the
pattern that replaced it (add the new page's source to `INTERACTIVE`, write a short
hand-authored `docs/results/<name>.md`, add a nav entry).

### Results-page house style (default for reporting and presentation)

As of 2026-08-01, this interactive HTML "night lights" style is the **default** for any
new results/presentation page — not just the density atlas. Reference implementations:
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
independent copy of the same system inside the actual pipeline — the two are not sliced
from one shared source, since a static `.html` template has no mechanism to slice from a
`.py` file at pipeline run time the way `build_pakistan_pv_evidence_overview.py` slices
CSS from its sibling script. Keep the two in sync by eye when the palette changes; a
`third` reuse point (a real templating layer shared between the standalone scripts and
`src/earthpv/templates/`) is worth building once keeping them in sync by eye actually
starts to hurt, not before. A new **standalone script** still either slices the CSS
wholesale — `_slice`/`_shared_fragments` in `build_pakistan_pv_evidence_overview.py` is
the pattern to copy, matched by exact string markers that fail loudly rather than
silently drift — or copies the `<style>` block outright. A section that deliberately
diverges between pages should be written directly in the new page instead of forced
through a shared slice: `build_pakistan_pv_evidence_overview.py`'s
`POSE_SECTION_HTML`/`POSE_SECTION_JS` stopped slicing the sibling's orientation section
the moment its chart selection and layout diverged (fewer charts, different placement).

**The atlas is generated by the pipeline itself, not only by standalone scripts.**
`src/earthpv/atlas.py::build_evidence_atlas` + `src/earthpv/templates/
pv_evidence_atlas.html` is the pipeline-native version of this style: three tiers by
**standard of proof** rather than by point estimate (Verified / Best estimate / Ceiling
— see "Sub-400 m² instruments" below for what each tier means and how the numbers were
arrived at), promoted 2026-08-01 to the `earthpv atlas` CLI's recommended path,
superseding `build_sub400_bracket_atlas`'s older Low/Central/High/All-PV framing (kept,
undocumented as the default, for AOIs that only have the older bracket inputs). Invoke it
with the same three `--sub400-{low,central,high}-cells` flags the bracket atlas already
used, plus one new flag, `--osm-solar <national OSM/Overpass solar parquet>` — passing
that flag is what selects the evidence atlas over the bracket atlas; the run's own
`candidates.parquet` is found automatically. `density`'s own end-of-run auto-atlas-call
deliberately still writes the plain `build_atlas` (grid/regions only) rather than
guessing at these three extra paths — see the comment above that call in `density.py` for
why guessing would be unsafe. Regenerate the atlas explicitly once the OSM pull,
`earthpv roof-classifier`, and the `sub400_capacity.py`/`roofclf_capacity.py` building
parquets exist for an AOI; `configs/aoi.yaml`'s Pakistan `dashboard:` block already points
its `capacity` panel at the regenerated `results/pakistan_pv_evidence_atlas.html`.

### Small-PV JOSM validation leads (`pixi run small-pv-leads`)

`scripts/build_small_pv_josm_leads.py`, added 2026-08-01 as a **regular, repeatable
task** (`pixi run small-pv-leads` in `pixi.toml`, alongside `docs-figures`) rather than
a one-off script — re-run it whenever national roofclf/SPPI scoring or the OSM solar
pull is refreshed. It writes three GeoJSON files for manual review in JOSM, answering a
narrower question than any capacity number: does the sub-400 m² instrument actually
point at real, previously unmapped installations when a human looks at the imagery?

- `results/pakistan_small_pv_josm_leads.geojson` — the **AND-gate** population
  (roofclf AND SPPI both agree, `sub400_low_incremental_buildings.parquet`, the
  evidence atlas's Verified tier).
- `results/pakistan_small_pv_josm_leads_roofclf_only.geojson` — **roofclf alone**
  (`sub400_central_incremental_buildings.parquet`, the Best-estimate tier).
- `results/pakistan_small_pv_josm_leads_sppi_only.geojson` — **SPPI alone**, gated at
  its own pooled precision-targeted threshold (`sppi.pooled_precision_threshold`, same
  93-cell domain and incremental/contamination filters as the other two) with no
  roofclf condition — derived fresh by the script each run, not a pre-built artifact,
  since SPPI was never adopted as its own deployable capacity instrument in this
  project (see the SPPI cross-validation notes above). Its `est_kwp` is explicitly
  **uncalibrated** (raw area × the module constant, no measured precision weight).

All three exclude buildings within 30 m of an existing OSM solar feature
(`export.filter_new_leads`) so the files test genuinely untested leads rather than
re-confirming known installations, rank by the model's own confidence score (recovered
for the two pre-built populations by an exact-geometry join back to the per-cell
probability parquets, not a proxy like roof area — an earlier, roof-area-ranked
revision of this file was replaced the same day after a first human-reviewed batch came
back "promising but still lots of false positives"), and cap at 6 leads per 0.1° cell so
the sample spans the checked area instead of clustering into whichever cell scores
highest. All three exist specifically so a human can compare their false-positive rates
against each other in JOSM.

**A specific false-positive mode found by that comparison, 2026-08-01**: cell
`0061_0012`'s roofclf-only leads are very bright white buildings — and checking them
against the AND-gate threshold shows **SPPI does not catch this one**: all six
buildings score `sppi` 0.05–0.10, comfortably above the AND-gate's −0.0144 cutoff, so
they pass both detectors together. This is a shared blind spot, not something
roofclf-vs-SPPI disagreement resolves — worth targeted hard-negative labeling (bright
non-PV roofs specifically) rather than expecting the AND-gate to fix it.

**A known, measured limitation surfaced by this exercise, not a bug**: in JOSM, a
flagged building's polygon sometimes sits *among* several real installations rather
than exactly on the one carrying the panels. This matches `roofclf.packing_density`'s
own finding that the densest quadrats (Karachi coastal, Quetta, Sialkot) have a median
15–17 m spacing between neighboring small installations — at or below Sentinel-2's
10 m pixel size, so per-building attribution is a real sensor-resolution ceiling in
those areas, not a training defect. Not yet addressed in the leads file: flagging
leads whose nearest neighbor sits inside that ~15–20 m band as "dense cluster, exact
attribution uncertain" instead of pointing at one specific polygon (discussed, not yet
implemented as of this writing).

### Rooftop potential & saturation atlas (`earthpv atlas --potential-buildings`)

A forward-looking counterpart to everything above: not "how much PV is already there,"
but where large, currently-uncovered roofs and high modelled irradiance overlap — a
siting signal for *future* rooftop solar, plus a saturation view of where PV adoption is
already dense vs. sparse. `potential.py::large_roof_buildings` pulls every VIDA building
nationally with `roof_area_m2 >= 200` from `roofclf.score_buildings_national`'s existing
per-cell output, using **only that table's footprint geometry, never `p_roofclf`/
`sppi`** — this is what keeps the feature outside every calibration/precision problem
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
regardless of ground truth — expected, documented in `docs/methods/density.md`, not a
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
- **`row.mask` / `row.image` on a pandas row:** use bracket access (`row["mask"]`) — `.mask`
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
  unless lingering is enabled. Run `loginctl show-user "$USER" | grep Linger` — if `Linger=no`,
  `loginctl enable-linger "$USER"` once (no sudo needed for your own account) before launching
  anything multi-hour, or it can silently die with no error/traceback partway through.
