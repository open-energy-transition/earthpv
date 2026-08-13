# Small ground-mounted PV has no instrument -- now with external quantitative evidence (2026-08-13)

!!! note "OPEN (as of 2026-08-13)"

    This is not a new finding -- [Open questions #4](../open-questions.md) has flagged
    "small ground-mounted installations have no instrument at all" since before this
    entry existed, on structural grounds alone. What's new here is external, independent
    quantitative evidence that the gap is large in absolute terms, not just plausible in
    principle, plus a first concrete look at what building it would take. Nothing has
    been built; this is a proposal, not a shipped fix.

## The external evidence

TransitionZero + PRIED's ["Shedding light on Pakistan's distributed solar
revolution"](https://www.transitionzero.org/shedding-light-on-pakistans-distributed-solar-revolution)
(Oct 2025) reports two independently-derived national estimates for Pakistan's
distributed solar, compared in full elsewhere against this project's own atlas. The one
number that matters for this doc: both of their methods converge on **roughly 5 GW of
solar installed specifically on agricultural land**, mostly tube-well irrigation pumps --
TransitionZero's satellite-based estimate says 5.64 GW ground-mounted nationally
(purchased high-resolution imagery over sample areas, extrapolated by region/urban-rural),
PRIED's independent nationally-representative household survey (5,320 respondents,
stratified random, 95% CI) says 5.04 GW for the agriculture sector specifically. Two
methods that disagree with each other by ~6 GW on the *national total* agree to within
12% on this one component.

This project's own published evidence atlas currently reports **2.2 GW of ground-mount,
total, nationally** (`mwp_ground` in the published atlas JSON) -- everything: utility-scale
solar farms, industrial ground-mount, *and* agricultural tube-wells, combined, is less
than half of what two independent external methods say agricultural ground-mount *alone*
should be. This is the single largest and most confidently-explainable component of the
gap between this project's Best estimate (~16.0 GW) and TransitionZero/PRIED's (~29-34
GW) -- the rest of that gap has its own candidate explanations (density-domain coverage,
imagery/survey recency, definitional mismatch between geometric placement and
self-reported sector) that are a separate matter from this doc's narrower scope.

## Why this is structural, not a tuning problem

Both of this project's sub-400 m² instruments are per-*building* classifiers:

- `roofclf` scores a VIDA building footprint. A free-standing tube-well array sitting in
  a field has no building footprint to attach to -- there is nothing for
  `roofclf.building_table` to build a row from.
- The segmentation model is trained with everything below `chips.MIN_PV_AREA` (400 m²)
  burned as `ignore` in the training mask, so it receives no gradient there regardless of
  placement, and a ground array below that floor is invisible to it whether or not it
  sits on a building.

So a small ground array is doubly uncovered: too small for segmentation, and footprint-less
for roofclf. This is a different shape of gap than the rooftop one (which `roofclf`
closes), not a smaller version of it, and none of the mitigations that work for rooftops
(coverage-ratio correction, density-domain restriction, SPPI cross-check) generalize to
something with no footprint to begin with.

## We already have labeled examples of exactly this population, unused

Five of this project's own rural calibration quadrats already have hand-mapped small
ground-mount installations, none of them usable by either existing instrument:

| quadrat | ground installations | areas (m²) |
|---|---|---|
| Bahawalnagar Rural | 3 | 22.8, 32.5, 67.3 |
| Tank Rural | 3 | 25.9, 50.8, 285.6 |
| Muzaffargarh Rural Wide | 5 | 71.7, 33.4, 39.6, 28.2, 82.1 |
| Muzaffargarh Rural | 1 | 89.8 |
| Khairpur Rural | 3 | 13.4, 22.1, 116.8 |

15 installations, 13.4-285.6 m², all well under the 400 m² segmentation floor and none
attached to a building. This is a small but real, already-collected, currently-wasted
labeled set -- a first model wouldn't need new mapping to get started, just a different
way of turning them into training rows.

## What a fix would need

Sketch only -- nothing here has been validated against data:

1. **A footprint source that isn't VIDA buildings.** Candidates: field/parcel boundaries
   (if a Pakistan cropland-parcel dataset exists at usable coverage), or a sliding
   fixed-size tile/patch classifier scanned across cropland cells directly (closer to
   how `chips.py` already tiles imagery for segmentation, just at roofclf's per-pixel
   feature granularity rather than a building's).
2. **A candidate universe to score.** roofclf's universe is "every VIDA building in the
   AOI." The equivalent here is "every cropland pixel/parcel in the AOI," which is a much
   larger and less naturally bounded search space -- likely needs a coarse cropland mask
   (e.g. an existing land-cover product) as a pre-filter, or the search space is
   national-scale-infeasible.
3. **More ground-mount negatives than the 15 positives above.** A classifier needs
   verified *absence* too, and "cropland with no PV" is not currently a labeled class
   anywhere in this project -- the existing quadrats' negatives are all building-scoped.
4. **A capacity conversion.** Existing ground-mount capacity already uses a separate
   `DEFAULT_KWP_PER_M2_LAND` constant (site-area, not module-area) precisely because
   applying the rooftop module constant to ground-mount overstates by 2-3x
   (`docs/methods/density.md`) -- a small-ground-mount instrument would need the same
   care, likely inheriting this constant rather than needing a new one.

## Not done here

No code was written, no data was pulled beyond what's already in this project's own
quadrat labels, and no feasibility judgement is being made about the cropland-mask or
parcel-boundary questions above -- those need their own investigation before this is
buildable, let alone scheduled.
