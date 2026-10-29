# Open questions

What is genuinely unresolved, as of 2026-10-28. This page exists so that the honest gaps are
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
scoring, because the quadrats are curated and industrial-leaning. Three scorings have shipped
since 2026-08-17 and none has a logged verdict: the parcel-label batch (seed 20260817,
`results/pakistan_roofclf_parcel_validation/`) was reviewed by the owner but its per-cell
counts were never written down; the Box 18 refit (seed 20260820) and the area-weighted
rescoring (seed 20260920), both in `results/pakistan_roofclf_validation/`, were generated and
not reviewed. `results/roofclf_random_validation_log.csv` holds all three batches as 60 rows
(the third added 2026-10-28), every verdict blank. The published Best
therefore rests on an unreviewed rescoring, priced since 2026-10-25 by a weighting that leans
harder on the score's level (item 1), and item 2 would move it again on top.
Protocol: [roofclf random-cell validation](methods/roofclf-national-validation.md). The
out-of-domain batch (`results/pakistan_roofclf_validation_outdomain/`) is blocked by stale
imagery (item 4) and should not hold the others up.

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

### 8. `building_table`'s roof term counts a ground array that clips a shed as rooftop PV

`parcel_pv_area` skips any installation at or above `YARD_MAX_INSTALLATION_M2` (400 m&sup2;),
because above that floor ground-mount is segmentation's and the atlas already prices it. The
roof term beside it (`roof_pv_area`) has no such guard. On Kalat Rural, sited deliberately to
include ground-mount, **69 of the 89 buildings the roof term labels has-PV are labelled solely
because a >= 400 m&sup2; ground array clips them** (median footprint 29 m&sup2;, a 21.24% base
rate at 46.5 bldg/km&sup2;). Folding it in unchanged would fit the sparse band's coverage
ratio on ground-mount and double-count against segmentation's `est_mwp_rc_ground`.

**Guard in place (2026-10-25):** `roof_pv_area` now ignores ground-placed installations of
400 m&sup2; or more, the owner's condition for letting farm areas calibrate `roofclf` at all
(every area now feeds both detectors). **What would close it:** the next refit re-measures every
quadrat's `base_rate` and `pv_area_true_m2` with the guard (expected small outside Kalat,
unmeasured), and the owner decides whether Kalat Rural joins. Until then it is excluded from
every refit by hand, because `roofclf.discover_quadrats` picks it up automatically, as it now
picks up the farm areas. See [Calibration boxes](issues/pakistan-calibration-boxes.md)' Box 17.

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

### 13. Glint and pose: four untested refinements

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
