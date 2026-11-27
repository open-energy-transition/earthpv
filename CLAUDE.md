# CLAUDE.md

This file guides Claude Code (claude.ai/code) in this repository. It records the **current**
pipeline: its rules, its gotchas and its published results. What was tried, rejected or
superseded lives in `docs/experiments.md` (the dated experiment register); open items in
`docs/open-questions.md`; method write-ups in `docs/methods/` and `docs/issues/`; per-country
write-ups in `docs/results/<country>.md`. Check those before re-deriving something. Pre-change
outputs are kept beside the canonical paths with `_PRE_<change>_<date>` suffixes or under
`/home/tobi/earthpv_data/*PRE*`.

## What this is

`earthpv` detects solar PV in Sentinel-2 L2A imagery and turns it into a per-country **evidence
atlas** of installed capacity. Labels come from OpenStreetMap solar mapping; building footprints
(VIDA) classify detections as rooftop or ground. It is **recall-first**: candidates are meant to
be validated by people against high-res imagery in OSM workflows, so false positives are
tolerated. Two detectors:

- **Segmentation** outlines arrays **> 400 m²** (the practical floor for per-pixel supervision
  at 10 m GSD), localized per country on that country's own OSM labels (TerraMind fine-tunes via
  TerraTorch; the released baseline v28 is a ResNet-50).
- **`roofclf`**, a per-building "does this roof carry PV?" classifier, covers roofs below the
  floor. It is not optional: Germany's legally complete register (MaStR) puts **65.5% of rooftop
  capacity in installations below 400 m²** (97.2% by count; quote the capacity share).

Twenty-six countries plus Texas and California have a published atlas ("Country runs"; Sweden
was published by a contributor and is not in its table).
`README.md` has the narrative and headline numbers.

## Main workflow (default pipeline)

The evidence atlas (`atlas.build_evidence_atlas`) combines:

- **Segmentation** (`infer` → `postprocess` → `density`): every mapping lead regardless of size,
  the only instrument for ground-mount at any size, and the rooftop instrument for arrays
  **≥ 400 m²** wherever roofclf is not calibrated to replace it. Each country runs its own
  checkpoint (table under "Country runs").
- **roofclf** (`roof-classifier` → `roofclf-score-national` → `ge400-roof-capacity` →
  `sub400-capacity`): every building **< 400 m²**, and it **replaces** segmentation's rooftop
  estimate for buildings **≥ 400 m²** inside the density-calibrated domain, where it measures
  better (AUC ~0.76-0.78 against segmentation's ~0.50-0.78, quadrat-dependent). Both capacity
  functions are domain-restricted and refuse to rescale to a national total on their own.
- **Best** = hand-mapped OSM + segmentation's ground-mount + roofclf's rooftop replacement
  in-domain + segmentation's recall-corrected rooftop out-of-domain + roofclf density below
  400 m², de-duplicated against each other and against OSM, floored per cell at Verified plus
  whatever a person judged solar there. **Verified = the hand-mapped OSM capacity alone** (plus
  CSP at its rating). Best carries a 90% credible interval.
- **SPPI is in no atlas (owner, 2026-11-13).** `sub400-capacity` still writes the AND-gate and
  out-of-domain files and `roofclf-score-national` still computes SPPI per building: research
  outputs nothing reads. roofclf never used SPPI as a feature. The evidence template reads cells
  by name (`cell_cols`), so pages built with the three retired all-zero columns draw alike.

Full sequence: `docs/reproduce.md`, "The full pipeline". Short version:

```bash
earthpv labels --aoi <aoi>       && earthpv chips --aoi <aoi>
earthpv train  --config configs/terramind_pv.yaml
earthpv infer  --aoi <aoi> --checkpoint <ckpt>
earthpv postprocess --aoi <aoi> --threshold 0.3
earthpv export --aoi <aoi>
pixi run blob-review draw --aoi <aoi>   # solar farm review: every outline above the merge cap.
#   Judge on Sentinel-2 in data/oversize_review/index.html, then `blob-review apply --verdicts ...`
pixi run large-review draw --aoi <aoi>  # large installation review: leads 10,000 m2 up to the
#   cap, reviewed in JOSM while mapping (data/large_review/<aoi>/<aoi>_large_review.osm), then
#   `large-review apply --josm <saved layer>`; after a new OSM pull, `apply --labels <pull>`
earthpv density --aoi <aoi> --districts && earthpv check-density --aoi <aoi>

earthpv roof-classifier --aoi <aoi>                 # needs mapped calibration quadrats
earthpv roofclf-score-national --aoi <aoi>          # long: hours at country scale

# ESSENTIAL, not optional -- run after every national scoring pass. See
# docs/methods/roofclf-national-validation.md. Draws 20 random in-domain cells and their page;
#   judge in data/roofclf_review/index.html, then `pixi run roofclf-review apply ...`
pixi run roofclf-review draw --aoi <aoi> --seed <fresh int> [--calib-dir <its fit>]

earthpv ge400-roof-capacity --aoi <aoi> --osm-solar <national OSM solar pull>   # before sub400
earthpv sub400-capacity     --aoi <aoi> --osm-solar <national OSM solar pull>
earthpv roof-potential --aoi <aoi> --roofclf-dir data/roofclf_national_with_sppi/<aoi>/prob \
  --roof-table <calibration buildings.geoparquet> --osm-solar <national OSM solar pull>
earthpv atlas --aoi <aoi> \
  --sub400-central-cells data/roofclf_national_with_sppi/<aoi>/density/sub400_central_incremental_buildings.parquet \
  --ge400-roof-cells     data/roofclf_national_with_sppi/<aoi>/density/ge400_roof_incremental_buildings.parquet \
  --osm-solar <national OSM solar pull>
```

`--osm-solar` is required, and `density` no longer writes an atlas (`build_combined_atlas`
remains on `templates/pv_atlas.html`).

**Countries without quadrats.** With a complete register (Germany) the capacity half needs no
mapped quadrats: `roof-classifier` fits on pseudo-quadrats, `roofclf-score-national` scores the
country, and `scripts/calibrate_germany_capacity.py` fits kWp per credited m² against the
register (see "MaStR validation"). With neither, build the **segmentation-only atlas** (`earthpv
atlas --aoi <aoi> --osm-solar <pull>`, no `--sub400-central-cells`): Best does not reach below the
floor and the page says "not measured" there. France is in this state because roofclf does not
transfer to French residential PV.

### Human review steps (part of the workflow, not extras)

An agent prepares each of these and **never judges them**; verdicts come from named people.

- **No verdict from imagery the project may not use (owner, 2026-11-20).** A verdict that
  feeds capacity, lead files, the quality checklist, a study or a training set rests on
  Sentinel-2 (free Copernicus data) or is an installation mapped in OpenStreetMap. Google,
  Bing, Esri and Mapbox imagery may be used only inside an OSM editor, for tracing into OSM
  (Esri's terms forbid using its imagery to verify a published compilation, 3.3(b), and allow
  tracing into open data; Mapbox's allow deriving only for OSM). So the blob page shows
  Sentinel-2 alone and its links open only free data (`build_review_page.LINKS_FREE`);
  `oversize_review apply` refuses an export without `imagery_date` = `Sentinel-2 only`
  (`S2_ONLY`, every page before 2026-11-20 showed Esri) and records `imagery` per verdict; the
  large review is done in JOSM, where the map is the verdict. Verdicts applied before
  2026-11-20 stand (owner: "in the future"). **Still at odds with the rule, owner to decide:**
  the roofclf random-cell and level pages (Esri + Mapbox panels; their verdicts feed the
  checklist's `roofclf_checked`), `verdict_hard_negatives.py` (Esri-era verdicts as training
  negatives), the MapRoulette pilot (`scripts/maproulette_review.py`, uncommitted; editor
  imagery, `apply` refuses its CSV), and the research tools that fetch Esri
  (`aef_render_review_tiles.py`,
  `spain_greenhouse_check.py`, `osm_sweep_completeness_review.py`; `label_audit.py review`
  now refuses); docs/open-questions.md 26.
  Never build a new review whose verdicts rest on commercial imagery.

- **roofclf random-cell review, after every national scoring pass (2026-11-19).** The
  calibration quadrats are curated and industrial-leaning; scoring well there is not evidence
  roofclf works on the rest of the country. `pixi run roofclf-review draw --aoi <aoi> --seed S`
  (`scripts/roofclf_review_page.py`) draws 20 cells uniformly from the scored cells inside the
  density domain the atlas prices (`tile_roofclf_detections_geojson.py --random-cells
  --in-domain`; `--all-cells` for every scored cell), quadrats excluded, into
  `results/<aoi>_roofclf_random_<seed>/`, adds blank rows to the country's log
  (`results/roofclf_random_validation_log.csv` for Pakistan, `results/<aoi>_roofclf_random_
  validation_log.csv` elsewhere: `quality.ROOFCLF_LOG`, which the checklist reads) and pages
  20 random flagged roofs per cell like the blob and large pages (`data/roofclf_review/` ->
  /home, hub `index.html`; keys 1-4, bright roof counted not PV, no score shown). Each roof is
  six panels: roof and yard, close up, 300 m, on **Esri (saved) and Mapbox (fetched live by
  the browser, never stored)** over the same ground (`view`), lines drawn by the page (`o`
  hides them). Mapbox needs a public `pk.` token in `~/.config/earthpv/mapbox_token`, written
  into the page, or pasted by the reviewer (kept in the browser). A batch drawn from another
  scoring is refused (fingerprint in `review_design.json`). `apply --verdicts --reviewer`
  fills the log and writes the batch's precision (cells weighted by flagged count); `status`
  lists every page. `level` pages the blind score-level review, whose
  `roofclf_level_review.py analyze` reads the level against the published scoring. Only seed
  20261107 (`BATCH_OF`, drawn from every scored cell) describes Pakistan's published scoring.
- **Mapped PV outside the calibration areas validates sensitivity only.** It was mapped from
  segmentation leads, area screening and chance finds, so it is positive-only and selected.
  `scripts/roofclf_osm_positive_check.py` compares roofclf's score on those roofs with the
  quadrats' out-of-fold score per array-size bin, post-stratified on proximity to a segmentation
  lead. Never read fill per PV roof, the coverage ratio or the level from that set (mappers skip
  tiny arrays: fill reads 1.4-2.5x the quadrats'). `scripts/osm_sweep_completeness_review.py`
  draws a blind, score-stratified review of unmapped roofs in densely mapped ~1 km boxes; a box
  found nearly complete is a candidate calibration area, which only the owner can declare.
- **Solar farm (blob) review (owner, 2026-11-02).** A model outline above the merge cap stays
  out of capacity until it is mapped or a person judges it solar on the Sentinel-2 page (three
  composite panels, nothing else, since 2026-11-20). `run_country_compute.sh`
  draws a country's page after `export`; `data/oversize_review/index.html` lists every
  country's page and `pixi run blob-review status` the counts. Sittings can be partial: apply
  any export, then `density --districts` (no `--force`) and the atlas. Mechanics and pricing are
  under "Density stage". **Verdicts of both review pages become mapping leads** (2026-11-19):
  after the atlas, re-run the `leads` release (below), which moves `pv` outlines to the
  confirmed-lead file and drops `not_pv`/`bright_roof` ones from the lead files. **Only the
  confirmed file reaches mappers (owner, 2026-11-19)**: the atlas links no unchecked lead or
  blob file.
  **`pixi run flywheel-status`** (`scripts/flywheel_status.py`) reads the verdicts into a call
  per country and placement: precision of new outlines >= 1 ha with a 90% Wilson interval
  (30+ verdicts; fine if it starts >= 0.8, false alarms if it ends < 0.5; blobs never decide),
  false alarms per 1,000 cells, and new labels (confirmed leads + OSM edits after the latest
  local chip corpus) against the corpus; >= 10% asks for a mapping round and a retrain. The
  thresholds are judgement, approved by the owner (2026-11-19). It cannot see recall: the
  held-out region decides when to stop.
  Verdicts as training negatives are an experiment (`scripts/verdict_hard_negatives.py`,
  Texas v47 vs control v47c, `scripts/run_texas_verdict_negatives.sh`), not a pipeline step.
- **Large installation review (owner, 2026-11-10), in JOSM since 2026-11-20 (owner).** Leads
  from `LARGE_MIN_M2` (10,000 m²) up to the cap, rooftop and ground (`pixi run large-review`,
  `scripts/oversize_review.py --kind large`; `results/<aoi>_large_review/`, packages in
  `data/large_review/` -> /home), drawn after the blob page. `draw` writes the JOSM layer
  `data/large_review/<aoi>/<aoi>_large_review.osm` (`write_josm`: open leads largest first,
  `upload="never" download="never"`, tags `earthpv:code`/`earthpv:review=todo`/`earthpv:draw`)
  and no page. The reviewer maps the solar that is there into OSM (Todo list + continuous
  download, `docs/contribute/review.md`) and marks a lead with none `earthpv:review=not_pv`;
  `apply --josm <saved layer>` writes review.csv's `josm`/`josm_reviewer` columns and never
  touches `verdict`. A mapped lead needs no mark: `apply` (and `draw`) set `osm` = `mapped` for
  every lead the given `--labels` pull now covers, and the map counts it at its own shape. A
  `not_pv` mark only takes the lead off the layer and counts as checked in the quality
  checklist; it prices nothing (the lead keeps its bin's P(real)) and no lead file, study or
  training set reads it. `--page` adds the Sentinel-2 page (`GUIDE_LARGE`), whose verdicts
  price as before; once drawn, `draw` keeps it current, `--no-page` removes it, and `package`
  removes a page from before 2026-11-20 (Esri). Both draws are
  retried once and never fatal, so check the layer exists (a DNS outage once left one missing
  while its step read done); `pixi run large-review status` says which countries have them.
  Any named reviewer counts (owner); it is a documented way to contribute
  (`docs/contribute/review.md`). It matters most for large ROOF leads, whose bins price P(real)
  at 0.00-0.07 where reviewers found 92-99% solar. Both pages carry key 4 **"Bright roof"**:
  priced as `not_pv`, kept as `flag: bright_roof` in review.csv (`review_flag` in
  review.geojson, a `status` column) so the false alarm can be studied
  (`build_review_page.write_page(bright_roof=True)`; other pages on that builder keep three
  keys, since their joins know only those).
- **Imagery date is the gate on sparse areas, not mapping effort.** Out-of-domain random cells
  and low-density quadrats often sit under reference imagery too old to confirm or refute recent
  small PV, so a zero there is uninterpretable. Do not register such a quadrat (it pulls the
  sparse band's coverage ratio toward zero). Check `imagery_layer`/`imagery_date` before
  drawing, not after mapping.

## Environments & commands

Managed with **pixi**:
- `default` -- the data pipeline (DuckDB, geopandas, rasterio, odc-stac). No PyTorch.
- `ml` -- adds `torch`/`torchvision` (**cu126 wheels**) and `terratorch`; shares `default`'s
  solve-group.
- `docs` -- mkdocs-material only (`no-default-feature`), so a docs edit never waits on a solve.
- `ml-cpu` / `ml-rocm` -- the `ml` stack on PyTorch's CPU-only or ROCm 6.3 wheels, for people
  without an NVIDIA card (`docs/contribute/new-atlas.md`, "No NVIDIA card?"). Each has its own
  solve-group (`+cpu`/`+rocm6.3` wheels cannot share one with `+cu126`), so their data libraries
  resolve newer than `default`'s; the model stack (terratorch, lightning, timm,
  segmentation-models-pytorch, huggingface-hub, kornia) is pinned to `ml`'s locked versions:
  **move those pins whenever `ml` re-locks**. `pytorch-triton-rocm` must name the ROCm index
  itself or the solve fails. No code switch: `infer`/`train`/`evaluate` take the GPU whenever
  `torch.cuda.is_available()`, which a ROCm build reports for an AMD card. `ml-rocm` has never
  run on an AMD card. CPU inference matches the 1060's to rounding (no pixel crosses 0.3) at ~3x
  the time; CPU training is impractical (Lightning turns `16-mixed` into `bf16-mixed`, ~40 s per
  ResNet-50 batch).

```bash
pixi install            # default env
pixi install -e ml      # + torch cu126 + terratorch (multi-GB solve)
pixi install -e docs    # mkdocs-material
pixi run -e ml gpu-check # names the device infer/train will use (scripts/gpu_check.py; exit 0 on CPU)
```

Run stages via the CLI (Typer); long GPU stages in the `ml` env, or call the interpreter directly
to avoid pixi's per-invocation overhead:

```bash
pixi run earthpv labels --aoi germany            # default env is fine for data stages
.pixi/envs/ml/bin/python -m earthpv.cli train --config configs/terramind_pv.yaml
.pixi/envs/ml/bin/python -m earthpv.cli infer  --aoi punjab --checkpoint data/models/<best>.ckpt
```

CLI stages (`src/earthpv/cli.py`): `labels → chips → train → evaluate → infer → postprocess →
export`, plus `compose` (imagery for AOIs with no local composites), the capacity stages listed
under "Main workflow", `combine-atlas`, `osm-hard-negatives`, `groundclf*`, `validate-mastr` and
`validate-france`. `train --smoke` runs 50 steps; `chips --limit N` caps the chip count.
`roofclf-score-national` is the long pole (hours) and is resumable per cell like `density`.

**There is no test suite and no lint task wired** (`tests/test_mastr_validation.py` runs as a
plain script; pytest is not a dependency). Ruff is configured (line-length 100) but run
manually. The practical check is a small end-to-end run: `chips --aoi germany --limit 500` →
`train --smoke` → `evaluate`.

**The released segmentation model is v28 (owner, 2026-11-12)**, fetched with `pixi run
fetch-model`: `scripts/fetch_model.py` downloads `earthpv_segmentation_v28.ckpt` from release
`segmentation-model-v28-2026-11-12` into `data/models/release/` and checks its SHA-256;
`new_region.py plan` and the setup docs take the file name from its `RELEASE` (the default
entry of `RELEASES`). **v14, the TerraMind released 2026-10-23, stays released as the
alternative (owner, 2026-11-20)**: `pixi run fetch-model -- --model terramind` (Apache-2.0,
33 MB, threshold 0.3), for deserts, dark open ground and very large parks; before choosing
in a country of large parks, compare both runs' OSM ground screens by park size.
`scripts/build_hybrid_prob.py` combines two runs by outline size (one model everywhere, the
other inside its own outlines above a size; California's test in
`docs/results/california.md#a-size-hybrid-2026-11-20`). It is
`v28_resnet50_south_africa/last.ckpt` (ResNet-50 from SSL4EO-S12 on v14's corpus, EMA weights
after a fixed 42-epoch budget) put through `scripts/slim_checkpoint.py` (139 MB, identical
predictions), run at threshold 0.3 (`results/release_model_benchmark_v28.csv`,
`docs/pretrained-model.md`). **Every published atlas runs on its own country's checkpoint; the
release changes no published number.** To release a newer model: slim it, upload it with
`SHA256SUMS`, `MODEL_CARD.md`, `LICENSE`, `NOTICE`, its config and benchmark to a new tag,
update its entry in `RELEASES`, and redo the page's tables. **The weights are CC BY 4.0** (the SSL4EO-S12
licence; `NOTICE` carries the SSL4EO-S12, OpenStreetMap and Copernicus attributions); detections
stay ODbL like every data output. The config's recipe (`ema`, `jitter`, the warmup-cosine
`scheduler`) needs `train.py` options that are not on main yet.

## Architecture

### Data reuse -- the load-bearing design decision

To avoid re-downloading terabytes, imagery and labels are **reused from a sibling
`rooftopsenti` project** on the same drive, pointed at by `local_root` in `configs/aoi.yaml` and
each AOI's `source_region`. `src/earthpv/local_source.py` reads that project's per-MGRS-tile
Sentinel-2 composite COGs (`CompositeIndex`) and its OSM/Overture label + building parquets
(`load_solar_labels`, `load_buildings`). The Overture (`overture.py`) and Planetary-Computer
(`imagery.py`) fetchers are **fallbacks** for AOIs with no local artifacts. **Direct Overture S3
queries time out from this machine -- prefer the local/VIDA paths.**

An AOI is only fully usable where its `source_region` has composites. `germany` uses
`germany_500`; `punjab` uses `pakistan_500` for *buildings*, but that region's composites cover
**Balochistan, not Punjab**, so Punjab imagery is built by `compose` into
`data/composites/punjab/`, which `infer` prefers over the `source_region`.

### Bands & the segmentation models

Local composites are **10-band** (B02–B12 minus the 60 m bands B01/B09). TerraMind's pretrained
S2L2A patch-embed is 12-band; `configs/terramind_pv.yaml` passes `backbone_bands: {S2L2A: [10
names]}` so TerraTorch **subsets the patch-embed** to those bands (`config.py` holds
`LOCAL_BANDS` / `MODEL_BANDS` and the mapping). Country checkpoints use `terramind_v1_tiny` (fits
a 6 GB GPU), a plain ViT, so the UNet decoder needs the neck stack `SelectIndices →
ReshapeTokensToImage → LearnedInterpolateToPyramidal`. Training (`train.py`) is a TerraTorch
`SemanticSegmentationTask` via Lightning; checkpoints monitor `val/mIoU`.

- **Compare checkpoints on installation recall at matched pixel precision, never on one
  val/mIoU or one fixed threshold.** val/mIoU is dominated by large ground plants and
  epoch-selection noise is as large as a backbone change; a fixed threshold rewards whichever
  checkpoint fires most. `scripts/compare_backbones.py` (paired McNemar per installation over
  every AOI's holdout) and `evaluate(extra_thresholds=...)` do this. Probabilities saturate, so
  matching often needs a threshold of 0.95-0.97.
- **Averaging an epoch pair's weights beats picking either epoch**
  (`scripts/average_checkpoints.py`, in-corpus and zero-shot; recomputing BatchNorm statistics does
  not help). But a threshold matched on holdout chips measures outline width, not false objects:
  over whole cells an average at its matched ~0.97 loses arrays to the baseline at 0.3, while at 0.3
  it finds more and adds a few smooth false sheets over plain farmland. **Chip-level holdouts cannot
  measure large false sheets**; `scripts/sheet_scan.py` (`curve`, `blobs`) compares whole cells.
- **Judge a candidate baseline (released) model zero-shot.** `scripts/zero_shot_suite.py build`
  makes `data/chips/zs_<aoi>` from whole chip sets of 10 countries outside
  `combined_south_africa` (5 km exclusion around corpus chips), scored with fair_score as
  `zs_<aoi>@<aoi>` and pooled by `zero_shot_suite.py report`; valid only for models trained on
  that corpus. `scripts/run_baseline_checks.sh` runs it and the sheet scan.
- **TerraTorch's TerraMind backbone does not standardise its input**, so stock checkpoints see
  DN / 10000. `backbone: earthpv_terramind` with `backbone_variant: terramind_v1_*`
  (`terramind_backbone.py`) applies TerraMind's own statistics (existing checkpoints load
  unchanged), but it gave no gain after full fine-tuning (v21, register). TiM variants cannot
  take our 10 bands.
- **On the GTX 1060 `train` uses PyTorch's math SDPA kernel** (`earthpv.attention`, pre-Volta
  only): the default kernel is ~3x slower for TerraMind training. **Inference deliberately keeps
  the default kernel**: the kernels agree only to rounding, so switching would break
  byte-for-byte reproduction of published rasters. `EARTHPV_SDPA=default|math` overrides.
- **Training is protected against systemd-oomd.** `datamodule` drops each chip from the page
  cache after reading it (a ~20 GB corpus cannot be cached inside a unit's MemoryMax).
  `resume: true` is opt-in and continues from the run's own `last.ckpt`; pair it with
  `systemd-run -p Restart=on-abnormal`.
- `src/earthpv/thor_backbone.py` (reads the gitignored `third_party/` checkout) is tooling from
  a backbone comparison that was not adopted.

### Adding a new AOI

`scripts/new_region.py` is the front door: `check` preflights the four open sources (Overpass
label count, VIDA parquet for the ISO3, geoBoundaries ADM1/ADM2, Sentinel-2 cloud cover in the
compose window) read-only, `add` appends the AOI block to `configs/aoi.yaml` (with `val_tiles:
[]`) and re-parses it, `plan` prints the runbook. **New AOIs must carry `division.iso3`**
(`buildings._iso3_for` prefers it; the ISO2 fallback covers only PK/DE/IN, so an AOI without it
fails at `density`). `source.coop` 403s any request without a User-Agent header, which reads
exactly like "no such country." Guide: `docs/reproduce.md`, "Scale to a new country". Before a
new country's atlas is built, re-run `scripts/ember_import_ceiling.py` and add any official
figures to `scripts/official_capacity.py` and re-run it.

**New AOIs sit on the global 0.1° lattice**: `grid_origin` on whole tenths of a degree, so a
country's cells are global cells and its atlas combines with its neighbours' cell by cell
(`earthpv.global_grid`, "Combined atlases"). `new_region.py add` writes it
(`global_grid.snap_down` of the bbox corner); `compose` refuses to START an AOI off the lattice
and only warns for one that already holds composites (`EARTHPV_ALLOW_OFF_LATTICE=1` overrides).
**Never change a `grid_origin` after the first compose**: it renames every cell. Off the lattice:
Pakistan, Germany, France, Zambia, Nigeria.

**A state or province can be an AOI** (`division.subtype: region`: California, Texas). Compose
clips to its ADM1 polygon by name (`compose._aoi_boundary`); `density.subnational_units` makes
its ADM2 units (more than half their area inside; a representative point lost Texas's Aransas
County to the bay) its regions, with no district layer, so the province chart, cell count and
`pick_val_region.py`'s holdout stay inside it; `density.aoi_border` clips the OSM solar file and
the CSP table to it. Training labels still take the neighbours inside the bbox.
`scripts/vida_subset.py` (`VIDA_BOXES` in `prepare_country_vida.sh`) installs only some boxes of
a country's VIDA: **`data/vida/USA.parquet` holds California's and Texas's footprints only**, so
another US state needs it redone with its box added (`<raw>.json` lists the boxes).

### Compose stage (imagery for AOIs without local composites)

`compose.py` builds Sentinel-2 composites via Planetary Computer STAC
(`imagery.annual_composite`: dry-season median of the ~12 least-cloudy scenes per 0.1° cell). It
composites **building-populated cells** (prioritized by density) plus label cells
(`compose._solar_label_cells` covers a mapped park's whole outline). Output mirrors the
rooftopsenti COG layout (`<cell>/composite_0.tif`) so `CompositeIndex`/`infer` read it
unchanged. It is **resumable** and **network-bound**; it honours an AOI's `compose_window` when
`--window` is not passed. AOI keys: `ring_cells: N` adds every cell within N cells of the
selection (appended, so resumed runs are unchanged); `cell_selection: duckdb` aggregates
per-cell VIDA counts in DuckDB (cached in `data/cells_cache/`) for very large countries;
`grid_origin` pins the cell naming.

`imagery._rank_items` ranks scenes covering >= 99% of the cell first (`eo:cloud_cover` is per
MGRS tile, so dry-season scenes tie at 0%), and `imagery.BAND_DROPOUT_MAX` raises on a cell that
lost a band (failed reads used to become zeros). Composites built before 2026-10-10 lack both
fixes; India, Zambia, Nigeria and Vietnam were not recomposited (open question 11;
`scripts/scan_composite_defects.py` measures a country).

### Postprocess & ranking

`postprocess.py` polygonizes probability rasters, then joins candidates to building footprints
for a rooftop/ground/no-building `placement` and a `rank_score` (confidence × building prior).
Footprints come from `buildings.py::load_dense_buildings` -- **VIDA Open Buildings**
(Google+Microsoft, includes small/unmapped roofs), fetched windowed-and-cached per AOI; the
local Overture ≥500 m² set is the fallback. `postprocess.replace_with_osm_geometry` substitutes
an OSM-mapped installation's geometry for the model's coarse polygon when one matches (closest
match only). `export.py` sorts by `rank_score` and writes GeoParquet/GeoJSON + a MapRoulette
challenge.

For large countries: `--building-buffer-m` bounds which footprints are fetched (placement uses
30 m and the rank prior ~40 m; 500 for Vietnam/India); `--stream-buildings` fetches/joins/discards
per 0.25° chunk; `--reuse-join <previous candidates.parquet>` (with `--stream-buildings`) keeps
the join of every chunk whose candidates are unchanged (India's full join is 23 h).

### Density stage (segmentation capacity, PyPSA-ready shapes)

`density.py` reuses the per-cell probability rasters (no GPU) to report capacity per
building/cell/region for the **≥ 400 m²** population. Three area metrics per building: `*_det`
(thresholded polygons, a precision-honest floor), `*_exp` (probability-weighted, an
upper-leaning ceiling) and `*_cal` (`*_det` re-weighted by measured P(real | size, glint,
placement)). The headline is `est_mwp_rc`, which also divides by measured recall per size class
(Horvitz-Thompson). Derivation: `docs/methods/density.md`.

**Area → capacity uses two calibrated constants, never one.** Rooftop converts at
`DEFAULT_KWP_PER_M2_MODULE = 0.18` kWp/m² (module area); ground at `DEFAULT_KWP_PER_M2_LAND =
0.05` (site area: ground labels are OSM `power=plant` perimeters; `KWP_LAND_CI90 = (0.035,
0.075)`; capacity-tagged parks measure 0.043-0.047 in India, South Africa, Texas and
California). The module constant on site area overstates ground-mount 2-3x, so
`_ratios`/`_composed_mwp_draws` split every estimator by `placement` before conversion. Both
constants carry lognormal priors (`capacity_calibration.kwp_draws`) that propagate into the
intervals. France's register measures the module constant at 0.150; 0.18 stays pending an owner
decision.

**Precision/recall calibration is split by placement**
(`capacity_calibration.derive_placement_tables`); ground bins fall back to `p_unmapped = 0.0` (an
honest floor). `density.candidate_p_real`, `candidate_recall` and `_candidate_uncertainty` select
each candidate's placement subtable. **Recall is "was this installation found by ANY candidate"**: a
large array overruns its VIDA footprint and is classified `ground_adjacent`/`no_building`, so a
same-placement finder understated large-rooftop recall up to 24x.

**The checked-in calibration YAML is load-bearing**
(`configs/calibration/<aoi>_candidate_precision.yaml`) and was silently regressed once by a bare
re-run. Guards: `calibrate-candidates --by-placement` defaults to True;
`capacity_calibration.write_table` **refuses** to overwrite a table carrying evidence the new one
lacks (placement split, glint calibration, manual reviews, `register-p-unmapped`, review blocks)
unless `--allow-downgrade`; `density.py` warns when a table lacks `placement_bins` for an AOI with
both placements. Pakistan's table (v16, 41 calibration boxes, `status: interim-mapped-only`:
`p_unmapped` from mapped installations only, no glint sample yet) needs the calibration boxes and
`--glint-sample` to reproduce, not a bare re-run.

**OSM reference polygons are dissolved before use** (`labels.dissolve_overlapping`): a
`power=plant` perimeter with a nested `power=generator`, or duplicate mapping passes, would
otherwise double-count. Wired into `export.load_mapped_reference_attrs`,
`postprocess.replace_with_osm_geometry` and `atlas.build_evidence_atlas`'s OSM sum.

**The merge cap.** Candidates over `postprocess.MAX_CANDIDATE_M2` (100k m²) are excluded from
capacity (`density.capacity_relevant_candidates`, shared by `density`, the evidence atlas and
`calibrate-candidates`): `polygonize_chips` merges touching pixels with no bound, so a sheet of
false positives becomes one multi-km² "installation". A `geometry_source == "osm"` oversize
candidate is exempt but always ground, and where the AOI has a ground screen
(`results/<aoi>_osm_ground_screen/screen_full.csv`, auto-discovered by `density.load_osm_screen`)
an outline above 5 km² that fails it (imaged >= 0.9, detected >= 0.5) is credited at outline
area x `det_frac`. Verified carries that outline at the same share (`screen_credit`), so Best
takes it through its per-cell floor rather than at the bin's `p_real`.

**Blobs (model outlines above the cap) count only once a person has judged them (owner,
2026-11-01).** `scripts/oversize_review.py draw|apply` writes an `oversize_review` block into
the calibration table; `density.load_oversize_admission` admits exactly the new-lead outlines
(`export.new_lead_mask` at the review's `min_distance_m`) with a `pv` verdict in its
`review_csv`, matched by `candidate_index` and area, whole (`p_real_fixed` 1, stratum
`reviewed`), placed as ground, recall 1. One judged and later mapped is counted from the map; a
verdict naming an outline the candidates no longer hold at that area is an error (a new model
run needs `draw --redraw`, which also clears the crops). `draw` queues every blob (stratum
`queue`, largest first); `apply` takes partial exports, keeps earlier verdicts, reports
agreement with them, and refuses unsure census/sample rows unless `--unsure-as`; a blank or
unsure queue outline stays out and returns on the next page; `excluded_regions` no longer
filters (a verdict outranks it). The queue is the published blob
file's population (`oversize_review.lead_screened`; `run_source` takes the candidates and
reference behind the page from `release_leads.SOURCES`). The review blocks act at population
level, outside `process_cell`, so cached partials stay valid and no `--force` is needed;
`calibrate-candidates` carries them forward and `_table_evidence` guards them. A country without
the block keeps the cap exactly.

**The review page shows the imagery the model saw, and only that (2026-11-20).** `draw` runs
`package`: three Sentinel-2 panels per outline in `data/oversize_review/<aoi>/crops/`
(`<code>_s2`, `_pixels`, `_false`: composite true colour, 10 m detail, false colour
SWIR/NIR/red; fixed reflectance stretch) and `index.html` from `build_review_page.write_page`
(keys 1-4, notes, links `LINKS_FREE` + `josm_link`: Copernicus Browser, OSM, JOSM with the
changeset hashtags; CSV export `<aoi>_blob_verdicts.csv` whose `imagery_date` is `Sentinel-2
only, <window>`), plus the same outlines as a JOSM layer. A settled outline (verdict, JOSM
`mapped`/`not_pv`, or `osm` = `mapped`) leaves the page and layer on the next `package`,
`--include-judged` keeps it. Saved progress is keyed to the draw, so old verdicts cannot attach
to a redraw's codes. What 10 m cannot settle stays unsure and out of capacity until mapped.

**A verdict on a lead below the cap replaces its bin's P(real) (owner, 2026-11-10).** `apply
--kind large` writes a `lead_review` block (`capacity_calibration.LEAD_REVIEW_KEY`;
`min_area_m2`, `review_csv`, `mapped_reference`, `min_distance_m`, reviewers).
`density.load_oversize_admission` returns its verdicts with the blob rows (`p_real_judged`:
`not_pv` 0, `pv` 1 on the ground and 1/`rooftop_outline_ratio` on a roof), so every caller of
`capacity_relevant_candidates` gets them; `cc.candidate_p_real(judged=...)` applies them at the
five pricing call sites (`density.judged_of`). Unlike a blob, a judged lead keeps its bin's
recall, its placement and its kWp constant, and stays in `process_cell` and `*_det`. **A roof
lead judged solar counts 1/2.5 of its outline, a ground lead whole** (owner;
`capacity_calibration.LEAD_ROOF_OUTLINE_RATIO`, recorded per block): Pakistan's roof outlines of
5k-50k m² are 2.52x the mapped array, measured in Pakistan only. Unsure or blank changes
nothing. Best's per-cell floor adds judged parks and leads (`atlas.judged_floor_kwp`, shared by
`build_evidence_atlas` and `_size_distribution_data`, which must agree; cell column
`judged_park_mwp`).

**`buildings.geoparquet`'s summed rooftop capacity is not `grid.geoparquet`'s region total**, by
construction: the region total sums each rooftop candidate's polygon once, the per-building
table credits only its intersection with each building capped at roof area (~46% gap in
Pakistan). Per-building disaggregation is a conservative floor.

**A model outline is ~2.4x the panel area it found** (Pakistan rooftop >= 400 m²,
`scripts/candidate_area_bias.py` on pre-substitution candidates; open question 17). Published
capacity barely sees it (matched candidates carry their OSM outline, bin `p_real` discounts the
rest); it bites wherever `p_unmapped` credits unmatched candidates as real, i.e. Germany's
register-derived bins.

**The 90% credible interval** (`atlas._evidence_uncertainty`) composes every measured source
(kWp priors, coverage-ratio quadrat bootstrap, `KWP_LAND_CI90`, the farm-ground replicates) with
correlated terms sharing one draw vector, and asserts its component point values sum to the
published total: a guard against adding a component without adding it to the uncertainty.

**OSM and a recall-corrected total: combine, don't add.** `est_mwp_rc` already stands in for the
mapped installations the model missed. `build_evidence_atlas` (and `_size_distribution_data`)
takes, per placement x size bin, `max(HT, D + U)`: the absorbed share comes out of each
candidate's inflation, never below a cell's `est_mwp_cal_*` (`atlas.osm_absorbed_inflation`).
Where a recall correction applies, OSM counts as matched at the table's `min_distance_m`
(100 m). Inside the ge400 roofclf domain every OSM rooftop installation is counted from the map.
`--legacy-osm-addition` reproduces the old convention; the page records it in
`totals.osm_combination`.

**Pricing low-confidence open ground apart exists but is not adopted** (owner decision pending):
`calibrate-candidates --confidence-split 0.9` or `scripts/split_calibration_tables.py` adds a
third placement table (`capacity_calibration.LOWCONF_GROUP`); every pricing call passes
`confidence`, and `_placement_group` refuses a split table without it.

**Overture publishes a coastal admin division twice** (land, and land plus territorial waters).
**Keep the LAND polygon, the SMALLER of a nested pair.** `density.drop_nested_duplicates` (in
`load_admin` at both levels, repeated by `atlas._region_rows`) tests **nesting**, not name
equality. geoBoundaries has no maritime rows.

### roofclf capacity (the sub-400 half)

Method: `docs/methods/roofclf.md`.

- **≥ 400 m² replacement in-domain** (`roofclf_ge400_capacity.py`, `earthpv
  ge400-roof-capacity`): segmentation is blind to array size relative to its building, so a
  large building with a small array reads as a miss. Outside the domain,
  segmentation's `est_mwp_rc_roof` remains the only number.
- **The coverage ratio** (true mapped PV area / score-weighted roof area) is measured **per
  building-size decile AND per density stratum**
  (`sub400_capacity.coverage_ratio_by_size_and_density`, shared by sub-400 central, the AND-gate and
  the ≥ 400 m² replacement). Its uncertainty comes from **resampling calibration quadrats**, not
  buildings: 200 bootstrap replicates, one replicate index shared across all roofclf components
  (`sub400_capacity.COVERAGE_BOOTSTRAP_SEED`).
- **roofclf's own misses are corrected for** (`sub400_capacity.area_recall_by_size_and_density`):
  divide by the measured share of mapped PV **area** on flagged buildings, per size bin and
  density stratum. Coverage ratio and area recall are refit inside the SAME bootstrap
  replicates. `--no-recall-correct` reproduces uncorrected figures; `--coverage-boot N` (default
  200; 0 disables and narrows the interval).
- **Priced by probability, not a threshold** (`sub400_capacity.WEIGHTINGS`, `--weighting`,
  default `probability`): every in-domain building counts by its `p_roofclf`, with coverage
  ratio and area recall refit on the same weights; output is one row per (cell, size bin) with
  `n_buildings` and `sum_p`. It trusts the score's LEVEL in sparse national cells, which is
  unmeasured (open question 1 holds the declared revert rule). The AND-gate files stay
  thresholded (`_check_weighting` refuses probability with SPPI), and the fitting primitives keep
  `"threshold"` as their own default, so a new caller passes `weighting` explicitly. **Give
  `ge400-roof-capacity` and `sub400-capacity` the same `--weighting`.** The atlas records it in
  `totals.roofclf_weighting`.
- **The sub-400 populations dedupe only against candidates whose figure Best uses**
  (`sub400_capacity.dedup_candidates`). `sub400-capacity` reads the domain from
  `ge400-roof-capacity`'s output, so **run ge400-roof-capacity first**.
- **The parcel label (`roof-classifier --parcel-label`) is the production label**: it adds mapped
  PV within `YARD_RING_M` (20 m) of a footprint, whole to the nearest building, for installations
  below 400 m² only (`roofclf.parcel_pv_area`). 80% of what it recovers is rooftop PV overhanging
  an undersized VIDA outline, 20% OSM `placement=ground`; quote
  `sub400_capacity.parcel_label_composition` for the placement claim. A parcel-label model
  needs its own national rescoring; `roofclf.check_scoring_matches_calibration` refuses to pair
  a scoring with another calibration's coverage ratio.
- **A foreign quadrat table can train a country's fit** (`roof-classifier --extra-table
  <other>/buildings.geoparquet --extra-share 0.5`): its rows enter every fold's training and the
  deployment fit at that share of the likelihood, are never a fold, and never reach the coverage
  ratio. There is **no global roofclf**: pooling never beats a country's own fit, and a matched
  donor helps only while a country has few areas (`scripts/roofclf_loco.py`). `bf_confidence`
  is not a feature (empty outside Pakistan).
- **Ranking is not a level.** Check a new country's pricing leave-one-box-out against a
  roof-area-only null (`scripts/roofclf_yemen_pricing.py`), not only its AUC: Yemen's scores rank
  well and price worse than roof area, so Yemen stays "not measured".
- **The density-calibration domain is a building-density band**, fit from the density span of
  every Rule-1-complete calibration quadrat (NOT `select_calibrated_quadrats`'s precision-trust
  selection). Pakistan: **(48.5, 5,258.00) bldg/km²**, 2,957 of 4,463 cells (94.7% of buildings).
  Per AOI: `density.calibrated_density_range(aoi)` looks up `CALIBRATED_BLDG_DENSITY_BY_AOI`
  (france 17.5-390.8), warns when an AOI has none and falls back to Pakistan's; `aoi` is threaded
  through `sub400_capacity.py`, `roofclf_ge400_capacity.py`, `growth.py` and `cli.py`.
  `--ratio-lo`/`--ratio-hi` do **not** affect this domain (they tune the precision-trust band, a
  real footgun). **To widen it**, a quadrat's OWN average density must read below the floor, so
  a range-extending quadrat must deliberately average in non-built land.

**Pakistan's published figures.** Segmentation v16 with the 41-box table: `est_mwp_rc` 3,146.8
MWp (rooftop 1,994.3, ground 1,152.5). roofclf fitted on 41 areas (16 features, parcel label,
area-weighted zonal means, recall-corrected, probability-weighted), coverage ratio and area
recall fitted on the **19 pinned areas** (`sub400_capacity.PINNED_COVERAGE_QUADRATS`): sub-400
central 24,381.0, ≥ 400 m² rooftop replacement 7,257.9. Median LOQO fold AUC 0.8459, deployment
threshold 0.2470 (precision 0.50, recall 0.642). **Best 34,468.6 MWp (90% 28,626-41,308),
Verified 3,637.5 (2,917-4,664).** `check-density` passes all 7 regions (Gilgit-Baltistan exempt
from the ratio check). **No random validation cell has been reviewed yet** (every row of
`results/roofclf_random_validation_log.csv` is blank, five seeds) and neither has the blind
score-level review (`results/pakistan_roofclf_level_review/`), so the published figure rests on
an unreviewed rescoring (open question 3). The coverage ratio's lower band (< 1,717 bldg/km²)
prices 2,937 of 2,957 in-domain cells from 9 quadrats.

### One atlas template, one config file per country (`configs/atlas/<aoi>.yaml`)

`templates/pv_evidence_atlas.html` is shared by every country; everything country-specific lives
in `configs/atlas/<aoi>.yaml`, never in the builder. `atlas_config.load(aoi)` supplies `title`,
`cities`, `calibration_boxes`, `composition_page`, `layers`, `validation`, `map_view`,
`start_here`, `small_rooftop` and three optional confidence blocks (`ground_truth`, `caveats`,
`corroboration`). A missing file is normal; a malformed one is an error, including an unknown key.
**`small_rooftop` says how the rooftop estimate below 400 m² is made**: roofclf when absent, or
`method: roof_area` with `roof_m2`, `kwp_per_m2` and `register` (Germany). The page gets it as
`__SMALL_ROOF_JSON__` (`atlas.small_rooftop_json`) and the charts, method text, map layers, KPI
tile, footer, CSVs and `_composition_note` name the method from it, so a roof-area estimate is
never called roofclf. No page names the segmentation model (TerraMind or ResNet-50 checkpoints;
the page data records neither).
`_confidence_html` gates every claim on the thing that makes it true and derives its counts;
`_composition_note` derives "which method supplies most of Best" from the page's own components.
`_load_calib_boxes` looks in `data/labels/<aoi>/` before `data/labels/`.

**`scripts/check_atlas_templates.py` fails CI** if a published atlas names another country in its
visible text or links another country's page (config strings are exempt). **`pv_growth_atlas.html`
and `pv_size_atlas.html` still carry Pakistan-only prose and links** and are not covered by the
guard.

### The evidence atlas page

**MapLibre GL JS 5.24 and Observable Plot 0.6.17 on D3 7.9**, from jsDelivr at exact versions
with SRI hashes. **MapLibre 5, not 6**: v6 is ESM-only with a separate module worker, which does
not load from a CDN into a `file://` page or an iframe. Offline, hero, KPIs, tables, the
composition bar and the pose plot still render; the map and Plot charts say they could not load.

Page rules worth knowing before touching the template:

- **Unmeasured is "not measured", never 0**, on every surface, keyed off `totals.*_status`
  (`small_rooftop_status`, `small_ground_status`). The size chart continues each unmeasured bar
  below 400 m² as an open-ended fade (also on empty bins; never on the "<400 m², not split"
  column, which holds capacity with no per-installation size: farm ground PV, Germany's per-cell
  rooftop half, `totals.size_unbinned_*_mwp`). The hero total carries a scope chip, ">400 m²
  only" or "rooftops >400 m² only", from the same statuses.
- **Colour means method**: OSM teal, segmentation blue, roofclf amber, farm ground PV green;
  hatching means ground-mount. Farm calibration areas (`_farm_calib_`) are green diamonds,
  building areas ink diamonds.
- **Map**: "Show" picks the cell quantity (Best, *Not yet in OpenStreetMap*, hand-mapped, model
  >= / < 400 m², CSP, rooftop potential), always as MWp per cell, on log ember ramps
  (`RAMP_DARK`/`RAMP_LIGHT`, floor `RAMP_FLOOR_SHARE`, night glow `HOT_SHARE`). **No OSM data
  shows when a page opens (owner)**: the OSM capacity rings and the live Overpass overlay are
  opt-in. Basemaps: none, Esri grey, OpenStreetMap, Esri satellite (**CARTO needs an API key**).
  City labels are HTML (no glyph server). Readers can add GeoJSON/CSV/XYZ/WMS; a country can ship
  layers in its config (embedded by `atlas.map_layers_json`, 5 MB cap). **Unimaged cells are
  hatched** (`unimaged` runs from `atlas._cell_coverage`), and the map frames the whole country
  unless the config names a `map_view`.
- **Layout**: one wide template on every page since 2026-11-13 (map ~60% with the size chart
  beside it, KPIs 2 x 2 beside the province chart, lower sections paired). No EarthPV logo above
  the title (owner). A `.dl-item` needs `[hidden] { display: none }` beside its `display: flex`,
  or empty download cards show.
- **Type (owner, 2026-11-27)**: Source Serif 4 for the title, section titles, the large numbers
  and longer prose; Source Sans 3 for captions, labels, legends, tables and chart text
  (`--font-serif`, `--font-text`; `@fontsource-variable/*@5.2.8` from jsDelivr by unicode-range,
  Georgia and the system sans offline). Spacing on `--sp-1`..`--sp-8`; labels, links and buttons
  in ink (links underlined in the accent), so colour stays with the data. **The map card, its
  tooltip, popups and add-a-layer dialog keep `--font-display`/`--font-mono` (owner: the map is
  not touched)**, so never restyle the page through those two tokens. **Never name a
  placeholder in a template comment**: the builder and `retemplate_atlas.py` fill every
  occurrence (a CSS comment naming the badge's placeholder pasted its `<style>` into the page's).
- **Quality checklist** (`earthpv.quality`, `__QUALITY_HTML__`, section `#quality` below the
  panel orientation, above the background notes; owner, 2026-11-19): 16 checks in five stages (detection, map ground truth, checked by
  people, below 400 m², independent), each done / with flags / under way / not yet / n/a and
  tagged with the level that needs it. Every status is read from a record (page totals,
  `validation` declarations, calibration table, review CSVs, `results/<aoi>_checkpoint_decision.json`,
  `<density>/plausibility.csv`, the roofclf random-cell log, `results/glint_coverage/`); what
  no file holds goes in the config's `quality: {<check>: {status, note}}` (model choice of
  Pakistan, Germany, France, Zambia). `patch_atlas_leads.py` and `retemplate_atlas.py`
  recompute it on every pass, so re-run `patch_atlas_leads.py` on the pages after a review
  sitting or a declaration.
- **Tiles and sections**: the generation tile (`totals.generation`, `atlas.generation_totals`:
  Best times PVGIS yield from a cached probe grid `data/irradiance_probes/<aoi>.csv`, fetched by
  `earthpv atlas` unless `--no-fetch-irradiance`; leans high, carries no yield uncertainty;
  **south of the equator the panel azimuth is 0**); the province chart (top 7, `PROV_TOP`); the
  Capacity and Uncertainty pair (owner, 2026-11-22: every part of Best as its own bar on one
  MWp scale under method headings, and each part's 90% range as % below and above its own
  figure, both in the references chart's idiom: name above the bar, value at its end, no text
  inside a coloured bar, no log axis). **The pair is off every page** (owner, 2026-11-25: "we
  have to work on this further before publishing"): `#capUnc` starts `hidden` and is drawn only
  when `SHOW_CAP_UNC` is true in the template, and `check_atlas_templates.py` fails any published
  atlas whose switch differs from the template's or that predates it (re-template it). Turn it on
  only on the owner's word. "How the estimate is built" (`renderMethod()`
  from the page's own components); "Against official and published figures" (national and
  per-province bars against `configs/external/official_capacity.yaml`, written by
  `scripts/official_capacity.py`, and the Ember import ceiling; drawn side by side, never
  scored). The hero dates the atlas by the scenes' median acquisition date (`totals.imagery_dates`,
  `configs/atlas_imagery_dates.yaml`; `earthpv atlas` reconstructs a missing entry by re-running
  compose's STAC search, `--no-fetch-imagery-dates` skips it).
- **Rooftop potential layer** (`potential.py`, `earthpv roof-potential`): free roof area x roof
  share x 0.18 kWp/m² x PVGIS yield, in GWh/yr, off when the page opens and in no total. `earthpv
  atlas` picks up `<pred_dir>/<aoi>/potential/roof_potential_cells.parquet` by itself, so run
  `roof-potential` wherever a national roofclf scoring exists (only Pakistan has one).
- **Solar thermal power plants (CSP) count in Best and Verified at their electric rating, never
  as PV** (`solar_thermal.py`, `atlas._append_csp`, `docs/methods/solar-thermal.md`): added from
  `data/labels/<aoi>_csp_plants.parquet` as ground rows priced at `csp_mw`, always counted from
  the map, carried as `csp_mwp` and `totals.csp_*`. Capacity is `plant:output:electricity`, else
  site x `CSP_MW_PER_KM2` 27.2 (also for a tag > 3x that density on >= 0.5 km², e.g. a whole
  complex's rating on one plant). A PV outline at least half inside a plant is dropped as mirror
  field. A country without a table reads `csp_status.checked: false`.
- **Downloads**: every figure as PNG/SVG/CSV, re-rendered at 960 px, never serialised from
  screen; plus the release files below. **Every export carries the page's quality level
  (owner, 2026-11-19)**: `<country>_pv_atlas_<level>_<what>.<ext>` (`exportName`), the
  badge's medallion in a PNG/SVG header plus a level line under the figure, a leading
  `earthpv_quality_level` CSV column and GeoJSON property. `qualityLevel()` reads the badge
  the page shows (`.vscore--<tier>`), so a re-badged page exports its new level unrebuilt.
- **Plot gotchas**: on a log scale Plot routes any `tickFormat` through d3's log formatter, which
  blanks every tick with mantissa > 2 (draw labels with a text mark); a `{value, label}` channel
  object as `barX`'s `y` breaks the implicit stack (rename the field instead); `grid: true` on a
  scale plus a `gridX` mark draws two grids.

**Release files (default steps of `run_country_compute.sh`, owner 2026-11-13).**
- **Mapping leads**: the model's candidates more than 100 m from any OSM solar feature.
  `scripts/release_leads.py --aoi <aoi> --upload` (after `atlas`) rebuilds a country's files
  with export's ranking and `candidate_id`s from the run behind the page, clipped to the page's
  regions (refuses a run whose regions differ), and uploads only that country's CONFIRMED file
  plus README.md and SHA256SUMS to the current tag, removing any lead or blob file still there
  (owner, 2026-11-19: the release holds confirmed files only; lead and blob files stay in
  `--out`, the manifest has no link for them; `--refresh` rewrites README/sums/manifest without
  rebuilding); the default `--out`, `/home/tobi/earthpv_data/pv_new_leads_2026-11-02`, must
  hold every country's files.
  `scripts/patch_atlas_leads.py` links them on `results/<aoi>_pv_evidence_atlas.html`; commit
  `configs/atlas_leads.json` (manifest, read by `atlas.leads_release`) with the page. `SOURCES`
  needs an entry only for a non-default run or OSM pull; France's entry names its audited
  `france-osm-leads-2026-10-22` release instead (no confirmed file, so no leads card). Germany's leads are held to the candidates of
  its checked 2026-11-01 files (`keep_ids_from`, copies in `data/leads_reference/`), since the
  pre-cap OSM file its reference also named is gone. **Blobs** (leads above 100,000 m²) go to their
  own `<aoi>_pv_blob_leads.geojson`, largest first (`release_leads.split_blobs`). **Review
  verdicts sort the files** (`release_leads.review_table`, the calibration table's
  `oversize_review`/`lead_review` blocks, shared with `release_polygons`): an outline judged
  `pv` that OSM still lacks goes to `<aoi>_pv_confirmed_leads.geojson` (largest first, written
  only when non-empty, exempt from every lead screen), one judged not PV is in no file, unsure
  ones stay marked `review_verdict`. Manifest keys `confirmed` (with `mapped_since`) and
  `judged_not_pv`. **The atlas offers mappers only the confirmed file (owner, 2026-11-19)**:
  `atlas.leads_for_page` keeps the lead and blob files' counts in `totals.leads` (the quality
  checklist reads them) but never their links, and a country with no confirmed file shows no
  leads card. The Downloads heading reads "Download the raw data and new OpenStreetMap hints
  behind this atlas": the polygon file is the raw data, the confirmed leads the hints.
- **Polygons**: `scripts/release_polygons.py --aoi <aoi> --upload` (after `leads`) writes
  `<aoi>_pv_polygons.parquet` (model outlines inside the page's regions, any size, with
  `osm_within_100m` and any `review_verdict`, plus the atlas's own `--osm-solar` rows and CSP
  plants; GeoParquet 1.1, zstd, Hilbert order) to release `pv-polygons-2026-11-11` (default
  `--out` `/home/tobi/earthpv_data/pv_polygons_2026-11-11`, must hold every country's file);
  `configs/atlas_polygons.json` feeds `atlas.polygons_release`; `scripts/patch_atlas_polygons.py`
  adds the card. The OSM rows come from `evidence_atlas_inputs.json`, else `ATLAS_OSM_SOLAR`,
  else the national file. An outline invalid as mapped in OSM is kept as is, never repaired.
- **Lead screens** (one rule per screen, used by `release_leads.py` and `earthpv export`'s
  new-leads file): `export.steep_rule` drops a lead under `STEEP_MAX_AREA_M2` (1,000 m²) whose
  GLO-90 slope exceeds `STEEP_SLOPE_DEG` (15°) and any lead above `STEEP_CAP_DEG` (30°), and keeps
  a larger one flagged `steep_review` for a human (shaded slopes, cliff edges and gullies read
  like panels; slope from whole cached DEM tiles in `data/dem` -> /home).
  `export.low_confidence_rule` drops a `no_building` lead whose PEAK `confidence` is below
  `LOWCONF_MAX_CONFIDENCE` (0.9); `ground_adjacent` is spared. **The surface-water screen is per
  country** (`lead_water_screen: true` in configs/aoi.yaml: Pakistan, Egypt, Namibia;
  `export --water-screen/--no-water-screen`; `surface_water.py`, JRC Global Surface Water, cache
  `data/jrc_gsw` -> /home): drops non-rooftop leads >= 25% ever wet. Never India or Vietnam
  (salt-marsh, floating and pond PV). `planetary_computer.sign` 404s for this dataset; the module
  signs with the collection token, which lives ~15 min. No screen removes a `steep_review` lead.

**`scripts/retemplate_atlas.py` moves published pages onto a new template without rebuilding
them**: it recovers each placeholder's value by aligning the page with the template it was built
from (`--old-template <git rev>`, default HEAD), proves the split by substituting back, then
fills the current template (only `__LAYERS_JSON__`, `__SMALL_ROOF_JSON__` and `__AOI_KEY__` are
computed fresh). **After
a template commit, pass the revision the pages were last built from**, not HEAD (a page
restored from before 2026-11-13 was built on b1d03e0 plus ad064f7's template diff). `--new-template`
fills a template other than the working tree's; `--refresh-prose REV` rewrites the confidence and
composition prose from each page's data block where `atlas.py` at REV reproduces the existing
prose; `--old-config DIR` checks a page against the country config it was built from when that
config has changed since. **It recomputes the quality checklist from the tree it runs in**: in a
clean worktree the records under `data/` and untracked `results/` are missing and checks fall
to "Not yet", so link `data`, copy the records, or put each page's published `#quality` section
back for a template-only change. Single-purpose patchers (`scripts/patch_atlas_*.py`: leads, polygons, sizes, references,
generation, coverage, view, pose, potential, drop_sppi) change one section of a published page
without a rebuild.

**Re-template the SYNC SOURCES too, not only `docs/assets/interactive/`.** Most published
atlases are copies `build_docs_figures.sync_interactive` makes from
`results/<aoi>_pv_evidence_atlas.html` (Germany from `data/predictions/germany/density/`); a
local `pixi run docs-figures` copies those over the committed pages and would revert them.
Expect `docs-figures` to rewrite ~50 SVGs whose only change is matplotlib's timestamp and random
ids: revert those, keep only real content changes.

**`scripts/screenshot_pages.py` drives Firefox over WebDriver BiDi** (`--screenshot` fires at the
load event and captures an empty WebGL map); a Shot can name a `ready` expression, and the atlas
sets `data-atlas-ready` on `<html>` once its map has drawn. Atlas iframes on the docs site carry
`allow="fullscreen"` and `local-network-access; loopback-network` (`build_atlas_pages.py`) and
are **sized to the whole atlas, not the viewport (owner)**: `.page-full-bleed.fit` makes
`embed-theme.js` fit the frame to its `<body>`, so that script also redoes in-page links and the
tooltip's flip test against the site page and its sticky header.

**Calibration areas open in JOSM or iD from the atlas** (Remote Control `import` as a locked
`upload_policy=never` layer, then `load_and_zoom` with the protocol's changeset comment and
`#tracethesun;#earthpv;#earthpv-calibration`; iD via `#gpx=<url>.geojson`), and a **Propose**
control drops a 2 km square matching `new_calibration_quadrat.geodesic_square`. Boundaries come
from `pixi run calib-publish` (`scripts/publish_calibration_areas.py`) into
`docs/assets/labels/calibration_areas/<aoi>.geojson` plus one file per area; the page fetches the
index at run time. **Re-run it whenever a quadrat or candidate is added or `calibration_boxes`
changes**; `check_atlas_templates.py` fails CI on a configured box without a published file.

**Calibration candidates are sampled, not hand-picked:** `pixi run calib-candidates -- --aoi
<aoi>` (`scripts/propose_calibration_candidates.py`) cuts the density grid into 8 bands of equal
building share and draws one building-weighted candidate per band (seed from the AOI name, 20 km
spacing, one province each while possible), placed on VIDA footprints (1 km boxes above 600
bldg/km², 2 km otherwise), behind an **imagery gate** (the oldest Esri capture at centre and
corners no more than 12 months before `compose_window` start). Output in
`data/labels/<aoi>/candidate_quadrats/`, failures in `screened_out.csv`; `--replace` redraws only
sampled candidates; then run `calib-publish`. Other modes: `--bronze --priority` (two purposive
start-here boxes), `--pv-rich --score-dir` (town windows with the most top-5% roofclf roofs from
a model that has not seen the AOI; review each in `pv_rich_review.csv` before
`--pv-rich-confirmed-only`), `--false-alarm`, `--towns` (random town boxes), `--bright`
(bright-roof boxes from `scripts/roofclf_bright_screen.py`), `--farmland` (cropland-stratified
3 km farm boxes), `--exclude-box W,S,E,N`. Pakistan has no `compose_window` or `division.iso3`,
so the sampler takes `--window-start 2025-11-01` there. Whether purposive boxes (PV-rich,
false-alarm, bright) enter a coverage ratio is an owner decision. **Stars**: `calib-publish` stars
the first candidate on every atlas whose own page reports roofclf or groundclf as not measured
(farm boxes first where only farm ground PV is unmeasured); `start_here: <stem>` in the country
config picks the star, `start_here: none` stars nothing.

**The community guide is the "Contribute" nav section** (`docs/contribute/`; `index.md`
keeps the `/contribute/` URL that popups, badges and README link to). `index.md` is the
flywheel overview: the stage-by-stage figure (`build_docs_figures.write_flywheel_stages_diagram`,
`mapping_flywheel_stages.svg`, same six station numbers as `osm_ai_flywheel.svg`, station 3
"Check the leads" = review page then editor), one section per stage and the quality-level
summary; the calibration-area how-to is `calibration-areas.md` (the atlas popup's link since
2026-11-19; older pages still land on the overview) and local datasets `local-data.md`. Nav
follows the stages. Mappers report through
`.github/ISSUE_TEMPLATE/calibration-area.yml` (the popup's "Report progress" link prefills it);
country requests and claims through `new-country.yml` (label `new-country`), prefilled from the
globe by `new-atlas.js`. A screenshot still to be taken is a `<div class="shot-needed" markdown>`
placeholder naming the target file. `new_calibration_quadrat.py --aoi <aoi>` registers outside
Pakistan into `data/labels/<aoi>/`; Pakistan stays flat in `data/labels/`.

### Combined atlases (`earthpv combine-atlas`)

`earthpv combine-atlas --config configs/combined/<name>.yaml` (`combine.py`, page
`combine_page.py`) sums several countries' evidence atlases on the global grid into
`data/combined/<name>/`. Per member: (1) **control**: `build_evidence_atlas(cells_only=True)` on
its own density run must reproduce its published Verified/Best (`CONTROL_TOL_MWP`) or the member
is refused; (2) **global grid**: `density`'s candidate figure is recomputed on the lattice from
`density.priced_candidates`, OSM and roofclf rows join by position; an off-lattice member's
roofclf half must be split per global cell (Germany: `.../germany/density_gcell/`); (3)
**partition**: detections and OSM count only inside the member's border
(`build_evidence_atlas(partition=...)`), whereas a country's own page keeps border cells whole;
(4) **joint interval**: kWp draws share one seed across members, each member's own terms get a
member seed or permutation (`_evidence_uncertainty(perm_seed=)`); the country pages draw
segmentation's kWp independently of OSM's and so understate that correlation (not changed). The
per-cell floor is
grid-dependent, so a member's combined Best differs slightly from its page's. A Europe preview
(Germany, France, Poland, Turkey) exists, unpublished and uncommitted.

`density` writes `gcell` on an on-lattice grid, `candidate_estimates.parquet` (every priced
detection; `candidate_row` counts density's cap-filtered frame, not candidates.parquet, so join
on the point) and `grid_origin`/`grid_on_global_lattice`/`n_candidates_outside_border`/
`est_mwp_rc_outside_border` in `meta.json`; `earthpv atlas` writes
`<density_dir>/evidence_atlas_inputs.json`, which `combine.member_inputs` reads. A test build with
`--out` elsewhere overwrites that record too.

### Plausibility gate (`plausibility.py`, `earthpv check-density`)

The atlas has no human on each candidate, so a false-positive mode that survives `p_real`
reaches the headline silently. Two per-region checks from artifacts `density` wrote: the
**ground-mount:rooftop capacity ratio** (bare ground, riverbed, salt flat, rock and snow read
bright) and **single-cell concentration** (one 0.1° cell over 25% of a region); both need
`mwp_ground >= 50`. `RATIO_CHECK_EXEMPT_REGIONS` exempts Gilgit-Baltistan from the ratio check.
In segmentation-only countries the ratio check also fires on a *missing rooftop denominator*,
which is stated on publication, not waived. Exit 1 = a region failed, 2 = `density` has not run.
**Run it between `density` and publishing** -- docs CI cannot, since `data/` is gitignored.

### Invariants that prevent tiling artifacts (do not regress)

Naive sliding-window inference produced a regular grid of false positives. Two fixes must stay:
- **Positive chips are jittered** (`chips.py::sample_chip_centers`, ±900 m) so the array is
  *not* centered in the frame. Without jitter the model learns a center bias and fires once per
  window at inference → a grid at the stride spacing. Diagnostic: nearest-neighbor distance
  between detections spikes at the window stride.
- **`infer.py` overlap-adds windows with a 2D Hann taper** into one seamless raster per cell,
  with a **stride that is not a multiple of the 16 px ViT patch size** (currently 104) so
  patch-edge effects decorrelate between neighbors.

### Documentation site

`mkdocs.yml` + `docs/` build the MkDocs Material site published to GitHub Pages by
`.github/workflows/docs.yml` on every push to `main`. **Every figure and embedded interactive
page under `docs/assets/` is generated** by `scripts/build_docs_figures.py` (`pixi run
docs-figures`) from tracked files (`results/*.csv`, the atlas HTML's embedded JSON, calibration
YAML): edit the sources, not the SVGs. Preview: `pixi run docs-figures && pixi run -e docs
docs-serve`. The build runs `--strict`. Docs prose avoids em dashes and emoji.

**`mkdocs build --strict` does NOT validate URLs inside raw HTML.** A raw relative URL needs one
`../` per path segment of the page's own served URL (`index.md` excepted).
`scripts/check_docs_links.py` checks them and runs in the docs workflow ahead of the build.

**The site root is the Electrify Earth globe**, generated with `docs/assets/landing/earth.json`
by `scripts/build_landing_page.py` (called by `build_atlas_pages.py`): **never edit
`docs/index.md` by hand**; the written introduction is `docs/overview.md`.
`docs/overrides/landing.html` is a standalone template drawn by `docs/assets/landing/landing.js`:
countries with an atlas inked, their 0.1° cells as a raster, a brush stroke whose sweep is the
atlases' summed Best over the world total in `configs/external/global_pv_capacity.yaml` (update
it at each IEA PVPS Snapshot), a hover card with tier medal, Best and a four-bar size chart (an
unmeasured first bar fades and reads "at least"). A click on a country without an atlas opens
`docs/contribute/new-atlas.md` with `?country=&iso3=&bbox=`. Rules: **nothing on the globe may be
a texture fixed to the screen (owner)**, even the hatching is geometry; **Crimea is Ukraine's
(owner)**: `build_base_map` moves Natural Earth's polygon into Ukraine (`TRANSFERS`), so check
any new base map; a simplified ring must keep its winding or d3 fills the rest of the sphere.
`world.json` (Natural Earth 1:50m) is rebuilt only with `--base-map`; US states and Chinese
provinces (`regions.json`, rebuilt with `--admin1`) are picked one by one, a state's `d` being
its geoBoundaries name, which `compose._aoi_boundary` matches. VIDA barely reaches China. The
globe follows the site's light/dark choice; every colour that differs by theme is in `THEMES`
in landing.js (stars from `stars.json`, rebuilt with `--stars bsc5.dat`).
**Every page's social card (`og:image`) is this globe**: `pixi run docs-screenshots
social-preview` serves the built site, renders its root at 1200x630 without buttons or
legend into `docs/assets/figures/social-preview.png` and writes the PNG's hash to
`docs/overrides/partials/social-image-version.html` (the templates' `?v=`, so social sites
refetch). Its figures are fixed in the PNG: **re-run it whenever an atlas is added or a Best
changes.**

**The site opens dark whatever the system's theme (owner, 2026-11-18)**: `mkdocs.yml` lists the dark
palette first with no `media` (landing.html writes the same order, dark 0, light 1), and
`docs/overrides/partials/palette-default.html` forgets a palette Material stored under the old
`(prefers-color-scheme: ...)` entries, once. `embed-theme.js` syncs the PV Atlas frames
(`.page-full-bleed`) as well as `.embed` ones. Standalone result pages opened outside the site still
follow the system.

**The PV Atlas pages are generated** (`scripts/build_atlas_pages.py`, one row per country in
`ATLASES`; **never edit `docs/atlas*.md` by hand**). Each page's tier (Gold/Silver/Bronze) is read
from the calibration badge its own atlas carries (`atlas.VALIDATION_TIERS`); Silver/Bronze pages
open with a closable banner (`WARNING`, `TIER_NOTE` or `LEADS_WARNING`, plus `CTA`;
`docs/assets/javascripts/atlas-banner.js`). Tier rules:
- A judgement tier goes in `configs/atlas/<aoi>.yaml` (`validation: {score, note}`, which beats
  `derive_validation_score` and is read by all three atlas builders and
  `apply_validation_badges.py`), with a country note in `build_atlas_pages.TIER_NOTE`.
- **Gold and Silver also need the leads mapped in OSM to localize the model (owner)**: a
  verdict on at least `atlas.LEAD_SHARE_MIN` (a third) of a lead file's leads of 1 ha and up
  (`atlas.LEAD_RULE_MIN_M2`) and of its blobs, i.e. of the two review pages' outlines (owner,
  2026-11-19; smaller leads reach no page and no mapper; earlier declarations counted every
  lead and stand), and the localized model retrained on the OSM pull holding that mapping, declared as
  `validation.retrained_on_leads: {leads, share, blobs_share, model, by, date, note}`
  (`atlas.leads_retrained`). Declared without `model`, the page stays Bronze with "Leads
  checked; the model is not yet retrained on them" (`atlas.LEAD_RULE_SUB`). Without it
  `resolve_validation_badge` shows Bronze whatever the tier earned (keeping it as
  `data-earned`) and the page gets the leads banner; `atlas.lead_rule_gaps` names the gaps.
- **Gold also needs roofclf checked by people (owner)**: random validation and point-data
  inspection (`scripts/export_roofclf_points.py`) on the scoring behind the page.
- **Gold also needs solar glint measured on the large installations (owner, 2026-11-19)**:
  a glint survey read >= `atlas.GLINT_MIN_CLEAR` (10) clear scenes over a census or random
  draw of the installations >= 1 ha mapped in OSM (`atlas.glint_required`: a third, >= 100 or
  all, 1,000 suffice); declared as `validation.glint_survey`, numbers from
  `scripts/glint_coverage.py`. A declared Gold without it shows Silver (`atlas.glint_surveyed`,
  `shown_validation_score`; `build_atlas_pages.GLINT_WARNING`). A fitted pose is not
  required. France, India and Pakistan's surveys meet it; none is declared yet.
  `derive_validation_score` stops at Silver, so Gold is only ever declared. **No atlas is Gold;
  Pakistan is Silver.** `derive_validation_score` gives Silver to any AOI with a registered area
  in `data/labels/<aoi>/`, `used: false` or not (India is pinned Bronze for that reason).
- `docs/atlas-quality-levels.md` is generated (`quality_page`).

**Every evidence atlas shows an import ceiling** (Chinese panel exports to the country from Jan
2017 to the end of the imagery window, Ember customs data, CC-BY-4.0):
`scripts/ember_import_ceiling.py --csv <Ember monthly CSV>` writes
`configs/external/ember_china_panel_imports.yaml`; `atlas.import_ceiling(aoi)` puts it in
`totals.import_ceiling`. Countries with domestic manufacturing or other routes are flagged
`ceiling: false` and the page says why. It is context, never a judge of an estimate.

Nav runs **Results → How it works → Setup → Experiments**. `docs/open-questions.md` is
**excluded from the published site** (`exclude_docs`), so no site page may link to it; an item is
removed once closed and moves to the register with a verdict. Every doc under `docs/issues/`
carries a dated status banner. The site chrome (`docs/assets/stylesheets/extra.css`) shares its
`--pv-*` tokens with the embedded result pages; keep both in sync by eye.
`docs/assets/javascripts/embed-theme.js` drives each embedded page's theme from Material's toggle.
`pixi run docs-screenshots` needs a real (snap) Firefox profile staged under
`~/earthpv-screenshots/` (not `/tmp` or the external drive) and pins `ui.systemUsesDarkTheme` and
`ui.prefersReducedMotion`.

**The "night lights" HTML style (dark glowing choropleth, KPI strip, tab switcher, `<details
class="xdetails">` methodology sections) is the default for any new results page.** Reference:
`src/earthpv/templates/pv_evidence_atlas.html`; a standalone script slices the shared CSS via
matched string markers (`build_pakistan_pv_evidence_overview.py`'s `_slice`/`_shared_fragments`)
rather than forking it. Static figures are only for the docs site's `<img>`s and print.

### Calibration quadrats

**45 Pakistani quadrats are registered; 41 are in the roofclf fit, 19 in its coverage ratio**
(pinned, owner). Purposive selections (industrial estates, dense residential blocks), rural
extensions that set the density domain, then sampled boxes. All but Jhang f2 (`corroborated`,
poor imagery) are declared **Rule-1 complete** by the owner (every visible panel mapped). Box
21's three random boxes (Gujranwala s8, Qilla Abdullah s6, Sanghar s2) stay out of both fits as a
test of the level; whether Kalat Rural, Kasur and Sahiwal f6 may set the price is open question
21 (their household PV is mostly farm-yard ground arrays the parcel label hands to roofs).
History: `docs/issues/pakistan-calibration-boxes.md`; per-quadrat table:
`docs/methods/calibration-quadrats.md`.

- **Rule-1 is epoch-relative**: it certifies completeness against the mapping imagery's own
  capture date, so the newest installations are missed. Precision and `base_rate` are **lower
  bounds**, `rate_ratio` an **upper bound**; recall over mapped installations is unaffected.
- **Every area feeds both detectors (owner)**: mappers map every installation, ground and
  rooftop, in building and farm areas alike. `roofclf.discover_quadrats` returns both kinds
  (`farm=True`/`False` selects one); fits name their quadrats with explicit `--quadrat` flags.
- `roofclf.roof_pv_area` ignores a ground-placed installation of 400 m² or more unless at least
  half of it lies on footprints (`GROUND_GUARD_MIN_ON_ROOF`): industrial areas are mapped as
  untagged `power=plant` roof outlines, which the guard would otherwise strip.
- **Ranking transfers across quadrats; absolute adoption rates do not** (`rate_ratio` spans
  0.2-5x), hence the stratified coverage ratio. `select_calibrated_quadrats` picks the
  precision-trusted subset (`rate_ratio` roughly in [0.5, 2.0]) independently of Rule-1 status
  and of the density domain; check both gates for any new quadrat.
- `scripts/new_calibration_quadrat.py` adds one (geodesic square or `--geojson`), checks overlap
  with every existing quadrat, and cross-confirms a live Overpass pull against a second query
  (mirrors have returned truncated, non-error responses).
- Capacity commands read each quadrat's building density from a profile table,
  `sub400_capacity.quadrat_profile_for(aoi)`: `results/calibration_quadrats.csv` for Pakistan,
  `results/<aoi>_calibration_quadrats.csv` otherwise (`scripts/build_calibration_quadrats_csv.py
  --labels-dir data/labels/<aoi> --out ...`), or `--quadrat-profile`.

### Farm ground PV: `groundclf` and farm calibration areas

A footprint-free pixel detector for small arrays beside fields (solar pumps), which neither
detector above sees (`src/earthpv/groundclf.py`, `docs/methods/groundclf.md`; models tagged with
the old name `roofclf_ground` still load, `LEGACY_DETECTORS`):

```bash
pixi run calib-candidates -- --aoi <aoi> --farmland          # cropland-stratified 3 km boxes
earthpv groundclf --aoi <aoi> --clean-region <b.geojson> --weak-region <b.geojson>
earthpv groundclf-score-national --aoi <aoi>             # blobs per cell, resumable
earthpv groundclf-capacity --aoi <aoi> --osm-solar <national OSM pull>
```

- **Atlas field**: `earthpv atlas --ground-cells <ground_cells.parquet>` adds `small_ground`
  (farm ground PV < 400 m²) to Best in the detector's domain only, in green; without it the page
  says "not measured". Run `groundclf-capacity` with the SAME `--osm-solar` file the atlas
  counts, and `--roofclf-buildings` where a roofclf half exists (a blob within 20 m of a priced
  building is its yard array).
- **A calibration domain per region** (`groundclf.domain_cells`): a cell is priced with a
  region's ratio only if its cropland share, building density AND median elevation (Copernicus
  DEM, cached in `data/cells_cache/<aoi>_elevation.parquet`) each lie within x/÷1.25 of that
  region's areas; a region is the areas sharing the `region` boundary property; a region with
  no detected area prices nothing. Regrouping changes the fit's random draws: retrain, never
  patch `calibration.csv`. The headline is `est_mwp_in_domain`. Interval: `region_ratio_draws`
  bootstraps each region from `BOOT_MIN_AREAS` (3) areas, else a stated x/÷2 (`JUDGEMENT_CI90`).
- **Farm quadrats carry `_farm_calib_` in their stem** (`roofclf.FARM_QUADRAT_INFIX`;
  `new_calibration_quadrat.py --farm`) and are the clean areas; building quadrats join as kind
  `train` (pixels in the fit, not the threshold, ratio or domain). Blobs inside any registered
  area count nothing (`--labels-dir`). A farm area not declared `rule1` trains only.
- **A mapped polygon is priced by its tag** (`groundclf.panel_area_factor`): `power=generator` is
  the array; `power=plant` counts 0.05/0.18 of its area, or 0 when a generator inside carries its
  panels; nodes count 0. **`osm_panel_tracers`** in `configs/aoi.yaml` names mappers whose
  polygons are panel traces whatever the tag (`labels.panel_traced`, matched on last editor); the
  evidence atlas prices those ground polygons at the MODULE constant.
- Clean areas give precision, threshold and capacity ratio; weak areas (`--weak-region`) train
  only, as multiple-instance bags. **Thresholds are logits** (a balanced fit saturates at p = 1.0
  in float32). The capacity estimand defaults to arrays below 400 m² (`--max-array-m2`).
- **Vetoes**: >= 30% of a blob within 8 m of a paved OSM road; SWIR more than 20% below the
  blob's ring (water-harvesting ponds); no pixel within 50 m of a building, cropland or green
  pixel; a blob over 25,000 m² (`MAX_BLOB_M2`); GLO-90 slope over 12° (`SLOPE_VETO_DEG`).
- **Overpass is a cached dependency**: area labels in `data/groundclf/<aoi>/areas/`, paved roads
  per 1° chunk in `data/roads/<aoi>/`; national scoring never calls it. A chunk that cannot be
  fetched leaves its blobs `road_checked=False`, reported in the summary.
- **Only Yemen has a farm figure** (seven areas, 171.0 MWp in 34 cells, no slope veto; the rest
  of Tihama is a training-only weak region, `data/labels/yemen/tihama_stale_imagery_region.geojson`).
  The seven sampled 3 km farm boxes are mapped but `used: false`: the fourteen-area refits of
  2026-10-25 that use them, with the slope veto, are unpublished (docs/results/yemen.md).
  Pakistan's farm fit (object precision 2-5%, ~0 recall on Jhang f5 and Swabi) is not scored,
  so Pakistan's farm ground PV stays "not measured". Farm candidates exist for Yemen, Egypt,
  Morocco, India, Pakistan and South Africa.

### Glint

Sentinel-2's specular glint is a secondary, corroborating signal, not a standalone detector
(`docs/methods/glint.md`):
- **Direct per-target detection boosts (never demotes) `rank_score`**: detection rate rises from
  ~6% to ~73% with installation size; validation plateaus around 26-31% for arrays ≥ 1,000 m².
- **Per-pixel SCL cloud masking** (`glint._read_target_scl`) is gated on the annulus, not the
  target (a real glint is often saturated-bright, which SCL also flags as cloud).
- **Tile copies count once and asset URLs are re-signed per read**: overlapping MGRS tiles
  deliver one pass as 2-4 items (`annotate_spikes` collapses them via
  `one_row_per_acquisition`; `dedupe_items=True` avoids fetching them), and
  `glint._asset_href` re-signs Planetary Computer URLs at open (a cached 45-min token silently
  dropped scenes in long pulls).
- **Opportunity-normalized sensitivity** (`glint_opportunity.py`): the capacity calibration
  models `k ~ Poisson(q_b * opportunity)` instead of dividing by a flat per-bin sensitivity.
- **Panel-pose surveys** (`scripts/glint_pose_survey.py`, `pose.py`) sit on the Pakistan, France
  and India atlases; large installations are read in parts (`pose_parts.py`, `parts-pull`/
  `parts-analyze`: 100 m cells grouped into orientations). Every pose point carries OSM id,
  coordinates, admin-1 and cached OSM `name`/`operator`. `scripts/patch_atlas_pose.py` replaces
  only a page's pose section.

### MaStR validation (Germany)

`mastr_validation.py` / `earthpv validate-mastr` checks against a legally complete register.
**65.5% of German rooftop capacity sits below the 400 m² / 72 kWp floor**, and that share is
**not transferable as a flat constant** (0.25-1.00 across municipalities; France brackets its own
at 17-31%). Read the **above-floor** block of the comparison (truth = `kw_rooftop - kw_le_72`).
German OSM (~3.6% of registered rooftop units) cannot serve as a completeness reference.

- **The register as a precision instrument** (`scripts/mastr_p_unmapped.py`,
  `calibrate-candidates --mastr-p-unmapped`): MaStR geolocates units only at/above 30 kWp, so a
  registered point inside an unmapped candidate is evidence it is real, for exactly
  segmentation's population. `derive_placement_tables` takes it via opt-in
  `p_unmapped_by_placement`. **The chance term must be land-use matched** (base rate among
  undetected buildings, same cells, same size bin); correction `(obs - f) / (1 - f)`, a lower
  bound. `>50k m²` and all ground keep the displaced-polygon control.
- **OSM rooftop polygons convert at a size-dependent constant in Germany**
  (`capacity_calibration.osm_rooftop_kwp_per_m2`: 0.200 / 0.189 / 0.139 / 0.051 kWp/m² for <200 /
  200-500 / 500-2k / >2k m², because German OSM outlines roofs and sites); every other AOI gets
  the flat 0.18. Only `build_evidence_atlas` uses it; `_size_distribution_data` keeps the flat
  constant deliberately.
- **Germany's sub-400 half is register-calibrated.** roofclf calibration is one constant, kWp per
  credited m², fitted against MaStR across fully covered Gemeinden (`vg250_gem.parquet`, AGS):
  0.2793 kWp/m² (`scripts/run_germany_roofclf_production.py`,
  `scripts/calibrate_germany_capacity.py`, `scripts/validate_sub400_against_mastr.py`;
  production fit `data/roofclf_germany_prod/`). **But the published half is
  `scripts/build_germany_sub400_atlas_inputs.py --method size_band --kwp-per-m2 0.03493
  --min-roof-m2 200 --max-roof-m2 400`** (roof area at a register-fitted constant, no classifier;
  `scripts/germany_sub400_topup.sh`), not the builder's roofclf default; `small_rooftop:
  {method: roof_area}` in its atlas config makes the page say so. The component must be
  **INCREMENTAL** (sub-400 roofs only, deduped against OSM and segmentation) and
  **pre-aggregated to one row per cell** (25M geometries OOM `atlas._join_buildings_to_grid_cells`).
  Where PV is near-ubiquitous capacity is close to proportional to roof area, so in Germany the
  roof-area baseline beats roofclf. **A national total agreeing with a register is not evidence
  the geography is right**: errors cancel, and PyPSA consumes the per-cell geography. Germany's
  Best exceeds its register (~74,800 MWp); the page says to read the tiers as geography.

### France validation (ODRE register + OpenPVMapper)

`france_validation.py` / `earthpv validate-france`. The register **censors units below 36 kW
into per-commune/IRIS aggregates, publishes no coordinates and has no rooftop/ground field**, so
shares are bracketed, never stated, and there is no `p_unmapped` instrument. Its **dated
year-end vintages** are read back to a quadrat's mapping day by `interpolate_to_date`. Against 14
hand-mapped communes it measures the module constant at **0.150 kWp/m²** (not acted on).
Write-ups: `docs/methods/france-validation.md`, `docs/results/france.md`.

- **`tag` on the French labels is load-bearing**: `thermal` (solar hot water) and `false` are
  dropped; `unknown`/`missing` go to `data/labels/france_sensitivity/`.
- **France quadrats live in `data/labels/france/`, NOT `data/labels/`** (where they would join
  the next Pakistani refit); pass `--labels-dir`. **Saint-Gely-du-Fesc is unfinished** and
  excluded from every fit by explicit `--quadrat` flags; Langoat and Saulny are excluded from the
  module-constant fit (register hole). Commune-sized quadrats: France runs `roof-classifier`
  **without `--seg-prob-dir`** (`building_table` reads seg probability from one 0.1° cell).
- **roofclf does not transfer to French residential PV** (median array 20 m² against a 100 m²
  pixel). Whether roofclf can work is a property of national subsidy design (array size) and
  cannot be inferred from a neighbour.
- **OpenPVMapper** (Kasmi 2026, `doi:10.5281/zenodo.21534856`, CC-BY-4.0) is a model output:
  agreement with it is not validation.
- **Register CSV exports truncate silently on an SSL reset**: `scripts/fetch_odre_vintages.sh`
  re-fetches until the line count is plausible and `load_vintages` refuses a vintage under 1 GWp.
- **Run**: `grid_origin: [-5.15, 41.33]`, `compose_window: ["2024-05-01", "2024-09-30"]`;
  checkpoint `data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt`; the precision
  table is fitted with `--recall-reference none`, so France's figures are a **precision floor,
  not recall-corrected**: quote `est_mwp_det`/`est_mwp_exp`, never `est_mwp_cal` or
  `est_mwp_rc_roof`, in register comparisons. `check-density` fails 9 of 13 regions on the
  ratio (missing rooftop denominator). The v5 register comparison is
  `results/france_validation_v5/` (`results/france_validation/` is a v4 run); `validate-france
  --pred-dir` takes `data/predictions_v5`, not `data/predictions_v5/france` (the wrong one
  silently skips the floor-recall block).

### Country runs

Owner rules for every new country: **localize** segmentation on the country's own OSM labels,
ship whichever checkpoint scores better on a held-out region (tie goes to local;
`compare_local_vs_v5.py` scores both at the same pixel precision), >= 1,000 buildings per cell
plus label cells, end in an evidence atlas, publish by push to main. Holdouts are picked from
the label map before training by `scripts/pick_val_region.py` and written into
`configs/aoi.yaml`.

Machinery: `earthpv-country-queue` (`scripts/run_country_queue.sh`; status `bash
scripts/country_queue_status.sh`; markers `data/country_queue_markers/`; log
`data/country_monitor.log`) and the earlier `earthpv-vn-in-queue` (`scripts/run_vn_in_queue.sh`,
`data/vn_in_monitor.log`) pull labels, run the thermal filter and compose, then hand each country
to `scripts/run_country_compute.sh <aoi>` (chips -> `mark_val_buffer.py` -> merge -> train ->
`pick_best_checkpoint.py` or, with `snapshots:`, `pick_checkpoint_by_recall.py` ->
`compare_local_vs_v5.py` -> infer -> postprocess -> thermal -> export -> blob and large review
pages -> ground screen -> calibrate -> density -> check-density -> osm_solar -> csp -> atlas ->
leads -> polygons, behind markers in `data/<aoi>_pipeline_markers/`).
- **The queue decides an atlas is finished by grepping `data/<aoi>_pipeline.log` for "ATLAS
  DONE"**, so removing `<aoi>_atlas_done` does not relaunch a finished country: re-run its steps
  as a one-off unit.
- **Editing a script a unit is running is unsafe** (bash reads incrementally): restart the unit.
- Before stopping a compose unit by hand, `rm data/vn_in_queue_markers/<aoi>_round_start`; stop
  the QUEUE first when removing compute markers.
- Disk guards: `DISK_MIN_HOME_GB` (default 5 on `/`, the system disk, since
  2026-11-22 (owner; was 120), overridable by environment) and
  `DISK_MIN_MORE_GB` (default 15) on `/run/media/tobi/moreaidata`, where Mexico, Chile and
  Australia (and Texas's composites) keep their data.
- A `COUNTRIES` row's sixth field names a country whose compose must finish before this one's
  starts (`chile|...|CHL|10x20||mexico`); its labels may pull earlier.
- **A country can be given the GPU first**: `scripts/gpu_priority.py --aoi <aoi> [--now]` (unit
  `earthpv-gpu-priority-<aoi>`) SIGSTOPs every other process WAITING on `data/.gpu.lock` and
  holds the lock between the country's GPU steps until its `infer` marker; a running job is never
  touched. Killed hard, it leaves waiters stopped: `pkill -CONT -x flock`.

Published atlases (each page's `totals` match these; queue counts for the reviews come from
`pixi run blob-review status` / `large-review status`):

| Country | Checkpoint | Verified / Best (MWp) | Notes |
| --- | --- | --- | --- |
| Pakistan | `v16_combined_pakistan` | 3,637.5 / 34,468.6 | roofclf half; Silver |
| Germany | `v4_combined_all` ep 41 | 26,635 / 86,009.9 | register-calibrated sub-400 half; earns Silver, shows Bronze until retrained on its checked leads |
| France | `v5_combined_france` | 12,381.7 / 13,447.1 | precision floor, no roofclf; shows Bronze (leads unchecked) |
| India | `v5_combined_france` | 70,266.0 / 102,779.7 | `ring_cells: 3`; pinned Bronze |
| Vietnam | `v9_combined_vietnam` | 8,179.8 / 9,118.9 | |
| Egypt | `v12_combined_egypt` | 3,315.1 / 3,848.7 | thin Cairo holdout |
| Yemen | `v25_combined_yemen` | 277.5 / 623.6 | farm ground PV; earns Silver, shows Bronze |
| South Africa | `v14_combined_south_africa` | 9,322.7 / 10,075.9 | |
| Morocco | `v11_combined_morocco` | 898.9 / 935.1 | AOI stops at 27.7N |
| Poland | `v15_combined_poland` | 6,604.1 / 9,110.2 | |
| Zambia | `v4_combined_all` ep 41 | 505.8 / 531.7 | |
| Nigeria | `v45r_resnet50_nigeria` ep 11 at 0.3 | 128.7 / 164.8 | localized ResNet-50 and the 2026-11-14 pull since 2026-11-19 |
| Namibia | `v17_combined_namibia` | 464.3 / 512.3 | Cuvelai pans partly in Best |
| Turkey | `v19_combined_turkiye` ep 12 | 10,714.9 / 17,598.4 | dark open ground in Best |
| Spain | `v26_combined_spain` ep 21 | 39,379.3 / 41,776.7 | floor of 1 building per cell |
| Belgium | `v31_combined_belgium` ep 22 | 502.3 / 970.8 | published before owner review; calibration areas still owed |
| Portugal | `v30_combined_portugal` ep 19 | 5,830.5 / 6,193.6 | Azores and Madeira in |
| Netherlands | `v5_combined_france` ep 25 at 0.98 | 3,708.6 / 4,567.3 | v32 lost on recall; recall not corrected |
| Luxembourg | `v33_combined_luxembourg` ep 21 | 25.4 / 40.5 | 8.3 of the model's 21.3 MWp lies beyond the border |
| Italy | `v34_combined_italy` avg ep 21+29 at 0.7 | 12,175.7 / 19,972.6 | a map of the ground-mounted fleet |
| Denmark | `v37r_resnet50_denmark` ep 10 at 0.95 | 2,639.9 / 2,683.1 | localized ResNet-50 since 2026-11-19; thin Nordjylland holdout |
| Texas | `v39r_resnet50_texas` ep 18 at 0.3 | 45,712.0 / 51,488.0 | state AOI, counties as regions; localized ResNet-50 since 2026-11-20, OSM screen still v39's |
| California | `v38_combined_california` avg ep 32+40 at 0.95 | 27,118.1 / 32,198.9 | state AOI; small-scale PV unmeasured; ResNet v38r rejected (misses large parks) |
| Mexico | `v40r_resnet50_mexico` ep 10 at 0.3 | 12,084.9 / 12,358.4 | first iteration (2026-11-22), reviews open; thin Chihuahua holdout (21 installations) |
| Chile | `v44r_resnet50_chile` ep 15 at 0.3 | 13,613.7 / 13,901.9 | first iteration (2026-11-22), reviews open; Verified above IRENA's 12,032 MW |
| Australia | `v28_resnet50_south_africa` (general) at 0.2 | 16,596.1 / 16,818.4 | first iteration (2026-11-22), reviews open; local v46r lost on New South Wales (size split suspect); rooftops unmeasured |
| Indonesia | `v28_resnet50_south_africa` (general) at 0.98 | 821.9 / 989.5 | first iteration (2026-11-25), reviews open; local v48r lost on East Java; Cirata (floating) priced at the land constant |

Country points still in force (write-ups in `docs/results/<country>.md`):
- **India**: Verified is almost all ground perimeters; Best counts the parks above the cap that
  the owner judged solar (verdicts in `results/india_oversize_review/`), and Verified credits the
  seven outlines above 5 km² that fail the screen at their detected share (Khavda). The register
  is MNRE via MoSPI eSankhyiki (`scripts/validate_india_mnre.py`, fetched through MoSPI's MCP
  server; the REST API needs TLS legacy renegotiation). The `ring_cells: 3` Himalayan cells add
  ~220 MWp of false positives on shaded slopes and snow edges, stated on the page, no veto yet.
- **Yemen**: segmentation finds almost none of its labels, so Best is the OSM map plus farm
  ground PV. v25 runs from `data/predictions_v25/yemen` (`data/predictions/yemen` is v13's) with
  its own precision table. Its holdout is a farm area where every model is blind, so model
  decisions rest on `scripts/yemen_v25_national_recall.py` (every mapped array >= 400 m², matched
  pixel precision). roofclf is fitted but left off (owner).
- **Egypt**: the rooftop estimate is ~0. Many leads are swimming pools and wastewater-plant
  basins; `earthpv osm-hard-negatives` (`osm_negatives.py`, `--pbf` reads a Geofabrik extract
  when Overpass is overloaded) cut 1,120 chips into `data/chips/egypt_hard_neg` (-> /home), 175 of
  them in the Cairo holdout, so score the sets apart. v20, trained with them, cut pool leads but
  is not shipped (owner decision, open question 19).
- **Morocco**: geoBoundaries MAR includes Western Sahara, so `atlas.build_evidence_atlas` clips
  region outlines to the AOI bbox.
- **Namibia**: v17 reads the Cuvelai basin's seasonal pans (oshanas) as ground PV, priced
  through the >50k m² ground bin; no filter, the page says so. geoBoundaries NAM ADM2 names are
  shuffled (ADM1 is right; boxes are named by region), and Esri serves most of Namibia only to
  zoom 17.
- **Turkey**: open-ground false positives (lava and rock north of Lake Van, shaded eastern
  slopes, dark fields) are priced through ground bins with a high mapped share; no filter, the
  page says so. `check-density` fails 42 provinces.
- **Spain**: **VIDA has block-shaped holes**, city centres included, so `data/vida/ESP.parquet` is
  VIDA plus OSM buildings in empty 0.01° blocks (`scripts/fill_vida_from_osm.py`; raw at
  `/home/tobi/earthpv_data/ESP.parquet`); the Netherlands is filled the same way, other
  countries are unchecked. Plastic greenhouses are not read as PV though footprints trace them.
  REE is national only on the page.
- **Portugal**: geoBoundaries PRT ADM1 garbles 6 of 20 names (UTF-8 read as Latin-1);
  `density._repair_mojibake` fixes them on read. DGEG's NUTS II regions do not nest with the
  districts, so the page compares the national figure only.
- **Netherlands**: ships v5 at 0.98, the only threshold where v5 reaches v32's precision.
  Zoneiland (Almere) counts 0.5 MW as CSP from its tags, unchecked.
- **Luxembourg**: 23 of its 40 cells straddle the border and are kept whole; ILR publishes no
  canton figures.
- **Italy**: the model outlines almost no rooftops, so against GSE's regional totals the
  macro-regions rank backwards and against its ground-mounted shares they agree.
  geoBoundaries ITA ADM1 is ISTAT's five macro-regions; `official_capacity.py` sums GSE's 21
  regions into them.
- **Denmark**: solar heating fields look like parks: model outlines inside mapped thermal
  polygons are dropped, unmapped ones count as PV. `Høng solvarmeanlæg` is tagged
  `plant:output:electricity=yes` and counts 1.7 MW CSP, probably mis-tagged.
- **Texas / California**: compared with EIA (Electric Power Monthly and EIA-860M by county,
  `data/external/eia/`, `official_capacity.eia860m_state`, which matches county names case-blind)
  at about 1.27-1.29x panel over inverter. Both review pages judged (owner, 2026-11-18): an
  EIA plant within 500 m predicts a park verdict (Texas 19 of 21 blobs, California 28 of 29),
  and Texas's roof leads are mostly not PV (37 of 180 solar; 95 of the rest bright roofs).
  Texas moved to its ResNet run (2026-11-20, `data/predictions_resnet_20261119/texas`): the
  verdicts were carried over by overlap (`scripts/carry_review_verdicts.py`, at least half of
  a new outline inside judged ones), leaving 93 blobs and 304 large leads unjudged. Before a
  localized model replaces another, compare the OSM ground screen of both runs by park size:
  California's ResNet won its holdout (no large park in it) but detects 140 of 276 km² of
  the parks above 3 km².
  Overpass refused Texas's CSP area scan; `solar_thermal_plants.py --pbf` read the Geofabrik
  extract. No Ember line (customs data are national).
- **Mexico / Chile / Australia** (published 2026-11-22 as first iterations, before any
  review): segmentation-only, Verified almost all OSM park outlines at the land constant.
  Official figures are IRENA's 2025 national PV (`IRENA_NATIONAL_PENDING` in
  `official_capacity.py`: the scope says the national figures are not typed in yet); owed
  are SENER/CRE, CNE/CEN and the Clean Energy Regulator. Mexico's and Australia's CSP scans
  failed on Overpass in the chain and were re-run with `solar_thermal_plants.py --pbf`
  (Geofabrik extracts on moreaidata). Australia's holdout comparison has an implausible size
  split (local v46r finds 99.7% of 250-500 m2 arrays, 0.3% of 500-1,000 m2), unresolved.
  Chile's blobs sit mostly in the northern desert (salt flats, evaporation ponds).
- **Indonesia** (published 2026-11-25 as a first iteration, before any review): segmentation
  only, on the general v28 at its matched 0.98 (the localized v48r lost on East Java at pixel
  precision 0.60). Official figure IRENA 2025 (1,494 MW, `IRENA_NATIONAL_PENDING`: ESDM and
  PLN's PLTS Atap owed); Ember is **not a ceiling** (51.7 GW of Chinese cells against 5.7 GW of
  panels: domestic assembly). No `lead_water_screen` (Cirata floating PV); Cirata's outline
  prices at 92.8 MWp against its 192 MWp rating, since floating plants get the land constant.
  Equatorial Sumatra is cloudy in every window (Medan, Pekanbaru 4 clear days). Data on /home.
- **Poland**: compose snaps the grid to the country's own lower-left, so the ground screen and
  `pick_val_region.py` use `density._grid_origin`, never the raw `grid_origin`.

**Solar thermal is in OSM under the same `generator:source=solar` tag.**
`scripts/drop_solar_thermal.py --aoi <aoi>` drops thermal/CSP elements from the labels before
chips (`--by-id` at India's size); `--candidates` drops candidates at least half inside them
before `density`. Thermal also means `generator:type=solar_thermal_collector` with no method tag
and the plants in `KNOWN_THERMAL`. `scripts/solar_thermal_plants.py --aoi <aoi> --osm-solar <the
atlas's OSM file> [--candidates ...] [--by-id | --pbf <extract> | --tile-deg 2]` filters the
atlas's OSM file in place (original kept as `<stem>_PRE_thermal_<date>.parquet`), drops features
at least half inside a CSP plant (mappers draw mirror rows with the PV preset), writes the CSP
table (even empty) and reports to `results/solar_thermal/`; `run_country_compute.sh` runs it
after `osm_solar` (non-fatal). France and Germany were never checked. Heating plants are dropped
from PV and not counted. The label backup is named `<aoi>_solar_labels_with_thermal.parquet`
because `chips._newest_overpass_path` globs `<aoi>_overpass_solar*.parquet` and takes the last
name in sort order: a backup matching that glob silently undoes the filter.

**A candidate file that only LOST rows needs only the touched cells recomputed**:
`scripts/density_partial_update.sh <aoi> [pred_dir]` moves aside the partials of cells a removed
candidate intersects, rewrites the fingerprint and runs `density` without `--force` (identical
to `--force` to the last digit; India ~1 h against 28 h). **Run `density` and `atlas` from a tree
that has `results/<aoi>_osm_ground_screen/`**: the screen is read by a relative path and is
untracked, so a clean worktree silently skips it (India +2,845 MWp).

Opt-in pieces for large countries: `fetch_geoboundaries` caches to
`data/geoboundaries/gb_<ISO3>_<LEVEL>.geojson`, and `EARTHPV_REQUIRE_BOUNDARY=1` makes compose
fail closed instead of renaming every cell; compose network hardening (GDAL `TCP_KEEPALIVE` +
`LOW_SPEED_TIME=60`, `EARTHPV_NET_TIMEOUT_S=120`, `EARTHPV_FORCE_IPV4=1` via
`compose._harden_python_network`; stall watchdog 900 s); `prepare_national_osm_solar.py
--keep-detected-screen` keeps ground features above the 5 km² cap on the screen's evidence;
`overpass_labels_chunked.py` caches tiles and resumes (`--fetch-only`);
`scripts/ranged_download.py` (source.coop throttles single streams); `parquet_metadata_cache` on
every DuckDB connection.

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
  own `best_model_path` from every `last*.ckpt` and takes the best score. **A run whose config
  sets `snapshots: {keep_last: 12}`** (a slim checkpoint per epoch, EMA weights where the run has
  EMA) is picked by `scripts/pick_checkpoint_by_recall.py`: installation recall at the
  val/mIoU pick's precision, chosen on half the val chips and confirmed on the other, a
  false-alarm guard, and the best+last weight average as a candidate. The `pick`/`decide`
  markers then hold the checkpoint AND its threshold (line 2; absent means 0.3), which
  postprocess, the ground screen and density take. `PICK_BY_RECALL=0` opts out. The shipped
  threshold is the matched one, which for an averaged candidate can be ~0.97 and loses arrays
  over whole cells; not yet changed.
- **`scripts/merge_chip_index.py` writes `data/chips/combined/index.parquet` unless `--out` is
  given**, which is an existing corpus: pass `--out` or back it up first.
- **`roofclf.discover_quadrats` globs `*_calib_*_boundary.geojson`.** A quadrat stem without
  `_calib_` is invisible to `earthpv roof-classifier`, which fails with "No calibration quadrats
  found" seconds after launch -- easy to mistake for a still-running job. Anything in
  `data/labels/` matching the glob joins the next Pakistani refit (keep other countries'
  quadrats in `data/labels/<aoi>/`).
- **`export.load_mapped_reference_attrs` globs `data/labels/*_overpass_solar.parquet`
  AOI-agnostically**, so every country's pull there enters every AOI's mapped reference.
  Matching is spatial, but `recall_reference` provenance counts change: move other countries'
  files aside before re-deriving Pakistan's table.
- **A "national" OSM pull is not national until it is clipped to the border.**
  `prepare_national_osm_solar.py` builds the `--osm-solar` input: it clips on the geoBoundaries
  ADM1 union by default (`--no-clip` opts out), maps `small` -> rooftop, reclassifies rooftop
  features above `MAX_CANDIDATE_M2` as ground, and drops ground features above 5 km² unless
  `--keep-detected-screen`. With the screen, an outline above 5 km² that fails it is credited:
  `area_m2` becomes outline x `det_frac`, floored at the union of the plants mapped inside it
  that are each under the cap, and `screen_credit` records the share, which
  `atlas._apply_screen_credit` reapplies after the atlas's own dissolve. Only an outline earning
  nothing is dropped.
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
  (`imagery.BAND_RESAMPLING`, `compose --resampling`). Recompose a country wholesale or leave it
  alone. SCL stays nearest always.
- **roofclf's zonal means are AREA-WEIGHTED, and calibration and national scoring must never
  disagree about that.** `roofclf.area_weighted_zonal_mean` weights each 10 m pixel by the
  fraction of the footprint covering it (`preprocess.coverage_matrix`, subpix 4) instead of
  pixel-centre sampling, where 72.4% of Pakistani VIDA footprints own zero pixels. Applied in
  BOTH `building_table` and `score_buildings_national`, resolved from
  `roofclf.AREA_WEIGHTED_ZONAL`, recorded in `model_full.json` and the scoring's `_model.json`;
  `check_scoring_matches_calibration` refuses a mismatch. `--no-area-weighted` reproduces the
  older figures.
- **`preprocess.trimmed_mean_stack` replaces `np.nanpercentile` in every stack-reading path**
  (`np.nanpercentile` falls back to a per-slice Python loop on any NaN: 24.5 s against 0.08 s);
  bit-identical results.
- **A pre-2022 composite layer is on a different radiometric scale** (no BOA offset before
  baseline 04.00; every model here is fitted on post-2022 composites at +1000 DN). Pakistan's
  composite_1 offset is **per cell, not flat**: 122 cells built 2026-07-05 already match
  composite_0, the rest read ~800 DN darker with a wide spread. Harmonize per cell
  (`scripts/composite1_offset_survey.py`, `roofclf.epoch_feature_frame(..., dn_offset=...)`)
  before scoring one. An old epoch is not a negative set for roofclf.
- **Training positive threshold** is `MIN_PV_AREA` in `chips.py` (arrays below it are burned as
  `ignore = -1`, not negatives). Changing it requires rebuilding chips and retraining.
- **Geographic val split** uses `val_tiles` in `configs/aoi.yaml`; these must be MGRS tiles the
  `source_region` actually downloaded, or the val set ends up empty (datamodule then falls back
  to a random 20% split).
- **Areas are geodesic** (`labels.geodesic_area_m2`), never `.area` on lat/lon geometries.
- Long GPU/network stages are run detached and polled; the rich progress bar does not flush
  cleanly to a redirected log, so watch checkpoint files / cell counts rather than the log.
- **The aidisc drive is the binding constraint; `/home` is where bulk outputs belong.**
  Composites and national scoring passes live under `/home/tobi/earthpv_*` and are symlinked back
  into `data/` (`data/composites/<aoi>` -> `/home/tobi/earthpv_composites/<aoi>`); newer
  countries use `/run/media/tobi/moreaidata`. **A new AOI's composites MUST be symlinked off
  aidisc, never written straight into `data/composites/<aoi>/`** (~10 MB per cell). A full disk
  does not name itself: `compose` dies with Python **exit code 120** (failure to flush stdout)
  and a truncated log. Committed cells survive (atomic `.tif.tmp` rename), so recovery is move,
  symlink, resume. Check `df -h /run/media/tobi/aidisc` BEFORE a national run; moving and
  symlinking preserves data, deleting does not.
- **A country-scale `compose` leaks file descriptors and degrades before it dies; run it in a
  restart loop capped by WALL CLOCK** (e.g. `timeout 7200` per pass, rc=124 as the expected
  path), not by waiting for a crash -- a degraded pass looks healthy while running at a quarter
  of the rate. It is resumable and idempotent, and a fresh pass also re-signs the Planetary
  Computer SAS token (~24 h lifetime; on 403s `annual_composite` fails over to Earth Search).
  Let "a pass added nothing" be the stop condition.
- **With `workers` > 1, set `imagery.PC_TIMEOUT_S` to several times the expected per-cell wall
  time, and `compose_loop.sh`'s `STALL_S` well above a pass's startup cost plus one slow cell.**
  Compose is bandwidth-bound (~290 MB per cell), so under N workers a healthy cell takes ~N x its
  uncontended time; a short patience trips on every cell and each hand-off downloads the cell
  twice, a livelock that reads exactly like a provider outage. Diagnostic: measure the link (an
  outage leaves it idle, this leaves it saturated) and count `exceeded <N>s` hand-offs per
  landed cell.
- **`nohup setsid` alone does not survive a session logout on this machine.** systemd-logind
  kills a whole session's cgroup unless lingering is enabled: check
  `loginctl show-user "$USER" | grep Linger` and `loginctl enable-linger "$USER"` once before
  anything multi-hour. Run each long job as its own `systemd-run --user` unit.
