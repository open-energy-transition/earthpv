# Germany: capacity map and register validation

Germany is the only place this project can check itself against an answer rather than
against another estimate. Registration in the **Marktstammdatenregister (MaStR)** is legally
mandatory for grid-connected PV, so German rooftop capacity per municipality is not a sample.
This page is the first national end-to-end run there, produced 2026-08-31 from compose
through the atlas below, and re-derived 2026-09-01 after the register was also used to
measure candidate precision.

It is a different kind of page from the [Pakistan capacity map](capacity.md) or the
[Gujarat map](gujarat.md). Those report what the pipeline estimates. This one reports how
wrong that estimate is, because here that is measurable.

<div class="embed" markdown>
<iframe src="../../assets/interactive/germany_pv_atlas.html" title="Germany PV capacity atlas" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Hover a cell for its value.
<a href="../../assets/interactive/germany_pv_atlas.html" target="_blank">Open full screen</a>.
</p>

!!! danger "Do not read this atlas's hero number"
    The six-estimator template's hero figure is `est_mwp_rc`, and the register shows that
    estimator overstates German rooftop capacity by roughly threefold. **Germany's readable
    estimator is `est_mwp_det`**, the precision-honest floor, at an OLS slope of 0.340 against
    the register. The cause is a recall denominator, it is diagnosed rather than fixed, and it
    is tracked as [open question 3](../open-questions.md). The atlas is published as-is rather
    than with a Germany-specific hero, because showing all six exposures side by side is the
    page's whole premise and quietly swapping one country's headline would hide exactly the
    disagreement this page exists to report.

!!! warning "Segmentation-only: no roofclf half, and a register cannot supply one"
    Germany has **zero calibration quadrats**, so neither `roofclf` nor the sub-400 m<sup>2</sup>
    instruments exist for it, the same state as Gujarat. The register does not substitute:
    MaStR publishes no coordinates below 30 kWp, which is `roofclf`'s entire domain. Closing
    this needs mapped German quadrats, and the 3.6% OSM completeness measured on this page
    means they have to be *mapped*, not derived from an OSM pull.

## What ran

| | |
| --- | --- |
| 4,656 | 0.1&deg; cells composited and inferred (of 4,664 selected; 8 returned empty composites from both STAC sources) |
| 2025-04-01 to 2025-09-30 | composite window, matched to the register cutoff and to the training imagery |
| `v4_combined_all` epoch=41 | checkpoint. **Not** the documented `v3_combined_india`, which is no longer on disk (owner-approved substitution, 2026-08-23) |
| 23,920 | capacity-relevant candidates (of 24,590; oversize blobs excluded as `density` does) |
| 6,613 / 17,307 | OSM-mapped / unmapped candidates |
| 10,533 of 10,949 | municipalities covered: **96.2% by count, 99.75% by capacity** |

That coverage is what lets `validate_density_against_mastr` report a national result instead
of refusing. The guard is not decorative: a run covering 4 of Germany's 76 MGRS tiles would
have produced a national sum near 5% of truth and a slope that reads as catastrophic model
failure rather than as missing imagery.

## How accurate is it

Truth here is `kw_rooftop - kw_le_72` = **25,723.5 MWp**, the registered capacity in units
above the 400 m&sup2; / 72 kWp segmentation floor. That is the denominator a &ge; 400 m&sup2;
model can actually see; measured against *all* rooftop capacity (74,637.6 MWp) every slope
below falls by roughly the 65.5% sub-floor share, which is a statement about the floor and
not about the model.

| Estimator | Slope (1.0 = unbiased) | Predicted MWp | Spearman &rho; | Reading |
| --- | --- | --- | --- | --- |
| `est_mwp_det` | **0.340** | 10,699.6 | 0.661 | Precision-honest floor. Germany's readable number |
| `est_mwp_exp` | 0.388 | 13,110.4 | 0.656 | Probability-weighted ceiling |
| `est_mwp_cal` | 0.167 | 5,190.2 | 0.651 | Precision-weighted. Was 0.038 before the register fix below |
| `est_mwp_rc_roof` | 3.11 | 97,728.4 | 0.597 | Recall-corrected. **Overstates; do not use** |

Two things are worth taking away, and they point in opposite directions.

**Ranking transfers; level does not.** Every estimator lands at &rho; &asymp; 0.60 to 0.66
while slopes span 0.17 to 3.11. The model puts capacity in the right municipalities and gets
the amount wrong. That is the same pattern as Pakistan's
[external comparison](capacity.md#what-this-map-cannot-tell-you-and-what-an-independent-estimate-confirms-it-can),
now confirmed against a mandatory register rather than owner-attested quadrats.

**No estimator here is close to unbiased.** The best-calibrated recovers about a third of the
capacity it could see. Read that as the honest accuracy of segmentation-only detection at
10 m GSD, not as a defect introduced by the calibration work below.

## What the register bought, and what it broke

The full derivation is in
[Validating against a complete register](../methods/mastr-validation.md); the outcome in
brief.

Germany's calibration table shipped `p_unmapped: 0.0` &mdash; no instrument existed for
P(candidate is real | no OSM match), so every unmapped candidate was priced at zero. MaStR
closes that above 30 kWp, where it publishes per-unit coordinates (it publishes none below,
for 4.17 million units). Measured per placement and chance-corrected, rooftop `p_unmapped`
runs 0.061 to 0.759 across the size bins.

That fix moved `est_mwp_cal` from 0.038 to 0.167 &mdash; better bounded, still far
from 1.0. It also moved `est_mwp_rc_roof` from 0.262 to 3.11, from understating truth
to overstating it. **Two errors had been cancelling**: a `p_real` held down by the missing
term, and a recall denominator that is too small. Removing the first exposed the second.

This is the single most useful thing the register did, and it is a warning rather than a
result. A plausible-looking national total had been produced by two large errors pointing in
opposite directions, and nothing except a complete reference could have revealed it.
**Pakistan shares the same estimator code and has no complete register.**

## The plausibility gate, before and after

`check-density` is the pre-publication gate for the failure modes `p_real` weighting cannot
catch. The register fix moved it in both directions, which is worth recording rather than
just reporting the final state:

| | Before | After |
| --- | --- | --- |
| ok | 19 | 17 |
| suspect | 1 (Saarland, ground-mount 3.6x rooftop) | 0 |
| fail | 0 | 3 (Hamburg, Bremen) |

**Saarland's flag cleared legitimately.** It was flagged because ground-mount read 3.6x its
rooftop total; rooftop capacity rising twelvefold is exactly the correction that ratio was
complaining about.

**The three new failures are structural, not detections.** Both regions are city-states
spanning only a handful of 0.1&deg; cells: Hamburg's top cell holds 32% of its 297.9 MWp,
Bremen's 38% of 214.8 MWp. A region a few cells wide will always concentrate, so the
single-cell-concentration check is uninformative there. That is the same reading this project
already applies to Islamabad Capital Territory in Pakistan, and the same standing precedent
for publishing a checked-genuine plausibility failure. Note the ground:rooftop ratio check
correctly skipped both (it requires `mwp_ground >= 50`; they have 7.1 and 3.1), while the
concentration check has no equivalent minimum-region-size guard.

One data quirk visible in the output: `plausibility.csv` carries **20 rows for Germany's 16
states**, with Hamburg, Mecklenburg-Vorpommern, Niedersachsen and Schleswig-Holstein each
appearing twice. That is a duplication in the region polygons, not a duplicated estimate, and
it inflates the denominator in the "of 20 regions" summary line.

## What this run opens up

Three things follow from it, all tracked on [Open questions](../open-questions.md).

**The recall denominator has to be audited, and not only for Germany** (item 3). The
`est_mwp_rc` overshoot above is diagnosed but unfixed, and Pakistan runs the same estimator
code without a register to catch it.

**MaStR also records installed pose, uncensored** (item 12). `glint_opportunity.py` documents
its pose prior as necessarily *assumed*, because this project's own pose survey was fitted
from observed glints and is therefore censored by construction. The register carries azimuth
and tilt for 97.4% of 4.44M rooftop units, of which 225,138 also have coordinates. Checked
against the assumed prior it is far too narrow: 23.8% of German units are pitched steeper than
40&deg; where the prior implies 3.04%. That makes Germany a place to test the glint model's
mechanism rather than just its hit rate.

**France, not Germany, is the place to check the small half** (item 5). The 30 kWp coordinate
cliff means this register can say nothing about the sub-400 m&sup2; population, which is where
`roofclf` operates and where the evidence is still 30 purposive Pakistani quadrats.
DeepPVMapper and BDAPPV cover exactly that band in France.

## Reproducing this

```bash
# compose is the long pole (~4,700 cells at ~35 cells/h). LimitNOFILE must be the
# soft:hard PAIR -- a bare 65536 sets only the hard limit, leaves the soft limit at
# 1024, and compose dies repeatedly on "Too many open files".
systemd-run --user --unit earthpv-compose-germany --working-directory=$PWD \
  --property=Restart=on-failure --property=LimitNOFILE=65536:65536 \
  bash -c '.pixi/envs/default/bin/python -m earthpv.cli compose --aoi germany \
           --use-vida --workers 5 --window 2025-04-01:2025-09-30'

pixi run -e ml earthpv infer --aoi germany --checkpoint <ckpt>
pixi run earthpv postprocess --aoi germany --threshold 0.3

pixi run python scripts/mastr_p_unmapped.py --base-rate-cells 150
pixi run earthpv calibrate-candidates --aoi germany \
  --mastr-p-unmapped results/germany_mastr_p_unmapped.csv

pixi run earthpv density --aoi germany --districts --force
pixi run earthpv check-density --aoi germany
pixi run earthpv validate-mastr --aoi germany --solar-path <national OSM solar pull>
```

`scripts/run_germany_mastr_pipeline.sh` chains everything after `compose` and waits for it.
See [Setup New Country](../reproduce.md) for the full runbook.
