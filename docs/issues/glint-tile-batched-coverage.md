## Status (2026-07-20): implemented

`earthpv.glint.tile_scene_series_batch` (+ `_search_items_bbox`, `_read_targets_from_item`,
`_read_target_stats` factored out of `_polygon_band_stats` so both paths share one
per-pixel implementation). Wired into both consumers named in the problem statement:
`postprocess.add_glint_prior` (new `tile_deg` param, default 1.0) and
`scripts/glint_density_pull.py` / `scripts/glint_candidate_precision.py`'s `pull`
commands (new `--batch`/`--tile-deg`, batched by default, `--no-batch` keeps the old
path). Measured ~22x wall-clock on a real 6-candidate cluster in one tile.

**Real bug found and fixed during validation** (synthetic-only testing would have
missed this): grouping by bbox instead of point means a target sitting near a genuine
Sentinel-2 tile-overlap seam can have items from an ADJACENT tile show up in its
group's search results. The original design (dedupe items by date *before* checking
per-target coverage, "keep the alphabetically-first item id per date-key") could keep
an item that does not actually cover a given seam-zone target while discarding the one
that does — silently, because `TileAngles.at()` always returns an angle via its
nearest-finite-node fallback even for a point outside real coverage, so the miss only
surfaces as zero finite pixels in the actual band read. Caught by comparing against
the original per-target `scene_series` on 6 real Pakistan candidates: one (sitting near
a tile seam) came back with 0/21 finite scenes in the batched path vs 19/20 clear in
the original. Fixed by moving the per-date dedup to AFTER reading, per target, keeping
whichever item actually had data (max `npx`) — verified this brings batched output to
exactly 0.000 numerical difference from the original on all matched scenes, plus one
extra genuinely-valid scene the bbox search found that the point search didn't.

---

# Batch glint queries by Sentinel-2 tile to scale coverage from hundreds to thousands

**Labels:** enhancement, glint, performance

## Problem

The glint check (`postprocess.py::add_glint_prior`) costs one STAC search plus
dozens-to-hundreds of per-scene metadata and band reads *per candidate* — ~1–2
min each, which is why it's budgeted to a few hundred candidates per run
(`--glint-top-n`). Coverage, not signal quality, is the binding constraint: the
calibrated likelihood-ratio boost (measured LR ~1.9–3.5× for ≥500 m²) applies to
every eligible candidate, but only the few hundred queried ever receive it.

The cost structure is wasteful because candidates cluster heavily in the same
MGRS tiles: every candidate in a tile re-runs the same STAC search over the same
scene list, and re-fetches the same `MTD_TL.xml` granule angles
(`glint._cached_tile_angles` caches these per item, but the item list itself is
rediscovered per candidate).

## Proposal

Restructure the pull from candidate-major to tile-major:

1. **Group eligible candidates by MGRS tile** (candidates are already polygons;
   the tile id is on every STAC item, or derivable from the geometry).
2. **One scene search per tile** for the lookback window, shared by all
   candidates in that tile.
3. **Per scene, one windowed read serving many polygons**: open each B03/B08
   asset once and read all member candidates' windows from it (rasterio COG
   range reads; adjacent candidates often share blocks), instead of each
   candidate re-opening the same assets.
4. Keep the per-candidate output contract identical (`scene_series` →
   `spike_fit` → `glint_spikes/consistent/fit_*` columns) so
   `add_glint_prior`'s scoring and calibration logic is untouched — only the
   fetch layer changes.

Cost goes from O(candidates × scenes) searches + asset opens to
O(tiles × scenes), with candidates-per-tile amortized to window reads. Pakistan's
candidate set concentrates in a few dozen tiles, so a full-candidate-list glint
pass (thousands of eligible candidates) should land in the same wall-clock range
as today's 300.

## Design constraints

- **Thread-safety:** pystac-client search is not thread-safe
  (`glint._SEARCH_LOCK`) — tile-major batching actually reduces lock pressure
  (one search per tile), but per-scene fan-out across candidates must reuse the
  existing GDAL env/session handling (`_GDAL_ENV`).
- **Resumability:** at thousands of candidates the pull will outlive PC token
  lifetimes and hit outage waves (see the Jul 16–17 AFD 504 wave). Persist
  per-tile (or per-candidate) partials the way `glint_density_pull.py` does, so
  a relaunch is lossless.
- **Provider fallback:** keep the PC→Earth Search fallback per tile, not per
  candidate, so a total PC miss doesn't multiply into per-candidate retries.
- The `--glint-top-n` budget knob should survive as a cap on *eligible
  candidates*, but its default can rise dramatically once cost is tile-major.
