# Random-cell manual validation of roofclf (JOSM)

**Audience:** anyone reviewing model output in JOSM, and anyone deciding whether to
trust a `roofclf` capacity number.
**Status:** added 2026-08-06, alongside `--random-cells` in
`scripts/tile_roofclf_detections_geojson.py`. First batch (20 cells, seed 1) is in
`results/pakistan_roofclf_validation/`.

## Why this is essential, not optional

The [main workflow](../reproduce.md#the-full-pipeline)'s < 400 m² half is `roofclf`, a
classifier fit on the current set of hand-mapped calibration quadrats. Those quadrats are the only
ground truth this project has, but they are also **curated**: a mapper picked each one,
and the set leans industrial/urban because that is where mapping effort went first (see
[Calibration quadrats overview](calibration-quadrats.md)). A model that scores well only
on the ground its own evaluation set was drawn from is not evidence that it works
everywhere the evidence atlas reports a number for -- it is evidence that it works
*there*.

Random national cells are the deliberately un-curated counterpart. Nobody chose Cell
`0116_0107` because it looked interesting; it was one of 4,470 scored cells with an equal
chance of being drawn. A `roofclf` that holds up on an unpicked sample is a much stronger
claim than one that holds up on 17 hand-picked boxes, and a `roofclf` that does not is
exactly the failure mode the quadrats cannot see by construction.

This is why it belongs in [the full pipeline](../reproduce.md#the-full-pipeline) as its
own step, not as an occasional side-check: **every national `roofclf-score-national` run
should be followed by drawing a fresh random-cell batch and reviewing it**, and the
result should be recorded (see [Recording results](#recording-results) below) so skill
against the un-curated population is tracked the same way LOQO fold AUC already tracks
skill against the quadrats. A capacity number with no random-cell review behind it is
missing half its evidence.

## Generating a batch

```bash
pixi run roofclf-tiles -- --random-cells 20 --seed 1 --mapcss
```

This reuses the exact script and output convention `--all-quadrats` already uses
(`scripts/tile_roofclf_detections_geojson.py`) -- same complete-per-region tiling, same
JOSM GeoJSON schema, same `results/<aoi>_roofclf_validation/` output folder, so quadrat
and random-cell tiles sit side by side and a reviewer moves between them without
learning a second format.

What is different:

- **The cells are the unit, not a hand-drawn boundary.** Each region is one 0.1°
  national grid cell (~11 km × 11 km, ~121 km²) -- much larger than a quadrat, so expect
  more tiles per region (`--max-per-file` still caps each at 2,000 features).
- **Selection is random, not chosen.** `--seed` makes a draw reproducible (rerun the
  same command and get the same cells back); pick a fresh seed for a new, independent
  batch. Only cells with at least one flagged building are drawn by default -- an empty
  cell gives a reviewer nothing to check -- but `--include-empty-cells` samples the full
  national set including zero-detection cells, useful for spot-checking true negatives
  specifically.
- **Calibration overlap is still excluded** (the same `exclude_calibration_overlap` a
  `--cell` run uses): if a randomly drawn cell happens to contain a calibration quadrat,
  buildings inside that quadrat's own boundary are dropped, so a random batch never
  silently re-reviews ground already covered by `--all-quadrats`.

Defaults point at the current national scoring
(`data/roofclf_national_with_sppi/<aoi>/prob`) and the current calibration snapshot's
threshold (`data/roofclf/summary.json`) -- the same "current" paths
`roofclf-score-national` and `sub400-capacity` write to and read from, so a batch drawn
right after a national re-run always reflects that run, not a stale one.

## Reviewing in JOSM

1. **Load the layer(s).** File -> Open, point at one or more
   `pakistan_roofclf_tiles_<cell>_partN_ofM.geojson` files under
   `results/pakistan_roofclf_validation/`. Load the sibling `.mapcss` once (Preferences ->
   Map Paint Styles -> +) -- every tile in a batch shares the same style, so one load
   covers the whole batch, not one per file.
2. **Turn on a high-resolution background** (Esri/Bing, whichever JOSM has configured) --
   the polygons are Sentinel-2-scale detections, not something to judge against OSM's
   own tiles.
3. **Go feature by feature**, not by area. A detection's popup (or the relation editor)
   shows `p_roofclf`, `sppi`, `roof_area_m2` and `osm_matched`; use these to understand
   *why* the model flagged it, not just whether it looks right, since a systematic
   pattern (e.g. every miss is a bright metal roof) is worth more than a raw pass/fail
   tally.
4. **Classify each one**: real PV, not PV (false positive), or unclear (imagery too old,
   too small, ambiguous roof material -- do not force a call the imagery cannot support).
5. **Never edit OSM from this layer directly.** Every feature carries
   `do_not_upload: "earthpv model detection, NOT verified OSM data..."` for exactly this
   reason -- these are candidate detections, not verified installations. Confirming a
   detection is real means mapping the panel fresh, by eye, against the imagery, the same
   way any other quadrat installation is mapped ([quadrat mapping
   protocol](../calibration-mapping-protocol.md)) -- the detection tells you where to
   look, it does not supply the geometry to publish.

## Recording results

There is no automated scoring here -- a random cell has no exhaustive ground truth the
way a Rule-1 quadrat does, so this cannot produce an AUC or a recall number the way
`roof-classifier`'s LOQO folds do. What it produces is a **measured precision estimate on
an unbiased sample**, which the quadrats structurally cannot: per reviewed cell, record
at minimum

- cell id, seed, and threshold used (from the batch's own `earthpv.tile_bbox`/`region`
  metadata already embedded in each GeoJSON's `earthpv` block -- copy it, don't retype it)
- reviewer, review date
- counts: real / false positive / unclear
- any systematic pattern noticed (a roof material, a terrain type, a size band)

into `results/roofclf_random_validation_log.csv` (one row per reviewed cell; create it
with a header row of `date,reviewer,cell,seed,threshold,n_real,n_false_positive,
n_unclear,notes` if it does not exist yet). Pooling this log's `n_real` /
`n_false_positive` across batches over time is what turns "we spot-checked some cells"
into a national precision estimate with a sample size -- a single batch is a start, not
a conclusion; **CLAUDE.md's roofclf section should be updated with the pooled result**
once enough batches exist to say something the 17-quadrat LOQO number doesn't already
say.

## The first batch drew zero domain-matched cells -- fixed 2026-08-10

`--random-cells` draws uniformly from every scored cell with >= 1 flagged building
nationally (3,417 of 4,470), **not** from `sub400_capacity.national_cell_domain`'s 163
cells that the published capacity figure is actually restricted to (only 136 of those
163 have >= 1 flagged building). The first batch (20 cells, seed 1,
`results/pakistan_roofclf_validation/`) landed entirely outside the domain by chance --
every cell in it has building density far below the calibrated 553-5,258/km² range --
so a full review of it would measure precision on a population that contributes exactly
0 MWp to the atlas, not the population the number describes.

Two fresh, explicitly stratified batches were drawn the same session (`--cell` with an
externally-computed cell list stands in for a domain-aware `--random-cells`, since the
script has no domain flag itself):

- `results/pakistan_roofclf_validation_domain/` -- 20 cells drawn uniformly from the
  136 domain cells with >= 1 flagged building (seed 20260810). 86,733 buildings, 113
  tiles -- much larger per cell than the original batch, since domain cells are dense
  urban tiles, not sparse rural ones.
- `results/pakistan_roofclf_validation_outdomain/` -- 20 cells drawn uniformly from the
  qualifying cells OUTSIDE the domain (seed 20260811), kept as a second, explicitly-labeled
  population rather than silently mixed with the domain batch: a reviewer's precision
  estimate on THIS batch says something about the capacity outside the calibrated domain,
  not about the number the atlas reports.

**The density-calibrated domain has since grown substantially** (see
[Calibration quadrats](calibration-quadrats.md) for its current size), so the specific
cell counts above describe the domain as it stood on 2026-08-10, not today's -- but the
general lesson (a random-cell batch must be drawn domain-aware, or it silently measures a
different population than the one the atlas reports) still holds for any future batch.

Neither of these two batches, nor later random-cell batches drawn against subsequent
national scoring passes, has had its per-cell counts logged to
`results/roofclf_random_validation_log.csv` yet -- generating the tiles is not the
validation; someone needs to open them in JOSM per the steps above and log
real/false-positive counts. Until that happens, this project's precision figures rest
entirely on the hand-picked quadrats, and the domain-restricted capacity numbers (sub-400
central/AND-gate, >= 400 m² roofclf rooftop) have no unbiased-sample check behind them at
all. See [Open questions](../open-questions.md) for the current status of this backlog.
