# Pakistan capacity map

How much rooftop solar does Pakistan actually have? The honest answer depends on how much
proof you require, so this atlas gives two, not one: what a person has actually drawn in
OpenStreetMap, and this project's own best defensible estimate. Both read the same
underlying detections -- a segmentation model for individual arrays 400 m<sup>2</sup> and
larger, plus two independent per-building instruments (**roofclf**, **SPPI**) for
everything smaller that the segmentation model is trained blind to. A third, looser
tier (an explicit, uncalibrated ceiling) was published here through early August 2026 and
was retired 2026-08-06: a roofclf refit's lower deployment threshold roughly doubled it
with no accompanying validation, so it had stopped being a meaningful bound.

<div class="embed" markdown>
<iframe src="../../assets/interactive/pakistan_evidence_atlas.html" title="Pakistan PV evidence atlas: Verified and Best estimate" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Switch tier with the tabs, hover a cell for its value.
<a href="../../assets/interactive/pakistan_evidence_atlas.html" target="_blank">Open full screen</a>.
</p>

## Two tiers, one country

| Tier | Pakistan | What it admits as evidence |
| --- | ---: | --- |
| Verified | 7,384 MWp | Every installation a person has drawn in OpenStreetMap (16,085 of them), plus sub-400 m<sup>2</sup> buildings where **roofclf and SPPI both agree** -- two independent detectors, not one model trusted alone. |
| **Best estimate** | **14,473 MWp** | Verified, plus &ge;400 m<sup>2</sup> capacity (6,937 MWp: roofclf's own rooftop estimate inside the density-matched cells, segmentation's recall-corrected rooftop detections everywhere else, segmentation's ground-mount detections throughout -- see "Segmentation vs. roofclf on large rooftops" below), plus the roofclf per-building density estimate for sub-400 m<sup>2</sup> buildings inside the same cells -- the project's own pick. |

Both tiers fold in the same &ge;400 m<sup>2</sup> segmentation total; what changes between
them is how much of the sub-400 m<sup>2</sup> population each is willing to trust, and at
what precision. Neither double-counts, on either axis: OpenStreetMap-mapped installations
are matched by location and removed from the model-detected side before summing, **and**
(fixed 2026-08-06) the sub-400 m<sup>2</sup> instrument itself drops any building within 30 m
of an OpenStreetMap solar feature, not just those near an existing segmentation candidate --
without that second check, a building OSM had already mapped but segmentation missed
entirely could be counted twice (measured before the fix: 3.3-3.8% of the sub-400 m<sup>2</sup>
component's MWp, 343-438 MWp).

**Both tiers moved 2026-08-06 with three further fixes, none of them a new measurement --
each replaces an assumption with something already sitting in the calibration quadrats'
own ground truth:**

- **Sub-400 m<sup>2</sup> capacity no longer assumes a flagged roof is fully covered by
  panels.** It multiplied roof area by precision alone (the fraction of flags that are
  real), which silently assumed every real one is 100% module. Measured against the
  quadrats' own mapped PV polygons, a flagged sub-400 m<sup>2</sup> roof is on average
  only ~20-27% covered -- so precision alone overstated this component 1.4-2.3x. Both
  small-PV numbers now use the measured (true mapped PV area / roof area) ratio on the
  flagged population instead: central 10,503 &rarr; 3,906 MWp, low (the AND-gate) 5,600
  &rarr; 2,350 MWp.
- **OpenStreetMap dedup in the atlas itself is now geometric, not an id lookup.** The
  candidate-to-OSM match assigns one OSM id per candidate polygon even when that polygon
  overlaps several mapped installations (common in dense residential areas), so using
  that id set to mark "already found by the model" undercounted matches: 1,674 of 16,085
  installations against 3,022 found by a direct 30 m proximity check. The mapped-but-
  unmatched component fell 3,298 &rarr; 1,398 MWp accordingly -- that MWp was never
  missing, the model had already found it.
- **Best is now floored at Verified, per cell.** Best subtracts a cell's matched OSM
  value and substitutes the model's own estimate, which is occasionally smaller than
  what it replaced -- Pakistan's largest solar park read Verified 866 MWp against Best
  243 MWp before this fix. 62 of 4,463 cells needed the floor.

**A fourth change, 2026-08-07: roofclf now replaces segmentation's own rooftop estimate
for &ge;400 m<sup>2</sup> buildings inside the density-matched cells.** Measured on the
calibration quadrats' own &ge;400 m<sup>2</sup> buildings, roofclf discriminates real PV
far better than segmentation's own raster probability there (AUC 0.896 vs 0.73-0.78,
recall 94.2% vs 19-25% at matched precision) -- segmentation is a known weak instrument
for small PV, *including* a small array on an otherwise large roof, which is exactly
this population. Segmentation's own rooftop total stays in force outside the
density-matched cells (no roofclf evidence there) and its ground-mount total is
unaffected everywhere (roofclf has no footprint to score for ground-mount). See
"Segmentation vs. roofclf on large rooftops" below for the full comparison.

!!! warning "This is a research methodology under active validation, not a finished census"
    All 17 ground-truth calibration quadrats are now **Rule-1 complete** (every
    visible panel independently verified, as of 2026-08-05), and the density-matched
    calibration covers 92 of Pakistan's 4,463 grid cells. roofclf's own measured skill
    still varies by quadrat (AUC 0.76 to 0.94 across the 17) and its predicted rate does
    not reliably separate well-calibrated cells from over-predicting ones -- see
    [Capacity density](../methods/density.md) for what is independently corroborated
    and what is still open.

    **Segmentation's own &ge;400 m<sup>2</sup> total (5,078 MWp) is a separate, still-open
    provenance question outside the density-matched domain, not touched by the 2026-08
    fixes above.** It is computed from a `candidates.parquet` snapshot that predates the
    2026-07-29 OSM-geometry replacement (`postprocess.replace_with_osm_geometry`), which
    cut matched-candidate area by roughly a third by swapping coarse model polygons for
    the real mapped footprint, and from a recall table fit before the current
    16,085-installation national OSM pull existed. A combined re-derivation (current
    candidates + recall re-measured against all 18 Rule-1-complete quadrats) was carried
    out 2026-08-06: it moved the total to 2,327.2 MWp (roof 640.2, ground 1,686.9) -- but
    `check-density` failed on the result (Khyber Pakhtunkhwa and Balochistan both crossed
    from suspect to fail on their ground:rooftop ratio), so it was **not published**.
    Segmentation's *ground-mount* total (2,848 MWp) still comes from the original,
    passing 5,078 MWp snapshot everywhere, and so does its *rooftop* total outside the
    92 density-matched cells -- only inside those cells has rooftop now moved to the
    roofclf-based instrument described above, which does not depend on this open
    question. See CLAUDE.md's Density stage section for the full derivation, the failure
    numbers, and where the reverted attempt is kept for whoever root-causes it next.

## Segmentation vs. roofclf on large rooftops

Measured on the calibration quadrats' own &ge;400 m<sup>2</sup> buildings (5,004 of them,
13 quadrats, leave-one-quadrat-out): roofclf's per-building score reaches **AUC 0.896**
against segmentation's own raster probability at **0.726-0.775** (checked against both
the undocumented checkpoint roofclf's code defaulted to and `v3_combined_india`, the
actual production checkpoint -- the production one scores slightly *better* of the two,
so this is not an artifact of comparing against a weaker model). At matched ~54%
precision, per-building recall is **94.2%** (roofclf) against **19-25%** (segmentation).
Segmentation's blind spot is specifically small PV -- and that includes a small array on
an otherwise large roof, which a building-size filter alone does not screen out.
roofclf's rooftop capacity (`roofclf_ge400_capacity.py`) now replaces segmentation's own
rooftop estimate inside the 92 density-matched cells for exactly this reason; ground-mount
has no building footprint for roofclf to score, so it stays segmentation-only everywhere.

## Segmentation: the part of this that outlines panels

The &ge;400 m<sup>2</sup> segmentation total (5,078 MWp, [1,841 to 2,930] rooftop-only
credible interval once split by placement) is still the source for ground-mount capacity
everywhere and for rooftop capacity outside the density-matched domain (see above for the
in-domain rooftop swap). A recall-first TerraMind checkpoint reads a year of Sentinel-2
imagery across every building-populated cell, and pixels above threshold are polygonized,
joined to a building
footprint, and reweighted by a measured probability of being real before their area is
counted. Rooftop and ground-mount candidates convert to capacity at different rates,
because a rooftop detection outlines the panels while a ground-mount detection outlines
the *site* -- see [Capacity density](../methods/density.md) for both derivations, and
[Growth](growth.md) for how this same instrument changed between the 2021/22 pre-boom
epoch and now.

## Using it in an energy model like [PyPSA](https://pypsa.org/)

The density stage writes three layers under `data/predictions/<aoi>/density/`:

* `buildings.geoparquet` -- one row per building carrying PV signal, with roof area,
  PV area under each metric, estimated kWp and rooftop or ground placement.
* `grid.csv` and `grid.geoparquet` -- one row per 0.1 degree cell. The `lon_center` and
  `lat_center` columns map straight onto atlite or PyPSA-Earth cutout grids and Voronoi
  bus regions.
* `regions.*` -- per province, and with `--districts` per ADM2, additive totals with
  credible bands rebuilt from summed posterior draws.

Bin-level uncertainty is fully correlated across cells, so a regional interval must be
built from summed draws. Adding per-cell bounds gives the wrong answer.

## Reproducing this map

This is earthpv's [main workflow](../reproduce.md#the-full-pipeline), end to end: the
&ge;400 m<sup>2</sup> segmentation half, then the < 400 m<sup>2</sup> roofclf half, then
the atlas that combines them.

```bash
# >= 400 m2 segmentation half
pixi run earthpv calibrate-candidates --aoi pakistan
pixi run earthpv density --aoi pakistan --districts
pixi run earthpv check-density --aoi pakistan   # gate: exits non-zero on an implausible region

# < 400 m2 roofclf half -- needs mapped calibration quadrats first, see
# calibration-mapping-protocol.md. roofclf-score-national is the long pole (hours at
# country scale) and is resumable per cell like density.
pixi run earthpv roof-classifier --aoi pakistan
pixi run earthpv roofclf-score-national --aoi pakistan
pixi run earthpv sub400-capacity --aoi pakistan \
    --osm-solar data/labels/pakistan_overpass_solar.parquet

# roofclf's >= 400 m2 ROOFTOP swap (2026-08-07) -- same national scoring pass, just the
# large-building slice; replaces segmentation's rooftop estimate inside the same
# density-matched cells sub400-capacity already restricts to.
pixi run earthpv ge400-roof-capacity --aoi pakistan \
    --osm-solar data/labels/pakistan_overpass_solar.parquet

# Evidence atlas (Verified / Best estimate), combining all three.
# (--sub400-high-cells is no longer accepted here -- the Ceiling tier was removed
# 2026-08-06; it still exists for the older bracket atlas, see build_sub400_bracket_atlas.)
pixi run earthpv atlas --aoi pakistan \
    --osm-solar data/labels/pakistan_overpass_solar.parquet \
    --sub400-low-cells     data/roofclf_national_with_sppi/pakistan/density/sub400_low_incremental_buildings.parquet \
    --sub400-central-cells data/roofclf_national_with_sppi/pakistan/density/sub400_central_incremental_buildings.parquet \
    --ge400-roof-cells     data/roofclf_national_with_sppi/pakistan/density/ge400_roof_incremental_buildings.parquet
```

Neither `density` nor `roofclf-score-national` needs a GPU or retraining; both run on
rasters already on disk, each taking roughly two hours single-process for all of
Pakistan, and both are resumable per cell. See [Setup New
Country](../reproduce.md#the-full-pipeline) for the stages that produce those rasters in
the first place, and [Capacity density](../methods/density.md) for how `roofclf`/SPPI
and the OSM pull that feed the evidence atlas are themselves built.
