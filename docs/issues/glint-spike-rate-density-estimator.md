# Glint spike-rate as a statistical density estimator for sub-pixel PV

**Labels:** enhancement, density, villages

## Problem

Segmentation-based density estimation collapses in exactly the size regime
where most of Pakistan's distributed PV lives. Measured on 500 OSM-confirmed
installations (`results/glint_validation_pakistan/REPORT.md`, 2026-07-17):

| size | detection rate |
|---|---|
| <100 m² | 6% |
| 100–500 m² | 16% |
| 500–1k m² | 22% |

For these sizes `density.py`'s fallback (centroid-pixel probability ×
footprint area) is effectively noise. Urban rooftop and village density
numbers built on it inherit that.

## Proposal

Stop trying to *find every panel* below the resolution limit; instead
*estimate what fraction of roofs have panels*, using glint as a sampling
instrument:

1. Per grid cell (or per calibration stratum), draw a random sample of N
   building footprints.
2. For each, compute the existing per-scene glint statistic over ~2 years of
   S2 scenes (machinery already exists: `scripts/glint_validate_pakistan.py`
   pull/analyze, `src/earthpv/glint.py`) and record spike-detected yes/no.
3. Invert the observed spike rate through the size-resolved detection curve
   (already measured, table above) to get an adoption-rate estimate with a
   binomial confidence interval.
4. Combine adoption rate × median installation size (from calibration
   quadrats, per stratum) into a small-PV density term that complements the
   segmentation-based `pv_area_det`/`pv_area_exp` for ≥1k m² installations.

## Why this is credible now

- The detection-probability curve is measured, not assumed — that's what makes
  the inversion legitimate.
- Spike amplitude is roughly size-independent (median 2.2–3.1× baseline
  across all buckets), so the instrument doesn't saturate or fade with size;
  only the *chance* of catching a spike does, and that's what the curve
  captures.
- Per-target cost is a STAC stats pull, already proven at 500-target scale
  (survived a PC outage, resumable).

## Status (2026-07-18): v1 implemented, instrument floor measured

`scripts/glint_spike_rate_estimator.py` implements sample → (existing
`glint_density_pull.py`) → analyze, end-to-end tested on a small Lahore patch.
The false-spike floor is no longer an open question — measured on the
corroboration experiment's control buildings:

| criterion | Lahore controls (n=69) | detection prob, 100–500 m² bucket |
|---|---|---|
| detected (≥1 spike) | **20.3%** false rate | 16.2% |
| validated (≥2 consistent) | **8.7%** false rate | 8.8% |

i.e. **below ~500 m², the instrument's false rate currently equals or exceeds
its true-detection rate — the inversion is undefined exactly where the
estimator matters most.** It works today for the 500 m²–50k m² range
(validated: d 16–31% vs f 8.7%). Two caveats cut in opposite directions:
(a) the "controls" were only model-negative, not verified-negative — real
unmapped PV among them inflates f, so the true floor may be lower (quadrat
verified-negatives will settle this); (b) Germany controls show far higher
false rates (70%/21%), so the floor is region-dependent and must be measured
per deployment region. Next steps, in order: get verified-negative f from
quadrats; re-tune the spike/consistency thresholds for specificity rather
than the validation-tuned operating point; only then trust sub-500 m²
estimates.

## Open questions

- ~~False-spike rate on *non*-PV roofs (metal roofs, water tanks) sets the
  estimator's floor — needs measuring on a known-negative building sample~~
  Measured (see Status above): 8.7–20.3% on Lahore model-negative controls,
  region-dependent; verified-negative measurement from quadrats still needed.
- Sample size N per cell for a target CI width; likely hundreds of buildings
  per stratum, not per cell — may argue for stratum-level rather than
  cell-level estimation, disaggregated by covariates.
- Detection curve was measured on OSM-mapped (biased toward visible?)
  installations; quadrat data should re-verify it.

## Acceptance

- A `glint_density` estimate per stratum (or cell) with CI, validated against
  ≥2 held-out exhaustively-mapped calibration quadrats
  (`docs/calibration-mapping-protocol.md`), for at least one urban and one
  village stratum.

---
🤖 Drafted with [Claude Code](https://claude.com/claude-code)
