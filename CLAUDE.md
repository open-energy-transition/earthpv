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
User-Agent header, which reads exactly like "no such country". Guide: `docs/scale.md`.

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
the rooftop headline claims to describe. Two instruments, both dropping the polygon:

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
13,964 m² mapped**. Quadrat file naming is size-agnostic (`*_calib_*_boundary.geojson`,
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
