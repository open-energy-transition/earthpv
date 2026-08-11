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
| Verified | 6,139 MWp | Every installation a person has drawn in OpenStreetMap (15,642 of them, deduplicated -- see "Ground-mount fixes" below), plus sub-400 m<sup>2</sup> buildings where **roofclf and SPPI both agree** -- two independent detectors, not one model trusted alone. |
| **Best estimate** | **16,441 MWp** | Verified, plus &ge;400 m<sup>2</sup> capacity (7,860 MWp: roofclf's own rooftop estimate inside the density-matched cells, segmentation's recall-corrected rooftop detections everywhere else, segmentation's ground-mount detections throughout -- see "Segmentation vs. roofclf on large rooftops" below), plus the roofclf per-building density estimate for sub-400 m<sup>2</sup> buildings inside the same cells, plus 278 MWp of roofclf-AND-SPPI agreement **outside** those cells -- a clearly-marked extrapolation, see "A sixth change" below -- the project's own pick. |

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
  flagged population instead of precision: central 10,503 &rarr; 3,906 MWp, low (the
  AND-gate) 5,600 &rarr; 2,350 MWp (2026-08-06).
- **That ratio is now measured per building size, not as one flat number (2026-08-09).**
  A flat 19.9%/26.5% coverage ratio applied the same multiplier to a 50 m<sup>2</sup> roof
  and a 350 m<sup>2</sup> roof alike. Binning the same calibration-quadrat labels by each
  flagged building's own roof area (`sub400_capacity.coverage_ratio_by_size`, 10
  equal-count bins) shows real size structure instead: roofclf-only coverage ranges
  ~0.17-0.25 across the deciles (area-weighted mean 0.203, barely above the old flat
  0.199), while the AND-gate population is markedly steeper, ~0.21 in the smallest decile
  of flagged roofs up to ~0.46 in the largest (area-weighted mean 0.267 against the old
  flat 0.265). `roofclf_ge400_capacity.py`'s &ge;400 m<sup>2</sup> rooftop instrument now
  draws from this SAME calibration (one fit spanning both size regimes, since the ratio is
  continuous across the 400 m<sup>2</sup> boundary) rather than its own separate flat
  0.2372. Net effect on the aggregates, since a flat number was already close to the
  population-weighted average -- individual buildings' shares move more than the totals
  do: central 3,906 &rarr; 3,993 MWp, low (AND-gate) 2,350 &rarr; 2,364 MWp, &ge;400
  m<sup>2</sup> roofclf rooftop 3,432 &rarr; 3,380 MWp.
- **The density-matched domain widened from 92 to 163 of Pakistan's 4,463 cells
  (2026-08-09).** All three roofclf capacity functions only ever speak for cells whose
  building density falls inside `density.CALIBRATED_BLDG_DENSITY_KM2` -- a constant that
  had gone stale: it was fit on 8 (no-Quetta) quadrats in 2026-07-30 and never
  recomputed as the calibration set grew to 18. Recomputed from the density span of every
  currently Rule-1-complete quadrat (553-5,258 bldg/km<sup>2</sup>, not just the 13
  quadrats whose *precision* is separately trusted -- a quadrat like Quetta or Mardan is
  still real ground truth about density even where its roofclf precision is excluded from
  that narrower fit), this widens the domain to 3.7% of national cells / 24.5% of
  national buildings, still describing only those cells, not the country. Moved: central
  3,993 &rarr; 5,075 MWp, low (AND-gate) 2,364 &rarr; 2,807 MWp, &ge;400 m<sup>2</sup>
  roofclf rooftop 3,380 &rarr; 4,336 MWp. Ground-mount capacity is untouched by this
  change at every step -- roofclf has no footprint to score there, so nothing about this
  domain restriction ever applied to it.
- **The coverage ratio is now also stratified by building density, not pooled across the
  whole domain (2026-08-09).** `rate_ratio` (roofclf's predicted/true adoption rate) is
  close to flat across quadrats while true adoption spans 3-30% base rate -- standing
  evidence that a single pooled fit hides real structure by density regime, the same
  reasoning that motivated size-stratification a few hours earlier. The 13
  precision-calibrated quadrats split into two building-density bands at their own
  median (871-1,758 and 1,758-2,316 bldg/km<sup>2</sup>); each band fits its own
  size-binned coverage-ratio table, and a national cell is assigned to a band by its own
  measured density. The two bands turn out fairly close in their overall level (0.217 vs
  0.220 for roofclf-only) but differ more within specific size bins, and the AND-gate's
  two bands separate more (0.385 vs 0.317 overall) -- real, if modest, structure a pooled
  fit was averaging away. Moved: central 5,075 &rarr; 4,874 MWp, low (AND-gate) 2,807
  &rarr; 2,836 MWp, &ge;400 m<sup>2</sup> roofclf rooftop 4,336 &rarr; 4,269 MWp.
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

**A fifth change, 2026-08-11: ground-mount was overstated by two independent
mechanisms, both fixed, plus the "still-open" recall question below is now resolved.**
A full pipeline review found that OSM ground-mount solar features overlap (a
`power=plant` perimeter with a nested `power=generator` way, or duplicate mapping
passes) -- summing them double-counted real installations, measured at Quaid-e-Azam
Solar Park where 77% of the dissolved `generator` footprint already sat inside its own
`plant` perimeter. A new `labels.dissolve_overlapping` step merges overlapping features
before any capacity computation touches them (nationally: ground-mount OSM area
55.95 &rarr; 42.32 km<sup>2</sup>, -24.4%), wired into both the OSM-geometry-replacement
step and the atlas's own Verified-tier sum. Separately, the ground-mount site-area
conversion constant (`DEFAULT_KWP_PER_M2_LAND`) had never been checked against a real
plant -- calibrated against Quaid-e-Azam Solar Park (400 MW / 8,904,839 m<sup>2</sup>)
and the Sukkur solar farm (150 MW combined / 2,606,013 m<sup>2</sup>), it moved
0.07 &rarr; 0.05 kWp/m<sup>2</sup>. Combined with the recall/precision fix below and a
placement-split calibration (rooftop and ground-mount no longer share one set of area
bins -- pooling let ground-mount borrow rooftop's much higher OpenStreetMap
corroboration rate in the same size bin), the national segmentation total fell
**5,078 &rarr; 4,052 MWp**: rooftop rose **2,230 &rarr; 2,916 MWp** (+31%, it had been
diluted by ground-mount's low corroboration in shared bins) and ground-mount fell
**2,848 &rarr; 1,136 MWp** (-60%). Full derivation, including why `check-density`'s
ground:rooftop ratio check for Khyber Pakhtunkhwa and Balochistan now passes (0.49x and
2.01x, both previously 3-18x) while a *different* plausibility check flags three
regions for legitimate, checked reasons (their own calibration-quadrat cities --
Peshawar, Quetta, Islamabad -- naturally dominate otherwise sparse regions once the
ground-mount over-inflation that used to mask that concentration was removed):
`docs/issues/pakistan-calibration-boxes.md`.

!!! warning "This is a research methodology under active validation, not a finished census"
    All 19 ground-truth calibration quadrats are now **Rule-1 complete** (every
    visible panel independently verified) and re-pulled from live OpenStreetMap
    2026-08-10/11, and the density-matched calibration covers 136-163 of Pakistan's
    4,463 grid cells (the atlas's own domain-cell count vs. the wider density-only
    figure -- see `docs/methods/density.md` for why they differ). roofclf's own
    measured skill still varies by quadrat and its predicted rate does not reliably
    separate well-calibrated cells from over-predicting ones -- see
    [Capacity density](../methods/density.md) for what is independently corroborated
    and what is still open.

    **Segmentation's own &ge;400 m<sup>2</sup> total is now current, not a stale
    snapshot.** The previous version of this warning described an open provenance gap:
    the published 5,078 MWp figure predated the 2026-07-29 OSM-geometry replacement and
    used a recall table fit before the current national OSM pull existed, and a
    2026-08-06 attempt to fix both together (moving the total to 2,327.2 MWp) failed
    `check-density`'s ground:rooftop ratio check for Khyber Pakhtunkhwa and Balochistan
    and was not published. The 2026-08-11 fix above re-derives against the fully
    current candidates AND the full 19-quadrat recall reference, AND fixes the
    root-cause mechanism the 2026-08-06 attempt could not isolate (pooling rooftop and
    ground-mount into one calibration, rather than a missing regional stratum) --
    `est_mwp_rc` now stands at 4,052 MWp (roof 2,916, ground 1,136), fingerprint-verified
    against the current `candidates.parquet`, with `check-density`'s ratio check
    passing where it previously failed.

**A sixth change, 2026-08-11: roofclf-AND-SPPI agreement now extends into cells outside
the density-matched domain, folded into Best only, as a substitute for manual validation
that turned out to be blocked.** A random-cell JOSM validation batch was drawn
specifically to test whether the 136-163 cell domain above could be widened with
evidence, split between cells inside and outside it. The outside-domain half couldn't be
manually checked: the reference imagery behind it is too old to confirm or refute
recently-installed small PV. Requiring two independently-built detectors (roofclf, a
supervised classifier; SPPI, a zero-training spectral index) to agree is used as a
substitute standard of evidence for exactly this population --
`sub400_capacity.out_of_domain_and_gate_capacity` applies the same coverage-ratio fit
measured on the in-domain quadrats to every one of the other 4,300 national cells. **This
is a strict extrapolation, not a modest widening**: measured the day this was added,
every one of those 4,300 cells sits below the calibrated density band (median
87 bldg/km<sup>2</sup> against a calibrated floor around 553/km<sup>2</sup>) -- none
above it -- so the fit is being applied to a settlement-density regime with no
calibration quadrat anywhere in it. It adds **1,224 MWp** (217,751 buildings across 2,983
cells) to Best only, never Verified, moving Best **11,230 &rarr; 12,410 MWp**. On the map
these cells get their own dotted marker, distinct from the dashed calibrated-domain
outline, so the two standards of evidence are never visually conflated. Full derivation
in `sub400_capacity.out_of_domain_and_gate_capacity`'s docstring.

**A seventh change, 2026-08-11: two new calibration quadrats, an important negative
result about what actually widens the density-matched domain, and a recalibrated
trusted-quadrat set.** Two quadrats were added specifically to try to push the domain's
553 bldg/km<sup>2</sup> floor lower: `muzaffargarh_rural_calib_1km` (1 km<sup>2</sup>,
Muzaffargarh District) and `malok_calib_4p13km2` (4.13 km<sup>2</sup>, Lodhran District).
**Neither did** -- both measured their OWN building density above the current floor
(639 and 1,427.8 bldg/km<sup>2</sup> respectively), because a quadrat boundary drawn
around a real settlement (the only sensible way to draw one) reads far denser locally
than the sparse 0.1&deg;-cell average around it. A third boundary,
`muzaffargarh_rural_wide_calib_2km`, was deliberately placed to include open farmland
alongside a village and verified at 277.8 bldg/km<sup>2</sup> -- genuinely below the
floor -- and is now awaiting a JOSM completeness pass.

Malok's inclusion did move the numbers, though, and by more than just adding one
quadrat: refitting `roofclf` on all 21 quadrats shifted every quadrat's predicted rate
enough that Multan **dropped out** of the trusted 13-quadrat precision/coverage-ratio set
(rate_ratio crossed from just-under to just-over 2.0) while Sialkot, Hasal and Malok
**newly qualified** -- net 13 &rarr; 15. Losing an industrial estate with historically
high coverage lowered every domain-restricted figure: sub-400 central (Best) 3,907 &rarr;
**3,870 MWp**, sub-400 AND-gate (Verified) 2,257 &rarr; **2,091 MWp**, out-of-domain
extension (Best only) 1,224 &rarr; **1,149 MWp**, &ge;400 m<sup>2</sup> roofclf rooftop
&rarr; **3,156 MWp**. Evidence atlas: Verified 5,467 &rarr; **5,300 MWp**, Best 12,410
&rarr; **11,998 MWp**. The density-matched domain itself is unchanged (still 553.4-5,258.0
bldg/km<sup>2</sup>, still 136-163 cells) -- this move is entirely recalibration from a
richer quadrat set, not a domain-size effect. `docs/calibration-mapping-protocol.md`'s
Rule 1 definition was formally amended the same day to state its imagery-epoch bound
explicitly (a Rule-1 declaration certifies completeness as of the *mapping* imagery's
capture date, not the model's own Sentinel-2 epoch) rather than leaving that only as a
narrative caveat elsewhere.

**An eighth change, 2026-08-11, the same day: a third quadrat found the actual mechanism
for widening the domain and it worked.** The lesson from the seventh change's two
failed attempts was that a quadrat's OWN density, not its surrounding cell's average,
determines whether it extends `density.CALIBRATED_BLDG_DENSITY_KM2`'s floor -- and a
boundary traced around a settlement (the natural way to draw one) is always denser than
the land around it. `muzaffargarh_rural_wide_calib_2km` (4 km<sup>2</sup>) was
deliberately drawn to include open farmland alongside a village instead, verified at
**277.75 bldg/km<sup>2</sup>** -- genuinely below the 553.40 floor -- before asking it to
be mapped. It came back with **zero mapped PV installations**, the first confirmed-zero
quadrat in the set: real ground truth about a rural population with no adoption, not a
failed pull. (The OSM pull itself needed a manual work-around: the fetch tooling hard-
fails on any single empty Overpass response by design, with no path to ever accept a
*real* empty result -- resolved by gathering 8 independent non-timeout query responses,
all zero, well beyond the confirmation bar the tooling already trusts for a non-zero
pull, then writing a schema-matching empty parquet by hand.)

The floor moved **553.40 -> 277.75** bldg/km<sup>2</sup>, growing the domain from **163
to 646** of Pakistan's 4,463 cells (3.7% -> 14.5% of cells, 24.5% -> 48.9% of national
buildings) -- by far the largest jump in this constant's history, from one quadrat,
because it targeted the mechanism directly. Re-ran the full chain again: sub-400 central
(Best) 3,870 &rarr; **5,557 MWp**, sub-400 AND-gate (Verified) 2,090 &rarr; **2,676
MWp**, out-of-domain extension (now describing a smaller remaining population) 1,149
&rarr; **575 MWp**, &ge;400 m<sup>2</sup> roofclf rooftop &rarr; **5,049 MWp**. Evidence
atlas: Verified 5,300 &rarr; **5,886 MWp** (+11.0%), Best 11,998 &rarr; **14,462 MWp**
(+20.5%) -- real increases from new calibration coverage this time, not the
recalibration-only move of the seventh change. **Generalizable lesson for the next
quadrat**: to widen this domain further, size and place a boundary so its own average
deliberately includes enough non-built land to read below the current floor -- picking a
"low-average" surrounding cell and then tracing a settlement inside it, as both earlier
attempts did, will not work.

**A correction and a ninth change, same day: the eighth change's "confirmed zero" was
wrong, and a second widening quadrat pushed the floor down again.** The owner went back
to `muzaffargarh_rural_wide_calib_2km`, found PV the original sweep had missed, mapped
it, and reported the correction. Re-pulled once the mapping propagated: **12
installations** (not 0), base_rate 0.81%. What the eighth change's "8 independent
confirming queries, all zero" actually established was that the box held 0 OSM-mapped
installations *at that moment* -- true, but a different claim from "mapping is
complete," which only a person can attest to. `rate_ratio` (3.39) keeps this quadrat out
of the trusted precision subset regardless, so the correction changed no coverage-ratio
number directly, only the domain-restriction share every widening quadrat naturally
carries.

A second quadrat, `khairpur_rural_calib_2km` (Khairpur District, Sindh -- deliberately
outside the Muzaffargarh area for geographic diversity), used the same verified-before-
mapping method: 4 km<sup>2</sup>, checked at **141.0 bldg/km<sup>2</sup>** against VIDA
buildings before being handed over, confirmed with 3 ground-mount installations after
mapping. Combined, the two quadrats moved the floor **277.75 -> 141.00** bldg/km<sup>2</sup>,
growing the domain **646 -> 1,680** of Pakistan's 4,463 cells (14.5% -> 37.6% of cells,
48.9% -> 78.6% of national buildings) -- the largest cumulative widening yet, in two
verified steps. Re-ran the full chain once more: sub-400 central (Best) 5,557 &rarr;
**6,531 MWp**, sub-400 AND-gate (Verified) 2,676 &rarr; **2,929 MWp**, out-of-domain
extension (a much smaller remaining population now) 575 &rarr; **278 MWp**, &ge;400
m<sup>2</sup> roofclf rooftop &rarr; **6,427 MWp**. Evidence atlas: Verified 5,886 &rarr;
**6,139 MWp** (+4.3%), Best 14,462 &rarr; **16,441 MWp** (+13.7%).

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

The &ge;400 m<sup>2</sup> segmentation total (4,052 MWp, [1,894 to 3,402] rooftop-only
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
    --sub400-low-cells       data/roofclf_national_with_sppi/pakistan/density/sub400_low_incremental_buildings.parquet \
    --sub400-central-cells   data/roofclf_national_with_sppi/pakistan/density/sub400_central_incremental_buildings.parquet \
    --sub400-outdomain-cells data/roofclf_national_with_sppi/pakistan/density/sub400_outdomain_and_gate_incremental_buildings.parquet \
    --ge400-roof-cells       data/roofclf_national_with_sppi/pakistan/density/ge400_roof_incremental_buildings.parquet
```

`--sub400-outdomain-cells` is optional (added 2026-08-11) -- omitting it reproduces the
pre-2026-08-11 Best-estimate total exactly, folding in nothing for cells outside the
density-matched domain. Passing it adds roofclf-AND-SPPI agreement in those cells to
Best only, marked as a strict extrapolation (see "A sixth change" above).

Neither `density` nor `roofclf-score-national` needs a GPU or retraining; both run on
rasters already on disk, each taking roughly two hours single-process for all of
Pakistan, and both are resumable per cell. See [Setup New
Country](../reproduce.md#the-full-pipeline) for the stages that produce those rasters in
the first place, and [Capacity density](../methods/density.md) for how `roofclf`/SPPI
and the OSM pull that feed the evidence atlas are themselves built.
