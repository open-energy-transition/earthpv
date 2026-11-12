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
country's own OSM labels, and twenty-one countries have a published evidence atlas (see "Country
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
  published rasters come from `v16_combined_pakistan` since 2026-10-28, `v3_combined_india`
  before; the others are listed under "Country runs").
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
  against each other and against OSM, and floored per cell at **Verified** plus any park a person
  judged solar there (hand-mapped OSM
  plus the stricter roofclf+SPPI agreement population). Best carries a 90% credible interval.

The end-to-end command sequence is in `docs/reproduce.md`'s "The full pipeline"; the short
version:

```bash
earthpv labels --aoi <aoi>       && earthpv chips --aoi <aoi>
earthpv train  --config configs/terramind_pv.yaml
earthpv infer  --aoi <aoi> --checkpoint <ckpt>
earthpv postprocess --aoi <aoi> --threshold 0.3
earthpv export --aoi <aoi>
pixi run blob-review draw --aoi <aoi>   # the solar farm review: every outline above the merge
#   cap. Judge in data/oversize_review/index.html, then `pixi run blob-review apply --verdicts ...`
pixi run large-review draw --aoi <aoi>  # the large installation review: leads 10,000 m2 up to
#   the cap. Judge in data/large_review/index.html, then `pixi run large-review apply ...`
earthpv density --aoi <aoi> --districts && earthpv check-density --aoi <aoi>

earthpv roof-classifier --aoi <aoi>                 # needs mapped calibration quadrats
earthpv roofclf-score-national --aoi <aoi>          # long: hours at country scale

# ESSENTIAL, not optional -- run after every national scoring pass. See
# docs/methods/roofclf-national-validation.md.
pixi run roofclf-tiles -- --random-cells 20 --seed <fresh int> --mapcss

earthpv ge400-roof-capacity --aoi <aoi> --osm-solar <national OSM solar pull>   # before sub400
earthpv sub400-capacity     --aoi <aoi> --osm-solar <national OSM solar pull>
# NOTE: --sub400-outdomain-cells is deliberately NOT passed -- see "Density stage".
earthpv roof-potential --aoi <aoi> --roofclf-dir data/roofclf_national_with_sppi/<aoi>/prob \
  --roof-table <calibration buildings.geoparquet> --osm-solar <national OSM solar pull>
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

**The solar farm review is part of this workflow too (owner, 2026-11-02).** A very large
model outline (a blob) stays out of capacity until it is mapped or a person judges it solar, so
one look per outline is the cheapest capacity there is to verify. `run_country_compute.sh` draws
a country's package after `export`; `data/oversize_review/index.html` lists every country's page,
`pixi run blob-review status` the counts. Sittings can be partial: apply any export, then
`density --districts` (no `--force`) and the atlas. An agent prepares this and never judges it.
See "Density stage".

**So is the large installation review (owner, 2026-11-10)**: the same disk page for the leads
from `LARGE_MIN_M2` (10,000 m²) up to the cap, rooftop and ground (`pixi run large-review`,
`scripts/oversize_review.py --kind large`; `results/<aoi>_large_review/`, packages in
`data/large_review/` -> /home, ~190 KB per lead). `run_country_compute.sh` draws it after the
blob page (both retried once, never fatal: a 2026-11-09 DNS outage left Belgium's blob page
missing while its step read done). Any named reviewer's verdict counts (owner), and it is a
documented way to contribute for people who run EarthPV (`docs/contribute/review.md`). The 18
countries with a run (about 37,000 leads; India 9,935, Germany 7,592) were queued 2026-11-10 in
unit `earthpv-large-review-draw` (log `data/large_review_draw.log`, smallest first);
`pixi run large-review status` says which have pages. The owner judged seven 2026-11-10
(Belgium, Egypt, Netherlands, Nigeria, Portugal, South Africa, Yemen: 2,335 of 2,443 leads,
1,381 solar, 108 unsure), applied the same day, roofs at 1/2.5 (owner). Large ROOF leads are
priced far too low: their bins put P(real) at 0.00-0.07, and the owner found 92-99% solar in
Belgium, the Netherlands, Portugal and South Africa. Rebuilt and published the same day
(`/home/tobi/earthpv_data/lead_review_20261110/rebuild.sh`, density backups in
`lead_review_PRE_20261110/`; controls with the verdicts hidden reproduced all seven pages
exactly); the Netherlands' and Portugal's first pages went out with their verdicts, also
2026-11-10, and the owner judged Namibia's 105 the same day (10 solar, 95 not, 64 of them
Cuvelai pans; Best 530.2 -> 512.3). Best: Belgium 639.3 -> 970.8, Netherlands 3,927.2 -> 4,567.3, Portugal
6,147.9 -> 6,193.6, Yemen 586.2 -> 623.6, Egypt 3,809.9 -> 3,848.7, Nigeria 126.9 -> 157.3,
South Africa 9,839.0 -> 10,075.9; Verified unchanged. Esri's `export`
answers HTTP 500 for detail finer than it holds (Namibia, Zambia, Yemen: zoom 17), so `_esri`
steps down to half and a quarter of the pixels. Pricing: "Density stage". **Both pages
carry a fourth verdict, key 4 "Bright roof" (owner, 2026-11-10)**: not PV on a very bright
roof, priced as `not_pv`, kept apart as `flag: bright_roof` in review.csv (`review_flag` in
review.geojson, a column in `status`) so the false alarm can be studied
(`build_review_page.write_page(bright_roof=True)`; the other pages that share it keep three
keys, since their joins know only those).

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
- **TerraTorch's TerraMind backbone does not standardise its input** (only its generation and
  TiM builders take TerraMind's pretraining mean/std), so every checkpoint up to v20 saw DN /
  10000, each band's spread 5-8x narrower than in pretraining. `backbone: earthpv_terramind`
  with `backbone_variant: terramind_v1_*` (`terramind_backbone.py`) applies TerraMind's own
  statistics inside the model, like `thor_backbone`; existing checkpoints load unchanged. A
  frozen-feature probe put held-out token AP at 0.469 on DN / 10000 against 0.737 (corpus
  statistics 0.452), but **v21** (v14's recipe and corpus, `scripts/run_tmnorm_compare.sh`,
  2026-10-30) shows it does not survive full fine-tuning at 1e-4: rooftop recall 0.575 against
  v14's 0.574 at matched precision, ground 0.6 points lower, France worse at both saved epochs;
  it only converges in half the epochs. Rejected; untested with a lower encoder LR. TiM
  variants cannot take our 10 bands. Small and Base fit the 1060 at batch 8 (1.0 / 2.7 GiB
  peak, 2x / 4.9x Tiny's step time).
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
site"), and add any official figures to `scripts/official_capacity.py` and re-run it.

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
records 19,491 features). **Pakistan's table was re-derived 2026-10-26 for v16**, with the
any-candidate recall, and again **2026-11-07 with 41 calibration boxes** (the three random
boxes of Box 21 and Jhang f2 held out), as `status: interim-mapped-only`: `p_unmapped` from
mapped installations only, no glint sample in any bin yet. None of the eleven boxes added then
holds a v16 candidate, so they add recall evidence only (`est_mwp_rc` 3,143.1 -> 3,146.8).

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
and `calibrate-candidates`. The Verified layer carries that outline at the same share
(`screen_credit`, below) rather than dropping it, so Best takes it whole through its per-cell
floor instead of the model figure, which the size bin's `p_real` halves a second time.

**Model outlines above the cap (blobs) count only once a person has judged them (owner,
2026-11-01).** A blob never enters capacity until it is mapped in OSM or carries a `pv` verdict
in the country's review: `scripts/oversize_review.py draw|apply` writes an `oversize_review`
block into the calibration table, and `density.load_oversize_admission` admits exactly the
new-lead outlines (`export.new_lead_mask` at the review's `min_distance_m`) with a `pv` verdict
in its `review_csv`, matched by `candidate_index` and area, whole (`p_real_fixed` 1, stratum
`reviewed`), placed as ground, recall 1. One judged and then mapped leaves the pool and is
counted from the map; a verdict naming an outline the candidates do not hold at that area is an
error (a new model run needs `draw --redraw`). From 2026-10-29 to 2026-11-01 India admitted 1,650 at
the review's census and sample shares (30 of the 30 largest, 51 of 58 drawn by area; +28,468
MWp); now only its judged parks (1,427 of 1,789, 577 km2). The owner judged the queues of
eleven more countries 2026-11-03 (913 of 919 outlines, 176 parks; applied 2026-11-04,
`/home/tobi/earthpv_data/judged_PRE_20261104/` holds each density before), and Turkey's
774 on 2026-11-06 (773 judged, 396 parks, 89.8 km2, +4,489.6 MWp;
`/home/tobi/earthpv_data/judged_PRE_20261106/`), and Germany's 581 the same day (149 parks,
32.4 km2, +1,619.1 MWp; its density, last run 2026-09-15, also took -82.0 from the 11 October
rule; the 43 on band-loss composite cells all judged not solar). Re-running `density` for it also applies the 11 October rule (a mapped
outline above the cap is ground) to pages built before it: Best moved by it in Vietnam
(+2.7 MWp) and France (-8.2). Best's per-cell floor is Verified
plus the judged parks in the cell (owner, 2026-11-02; `build_evidence_atlas` and
`_size_distribution_data`, which must agree). `draw` queues every blob (stratum
`queue`, largest first; since 2026-11-02 the default, census and sample only on request) and
`apply` takes a partial export, keeping earlier verdicts; a blank or unsure queue outline stays
out and returns on the next page; `excluded_regions` no longer filters (a verdict outranks it).
**The queue is the published blob file's population** (`oversize_review.lead_screened`: the
page's regions and the lead screens; `run_source` takes the candidates and reference behind the
published atlas from `release_leads.SOURCES`, plus France's
`data/labels/france_mapped_20261022.parquet`). They are population-level
only: kept out of `process_cell`, so cached partials stay valid and no `--force` is needed.
`calibrate-candidates` does not see them (the bins describe the rest) and carries the block
forward; `_table_evidence` guards it. A country without the block keeps the cap exactly; its
unmapped parks above the cap appear only in the new-leads export.
**The review is a disk review of the imagery the model saw (2026-10-29).** `draw` (a
non-fatal step of `run_country_compute.sh` after `export`) also runs `package`: one 2 x 2 JPEG
per outline in `data/oversize_review/<aoi>/crops/` (composite true colour, 10 m detail, false
colour SWIR/NIR/red, Esri with capture date; FIXED reflectance stretch) and `index.html`, the
`build_review_page.write_page` page (keys 1/2/3, notes, Google/Bing/Wayback/JOSM links, CSV
export, `<aoi>_blob_verdicts.csv`; a judged outline leaves the page on the next `package`,
`--include-judged` keeps it). `apply --verdicts <export>` refuses unsure census or sample rows
unless `--unsure-as`, and reports agreement with earlier verdicts; `draw` never redraws over
verdicts (`--redraw`, which also clears the crops). The page's saved progress is keyed to the
draw, so old verdicts cannot attach to a redraw's codes. The composite
decides epoch (11 of India's 50 sampled parks postdate Esri), Esri decides texture (dark ploughed
fields read as panel blocks at 10 m): neither panel alone suffices.

**A verdict on a lead below the cap replaces its size bin's P(real) (owner, 2026-11-10).**
`apply --kind large` writes a `lead_review` block (`capacity_calibration.LEAD_REVIEW_KEY`;
`min_area_m2`, `review_csv`, `mapped_reference`, `min_distance_m`, every reviewer's name).
`density.load_oversize_admission` returns its verdicts in the same frame as the blob rows
(column `p_real_judged`: `not_pv` 0, `pv` 1 on the ground and 1/`rooftop_outline_ratio` on a
roof; `_lead_verdicts`), so every caller of
`capacity_relevant_candidates` gets them with no change; `cc.candidate_p_real(judged=...)`
applies them at the five call sites that price candidates (`density.judged_of`). Unlike a blob,
a judged lead KEEPS its bin's recall (it is one of the installations recall was measured on),
its placement and its kWp constant; it stays in `process_cell`'s candidate set (cached partials
valid) and in `*_det`. Uncertainty: a constant P(real), recall drawn. Best's per-cell floor
adds judged leads at their verdict's share and their own placement's constant
(`atlas.judged_floor_kwp`, shared by `build_evidence_atlas` and `_size_distribution_data`; the
cell column keeps the name `judged_park_mwp`). Unsure or blank changes nothing; a lead mapped
since rests. `calibrate-candidates` carries the block forward and `_table_evidence` guards it.
Checked 2026-11-10: with no block, Poland and Belgium rebuild to their published Verified/Best
exactly; with 40 synthetic verdicts on a scratch Belgian run (14 rooftop `pv`, whole), Best
639.3 -> 822.3 and the size chart re-bins it. **A roof lead judged solar counts 1/2.5 of its
outline, a ground lead whole (owner, 2026-11-10;
`capacity_calibration.LEAD_ROOF_OUTLINE_RATIO`, recorded per block as
`rooftop_outline_ratio`)**: Pakistan's roof outlines of 5k-50k m2 are 2.52x the mapped array
(open question 17), which a bin's P(real) used to absorb. Measured in Pakistan only.

**`buildings.geoparquet`'s summed rooftop capacity is not `grid.geoparquet`'s region total,
by construction**: the region total sums each rooftop candidate's full polygon once, the
per-building table credits only the intersection with each building capped at its roof area
(~46% gap nationally in Pakistan). Per-building disaggregation is a conservative floor.

**A model outline is ~2.4x the panel area it found** (Pakistan rooftop >= 400 m², 2.5 inside
Rule-1 quadrats; `scripts/candidate_area_bias.py` on PRE-substitution candidates, open
question 17). Published capacity barely sees it (matched candidates carry their OSM outline,
and bin `p_real` discounts the rest to ~0.9 of mapped area); it bites wherever `p_unmapped`
credits unmatched candidates as real, i.e. Germany's register-derived bins.

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

**A foreign quadrat table can train a country's fit** (`roof-classifier --extra-table
<other>/buildings.geoparquet --extra-share 0.5`): its rows enter every fold's training and the
deployment fit at that share of the likelihood, are never a fold, and never reach the coverage
ratio. Pakistan's unchanged model ranks Yemen's four building boxes with PV as well as Yemen's
own (median AUC 0.809 against 0.813; equal-share pooling 0.818, `data/roofclf_yemen_pk_pooled`;
unweighted pooling loses the farm areas), so ranking is not Yemen's problem: the level and
the rural false positives are (`scripts/roofclf_transfer_yemen.py`).

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

**Pricing low-probability open ground apart exists but is not adopted (2026-11-01).**
`calibrate-candidates --confidence-split 0.9` (off by default) or
`scripts/split_calibration_tables.py` (splits a checked-in table's ground bins, keeping its
recall rows and evidence) adds a third placement table, `capacity_calibration.LOWCONF_GROUP`,
for the lead rule's class; every pricing call passes `confidence`, and `_placement_group`
refuses a split table without it. It RAISES the model's priced capacity in 12 of 13 countries
(the confident ground outlines get their own, higher mapped share) yet moves Best by under
0.5% (South Africa -35.5 MWp; controls reproduce the published pages exactly). Owner decision.

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

**Pakistan's current published figures (2026-11-07).** Segmentation (v16, 41-box table)
`est_mwp_rc` **3,146.8 MWp** (rooftop 1,994.3, ground 1,152.5). roofclf (fitted on 41 areas
since 2026-11-07, 16 features without `bf_confidence`, parcel label, area-weighted zonal means,
recall-corrected, probability-weighted since 2026-10-25), its coverage ratio and area recall
fitted on the **19 pinned areas** (`sub400_capacity.PINNED_COVERAGE_QUADRATS`, see "Calibration
quadrats"), as priced in the atlas: sub-400 central **24,381.0 MWp**, sub-400 AND-gate (floor,
thresholded, uncorrected) **3,500.7 MWp**, ≥ 400 m² rooftop replacement **7,257.9 MWp**; median
LOQO fold AUC 0.8459 over the 41 areas (0.8678 over the 30 earlier ones, against 0.8682 before),
within-size 0.815, deployment threshold 0.2470 (precision 0.50, recall 0.642). Atlas: **Best
34,470.3 MWp (90% CI 28,628-41,310), Verified 7,138.3 MWp (90% CI 6,182-9,116)** (30-area fit
with `bf_confidence` until 2026-11-07: Best 34,142.4, Verified 7,350.8; on `v3_combined_india`
until 2026-10-28: Best 34,588.8, Verified 6,994.1; thresholded until 2026-10-25: Best 24,438.3,
90% 20,894-33,666). `check-density` passes all 7 regions (Gilgit-Baltistan exempt from the ratio
check). **The mandatory random validations of the last four rescorings (seeds 20260817,
20260820, 20260920, 20261107; tiles in `results/pakistan_roofclf_parcel_validation/`,
`results/pakistan_roofclf_validation/` and `results/pakistan_roofclf_q41_validation/`) have NOT
been reviewed**: `results/roofclf_random_validation_log.csv` has 80 rows with blank verdicts,
so the published figure rests on an unreviewed rescoring (open question 3). **The score-level
review** (`scripts/roofclf_level_review.py`, 400 blind roofs in 100-1,000 bldg/km² cells,
`results/pakistan_roofclf_level_review/`) tests whether scores sum to the PV-roof count the 9
lower-band quadrats imply (1.115 / 1.270 per PV roof under the 30-area model; 1.136 for the
lower band under the 41-area one); drawn 2026-10-28, not yet reviewed. The coverage ratio's
lower band (< 1,717 bldg/km²) prices 2,937 of 2,957 in-domain cells from those 9 quadrats. Pre-change outputs are kept beside the canonical paths with `_PRE_<change>_<date>`
suffixes.

**Overture publishes a coastal admin division twice** (land, and land plus territorial waters).
**Keep the LAND polygon, the SMALLER of a nested pair** -- "keep the largest" picks the wrong one
every time. `density.drop_nested_duplicates` (in `load_admin` at both levels, repeated on read
by `atlas._region_rows`) tests **nesting**, not name equality, so genuinely distinct same-name
divisions survive. Only Germany's admin layer was affected; geoBoundaries has no maritime rows.

### One atlas template, one config file per country (`configs/atlas/<aoi>.yaml`)

`templates/pv_evidence_atlas.html` is shared by every country, and everything country-specific
lives in `configs/atlas/<aoi>.yaml`, never in the builder. `atlas_config.load(aoi)` supplies
`title`, `cities`, `calibration_boxes`, `composition_page`, `layers`, `validation`, `map_view` and
three optional confidence blocks (`ground_truth`, `caveats`, `corroboration`). A missing file is
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
  >= / < 400 m²), always as MWp per cell (the per-km² toggle was removed 2026-10-28); the log
  colour scale is refitted per quantity.
  Basemaps: none (night lights), Esri grey canvas, OpenStreetMap, Esri satellite (**CARTO needs
  an API key now**). City labels are HTML (no glyph server); calibration areas are diamonds.
- **More layers**: an opt-in *live OSM solar* overlay queries Overpass from zoom 11 (mirrors can
  lag months, so the status line shows the returned OSM timestamp); readers add GeoJSON/CSV,
  GeoJSON URLs, XYZ tiles or WMS; a country can ship layers in its config (`layers:`, schema in
  `atlas_config`), embedded by `atlas.map_layers_json` (5 MB cap) into a `pv-layers` block.
- **Downloads**: every figure as PNG/SVG/CSV, the map as PNG plus the grid as GeoJSON/CSV,
  re-rendered at 960 px with title and source line, never serialised from screen.
- **Mapping leads (2026-10-28)**: the Downloads section links the country's lead file, its
  model's candidates more than 100 m from any OSM solar feature, from `totals.leads`
  (`atlas.leads_release`, manifest `configs/atlas_leads.json`). The files are GitHub release
  assets, never embedded (India's is 91 MB): `scripts/release_leads.py --out <dir> [--upload]`
  rebuilds them with export's ranking and `candidate_id`s from the run behind each page (Nigeria
  from `data/predictions_v5_nigeria`), clipped to the page's regions, and refuses a run whose
  regions differ from the page's; France links its audited `france-osm-leads-2026-10-22`.
  `scripts/patch_atlas_leads.py` adds the link to a published page without a rebuild (and
  re-resolves the badge, below). **A new country gets its file only when `release_leads.py` is
  re-run for it** (add it to `SOURCES`).
  **Blobs have a file of their own (owner, 2026-11-01)**: leads above `MAX_CANDIDATE_M2`
  (100,000 m2) go to `<aoi>_pv_blob_leads.geojson`, largest first (`release_leads.split_blobs`,
  manifest `blobs`, linked on the same card); `--resplit` split the 11-01b files in place,
  keeping their `made` date. 100,556 leads and 3,127 blobs; France's audited release already
  kept its 29 apart (`france_pv_leads_oversize.geojson`).
  **Every outline in one GeoParquet (owner, 2026-11-11)**: `scripts/release_polygons.py
  --aoi <aoi> --out <dir> [--upload]` writes `<aoi>_pv_polygons.parquet` (`source` model or
  osm: the run's candidates inside the page's regions, any size, with `osm_within_100m` and
  any `review_verdict`, plus the atlas's `--osm-solar` file and its CSP plants; zstd 19,
  Hilbert order, GeoParquet 1.1 bbox column, model coordinates at 6 decimals) to release
  `pv-polygons-2026-11-11`, and `configs/atlas_polygons.json`, which `atlas.polygons_release`
  puts in `totals.polygons`: a Downloads card after the lead files.
  `scripts/patch_atlas_polygons.py` adds it to a published page and its results/ sync source.
  India only so far (103,619 model + 7,309 OSM outlines, 19.3 MB).
  **Small leads on steep ground are left out (owner, 2026-10-31)**: `export.steep_lead_screen`
  drops a lead under `STEEP_MAX_AREA_M2` (1,000 m²) whose GLO-90 slope at its representative
  point exceeds `STEEP_SLOPE_DEG` (15°), and keeps a larger one flagged `steep_review` (a
  mountain solar farm needs a human) unless it is above `STEEP_CAP_DEG` (30°, any size;
  owner, 2026-11-01, from 60 Wadi Hadramawt shadows the owner flagged,
  `results/leads_steep_screen/owner_flagged_yemen.csv`); every lead carries `slope_deg`.
  One rule for every caller: `export.steep_rule`. Shaded slopes, cliff
  edges, escarpment shadows and gullies read like panels: a third of Yemen's leads stood above
  12° against 0.5% of its highland OSM solar. Applied by `release_leads.py` (tag
  `pv-new-leads-2026-11-01`; the 2026-10-28 files stay published) and by `earthpv export`'s
  new-leads file. Validation: `scripts/validate_steep_lead_screen.py`,
  `results/leads_steep_screen/`; the owner judged 153 sampled leads on imagery (2026-11-01,
  `verdicts_owner.csv`): none solar, removed 86 not / 3 unsure, kept 62 not / 2 unsure. The
  slope is read from whole cached DEM tiles (`data/dem` -> /home, ~5 MB each); a first
  country-wide run downloads hundreds, slowly under a busy link.
  **Open-ground leads of low peak probability are left out too (2026-11-01)**:
  `export.low_confidence_rule` drops a `no_building` lead whose `confidence` (the PEAK
  probability in the outline, not a mean) is below `LOWCONF_MAX_CONFIDENCE` (0.9), any size.
  MaStR finds a unit in 0-5% of such unmatched outlines against 10-38% above 0.9; 0-1.3%
  OSM-mapped in most countries; at most 1.5% of mapped area lost. Below 0.9 the mapped share
  is flat, so a lower cut buys nothing, and `ground_adjacent` is spared (15-35% register hits).
  **The surface-water screen is per country** (`lead_water_screen: true` in configs/aoi.yaml:
  Pakistan, Egypt, Namibia; `export --water-screen/--no-water-screen`): `surface_water.py`
  (JRC Global Surface Water 1984-2020, block cache `data/jrc_gsw` -> /home) drops non-rooftop
  leads >= 25% ever wet (pans, salt pans, ponds). Never India or Vietnam: Khavda's salt marsh,
  floating and pond PV. `planetary_computer.sign` 404s for this dataset; the module signs with
  the collection token, which lives ~15 min. Released as `pv-new-leads-2026-11-01b`; neither
  screen removes a `steep_review` lead (the owner keeps those for a human; the rule alone would
  take 2,017 of 3,298). Survey: `results/fp_filter_survey/`.
- **Size chart on every page (2026-10-30)**: `_size_distribution_data` re-bins Best by size
  with or without a roofclf half (it was Pakistan-only), counting only candidates and OSM
  inside the grid, as the per-cell total does. Where `small_rooftop_status` or
  `small_ground_status` is unmeasured, a bar below 400 m² continues past its measured top as a fade
  that goes invisible, open-ended, in the same column (owner, 2026-11-02; a fixed height, since the
  amount is unknown; on every such bin however short, an empty one fading up from the axis since
  2026-11-12; never on the "not split" column), with a header, legend key, tiles, tooltip
  notes and CSV columns saying so. Capacity below 400 m² with no per-installation size (farm
  ground PV, Germany's per-cell rooftop half) is a "<400 m², not split" column
  (`totals.size_unbinned_*_mwp`). `scripts/patch_atlas_sizes.py` adds it to a published page
  and refuses one whose bins miss its Best by over 2%. Yemen was rebuilt for it instead
  (2026-10-30) on the late 2026-10-24 OSM pull its density already used, keeping the published
  seven-area farm fit (`/home/tobi/earthpv_data/yemen_7areas_20261024`); the working tree's
  fourteen-area refits stay unpublished.
- **Rooftop potential layer (owner, 2026-11-02)**: an entry in "Show", off when the page opens,
  from `potential.py`: free roof area x roof share x 0.18 kWp/m2 x PVGIS yield, coloured in
  GWh/yr because capacity would ignore the sun. `earthpv atlas` picks up
  `<pred_dir>/<aoi>/potential/roof_potential_cells.parquet` by itself (no flag) and the entry
  hides where the table is absent, so `roof-potential` is a default step wherever a national
  roofclf scoring exists; only Pakistan has one built. It is where solar could still go: no
  total includes it. **Roof share** is how much of a footprint mapped PV covers on PV roofs
  (Pakistan 0.337, 0.235-0.683), what owners install rather than a maximum, and the largest
  uncertainty. Pakistan: 426.6 TWh/yr, 261 GWp (297-861 TWh/yr). `atlas --potential-cells` still
  draws the standalone page with its size filter; `scripts/patch_atlas_potential.py` adds the
  data to a published page. Method: `docs/methods/density.md`.
- **Uncertainty section**: a forest plot of each Best component's point and 90% interval, from
  the same `uncertainty.components` the headline CI is composed from.
- **"Against official and published figures" (2026-10-29)**: the national total (Best and
  Verified with their intervals) beside each `totals.references` entry and the Ember customs
  record, then per province this atlas's bar over the reference's for the first reference
  that publishes provinces (a picker when several do), with its rank agreement in words and
  as Spearman's rho. Plain bars from zero, each name above its bar and its value at the end,
  amber for the atlas and grey (`--ref`) for everything else: the first version's dots and
  dumbbells in small monospace were hard to read (owner). The atlas is dated by the median
  acquisition date of its scenes and their middle half (`totals.imagery_dates`,
  `atlas.imagery_dates`, `configs/atlas_imagery_dates.yaml`): composites do not record their
  scenes, so `scripts/imagery_median_date.py` re-runs compose's STAC search and ranking for
  a random sample of each AOI's cells. The hero no longer carries the Ember line, and its
  imagery line gives that median date rather than the compose window (owner, 2026-11-08; the
  window only where a page has no reconstruction). `earthpv atlas` writes the entry itself for
  an AOI without one (`atlas.reconstruct_imagery_dates`; `--no-fetch-imagery-dates` skips it),
  so only a re-compose needs the script by hand. Downloaded figures' source line keeps the
  window.
  `scripts/official_capacity.py` writes `configs/external/official_capacity.yaml`
  (registers from disk: MaStR per Land, ODRE per region at the 2024-12-31 vintage, MNRE per
  state for Jan 2026; cited documents typed into `PUBLISHED`, e.g. TransitionZero's Pakistan
  provinces); `atlas.official_capacity(aoi, provinces)` refuses a province key the page does
  not have. `scripts/patch_atlas_references.py` adds the section to a published page without a
  rebuild. Drawn side by side, never scored: none of them is ground truth for the map.
- **For every page built or retemplated from 2026-10-24 on**: the province chart shows the top 7
  (`PROV_TOP`) with a *Show all N provinces* toggle; a fifth KPI tile gives processed cells
  against the country's (`totals.n_cells_processed` / `n_cells_country`, `atlas._cell_coverage`);
  the Silver/Bronze banner is short. Since 2026-11-07 (owner) hand-mapped OSM is one tile (both
  sizes, split beneath), and the coverage tile gives way to what the installed PV generates per
  year (`totals.generation`, `atlas.generation_totals`: each cell's Best times its PVGIS yield,
  interpolated from a cached probe grid, `pv_capacity.irradiance_probes_path`) wherever one is
  cached, which `earthpv atlas` does by default (`fetch_irradiance_probes`: 100 PVGIS points,
  once per AOI, into `data/irradiance_probes/<aoi>.csv`; `--no-fetch-irradiance` keeps the
  coverage tile); the unimaged hatching keeps the coverage counts.
  `scripts/patch_atlas_generation.py --fetch` adds it to a published page. Pakistan 55.9 TWh/yr at
  1,623 kWh/kWp. Yield is for equator-facing panels at the latitude's tilt, so it leans high
  (Germany 96.0 TWh/yr from its 86 GWp Best); the tile's tooltip says so. Its interval is Best's
  at the same mean yield, so it carries no yield uncertainty, and no pose survey enters it.
  **South of the equator the panel azimuth is 0** (`specific_yield_kwh_per_kwp`, 2026-11-07:
  180 everywhere had South Africa at 1,073 kWh/kWp instead of 1,830; the wrong grids are in
  `data/irradiance_probes/PRE_azimuth_fix_20261107/`). Method: `docs/methods/density.md`.
- **Cells nobody imaged are hatched (2026-10-28)**: `unimaged` in the data block (runs
  `[lon0, lat0, n]` from `atlas._cell_coverage`, exactly `n_cells_country - n_cells_processed`
  cells) is drawn over the cells, so an OSM-only cell shows its colour hatched and bare land
  means imaged with nothing found; the map frames the whole country (`_bounds_with_runs`) unless
  its config names a `map_view` (Spain and Portugal open on the mainland, owner 2026-11-10;
  `scripts/patch_atlas_view.py` sets it on a published page, byte-identical to a rebuild), and
  the hatch has a layer switch, a legend key with the counts, a hover and a PNG legend key.
  `scripts/patch_atlas_coverage.py` adds it, and the two counts where a page lacks them, to a
  published page without a rebuild; every published atlas and its sync source carries it.
- **Farm and building calibration areas are drawn apart (2026-10-25)**: a farm area
  (`_farm_calib_`) is a green diamond with its own layer switch and legend key, a building area
  the ink diamond; tooltips and popups say what each calibrates and whether the page's figures
  use it (`farm`/`used` from `atlas._load_calib_boxes`; a page built earlier reads `farm` from
  the published ids once the areas load). Neither kind feeds the other's instrument.
- **Colour means method everywhere**: OSM teal, segmentation blue, roofclf amber, roofclf+SPPI
  violet, farm ground PV green; hatching means ground-mount everywhere.
- **"How the estimate is built" (2026-10-28)**: a plain-language methods section, one step per
  method, written by the template's `renderMethod()` from the page's own components (gated like
  the composition bar, so a segmentation-only country never reads about roofclf); the hero links
  to it. Country evidence stays in `configs/atlas/<aoi>.yaml` caveats.
- **Solar thermal power plants (CSP) count in Best and Verified (owner, 2026-11-07)**, at their
  electric rating in MW, never as PV (`solar_thermal.py`, `docs/methods/solar-thermal.md`).
  `atlas._append_csp` adds `data/labels/<aoi>_csp_plants.parquet` to the hand-mapped population
  after its dissolve, as ground rows priced at their rating (`csp_mw`), always counted from the
  map (never "matched" by a detection, never in the OSM-misses absorption); `_size_distribution_
  data` adds them the same way. They are inside `osm_mwp`, carried apart as cell column
  `csp_mwp`, `totals.csp_mwp`/`csp_n`/`csp_status`, a tile and a map quantity where non-zero, a
  composition row (`osm_csp`, `osm_unmatched_csp`) and a method step. A tagged plant is exact; one
  priced from site area takes one shared lognormal draw (`CSP_LOG_SD` 0.41, never permuted). A
  country without a table reads `csp_status.checked: false`. Capacity: `plant:output:electricity`,
  else site x `CSP_MW_PER_KM2` 27.2 (median of 46 tagged plants), also for a tag more than 3x that
  density on >= 0.5 km2 (Noor 3's 582 MW is the whole complex). A PV outline at least half inside a
  plant is dropped as mirror field (`_append_csp` warns: the OSM file was not filtered).

**Plot gotchas**: on a log scale Plot routes any `tickFormat` through d3's log formatter, which
blanks every tick with mantissa > 2 (draw labels with a text mark); a `{value, label}` channel
object as `barX`'s `y` breaks the implicit stack (rename the field instead); `grid: true` on a
scale plus a `gridX` mark draws two grids.

**`scripts/retemplate_atlas.py` moves published pages onto a new template without rebuilding
them**: it recovers each placeholder's value by aligning the page with the template it was built
from (`--old-template <git rev>`, default HEAD), proves the split by substituting back, then
fills the current template; only `__LAYERS_JSON__` and `__AOI_KEY__` are computed fresh. **After
a template commit, pass the revision the pages were last built from**, not HEAD. `--new-template`
fills a template other than the working tree's (keeps an uncommitted edit out); `--refresh-prose
REV` also rewrites the confidence and composition prose from each page's own data block, only
where `atlas.py` at REV reproduces the page's existing prose (a page whose country config has
changed since keeps its prose).

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
(`build_atlas_pages.py`). **They are sized to the whole atlas, not the viewport (owner,
2026-11-06)**: `.page-full-bleed.fit` makes `embed-theme.js` fit the frame to its `<body>`,
so the site page scrolls as one and the switcher and Silver/Bronze banner scroll away above
the map. The frame never scrolls, so that script also redoes the atlas's in-page links
(`#method`) and the tooltip's flip-below test against the site page and its sticky header.

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
  `--replace` redraws only sampled candidates. Then run `calib-publish`. Pakistan's eight
  (seed 24490, drawn 2026-10-28 on the pre-v16 grid) are Box 21 in
  `docs/issues/pakistan-calibration-boxes.md`.
- **Start-here boxes:** `--bronze --priority` adds two PURPOSIVE 1 km boxes per Bronze AOI (the
  most large-roof area in the densest quarter, chosen on buildings only, marked `selection:
  purposive: ...`); the eight sampled boxes stay the representative set. `calib-publish` ranks
  them first and the atlas draws `start_here` as a star. `--exclude-box W,S,E,N`
  (repeatable) leaves out a district whose footprints do not read as roofs (Spain: the
  Campo de Dalias greenhouses, central Madrid).
- **PV-rich boxes** (`--pv-rich --score-dir <roofclf prob dir>`, 2026-10-28): purposive 1 km
  TOWN windows (own density >= 800 bldg/km²) with the most household roofs in the national top
  5% of a roofclf scoring from a model that has NOT seen the AOI's labels (Yemen: Pakistan's,
  `data/roofclf_transfer/yemen_pk/prob`). Rooftop positives for the fit, not the level. Draw
  with `--dry-run`, look at each window's top-scored roofs on Esri z18, record the verdict in
  `candidate_quadrats/pv_rich_review.csv` (`no_pv` keeps the draw 5 km away), then write with
  `--pv-rich-confirmed-only`. Without the town floor Pakistan's model filled Yemen's top windows
  with rural stone houses, roofless shells and greenhouse tunnels at p > 0.9. Yemen's ten
  (`*_pv<k>_calib_1km`) were confirmed by the assistant, not the owner.
- **Which atlases get a star** (2026-10-29): `calib-publish` ranks and stars candidates on
  every atlas whose own page reports roofclf (`totals.small_rooftop_status`, or for an older
  page all `small_*` zero) or groundclf (`totals.small_ground_status`) as not measured
  (`unmeasured_instruments`), Gold and Silver included; only a page measuring both gets none.
  Where only farm ground PV is unmeasured, farm boxes rank first: Pakistan's star was Badin
  (`badin_f8_farm`, 94% cropland; 2 rooftop arrays), then Qambar Shahdadkot f7 (no PV), Swabi
  f4 (57 installations, 45 ground) and Lasbela f1 (37, 36 ground), all mapped 2026-10-29. With
  no farm candidate left the star falls back to the densest building box (Gujranwala s8,
  mapped the same day; then Malakand s7).
  Germany and France qualify but have no open candidates.
- **A chosen star**: `start_here: <stem>` in `configs/atlas/<aoi>.yaml` makes `calib-publish`
  rank that country's candidates with it first and star it, on any atlas. Yemen's was Yafi'
  (2026-10-29, picked on Esri imagery over the classifier's top window, Adh Dhihar); mapped
  and registered the same day, so the key was dropped and the star moved on by rule. Ghayl
  Bawazir (`ghayl_bawazir_fa1_calib_1km`, owner's pick 2026-10-30) went the same way: swept
  2026-10-31, registered with no PV. Since then Yemen has no star (`start_here: none`,
  owner): the candidates keep their mapping order, none is starred.
- **False-alarm boxes** (`--false-alarm <window> [--score-dir]`, 2026-10-30): one purposive
  1 km box at a window `pv_rich_review.csv` marks `no_pv`, selection "...where a reviewer saw
  no solar" (the atlas popup keys on that, never on "PV classifier"). The level's other end
  from a PV-rich box: Ghayl Bawazir, 683 of 966 buildings in Pakistan's model's top 5%, its
  top-scored roofs roofless shells. Whether it enters the coverage ratio is an owner decision.
- **Random town boxes** (`--towns [--n-towns 6]`, 2026-10-31): a building drawn at random
  from the whole density grid, its 1 km box kept if it reaches the town floor (800 bldg/km2),
  no PV signal anywhere; selection "random town boxes by building, seed N", stems
  `<place>_t<k>_calib_1km`. `calib-publish` ranks them first, in draw order, so a partly
  mapped set stays a random sample. Yemen's six (seed 94417): As Sab'in, Az Zaydiah, Dhamar,
  Bani Hushaysh, Al Marawi'ah, Bayt al Faqih; 60 of the 74 buildings drawn were outside
  towns, so about one Yemeni building in five sits in one.
- **Bright-roof boxes** (`--bright`, 2026-11-05): purposive 1 km boxes where roofs are
  brighter in NIR/SWIR (mean of B08, B8A, B11, B12) than in any calibration area. roofclf
  over-credits such roofs, and the calibration set holds too few to test a fix. The mode reads
  `scripts/roofclf_bright_screen.py`'s national screen (`data/roofclf_bright_screen/<aoi>/`,
  every in-domain building through `epoch_feature_frame`): windows whose median roof is
  brighter than every area's, ranked by score mass on roofs beyond the calibration p99, one
  per province, the same imagery gate; stems `<place>_br<k>_calib_1km`. Pakistan's two
  (Quetta, east of Karachi, drawn at `--pv-rich-min-density 300`) are Box 23;
  `calib-publish` ranks them after the sampled boxes. Entering the coverage ratio is an
  owner decision.

**The community guide is the "Contribute Data" nav section**, `docs/contribute/` (`index.md`
keeps the `/contribute/` URL that popups, badges and README link to; plus `id.md`, `josm.md`,
`report.md`, `maintainers.md`). Mappers report through `.github/ISSUE_TEMPLATE/calibration-area.yml`;
the popup's "Report progress" link prefills `area` and `country`. Country requests, and claims
of a country someone is building, go through `.github/ISSUE_TEMPLATE/new-country.yml` (label
`new-country`), which `contribute/new-atlas`'s links open prefilled with the globe's country, ISO3
and box (`new-atlas.js`). A screenshot still to be taken
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

**The site root is the Electrify Earth globe (owner, 2026-11-08)**, and the written introduction
moved to `docs/overview.md` (`/overview/`; the root redirects old `#anchors` there). `docs/index.md`
and `docs/assets/landing/earth.json` are generated by `scripts/build_landing_page.py`, which
`build_atlas_pages.py` calls, so **never edit `docs/index.md` by hand** and a new country is inked
by its one row in `ATLASES`. `docs/overrides/landing.html` is a standalone template (no Material
chrome), drawn by `docs/assets/landing/landing.js`: a sketched globe where a country with an atlas
is outlined in ink and the rest stay pencil, the atlases' own 0.1 degree cells laid down as a per-pixel raster
(white = processed, blush to vermilion on a log scale = Best, a small red mark from `RED_MW`; owner: white land, so the red stands out), and
a brush stroke round the globe whose sweep is the atlases' summed Best over the world total in `configs/external/global_pv_capacity.yaml` (IEA PVPS,
DC, end of 2025: 330.7 of 2,974 GW, 11.1%; update it at each Snapshot). Wet ink is Verified, the
dry part what Best adds. **Nothing on the globe may be a texture fixed to the screen (owner,
2026-11-08)**: land turning under one looks as if it slides beneath a second sheet, so even the
pencil hatching is geometry. A polygon of an atlas country with no processed cell stays pencil
(France's overseas parts) but still clicks through to its atlas. The hover card holds the atlas's
Gold, Silver or Bronze medal (the disc and mark of the page's own badge, `tier_of`), its Best, and its
size chart as four horizontal bars in MW/GW: <400 m² (vermilion, `size_unbinned_*` included), 400-5k,
5k-100k and >=100k m² (owner, 2026-11-11, replacing 2026-11-09's two shares; `_atlas_facts`,
`SIZE_GROUPS`, from the page's `bins`). Where a page has no rooftop detector below the floor the first
bar fades on past its end and reads "at least" ("not measured" if it rounds to nothing), and a line
names what was not measured, so a floor never passes for a measured amount.
`scripts/atlas_osm_by_size.py` and `totals.osm_mwp_lt400`/`_ge400` no longer feed the card. A click on a country without an
atlas opens `docs/contribute/new-atlas.md` with `?country=&iso3=&bbox=`, which `new-atlas.js`
writes into the commands' `YOUR_*` placeholders. `docs/assets/landing/world.json` is Natural Earth
1:50m, rebuilt only with `--base-map`; a simplified ring must keep its winding or d3 fills the
rest of the sphere (`build_base_map` restores it). The United States and China are drawn and picked
state by state (owner, 2026-11-08; `regions.json`, Natural Earth 1:50m admin-1, rebuilt only with
`--admin1`), and a state's `d` is its name as geoBoundaries spells it, which `compose._aoi_boundary`
matches (`Guangzhou Province` is Guangdong there). A state becomes an atlas by its display name in
`ATLASES`. VIDA barely reaches China (2.7 M footprints, nearly all along its southern border), so the
contribute page warns before a province run.

**The PV Atlas pages are generated** (`scripts/build_atlas_pages.py`): one row per country in
`ATLASES`; each page's tier (Gold/Silver/Bronze) is read from the calibration badge its own
atlas carries (`atlas.VALIDATION_TIERS`), the switcher and `--nav` block are grouped by tier, and
Silver/Bronze pages open with a banner of two short sentences saying what is not yet
calibrated or verified and one contribute link (`banner`: `WARNING`, `TIER_NOTE` or
`LEADS_WARNING`, plus `CTA`; owner, 2026-11-06), which a reader can close
(`docs/assets/javascripts/atlas-banner.js`, remembered per wording in localStorage). A new
country is one row plus a rerun; **never edit
`docs/atlas*.md` by hand**. A tier that is a judgement goes in `configs/atlas/<aoi>.yaml`
(`validation: {score, note}`, which beats `derive_validation_score` and is read by all three
atlas builders and `apply_validation_badges.py`), with a country note in
`build_atlas_pages.TIER_NOTE`. **Gold and Silver also need the leads mapped in OSM to
localize the model (owner, 2026-11-01)**: at least `atlas.LEAD_SHARE_MIN` (a third) of a lead
file's leads and of its blobs have a verdict, and the localized model was trained again on
the OSM pull holding that mapping, declared as `validation.retrained_on_leads: {leads, share,
blobs_share, model, by, date, note}` (`atlas.leads_retrained`; `blobs_share` defaults to
`share`); it does not lapse with a new lead file. A third because the real ones sit at the
top of the ranked file: the top third held 69% of what was mapped later in Pakistan, 87% in
Yemen, 46% of register hits in Germany, and below it 2-4% were real
(`scripts/lead_share.py`, `results/lead_share/`). It replaced "every lead in the current
file checked" (2026-10-31); `validation.leads_checked` is now a record the Downloads card
states. Without it `resolve_validation_badge` shows Bronze whatever the tier earned (an
explicit `--validation-score` is capped too), keeps the earned tier on the badge as
`data-earned`, and `build_atlas_pages` gives the page the leads banner (`LEADS_WARNING`
with `SMALL_GAP` and `LEADS_NEED`, linking `docs/contribute/leads.md`).
`atlas.lead_rule_gaps` names what a page lacks. `docs/atlas-quality-levels.md`
(generated, `quality_page`; the owner removed its standings table) lists every criterion
and ends on the flywheel figure the levels follow. Pakistan's v16 is declared retrained on
v3's 2026-07-16 lead file at `share: 0.5` (the owner's "over half", blobs counted among the
leads then; 385 of its 4,435 leads are mapped in v16's pull); France, Germany and Yemen earn
Silver and show Bronze until they declare one. **Gold also needs roofclf checked by people
(owner, 2026-11-02)**: random validation (`results/roofclf_random_validation_log.csv`) and
point data inspection (`scripts/export_roofclf_points.py`) on the scoring behind the page.
`derive_validation_score` stops at Silver, so Gold is only ever declared (`validation.score:
gold`, or `--validation-score`). **No atlas is Gold today; Pakistan is Silver** (config, its
own `TIER_NOTE`) until both are recorded; no figure changed. **Germany earns Silver** (its
register-calibrated small half fails its own register check). **Yemen earns Silver**: its farm
areas calibrate farm ground PV only, so household rooftops below 400 m² are unmeasured; its twelve building boxes carry
`used: false` (roofclf was fitted on nine 2026-10-25, median fold AUC 0.71, and left off by the
owner; Yafi' and Qa'tabah town, the first PV-rich town boxes, were mapped 2026-10-29). In those
two Pakistan's unchanged roofclf ranks household roofs at AUC 0.79 / 0.89 but its scores sum to
3.6 per PV roof (170 over 47) against 1.115 in Pakistan's quadrats: the first measured level.

**Every evidence atlas shows an import ceiling** (in its "Against official and published
figures" section since 2026-10-29, no longer under the headline): solar panels imported from
China from Jan 2017 to the end of the imagery window, from Ember's customs-based export data
(CC-BY-4.0).
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

**45 Pakistani quadrats are registered; 41 are in the `roofclf` fit (since 2026-11-07), 19 in
its coverage ratio.** Purposive selections
(industrial estates, dense residential blocks) plus deliberately rural extensions that set the
density domain, then sampled boxes (Boxes 19-22). All but Jhang f2 are declared **Rule-1
complete** by the owner (every visible panel mapped).
**Rule-1 is epoch-relative**: it certifies completeness against the mapping imagery's own capture
date, not the Sentinel-2 composite's, so the newest installations are structurally missed. This
makes precision and `base_rate` **lower bounds** and `rate_ratio` an **upper bound**; recall over
mapped installations is unaffected.

**Every area feeds both detectors (owner, 2026-10-25)**: mappers map every installation,
ground and rooftop, in building and farm areas alike. `roofclf.discover_quadrats` returns both
kinds by default (`farm=True`/`False` selects one). **The 2026-11-07 refit took in Kasur,
Jacobabad and Mastung (gap boxes), Kalat Rural (owner's call) and seven farm areas** (Badin f8,
Jhang f5, Lasbela f1, Qambar Shahdadkot f7, Sahiwal f6, Swabi f4, Thatta f3) by explicit
`--quadrat` flags: Jhang f2 is `corroborated` (poor imagery), and Box 21's three random boxes
(Gujranwala s8, Qilla Abdullah s6, Sanghar s2) stay out of both fits as a test of the level.
`roofclf.roof_pv_area` ignores a ground-placed installation of 400 m² or more unless at least
half of it lies on footprints (`GROUND_GUARD_MIN_ON_ROOF`, the overlap test
`labels.classify_placement` applies to an untagged generator but never to an untagged
`power=plant`). The industrial areas are mapped as untagged `power=plant` roof outlines, so
without the test the 2026-10-25 guard stripped 117 of Faisalabad's 164 PV buildings and 189 of
Multan's 292; Kalat's farm arrays lie at most 0.47 on footprints and stay out. It still drops 16
of Multan's large arrays, some of them on roofs (Esri), which is what moves Multan's
`rate_ratio` past 2.

**Ranking transfers across quadrats; absolute adoption rates do not** (`rate_ratio` has spanned
0.2-5x), which is why the coverage ratio is stratified. `select_calibrated_quadrats` picks the
precision-trusted subset (`rate_ratio` roughly in [0.5, 2.0]) independently of Rule-1 status and
of the density-domain selection; check both gates for any new quadrat. **Pakistan's set is
pinned** (`sub400_capacity.PINNED_COVERAGE_QUADRATS`, owner, 2026-11-07) to the 19 areas the
rule chose from the 30-area fit. On the 41-area fit the rule drops Multan (`rate_ratio` 1.88 ->
2.13) and admits Kalat Rural, Kasur and Sahiwal f6, whose household PV is 72%, 42% and 66%
farm-yard ground arrays that the parcel label hands to the nearest building: Kalat carries
about 7x the PV per probability-weighted roof area of any other area, and with all three Best
read 37,456 MWp with a 90% interval reaching 82,394. Separately, the lower band's ≥ 400 m²
price swings about 1,000 MWp on whether one industrial estate (Multan or SITE Karachi) sits
below the median band edge. Whether the new areas may set the price is open question 21.
`scripts/new_calibration_quadrat.py` adds one (geodesic square or hand-drawn `--geojson`): it
checks boundary overlap with every existing quadrat before writing, and cross-confirms a live
Overpass pull against a second query (mirrors have returned truncated, non-error responses).

Per-quadrat table: `docs/methods/calibration-quadrats.md`. Dated history of every
addition/correction/withdrawal: `docs/issues/pakistan-calibration-boxes.md`.

### Farm ground PV: `groundclf` and farm calibration areas

A footprint-free pixel detector in the roofclf family for small arrays beside fields (solar
pumps), which neither instrument above sees (`src/earthpv/groundclf.py`,
`docs/methods/groundclf.md`). Named `roofclf_ground` until 2026-10-25: models tagged with
the old name still load (`LEGACY_DETECTORS`) and `data/roofclf_ground` is a symlink to
`data/groundclf`:

```bash
pixi run calib-candidates -- --aoi <aoi> --farmland          # cropland-stratified 3 km boxes
earthpv groundclf --aoi <aoi> --clean-region <b.geojson> --weak-region <b.geojson>
earthpv groundclf-score-national --aoi <aoi>             # blobs per cell, resumable
earthpv groundclf-capacity --aoi <aoi> --osm-solar <national OSM pull>
```

- **A standard atlas field**: `earthpv atlas --ground-cells <ground_cells.parquet>` adds
  `small_ground` (farm ground PV < 400 m²) to Best in the detector's calibration domain only,
  with its own tile, map quantity, province column, composition and uncertainty row, in green.
  Without it a page says "not measured" (`totals.small_ground_status.measured: false`), never 0.
  Run `groundclf-capacity` with the SAME `--osm-solar` file the atlas counts, and
  `--roofclf-buildings` where a roofclf half exists (a blob within 20 m of a priced building is
  its yard array).
- **A calibration domain PER REGION** (`groundclf.domain_cells`): a cell is priced with a
  region's ratio only if its cropland share, building density AND median elevation (Copernicus
  DEM, `cell_elevation`, cached in `data/cells_cache/<aoi>_elevation.parquet`) each lie within
  x/÷1.25 of that region's areas; a region = a landscape, the areas sharing the `region`
  boundary property (Yemen: Tihama, Highlands); a region with no detected area prices nothing
  (`regions_unpriced`). Regrouping changes the fit's random draws: retrain, never patch
  `calibration.csv`. The headline
  is `est_mwp_in_domain`; `est_mwp_all_cells_extrapolated` is not on the page. Interval:
  `region_ratio_draws` bootstraps each region over its own areas from `BOOT_MIN_AREAS` (3), else
  a stated x/÷2 (`JUDGEMENT_CI90`); the summary's `interval` names which. Blobs inside a
  registered farm area count nothing (`--labels-dir`).
- **Farm quadrats carry `_farm_calib_` in their stem** (`roofclf.FARM_QUADRAT_INFIX`;
  `new_calibration_quadrat.py --farm`). They are the detector's clean areas; building
  quadrats join as kind `train` (owner's choice, 2026-10-25): their pixels enter the fit, but
  not the threshold, the ratio or the domain, so the figure stays a farm figure. Blobs inside
  any registered area, either kind, count nothing.
- **A mapped polygon is priced by its tag** (`groundclf.panel_area_factor`):
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
  of a building, cropland or green pixel; a blob over 25,000 m² (`MAX_BLOB_M2`); a blob on
  Copernicus GLO-90 slope over 12° (`SLOPE_VETO_DEG`, `dem_slope_at`; whole DEM tiles cached in
  `data/dem/` -> `/home`, a remote full-resolution read takes a minute per tile): highland
  cliff shadows, which no cell-level domain variable separates.
- **The capacity estimand defaults to arrays below 400 m²** (`--max-array-m2`; `0` prices every
  size).
- **Overpass is a cached dependency**: area labels in `data/groundclf/<aoi>/areas/`, paved
  roads per 1-degree chunk in `data/roads/<aoi>/`. National scoring never calls it; the road veto
  is applied in the capacity step. A chunk that cannot be fetched leaves its blobs with
  `road_checked=False`, reported in the summary.
- **Farm candidates exist for Yemen, Egypt, Morocco, India, Pakistan and South Africa** (8 each);
  `calib-publish` ranks them after every building box. Pakistan has no `compose_window` or
  `division.iso3` in `configs/aoi.yaml`, so the sampler takes `--window-start 2025-11-01` in
  every mode (`gate_setup`).
- **Pakistan's farm areas (2026-10-29) do not work**: eight 3 km boxes, `region` Punjab plain /
  Lower Indus / Peshawar valley / Balochistan coast; the fit (`data/groundclf/pakistan` on
  /home) has held-out pixel AUC ~0.83 but object precision 2-5% and ~0 recall on Jhang f5 and
  Swabi (ground arrays median 44-106 m² against 'Amran's 581). Not scored; Pakistan's farm
  ground PV stays "not measured". A farm area its config does not declare `rule1` (Jhang f2)
  trains only (`train_ground`'s `train_only`).
- **Yemen is the only country with a farm figure**: seven areas ('Amran plus six Tihama areas cut where
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
- **Panel-pose surveys** (`scripts/glint_pose_survey.py`, `pose.py`) sit on the Pakistan
  (2,000-target sample, 281 fits), France (all 6,337 OSM installations >= 1,000 m2, 1,277
  fits, 2026-10-26; no French false-floor control yet) and India (`india2000`, on /home:
  `targets --sample`, 2,000 of 3,739, 312 fits, 321 points, 2026-11-02; no control) atlases.
  **India's fits split in two**: south at tilt ~19 on Oct-Dec dates, and a quarter east (az
  ~93) at tilt ~10 on Apr-Jun dates, south of 20N above all. Imagery shows north-south rows
  behind the east fits (`data/glint/india2000_pose/east_check/`, the assistant's eye, not the
  owner's), so probably single-axis trackers, whose fitted tilt is their roll at overpass.
  Weak low-share east orientations are unconfirmed. Every pose point carries its
  OSM id, coordinates, admin-1 region and, from the cached `osm-tags` lookup
  (`<survey>osm_tags.parquet`), OSM `name`/`operator`; the chart's CSV download lists them.
  `scripts/patch_atlas_pose.py` adds or replaces only a published page's pose section.
- **Large installations are read in parts** (`pose_parts.py`, `glint_pose_survey.py
  parts-pull`/`parts-analyze`, 2026-10-26): >= 50,000 m2 outlines are cut into 100 m cells,
  read from one window per installation against the WHOLE installation's annulus, fitted per
  cell, and grouped into orientations (normals within 5 deg, >= 2 cells); the atlas shows
  one point per orientation with its share of the area. **Pakistan's country2000 series
  (the atlas's 2,000) predate the SCL cloud veto**; on the 843 top-ups the veto removes 7% of
  fits, and Fauji Cement's published pose rests entirely on cloudy dates.

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
Verified 26,635 / Best 86,009.9 MWp** (84,472.7 before 149 judged parks, 2026-11-06) against
~74,800 MWp registered: Best fails its own register
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
QUEUE first when removing compute markers. The queue's disk guard is `DISK_MIN_HOME_GB`
(default 120, overridable by environment; Spain's queue ran at 100 from 2026-11-07, owner).
**A country can be given the GPU first** (owner, 2026-11-07, Spain): `scripts/gpu_priority.py
--aoi <aoi> [--now]` (unit `earthpv-gpu-priority-<aoi>`) pauses (SIGSTOP) every other process
WAITING on `data/.gpu.lock` and holds the lock between the country's GPU steps, from its
compose_done (or now) until its `infer` marker; a running job is never touched. Killed hard, it
leaves waiters stopped: `pkill -CONT -x flock`.

| Country | Checkpoint | Verified / Best (MWp) | Notes |
| --- | --- | --- | --- |
| Pakistan | `v16_combined_pakistan` | 7,138.3 / 34,470.3 | roofclf half on 41 areas, priced on 19; probability-weighted, Silver until people have checked it; see "Density stage" |
| Germany | `v4_combined_all` ep 41 | 26,635 / 86,009.9 | register-calibrated roofclf; earns Silver, shows Bronze (leads unchecked); 149 judged parks count |
| France | `v5_combined_france` | 12,381.7 / 13,447.1 | precision floor, no roofclf; earns Silver, shows Bronze (leads unchecked) |
| India | `v5_combined_france` | 70,266.0 / 102,779.7 | v10 lost the Gujarat holdout; `ring_cells: 3`; 1,427 judged parks count; 4 CSP plants 197.9 MW |
| Vietnam | `v9_combined_vietnam` | 8,179.8 / 9,118.9 | 32 judged parks count |
| Egypt | `v12_combined_egypt` | 3,315.1 / 3,848.7 | thin Cairo holdout; 46 judged large leads count |
| Yemen | `v25_combined_yemen` | 277.5 / 623.6 | retrained on mapped leads 2026-11-02 (holdout tie, wins on every mapped array); farm ground PV; earns Silver, shows Bronze (leads unchecked) |
| South Africa | `v14_combined_south_africa` | 9,322.7 / 10,075.9 | decisive localization win; 344 judged large leads count; 7 CSP plants 600 MW, 13.4 km2 of PV-tagged mirror rows out |
| Morocco | `v11_combined_morocco` | 898.9 / 935.1 | tie near 1.0; AOI stops at 27.7N; Noor 1-3 CSP 518.6 MW |
| Poland | `v15_combined_poland` | 6,604.1 / 9,110.2 | 113 judged parks count (+1,329 MWp) |
| Zambia | `v4_combined_all` ep 41 | 505.8 / 531.7 | |
| Nigeria | `v5_combined_france` ep 25 | 90.2 / 157.3 | name `v8` is taken by `v8_combined_nigeria` |
| Namibia | `v17_combined_namibia` | 464.3 / 512.3 | Cuvelai pans partly in Best (those of 1 ha and up judged out 2026-11-10); one calibration box |
| Turkey | `v19_combined_turkiye` ep 12 | 10,714.9 / 17,598.4 | tie with v5 on the holdout; dark open ground in Best; 396 judged parks count (+4,490 MWp); 1 CSP plant 5.8 MW |
| Spain | `v26_combined_spain` ep 21 | 39,379.3 / 41,776.7 | clear win over v5 on the holdout; floor of 1 building per cell; 43 CSP plants 2,383 MW; 998 blobs not judged yet |
| Belgium | `v31_combined_belgium` ep 22 | 502.3 / 970.8 | recall tie with v5, wins on IoU (thin holdout: Brussels, 2 cells); Best is 8.0% of Elia's 12,128 MW, 224 judged large leads counting (639.3 before, 2026-11-10); published before owner review; leads, calibration areas and the 4-outline farm review still owed |
| Portugal | `v30_combined_portugal` ep 19 | 5,830.5 / 6,193.6 | clear win over v5 on the Lisbon holdout; Azores and Madeira in; Best is 84% of DGEG's 7,396 MW; 153 judged large leads count; 110 blobs not judged yet; Évora molten-salt CSP 3.4 MW |
| Netherlands | `v5_combined_france` ep 25 at 0.98 | 3,708.6 / 4,567.3 | v32 lost the Zuid-Holland holdout on recall; Best is 16% of CBS's 29,426.5 MWp; 543 judged large leads count; 7 blobs not judged yet |
| Luxembourg | `v33_combined_luxembourg` ep 21 | 25.4 / 40.5 | tie with v5 on the thin Mersch holdout (39 of 48 each); Best is 5.4% of ILR's 746.35 MW; 8.3 of the model's 21.3 MWp lies beyond the border; no large installation review yet, 1 blob not judged |
| Italy | `v34_combined_italy` avg ep 21+29 at 0.7 | 12,175.7 / 13,880.6 | clear win over v5 on the Nord-Ovest holdout (0.645 vs 0.544 of 3,350); Best is 32% of GSE's 43,687 MW and 97% of its 14,296 MW ground-mounted; 377 blobs and 4,586 large leads not judged yet |
| Denmark | `v37_combined_denmark` ep 28 at 0.95 | 2,639.9 / 2,695.1 | win over v5 on the thin Nordjylland holdout (52 vs 45 of 98, all >= 1,000 m2); Best is 49% of Energistyrelsen's 5,468 MW; 3 blobs and 63 large leads not judged yet |

Per-country write-ups are `docs/results/<country>.md`. Country-specific points still in force:
- **India**: Verified is almost all ground perimeters. **Best counts the unmapped parks
  above the merge cap that a person judged solar** (1,427 of 1,789, 577 km2, 28,857 MWp of
  `est_mwp_rc`, all judged by the owner 2026-11-02; 81 from 2026-11-01; from 2026-10-29 1,650 at
  the review's shares, +28,468; verdicts in `results/india_oversize_review/`; the other 149 met
  the lead screens and count only if mapped)
  and Verified credits the seven outlines above 5 km² that fail the screen at their detected
  share (Khavda 2,230 MWp in both tiers; Rewa still unimaged). Pre-change outputs carry
  `_PRE_oversize_20261029`, those before the blob rule
  `/home/tobi/earthpv_data/india_PRE_blobrule_20261101/`, those before the full review
  `/home/tobi/earthpv_data/india_PRE_judged_20261102/`. **India's register is MNRE via MoSPI eSankhyiki** (state x month x
  ground/rooftop/hybrid/KUSUM, `scripts/validate_india_mnre.py`, fetched through MoSPI's MCP
  server; the REST API needs TLS legacy renegotiation): January 2026 ground-mounted Best 0.91 of
  registered (0.82 AC basis), Spearman 0.97 over 19 states,
  rooftop 7.5%. Its solar thermal was taken out 2026-11-07 (30 outlines, 9.1 km2, -455 MWp in
  both tiers; 5 candidates, -61.5 MWp of model ground) and its 4 CSP plants (197.9 MW) count
  instead. **The compose was widened by `ring_cells: 3`** (+3,573
  cells, published 2026-10-28; `scripts/run_india_ring_chain.sh`, markers
  `data/india_ring_markers/`; the run before it is kept in
  `/home/tobi/earthpv_data/india_PRE_ring_20261024/`). It imaged Khavda's outlines whole
  (+330 MWp) and every mapped outline cell, but its Himalayan cells add ~220 MWp of
  false positives on shaded slopes and snow edges, which the page states and no veto removes
  yet. India is **pinned Bronze** in `configs/atlas/india.yaml`: `derive_validation_score`
  gives Silver to any AOI with a registered area in `data/labels/<aoi>/`, `used: false` or not.
- **Yemen**: segmentation finds almost none of its labels (small Tihama irrigation arrays barely
  differ from their surroundings), so Best is the OSM map plus farm ground PV. **v25** (published
  2026-11-02, retrained on the 2026-11-01 pull holding the 827 features the owner mapped from
  v13's leads) runs from `data/predictions_v25/yemen` (-> /home; `data/predictions/yemen` is
  v13's), with its own precision table; the farm figure is the seven-area fit re-deduplicated
  there. The 'Amran holdout is now the Huth farm area, where every model is blind, so the
  ship decision rests on `scripts/yemen_v25_national_recall.py` (every mapped array >= 400 m2,
  matched pixel precision): 0.152 against v13's 0.128, half the alarm pixels.
- **Egypt**: the model's rooftop estimate is ~0 (no rooftop candidate matches a mapped rooftop).
  **Many of its leads are swimming pools and wastewater treatment plants** (owner, 2026-10-29),
  above all the plants' rectangular basins. `earthpv osm-hard-negatives` (`osm_negatives.py`)
  cuts hard-negative chip centers on the OSM-mapped ones and counts the leads each class
  touches; `--pbf` reads a Geofabrik extract when Overpass is overloaded. OSM explains the
  pools (77 of 1,165 leads mostly a mapped pool) but not the plants (9 leads). 1,120 chips in
  `data/chips/egypt_hard_neg` (-> /home), val-buffered with `mark_val_buffer.py --chips`;
  175 fall in the Cairo holdout against its 9 original chips, so score the sets apart. No
  model has been trained on them yet (open question 19).
- **Morocco**: geoBoundaries MAR includes Western Sahara, so `atlas.build_evidence_atlas` clips
  region outlines to the AOI bbox.
- **Namibia** (published 2026-10-29): v17 beat v5 on the Erongo holdout (recall >= 500 m2
  0.952 against 0.766), but **reads the Cuvelai basin's seasonal pans (oshanas) as ground
  PV**: about 54 of the 66 MWp Best adds over Verified (31 of 48 since the owner judged the
  leads of 1 ha and up, 2026-11-10), 10 of 10 sampled on Esri were pans;
  priced through the >50k m2 ground bin (21 of 101 mapped). No filter yet; the page says so.
  geoBoundaries NAM ADM2 names are shuffled (ADM1 is right; `propose_calibration_candidates.py`
  names Namibian boxes by region), and Esri serves most of Namibia only to zoom 17, so one
  calibration box passes the imagery gate.
- **Turkey** (published 2026-11-04): v19 tied v5 on the Gaziantep holdout (recall >= 500 m2
  0.968 against 0.970, pixel IoU 0.581 against 0.548) and ships under the tie rule. Of what Best
  adds over Verified, rooftop is partly real (roof-wide arrays in Manisa, Bursa and Ankara
  industrial estates), open ground mostly not (lava and rock north of Lake Van, shaded eastern
  slopes, dark fields; 0 of 10 sampled on Esri, the assistant's look), priced through ground
  bins whose mapped fraction is high (0.375 above 50k m2). No filter; the page says so. Of 774
  blobs (175 km2) the owner judged 396 parks (89.8 km2, 2026-11-06): Best 13,103.0 -> 17,592.6;
  `check-density` then fails 42 provinces (ratio; 15 also on one cell, 12 of them a judged
  park). Ember is not a ceiling (cells 36 GW, panels 6).
- **Spain** (published 2026-11-08): v26 beat v5 on the Castilla-La Mancha holdout (recall >=
  500 m2 0.863 against 0.787 at pixel precision 0.84). **VIDA has block-shaped holes in Spain**,
  city centres included, so `data/vida/ESP.parquet` is VIDA plus OSM buildings in empty 0.01 deg
  blocks (`scripts/fill_vida_from_osm.py`; raw at `/home/tobi/earthpv_data/ESP.parquet`); other
  countries' VIDA has not been checked for holes. Imaged at a floor of 1 building per cell
  (owner; 5,712 cells against 1,896). Plastic greenhouses are not read as PV
  (`scripts/spain_greenhouse_check.py`: 68.5 of 3,126 MWp in the five districts, the assistant's
  look at 15 outlines), though footprints trace them as buildings. Of what Best adds over
  Verified, open ground is mostly rock, fields and quarries (3 of 20 solar, the assistant's
  look); the page says so. 998 blobs (324.4 km2) await the review and none counts. REE is
  national only on the page: its capacity API returned 500s and its regional notes lack totals
  for the large regions.
- **Portugal** (published 2026-11-10): geoBoundaries PRT ADM1 garbles 6 of its 20 names
  (UTF-8 read as Latin-1, with a control byte YAML refuses); `density._repair_mojibake` fixes
  them on read, and changes no other cached boundary. DGEG's regions are NUTS II, which the
  districts do not nest in, so the page compares the national figure only.
- **Netherlands** (published 2026-11-10): ships v5 at threshold 0.98, the only threshold where
  v5 reaches v32's precision (`compare_local_vs_v5.py`); recall is not corrected, so arrays
  that never reach 0.98 are missing. VIDA has holes here too: 2.87 M of the 6.96 M footprints
  are OSM fill (`scripts/fill_vida_from_osm.py`). Ember is not a ceiling (226.7 GW imported,
  most passed on). Zoneiland (Almere) counts 0.5 MW as CSP from its tags, unchecked.
- **Luxembourg** (published 2026-11-11): 23 of its 40 cells straddle the border and are kept
  whole, so 8.3 of the model's 21.3 MWp (recall-corrected; `n_candidates_outside_border` in
  its density `meta.json`) lies in France, Belgium or Germany, the largest a 0.16 km2
  OSM-matched park across the Sauer from Echternach that is exempt from the merge cap. ILR
  publishes no canton figures, and Ember is not a ceiling (155.2 MW of panels straight from
  China against 746.35 MW installed).
- **Italy** (published 2026-11-12): a map of the ground-mounted fleet. The model outlines
  almost no rooftops (Best 704 MWp rooftop, 13,176 ground) where GSE puts two thirds of
  43,687 MW on buildings, so against GSE's regional totals the five macro-regions rank
  backwards (rho -0.5) and against its ground-mounted shares in the same order, each within
  a quarter. geoBoundaries ITA ADM1 is ISTAT's five macro-regions; `official_capacity.py`
  sums GSE's 21 regions into them. Ember is not a ceiling (17.4 GW imported directly, 19.3 GW
  built before 2017). Ground outlines not checked by eye.
- **Denmark** (published 2026-11-12): Best adds only 55 MWp over Verified (floored in 144
  cells). Solar heating fields look like parks: the 33 model outlines inside the 674 mapped
  thermal polygons were dropped, unmapped ones count as PV. `Høng solvarmeanlæg` (a heating
  plant by name) is tagged `plant:output:electricity=yes` and counts as 1.7 MW CSP, probably
  mis-tagged. Energistyrelsen's quarterly note has no regions. Ember is not a ceiling (4.35 GW
  imported directly against 5.47 GW registered).
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
least half inside them before `density`. Since 2026-11-07 thermal also means
`generator:type=solar_thermal_collector` with no method tag (Spain: 161 rows, 156 inside Alvarado
II) and the plants in `KNOWN_THERMAL` (by id, on documentary evidence). **Every published country
but France and Germany was checked 2026-11-07** (their scan was stopped on the owner's request; their
pages read `csp_status` absent, i.e. not checked, until they run) with `scripts/solar_thermal_plants.py --aoi <aoi> --osm-solar <the
atlas's OSM file> [--candidates ...] [--by-id | --pbf <Geofabrik extract> | --tile-deg 2]`, which
filters the atlas's own OSM file in place (original `<stem>_PRE_thermal_<date>.parquet`), drops
any feature at least half inside a CSP plant (mappers draw mirror rows with the PV preset: South
Africa 50 rows, 13.4 km2, ~670 MWp counted as PV until then), writes the CSP table (even empty)
and reports to `results/solar_thermal/`, caching the Overpass tags there (Overpass 502/504s on
area scans: `--tile-deg 2` or `--by-id`). `run_country_compute.sh` runs it after `osm_solar`
(non-fatal). CSP found: Spain 43 plants 2,383 MW, South Africa 7 / 600, Morocco 3 / 518.6, India 4
/ 197.9, Turkey 1 / 5.8; none in Egypt, Pakistan, Namibia, Zambia, Nigeria, Yemen, Vietnam, Poland
(14 collectors left PV there). Pages whose figures did not change were not rebuilt.
Heating plants (thermal, no electric output) are dropped from PV and not counted. The backup is
named `<aoi>_solar_labels_with_thermal.parquet` because `chips._newest_overpass_path` globs
`<aoi>_overpass_solar*.parquet` and takes the last name in sort order; a backup matching that
glob silently undoes the filter (dotted stems are now ignored).

**A candidate file that only LOST rows needs only the touched cells recomputed**:
`scripts/density_partial_update.sh <aoi> [pred_dir]` moves the partials of cells whose box a
removed candidate intersects aside, rewrites the fingerprint and runs `density` without
`--force` (a partial depends only on its cell's buildings, raster and box candidates and holds no
candidate index; on Namibia identical to `--force` to the last digit; India ~1 h against 28 h).
**Run `density` and `atlas` from a tree that has `results/<aoi>_osm_ground_screen/`**: the screen
is read by a relative path and is untracked, so a clean worktree silently skips it (India +2,845
MWp until it was linked in, 2026-11-07).

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
  above 5 km² unless `--keep-detected-screen`. With the screen, an outline above 5 km² that
  fails it is credited, not dropped (2026-10-29): `area_m2` becomes outline x `det_frac`,
  floored at the union of the plants mapped inside it that are each under the cap (the cap runs
  after `dissolve_overlapping`, so they used to go out with it), and `screen_credit` records the
  share, which `atlas._apply_screen_credit` reapplies after the atlas's own dissolve. Only an
  outline earning nothing (unimaged, nothing nested) is dropped. Of the screened countries only
  India's layer changes.
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
