# Open questions

What is genuinely unresolved, as of 2026-08-26. This page exists so that the honest gaps are
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

**Reach dropped an order of magnitude since this was first measured, apparently as a side
effect of an unrelated refit, not a deliberate fix -- re-verify before treating this as
closed.** As measured 2026-08-16: `coverage_ratio` and `area_recall` (83% of Best) were fit
on quadrats spanning 872 to 4,195 bldg/km2 while 84.1% of in-domain buildings sit in cells
sparser than every one of them (building-weighted median 252 bldg/km2), pricing 9,842 MWp
(54% of published Best) with a multiplier fit entirely on denser ground. Re-run
(`scripts/trust_gate_density_audit.py`) as of the 2026-08-17 parcel-label refit and again
after the 2026-08-20 Box 18 quadrats (Attock/Layyah/Lodhran) were folded in: the sparsest
quadrat surviving the trust gate is now 124 bldg/km2 (`bahawalnagar_rural`, whose own
`rate_ratio` moved 2.19 &rarr; 1.78 &rarr; 1.70 across the three fits and crossed the 2.0
ceiling sometime between 2026-08-16 and 2026-08-17), only 13.5% of in-domain buildings sit
sparser than every fit quadrat, and only ~5% of published Best is priced out of calibration
range -- essentially unchanged between the 2026-08-17 and 2026-08-20 fits, so the Box 18
quadrats did not move this finding further. **Nobody appears to have deliberately checked
Bahawalnagar Rural's rate_ratio against this page when it crossed the gate** -- worth asking
the owner whether that shift was noticed, since it is the whole reason this item's severity
changed. Full before/after table:
[roofclf calibration density mismatch](issues/roofclf-calibration-density-mismatch.md).

The trust gate is still not density-neutral (Spearman(density, rate_ratio) -0.36 on the
current 30-quadrat fit, versus -0.58 on 2026-08-16), so the *mechanism* is unfixed even
though its *reach* is now small. `nasirabad_rural` and `tank_rural` no longer lack
`n_buildings` (both are now scored -- 189 and 225 buildings respectively -- by every
`roof-classifier` run since 2026-08-13), so that specific blocker from the original
measurement is resolved; both still fail the gate on their own `rate_ratio` (tank_rural
0.307, below the 0.5 floor; nasirabad_rural undefined, zero true positives), which is a
legitimate exclusion, not a data gap. Remaining open work: settle the gate band explicitly
now that its (much smaller) confounding is measured, and directly extend the fit's own
density support into the remaining gap (50-125 bldg/km2, where the 13.5% still-uncovered
population actually sits) rather than the stale 150-600 bldg/km2 target. Eight unscreened
candidate quadrats targeting exactly that band, spanning Punjab/Sindh/Khyber Pakhtunkhwa/
Balochistan, are proposed and awaiting the owner's own imagery-recency check (no automated
check exists) in `data/labels/candidate_quadrats/*_gap_calib_2km_candidate.geojson` -- see
[Calibration boxes](issues/pakistan-calibration-boxes.md)'s Box 19.

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
an annual series does not (composites for 2022/23 to 2024/25 are being built).

The two-epoch diff itself failed its first sanity check and now carries a persistence
gate (2026-08-20). Almost all PV detected pre-boom should still exist post-boom, yet
only 26.6 percent of pre-boom segmentation candidates had any current-epoch detection
within 50 m (11.4 percent of model-geometry ones; rooftop 86 percent, ground_adjacent
44 percent, no_building 5.6 percent). The vanishing mass was concentrated above
latitude 34: winter snow in the 2021-10 to 2022-01 composite, scored by a precision
calibration that never saw snow, and let through `check-density` by Gilgit-Baltistan's
ratio-check exemption. It inflated the pre-boom level enough to turn the national
ground-mount delta negative. `growth.persistence_gate` now drops pre-boom candidates
with no current-epoch corroboration before the pre-boom level is recomputed
(pre-boom segmentation 5,646.5 to 4,408.6 MWp, ground 1,253.0 to 346.5; national delta
3,497.5 to 4,415.5 MWp), with the ungated values kept per cell as `*_preboom_ungated`.

What remains open, in order of expected effect on the delta:

- **The gate is one-directional.** Current-epoch-only false positives cannot be gated
  (they are indistinguishable from genuine new installations here) and are priced by
  `p_real` alone, so the residual false-positive bias on the delta is now upward where
  it was previously downward and much larger. A snow/SCL mask on the pre-boom
  composite, or a winter-free compose window, would remove the FP mode at the source
  instead of at the diff.
- **The roofclf halves are epoch-insensitive rather than unstable.** They passed the
  same persistence check (94 percent of pre-boom flagged cells still flagged, 3 to 4
  percent of capacity on dropped cells), but the pre-boom roofclf level reads about 79
  percent of the current one for a boom that multiplied the true sub-400 stock. Much of
  roofclf's signal is adopter-propensity building appearance that predates the panels,
  so the sub-400 and >= 400 roofclf deltas are floors on true rooftop growth. Measuring
  roofclf's epoch sensitivity directly (score the same mapped quadrat buildings on both
  composites and compare against known install-date installations, e.g. from the
  step-change onset set) is the concrete next step.
- **No composed credible interval on the delta**, and the pre-boom epoch has no
  calibration of its own, so every stated pre-boom level remains an artifact of
  current-epoch calibration transfer; only diffs of the fixed instrument are meaningful.

### 15. Nightlights as a substitute or complement to VIDA buildings

VIDA Open Buildings is a single load-bearing input across the pipeline: it is the unit roofclf
classifies (every VIDA footprint gets a has-PV score), the population
`density.CALIBRATED_BLDG_DENSITY_KM2` stratifies by, the layer `postprocess` joins against for
rooftop/ground/no-building `placement`, and the filter `compose` uses to decide which 0.1° cells
even get composited. It carries three costs this project has already hit: it is a **single
present-day snapshot** (a building built after the pre-boom epoch reads as bare ground in that
epoch's table -- `growth.persistence_gate`, item 14 above), its footprints are imagery-derived
and routinely undersized or a metre or two offset (the reason the parcel label's yard-overhang
term exists, see [The rooftop classifier](methods/roofclf.md)), and its per-country availability
is not guaranteed -- Germany has no VIDA file at all, one of three blockers to a full
MaStR-comparable atlas there ([Validation against MaStR](methods/mastr-validation.md)). VIIRS
nightlights is free, global, monthly, and none of those three problems apply to it, which makes
it worth asking whether it can substitute for VIDA anywhere, or at least flag where VIDA is
deficient.

**What already exists points away from a straightforward fix.**
`scripts/build_pv_external_comparison.py` correlates a 500 m VIIRS VNL v2.1 composite against
per-cell Best estimate: Pearson r = 0.76 raw, but only **r = 0.55 once log roof area is
partialled out**. Most of nightlights' apparent signal is therefore redundant with what
VIDA-derived building density already supplies, not independent information a stratification
model would gain by adding it. **2026-08-26: registered and rerun** against the current
18,826.7 MWp atlas -- both numbers barely moved (0.548 to 0.545 partial) despite a 14% shift in
the headline total since the script's only prior run (2026-08-12), so this looks like a stable
property of the estimate's geography, not an artifact of one refit; full numbers, including the
same result for the Relative Wealth Index, now live in
[Experiments](experiments.md#external-corroboration-from-nightlights-and-a-wealth-index). Read
that alongside [Capacity density](methods/density.md)'s own three failed attempts at finding
*any* coarse per-cell proxy (candidate density, roofclf's predicted rate, SPPI agreement rate)
for which quadrat-regime a national cell resembles -- a fourth coarse proxy succeeding where
three did not would be the surprise, not the default expectation.

**Resolution rules it out as a footprint replacement outright.** roofclf needs the footprint
geometry itself, not just a settlement signal: about half of Pakistani VIDA buildings are
already sub-pixel at Sentinel-2's 10 m GSD and fall back to a representative point, and VIIRS
DNB's ~500 m pixel is 50x coarser again on a side (2,500x by area). A brighter or dimmer pixel
does not tell `postprocess` which building under it is rooftop versus ground, or give
`sub400_capacity` a footprint area to divide by. Any role nightlights can play is at the cell or
region level, not the building level.

**Where it could plausibly still help, none of it tried:**

- **A VIDA-coverage plausibility check.** A cell that is bright in VIIRS but has implausibly low
  VIDA building density is a candidate for "VIDA is missing structures here" -- the same failure
  mode Germany hits at the country level, just at cell granularity. Cheap to compute (VIDA
  building count per cell against `zonal_ntl()`'s already-implemented per-cell mean radiance),
  and it would slot into `plausibility.py` alongside the existing ground:rooftop and
  single-cell-concentration checks rather than needing a new stage.
- **Unblocking `compose`'s cell-selection step for a country with no VIDA file.** The "populated
  cells" filter currently reads VIDA building points; a country that fails
  `scripts/new_region.py`'s `check_vida` gate has no path through that step today. A
  VIIRS-derived built-up mask is a strictly worse proxy for "has roofs" than building points, but
  it is better than no proxy at all -- it would only need to unblock imagery composition, not
  per-building scoring, which would still need VIDA or an equivalent footprint source before
  roofclf or sub400-capacity could run.
- **A staleness cross-check for the growth work.** VIIRS's monthly cadence is the one input in
  this pipeline that is not a single snapshot. Comparing VIIRS radiance change against
  `growth.py`'s persistence-gated delta (item 14 above), even coarsely, is an independent check
  on the direction of the 2022-2026 boom that costs nothing to compute against data already
  downloaded for the external-comparison script.

**Concrete next step:** test the VIDA-density-vs-nightlights ratio specifically as a
`check-density`-style plausibility flag (the first bullet above), since that is the one
candidate role where VIIRS's coarseness is not disqualifying and it is the one bullet above
still untried. Item 4's post-stratification use should stay lower priority given the
partial-correlation result, unless nightlight *variability* over time, rather than the mean
level, turns out to behave differently from building density -- untested either way.

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
