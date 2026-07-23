## Status (2026-07-21): country-scale revalidation — flags hold up, scene counts don't

Ran `scripts/glint_revalidate_pakistan.py`: the same 500 OSM-confirmed Pakistan
targets used for the original per-target study (`pakistan_summary.csv`,
`pakistan_stats_by_size.csv`), re-pulled through `tile_scene_series_batch` (33
one-degree groups) and scored both ways — the default spatial-ring criterion and
the self-referenced one added for the dense-urban failure mode
([[earthpv glint direct detection]]). Output: `data/glint/pakistan_revalidate_tilebatch.csv`.

**Flag-level agreement is good:** `detected` matches the original per-target pull on
90.8% of targets, `validated` on 91.4%. Self-referenced vs default-criterion detected
agree 94.8% of the time — the two criteria aren't the source of any disagreement below.

**But the run itself was badly hit by the PC SAS-token-expiry problem** (the same
~30-45 min token lifetime documented in `compose_loop_preboom.sh`'s comments,
hitting a single long batched fetch instead of a resumable loop): it ran 2026-07-20
20:40 → 2026-07-21 11:01, ~14.5 hours wall-clock for what a 6-candidate single-tile
cluster test measured at ~22x speedup — 33 groups over 2 years of scenes should not
take that long. The log has 5879 lines of `GDAL`/`CPLE_AppDefined` read errors
(`response_code=403/206`, `TIFFReadEncodedTile`/`TIFFFillTile` failures) over that
span. Before this run, `_read_targets_from_item` only guarded the per-target read,
not the `rasterio.open()` asset-open itself — an expired token failed *there*,
outside any try/except, which crashed the whole run (no cross-group checkpointing,
so a crash 45 min in loses all 500 targets' progress, hit once already this session).
Wrapped the asset open too (see the diff), which is why this run finished at all
(500/500 targets returned ≥1 scene) instead of dying partway through.

**That fix converts a hard crash into silent data loss, and the numbers show it:**
comparing `n_scenes` (old per-target pull) to `new_n_scenes` (new batched pull) on
the 499 targets present in both — median target **lost 63 scenes**, mean 69 (one
target lost 316); **239/499 (48%) lost more than half** their original scene count.
Only 2 targets have 0 scenes in both (genuinely no coverage, not a regression). This
scene loss is NOT random noise — it lines up exactly with the per-bucket rate drop:

| bucket | pct_detected (orig) | pct_detected (new, default) | pct_detected (new, selfref) |
|---|---|---|---|
| <100 | 6.2 | 7.5 | 7.5 |
| 100-500 | 16.2 | 11.2 | 17.5 |
| 500-1k | 22.5 | 20.0 | 27.5 |
| 1k-5k | 44.7 | 35.3 | 38.8 |
| 5k-50k | 52.4 | 39.0 | 40.2 |
| >50k | 72.8 | 62.4 | 61.3 |

Every bucket except `<100` (which only needs 1 spike, so tolerates losing scenes)
reads lower with the batched fetch — worst in the large-array buckets that the whole
glint check exists to serve (LR boost is calibrated on ≥500 m²,
[[earthpv glint validation]]). 40 targets flipped from detected→not-detected
(scene starvation); only 6 flipped the other way.

**Conclusion:** the try/except fix was necessary (a crash losing all progress is
strictly worse) but is not sufficient — it just moves the failure from loud to
silent. The real fix is keeping a batched group's token fresh when it's actually
read: `_search_items_bbox` mints the SAS href at search time, and a group processed
tens of minutes later (queued behind earlier groups' retries) reads a stale URL
before ever hitting the per-target code. Either re-search immediately before each
group's reads instead of once up front, or apply the same bounded-runtime
auto-restart pattern `compose_loop_preboom.sh` already uses for compose (kill and
relaunch every ~25 min, well under the token lifetime, resuming from whatever's
already written). Re-running the full study after that fix is the only way to get a
scene-count comparison that means what it looks like it means.

---

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
