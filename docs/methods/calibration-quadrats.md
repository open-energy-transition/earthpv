# Calibration quadrats: overview

This is the single current-state table for every ground-truth calibration quadrat —
what `roofclf` (`earthpv roof-classifier`) trains and evaluates on, and the only source
of real recall/precision evidence below the segmentation model's 400 m<sup>2</sup> floor.
The narrative history of how each quadrat was mapped, re-pulled, and corrected over time
lives in [Calibration boxes](../issues/pakistan-calibration-boxes.md); this page is the
answer to "what do we have *right now*," regenerated from the label files directly
rather than hand-maintained prose.

## Why two different things are both called "calibration" here

- **This page** — hand-verified (or partially-verified) small areas where PV is mapped
  from OpenStreetMap/Overpass, used to measure the sub-400 m<sup>2</sup> detection gap and
  train/evaluate `roofclf`. See
  [the mapping protocol](../calibration-mapping-protocol.md) for how a quadrat is built.
- [Candidate-precision calibration](calibration.md) — a *different* mechanism
  (`configs/calibration/<aoi>_candidate_precision.yaml`) that scores whether an
  already-detected candidate is real, at country scale. It reads some of these quadrats
  too (`--calibration-box`), but answers a different question.

## Current quadrats

Regenerated 2026-07-30 directly from `data/labels/*_calib_*_boundary.geojson` +
their newest `_overpass_solar` pull (`_newest_solar`'s dated-file-wins rule) and a live
VIDA building fetch — not cached, not hand-typed. Source: `results/calibration_quadrats.csv`,
reproducible with the query in `roofclf.discover_quadrats`/`load_quadrat`. Sorted by
`base_rate` (ascending) — see below for what that column means.

| quadrat | province | stratum | Rule-1 | buildings | PV buildings | base rate | installations | median install m² | % sub-400 m² | packing (nn_median_m) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Quetta | Balochistan | 5 arid / bare-land | **yes** | 5,258 | 157 | **3.0%** | 73 | 103.9 | 94.5% | 44.0 m |
| **Peshawar East** | Khyber Pakhtunkhwa | 2/3 dense urban (unclassified) | no | 3,382 | 126 | **3.7%** | 131 | 44.9 | 100.0% | 17.3 m |
| Sialkot | Punjab | 2 dense old/informal urban | **yes** | 4,208 | 238 | **5.7%** | 181 | 63.9 | 98.3% | 18.8 m |
| Multan | Punjab | 6 industrial | no | 1,028 | 88 | **8.6%** | 45 | 877.1 | 26.7% | 50.8 m |
| Sundar | Punjab | 6 industrial | no | 735 | 72 | **9.8%** | 49 | 999.4 | 26.5% | 52.1 m |
| Faisalabad | Punjab | 6 industrial | no | 1,236 | 155 | **12.5%** | 84 | 665.9 | 28.6% | 45.8 m |
| SITE Karachi | Sindh | 6 industrial | no | 1,961 | 257 | **13.1%** | 70 | 1,059.9 | 14.3% | 46.2 m |
| Mardan | Khyber Pakhtunkhwa | 1/3 planned housing | **yes** | 4,751 | 654 | **13.8%** | 794 | 21.7 | 100.0% | 11.2 m |
| **Peshawar** | Khyber Pakhtunkhwa | 2/3 dense urban (unclassified) | no | 2,111 | 348 | **16.5%** | 360 | 71.5 | 99.4% | 15.7 m |
| Karachi coastal | Sindh | 1 affluent planned | **yes** | 929 | 172 | **18.5%** | 165 | 86.2 | 98.8% | 16.8 m |
| Lahore | Punjab | 1 affluent planned | no | 1,938 | 583 | **30.1%** | 1,034 | 31.1 | 99.9% | 7.2 m |

**Rule-1 = yes** means a human mapper declared every visible panel inside the boundary
mapped, verified against high-res imagery, per
[the protocol's completeness rule](../calibration-mapping-protocol.md#completeness-declaration-and-qa).
Only these quadrats' *negatives* (a building with no mapped PV) are trustworthy — for
every other row, "not mapped" can mean "genuinely no PV" or "nobody has mapped it yet,"
and the two are indistinguishable without a completeness pass. **Rule-1 = no** quadrats
are still used for training positives and general features (`roofclf` uses all eleven),
just not as a source of confirmed negatives.

!!! warning "Peshawar and Peshawar East overlap — not yet deduplicated"
    The two Peshawar boxes are ~995 m apart and share 6.56% of their area as one corner
    (checked before Peshawar East was created, added on the user's confirmation). That
    corner is disproportionately PV-dense: **42 of Peshawar East's 131 installations
    (32.1%) sit inside it.** Pooling both quadrats into `roofclf` training/LOQO without
    deduplicating that corner double-counts those ~42 installations and their host
    buildings, breaking the leave-one-quadrat-out fold-independence assumption for this
    pair. Not fixed yet — `roofclf.building_table` has no overlap-aware filtering today.
    The two boxes' very different base rates (16.5% vs 3.7%, despite sitting this close
    together) is itself the clearest illustration on this page of why `base_rate` cannot
    be pooled across quadrats, adjacent or not.

## What "PV density" means here, precisely

Two different numbers on this page are both reasonably called "PV density," and they
answer different questions:

- **`base_rate`** (the column this table is sorted by) — the fraction of *buildings*
  inside the quadrat that carry PV (`pv_area / roof_area >= 5%`). This is the number
  `roofclf`'s calibration work (see [Capacity density](density.md#national-deployment-a-scaling-success-with-one-clean-calibration-lesson))
  found does **not** transfer at a flat rate across quadrats — Quetta (3.0%) and Lahore
  (30.1%) are a 10x spread, and a classifier's raw predicted rate does not reliably tell
  you which regime a new area is in.
- **installation count / median size / % sub-400 m²** — describes the *shape* of the PV
  population, independent of how many buildings there are. Peshawar and Mardan both have
  >99% of installations below the detection floor with small median sizes (71.5 m² and
  21.7 m²) — a genuinely different population from the industrial quadrats' few-but-large
  arrays (SITE Karachi: 70 installations, median 1,059.9 m²).

Neither number is "the" PV density of Pakistan — each quadrat is a hand-picked landscape
sample (see the [protocol's stratum table](../calibration-mapping-protocol.md#the-quadrat-plan)),
not a random one, and this page's own base-rate spread is the clearest evidence that
pooling them into one national rate would be wrong. See
[Capacity density](density.md#sub-400-m2-experimental-capacity-density-stratified-deliberately-separate)
for how (and how cautiously) this evidence feeds a capacity number.

## Packing distance, at a glance

`nn_median_m` (median distance from a sub-400 m² installation to its nearest neighbour of
any size, `roofclf.packing_density`) splits the eleven quadrats cleanly into two
clusters, with nothing in between:

- **Tightly packed (7–19 m, informal/residential):** Lahore, Mardan, Peshawar, Peshawar
  East, Karachi coastal, Sialkot.
- **Sparse (44–52 m, industrial):** Quetta, Faisalabad, SITE Karachi, Multan, Sundar.

Quetta is the one landscape-vs-packing mismatch: an arid *settlement* (not an industrial
estate) that nonetheless packs sparsely — a reminder that packing distance is a proxy for
building layout, not a direct stand-in for the stratum table.

## Adding a new quadrat

1. Pick a center coordinate and pull a live Overpass snapshot for a precise geodesic
   1 km² box (`earthpv overpass-labels --bbox ...`) — see
   [the protocol](../calibration-mapping-protocol.md) for how to choose a *good* location
   (typical, not showcase; check this page for packing-distance/stratum gaps first).
2. **Check for overlap with existing quadrats before mapping** — a box within ~1 km of
   an existing center will share a corner with it, which is fine for an adjacent
   neighbourhood but worth deciding on deliberately, not discovering after the fact.
3. It is discoverable automatically (`roofclf.discover_quadrats`, globs
   `*_calib_*_boundary.geojson`) as soon as the boundary + a matching `_overpass_solar`
   file exist — no registration step beyond that.
4. It is **not** Rule-1 until a human mapper completes and a second mapper countersigns
   the completeness pass (protocol link above). A boundary + OSM snapshot, however fresh
   or often re-pulled, is not a substitute — see Peshawar's entry in
   [Calibration boxes](../issues/pakistan-calibration-boxes.md) for what that looks like
   in practice (three re-pulls the same day as new labels landed, still not Rule-1).
