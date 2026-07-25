# Standard-pose glint matched filter (assessed against real data — not recommended as a general detector)

## The idea, as discussed

Use the population's dominant (tilt, azimuth) as a forward model: predict the small
set of calendar dates a panel at that pose would glint into Sentinel-2 at a given
latitude, then cheaply check only those dates across every building in a city/village
instead of the expensive blind 2-year per-target spike search that made brute-force
building scanning "computationally infeasible" in the original direct-detection test
(`scripts/glint_direct_detect.py`, ~1 min/building).

## What the n=2000 study actually shows

Fitted (tilt, azimuth) for 290/2000 targets (`data/glint/country2000_summary.csv`,
`n_consistent >= 2`), binned into 3°-tilt x 10°-azimuth cells:

- The single densest bin (tilt 12-15°, azimuth 165-175°) holds **28/290 = 9.7%**
  of the fitted population.
- The top 3 bins together: **19.3%**. Top 5 bins: **26.6%**.
- Full spread: tilt ranges 2.5°-28.6° (IQR 6.3°-18.8°), azimuth 81.7°-180.1°
  (IQR 139°-173°) -- both wide, and tilt is visibly **bimodal**, not unimodal: a
  large low-tilt cluster (3-6°, 64 targets -- shallow-mount ground/utility) and a
  separate broad hump at 15-21° (83 targets -- typical fixed-pitch rooftop).

**Conclusion: the population is not concentrated enough for this to work as a
general "one pose, scan any city" detector.** Even picking the single best bin only
ever has a shot at ~10% of real installations; a handful of bins tops out at ~27%.
That's not "cheap recall boost," that's "cheap recall boost for a tenth of the
population, and you still don't know it's a false negative vs. a different pose for
the other 90%." Building this as a country-wide brute-force scanner would mostly
produce a lot of confident non-detections that mean nothing.

(Note: this session's Lahore calibration-box result -- glint at 0/1,021 confirmed
installations in one dense planned-housing development -- fits neatly into this
picture. A *single development* plausibly does share one roof convention by
construction, but that's a *local* fact about that one subdivision, not a *national*
standard pose. The 2000-target country sample mixes hundreds of such local
conventions together, which is exactly why the aggregate looks this dispersed.)

## What would actually be worth building instead

The failure mode is scope, not the core idea. Two narrower, better-grounded versions
survive the data:

1. **Per-locality pose calibration, not a national one.** Fit (tilt, azimuth) from
   whatever OSM-confirmed installations already exist *within* a target
   city/subdivision (even a handful), then matched-filter-scan the rest of that
   *same* locality's buildings against its own local mode. This only works where a
   locality already has enough seed installations to fit a local pose in the first
   place -- it's a densification tool for partially-mapped areas, not a way to find
   PV in areas with zero existing signal.
2. **Top-K pose bank as a pre-filter, not a detector.** Use the 3-5 densest bins
   (covering ~27% of the fitted population) to build a small set of candidate
   glint-date calendars, and only run the (still relatively cheap, chunked
   tile-batched) blind per-target search on buildings that show *zero* hits against
   all K predicted-date sets over a short trial window -- i.e. use it to cheaply
   triage which buildings can skip a full 2-year pull because a top-K pose already
   found their glint on the first pass, not to declare "no signal" on a miss.

Both are legitimate follow-ups; neither is "scan every building in Pakistan with one
predicted date list," which the data plainly doesn't support.

## Status

Assessed, not implemented. Do not build the general brute-force version described
in the original conversation -- the concentration data above is the reason. If
either narrower version (per-locality calibration, or the top-K triage pre-filter)
is wanted, that's a fresh, smaller scoping exercise, not a continuation of this one.
