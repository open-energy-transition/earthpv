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
atlas is its primary output.** Two detectors, split by placement and by calibration
coverage rather than cleanly by size, combined into one product:

- **Segmentation** (`infer` → `postprocess` → `density`) -- the TerraMind fine-tune,
  outlining panels directly. Produces every mapping lead regardless of size, and is the
  only instrument for ground-mount at any size (`roofclf` has no footprint to classify
  there). It also remains the authoritative rooftop instrument for individual arrays
  **≥ 400 m²** everywhere `roofclf` (below) has not been calibrated to replace it.
- **`roofclf`** (`roof-classifier` → `roofclf-score-national` → `sub400-capacity` →
  `ge400-roof-capacity`) -- a per-building "does this roof carry PV?" classifier,
  cross-checked with the zero-training **SPPI** spectral index for the atlas's Verified
  tier (roofclf AND SPPI agreeing). Covers every building **< 400 m²** (`sub400-capacity`)
  and, as of 2026-08-07, also **replaces** segmentation's own rooftop estimate for
  buildings **≥ 400 m²** (`ge400-roof-capacity`) inside the same density-matched cells,
  where it measures better (AUC 0.896 vs segmentation's 0.73-0.78 on identical
  buildings) -- see "roofclf now replaces segmentation's own rooftop estimate" below.
  Both capacity functions are domain-restricted to the same cells and refuse to rescale
  to a national total on their own.
- **`atlas.build_evidence_atlas`** (`earthpv atlas --sub400-central-cells
  --sub400-low-cells --sub400-outdomain-cells --ge400-roof-cells --osm-solar`) combines
  both into two tiers by *standard of proof* -- **Verified** (hand-mapped OSM, or
  roofclf+SPPI agreement) and **Best estimate** (segmentation's ground-mount detections,
  roofclf's rooftop replacement inside its calibrated cells plus segmentation's own
  recall-corrected rooftop detections outside them, plus roofclf-alone density below
  400 m², plus roofclf+SPPI agreement outside the density-matched domain as a
  clearly-marked extrapolation -- see "Out-of-domain AND-gate" below) -- de-duplicated
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

earthpv sub400-capacity     --aoi <aoi> --osm-solar <national OSM solar pull>
earthpv ge400-roof-capacity --aoi <aoi> --osm-solar <national OSM solar pull>
earthpv atlas --aoi <aoi> \
  --sub400-central-cells   data/roofclf_national_with_sppi/<aoi>/density/sub400_central_incremental_buildings.parquet \
  --sub400-low-cells       data/roofclf_national_with_sppi/<aoi>/density/sub400_low_incremental_buildings.parquet \
  --sub400-outdomain-cells data/roofclf_national_with_sppi/<aoi>/density/sub400_outdomain_and_gate_incremental_buildings.parquet \
  --ge400-roof-cells       data/roofclf_national_with_sppi/<aoi>/density/ge400_roof_incremental_buildings.parquet \
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
--sub400-low-cells --sub400-outdomain-cells --osm-solar` to combine both into the
evidence atlas.
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

**Gujarat's first full capacity atlas, 2026-08-07** (`docs/results/gujarat.md`,
`docs/assets/interactive/gujarat_pv_atlas.html`), at the owner's direction. Compose +
infer + postprocess had already been run in full for this AOI (1,527/1,527 cells
composited, 1,526/1,527 inferred, `candidates.parquet` 4,816 rows, 2026-07-12) --
what was missing was everything from calibration onward: `calibrate-candidates
--recall-reference none` (no pipeline-independent mapped reference exists for India yet,
so this is `status: interim-mapped-only`, an honest precision floor, not a central
estimate), `density --districts --force` (2h24m, first-ever run for this AOI so no
fingerprint existed to protect), `check-density` (0 fail, 3 suspect -- the AOI bbox
spills slightly into 4 neighbouring Indian states/territories, all `suspect` on small
absolute MWp below the plausibility floor, not a Gujarat-specific finding), then the
plain segmentation-only `earthpv atlas` (no `--sub400-*`/`--ge400-roof-cells`: zero
calibration quadrats exist for Gujarat, so neither roofclf instrument can be fit here --
this is the documented main-workflow fallback for a country with no mapped quadrats yet,
not a lesser product). Result: **812.6 MWp** (`est_mwp_rc`, roof 197.0 / ground 615.6),
recall-*uncorrected* (recall-reference none means this number is `est_mwp_cal`,
precision-weighted only, with no Horvitz-Thompson inflation -- a floor, not a central
estimate, exactly the same sense in which Pakistan's own numbers before their own recall
correction were floors).

**A real, unresolved gap surfaced by this run, not a silent substitution: this atlas
does NOT use `v3_combined_india`**, the checkpoint the owner directed this project to use
for all future development the same day (see "Which segmentation checkpoint" under the
Density stage section above). Gujarat's existing candidates were produced 2026-07-12,
three days before `v3_combined_india` was even trained (2026-07-15/16) -- and
re-inferring with it was not possible because **the checkpoint file no longer exists
anywhere on this machine** (`find /` came back empty), and neither does `v2_combined`,
the checkpoint `configs/aoi.yaml`'s own Gujarat comment names as what was used ("the
existing Germany-trained checkpoint ... unchanged, same as the original Punjab
bootstrap"). Both were apparently deleted at some point after producing their outputs,
before this session started. This atlas is therefore built from whichever checkpoint
actually produced Gujarat's existing candidates -- almost certainly `v2_combined` per
that comment, but this can no longer be verified against the weights themselves, and
should NOT be read as a like-for-like comparison with Pakistan's `v3_combined_india`
numbers. Flagged prominently in `docs/results/gujarat.md` rather than silently glossed
over. Re-running Gujarat's compose+infer with whichever checkpoint is current when
someone next revisits this AOI, and re-deriving density/atlas from there, is the natural
next step -- not done here because it needs a fresh multi-hour training or inference run
this session judged out of scope, not because the gap was missed.

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

**`buildings.geoparquet`'s summed rooftop capacity is NOT the same number as
`grid.geoparquet`'s region-level rooftop total, structurally, not as a bug -- measured and
documented 2026-08-06** (`docs/methods/density.md`'s "`buildings.geoparquet`'s rooftop sum
is not the region total's rooftop component"). The region/national total
(`est_mwp_rc_roof`, `pv_area_det_roofcand_m2`) sums each rooftop-placed candidate's full
polygon area once; the per-building table (`density.per_building_detected`) only credits
each building with its actual geometric intersection with the candidates touching it,
capped at that building's own roof area -- so whatever part of a "rooftop"-classified
candidate's own polygon does not literally sit on a building (gaps between the buildings
a big polygon spans, general polygonize-and-merge over-draw past a roof's edge) is counted
in the first total and silently missing from the second. Measured on a single matched
candidate snapshot (so staleness above isn't confounding it): of 21,506,014 m² of
rooftop-placed candidate area nationally, only 11,527,028 m² (53.6%) is attributed to any
building -- a **46.4% gap**. `postprocess._join_buildings_metric`'s own recorded
`building_overlap_frac` (mean 0.588 across rooftop-classified candidates -- it only takes
>= 0.3 to be called `rooftop`) predicts a 9,781,295 m² gap via `sum(area * (1 -
overlap_frac))`, matching the measured 9,978,986 m² to within 2% -- confirming the
mechanism directly rather than leaving it circumstantial. **Ground-mount is not
involved**: both sides of this comparison are already restricted to `placement ==
"rooftop"` candidates before summing, so the gap is whitespace inside rooftop-classified
polygons, not a rooftop/ground-mount misclassification. Practical consequence: any
PyPSA-style per-building disaggregation built from `buildings.geoparquet` is a
conservative, roof-anchored floor and should not be expected to sum back to
`grid.geoparquet`'s own rooftop total.

**A full recall/precision re-derivation against the current candidates was attempted
2026-08-06 and NOT published -- restored the passing snapshot, matching the 2026-07-30
precedent for this exact failure shape.** The published `est_mwp_rc` (5,077.9 MWp) had
been computed from a `candidates.parquet` snapshot that predates the 2026-07-29
OSM-geometry replacement (no `candidates_fingerprint.json` existed to catch this), and
`configs/calibration/pakistan_candidate_precision.yaml`'s per-bin recall came from a
2026-07-23 reference pooling only 1 (now-retired, much smaller) calibration box. Both
were re-derived properly the same day: `earthpv calibrate-candidates` re-run against the
current `candidates.parquet` with all 18 Rule-1-complete quadrats pooled into
`--calibration-box` (14,811 fully-mapped installations, vs. the 1,021 the published table
used), then `earthpv density --force` with the refreshed table (~2h, 4,463/4,463 cells,
completed cleanly). Recall fell in every bin against this much richer ground truth
(500-1k: 0.736 -> 0.419, 1k-5k: 0.889 -> 0.644, 5k-50k: 0.991 -> 0.841, >50k: 1.000 ->
0.840), which alone would raise `est_mwp_rc`, but `p_real` fell by MORE in the
area-dominant large bins (mapped_frac for >50k: 0.713 -> 0.165) because the current,
OSM-replaced candidate population has a different bin composition than the snapshot the
2026-07-23 table was fit against -- net effect, `est_mwp_rc` **fell** to 2,327.2 MWp
(roof 640.2, ground 1,686.9), the opposite direction naive reasoning about recall alone
would predict.

**`check-density` failed on this refreshed state**: Khyber Pakhtunkhwa (ground:rooftop
5.54x) and Balochistan (10.17x) both crossed from `suspect` to `fail` (previously 3.35x /
3.90x). Checked whether the newly-found duplicate-OSM-match bug (see "Small-PV JOSM
validation leads" below / `docs/issues/osm-replacement-and-sppi-capacity.md` Part 3)
explains it at scale: nationally it affects 16 nested/duplicate candidate pairs, 3.27 km²
(10.3% of OSM-replaced candidate area) -- real, but far too small to account for a
5-10x regional ratio swing on its own. The actual driver is that the re-fit `p_real`
dropped much harder for rooftop-classified large candidates than for ground-mount ones
specifically in these two regions; not root-caused further given the same result was
already accepted as "confirmed genuine, not a further bug" once before at a similar
KP/Balochistan ratio failure (2026-07-30 entry above).

**Restored, not published**: `data/predictions/pakistan/density/` reverted to
`density_PUBLISHED_PINNED_backup_20260805/` (byte-identical, `check-density` re-verified
passing: 0 fail, 3 suspect, same as before this attempt) and
`configs/calibration/pakistan_candidate_precision.yaml` reverted to its last-committed
state (verified identical via `git diff`). The failing refreshed state is preserved at
`data/predictions/pakistan/density_TRUE_CURRENT_STATE_FAILING_20260806/` and the
re-derived (18-quadrat, current-candidates) calibration table at
`data/predictions/pakistan/density_PRE_recall_and_candidates_refresh_20260806/` is kept
alongside it for whoever picks up the root-cause next -- neither the >= 400 m² total this
would have produced nor the richer recall evidence behind it should be discarded, just
not shipped yet. The published evidence atlas (Verified 7,384.1 / Best 12,614.2 MWp,
`docs/assets/interactive/pakistan_evidence_atlas.html`) was built earlier the same day
from the still-passing state and needed no changes -- it already reflects the sub-400
coverage-ratio fix, the geometric OSM-dedup fix and the Best-floor fix documented above,
all independent of this recall/candidates question.

**roofclf now replaces segmentation's own rooftop estimate for >= 400 m² buildings inside
the density-matched domain -- implemented and shipped 2026-08-07, at the owner's explicit
direction after reviewing the measured comparison.** Two things resolved the open question
from the same-day segmentation-model audit (see "Which segmentation checkpoint" note
below): the owner confirmed segmentation validation should only ever use INSTALLATION
size (`pv_area_true_m2`), not building size -- a >= 400 m² building can carry an
installation far smaller than its own roof, which segmentation is trained blind to
regardless of the building it sits on, explaining the exact-zero-AUC quadrats found in
that audit without further root-causing them -- and confirmed `v3_combined_india` (the
existing production checkpoint) as the segmentation model to use going forward, no
retrain. New module `roofclf_ge400_capacity.py` (`domain_restricted_ge400_roof_capacity`,
CLI `earthpv ge400-roof-capacity`) mirrors `sub400_capacity.py`'s domain-restricted,
coverage-ratio-weighted design exactly, just for `roof_area_m2 >= 400` instead of `< 400`:
same 13-quadrat calibrated-density-ratio selection, same measured (true PV area / roof
area) multiplier (0.2372, close to sub-400's 0.1988-0.265 -- coverage is a similar
fraction of the footprint regardless of size), same OSM dedup. Unlike the sub-400
functions, this REPLACES rather than adds to segmentation's estimate (no dedup against
segmentation candidates): `atlas.py::build_evidence_atlas` takes a new optional
`ge400_roof_buildings_path`, uses the roofclf-based per-cell rooftop value inside the 92
density-matched cells and segmentation's own `est_mwp_rc_roof` everywhere else (that
column is the only evidence-backed number outside the domain), sums with
`est_mwp_rc_ground` (untouched -- roofclf cannot score ground-mount) into a new
`mwp_large` that replaces the bare `est_mwp_rc` reference throughout the function.
Result, run against the current national roofclf scoring (already covers every building
size, no re-inference needed) and the restored-published segmentation state: in-domain
roofclf rooftop 3,432.3 MWp vs segmentation's own 1,573.5 MWp for the identical 92 cells
(2.18x) -- checked against the domain's own building population (225,628 buildings
>= 400 m², 42.5% flagged) for a sanity bound, consistent with the quadrats' own 61% flag
rate at their higher true PV prevalence. National blended rooftop total 2,229.9 ->
4,088.7 MWp (in-domain replaced, out-of-domain segmentation kept); evidence atlas
republished: Verified unchanged at 7,384.1 MWp (rooftop swap does not touch Verified),
Best 12,614.2 -> **14,473.0 MWp**. Old atlas backed up to
`results/pakistan_pv_evidence_atlas_PRE_roofclf_ge400_swap_20260807_backup.html`.

**Which segmentation checkpoint -- an audit finding worth keeping, 2026-08-07.**
`roofclf.py`'s `seg_mean`/`seg_max` features (used throughout this project's
segmentation-vs-roofclf comparisons) default to `data/predictions_pk16085/pakistan/prob/`
(checkpoint `terramind-pv-epoch=11-step=5880.ckpt`, F1=0.624 on its own val split, chosen
via an actual top-k comparison 2026-07-19) -- an undocumented directory with zero mentions
anywhere in this file or `docs/` before this entry, NOT the checkpoint the main workflow's
`candidates.parquet`/`density.py` actually uses (`v3_combined_india/terramind-pv-
epoch=22-step=9062.ckpt`, F1=0.641 on a Multan val split, logged at the time as "no prior
evaluation" before that same-day safety-gate check). Recomputed roofclf's zonal-stat
features against the actual production raster for the same quadrat buildings rather than
trust two F1 numbers from different val splits: `v3_combined_india` scores AUC
0.761-0.775 on >= 400 m² buildings against `pk16085`'s 0.726 -- the production checkpoint
is slightly BETTER, so every segmentation-vs-roofclf comparison already made this session
was, if anything, mildly unfavorable to segmentation, not favorable. **Confirmed by the
owner as the checkpoint to use for all future development; no retrain planned.** A
second thing fell out of the same audit and was resolved by the owner directly rather
than further code investigation: 7 of 18 quadrats showed literal exact-zero probability
at EVERY building (positive and negative alike) from both checkpoints, despite those
cells' rasters having isolated nonzero pixels elsewhere -- explained by the
installation-size point above (a >= 400 m² building with a much smaller true array reads
as a segmentation miss regardless of its own footprint size), not chased further as a
separate raster/alignment bug.

**Coverage ratio is now measured per building size, not one flat number -- implemented
2026-08-09, at the owner's request.** Every coverage-ratio multiplier above (sub-400's
0.1988/0.265, >= 400 m²'s 0.2372) was a single flat number applied to every flagged
building regardless of how big its roof was. `sub400_capacity.coverage_ratio_by_size`
measures the same quantity (true mapped PV area / roof area on the flagged population)
binned by each flagged building's own `roof_area_m2` instead of pooled -- 10 equal-count
(quantile) bins over the calibration quadrats' own labels, falling back to the pooled
ratio for any bin with fewer than 25 flagged buildings. Measured on the 13
density-calibrated quadrats at the deployment threshold: roofclf-only coverage is fairly
flat across size deciles, ~0.17-0.25 (area-weighted mean 0.203, barely above the old flat
0.199) -- but the roofclf-AND-SPPI (AND-gate) population shows a real, much sharper size
trend, ~0.21 in the smallest decile of flagged roofs rising to ~0.46 in the largest
(area-weighted mean 0.267 against the old flat 0.265). `apply_size_coverage_ratio` looks
up each building's own ratio by which bin its `roof_area_m2` falls into (`np.searchsorted`
against the bin edges); `coverage_ratio_by_size` itself is called with NO built-in size
restriction, so ONE fit spans both sub-400 m² and >= 400 m² buildings together --
`roofclf_ge400_capacity.domain_restricted_ge400_roof_capacity` now imports and calls the
exact same function `sub400_capacity.py`'s own two capacity functions use, rather than
fitting its own separate >= 400 m²-only ratio, since the ratio was measured continuous
across the 400 m² boundary with no discontinuity there. `density_regime_coverage_ratio`
(sub400_capacity.py) and `density_regime_coverage_ratio_ge400`
(roofclf_ge400_capacity.py), the flat-ratio functions this replaces, are removed rather
than kept alongside the new one.

Re-ran all three domain-restricted capacity functions and the evidence atlas against the
current national roofclf scoring (no re-inference needed, CPU-only, ~1-2 min total since
the domain restriction only ever reads the 92 in-domain cells). Because a flat ratio was
already close to its own population's area-weighted mean in every case, the aggregate
MWp figures move only modestly even though individual buildings' shares now differ by
roof size: sub-400 central (Best-estimate small-PV) 3,906.4 -> **3,993.0 MWp** (+2.2%),
sub-400 AND-gate (Verified small-PV) 2,350.3 -> **2,364.3 MWp** (+0.6%), >= 400 m²
roofclf rooftop 3,432.3 -> **3,380.0 MWp** (-1.5%). Evidence atlas republished: Verified
7,384.1 -> **7,398.2 MWp**, Best estimate 14,473.0 -> **14,507.2 MWp**. Old atlas and the
pre-change sub400/ge400 building parquets backed up to
`results/pakistan_pv_evidence_atlas_PRE_20260809_size_coverage_ratio_backup.html` and
`data/roofclf_national_with_sppi/pakistan/density_PRE_20260809_size_coverage_ratio/`.

**The density-matched domain widened from 92 to 163 of Pakistan's 4,463 cells, same
day, at the owner's request ("how can I increase the number of cells processed for
roofclf").** All three domain-restricted capacity functions (`sub400_capacity.py`'s two,
`roofclf_ge400_capacity.py`'s one) only ever speak for cells whose building density falls
inside `density.CALIBRATED_BLDG_DENSITY_KM2` via `sub400_capacity.national_cell_domain`
-- a plain module-level constant, `(737.28, 4750.24)`, fit on 8 (no-Quetta) quadrats on
2026-07-30 and never recomputed since, even as the calibration set grew to 18. Two things
worth recording about how this was diagnosed: (a) `--ratio-lo`/`--ratio-hi` do NOT affect
this at all -- `national_cell_domain` never reads `select_calibrated_quadrats`'s output,
only the fixed tuple, so widening the ratio band on the CLI silently does nothing to cell
count, a real footgun if someone tries that first; (b) `roofclf-score-national` was
already scoring effectively all 4,463+ national cells (4,470 per-cell parquets existed
already) -- the bottleneck was never national scoring coverage, only this downstream
density filter. Measured before changing anything: recomputing the constant from the 13
quadrats `select_calibrated_quadrats` currently trusts for precision (871.6-2316.3/km²)
would have *shrunk* the domain to 50 cells, since that ratio-band selection drops
quadrats (Quetta, Mardan, Sialkot, Sundar, Rahim Yar Khan) specifically for being poorly
*calibrated*, not for having an untrustworthy *density measurement* -- a quadrat's
density is real Rule-1 ground truth regardless of whether its precision passed the ratio
band. Recomputed instead from the density span of **all 18** currently Rule-1-complete
quadrats (553.40-5258.00/km², sundar to quetta) -- presented to the owner as one of three
options (widen to all 18, narrow to the 13, or leave as documentation-only) and this was
the one chosen. `CALIBRATED_BLDG_DENSITY_KM2` updated in `density.py` (shared by
`sub400_capacity`'s domain restriction AND `density.py`'s own segmentation-only
`density_confidence` completeness flag -- the latter is not currently published for
Pakistan, so this change has no live effect there yet, only on roofclf). Domain grew to
163 cells (3.7% of national cells, 24.5% of national buildings). Re-ran all three
capacity functions + the evidence atlas: sub-400 central 3,993.0 -> **5,074.6 MWp**,
sub-400 AND-gate 2,364.3 -> **2,807.3 MWp**, >= 400 m² roofclf rooftop 3,380.0 ->
**4,335.7 MWp**. Evidence atlas: Verified 7,398.2 -> **7,841.2 MWp**, Best estimate
14,507.2 -> **16,110.1 MWp**. Ground-mount capacity is untouched at every step -- roofclf
has no footprint to score there, so this domain restriction never applied to it in the
first place. Old atlas and pre-change building parquets backed up to
`results/pakistan_pv_evidence_atlas_PRE_20260809b_widen_domain_backup.html` and
`data/roofclf_national_with_sppi/pakistan/density_PRE_20260809b_widen_domain/`.

**Coverage ratio is now also stratified by building density, not pooled across the whole
domain -- implemented 2026-08-09, same day, at the owner's request ("increase the
precision of roofclf... do 2 [a per-stratum correction]").** `rate_ratio` (roofclf's
predicted/true adoption rate) is close to flat across quadrats while true `base_rate`
spans 3-30% (see "Density and detection quality" below) -- standing evidence that a
single pooled fit hides real structure by density regime, the same argument that
motivated `coverage_ratio_by_size`'s SIZE stratification a few hours earlier in this same
session. New `sub400_capacity.coverage_ratio_by_size_and_density` +
`apply_stratified_coverage_ratio`: the 13 precision-calibrated quadrats split into
`DEFAULT_N_DENSITY_STRATA = 2` density bands at their own median (chosen deliberately
coarse -- 3+ bands leaves 4 or fewer quadrats per band, too thin to trust over the
pooled fit), each band still fits its own size-binned coverage table exactly like
`coverage_ratio_by_size` did before, with graceful fallback to the fully pooled fit if a
band's own flagged population is too sparse (none of the 3 capacity functions needed the
fallback in practice). A national cell is assigned to a band by ITS OWN measured
building density (from `national_cell_density.parquet`, already read for the domain
restriction itself), not by any property of the specific building being priced.
`roofclf_ge400_capacity.domain_restricted_ge400_roof_capacity` calls the exact same
function rather than fitting a separate one, matching how it already shared the
size-only fit. Measured: the two bands (871.6-1757.8 and 1757.8-2316.3 bldg/km² for the
13-quadrat calibration set) are fairly close in overall level for roofclf-only (0.217 vs
0.220) but differ more within specific size bins (e.g. the 274-314 m² bin: 0.157 low-density
vs 0.198 high-density), and separate more clearly for the AND-gate (0.385 vs 0.317
overall) -- real, if modest, structure a single pooled number was averaging away. Re-ran
all three domain-restricted capacity functions + the evidence atlas: sub-400 central
5,074.6 -> **4,874.0 MWp**, sub-400 AND-gate 2,807.3 -> **2,835.6 MWp**, >= 400 m² roofclf
rooftop 4,335.7 -> **4,268.7 MWp**. Evidence atlas: Verified 7,841.2 -> **7,869.4 MWp**,
Best estimate 16,110.1 -> **15,842.6 MWp** (Best moved down this time -- the ge400-roof
and central components both fell more than AND-gate/low rose). Old atlas + pre-change
building parquets backed up to
`results/pakistan_pv_evidence_atlas_PRE_20260809c_density_stratified_backup.html` and
`data/roofclf_national_with_sppi/pakistan/density_PRE_20260809c_density_stratified/`.

**Hard-negative retrain attempt using the one confirmed false-positive example already on
record, 2026-08-09 -- negative, not promoted, but genuinely informative.** Same request's
second half ("take the hard negatives we already know about") pointed at the one
concretely-locatable confirmed false-positive example in this project's history: cell
`0061_0012`'s six very-bright-roof buildings (see "Small-PV JOSM validation leads" below --
found 2026-08-01, roofclf scores them 0.98-1.00, SPPI mostly does not catch them either).
Retrieved their exact geometries from the national scoring output by matching
`(roof_area_m2, p_roofclf)` back to `data/roofclf_national_with_sppi/pakistan/prob/
0061_0012.parquet`, recomputed the same zonal-stat features `roofclf.building_table` uses
(reflectance band means, ndvi/ndbi/brightness/ratios) from that cell's own composite
raster, and appended them to `buildings.geoparquet` as `has_pv=0` rows under a synthetic
`quadrat` label excluded from `select_calibrated_quadrats` by construction (an all-negative
"fold" gets an astronomical `rate_ratio`, comfortably outside any sane `[ratio_lo,
ratio_hi]` band) -- `evaluate()`'s existing LOQO loop required no code change to handle
this gracefully (`auc()` already returns NaN rather than erroring on a single-class fold).
**Plain (unweighted) addition changed almost nothing**: 6 rows against ~92k moved these
buildings' own full-model score by 0.0001-0.003 (e.g. 0.9882 -> 0.9854) and left
`median_fold_auc`/`deployment_threshold` unchanged to 3 decimal places -- 6 examples
carry negligible gradient weight in a regularized fit over 92k rows, a real, if
unsurprising, negative result on its own. **Oversampling makes the tradeoff explicit
rather than solving it**: replicating the 6 rows 20x/100x/500x (0.13%/0.65%/3.16% of the
augmented table) does suppress the target scores (100x: down to 0.16-0.96; 500x: down to
0.01-0.35, now below the 0.2405 deployment threshold) but at a monotonically worsening
COST to overall held-out skill (`median_fold_auc` 0.8824 -> 0.8811 -> 0.8726 -> 0.839;
`median_fold_auc_within_size` 0.8364 -> 0.8336 -> 0.8217 -> 0.7851) -- the model is
learning to specifically distrust the tiny neighbourhood of feature-space these 6 points
define, at the expense of everything else roofclf was measured against. No oversampling
factor tested threads this needle; the AUC cost is already non-trivial by 100x, well
before the false positives are reliably suppressed. **Conclusion, and why nothing was
promoted to `data/roofclf/`**: n=6 is not enough signal to fix this failure mode by
retraining, with or without reweighting -- the fix this specific finding actually
recommends is mining MORE examples of the same bright-roof pattern nationally (the
mining machinery for this exists for the SEGMENTATION model, `hard_negatives.py`'s
bi-temporal confirmed-negative check, but has no roofclf/building-classifier
equivalent yet), not further leverage on the 6 already known. Kept as a diagnostic
record, not shipped: `data/roofclf_hardneg/` (the plain, unweighted augmented refit --
`buildings.geoparquet`, `model_full.json`, `folds.csv`, `summary.json`); the oversampling
sweep was not saved as a pinned artifact since none of its factors were candidates for
promotion.

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

**Three more measured issues found and fixed the same day (2026-08-06 release audit),
all upstream of the OSM-dedup fix above -- pre-release review found the atlas's two
headline numbers were each overstated by a different, independently-verifiable
mechanism.**

- **Sub-400 m² capacity assumed a flagged roof is entirely covered by panels.**
  `domain_restricted_capacity`/`domain_restricted_and_gate_capacity` multiplied
  flagged roof area by precision alone (`roof_area_m2 * kwp_per_m2 * precision`) --
  precision corrects for false positives, nothing corrected for the fact that a real
  installation covers only part of its roof. Measured directly against the
  calibration quadrats' own mapped `pv_area_true_m2`: on sub-400 m² buildings roofclf
  flags in the 13 selected quadrats, mapped PV covers only **19.9%** of the flagged
  footprint (roofclf-only) / **26.5%** (AND-gate) -- so precision alone (0.53 / 0.63)
  overstated capacity 2.7x / 2.4x. `sub400_capacity.density_regime_coverage_ratio`
  (new function) measures this ratio directly on the flagged population and replaces
  `precision` as the multiplier; `calibration_precision`/`calibration_recall` are kept
  in the summary for diagnostic comparison only. Central 10,502.9 -> **3,906.4 MWp**,
  low (AND-gate) 5,600.1 -> **2,350.3 MWp**.
- **The evidence atlas's own OSM-matched flag used `osm_matched_id`, a one-to-one
  nearest match, so it undercounted matches and inflated `osm_mwp_unmatched`.**
  `postprocess.replace_with_osm_geometry` assigns at most one OSM id per *candidate*
  polygon, even when that polygon (a coarse model blob, or a large mapped array) spans
  several OSM installations -- common in dense residential quadrats. Using that id set
  in `build_evidence_atlas` found only 1,674 of 16,085 OSM installations "already
  found by the model." A direct 30 m geometric proximity check (`export.new_lead_mask`,
  the same test the rest of the pipeline uses for "is this a new lead") finds 3,022.
  `osm_mwp_unmatched` fell 3,298.1 -> **1,398.4 MWp** -- that MWp was never missing from
  the model's own detections, it was a counting artifact.
- **`mwp_best` could read below `mwp_verified` in the same cell**, because Best
  discards a cell's matched-OSM value in favor of the model's own `est_mwp_rc`/
  `small_central`, which is sometimes smaller than what it replaced. Worst case measured:
  the Quaid-e-Azam Solar Park cell scored Verified 866.5 MWp against Best 243.3 MWp
  pre-fix (`est_mwp_rc` there was 0.2 MWp) -- Best is defined as "the highest defensible
  figure" and cannot legitimately read lower than Verified. `build_evidence_atlas` now
  floors `mwp_best` at `mwp_verified` per cell after both are computed (62 of 4,463
  cells needed it) and records `n_cells_best_floored` in the totals.

Evidence atlas republished with the three fixes above (OSM dedup from the prior entry
was already in): Verified 10,633.9 -> **7,384.1 MWp** (-30.6%), Best estimate
18,878.9 -> **12,614.2 MWp** (-33.2%), zero cells remaining with Verified > Best. Old
atlas backed up to
`results/pakistan_pv_evidence_atlas_PRE_coverage_ratio_and_dedup_fix_20260806_backup.html`;
pre-fix sub-400 building parquets backed up to
`data/roofclf_national_with_sppi/pakistan/density_PRE_coverage_ratio_fix_20260806/` and
`data/sub400_20260806_fixed_PRE_coverage_ratio_fix_20260806/`. **The &ge;400 m²
segmentation total (5,077.9 MWp) is untouched by this pass and is a separate, still-open
question**: it is computed from a `candidates.parquet` snapshot that predates the
2026-07-29 OSM-geometry replacement (see "roofclf.py" below for that fix's effect on
matched-candidate area), and the model's per-size-bin recall
(`configs/calibration/pakistan_candidate_precision.yaml`) was fit before the current
16,085-installation national OSM pull existed -- re-measuring recall against it moves
every bin down (e.g. 1k-5k: table 0.889 vs re-measured 0.606), which pulls the
&ge;400 m² total in the *opposite* direction from the stale-candidates issue. Recomputing
`est_mwp_rc` against the current candidates alone (no recall re-fit) gives ~2,847 MWp;
this needs a single combined re-derivation, not two independent partial fixes shipped
separately, and was left out of this pass for exactly that reason.

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

### Ground-mount double-counting and land-constant calibration, 2026-08-10/11

**A full pipeline review (this file's own "Which segmentation checkpoint" audit plus a
fresh ground-mount-specific pass) found and fixed several compounding overstatements in
the ground-mount half of the >= 400 m² total, and separately resolved the "still-open"
recall/candidates provenance question from 2026-08-06.** Full derivation and every
measured number: `docs/issues/pakistan-calibration-boxes.md`'s "Correction and full fix"
and "Placement-split calibration" sections. Summary:

- **OSM ground-mount polygons overlap and were double-counted.** A `power=plant`
  perimeter with a nested `power=generator` way, or duplicate mapping passes, describe
  ONE real installation as multiple features; summing their areas double-counts it
  (measured at Quaid-e-Azam Solar Park: 77% of the dissolved `generator` footprint sits
  inside the `plant` perimeter already covering it). New `labels.dissolve_overlapping`
  merges geometrically-overlapping same-placement polygons into one feature per
  connected cluster before ANY capacity computation touches them -- wired into
  `export.load_mapped_reference_attrs` (feeds `postprocess.replace_with_osm_geometry`)
  and `atlas.build_evidence_atlas`'s own Verified-tier OSM sum. Nationally: ground-mount
  OSM area 55.95 -> 42.32 km² (-24.4%), rooftop 6.21 -> 6.08 km² (-2.1%).
- **Dissolving the OSM reference, on its own, made a DIFFERENT bug worse before it was
  caught.** A bigger, dissolved reference polygon sits within match distance of MORE
  nearby candidates than the small fragments it replaced, so more candidates
  independently matched (and each fully inherited) the same installation's area:
  duplicate `osm_matched_id` groups nearly tripled (16, up from a pre-existing 3.27 km²
  /10.3% baseline) before a fix. `postprocess.replace_with_osm_geometry` now keeps only
  the closest match per OSM feature (`pandas.groupby(...).idxmin()`, not a naive
  `dist == minimum` equality test -- ties at `dist_m == 0.0` broke that and left 13 of
  16 duplicates unresolved on the first attempt); every other candidate that matched the
  same feature keeps its own original, unsubstituted geometry rather than being dropped,
  since it may be a genuinely separate detection.
- **`postprocess.MAX_CANDIDATE_M2`'s oversize exclusion was refactored into
  `density.capacity_relevant_candidates`**, shared by `run_density` and
  `atlas.build_evidence_atlas` so both use an IDENTICAL population: a `geometry_source
  == "osm"` oversize candidate (a real, human-mapped footprint, not a
  `polygonize_chips`-merged blob) is exempted from the exclusion after deduping
  overlapping OSM-oversize candidates via `dissolve_overlapping` (fixing Quaid-e-Azam
  Solar Park's own outer-envelope/member-way pair, which the original keep-largest dedup
  would have undercounted by 23%, the part of the member way outside the envelope).
- **`capacity_calibration.DEFAULT_KWP_PER_M2_LAND` was calibrated against real plants for
  the first time**, moving 0.07 -> **0.05** kWp/m² (geometric mean of Quaid-e-Azam Solar
  Park: 400 MW / 8,904,839 m² dissolved footprint = 0.0449, and the Sukkur solar farm:
  150 MW confirmed combined 3-phase capacity / 2,606,013 m² = 0.0576 -- the OSM tag on
  Sukkur's matched way names only one 50 MW phase, so using it alone would have been a
  3x undercount). `KWP_LAND_CI90` moved to (0.035, 0.075). Re-verified against a fresh
  Overpass re-pull of both boxes (see below): the dissolved footprint area came out
  byte-identical despite OSM fragmenting each site into many more raw features,
  confirming the dissolve fix is robust to exactly the kind of re-mapping that motivated
  the re-pull.
- **Precision/recall calibration is now split by placement**
  (`capacity_calibration.derive_placement_tables`, new): pooling rooftop and ground-mount
  into one set of area bins let ground-mount borrow rooftop's much higher OSM
  corroboration rate in the same bin (measured: ~1% of surviving ground candidates sit
  within 100 m of any OSM feature nationally vs ~14% for rooftop). Ground bins fall back
  to `p_unmapped = 0.0` ("interim-mapped-only-by-placement", an honest floor) rather than
  inheriting the pooled glint-derived value, since the existing glint sample
  (`data/glint/pakistan_cand_targets.parquet`, pulled 2026-07-19) predates three
  subsequent candidate-population regenerations and cannot be reliably re-attributed by
  placement. `density.py`'s `candidate_p_real`/`candidate_recall` (point estimate) and
  `_candidate_uncertainty` (credible-interval draws) both select each candidate's own
  placement subtable when one exists, falling back to the pooled table otherwise.
  Also fixed the same day: `calibrate-candidates`'s `cands`/`recall_cands` previously
  measured precision/recall against the RAW candidate file including oversize blobs
  `density.py` itself excludes from capacity -- now filtered through the same
  `capacity_relevant_candidates` both consumers share.
- **All 21 registered calibration areas (19 rooftop/mixed quadrats + 2 ground-mount
  boxes) were re-pulled from live Overpass**, at the owner's request
  (`scripts/refresh_calibration_areas.py`, new -- writes dated
  `<stem>_overpass_solar_<date>.parquet` files that never overwrite the pull they
  supersede, resumable if interrupted). Re-derived the calibration table against the
  fully refreshed set: 15,465 pooled installations, up from the single-box 3,832 the
  previously-published table used.

**Result, `density --force` (2h18m, 0 cell failures, fingerprint written) +
`check-density`**: national `est_mwp_rc` **5,077.9 -> 4,051.9 MWp** (-20.2%): rooftop
**2,229.9 -> 2,916.3 MWp (+30.8%)**, ground-mount **2,848.0 -> 1,135.6 MWp (-60.1%)** --
pooling had been dragging rooftop's own p_real down toward ground's, and ground's up
toward rooftop's, in every shared bin, so unpooling moved both, in opposite directions,
as predicted going in. **This also resolves the "still-open" provenance question left
by the 2026-08-06 recall/candidates re-derivation attempt above**: that attempt moved
the total to 2,327.2 MWp but failed `check-density`'s ground:rooftop ratio check for
Khyber Pakhtunkhwa and Balochistan and was reverted, unable to isolate why. The
placement-split fix is exactly the missing piece -- re-run against the fully current
candidates AND the full 19-quadrat recall reference, KP's ratio moved 3.35-8x ->
**0.49x** and Balochistan's 3.90-18x -> **2.01x**, both now comfortably inside the
3.0/5.0 warn/fail band. **`check-density` still reports FAIL, but on a different,
checked-and-confirmed-genuine mechanism**: 3 regions (Khyber Pakhtunkhwa, Balochistan,
Islamabad Capital Territory) now fail the single-cell-concentration check instead,
because shrinking the ground-mount over-inflation that used to dominate their totals
mechanically raised the visible concentration share of whatever legitimate signal
remained. Checked, not asserted: all three flagged cells are the calibration quadrats'
own cities (Peshawar, Quetta, and Islamabad's own urban core in a 10-cell federal
territory) -- see the doc above for the full per-region table. Published anyway, per
this project's own precedent for a checked-genuine plausibility failure (the original
2026-07-30 KP/Balochistan ratio finding).

Evidence atlas rebuilt: Verified **7,290.8 -> 5,466.9 MWp**, Best estimate
**14,242.6 -> 11,229.7 MWp** -- both net DECREASES despite rooftop capacity rising,
because ground-mount (54% of the old Verified tier) fell by more. `roofclf-score-national`
and roofclf's own model were untouched (`sub400-capacity`/`ge400-roof-capacity` re-run
for freshness against the corrected `candidates.parquet` but moved by <0.1%, as expected
since neither depends on the mechanisms fixed here). `atlas.CALIBRATION_BOXES["pakistan"]`
also gained two quadrats that existed on disk but were never listed
(`islamabad_northeast_calib_3p34km2`, one of the 13 quadrats the coverage-ratio/precision
fits actually trust, and `hasal_calib_1p00km2`) -- `_load_calib_boxes` now warns instead
of silently skipping a missing stem. Old atlas backed up to
`/tmp/pakistan_evidence_atlas_PRE_20260811_placement_split_backup.html` (not under
version control, session-local only).

Also generated, not yet reviewed by a human: two domain-stratified random-cell JOSM
validation batches (`results/pakistan_roofclf_validation_domain/`,
`..._outdomain/` -- the pre-existing seed-1 batch had drawn zero cells inside the
163-cell calibrated domain, see `docs/methods/roofclf-national-validation.md`) and a
KP/Balochistan largest-ground-mount-candidate JOSM layer
(`results/pakistan_groundmount_kp_balochistan_josm.geojson`,
`scripts/export_groundmount_kp_balochistan_josm.py`, new). None of these substitute for
the actual visual review; they exist so that review can happen.

### Out-of-domain AND-gate: a substitute for validation that turned out to be blocked, 2026-08-11

**The out-of-domain random-cell batch above (`results/pakistan_roofclf_validation_outdomain/`,
20 cells, seed 20260811) turned out not to be reviewable.** The owner attempted the JOSM
review it exists for and found the reference imagery too old to confirm or refute
recently-installed small PV in that population -- exactly the epoch-relative limitation
already on record for the calibration quadrats themselves (see "Rule-1 is epoch-relative"
above), now blocking the specific validation pass meant to test whether the 163-cell
density domain could be widened with evidence.

**Proposed and implemented the same day, at the owner's explicit direction: use
roofclf-AND-SPPI agreement as a substitute standard of evidence for exactly the
population that cannot currently be checked by eye.** New
`sub400_capacity.out_of_domain_and_gate_capacity` mirrors
`domain_restricted_and_gate_capacity` exactly (same pooled thresholds, same
`coverage_ratio_by_size_and_density` fit, same OSM/candidate dedup and >=400 m2
contamination filter) but applied to the 4,300 national cells OUTSIDE
`national_cell_domain()` instead of inside it. Requiring two independently-built
detectors to agree is a real, if partial, substitute for a human looking at fresh
imagery -- the same logic that already makes AND-gate agreement the Verified tier's own
standard of proof -- which is why this was wired into the **Best-estimate tier**
specifically, not treated as a one-off number.

**This is a strict extrapolation and the code says so at every level, not just in
prose.** Measured the moment this was built: of the 4,300 out-of-domain cells, **all
4,300 sit below `density.CALIBRATED_BLDG_DENSITY_KM2`'s lower edge (553.4/km2), zero
above it** -- median out-of-domain density 86.6/km2, roughly 6x sparser than the
least-dense calibrated quadrat. So this does not interpolate between calibrated
regimes, it extrapolates a coverage-ratio fit measured on 13 urban/semi-urban quadrats
(Lahore, Karachi, Faisalabad, Multan, Peshawar, etc.) across the rural remainder of the
country, which has no calibration quadrat anywhere in its density range. Rural roof
material, vegetation context and true PV prevalence could all differ from the urban
quadrats this ratio was measured on, and nothing in the pipeline could detect that if it
were true. `out_of_domain_and_gate_capacity`'s own docstring, its `summary["scope"]`
string, the atlas template's methodology prose, and a distinct dotted-outline map marker
(`is_extended`, separate from the calibrated domain's dashed `in_domain` outline) all
carry this caveat forward -- the goal is that nobody downstream can end up treating this
number with the same confidence as the calibrated one without deliberately ignoring
several places that say otherwise.

Measured result: **+1,224 MWp** (217,751 buildings across 2,983 cells, mean coverage
ratio 0.263 -- in line with the in-domain ratios). Folded into `mwp_best` only (never
`mwp_verified`) via a new `small_outdomain` grid column in `atlas.py::build_evidence_atlas`
(new optional `sub400_outdomain_buildings_path` parameter, new CLI flag
`--sub400-outdomain-cells`, wired into `earthpv sub400-capacity`'s standard output
alongside central/low so it is part of the default pipeline, not a side script). National
Best estimate moved **11,229.7 -> 12,410.4 MWp** (Verified unchanged at 5,466.9 MWp, since
this tier never touches it) -- less than the raw +1,223.6 MWp the population itself
totals, because `mwp_best`'s existing per-cell floor at `mwp_verified` means the addition
is invisible in cells where hand-mapped OSM already exceeds the model's estimate by more
than this extension provides; that floor mechanism working as designed, not a
miscalculation. Old atlas backed up to
`/tmp/pakistan_evidence_atlas_PRE_20260811_outdomain_andgate_backup.html`
and the pre-change building parquets to
`data/roofclf_national_with_sppi/pakistan/density_PRE_20260811_outdomain_andgate_backup/`
(both session-local, not under version control).

### Three new calibration quadrats, and a real lesson about what "widens the domain" means, 2026-08-11

**Attempted to widen `CALIBRATED_BLDG_DENSITY_KM2`'s lower edge with two new quadrats,
both landed inside the existing range instead -- a genuine, non-obvious finding, not a
failed experiment.** `muzaffargarh_rural_calib_1km` (1 km², picked from the densest
200x200 m building cluster inside a national cell averaging ~200 bldg/km², mapped
complete by the owner) measured **639 bldg/km²** of its own -- inside 553.4-5,258.0, not
below it. `malok_calib_4p13km2` (4.13 km², a mapper-drawn boundary near Malok, Lodhran
District, "complete as the imagery in JOSM allows") measured **1,427.8 bldg/km²** --
also inside. **The mechanism**: `national_cell_domain`'s density figure averages over an
entire 0.1° cell (~121 km²), while a real settlement is a tight cluster surrounded by
empty farmland -- so ANY quadrat boundary traced around a village or town's built-up
extent (the natural way to draw one, since that's where any PV would be) reads far
denser locally than the sparse national cells its surroundings would otherwise resemble.
Picking a *low-average* cell to build a quadrat in does not produce a *low-density*
quadrat. Directly verified this before drawing anything further: a 2km-square box at
(30.573, 71.127), in the SAME cell as `muzaffargarh_rural` but deliberately not centered
on its village cluster, measures **277.8 bldg/km²** via direct VIDA building count --
genuinely below the floor. That boundary
(`muzaffargarh_rural_wide_calib_2km_boundary.geojson`, 0 overlaps, ~1,111 buildings) is
drawn and waiting for a JOSM completeness pass; recomputing the range once it is Rule-1
would extend the floor from 553 to ~278 bldg/km², pulling roughly another 1,000+ cells
into the calibrated domain. **The actual, generalizable rule going forward**: a
range-extending quadrat needs to be sized/placed so ITS OWN average includes enough
non-built land alongside any settlement to read below the current floor -- not just
"located in a low-average cell."

**Rule 1's definition was formally amended the same day, at the owner's direction,
after declaring Malok complete.** The owner's exact words: "Malok is as complete as the
imagery in JOSM allows... the labels will not [capture] PV that was built in between the
date of the JOSM imagery and the date of the Sentinel-2 imagery we are using." This
epoch-relative bound had been documented as a narrative finding since 2026-08-05 (see
"Rule-1 is epoch-relative" above), but was never part of the RULE 1 DEFINITION itself in
`docs/calibration-mapping-protocol.md` -- now it is: the blockquote gained a second
paragraph stating a Rule-1 declaration certifies completeness "as of the mapping
imagery's capture date," not as of the model's own epoch, plus a forward-looking "Open
item" noting that closing this gap for real needs imagery contemporaneous with (or newer
than) the Sentinel-2 composite -- e.g. a tasked high-resolution commercial capture --
which JOSM's default background layers do not reliably provide. Not pursued yet;
`scripts/fraction_stale_label_audit.py` remains the interim, no-new-imagery way to bound
the size of the gap.

**Malok's inclusion shifted the trusted 13-quadrat precision/coverage-ratio set more than
just by adding itself.** Refitting `roofclf` on all 21 quadrats (96,857 -> 102,748
buildings) moved every quadrat's predicted rate slightly, which moved `rate_ratio`
(predicted/true adoption rate) enough to cross `select_calibrated_quadrats`'s [0.5, 2.0]
trust band in three places at once: **Multan dropped out** (rate_ratio 2.016, just over
the cutoff -- previously just under), while **Sialkot** (1.337), **Hasal** (exactly
0.500) and **Malok** (0.858) newly qualify. Net: trusted set 13 -> **15** quadrats, a
real compositional change, not a simple addition -- checked directly (`select_calibrated_
quadrats` re-run), not assumed. `muzaffargarh_rural` itself never entered this set
(rate_ratio 2.903, same overestimate-side exclusion as Quetta/Sialkot/Sundar historically)
despite being Rule-1 complete -- Rule-1 status and precision-trust are independent gates,
as documented throughout this file; `select_calibrated_quadrats` does not check Rule-1 at
all, only `rate_ratio`, which is exactly why Malok's Rule-1 declaration was confirmed with
the owner before letting it enter this set (see the conversation this session -- a
non-Rule-1 quadrat's negatives are not trustworthy, and this selection function has no
guard against that on its own).

Re-ran the full downstream chain (`sub400-capacity`, `ge400-roof-capacity`, the evidence
atlas) against the 21-quadrat refit. All three domain-restricted components moved down,
consistent with losing Multan (an industrial estate, historically high coverage ratio)
from the trusted set: sub-400 central (Best) 3,906.8 -> **3,870.3 MWp**, sub-400 AND-gate
(Verified) 2,257.1 -> **2,090.5 MWp**, out-of-domain AND-gate extension (Best only)
1,223.6 -> **1,148.8 MWp**, >= 400 m² roofclf rooftop (in-domain) -> **3,156.4 MWp**
(precise prior in-domain figure not independently logged this session; back-calculated
from the measured -303.2 MWp national `mwp_large` delta at ~3,459.6 MWp). Evidence atlas:
Verified **5,466.9 -> 5,300.3 MWp** (-3.0%), Best **12,410.4 -> 11,997.8 MWp** (-3.3%).
Neither `CALIBRATED_BLDG_DENSITY_KM2` (still 553.4-5,258.0) nor the domain cell counts
(163 sub-400, 136 atlas-joined) changed -- this move is entirely precision/coverage-ratio
recalibration from the richer, still-non-widening quadrat set, not a domain-size effect.
Backups: `/tmp/pakistan_evidence_atlas_PRE_20260811_malok_backup.html`,
`data/roofclf_national_with_sppi/pakistan/density_PRE_20260811_malok_backup/`,
`data/roofclf_PRE_20260811_muzaffargarh_rural_backup/` (all session-local).

Registered both new Rule-1 quadrats in `results/calibration_quadrats.csv` and
`atlas.py::CALIBRATION_BOXES["pakistan"]` (21 and 21 respectively, `muzaffargarh_rural`
and `malok`). `imagery_layer`/`imagery_date` remain unpopulated for both -- the
known gap documented since 2026-08-01 is still open; neither quadrat's JOSM background
layer/capture date was recorded when they were mapped.

### A quadrat that actually widened the domain, same day (2026-08-11)

**The third candidate from the same session -- `muzaffargarh_rural_wide_calib_2km`,
deliberately drawn to include open farmland alongside a village rather than trace a
settlement's built-up edge -- measured 277.75 bldg/km², genuinely below the 553.40 floor,
confirmed via direct VIDA building count before asking the owner to map it.** The owner
mapped it and reported zero PV found. Registered as the first confirmed-zero quadrat in
the set (`n_pv_buildings=0`, `base_rate=0.0`, `n_installations=0`) -- real, useful
ground truth: a true rural non-adoption population, distinct from every other quadrat's
"how much did we miss" question.

**The OSM pull for this box could not go through the normal path at all, which is worth
recording as a real tooling gap, not just a workaround.** `build_overpass_labels` hard-
raises on ANY empty Overpass response by design (`scripts/new_calibration_quadrat.py`'s
own comment: "an empty response counts as a failure, not as an empty box") -- because
one bad response cannot be distinguished from a genuinely empty box, per the 2026-08-05
Lahore truncation incident. That design has no path to ever accept a *real* empty result,
no matter how many times it is confirmed. Resolved by gathering independent evidence
outside that code path: **8 separate, successful (non-timeout) Overpass queries across
~20 minutes, using both the script's own retry loop and a direct manual query against
`earthpv.overpass`'s primitives, all returned exactly 0 elements** with zero contradicting
non-zero responses anywhere -- stronger confirmation than the truncation check the
codebase already trusts (which accepts a single non-zero confirming query against one
prior count). On that basis, a schema-matching empty `_overpass_solar.parquet` was
written by hand (matching `fetch_solar_overpass`'s exact column set, verified to
round-trip through `roofclf.load_quadrat` identically to a normal pull) rather than
leaving the box unregistered. `scripts/new_calibration_quadrat.py` still has no automated
way to accept a confirmed-zero result -- worth fixing if another genuinely-empty box comes
up, since manually reconstructing the schema by hand does not scale.

**This is the widening the two 2026-08-11 attempts above were looking for.**
`CALIBRATED_BLDG_DENSITY_KM2`'s lower edge moved **553.40 -> 277.75** bldg/km²
(`density.py`), growing the roofclf domain restriction from **163 to 646** of Pakistan's
4,463 national cells (3.7% -> 14.5% of cells, 24.5% -> 48.9% of national buildings) --
the largest single jump in this constant's history, from ONE quadrat, because it targeted
the actual mechanism (a quadrat's own average must include enough non-built land to read
below the floor) rather than a location's surrounding-cell average. `select_calibrated_
quadrats`'s trusted precision set moved again too, in the same way retraining always
perturbs it: 15 -> 14 (Hasal dropped out this time; the new quadrat's own rate_ratio is
correctly excluded as well, since 0/0-adjacent division against a true zero base rate
produces an enormous ratio, guarded by the existing `max(y.mean(), 1e-9)` floor in
`roofclf.py` so this did not crash anything, just correctly excluded it).

Re-ran the full chain again (`sub400-capacity`, `ge400-roof-capacity`, the evidence
atlas) against the widened domain: sub-400 central (Best) 3,870.3 -> **5,556.8 MWp**,
sub-400 AND-gate (Verified) 2,090.5 -> **2,676.2 MWp**, out-of-domain AND-gate extension
(now describing only the smaller remaining 3,817-cell out-of-domain population) 1,148.8
-> **574.7 MWp**, >= 400 m² roofclf rooftop (in-domain) -> **5,048.9 MWp**. Evidence
atlas: Verified **5,300.3 -> 5,886.0 MWp** (+11.0%), Best **11,997.8 -> 14,462.0 MWp**
(+20.5%) -- both real increases from genuine new calibration coverage, not
recalibration noise like the Malok move earlier the same day. Backups:
`/tmp/pakistan_evidence_atlas_PRE_20260811_widen_domain_backup.html`,
`data/roofclf_national_with_sppi/pakistan/density_PRE_20260811_widen_domain_backup/`,
`data/roofclf_PRE_20260811_wide_backup/` (all session-local).

**The generalizable lesson, stated once for reuse**: a calibration quadrat widens
`national_cell_domain`'s density floor only if its OWN average density (not the
surrounding national cell's average) reads below the current floor. A boundary traced
around a settlement's built-up extent -- the natural, arguably only sensible way to draw
a mapping box, since that is where any PV would be -- will essentially never do this,
because villages and towns are inherently dense and it is the land *between* them that
pulls the country average down. A range-extending quadrat has to be sized and placed to
average in enough of that non-built land on purpose.

### A false "confirmed zero" corrected, and a second widening quadrat, same day (2026-08-11)

**The "confirmed zero" declaration for `muzaffargarh_rural_wide_calib_2km` earlier this
session was wrong -- and the reason why is a real gap in the tooling, not just an unlucky
guess.** The owner went back to the box, found PV that the original JOSM sweep had
missed, mapped it, and reported the correction. Re-pulling once the new mapping had
propagated to Overpass found **12 installations** (7 rooftop, 5 ground; 9 of 1,111
buildings flagged `has_pv`, base_rate 0.81%), cross-confirmed cleanly this time ("wrote
12 features; confirming query sees 12"). What actually happened the first time: 8
independent, non-timeout Overpass queries over ~20 minutes all genuinely returned 0
elements *at that moment*, because the box genuinely held 0 OSM-mapped installations
*at that moment* -- the queries were not lying, the underlying map data was incomplete.
"Repeated confirming queries against live OSM" and "a human completeness sweep" answer
different questions: the former can only ever attest to what is currently mapped, never
to whether mapping is finished. Rule 1 exists precisely because that second question
needs a person's declaration, and this is a concrete case of what happens when that
declaration is skipped in favor of a data-side proxy, however well-corroborated the
proxy appears. **Practical consequence for this correction**: `rate_ratio` (3.39) keeps
`muzaffargarh_rural_wide` out of the trusted precision-calibration subset either way, so
the correction did not need to touch any coverage-ratio or precision number directly --
only the domain-restriction share that naturally follows from the (unchanged) building
count. `atlas.py::CALIBRATION_BOXES`'s comment for this quadrat now documents the
correction in place rather than presenting the wrong number as settled history.

**A second range-extending quadrat, `khairpur_rural_calib_2km`, was added the same
session using the exact same verified method**: a 4 km² box deliberately including
farmland, its own density checked directly against VIDA buildings (141.0 bldg/km²,
564 buildings) *before* asking the owner to map it, rather than trusting a surrounding
cell's average. Chosen in Khairpur District, Sindh specifically for geographic
diversity -- every other 2026-08-11 quadrat is in or near Muzaffargarh, Punjab. Mapped
and confirmed the same way: 3 installations, all ground-mount, median 22.1 m²,
base_rate 0.53%, `rate_ratio` 4.36 (also outside the trusted precision subset). Its OSM
pull needed one retry for a clean cross-check (the first attempt's confirming query
timed out rather than disagreeing, so it was correctly treated as unverified rather than
accepted).

**Combined effect of both quadrats**: `CALIBRATED_BLDG_DENSITY_KM2`'s floor moved
**277.75 -> 141.00** bldg/km², growing the roofclf domain restriction from **646 to
1,680** of Pakistan's 4,463 national cells (14.5% -> 37.6% of cells, 48.9% -> 78.6% of
national buildings) -- by far the largest cumulative widening in this constant's
history, done in two verified steps in one session. Re-ran the full chain again:
sub-400 central (Best) 5,556.8 -> **6,531.3 MWp**, sub-400 AND-gate (Verified)
2,676.2 -> **2,928.8 MWp**, out-of-domain AND-gate extension (now describing a much
smaller remaining 2,783-cell population) 574.7 -> **278.0 MWp**, >= 400 m² roofclf
rooftop (in-domain) -> **6,427.2 MWp**. Evidence atlas: Verified 5,886.0 -> **6,138.6
MWp** (+4.3%), Best 14,462.0 -> **16,441.4 MWp** (+13.7%). `select_calibrated_quadrats`'s
trusted subset shifted again too (now 15, with Multan back in and Hasal out relative to
the previous count) -- the same perturbation-from-retraining pattern documented earlier
this session, not a new mechanism. Backups: `/tmp/pakistan_evidence_atlas_PRE_20260811_
khairpur_and_correction_backup.html`, `data/roofclf_national_with_sppi/pakistan/
density_PRE_20260811_khairpur_and_correction_backup/`, `data/roofclf_PRE_20260811_
wide_correction_and_khairpur_backup/` (all session-local).

### The evidence atlas now reports 90% intervals on both tiers, 2026-08-11

**The project's documented primary output was reporting two bare point estimates, while
the older, superseded `build_atlas`/`_build_estimator_atlas` path had carried credible
intervals all along.** That was backwards, and the entries above are the argument for
fixing it: Verified and Best each moved 20-35% five separate times in this one session
(placement-split calibration, dissolved OSM, Malok, two domain widenings), purely from
recalibration, and a reader of the page had no way to see that the numbers were that
soft. `atlas._evidence_uncertainty` now composes a 90% interval per tier from every
uncertainty this pipeline actually measures, and the page shows it under each KPI and in
the hero. Point estimates are **byte-identical** -- verified by diffing the rebuilt
atlas's embedded totals against the pre-change published atlas (`mwp_verified` 6,138.6,
`mwp_best` 16,441.4, every component unchanged) -- this pass adds intervals and changes
no published figure. Result: **Verified 6,138.6 MWp (90% 5,096-7,498), Best 16,441.4 MWp
(90% 12,883-19,147)**.

Five things about how it is composed that matter more than the numbers:

- **Correlated terms share one draw vector, deliberately.** One module-constant draw
  multiplies every module-area component and one land draw every site-area component,
  because it is the same physical constant in all of them -- drawing per component would
  cancel most of its effect out, which is exactly wrong for a constant applied to a whole
  country at once. Same reasoning for the coverage ratio: all four roofclf-based
  components (`sub400` central, `sub400` AND-gate, out-of-domain AND-gate, >= 400 m²
  rooftop) are fit on the SAME quadrats, so `sub400_capacity.COVERAGE_BOOTSTRAP_SEED` is a
  fixed shared constant and `atlas._aligned_coverage_factors` indexes every component with
  the same `arange(n_draws) % n_boot`, so replicate b means the same resampled quadrat set
  everywhere. Treating four estimates built from one calibration set as independent would
  report a Best interval narrower than the evidence supports.
- **The coverage ratio's error is measured by resampling QUADRATS, not buildings**
  (`sub400_capacity.coverage_ratio_bootstrap_factors`, 200 replicates, ~7 s). A
  building-level bootstrap over ~100k rows that share a mapper, a settlement pattern and
  one imagery epoch would report an interval far too narrow to be honest; quadrat
  composition is the thing that has demonstrably moved these numbers (Malok alone shifted
  the trusted set 13 -> 15 and every component 1-8%). Returns dimensionless multiplicative
  factors so the atlas composes them without touching quadrat data and the kWp constant
  cancels. A quadrat drawn twice genuinely counts twice -- its rows are duplicated under
  synthetic labels rather than deduplicated by `isin`, which would silently degrade the
  bootstrap into an m-out-of-n subsample. Measured factor CI90: central 0.885-1.151, AND-gate
  0.848-1.169, out-of-domain 0.726-1.203, >= 400 m² rooftop 0.650-1.105.
- **The bootstrap mean is NOT 1.0 for the >= 400 m² component (0.934) and that is a finding,
  not a defect** -- the point fit uses every calibrated quadrat, while a resample often
  omits whichever ones carry the highest coverage in the largest size bins, so the
  published point sits at the high end of what equally plausible quadrat sets produce.
  Deliberately not bias-corrected away; a factor of 1.0 still falls inside every
  component's own interval, so the published number stays inside its reported range while
  the skew stays visible (`factor_mean` in the atlas's `totals.uncertainty`).
- **One term is a stated judgement, not a measurement, and is isolated so it can be
  audited**: `atlas.OUTDOMAIN_EXTRAPOLATION_CI90 = (0.25, 1.25)`, a uniform factor on the
  out-of-domain AND-gate component alone, because all 2,783 out-of-domain cells sit BELOW
  the calibrated density band and no quadrat constrains their coverage ratio in either
  direction. Skewed down rather than symmetric (the plausible failure is over-crediting
  rural roofs). `mwp_best_ci_without_extrapolation` is reported alongside so its
  contribution is visible -- and measured, it is negligible: 12,981-19,345 without it
  against 12,883-19,147 with it, because the component is only 278 of 16,441 MWp. **The
  Best interval is dominated by the >= 400 m² rooftop coverage ratio (6,427 MWp, 4,055-7,668)
  and the sub-400 m² central component (6,531 MWp, 5,266-7,975), not by the extrapolation
  everyone would suspect first.**
- **A silent zero-width interval was found and fixed on the way.** `meta.json` carried
  `total_est_mwp_rc_lo/hi` and `..._rc_roof_lo/hi` but never a `..._rc_ground` pair, so
  ground-mount (1,135.6 MWp) was contributing an interval of exactly zero width -- on the
  component whose conversion constant has by far the WIDEST prior in the pipeline (land
  0.035-0.075, +-43%, against module's +-17%). `density._unc_mwp_ci` now emits
  `est_mwp_rc_ground_lo/hi`, differenced per draw (the two summary intervals cannot be
  subtracted; the draws can, and are the same draws, so it is exact). Until a density
  re-run exists, the atlas substitutes the land prior alone for it, logs a warning, and
  records it in `segmentation_estimators_using_kwp_prior_only` -- an explicit degradation
  rather than a silent one. That alone widened Best from 12,999-19,118 to 12,926-19,293
  under the lognormal fallback, and to 12,883-19,147 once the exact draws landed.

Also added, for exactness on the next density run: `density.aggregate` writes
`density/total_draws.parquet`, the national draw VECTORS (1000 floats per estimator, not
the n_cells x n_draws matrix) for `est_mwp_rc`/`_roof`/`_ground`/`cal_total`.
`atlas._segmentation_total_factors` prefers it and falls back to a lognormal matched to
meta's lo/hi, reporting which path it used in `segmentation_factor_method`. The fallback is
what the current atlas uses (no density run has written the file yet); it reproduces the
published point and interval but assumes a lognormal shape between them and drops the
roof/ground correlation, which slightly narrows their sum.

`_evidence_uncertainty` **asserts** that its component point values sum to each published
tier total (up to an explicit `best_floor_offset_mwp` carrying `mwp_best`'s per-cell floor
at `mwp_verified`, 739.4 MWp here, treated as deterministic). That assertion is the guard
against the failure mode this whole function invites: someone adds a component to the atlas
and not to the uncertainty composition, and the page then shows an interval for a different
quantity than the number beside it.

CLI: `--coverage-boot N` on both `sub400-capacity` and `ge400-roof-capacity` (default 200,
0 disables -- and disabling it makes the atlas interval silently NARROWER, which is why
`totals.uncertainty.coverage_bootstrap_missing` records any component that arrives without
one). Backups: `results/pakistan_pv_evidence_atlas_PRE_20260811_uncertainty_backup.html`,
`data/roofclf_national_with_sppi/pakistan/density_PRE_20260811_uncertainty_backup/`.

### Validating against a complete register: Germany and MaStR, 2026-08-11

**New module `mastr_validation.py` + `earthpv validate-mastr`, and the first
externally-verifiable check on the claim this project's whole two-detector architecture
rests on.** Full writeup: `docs/methods/mastr-validation.md`. `calibrate.py` already
calibrated a probability *raster* against MaStR; nothing had ever checked the parts
downstream of it. Germany matters because MaStR registration is legally mandatory, so
per-municipality rooftop capacity there is the answer rather than a sample -- the one thing
21 purposive, owner-attested, epoch-relative Pakistani quadrats can never be.

- **The detection-floor claim holds, and is now measured at the right threshold.** The
  project has been quoting MaStR's "72.6% of rooftop capacity is in units <= 100 kWp" as a
  proxy. 400 m² of module at 0.18 kWp/m² is **72 kWp**, and the exact share below that is
  **65.5% of rooftop capacity** (and 97.2% of installations), on 4,411,015 rooftop units
  totalling 74.8 GWp. So an instrument that only sees above the floor is describing roughly
  a third of what a "rooftop solar" headline implies. The <= 100 kWp row reproduces 72.6%
  exactly, which is the check that this module's filters match
  `mastr.aggregate_gemeinden`'s. **Quote the capacity share, not the count share** -- 97.2%
  of installations against 65.5% of capacity is a factor-of-relevance difference and the
  count version overstates the gap badly.
- **That share is much less transferable than the tidy national percentage suggests.** The
  project transfers it to Pakistan as a constant (the MaStR-shape transfer, implying ~5.9
  GWp). Across 10,675 German municipalities with >= 100 kW: median 0.762, **5th-95th
  percentile 0.249-1.000**, SD 0.235, p90/p10 ratio 2.69. And it is not just noise --
  **Spearman -0.42 against a municipality's own total capacity**: capacity concentrates
  where large industrial roofs are, and those have a lower small-PV share, so the
  unweighted mean over municipalities (0.724) sits 7 points ABOVE the capacity-weighted
  national figure (0.655). Any transfer reasoning from "a typical place" rather than from a
  capacity-weighted total is biased upward.
- **German OSM cannot serve as the complete reference, measured non-circularly.** The trap
  worth recording: `data/calibration/completeness.parquet`'s `completeness` column IS
  `0.18 * osm_area / kw_rooftop`, so selecting "well-mapped" municipalities with it and
  then measuring `kw_rooftop / osm_area` to test that same 0.18 is selecting on the
  estimator. Measuring completeness by unit COUNT instead (no area, no constant):
  **3.6% of registered German rooftop units are mapped in OSM**, and the well-mapped tail
  is both thin and useless for calibration -- 55 municipalities at >= 30% completeness, 18
  at >= 50%, 3 at >= 80%, with the pooled implied kWp/m² swinging **0.239 -> 0.083 -> 0.069**
  across those cutoffs and per-municipality values spanning 0.02-0.99 against the project's
  0.18. That is not sampling noise around a true value: nothing in OSM says whether a
  `generator:source=solar` polygon outlines the array or the whole roof, so the ratio
  measures mapper convention. **`DEFAULT_KWP_PER_M2_MODULE` therefore stays as calibrated;
  this route is a measured negative result, not a blocked one.** Two things travel beyond
  Germany: "Germany is well mapped in OSM" is true of buildings and false of rooftop PV,
  and the same array-vs-roof ambiguity applies to Pakistan's own OSM reference, which is
  used both as a recall denominator and as the Verified tier's population.
- **The end-to-end per-municipality comparison is written and wired but cannot run yet**,
  and the blockers are data acquisition, not code: `data/composites/germany/` is absent
  (the sibling project has **14 of the 76** MGRS tiles Germany needs, and
  `data/predictions/germany/prob/` holds 4 tiles in a per-MGRS-tile layout `density` cannot
  read); `data/vida/DEU.parquet` is absent so there is no small-roof building layer for
  `roofclf`; and all 21 calibration quadrats are Pakistani, which the 3.6% figure above
  means German quadrats must be *mapped* rather than derived from an OSM pull.
  `validate_density_against_mastr` reports its own coverage and **refuses to call a
  partial-coverage result national** -- not hypothetical, since a 4-of-76-tile run would
  produce a national sum ~5% of truth and a slope that reads as catastrophic model failure
  rather than as missing imagery.

**This project's first test file, `tests/test_mastr_validation.py`**, exists because the
harness above is otherwise entirely unexercised: it feeds the register back through it
synthetically (a grid carrying exactly MaStR's capacity must return slope 1.0, half of it
0.5, a 200-municipality grid must be refused as non-national), which pins the units, the
origin-forced fit, the kW->MWp conversion and the coverage guard. It immediately earned its
keep by catching a real bug: a Spearman over a constant column returns NaN, and
`json.dumps` writes a bare `NaN` that strict JSON parsers reject, so the report file would
have been unreadable in exactly the degenerate case a fixture always produces (fixed via
`mastr_validation._num`). Run it with
`.pixi/envs/default/bin/python tests/test_mastr_validation.py` (pytest is still not a
declared dependency, so the file also runs as a plain script).

One drive-by fix in the same pass: `scripts/screenshot_pages.py` now pins
`ui.prefersReducedMotion` in its throwaway Firefox profile. The atlas templates animate
their hero figure with a count-up and `--screenshot` fires mid-animation, so **every
committed atlas PNG has been showing a wrong hero number for months** (the previous one
read 885 against a real 11,230; the first re-shoot this session read 4,818 against 16,441).
Each template already short-circuits its count-up to the final value under reduced motion,
so asking for it is the whole fix -- no wait, no template change.
`docs/assets/figures/pakistan_evidence_atlas.png` is re-shot and correct;
**the other pages' PNGs still carry the old defect until `pixi run docs-screenshots` is
re-run for them.**

### Documentation restructured around the shipped workflow, 2026-08-11

**At the owner's request: make the current success workflow the main content, update the
experiments page and the closed issues, and delete what is no longer relevant.** The site
had accumulated the standard failure mode of a research log used as documentation -- a
438-line `how-it-works.md` with the experiment register buried two thirds down, a
`docs/notes/index.md` status table whose rows had gone factually wrong, five issue docs
absent from nav entirely, and several write-ups whose headline claim had since been
reversed with nothing on the page saying so.

Structure now runs **Results -> How it works -> Setup -> Experiments -> Open questions**,
in that nav order deliberately: the output first, the working pipeline second, the history
last.

- **`docs/experiments.md` (new)** is the canonical register, split out of
  `how-it-works.md` (179 lines cut) and expanded to cover every experiment including the
  ones that previously only existed inside an issue doc. 38 rows with a verdict each
  (`shipped` / `partial` / `rejected` / `superseded`, reusing `extra.css`'s existing
  `.outcome` badge classes), then prose sections for what worked and why, and a table
  linking every deep write-up. `how-it-works.md` is now purely a description of the
  pipeline as it runs.
- **`docs/open-questions.md` (new)** replaces the deleted `notes/index.md`. 12 ranked open
  items plus a "known defects carried on purpose" section (the 3 `check-density`
  concentration failures, the `buildings.geoparquet` 46.4% structural gap, NaN-scored
  buildings in tile-overlap strips, the two deleted checkpoints). The rule stated on the
  page: an item belongs here only if a concrete next step exists and has not been taken,
  and when it closes its row is deleted rather than annotated, moving to the experiments
  register with a verdict.
- **Every one of the 14 surviving `docs/issues/*.md` now carries a dated status banner**
  (`!!! success` shipped / `!!! info` closed negative / `!!! warning` superseded /
  `!!! note` open) stating what state the doc describes and what has changed since. This
  was the single largest honesty gap: `roofclf-national-deployment-and-temporal-features.md`
  still led with "roofclf's national output is not folded into density.py or the published
  capacity atlas", a decision reversed on 2026-08-07, and `sppi-spectral-index-evaluation.md`
  was titled "not adopted for detection" while SPPI defines the Verified tier.
- **Three docs deleted**, on the rule "remove only where every operative claim is now false
  AND the evidence is preserved elsewhere": `notes/index.md`,
  `issues/osm-replacement-and-sppi-capacity.md` (all three parts superseded; Part 3's
  duplicate-match bug fixed via `groupby(...).idxmin()`, Part 2's "not yet national" false
  since SPPI went national) and `issues/density-force-recompute-plausibility-fail.md` (its
  stated cause -- a `no_building` aggregation regression -- was displaced by the measured
  pooled-calibration cause, and its closing "check-density now passes" is false of the
  published state). Their residual open items moved to `open-questions.md`.
- **`docs/methods/density.md`'s Gilgit-Baltistan admonition was rewritten**: it still
  asserted the ratio failures were an unlocated `density.py` regression. Corrected to the
  measured cause, with the still-valid separate justification for the GB exemption and the
  current 3-concentration-failure state.

**Every reference to a deleted or nonexistent doc was retargeted, not left dangling**, and
this surfaced two paths that had never existed at all:
`docs/issues/small-pv-step-signal.md` (referenced from `scripts/sppi_growth_map.py`,
`configs/aoi.yaml` and `boom-window-stacking-experiment.md`) and
`docs/issues/glint-alignment-check.md` (referenced from `src/earthpv/glint.py`, where the
real artifact is `scripts/glint_alignment_check.py`). Also fixed: two links in
`pakistan-calibration-boxes.md` to a slug that never existed, and three links to the moved
`how-it-works.md#experiments` anchor. `mkdocs build --strict` now runs with **zero**
warnings, zero orphaned pages and zero broken anchors, where before it reported 6 orphans
and 2 bad anchors.

Numbers refreshed throughout from the artifacts rather than copied forward: **23 quadrats,
all Rule-1, 63.9 km², 15,494 installations, 104,423 buildings**; roofclf **0.857 AUC /
0.830 within size band** at threshold **0.2443**; atlas **Verified 6,138.6 (90%
5,096-7,498) / Best 16,441.4 (90% 12,883-19,147)**. `docs/index.md`'s stat strip was
carrying 11,230 MWp and 0.874 AUC, and `README.md` 5,467 / 11,230 -- both several
recalibrations stale. The MaStR **65.5%** figure is now the headline justification for
running two detectors, on `index.md`, `README.md` and
`docs/methods/mastr-validation.md`, replacing the ~72.6% proxy.
`docs/results/growth.md` was un-commented back into nav with an admonition marking it a
secondary product built partly on the unpromoted fraction head.

### Glint now uses per-pixel SCL cloud flags, 2026-08-11

**Cloud false positives were reported from manual review of glint detections. The imagery
already carried the mask to fix it and the production glint path was not reading it.**
Sentinel-2 L2A ships the Scene Classification Layer (SCL) alongside the reflectance bands
(8 cloud medium, 9 cloud high, 10 thin cirrus, 3 cloud shadow); `imagery.py` has always
used it to build the segmentation composites, and `scripts/glint_cell_pixel_scl_coherence_
pilot.py` prototyped per-pixel SCL masking for glint in particular, its header noting
"clouds still looked like a big issue". `glint.py` itself consulted **no** per-pixel cloud
information at all -- only the whole-scene `eo:cloud_cover` STAC property at a default
cutoff of **80**, i.e. it accepted 79%-cloudy scenes and leaned entirely on the annulus.

**Measured first, on 4,616 cached scene rows (`data/glint/detail.parquet`), and it
reframes the problem: the spike rate does NOT rise with scene cloudiness** -- 4.37% /
5.35% / 5.47% / 2.24% / 2.62% across the 0-10 / 10-30 / 30-50 / 50-70 / 70-100%
`eo:cloud_cover` bands, and spike scenes are marginally *less* cloudy than average (median
12.7 vs 15.8). So the false positives are not cloudy scenes slipping past a threshold;
they are **localized** cloud over one target in an otherwise ordinary scene, which
whole-scene metadata cannot see even in principle. Raising or lowering `max_cloud` would
not have helped, and per-pixel data was the only way through.

Implemented: `_read_target_scl` + `SCL_CLOUD_CLASSES`, wired into BOTH read paths
(`_scene_row` for the per-target path, `tile_scene_series_batch`'s `_process_item` for the
country-scale batched one) behind `use_scl=True`, recording `scl_cloud_frac`,
`scl_ring_cloud_frac` and `scl_npx` per scene. `annotate_spikes` gained
`max_ring_cloud_frac` (default `MAX_RING_CLOUD_FRAC = 0.20`) and a `cloud_free` column;
`spike_fit` now returns `n_cloud_vetoed`. Both existing batch call sites
(`postprocess.add_glint_prior`, `roofclf_glint`) pass keyword args, so they inherit the
default with no change.

Four design decisions worth not undoing:

- **The gate is on the ANNULUS, not the target.** SCL classifies bright saturated pixels as
  cloud and a real specular glint often *is* saturated, so a target-side veto would discard
  exactly the events this detector exists to find. Cloud is spatially extended: if cloud
  brightened the target, its surroundings are almost certainly cloudy too. `scl_cloud_frac`
  is recorded for study but vetoes nothing.
- **Classes 1 (saturated/defective) and 11 (snow) are deliberately NOT treated as cloud**,
  for the same saturation reason and because snow is persistent rather than per-date (the
  clear-scene baseline already absorbs it) and is a different problem.
- **A vetoed scene leaves the clear-sky baseline too**, not just the spike set, or a
  cloud-brightened date would inflate the baseline and mask real glints.
- **NaN means unknown and never vetoes**, so a series pulled before this existed behaves
  exactly as it did, and an unreadable SCL degrades to the old geometric tests rather than
  silently discarding the scene. Below 5 surviving clear scenes `annotate_spikes` warns
  rather than reporting a confident zero.

Cost: one extra asset read per scene, about +50% network time at the default two bands.

**Two latent bugs fell out, both found by the measurement harness rather than by reading:**
(a) `annotate_spikes` short-circuits on all-missing input and used to return the bare input
frame, i.e. WITHOUT `clear`/`spike`, so the documented composition
`fit_best_orientation(annotate_spikes(series))` raised `AttributeError` for any target whose
series had no usable reflectance stats -- `spike_fit` never hit it because it checks
`.empty` first. Now the empty return carries every column the function promises, and
`fit_best_orientation` guards the case as well. (b) A cautionary one about this project's
own read path: a **pandas index-alignment bug in the measurement script** (a GeoSeries built
with a fresh 0-11 index assigned into a frame still carrying its original 12-23 index)
produced all-NaN geometries, and every read then returned `(nan, nan, 0)` -- which is
indistinguishable from "the detector correctly found nothing". It was caught only because a
target with 24 known spikes reported zero. Any glint result where `npx` is 0 across a whole
series should be read as a plumbing failure, not as an absence of PV.

### Optimal-imagery-date glint boost for roofclf: tested, negative, 2026-08-11

**Owner's idea: pick the Sentinel-2 date when panels are geometrically able to glint and
feed that imagery to `roofclf`, so that in dense urban blocks many installations brighten at
once and the signal-to-noise ratio rises. Well motivated -- `roofclf` reads a dry-season
MEDIAN composite, which is built to suppress exactly the transient specular events that mark
a panel -- and it is also the right correction to the earlier cell-aggregate glint failure
(that used a 90th-percentile statistic over a whole 300 m cell, which only moves if ~10% of
the cell brightens; this is a per-building feature instead). Measured in two steps, both
negative, with the reason being geometry rather than anything fixable by processing.**

**Step 1, the ceiling (`scripts/glint_observability_ceiling.py`, geometry only, no pixel
reads).** Sentinel-2 views near-nadir, so the pose that reflects the sun into the sensor is
roughly tilt = sun_zenith/2, azimuth = sun azimuth at the ~10:30 overpass: a narrow locus,
fixed by the calendar. Measured from real granule angles over 2 years at all 23 quadrats:
only a **median 13.2% of a plausible south-facing installed population (range 6.7-23.6%)**
can ever satisfy it, and the **single best date reaches 1.0-1.8%**, which kills the "one
optimal date" framing specifically. A textbook south-facing array at tilt 30 (i.e. tilt =
latitude, standard practice) has a minimum misalignment of **8.6 deg across the entire
archive** -- it never glints; at tilt 20 it reaches 0.3 deg and does. Sensitivity across
assumed pose priors: 7.6-14.3% median, so the conclusion is not an artifact of one
assumption.

Three things worth keeping from Step 1:

- **The installed pose distribution has to be ASSUMED and the project's own pose survey
  cannot supply it.** Those 192 poses were fitted FROM observed glints, so every one
  satisfies the glint condition by construction; measured here, the survey's azimuths sit
  inside the observable band, which is what censoring predicts rather than installer
  practice. Also found while reading it: the survey stores each fit **plus its mirror
  image** (96 of 192 rows, azimuth mean exactly 180.000) because the specular condition at
  near-nadir view is degenerate in azimuth. De-mirrored, the survey median is tilt 14.8 /
  az 163.7.
- **The between-quadrat spread is driven by how many relative orbits cover the point, not by
  latitude**: Sialkot 530 scenes -> 23.6% ceiling, Lahore 156 scenes -> 7.5%. More orbits
  means more view azimuths, which widens the band. Also not improvable by processing.
- **An earlier estimate of 29% was wrong and is superseded.** It pooled granule geometry
  across DIFFERENT target locations, but a building only ever sees the geometry at its own
  position. Per-location, Lahore is 7.5%. Two other harness bugs of the same family were
  caught the same way: deduping scenes by DATE rather than by minute collapses same-day
  different-orbit scenes and understated the ceiling ~4x, and a pandas index-alignment slip
  (GeoSeries with a fresh 0-11 index assigned into a frame indexed 12-23) produced all-NaN
  geometries whose reads returned `(nan, nan, 0)` -- indistinguishable from "the detector
  correctly found nothing", caught only because a target with 24 known spikes reported zero.

**Step 2, the feature (`scripts/glint_date_roofclf_feature.py`).** Lahore quadrat, 6.61 km2,
13,500 buildings, 3,432 with mapped PV -- the densest ground truth in the project and exactly
the dense-urban case the idea targets. Top glint-window scenes pulled (SCL-gated for cloud),
per-building max across them, formed as both a ratio and an excess over the same building's
composite brightness, evaluated on a **west/east spatial holdout** (neighbours 20 m apart
share pixels and roof material, so a random fold would report the optimism of memorising
neighbourhoods). Standalone the feature does separate PV, 0.613 AUC -- but **0.528 within
roof-size band**, i.e. nearly all of it was size. Incremental on top of `MODEL_FEATURES`:
size-controlled AUC **0.7875 -> 0.7879**, plain AUC 0.8925 -> 0.8933. The same nothing
epoch-jump and step-change returned, for the same reason: at most a few percent of buildings
can carry the signal, so there is nothing to learn.

Documented with three generated figures (`glint_pose_window`, `glint_observability`,
`glint_date_auc`, light+dark via `build_docs_figures.py`) and a real before/after gallery
(`scripts/glint_date_gallery.py` -> `docs/glint_examples_S2_glintdate/`) showing the five
best-case Lahore buildings on the predicted glint date against the nearest clear scene 5 days
earlier, one shared colour stretch: **nothing flares**. Best cases rather than a random
sample deliberately, since a random sample invites "you did not pick the ones that glint".
Full writeup: `docs/methods/glint.md`'s "Can a predicted glint date boost the roof
classifier?".

**What survives and should NOT be read as killed by this**: per-locality pose calibration
(if one installer did a subdivision, that locality's own pose may fall in the observable band
even though a national average does not), and glint's existing role corroborating individual
large arrays, where detection reaches 73% above 50,000 m2. What is dead is using glint to
lift the small-rooftop classifier.

### Glint opportunity normalisation (shipped) and glint-mined hard negatives (rejected), 2026-08-12

**Two follow-ups to the glint work, one a real win and one a clean negative.**

**1. Opportunity-normalised glint sensitivity -- SHIPPED (`src/earthpv/glint_opportunity.py`).**
`capacity_calibration`'s glint inversion divides a candidate bin's validation rate by that
bin's *sensitivity*, taken as a per-bin constant from the 500-target OSM-confirmed study.
Measured 2026-08-12: sensitivity is not a constant of the bin, it is a function of how many
chances a target got, and pooling divides two rates measured under different exposure.
Expected opportunity `E` (scene count x pose-compatible fraction) has mean 6.0 and range
1.8-25.4 across the 499 study targets. Splitting each size bin into opportunity tertiles:
5k-50k m2 goes 0.036 / 0.321 / **0.538**, >50k goes 0.129 / 0.133 / **0.516**, 100-500 goes
0.000 / 0.000 / **0.259** -- roughly **2x variation inside a single bin**, the same order as
the between-bin variation the calibration already takes seriously. `<100 m2` stays flat
(0.026 / 0.000 / 0.037), the correct sanity check: a sub-pixel array does not glint however
many chances it gets.

Model: `k_i ~ Poisson(q_b * E_i)`, validated = `P(k >= 2)`. `q_b` is per-opportunity glint
probability -- a property of panels and sensor, not of location, so it transfers. Fitted `q`
is monotone in size (0.056, 0.085, 0.088, 0.146, 0.169, 0.172), which the physics predicts.
Three validations: recovers a known `q` in simulation at 0.002/0.01/0.05; reproduces the
study constants when applied to the study's own population (0.306 -> 0.293, 0.293 -> 0.275),
i.e. same quantity at higher resolution; and the tertile response above confirms the premise
before anything was wired. `derive_table` gained `sensitivity_override` and now records both
the value used and the study constant it replaced.

**2. Glint-mined roofclf hard negatives -- REJECTED, and the reason is quantity not quality
(`scripts/glint_mine_hard_negatives.py`, `scripts/glint_hardneg_retrain.py`).** The
2026-08-09 n=6 retrain concluded more examples of the bright-roof pattern were needed and
that no roofclf-side miner existed. Built one: flagged buildings >= 1000 m2, not OSM-mapped,
not found by segmentation, at high-opportunity cells, that never glint.

- **Feasibility is narrow and was measured first.** Contamination of a glint-absence-mined
  set is only acceptable for large roofs at high opportunity; below 1,000 m2 it would be
  28-40% real PV. The best available cells reach `E` 15.3, not the ~25 needed for a clean
  set. Mined 2 cells (including `0061_0012`, which holds the six known bright-roof false
  positives): 1,282 flagged >= 1000 m2 -> 652 after OSM/segmentation exclusion -> 400 capped
  -> **131 reaching usable sensitivity -> 126 mined negatives**, 4 glint-validated as real PV.
- **The mined set turned out far cleaner than estimated, and the correction is worth
  keeping.** I estimated 28% contamination using roofclf's NATIONAL precision (0.526) as the
  prior. The observed validation rate measures it directly instead: 4/131 = 3.05%, which
  against sensitivity 0.65 and false-rate 0.01 implies the real-PV share of this filtered
  population is **3.2%**, so contamination is **1.15%**. The mining filters do most of the
  work -- segmentation has 0.83-0.95 recall above 400 m2, so a large array it missed that
  OSM also never mapped is very unlikely to be real. **Do not use a population's pooled
  precision as the prior for a heavily filtered subset of it.**
- **Result: nothing generalises.** LOQO median AUC 0.8568 -> 0.8571, within-size
  0.8299 -> 0.8294. By size regime on held-out quadrat buildings: all sizes 0.8708 ->
  0.8707, >= 400 m2 0.8894 -> 0.8897, >= 1000 m2 0.9195 -> 0.9194. The model DOES respond
  locally -- the mined buildings' own mean score falls 0.5634 -> 0.4815 and the share
  clearing the deployment threshold falls 97.6% -> 89.7% -- but that is memorisation of the
  neighbourhood it was shown, not transferable skill. Same shape as the n=6 result at 21x
  the scale, now with labels clean enough (1.2% contamination) that noise is ruled out as the
  explanation.
- **What this means for anyone continuing**: 126 rows is 0.12% of a 104,423-row table, so
  the binding constraint is volume. Glint mining yields ~126 negatives per 2 cells at ~45
  minutes of network each, and only for >= 1000 m2 roofs -- which is NOT where roofclf's
  documented failure mode lives (small bright roofs, where a mined set would be 28-40% real
  PV). Scaling this to the tens of thousands of negatives that might move a fit is possible
  but would take days of pulls for a population the classifier is already good at
  (>= 1000 m2 AUC is 0.92). The bright-roof problem needs a different instrument.

One efficiency bug worth not repeating: the miner originally computed opportunity per
BUILDING, which is 400 STAC searches for 2 distinct answers -- every building in a 0.1 deg
cell sees the same scenes and `TileAngles.at` moves by a fraction of a degree across 11 km,
far below the 6 deg tolerance it feeds. Per-cell computation took that step from ~an hour to
90 seconds.

### A 24th calibration quadrat: Sanghar, 2026-08-12

**Added via a hand-drawn boundary the owner supplied
(`data/labels/calibration_boundaries/sanghar_2x2.geojson`), the same drawn-boundary path
Malok and Muzaffargarh Rural Wide used.** `scripts/new_calibration_quadrat.py --name
sanghar --geojson data/labels/calibration_boundaries/sanghar_2x2.geojson` ran the
protocol's mechanical steps in order: geometry normalised through `roofclf.load_boundary`
(a clean, already-closed 4-vertex polygon, no repair needed), overlap-checked against all
23 existing quadrats (clear -- nearest is Khairpur Rural, 115 km away, so this is also the
first quadrat in Sanghar District and genuinely geographically distinct from the
Muzaffargarh/Khairpur cluster the last two additions sat in), then a live Overpass pull
cross-checked against a confirming query of the same bbox (465 features written, 465 seen
-- clean on the first attempt, no truncation retry needed). 3.98 km<sup>2</sup> (the
supplied box was drawn as "2 x 2" but a lon/lat rectangle is not a geodesic square, hence
the `_calib_3p98km2` stem), 464 installations after the representative-point filter, 99.8%
below the 400 m<sup>2</sup> floor (median 30.2 m<sup>2</sup>), packing distance 24.4 m --
a dense small-rooftop population, closer in character to Sialkot/Hasal than to the
Muzaffargarh/Khairpur rural-extension pair.

**Declared Rule-1 complete by the owner directly, at the same time as this addition.**
Registered in `results/calibration_quadrats.csv` (`rule1_complete=True`, province Sindh,
`stratum` left at the default "unclassified pending mapper review" -- no stratum
classification was supplied, and one is never guessed here) and in
`atlas.py::CALIBRATION_BOXES["pakistan"]`. `imagery_layer`/`imagery_date` are blank, same
open gap every other quadrat in this file carries (`docs/issues/calibration-imagery-dating.md`).

**Not yet in a `roofclf` refit, so its building-derived columns are deliberately blank,
not guessed.** `n_buildings`, `n_pv_buildings`, `base_rate` and `nn_median_m` in
`results/calibration_quadrats.csv` need the VIDA join `roofclf.building_table` performs,
which only happens inside an actual `roofclf` fit -- regenerating
`results/calibration_quadrats.csv` via `scripts/build_calibration_quadrats_csv.py
--folds data/roofclf/folds.csv` (done, to pick up Sanghar's geometry/solar-pull columns)
left those four blank for exactly this reason, per that script's own documented
behaviour, rather than carrying over nothing-to-carry from a previous value. The same
regeneration also refreshed the other 23 quadrats' `base_rate`/`n_buildings`/etc. to match
the current (2026-08-11) `data/roofclf/folds.csv` -- `results/calibration_quadrats.csv`
was quietly stale against it before this (e.g. Quetta's own base rate read 2.99% there
against the fold table's actual 4.72%), a pre-existing drift this session's regeneration
fixed as a side effect, not something Sanghar's addition caused.

**Natural next step, not done here**: fold Sanghar into the next `roofclf` refit (adds a
24th fold to leave-one-quadrat-out) and re-run `select_calibrated_quadrats` to see whether
its own `rate_ratio` lands inside the trusted [0.5, 2.0] precision band, then re-derive
`sub400-capacity`/`ge400-roof-capacity`/the evidence atlas if it does or if its own
building density moves `density.CALIBRATED_BLDG_DENSITY_KM2`'s range. A single quadrat
addition does not by itself justify a multi-hour national re-run; that is a separate,
larger action for whoever next revisits capacity numbers.

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
