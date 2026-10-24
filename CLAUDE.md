# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository. It documents the **current** state of the pipeline and its main results. The
detailed, dated history of what was tried, rejected, or superseded to get here lives in
`docs/experiments.md` (the experiment register) and `docs/open-questions.md` (open items) --
consult those before re-deriving something that may already have a documented answer.

## What this is

`earthpv` detects individual large rooftop solar PV arrays (target > 400 m², the practical
floor for per-pixel supervision at Sentinel-2's 10 m GSD) from Sentinel-2 L2A imagery by
fine-tuning the open-source **TerraMind** geospatial foundation model (IBM/ESA, via
**TerraTorch**). Labels come from OpenStreetMap solar mapping (through Overture Maps);
building footprints classify detections as rooftop/ground. It is **recall-first**: candidates
are meant to be human-validated against high-res imagery in OSM workflows, so false positives
are tolerated. Installations below the 400 m² floor are not targeted by segmentation at all --
that gap is closed by a separate per-building classifier, `roofclf` (see "Main workflow"
below). Trained on Germany, inferred on Pakistan (primary AOI) and Gujarat, India. Read
`README.md` for the narrative and current headline numbers.

**Why two detectors, not one**: Germany's legally-complete PV register (MaStR) shows **65.5%
of rooftop capacity sits in installations below the 400 m² floor** (97.2% of installations by
count) -- see "MaStR validation" below. A segmentation model trained only above that floor is
structurally blind to roughly two-thirds of the capacity a "rooftop solar" headline implies,
which is why `roofclf` exists and why it is not optional infrastructure.

## Main workflow (default pipeline, primary output)

This is the project's default, documented workflow, and the **evidence atlas** is its primary
output. Two detectors, split by placement and by calibration coverage rather than cleanly by
size, combined into one product:

- **Segmentation** (`infer` → `postprocess` → `density`) -- the TerraMind fine-tune,
  outlining panels directly. Produces every mapping lead regardless of size, and is the only
  instrument for ground-mount at any size (`roofclf` has no footprint to classify there). It
  remains the authoritative rooftop instrument for individual arrays **≥ 400 m²** everywhere
  `roofclf` has not been calibrated to replace it. Production checkpoint: `v3_combined_india`
  (`terramind-pv-epoch=22-step=9062.ckpt`), confirmed by the owner 2026-08-07, no retrain
  planned. (Two earlier checkpoints, `v2_combined` and an undocumented `pk16085` variant, were
  deleted from disk at some point and can no longer be independently re-verified; a Gujarat
  atlas built before this was noticed is flagged in `docs/results/gujarat.md`.)
- **`roofclf`** (`roof-classifier` → `roofclf-score-national` → `ge400-roof-capacity` →
  `sub400-capacity`) -- a per-building "does this roof carry PV?" classifier, cross-checked
  with the zero-training **SPPI** spectral index (roofclf AND SPPI agreeing) as an internal
  floor under the atlas's headline figure. Covers every building **< 400 m²** and, since
  2026-08-07, also **replaces** segmentation's own rooftop estimate for buildings **≥ 400 m²**
  inside a density-calibrated domain of cells, where it measures better (AUC ~0.76-0.78 vs
  segmentation's ~0.50-0.78, strongly conditional on quadrat). Both capacity functions are
  domain-restricted and refuse to rescale to a national total on their own; an AND-gate variant
  can additionally cover cells *outside* the calibrated domain as an explicitly-flagged
  extrapolation, but that component is **no longer published** (dropped from the atlas
  2026-08-15; see "Density stage" below).
- **`atlas.build_evidence_atlas`** combines both into **Best estimate**, this project's own
  highest defensible figure (hand-mapped OSM, plus segmentation's ground-mount detections,
  roofclf's rooftop replacement in-domain plus segmentation's own recall-corrected rooftop
  out-of-domain, and roofclf-alone density below 400 m²) -- de-duplicated against each other
  and against OSM, and
  floored per cell at hand-mapped OSM plus the stricter roofclf+SPPI agreement population
  (internally still called "Verified" in the code, but no longer surfaced anywhere in the
  published atlas, docs, or README -- 2026-08-12 decision). Reports a 90% credible interval on
  the headline figure (see "Density stage").

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
# NOTE: --sub400-outdomain-cells is deliberately NOT passed (2026-08-15) -- see "Density stage".
earthpv atlas --aoi <aoi> \
  --sub400-central-cells data/roofclf_national_with_sppi/<aoi>/density/sub400_central_incremental_buildings.parquet \
  --sub400-low-cells     data/roofclf_national_with_sppi/<aoi>/density/sub400_low_incremental_buildings.parquet \
  --ge400-roof-cells     data/roofclf_national_with_sppi/<aoi>/density/ge400_roof_incremental_buildings.parquet \
  --osm-solar <national OSM solar pull>
```

**Random-cell manual validation is part of this workflow, not an optional extra.** The
calibration quadrats are curated and industrial-leaning; a `roofclf` that scores well only
there is not evidence it works on the un-curated rest of the country.
`scripts/tile_roofclf_detections_geojson.py --random-cells N --seed S` draws N cells uniformly
at random from the national scoring output, excludes anything inside a calibration quadrat, and
writes JOSM-reviewable GeoJSON tiles into `results/<aoi>_roofclf_validation/`. Results get
logged to `results/roofclf_random_validation_log.csv`. Full protocol:
`docs/methods/roofclf-national-validation.md`. **Known limitation**: out-of-domain random cells
have so far turned out to sit under stale JOSM reference imagery, too old to confirm or refute
recently-installed small PV -- this is what motivated the out-of-domain AND-gate substitute, and
then (2026-08-15) its removal from the published atlas (see "Density stage" below), not a fixable
review-process bug. **2026-08-17: this now also blocks purpose-drawn quadrats, not just randomly
sampled review cells.** Three low-density boxes drawn to widen the domain (Dera Ghazi Khan
11.8 bldg/km², Waziristan 16.9, Jamshoro 30.9) were swept and all came back at zero
installations against 83 roofclf-AND-SPPI flagged buildings / 475.4 kWp claimed -- but under
imagery the owner reports as very old, so the zeros are uninterpretable in both directions and
none was registered. Registering them would have moved the floor to 11.8 (66.3% -> 95.6% of
cells) and pulled the sparse band's coverage ratio toward zero on evidence that does not
support it: the Muzaffargarh Rural Wide mistake again, caught before a refit. **The gate on
widening the density domain further is therefore imagery date, not mapping effort** -- check
`imagery_layer`/`imagery_date` before drawing, not after mapping. See Box 17.

**A country with a complete register does not need mapped quadrats for the capacity half.**
Germany has zero quadrats and now has a roofclf half anyway, because MaStR publishes per-
municipality totals and the estimator is an aggregate: `roof-classifier` fits the model on
pseudo-quadrats, `roofclf-score-national` scores the country, and
`scripts/calibrate_germany_capacity.py` fits kWp per credited m2 against the register instead
of a quadrat coverage ratio. See "MaStR validation" below for what that is worth (it ties a
roof-area baseline in Germany and beats it 3.4x in Pakistan).

A country with neither quadrats nor a complete register gets the **segmentation-only evidence
atlas**
(`earthpv atlas --aoi <aoi> --osm-solar <pull>`, omitting BOTH `--sub400-low-cells` and
`--sub400-central-cells`; supplying one is rejected as a half-configured run) until quadrats
exist to fit `roofclf` -- still this workflow's output for that country, just missing its
sub-400 m² half. Verified degrades to hand-mapped OSM alone and Best to that plus the ≥ 400 m²
detections; neither tier reaches below the floor. Gujarat is in this state; France is too
(`roofclf` does not transfer to French residential PV). Germany no longer is.

**`--osm-solar` is now required, and `density` no longer writes an atlas at all (2026-09-02).**
The six-estimator and simple atlases (`atlas.build_atlas`, `_build_estimator_atlas`,
`_build_simple_atlas`, `templates/pv_estimator_atlas.html`) were **removed**: `density` called
`build_atlas` at the end of every run, which kept producing a deprecated page alongside the real
product -- for Germany it published a 114 GWp hero against a 74.8 GWp complete register. Neither
template was embedded in any published page. Artifacts derived from them were removed with them
(`docs/assets/interactive/pakistan_capacity_atlas.html`, the `capacity_estimators` docs figure and
its reader, the README screenshot entry) so the "every figure is generated from a tracked source"
invariant stays true. `build_sub400_bracket_atlas` and `build_combined_atlas` are untouched and
still share `templates/pv_atlas.html`. Gujarat's committed atlas HTML predates this and can no
longer be regenerated as-is; rebuild it as an evidence atlas when that AOI is revisited.

**Of the many sub-400 m² instruments tried in this project's history (a per-pixel fraction
head, SPPI as a standalone detector, spectral unmixing, several hard-negative and
quadrat-supervised segmentation retrains), only `roofclf` (cross-validated with SPPI) was
promoted into the main workflow.** The rest are documented, with why they didn't ship, in
`docs/experiments.md`.

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
workflow" above: `density → check-density` for the ≥ 400 m² segmentation half, `roof-classifier
→ roofclf-score-national → sub400-capacity` for the < 400 m² roofclf half, then
`atlas --sub400-central-cells --sub400-low-cells --sub400-outdomain-cells --osm-solar` to
combine both. `roofclf-score-national` is the long pole (hours at country scale) and is
resumable per-cell like `density`.

**There is no test suite and no lint task wired** (one test file exists,
`tests/test_mastr_validation.py`, run as a plain script -- pytest is not a declared dependency).
Ruff is configured (line-length 100) but run manually. The practical "does it work" check is a
small end-to-end run: `chips --aoi germany --limit 500` → `train --smoke` → `evaluate`.

**The released segmentation model is v14, fetched with `pixi run fetch-model` (2026-10-23).**
`scripts/fetch_model.py` downloads `earthpv_segmentation_v14.ckpt` from the GitHub release
`segmentation-model-v14-2026-10-23` into `data/models/release/` and checks its SHA-256;
`new_region.py plan` and the setup docs take the file name from its `RELEASE` dict. It is
`v14_combined_south_africa` epoch 41 put through `scripts/slim_checkpoint.py` (optimizer state
dropped, `backbone_pretrained: false`, so 33 MB and no Hugging Face download at load), and with
the committed code it reproduces South Africa's published probability raster byte for byte.
It won a seven-checkpoint, eleven-region benchmark on installation recall (84.4% against v5's
81.5% outside South Africa, paired p < 1e-30; rooftop 400-5,000 m2 52.3% against 49.1%) at lower
pixel precision (0.72 against 0.79; it spreads into the desert around Moroccan parks). v15 is
the precise alternative and is not released. Table: `results/release_model_benchmark.csv`,
write-up: `docs/pretrained-model.md`. **Every published atlas still runs on its own country's
checkpoint; the release changes no published number.** To release a newer model: slim it, upload
it with `SHA256SUMS`, `MODEL_CARD.md`, `LICENSE` and `NOTICE` to a new tag, update `RELEASE`,
and redo the page's tables from the same benchmark. **The weights are Apache-2.0** (owner
decision 2026-10-23, matching TerraMind); `NOTICE` carries the TerraMind, OpenStreetMap and
Copernicus attributions, and detections made with the model stay ODbL like every data output.

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

### Adding a new AOI

`scripts/new_region.py` is the front door for a region with no local data: `check` preflights
the four open sources (Overpass label count, VIDA parquet for the ISO3, geoBoundaries
ADM1/ADM2, Sentinel-2 cloud cover in the compose window) read-only, `add` appends the AOI block
to `configs/aoi.yaml` and re-parses to catch a bad insert, `plan` prints the runbook. **New AOIs
must carry `division.iso3`** -- `buildings._iso3_for` prefers it and the ISO2 fallback map only
covers PK/DE/IN, so an AOI without it fails at the density stage rather than at setup.
`source.coop` 403s any request without a User-Agent header, which reads exactly like "no such
country." Guide: `docs/reproduce.md`'s "Scale to a new country" section.

**Gujarat has a full segmentation-only capacity atlas** (`docs/results/gujarat.md`,
`docs/assets/interactive/gujarat_pv_atlas.html`): 812.6 MWp (`est_mwp_rc`, roof 197.0 / ground
615.6), recall-*uncorrected* (a precision-weighted floor, no OSM reference exists for India
yet). It has zero calibration quadrats, so it has no roofclf half. It was also built from
whichever checkpoint produced its 2026-07-12 candidates (likely `v2_combined`, since-deleted and
unverifiable), not the current `v3_combined_india` -- flagged in the doc, not silently glossed
over; re-running compose+infer with the current checkpoint is the natural next step for anyone
who revisits this AOI. **Superseded 2026-10-11 by the national India atlas** (below).

### Compose stage (imagery for AOIs without local composites)

`compose.py` builds Sentinel-2 composites on demand via Planetary Computer STAC
(`imagery.annual_composite`: dry-season median of the ~12 least-cloudy scenes per 0.1° cell). It
only composites **building-populated cells** (rooftop PV needs roofs), prioritized by density,
so "full Punjab" reduces to the ~60 cells covering its cities. Output mirrors the rooftopsenti
COG layout (`<cell>/composite_0.tif`) so `CompositeIndex`/`infer` read it unchanged. It is
**resumable** (skips finished cells) and **network-bound** (~2 min/cell).

### Postprocess & ranking

`postprocess.py` polygonizes probability rasters, then joins candidates to building footprints
for a rooftop/ground/no-building `placement` and a metric-based `rank_score` (confidence ×
building prior). Footprints come from `buildings.py::load_dense_buildings` -- **VIDA Open
Buildings** (Google+Microsoft, imagery-derived, includes small/unmapped roofs), fetched
windowed-and-cached per AOI; the local Overture ≥500 m² set is the fallback.
`postprocess.replace_with_osm_geometry` substitutes an OSM-mapped installation's real geometry
for the model's coarse candidate polygon when one matches (keeping only the closest OSM match
per feature, to avoid the same feature being inherited by several nearby candidates).
`export.py` sorts by `rank_score` and writes GeoParquet/GeoJSON + a MapRoulette challenge. This
candidate-polygon path is the > 400 m² individual-detection product; `density.py` covers smaller
installations via aggregation instead (see below).

### Density stage (aggregation into PyPSA-ready shapes)

`density.py` reuses the same per-cell probability rasters (no GPU, no retraining) to report
*aggregate* PV capacity per building/grid-cell/region rather than individual candidate polygons.
It aggregates the **≥ 400 m²** population into PyPSA-ready shapes; it is measurably blind below
that floor on its own (one fully-mapped km² of residential Lahore holds 3.3× more sub-100 m² PV
area than this instrument finds nationally there). It reports three area metrics per building:
`*_det` (thresholded candidate polygons -- precision-honest floor), `*_exp`
(probability-weighted area, an upper-leaning ceiling), and `*_cal` (`*_det` re-weighted by a
measured P(real | size, glint, placement) -- the headline capacity number, `est_mwp_rc`).

**Area → capacity uses two constants, never one, and both are calibrated against real plants,
not assumed.** Rooftop detections convert at `DEFAULT_KWP_PER_M2_MODULE = 0.18` kWp/m² (module
area). Ground-mount detections convert at `DEFAULT_KWP_PER_M2_LAND = 0.05` kWp/m² (site area --
ground-PV training labels are OSM `power=plant` perimeters, so only the ground-cover ratio is
module; `KWP_LAND_CI90 = (0.035, 0.075)`), calibrated from two real Pakistani plants (Quaid-e-Azam
Solar Park: 400 MW / 8.9M m² dissolved footprint; Sukkur: 150 MW confirmed combined-phase
capacity / 2.6M m²). Applying the module constant to site area overstates ground-mount by
2-3x -- `_ratios`/`_composed_mwp_draws` split every estimator by `placement` before conversion
specifically to prevent that. Both constants carry lognormal priors (`capacity_calibration.py`,
`kwp_draws`) that propagate into the atlas's credible intervals rather than being treated as
exact.

**Precision/recall calibration is split by placement** (`capacity_calibration.derive_placement_tables`):
pooling rooftop and ground-mount into one set of area bins let ground-mount borrow rooftop's
much higher OSM corroboration rate in the same bin. Ground bins fall back to
`p_unmapped = 0.0` (an honest floor) rather than inheriting the pooled value.
`density.candidate_p_real`/`candidate_recall` and `_candidate_uncertainty` both select each
candidate's own placement subtable when one exists.

**The checked-in calibration YAML is load-bearing and was silently regressed once.**
`calibrate-candidates --by-placement` was opt-in until 2026-08-15, and a 2026-08-14 re-run
without it (and without `--glint-sample`/`--calibration-box`) replaced
`configs/calibration/pakistan_candidate_precision.yaml` with a pooled, mapped-only table derived
from a different candidate population -- nothing errored, and the published atlas's own numbers
came from the 2026-08-11 table, which was restored 2026-08-15. Three guards now exist:
`--by-placement` **defaults to True**; `capacity_calibration.write_table` **refuses** to
overwrite a table carrying evidence the new one lacks (placement split, glint calibration,
manual reviews) unless `--allow-downgrade` is passed; and `density.py` warns when it loads a
table with no `placement_bins` for an AOI whose candidates span both placements. Reproducing
Pakistan's table needs the calibration boxes and the glint sample, not a bare re-run -- its
`recall_reference` field records which (18,276 features = the pre-pipeline snapshot's 2,811 plus
19 calibration boxes).

**OSM reference polygons are dissolved before use** (`labels.dissolve_overlapping`): a
`power=plant` perimeter with a nested `power=generator` way, or duplicate mapping passes, would
otherwise double-count one real installation's area. Wired into
`export.load_mapped_reference_attrs`, `postprocess.replace_with_osm_geometry`, and
`atlas.build_evidence_atlas`'s own OSM sum.

`density` also **excludes candidates over `postprocess.MAX_CANDIDATE_M2` (100k m²)** from
capacity (`density.capacity_relevant_candidates`, shared by `run_density` and the evidence
atlas) -- `polygonize_chips` merges every touching thresholded pixel with no upper bound, so a
connected sheet of false positives can become one multi-km² "installation." A
`geometry_source == "osm"` oversize candidate (a real, human-mapped footprint) is exempted from
the exclusion. **Since 2026-10-11 the exemption has two limits, each mirroring a rule the OSM
layer already applies to Verified** (`prepare_national_osm_solar.py`): an exempted outline is
always ground (VIDA traces a park's panel rows as buildings, so 101 Indian park outlines had
been placed `rooftop` and converted at the module constant), and when the AOI has a ground
screen (`results/<aoi>_osm_ground_screen/screen_full.csv`, auto-discovered by
`density.load_osm_screen`) an outline above 5 km² that fails the screen's evidence (imaged
>= 0.9, detected >= 0.5) is credited at outline area x `det_frac` instead of whole. Before it,
an outline the gate dropped from Verified came back into Best whole (India's Khavda outlines,
3,789 MWp). The same rule runs in `density`, the evidence atlas and `calibrate-candidates`.

**Current national result (Pakistan, `est_mwp_rc`, as of the 2026-08-11 placement-split fix):
4,051.9 MWp** (rooftop 2,916.3 MWp, ground-mount 1,135.6 MWp). `check-density` currently reports
0 fail on the ground:rooftop ratio check (previously the dominant failure mode, root-caused as
uneven OSM-replace correction between placements, now fixed by the placement split above) but
**3 regions still fail the single-cell-concentration check** (Khyber Pakhtunkhwa, Balochistan,
Islamabad Capital Territory) -- checked and confirmed genuine (all three flagged cells are the
calibration quadrats' own cities), published anyway per this project's standing precedent for a
checked-genuine plausibility failure.

**A known, structural (not buggy) gap**: `buildings.geoparquet`'s summed rooftop capacity is
NOT the same number as `grid.geoparquet`'s region-level rooftop total. The region total sums
each rooftop-placed candidate's full polygon area once; the per-building table only credits each
building with its actual geometric intersection, capped at that building's own roof area -- so
whitespace inside a rooftop-classified polygon that doesn't literally sit on a building is
counted in the first total and missing from the second (measured ~46% gap nationally). Any
PyPSA-style per-building disaggregation from `buildings.geoparquet` is therefore a conservative,
roof-anchored floor. Full derivation: `docs/methods/density.md`.

**roofclf replaces segmentation's own rooftop estimate for ≥ 400 m² buildings inside a
density-calibrated domain** (`roofclf_ge400_capacity.py`, `earthpv ge400-roof-capacity`) --
segmentation is trained blind to installation size relative to its building, so a ≥ 400 m²
building can carry a much smaller true array and read as a segmentation miss regardless of its
own footprint size (confirmed by the owner as the explanation for several quadrats where
segmentation scores exact-zero AUC). Outside the domain, segmentation's own `est_mwp_rc_roof`
remains the only evidence-backed number.

**The coverage ratio (true mapped PV area / flagged roof area -- corrects for a flagged roof not
being entirely covered by panels) is measured per building-size decile AND per density stratum**,
not as one flat number (`sub400_capacity.coverage_ratio_by_size_and_density`, shared by all three
domain-restricted capacity functions: sub-400 central, sub-400 AND-gate, and the ≥ 400 m² roofclf
replacement). Its uncertainty is measured by **resampling calibration quadrats** (not buildings --
quadrat composition, not per-building noise, is what has repeatedly moved these numbers), 200
bootstrap replicates, and the same replicate index is shared across all four roofclf-based atlas
components since they are fit on the same quadrats (`sub400_capacity.COVERAGE_BOOTSTRAP_SEED`).

**The parcel label (`roof-classifier --parcel-label`, 2026-08-16) counts PV in the yard, not
just on the roof.** `pv_area_true_m2` was the intersection of mapped PV with the VIDA
footprint, so an array two metres off the wall booked zero coverage ratio and zero area recall
on a building roofclf usually flags anyway. `roofclf.parcel_pv_area` adds mapped PV within
`YARD_RING_M` (20 m) of a footprint, attributed whole to its single nearest building, for
installations below the 400 m² segmentation floor only (above it, ground-mount is
segmentation's and the atlas already counts it). **80% of what this recovers turns out not to
be ground-mount at all**: across the 27 quadrats it adds 146,766 m², of which 29,764 (20%) is
OSM `placement=ground` and 117,003 (80%) is mapped *rooftop* PV whose polygon extends past an
undersized, imagery-derived VIDA outline. Both belong in the numerator -- the overhang term is
self-consistent, since the same undersizing shrinks the calibration denominator and the
national flagged roof area alike -- but only the ground term makes the atlas's "rooftop" line
partly ground-mount, so `sub400_capacity.parcel_label_composition` reports the split in both
capacity summaries and it is what to quote for the placement claim. **The yard *feature* block
(`roofclf.yard_features`, zonal statistics over a distance-transform Voronoi ring, SPPI
included) does NOT ship**: against the parcel label itself it scores median fold AUC 0.8712
against 0.8734 for the roof-only feature set, because the term it exists to explain is 1.6% of
quadrat PV area. Available behind `--yard-features` for re-measurement once cropland quadrats
exist. The label is off by default; a parcel-label model needs its own national rescoring, and
`roofclf.check_scoring_matches_calibration` refuses to pair one national scoring with another
calibration's coverage ratio. **Scored nationally, validated and PUBLISHED 2026-08-17**: sub-400
central 7,890.2 -> 9,201.7 MWp, the sub-400 AND-gate 2,179.7 -> 2,647.0, the >= 400 m² roofclf
rooftop replacement 7,189.4 -> 7,405.0, Best estimate 18,218.4 -> 19,745.9 (90% CI
16,051-23,520) and, unlike the recall correction, the internal floor too (5,389.5 -> 5,856.8 --
legitimate for a floor, since it prices agreed-on buildings more completely rather than
extrapolating to unseen ones). Random-cell validation was run by the owner (20 cells, seed
20260817, tiles in `results/pakistan_roofclf_parcel_validation/`) before promotion; **the
per-cell counts are still missing from `results/roofclf_random_validation_log.csv`, which is
header-only** -- that log is the only durable record of the review and should be filled in.
The parcel calibration and scoring now occupy the canonical paths (`data/roofclf/`,
`data/roofclf_national_with_sppi/pakistan/{prob,density}`); the roof-only versions are kept as
`*_PRE_20260817_parcel_label` so every pre-widening figure stays reproducible. Full derivation:
`docs/methods/roofclf.md`'s "The parcel label", `docs/issues/small-ground-mount-instrument.md`.

**2026-08-20: Attock/Layyah/Lodhran (Box 18) declared Rule-1 and folded into a fresh refit**
(30 quadrats total, `kalat_rural_calib_3km` still excluded -- see "Calibration quadrats"
below). Same national rescoring + capacity chain, re-run in place: sub-400 central
9,201.7 -> **8,922.7 MWp**, sub-400 AND-gate 2,647.0 -> **2,515.3 MWp**, the >= 400 m² roofclf
rooftop replacement 7,405.0 -> **6,747.3 MWp**, Best estimate 19,745.9 -> **18,826.7 MWp**
(90% CI 16,022-24,358), and the internal floor (Verified) 5,856.8 -> **5,725.1 MWp**. All
three components moved down, consistent with the added peri-urban diversity giving a
slightly less confident fit (median LOQO fold AUC 0.8735 -> 0.8574) rather than any single
quadrat dominating. Pre-refit tables kept at `data/roofclf_PRE_box18_20260820/` and
`data/roofclf_national_with_sppi/pakistan/density_PRE_box18_20260820/`. Random-cell
validation (20 cells, seed 20260820, tiles in `results/pakistan_roofclf_validation/`) was
generated but **not yet reviewed** -- rows logged to `results/roofclf_random_validation_log.csv`
with blank verdict columns, same backlog pattern as the 2026-08-17 batch above.

**roofclf's own misses are corrected for too, since 2026-08-15**
(`sub400_capacity.area_recall_by_size_and_density`). The coverage ratio prices the PV on roofs
roofclf *flagged*; on its own it books zero MWp for every installation on a roof roofclf missed.
Dividing by the measured share of true mapped PV **area** that lands on flagged buildings, per
size bin and density stratum, is the same Horvitz-Thompson step `density.py`'s `est_mwp_rc` has
always applied to segmentation candidates -- the two halves of the atlas now use one estimator
rather than two. Measured on the 16 rate_ratio-trusted quadrats: **0.808 for sub-400 m² buildings
(0.34-0.99 across size deciles) and 0.978 for ≥ 400 m² ones**, moving sub-400 central 6,372.1 →
**7,890.2 MWp** and the ≥ 400 m² roofclf rooftop replacement 7,030.8 → **7,189.4 MWp**. Both
tables are refit inside the SAME bootstrap replicates, so one factor vector prices
`coverage_ratio / area_recall` together and their (strongly dependent) errors are never
multiplied as if independent. **Deliberately NOT applied to either AND-gate tier** -- those are
floors, and a floor that extrapolates to installations neither detector saw is not a floor. The
correction is a lower bound in two further ways documented in `area_recall_by_size`'s docstring:
Rule-1 epoch staleness biases measured recall up, and the national population it is applied to is
already deduped against segmentation and OSM while recall is measured over a whole quadrat.

**OSM and a recall-corrected total: combine, don't add (2026-10-20).** Segmentation's
`est_mwp_rc` divides each detection by the recall of its size class, measured as the share of
OSM-mapped installations some candidate matches, so it already stands in for the mapped
installations the model missed. Best used to ADD those (`osm_mwp_unmatched`) on top: counted
twice in expectation. `build_evidence_atlas` (and `_size_distribution_data`, which must
re-bin the same total) now takes, per placement x size bin, `max(HT, D + U)`: the absorbed
share comes out of each candidate's inflation, never below a cell's precision-weighted
`est_mwp_cal_*`, so mapped installations stay in their cells (`atlas.osm_absorbed_inflation`).
Where a recall correction applies, OSM counts as matched at the table's own `min_distance_m`
(100 m), not 30 m. Second fix, Pakistan only: inside the ge400 roofclf domain every OSM rooftop
installation is counted from the map -- segmentation's rooftop figure is discarded there and
roofclf is deduped against OSM, so a mapped array segmentation also detected was counted
NOWHERE (687 installations, 466 MWp; the per-cell floor restored 36). Only AOIs with a recall
table are affected (Pakistan, Germany). **Pakistan 24,330.0 -> 24,406.8 MWp, Germany 88,709 ->
84,473 MWp.** A `--legacy-osm-addition` rebuild reproduced both published data blocks exactly
before the fixed ones were published, and the page records its convention in
`totals.osm_combination`. **Third gap, closed the same day**: the sub-400 m2 populations deduped against EVERY candidate,
so a flagged small roof next to a rooftop candidate inside the ge400 domain (whose figure Best
discards) or next to an oversize blob excluded from capacity was counted nowhere.
`sub400_capacity.dedup_candidates` now keeps only candidates whose figure Best uses
(`--legacy-seg-dedup` reproduces the old run, verified exact first); `sub400-capacity` reads
the domain from `ge400-roof-capacity`'s output, so **run ge400-roof-capacity first**. Estimated
from counts at ~300 MWp, measured at **31.6 MWp** (central) and 23.4 (AND-gate): two-thirds of
the freed roofs sit next to OSM-mapped PV, now counted from the map. **Pakistan Best
24,406.8 -> 24,438.3, Verified 6,970.7 -> 6,994.1.** Pre-fix outputs:
`data/roofclf_national_with_sppi/pakistan/density_PRE_segdedup_20261020/`.

**The density-calibration domain is a building-density band, `density.CALIBRATED_BLDG_DENSITY_KM2`**,
fit from the density span of every Rule-1-complete calibration quadrat -- **NOT** from
`select_calibrated_quadrats`'s separate precision-trust selection (a quadrat's density is real
ground truth regardless of whether its *precision* is trusted for the coverage-ratio fit).
Currently **(48.5, 5,258.00) bldg/km²** (widened again 2026-08-13, same day, by
`nasirabad_rural_calib_2km`, own density 48.5 bldg/km², below the 123.5 floor
`bahawalnagar_rural_calib_4p00km2` had just set hours earlier), covering
**2,957 of 4,463 national cells (66.3%, 94.7% of national buildings)**.
`--ratio-lo`/`--ratio-hi` on the CLI do **not** affect this
domain at all -- they tune `select_calibrated_quadrats`'s independent precision-trust band,
a real footgun if conflated. **The generalizable lesson for widening this domain further**: a
quadrat only lowers the floor if the quadrat's OWN average density (not its surrounding national
grid cell's average) reads below the current floor. A boundary traced around a settlement's
built-up extent -- the natural way to draw one, since that's where PV would be -- will almost
never do this, because villages/towns are inherently dense and it's the farmland *between* them
that pulls a country average down; a range-extending quadrat has to be sized and placed to
average in enough non-built land on purpose. `docs/methods/calibration-quadrats.md` and
`docs/methods/density.md` have the full derivation and every historical widening step.

Current domain-restricted capacity figures (post 2026-09-21 `roofclf` refit + national
rescoring on **area-weighted zonal means**, 30 quadrats -- still excludes
`kalat_rural_calib_3km`; parcel label, recall-corrected): sub-400 central (feeds Best
estimate) **13,262.6 MWp**, sub-400 AND-gate (the internal floor population, uncorrected by
design) **3,784.3 MWp** (13,231.0 / 3,760.9 before the 2026-10-20 dedup fix), ≥ 400 m² roofclf rooftop replacement (in-domain) **8,256.7 MWp**
(previous, pixel-centre sampling: 8,922.7 / 2,515.3 / 6,747.3). The model itself moved
median fold AUC 0.8574 -> **0.8682**, within-size 0.8093 -> **0.8193**, deployment threshold
0.2535 -> **0.2446** and recall at precision 0.500 from 0.6386 -> **0.6583** (123,898
buildings, 17,151 with PV, 22,580 flagged). The density-calibration domain did **not** move:
still 2,957 of 4,463 cells (66.3%, 94.7% of buildings). The out-of-domain AND-gate, still
unpublished, went 61.7 -> **189.3 MWp**.

**Outside the calibrated domain, roofclf-AND-SPPI agreement CAN be used as a substitute standard
of evidence** (`sub400_capacity.out_of_domain_and_gate_capacity`, `--sub400-outdomain-cells`),
but **is no longer published: the owner dropped it from the atlas 2026-08-15**, since it was the
one Best-estimate component not measured where it was applied (a coverage-ratio fit from
urban/semi-urban quadrats extrapolated across a much sparser rural remainder with no calibration
coverage of its own) and manual JOSM review of that population is blocked by stale reference
imagery (see "Main workflow" above). It was worth +61.7 MWp over 1,506 out-of-domain cells.
Everything that reported it degrades to absent rather than zero -- the component is omitted from
`_evidence_uncertainty` outright, and the atlas/composition templates drop the dotted
`is_extended` outline, the "Small PV, extrapolated" province column, the size chart's third
legend key and the SPPI-in-Best slice. Pass the flag and it all comes back.

**The evidence atlas reports a 90% credible interval on its headline figure**
(`atlas._evidence_uncertainty`), composing every measured uncertainty source (module/land kWp
priors, coverage-ratio quadrat bootstrap, an explicit stated judgement band on the out-of-domain
extrapolation alone when it is supplied, `KWP_LAND_CI90` for ground-mount) with correlated terms sharing one draw
vector where the underlying constant or calibration set is shared. It asserts its component
point values sum to the published total as a guard against silently adding a component to
the atlas without adding it to the uncertainty composition (the code still separately tracks
the OSM-plus-AND-gate floor's own point value and CI internally, but only Best estimate is
published). **Current published result: Best estimate 24,438.3 MWp (90% CI 20,894-33,666)**
(2026-10-20: 24,330.0 -> 24,406.8 when OSM-mapped misses stopped being added on top of the
recall-corrected satellite total, then -> 24,438.3 when the sub-400 m2 populations stopped
deduping against candidates Best does not use, see "OSM and a recall-corrected total" below; 2026-08-15: 16,608.7 -> 18,279.6 on the roofclf recall correction, then -61.7 on dropping the
out-of-domain extrapolation; 2026-08-17: -> 19,745.9 on the parcel-label promotion; 2026-08-20:
-> 18,826.7 on folding Box 18's three peri-urban quadrats into the refit; 2026-09-21:
-> 24,330.0 on the area-weighted-zonal refit + national rescoring. The floor (Verified)
moved similarly: 5,389.5 -> 5,856.8 (parcel label, 2026-08-17) -> 5,725.1 (Box 18, 2026-08-20)
-> 6,970.7 (area-weighted zonal, 2026-09-21, 90% CI 6,021-9,063) -> 6,994.1 (sub-400 dedup
fix, 2026-10-20, 90% CI 6,041-9,091)). **The mandatory 20-cell
random validation for this rescoring (seed 20260920, tiles in
`results/pakistan_roofclf_validation/`) has NOT been reviewed** -- nor have the 2026-08-17 and
2026-08-20 batches before it; `results/roofclf_random_validation_log.csv` carries 40 rows with
every verdict column blank.
CLI: `--coverage-boot N` on `sub400-capacity`/`ge400-roof-capacity` (default 200; 0 disables and
narrows the reported interval), `--no-recall-correct` on either to reproduce the
pre-2026-08-15 flagged-population-only figures exactly.

Full derivation, every historical recalibration step, and every rejected instrument:
`docs/methods/density.md`, `docs/experiments.md`.

**Overture publishes a coastal admin division TWICE -- land, and land-plus-territorial-waters
-- and nothing used to deduplicate them** (found 2026-09-13). Germany's admin layer came back
as **20 region rows for 16 Bundeslaender**, the four coastal states (Niedersachsen,
Schleswig-Holstein, Mecklenburg-Vorpommern, Hamburg) each appearing as a perfectly-nested
pair. The evidence atlas listed each of them twice in "Provinces, ranked by capacity", and
because the province join is a **cell-centroid point-in-polygon**, 1,152 of 4,656 cells matched
both rows of a pair: the province column summed to **29,559 MWp against a national 24,687**, a
19.7% double-count. Headline totals are summed from the grid, not from the provinces, so no
published total moved. **Keep the LAND polygon, which is the SMALLER of a nested pair** -- a
"keep the largest" dedup picks the wrong one every time. Germany's 16 kept polygons total
357,649 km² against its actual 357,596 km² of land. `density.drop_nested_duplicates` (applied
in `load_admin` at both levels, and repeated on read by `atlas._region_rows` so an
already-written `regions.geoparquet` cannot reintroduce it) tests **nesting**, not name
equality, so genuinely distinct same-name divisions survive -- verified against Gujarat's seven
repeated district names, which are disjoint. Only Germany was affected: every other AOI's admin
layer came from geoBoundaries, which has no maritime rows.

### One atlas template, one config file per country (`configs/atlas/<aoi>.yaml`)

**The Pakistan atlas IS the template, and since 2026-09-20 everything country-specific in it
lives in `configs/atlas/<aoi>.yaml` instead of in the builder.**
`templates/pv_evidence_atlas.html` was always shared, but the prose inside it and inside
`build_evidence_atlas` was written for Pakistan and shipped verbatim to every other country.
Germany's, France's and Zambia's published atlases each told their readers that **Pakistan's
NEPRA net-metering register** put "registered rooftop solar at 5.3-6.3 GW nationally" as
independent corroboration of THEIR headline figure, carried Pakistan's measured
124 bldg/km2 density-sparsity caveat, linked Pakistan's composition page, and rendered
"All **0** quadrats behind the small-panel instruments were chosen by a researcher". None of
it failed a build, and none of it was visible from the Pakistan page it was written for.

`atlas_config.load(aoi)` supplies `title`, `cities`, `calibration_boxes`, `composition_page`
and three optional confidence blocks (`ground_truth`, `caveats`, `corroboration`). A missing
file is normal and means a complete page minus the sections that need local evidence; a
malformed one is an error, including an unknown key, since a typo would silently drop the
section it was meant to fill. `CITIES` and `CALIBRATION_BOXES` are gone from `atlas.py`.

Two builder functions replace what used to be one Pakistan-shaped string literal:
- **`_confidence_html`** gates every claim on the thing that makes it true: the
  quadrat-resampling bullet on an actual coverage bootstrap (Germany's roofclf half is fitted
  against its register and has none), the purposive-sampling and Rule-1-epoch bullets on
  actually having quadrats, the corroboration paragraph on the AOI supplying one. It also
  derives two counts that were written out as words and were only ever right for one build
  ("three specific ... sources", "two unrelated data sources").
- **`_composition_note`** derives the "which method supplies most of Best" sentence from the
  page's own components, mirroring the template's `compRows()` grouping, instead of asserting
  roofclf on a country that has no roofclf half. Zambia's page said roofclf supplied most of
  its Best estimate; it is segmentation-only.

`_load_calib_boxes` now looks in `data/labels/<aoi>/` before `data/labels/`, so France's 14
hand-mapped communes are drawn on its own map without being moved into the flat directory
that feeds Pakistani roofclf refits.

**`scripts/check_atlas_templates.py` fails CI** if a published atlas names another country in
its visible text (scripts, styles and comments excluded) or links another country's page. A
country's OWN config may name another on purpose, which is how Germany's page compares its
48.4% municipal error to Pakistan's 26.5%, so config-supplied strings are removed before the
check. Verified against the pre-fix Germany page: it catches both the NEPRA prose and the
composition link.

Germany, France and Zambia were rebuilt and republished on this template 2026-09-20. **No
total moved** (Germany 26,635 / 88,709, France 12,382 / 13,369, Zambia 505.8 / 526.3 MWp);
only prose, map annotations, the composition sentence and the template features those pages
had been built too early to receive. Pakistan's own page changes by two sentences: the
composition note gains real percentages, and the intro drops one now-derived word.

**Still carrying Pakistan-only prose and hardcoded links: `pv_growth_atlas.html` and
`pv_size_atlas.html`**, which are not covered by the guard because only evidence atlases are
published per country today. A second country's growth atlas would reintroduce exactly this
bug.

### The evidence atlas page: MapLibre GL + Observable Plot (2026-10-19)

**The map is MapLibre GL JS 5.24 and the charts are Observable Plot 0.6.17 on D3 7.9**, loaded
from jsDelivr at exact versions with SRI hashes (the hand-drawn SVG map could not pan, zoom,
take a basemap or another layer, and nothing was exportable). **MapLibre 5, not 6**: v6 is
ESM-only with a separate module worker, which does not load from a CDN into a `file://` page or
an iframe. Offline, the page degrades rather than breaks: hero, KPIs, tables, the composition bar
and the pose plot are plain SVG/HTML and still render; the map and the three Plot charts say
they could not load.

- **Map**: "Show" picks the cell quantity (Best, *Not yet in OpenStreetMap* = Best minus
  hand-mapped, hand-mapped, model >= / < 400 m2); "per km2" divides by cell area; the log
  colour scale is refitted per quantity (2nd percentile to max). Basemaps: none (night
  lights), Esri grey canvas (follows the theme), OpenStreetMap, Esri satellite. Over a basemap
  the fill fades with zoom and hands over to capacity-coloured cell outlines, so imagery shows
  through at roof scale. **CARTO basemaps were tried and dropped: unkeyed requests now get an
  "API KEY REQUIRED" tile.** City labels are HTML (no glyph server), calibration areas are
  diamonds drawn into a canvas icon (a round marker read as one more city).
- **More layers**: an opt-in *live OSM solar* overlay queries Overpass for the view from zoom
  11 (overpass-api.de, then private.coffee; **a mirror lagged three months**, so the status
  line shows the OSM timestamp returned, and a query takes ~30 s); readers add GeoJSON/CSV
  files (drop on the map), GeoJSON URLs, XYZ tiles or a WMS (`{bbox-epsg-3857}`), URL layers
  persisting in localStorage; and a country can ship layers in `configs/atlas/<aoi>.yaml`
  (`layers:`, schema in `atlas_config`), embedded by `atlas.map_layers_json` (5 MB cap) into a
  `pv-layers` block kept separate from the `pv` data block.
- **Downloads**: every figure as PNG (2x), SVG and CSV, the map as PNG (legend, labels and
  attribution composited in) plus the grid as GeoJSON/CSV. Exports are re-rendered at 960 px
  and wrapped with title, subtitle and a source/date line, never serialised from screen.
- **New section: uncertainty**, a forest plot of each Best component's point and 90% interval
  on a log axis, from the same `uncertainty.components` the headline CI is composed from.
- **Colour means method everywhere**: OSM teal, segmentation blue, roofclf amber,
  roofclf+SPPI violet, farm ground PV green (2026-10-24); hatching means ground-mount everywhere (the size chart now stacks with
  hatched ground). Before, blue meant OSM on the map, segmentation in the composition and
  ground-mount in the size chart. Dark `--large` moved #4fb2e8 -> #5b9cf2: against the OSM
  teal it measured dE 13.6 for normal vision, under the floor of 15.

**Plot gotchas, each hit once here**: on a log scale Plot routes any `tickFormat` through d3's
log formatter, which blanks every tick with mantissa > 2 (draw the labels with a text mark);
a `{value, label}` channel object as `barX`'s `y` breaks the implicit stack and the bars
vanish (rename the field instead -- a tip labels a channel by its field name); `grid: true`
on a scale plus a `gridX` mark draws two grids with different ticks.

**`scripts/retemplate_atlas.py` moves published pages onto a new template without rebuilding
them.** It recovers each placeholder's value by aligning the page with the template it was
built from (`--old-template <git rev>`, default HEAD), proves the split by substituting back
and comparing, then fills the current template; only `__LAYERS_JSON__` is computed fresh, from
config. The 11 published pages were moved this way and their `pv` data blocks and confidence
prose are byte-identical to before. **After a template commit, pass the revision the pages were
last built from**, not HEAD. A rebuild through `earthpv atlas` was checked against it on Yemen:
same totals and interval.

**Re-template the SYNC SOURCES too, not only `docs/assets/interactive/`.** Most published
atlases are copies `build_docs_figures.sync_interactive` makes from `results/<aoi>_pv_evidence_atlas.html`
(Germany from `data/predictions/germany/density/`); CI cannot see those gitignored sources, so the
committed copies are what ships, but a local `pixi run docs-figures` copies the sources over
them. The 2026-10-19 template move re-templated only the docs copies, and the next local
docs-figures run would have reverted all ten pages to the old template; caught and fixed
2026-10-20. Also expect `docs-figures` to rewrite ~50 SVGs whose only change is matplotlib's
timestamp and random clip/image ids: revert those, keep only real content changes.

**`scripts/screenshot_pages.py` drives Firefox over WebDriver BiDi** (a stdlib WebSocket
client) instead of `--screenshot`, which fires at the load event and captured an empty WebGL
map. A Shot can name a `ready` expression; the atlas sets `data-atlas-ready` on `<html>` once
its map has drawn a complete frame. The atlas iframes on the docs site carry
`allow="fullscreen"` (`build_atlas_pages.py`), or the map's fullscreen button does nothing.

**Calibration areas open in JOSM or iD from the atlas (2026-10-20).** Clicking an area, or a
hollow-diamond candidate, offers **Open in JOSM** (Remote Control: `import` of the area's
published GeoJSON as a locked layer with `upload_policy=never`, then `load_and_zoom` into
its own layer with the protocol's changeset comment and `#tracethesun;#earthpv;#earthpv-calibration`),
**Open in iD** (`#gpx=<url>.geojson`, iD's never-uploaded custom-data layer) and a GeoJSON
download. A **Propose** map control drops a 2 km square on the next click (same corners as
`new_calibration_quadrat.geodesic_square` to < 0.1 mm), checks overlap against every
published area as `check_overlap` does, and labels it hand-picked. The boundaries are NOT
the embedded rings (rounded to ~100 m): `pixi run calib-publish`
(`scripts/publish_calibration_areas.py`) writes full-precision
`docs/assets/labels/calibration_areas/<aoi>.geojson` plus one `<aoi>/<stem>.geojson` per area
(configured boxes, candidates, and unlisted registered quadrats for the overlap check only),
and the page fetches its index at run time by `data-aoi-key` (`__AOI_KEY__`, which
`retemplate_atlas.py` fills fresh). So a new candidate reaches every atlas with a re-publish,
no rebuild. Re-run it whenever a quadrat or candidate is added or `calibration_boxes`
changes; `check_atlas_templates.py` fails CI on a configured box without a published file.
The iframes also carry `local-network-access; loopback-network` for Chrome's prompt on
requests to 127.0.0.1.

**Calibration candidates are sampled, not hand-picked (2026-10-20):**
`pixi run calib-candidates -- --aoi <aoi>` (or `--bronze`), i.e.
`scripts/propose_calibration_candidates.py`.
- **Strata:** the AOI's density grid is cut into 8 bands of equal building share, one
  candidate each.
- **Draw:** building-weighted random cells per band, from a seed derived from the AOI name.
  20 km spacing, one province each while possible.
- **Placement:** the box is put on VIDA footprints, with its own density within 25% of the
  cell's. 1 km boxes above 600 bldg/km², 2 km otherwise.
- **Imagery gate:** the oldest Esri World Imagery capture at the centre and corners must be
  no more than 12 months before `compose_window` start. It is read from
  `World_Imagery/MapServer/4/query`, the endpoint iD's imagery panel uses.
- **Output:** `data/labels/<aoi>/candidate_quadrats/`, with failures in `screened_out.csv`.
  `--replace` redraws only sampled candidates. Then run `calib-publish`.
- **Start-here boxes (2026-10-22, owner request):** `calib-candidates -- --bronze --priority`
  adds two PURPOSIVE 1 km boxes per Bronze AOI: among cells in the densest quarter of its
  buildings, the window with the most roof area in VIDA footprints >= 1,000 m2, as dense as
  that quarter's floor, 20 km apart, 5 km from sampled candidates, same imagery gate. Chosen
  on buildings only, never on a solar layer, and marked `selection: purposive: ...`; they
  raise the base rate, so the eight sampled boxes stay the representative set.
  `calib-publish` ranks a Bronze AOI's candidates (start-here by large-roof area, then the
  rest densest first) and the atlas draws `start_here` as a star with a *Start here* legend
  button. Ranked at publish, so the star moves on by itself once its box is registered.

**The community guide is the "Contribute Data" nav section**, `docs/contribute/`.
- Pages: `index.md` (overview; it keeps the `/contribute/` URL that the atlas popups,
  badges and README link to), `id.md`, `josm.md`, `report.md`, `maintainers.md`.
- Mappers report through a GitHub issue form, `.github/ISSUE_TEMPLATE/calibration-area.yml`.
  The popup's "Report progress" link prefills `area` and `country`.
- A screenshot still to be taken is a `<div class="shot-needed" markdown>` placeholder that
  names the target file. Replace the whole block with the image once it exists.
- The Silver and Bronze notes atop the atlas pages are `WARNING` + `HELP` + `CTA` in
  `scripts/build_atlas_pages.py`.

`new_calibration_quadrat.py --aoi <aoi>` registers outside Pakistan: it writes to
`data/labels/<aoi>/`, uses that AOI's admin files, and takes ISO3 and country from
`configs/aoi.yaml`. Pakistan stays flat, because a flat non-Pakistani box would join the
next Pakistani refit.



### Plausibility gate (`plausibility.py`, `earthpv check-density`)

The leads product has a human on every candidate; the capacity atlas has nobody, so a
false-positive mode that survives `p_real` reaches the headline number silently. Two per-region
checks, both from artifacts `density` already wrote: **ground-mount:rooftop capacity ratio**
(bare ground, riverbed, salt flat, rock and snow read bright and nothing constrains them to a
plausible host) and **single-cell concentration** (one 0.1° cell over 25% of a region means that
region's total is one blob, not a population). Both need `mwp_ground >= 50` so a tiny region's
ratio is not noise. `RATIO_CHECK_EXEMPT_REGIONS` exempts Gilgit-Baltistan from the ratio check
specifically (its real rooftop base rate is near zero, making the ratio structurally
uninformative there). Exit 1 = a region failed, 2 = `density` has not run. **Run it between
`density` and publishing** -- the docs CI *cannot*, since `data/` is gitignored, so this gate is
only as good as the operator invoking it.

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
`.github/workflows/docs.yml` on every push to `main` (i.e. every merged PR), not just commits
that touch doc-related paths -- a path filter here previously skipped rebuilds and was dropped
2026-08-18. **Every figure and embedded interactive page under `docs/assets/` is generated** by
`scripts/build_docs_figures.py` (`pixi run docs-figures`), which reads its numbers from tracked
files (`results/*.csv`, the atlas HTML's embedded JSON, calibration YAML) so the site cannot
drift from them -- edit the sources, not the SVGs. Local preview:
`pixi run docs-figures && pixi run -e docs docs-serve`. The build runs `--strict`, so a broken
internal link fails CI. Docs prose avoids em dashes and emoji.

**`mkdocs build --strict` does NOT validate URLs inside raw HTML, and this shipped a 404.**
It rewrites Markdown links for `use_directory_urls` but copies raw HTML through verbatim, so
`<iframe src="assets/interactive/...">` on a page served at `/data-registry/` resolved against
the page and 404'd while CI stayed green -- the Markdown CSV link on the same page was
rewritten correctly, which is why the source looked fine. A raw relative URL needs one `../`
per path segment of the page's own served URL (`index.md` excepted, it is served at its
directory). `scripts/check_docs_links.py` now checks every raw-HTML relative URL in `docs/`
for the right prefix and an existing target, and runs in the docs workflow ahead of the build.


**The PV Atlas pages are generated** (`scripts/build_atlas_pages.py`, 2026-10-19): one row per
country in `ATLASES`; each page's tier (Gold/Silver/Bronze) is read from the calibration badge
its own atlas carries (`atlas.VALIDATION_TIERS`), the switcher and the `--nav` block are grouped
by tier, and Silver/Bronze pages open with a missing-small-installations warning and a call to
map a calibration area. A new country is one row plus a rerun; never edit `docs/atlas*.md` by hand.
A tier that is a judgement rather than a fact about the files goes in `configs/atlas/<aoi>.yaml`
(`validation: {score, note}`, which beats `derive_validation_score` and is read by all three
atlas builders and `apply_validation_badges.py`). **Yemen is Silver since 2026-10-23** (owner decision, on registering Al Wehdah before anything
was fitted to it): its box carries `used: false` in `configs/atlas/yemen.yaml`, which keeps the
confidence section from claiming ground truth the figures do not use (the default prose, gated
only on having a box, said the page's accuracy checks rested on it), and
`build_atlas_pages.TIER_NOTE` has a Yemen note. Kept Silver 2026-10-24 when seven farm areas
went in as used boxes: they calibrate farm ground PV only, household rooftops below 400 m2 are
still unmeasured, and the config's own `confidence.ground_truth` replaces the default
Pakistan-shaped quadrat paragraph. **Germany is Silver since 2026-10-22**
(owner decision): its register-calibrated small half fails its own register check, so the
page carries a Germany-specific note (`build_atlas_pages.TIER_NOTE`) instead of the generic
"no estimate below the floor".

**Every evidence atlas shows an import ceiling** (2026-10-19, owner request): solar panels
imported from China from Jan 2017 to the end of the imagery window, from Ember's customs-based
export data (CC-BY-4.0). `scripts/ember_import_ceiling.py --csv <Ember monthly CSV>` writes
`configs/external/ember_china_panel_imports.yaml`; `atlas.import_ceiling(aoi)` puts it in
`totals.import_ceiling` and the hero shows Best as a share of it. India, Germany and France are
flagged `ceiling: false`, and so is Poland (domestic manufacturing; pre-2017 fleets and EU
imports via the Netherlands; Poland's fleet already exceeded its direct imports in 2025) and the page says why instead of calling it a ceiling. Re-run the script when a
new country's AOI is added, before its atlas is built. `docs/methods/validity.md` has the table.

Nav runs **Results → How it works → Setup → Experiments**, output first,
pipeline mechanics second, history last. `docs/experiments.md` is the canonical, dated register
of every experiment (shipped/partial/rejected/superseded) with links to the deep write-ups under
`docs/issues/`; `docs/open-questions.md` lists concrete, actionable open items and is
**excluded from the published site** (`exclude_docs` in mkdocs.yml, owner request 2026-10-18),
so no site page may link to it; the same list keeps the superseded Gujarat page, the never-run
Europe campaign plan and unlinked atlas snapshots off the site (2026-10-19) (an item is
removed once closed, moving to the experiments register with a verdict, not annotated in place).
Every surviving doc under `docs/issues/` carries a dated status banner stating whether it's
shipped, closed-negative, superseded, or still open, since several were written mid-investigation
and later reversed.

The site chrome (`docs/assets/stylesheets/extra.css`) shares its design tokens (`--pv-*`) with
the result pages it embeds -- keep both in sync by eye when the palette changes.
`docs/assets/javascripts/embed-theme.js` drives each embedded result page's own theme toggle from
the site's Material toggle. `scripts/screenshot_pages.py` (`pixi run docs-screenshots`) renders
the interactive HTML pages to PNG for the README; it needs a real (snap) Firefox profile staged
under `~/earthpv-screenshots/` (not `/tmp` or the external drive) and pins both
`ui.systemUsesDarkTheme` and `ui.prefersReducedMotion` (the atlas templates animate their hero
number with a count-up that a screenshot can otherwise catch mid-animation).

**The interactive "night lights" HTML style (dark glowing choropleth, KPI strip, tab switcher,
`<details class="xdetails">` methodology sections) is the default for any new results page.**
Reference implementation: `src/earthpv/templates/pv_evidence_atlas.html` (pipeline-native) /
`results/pakistan_pv_evidence_overview.html` (standalone-script version). A new standalone
script slices the shared CSS via matched string markers (see
`build_pakistan_pv_evidence_overview.py`'s `_slice`/`_shared_fragments`) rather than forking it
by hand. This supersedes static PNG/PDF figures for anything meant to be read interactively;
static figures stay appropriate only for the docs site's embedded `<img>`s and print/export
use cases.

`earthpv dashboard --aoi <name>` (bundles an AOI's HTML pages into one tabbed page) still exists
and works but is **not used by the current docs site** -- Results now just links directly to
each standalone artifact page.

### Calibration quadrats

**31 quadrats as of 2026-08-19 (three peri-urban screens -- Attock, Layyah, Lodhran --
the most recent additions), spanning Pakistan** -- purposive selections (industrial estates, dense residential blocks) plus several
deliberately-rural extensions used to widen the density-calibration domain (see "Density stage"
above). Bahawalnagar Rural's own building density (123.5 bldg/km², measured directly against
VIDA) came in below the prior domain floor (141.00 bldg/km², set by Khairpur Rural), so
`density.CALIBRATED_BLDG_DENSITY_KM2` was widened to (123.5, 5,258.00) alongside a fresh
`roofclf` re-fit and national rescoring that includes it (2026-08-13); see
`docs/issues/pakistan-calibration-boxes.md`'s Box 14. **Nasirabad Rural is this project's
first confirmed-zero quadrat** (48.5 bldg/km² own density, 0 installations after the owner
visually swept the imagery, not just an OSM/Overpass check -- the exact distinction that
made Muzaffargarh Rural Wide's original "confirmed zero" wrong; see Box 15) -- its density
is lower than Bahawalnagar Rural's, so the floor moves again, to 48.5. Tank Rural (Khyber
Pakhtunkhwa, 55.75 bldg/km², 10 installations) sits inside the widened range without moving
it further, and is KP's first rural-extension quadrat (Box 16). Both are folded into a
fresh `roofclf` refit and national rescoring alongside this second widening (2026-08-13).
**Kalat Rural (2026-08-17, Box 17) is registered and Rule-1 but must be kept OUT of any
`roofclf` refit until `building_table`'s roof term gets a placement/size guard.** It was
sited deliberately to include ground-mount, and 22,064 m² of its 28,412 m² of mapped PV is
ground-mount at or above the 400 m² floor -- against 18,919 m² of VIDA roof area in the whole
box. `parcel_pv_area` skips such installations (its rule 3); the roof term does not, so
**69 of the 89 buildings it labels has-PV are labelled solely because a ≥ 400 m² ground array
clips them** (21.24% base rate at 46.5 bldg/km², higher than Mardan's). Folding it in would
fit the sparse band's coverage ratio on ground-mount and double-count against segmentation's
`est_mwp_rc_ground`. `roofclf.discover_quadrats` globs the label directory, so the next
`earthpv roof-classifier` run picks it up automatically -- see `docs/open-questions.md`'s
item 2. Its move also cost it its purpose: sited at 25.9 bldg/km² and moved to 46.5, it now
sits 1.7 below the domain floor and widens it from 2,957 to 2,997 cells (66.3% -> 67.2%)
instead of the 3,609 (80.9%) the original location would have reached.
**Three peri-urban screening boxes were added 2026-08-19** -- Attock (894.75 bldg/km² own
density, 54 installations), Lodhran (237.25, 36 installations) and Layyah (146.00, 17
installations), all Punjab, all-sub-400 m² populations, none moving the density floor (all
sit well inside the existing 48.5-5,258.00 range). Registered from six candidate screening
boxes total; the other three (Mardan, Shikarpur, Sialkot District) were dropped before
mapping for stale/unusable imagery, the same gate Box 17 identifies -- see
`docs/issues/pakistan-calibration-boxes.md`'s Box 18. **Update 2026-08-20: the owner declared
all three Rule-1**, and they were folded into a fresh `roofclf` refit the same day (30
quadrats -- every discoverable quadrat except Kalat Rural, which stays excluded per its own
entry above). Median fold AUC moved 0.8735 -> 0.8574 (27 -> 30 quadrats); the density-
calibration domain itself did not move (still 2,957/4,463 cells, 66.3%, 48.5-5,258.00
bldg/km², confirming none of the three widens it as expected). Pre-refit model/tables kept at
`data/roofclf_PRE_box18_20260820/` for comparison.
Every quadrat through Kalat Rural, plus these three as of 2026-08-20, is declared **Rule-1
complete** by the owner (every visible panel mapped) --
**Rule-1 is epoch-relative**: it certifies completeness against the mapping imagery's own
(usually unrecorded) capture date, not against the Sentinel-2 composite's epoch, so the newest
installations are structurally missed regardless of mapping effort. This makes precision and
`base_rate` **lower bounds** and `rate_ratio` an **upper bound**; recall over mapped
installations is unaffected. `scripts/new_calibration_quadrat.py` is the tool for adding one
(geodesic square or hand-drawn `--geojson`) -- it checks for boundary overlap with every existing
quadrat before writing anything, and a live Overpass pull is cross-confirmed against a second
query before being trusted (mirrors have intermittently returned truncated, non-error responses).
**Ranking transfers across quadrats; absolute adoption rates do not** (`rate_ratio`, i.e.
predicted/true adoption rate, has spanned 0.2-5x across the quadrat set) -- this is why
`roofclf`'s per-stratum coverage-ratio correction exists rather than a single pooled precision
number. `select_calibrated_quadrats` picks the precision-trusted subset (`rate_ratio` inside
roughly [0.5, 2.0]) independently of Rule-1 status and independently of the density-domain
selection above; both gates must be checked separately for any new quadrat.

Full per-quadrat table and status: `docs/methods/calibration-quadrats.md`. Dated history of
every addition/correction/withdrawal: `docs/issues/pakistan-calibration-boxes.md`.

### Farm ground PV: `roofclf_ground` and farm calibration areas (2026-10-23)

A footprint-free pixel detector in the roofclf family for small arrays beside fields
(solar pumps), which neither instrument above sees: in Yemen's 'Amran test ground only
6.6% of the owner-traced array area lies on a VIDA footprint, and segmentation found 0
(v13) / 4 (v5) of 283 arrays of any size. `src/earthpv/roofclf_ground.py`:

```bash
pixi run calib-candidates -- --aoi <aoi> --farmland          # cropland-stratified 3 km boxes
earthpv roofclf-ground --aoi <aoi> --clean-region <b.geojson> --weak-region <b.geojson>
earthpv roofclf-ground-score-national --aoi <aoi>             # blobs per cell, resumable
earthpv roofclf-ground-capacity --aoi <aoi> --osm-solar <national OSM pull>
```

- **In the atlas since 2026-10-24, a standard field on every page**: `earthpv atlas
  --ground-cells <ground_cells.parquet>` adds `small_ground` (farm ground PV < 400 m2) to Best
  in the detector's calibration domain only, beside roofclf's rooftop `small_central`, as its
  own tile, map quantity, hover row, province column, composition and uncertainty row, in
  green (#68a800 / #245c00, hatched). Without it a page says "not measured"
  (`totals.small_ground_status.measured: false`), never 0. Interval: module draw x the
  replicates `roofclf-ground-capacity` writes per region (see the domain bullet below),
  labelled on the page from the summary's `interval`; `atlas.GROUND_MIN_AREAS` /
  `GROUND_JUDGEMENT_CI90` only serve a summary that predates it. Run `roofclf-ground-capacity` with
  the SAME `--osm-solar` file the atlas counts, and `--roofclf-buildings` where a roofclf
  half exists (a blob within 20 m of a priced building is its yard array). Yemen: 32.7 MWp
  on 'Amran alone (Best 67.1 -> 99.8), then 169.1 MWp on seven areas (Best 302.1). The 11 other published pages were moved onto the template with
  `retemplate_atlas.py`, data blocks byte-identical; they had been built from HEAD's
  template minus 8331c25's star-icon and start-here wording, which reached them by hand
  edit, so no git revision reproduced them and the old template was reconstructed.
- **A calibration domain PER REGION** (`roofclf_ground.domain_cells`, 2026-10-24): a cell is
  priced with a region's ratio only if its cropland share, building density AND median
  elevation (Copernicus DEM, `cell_elevation`, cached in `data/cells_cache/<aoi>_elevation.parquet`)
  each lie within x/÷1.25 of that region's areas; a region = areas sharing the `region`
  property on their boundary. The headline is `est_mwp_in_domain`; the all-cells figure
  (pooled ratio) is reported only as `est_mwp_all_cells_extrapolated` and is not on the
  page. History: no domain put the first smoke test on Al Hudaydah's city and coast; one box
  around ALL areas, once Tihama joined 'Amran, held 289 cells of highland terraces (Ibb,
  Sana'a, Ta'izz) at Tihama's ratio (1.19 against 'Amran's 0.17) and reached 3,532 MWp,
  above Yemen's 2,848 MWp import ceiling; per-region boxes without elevation 2,366 MWp.
  Interval: `region_ratio_draws` bootstraps each region over its own areas from
  `BOOT_MIN_AREAS` (3), else a stated x/÷2 (`JUDGEMENT_CI90`), and the summary's `interval`
  names which; the atlas uses it as is. Blobs inside a registered farm area count nothing
  (completely mapped; `--labels-dir`).
- **Farm quadrats carry `_farm_calib_` in their stem** (`roofclf.FARM_QUADRAT_INFIX`;
  `new_calibration_quadrat.py --farm`). `roofclf.discover_quadrats` skips them unless
  `farm=True`, because a ground array would label the farmhouse beside it as PV-carrying
  (the Kalat Rural problem). Overlap checks and `calib-publish` still see them.
- **A mapped polygon is priced by its tag** (`roofclf_ground.panel_area_factor`, owner
  decision 2026-10-24): `power=generator` is the array; `power=plant` is a site, counted at
  0.05/0.18 of its area (the land constant, as Verified prices it), or 0 when a generator
  inside it carries its panels; nodes count 0. **`osm_panel_tracers`** (configs/aoi.yaml,
  Yemen: the owner's account) names mappers whose polygons are panel traces whatever the tag:
  `labels.panel_traced`, written as `panel_traced` by `prepare_national_osm_solar.py`, and the
  evidence atlas then prices those ground polygons at the MODULE constant in Verified (and in
  `_evidence_uncertainty`, via `osm_ground_traced`). Matched on last editor: pulls carry
  `osm_user`/`osm_version` since 2026-10-24 (`overpass.element_meta_by_id` annotates older
  files). Every other country has no tracers and does not move. Yemen: Verified 65.9 -> 130.9
  MWp on the 2026-10-24 pull, ~42 MWp of it this pricing.
- **Two label sources.** Clean areas (farm quadrats, `--clean-region`: every installation mapped)
  give precision, the deployment threshold and the capacity ratio. Weak areas
  (`--weak-region`: ordinary OSM, oversized rectangles and nodes) train only, as
  multiple-instance bags. Tihama's UNGSC rectangles, useless as masks (they are why v13
  learned nothing in Yemen), give held-out bag AUC 0.934 this way.
- **Thresholds are logits**, not probabilities: a balanced fit puts strong detections at
  p = 1.0 in float32, which ties exactly the leads a reviewer should see first.
- **Vetoes, each measured on 'Amran's reviewed leads**: >= 30% of a blob within 8 m of a paved
  OSM road (9 leads, 0 mapped arrays lost); SWIR more than 20% below the blob's ring, i.e.
  water-harvesting ponds (11 leads, 0 of 301 mapped arrays; MNDWI fails, ponds read dry in a
  dry-season median); no pixel within 50 m of a building, cropland or green pixel; a blob
  over 25,000 m2 (`MAX_BLOB_M2`, 2026-10-24: 87% of Yemen's national detected area was in
  sheets of 5,000 m2+ on lava fields and rock, the largest 61 km2; the largest mapped farm
  installation is 22,231 m2, the largest calibration-area detection 16,000 m2).
- **The capacity estimand defaults to arrays below 400 m2** (`--max-array-m2`, roofclf's
  floor), but 88% of 'Amran's array AREA is at or above it and segmentation misses that too;
  `--max-array-m2 0` prices every size.
- **Overpass is a dependency, cached so it is paid once**: area labels in
  `data/roofclf_ground/<aoi>/areas/`, paved roads per whole 1-degree chunk in
  `data/roads/<aoi>/`. National scoring never calls it: the road veto is a vector overlap the
  capacity step applies, fetching only chunks that hold a blob (or `--roads <parquet>`). A
  chunk that cannot be fetched leaves its blobs with `road_checked=False`, reported in the
  summary, never silently.
- **Farm candidates exist for Yemen, Egypt, Morocco, India, Pakistan and South Africa**
  (8 each, published 2026-10-23); `calib-publish` ranks them after every building box, so
  drawing them never reorders those. Pakistan has no `compose_window` or `division.iso3` in
  `configs/aoi.yaml`: the sampler takes `--window-start 2025-11-01` (compose's default when
  its composites were built 2026-07-04; the files carry no window tag) and the ISO2 fallback.
- **Yemen (2026-10-24): seven farm areas, 169.1 MWp (90% 77 to 327) in 34 cells.** 'Amran
  (`amran_huth_farm_calib_129p53km2`, the whole test ground) and six Tihama areas cut from the
  owner's `Yemen-mixed-labels.geojson` boundary where Esri imagery is from 2024-10-01 on
  (Esri shows the newest capture at a point; checked on 552 points), along the 0.1-degree
  grid (331.6 of 530.6 km2); the rest is a training-only weak region,
  `data/labels/yemen/tihama_stale_imagery_region.geojson`. Refit: threshold 9.17, pooled
  precision 0.55 at 39% array recall; the detector finds 60% of 'Amran's arrays and 6-50% of
  each Tihama area's, which is why Tihama's ratio is 1.19. A sample of 12 Tihama UNGSC
  rectangles on Esri April 2025 imagery: all hold panels (2-4 small groups, ~10-25% of the
  rectangle), missed ones mostly among orchard trees. Tihama's areas surround a hotspot, so
  its ratio on the rest of the lowland is the soft spot. Pre-refresh outputs:
  `/home/tobi/earthpv_data/yemen_PRE_osmrefresh_20261024/`. Analysis, leads and the owner's
  review of the first run: `results/yemen_agripv_testground/`.

### Glint

Sentinel-2's specular-glint response (a panel briefly outshines diffuse reflectance at the right
sun/view geometry) is a secondary, corroborating signal, not a standalone detector. Current
state:
- **Direct per-target detection** works and is used to boost (never demote) `rank_score`:
  detection rate rises from ~6% to ~73% with installation size; validation plateaus around
  26-31% for arrays ≥ 1,000 m². See `docs/methods/glint.md`.
- **Per-pixel SCL cloud masking is shipped** (`glint.py`'s `_read_target_scl`): a per-scene,
  whole-image cloud-cover cutoff couldn't see localized cloud over one target, which SCL's
  per-pixel classification can. Gated on the annulus, not the target (a real glint is often
  itself saturated-bright, which SCL also flags as cloud).
- **Tile copies count once, and asset URLs are re-signed per read (2026-10-22).**
  Overlapping MGRS tiles deliver one pass as 2-4 items about 14 s apart, and the
  minute-keyed dedupe in `tile_scene_series_batch` kept both, so one glint counted as two
  consistent dates. `annotate_spikes` now collapses them (`one_row_per_acquisition`), and
  `dedupe_items=True` avoids fetching them. The fix took Pakistan's pose survey from 346
  to 336 fits, and the atlas pose section from 290 to 281 of 2,000. The 662-candidate
  `p_unmapped` sample is uncached and unchecked (open question 2, "Pakistan's segmentation calibration table is stale in four known ways"). `glint._asset_href`
  re-signs Planetary Computer URLs at open, because the client keeps a 45-min token until
  under 60 s is left, which was the silent scene loss in long pulls.
- **Opportunity-normalized glint sensitivity is shipped** (`src/earthpv/glint_opportunity.py`):
  a target's glint-validation rate depends on how many geometrically-compatible scenes it got
  a chance to be seen in, not just its size bin, so the capacity calibration's inversion now
  models `k ~ Poisson(q_b * opportunity)` instead of dividing by a flat per-bin sensitivity
  constant.
- **Rejected**: using a predicted "optimal glint date" to boost the small-rooftop `roofclf`
  classifier (only 1-2% of a plausible installed population can ever satisfy the specular
  geometry on any single date -- a sensor/calendar ceiling, not fixable by processing), and
  mining `roofclf` hard negatives from glint-absence at large non-OSM-mapped roofs (the mined
  set was cleaner than expected but too small -- ~126 usable negatives per ~45 min of pulls --
  to move a 104k-row fit). Both fully written up in `docs/experiments.md` and
  `docs/methods/glint.md`.

### MaStR validation (Germany)

`mastr_validation.py` / `earthpv validate-mastr` is the project's one externally-verifiable
check against a legally-complete register, since Germany's MaStR is mandatory registration
rather than a sample -- the one thing purposive, owner-attested Pakistani quadrats can never be.
Key results: **65.5% of German rooftop capacity sits below the 400 m² / 72 kWp detection floor**
(97.2% of installations by count -- quote the capacity share, the count share overstates the
gap). That share is **not safely transferable as a flat constant**: it varies 0.25-1.00 across
municipalities (5th-95th percentile) and correlates negatively with a municipality's own total
capacity (large industrial roofs pull the share down), so the capacity-weighted national figure
(0.655) sits meaningfully below the simple across-municipality mean (0.724). German OSM cannot
serve as an independent completeness reference for calibrating the module constant (only ~3.6%
of registered rooftop units are mapped in OSM at all, and the well-mapped tail's implied
kWp/m² swings 0.02-0.99 depending on mapper convention) -- this was tested and is a measured
negative result, not a blocked one; `DEFAULT_KWP_PER_M2_MODULE` stays as independently
calibrated.

**The end-to-end per-municipality comparison RAN nationally 2026-08-31** (it was blocked until
then on composites and a building layer; both were acquired 2026-08-23 -- 4,656 composited cells,
`data/vida/DEU.parquet` 27.9M rows). Coverage 10,533/10,949 Gemeinden = **96.2% by count, 99.75%
by capacity**, so `validate_density_against_mastr` reports it as national rather than refusing.
Read the **above-floor** block (truth = `kw_rooftop - kw_le_72` = 25,723.5 MWp, what a ≥400 m²
model can see), not the all-capacity one.

**A register also works as a precision instrument, and this is where it gets interesting**
(`scripts/mastr_p_unmapped.py`, `calibrate-candidates --mastr-p-unmapped`, 2026-09-01). MaStR
publishes per-unit **coordinates** only at/above 30 kWp -- 0.00% of the 4.17M units below that
carry one (a privacy policy, not missing data; the same field is 80% filled for ground-mount),
rising to 99.7% at/above 72 kWp. So a registered unit's address point falling *inside* an
unmapped candidate polygon is direct evidence that candidate is real, for exactly the population
segmentation targets -- and the register is structurally silent below the floor, i.e. over
`roofclf`'s entire domain. **A complete register therefore improves the instrument that already
worked and does nothing for the one that needed help most; it does not remove the need for
mapped quadrats.** Germany still has **zero** calibration quadrats and so no roofclf half.

Measured rooftop `p_unmapped` (chance-corrected, per placement): 0.061 / 0.107 / 0.213 / 0.514 /
0.759 across the 100-500 → >50k m² bins; ground 0.000-0.247. The table previously shipped
`p_unmapped: 0.0` everywhere. `derive_placement_tables` gained an opt-in
`p_unmapped_by_placement` for this -- its docstring declined to split `p_unmapped` only because
the *glint* sample never recorded a placement, which a geolocated register does. Omitting the
argument reproduces the old behaviour exactly, so **Pakistan is unaffected** (verified by
regression check). `_table_evidence` now carries `register-p-unmapped`, so a bare
`calibrate-candidates` re-run is refused rather than silently discarding it.

**THE CHANCE TERM MUST BE LAND-USE MATCHED -- this was got wrong once.** A displaced control
(polygons moved 500-1,000 m on a random bearing) puts the false-match rate at 0.3-2.3%, but
displacement can land a polygon in farmland, measuring how empty the countryside is rather than
how often a false positive captures a neighbour's unit. The right null is the base rate among
buildings the model did **not** detect, same imaged cells, same size bin: **2.2% (n=48,841) /
9.1% (n=24,967) / 17.6% (n=2,119)** for 500-1k / 1k-5k / 5k-50k m². Large German roofs carry
registered PV often enough that containment alone is weak evidence. Candidates still run 2.8-4.8x
above that null so the signal is real, but the naive version overstated `p_unmapped` by 10-25%.
Correction is the mixture `(obs - f) / (1 - f)`, and the result stays a **lower bound** (S < 1).
`>50k` keeps the displaced control (VIDA footprints that large barely exist, n=17); ground keeps
it throughout, since "an undetected building of this size" is not the right null for ground-mount.
**Rejected**: dividing by an OSM-mapped positive control the way the glint inversion does --
German OSM rooftop PV is the 3.6%-complete enthusiast-mapped tail, which skews below 30 kWp and
so carries no coordinates, making the control contaminated by the very suppression it should
absorb (rooftop S=0.435 on n=200 vs obs=0.599 on n=4,417; it inverts).

**Fixing `p_unmapped` exposed a second, opposite error: `est_mwp_rc` was far too high.** Two
errors had been cancelling. `est_mwp_cal`'s slope moved 0.038 → 0.167 (better bounded, still far
from 1.0); `est_mwp_rc_roof` moved 0.262 → 3.11, from understating to overstating ~3x.

**FIXED 2026-09-02, and the cause was not the obvious one.** `derive_placement_tables` restricted
BOTH sides of the recall measurement by placement: a rooftop reference installation only counted
as found if the finding candidate was also classified `rooftop`. Precision and recall are
asymmetric -- `mapped_frac` asks "is THIS candidate real" (so placement matters), `recall` asks
"was this real installation detected AT ALL" (so how `postprocess` labelled the finder does not).
Rooftop recall, same-placement vs any-candidate: 5k-50k **0.096 → 0.693** (7.3x), >50k
**0.036 → 0.852** (23.9x). Mechanism, which explains why the error grows with size: a large array
overruns its imagery-derived VIDA footprint, `building_overlap_frac` collapses, and the candidate
that correctly found a rooftop array is classified `ground_adjacent`/`no_building` -- the same
undersizing the parcel label exists to handle. `1/recall` then inflated it up to the 20x
`DEFAULT_RECALL_FLOOR` clamp. Two hypotheses were measured and **refuted** first: oversize
`rooftop` reference features (they recall at 0.841, same as the rest) and count-recall applied to
area (ratio 1.01-1.08).

**PAKISTAN IS AFFECTED and its published numbers are overstated.** Same code, no register to
notice: rooftop recall moves 0.423 → 0.808 (5k-50k) and 0.065 → 0.952 (>50k), ground 0.107 → 0.417
(500-1k). Pakistan's figures come from the checked-in `pakistan_candidate_precision.yaml` and do
**not** move until that is deliberately re-derived (which needs `--glint-sample` and the
calibration boxes, per "The checked-in calibration YAML is load-bearing" above). Re-deriving it
will lower `est_mwp_rc` and therefore Best estimate. Not done -- an owner decision.

**After the fix `est_mwp_rc_roof` is Germany's readable estimator at slope 0.405** -- the best
calibrated of the four (exp 0.388, det 0.340, cal 0.167; det/exp are unchanged throughout, the
sanity check that neither uses recall). Nationally `est_mwp_rc` went 114,145 -> **24,687 MWp**.

**Germany's evidence atlas tier totals must not be quoted as capacity.** The 118%
ground-mount figure once recorded here described a computation the atlas no longer performs:
it keeps only OSM features whose representative point lands in a building-populated grid cell,
so the national OSM sum (65.9 GWp at the assumed constants) is not what Verified reports.
**Measured 2026-09-13 against MaStR**, the assumed constants are wrong in the opposite
direction for ground: matching geolocated register units into dissolved OSM polygons gives
**0.081 kWp/m2 for ground against the assumed 0.050** (1.62x, i.e. too LOW) and 0.081 against
0.180 for rooftop (a biased sample: 5.2% coordinate coverage, >= 30 kWp skewed). The real
data-quality problem is the ground POPULATION: **73% of German OSM ground area contains no
registered ground unit**, and corroboration is exactly **0% above 5 km2** (21 polygons, 33% of
ground area, largest 88.3 km2 against a largest real German park of ~5 km2).
`prepare_national_osm_solar.py` now drops ground features above 5 km2 -- prophylactic, since
all 21 already fall outside the density grid and Verified was 38,508.1 MWp with or without them.

**RECONCILED 2026-09-13, and the overstatement was ROOFTOP, not ground.** Replicating the
atlas's exact in-grid population: ground assumed 17.97 GWp against 19.82 GWp of register
capacity actually inside those polygons (**ratio 0.91, fine**), rooftop assumed 20.54 GWp
against ~8.2 GWp (**~2.5x over**). The cause is that an OSM rooftop polygon is a different
object at different sizes. Measured on the 2,780 polygons containing EXACTLY ONE registered
unit (unrestricted, sub-200 m2 polygons appear to carry an impossible 0.63 kWp/m2 because they
collect neighbours' address points): **<200 m2 0.200, 200-500 0.189, 500-2k 0.139, >2k 0.051
kWp/m2**. 4,694 polygons above 2,000 m2 hold 101.2 of 122.4 km2 of all OSM rooftop area, so the
flat 0.18 turned 8.8 GWp into 22.0.
`capacity_calibration.osm_rooftop_kwp_per_m2` applies the table, **keyed by AOI** --
Pakistan/France/Gujarat/Punjab/None all return the flat 0.18, verified not assumed. Germany's
tiers move to **Verified 25,921 / Best 87,743 MWp** (then **26,635 / 88,709** after the
2026-09-15 no-filter grid rebuild and the national OSM border clip, **Best 84,473** since the
2026-10-20 OSM combination fix) and both placements now sit within ~10% of
the register. Only `build_evidence_atlas` uses it; `_size_distribution_data` still uses the flat
constant deliberately, so the headline and the size chart cannot disagree silently.

The underlying cause is mapper convention, which was already a documented negative result
here: German OSM polygons outline roofs and sites rather than arrays, and the implied kWp/m²
spans 0.02-0.99 against 0.18. What the size-dependent table adds is that the convention varies
*systematically with polygon size*, which is what makes it correctable rather than merely noted.
`scripts/prepare_national_osm_solar.py` builds the `--osm-solar` input (a raw rooftopsenti pull
has no `placement` column); it maps `small` -> rooftop (a SIZE class, 114k features) and caps
`rooftop` at `MAX_CANDIDATE_M2`, reclassifying 494 features up to 4.19 km² as ground so they
convert at the land constant.

**GERMANY NOW HAS A roofclf HALF, CALIBRATED FROM THE REGISTER RATHER THAN FROM QUADRATS
(2026-09-13).** Germany has no exhaustively mapped calibration boxes, and mapping some looked
like the prescription. It is not the binding constraint. The classifier ranks German roofs
adequately on OSM labels (0.824 AUC); what 3.6%-complete labels cannot do is fit a
`coverage_ratio`. They do not have to: **the estimator emits a per-area aggregate and a complete
register publishes exactly that per municipality**, so the calibration is one constant, kWp per
unit of credited roof area, fitted against MaStR across 9,674 fully covered Gemeinden.
`vg250_gem.parquet` (10,949 municipality polygons, joins to MaStR on AGS) is what makes this
possible. The 30 kWp coordinate cliff blocks `p_unmapped`, i.e. precision; it does not block
calibration.

Result over all 4,656 cells and 25.0M assessable buildings: **0.2793 kWp/m2 (90% 0.2654-0.2926),
national 52.37 GWp against a registered 54.29 (0.96)**, median municipal error 48.4%, rho 0.825.
The national extrapolation is a real out-of-sample test -- the constant is fitted only where the
grid fully covers a municipality, then applied countrywide -- and the 4% shortfall is reported,
not absorbed. Scripts: `scripts/run_germany_roofclf_production.py`,
`scripts/calibrate_germany_capacity.py`, `scripts/validate_sub400_against_mastr.py`.

**THE BEST TRAINING MIX WAS MEASURED, AND THE FRENCH BORDER SET IS THE ONLY FOREIGN DATA THAT
HELPS.** Leave-one-German-quadrat-out: Germany only 0.8240 AUC / 0.7290 within size band,
**Germany + France border (cadastre + OpenPVMapper, 29 Alsace/Moselle communes) 0.8372 / 0.7546**,
Germany + France national 0.7384 / 0.6359, France border alone 0.7828 / 0.7152. Adding the
border set helps; adding the national French set **hurts by 0.086 AUC**. Proximity, cadastre
footprints and swamping (16,435 French positives against Germany's 2,252) are confounded and
this test cannot separate them. `data/roofclf_germany_prod/` is the production fit.

**THE SUB-400 m2 ESTIMATOR IS VALIDATED AGAINST A COMPLETE REGISTER FOR THE FIRST TIME, AND THE
ANSWER IS REGIME-SPECIFIC.** Against a roof-area baseline (total roof area times a constant),
per municipality: **Pakistan roofclf 26.5% median error against the null's 88.9% -- a 3.4x cut**
(29 Rule-1 quadrats, leave-one-out); **Germany roofclf 48.4% against the null's 37.8% -- the
baseline wins**. Where PV is rare, roof area says little about which places hold capacity; where
it is near-ubiquitous, capacity is close to proportional to roof area by construction. **The
machinery is validated in the regime it was built for.**

**A NATIONAL TOTAL AGREEING WITH A REGISTER IS NOT EVIDENCE THE GEOGRAPHY IS RIGHT.** Germany's
cross-validated total ratio came out at 1.003 while the median municipality was off by 53%,
because over-prediction of the top decile (1.8x) cancelled under-prediction of the bottom 90%.
Three German models with municipal errors spanning 37.8-63.9% all produced essentially the same
national figure. PyPSA consumes the per-cell geography, not the total.

**THREE WAYS OF SUPERVISING THE GERMAN CLASSIFIER, AND ONLY ONE IS SOUND.** (1) OSM labels: 3.6%
complete but span all sizes. (2) **Register COORDINATES: rejected.** MaStR geolocates 108,443
units at 30-72 kWp, which gave a better classifier (0.8792 AUC against 0.8563) and a **worse
estimate (63.9% municipal error against 48.4%)** -- coordinates start at 30 kWp, so 42.1 of the
49.0 GWp below the floor can never be located and the labels disagree with the estimand.
Optimising building-level AUC on a mismatched label subset moves the aggregate confidently the
wrong way. (3) **Register COUNTS as a known class prior** (`scripts/roofclf_pu_known_prior.py`):
exact rooftop unit counts for all 11,024 Gemeinden, 4.41M units across every band including the
4.13M with no coordinate. Positive-unlabelled training against that prior fixes the label
problem (33.4% against coordinate labels' 70.6%) but **only ties the roof-area baseline on
representative municipalities (33.4% against 34.2%, rho 0.921 against 0.920)**. The first run
said 18.2% against 24.1% -- that was 55 PV-dense municipalities at a 27.0% base rate against
Germany's 15.9%, selected because they maximised geolocated units. **Always check the sample
before believing a win.** The prior is training-only; evaluation is grouped by municipality so a
held-out Gemeinde's count is truth, never an input, or the exercise is circular.

**Four approaches -- OSM labels, register coordinates, a known prior, authoritative footprints --
and none beats multiplying roof area by a constant at municipality level in Germany.** That is
now a settled, thrice-confirmed finding, and it is the counterpart to Pakistan's 3.4x win.

**Germany's evidence atlas now carries the roofclf half** (Verified 38,508 -> 41,937, Best
49,324 -> 61,854 MWp when it was added; **now Verified 26,635 / Best 84,473** after the
size-dependent rooftop constant above and the 2026-10-20 OSM combination fix), built by
`scripts/build_germany_sub400_atlas_inputs.py`. Three things
about that generator are load-bearing: the component must be **INCREMENTAL** (sub-400 m2 roofs
only, deduped against the hand-mapped OSM population and segmentation's own candidates) or it
double-counts what Best already holds -- the first build read **97.2 GWp** before dedup against
61.9 after; it is **pre-aggregated to one row per cell** on a real building point, because
handing `atlas._join_buildings_to_grid_cells` 25M geometries peaks over 20 GB and is OOM-killed
while the per-cell sum is identical; and the floor tier is **"both signals in their top decile",
not precision-calibrated**, because Germany cannot fit a precision threshold on 3.6% labels.
**Best still fails its own register check** -- 84,473 MWp (88,709 before 2026-10-20) against
roughly 74,800 MWp of registered German PV -- so read the tiers as geography, not capacity, and the atlas note says
so. Note what did and did not get fixed: the size-dependent constant reconciled the **OSM**
component (both placements now within ~10% of the register), so what is left over is the
roofclf sub-400 half and segmentation's own detections, not the conversion constants.

Full writeup: `docs/methods/mastr-validation.md`, `docs/results/germany.md`. The calibration is
walked through visually in `docs/assets/figures/germany_calibration.svg`.

### France validation (ODRE register + OpenPVMapper)

`france_validation.py` / `earthpv validate-france` is the **second** complete-register check,
and deliberately not a copy of the MaStR one -- France's register is a different instrument.
**It censors every unit below 36 kW into per-commune/per-IRIS aggregates, publishes NO
coordinates at any size, and carries NO rooftop/ground attribute.** Consequences: (1) the
72 kWp floor share is still *exactly* computable, because the censoring cliff sits below the
floor, but shares below 36 kW are unrecoverable and are returned as `None`, never modelled;
(2) **Germany's `p_unmapped` precision instrument has no French counterpart** and no
substitute is offered; (3) every share is **bracketed, never stated** -- `all_pv` (17.3%) is
a firm lower bound on the rooftop share, `bt_only` (31.1%) a rooftop-leaning upper one.
Against Germany's directly-measured **65.5% of rooftop**, this settles by measurement what
Germany's page argued from dispersion: **the below-floor share is not a transferable
constant.** France's fleet is far more ground-mount-heavy (35.0 GWp all PV vs 19.1 GWp on
low voltage). Count share is 92.0% -- quote the capacity share.

**What France can do that Germany could not: measure the module constant.** ODRE publishes
**dated year-end vintages** (2017 on; 2020-2025 pulled, 9.3 -> 30.4 GWp). An aggregate row
carries one group-level date over hundreds of units, so the current snapshot cannot be
filtered to a past epoch -- but a past snapshot can just be downloaded, and
`interpolate_to_date` reads per-commune small-PV capacity back to a quadrat's own mapping
day. Against **14 exhaustively hand-mapped communes** (3,335 features, median 20 m2, on
sub-metre IGN imagery), the register's sub-36 kW band divided by mapped sub-200 m2 module
area gives **`DEFAULT_KWP_PER_M2_MODULE` = 0.150 kWp/m2 against the assumed 0.180** (ratio
0.83; 0.147 under the widest PV definition; median 0.149, IQR 0.129-0.273, 11 of 14 communes).
**The epoch correction is worth 53%** -- the same communes read 0.230 against today's
register. The German attempt at this measurement is a documented negative result (3.6% OSM
completeness, implied constant 0.02-0.99). **Not yet acted on**: 0.18 is unchanged pending an
owner decision, and the French figure does not transfer to Pakistan on its own.

**`tag` on the French labels is load-bearing, not decoration.** 381 of 3,335 features are
`thermal` (solar hot-water collectors -- area, no kilowatts), 12 are mapper-retracted
`false`. Both are dropped. `unknown` (84) and `missing` (181) are genuinely ambiguous
(`missing` overlaps OpenPVMapper at 48.6%, between `normal`'s 66.6% and `thermal`'s 29.4%),
so they are excluded from the primary set and written to `data/labels/france_sensitivity/`;
including them moves the constant 0.150 -> 0.147, i.e. not at all. **Solar thermal is the
systematic confusion for any imagery-based detector and is invisible without the tag**: 137
OpenPVMapper polygons in these communes sit on one.

**France quadrats live in `data/labels/france/`, NOT `data/labels/`** --
`roofclf.discover_quadrats` globs the latter, so a French quadrat there would silently join
the next Pakistani refit (the Kalat Rural footgun again). Pass `--labels-dir`.
`scripts/build_france_quadrats.py` builds them: commune contour as the boundary (the mapper's
unit of work; mapping spills up to 23% outside, so features are clipped to it), `mapping_date`
from the median feature `imageDate` rather than `metadata.json`, placement from VIDA overlap.
**Saint-Gely-du-Fesc is marked unfinished by the mapper**, is not Rule-1 complete, and is
excluded from every fit by explicit `--quadrat` flags. Langoat and Saulny are excluded from
the module-constant fit specifically: the register reports no sub-36 kW capacity there at
their mapping epoch despite mapped installations, which is a hole in the reference.

**OpenPVMapper** (Kasmi 2026, `doi:10.5281/zenodo.21534856`, CC-BY-4.0; 1.14M rooftop
polygons, ~15 GWp, mainland France) is scored **against the register first**, so a later
earthpv comparison can be read knowing which way the reference leans. Cut to the same
population on both sides (<= 72 kWp, low voltage) it recovers **91% of registered capacity**,
slope 0.79, Spearman 0.79 over 17,970 communes -- a good reference for the sub-floor band.
Its own implied capacity density is **0.129 kWp/m2**, against 0.150 measured and 0.180
assumed: three attempts at one constant spanning 1.4x. Against the hand-mapped truth it
recalls **0.667** (area 0.670) at raw precision 0.555. **It is a model output (~74-75%
published precision), not ground truth -- agreement with it is not validation**, and the 14
communes are its own manual-correction layer, so precision measured there is an optimistic
bound and recall is the transferable half.

**Register CSV exports truncate silently on an SSL reset** (a 2021 pull came back at 5.4 GWp
against the true 13.4, reading as a year PV barely existed). `scripts/fetch_odre_vintages.sh`
re-fetches until the line count is plausible and `load_vintages` refuses any vintage under
1 GWp outright.

**Two things break when a quadrat is commune-sized rather than a 1-4 km2 box.** (1)
`roofclf.building_table` reads seg/frac probability from a SINGLE 0.1 deg cell (the
boundary's representative point) and zero-fills the rest; 7 of 14 French communes straddle
2-4 cells, so France runs `roof-classifier` **without `--seg-prob-dir`** -- a feature
correct in some quadrats and part-zero in others is worse than absent everywhere, and
segmentation carries almost no signal on 20 m2 arrays anyway. The composite read is properly
windowed and is unaffected. (2) The density domain is per-AOI, not a method constant:
`density.calibrated_density_range(aoi)` now looks up `CALIBRATED_BLDG_DENSITY_BY_AOI`
(pakistan 48.5-5258.0 unchanged, **france 17.5-390.8**) and warns when an AOI has no entry
instead of silently borrowing Pakistan's. `CALIBRATED_BLDG_DENSITY_KM2` remains Pakistan's
and remains the fallback, so no existing Pakistani call site changed behaviour.
`compose.run_compose` now also honours an AOI's `compose_window` when `--window` is not
passed, so a national run cannot land on a different epoch than the quadrat cells it skips.
**FIXED 2026-09-12: `aoi` is threaded through the whole chain.** `sub400_capacity.py`
(`national_cell_domain`, `domain_restricted_capacity`, `domain_restricted_and_gate_capacity`,
`out_of_domain_and_gate_capacity`), `roofclf_ge400_capacity.py` and `growth.py` all take `aoi`
and resolve the band via `density.calibrated_density_range`, and `cli.py` passes it. The
parameter defaults to `None` for backwards compatibility, and
`calibrated_density_range(None) == calibrated_density_range("pakistan") ==
CALIBRATED_BLDG_DENSITY_KM2`, so Pakistan is provably unchanged. Verified by a functional test:
a 20 bldg/km2 cell is in-domain for France but not Pakistan and a 1,200 bldg/km2 cell the
reverse. `scripts/trust_gate_density_audit.py` and `scripts/detection_domain_examples.py` still
import the constant directly and are left alone deliberately -- both read the hardcoded
Pakistani `national_cell_density.parquet` and take no `--aoi`.


AOI config: `france` carries `grid_origin: [-5.15, 41.33]` so a targeted quadrat-cell compose
and a later national one name cells identically, and `compose_window: ["2024-05-01",
"2024-09-30"]` -- summer 2024, chosen so imagery, the calibration labels (10 of 14 communes
mapped 2023-2024) and the register's 2024-12-31 vintage all sit in one epoch. **Four communes
(Langoat 2021, Saulny/Eaunes 2022, Gannay 2022-23) predate that window**, so their labels
understate what the imagery shows. National cell count: **5,471** at `--min-buildings 1000`,
**6,858 built** at `--min-buildings 1` (the 2026-09-16 compose, which is what the published
atlas runs on; 6,021 survive the border clip).
Checkpoint: `v4_combined_all` epoch=41, the same owner-approved substitution Germany used
(`v3_combined_india` is no longer on disk).

**ROOFCLF DOES NOT TRANSFER TO FRENCH RESIDENTIAL PV, and this is the most important
earthpv-side result here.** Fitted on 13 hand-mapped communes (44,314 buildings, 1,231 with
PV, 2.78% base rate, LOQO, parcel label): **median fold AUC 0.710, 0.627 within size band**,
against Pakistan's 0.857 / ~0.834. Building size alone gets 0.673 and spectral-only 0.672, so
**reflectance is worth ~0.037 AUC**; at a precision-0.5 threshold it flags **16 buildings out
of 44,314** (recall 0.0065). Segmentation scores **exactly 0.500 in all 13 folds**. The cause
is physical: the median mapped French installation is **20 m2 against a 100 m2 Sentinel-2
pixel**. The control that isolates it to the sensor is OpenPVMapper, which recalls the same
installations at 0.67 from sub-metre imagery with **no size gradient** across 0-400 m2.
**This bounds roofclf, it does not refute Pakistan's** -- Pakistani quadrats hold arrays that
are small relative to the 400 m2 floor but still large relative to a pixel. Treat Pakistan's
sparse-density stratum (the weakest part of the coverage-ratio fit) as the nearest thing to
this regime. Consequence for France: **no roofclf half in its atlas**, and `rate_ratio` spans
0.37-6.91 across the communes so several fail the precision-trust gate anyway.

**France HAS a candidate-precision calibration table since 2026-09-11**
(`configs/calibration/france_candidate_precision.yaml`, status `interim-mapped-only`,
re-derived 2026-09-17 against the expanded candidate set), so `est_mwp_cal` is precision-
weighted rather than collapsing to `est_mwp_det`. It is fitted with `--recall-reference none`,
so there is no recall correction and `est_mwp_rc` equals `est_mwp_cal_total`: France's atlas
figures remain a **precision-honest floor, not a recall-corrected estimate**. The hand-mapped
communes are still NOT used as that recall reference, deliberately -- they are a sub-400 m2
ground truth against a >= 400 m2 candidate population (see the atlas paragraph below).

**FRANCE'S EVIDENCE ATLAS IS NATIONAL (the 31-cell version is long superseded; the
`--min-buildings 1` compose landed 2026-09-16 and the whole chain was re-run 2026-09-17).**
Compose built **6,858 cells**, the density border clip drops **837 (12.2%)** as Spanish /
Belgian / German / Italian / Atlantic, leaving **6,021 French cells** against the 5,473 of the
`--min-buildings 1000` grid. Inference, postprocess, `calibrate-candidates`, `density` and
`atlas` all re-ran over that set (**49,145 candidates** against 39,462). Published result:
**Verified 12,381.7 MWp (90% 9,410-16,613), Best 13,368.5 MWp (90% 11,478-17,762)** against a
registered 34.6 GWp. Verified did not move at all on the widening and Best moved ~+100 MWp:
the cells a one-building floor adds are sparse and rural, so they carry model detections and
no hand-mapped installations. **`--include-offgrid-osm` is now a no-op for France and was not
passed**: 100% of the 54,111 border-clipped national OSM features fall inside the grid, where
79.7% fell outside the 5,473-cell one. Segmentation-only (no roofclf half). Still a **strict
precision floor**: no glint sample, so `p_unmapped` = 0.0 and `p_real` collapses to the
OSM-mapped fraction (0.04-0.33 by bin), and recall was **deliberately skipped**
(`--recall-reference none`) rather than measured against the hand-mapped communes, which are a
sub-400 m2 ground truth against a >= 400 m2 candidate population -- pooling them would have
manufactured a large, badly-determined correction against the 20x `DEFAULT_RECALL_FLOOR` clamp.
**`check-density` now fails 9 of 13 regions** (was 1 of 6 on the 31-cell run), every one on the
ground-mount:rooftop ratio -- Corse 79x, PACA 23x, Nouvelle-Aquitaine 17x, down to
Ile-de-France 5x, plus Auvergne-Rhone-Alpes suspect at 4.4x; nationally 852 MWp rooftop against
7,088 MWp ground. The register puts 19.1 of France's 34.6 GWp on low voltage, so the true ratio
is near parity: this gate is firing on the MISSING ROOFTOP DENOMINATOR (a 20 m2 French array is
a fifth of a pixel), not on a ground-mount false-positive blowout. Published with that stated,
not waived.

**FOOTGUN I INTRODUCED: `export.load_mapped_reference_attrs` globs
`data/labels/*_overpass_solar.parquet` AOI-AGNOSTICALLY.** France's national pull had to be
named `france_national_overpass_solar.parquet` to be seen at all (as
`france_national_osm_solar.parquet` it was invisible and every `mapped_frac` came out 0.000,
which would have zeroed the whole atlas). That file is now in the glob's path, so **any future
`calibrate-candidates --aoi pakistan` will pool 318,611 French features into its mapped
reference.** Matching is spatial so Pakistani results are unaffected numerically, but the
table's `recall_reference` provenance count (documented as 18,276) WILL change. Move or rename
the France file before re-deriving Pakistan's table.

**FRANCE IS SCORED AGAINST ITS REGISTER TWICE, ZERO-SHOT AND RETRAINED (2026-09-11/12).**
Same 20,501 communes, 93.0% capacity coverage, same 5,473-cell grid, so the runs are directly
comparable. On the
above-floor low-voltage denominator: `est_mwp_exp` slope **0.162 -> 0.170**, Spearman
**0.290 -> 0.449**; `est_mwp_det` slope **0.127 -> 0.160**, Spearman **0.262 -> 0.446**
(Germany, in-domain, on a TRUE rooftop denominator: 0.388/0.656 and 0.340/0.661). **The gain
is placement, not magnitude** -- rho closed half the gap to Germany while slope moved 5-25%
and total recovery went 26% -> 34%. Spearman is scale-free so it cannot be blamed on
conversion constants or the proxy denominator; slope partly can, since France's register has
no rooftop/ground field. **Quote `est_mwp_det`/`est_mwp_exp` for France, never `est_mwp_cal`
or `est_mwp_rc_roof`** -- both sit near 0.02 for BOTH models because there is no French glint
sample, so `p_unmapped`=0 and `p_real` collapses to the OSM-mapped fraction (Germany's
`est_mwp_cal` collapses identically at 0.167 and is rescued by a recall correction France
lacks).

**RE-SCORED ON THE FINISHED 6,021-CELL GRID (2026-09-20), and it barely moved.** The A/B above
is frozen on the 5,473-cell grid; re-running `validate-france --density-dir
data/predictions_v5/france/density` against the widened one lifts register coverage from 93.0%
to **98.4% of registered capacity (21,667 communes against 20,501)** and gives `est_mwp_exp`
slope **0.169** / rho **0.420** / 32.6% recovery and `est_mwp_det` slope **0.159** / rho
**0.417** / 33.3%, against 0.170/0.449/33.8% and 0.160/0.446/34.4% before. The 1,166 added
communes are the sparse rural ones a one-building cell floor reaches and the model finds little
in them, so rho slips ~0.03 while slope holds to three decimals. Artifacts:
`results/france_validation_v5/france_validation.json` (pre-widening copy kept as
`*_PRE_6021cell_20260920.json`); the comparison atlas is rebuilt from it.
**Watch the `--pred-dir` argument**: `validate-france` appends `france/candidates.parquet`
itself, so it takes `data/predictions_v5`, not `data/predictions_v5/france` -- the wrong one
silently skips the whole `earthpv_vs_mapped` floor-recall block instead of failing.

**What retraining changed is shape, not volume**: 13,419 -> 39,462 candidates, median area
8,301 -> 1,400 m2, rooftop share 26.9% -> 50.3%, blobs >= 10,000 m2 6,036 -> 2,076, and total
area DOWN 364 -> 255 km2. `polygonize_chips` merges touching thresholded pixels with no upper
bound, so v4's oversized blobs over France were merged false-positive sheets.

**v5 (`configs/terramind_pv_v5_france.yaml`, `data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt`,
early-stopped at 33, 8h19m) IS APPLIED TO FRANCE ONLY.** Pakistan and Germany keep v4 and
their published figures are untouched. France val holdout: Centre-Val de Loire (lon 0.5-3.1E,
lat 46.5-48.4N), 1,518 chips, carved into `data/chips/france/index.parquet` before the merge.

**v6 RESOLVED THE v5 CONFOUND (2026-09-12): it is corpus SIZE, not merely French presence.**
`configs/terramind_pv_v6_france_capped.yaml` caps France to Germany's size (3,201 train chips
against v5's 17,059) with a byte-identical val holdout, so the only variable is French training
volume. On the above-floor low-voltage denominator, `est_mwp_exp`: v4 zero-shot slope 0.162 /
rho 0.290 / 26% recovery, **v6 0.100 / 0.364 / 18%**, v5 0.170 / 0.449 / 34%. **v6 recovers
less than half of v5's rank gain and is WORSE than zero-shot on slope and recovery** -- a
half-measure retrain lands somewhere worse than either end. The two effects do separate: blob
suppression saturates early (merged false-positive sheets >= 10k m2 fall 6,036 -> 2,678 with
19% of the French data, 79% of v5's total reduction) while candidate yield keeps scaling
(13,419 -> 14,544 -> 39,462). v6 artifacts: `data/predictions_v6/`, `results/france_validation_v6/`,
`results/france_pv_evidence_atlas_v6.html` (Verified 11,163 / Best 12,045 MWp -- Verified is
identical to v5's because it is hand-mapped OSM times the constants and never touches the
model). **v5 stays France's production checkpoint.**

**THE 400 m2 FLOOR IS NOW MEASURED, NOT ARGUED (2026-09-12).** `france_validation.mapped_vs_earthpv`,
exposed as `earthpv validate-france --pred-dir`, scores candidates against the 2,622 hand-mapped
installations per size bin. Recall climbs with array size (Spearman **+0.83, p=0.042**, from
0.000 below 20 m2 to 0.095 at 200-400 m2) while **OpenPVMapper, reading the same installations
in the same communes from sub-metre imagery, is flat (-0.29, p=0.58)**. The gradient is the
sensor, not the annotator. It survives across three models (v4/v6/v5: pooled count recall
0.0118 / 0.0103 / 0.0118). Precision is deliberately NOT reported (four communes were mapped
1-3 years before the composite window, which biases precision and leaves recall alone), a
commune under 99% cell coverage is excluded rather than read as recall 0, and the >= 400 m2 bin
holds only 44 installations (recall 0.045, 95% Wilson 0.013-0.151) so it cannot be read as
"earthpv fails above its own floor".

**TWO ALTERNATIVE EXPLANATIONS FOR THE FRENCH roofclf FAILURE WERE TESTED AND REJECTED.**
*Too few labels?* No: OpenPVMapper pseudo-quadrats over 90 communes give 386,565 buildings and
16,435 positives, **13.4x the supervision**, and move AUC by **-0.005** (0.706 against 0.710).
The control that settles it is that the same model scores **0.683 on held-out OpenPVMapper
labels**, its own source -- the features do not separate PV-bearing roofs whatever the labels
say. *Bad footprints?* Partly, and now quantified: the DGFiP cadastre (per-commune by INSEE,
authoritative, ~2 s per commune) finds 103,697 buildings and 1,759 PV-bearing where VIDA finds
44,314 and 1,231, and fixing that is worth **+0.027 AUC within size band, 14% of the gap** to
Pakistan. Real, worth adopting, nowhere near enough.

**THE SIZE REGIME IS SET BY POLICY, NOT GEOGRAPHY (2026-09-13).** Across the France-Germany
border French arrays are flat at 20.5-21.7 m2 in every 10 km band out to 60 km and then step at
the line. **How big the step is depends entirely on the instrument**: the geolocated comparison
says ~5x, but its German side is OSM at ~3.6% completeness and mappers trace large arrays first.
Both COMPLETE registers cut to the same sub-36 kW band give **5.34 kWp per unit in Alsace/Moselle
against 10.41 in BW/RP/Saarland -- 1.95x**, half what imagery implies. Figure:
`docs/assets/figures/border_array_size.svg`. The practical warning for a new country: whether
`roofclf` can work is a property of national subsidy design and cannot be inferred from a
neighbour.

**France has an atlas page** (`docs/atlas-france.md`) beside Pakistan's and Germany's, and its
two interactive pages are in `build_docs_figures.py`'s sync list rather than copied by
`rebuild_france_atlases_v5.sh`, which meant `pixi run docs-figures` could not refresh them.

**Artifacts**: baseline frozen at `results/france_validation/france_validation_BASELINE_zeroshot.json`
+ `configs/calibration/france_candidate_precision_BASELINE_v4.yaml` + `*_BASELINE_zeroshot.html`
atlases; v5 at `data/predictions_v5/` + `results/france_validation_v5/`. National evidence
atlas on v5, over 6,021 cells: **Verified 12,381.7 / Best 13,368.5 MWp** (90% 11,478-17,762;
was 12,382 / 13,270 over 5,473+485 cells before the `--min-buildings 1` compose landed
2026-09-16, and 11,163 / 11,995 before the 2026-09-15 off-grid-OSM and border-clip
corrections) against a registered 34.6 GWp -- a strict precision floor, recall deliberately
skipped. **`results/france_validation/france_validation.json` is NOT the v5 artifact**: the
2026-09-17 chain re-ran `validate-france` with no `--density-dir`, so that canonical-looking
path holds a v4 (`data/predictions/france/density`, 2026-09-11) register comparison with the
OpenPVMapper blocks missing. The v5 one is `results/france_validation_v5/`.

**`scripts/merge_chip_index.py` ALWAYS writes `data/chips/combined/index.parquet`**, which is
v3india's corpus. Back it up before merging a new corpus and move the result aside, or it is
silently clobbered.

Full writeup: `docs/methods/france-validation.md`, `docs/results/france.md`.

### Vietnam and India: the unattended localized run (launched 2026-09-23)

The owner asked for Vietnam, then **all of India**, each ending in an evidence atlas, with the
segmentation **localized** on each country's own OSM labels (not run zero-shot), the checkpoint
chosen by **whichever scores better on a held-out region** (tie goes to local), and publication by
push to main. It runs as one systemd queue, `earthpv-vn-in-queue` (`scripts/run_vn_in_queue.sh`,
network lane: labels, compose, Vietnam first, India preempted), which hands each country to
`earthpv-<aoi>-compute` (`scripts/run_country_compute.sh`: chips -> `mark_val_buffer.py` -> merge
-> train -> `pick_best_checkpoint.py` -> `compare_local_vs_v5.py` -> infer -> atlas chain, behind
markers in `data/<aoi>_pipeline_markers/`). Status: `bash scripts/vn_in_status.sh`; the durable
check-in log is `data/vn_in_monitor.log`. Checkpoints are **v9_combined_vietnam** and
**v10_combined_india** (`v8` is a concurrent session's `v8_combined_nigeria`).

**Vietnam published 2026-09-26: Verified 8,179.8 / Best 8,860.5 MWp** on v9 (held-out Central
Highlands: pixel IoU 0.762 against v5's 0.724, recall >= 500 m2 tied). `docs/results/vietnam.md`.
India's compose is ~25,600 cells at ~90 cells/h, i.e. roughly 11 days; its v10 trains at a
milestone (label cells plus 3,000 density cells) with inference running incrementally behind it.
Holdouts: Vietnam = Kon Tum/Gia Lai/Dak Lak/Dak Nong (385 cells); India = Gujarat's old
Surat-Bharuch-Vadodara val box (240 cells), inherited so v5 is out-of-sample there too.

What this run changed, all opt-in so other AOIs keep their behaviour:
- **`cell_selection: duckdb`** (AOI key): per-cell VIDA counts aggregated in DuckDB and cached in
  `data/cells_cache/`. The in-memory path peaks at 6.9 GB for Nigeria's 68M points and would need
  ~50 GB for India's 527M. Bit-identical cell lists, order included, on Zambia and Nigeria.
- **`fetch_geoboundaries` caches** to `data/geoboundaries/gb_<ISO3>_<LEVEL>.geojson` with retries;
  `EARTHPV_REQUIRE_BOUNDARY=1` makes compose fail closed instead of renaming every cell.
- **Compose network hardening** (compose units only): GDAL `TCP_KEEPALIVE` + `LOW_SPEED_TIME=60`
  (pooled keep-alive connections to the Sentinel-2 blob host died silently and each request waited
  out `tcp_retries2`, ~15 min), and `EARTHPV_NET_TIMEOUT_S=120` + `EARTHPV_FORCE_IPV4=1`
  (`compose._harden_python_network`: one hung STAC search holds `imagery._SEARCH_LOCK` and stalls
  every worker, Earth Search fallback included). Rate went ~36 -> ~90 cells/h. Cost: ~1 dropped
  band read per cell. Stall watchdog 900 s: a pass now lands its first cell in 2-3 min.
- **`postprocess --building-buffer-m`** (500 for VN/IN): Vietnam's 2 km building set was
  OOM-killed 3x at 14 GB. Placement and the rank prior only use buildings within ~40 m.
- **`postprocess --stream-buildings`**: per-0.25-deg fetch/join/discard instead of a national
  building table (identical placement/overlap on all 6,536 Vietnam candidates, 1.9 GB vs 14-18.5 GB).
  Needed for India; systemd-oomd killed a 500 m global join AND a compose together at 10:07 09-26.
- **`prepare_national_osm_solar.py --keep-detected-screen`**: the 5 km2 ground cap is German;
  Vietnam's five largest parks (5.6-8.3 km2, ~1.9 GWp) are 92-99% detected, so above the cap a
  feature is kept on the screen's evidence. India's parks are tens of km2.
- `overpass_labels_chunked.py` caches tiles and resumes (`--fetch-only`), `merge_chip_index.py
  --out`, `scripts/ranged_download.py` (source.coop throttles single streams; 16 ranges),
  `parquet_metadata_cache` on every DuckDB connection (India cell query 4.6 -> 2.8 s).
- **Editing a script a unit is running is unsafe** (bash reads incrementally): restart the unit.
  Before stopping a compose unit by hand, `rm data/vn_in_queue_markers/<aoi>_round_start`, or the
  queue books a false unproductive round and a 1 h cooldown. Stop the QUEUE first when removing
  compute markers, or its next tick can relaunch the chain before the markers are gone.

**India published 2026-10-11 on v5, not v10: Verified 67,592.6 / Best 72,271.1 MWp** (90%
47,486-97,145 / 63,487-98,370) over 25,576 cells, Sentinel-2 November 2025 to March 2026.
v10 lost the inherited Gujarat holdout on recall >= 500 m2 (0.911 against 0.938) and IoU
(0.663 against 0.686), so v5 ships under the rule; a whole-country v10 diagnostic runs after.
`docs/results/india.md`. Verified is almost all ground perimeters (1,331 km2 at 0.05).
**Revised the same day from Best 75,855.7** by the OSM-outline fix (see "Density stage"):
Khavda's two screen-rejected outlines went 3,789 -> 796 MWp, and 101 park outlines VIDA had
placed `rooftop` moved to ground (model rooftop 4,109 -> 843 MWp; they had also set the
largest rooftop bin's `p_real`, 0.318 -> 0.171 once the table was re-derived). Pre-fix outputs
are kept in `/home/tobi/earthpv_data/india_PRE_osm_outline_fix_20261011/`.
`check-density` fails 17 of 35 regions, 16 on the ground:rooftop ratio (the missing rooftop
denominator, as in France: national 38x against MNRE's 3.8x) and six single-cell flags, each
a mapped plant. 27.8 GW of `est_mwp_rc`'s 32,868 MWp is the 1,331 OSM-outline candidates
exempt from the merge cap. Eleven capacity-tagged Indian parks measure 0.045 kWp/m2 (mostly
AC) against the 0.05 land constant. The Gujarat page is superseded: the state went 765 ->
4,554 MWp, mostly because the OSM oversize exemption (2026-08-10) postdates that run.

**India's compose is being widened by `ring_cells: 3` (2026-10-22, owner request)**, an AOI
key that adds every cell within 3 cells (~33 km) of the >= 1,000-building and label
selection (`compose._add_ring_cells`), so a park built away from buildings is imaged too:
+3,573 cells (742 with no buildings), appended after the existing ones so resumed runs are
unchanged. It is insurance, not a measured gap: 97.3% of mapped Indian ground-PV area
already sits in cells with >= 1,000 buildings even after removing the VIDA "buildings"
that are a park's own panel rows, and a 1-cell ring reaches all of it. The published atlas
does not move until infer -> postprocess -> ... -> atlas is re-run over the new cells.
The 500 m `--building-buffer-m` in `postprocess` is NOT a search radius: it only bounds
which footprints are fetched for placement (30 m) and the rank prior; nothing is dropped.

**Compose defects, fixed 2026-10-10 for new composites only (open question 11, "Composites built before 2026-10-10 carry two compose defects").**
`eo:cloud_cover` is per MGRS tile, so dry-season scenes tie at 0% and the twelve kept could
all come from a tile clipping the cell's corner: Rewa Ultra Mega Solar's cell was 87% empty
and the 750 MW park dropped out of India's Verified. `imagery._rank_items` ranks scenes
covering >= 99% of the cell first. And `odc.stac.load(fail_on_error=False)` turns failed reads
into zeros, so a cell could lose a whole band; `imagery.BAND_DROPOUT_MAX` now raises (the cell
is retried). India (1.3% of cells each), Zambia, Nigeria and Vietnam were NOT recomposited;
`scripts/scan_composite_defects.py` measures a country.

**Solar-thermal is in OSM under the same `generator:source=solar` tag**, and the label pull
keeps it. `scripts/drop_solar_thermal.py --aoi <aoi>` drops thermal/CSP elements from the
labels before chips; `--candidates` drops candidates at least half inside them before
`density`. Morocco's pull was half thermal (1,697 of 3,440, the Noor CSP complex). Every
country before Morocco is unfiltered; India's share was measured after publication (253
features, 473 MWp, ~0.7% of both tiers) and is carried as a known defect. At India's size
the bbox scan fails on every Overpass mirror; `--by-id` looks the label elements up by id
instead and finds the same droppable set. **The filter's backup was silently undoing it
until 2026-10-11**: it was named `<aoi>_overpass_solar.with_thermal.parquet`, and
`chips._newest_overpass_path` (chips, `evaluate`, compose's label cells) globs
`<aoi>_overpass_solar*.parquet` and takes the last name in sort order, which was the
backup. Morocco's first v11 trained on it, and its holdout PV pixels were 75% Noor CSP
mirrors. The backup is now `<aoi>_solar_labels_with_thermal.parquet` and dotted stems are
ignored; Morocco's pre-fix run is kept in
`/home/tobi/earthpv_data/morocco_PRE_thermalfix_20261011/`.

### Morocco, Egypt, Yemen, South Africa (launched 2026-10-10)

Same owner rules as above (localize, ship the better checkpoint on a holdout, >= 1,000
buildings per cell plus label cells, publish by push to main). `earthpv-country-queue`
(`scripts/run_country_queue.sh`; status `bash scripts/country_queue_status.sh`; markers
`data/country_queue_markers/`; check-in log `data/country_monitor.log`) pulls labels, runs the
thermal filter, composes one country at a time and hands each to `run_country_compute.sh
<aoi>` with `SKIP_DIAGNOSTIC=1`. Checkpoints v11_combined_morocco, v12_combined_egypt, v13_combined_yemen,
v14_combined_south_africa. Holdouts are picked from the label map before training by
`scripts/pick_val_region.py` (ADM1 rule in its docstring) and written into `configs/aoi.yaml`.
Morocco's AOI stops at 27.7N, the internationally recognised line (geoBoundaries MAR includes
Western Sahara), and its holdout (Draa-Tafilalet, 8 of 39 positives) is too thin to settle the
ship rule with confidence. Rebuilt from the filtered labels it has 49 train chips against the
chain's floor of 50, so Morocco waits on an owner decision (accept 49, or a smaller holdout).

**Egypt published 2026-10-12 on its localized v12: Verified 3,315.1 / Best 3,378.6 MWp**
(90% 2,314-4,789 / 3,028-4,823) over 946 cells, Sentinel-2 April to September 2026. v12 beat
v5 on the Cairo Governorate holdout on recall >= 500 m2 (5 of 23 against 1 of 23; IoU 0.062
against 0.066), a thin holdout (7 positive chips, 0.3% of Egypt's chip PV pixels). Verified is
mostly three parks (Benban 36.9 km2, 10.0 km2 north of it, Kharga 8.8 km2). The model's rooftop
estimate is 0.2 MWp: the 176 rooftop candidates >= 1,000 m2 match no mapped rooftop, so their
`p_real` is 0. `docs/results/egypt.md`.

**Yemen published 2026-10-12 on its localized v13: Verified 65.9 / Best 67.1 MWp** (90%
46-95 / 49-98; since 2026-10-24, on a refreshed OpenStreetMap pull with the owner's panel
traces at the module constant and 169.1 MWp of farm ground PV: **Verified 130.9 / Best 302.1
MWp**, 90% 109-161 / 210-471; see "Farm ground PV") over 810 cells, Sentinel-2 October 2025 to March 2026, against IRENA's 456 MW
at end-2025. **The ship decision was a zero-zero tie** (both checkpoints 0 of 25 'Amran
arrays, IoU 0) and went to v13 by the tie rule, on no evidence. Yemen's labels are 1,697
solar irrigation arrays of ~600 m2 in Tihama farmland, mapped in 2023: their reflectance
differs from a 30 m ring by ~2% per band (Egypt/Vietnam 8-25%), no shift within 60 m finds
them, and v13 lights up 2 of 1,466 mapped features nationally. So `p_real` is ~0 in every
bin and Best is the OSM map plus 1.2 MWp. Three real unmapped parks (Aden 1.31 km2, Mocha
0.64, a Red Sea coast park 0.38) are among the 29 oversize detections and excluded by the
merge cap along with 26 dark-rock ones; they are in the new-leads export.
`docs/results/yemen.md`. **`screen_osm_ground_perimeters.py` crashed on a country with no
perimeter >= 50,000 m2** (Yemen) and now writes a header-only CSV that `density` can read.

**South Africa published 2026-10-14 on its localized v14: Verified 9,393.8 / Best 9,755.6
MWp** (90% 7,078-12,787 / 8,789-12,875) over 3,647 cells, Sentinel-2 April to September 2026,
against SAPVIA's 10.12 GW (July 2026). **The first decisive localization win of this queue**:
on the Western Cape holdout (452 positive chips, 17.5% of dissolved positives) recall >= 500
m2 0.794 against v5's 0.744, >= 1,000 m2 0.858 against 0.708, pixel IoU 0.671 against 0.364;
v5 still finds slightly more below 1,000 m2. Verified is 7,568.6 MWp of mapped ground and
1,825.3 of mapped rooftop; the model adds 362 MWp net (floored in 591 cells). **86
capacity-tagged parks measure 0.045 kWp/m2** (4,817 MW on 106.3 km2, mostly AC), the same as
India's, against the 0.05 land constant. Three parks mapped in 2026 (Teraco Sediba, Ukuqala,
Sonvanger, ~260 MWp) were construction sites in the composite and count in Verified at their
full outlines, since only perimeters above 5 km2 are screened. `check-density` fails 6 of 9
provinces (ground:rooftop ratio of the model's estimate, plus four single-cell flags that are
each one mapped plant). `docs/results/south-africa.md`.

**Morocco published 2026-10-19 on its localized v11: Verified 380.4 / Best 411.2 MWp** (90%
265-550 / 361-554) over 703 cells north of 27 deg 40' N, Sentinel-2 April to September 2026,
against ONEE's 1,285 MW of utility-scale PV plus 534 MW CSP (pv magazine, 2026-02-26). The
owner accepted 49 train chips (one under the chain's floor of 50) on 2026-10-18. **The ship
decision was a tie near 1.0** (recall >= 500 m2 0.992 vs v5 0.994, IoU 0.935 vs 0.938): the
Draa-Tafilalet holdout is three parks (Noor IV 72 MW, Noor Erfoud and Noor Zagora 40 MW each)
and no small arrays. Verified is 377.8 MWp of mapped ground; the model adds 87.7 MWp
(`est_mwp_rc`, all ground; no rooftop candidate matches a mapped rooftop). Nothing is mapped
at Noor Midelt. **`atlas.build_evidence_atlas` now clips region outlines to the AOI bbox**:
geoBoundaries MAR draws Laayoune-Sakia El Hamra and Guelmim-Oued Noun into Western Sahara
(south to 24.4 N); every cell lies inside the bbox, so no total moves. `docs/results/morocco.md`.

**Poland published 2026-10-22 on its localized v15: Verified 6,604.3 / Best 7,780.9 MWp** (90%
4,618-9,528 / 6,411-10,398) over 3,948 cells, Sentinel-2 May to September 2026, against about
21.8 GW installed (Feb 2025). v15 beat v5 on held-out Lublin cells (recall >= 500 m2 0.960 vs
0.927, IoU 0.645 vs 0.571). Three run-level fixes came out of it: `pick_best_checkpoint.py`
reads every `last*.ckpt` (a killed run's `last.ckpt` had picked the wrong epoch); the ground
screen and `pick_val_region.py` use `density._grid_origin` (compose snaps the grid to the
country's own lower-left, 14.1E for Poland, so the raw `grid_origin` read every perimeter
from the neighbouring cell; the held-out cells are Lublin shifted one column east);
`new_region.py add` writes `val_tiles: []`. **168 model detections above the merge cap (39.7 km2,
~2 GWp) are mostly real, unmapped parks** in Poland, excluded by the cap like everywhere else.
`docs/results/poland.md`.

**Label cells cover a park's whole outline since 2026-10-12** (`compose._solar_label_cells`).
A cell per mapped feature by its representative point left an outline crossing a cell edge
half imaged, and the ground screen (90% imaged above 5 km2) dropped two Egyptian parks that
were 96-98% detected where imaged: Verified 2,374.6 -> 3,315.1 once the five cells were
composed. South Africa gains 21 cells, Morocco and Yemen none; of the published countries only
India has such cells uncomposed (8, six at Khavda; open question 11). **The queue decides an
atlas is finished by grepping `data/<aoi>_pipeline.log` for "ATLAS DONE"**, so removing
`<aoi>_atlas_done` does not relaunch a finished country: re-run its steps as a one-off unit.

## Conventions & gotchas

- **GPU:** the target card is a **GTX 1060 (Pascal, sm_61)** → PyTorch must be **cu126** wheels
  (CUDA 13 dropped Pascal). Pinned in `pixi.toml`.
- **`data/` is gitignored** and lives on the external drive
  (`/run/media/tobi/aidisc/earthpv/data/`): `chips/`, `composites/`, `models/`, `predictions/`.
  Files there are invisible to git/IDE explorers that hide ignored files.
- **`row.mask` / `row.image` on a pandas row:** use bracket access (`row["mask"]`) -- `.mask`
  resolves to the `Series.mask` method, a bug hit more than once here. **A column named `cov`
  is the same trap** (`DataFrame.cov`, the covariance method) and cost a run in
  `validate_sub400_against_mastr.py`; it failed loudly only because comparing a method to a
  float raises. Name a column something pandas does not already define, and prefer brackets.
- **Selecting "the best checkpoint" by mtime is wrong.** `train.py` sets `save_top_k=2`, so a
  run directory holds the two BEST checkpoints and `ls -t | head -1` returns the SECOND-best
  whenever the final improvement is not the argmax -- exactly what happened to v6 (epoch 30 at
  0.7818 against epoch 26 at 0.7828). Use `scripts/pick_best_checkpoint.py`, which reads
  Lightning's own `best_model_path` out of the checkpoint's ModelCheckpoint callback state.
  **A restarted run leaves the dead run's files in the same directory**, and Lightning then
  writes the live run's state to `last-v1.ckpt`; reading only `last.ckpt` returned the dead
  run's best (Poland 2026-10-22: epoch 7 at 0.776 instead of epoch 27 at 0.804, caught
  before publication). The picker now reads every `last*.ckpt` and takes the best score.
- **`roofclf.discover_quadrats` globs `*_calib_*_boundary.geojson`.** A quadrat stem without
  `_calib_` is invisible to `earthpv roof-classifier`, which fails with "No calibration
  quadrats found" seconds after launch -- easy to mistake for a still-running job if nothing is
  watching it.
- **A "national" OSM pull is not national until it is clipped to the border.** Two
  independent leaks, both live until 2026-09-15 and both invisible while the atlas dropped
  OSM outside its density grid: `export.load_mapped_reference_attrs` globs
  `data/labels/*_overpass_solar.parquet` AOI-agnostically, so Germany's national file spanned
  lon 5.9-75.4 and reached into Pakistan (249,115 of 475,210 features were foreign); and a
  bbox pull is not a border pull, so only **21.8%** of `france_overpass_solar.parquet` is
  actually in France, most of the remainder being Spanish. `--include-offgrid-osm` made both
  visible at once by turning every foreign feature into a map cell.
  `prepare_national_osm_solar.py` now clips on the geoBoundaries ADM1 union by default
  (`--no-clip` opts out), as `scripts/overpass_labels_chunked.py` already does at pull time.
- **Overture prunes its release directory to the last two releases.** `configs/aoi.yaml`'s
  pinned `overture_release` will eventually 404 as `IO Error: No files found`, which reads like
  "no data for this area" rather than "your release expired". Check
  `https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/?list-type=2&prefix=release/&delimiter=/`
  for what still exists. Overture is also ~166 s per commune from here; for France the DGFiP
  cadastre is the same footprints per INSEE in ~2 s.
- **Anything that loads every scored building at once will OOM.** 25M buildings reprojected in
  one go peaks at **22.7 GB**; stream per cell instead (`calibrate_germany_capacity.py` does,
  at 2.6 GB). Run long jobs with `--property=MemoryMax=` so a regression fails fast rather than
  thrashing swap.
- **A new atlas component must be INCREMENTAL before it goes in.** Best already carries
  segmentation's own detections and the hand-mapped OSM population, so a component crediting
  every building double-counts. Germany's first build read 97.2 GWp before deduping against
  both layers and 61.9 GWp after.
- **The native-20 m bands are resampled BILINEAR since 2026-09-19, and the two modes must
  not be mixed within an AOI.** B05-B07, B8A, B11 and B12 are 20 m at the sensor; odc.stac
  previously replicated each value nearest-neighbour into a 2x2 block (measured: B11/B12
  are 2x2-constant over 100.0% of cell 0122_0077 against 0.0% for B02/B08), which
  misregisters the band a `roofclf` footprint sees by up to 10 m -- and the model's four
  largest coefficients are SWIR or SWIR-derived (`b11_mean` +4.33, `swir_vis_ratio` -3.92,
  `ndbi` +3.65, `b12_mean` -3.23, against +2.78 for the largest 10 m band). Bilinear is
  worth +0.0041 AUC within size band over 30 quadrats (20/30 folds, sign test p=0.061):
  suggestive, free, and shipped as the default (`imagery.BAND_RESAMPLING`,
  `compose --resampling`). **Every existing composite -- Pakistan, Germany, France, Zambia,
  Nigeria -- is `nearest`**, and composites now carry an `earthpv_resampling` tag (absent =
  nearest). `compose` INHERITS an AOI's existing mode by default and only gives a fresh AOI
  bilinear, so a resumable run cannot mix the two: that matters because a country-scale
  compose runs in a restart loop (`compose_loop.sh`), and the first pass after a default
  changes is exactly where silent mixing would happen. Recompose a country wholesale or
  leave it alone; a model calibrated on one and scored on the other is a domain shift. SCL stays nearest always (interpolating class 4 and class 8
  invents class 6). *Sharpening* those bands by regression on the visible ones was measured
  and REJECTED (-0.0047 AUC, 7/30 folds, p=0.008): the SWIR signal is not predictable from
  the visible bands, which is why it carries weight in the first place.
- **`roofclf`'s zonal means are AREA-WEIGHTED by default since 2026-09-20, and the
  calibration and national scoring must never disagree about that.** `zonal_mean_max`
  rasterises with `all_touched=False`, so a pixel belongs to a building only if its CENTRE
  falls inside and **72.4% of Pakistani VIDA footprints own zero pixels**, falling back to a
  one-pixel representative-point sample. `roofclf.area_weighted_zonal_mean` weights each
  10 m pixel by the fraction of the footprint covering it instead
  (`preprocess.coverage_matrix`, subpix 4). Worth **+0.0119 AUC within size band** (24 of 29
  folds, p = 0.0005) and **+2.0 points of recall at a fixed precision of 0.500** (0.6386 to
  0.6583), for **no new imagery** -- which is what separates it from the reducer and
  frame-count changes in the same register section, both of which need a country
  recomposited. Applied in BOTH `building_table` and `score_buildings_national`, resolved
  from `roofclf.AREA_WEIGHTED_ZONAL`; `--no-area-weighted` on `roof-classifier` and
  `roofclf-score-national` reproduces every figure published before that date. The
  convention is recorded in `model_full.json` and in a scoring run's `_model.json`, and
  `check_scoring_matches_calibration` refuses a mismatched pair by name. Two details are
  load-bearing and were NOT in the experimental version: nodata is masked with the same
  all-bands-equal-fill test `zonal_mean_max` uses (unmasked, a cell-edge fill pixel reads as
  genuine near-zero reflectance, the mechanism behind the 45.6% cell-edge artefact), and a
  footprint with no subpixel of its own keeps the pixel-centre value rather than becoming
  NaN (the experiment silently dropped 0.16-0.47% of buildings, the smallest ones).
  **Both were run on 2026-09-20/21 and Pakistan's published figures DID move**: refit on 30
  quadrats, rescored over 4,471 cells, and the whole capacity chain re-run, taking Best
  estimate 18,826.7 -> **24,330.0 MWp** and Verified 5,725.1 -> **6,970.7**. The mandatory
  20-cell manual validation was generated (seed 20260920) but **not reviewed**, so the
  published figure currently rests on an unreviewed rescoring.
- **`preprocess.trimmed_mean_stack` replaces `np.nanpercentile` in every stack-reading
  path.** `np.nanpercentile` falls back to a per-1-D-slice Python loop the moment the array
  holds a NaN, which a cloud-masked stack always does: 24.5 s for one call on a
  (12, 10, 236, 245) stack against 0.08 s. The replacement is bit-identical (maxdiff 0, same
  NaN pattern, verified on full quadrat stacks), so `tmean_trim`/`trimzonal`/`year_trim`
  reproduce their published figures exactly.
- **A pre-2022 composite layer is on a different radiometric scale.** Scenes processed
  before Sentinel-2 baseline 04.00 (2022-01-25) carry no BOA offset and every model here is
  fitted on post-2022 composites, which carry +1000 DN. Pakistan's composite_1 (2021-10 to
  2022-01) reads 730-860 DN darker than composite_0 in every band on each layer's own dark
  tail; pass `roofclf.epoch_feature_frame(..., dn_offset=transfer_calibration.
  PRE_BASELINE_DN_OFFSET)` when scoring one. The growth pipeline did not (open question 10,
  "Growth as a product"). **But the offset is per cell, not flat (2026-10-22):** the 122 cells
  whose composite_1 was built 2026-07-05, 24 of the 30 quadrats among them, already sit on
  composite_0's scale, and the ~4,345 later cells read ~800 DN darker with a wide spread, so
  harmonize per cell (match each band's window median to composite_0) rather than adding 1000
  (`scripts/composite1_offset_survey.py`).
  And do not treat an old epoch as a negative set for `roofclf`: its 2021 score predicts
  today's PV at AUC 0.83 against 0.87, because it reads adopter-type roofs more than panels
  (experiments register, 2026-10-20).
- **Training positive threshold** is `MIN_PV_AREA` in `chips.py` (arrays below it are burned as
  `ignore = -1`, not negatives). Changing it requires rebuilding chips and retraining.
- **Geographic val split** uses `val_tiles` in `configs/aoi.yaml`; these must be MGRS tiles the
  `source_region` actually downloaded, or the val set ends up empty (datamodule then falls back
  to a random 20% split).
- **Areas are geodesic** (`labels.geodesic_area_m2`), never `.area` on lat/lon geometries.
- Long GPU/network stages are run detached (`nohup … &`) and polled; the rich progress bar does
  not flush cleanly to a redirected log, so watch checkpoint files / cell counts to gauge
  progress rather than parsing the log.
- **The aidisc drive is the binding constraint; `/home` (sda4, ~1.2 TB free) is where bulk
  outputs belong.** This applies beyond composites: national roofclf scoring passes are ~4.7 GB
  each, and `data/roofclf_national_germany_{vida,osm}` were moved to
  `/home/tobi/earthpv_data/roofclf_passes/` and symlinked back when aidisc hit 98%. Moving and
  symlinking preserves the data and the paths; deleting does not. Check `df -h` BEFORE a
  national run, and guard long writes so they stop short of 100% rather than taking the whole
  volume down.
- **A new AOI's composites MUST be symlinked onto `/home` (sda4, 1.3 TB), never written
  straight into `data/composites/<aoi>/` on the aidisc drive.** `data/composites/germany`
  and `.../pakistan` are symlinks to `/home/tobi/earthpv_composites/<aoi>` for exactly this
  reason; France was created as a real directory on aidisc and filled the 229 GB drive to
  **100% (2.0 MB free)** at 2,789 of 5,471 cells, taking the whole project's data volume
  with it. The failure does not name the disk: `compose` dies with Python **exit code 120**
  (a failure to flush stdout) and the log truncates mid-word, which reads like a crash. A
  country is roughly 10 MB/cell, so budget ~55 GB for France and check
  `df -h /run/media/tobi/aidisc` BEFORE starting, not after. Committed cells survive a
  disk-full (each is written to `.tif.tmp` and atomically renamed), so recovery is: move the
  directory to `/home`, symlink it back, and resume.
- **A country-scale `compose` leaks file descriptors and WILL die partway through; run it
  in a restart loop, not as a single invocation.** Measured on France 2026-09-04/05: the
  process dies with `OSError(24, 'Too many open files')` / `RasterioIOError: Attempt to
  create new tiff file ... failed` after roughly 150-300 cells, despite a 524,288 FD limit.
  It surfaces through whichever remote call happens to be next (a raster read, or the STAC
  API client), so the traceback varies. Two things make it look like something else:
  (1) a Planetary Computer **SAS token expires ~24 h after it is signed**, and a run that
  crosses that boundary gets a 403 storm which accelerates the leak -- but the leak happens
  on a fresh token too, so the token is not the root cause; (2) `annual_composite` fails
  over to Earth Search on the 403s, so **the data is fine** -- all 224 cells from the first
  France run passed a fill-fraction/max-reflectance check, including the 85 written after
  the token expired. **Throughput is unaffected by the leak** (~0.74 cells/min either way),
  so the fix is to re-invoke `compose` (resumable, idempotent) in a loop, which also
  re-signs the token. **Cap each pass by WALL CLOCK, not by waiting for the crash** --
  restarting only on a non-zero exit is NOT enough and was measured failing: before it dies,
  the process DEGRADES, and a degraded pass looks identical to a healthy one from outside.
  France's pass 3 decayed 58 -> 172 -> 256 s/it with RSS past 8 GB, running at 0.17
  cells/min against 0.74, and never crashed, so a crash-triggered loop left it there for
  four hours. `scripts/run_france_national_compose.sh` now wraps each pass in
  `timeout 7200` and treats rc=124 as the expected path; a fresh process recovered to 0.80
  cells/min immediately. Budget passes generously (~90 cells per 2 h pass) and let "a pass
  added nothing" be the stop condition rather than a pass cap.
- **A restart loop's own watchdogs can LIVELOCK a compose that is otherwise perfectly
  healthy, and it reads in the log exactly like a provider outage.** Measured on Nigeria
  2026-09-19/20: the run reached 2,340 of 6,341 cells and then produced **zero cells for 17
  hours** across ten chain rounds, each logging "+0 this round" and paying its 1,800 s
  provider cooldown. The provider was never down. The link was **saturated at 6.3-6.8 MB/s
  throughout**, and a direct test of three missing cells composited two of them (47.8 s via
  PC in the north, 297.8 s via Earth Search mid-country) while refusing the third for real
  (99% empty, Niger Delta cloud). Only **67 cells had ever failed**; the other ~3,934 were
  simply never reached. Mechanism: `imagery.PC_TIMEOUT_S` defaults to **60 s, which is a
  SINGLE-CELL number**. A cell is bandwidth-bound (~290 MB of COG reads against a
  ~380 MB/min link), so under N workers a perfectly healthy cell takes roughly N x its
  uncontended ~50 s, **every** cell trips the patience, and each hand-off downloads the cell
  TWICE because the abandoned PC attempt keeps reading in the background -- the same death
  spiral `imagery._PROVIDER_OVERRIDE`'s comment describes, entered from the other side.
  `compose_loop.sh`'s `STALL_S` then compounds it: at 600 s the watchdog killed every pass
  before a single contended cell could land, since a pass needs 4-5 minutes just to fetch
  VIDA, select cells and skip the ones already on disk. Fix (`scripts/run_nigeria_chain.sh`,
  committed under `4b64013`, whose message is about roofclf zonal means): `PC_TIMEOUT_S=600`
  passed to the compose unit via `systemd-run --setenv`, and `STALL_S=2400`. After it, three
  consecutive full 3,600 s passes gained 53/59/58 cells with `stall=0` throughout and a
  hand-off rate of 14% that did not climb. **The number that matters is that ~57 cells/h is
  1.6x the ~35 cells/h the same run managed BEFORE it locked up**: it was already paying for
  double-downloads on most cells and had merely not yet tipped into paying on all of them, so
  **a compose that is "progressing" is not evidence the patience is set right**. The
  diagnostic that separates the two cases in one minute is to measure the link -- a real
  provider outage leaves it idle, this leaves it saturated -- and to count `exceeded <N>s`
  hand-offs per landed cell. Set `PC_TIMEOUT_S` to several times the expected per-cell wall
  time whenever `workers` > 1, and keep `STALL_S` well above a pass's startup cost plus one
  slow cell.
- **`nohup setsid` alone does not survive a session logout on this machine.** systemd-logind
  kills a whole session's cgroup (all processes in it, `setsid` or not) when the session ends
  unless lingering is enabled. Run `loginctl show-user "$USER" | grep Linger` -- if `Linger=no`,
  `loginctl enable-linger "$USER"` once (no sudo needed for your own account) before launching
  anything multi-hour, or it can silently die with no error/traceback partway through.
