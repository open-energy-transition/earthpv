# Cell-edge false positives in the roof classifier

Status: **root-caused and fixed in code, 2026-08-06. The national scoring output on disk
(`data/roofclf_national_20260805/`) still carries the bug and every product derived from
it is affected.**

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
3. `atlas.build_evidence_atlas` -> `results/pakistan_pv_evidence_atlas.html`. The Verified
   and Best-estimate tiers both take a small-PV component from those parquets.
4. `pixi run small-pv-leads` and `pixi run roofclf-tiles` (the JOSM layers that surfaced
   this).
5. `roofclf.run_roof_classifier`, to refit `model_full.json` on quadrat features that no
   longer average fill into `sialkot` and `sukkur`. The effect there is small but the
   deployment threshold is derived from the same fit.

The published sub-400 m² numbers should be treated as **unreliable until step 3 is
redone**, in the specific direction of over-counting.

## A second, independent bug found while testing this

`score_buildings_national` claims that assigning each building to the cell whose bbox
contains its representative point means "every building nationwide is scored by exactly
one cell". That is false: composite cell bboxes **overlap**, so a building in an overlap
is written to both cells' parquets.

- Cells `0135_0078` and `0219_0117` overlap by 31.9% of area and share **137,556
  buildings, 32.4% of `0135_0078`'s rows**.
- 796 tile pairs overlap by more than 5% of either tile's area, involving 901 of the
  4,473 tiles (20.1%).
- Summed over those pairs, **2,221,352 duplicated building instances**, against a
  national per-cell row total of 81,762,684 -- so at least **2.7% of the national
  building population is a duplicate**. That is a lower bound twice over: it ignores
  every pair overlapping by less than 5%, and a building shared by three cells is counted
  once per pair rather than twice over.

The two grids appear to come from separate `compose` runs with different cell origins
whose output landed in the same `composites/` directory. This inflates the national
building count and double-counts area in anything that sums over the per-cell parquets
without deduplicating. It is **not fixed** -- the ownership rule needs a real
tie-break (e.g. nearest cell centre, or a canonical grid) and that changes national
totals, so it is left for an explicit decision.
