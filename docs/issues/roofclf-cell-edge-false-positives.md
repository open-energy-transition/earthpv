# Cell-edge false positives in the roof classifier

!!! success "SHIPPED (as of 2026-08-11)"

    Both bugs are fixed and the full downstream re-run (refit, national scoring, sub-400
    capacity, evidence atlas) completed 2026-08-06. The MWp figures in the outcome table
    below were invalidated the same day by the coverage-ratio fix and have moved several
    times since; current numbers are on [Capacity](../results/capacity.md). One residual
    item is still open and tracked in [Open questions](../open-questions.md): a building
    with no valid pixel in its own cell's tile scores NaN rather than being rescued by a
    targeted re-read.

Status: **both bugs (cell-edge fill and composite-tile grid-origin overlap) root-caused
and fixed in code, 2026-08-06. The full re-run (refit -> national scoring -> sub-400
capacity -> evidence atlas) was kicked off the same day; see the bottom of this doc for
the outcome.**

A JOSM review pass over `pixi run roofclf-tiles` output found dense clusters of
roof-classifier detections lining up along straight lines that do not correspond to
anything on the ground. The lines are the boundaries of the 0.1 degree composite cells
the national scoring loop iterates over.

## What it was

Not a model problem. `roofclf.score_buildings_national` scored a band of buildings along
every cell edge against **raster fill instead of imagery**, and the classifier reads fill
as near-certain PV.

The chain:

1. `CompositeIndex.read_window` takes an EPSG:4326 bbox. For a per-cell read that bbox is
   the tile's own bounds, which were themselves produced by projecting the tile's UTM
   bounds to lat/lon (`box(*transform_bounds(src.crs, "EPSG:4326", *src.bounds))`).
2. `read_window` projects that lat/lon box **back** to UTM. A lat/lon box is not a UTM
   box, so the round trip returns the envelope of the reprojected quad, which is strictly
   larger than the tile. Measured across Pakistan's 4,473 tiles the inflation is 50-70 m
   in central Punjab and **up to 357 m** at the worst tile.
3. `rasterio.merge.merge(srcs, bounds=wb, nodata=0)` honours the inflated bounds and fills
   everything the tile does not cover with **zeros**. In cell `0135_0078` (Lahore) that is
   a 5-7 pixel frame, 2.2% of the returned window.
4. `zonal_mean_max` averaged those zeros in with real pixels, and for a building whose
   footprint lies entirely outside the tile returned an all-zero reflectance vector.

Zero reflectance is darker than any real roof, and the classifier's whole signal is that
PV is dark with a characteristic SWIR shape. The fitted national model
(`data/roofclf_20260805_newquadrats/model_full.json`) returns, for an all-zero footprint:

| roof area | p(all-zero fill) | p(typical roof) |
|---|---|---|
| 30 m² | 0.484 | 0.036 |
| 100 m² | 0.735 | 0.100 |
| 400 m² | 0.906 | 0.280 |

The deployment threshold is 0.2407, so **a fill building is flagged at every roof size.**

## How big it was

Scanned over all 4,473 per-cell parquets in `data/roofclf_national_20260805/`. An
all-fill building is identifiable after the fact because `compute_sppi` of an all-zero
band vector is exactly 0.0:

- 81,762,684 building rows, 5,989,061 flagged at the 0.2407 deployment threshold.
- **2,862,254 rows (3.50%) are all-fill**, and **95.4% of them are flagged**.
- **45.6% of every flagged building in the country is a fill artifact.**

Spatially, in cell `0135_0078`, flag rate by distance from the cell boundary:

| distance to cell edge | n | flag rate | all-fill share |
|---|---|---|---|
| 0-25 m | 2,410 | **65.3%** | 63.2% |
| 25-50 m | 2,412 | 33.8% | 27.6% |
| 50-75 m | 2,538 | 11.9% | 3.1% |
| 75-100 m | 2,682 | 10.4% | 0.0% |
| > 800 m | 329,357 | 5.9% | 0.0% |

The training path was almost clean, which is why this went unnoticed: a quadrat's read
window is a small box well inside a tile. Of the 17 quadrats only `sialkot_calib_1km`
(1.0% of its window) and `sukkur_calib_2p63km2` (0.45%) contain any fill at all. So the
model was fitted on real pixels and deployed on a raster that has a fill frame in every
cell -- a train/deploy skew, not a modelling error.

## The fix

`zonal_mean_max` gained a `nodata` parameter. Passed `nodata=COMPOSITE_FILL` (0.0) for a
reflectance window, a pixel whose every band equals the fill value is relabelled to the
rasterization background, so it enters neither the sums nor the counts. A footprint left
with no valid pixel falls through to the existing representative-point branch, which now
also rejects a point landing on fill or outside the window, and returns NaN.

Callers:

- `score_buildings_national` **keeps the row** and writes `p_roofclf`/`sppi` as NaN,
  counted in `n_unscored_nodata` and logged. Keeping the row matters because
  `potential.large_roof_buildings` reads this table for footprint geometry alone and
  dropping rows would quietly shrink the national building population. NaN never
  satisfies `p_roofclf >= threshold`, so an unscored building cannot reach a capacity
  figure or a JOSM lead.
- `building_table` **drops** the row instead, with a warning -- an unfeaturisable
  building cannot contribute to a fit, and a silent NaN would poison `fit_logistic`'s
  standardisation.
- `sppi.score_buildings_national_growth` keeps the row with NaN SPPI in both epochs.

### Padding the read was tried and rejected

The obvious alternative -- request a wider window so the fill frame falls outside the
cell, letting `read_window` mosaic in the neighbouring tiles -- is worse, and measurably
so. Three reasons, all discovered by testing it:

- Composite tiles **overlap their neighbours by ~150 m strips** (cell `0134_0078` covers
  1.5% of `0135_0078`, and `0219_0117`, from a second grid origin, covers **31.9%** of
  it).
- `rasterio.merge`'s "first source wins" precedence is **filename sort order**, not "the
  cell's own tile". In `0135_0078`'s padded read the own tile sorts 5th of 10, so the
  cell's whole border strip gets re-sourced from differently-composited neighbours.
- The requested bounds are not on the source pixel grid (measured offset 0.275 px
  unpadded, 0.35 px padded), so `merge` shifts every pixel by a fraction of one, and by a
  *different* fraction once padded.

Measured, at the 0.2407 threshold:

| variant | Lahore edge < 50 m | Lahore interior > 500 m | isolated cell edge | isolated cell interior |
|---|---|---|---|---|
| before the fix | 49.3% | 5.95% | 90.3% | 3.86% |
| 150 m pad, no mask | 10.1% | 5.96% | 4.78% | 4.68% |
| **mask, no pad (shipped)** | **5.06%** | **5.95%** | **0.40%** | **3.86%** |

Masking alone puts the edge rate at or below the interior rate and leaves interior
buildings **bit-identical** to the current output. Padding leaves Lahore's edge 1.7x
elevated and moves the isolated cell's *interior* rate by +21% relative, for no benefit.

Verified on the real `score_buildings_national` over the first six cells: cells with no
fill reproduce the old flag counts exactly (308/308, 349/349, 576/576), and in cells with
fill the new NaN count matches the old `sppi == 0` count one-for-one (176/177, 1/1,
40/40).

The cost of not padding is that a building genuinely outside its own cell's tile now goes
unscored rather than being scored from a neighbour: 2,263 of 424,702 (0.5%) in Lahore,
9,140 of 304,710 (3.0%) in the isolated cell. That is the honest outcome -- the
alternative was scoring it against a different composite's radiometry -- but a targeted
rescue (re-read only the NaN buildings, with the own tile forced to win precedence and
the bounds snapped to its pixel grid) is a reasonable follow-up if the coverage loss
matters.

## A stopgap that needs no re-run

Because `compute_sppi` of an all-zero band vector is exactly 0.0, the artifact rows in
the existing output are identifiable post-hoc: **drop any row with `sppi == 0.0`**. On
cell `0135_0078` that leaves 26,802 flagged buildings against the 26,840 a correct re-run
produces -- 0.14% off, the residual being buildings whose footprint straddles the fill
frame and so was only partly corrupted. This is good enough to re-derive the sub-400 m²
capacity figures and to filter the JOSM lead files without waiting for the national pass,
and it is *not* a substitute for it.

## What has to be re-run

Everything downstream of `data/roofclf_national_20260805/`, in order:

1. `roofclf.score_buildings_national` nationally (~2h16m for one epoch on this machine).
   Expect roughly 45% fewer flagged buildings.
2. `sub400_capacity.domain_restricted_capacity` / `domain_restricted_and_gate_capacity`
   -> `data/sub400_20260806/sub400_{central,low}.parquet`.
3. `atlas.build_evidence_atlas` -> `docs/assets/interactive/pakistan_evidence_atlas.html`
   (canonical location as of 2026-08-06 -- this is the project's primary output, so it
   lives directly under `docs/`, not `results/`). Best estimate takes its small-PV
   component from those parquets.
4. `pixi run small-pv-leads` and `pixi run roofclf-tiles` (the JOSM layers that surfaced
   this).
5. `roofclf.run_roof_classifier`, to refit `model_full.json` on quadrat features that no
   longer average fill into `sialkot` and `sukkur`. The effect there is small but the
   deployment threshold is derived from the same fit.

The published sub-400 m² numbers should be treated as **unreliable until step 3 is
redone**, in the specific direction of over-counting.

## A second, independent bug found while testing this -- also fixed, 2026-08-06

`score_buildings_national` claimed that assigning each building to the cell whose bbox
contains its representative point means "every building nationwide is scored by exactly
one cell". That was false in two distinct ways, one narrow and severe, one shallow and
universal -- both stem from the same root cause (ownership tested against a tile's own,
slightly-larger-than-nominal geometry instead of an exact, non-overlapping canonical
grid), and both are fixed by the same change.

**The severe case: two different grid origins.** `configs/aoi.yaml`'s
`pakistan.grid_origin` snaps the pakistan AOI's grid to be *phase*-congruent with
Punjab's own (mod 0.1 deg), left over from an earlier on-demand `compose --aoi punjab`
run -- but phase congruency is not index equality: Pakistan's own snapped origin is
Punjab's origin minus 85 cells of longitude, so the same ground gets two
differently-numbered, both "valid-looking" canonical names (e.g. Lahore is `0134_0078`
under Pakistan's grid, `0219_0117` under Punjab's). Exactly 3 canonical cells nationally
were claimed by both grids, all three in the Lahore area, each pair sharing 52-81% of
its rows (measured by exact representative-point match): 240,704 / 201,898 / 340,961
duplicated instances, 783,563 total.

**The universal case: ordinary neighbouring tiles of the SAME grid.** Composite tiles are
deliberately ~0.101 deg, ~1% oversized on their own so `read_window` never gaps at a seam
(`density.py`'s own `_canonical_window` comment documents this). `density.py` crops that
buffer away before summing (`_canonical_window`); `score_buildings_national` did not --
it tested ownership against the tile's own inflated geometry directly, so a building in
that ~1% buffer strip was legitimately inside BOTH neighbours' geometries and got written
to both cells' output files. Measured directly on ordinary (non-Lahore, non-duplicate-
grid) neighbour pairs in the pre-fix output: `0135_0078`/`0135_0079` shared 0.54% of the
smaller cell's rows, `0061_0012`/`0061_0011` shared 2.40%, `0062_0012`/`0062_0011` shared
3.01%. Summed over the whole country this is far bigger than the severe case: re-running
the fixed code end-to-end (2026-08-06) dropped the national building count from
81,762,684 to 75,703,524, **4,885,803 fewer rows (6.0%)**, spread across 4,461 of the
4,470 surviving cells (i.e. almost every cell was inflated a little, not just the 3
duplicate-origin ones a lot) -- every single differing cell went down, never up,
confirming this was pure double-counting rather than noise.

**Fixed** by `canonical_composite_manifest`, mirroring the dedup `density.cell_manifest`
already does for probability rasters: recompute every composite tile's cell from its own
centre under the AOI's *own* grid origin (ignoring the tile's directory name), and where
two tiles land on the same recomputed cell, keep whichever tile's name already equals
that canonical name. `score_buildings_national` and
`sppi.score_buildings_national_growth` now iterate that manifest instead of the raw
composite index, and use each cell's exact canonical (non-overlapping, by construction)
0.1 deg box for both building ownership and the raster read -- so no cell pair can ever
claim the same ground again, independent of how many raw tiles happen to exist per bin,
and independent of whether the overlap came from a severe grid mismatch or the ordinary
per-tile buffer. Building counts per cell now match `national_cell_density.parquet`
(itself derived from probability rasters via `density.cell_manifest`, unaffected by
either version of this bug) exactly.

## Measured outcome of the full re-run (2026-08-06)

`scripts/run_roofclf_edge_fix_repipeline.sh` ran refit -> national scoring -> sub-400
capacity -> evidence atlas end to end (as a detached `systemd-run --user` unit,
~2h23m wall clock, almost entirely the national scoring pass):

| | before (buggy) | after (fixed) | change |
|---|---|---|---|
| national building rows | 81,762,684 | 75,703,524 | -6.0M (-7.4%, both bugs combined) |
| domain-restricted roofclf-only (Best-estimate component) | -- | 10,502.9 MWp | -- |
| domain-restricted AND-gate (internal floor component) | -- | 5,600.1 MWp | -- |
| evidence atlas: hand-mapped-plus-AND-gate floor | 13,697.1 MWp | 10,634 MWp | -22.4% |
| evidence atlas: Best-estimate tier | 21,354.8 MWp | 18,879 MWp | -11.6% |

Both figures fell, in the direction the diagnosis predicted (removing false-positive-driven
over-counting), by double digits. The refit itself moved little (18 quadrats, 91,840
buildings, median fold AUC 0.8824 vs the pre-fix 0.8876, deployment threshold 0.2405 vs
0.2407) -- almost all of the movement is the national scoring and downstream capacity
math, not the model changing. Pre-fix atlas backed up to
`results/pakistan_pv_evidence_atlas_PRE_edge_overlap_fix_20260806_backup.html`; new
outputs live at `data/roofclf/`, `data/roofclf_national_with_sppi/pakistan/`,
`data/sub400_20260806_fixed/`, and `docs/assets/interactive/pakistan_evidence_atlas.html`
(moved out of `results/` and into `docs/` the same day -- see below).

**Moved to `docs/`, 2026-08-06.** The evidence atlas is this project's primary output,
so its canonical copy now lives at `docs/assets/interactive/pakistan_evidence_atlas.html`
directly, with no separate `results/` original to keep in sync -- the docs site already
embedded it from exactly that path, and the README's hero screenshot
(`scripts/screenshot_pages.py`) now reads from there too. `scripts/build_docs_figures.py`
no longer syncs it in from `results/`. Historical dated backups (like the one above)
still land in `results/`, since a backup is not itself needed to build the docs.

`roofclf.run_roof_classifier`'s default `--out-dir` (`data/roofclf/`) and
`score_buildings_national`'s canonical national location
(`data/roofclf_national_with_sppi/pakistan/prob/`) are now established as the
project's ongoing "current" paths -- `scripts/build_small_pv_josm_leads.py` already
hardcodes them, so a future refresh only needs to re-run
`scripts/run_roofclf_edge_fix_repipeline.sh` (or its steps individually) against the
same paths, not a newly dated directory each time.
