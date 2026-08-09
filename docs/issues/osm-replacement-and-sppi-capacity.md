## OSM geometry replacement (shipped) + SPPI building-scoped capacity (validated, not yet national)

2026-07-29. Two features implemented together, following the plan/decision recorded in
this session: `todo.md` #5 (replace detected polygons with the mapped OSM polygon where
one exists) and adding SPPI (`docs/issues/sppi-spectral-index-evaluation.md`) as a
building-scoped, precision-calibrated PV detector.

### Part 1 -- OSM geometry replacement (shipped, ran nationally)

`postprocess.replace_with_osm_geometry` (new) swaps a candidate's polygonized blob for
the real OSM footprint when one is mapped within `--osm-match-distance-m` (default
30 m, `postprocess.NEAR_BUILDING_M`). Wired into `run_postprocess` right after
`area_m2`/`flag_oversize` on the model's own geometry but before the building join, so
placement classification runs on the corrected shape too. Default on
(`--osm-replace/--no-osm-replace`).

New in `export.py`: `load_mapped_reference_attrs` (an attribute-preserving twin of
`_load_mapped_reference`, which only ever kept `geometry`) and `match_mapped_polygons`
(returns which mapped feature matched and how far, not just a boolean, via the same
chunked local-UTM nearest-neighbor pattern as `new_lead_mask` -- kept as a separate
function rather than a refactor of `new_lead_mask` itself, since that function is
load-bearing for the published recall/precision calibration).

**Ran on `pakistan`, replacing the previous `candidates.parquet`** (backed up to
`candidates_pre_osm_replace_20260729.parquet`). Results:

- **2,022/6,566 candidates (30.8%) now carry the real OSM footprint.**
- Of those, **91% shrink** (median -10,652 m²) -- the model's polygonize-and-merge
  systematically over-draws relative to the true installation, exactly the known
  failure mode (`postprocess.MAX_CANDIDATE_M2`'s own docstring). 9% grow (OSM has the
  fuller site; the model only lit up part of it).
- **Oversize-flagged candidates dropped from 233 to 149** -- a direct, welcome
  side-effect: shrinking over-merged blobs pulls a meaningful share of them back under
  `MAX_CANDIDATE_M2`, recovering real capacity that was previously excluded as an
  unreliable blob. This is independently relevant to the still-open
  [density-force-recompute-plausibility-fail](density-force-recompute-plausibility-fail.md)
  investigation (Gilgit-Baltistan's ground-mount inflation), though it has not been
  re-run against this new `candidates.parquet` yet.
- Total candidate area fell 168.5M m² -> 126.7M m² (-25%).
- All replaced geometries pass `.is_valid` (real OSM ways occasionally have invalid
  topology -- self-intersections etc. -- that a model-polygonized shape never does;
  `shapely.make_valid` repairs them before the building-intersection join, which
  otherwise raises `GEOSException` on a country-scale run).

**Imagery-currency caveat, raised mid-session and addressed:** a replacement polygon is
only as current as the OSM mapper's own imagery, and mapping passes lag real
installation growth (`docs/calibration-mapping-protocol.md`). `overpass.py`'s query
changed from `out body geom` to `out meta geom`, so every freshly-fetched OSM feature now
carries its last-edit `osm_timestamp`, threaded through
`load_mapped_reference_attrs` -> `match_mapped_polygons` -> `replace_with_osm_geometry`'s
new `osm_match_timestamp` column, with a log line reporting how many matches are known
vs. unknown vs. >12 months old. **This is provenance, not a filter** -- no match is
excluded on age; a human/future pass can now audit staleness directly rather than
trusting silently. Verified live against the Sialkot quadrat bbox (182/182 features
returned a valid timestamp). The existing whole-country
`data/labels/pakistan_overpass_solar.parquet` (16,085 features, last fetched 2026-07-18)
**predates this field and was not re-fetched this session** -- refreshing it is the
natural next step (`earthpv overpass-labels --bbox <pakistan bbox> --name pakistan
--iso3 PAK`) but is a slower live-API operation than seemed warranted to do
unprompted; until then, its matches report `osm_match_timestamp` as unknown, honestly.

### Part 2 -- SPPI building-scoped capacity: quadrat validation (NOT promoted to national)

New module `src/earthpv/sppi.py` promotes the formula out of the one-off
`scripts/sppi_index_test.py`: `compute_sppi`/`add_sppi`, plus LOQO threshold calibration
(`calibrate_threshold_loqo`) and two measurement functions
(`sppi_only_incremental`, `recall_effect`). `capacity_calibration.derive_table` gained a
`recall_cands` parameter (defaults to `cands`, so every existing call site is
unchanged) -- the hook for measuring recall against segmentation ∪ SPPI, ready but not
exercised nationally.

Ran `scripts/sppi_capacity_validation.py` against `data/roofclf/buildings.geoparquet`
(no new national computation -- exactly the "quadrats first" scope decided with the
user). Two threshold criteria were tried:

- **Youden's J** (max sensitivity+specificity-1, `roofclf`'s own AUC-style framing):
  median held-out precision **0.272**, and the arid quadrat (Quetta) fell to **4.9%**
  precision at 2,848 flagged buildings -- unusable.
- **Precision-targeted** (most conservative threshold clearing 50% precision on the
  training pool, leave-one-quadrat-out): median held-out precision **0.524**, a real
  improvement, and the right criterion for a *capacity-contributing* detector where a
  false positive directly inflates the published number (`sppi.calibrate_threshold_loqo`
  now defaults to this).

**Result, precision-targeted, per quadrat** (buildings SPPI flags that the segmentation
raster's own raster misses, i.e. `seg_max < 0.3`):

| quadrat | n flagged | precision | incremental capacity |
| --- | ---: | ---: | ---: |
| Karachi coastal | 28 | 0.857 | 829 kWp |
| Sundar | 9 | 0.778 | 241 kWp |
| Multan | 14 | 0.714 | 371 kWp |
| Lahore | 37 | 0.676 | 613 kWp |
| SITE Karachi | 21 | 0.524 | 1,461 kWp |
| Sialkot | 79 | 0.468 | 947 kWp |
| Faisalabad | 37 | 0.405 | 893 kWp |
| **Quetta (arid)** | **955** | **0.105** | 1,804 kWp (untrustworthy) |
| **Mardan** | **2** | **0.000** | ~0 kWp (threshold didn't transfer) |

Recall effect (does "segmentation OR SPPI" catch more true installations, the same
question `derive_table`'s recall block asks nationally): median recall rose from
**1.9%** (segmentation-only, matching this session's earlier finding that segmentation
is near-chance in non-industrial quadrats) to **63.2%** (combined) -- a large, genuine
effect on the recall side, independent of the precision question above.

**Go/no-go: NOT YET READY for national deployment**, for two distinct reasons, not one:

1. **Building-scoping reduced but did not fix the arid false-positive mode.** Quetta
   still lands at 10.5% precision even restricted to buildings -- a building sitting in
   or near bright bare terrain still carries enough of that background signal in its
   zonal-mean reflectance to confuse SPPI. This is the exact failure this design was
   meant to close and it is only partially closed.
2. **A single pooled threshold does not transfer to every quadrat.** Mardan collapses to
   2 flagged buildings under a threshold fit on the other 8 -- the same "no single
   national constant is defensible" lesson this project has already learned from
   `exp_scale` (49x quadrat spread) and `rate_ratio` (now 0.235-4.833 across nine
   quadrats).

**Before any national step**: either (a) exclude the regions `plausibility.py` already
flags suspect for ground-mount (Balochistan, Gilgit-Baltistan, Azad Kashmir) from this
mechanism specifically, and/or (b) add more quadrats per stratum before trusting one
pooled cut nationally -- the same prescription this project already follows for
`exp_scale`. Reproduce: `.pixi/envs/default/bin/python scripts/sppi_capacity_validation.py`.

### Part 3 -- a real double-counting bug in OSM geometry replacement, found via two new
ground-mount calibration quadrats (2026-08-06)

While building `sukkur_solar_farm_gmcalib_5p93km2` and
`quaid_e_azam_solar_park_gmcalib_14p07km2` (two ground-mount solar-farm calibration
areas -- OSM boundaries for the combined Helios/Meridian/HND/Scatec Sukkur complex and
Quaid-e-Azam Solar Park, see `docs/issues/pakistan-calibration-boxes.md` for the
boxes themselves), checking the two sites against the current `candidates.parquet`
surfaced a mechanism Part 1 above did not anticipate: **`replace_with_osm_geometry`
matches each candidate independently to its own nearest OSM feature, with no check for
whether two different candidates matched two OSM features that themselves overlap.**

Both Pakistani solar-farm sites checked turn out to have nested/duplicated OSM mapping
-- an outer envelope (tagged `generator:source=solar` at both sites, oddly, rather than
`plant:source=solar`) drawn over pre-existing finer per-phase/per-block mapping, with no
tags distinguishing the levels. At Quaid-e-Azam Solar Park this produced exactly the
failure mode: candidate 1682 matched the outer envelope (`osm-way/1530316244`,
8,904,839 m²) and candidate 1680 -- a **different, separately-detected** candidate --
matched one of its own contained member ways (`osm-way/596123516`, 1,745,036 m²,
confirmed **100% contained** within candidate 1682's replaced geometry). Both survive
independently in `candidates.parquet` and both get summed by `density.py`, so this one
physical site's ~8.90 km² footprint is currently double-counted to ~10.65 km²
(+20%) in any capacity estimate built from this candidate snapshot -- on top of, and a
different mechanism from, the ground-mount aggregation issues already tracked in
`docs/issues/density-force-recompute-plausibility-fail.md`.

The Sukkur site shows the opposite failure instead: only one candidate falls near the
site (44,948 m², `geometry_source=model`, never OSM-replaced) against a true dissolved
footprint of 2,606,013 m² -- a **58x undercount**, consistent with this project's
established "segmentation badly underestimates ground-mount" finding, now with a second,
independently-confirmed data point beyond Quaid-e-Azam Solar Park's own count-zero cell
(see the evidence-atlas `mwp_best` floor fix earlier this session).

**Not fixed here** -- this was found as a side effect of building the two calibration
quadrats, not the task in progress (the density/calibration re-derivation covering issue
#2's stale-candidates problem was already running when this was found). A fix needs
`replace_with_osm_geometry` (or a post-hoc pass over `candidates.parquet`) to detect when
two candidates' replaced geometries overlap and collapse them to one, keeping the
larger/more-complete match -- worth doing together with, not separately from, whatever
`candidates.parquet` rebuild eventually resolves the OSM-replace/stale-recall
reconciliation flagged as still-open in CLAUDE.md's "Three more measured issues" entry.

The two new quadrats are deliberately named `..._gmcalib_...` rather than `..._calib_...`
so `roofclf.discover_quadrats()`'s glob (`*_calib_*_boundary.geojson`) does not pick them
up -- they test ground-mount segmentation/capacity, not per-building rooftop
classification, and mixing ground-mount PV into roofclf's training population would
contradict the placement-separation this project already enforces everywhere else
(rooftop vs. ground-mount kWp/m² constants, `sub400_capacity`'s roof-only scope, etc.).
Each quadrat's own ground truth also needed a fix before use: the raw Overpass pull
returned 21 (Sukkur) and 6 (QASP) overlapping/nested elements whose areas sum to far more
than the true footprint (8.63 km² raw vs. 2.61 km² dissolved at Sukkur; 22.20 km² raw
vs. 8.90 km² dissolved at QASP) -- both quadrats' `*_overpass_solar.parquet` now hold one
dissolved-footprint row instead of the raw multi-row pull.
