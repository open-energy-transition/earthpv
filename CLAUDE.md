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
- **`roofclf`** (`roof-classifier` → `roofclf-score-national` → `sub400-capacity` →
  `ge400-roof-capacity`) -- a per-building "does this roof carry PV?" classifier, cross-checked
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

earthpv sub400-capacity     --aoi <aoi> --osm-solar <national OSM solar pull>
earthpv ge400-roof-capacity --aoi <aoi> --osm-solar <national OSM solar pull>
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

A country with no mapped calibration quadrats yet gets the ≥ 400 m² segmentation-only atlas
(`earthpv atlas --aoi <aoi>`, no `--sub400-*`) until quadrats exist to fit `roofclf` -- that is
still this workflow's output for that country, just missing its sub-400 m² half (this is
Gujarat's current state).

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
who revisits this AOI.

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
the exclusion.

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

Current domain-restricted capacity figures (post 2026-08-13 second `roofclf` refit + national
rescoring, 27 quadrats including `nasirabad_rural_calib_2km` and `tank_rural_calib_2km`; the two
recall-corrected figures as of 2026-08-15): sub-400 central (feeds Best estimate)
**7,890.2 MWp**, sub-400 AND-gate (the internal floor population, uncorrected by design)
**2,179.7 MWp**, ≥ 400 m² roofclf rooftop replacement (in-domain) **7,189.4 MWp**.

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
published). **Current published result: Best estimate 18,218.4 MWp (90% CI 14,346-21,768)**
(2026-08-15: 16,608.7 -> 18,279.6 on the roofclf recall correction above, then -61.7 on dropping
the out-of-domain extrapolation; the floor is unchanged at 5,389.5 MWp throughout, as intended --
neither change touches it).
CLI: `--coverage-boot N` on `sub400-capacity`/`ge400-roof-capacity` (default 200; 0 disables and
narrows the reported interval), `--no-recall-correct` on either to reproduce the
pre-2026-08-15 flagged-population-only figures exactly.

Full derivation, every historical recalibration step, and every rejected instrument:
`docs/methods/density.md`, `docs/experiments.md`.

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

Nav runs **Results → How it works → Setup → Experiments → Open questions**, output first,
pipeline mechanics second, history last. `docs/experiments.md` is the canonical, dated register
of every experiment (shipped/partial/rejected/superseded) with links to the deep write-ups under
`docs/issues/`; `docs/open-questions.md` lists concrete, actionable open items (an item is
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

**28 quadrats as of 2026-08-17 (Kalat Rural, the most recent addition), spanning
Pakistan** -- purposive selections (industrial estates, dense residential blocks) plus several
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
All are declared **Rule-1 complete** by
the owner (every visible panel mapped) --
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
calibrated. **The full end-to-end per-municipality density comparison cannot run yet** -- Germany
has only 14 of 76 needed MGRS composite tiles and no VIDA building layer, and no calibration
quadrat exists there yet; `validate_density_against_mastr` refuses to report a partial-coverage
result as national. Full writeup: `docs/methods/mastr-validation.md`.

## Conventions & gotchas

- **GPU:** the target card is a **GTX 1060 (Pascal, sm_61)** → PyTorch must be **cu126** wheels
  (CUDA 13 dropped Pascal). Pinned in `pixi.toml`.
- **`data/` is gitignored** and lives on the external drive
  (`/run/media/tobi/aidisc/earthpv/data/`): `chips/`, `composites/`, `models/`, `predictions/`.
  Files there are invisible to git/IDE explorers that hide ignored files.
- **`row.mask` / `row.image` on a pandas row:** use bracket access (`row["mask"]`) -- `.mask`
  resolves to the `Series.mask` method, a bug hit more than once here.
- **Training positive threshold** is `MIN_PV_AREA` in `chips.py` (arrays below it are burned as
  `ignore = -1`, not negatives). Changing it requires rebuilding chips and retraining.
- **Geographic val split** uses `val_tiles` in `configs/aoi.yaml`; these must be MGRS tiles the
  `source_region` actually downloaded, or the val set ends up empty (datamodule then falls back
  to a random 20% split).
- **Areas are geodesic** (`labels.geodesic_area_m2`), never `.area` on lat/lon geometries.
- Long GPU/network stages are run detached (`nohup … &`) and polled; the rich progress bar does
  not flush cleanly to a redirected log, so watch checkpoint files / cell counts to gauge
  progress rather than parsing the log.
- **`nohup setsid` alone does not survive a session logout on this machine.** systemd-logind
  kills a whole session's cgroup (all processes in it, `setsid` or not) when the session ends
  unless lingering is enabled. Run `loginctl show-user "$USER" | grep Linger` -- if `Linger=no`,
  `loginctl enable-linger "$USER"` once (no sudo needed for your own account) before launching
  anything multi-hour, or it can silently die with no error/traceback partway through.
