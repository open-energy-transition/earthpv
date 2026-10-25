# Pakistan PV evidence atlas: downloadable data (2026-10-25)

This release accompanies the [Pakistan PV evidence atlas](https://open-energy-transition.github.io/earthpv/atlas/)
built by [`earthpv`](https://github.com/open-energy-transition/earthpv). It reproduces the
page as published on 2026-10-25: **Best estimate 34,588.8 MWp (90% range 29,308 to 41,736)**
and **Verified 6,994.1 MWp (90% range 6,041 to 9,091)**. All geometries are WGS84
(EPSG:4326); capacity columns named `*_mwp*` are MWp and `*_kwp*` are kWp (DC, peak).

**Every file is a point-in-time snapshot.** Nothing here is regenerated when the pipeline
reruns, so check this date against the atlas's own "generated" stamp before treating a number
as current. How each figure is derived: `docs/methods/density.md` and
`docs/methods/roofclf.md` in the repository.

## What changed since the 2026-08-14 release

- **roofclf is priced by probability (2026-10-25).** Both roofclf Best components now count
  every roof in proportion to its classifier score instead of counting only the roofs above a
  threshold. Held out one calibration quadrat at a time, that cut the median error on true
  sub-400 m² PV area from 0.386 to 0.094. Its two tables are therefore one row per grid cell
  and size bin, not one per building, and are renamed `..._by_cell_and_size.parquet`. Best
  moved from 24,438.3 to 34,588.8 MWp; Verified is unchanged. Why, and what it leaves
  untested: `docs/methods/roofclf.md`, "Count every roof by its score".
- **roofclf refit on 30 quadrats** with area-weighted zonal means (2026-09-20), up from 27.
- **OSM and the satellite estimate are combined, not added (2026-10-20)**: an OSM installation
  the satellite figure already stands in for is not counted a second time.
- **New: the atlas's own per-cell table** (`pakistan_atlas_capacity_by_cell.parquet`), every
  Best and Verified component per cell. Also new: the admin-region table, the fitted roofclf
  model and its calibration summary.

## Start here: Best and Verified per cell

**`pakistan_atlas_capacity_by_cell.parquet`** (4,463 rows): the map on the atlas page, one row
per 0.1° grid cell. This is the PyPSA-ready table. Its columns sum to the page's headline
figures.

| Column | Meaning |
| --- | --- |
| `lon0`, `lat0` | South-west corner of the cell; `geometry` is the cell polygon |
| `mwp_best` | Best estimate: `osm_mwp_unmatched + mwp_large + small_central + small_outdomain + small_ground`, floored at `mwp_verified` |
| `best_floor_lift` | What that floor added in this cell (632.5 MWp nationally) |
| `mwp_verified` | Verified: `osm_mwp + small_low` |
| `osm_mwp`, `osm_n` | Hand-mapped OpenStreetMap capacity and installation count, deduplicated |
| `osm_mwp_unmatched` | The part of `osm_mwp` the satellite estimate does not already stand in for |
| `mwp_large` | 400 m² and up: roofclf's rooftop estimate inside the calibrated domain, segmentation's recall-corrected rooftop outside it, plus segmentation's ground-mount everywhere |
| `small_central` | roofclf alone, rooftop below 400 m², priced by probability, inside the domain |
| `small_low` | roofclf AND SPPI agreeing, rooftop below 400 m², thresholded: the floor |
| `small_outdomain` | Out-of-domain extrapolation: 0, not published |
| `small_ground` | Farm ground PV below 400 m²: 0, not measured in Pakistan |
| `in_domain` | 1 inside the density-calibration domain (2,957 cells) |
| `is_extended` | 1 where an out-of-domain extrapolation contributes (none) |
| `model_covered` | 1 where imagery was processed (all cells) |
| `n_pv_buildings` | Segmentation's count of buildings carrying a detection |

National sums: Best 34,588.8, Verified 6,994.1, `small_central` 24,206.3, `mwp_large`
8,405.6, `small_low` 3,784.3, `osm_mwp` 3,209.8, `osm_mwp_unmatched` 1,344.3 MWp.

## Segmentation: arrays of 400 m² and up

- **`pakistan_capacity_by_cell.parquet`** (4,463 rows): the segmentation half on its own, per
  0.1° cell. Building count, roof area, and PV area/capacity under three estimators: `*_det`
  (thresholded candidate polygons, a precision-honest floor), `*_exp` (probability-weighted
  area, a ceiling), and `*_cal`/`*_rc` (calibrated, and recall-corrected). `est_mwp_rc` is the
  segmentation headline (4,051.9 MWp nationally; rooftop `est_mwp_rc_roof`, ground
  `est_mwp_rc_ground`), with `est_mwp_rc_lo`/`_hi` its interval. Inside the calibrated domain
  the atlas replaces `est_mwp_rc_roof` with roofclf's estimate, so for Best use the atlas
  table above. `bldg_density_km2` sets the density-calibration domain.
- **`pakistan_capacity_by_region.parquet`** (133 rows): the same estimators per admin unit,
  `level` `region` (7 provinces and territories) or `county` (126 districts).
- **`pakistan_capacity_by_building.parquet`** (91,424 rows): one row per building carrying a
  segmentation candidate: roof area, PV area and capacity (`det`/`cal`/`exp`), placement
  (`pv_placement`), region and district. **It sums to about 46% less than the cell table's
  rooftop total**: the cell table credits a candidate's whole polygon once, this table only the
  part intersecting each building's own footprint. Use it as a conservative floor for
  per-building disaggregation.
- **`pakistan_raw_detections_unreviewed.parquet`** (6,566 rows): the segmentation model's
  candidate polygons, before any human review: `confidence`, `area_m2`, `placement`
  (rooftop, ground_adjacent, no_building), `rank_score` (confidence times a building prior,
  used to rank mapping leads), `oversize` (above 100,000 m², excluded from capacity unless
  OSM-mapped), `geometry_source` (`osm` where an OSM outline replaced the model's), and the
  matched OSM element where there is one. **Leads, not validated ground truth.**

## roofclf: rooftop PV per building

roofclf scores every building footprint for "does this roof carry PV?". The capacity chain
converts score-weighted roof area to panel area with a coverage ratio, divides by area
recall, both measured on the calibration quadrats per size decile and density band, and
converts at 0.18 kWp per m² of module.

- **`pakistan_roofclf_sub400_central_by_cell_and_size.parquet`** (5,914 rows) and
  **`pakistan_roofclf_ge400_roof_by_cell_and_size.parquet`** (6,045 rows): the two Best
  components, below 400 m² and from 400 m² up, inside the domain. One row per cell
  (`cell`) and roof-size bin (`size_bin_lo`, the lower edge in m²: 0 and 100 below 400 m²;
  400, 1,000, 5,000 and 20,000 above). `n_buildings` is the buildings priced in the group
  (67.8 million and 636 thousand); `sum_p` is the sum of their scores, the expected number of
  PV-carrying roofs (2.89 million and 155.5 thousand); `roof_area_m2` is the group's
  capacity-weighted mean roof size; `geometry` is one real building's representative point,
  not the cell. `est_kwp_sub400`/`est_kwp_ge400_roof` is the capacity (24,206.3 and 7,503.2
  MWp in total). `est_kwp_sub400_ground`/`est_kwp_ge400_roof_ground` is the share of it that
  is ground-placed PV in the building's yard (213.0 and 66.0 MWp), which the atlas books as
  ground-mount.
- **`pakistan_roofclf_sub400_low_buildings.parquet`** (567,424 rows): the floor population,
  one row per building where roofclf (`p_roofclf` >= 0.2446) and the spectral index SPPI
  (`sppi` >= -0.0316) agree. Thresholded by design and not recall-corrected:
  `est_kwp_sub400_and_gate`, 3,784.3 MWp in total.
- **`pakistan_roofclf_sub400_outdomain_andgate_buildings.parquet`** (34,569 rows): the same
  agreement rule outside the calibrated domain, 189.4 MWp. **Not in the published figures**:
  it would apply a correction where no quadrat measured it.
- **`pakistan_roofclf_model.json`** and **`pakistan_roofclf_summary.json`**: the fitted
  logistic regression (features, coefficients, zonal convention) and its calibration summary
  (30 quadrats, median held-out AUC 0.868, 0.819 within roof-size band, deployment threshold
  0.2446).
- **`pakistan_calibration_quadrat_boundaries.zip`**: the boundary of each of the 30 quadrats
  roofclf was fitted on (every visible panel mapped by hand), plus `quadrats.csv`: buildings,
  PV buildings, held-out AUC, `rate_ratio`, and `coverage_ratio_quadrat` (True for the 19 the
  coverage ratio and area recall were fitted on). Per-quadrat history:
  `docs/methods/calibration-quadrats.md` and `docs/issues/pakistan-calibration-boxes.md`.

## Panel pose (glint)

**`pakistan_glint_pose_survey.csv`** (2,000 rows): a stratified survey of OSM-mapped
installations (`kind` generator or plant, size class `bucket`, `placement`, `area_m2`).
Per installation: Sentinel-2 scenes (`n_scenes`, cloud-free `n_clear`), specular-glint spikes
(`n_spikes`, `med_spike_amp`, `detected`), and where enough spikes agree, a fitted panel tilt
and azimuth (`fit_tilt`, `fit_az`, `n_consistent`, `validated`). A physical cross-check of
orientation, not a capacity estimate: `docs/methods/glint.md`.

## Model checkpoint

**`terramind_pv_segmentation_checkpoint.ckpt`**: the TerraMind `terramind_v1_tiny`
segmentation fine-tune that produced the detections and segmentation capacity above, the same
file as in the 2026-08-14 release. Load it with TerraTorch's `SemanticSegmentationTask`; the
10-band input is specified in `configs/terramind_pv.yaml` and `src/earthpv/config.py`. It is
not the project's released general-purpose model (see `docs/pretrained-model.md`).

## Everything mapped in OSM today (live, not a snapshot)

For the current state of hand-mapped PV in Pakistan, query Overpass directly:

```
[out:json][timeout:180];
area["name"="Pakistan"]["admin_level"="2"]->.searchArea;
(
  nwr["generator:source"="solar"](area.searchArea);
  nwr["plant:source"="solar"](area.searchArea);
);
out meta geom;
```

Paste it into [overpass-turbo.eu](https://overpass-turbo.eu/) for a map and GeoJSON export.
`out meta` carries each element's last-edit timestamp, which matters because the quadrats'
completeness is only as current as the imagery each mapper used.

The data files derive from OpenStreetMap (ODbL) and contain modified Copernicus Sentinel-2
data.
