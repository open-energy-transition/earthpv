---
title: "EarthPV: Germany"
hide:
  - navigation
  - toc
---

<div class="page-full-bleed" markdown>
<nav class="atlas-switch" aria-label="Choose a country atlas">
  <span class="atlas-switch__label">Atlas</span>
  <a href="../atlas/">Pakistan</a>
  <span aria-current="page">Germany</span>
  <a href="../atlas-france/">France</a>
  <a href="../atlas-zambia/">Zambia</a>
  <span class="atlas-switch__note">
    <b>Verified</b> is the hand-mapped OpenStreetMap population alone. <b>Best</b> adds three
    things to it: the model's own &ge; 400 m&sup2; detections, a register-calibrated estimate
    of everything below that floor, and the mapped installations the model did not itself find.
    The sub-400 m&sup2; part is the largest of the three, and it is a
    <b>statistical estimate, not a detection</b>: roof area in the 200-400 m&sup2; band priced
    at 0.03493 kWp/m&sup2; against MaStR, with no classifier. It replaced a roofclf component
    measured as worse than a plain roof-area baseline (48.4% against 37.8% median municipal
    error; this estimator scores 35.6%). Because a regression has no second detector to agree
    with, Verified carries no sub-400 component &mdash; which is why the two tiers are so far
    apart here, and why Verified alone excludes the 65.5% of German rooftop capacity sitting
    below the floor.
    Both tiers now also count hand-mapped installations outside the composited grid, in cells
    with no imagery and no inference of their own.
    <b>Read the tiers as geography, not capacity</b> &mdash; they fail their own register
    check, because German OpenStreetMap polygons outline roofs and sites rather than arrays.
    <a href="../results/germany/">What was measured, and how</a>.
  </span>
</nav>
<iframe src="../assets/interactive/germany_pv_evidence_atlas.html" title="Germany PV evidence atlas: verified and best estimate by 0.1-degree cell"></iframe>
</div>
