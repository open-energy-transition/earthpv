# Solar glint

`src/earthpv/glint.py` is the production module; `postprocess --check-glint` is the entry
point. For the physics, the country-wide pose survey and the sensitivity curve, see
[Panel pose from glint](../results/pv-pose.md). This page covers how the detector is
built and how it is budgeted.

## The measurement

For each target, pull roughly two years of per-scene Sentinel-2 L2A statistics in bands
B03 and B08, scene cloud cover at most 80 percent. The statistic per scene is the 98th
percentile reflectance inside the polygon against a 30 m annulus around it. Sub-pixel
polygons fall back to an `all_touched` mask so even a feature under 100 m<sup>2</sup> reads
its brightest touched pixel.

**Detected** means at least one spike: simultaneously bright in B03 and B08 inside the
polygon while the surrounding annulus stays stable, which rules out haze and cloud
brightening.

**Validated** means one fixed panel orientation, a single tilt and azimuth, explains at
least two spike dates through the specular reflection condition within a 3 degree
tolerance. The spikes are then geometrically consistent with one glass plane rather than
random brightening.

Sun and view geometry are propagated with Skyfield and cross-checked against the real
`MTD_TL.xml` granule angles. A separate check confirmed sun-only agreement is exact, while
full TLE-propagated forward prediction is unreliable for reconstructing historical spike
dates, which is why `glint.py` never uses TLEs for anything but the forward-looking
overpass calendar.

## The contract with the ranking

Reward-only. A candidate with fewer than two mutually consistent spike dates is left
unchanged, and the multiplier for a confirmed candidate approaches its size bucket's
measured likelihood ratio, capped at four times, as the consistent-date count saturates
at four. This matches the recall-first contract that the building and epoch priors follow.

## Budgeting a network-bound check

Each candidate needs dozens to hundreds of Sentinel-2 reads, so the check is opt-in and
targeted rather than universal.

```bash
pixi run earthpv postprocess --aoi punjab --check-glint \
    --glint-top-n 300 --glint-skip-top 100
```

* Candidates below 500 m<sup>2</sup> are **never** queried. Their measured likelihood ratio
  is about 1, so the answer changes nothing.
* The `--glint-skip-top` highest-ranked candidates are skipped. They reach human validation
  regardless.
* The `--glint-top-n` budget goes to the best-ranked eligible candidates in the uncertain
  band below that.

**Fetched tile-major, not per candidate.** `glint.tile_scene_series_batch` does one STAC
search and one set of asset opens per spatial bin (`--glint-tile-deg`, default 1.0 degree),
shared by every eligible candidate in it, instead of rediscovering the same scene list and
reopening the same cloud-optimized GeoTIFFs once per candidate. Candidates cluster heavily
by tile, so this measured a 22x speedup on a real six-candidate cluster, with output
identical to the old per-candidate fetch down to 0.000 numerical difference on matched
scenes. That equivalence was verified only after fixing a real bug in which a
seam-zone candidate could silently pick up an adjacent tile's non-covering item.

Each tile group tries Planetary Computer first and falls back to Earth Search on AWS Open
Data, which needs no authentication and fails independently.

!!! warning "Token expiry at country scale"
    A country-scale batched run can silently lose roughly half the scenes for 48 percent of
    targets when the Planetary Computer signing token expires mid-run. Check the per-target
    scene counts before trusting a large pull, and relaunch: the per-target file resume
    design means nothing already fetched is lost.

## Dense urban blocks need a different criterion

The default check requires the surrounding annulus to be dim **right now**
(`a > 1.5 x r`). At roughly 2,500 buildings per square kilometre that fails structurally:
every annulus is lined with similarly bright rooftops. Exhaustively scanning a 0.2 square
kilometre Lahore residential block against fresh Overpass ground truth found **zero**
detections anywhere, mapped or unmapped, and a confirmed heavily panelled 503 m<sup>2</sup>
rooftop never exceeded a 1.09 times ratio over a full year.

`--glint-self-referenced` (`glint.annotate_spikes`) swaps the absolute test for a temporal
one: the annulus must stay near **its own** baseline rather than be dim in absolute terms.
It keeps the same cloud and haze rejection, and it was verified to match the default mode
to within one consistent-date count on eight installations the default already detects. It
is a different criterion for the same evidence, not a laxer one. Reach for it in dense
urban contexts, not as a general replacement.

## Glint as a direct detector

Tested, and mostly negative. Scanning every building rather than only model candidates
gives about 1 percent hit rate on random buildings and about 9 percent on the model's new
leads, from 61 validated targets. That is enough to produce a first glint-calibrated
density contribution but not enough to replace the model.

The idea of using the population's dominant pose as a cheap forward model, predicting the
few dates a standard panel would glint and checking only those across a whole city, is
[assessed and not recommended](../issues/standard-pose-matched-filter.md): the densest pose
bin holds under 10 percent of fitted installations and the top five bins under 27 percent.
Two narrower versions survive the data, per-locality pose calibration and a top-K
triage pre-filter, and both are open work.

## Research scripts

| Script | What it answers |
| --- | --- |
| `glint_validation.py`, `glint_validate_pakistan.py` | the core empirical validation, the latter at country scale stratified by size |
| `glint_candidate_precision.py` | stratified glint sample of unmapped candidates, feeding `calibrate-candidates` |
| `glint_iou_experiment.py`, `glint_pixel_refine.py` | can glint move pixel IoU rather than just re-rank? Threshold gating no; per-pixel spike-amplitude trim, a narrow win |
| `glint_density_*.py`, `glint_cell_density_*.py` | two attempts at regional density from glint, both negative |
| `glint_skyfield_check.py` | independent astronomy cross-check of the geometry fit |
| `s1_corner_reflector_test.py` | the Sentinel-1 dihedral hypothesis, negative |
| `glint_s2_example_grid.py` | builds the [Sentinel-2 image gallery](../glint_examples.md) |
| `build_pv_pose_country2000.py` | builds the [pose survey page](../results/pv-pose.md) |
