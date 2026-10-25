# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository. It documents the **current** state of the pipeline: its rules, its gotchas and its
published results. What was tried, rejected or superseded to get here lives in
`docs/experiments.md` (the dated experiment register) and `docs/open-questions.md` (open
items); method write-ups are under `docs/methods/` and `docs/issues/`. Consult those before
re-deriving something that may already have a documented answer.

## What this is

`earthpv` detects individual large solar PV arrays (target > 400 m², the practical floor for
per-pixel supervision at Sentinel-2's 10 m GSD) from Sentinel-2 L2A imagery by fine-tuning the
open-source **TerraMind** geospatial foundation model (IBM/ESA, via **TerraTorch**). Labels come
from OpenStreetMap solar mapping; building footprints classify detections as rooftop/ground. It
is **recall-first**: candidates are meant to be human-validated against high-res imagery in OSM
workflows, so false positives are tolerated. Installations below the 400 m² floor are covered by
a separate per-building classifier, `roofclf`. Segmentation is localized per country on that
country's own OSM labels, and twelve countries have a published evidence atlas (see "Country
runs"). Read `README.md` for the narrative and headline numbers.

**Why two detectors**: Germany's legally complete PV register (MaStR) puts **65.5% of rooftop
capacity in installations below the 400 m² floor** (97.2% by count; quote the capacity share).
A segmentation model trained above that floor is structurally blind to about two-thirds of
rooftop capacity, which is why `roofclf` is not optional infrastructure.

## Main workflow (default pipeline, primary output)

The **evidence atlas** is the primary output. Two detectors, split by placement and by
calibration coverage rather than cleanly by size, combine into one product:

- **Segmentation** (`infer` → `postprocess` → `density`): the TerraMind fine-tune, outlining
  panels directly. Produces every mapping lead regardless of size, is the only instrument for
  ground-mount at any size, and is the rooftop instrument for arrays **≥ 400 m²** wherever
  `roofclf` is not calibrated to replace it. Each country runs its own checkpoint (Pakistan's
  published rasters come from `v3_combined_india`, which is no longer on disk; the others are
  listed under "Country runs").
- **`roofclf`** (`roof-classifier` → `roofclf-score-national` → `ge400-roof-capacity` →
  `sub400-capacity`): a per-building "does this roof carry PV?" classifier, cross-checked with
  the zero-training **SPPI** spectral index (roofclf AND SPPI agreeing) as an internal floor.
  Covers every building **< 400 m²** and also **replaces** segmentation's rooftop estimate for
  buildings **≥ 400 m²** inside the density-calibrated domain, where it measures better (AUC
  ~0.76-0.78 against segmentation's ~0.50-0.78, strongly quadrat-dependent). Both capacity
  functions are domain-restricted and refuse to rescale to a national total on their own.
- **`atlas.build_evidence_atlas`** combines both into **Best estimate**: hand-mapped OSM, plus
  segmentation's ground-mount, roofclf's rooftop replacement in-domain plus segmentation's own
  recall-corrected rooftop out-of-domain, plus roofclf density below 400 m², de-duplicated
  against each other and against OSM, and floored per cell at **Verified** (hand-mapped OSM
  plus the stricter roofclf+SPPI agreement population). Best carries a 90% credible interval.

The end-to-end command sequence is in `docs/reproduce.md`'s "The full pipeline"; the short
version:

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

earthpv ge400-roof-capacity --aoi <aoi> --osm-solar <national OSM solar pull>   # before sub400
earthpv sub400-capacity     --aoi <aoi> --osm-solar <national OSM solar pull>
# NOTE: --sub400-outdomain-cells is deliberately NOT passed -- see "Density stage".
earthpv atlas --aoi <aoi> \
  --sub400-central-cells data/roofclf_national_with_sppi/<aoi>/density/sub400_central_incremental_buildings.parquet \
  --sub400-low-cells     data/roofclf_national_with_sppi/<aoi>/density/sub400_low_incremental_buildings.parquet \
  --ge400-roof-cells     data/roofclf_national_with_sppi/<aoi>/density/ge400_roof_incremental_buildings.parquet \
  --osm-solar <national OSM solar pull>
```

**Random-cell manual validation is part of this workflow, not an optional extra.** The
calibration quadrats are curated and industrial-leaning; a `roofclf` that scores well only there
is not evidence it works on the rest of the country.
`scripts/tile_roofclf_detections_geojson.py --random-cells N --seed S` draws N cells uniformly
from the national scoring output, excludes calibration quadrats, and writes JOSM-reviewable
GeoJSON tiles into `results/<aoi>_roofclf_validation/`. Results go in
`results/roofclf_random_validation_log.csv`. Protocol:
`docs/methods/roofclf-national-validation.md`.

**Imagery date is the gate on sparse areas, not mapping effort.** Out-of-domain random cells and
low-density quadrats have repeatedly sat under reference imagery too old to confirm or refute
recently installed small PV, so a zero there is uninterpretable in both directions. Do not
register such a quadrat: it pulls the sparse band's coverage ratio toward zero on evidence that
does not support it. Check `imagery_layer`/`imagery_date` before drawing, not after mapping
(Box 17 in `docs/issues/pakistan-calibration-boxes.md`).

**A country with a complete register does not need mapped quadrats for the capacity half.**
Germany has none: MaStR publishes per-municipality totals and the estimator is an aggregate, so
`roof-classifier` fits on pseudo-quadrats, `roofclf-score-national` scores the country, and
`scripts/calibrate_germany_capacity.py` fits kWp per credited m² against the register instead of
a quadrat coverage ratio (see "MaStR validation").

**A country with neither** gets the **segmentation-only evidence atlas** (`earthpv atlas --aoi
<aoi> --osm-solar <pull>`, omitting BOTH `--sub400-low-cells` and `--sub400-central-cells`;
supplying one is rejected as a half-configured run). Verified degrades to hand-mapped OSM alone
and Best to that plus the ≥ 400 m² detections; neither reaches below the floor. France is in
this state because `roofclf` does not transfer to French residential PV.

**`--osm-solar` is required, and `density` no longer writes an atlas.** The old six-estimator
and simple atlases were removed; `build_sub400_bracket_atlas` and `build_combined_atlas` remain
and share `templates/pv_atlas.html`.

Of the many sub-400 m² instruments tried, only `roofclf` (cross-validated with SPPI) was
promoted; the rest are in `docs/experiments.md`.

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

Run pipeline stages via the CLI (Typer). Long GPU stages should use the `ml` env; to avoid
pixi's per-invocation overhead you can call the interpreter directly:

```bash
pixi run earthpv labels --aoi germany            # default env is fine for data stages
.pixi/envs/ml/bin/python -m earthpv.cli train --config configs/terramind_pv.yaml
.pixi/envs/ml/bin/python -m earthpv.cli infer  --aoi punjab --checkpoint data/models/<best>.ckpt
```

CLI stages (`src/earthpv/cli.py`): `labels → chips → train → evaluate → infer → postprocess →
export`, plus `compose` (build imagery for AOIs with no local composites). `train --smoke` runs
50 steps; `chips --limit N` caps the chip count for quick runs. For capacity, see "Main
workflow": `density → check-density` for the ≥ 400 m² segmentation half, `roof-classifier →
roofclf-score-national → ge400-roof-capacity → sub400-capacity` for the roofclf half, then
`atlas --sub400-central-cells --sub400-low-cells --ge400-roof-cells --osm-solar` to combine
them. `roofclf-score-national` is the long pole (hours at country scale) and is resumable
per-cell like `density`.

**There is no test suite and no lint task wired** (one test file exists,
`tests/test_mastr_validation.py`, run as a plain script -- pytest is not a declared dependency).
Ruff is configured (line-length 100) but run manually. The practical "does it work" check is a
small end-to-end run: `chips --aoi germany --limit 500` → `train --smoke` → `evaluate`.

**The released segmentation model is v14, fetched with `pixi run fetch-model`.**
`scripts/fetch_model.py` downloads `earthpv_segmentation_v14.ckpt` from the GitHub release
`segmentation-model-v14-2026-10-23` into `data/models/release/` and checks its SHA-256;
`new_region.py plan` and the setup docs take the file name from its `RELEASE` dict. It is
`v14_combined_south_africa` epoch 41 put through `scripts/slim_checkpoint.py` (optimizer state
dropped, `backbone_pretrained: false`, so 33 MB and no Hugging Face download at load), and it
reproduces South Africa's published probability raster byte for byte. It has the best
installation recall of seven checkpoints over eleven regions, at lower pixel precision; v15 is
the precise alternative and is not released (`results/release_model_benchmark.csv`,
`docs/pretrained-model.md`). **Every published atlas still runs on its own country's
checkpoint; the release changes no published number.** To release a newer model: slim it,
upload it with `SHA256SUMS`, `MODEL_CARD.md`, `LICENSE` and `NOTICE` to a new tag, update
`RELEASE`, and redo the page's tables from the same benchmark. **The weights are Apache-2.0**
(matching TerraMind); `NOTICE` carries the TerraMind, OpenStreetMap and Copernicus
attributions, and detections made with the model stay ODbL like every data output.

## Architecture

### Data reuse -- the load-bearing design decision

To avoid re-downloading terabytes, imagery and labels are **reused from a sibling
`rooftopsenti` project** on the same drive, pointed at by `local_root` in `configs/aoi.yaml` and
each AOI's `source_region`. `src/earthpv/local_source.py` reads that project's per-MGRS-tile
Sentinel-2 composite COGs (`CompositeIndex`) and its OSM/Overture label + building parquets
(`load_solar_labels`, `load_buildings`). The Overture (`overture.py`) and Planetary-Computer
(`imagery.py`) fetchers are **fallbacks** for AOIs with no local artifacts. **Direct Overture S3
queries time out from this machine -- prefer the local/VIDA paths.**

Consequence: an AOI is only fully usable where the `source_region` actually has composites.
`germany` uses `germany_500`; `punjab` uses `pakistan_500` for *buildings* but that region's
composites cover **Balochistan, not Punjab** -- so Punjab imagery is built on demand by the
`compose` stage into `data/composites/punjab/`, which `infer` prefers over the `source_region`.

### Bands & the TerraMind model

Local composites are **10-band** (B02–B12 minus the two 60 m atmospheric bands B01/B09).
TerraMind's pretrained S2L2A patch-embed is 12-band; at load, `configs/terramind_pv.yaml`
passes `backbone_bands: {S2L2A: [10 names]}` so TerraTorch **subsets the patch-embed** to
exactly those 10 bands (`config.py` holds `LOCAL_BANDS` / `MODEL_BANDS` and the mapping). The
backbone is `terramind_v1_tiny` (fits a 6 GB GPU); it's a plain ViT, so a UNet decoder needs a
feature pyramid built by the neck stack `SelectIndices → ReshapeTokensToImage →
LearnedInterpolateToPyramidal`. Training (`train.py`) is a TerraTorch `SemanticSegmentationTask`
via Lightning; checkpoints monitor `val/mIoU`.

- **Compare checkpoints on installation recall, never on one val/mIoU.** val/mIoU is dominated
  by large ground plants, and epoch selection noise is as large as a backbone change (v14's
  second-best checkpoint finds 0.621 of rooftop arrays against the shipped one's 0.565).
  `scripts/compare_backbones.py` (paired McNemar per installation, at matched pixel precision,
  over every AOI's holdout) and `evaluate(extra_thresholds=...)` do this.
- **On the GTX 1060 `train` uses PyTorch's math SDPA kernel** (`earthpv.attention`, pre-Volta
  GPUs only): the default kernel is about 3x slower for TerraMind training. **TerraMind
  inference deliberately keeps PyTorch's default kernel**: the gain is small and the kernels
  agree only to rounding, so switching would break byte-for-byte reproduction of published
  rasters. `EARTHPV_SDPA=default|math` overrides.
- **Training is protected against systemd-oomd.** `datamodule` drops each chip from the page
  cache after reading it (a ~20 GB corpus cannot be cached inside a unit's MemoryMax).
  `resume: true` in a training config is opt-in and continues from the run's own `last.ckpt`;
  pair it with `systemd-run -p Restart=on-abnormal`.
- `src/earthpv/thor_backbone.py` (THOR-Tiny, read from the gitignored `third_party/` checkout
  because it pins TerraTorch 1.2.5) is tooling from a backbone comparison that was not adopted.

### Adding a new AOI

`scripts/new_region.py` is the front door for a region with no local data: `check` preflights
the four open sources (Overpass label count, VIDA parquet for the ISO3, geoBoundaries
ADM1/ADM2, Sentinel-2 cloud cover in the compose window) read-only, `add` appends the AOI block
to `configs/aoi.yaml` (with `val_tiles: []`) and re-parses to catch a bad insert, `plan` prints
the runbook. **New AOIs must carry `division.iso3`** -- `buildings._iso3_for` prefers it and the
ISO2 fallback map only covers PK/DE/IN, so an AOI without it fails at the density stage rather
than at setup. `source.coop` 403s any request without a User-Agent header, which reads exactly
like "no such country." Guide: `docs/reproduce.md`'s "Scale to a new country" section. Before a
new country's atlas is built, re-run `scripts/ember_import_ceiling.py` (see "Documentation
site").

### Compose stage (imagery for AOIs without local composites)

`compose.py` builds Sentinel-2 composites on demand via Planetary Computer STAC
(`imagery.annual_composite`: dry-season median of the ~12 least-cloudy scenes per 0.1° cell). It
only composites **building-populated cells** (rooftop PV needs roofs), prioritized by density,
plus label cells (since 2026-10-12 `compose._solar_label_cells` covers a mapped park's whole
outline, not just its representative point). Output mirrors the rooftopsenti COG layout
(`<cell>/composite_0.tif`) so `CompositeIndex`/`infer` read it unchanged. It is **resumable**
(skips finished cells) and **network-bound**. `compose.run_compose` honours an AOI's
`compose_window` when `--window` is not passed. AOI keys: `ring_cells: N` adds every cell within
N cells of the selection (appended after existing cells, so resumed runs are unchanged);
`cell_selection: duckdb` aggregates per-cell VIDA counts in DuckDB (cached in
`data/cells_cache/`), needed for very large countries; `grid_origin` pins the cell naming.

**Composites built before 2026-10-10 carry two known defects** (open question 11):
`eo:cloud_cover` is per MGRS tile, so dry-season scenes tie at 0% and the twelve kept could all
come from a tile clipping the cell's corner (`imagery._rank_items` now ranks scenes covering
>= 99% of the cell first); and `odc.stac.load(fail_on_error=False)` turned failed reads into
zeros, so a cell could lose a whole band (`imagery.BAND_DROPOUT_MAX` now raises and the cell is
retried). India, Zambia, Nigeria and Vietnam were not recomposited;
`scripts/scan_composite_defects.py` measures a country.

### Postprocess & ranking

`postprocess.py` polygonizes probability rasters, then joins candidates to building footprints
for a rooftop/ground/no-building `placement` and a metric-based `rank_score` (confidence ×
building prior). Footprints come from `buildings.py::load_dense_buildings` -- **VIDA Open
Buildings** (Google+Microsoft, imagery-derived, includes small/unmapped roofs), fetched
windowed-and-cached per AOI; the local Overture ≥500 m² set is the fallback.
`postprocess.replace_with_osm_geometry` substitutes an OSM-mapped installation's real geometry
for the model's coarse candidate polygon when one matches (keeping only the closest OSM match
per feature). `export.py` sorts by `rank_score` and writes GeoParquet/GeoJSON + a MapRoulette
challenge.

For large countries: `--building-buffer-m` bounds which footprints are fetched (placement uses
30 m and the rank prior ~40 m, so nothing is dropped; 500 for Vietnam/India);
`--stream-buildings` fetches/joins/discards per 0.25° chunk instead of holding a national
building table; `--reuse-join <previous candidates.parquet>` (with `--stream-buildings`) keeps
the join of every chunk whose candidate geometries are unchanged (India's full join is 23 h).

### Density stage (aggregation into PyPSA-ready shapes)

`density.py` reuses the per-cell probability rasters (no GPU) to report *aggregate* PV capacity
per building/grid-cell/region for the **≥ 400 m²** population; it is measurably blind below that
floor on its own. Three area metrics per building: `*_det` (thresholded candidate polygons --
precision-honest floor), `*_exp` (probability-weighted area, an upper-leaning ceiling), and
`*_cal` (`*_det` re-weighted by a measured P(real | size, glint, placement)). The headline
segmentation number is `est_mwp_rc`, which additionally divides by measured recall per size
class (Horvitz-Thompson). Full derivation: `docs/methods/density.md`.

**Area → capacity uses two calibrated constants, never one.** Rooftop converts at
`DEFAULT_KWP_PER_M2_MODULE = 0.18` kWp/m² (module area); ground-mount at
`DEFAULT_KWP_PER_M2_LAND = 0.05` kWp/m² (site area: ground training labels are OSM
`power=plant` perimeters; `KWP_LAND_CI90 = (0.035, 0.075)`, calibrated on two Pakistani plants
and since matched by capacity-tagged parks in India and South Africa at 0.045). Applying the
module constant to site area overstates ground-mount 2-3x, so `_ratios`/`_composed_mwp_draws`
split every estimator by `placement` before conversion. Both constants carry lognormal priors
(`capacity_calibration.py`, `kwp_draws`) that propagate into the credible intervals. France's
register measures the module constant at 0.150; 0.18 is unchanged pending an owner decision.

**Precision/recall calibration is split by placement** (`capacity_calibration.derive_placement_tables`):
pooling let ground-mount borrow rooftop's much higher OSM corroboration rate. Ground bins fall
back to `p_unmapped = 0.0` (an honest floor). `density.candidate_p_real`/`candidate_recall` and
`_candidate_uncertainty` select each candidate's own placement subtable. **Recall is
"was this real installation found by ANY candidate"**: restricting the finder to the same
placement understated large-rooftop recall up to 24x (a large array overruns its VIDA footprint
and gets classified `ground_adjacent`/`no_building`).

**The checked-in calibration YAML is load-bearing** (`configs/calibration/<aoi>_candidate_precision.yaml`)
and was silently regressed once by a bare re-run. Guards: `calibrate-candidates --by-placement`
defaults to True; `capacity_calibration.write_table` **refuses** to overwrite a table carrying
evidence the new one lacks (placement split, glint calibration, manual reviews,
`register-p-unmapped`) unless `--allow-downgrade`; `density.py` warns when a table has no
`placement_bins` for an AOI whose candidates span both placements. Reproducing Pakistan's table
needs the calibration boxes and `--glint-sample`, not a bare re-run (its `recall_reference`
records 18,276 features). **Pakistan's table predates the any-candidate recall fix, so its
published `est_mwp_rc` (and Best) is overstated** until the table is deliberately re-derived --
an owner decision, not done.

**OSM reference polygons are dissolved before use** (`labels.dissolve_overlapping`): a
`power=plant` perimeter with a nested `power=generator` way, or duplicate mapping passes, would
otherwise double-count one installation. Wired into `export.load_mapped_reference_attrs`,
`postprocess.replace_with_osm_geometry`, and `atlas.build_evidence_atlas`'s own OSM sum.

**Candidates over `postprocess.MAX_CANDIDATE_M2` (100k m²) are excluded from capacity**
(`density.capacity_relevant_candidates`, shared by `run_density` and the evidence atlas):
`polygonize_chips` merges every touching thresholded pixel with no upper bound, so a connected
sheet of false positives can become one multi-km² "installation". A `geometry_source == "osm"`
oversize candidate (a real, human-mapped footprint) is exempt, with two limits mirroring
`prepare_national_osm_solar.py`'s rules for Verified: an exempted outline is always ground
(VIDA traces a park's panel rows as buildings), and when the AOI has a ground screen
(`results/<aoi>_osm_ground_screen/screen_full.csv`, auto-discovered by `density.load_osm_screen`)
an outline above 5 km² that fails the screen (imaged >= 0.9, detected >= 0.5) is credited at
outline area x `det_frac` instead of whole. The same rule runs in `density`, the evidence atlas
and `calibrate-candidates`. Real unmapped parks above the cap are excluded too; they appear in
the new-leads export.

**`buildings.geoparquet`'s summed rooftop capacity is not `grid.geoparquet`'s region total,
by construction**: the region total sums each rooftop candidate's full polygon once, the
per-building table credits only the intersection with each building capped at its roof area
(~46% gap nationally in Pakistan). Per-building disaggregation is a conservative floor.

**roofclf replaces segmentation's rooftop estimate for ≥ 400 m² buildings inside the density
domain** (`roofclf_ge400_capacity.py`, `earthpv ge400-roof-capacity`): segmentation is blind to
installation size relative to its building, so a large building with a small array reads as a
miss. Outside the domain, segmentation's own `est_mwp_rc_roof` remains the only number.

**The coverage ratio** (true mapped PV area / score-weighted roof area, or flagged roof area
under `--weighting threshold`) **is measured per building-size decile AND per density
stratum** (`sub400_capacity.coverage_ratio_by_size_and_density`, shared by sub-400 central,
sub-400 AND-gate and the ≥ 400 m² replacement). Its uncertainty comes from
**resampling calibration quadrats**, not buildings (quadrat composition is what moves these
numbers): 200 bootstrap replicates, with one replicate index shared across all roofclf atlas
components (`sub400_capacity.COVERAGE_BOOTSTRAP_SEED`).

**roofclf's own misses are corrected for** (`sub400_capacity.area_recall_by_size_and_density`):
dividing by the measured share of true mapped PV **area** landing on flagged buildings, per size
bin and density stratum -- the same Horvitz-Thompson step as `est_mwp_rc`. Coverage ratio and
area recall are refit inside the SAME bootstrap replicates so their dependent errors are never
multiplied as if independent. **Deliberately NOT applied to either AND-gate tier**: those are
floors. `--no-recall-correct` reproduces the uncorrected figures; `--coverage-boot N` (default
200; 0 disables and narrows the interval).

**roofclf's Best components are priced by probability, not by a threshold (2026-10-25)**
(`sub400_capacity.WEIGHTINGS`, `--weighting`, default `probability`). Every in-domain building
counts by its `p_roofclf`, with coverage ratio and area recall refit on the same weights, and
the output is one row per (cell, size bin) carrying `n_buildings` and `sum_p`. Leave-one-quadrat-
out it cut the median sub-400 m² PV-area error 0.386 -> 0.094 (20 of 29); thresholding booked
12% of mapped PV in quadrats below 300 bldg/km². What it trusts instead is the score's LEVEL in
sparse national cells, which is unmeasured (open question 1 holds the declared revert rule).
**The AND-gate floors stay thresholded** (`_check_weighting` refuses probability with SPPI),
and the fitting primitives (`coverage_ratio_by_size`, `area_recall_by_size` and their
stratified and bootstrap wrappers) keep `"threshold"` as their own default, so a new caller
passes `weighting` explicitly. Give `ge400-roof-capacity` and `sub400-capacity` the same
`--weighting`; `threshold` reproduces the pre-2026-10-25 figures. The atlas records it in
`totals.roofclf_weighting` and counts the size chart's roofclf objects as `sum_p`.

**The parcel label (`roof-classifier --parcel-label`) is the production label.** It adds mapped
PV within `YARD_RING_M` (20 m) of a footprint, attributed whole to the nearest building, for
installations below 400 m² only (`roofclf.parcel_pv_area`). 80% of what it recovers is mapped
rooftop PV overhanging an undersized VIDA outline and 20% is OSM `placement=ground`;
`sub400_capacity.parcel_label_composition` reports the split, which is what to quote for the
placement claim. A parcel-label model needs its own national rescoring, and
`roofclf.check_scoring_matches_calibration` refuses to pair a scoring with another
calibration's coverage ratio. Full derivation: `docs/methods/roofclf.md`.

**OSM and a recall-corrected total: combine, don't add.** `est_mwp_rc` already stands in for
the mapped installations the model missed, so adding unmatched OSM on top counts them twice.
`build_evidence_atlas` (and `_size_distribution_data`, which re-bins the same total) takes, per
placement x size bin, `max(HT, D + U)`: the absorbed share comes out of each candidate's
inflation, never below a cell's precision-weighted `est_mwp_cal_*`
(`atlas.osm_absorbed_inflation`). Where a recall correction applies, OSM counts as matched at
the table's own `min_distance_m` (100 m). Inside the ge400 roofclf domain every OSM rooftop
installation is counted from the map. `--legacy-osm-addition` reproduces the old convention;
the page records its convention in `totals.osm_combination`.

**The sub-400 populations dedupe only against candidates whose figure Best uses**
(`sub400_capacity.dedup_candidates`; `--legacy-seg-dedup` reproduces the old run).
`sub400-capacity` reads the domain from `ge400-roof-capacity`'s output, so **run
ge400-roof-capacity first**.

**The density-calibration domain is a building-density band**, `density.CALIBRATED_BLDG_DENSITY_KM2`
for Pakistan, fit from the density span of every Rule-1-complete calibration quadrat -- **NOT**
from `select_calibrated_quadrats`'s separate precision-trust selection. Currently **(48.5,
5,258.00) bldg/km²**, covering **2,957 of 4,463 national cells (66.3%, 94.7% of buildings)**.
The band is per AOI: `density.calibrated_density_range(aoi)` looks up
`CALIBRATED_BLDG_DENSITY_BY_AOI` (france 17.5-390.8), warns when an AOI has none, and falls back
to Pakistan's; `aoi` is threaded through `sub400_capacity.py`, `roofclf_ge400_capacity.py`,
`growth.py` and `cli.py`. `--ratio-lo`/`--ratio-hi` do **not** affect this domain (they tune
the precision-trust band, a real footgun if conflated). **To widen it**, a quadrat's OWN average
density must read below the floor; a boundary traced around a settlement almost never does, so a
range-extending quadrat must deliberately average in non-built land. History:
`docs/methods/calibration-quadrats.md`, `docs/methods/density.md`.

**Out-of-domain roofclf-AND-SPPI capacity (`sub400_capacity.out_of_domain_and_gate_capacity`,
`--sub400-outdomain-cells`) exists but is not published** (owner decision 2026-08-15): it is
the one component not measured where it would be applied, and its manual review is blocked by
stale imagery. Everything that reports it degrades to absent rather than zero when the flag is
omitted; pass it and it comes back.

**The 90% credible interval** (`atlas._evidence_uncertainty`) composes every measured source
(module/land kWp priors, coverage-ratio quadrat bootstrap, `KWP_LAND_CI90`, the farm-ground
replicates) with correlated terms sharing one draw vector, and asserts its component point
values sum to the published total -- a guard against adding an atlas component without adding it
to the uncertainty.

**Pakistan's current published figures.** Segmentation `est_mwp_rc` **4,051.9 MWp** (rooftop
2,916.3, ground 1,135.6). roofclf (30 quadrats, parcel label, area-weighted zonal means,
recall-corrected, probability-weighted since 2026-10-25): sub-400 central **24,206.3 MWp**,
sub-400 AND-gate (floor, thresholded, uncorrected) **3,784.3 MWp**, ≥ 400 m² rooftop replacement
**7,503.2 MWp**; median LOQO fold AUC 0.8682, within-size 0.8193, deployment threshold 0.2446.
Atlas: **Best 34,588.8 MWp (90% CI 29,308-41,736), Verified 6,994.1 MWp (90% CI 6,041-9,091)**
(thresholded until 2026-10-25: Best 24,438.3, 90% 20,894-33,666). `check-density` fails 3 regions
on single-cell concentration (KP, Balochistan, ICT), checked genuine (the calibration quadrats'
own cities) and published per standing precedent. **The mandatory random validations of the last
three rescorings (seeds 20260817, 20260820, 20260920; tiles in
`results/pakistan_roofclf_parcel_validation/` and `results/pakistan_roofclf_validation/`) have
NOT been reviewed**: `results/roofclf_random_validation_log.csv` has 40 rows with blank verdicts,
so the published figure rests on an unreviewed rescoring (open question 3). Pre-change outputs
are kept beside the canonical paths with `_PRE_<change>_<date>` suffixes.

**Overture publishes a coastal admin division twice** (land, and land plus territorial waters).
**Keep the LAND polygon, the SMALLER of a nested pair** -- "keep the largest" picks the wrong one
every time. `density.drop_nested_duplicates` (in `load_admin` at both levels, repeated on read
by `atlas._region_rows`) tests **nesting**, not name equality, so genuinely distinct same-name
divisions survive. Only Germany's admin layer was affected; geoBoundaries has no maritime rows.

### One atlas template, one config file per country (`configs/atlas/<aoi>.yaml`)

`templates/pv_evidence_atlas.html` is shared by every country, and everything country-specific
lives in `configs/atlas/<aoi>.yaml`, never in the builder. `atlas_config.load(aoi)` supplies
`title`, `cities`, `calibration_boxes`, `composition_page`, `layers`, `validation` and three
optional confidence blocks (`ground_truth`, `caveats`, `corroboration`). A missing file is
normal (a complete page minus the sections that need local evidence); a malformed one is an
error, including an unknown key.

`_confidence_html` gates every claim on the thing that makes it true (the quadrat-resampling
bullet on an actual coverage bootstrap, purposive-sampling and Rule-1 bullets on actually
having quadrats, corroboration on the config supplying one) and derives its counts.
`_composition_note` derives the "which method supplies most of Best" sentence from the page's
own components. `_load_calib_boxes` looks in `data/labels/<aoi>/` before `data/labels/`.

**`scripts/check_atlas_templates.py` fails CI** if a published atlas names another country in
its visible text or links another country's page (config-supplied strings are exempt, so a
country's own config may compare against another on purpose). **`pv_growth_atlas.html` and
`pv_size_atlas.html` still carry Pakistan-only prose and links** and are not covered by the
guard; a second country's growth atlas would leak Pakistan's text.

### The evidence atlas page: MapLibre GL + Observable Plot

**The map is MapLibre GL JS 5.24 and the charts are Observable Plot 0.6.17 on D3 7.9**, loaded
from jsDelivr at exact versions with SRI hashes. **MapLibre 5, not 6**: v6 is ESM-only with a
separate module worker, which does not load from a CDN into a `file://` page or an iframe.
Offline, the page degrades: hero, KPIs, tables, the composition bar and the pose plot are plain
SVG/HTML; the map and the three Plot charts say they could not load.

- **Map**: "Show" picks the cell quantity (Best, *Not yet in OpenStreetMap*, hand-mapped, model
  >= / < 400 m²); "per km²" divides by cell area; the log colour scale is refitted per quantity.
  Basemaps: none (night lights), Esri grey canvas, OpenStreetMap, Esri satellite (**CARTO needs
  an API key now**). City labels are HTML (no glyph server); calibration areas are diamonds.
- **More layers**: an opt-in *live OSM solar* overlay queries Overpass from zoom 11 (mirrors can
  lag months, so the status line shows the returned OSM timestamp); readers add GeoJSON/CSV,
  GeoJSON URLs, XYZ tiles or WMS; a country can ship layers in its config (`layers:`, schema in
  `atlas_config`), embedded by `atlas.map_layers_json` (5 MB cap) into a `pv-layers` block.
- **Downloads**: every figure as PNG/SVG/CSV, the map as PNG plus the grid as GeoJSON/CSV,
  re-rendered at 960 px with title and source line, never serialised from screen.
- **Uncertainty section**: a forest plot of each Best component's point and 90% interval, from
  the same `uncertainty.components` the headline CI is composed from.
- **For every page built or retemplated from 2026-10-24 on**: the province chart shows the top 7
  (`PROV_TOP`) with a *Show all N provinces* toggle; a fifth KPI tile gives processed cells
  against the country's (`totals.n_cells_processed` / `n_cells_country`, `atlas._cell_coverage`;
  hidden until a rebuild provides them); the Silver/Bronze banner is short.
- **Colour means method everywhere**: OSM teal, segmentation blue, roofclf amber, roofclf+SPPI
  violet, farm ground PV green; hatching means ground-mount everywhere.

**Plot gotchas**: on a log scale Plot routes any `tickFormat` through d3's log formatter, which
blanks every tick with mantissa > 2 (draw labels with a text mark); a `{value, label}` channel
object as `barX`'s `y` breaks the implicit stack (rename the field instead); `grid: true` on a
scale plus a `gridX` mark draws two grids.

**`scripts/retemplate_atlas.py` moves published pages onto a new template without rebuilding
them**: it recovers each placeholder's value by aligning the page with the template it was built
from (`--old-template <git rev>`, default HEAD), proves the split by substituting back, then
fills the current template; only `__LAYERS_JSON__` and `__AOI_KEY__` are computed fresh. **After
a template commit, pass the revision the pages were last built from**, not HEAD.

**Re-template the SYNC SOURCES too, not only `docs/assets/interactive/`.** Most published
atlases are copies `build_docs_figures.sync_interactive` makes from
`results/<aoi>_pv_evidence_atlas.html` (Germany from `data/predictions/germany/density/`); a
local `pixi run docs-figures` copies those sources over the committed pages and would revert
them. Expect `docs-figures` to rewrite ~50 SVGs whose only change is matplotlib's timestamp and
random ids: revert those, keep only real content changes.

**`scripts/screenshot_pages.py` drives Firefox over WebDriver BiDi** (`--screenshot` fires at
the load event and captures an empty WebGL map). A Shot can name a `ready` expression; the atlas
sets `data-atlas-ready` on `<html>` once its map has drawn a complete frame. Atlas iframes on
the docs site carry `allow="fullscreen"` and `local-network-access; loopback-network`
(`build_atlas_pages.py`).

**Calibration areas open in JOSM or iD from the atlas.** Clicking an area offers **Open in
JOSM** (Remote Control `import` of the area's GeoJSON as a locked `upload_policy=never` layer,
then `load_and_zoom` with the protocol's changeset comment and
`#tracethesun;#earthpv;#earthpv-calibration`), **Open in iD** (`#gpx=<url>.geojson`) and a
download. A **Propose** control drops a 2 km square matching
`new_calibration_quadrat.geodesic_square` and checks overlap as `check_overlap` does. The
boundaries come from `pixi run calib-publish` (`scripts/publish_calibration_areas.py`), which
writes full-precision `docs/assets/labels/calibration_areas/<aoi>.geojson` plus one file per
area; the page fetches its index at run time, so a new area reaches every atlas with a
re-publish, no rebuild. **Re-run it whenever a quadrat or candidate is added or
`calibration_boxes` changes**; `check_atlas_templates.py` fails CI on a configured box without a
published file.

**Calibration candidates are sampled, not hand-picked:** `pixi run calib-candidates -- --aoi
<aoi>` (or `--bronze`), i.e. `scripts/propose_calibration_candidates.py`.
- **Strata:** the density grid cut into 8 bands of equal building share, one candidate each.
- **Draw:** building-weighted random cells per band, seed derived from the AOI name; 20 km
  spacing, one province each while possible.
- **Placement:** on VIDA footprints, own density within 25% of the cell's; 1 km boxes above
  600 bldg/km², 2 km otherwise.
- **Imagery gate:** the oldest Esri World Imagery capture at centre and corners must be no more
  than 12 months before `compose_window` start (`World_Imagery/MapServer/4/query`).
- **Output:** `data/labels/<aoi>/candidate_quadrats/`, failures in `screened_out.csv`.
  `--replace` redraws only sampled candidates. Then run `calib-publish`.
- **Start-here boxes:** `--bronze --priority` adds two PURPOSIVE 1 km boxes per Bronze AOI (the
  most large-roof area in the densest quarter, chosen on buildings only, marked `selection:
  purposive: ...`); the eight sampled boxes stay the representative set. `calib-publish` ranks
  them first and the atlas draws `start_here` as a star.

**The community guide is the "Contribute Data" nav section**, `docs/contribute/` (`index.md`
keeps the `/contribute/` URL that popups, badges and README link to; plus `id.md`, `josm.md`,
`report.md`, `maintainers.md`). Mappers report through `.github/ISSUE_TEMPLATE/calibration-area.yml`;
the popup's "Report progress" link prefills `area` and `country`. A screenshot still to be taken
is a `<div class="shot-needed" markdown>` placeholder naming the target file.

`new_calibration_quadrat.py --aoi <aoi>` registers outside Pakistan into `data/labels/<aoi>/`,
using that AOI's admin files and ISO3. Pakistan stays flat, because a flat non-Pakistani box
would join the next Pakistani refit.

### Plausibility gate (`plausibility.py`, `earthpv check-density`)

The capacity atlas has no human on each candidate, so a false-positive mode that survives
`p_real` reaches the headline silently. Two per-region checks from artifacts `density` already
wrote: **ground-mount:rooftop capacity ratio** (bare ground, riverbed, salt flat, rock and snow
read bright) and **single-cell concentration** (one 0.1° cell over 25% of a region). Both need
`mwp_ground >= 50`. `RATIO_CHECK_EXEMPT_REGIONS` exempts Gilgit-Baltistan from the ratio check.
In segmentation-only countries the ratio check also fires on a *missing rooftop denominator*
(small arrays are a fraction of a pixel), which is stated on publication, not waived. Exit 1 = a
region failed, 2 = `density` has not run. **Run it between `density` and publishing** -- docs CI
cannot, since `data/` is gitignored.

### Invariants that prevent tiling artifacts (do not regress)

Naive sliding-window inference produced a regular grid of false positives. Two fixes must stay
in place:
- **Positive chips are jittered** (`chips.py::sample_chip_centers`, ±900 m) so the PV array is
  *not* centered in the frame. Without jitter the model learns a center bias and fires once per
  window at inference → a grid at the stride spacing. Diagnostic: nearest-neighbor distance
  between detections spikes at the window stride.
- **`infer.py` overlap-adds windows with a 2D Hann taper** into one seamless raster per cell,
  with a **stride that is not a multiple of the 16 px ViT patch size** (currently 104) so
  patch-edge effects decorrelate between neighbors.

### Documentation site

`mkdocs.yml` + `docs/` build the MkDocs Material site published to GitHub Pages by
`.github/workflows/docs.yml` on every push to `main` (no path filter). **Every figure and
embedded interactive page under `docs/assets/` is generated** by
`scripts/build_docs_figures.py` (`pixi run docs-figures`), which reads its numbers from tracked
files (`results/*.csv`, the atlas HTML's embedded JSON, calibration YAML) so the site cannot
drift from them -- edit the sources, not the SVGs. Local preview:
`pixi run docs-figures && pixi run -e docs docs-serve`. The build runs `--strict`. Docs prose
avoids em dashes and emoji.

**`mkdocs build --strict` does NOT validate URLs inside raw HTML.** A raw relative URL needs one
`../` per path segment of the page's own served URL (`index.md` excepted).
`scripts/check_docs_links.py` checks every raw-HTML relative URL in `docs/` and runs in the docs
workflow ahead of the build.

**The PV Atlas pages are generated** (`scripts/build_atlas_pages.py`): one row per country in
`ATLASES`; each page's tier (Gold/Silver/Bronze) is read from the calibration badge its own
atlas carries (`atlas.VALIDATION_TIERS`), the switcher and `--nav` block are grouped by tier, and
Silver/Bronze pages open with a missing-small-installations warning (`WARNING` + `HELP` + `CTA`)
and a call to map a calibration area. A new country is one row plus a rerun; **never edit
`docs/atlas*.md` by hand**. A tier that is a judgement goes in `configs/atlas/<aoi>.yaml`
(`validation: {score, note}`, which beats `derive_validation_score` and is read by all three
atlas builders and `apply_validation_badges.py`), with a country note in
`build_atlas_pages.TIER_NOTE`. **Germany is Silver** (its register-calibrated small half fails
its own register check). **Yemen is Silver**: its building box carries `used: false` and its
farm areas calibrate farm ground PV only, so household rooftops below 400 m² are unmeasured.

**Every evidence atlas shows an import ceiling**: solar panels imported from China from Jan 2017
to the end of the imagery window, from Ember's customs-based export data (CC-BY-4.0).
`scripts/ember_import_ceiling.py --csv <Ember monthly CSV>` writes
`configs/external/ember_china_panel_imports.yaml`; `atlas.import_ceiling(aoi)` puts it in
`totals.import_ceiling`. India, Germany, France and Poland are flagged `ceiling: false` (domestic
manufacturing or non-Chinese import routes) and the page says why. Table:
`docs/methods/validity.md`.

Nav runs **Results → How it works → Setup → Experiments**. `docs/experiments.md` is the
canonical register of every experiment (shipped/partial/rejected/superseded) with links to
`docs/issues/`; `docs/open-questions.md` lists actionable open items and is **excluded from the
published site** (`exclude_docs`), so no site page may link to it; an item is removed once
closed and moves to the register with a verdict. Every doc under `docs/issues/` carries a dated
status banner (shipped, closed-negative, superseded, or open).

The site chrome (`docs/assets/stylesheets/extra.css`) shares its design tokens (`--pv-*`) with
the result pages it embeds -- keep both in sync by eye. `docs/assets/javascripts/embed-theme.js`
drives each embedded page's theme toggle from the site's Material toggle.
`pixi run docs-screenshots` needs a real (snap) Firefox profile staged under
`~/earthpv-screenshots/` (not `/tmp` or the external drive) and pins `ui.systemUsesDarkTheme`
and `ui.prefersReducedMotion` (the hero count-up animation can otherwise be caught mid-way).

**The interactive "night lights" HTML style (dark glowing choropleth, KPI strip, tab switcher,
`<details class="xdetails">` methodology sections) is the default for any new results page.**
Reference: `src/earthpv/templates/pv_evidence_atlas.html` (pipeline-native) /
`results/pakistan_pv_evidence_overview.html` (standalone-script version). A new standalone script
slices the shared CSS via matched string markers (`build_pakistan_pv_evidence_overview.py`'s
`_slice`/`_shared_fragments`) rather than forking it by hand. Static figures stay appropriate
only for the docs site's embedded `<img>`s and print/export.

### Calibration quadrats

**31 Pakistani quadrats are registered; 30 are in the `roofclf` fit.** Purposive selections
(industrial estates, dense residential blocks) plus deliberately rural extensions that set the
density domain. All are declared **Rule-1 complete** by the owner (every visible panel mapped).
**Rule-1 is epoch-relative**: it certifies completeness against the mapping imagery's own capture
date, not the Sentinel-2 composite's, so the newest installations are structurally missed. This
makes precision and `base_rate` **lower bounds** and `rate_ratio` an **upper bound**; recall over
mapped installations is unaffected.

**`kalat_rural_calib_3km` must stay OUT of any `roofclf` refit** until `building_table`'s roof
term gets a placement/size guard: sited to include ground-mount, most of its has-PV buildings are
labelled only because a ≥ 400 m² ground array clips them, which would fit the sparse band's
coverage ratio on ground-mount and double-count against segmentation.
`roofclf.discover_quadrats` globs the label directory, so the next `earthpv roof-classifier` run
picks it up automatically unless excluded (open question 8).

**Ranking transfers across quadrats; absolute adoption rates do not** (`rate_ratio` has spanned
0.2-5x), which is why the coverage ratio is stratified. `select_calibrated_quadrats` picks the
precision-trusted subset (`rate_ratio` roughly in [0.5, 2.0]) independently of Rule-1 status and
of the density-domain selection; check both gates for any new quadrat.
`scripts/new_calibration_quadrat.py` adds one (geodesic square or hand-drawn `--geojson`): it
checks boundary overlap with every existing quadrat before writing, and cross-confirms a live
Overpass pull against a second query (mirrors have returned truncated, non-error responses).

Per-quadrat table: `docs/methods/calibration-quadrats.md`. Dated history of every
addition/correction/withdrawal: `docs/issues/pakistan-calibration-boxes.md`.

### Farm ground PV: `roofclf_ground` and farm calibration areas

A footprint-free pixel detector in the roofclf family for small arrays beside fields (solar
pumps), which neither instrument above sees (`src/earthpv/roofclf_ground.py`,
`docs/methods/roofclf-ground.md`):

```bash
pixi run calib-candidates -- --aoi <aoi> --farmland          # cropland-stratified 3 km boxes
earthpv roofclf-ground --aoi <aoi> --clean-region <b.geojson> --weak-region <b.geojson>
earthpv roofclf-ground-score-national --aoi <aoi>             # blobs per cell, resumable
earthpv roofclf-ground-capacity --aoi <aoi> --osm-solar <national OSM pull>
```

- **A standard atlas field**: `earthpv atlas --ground-cells <ground_cells.parquet>` adds
  `small_ground` (farm ground PV < 400 m²) to Best in the detector's calibration domain only,
  with its own tile, map quantity, province column, composition and uncertainty row, in green.
  Without it a page says "not measured" (`totals.small_ground_status.measured: false`), never 0.
  Run `roofclf-ground-capacity` with the SAME `--osm-solar` file the atlas counts, and
  `--roofclf-buildings` where a roofclf half exists (a blob within 20 m of a priced building is
  its yard array).
- **A calibration domain PER REGION** (`roofclf_ground.domain_cells`): a cell is priced with a
  region's ratio only if its cropland share, building density AND median elevation (Copernicus
  DEM, `cell_elevation`, cached in `data/cells_cache/<aoi>_elevation.parquet`) each lie within
  x/÷1.25 of that region's areas; a region = areas sharing the `region` property. The headline
  is `est_mwp_in_domain`; `est_mwp_all_cells_extrapolated` is not on the page. Interval:
  `region_ratio_draws` bootstraps each region over its own areas from `BOOT_MIN_AREAS` (3), else
  a stated x/÷2 (`JUDGEMENT_CI90`); the summary's `interval` names which. Blobs inside a
  registered farm area count nothing (`--labels-dir`).
- **Farm quadrats carry `_farm_calib_` in their stem** (`roofclf.FARM_QUADRAT_INFIX`;
  `new_calibration_quadrat.py --farm`). `roofclf.discover_quadrats` skips them unless
  `farm=True` (a ground array would label the farmhouse beside it as PV-carrying).
- **A mapped polygon is priced by its tag** (`roofclf_ground.panel_area_factor`):
  `power=generator` is the array; `power=plant` is a site, counted at 0.05/0.18 of its area, or 0
  when a generator inside it carries its panels; nodes count 0. **`osm_panel_tracers`** in
  `configs/aoi.yaml` names mappers whose polygons are panel traces whatever the tag
  (`labels.panel_traced`, written as `panel_traced` by `prepare_national_osm_solar.py`); the
  evidence atlas prices those ground polygons at the MODULE constant. Matched on last editor
  (`osm_user`/`osm_version`; `overpass.element_meta_by_id` annotates older pulls).
- **Two label sources.** Clean areas (farm quadrats, `--clean-region`) give precision, threshold
  and capacity ratio. Weak areas (`--weak-region`: ordinary OSM, oversized rectangles, nodes)
  train only, as multiple-instance bags.
- **Thresholds are logits**, not probabilities (a balanced fit saturates strong detections at
  p = 1.0 in float32).
- **Vetoes**: >= 30% of a blob within 8 m of a paved OSM road; SWIR more than 20% below the
  blob's ring (water-harvesting ponds; MNDWI fails in a dry-season median); no pixel within 50 m
  of a building, cropland or green pixel; a blob over 25,000 m² (`MAX_BLOB_M2`).
- **The capacity estimand defaults to arrays below 400 m²** (`--max-array-m2`; `0` prices every
  size).
- **Overpass is a cached dependency**: area labels in `data/roofclf_ground/<aoi>/areas/`, paved
  roads per 1-degree chunk in `data/roads/<aoi>/`. National scoring never calls it; the road veto
  is applied in the capacity step. A chunk that cannot be fetched leaves its blobs with
  `road_checked=False`, reported in the summary.
- **Farm candidates exist for Yemen, Egypt, Morocco, India, Pakistan and South Africa** (8 each);
  `calib-publish` ranks them after every building box. Pakistan has no `compose_window` or
  `division.iso3` in `configs/aoi.yaml`, so the sampler takes `--window-start 2025-11-01`.
- **Yemen is the only country with farm areas**: seven ('Amran plus six Tihama areas cut where
  Esri imagery is from 2024-10 on), 169.1 MWp (90% 77-327) in 34 cells. The rest of Tihama is a
  training-only weak region (`data/labels/yemen/tihama_stale_imagery_region.geojson`). Analysis
  and the owner's lead review: `results/yemen_agripv_testground/`.

### Glint

Sentinel-2's specular-glint response is a secondary, corroborating signal, not a standalone
detector (`docs/methods/glint.md`):
- **Direct per-target detection** boosts (never demotes) `rank_score`: detection rate rises from
  ~6% to ~73% with installation size; validation plateaus around 26-31% for arrays ≥ 1,000 m².
- **Per-pixel SCL cloud masking** (`glint._read_target_scl`), gated on the annulus, not the
  target (a real glint is often saturated-bright, which SCL also flags as cloud).
- **Tile copies count once and asset URLs are re-signed per read.** Overlapping MGRS tiles
  deliver one pass as 2-4 items seconds apart: `annotate_spikes` collapses them
  (`one_row_per_acquisition`) and `dedupe_items=True` avoids fetching them.
  `glint._asset_href` re-signs Planetary Computer URLs at open (the client's cached 45-min token
  silently dropped scenes in long pulls). The 662-candidate `p_unmapped` sample predates this and
  is unchecked (open question 2).
- **Opportunity-normalized sensitivity** (`src/earthpv/glint_opportunity.py`): the capacity
  calibration models `k ~ Poisson(q_b * opportunity)` instead of dividing by a flat per-bin
  sensitivity.

### MaStR validation (Germany)

`mastr_validation.py` / `earthpv validate-mastr` checks against a legally complete register.
**65.5% of German rooftop capacity sits below the 400 m² / 72 kWp floor**, and that share is
**not transferable as a flat constant** (0.25-1.00 across municipalities, 5th-95th percentile;
France's register brackets its own share at 17-31%). Germany's grid covers 96.2% of Gemeinden by
count, 99.75% by capacity. Read the **above-floor** block of the comparison (truth =
`kw_rooftop - kw_le_72`), not the all-capacity one. German OSM (~3.6% of registered rooftop
units) cannot serve as a completeness reference.

**The register as a precision instrument** (`scripts/mastr_p_unmapped.py`,
`calibrate-candidates --mastr-p-unmapped`). MaStR geolocates units only at/above 30 kWp (a
privacy policy), so a registered unit's point inside an unmapped candidate is direct evidence the
candidate is real, for exactly segmentation's population; the register is silent over `roofclf`'s
domain. `derive_placement_tables` takes it via opt-in `p_unmapped_by_placement` (omitting it
reproduces old behaviour; Pakistan unaffected). **The chance term must be land-use matched**: the
null is the base rate among buildings the model did NOT detect, same cells, same size bin (large
German roofs carry registered PV often); a displaced-polygon control measures how empty farmland
is instead. Correction is `(obs - f) / (1 - f)`, a lower bound. `>50k m²` and all ground keep the
displaced control.

**OSM rooftop polygons convert at a size-dependent constant in Germany**
(`capacity_calibration.osm_rooftop_kwp_per_m2`, keyed by AOI): German OSM outlines roofs and
sites rather than arrays, measured at 0.200 / 0.189 / 0.139 / 0.051 kWp/m² for <200 / 200-500 /
500-2k / >2k m². Every other AOI returns the flat 0.18. Only `build_evidence_atlas` uses it;
`_size_distribution_data` keeps the flat constant deliberately.

**Germany's roofclf half is calibrated from the register, not quadrats.** The classifier ranks
German roofs adequately on OSM labels; the calibration is one constant, kWp per credited m²,
fitted against MaStR across fully covered Gemeinden (`vg250_gem.parquet`, joins on AGS): **0.2793
kWp/m² (90% 0.2654-0.2926), national 52.37 GWp against a registered 54.29**. Scripts:
`scripts/run_germany_roofclf_production.py`, `scripts/calibrate_germany_capacity.py`,
`scripts/validate_sub400_against_mastr.py`. Production fit: `data/roofclf_germany_prod/` (Germany
plus the French border set, the only foreign data that helped).

**Against a roof-area baseline the sub-400 estimator is regime-specific**: Pakistan roofclf 26.5%
median municipal error against the null's 88.9% (a 3.4x cut); Germany 48.4% against 37.8% (the
baseline wins, and no alternative supervision has beaten it). Where PV is near-ubiquitous,
capacity is close to proportional to roof area. **A national total agreeing with a register is
not evidence the geography is right**: over- and under-prediction cancel, and PyPSA consumes the
per-cell geography.

**Germany's atlas** (`scripts/build_germany_sub400_atlas_inputs.py`): the roofclf component must
be **INCREMENTAL** (sub-400 roofs only, deduped against OSM and segmentation), it is
**pre-aggregated to one row per cell** (25M geometries OOM `atlas._join_buildings_to_grid_cells`),
and its floor tier is "both signals in their top decile", not precision-calibrated. **Published:
Verified 26,635 / Best 84,473 MWp** against ~74,800 MWp registered: Best fails its own register
check, so read the tiers as geography, not capacity (the page says so). Write-ups:
`docs/methods/mastr-validation.md`, `docs/results/germany.md`.

### France validation (ODRE register + OpenPVMapper)

`france_validation.py` / `earthpv validate-france`. France's register **censors units below 36 kW
into per-commune/IRIS aggregates, publishes no coordinates, and has no rooftop/ground field**, so
shares are bracketed, never stated, and there is no `p_unmapped` instrument. It publishes **dated
year-end vintages**, which `interpolate_to_date` reads back to a quadrat's mapping day. Against 14
hand-mapped communes this measures the module constant at **0.150 kWp/m² against the assumed
0.180** (not yet acted on; does not transfer to Pakistan on its own). Write-ups:
`docs/methods/france-validation.md`, `docs/results/france.md`.

- **`tag` on the French labels is load-bearing**: `thermal` (solar hot water) and `false` are
  dropped; `unknown`/`missing` go to `data/labels/france_sensitivity/`. Solar thermal is the
  systematic confusion for imagery detectors.
- **France quadrats live in `data/labels/france/`, NOT `data/labels/`** (where they would join
  the next Pakistani refit); pass `--labels-dir`. `scripts/build_france_quadrats.py` builds them.
  **Saint-Gely-du-Fesc is unfinished** and excluded from every fit by explicit `--quadrat` flags;
  Langoat and Saulny are excluded from the module-constant fit (register hole).
- **Commune-sized quadrats**: `roofclf.building_table` reads seg/frac probability from a single
  0.1° cell, so France runs `roof-classifier` **without `--seg-prob-dir`**.
- **`roofclf` does not transfer to French residential PV** (median fold AUC 0.710 against
  Pakistan's ~0.86; the median French array is 20 m² against a 100 m² pixel). Hence no roofclf
  half. Whether `roofclf` can work is a property of national subsidy design (array size) and
  cannot be inferred from a neighbour.
- **OpenPVMapper** (Kasmi 2026, `doi:10.5281/zenodo.21534856`, CC-BY-4.0) is a model output, not
  ground truth: agreement with it is not validation.
- **Register CSV exports truncate silently on an SSL reset**: `scripts/fetch_odre_vintages.sh`
  re-fetches until the line count is plausible and `load_vintages` refuses any vintage under
  1 GWp.
- **AOI config**: `grid_origin: [-5.15, 41.33]`, `compose_window: ["2024-05-01", "2024-09-30"]`
  (imagery, labels and the 2024-12-31 register vintage in one epoch).
- **Checkpoint: v5** (`data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt`),
  applied to France only. **Candidate precision table**
  `configs/calibration/france_candidate_precision.yaml` is fitted with `--recall-reference none`,
  so France's figures are a **precision floor, not recall-corrected**; quote
  `est_mwp_det`/`est_mwp_exp`, never `est_mwp_cal` or `est_mwp_rc_roof`, in register comparisons.
- **Published (6,021 cells after the border clip): Verified 12,381.7 / Best 13,368.5 MWp** (90%
  11,478-17,762) against a registered 34.6 GWp. `check-density` fails 9 of 13 regions on the
  ground:rooftop ratio, from the missing rooftop denominator.
- **Artifacts**: the v5 register comparison is `results/france_validation_v5/`;
  `results/france_validation/france_validation.json` is a v4 run despite its canonical-looking
  path. `validate-france --pred-dir` takes `data/predictions_v5`, not
  `data/predictions_v5/france` (the wrong one silently skips the floor-recall block).

### Country runs

Owner rules for every new country: **localize** segmentation on the country's own OSM labels,
ship whichever checkpoint scores better on a held-out region (tie goes to local), >= 1,000
buildings per cell plus label cells, end in an evidence atlas, publish by push to main.
Holdouts are picked from the label map before training by `scripts/pick_val_region.py` and
written into `configs/aoi.yaml`.

Machinery: `earthpv-country-queue` (`scripts/run_country_queue.sh`; status
`bash scripts/country_queue_status.sh`; markers `data/country_queue_markers/`; log
`data/country_monitor.log`) and the earlier `earthpv-vn-in-queue` (`scripts/run_vn_in_queue.sh`,
`bash scripts/vn_in_status.sh`, `data/vn_in_monitor.log`) pull labels, run the thermal filter and
compose, then hand each country to `scripts/run_country_compute.sh <aoi>` (chips ->
`mark_val_buffer.py` -> merge -> train -> `pick_best_checkpoint.py` -> `compare_local_vs_v5.py`
-> infer -> atlas chain, behind markers in `data/<aoi>_pipeline_markers/`). **The queue decides
an atlas is finished by grepping `data/<aoi>_pipeline.log` for "ATLAS DONE"**, so removing
`<aoi>_atlas_done` does not relaunch a finished country: re-run its steps as a one-off unit.
**Editing a script a unit is running is unsafe** (bash reads incrementally): restart the unit.
Before stopping a compose unit by hand, `rm data/vn_in_queue_markers/<aoi>_round_start`; stop the
QUEUE first when removing compute markers.

| Country | Checkpoint | Verified / Best (MWp) | Notes |
| --- | --- | --- | --- |
| Pakistan | `v3_combined_india` | 6,994.1 / 34,588.8 | roofclf half, probability-weighted; see "Density stage" |
| Germany | `v4_combined_all` ep 41 | 26,635 / 84,473 | register-calibrated roofclf; Silver |
| France | `v5_combined_france` | 12,381.7 / 13,368.5 | precision floor, no roofclf |
| India | `v5_combined_france` | 67,592.6 / 72,271.1 | v10 lost the Gujarat holdout |
| Vietnam | `v9_combined_vietnam` | 8,179.8 / 8,860.5 | |
| Egypt | `v12_combined_egypt` | 3,315.1 / 3,378.6 | thin Cairo holdout |
| Yemen | `v13_combined_yemen` | 130.9 / 302.1 | zero-zero tie; farm ground PV; Silver |
| South Africa | `v14_combined_south_africa` | 9,393.8 / 9,755.6 | decisive localization win |
| Morocco | `v11_combined_morocco` | 380.4 / 411.2 | tie near 1.0; AOI stops at 27.7N |
| Poland | `v15_combined_poland` | 6,604.3 / 7,780.9 | |
| Zambia | `v4_combined_all` ep 41 | 505.8 / 526.3 | |
| Nigeria | `v5_combined_france` ep 25 | 90.2 / 120.9 | name `v8` is taken by `v8_combined_nigeria` |

Per-country write-ups are `docs/results/<country>.md`. Country-specific points still in force:
- **India**: Verified is almost all ground perimeters. 253 solar-thermal features (~0.7% of both
  tiers) remain as a known defect. **The compose is being widened by `ring_cells: 3`** (+3,573
  cells); the downstream re-run is `scripts/run_india_ring_chain.sh` (markers
  `data/india_ring_markers/`), writing `results/india_pv_evidence_atlas_ring.html` beside the
  published page; the published run is kept in `/home/tobi/earthpv_data/india_PRE_ring_20261024/`.
  8 label cells (six at Khavda) are uncomposed (open question 11).
- **Yemen**: segmentation finds almost none of its labels (small Tihama irrigation arrays barely
  differ from their surroundings), so Best is the OSM map plus farm ground PV.
- **Egypt**: the model's rooftop estimate is ~0 (no rooftop candidate matches a mapped rooftop).
- **Morocco**: geoBoundaries MAR includes Western Sahara, so `atlas.build_evidence_atlas` clips
  region outlines to the AOI bbox.
- **Poland**: compose snaps the grid to the country's own lower-left, so the ground screen and
  `pick_val_region.py` use `density._grid_origin`, never the raw `grid_origin`.
- **South Africa / India**: capacity-tagged parks measure 0.045 kWp/m² (mostly AC) against the
  0.05 land constant.

Opt-in pieces built for large countries (other AOIs keep their behaviour):
`fetch_geoboundaries` caches to `data/geoboundaries/gb_<ISO3>_<LEVEL>.geojson`, and
`EARTHPV_REQUIRE_BOUNDARY=1` makes compose fail closed instead of renaming every cell;
compose network hardening (GDAL `TCP_KEEPALIVE` + `LOW_SPEED_TIME=60`, `EARTHPV_NET_TIMEOUT_S=120`,
`EARTHPV_FORCE_IPV4=1` via `compose._harden_python_network`; stall watchdog 900 s);
`prepare_national_osm_solar.py --keep-detected-screen` keeps ground features above the 5 km² cap
on the screen's evidence (the cap is German); `overpass_labels_chunked.py` caches tiles and
resumes (`--fetch-only`); `scripts/ranged_download.py` (source.coop throttles single streams);
`parquet_metadata_cache` on every DuckDB connection.

**Solar-thermal is in OSM under the same `generator:source=solar` tag.**
`scripts/drop_solar_thermal.py --aoi <aoi>` drops thermal/CSP elements from the labels before
chips (`--by-id` at India's size, where the bbox scan fails); `--candidates` drops candidates at
least half inside them before `density`. Countries before Morocco are unfiltered. The backup is
named `<aoi>_solar_labels_with_thermal.parquet` because `chips._newest_overpass_path` globs
`<aoi>_overpass_solar*.parquet` and takes the last name in sort order; a backup matching that
glob silently undoes the filter (dotted stems are now ignored).

## Conventions & gotchas

- **GPU:** the target card is a **GTX 1060 (Pascal, sm_61)** → PyTorch must be **cu126** wheels
  (CUDA 13 dropped Pascal). Pinned in `pixi.toml`.
- **`data/` is gitignored** and lives on the external drive
  (`/run/media/tobi/aidisc/earthpv/data/`): `chips/`, `composites/`, `models/`, `predictions/`.
  Files there are invisible to git/IDE explorers that hide ignored files.
- **`row.mask` / `row.image` on a pandas row:** use bracket access (`row["mask"]`) -- `.mask`
  resolves to the `Series.mask` method. **A column named `cov` is the same trap**
  (`DataFrame.cov`). Name columns something pandas does not already define, and prefer brackets.
- **Selecting "the best checkpoint" by mtime is wrong.** `train.py` sets `save_top_k=2`, so
  `ls -t | head -1` returns the SECOND-best whenever the final improvement is not the argmax. A
  restarted run leaves the dead run's files in the same directory and Lightning writes the live
  run's state to `last-v1.ckpt`. Use `scripts/pick_best_checkpoint.py`, which reads Lightning's
  own `best_model_path` from every `last*.ckpt` and takes the best score.
- **`scripts/merge_chip_index.py` writes `data/chips/combined/index.parquet` unless `--out` is
  given**, which is an existing corpus: pass `--out` or back it up first.
- **`roofclf.discover_quadrats` globs `*_calib_*_boundary.geojson`.** A quadrat stem without
  `_calib_` is invisible to `earthpv roof-classifier`, which fails with "No calibration quadrats
  found" seconds after launch -- easy to mistake for a still-running job. Anything in
  `data/labels/` matching the glob joins the next Pakistani refit (keep other countries' quadrats
  in `data/labels/<aoi>/`).
- **`export.load_mapped_reference_attrs` globs `data/labels/*_overpass_solar.parquet`
  AOI-agnostically**, so every country's pull in that directory enters every AOI's mapped
  reference. Matching is spatial, but `recall_reference` provenance counts change (Pakistan's
  table documents 18,276); move other countries' files aside before re-deriving Pakistan's table.
- **A "national" OSM pull is not national until it is clipped to the border** (a bbox pull is
  not a border pull). `prepare_national_osm_solar.py` builds the `--osm-solar` input: it clips
  on the geoBoundaries ADM1 union by default (`--no-clip` opts out), maps `small` -> rooftop,
  reclassifies rooftop features above `MAX_CANDIDATE_M2` as ground, and drops ground features
  above 5 km² unless `--keep-detected-screen`.
- **Overture prunes its release directory to the last two releases.** A pinned
  `overture_release` eventually 404s as `IO Error: No files found`, which reads like "no data
  for this area". Check
  `https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/?list-type=2&prefix=release/&delimiter=/`.
  For France the DGFiP cadastre gives the same footprints per INSEE in ~2 s.
- **Anything that loads every scored building at once will OOM** (25M buildings reprojected
  peak at 22.7 GB); stream per cell. Run long jobs with `--property=MemoryMax=` so a regression
  fails fast rather than thrashing swap.
- **A new atlas component must be INCREMENTAL before it goes in.** Best already carries
  segmentation's detections and the hand-mapped OSM population, so a component crediting every
  building double-counts.
- **The native-20 m bands are resampled BILINEAR for fresh AOIs; never mix modes within an
  AOI.** Composites carry an `earthpv_resampling` tag (absent = nearest); Pakistan, Germany,
  France, Zambia and Nigeria are `nearest`. `compose` INHERITS an AOI's existing mode
  (`imagery.BAND_RESAMPLING`, `compose --resampling`), so a resumable run cannot mix the two.
  Recompose a country wholesale or leave it alone. SCL stays nearest always.
- **`roofclf`'s zonal means are AREA-WEIGHTED by default, and calibration and national scoring
  must never disagree about that.** `roofclf.area_weighted_zonal_mean` weights each 10 m pixel by
  the fraction of the footprint covering it (`preprocess.coverage_matrix`, subpix 4) instead of
  pixel-centre sampling, where 72.4% of Pakistani VIDA footprints own zero pixels. Applied in
  BOTH `building_table` and `score_buildings_national`, resolved from
  `roofclf.AREA_WEIGHTED_ZONAL`, recorded in `model_full.json` and the scoring's `_model.json`;
  `check_scoring_matches_calibration` refuses a mismatch. Nodata is masked with the same
  all-bands-equal-fill test `zonal_mean_max` uses, and a footprint with no subpixel keeps the
  pixel-centre value rather than becoming NaN. `--no-area-weighted` reproduces the older figures.
- **`preprocess.trimmed_mean_stack` replaces `np.nanpercentile` in every stack-reading path**
  (`np.nanpercentile` falls back to a per-slice Python loop on any NaN: 24.5 s against 0.08 s);
  bit-identical results.
- **A pre-2022 composite layer is on a different radiometric scale** (no BOA offset before
  baseline 04.00; every model here is fitted on post-2022 composites at +1000 DN). Pakistan's
  composite_1 offset is **per cell, not flat**: 122 cells built 2026-07-05 already match
  composite_0, the rest read ~800 DN darker with a wide spread. Harmonize per cell (match each
  band's window median to composite_0; `scripts/composite1_offset_survey.py`) before scoring one,
  e.g. via `roofclf.epoch_feature_frame(..., dn_offset=...)`. An old epoch is not a negative set
  for `roofclf` (it reads adopter-type roofs as much as panels).
- **Training positive threshold** is `MIN_PV_AREA` in `chips.py` (arrays below it are burned as
  `ignore = -1`, not negatives). Changing it requires rebuilding chips and retraining.
- **Geographic val split** uses `val_tiles` in `configs/aoi.yaml`; these must be MGRS tiles the
  `source_region` actually downloaded, or the val set ends up empty (datamodule then falls back
  to a random 20% split).
- **Areas are geodesic** (`labels.geodesic_area_m2`), never `.area` on lat/lon geometries.
- Long GPU/network stages are run detached and polled; the rich progress bar does not flush
  cleanly to a redirected log, so watch checkpoint files / cell counts rather than the log.
- **The aidisc drive is the binding constraint; `/home` (sda4, ~1.2 TB free) is where bulk
  outputs belong.** Composites and national scoring passes live under `/home/tobi/earthpv_*` and
  are symlinked back into `data/` (`data/composites/<aoi>` -> `/home/tobi/earthpv_composites/<aoi>`).
  **A new AOI's composites MUST be symlinked onto `/home`, never written straight into
  `data/composites/<aoi>/` on aidisc** (~10 MB per cell). A full disk does not name itself:
  `compose` dies with Python **exit code 120** (failure to flush stdout) and a truncated log.
  Committed cells survive (atomic `.tif.tmp` rename), so recovery is move, symlink, resume. Check
  `df -h /run/media/tobi/aidisc` BEFORE a national run; moving and symlinking preserves data,
  deleting does not.
- **A country-scale `compose` leaks file descriptors and degrades before it dies; run it in a
  restart loop capped by WALL CLOCK** (e.g. `timeout 7200` per pass, rc=124 as the expected
  path), not by waiting for a crash -- a degraded pass looks healthy from outside while running
  at a quarter of the rate. It is resumable and idempotent, and a fresh pass also re-signs the
  Planetary Computer SAS token (~24 h lifetime; on 403s `annual_composite` fails over to Earth
  Search and the data stays fine). Let "a pass added nothing" be the stop condition.
- **With `workers` > 1, set `imagery.PC_TIMEOUT_S` to several times the expected per-cell wall
  time, and `compose_loop.sh`'s `STALL_S` well above a pass's startup cost plus one slow cell.**
  Compose is bandwidth-bound (~290 MB per cell), so under N workers a healthy cell takes ~N x its
  uncontended time; the default 60 s patience then trips on every cell and each hand-off
  downloads the cell twice, a livelock that reads exactly like a provider outage. Diagnostic:
  measure the link (an outage leaves it idle, this leaves it saturated) and count `exceeded <N>s`
  hand-offs per landed cell. A compose that is "progressing" is not evidence the patience is
  right.
- **`nohup setsid` alone does not survive a session logout on this machine.** systemd-logind
  kills a whole session's cgroup unless lingering is enabled: check
  `loginctl show-user "$USER" | grep Linger` and `loginctl enable-linger "$USER"` once before
  anything multi-hour. Run each long job as its own `systemd-run --user` unit.
