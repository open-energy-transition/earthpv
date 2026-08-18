# Small ground-mounted PV has no instrument: measured, 2026-08-16

!!! note "PARTLY ADDRESSED (2026-08-16): the accounting fix shipped, the instrument did not"

    Option 2 below ("widen `roofclf`'s label rather than add a detector") was implemented
    the same day, on the owner's instruction, ahead of the cropland quadrats this page
    recommends first. `earthpv roof-classifier --parcel-label` now counts mapped PV within
    20 m of a footprint, attributed to its nearest building, below the 400 m<sup>2</sup>
    segmentation floor. Option 3 still stands: no standalone detector was built, and the
    AND-gate measured below was not shipped.

    Two results from implementing it, both of which change how the fix should be read:

    - **Most of what the parcel label adds is not ground-mount.** Across the 27 quadrats
      it adds 146,766 m<sup>2</sup>, of which 29,764 m<sup>2</sup> (20%) is OSM
      `placement=ground` and 117,003 m<sup>2</sup> (80%) is mapped ROOFTOP PV whose polygon
      extends past an imagery-derived VIDA footprint. The second is a real undercount in
      the roof-only label, and correcting it is self-consistent (the same undersizing
      shrinks the calibration denominator and the national flagged roof area), but it is
      not the gap this page is about.
    - **The yard feature block still does not earn its place, even against the widened
      label.** Median fold AUC 0.8712 with it against 0.8734 without. It ships off.

    Scored nationally, validated and published 2026-08-17, the widening moves Best estimate
    18,218.4 to 19,745.9 MWp. That increase should not be read as a ground-mount figure: of
    the PV area the parcel label now prices on flagged buildings, 1.03% is ground-tagged and
    4.84% is rooftop overhang, and roughly two thirds of the sub-400 m<sup>2</sup> move comes
    from the larger flagged population rather than from the widened area term at all. **The
    small ground-mount gap this page is about is therefore still open**: the published atlas
    now counts yard arrays it can see beside a flagged building, and still has no instrument
    for a field-sited array with no building to attach to.

    The capacity range below (0.4 to 3.5 GWp) is unchanged by any of this and still rests
    on four settlement-drawn quadrats over 16 km<sup>2</sup>. Cropland quadrats remain the
    binding input.

!!! note "OPEN, now with measurements (as of 2026-08-16)"

    The 2026-08-13 version of this page established the gap on structural grounds and sized
    it against two external estimates, but explicitly measured nothing ("No code was
    written, no data was pulled beyond what's already in this project's own quadrat
    labels"). This version measures it. Nothing has been shipped and no atlas number has
    moved; the point of the exercise was to decide whether an instrument is buildable and
    what it would be worth, and three of the four items in the old "what a fix would need"
    sketch turn out to be answered already by data on disk. The reproduction script is
    `scripts/small_ground_mount_assessment.py`.

    **One-line verdict:** the candidate universe problem is solved (the VIDA building index
    already brackets the population), the detection problem is not (under 1% precision at 30%
    recall, and 2% for a yard-SPPI/roofclf AND-gate, added 2026-08-16), and the size of the
    prize cannot be pinned down better than 0.4 to 3.5 GWp
    until somebody maps cropland quadrats, because 23% of the national building population
    sits in a density stratum currently represented by four quadrats and 16 km<sup>2</sup>.

## The external evidence (unchanged)

TransitionZero + PRIED's ["Shedding light on Pakistan's distributed solar
revolution"](https://www.transitionzero.org/shedding-light-on-pakistans-distributed-solar-revolution)
(Oct 2025) reports two independently-derived national estimates for Pakistan's distributed
solar. The one number that matters here: both converge on **roughly 5 GW of solar installed
specifically on agricultural land**, mostly tube-well irrigation pumps. TransitionZero's
satellite-based estimate says 5.64 GW ground-mounted nationally; PRIED's nationally
representative household survey (5,320 respondents, stratified random) says 5.04 GW for the
agriculture sector. This project's published atlas reports **2.2 GW of ground-mount in
total**, every size and type combined, and **zero below 400 m<sup>2</sup>**.

## What counts as a small ground-mount array, and why the definition is load-bearing

Two independent tests disagree with each other on roughly half the population, so every
number below requires **both**: OSM `placement == "ground"` **and** less than 30% of the
polygon overlapping a VIDA footprint.

| | geometry says ground | geometry says rooftop |
|---|---|---|
| **OSM tag says ground** | 300 | 443 |
| **OSM tag says rooftop** | 592 | 14,968 |

Requiring both is the conservative read: it discards 1,035 ambiguous installations and keeps
300, of which **262 are under 400 m<sup>2</sup>**, totalling 23,369 m<sup>2</sup> across the
27 quadrats. Median 64 m<sup>2</sup>, quartiles 38 and 153. This is 17x more labelled
examples than the five-quadrat hand count of 15 that the previous version of this page
worked from.

## The capacity constant is module, not land, and it is a 3.6x error

The old sketch's item 4 guessed that a small-ground-mount instrument would "likely inherit"
`DEFAULT_KWP_PER_M2_LAND`. It must not. Split by OSM `kind`:

| kind | placement | count | median area |
|---|---|---|---|
| `generator` | ground | 473 | 63 m<sup>2</sup> |
| `plant` | ground | 270 | 1,031 m<sup>2</sup> |
| `generator` | rooftop | 15,560 | 45 m<sup>2</sup> |

`DEFAULT_KWP_PER_M2_LAND = 0.05` was calibrated on `power=plant` **site perimeters** (QASP,
Sukkur), where only the ground-cover ratio is module. A small ground array is a
`power=generator` way traced around the panel table itself, so it is module area and
converts at `DEFAULT_KWP_PER_M2_MODULE = 0.18`. The sanity check agrees: the median 64
m<sup>2</sup> strict array reads 11.5 kWp at the module constant, squarely inside the 5 to 15 kWp a
solar tube-well pump actually draws, and an implausible 3.2 kWp at the land constant.

## The candidate universe is already built: these arrays sit next to buildings

The old sketch's item 1 asked for "a footprint source that isn't VIDA buildings" (cropland
parcels, or a sliding tile classifier). That is not needed. Distance from each installation
to the nearest VIDA footprint:

| within | quadrat installations (n=262) | quadrat PV area | national OSM (n=201) | random point, same cells |
|---|---|---|---|---|
| 5 m | 86.6% | 85.9% | 80.6% | 21.3% |
| 10 m | 93.9% | 93.8% | 91.0% | 26.7% |
| 30 m | 98.5% | 97.7% | 98.5% | 39.9% |
| 100 m | 100.0% | 100.0% | 99.0% | 64.5% |

The national column is the important one, because it is independent of where the quadrats
happen to be drawn: every OSM ground-tagged generator under 400 m<sup>2</sup> in Pakistan,
across 43 cells, against 200 random points per cell as a null. The anchor holds at 2.5x lift
at 30 m and 3.4x at 10 m.

And it is cheap. Sampling 48 national cells stratified over all eight building-density
octiles, the share of land within 30 m of a VIDA building is **9.6% nationally** (1.4% in the
sparsest octile, 22.8% in the densest), so a building-anchored search scans a tenth of the
country and keeps 98.5% of the population. That is the whole of the old item 1 and item 2,
answered with the index `roofclf` already scores nationally.

Item 3 ("more ground-mount negatives than the 15 positives") is answered the same way: in a
Rule-1-complete quadrat every building's yard is a verified negative, so the 27 quadrats
yield **118,756 labelled parcels carrying 253 positives** with no new mapping at all (253
rather than 262 because a few arrays share a host building and a few sit beyond the 20 m
yard depth).

## Can the three existing instruments see them?

### Per pixel, against a matched control: yes, and SPPI leads

For each installation, the composite pixel it falls in, against 60 control pixels drawn from
the same quadrat and matched on **both** distance to the nearest building and the fraction of
the pixel covered by a footprint. The matching matters: without it, positives sit beside
bright roofs that no control could contain, NDBI scores 0.856 AUC on that confound alone, and
every figure is inflated by about 0.06.

Within-quadrat AUC, 300 positives against 17,991 matched controls:

| feature | all | < 50 m<sup>2</sup> | 50 to 150 | 150 to 400 |
|---|---|---|---|---|
| SPPI | **0.833** | 0.763 | 0.832 | 0.933 |
| NDBI | 0.779 | 0.743 | 0.756 | 0.841 |
| fraction head | 0.660 | 0.606 | 0.625 | 0.765 |
| segmentation | 0.534 | 0.498 | 0.499 | 0.567 |
| all features, LOQO logistic | 0.851 | 0.792 | 0.847 | 0.965 |

Segmentation is at chance, as expected: everything under `chips.MIN_PV_AREA` is burned as
`ignore`. The fraction head is the instrument with the right *shape* for this problem
(sub-pixel, footprint-free, and `chips._burn_fraction` does burn ground placements below 400
m<sup>2</sup>), and it is nonetheless the weaker of the two spectral options. SPPI, which
needs no training at all, is the best single feature here.

### At the deployable unit, with the real base rate: no

The pixel table's 60:1 matched design flatters every instrument. The unit an instrument would
actually score is a building, and the base rate is 253 in 118,756. Features are the roof block
(what `roofclf` reads today), a yard block (zonal statistics over the surrounding land out to
20 m, partitioned by a distance-transform Voronoi so no pixel is credited to two buildings),
or both. Leave-one-quadrat-out, on all 27 quadrats:

| features | AUC | P@R30 | P@R50 |
|---|---|---|---|
| roof only (= `roofclf` today) | 0.670 | 0.004 | 0.004 |
| yard only | 0.672 | 0.006 | 0.005 |
| roof + yard | 0.713 | 0.007 | 0.005 |
| roof + yard + probability rasters | 0.722 | 0.008 | 0.005 |

and on the 99,804 buildings carrying no rooftop PV of their own, where the yard array is the
only PV present and so the only thing a score can be responding to:

| features | AUC | P@R30 | P@R50 |
|---|---|---|---|
| roof only | 0.678 | 0.001 | 0.001 |
| yard only | 0.718 | 0.005 | 0.002 |
| roof + yard | **0.747** | 0.004 | 0.002 |

and, separately, on the six quadrats under 600 bldg/km<sup>2</sup>, which is the stratum
holding 77% of the national building population and the closest thing here to the
agricultural case:

| features | AUC | P@R30 | positives |
|---|---|---|---|
| roof only | 0.578 | 0.005 | 14 |
| yard only | 0.622 | 0.003 | 14 |
| roof + yard | 0.617 | 0.005 | 14 |

Fourteen positives in 4,987 buildings is too thin to call, which is itself the point: the
stratum that matters most is the one with almost no ground truth in it.

**Precision at 30% recall is 0.4 to 0.8%.** For comparison `roofclf`'s rooftop deployment
threshold is set at a precision target of 0.5. A leads product at under 1% precision hands a
mapper more than a hundred wrong parcels per right one, and an aggregate capacity component at
that precision is a correction factor with a measurement attached rather than the other way
round.

The yard block is nonetheless a real signal, and specifically a signal about the yard: it
moves AUC +0.043 overall and +0.069 on the no-rooftop-PV subset (0.678 to 0.747), where roof
features alone cannot help. The two best single features are `log_yard_area` (0.697) and
`yard_sppi_max` (0.692).

### Making SPPI and roofclf agree does not rescue it either

The atlas's sub-400 m<sup>2</sup> rooftop floor is an AND-gate: a building counts only where
`roofclf` and SPPI agree. Transferring that construction here is the obvious next question, so
it was measured rather than assumed
(`small_ground_mount_assessment.py andgate`). Both scores are rank-normalised within quadrat
first, since SPPI's absolute scale spans 18x across quadrats and a national absolute cut would
be gating on quadrat brightness. The `roofclf` side is the roof-only leave-one-quadrat-out
logistic from the table above, which is generous to it: that model is fit on this label,
whereas the deployed classifier never saw it. Scoped to the 45,183 buildings that have at
least one yard pixel, which is the only population a yard gate can score and which carries a
base rate of 0.378%, 4x the all-buildings rate:

| gate | flagged | true | precision | recall | lift |
|---|---|---|---|---|---|
| roofclf p90 | 6,983 | 41 | 0.59% | 0.240 | 1.6x |
| yard-SPPI p90 | 4,534 | 56 | 1.24% | 0.327 | 3.3x |
| **AND p90** | 1,164 | 22 | 1.89% | 0.129 | 5.0x |
| OR p90 | 10,353 | 75 | 0.72% | 0.439 | 1.9x |
| AND p95 | 440 | 9 | 2.05% | 0.053 | 5.4x |
| AND p98 | 132 | 3 | 2.27% | 0.018 | 6.0x |

The AND-gate does what an AND-gate does, trading recall for a 5 to 6x lift, and it lands at
**2%** precision. Sweeping both thresholds independently for the best precision at any
operating point holding 20% recall gives 2.11%, at roofclf p61 and SPPI p94: the optimum
reaches that precision by turning the `roofclf` side effectively off, and what is left is
yard-SPPI alone.

That is the mechanism, and it is worth stating because it does not contradict the rooftop
result. The rooftop AND-gate works because `roofclf` and SPPI are two readings of the **same
surface**, so their disagreements are informative. Move the array two metres off the wall and
`roofclf` is still reading the roof while the evidence is in the yard, so the second vote is
not a second opinion, it is a weakly-correlated nuisance that mostly deletes true positives.
No threshold pair fixes that, because the problem is what the feature block is pointed at.

### The yard block does not help the rooftop task

Tested in case the change paid for itself on `roofclf`'s existing job. It does not: rooftop
AUC 0.8711 to 0.8709, and 0.8230 to 0.8209 within roof-size band. Clean negative.

## Most of this population is already standing inside roofclf's flags

This is the finding that most changes what a fix should look like.

- **168 of 253** buildings with a ground-mount array in the yard *also* carry rooftop PV, so
  the pipeline already flags them, for another reason.
- Of the remainder, `roofclf` flags **29.4%** against a 9.9% background rate, discriminating
  yard PV at 0.697 AUC (0.638 within roof-size decile) despite never having been trained on
  it. At 10 m a yard array bleeds into its neighbour's footprint statistics.
- Those flagged buildings hold **30%** of the yard PV area on buildings with no rooftop PV.

So the buildings are largely found already. What is missing is not detection but
**accounting**: `pv_area_true_m2` is the intersection of mapped PV with the roof polygon, so
an array two metres off the wall contributes zero to the coverage ratio and zero to the area
recall, on a building the classifier has already flagged. A separately-built ground-mount
detector added to the atlas would double-count a substantial share of this.

## How big is the prize? Between 0.4 and 3.5 GWp, and the range is the finding

The obvious estimator does not work. Per-building rates measured in these quadrats do not
transfer: the quadrats' own rooftop PV area is 14,846 m<sup>2</sup> per 1,000 buildings, which
extrapolated over 75.7M national buildings would be 202 GWp against the atlas's actual 7,890
MWp for the same sub-400 m<sup>2</sup> rooftop population, a 26x overstatement. That is the
documented "ranking transfers across quadrats, absolute adoption rates do not" trap
(`rate_ratio` spans 0.2 to 5x here), and it applies to ground-mount exactly as it does to
rooftop.

What does plausibly transfer is the **ratio measured inside each quadrat**: m<sup>2</sup> of
sub-400 m<sup>2</sup> ground-mount PV per m<sup>2</sup> of rooftop PV, re-weighted onto the
national building population by density stratum, the same stratification
`sub400_capacity.coverage_ratio_by_size_and_density` already uses.

| stratum (bldg/km<sup>2</sup>) | quadrats | rooftop PV | ground PV | ratio | share of national buildings |
|---|---|---|---|---|---|
| < 150 | 4 | 479 m<sup>2</sup> | 380 m<sup>2</sup> | **0.793** | 22.9% |
| 150 to 600 | 2 | 183,477 m<sup>2</sup> | 1,415 m<sup>2</sup> | 0.008 | 54.4% |
| 600 to 2,000 | 11 | 1,078,632 m<sup>2</sup> | 14,366 m<sup>2</sup> | 0.013 | 15.1% |
| >= 2,000 | 10 | 500,443 m<sup>2</sup> | 6,643 m<sup>2</sup> | 0.013 | 7.6% |

- Pooled, ignoring stratification: 1.29%, which applied to the atlas's 7,890 MWp sub-400
  rooftop component is **102 MWp**. This is the number a naive read produces and it is
  dominated by dense urban quadrats.
- Building-weighted across strata: 18.9%, or **1,492 MWp**, with a quadrat-bootstrap 90%
  interval of **435 to 3,526 MWp**.

The entire spread comes from one cell of that table. The `< 150 bldg/km2` stratum has a
ground-to-roof ratio sixty times the urban one, holds 22.9% of the national building
population, and rests on **four quadrats covering 16 km<sup>2</sup>**, all of them drawn
around villages. Pakistan's cultivated area is roughly 221,000 km<sup>2</sup>, so the
field-sited tube-well population that the external estimates actually point at is sampled at
0.007% coverage, and none of that sample is field-sited.

That is the honest position: the project's own ground truth is consistent with anything from
a rounding error to two thirds of TransitionZero and PRIED's agricultural figure, and no
amount of modelling on the current quadrat set narrows it.

## What follows

1. **Map cropland quadrats before building anything.** Four to six Rule-1 quadrats placed
   deliberately in irrigated farmland, not around settlements, is the only step that
   distinguishes a 0.4 GWp gap from a 3.5 GWp one, and it is the input every other option
   needs anyway. It also does double duty: `density.CALIBRATED_BLDG_DENSITY_KM2`'s floor
   moves only when a quadrat's own average density reads below it, and CLAUDE.md's own note
   says such a quadrat "has to be sized and placed to average in enough non-built land on
   purpose", which is exactly what a cropland quadrat is.
2. **If an instrument is built, widen `roofclf`'s label rather than add a detector.**
   *(Implemented 2026-08-16 -- see the banner at the top of this page for what it turned out
   to measure.)* Add the
   yard block to `roofclf.building_table` and let `pv_area_true_m2` count PV in the parcel
   rather than only on the roof. The candidate universe, the national scoring loop, the
   coverage ratio, the area recall, the density-domain restriction, the quadrat bootstrap and
   the dedup against OSM and segmentation are then all inherited unchanged, and there is still
   exactly one row per building, so the double-counting problem never arises. The yard
   partition is a pure raster operation per cell, so the national cost is small.
3. **Do not build a standalone small-ground-mount detector.** At 1 to 2% precision it cannot
   support a leads product, and as a capacity component it would be measured almost entirely
   outside where it is applied, which is the precise property that got the out-of-domain
   AND-gate dropped from the atlas on 2026-08-15.
4. **SPPI is the feature to carry over, not the fraction head.** It is zero-training, it is
   the strongest single spectral discriminator here (0.833 per pixel, 0.692 as
   `yard_sppi_max` per building), and it already has a role in the pipeline as the
   disagreeing second opinion.

## Not done here

No model was trained, no checkpoint was produced, no atlas number moved, and no capacity
component was added. The ratio estimates above are not published anywhere and should not be
quoted as an earthpv figure until the cropland quadrats exist. The anchor result is measured
on settlement-sited arrays plus OSM's own national sample, and OSM mapping is itself
settlement-biased, so whether a field-sited tube-well array is equally close to a building is
plausible but untested.
