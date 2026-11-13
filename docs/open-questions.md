# Open questions

What is genuinely unresolved, as of 2026-11-10. This page exists so that the honest gaps are
findable in one place rather than buried in the write-up of whichever experiment first ran
into them.

It is deliberately separate from [Experiments](experiments.md), which records what was
measured and settled. Something belongs here only if a concrete next step exists and has not
been taken. When an item is closed it moves to the experiments register with a verdict, and
its row here is deleted rather than annotated. Elsewhere in the repository, cite an item by
its title as well as its number: the numbers change whenever the list is re-ranked.

Items 1 to 3 each move Pakistan's published Best estimate, and each waits on mapping, a
decision or a review by the owner rather than on code.

## Ranked by expected value over cost

### 1. Probability-weighted roofclf capacity is published but untested where it adds most (2026-10-25)

**What changed.** Since 2026-10-25 `sub400-capacity` and `ge400-roof-capacity` count every
in-domain building in proportion to its `p_roofclf`, with the coverage ratio and area recall
refit on the same weights, instead of counting roofs above the 0.2446 threshold in full and
the rest not at all (owner decision; `--weighting threshold` restores the old count). Held
out one quadrat at a time it cut the median error on true sub-400 m&sup2; PV area from 0.386
to 0.094 (20 of 29 quadrats, Wilcoxon p = 0.0035), and thresholding booked 12% of mapped PV
in the six quadrats below 300 bldg/km&sup2;. Pakistan's Best moved 24,438.3 to 34,588.8 MWp
(90% 29,308-41,736); Verified is unchanged at 6,994.1 MWp. The measurement and the decision
are in the experiments register, "The capacity chain is a quantification problem", and
[roofclf](methods/roofclf.md#count-every-roof-by-its-score).

**What is still open.** The four reasons the switch was held back are now its untested risks:

1. **The gain sits where calibration is thinnest.** 80% of the +10.2 GWp lands in cells of
   100-1,000 bldg/km&sup2;. Four trusted quadrats lie below 1,000 bldg/km&sup2;
   (Bahawalnagar Rural, Layyah, Lodhran, Multan), and the six quadrats below 300
   bldg/km&sup2; hold 3,822 m&sup2; of mapped sub-400 m&sup2; PV between them. The trust
   gate is not density-neutral either (Spearman of density against `rate_ratio` -0.36), and
   area recall is PV-area-weighted, so the "sparse" band behaves like Islamabad.
2. **National sparse cells do not look like sparse quadrats.** They flag 1.3-1.4% of roofs
   against 0.2-0.3%, because a cell's 0.1-degree average density hides villages that are
   locally dense, while a sparse quadrat really is farmland. Both pricings match quadrats to
   cells on these unlike densities.
3. **Probability weighting trusts the score's level.** A small systematic score bias on rural
   roofs adds up over millions of buildings. Thresholding is immune to that and biased low
   instead; neither failure is measured nationally. In the 19 trusted quadrats the level
   holds: out-of-fold scores sum to 0.89 of the PV-carrying roofs below 400 m&sup2; and 1.03
   at or above it.
4. **The random-cell validation is unreviewed** (item 3).

**What would settle it,** with the rule declared before measuring:

1. **Map sparse and mid-density quadrats**, imagery date checked before drawing (item 4).
   The eight `*_gap_calib_2km_candidate.geojson` boxes in `data/labels/candidate_quadrats/`
   target 50-125 bldg/km&sup2;; the 100-1,000 band, where most of the change sits, needs boxes
   too, best drawn by the sampler (item 5). Score them with the current model, no refit, and
   compare the two pricings on per-quadrat |log| error. **Revert to `--weighting threshold`**
   if thresholding is closer in a clear majority, or if probability weighting's
   truth-weighted ratio across them falls outside 0.5-2.
2. **Check the score's level directly in rural cells**: a random, score-stratified sample of a
   few hundred sub-400 m&sup2; roofs in 100-1,000 bldg/km&sup2; cells, reviewed yes/no on recent
   imagery, tests whether the sum of scores matches the count of PV roofs there. **Drawn
   2026-10-28, waiting for the review:** 300 roofs below 400 m&sup2; and 100 at or above,
   blind, imagery-gated, in `results/pakistan_roofclf_level_review/`
   (`scripts/roofclf_level_review.py`; the folder's README is the protocol). The reference
   is the coverage ratio's lower density band, whose 9 quadrats price 2,937 of the 2,957
   in-domain cells (everything below 1,717 bldg/km&sup2;, three of the nine in Islamabad):
   their out-of-fold scores sum to 1.115 per PV roof below 400 m&sup2; and 1.270 at or above.
   The 0.89 and 1.03 quoted above do not reproduce from `data/roofclf/buildings.geoparquet`,
   which gives 0.997 and 1.158 for the 19 trusted quadrats. The rule is the revert band
   above, written into the draw's `design.json` before any answer; simulated on the drawn
   sample, the review separates "the level transfers" from "off by 1.5 to 2", not finer.
   **A first mapped reading (2026-10-29): the Kasur gap box** (55 bldg/km&sup2;, Box 22), where
   the production scores sum to 0.45 per PV roof below 400 m&sup2; against the 1.115
   reference, understating PV about 2.5 times. 16 PV roofs in one box: a pointer, not the
   answer. **The first sampled box, Qilla Abdullah s6** (473 bldg/km&sup2;, 33 PV roofs), reads
   2.21, overstating about twice: the two readings disagree in sign.

The two gaps the opt-in path had are closed: the atlas's size chart counts a
probability-weighted component's rooftop objects as the sum of scores (expected PV roofs)
rather than as (cell, size bin) rows, and the parcel label's ground share is measured on the
same score weights. Pre-switch outputs:
`data/roofclf_national_with_sppi/pakistan/density_PRE_probability_20261025/` and
`results/pakistan_pv_evidence_atlas_PRE_probability_20261025.html`.

### 2. Pakistan's segmentation calibration table is stale in four known ways

`configs/calibration/pakistan_candidate_precision.yaml` was derived 2026-08-11. Four things
found since each move Best, in different directions, and none has been applied:

- **Recall was measured against same-placement candidates only (found 2026-09-02).** A big
  rooftop array overruns its VIDA footprint and the candidate that found it gets labelled
  ground, so the reference counted as missed. Measured against any candidate, rooftop recall
  moves 0.423 to 0.808 (5k-50k m&sup2;) and 0.065 to 0.952 (> 50k), ground 0.107 to 0.417
  (500-1k). Applying it **lowers** `est_mwp_rc` and Best. See
  [Two errors that were cancelling](methods/mastr-validation.md#two-errors-that-were-cancelling).
- **Ground `p_unmapped` is 0.0 in every bin.** The owner's review of 120 unmapped ground
  detections drawn by AlphaEarth change score puts their real share at 0.18-0.26 (0.46 if
  every unsure verdict is PV; `results/aef_ground_review/owner_review_summary.json`).
  Applying it **raises** Best, by very roughly 0.4-0.7 GWp at current recall.
- **The 662-candidate glint sample predates two fetch fixes (2026-10-22):** tile copies of one
  pass counted as two dates, and a cached token expiring mid-pull. It sets the rooftop
  `p_unmapped`. Its series were never cached, so checking it needs a re-pull; the pose survey
  suggests a few percent of its 61 validations could be tile copies. The scene-count
  comparison in the batching study also still predates the token fix.
- **The 100-500 m&sup2; band** has `p_real` pinned only to [0.10, 0.89]. `earthpv
  calibrate-sample` emits a stratified sample of unmapped candidates, and about twenty
  verdicts per bin would collapse the widest remaining term.

**What would close it:** one re-derivation that takes all four together, since each rewrites
the same load-bearing table. It needs the calibration boxes and the glint sample (a bare
`calibrate-candidates` run is refused by `capacity_calibration.write_table`'s downgrade
guard), and the France pull must first be moved out of the
`data/labels/*_overpass_solar.parquet` glob (see CLAUDE.md). Owner decision.

### 3. The random-cell validation has never been logged

The main workflow makes a 20-cell random JOSM review mandatory after every national roofclf
scoring, because the quadrats are curated and industrial-leaning. Four scorings have shipped
since 2026-08-17 and none has a logged verdict: the parcel-label batch (seed 20260817,
`results/pakistan_roofclf_parcel_validation/`) was reviewed by the owner but its per-cell
counts were never written down; the Box 18 refit (seed 20260820) and the area-weighted
rescoring (seed 20260920), both in `results/pakistan_roofclf_validation/`, were generated and
not reviewed. The 41-area rescoring behind the page since 2026-11-07 (seed 20261107,
`results/pakistan_roofclf_q41_validation/`) was not reviewed either.
`results/roofclf_random_validation_log.csv` holds all four batches as 80 rows, every verdict
blank. The published Best
therefore rests on an unreviewed rescoring, priced since 2026-10-25 by a weighting that leans
harder on the score's level (item 1), and item 2 would move it again on top.
Protocol: [roofclf random-cell validation](methods/roofclf-national-validation.md). The
out-of-domain batch (`results/pakistan_roofclf_validation_outdomain/`) is blocked by stale
imagery (item 4) and should not hold the others up.

**Since 2026-11-10 both checks are disk review pages** (`scripts/roofclf_review_page.py`,
`data/roofclf_review/index.html`), the format the large-lead review was judged in: the
published batch (seed 20261107) as 20 random flagged roofs per cell, which `log` writes into
the log with a precision estimate, and item 1's 400-roof level review, whose export
`roofclf_level_review.py analyze` now also reads against the published 41-area scoring (the
draw was on the 30-area one; the same buildings, scores correlated 0.998). Only the 20261107
batch needs a review: the four older batches in the log (seeds 20260817, 20260820, 20260920,
20261030) describe scorings no page uses.

### 4. Stale reference imagery: the labels' epoch, and a sparse remainder nobody can check

Rule 1 certifies completeness against the mapping imagery, not against the Sentinel-2
composite (2025-11 to 2026-03), so an array installed in between is in the model's input and
missing from the labels: measured precision and `base_rate` are lower bounds, `rate_ratio` an
upper bound, and recall is unaffected. Esri's capture dates over every quadrat were read
2026-10-22 (`scripts/quadrat_imagery_dates.py`, output in
`/home/tobi/earthpv_data/roofclf_untapped/quadrat_imagery_dates.csv`): from 2020-01-18 for
Faisalabad to 2025-11-25, with four quadrats on 2023-or-earlier imagery (Faisalabad, Multan,
Sukkur, Peshawar) and two from January 2024 (Peshawar West, Sialkot). Staleness moves
`rate_ratio` and precision in the expected direction but weakly (Spearman +0.31, p = 0.10,
vanishing once base rate is controlled for). **Faisalabad passes the precision-trust gate on
six-year-old imagery**, so it helps fit the coverage ratio. These are the dates Esri serves
today, an upper bound on what a mapper saw, and the `imagery_layer`/`imagery_date` columns of
`results/calibration_quadrats.csv` are still empty.

The same staleness blocks widening the density domain. Three low-density boxes drawn for it
came back with zero installations under very old imagery and were not registered
([Calibration boxes](issues/pakistan-calibration-boxes.md)' Box 17), and the out-of-domain
review batch cannot be reviewed. The gate on widening is imagery date, not mapping effort.

**What would close it:** write the measured dates into the quadrat table, ask Faisalabad's
mapper which imagery they used, and re-check its trust if it was older than the composite by
years. For the sparse remainder, dated high-resolution imagery: the Maxar Open Data Program
([issue #3](https://github.com/open-energy-transition/earthpv/issues/3)), or Planet/NICFI
monthly basemaps, which reach about 30 degrees north and so cover Sindh but not Punjab.
[Calibration imagery dating](issues/calibration-imagery-dating.md) has the costing.

### 5. The calibration quadrats are purposive, not a probability sample

All 31 were chosen by a researcher, so the atlas's intervals describe variability within the
kind of place that has been mapped, not a design-based margin of error, and adding more
purposive quadrats cannot change that. Since 2026-10-20 a sampler exists:
`pixi run calib-candidates -- --aoi <aoi>` cuts the density grid into eight bands of equal
building share, draws building-weighted random cells, and screens each box on its Esri
imagery date. **Run for Pakistan 2026-10-28** (seed 24490, against the published grid): eight
boxes, one per band, all on Esri imagery from 2025-02 to 2025-05, six of them in the 66-617
bldg/km&sup2; range where most of Best sits, in Dera Ghazi Khan, Sanghar, Upper Dir, Zhob,
Azad Kashmir, Qilla Abdullah, Malakand and Gujranwala
([Calibration boxes](issues/pakistan-calibration-boxes.md), Box 21). None is mapped yet.
Mapping them gives quadrats with known inclusion probabilities, and it measures item 1 in
the bands that matter. A cheaper partial route, untried: model-assisted
estimation, post-stratifying the existing quadrats on variables known everywhere (building
density, roof-size mix, region).

No external check of `coverage_ratio` below the floor exists either. France cannot supply
one, because roofclf flags 16 of its 44,314 hand-mapped-commune buildings at precision 0.5;
it would take a third country whose arrays are large against a pixel and which has both a
register and hand-mapped truth.

### 6. The module constant: France measured 0.150 kWp/m&sup2;, every country uses 0.18

[Validation against the French register](methods/france-validation.md) measured
`DEFAULT_KWP_PER_M2_MODULE` at 0.150 kWp/m&sup2; (epoch-corrected, 11 of 14 hand-mapped
communes) against the assumed 0.180. Applying it would lower every module-area rooftop
conversion by 17%. French residential arrays are a different regime (median 20 m&sup2;), and
the measurement does not transfer to Pakistan on its own. The decision: keep 0.18 everywhere,
adopt 0.150 for France only, or widen the module prior in `kwp_draws` to span both. Owner
decision.

### 7. Keep turning the flywheel

More human-verified Pakistani installations, retrain, measure. In-domain training chips
tripled large-array recall (0.18 to 0.55 at or above 1,000 m&sup2; in Punjab), and no
architectural change has come close. For roofclf the equivalent is item 1's quadrats.

### 9. Small ground-mounted installations have no calibrated instrument

Both sub-400 m&sup2; instruments score building footprints, and a small free-standing array
has none; segmentation burns everything below 400 m&sup2; as `ignore`. In Pakistan this is
not a small gap: solar-powered irrigation tubewells are a large, fast-growing class in Punjab
and Sindh, and TransitionZero's satellite estimate (5.64 GW ground-mounted, mostly tubewells)
and PRIED's household survey (5.04 GW agricultural) agree within 12%, against 2.2 GW for this
project's entire ground-mount total.

What is measured (2026-08-16): 98.5% of the quadrats' 262 sub-400 m&sup2; ground arrays sit
within 30 m of a VIDA building, so a ring around the building index holds the population, but
detection at that unit lands under 1% precision at 30% recall in every stratum tested. A
density-stratified estimate puts the prize at 1,492 MWp (90% 435-3,526), all of its spread in
the < 150 bldg/km&sup2; stratum, which four village-centred quadrats represent.

An instrument exists since 2026-10-23: `groundclf`, a footprint-free pixel detector
([Farm ground PV](methods/groundclf.md)). In Yemen it reaches precision 0.63 at 62% array
recall on a fully traced test ground, where Pakistan's building-ring attempt above stayed
under 1%, and it trains on ordinary OSM labels read as bags. Since 2026-10-24 it is a field
on every atlas and in Yemen's Best: 169.1 MWp, calibrated on seven farm areas in two regions
('Amran highland, Tihama lowland), each cell priced by the region it resembles. Two regions
is still thin. Tihama's ratio scales detections UP (the detector finds a quarter of its
arrays), so a false detection is multiplied too, and its areas were drawn around a hotspot.
First run on Pakistan 2026-10-29, on eight farm areas mapped that day: it does not see the
arrays (object precision 2 to 5%, next to no recall at the deployed threshold, ground arrays
median 44 to 106 m&sup2;; [Farm ground PV](methods/groundclf.md#pakistan-arrays-too-small-to-see-2026-10-29)).

**What would close it:** farm areas in other landscapes (`calib-candidates -- --farmland`:
cropland strata, imagery gate included), so that a region needs no extrapolation in
elevation or cropland, and a random-cell review of in-domain detections, which would measure
the false-detection share the ratio amplifies. For Pakistan, blobs will not do at these
sizes; the untested route is the pixel scores' sum, leave-one-area-out over the eight areas
(does an area's summed score track its mapped ground PV, as roofclf's probability pricing
does?), with `--roofclf-buildings` so yard arrays roofclf already prices are not counted
twice. See
[Small ground-mounted instrument](issues/small-ground-mount-instrument.md).

### 10. Growth as a product

Per-epoch capacity would make the 2022-2026 boom measurable per district and checkable
against NEPRA net-metering registrations and customs imports. One two-epoch
[growth map](results/growth.md) exists; an annual series does not
(`scripts/compose_loop_years.sh` built composite_2 for a few hundred cells on 2026-08-19 to
08-21 and stopped). The diff carries a persistence gate since 2026-08-20 (pre-boom winter snow
had read as vanishing PV). Open, in order of expected effect on the delta:

- **composite_1's radiometric scale differs by cell (found 2026-10-20, corrected
  2026-10-22).** The 122 cells whose composite_1 was built on 2026-07-05, 24 of the 30
  quadrats among them, sit on composite_0's DN scale (median difference about 0 DN over 40
  sampled cells). The ~4,345 built from 2026-07-15 on read about 800 DN darker, with a wide
  spread (10th percentile about 0). So the flat `transfer_calibration.PRE_BASELINE_DN_OFFSET =
  1000` the code applies to composite_1 is wrong for the early batch, and the growth
  pipeline's unharmonized read is wrong for most of the late one. Matching each band's window
  median to composite_0 per cell handles both (`scripts/composite1_offset_survey.py`). Effect
  on the published delta unmeasured; segmentation has no harmonization path at all.
- **The gate is one-directional.** Current-epoch false positives cannot be gated, so the
  residual bias on the delta is upward. A snow/SCL mask on the pre-boom composite, or a
  winter-free window, would remove the false-positive mode at the source.
- **roofclf's deltas are floors on rooftop growth.** Its 2021 score predicts today's PV at AUC
  0.832 against 0.870, so most of its ranking is propensity that predates the panels, and
  the pre-boom roofclf level reads about 79% of today's for a boom that multiplied the stock.
- **No credible interval on the delta**, and the pre-boom epoch has no calibration of its own,
  so only diffs of the fixed instrument mean anything.

### 11. Composites built before 2026-10-10 carry two compose defects

Both are fixed in `imagery.py` for every composite built from 2026-10-10 on; nothing earlier
was recomposited. **Scene ranking ignored coverage**: `eo:cloud_cover` is per MGRS tile, so
dry-season scenes tie at 0% and the twelve kept could all come from a tile clipping the cell's
corner (Rewa Ultra Mega Solar's cell was 87% empty and the 750 MW park dropped out of India's
Verified). **Whole bands were lost to failed reads**, which `odc.stac` turns into zeros. A
third, compose adding one cell per mapped feature so outlines crossing a cell edge were half
imaged, was fixed 2026-10-12. Measured on random samples, about 1% of imaged area is affected
(India 1.3% of cells with a missing band and 0.79% of area in tile-edge gaps; Zambia, Nigeria,
Vietnam and France at or below that), concentrated rather than spread. India's eight uncomposed
outline cells (six at Khavda) were composed by the `ring_cells: 3` widening (published
2026-10-28). Rewa's cells were not rebuilt, and its two outlines (16.0 and 10.5 km&sup2;)
still screen as unimaged.

**What would close it:** recomposite only the affected cells (`scripts/scan_composite_defects.py`
finds them; about two hours for all of India), re-infer and re-run the atlas chain. Mixing is
not a concern, since recipe and radiometry are unchanged.

### 12. `compose` downloads 31 times more than it keeps (2026-09-19)

Measured on Nigeria: about 410 MB downloaded per cell to write 13.4 MB, because twelve
scenes by ten bands are reduced to one median. For a country of 6,000 cells that is about
2 TB of transfer and days of wall-clock, which makes compose the binding constraint on every
new country. The fix is to composite next to the data: run the unchanged `imagery.py` on a
VM in the archive's region (`sentinel-cogs` in AWS us-west-2, Planetary Computer in Azure
West Europe), or port the recipe to openEO or Earth Engine. Porting is riskier: the recipe's
scene selection, SCL classes and radiometric offset are what the checkpoints were trained
on, and a subtly different composite reads as domain shift. **Next step:** composite a few
dozen cells of an existing AOI on a co-located VM and diff them against the local ones; if
byte-identical, route the next country that way. (The Planetary Computer Hub was retired in
June 2024, so there is no free hosted notebook.)

### 13. Glint and pose: untested refinements, and what a longer window buys (updated 2026-11-10)

**A four-year window, not the denser constellation, is the free lever (assessed
2026-11-10, no pixels read; `scripts/glint_window_projection.py` reproduces every number
from `results/glint_opportunity/`, `results/glint_validation_pakistan/` and the stored
quadrat geometry).** Counting granules in the quadrats' metadata, the first half of 2026
holds only 7 to 44% more scenes than the second half of 2024 (median about 1.2x):
Sentinel-2C took over a slot rather than adding a satellite. Doubling the window to four
years doubles expected opportunities instead. Two models project it. The pooled Poisson in
`glint_opportunity.py` reproduces the measured validated rate and overshoots two-year
detection by about 60% (0.59 modelled against 0.37 measured, count-weighted over mapped
installations of 400 m&sup2; and up), so spikes cluster on some targets and never come on
others. A bounded two-component fit (a share `f` per bin that can glint at all, Poisson
chances for those; f = 0.21, 0.25, 0.52, 0.68 for 400-500, 500-1k, 1k-5k, 5k-50k m&sup2;,
capped at 1 above 50k where a plant is several planes) reproduces both measured rates and is
the line to quote. For the 9,076 mapped Pakistani installations of 400 m&sup2; and up:

| Window | Detected, by count | Validated, by count | Detected, by capacity | Validated, by capacity |
| --- | ---: | ---: | ---: | ---: |
| 2 yr, measured | 0.37 | 0.24 | 0.60 | 0.27 |
| 4 yr, bounded | 0.43 | 0.39 | 0.74 | 0.61 |
| 4 yr, pooled (ceiling) | 0.82 | 0.53 | 0.86 | 0.59 |

Rooftops of 400 m&sup2; and up barely move by count (0.32 to 0.37), since most are 400 to
1,000 m&sup2; where only a quarter can ever glint; ground and capacity move a lot, because
capacity sits in the 5k m&sup2; and larger bins where most arrays can glint and only lack
chances. Caveats: the array must exist at a fixed pose for the whole window (Pakistan's
post-2022 stock mostly does not reach back four years; India's, Spain's, France's and
Germany's parks do); the size mix is Pakistan's OSM mapping, 68% ground by count.
**Steps:** re-pull the 500-target validation sample (`glint_validate_pakistan.py`) over
four years and check the 5k-50k m&sup2; validated rate against the bounded 0.54 and the
pooled 0.63; if it lands there, pull four years for every lead of 1,000 m&sup2; and up in
the large-lead and blob review populations through the tile-major fetch (tens of thousands
of targets, days of network), add a glint column to the review pages, and let the largest
bins' pricing use glint absence as evidence (the opportunity model already makes silence
informative above about 20 expected chances). A window-length extension is also where
glint as a *detector* ends: it stays blind below 500 m&sup2; (likelihood ratio 1), caps at
the pose ceiling above, costs about a minute of network per target, and its 2.0%
false-spike floor was measured on buildings, not on the wet pans, ponds and basins where
the open-ground false positives live (still water cannot glint here, the sun never comes
within 17&deg; of zenith at overpass, but wind-roughened water can, unmeasured).

**A longer window cannot widen the observable azimuths (measured 2026-11-10).** The
required azimuth over two years runs 84&deg; to 180&deg; across the 23 quadrats and never
crosses due south; the second year repeats the first year's western edge to within 0.6&deg;.
The sun at a 10:30 crossing is always east of the meridian, and swath-edge view geometry
rotates the bisector to 180&deg; at most (Sialkot, Multan, Sundar, the multi-orbit
quadrats). So the shaded wedge on the pose plot, south through west and north to
east-southeast, is unmeasurable from Sentinel-2 at any window length, in every country
(north-east to north in the southern hemisphere). Only an afternoon crossing would mirror
the band; no free sensor at usable resolution has one, and Landsat crosses earlier, i.e.
further east. The east-west asymmetry of the installed population therefore comes only
from uncensored sources: MaStR (below) and OpenPVMapper.

**Landsat 8 and 9 as a second glint sensor (scoped 2026-11-10, untested).** Same
near-nadir view, 8-day combined revisit, a crossing 20 to 30 minutes earlier, so the
glinting pose needs a few degrees more tilt and a more easterly azimuth: a second band
beside Sentinel-2's, not a wider one. Pixel mixing at 30 m (15 m panchromatic) puts the
floor near 5,000 m&sup2;, i.e. the large-lead and blob population only. Three things it
could give that Sentinel-2 cannot: (1) more chances at a shifted geometry for arrays of
5,000 m&sup2; and up; (2) **a direct tracker test**: a fixed plane satisfies both sensors'
specular conditions at one pose, a single-axis tracker has rolled several degrees in the
half hour between crossings, outside the 3&deg; tolerance, which would settle India's
east-facing cluster (`india2000_pose`, today the assistant's eye on imagery); (3) OLI's
12-bit range rarely saturates, so spike amplitude becomes measurable. Steps, in order and
each cheap: extend `glint_observability_ceiling.py` to Landsat sun angles (metadata only);
pull Landsat Collection 2 series (Planetary Computer `landsat-c2-l2`, QA_PIXEL in place of
SCL, annulus widened to two or three pixels) for the Pakistani installations of 5,000
m&sup2; and up that already have Sentinel-2 poses plus the 600 verified negatives behind
the 2.0% floor; report Landsat's own detection and false-spike rates per bin, the joint-fit
agreement, and on India's east-facing sample whether the two sensors disagree the way a
tracker predicts. Read raw per-scene reflectance for glint, never the BRDF-adjusted
harmonized (HLS) product.

- **MaStR's uncensored pose distribution.** The installed-pose prior in
  `glint_opportunity.py` is assumed (`DEFAULT_POSE_PRIOR`, tilt 25 &plusmn; 8, azimuth
  180 &plusmn; 25), because the pose survey only sees poses that glinted. Germany's register
  records pose at registration for 97.4% of 4.44M rooftop units (225,138 with coordinates
  too), and it is far wider than the prior (tilt > 40&deg; 23.8% against 3.0%; 348,524
  east-west units a unimodal Gaussian cannot represent). Steps: swap it into
  `expected_opportunities` and re-check the glint-date rejection that rested on the assumed
  prior; then test per target whether validation tracks predicted specular compatibility.
  It does not transfer to Pakistan's flat roofs, but it tests the machinery.
- **OpenPVMapper as a second uncensored pose source**: it carries imagery-derived tilt and
  azimuth for small French installations, exactly the ones MaStR omits, and has never been
  used. A France glint pose survey started 2026-10-22 would be the natural check.
- **Per-locality pose calibration.** A province-level re-cut of the pose survey exists;
  fitting pose from a subdivision's own installations, which would improve yield modelling,
  does not.
- **Per-pixel glint anomaly counting**, scoring each pixel against its own baseline instead of
  a cell-level percentile. Prototyped, never evaluated; a PSF matched filter, the most
  favourable per-pixel statistic, already lost to the aggregate statistic, so a shape-free
  counting statistic is the remaining untested form.

### 14. Sentinel-1 backscatter variance as a false-positive filter

Distinct from the corner-reflection hypothesis that failed: multi-temporal backscatter
variance separates permanent structures from seasonally changing fields, and greenhouse metal
frames return bright, the opposite of PV. Cheap and untested.

### 15. Nightlights as a check on VIDA coverage

VIDA is a single load-bearing input everywhere (the unit roofclf classifies, the density
stratifier, the placement join, compose's cell filter), and it is a present-day snapshot with
undersized footprints. VIIRS nightlights cannot replace it (a 500 m pixel cannot tell which
roof carries PV) and adds little as a covariate (r = 0.48 against Best once log roof area is
partialled out, 2026-10-21). The one untried role where its coarseness does not disqualify it:
**a plausibility flag for cells bright in VIIRS but implausibly sparse in VIDA**, i.e. where
VIDA is missing structures, slotted into `plausibility.py` beside the existing checks.

### 16. The 90% interval leaves out choices of method (2026-10-28)

`atlas._evidence_uncertainty` composes measured errors only (the kWp priors, segmentation's
precision/recall posterior, the quadrat bootstrap, two stated judgement factors), and its
docstring names two exclusions: purposive sampling and the Rule-1 imagery epoch. It leaves
out method choices too, and those have moved Best further than the interval is wide: the
2026-10-25 weighting switch took Best from 24,438 MWp (90% 20,894-33,666) to 34,589
(29,308-41,736), each outside the other's interval, and the same docstring records five
20-35% moves in one week of recalibration. Pakistan's atlas config now says so in a caveat
(`confidence.caveats`, shown from the next rebuild). **What would close it**, an owner
decision: publish a stated method bracket beside the interval (the threshold-weighted Best is
one `--weighting threshold` run away), or add a judgement term the way
`OUTDOMAIN_EXTRAPOLATION_CI90` does for the out-of-domain component.

### 17. A segmentation outline is 2.4 times the array it finds (measured 2026-10-28)

Measured with `scripts/candidate_area_bias.py` on Pakistan's published v3 candidates before
OSM outline substitution, against the dissolved 2026-10-25 OSM pull
(`results/pakistan_candidate_area_bias.json`): a matched rooftop candidate of 400 m&sup2; or
more covers 2.43 times the mapped panel area it found (90% 2.36-2.51, n = 1,070), 2.52 inside
the Rule-1 quadrats, where 68% of its outline lies outside every mapped panel. The ratio
rises with size: about 1.0 at 1-5k m&sup2;, 2.5 above 5k m&sup2;. Ground candidates come to
1.48 against OSM site perimeters. Nothing calibrates candidate area: `p_real` and recall count
installations.

Pakistan's published capacity barely sees it, by construction: matched candidates take their
OSM outline before `density`, and every candidate in a bin is weighted by the bin's `p_real`,
so the p_real-weighted area of candidates of 500 m&sup2; or more comes to 0.92 (rooftop) and
0.89 (ground) of the mapped outline area. The inflation reaches capacity only where a table
credits unmatched candidates as real (`p_unmapped` > 0): Pakistan's published rooftop bins
above 5k m&sup2; (0.129), and **Germany's register-derived `p_unmapped` (0.06-0.76 by bin),
where German OSM is too sparse to swap outlines**. **Next step:** keep a pre-substitution
candidate file for Germany, run the script there, and if the ratio holds, price
`p_unmapped`-credited candidates at outline area divided by the measured ratio.

**It now also reaches every lead a person judges solar (2026-11-10).** The large installation
review (`pixi run large-review`, leads from 10,000 m&sup2; up to the cap) prices a judged
lead by its verdict. **Owner decision, 2026-11-10:** a roof lead judged solar counts 1/2.5 of
its outline (`capacity_calibration.LEAD_ROOF_OUTLINE_RATIO`, recorded per review as
`rooftop_outline_ratio`), a ground lead whole, as judged parks do. The ratio is Pakistan's
(roof outlines of 5k-50k m&sup2; 2.52 times the mapped array, above 50k 2.54); the owner's
first verdicts make it matter: 1,381 leads judged solar over seven countries, 92-99% of the
large roof leads in Belgium, the Netherlands, Portugal and South Africa. Whole outlines would
have added about 2,989 MWp of model capacity, 1/2.5 about 1,150. **Next step:** measure the
ratio where the verdicts are, by re-tracing the model's outline of mapped large roof arrays
(the candidate files keep only the swapped-in OSM outline) or, in Germany, as registered kWp
per m&sup2; of model outline from MaStR; where mappers outline whole roofs, the OSM route
reads low. Pakistan's ground outlines of 5k-50k m&sup2; measure 2.56 times the mapped site,
so whole ground leads lean high.

### 18. Grid load as a second, physical measure of the level (scoped 2026-10-28)

Every estimate of the level so far comes from imagery calibrated on mapped areas, and the
level is what moves Best (items 1 and 16). A system operator's hourly load that leaves out
consumers' own solar dips at midday in proportion to that solar's capacity times irradiance;
regressed on weather, it gives a capacity independent of imagery, quadrats and roofclf. It
measures capacity that displaces grid supply in daylight, not installed capacity: off-grid
systems never show, batteries move the saving to the evening, load shedding removes served
demand. Outside Germany it is a lower bound with stated confounders, not a ceiling to judge
Best against (the Ember import ceiling's lesson). The same machinery, capacity per cell times
hourly yield per kWp under a pose mix, is the hourly behind-the-meter generation an energy
model needs, which nothing here produces yet.

**The series exist, and demandcast already retrieves them**
(`open-energy-transition/demandcast`, whose source files record whether each series leaves out
embedded generation, and which has reviewed a `midday_dip` as `net_demand` for Germany,
Pakistan and four Indian states):

| Country | Hourly load (demandcast module) | Truth to test against | Terms |
| --- | --- | --- | --- |
| Germany | ENTSO-E actual total load from 2015 (`entsoe`, free API token); SMARD Netzlast needs none | MaStR, local: 6.28M units with commissioning date, `Einspeisungsart`, `AnschlussAnHoechstOderHochSpannung`, tilt and azimuth | ENTSO-E load is not CC BY: analyse, publish derived numbers only |
| Pakistan | ISMO system demand FY2025 (2024-07 to 2025-06), without K-Electric (`ismo`); NTDC 2015 to 2020-04 as the pre-boom shape (`ntdc`) | none; the atlas and PRIED's 33.35 GW survey | ISMO: personal use, no redistribution |
| South Africa | Eskom RSA contracted demand from 2021-04 (`eskom`) | Eskom's own demand-reduction estimate, 7,463.6 MW in December 2025; CSIR 6.8 GW mid-2025 | Eskom: no non-private use; check before publishing |
| India | NITI ICED demand met, 28 states and 5 UTs, 2017 to 2026-03 (`niti`) | MNRE's monthly state-wise rooftop capacity (21.5 GW nationally, September 2025) | open, redistributable |

Not checked: whether ISMO has posted FY2026 (2025-07 to 2026-06), the year that overlaps
Pakistan's composites. Its library lists files only in a browser.

**Germany first, where the answer is known.** Per month, regress hourly load on hour by
day-type effects, holidays, temperature by hour, and the capacity-weighted yield per kWp from
ERA5 (atlite, MaStR's pose mix, its capacity per cell as weights). The yield coefficient is
the embedded capacity the load leaves out, identified by sunny against cloudy days at the same
hour. Germany has no PV-free baseline, and dark days add lighting and heating load in the
same direction as missing PV, so judge the trend before the level. Criteria, fixed before
running:

1. The monthly coefficient tracks MaStR's cumulative capacity, 2015 to 2025, at r >= 0.9.
   If not, stop: the method fails with the best data there is.
2. Its slope against the MaStR subset the series leaves out is 0.8 to 1.2, and it tells which
   subset that is: all distribution-connected PV, or self-consumption units only.
3. The latest year is within 20% of that subset, with month-to-month scatter under 10%, so that
   one Pakistani fiscal year can say something.

If 1 holds and 2 or 3 fail, the method measures growth, not the level: item 10, not item 1.

**Then India, then Pakistan.** India has open data, a register per state, and Pakistan's
confounders: cloudy days are cooler, which lowers cooling load the other way, and demandcast
reviews a `midday_rise` in Karnataka, Rajasthan, Punjab and Uttar Pradesh from agricultural
supply moved to daytime, so those states need it modelled or left out. Pakistan last, against
Best outside K-Electric's territory and time-matched to the series, read as a lower bound.
South Africa's atlas has no rooftop half below 400 m&sup2;, so there it measures what the page
leaves out.

**Pakistan pilot, run 2026-10-29** (owner's choice of country;
`scripts/pakistan_grid_load_pilot.py`, outputs in `results/pakistan_grid_load_pilot/`, inputs
in `data/grid_load/pakistan/`). ISMO FY2025 load, ERA5 (Open-Meteo) and NASA POWER (CERES
SYN1deg) at 185 half-degree nodes holding 99.1% of Best outside K-Electric's territory, pose
18 deg south, losses 0.85; per month, day and hour-by-day-type effects, hour-specific
temperature, rain and dew point; ERA5's yield instrumented by POWER's, because the day effect
leaves only cloud anomalies to identify on and ERA5's errors in them bias the slope toward
zero (ERA5 alone recovers 0.66 of the instrumented estimate). Results:

- **The signal is there**: the instrumented 90% interval sits above zero in all 11 months,
  and the placebo (the yield of a week later) stays within 1.5 GWp of zero in the median month.
- **Its level is far below Best**: 9.4 GWp median over 11 months (8.0 without May 2025, whose
  placebo reads 8.6 GWp), monthly 3.6 to 16.0, against 31.9 GWp of Best outside K-Electric on
  composites 6 to 18 months later. Pose and losses move it 10%.
- **It does not grow across the year**, so the month-to-month swing is behaviour, not
  capacity: winter months run low (3.6 to 6.7), plausibly because a system that cannot export
  displaces at most its owner's own midday load, which is small without cooling; November
  runs high (16.0) on Lahore's smog closures, which changed demand on exactly the dark days.

Verdict: the load measures grid-displacing daytime capacity in Pakistan, a lower bound that
sits between the ~6 GW officially net-metered and Best, and cannot check the level, because
the gap has two explanations it cannot separate (PV that never displaces grid supply, and
Best being high). What would separate them: ISMO's hourly generation file (utility solar of
known capacity through the same chain; its URL sits behind the library's token, so it has to
be copied from a browser), the FY2026 file that overlaps the composites, and the Germany and
India tests above, which have registers.

**Prerequisites:** `~/.cdsapirc` exists (ERA5); atlite is in no pixi environment; no ENTSO-E
token; the MaStR sqlite is `~/.open-MaStR/data/sqlite/open-mastr.db` (4.6 GB). The ERA5
cutouts are the long pole and belong on /home. demandcast models gross demand and marks these
series as net of embedded solar with no way to add it back: per-region behind-the-meter
generation from this pipeline is its missing term.

### 19. Egypt: retrain with the pool and wastewater hard negatives (2026-10-29)

The owner's review found many of Egypt's leads on swimming pools and on wastewater
treatment plants' rectangular basins. Against OSM, 77 of 1,165 leads are mostly a mapped
pool, but only 9 touch a mapped wastewater feature: the plants the leads sit on are largely
unmapped. `earthpv osm-hard-negatives` cut 1,120 chips (872 pools, 248 wastewater; 889
train, 56 buffer, 175 val) into `data/chips/egypt_hard_neg`
([Egypt](results/egypt.md#false-positives-swimming-pools-and-treatment-basins)).
**Next step:** retrain v12's recipe with `egypt_hard_neg` added at 1x, compare on
installation recall at matched precision (`scripts/compare_backbones.py`) over Egypt's 9
original val chips, and separately on false-positive pixels over the 175 hard-negative val
chips, which would otherwise swamp them; then on leads per class. The treatment-plant count
needs a reviewed sample of the new leads, since OSM cannot supply it. `water=lake` (23
leads, partly resort lagoons) is the next class to check.

### 20. roofclf across countries: drop `bf_confidence`, borrow from a matched donor (2026-10-29)

The leave-one-country-out test (experiments register, "One roofclf for every country?")
found `bf_confidence` empty on every Yemeni and French building, filled with 0, which
Pakistan's model turns into +0.55 logit on every foreign roof. Rankings are untouched, but
foreign levels are inflated. **Done 2026-10-30:** the feature left `MODEL_FEATURES`,
Pakistan was refitted (median fold AUC 0.8682 to 0.8680) and rescored, and Yemen was
rescored with the refit model: Yafi' and Qa'tabah town now sum to 2.35 per PV roof
against 3.6. At Yemen's 18 areas with PV its own fit beats every single donor, so the
multi-donor `--extra-table` once planned here is not needed.
**Next step:**
1. ~~Republish Pakistan on the refit model.~~ **Done 2026-11-07**, on the 41-area refit
   without `bf_confidence` instead (item 21; Best 34,470.3 MWp), not the 30-area
   `data/roofclf_nobf` chain.
2. Review the new scoring's random cells (seed 20261030, 20 cells, 5,302 flagged
   buildings, `results/pakistan_roofclf_nobf_validation/`) along with the 60 still blank
   from earlier rescorings (item 3).
3. India's Gurgaon box has 12 mostly large PV roofs. India's first household box is the
   next useful target, fitted with Pakistan's table as donor at 25% (`docs/reproduce.md`,
   Step 6).
4. Yemen's household rooftops (2026-10-31). Its own fit ranks them (AUC 0.83), but priced
   leave-one-box-out (`scripts/roofclf_yemen_pricing.py`) its scores do not beat roof area
   alone on the four town boxes (median error 0.52 against 0.16 on the set the chain would
   use; Sayun at 0.12 to 0.31 of truth; Qa'tabah s6, no PV, priced above every town).
   Ghayl Bawazir, swept and registered with no PV the same day, removes every
   precision-0.5 cut from Yemen's scores, so the chain would book zero, and roof area
   prices it at about one town's PV. Whether to build a roof-area household figure for
   Yemen's towns is an owner decision. It needs town boxes drawn at random, not for their
   PV (`calib-candidates --towns`, six drawn 2026-10-31), so that towns without solar
   are averaged in. More PV-rich
   boxes add ranking, which is not the constraint.

### 21. Which areas may set Pakistan's roofclf price (2026-11-07)

Pakistan's roofclf was refit on 41 areas, but its coverage ratio is pinned to the 19 areas
the 30-area fit chose (`sub400_capacity.PINNED_COVERAGE_QUADRATS`): under the refit the
`rate_ratio` rule drops Multan and admits Kalat Rural, Kasur and Sahiwal f6, which lifts Best
from 34,470 to 37,456 MWp and the 90% interval's top from 41,310 to 82,394
([experiments register](experiments.md#pakistans-roofclf-on-41-areas-priced-on-the-19-it-had-2026-11-07)).
Three things decide whether the pin can go:

1. **Farm-yard ground PV in the rooftop label.** The parcel label hands mapped PV below
   400 m<sup>2</sup> within 20 m of a footprint to that building. In towns that is mostly
   rooftop PV overhanging an undersized outline; in Kalat 72% of household "PV" is ground
   arrays of 100 to 400 m<sup>2</sup> (solar pumps), Sahiwal 66%, Kasur 42%, Layyah 59%
   (already in the 19), against 4.6% over the lower band's nine areas. Counting only rooftop
   and overhanging PV in the coverage ratio's numerator would settle it for every area alike.
2. **The ground guard's 0.5 footprint share.** It keeps every one of Kalat's large arrays
   out (at most 0.47 on footprints) and still drops 16 of Multan's, some of them on roofs,
   which moves Multan's `rate_ratio` from 1.88 to 2.13, just past the rule's limit.
3. **The band edge is a median.** The lower band prices 2,937 of 2,957 in-domain cells, and
   its &ge; 400 m<sup>2</sup> price swings about 1,000 MWp on whether Multan or SITE Karachi
   falls below the edge.

**Next step:** decide item 1, refit the coverage ratio by the rule under it, and keep the pin
unless the three held-out random boxes (Gujranwala s8, Qilla Abdullah s6, Sanghar s2) read
closer to it. They now read 0.125 m<sup>2</sup> of PV per probability-weighted m<sup>2</sup>
of household roof against the lower band's 0.33, unchanged by the refit; that gap is
the level problem of item 1, which no choice of areas here fixes.
The five priced variants are in
`/home/tobi/earthpv_data/roofclf_national_q41/variants/`.

### 22. Other free satellite data: what could still help, ranked (scoped 2026-11-10)

An assessment, not a measurement. The register has already closed the exits that look
largest from outside: temporal Sentinel-2 features do not lift roofclf (the glint-date and
step-change tests), AlphaEarth and OlmoEarth, which fold in Landsat and Sentinel-1, measure
propensity rather than panels, VIIRS adds nothing once roof area is partialled out, Sentinel-1
corner reflection was speckle, and WorldCover works only gated behind SPPI. What remains
free can each clean a few percent of leads or corroborate a few hundred large outlines; none
moves a Best figure the way a calibration area mapped on dated imagery does, and no free,
openly licensed, global source of dated high-resolution imagery exists (item 4). Ranked by
expected effect on what is published, with the first measurement each would need:

- **The Sentinel-2 archive itself**: the four-year glint window (item 13) and annual growth
  epochs (item 10). Blocked by bandwidth, not data.
- **Landsat 8 and 9**: glint, the tracker test, and an onset year since 2013 per large
  outline (item 13). The onset year is also a false-positive filter for the open-ground
  modes the country notes list (Turkey's lava, Namibia's pans, Spain's quarries, Yemen's
  shaded slopes have no construction date in a 2013 to 2026 record; a park does) and a
  commissioning-year series for the growth product without any new composite. A per-lead
  time series at 30 m over the roughly 37,000 large leads is a small read. First
  measurement: onset year against MaStR commissioning dates for Germany's judged parks.
- **Google Open Buildings 2.5D Temporal** (annual presence and height, 2016 to 2023,
  Global South only; Pakistan, India, Yemen, Egypt, Nigeria, Namibia, Zambia, Morocco,
  Vietnam). VIDA is an undated snapshot and the unit roofclf classifies; building age and
  height are two features it does not have, and height separates sheds from houses, which
  the fill rate already depends on. First measurement: the two features on one Pakistani
  quadrat set, size-controlled AUC on the spatial holdout, the glint-date harness
  (`glint_date_roofclf_feature.py`); drop it below one point. It also gives item 15 a dated
  completeness check that VIIRS cannot.
- **Sentinel-1 multi-temporal variance** (item 14): unchanged, still untested; expect a
  narrow filter, since the level test in `sar.py` was weak and chance on mountain layover.
- **EMIT** (NASA hyperspectral on the ISS, 60 m, free, acquired over arid regions): a
  spectral PV signature in the SWIR that rock, pans and lava lack, at a pixel size that
  limits it to parks of a few hectares and up. Its coverage mask is the arid terrain where
  the open-ground false positives live, which is why it is here at all. First measurement:
  an advisory column on the blob review pages against the owner's existing verdicts, never
  a veto.
- **Copernicus VHR Europe mosaics** (2 m, 2018 and 2021, registered Copernicus users): the
  only free source that touches item 4's gate, dated high-resolution imagery for calibration
  areas, but Europe only, a 2021 vintage, and the licence needs reading before mappers trace
  from it. Relevant to Germany, France, Spain, Portugal, Poland, Belgium and the Netherlands.
- **NISAR** (L-band SAR, free from 2025): a second radar channel where C-band was marginal.
  A line here, not a plan.
- **Thermal (Landsat TIRS, 100 m)**: the daytime panel-to-desert contrast is not consistent
  in the literature; the robust signal is cold water. Egypt's pools and basins and wet pans
  read far cooler than panels at 10:00, and the JRC water layer in use ends in 2020, so
  basins built since are invisible to it. First measurement: Egypt's known pool leads.

Nothing in this list helps below a few thousand square metres, so nothing here helps
roofclf, SPPI or the sub-400 m&sup2; estimate, which is where about two thirds of capacity
sits in a complete register.

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

**India's atlas counts 473 MWp of solar-thermal as PV.** Its labels predate the
solar-thermal filter, and the check could only be run after publication, by OSM id lookup:
253 label features, 9.4 km&sup2; dissolved, three concentrated-solar plants among them,
about 0.7% of Verified and of Best. Removing it rewrites the candidate file and so rebuilds
the density stage (about 31 hours), which is not worth doing for 0.7% on its own; do it
with the next India rebuild (`drop_solar_thermal.py --aoi india --by-id`, then
`--candidates`). See [India](results/india.md).

**Two segmentation checkpoints no longer exist on disk.** `v2_combined` and
`v3_combined_india` were deleted at some point after producing their outputs. The Gujarat
atlas is therefore built from a checkpoint that can no longer be verified against its own
weights, which is stated on [that page](results/gujarat.md). Nothing recovers this except
retraining.

### 23. EuropePV: one atlas for the Continental Europe Synchronous Area (planned 2026-11-12)

Proposed, not started: a combined evidence atlas over CESA whose sub-400 m² half is band
roof area priced by national PV registers (Germany's size-band estimator generalised),
with no calibration quadrats. Plan, data inventory, measured rates, timeline (3 to 4 weeks
for the EU core plus Switzerland, 6 to 8 for the whole area) and disk (about 150 / 350 GB):
`docs/issues/europepv-synchronous-area-plan.md`. Open for the owner: build it at all, the
scope, the disk, and GPU sharing with the ResNet runs.

