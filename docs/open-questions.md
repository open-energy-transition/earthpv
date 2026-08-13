# Open questions

What is genuinely unresolved, as of 2026-08-11. This page exists so that the honest gaps are
findable in one place rather than buried in the write-up of whichever experiment first ran
into them.

It is deliberately separate from [Experiments](experiments.md), which records what was
measured and settled. Something belongs here only if a concrete next step exists and has not
been taken. When an item is closed it moves to the experiments register with a verdict, and
its row here is deleted rather than annotated.

## Ranked by expected value over cost

### 1. Keep turning the flywheel

More human-verified Pakistani installations, retrain, measure. Every shipped improvement in
[the experiments register](experiments.md) is smaller than this one. In-domain training chips
tripled large-array recall; nothing architectural has come close.

### 2. The calibration quadrats are purposive, not a probability sample

This is the single largest caveat on every capacity number the project publishes, and no
amount of additional modelling removes it. All 23 quadrats were chosen by a researcher to
span landscape types, not drawn at random from a defined national frame, so the intervals on
the [evidence atlas](results/capacity.md) are not a design-based margin of error and cannot
be made into one by adding more purposive quadrats.

What would actually close it is a probability sample drawn from the national
building-density frame, which does not exist yet. That is new mapping work rather than new
code. A cheaper partial route, not yet tried, is model-assisted estimation:
post-stratify the existing quadrats on auxiliary variables known for the whole population
(building density, roof-size distribution, nightlights, region) to get a design-consistent
national total with a variance estimate.

### 3. Ground-truth completeness is relative to the mapping imagery, not the satellite composite

Quadrats are mapped against OpenStreetMap's background imagery, whose capture date is
generally older than the Sentinel-2 composite the model reads. So Rule 1 certifies
completeness *as of the mapping imagery*, and the freshest installations cannot be mapped at
all. Known bias directions: measured precision is a lower bound, `base_rate` is a lower
bound, and `rate_ratio` is therefore an upper bound. Recall over mapped installations is
unaffected.

The magnitude is bounded but not resolved. Pooled over 13 quadrats the effect is only 5.8% of
apparent false positives, but per quadrat it dominates exactly where the sub-400 m² work
lives: 68.4% in coastal Karachi, 23.7% in Quetta, 11.7% in Lahore. The
`imagery_layer`/`imagery_date` fields exist in `results/calibration_quadrats.csv` and are
still empty for all 23 quadrats, which is why the per-quadrat magnitude is unknown rather
than merely unstated. Backfilling them against Esri Wayback is the cheap first step;
[Calibration imagery dating](issues/calibration-imagery-dating.md) has the full costing. Another 
starting point is the Maxar Open Data Program, which provides dated imagery over several areas
in Pakistan (see [Open Issue #3](https://github.com/open-energy-transition/earthpv/issues/3))

### 4. Small ground-mounted installations have no instrument at all

Both sub-400 m² instruments are per-*building* classifiers: they score a footprint. A small
free-standing ground array has no footprint to score, and the segmentation model was trained
with everything below its floor burned as `ignore`, so it gets no signal there either. This
is a distinct open gap rather than a smaller version of the rooftop one, and the partial
mitigations that work for rooftops do not generalise to it even in principle.

It probably matters more in Pakistan than the size of the gap suggests: solar-powered
irrigation tubewells are a large and fast-growing class of small ground-mounted arrays in
Punjab and Sindh farmland. Note that the rural quadrats' near-zero PV findings do **not**
bound this, because those are building-scoped measurements and a tubewell array sits on bare
ground.

**No longer just a plausible concern -- externally quantified, 2026-08-13.**
TransitionZero's satellite estimate (5.64 GW ground-mounted, mostly tube-wells) and
PRIED's independent household survey (5.04 GW agricultural) converge to within 12% of
each other despite disagreeing on the national total by ~6 GW -- and this project's own
published ground-mount total, *everything* combined (utility, industrial, agricultural),
is 2.2 GW. This is now the single largest, most confidently-explainable component of the
gap to those external estimates. Five of this project's own rural calibration quadrats
already have 15 hand-mapped small ground-mount installations (13.4-285.6 m²) sitting
unused by either existing instrument. See
[Small ground-mounted instrument](issues/small-ground-mount-instrument.md) for the full
evidence and a first sketch of what building one would need.

### 5. Manual review of the small size bins

In the 100 to 500 m² band, `p_real` is only pinned to [0.10, 0.89]. `earthpv
calibrate-sample` emits a stratified sample of unmapped candidates for human verdicts, and
roughly twenty verdicts per bin would collapse the widest remaining term in the calibration
table.

### 6. The out-of-domain population cannot currently be validated by eye

The Best-estimate tier includes a small extrapolated component for cells outside the
density-calibrated domain, priced with an explicit and deliberately wide allowance. The JOSM
validation batch built to test whether that domain could be widened with evidence
(`results/pakistan_roofclf_validation_outdomain/`) turned out not to be reviewable, because
the reference imagery there is too old to confirm or refute recently-installed small PV.
This is item 3 blocking item 6. Contemporaneous high-resolution imagery would unblock both;
free options worth checking first are Planet/NICFI monthly basemaps, which cover roughly to
30 degrees north and so include Sindh but not Punjab.

### 7. Two random-cell validation batches are generated but unreviewed

`results/pakistan_roofclf_validation_domain/` and `..._outdomain/` were drawn to measure
roofclf's precision against an unbiased population rather than the curated quadrats. Neither
has been through JOSM review. The protocol is in
[roofclf random-cell validation](methods/roofclf-national-validation.md), and the results
belong in `results/roofclf_random_validation_log.csv` so precision against that population
accumulates across batches.

### 8. A per-locality pose calibration

The [panel pose survey](results/pv-pose.md) fits a national pose distribution from glint.
Fitting a *local* pose from whatever installations a subdivision already has, rather than
assuming a national standard, is untried and would improve the yield modelling that turns
capacity into energy.

### 9. Sentinel-1 backscatter variance as a false-positive filter

Distinct from the corner-reflector hypothesis that failed. Multi-temporal backscatter
variance separates permanent structures from seasonally changing fields, and greenhouse metal
frames give a bright return, the opposite of PV. Cheap, and not ruled out by the negative
result on corner reflection.

### 10. Per-pixel glint anomaly counting

The statistic the [cell-aggregate glint test](issues/glint-spike-rate-density-estimator.md)
should have used. A 90th-percentile statistic over a whole cell only moves if roughly 10% of
the cell brightens at once; scoring each pixel against its own baseline does not have that
problem. Prototyped, never evaluated.

### 11. Glint scene coverage is silently incomplete

The tile-major glint fetch is 22x faster and numerically identical, but revalidation found
that token expiry silently drops scenes for a large share of targets rather than erroring.
The try/except fix moved the failure from loud to silent without removing it. Re-running the
full study after a proper token-refresh fix is the only way to get a scene-count comparison
that means what it appears to mean. See
[Glint tile-batched coverage](issues/glint-tile-batched-coverage.md).

### 12. Growth as a product

Per-epoch density estimates would make capacity a time series, so the 2022 to 2026 boom
becomes measurable per district and independently checkable against NEPRA net-metering
registrations and customs import series. A single [growth map](results/growth.md) exists;
an annual series does not.

## Known defects carried on purpose

These are understood, measured, and currently accepted rather than pending.

**The plausibility gate reports three failures on the published state.** Khyber Pakhtunkhwa,
Balochistan and Islamabad Capital Territory fail the single-cell-concentration check.
Checked rather than assumed: all three flagged cells are the calibration quadrats' own
cities, and the failures appeared only because shrinking a real ground-mount overstatement
mechanically raised the visible concentration share of whatever legitimate signal remained.
Published anyway, following this project's own precedent for a checked-genuine plausibility
failure. Gilgit-Baltistan is separately exempted from the ground-to-rooftop ratio check,
because its real rooftop base rate is near zero and the ratio is structurally uninformative
there.

**`buildings.geoparquet`'s rooftop sum is not the region total's rooftop component.** This is
structural, not a bug: the region total sums each rooftop-placed candidate's full polygon
once, while the per-building table credits each building only with its actual geometric
intersection. Measured at a 46.4% gap nationally, and confirmed by the recorded
`building_overlap_frac`. Any per-building disaggregation built from that file is a
conservative roof-anchored floor and should not be expected to sum back.

**Buildings with no valid composite pixel score NaN rather than being scored.** The
cell-edge fix excludes nodata fill from the zonal statistics, which is correct, but it leaves
0.5 to 3.0% of buildings in tile-overlap strips unscored. A targeted re-read from the correct
neighbouring tile would rescue them; it is not implemented, and the current behaviour is the
safe direction (nothing unscored can clear a threshold).

**Two segmentation checkpoints no longer exist on disk.** `v2_combined` and
`v3_combined_india` were deleted at some point after producing their outputs. The Gujarat
atlas is therefore built from a checkpoint that can no longer be verified against its own
weights, which is stated on [that page](results/gujarat.md). Nothing recovers this except
retraining.
