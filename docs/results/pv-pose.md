# Panel pose from solar glint

A glass-fronted PV panel is partly a mirror. Sentinel-2 views close to nadir, so a fixed
panel reflects the sun into the sensor only when its tilt and azimuth happen to bisect the
sun and the satellite at the roughly 10:30 local overpass. That is a narrow,
geometry-predictable condition, which makes it useful twice over: a flash is physical
evidence that something specular is on that roof, and the set of dates on which it flashed
inverts to a single panel orientation.

![Solar glint validation geometry: a matched panel tilt reflects the sun straight into Sentinel-2's near-nadir sensor while a mismatched tilt sends it elsewhere, and the resulting time series shows a reflectance spike on the geometry-predicted date while the surrounding annulus stays flat.](../glint_geometry.svg)

## The country survey

![Polar plot of fitted panel pose across Pakistan: tilt as radius from 0 to 30 degrees, azimuth as angle. Measured points cluster between east-southeast and due south at tilts of roughly 5 to 20 degrees, with a shaded wedge covering the rest of the compass, from due south through west and north to east-southeast, marking orientations this orbit can never observe.](../assets/figures/pv_pose_polar.svg#only-light)
![Polar plot of fitted panel pose across Pakistan: tilt as radius from 0 to 30 degrees, azimuth as angle. Measured points cluster between east-southeast and due south at tilts of roughly 5 to 20 degrees, with a shaded wedge covering the rest of the compass, from due south through west and north to east-southeast, marking orientations this orbit can never observe.](../assets/figures/pv_pose_polar.dark.svg#only-dark)

The interactive version below adds per-installation detail, the tilt and azimuth
histograms, and the validation rate by size.

<div class="embed" markdown>
<iframe src="../../assets/interactive/pakistan_pv_pose.html" title="Fitted panel pose across Pakistan from Sentinel-2 glint" loading="lazy"></iframe>
</div>
<p class="embed-note">
Fitted tilt and azimuth for 336 installations whose historical Sentinel-2 reflections agree
on one fixed panel plane, out of 2,843 checked across two years: a 2,000-installation
size-stratified sample plus 843 drawn at random in regions it left thin.
<a href="../../assets/interactive/pakistan_pv_pose.html" target="_blank">Open full screen</a>.
</p>

Three things in that plot are worth stating plainly.

**Nothing measured crosses due south, and that is the sensor, not the roofs.** Sentinel-2
crosses this latitude at a fixed local time, so over two full years the sun's azimuth at
the moment of every overpass never once swings west of south. A panel facing southwest,
west, north or northeast cannot glint into this sensor no matter how long you wait, so the
shaded wedge covering that arc is not measured emptiness -- it is missing measurement.
Installations facing that way are invisible to this method, not absent, so the plot shows
only what was actually measured rather than assuming the population is mirror-symmetric
about the south axis and filling the rest in.

**The population is dispersed, and bimodally so.** Tilt ranges from 2.5 to 28.6 degrees
with an interquartile range of 7.2 to 18.8, and it splits into a shallow cluster around
3 to 6 degrees (ground and utility mounts) and a broad hump at 15 to 21 degrees (typical
fixed-pitch rooftop). The single densest tilt-and-azimuth bin holds under 10 percent of the
fitted population.

**Most installations never produce a fittable pose.** In the size-stratified sample, 51
percent of the installations at or above 1,000 m<sup>2</sup> showed no glint signal at all,
and another 26 percent glinted once or on dates that disagree. That detects presence but
carries no orientation information. Only 23.2 percent reach this plot.

!!! note "Corrected 2026-10-22: one pass counted once"

    Neighbouring Sentinel-2 tiles overlap, so one satellite pass can arrive as two copies.
    The fit had counted a glint seen in both copies as two dates that agree. That was
    enough on its own to validate a pose for 10 of the 346 fitted installations (9
    ground-mount, 1 rooftop), and they are gone now. None of the remaining fits moved.
    The page also now includes the second regional top-up of 442 installations, which had
    been merged into the survey data without the page being rebuilt.

## France: the whole population

France's survey fits every OSM-mapped installation of 1,000 m<sup>2</sup> or more rather
than a sample: 1,277 poses from 6,337 installations, 20.2%, against Pakistan's 23.2% at the
same size. It is on the [France atlas](../atlas-france.md), where every point names its OSM
installation and the CSV download carries each one's id and coordinates. Numbers and caveats:
[France](france.md#panel-pose-from-sentinel-2-glint-2026-10-26).

## What glint is and is not good for

Glint is a **reward-only** signal in this pipeline. A candidate with two or more mutually
consistent spike dates gets a `rank_score` boost; a candidate with none is left exactly
where it was. The reason is in the sensitivity curve below: real installations frequently
do not glint, so absence is not evidence.

![Solar glint detection and validation rates for 500 OpenStreetMap-confirmed Pakistani installations across six size buckets. Detection rises from 6 percent below 100 square metres to 73 percent above 50,000, while geometric validation plateaus near 26 to 31 percent for everything above 1,000 square metres, against a measured 8.7 percent false-validation floor.](../assets/figures/glint_by_size.svg#only-light)
![Solar glint detection and validation rates for 500 OpenStreetMap-confirmed Pakistani installations across six size buckets. Detection rises from 6 percent below 100 square metres to 73 percent above 50,000, while geometric validation plateaus near 26 to 31 percent for everything above 1,000 square metres, against a measured 8.7 percent false-validation floor.](../assets/figures/glint_by_size.dark.svg#only-dark)

Two properties of that curve drive how the signal is used:

* **Detection scales with size, cleanly and monotonically.** Larger arrays get more
  chances at a glint, not brighter ones; spike amplitude is roughly constant at 2.2 to 3.1
  times baseline across every size class.
* **Geometric validation plateaus, it does not keep climbing.** Utility plants above
  50,000 m<sup>2</sup> are the easiest to detect but validate no better than mid-size
  arrays, because large plants mix orientations and often track the sun, which a
  single-plane fit cannot explain. The orientation fit is a rooftop and fixed-tilt tool.

Dividing the validated rate by the 8.7 percent control floor gives a per-bucket likelihood
ratio, which is what the `rank_score` multiplier is derived from: roughly 1.9 times for
500 to 1,000 m<sup>2</sup>, 3.5 times for 1,000 to 5,000, 3 times above that, and
**1 times below 500 m<sup>2</sup>**, where the instrument is blind and the pipeline
therefore never spends a query.

## Seeing it

The [glint image gallery](../glint_examples.md) shows six real installations glinting in
high-resolution imagery, plus the same phenomenon rendered from raw Sentinel-2 data, one
example per size bucket.

For how the detector works, the tile-batched fetch strategy, and the dense-urban
self-referenced mode, see [Solar glint](../methods/glint.md).

## Reproducing

```bash
pixi run python scripts/glint_validate_pakistan.py sample    # stratified 500-target sample
pixi run python scripts/glint_validate_pakistan.py pull      # ~2 years of scene stats, resumable
pixi run python scripts/glint_validate_pakistan.py analyze   # summary and aggregate CSVs
.pixi/envs/default/bin/python scripts/build_pv_pose_country2000.py   # the pose page above
```

The pull is network-bound and survives Planetary Computer outages by resuming per target.
Full report and CSVs: `results/glint_validation_pakistan/`.
