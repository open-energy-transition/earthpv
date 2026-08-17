# Open questions

What is genuinely unresolved, as of 2026-08-15. This page exists so that the honest gaps are
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

### 2. `building_table`'s roof term counts a ground array that clips a shed as rooftop PV

`parcel_pv_area`'s rule 3 skips any installation at or above `YARD_MAX_INSTALLATION_M2`
(400 m2), because above that floor ground-mount is segmentation's instrument and the atlas
already prices it. The roof term next to it has no such guard: it intersects every mapped PV
polygon with every VIDA footprint regardless of placement or size. Harmless while ground-mount
above the floor was rare in the quadrats; not harmless now.

Measured on Kalat Rural (added 2026-08-17, sited deliberately to include ground-mount):
**69 of the 89 buildings the roof term labels has-PV are labelled solely because a >= 400 m2
ground array clips them**, on roofs whose median footprint is 29 m2. That is a 21.24% base
rate in a 46.5 bldg/km2 rural box, higher than Mardan's. Folding it in unchanged would fit the
sparse density band's coverage ratio on ground-mount, extrapolate that across millions of rural
buildings, and double-count against segmentation's own `est_mwp_rc_ground`.

The step: extend rule 3 to the roof term, then re-measure every existing quadrat's
`base_rate`/`pv_area_true_m2` to see how much it moves them (expected small outside Kalat,
since ground-mount above the floor is rare elsewhere, but that is an assumption until
measured). Until then Kalat Rural must be excluded from any refit by hand --
`roofclf.discover_quadrats` globs the label directory, so it is picked up automatically.
See [Calibration boxes](issues/pakistan-calibration-boxes.md)'s Box 17.

### 3. The correction that prices most of the atlas is fit outside the density range it is applied to

`coverage_ratio` and `area_recall` multiply both roofclf components, which are 15,080 MWp or
83% of the published Best estimate. Both are fit on the quadrats `select_calibrated_quadrats`
returns, and those span 872 to 4,195 bldg/km2. The cells they are applied to do not: **84.1%
of in-domain buildings sit in cells sparser than every quadrat in the fit**, at a
building-weighted median of 252 bldg/km2, and **9,842 MWp, 54% of the published Best
estimate, is priced by a multiplier fit entirely on denser ground**. The density
stratification meant to absorb this is close to degenerate at deployment: two bands, and band
0 is fit from 8 quadrats spanning 872 to 1,758 bldg/km2 and then applied to 92.1% of national
buildings, everything in the domain from 48.5 up to 1,737.

**Measured 2026-08-16.** The trust gate is not density-neutral: Spearman(density, rate_ratio)
is -0.577, the sparse density tercile passes at 0.44 against 1.00 for the middle one, and all
five sparse quadrats it drops fail above the ceiling rather than below the floor. Relaxing
`ratio_hi` moves the roofclf half by -8.4% (-1,270 MWp), non-monotonically, because admitting
a quadrat moves the band split. That is 20 times the component dropped from the atlas on
2026-08-15 for being unmeasured where applied. The published 90% interval does not cover any
of this, because every quadrat the bootstrap can resample sits in the wrong band.

The fix is mapping in an identified band, 300 to 600 bldg/km2 first, then 150 to 300; together
those hold two thirds of the exposure. Three things are cheaper and worth doing first:
backfill the missing `n_buildings` for `nasirabad_rural` and `tank_rural` (189 and 225, which
currently bars them from the fit outright, including the very quadrat that set the domain's
48.5 floor), record the fit's own density support next to the domain in the capacity
summaries, and settle the gate band explicitly now that its confounding is measured. Full
derivation, the sweep table and the reproduction script:
[roofclf calibration density mismatch](issues/roofclf-calibration-density-mismatch.md).

### 4. The calibration quadrats are purposive, not a probability sample

This is the single largest caveat on every capacity number the project publishes, and no
amount of additional modelling removes it. All 27 quadrats were chosen by a researcher to
span landscape types, not drawn at random from a defined national frame, so the intervals on
the [evidence atlas](results/capacity.md) are not a design-based margin of error and cannot
be made into one by adding more purposive quadrats.

What would actually close it is a probability sample drawn from the national
building-density frame, which does not exist yet. That is new mapping work rather than new
code. A cheaper partial route, not yet tried, is model-assisted estimation:
post-stratify the existing quadrats on auxiliary variables known for the whole population
(building density, roof-size distribution, nightlights, region) to get a design-consistent
national total with a variance estimate.

### 5. Ground-truth completeness is relative to the mapping imagery, not the satellite composite

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
still empty for all 27 quadrats, which is why the per-quadrat magnitude is unknown rather
than merely unstated. Backfilling them against Esri Wayback is the cheap first step;
[Calibration imagery dating](issues/calibration-imagery-dating.md) has the full costing. Another 
starting point is the Maxar Open Data Program, which provides dated imagery over several areas
in Pakistan (see [Open Issue #3](https://github.com/open-energy-transition/earthpv/issues/3))

### 6. Small ground-mounted installations have no instrument at all

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
gap to those external estimates.

**Measured 2026-08-16, and the open part narrowed.** The quadrats hold 262 strict
sub-400 m² ground-mount installations, not the 15 a five-quadrat hand count found, and
**98.5% of them sit within 30 m of a VIDA building** (98.5% too on an independent national
OSM sample, against 39.9% for random points in the same cells). So the candidate universe
does not have to be invented: a 30 m ring around the building index `roofclf` already scores
covers a tenth of the country and keeps the population. What does not work is detection at
that unit, which lands under 1% precision at 30% recall in every stratum tested. What
stays genuinely open is the size of the prize: a density-stratified estimate puts it at
1,492 MWp with a 90% interval of 435-3,526 MWp, and the whole spread sits in the
`< 150 bldg/km²` stratum, which holds 22.9% of national buildings and is represented by four
quadrats covering 16 km², all drawn around villages rather than in farmland. Mapping cropland
quadrats is the step that resolves it. See
[Small ground-mounted instrument](issues/small-ground-mount-instrument.md) for the full
measurements and what they rule in and out.

### 7. Manual review of the small size bins

In the 100 to 500 m² band, `p_real` is only pinned to [0.10, 0.89]. `earthpv
calibrate-sample` emits a stratified sample of unmapped candidates for human verdicts, and
roughly twenty verdicts per bin would collapse the widest remaining term in the calibration
table.

### 8. The out-of-domain population cannot currently be validated by eye

The published Best estimate no longer carries this component: it was dropped 2026-08-15,
precisely because it was the one part of the total that could not be validated where it was
applied. The question it leaves open is not the headline figure but the coverage of the
domain itself -- roughly a third of the country's cells (holding ~5% of its buildings) are
outside it and are now reported as nothing rather than as an extrapolation. The JOSM
validation batch built to test whether the domain could be widened with evidence
(`results/pakistan_roofclf_validation_outdomain/`) turned out not to be reviewable, because
the reference imagery there is too old to confirm or refute recently-installed small PV.
**Confirmed again 2026-08-17, this time on purpose-drawn quadrats rather than random review
cells.** Three low-density boxes were drawn specifically to widen the domain, mapped, and all
three came back with zero installations against 83 roofclf-AND-SPPI flagged buildings and
475.4 kWp claimed. The imagery over all three is very old, so the zeros are uninterpretable in
both directions, and none was registered: as confirmed zeros they would have moved the domain
floor to 11.8 bldg/km<sup>2</sup> (66.3% -> 95.6% of cells) and pulled the sparse band's
coverage ratio toward zero on evidence that does not support it. See
[Calibration boxes](issues/pakistan-calibration-boxes.md)'s Box 17. The blocker is now known
to apply to *any* box drawn in the sparse remainder, not just to the cells the random sampler
happened to pick, so it gates the domain-widening programme itself.

This is item 5 blocking item 8. Contemporaneous high-resolution imagery would unblock both;
free options worth checking first are Planet/NICFI monthly basemaps, which cover roughly to
30 degrees north and so include Sindh but not Punjab.

### 9. Two random-cell validation batches are generated but unreviewed

`results/pakistan_roofclf_validation_domain/` and `..._outdomain/` were drawn to measure
roofclf's precision against an unbiased population rather than the curated quadrats. Neither
has been through JOSM review. The protocol is in
[roofclf random-cell validation](methods/roofclf-national-validation.md), and the results
belong in `results/roofclf_random_validation_log.csv` so precision against that population
accumulates across batches.

### 10. A per-locality pose calibration

The [panel pose survey](results/pv-pose.md) fits a national pose distribution from glint.
Fitting a *local* pose from whatever installations a subdivision already has, rather than
assuming a national standard, is untried and would improve the yield modelling that turns
capacity into energy.

### 11. Sentinel-1 backscatter variance as a false-positive filter

Distinct from the corner-reflector hypothesis that failed. Multi-temporal backscatter
variance separates permanent structures from seasonally changing fields, and greenhouse metal
frames give a bright return, the opposite of PV. Cheap, and not ruled out by the negative
result on corner reflection.

### 12. Per-pixel glint anomaly counting

The statistic the [cell-aggregate glint test](issues/glint-spike-rate-density-estimator.md)
should have used. A 90th-percentile statistic over a whole cell only moves if roughly 10% of
the cell brightens at once; scoring each pixel against its own baseline does not have that
problem. Prototyped, never evaluated.

One piece of evidence now bears on it, and it cuts against the optimistic reading. A
pixel-level PSF matched filter, the most favourable per-pixel statistic available since it
is the optimal linear detector for a known shape, [loses to the aggregate p98-minus-annulus
statistic](issues/glint-psf-matched-filter.md) on verified positives and negatives. Per-pixel
work is not automatically better than an aggregate here, because the glinting patch's shape
and position are unknown and vary by date. A per-pixel counting statistic that does not
assume a shape is still untested and remains the open item.

### 13. Glint scene coverage is silently incomplete

The tile-major glint fetch is 22x faster and numerically identical, but revalidation found
that token expiry silently drops scenes for a large share of targets rather than erroring.
The try/except fix moved the failure from loud to silent without removing it. Re-running the
full study after a proper token-refresh fix is the only way to get a scene-count comparison
that means what it appears to mean. See
[Glint tile-batched coverage](issues/glint-tile-batched-coverage.md).

### 14. Growth as a product

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
