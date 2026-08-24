# Calibration quadrats: overview

This is the single current-state table for every ground-truth calibration quadrat --
what `roofclf` (`earthpv roof-classifier`) trains and evaluates on, and the only source
of real recall/precision evidence below the segmentation model's 400 m<sup>2</sup> floor.
The narrative history of how each quadrat was mapped, re-pulled, and corrected over time
lives in [Calibration boxes](../issues/pakistan-calibration-boxes.md); this page is the
answer to "what do we have *right now*," regenerated from the label files directly
rather than hand-maintained prose.

## Why two different things are both called "calibration" here

- **This page** -- hand-verified (or partially-verified) small areas where PV is mapped
  from OpenStreetMap/Overpass, used to measure the sub-400 m<sup>2</sup> detection gap and
  train/evaluate `roofclf`. See
  [the mapping protocol](../calibration-mapping-protocol.md) for how a quadrat is built.
- [Candidate-precision calibration](calibration.md) -- a *different* mechanism
  (`configs/calibration/<aoi>_candidate_precision.yaml`) that scores whether an
  already-detected candidate is real, at country scale. It reads some of these quadrats
  too (`--calibration-box`), but answers a different question.

## Where they sit

![Map of Pakistan's provinces with all 31 calibration quadrats as markers whose area scales with mapped installations, 16,469 in total. The quadrats cluster in Punjab and around the major cities, with Lahore's 5,695 installations the largest marker, deliberately rural extensions spread across Sindh and Balochistan including Nasirabad Rural with zero installations, and Kalat Rural drawn as an open circle labelled excluded from the fit.](../assets/figures/quadrat_map.png)

The map is generated straight from the label files on disk
(`scripts/detection_domain_examples.py`), so unlike the table below it always reflects
every registered quadrat -- currently 31, including Kalat Rural, which is registered and
Rule-1 but excluded from the `roofclf` fit (a &ge; 400 m<sup>2</sup> ground-mount array
clipping roofs dominates its labels; see
[Calibration boxes](../issues/pakistan-calibration-boxes.md), Box 17). The geography is
the honest part: coverage is purposive and city-leaning, which is exactly why the
[random-cell validation](roofclf-national-validation.md) and the density-domain
restriction exist.

## Current quadrats

**Seventeen quadrats**, all regenerated together on 2026-08-05 by
`scripts/build_calibration_quadrats_csv.py` -> `results/calibration_quadrats.csv`. Geometry
and mapped-PV columns come from `data/labels/*_calib_*_boundary.geojson` + each quadrat's
newest `_overpass_solar` pull (`_newest_solar`'s dated-file-wins rule); the building columns
come from a named `roofclf` run's `folds.csv`, since they need the VIDA join
`roofclf.building_table` performs. Until that script existed this table was hand-maintained
despite the paragraph above claiming otherwise, which is how a row survives a boundary
change; it now refuses to carry a building count across a stem rename, and leaves
`stratum`/`rule1_complete` blank rather than guessing (Rule-1 means a mapper's declaration
and must never be inferred). Sorted by `base_rate` (ascending) -- see below for what that
column means.

That session was a large one: **six boundaries were replaced by hand-drawn extensions, one
quadrat was withdrawn, and five new quadrats were added** (Sukkur plus four Islamabad
diamonds, bolded above). Every replacement fully contains its predecessor and lost **zero**
mapped installations, which is checkable rather than asserted -- see
`scripts/verify_quadrat_pulls.py` and
[Calibration boxes](../issues/pakistan-calibration-boxes.md). Ground truth roughly
quadrupled: 83,748 buildings and 13,243 with PV, against 22,044 / 2,376 at nine quadrats.

**Lahore was replaced on 2026-08-05**, not merely re-counted: its 1 km² square gave way to
a hand-drawn 6.61 km² boundary (`lahore_calib_6p61km2`) that fully contains it, the first
non-square quadrat in the set. The old boundary and its pulls are kept at
`data/labels/retired/`. Nothing was lost in the swap -- all 1,014 installations the old box
held are present in the new pull -- and the added 5.61 km² is mapped at a comparable
standard (831 installations/km² against the old core's 1,034), so this is a genuine
extension rather than a dilution with unmapped ground. Its row below is therefore new
ground truth, while every **model** score for Lahore elsewhere on this site (LOQO folds,
fraction-head `scale`/AUC, the density-vs-detection correlations) was measured on the
retired 1 km² boundary and has not been recomputed -- see the warning below.

**Sundar was replaced the same day** on the same pattern: 1 km² square to a hand-drawn
4.34 km² boundary (`sundar_calib_4p34km2`) that fully contains it, again with 0 of the old
box's installations lost. Its extension reads differently from Lahore's, though, and the
difference is worth not smoothing over: the added 3.34 km² holds **25 installations/km²
against the old core's 49**, i.e. about half the density. For an industrial estate that is
what you would expect from extending past the estate boundary into its surroundings, but
"genuinely less PV out there" and "less completely mapped out there" are not
distinguishable without a completeness pass, and Sundar has never had one. Treat its base
rate as describing a mixed area rather than the estate.

**Multan was replaced the same day too**, after all seventeen boundaries had already been
declared Rule-1 (below): 1 km² square to a hand-drawn 3.92 km² boundary
(`multan_calib_3p92km2`) that fully contains it, 0 of the old box's 40 installations lost.
Same pattern as Sundar -- the added 2.92 km² holds **34 installations/km² against the old
core's 64**, about half the density, consistent with extending past the industrial estate
into its surroundings rather than a mapping gap, but not distinguishable from one without a
sweep. **Rule-1 does not carry forward to new ground automatically**: the blanket
declaration was for the boundaries that existed when it was made, so it was initially
withheld here pending the owner looking at the extended area specifically -- then
explicitly re-declared for it the same day, so this quadrat reads `yes` like the other
sixteen. The rule for the *next* extension is the same: re-assert, never infer.

**Known gap: this table was not regenerated when Hasal, Islamabad Northeast, Sanghar,
Bahawalnagar Rural, Nasirabad Rural, Tank Rural, Kalat Rural, or the three peri-urban
screens added 2026-08-19 (Attock, Layyah, Lodhran) were added, so it undercounts the current
31-quadrat set by fourteen.** `results/calibration_quadrats.csv` is
current; this page is a hand-maintained snapshot of it and has fallen behind more than
once before (see CLAUDE.md's per-quadrat history for the full account). The four rows
added below (Muzaffargarh Rural, Malok, Muzaffargarh Rural Wide, Khairpur Rural) are
inserted in the same base-rate-ascending order the rest of the table follows, but Hasal,
Islamabad Northeast, Sanghar (`sanghar_calib_3p98km2`, added 2026-08-12, Rule-1, Sindh --
464 installations, median 30.2 m², 99.8% below the 400 m² floor, packing 24.4 m),
Bahawalnagar Rural (`bahawalnagar_rural_calib_4p00km2`, added 2026-08-13, Rule-1,
Punjab -- 9 installations, median 26.9 m², 100% below the 400 m² floor, packing 74.8 m;
see [Calibration boxes](../issues/pakistan-calibration-boxes.md)'s Box 14), Nasirabad
Rural (`nasirabad_rural_calib_2km`, added 2026-08-13, Rule-1, Balochistan --
**0 installations**, a confirmed true-negative box, not an unswept one; see Box 15 for
why that declaration is trusted where Muzaffargarh Rural Wide's original zero was not),
Tank Rural (`tank_rural_calib_2km`, added 2026-08-13, Rule-1, Khyber Pakhtunkhwa --
10 installations, median 26.0 m², 100% below the 400 m² floor, packing 52.2 m; Box 16),
Kalat Rural (`kalat_rural_calib_3km`, added 2026-08-17, Rule-1, Balochistan --
52 installations, median 429.3 m², only 40.4% below the 400 m² floor, 45 ground / 7
rooftop, packing 47.0 m; Box 17), and the three peri-urban screens added 2026-08-19 --
Attock (`attock_periurban_calib_2km`, Punjab, 54 installations, median 18.4 m², packing
44.2 m), Lodhran (`lodhran_periurban_calib_2km`, Punjab, 36 installations, median 21.8 m²,
packing 29.6 m) and Layyah (`layyah_periurban_calib_2km`, Punjab, 17 installations, median
96.0 m², packing 296.6 m) -- are not yet reflected in the table below, none of them because
none had `n_buildings`/`n_pv_buildings`/`base_rate` when this snapshot was last hand-updated
-- do not read this table as exhaustive; `results/calibration_quadrats.csv` is current.
**Update 2026-08-20: the three peri-urban screens are now Rule-1** (the owner declared
completeness) and are folded into the current `roofclf` fit along with every other quadrat
here except `kalat_rural_calib_3km` -- see Box 18 in
[Calibration boxes](../issues/pakistan-calibration-boxes.md) for the full registration
(including three sibling candidates dropped for stale imagery before mapping) and its
2026-08-20 update for the refit itself.

**Kalat Rural must not enter a `roofclf` fit before `building_table`'s roof term gets a
placement/size guard.** It is the first quadrat whose mapped PV is dominated by ground-mount
at or above the 400 m² floor (22,064 m² of 28,412 m², against 18,919 m² of roof area in the
whole box), and while `parcel_pv_area` skips such installations, the roof term does not:
69 of the 89 buildings it would label has-PV are labelled solely because a ≥ 400 m² ground
array clips them. `roofclf.discover_quadrats` globs the label directory, so the next
`earthpv roof-classifier` run picks the box up automatically. See
[Calibration boxes](../issues/pakistan-calibration-boxes.md)'s Box 17 for the measurement.

**Correction: Muzaffargarh Rural Wide was never confirmed at a base rate of zero --
that declaration was wrong and has been corrected.** The row below originally read 0
installations / 0.0% base rate, from 8 independent Overpass queries all genuinely
returning zero at the time. What that actually established was "0 OSM-mapped
installations as of that pull," not "mapping is complete" -- a different claim only a
human sweep can make, which is exactly why Rule 1 requires one. The owner went back,
found PV the original sweep had missed, mapped it, and the corrected pull (cross-
confirmed) found **12 installations**, 9 of 1,111 buildings flagged, base rate 0.81%.
Its density (277.75 bldg/km<sup>2</sup>, unaffected by the correction since it depends on
building count, not PV) still moved `density.CALIBRATED_BLDG_DENSITY_KM2`'s floor from
553.40 to 277.75, growing the domain from 163 to 646 of Pakistan's 4,463 cells.
**Khairpur Rural**, added the same day for geographic diversity (Sindh, not Punjab),
pushed the floor down again to 141.00 bldg/km<sup>2</sup> (646 -> 1,680 cells) -- see
[Capacity](../results/capacity.md#the-headline-figure)'s "eighth change" and
subsequent correction/ninth-change entry for the full derivation.

| quadrat | province | stratum | Rule-1 | buildings | PV buildings | base rate | installations | median install m² | % sub-400 m² | packing (nn_median_m) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Khairpur Rural | Sindh | unclassified pending mapper review | **yes** | 564 | 3 | **0.5%** | 3 | 22.1 | 100.0% | 11.7 m |
| Muzaffargarh Rural Wide | Punjab | unclassified pending mapper review | **yes** | 1,111 | 9 | **0.8%** | 12 | 54.6 | 100.0% | 85.5 m |
| Muzaffargarh Rural | Punjab | unclassified pending mapper review | **yes** | 639 | 6 | **0.9%** | 7 | 89.8 | 100.0% | 292.6 m |
| Quetta | Balochistan | 5 arid / bare-land settlement | **yes** | 5,258 | 157 | **3.0%** | 73 | 103.9 | 94.5% | 44.0 m |
| Sialkot | Punjab | 2 dense older/informal urban | **yes** | 4,208 | 238 | **5.7%** | 181 | 63.9 | 98.3% | 18.8 m |
| Malok | Punjab | unclassified pending mapper review | **yes** | 5,891 | 367 | **6.2%** | 333 | 31.4 | 99.4% | 26.0 m |
| **Multan** | Punjab | 6 industrial | **yes** | 3,419 | 278 | **8.1%** | 164 | 605.5 | 37.8% | 35.2 m |
| Sundar | Punjab | 6 industrial | **yes** | 2,401 | 217 | **9.0%** | 132 | 1,047.5 | 29.5% | 47.0 m |
| Peshawar West | Khyber Pakhtunkhwa | unclassified pending mapper review | **yes** | 7,722 | 840 | **10.9%** | 415 | 170.8 | 64.3% | 27.8 m |
| Rahim Yar Khan | Punjab | unclassified pending mapper review | **yes** | 5,554 | 691 | **12.4%** | 664 | 28.0 | 98.6% | 17.3 m |
| Faisalabad | Punjab | 6 industrial | **yes** | 1,236 | 155 | **12.5%** | 84 | 665.9 | 28.6% | 45.8 m |
| SITE Karachi | Sindh | 6 industrial | **yes** | 7,110 | 894 | **12.6%** | 286 | 812.5 | 23.8% | 43.8 m |
| Mardan | Khyber Pakhtunkhwa | 1/3 planned housing, peri-urban | **yes** | 4,751 | 654 | **13.8%** | 794 | 21.7 | 100.0% | 11.2 m |
| **Sukkur** | Sindh | unclassified pending mapper review | **yes** | 6,096 | 919 | **15.1%** | 1,105 | 27.0 | 100.0% | 11.8 m |
| **Islamabad S** | Islamabad Capital Territory | unclassified pending mapper review | **yes** | 5,368 | 875 | **16.3%** | 703 | 56.6 | 98.7% | 21.2 m |
| Peshawar | Khyber Pakhtunkhwa | 2/3 dense urban (unclassified) | **yes** | 2,111 | 348 | **16.5%** | 360 | 71.5 | 99.4% | 15.7 m |
| Karachi coastal | Sindh | 1 affluent planned residential | **yes** | 4,584 | 813 | **17.7%** | 794 | 82.7 | 98.9% | 18.5 m |
| **Islamabad N** | Islamabad Capital Territory | unclassified pending mapper review | **yes** | 3,736 | 793 | **21.2%** | 708 | 92.1 | 97.5% | 22.7 m |
| **Islamabad E** | Islamabad Capital Territory | unclassified pending mapper review | **yes** | 5,270 | 1,130 | **21.4%** | 829 | 77.6 | 96.4% | 20.4 m |
| Lahore (DHA 5) | Punjab | 1 affluent planned residential | **yes** | 13,500 | 3,432 | **25.4%** | 5,688 | 29.0 | 99.0% | 6.8 m |
| **Islamabad W** | Islamabad Capital Territory | unclassified pending mapper review | **yes** | 3,815 | 999 | **26.2%** | 992 | 75.8 | 99.0% | 18.0 m |

**Rule-1 = yes** means a human mapper declared every visible panel inside the boundary
mapped, verified against high-res imagery, per
[the protocol's completeness rule](../calibration-mapping-protocol.md#completeness-declaration-and-qa).
Only a Rule-1 quadrat's *negatives* (a building with no mapped PV) are trustworthy -- without
the declaration, "not mapped" can mean "genuinely no PV" or "nobody has mapped it yet," and
the two are indistinguishable. **Every quadrat above now carries it** (2026-08-05), so the
column no longer discriminates between rows; it is kept because the distinction still governs
what the negatives mean, and because a future quadrat starts out without it.

**An eighteenth quadrat, `islamabad_northeast_calib_3p34km2`, was added 2026-08-06** from
a hand-drawn boundary (`data/labels/calibration_boundaries/5-quad.geojson`, the fifth
diamond in the same Islamabad cluster the four `islamabad_{north,east,south,west}`
quadrats above belong to) via `scripts/new_calibration_quadrat.py`. Confirmed clear
against all 17 existing quadrats (nearest is `islamabad_east` at 1.88 km). Not yet in the
table above -- that needs a `build_calibration_quadrats_csv.py` rerun against a `roofclf`
fit that includes it, which needs the VIDA building join, not just the raw OSM pull.
Measured directly from the pull in the meantime: 839 installations (99.0% sub-400 m²,
median 67.0 m², packing 18.6 m -- the same dense small-rooftop regime as the other three
Islamabad diamonds), 5,718 buildings, 1,292 with PV, **base rate 22.6%**. The owner declared
it **Rule-1 complete the same day it was created** -- recorded in
`results/calibration_quadrats.csv` (`rule1_complete: True`, since that column is a human
judgement no script may infer) -- so all **eighteen** quadrats now carry Rule-1, not
seventeen; the callout below predates this and still says seventeen.

**A nineteenth quadrat, `hasal_calib_1p00km2`, was added 2026-08-10** from a hand-drawn
boundary (`data/labels/calibration_boundaries/hasal.geojson`, ~1 km² near Bahawalpur,
Punjab) via `scripts/new_calibration_quadrat.py`. Confirmed clear against all 18
existing quadrats (nearest is `multan_calib_3p92km2` at 121.74 km). The OSM pull itself
succeeded on the first attempt (328 installations), but the script's independent
confirming cross-check against silent Overpass truncation could not complete -- all
three mirrors were down at the time -- so the pull is recorded `pull_unverified: True`
pending a re-check once Overpass recovers. Ground truth: 328 installations (99.7% below
the 400 m² floor, median 31.4 m², packing 18.5 m -- the tightly-packed
informal/residential regime). The owner declared it **Rule-1 complete the same day it
was created**, recorded in `results/calibration_quadrats.csv`.

Folded into a fresh 19-quadrat `roofclf` refit the same day: `hasal` contributes 4,378
buildings, 444 with PV (**base_rate 10.1%**), AUC **0.805**. Its `rate_ratio` is
**0.461** -- roofclf under-predicts adoption there by more than 2x, the same failure
shape as Rahim Yar Khan -- which keeps it just outside `select_calibrated_quadrats`'s
`[0.5, 2.0]` band, so it does not (yet) enter the trusted-13 set the domain-restricted
sub-400 m² capacity fit uses. It does widen the pooled 19-quadrat LOQO fit behind the
national deployment threshold, which moved 0.2405 -> **0.2441** (`median_fold_auc`
0.8824 -> 0.8757). Not yet in the table below -- see
[Calibration boxes](../issues/pakistan-calibration-boxes.md)'s Box 13 for the full
writeup.

While registering the eighteenth quadrat, a real bug surfaced in
`scripts/new_calibration_quadrat.py`: the OSM-pull retry loop's `except RuntimeError as e:`
shadowed the `e` (east bound) local from `w, s, e, n = poly.bounds` earlier in `main()`,
and Python's implicit `del e` at the end of an `except ... as e:` block (PEP 3110) left `e`
unbound on any retry past the first failed attempt --
`UnboundLocalError: cannot access local variable 'e'` rather than a clean retry. Hit for
real this time because all three Overpass mirrors failed on the first attempt (504, 502,
connection timeout) before recovering. Fixed by renaming the exception variable to `exc`.

!!! success "All seventeen quadrats are Rule-1 as of 2026-08-05"
    The repository owner declared completeness for the entire current set, which is what
    Rule-1 means here. Rule-1 coverage went from 3 of 12 to **17 of 17** in one step, and it is a
    reversal for Karachi coastal, whose Rule-1 the owner had withdrawn earlier the same day
    when its boundary was extended.

    This is a large gain in what the quadrats can support. Precision, false-positive rate and
    `base_rate` all require trustworthy negatives, and until now only three quadrats supplied
    them -- an old-city bazaar, a planned housing scheme and an arid low-adoption city, none
    of them in the dense small-rooftop regime the sub-400 m² program exists to measure. All
    seventeen now do, including the coastal, capital-territory and Sukkur regimes that had no
    Rule-1 coverage at all.

    Two caveats to carry rather than forget, because nothing in the data expresses them.
    Five of the seventeen (Sukkur and the four Islamabad diamonds) were first pulled from OSM
    the same day they were declared complete, and **no quadrat in this repo has a recorded
    independent second-mapper sweep** -- that has been true since the first one and is not
    new. So a precision figure derived from these negatives is owner-attested rather than
    independently verified, which is a real standard of evidence but not the same one.

!!! danger "Rule-1 is relative to the mapping imagery, not to Sentinel-2"
    Mapping is done against OpenStreetMap's background imagery (Esri/Bing/Maxar), and its
    capture date **does not match the Sentinel-2 composite the model reads** -- it is
    generally older. So Rule-1 certifies "every panel visible in *that* imagery is mapped".
    It cannot certify panels built afterwards, and in Pakistan's boom that gap is precisely
    where new installations live: present in the model's input, absent from the labels.
    **Rule-1 holds as of the mapping imagery, and only becomes a statement about the model's
    own epoch once imagery contemporaneous with the composite is acquired and swept.**

    The bias directions follow and are worth quoting alongside any number from these boxes:

    | quantity | effect | why |
    |---|---|---|
    | precision | **lower bound** | a correct detection of unmapped-but-real PV scores as a false positive |
    | `base_rate` | **lower bound** | a building carrying unmapped PV counts as a negative |
    | `rate_ratio` (pred/true) | **upper bound** | it divides by that understated `base_rate` |
    | recall over mapped installations | unaffected | it only ever divides by labels that exist |

    The magnitude is measurable without new mapping, by running one checkpoint over two
    imagery epochs (`scripts/fraction_stale_label_audit.py`): predicted PV now, not pre-boom,
    and unlabelled is a candidate post-mapping installation rather than an error. Measured
    2026-08-05 over 13 quadrats, it moves pooled precision 0.435 to 0.450 -- just 5.8% of
    apparent false positives. But that pooled figure is dominated by industrial quadrats with
    large false-positive pixel counts, and **per quadrat it is the dominant error term exactly
    where the sub-400 m² programme lives**: 68.4% of apparent false positives in Karachi
    coastal (precision 0.570 to 0.807), 23.7% in Quetta, 11.7% in Lahore.

    `imagery_layer` and `imagery_date` in `results/calibration_quadrats.csv` are where the
    epoch belongs. They are **empty for all seventeen quadrats**, which is why the per-quadrat
    magnitude is still unknown rather than merely unstated -- see
    [Calibration quadrat imagery dating](../issues/calibration-imagery-dating.md).

!!! success "roofclf was re-fit on all seventeen boundaries (2026-08-05)"
    `data/roofclf_20260805_newquadrats/` is the current fit: 17 quadrats, 83,748 buildings,
    13,243 with PV. Median leave-one-quadrat-out AUC **0.888** (0.877 at the previous
    7-quadrat fit), **0.838** within size band, worst fold Mardan at 0.758 -- still the
    weakest, as it has been since it was added. The precision-targeted deployment threshold
    moved to **0.2407**. Two numbers in that run are worth reading on their own:
    the segmentation baseline scores **exactly 0.500** both unconditionally and within size
    band, i.e. chance, and the fraction head scores **0.692** per building -- so below the
    400 m² floor roofclf is doing essentially all of the discriminating work, and any
    sub-400 m² estimate built on the segmentation raster is built on nothing.

!!! warning "The fraction-head and correlation tables are still stale"
    Re-fitting roofclf did **not** refresh everything the boundary changes invalidated. Still
    measured against retired boundaries, and deliberately left at their last self-consistent
    state rather than half-refreshed: the fraction head's per-quadrat `scale`/AUC in
    `results/fraction_quadrat_validation*.csv`, and the density-vs-detection table in
    `results/quadrat_detection_correlations.csv`.
    `scripts/quadrat_correlations.py` now prints which quadrats each model-side join failed
    to cover and when that table was written, because the failure is otherwise invisible: a
    label-keyed join pairs new ground truth with old scores at unchanged `n`, and a
    stem-keyed join silently drops the quadrat. Re-running `earthpv roof-classifier` and
    the quadrat evaluation scripts is what clears this.

!!! note "Peshawar East was removed 2026-08-05, which resolves the overlap it caused"
    Peshawar East is no longer a quadrat: it was withdrawn as wrong and its files retired
    to `data/labels/retired/`. It sat ~995 m from Peshawar and shared 6.56% of its area as
    one corner, and that corner was disproportionately PV-dense -- **42 of its 131
    installations (32.1%) sat inside it** -- so pooling the pair into `roofclf`
    training/LOQO either double-counted those installations and their host buildings or
    broke the leave-one-quadrat-out fold-independence assumption, and
    `roofclf.building_table` still has no overlap-aware filtering. Its 3.7% base rate
    against Peshawar's 16.5% at that distance was never reconciled either. Removal is what
    fixed this; no deduplication code was written, so **the overlap check in
    `scripts/new_calibration_quadrat.py` remains the only thing standing between the
    project and a repeat** -- do not pass `--allow-overlap` without a plan for the shared
    ground. The wider point the pair illustrated still holds and is made by the table
    above on its own: `base_rate` cannot be pooled across quadrats, adjacent or not.

## What "PV density" means here, precisely

Two different numbers on this page are both reasonably called "PV density," and they
answer different questions:

- **`base_rate`** (the column this table is sorted by) -- the fraction of *buildings*
  inside the quadrat that carry PV (`pv_area / roof_area >= 5%`). This is the number
  `roofclf`'s calibration work (see [Capacity density](density.md#national-deployment-a-scaling-success-with-one-clean-calibration-lesson))
  found does **not** transfer at a flat rate across quadrats -- Quetta (3.0%) and Lahore
  (25.4%) are an 8x spread, and a classifier's raw predicted rate does not reliably tell
  you which regime a new area is in. (Lahore's own base rate moved 30.1% -> 25.4% when its
  boundary was extended on 2026-08-05, which is the point restated: the number is a
  property of a specific boundary, not of "Lahore".)
- **installation count / median size / % sub-400 m²** -- describes the *shape* of the PV
  population, independent of how many buildings there are. Peshawar and Mardan both have
  >99% of installations below the detection floor with small median sizes (71.5 m² and
  21.7 m²) -- a genuinely different population from the industrial quadrats' few-but-large
  arrays (SITE Karachi: 70 installations, median 1,059.9 m²).

Neither number is "the" PV density of Pakistan -- each quadrat is a hand-picked landscape
sample (see the [protocol's stratum table](../calibration-mapping-protocol.md#the-quadrat-plan)),
not a random one, and this page's own base-rate spread is the clearest evidence that
pooling them into one national rate would be wrong. See
[Capacity density](density.md#sub-400-m2-experimental-capacity-density-stratified-deliberately-separate)
for how (and how cautiously) this evidence feeds a capacity number.

## Packing distance, at a glance

`nn_median_m` (median distance from a sub-400 m² installation to its nearest neighbour of
any size, `roofclf.packing_density`) used to split the eleven quadrats into two clusters
with **nothing in between**. The two quadrats added 2026-08-04 land in that gap, so the
gap was an artifact of which eleven boxes had been chosen, not a property of Pakistani
settlement:

- **Tightly packed (7–19 m, informal/residential):** Lahore (6.8 m since its 2026-08-05
  extension, previously 7.2 m), Mardan, Peshawar, Karachi coastal, Sialkot.
- **Intermediate (20–34 m):** Rahim Yar Khan (20.3 m), Peshawar West (34.0 m) -- both
  added after the original split was described, both sitting in what was an empty band.
- **Sparse (44–52 m, industrial):** Quetta, Faisalabad, SITE Karachi, Multan, Sundar.
- **A new extreme, 2026-08-11:** Muzaffargarh Rural measures **292.6 m** -- roughly 6x
  sparser than anything above, from a genuinely low-density rural population rather than
  an industrial estate. Malok (26.0 m) and Khairpur Rural (11.7 m) sit inside the
  existing tightly-packed/intermediate bands despite both being deliberately low
  *building*-density quadrats -- packing distance tracks installation clustering, not
  settlement density, so the two need not move together (Khairpur's 3 installations are
  a tight cluster of ground-mount arrays, not spread across the box). Muzaffargarh Rural
  Wide (85.5 m, corrected from an initial n=0 reading) lands in a genuinely new gap
  between the intermediate and sparse bands. None of this changes the correlation story
  below, but this cluster of quadrats is the first to test the fit's own extrapolation
  into a regime this sparse.

This matters beyond bookkeeping: `packing_density` was adopted because it correlates
r=0.70–0.82 with the imagery instruments' per-quadrat scale and skill, and a *bimodal*
predictor invites treating the two modes as two regimes to calibrate separately. A filled
gap means the underlying variable is continuous, so the correlation -- not the
cluster label -- is the part to rely on. And that correlation is mostly **installation
size** rather than spacing as such: see
[Density and detection quality](density.md#density-and-detection-quality-what-actually-correlates-with-what)
for the partial correlations that separate the two, and for why `base_rate`'s even
stronger relationship with predicted-versus-true *rate* is arithmetic rather than
landscape.

Quetta is the one landscape-vs-packing mismatch: an arid *settlement* (not an industrial
estate) that nonetheless packs sparsely -- a reminder that packing distance is a proxy for
building layout, not a direct stand-in for the stratum table.

## Adding a new quadrat

1. Run **`scripts/new_calibration_quadrat.py`**, which does steps 1 and 2 together.
   Either give it a center and a side length, and it builds the box geodesically
   (`pyproj.Geod.fwd`, never drawn by eye):

    ```bash
    python scripts/new_calibration_quadrat.py \
        --name peshawar_west --lat 33.9905887 --lon 71.4261494 --side-m 1500
    ```

    or hand it a boundary **drawn in JOSM** and exported as GeoJSON, which does not have
    to be square or even a single piece:

    ```bash
    python scripts/new_calibration_quadrat.py \
        --name gujranwala_east --geojson ~/drawn/gujranwala_east.geojson
    ```

    Either way it runs the overlap check *before writing anything*, pulls the Overpass
    snapshot and prints the size/placement/packing profile. `--dry-run` stops after the
    checks. A drawn boundary additionally gets a geometry report (parts, vertices, holes,
    bounding-box span and fill, whether it fits one 2.24 km training chip), is named by
    its geodesic area rather than a side length (`..._calib_1p24km2`), and carries
    `shape: drawn` plus the source path for provenance. The shape constraints that
    actually matter are in
    [the protocol](../calibration-mapping-protocol.md#drawing-the-boundary-in-josm) --
    close the way, keep the bounding box under ~2.2 km. See
    [the protocol](../calibration-mapping-protocol.md) for how to choose a *good* location
    (typical, not showcase; check this page for packing-distance/stratum gaps first).
2. **Overlap with existing quadrats is checked before anything is written**, and the
   script refuses to continue on a hit without `--allow-overlap` -- a box within ~1 km of
   an existing center will share a corner with it, which is fine for an adjacent
   neighbourhood but worth deciding on deliberately, not discovering after the fact
   (see the Peshawar pair's warning above for what discovering it late costs).
3. It is discoverable automatically (`roofclf.discover_quadrats`, globs
   `*_calib_*_boundary.geojson`) as soon as the boundary + a matching `_overpass_solar`
   file exist -- no registration step beyond that.
4. It is **not** Rule-1 until a human mapper completes and a second mapper countersigns
   the completeness pass (protocol link above). A boundary + OSM snapshot, however fresh
   or often re-pulled, is not a substitute -- see Peshawar's entry in
   [Calibration boxes](../issues/pakistan-calibration-boxes.md) for what that looks like
   in practice (three re-pulls the same day as new labels landed, still not Rule-1).
5. For the completeness pass itself, `pixi run calib-export` writes every quadrat -- boxes
   plus already-mapped solar -- as one JOSM layer with a paint style, so every quadrat can
   be swept in one sitting instead of one boundary file at a time:
   [Validating every quadrat in one pass](../calibration-mapping-protocol.md#validating-every-quadrat-in-one-pass).
