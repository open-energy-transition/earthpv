# The correction that prices most of the atlas is fit outside the density range it is applied to (2026-08-16)

!!! success "LARGELY CLOSED as of 2026-08-17 -- re-verified 2026-08-20, see update below"

    No number below has been changed and nothing has been withdrawn -- they are kept as
    measured on 2026-08-16 for reproducibility (`scripts/trust_gate_density_audit.py`
    recomputes them exactly from the saved per-building tables of that date). **But the
    reach this page is about has since shrunk dramatically**, not because of any fix aimed
    at it, as a side effect of `bahawalnagar_rural` (124 bldg/km<sup>2</sup>) crossing into
    the trust gate's `rate_ratio` band sometime between 2026-08-16 and the 2026-08-17
    parcel-label refit. Re-running the audit script against both the 27-quadrat
    (2026-08-17, pre-Box 18) and the current 30-quadrat (2026-08-20, Box 18) fits gives:

    | | 2026-08-16 (as measured below) | 2026-08-17 (27 quadrats) | 2026-08-20 (30 quadrats, current) |
    |---|---:|---:|---:|
    | sparsest quadrat in the fit | 872 bldg/km<sup>2</sup> (Multan) | 124 bldg/km<sup>2</sup> (Bahawalnagar Rural) | 124 bldg/km<sup>2</sup> (unchanged) |
    | in-domain buildings sparser than every fit quadrat | 84.1% | 13.5% | 13.5% (unchanged) |
    | roofclf half priced out of calibration range | 54.3% | 5.5% | 5.3% |
    | as a share of published Best estimate | 54% | 5% | 5% |

    **The short version, updated:** the multiplier is still fit on urban/semi-urban land and
    applied to sparser cells nationally, and the trust gate still selects on density as a
    side effect of selecting on precision (Spearman(density, rate_ratio) is -0.36 on the
    current 30-quadrat fit, versus -0.58 as measured 2026-08-16) -- so the *mechanism* this
    page describes is real and unfixed. But the practical *reach* of that mechanism dropped
    an order of magnitude between 2026-08-16 and 2026-08-17, apparently from
    Bahawalnagar Rural's own `rate_ratio` moving (2.19 &rarr; 1.78 &rarr; 1.70 across the
    three fits above) rather than from any deliberate widening of the gate. **The three
    Box 18 peri-urban quadrats folded in 2026-08-20 (Attock, Layyah, Lodhran) did NOT move
    this finding further** -- the sparsest passing quadrat, the out-of-range building share,
    and the out-of-range MWp share are all within measurement noise of the 2026-08-17
    figures. Whether Bahawalnagar Rural's rate_ratio crossing the gate on 2026-08-17 was
    itself examined and intentional, or a side effect of the parcel-label refit that nobody
    checked against this page, is not recorded anywhere and is worth asking the owner about.

    Figures in the body of this page below are left as originally measured on 2026-08-16 for
    reproducibility; read them as history, not as the current reach.

## What the multiplier is and how much rides on it

The roofclf half of the atlas is two components that share one formula:

```
est_kwp = roof_area_m2 * DEFAULT_KWP_PER_M2_MODULE * coverage_ratio / area_recall
```

| component | published |
|---|---|
| sub-400 m<sup>2</sup> rooftop (central) | 7,890.2 MWp |
| >= 400 m<sup>2</sup> roofclf rooftop replacement | 7,189.4 MWp |
| **total** | **15,079.6 MWp**, 83% of the 18,218.4 MWp Best estimate |

`coverage_ratio` and `area_recall` come from
`sub400_capacity.coverage_ratio_by_size_and_density` and `area_recall_by_size_and_density`,
both fit on the quadrats that `select_calibrated_quadrats` returns. So that selection is not
a side detail of the calibration; it sets the multiplier on five sixths of the published
figure.

## The trust gate selects on density, not only on precision

`select_calibrated_quadrats` keeps quadrats whose roofclf `rate_ratio` (predicted over true
adoption rate) falls in [0.5, 2.0]. Measured across the 25 quadrats that have a building
density on file:

**Spearman(density, rate_ratio) = -0.577.** roofclf over-predicts adoption in sparser
settlements, so an upper bound on `rate_ratio` removes the sparse end by construction rather
than by accident.

| density tercile | n | range (bldg/km<sup>2</sup>) | median rate_ratio | gate pass rate |
|---|---|---|---|---|
| sparse | 9 | 124 to 1,366 | 2.19 | **0.44** |
| middle | 8 | 1,428 to 2,109 | 0.97 | 1.00 |
| dense | 8 | 2,119 to 5,258 | 0.76 | 0.50 |

Five quadrats are dropped that are sparser than every survivor, and all five fail in the same
direction, above the ceiling rather than below the floor:

| quadrat | bldg/km<sup>2</sup> | base_rate | rate_ratio |
|---|---|---|---|
| bahawalnagar_rural | 124 | 0.016 | 2.19 |
| khairpur_rural | 141 | 0.005 | 4.41 |
| muzaffargarh_rural_wide | 278 | 0.008 | 3.10 |
| sundar | 553 | 0.091 | 2.24 |
| muzaffargarh_rural | 639 | 0.009 | 2.29 |

There is a case that this is backwards. The coverage ratio is *defined* as true mapped PV area
over flagged roof area, which is precisely the quantity that prices over-flagging. Excluding a
quadrat because roofclf over-predicts there removes the observation that would have measured
the over-prediction, and then applies a ratio measured where roofclf is well behaved. That is
an argument, not a finding, and it is not the reason this page exists; the reach below is.

## A second, independent blocker

`nasirabad_rural` and `tank_rural` have no `n_buildings` value in
`results/calibration_quadrats.csv`, so `quadrat_building_density_km2` cannot place them in a
density band and they can never enter the coverage-ratio fit no matter how the gate is set.
`nasirabad_rural` is the quadrat that set `density.CALIBRATED_BLDG_DENSITY_KM2`'s floor of
48.5 bldg/km<sup>2</sup>, so the quadrat that justifies including the sparsest cells in the
domain is structurally unable to contribute to the correction applied inside it. Both counts
are cheap to backfill: measured in-boundary against VIDA they are 189 and 225 buildings over
4.00 km<sup>2</sup>, giving 47.3 and 56.3 bldg/km<sup>2</sup>.

## Reach: the fit and the deployment barely overlap

The sparsest quadrat in the shipped fit is Multan at **872 bldg/km<sup>2</sup>**, itself
passing at rate_ratio 1.96 against a 2.0 ceiling. The calibrated density domain runs from
48.5, and the cells inside it look nothing like Multan:

- in-domain buildings in cells sparser than **every** quadrat in the fit:
  **60,276,228 of 71,662,822 (84.1%)**, across 2,894 of 2,957 cells
- their building-weighted density: p25 161, **median 252**, p75 374 bldg/km<sup>2</sup>,
  roughly a factor of 3.5 sparser than the sparsest calibration point

Carried through to capacity:

| component | published | priced out of calibration range |
|---|---|---|
| sub-400 m<sup>2</sup> rooftop | 7,890.2 MWp | 4,637.9 MWp (58.8%) |
| >= 400 m<sup>2</sup> roofclf rooftop | 7,189.4 MWp | 5,204.1 MWp (72.4%) |
| **roofclf half** | **15,079.6 MWp** | **9,842.0 MWp (65.3%)** |

**9,842 MWp is 54% of the published Best estimate.**

## The density stratification does not currently absorb this

`DEFAULT_N_DENSITY_STRATA = 2`, and the band edges are quantiles of the *quadrats'* own
densities, while national cells are assigned to a band by their own density. With the shipped
quadrat set the split lands at 1,822.5 bldg/km<sup>2</sup>, which puts:

- **band 0**: fit from 8 quadrats spanning 872 to 1,758 bldg/km<sup>2</sup>, applied to
  **99.6% of national cells and 92.1% of national buildings**, covering everything in the
  domain from 48.5 up to 1,737 bldg/km<sup>2</sup>
- **band 1**: fit from 8 quadrats spanning 1,887 to 4,195, applied to 19 cells and 7.9% of
  buildings

So a village cell at 50 bldg/km<sup>2</sup> and a peri-urban cell at 1,700 receive the
identical coverage ratio and the identical area recall. The stratification is real in the code
and close to degenerate at deployment, because the quadrat density distribution and the
national cell density distribution overlap only at their extreme ends.

The rural quadrats that could populate a sparse band do exist, and they are empty of signal.
At the deployment threshold they flag, in total, **nine buildings**: bahawalnagar_rural 0,
khairpur_rural 1, muzaffargarh_rural 2, muzaffargarh_rural_wide 6. The trusted set flags
18,839. Only `sundar` (553 bldg/km<sup>2</sup>, 660 flagged) carries any weight below 872, and
it is a semi-industrial estate rather than farmland.

## What the gate is worth, measured

Refitting both multipliers under a widening `ratio_hi` and recomputing both components
exactly. The `ratio_hi = 2.0` row is the shipped configuration and reproduces both published
totals to the digit, which is the check that the rest of the table means anything:

| ratio_hi | quadrats | sparsest | band split | sub-400 | >= 400 | roofclf half | vs shipped |
|---|---|---|---|---|---|---|---|
| **2.0 (shipped)** | 16 | 872 | 1,822 | 7,890.2 | 7,189.4 | **15,079.6** | 0.00% |
| 2.5 | 19 | 124 | 1,717 | 7,262.5 | 6,634.6 | 13,897.0 | -7.84% |
| 3.0 | 20 | 124 | 1,737 | 7,466.1 | 7,121.2 | 14,587.3 | -3.26% |
| 3.5 | 21 | 124 | 1,717 | 7,188.3 | 6,621.5 | 13,809.8 | -8.42% |
| 5.0 | 22 | 124 | 1,715 | 7,189.0 | 6,620.2 | 13,809.2 | -8.42% |
| no ceiling | 22 | 124 | 1,715 | 7,189.0 | 6,620.2 | 13,809.2 | -8.42% |

Two things to read off it. **The gate is worth about -1,270 MWp**, or -8.4% of the roofclf
half and -7.0% of the published Best estimate, which is 20 times the 61.7 MWp component that
was dropped from the atlas on 2026-08-15 for being unmeasured where applied. And **the
response is not monotone**: 3.0 recovers half of what 2.5 gave up, because admitting a quadrat
moves the band split and reshuffles which side of it the other quadrats fall on. A calibration
whose output jumps by 5 percentage points depending on which single quadrat crosses the
median is not stable, and with two bands and a handful of quadrats near the split it cannot be.

## What this does and does not mean

It does **not** mean the published figure is 8% too high and should be adjusted down.
Relaxing the gate admits quadrats where roofclf is measurably miscalibrated, which is what the
gate is for, and even the fully relaxed fit has almost no support at 150 to 400
bldg/km<sup>2</sup>, the building-weighted centre of the under-calibrated mass. Both settings
are poorly evidenced there; the sweep measures the sensitivity, not the correct answer.

It does mean three things that are not currently stated anywhere:

1. The density **domain** (48.5 to 5,258) is roughly 18 times wider at its sparse end than the
   **correction's** own support (872 to 4,195). CLAUDE.md already warns that the domain gate
   and the precision gate are independent and must be checked separately for each new
   quadrat. It does not say how far apart they have drifted, and the drift is the whole
   exposure.
2. The published 90% credible interval (14,346 to 21,768) does not contain this. The
   coverage-ratio bootstrap resamples calibration quadrats, and every quadrat it can resample
   sits in the wrong density band, so the interval measures sampling noise within the dense
   stratum and is silent about transfer to the sparse one.
3. By the project's own 2026-08-15 precedent, a component not measured where it is applied
   does not get published. Applied strictly here, that would mean restricting the roofclf
   domain to >= 872 bldg/km<sup>2</sup>, withdrawing 9,842 MWp of roofclf-priced capacity.
   The published total would not fall by the full amount, because `atlas.py`'s per-cell blend
   hands the >= 400 m<sup>2</sup> rooftop estimate back to segmentation's own `est_mwp_rc_roof`
   outside the domain; the sub-400 m<sup>2</sup> half (4,637.9 MWp) has no fallback at all and
   would go to zero, since the out-of-domain extrapolation was itself dropped on 2026-08-15.
   Either way the headline moves by thousands of MWp, which is the point.

## What would fix it

**Map low-density quadrats, targeting 300 to 600 bldg/km<sup>2</sup> first.** Inside the
under-calibrated population, 150 to 300 bldg/km<sup>2</sup> holds 40.8% of the buildings and
300 to 600 holds 27.5%, so those two bands are two thirds of the exposure. Start at the upper
end: flagged buildings, which is what the fit consumes, accumulate several times faster at 500
bldg/km<sup>2</sup> than at 124.

Be honest about the cost. All 27 existing quadrats together cover 80 km<sup>2</sup>, and the
existing rural boxes yield on the order of 1.5 flagged buildings per km<sup>2</sup>. Matching
the dense stratum's 18,839 flagged buildings at rural densities is not achievable by hand
mapping. It is also not necessary: a few hundred flagged buildings in band would convert this
from unmeasured to measured-with-a-wide-interval, and the existing quadrat bootstrap would
then widen the published interval honestly instead of understating it.

Three cheaper things are worth doing first, and none of them need new mapping:

- **Backfill `n_buildings` for `nasirabad_rural` and `tank_rural`** (189 and 225). It does not
  fix the gap, but it removes a silent second exclusion and lets those quadrats participate
  the moment the gate question is settled.
- **Record the fit's own density support alongside the domain** in
  `sub400_central_summary.json` and `ge400_roof_summary.json`, and warn when the domain
  extends past it, the same way `density.py` already warns about a calibration table with no
  `placement_bins`.
- **Decide the gate question explicitly**, with the sweep above as the evidence, rather than
  leaving [0.5, 2.0] as an unexamined default whose density confounding is now measured.

This is the concrete, quantified instance of the standing caveat in
[Open questions](../open-questions.md) that the quadrats are purposive rather than a
probability sample. The general form of that caveat cannot be closed without a national
sampling frame; this specific form can be narrowed a long way by mapping in one identified
density band.
