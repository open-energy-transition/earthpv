# Germany: capacity map and register validation

Germany is the only place this project can check itself against an answer rather than
against another estimate. Registration in the **Marktstammdatenregister (MaStR)** is legally
mandatory for grid-connected PV, so German rooftop capacity per municipality is not a sample.
This page is the first national end-to-end run there, produced 2026-08-31 from compose
through the atlas below and re-derived twice since, because the register found two errors in
it.

It is a different kind of page from the [Pakistan capacity map](capacity.md) or the
[Gujarat map](gujarat.md). Those report what the pipeline estimates. This one reports how
wrong that estimate is, because here that is measurable.

<div class="embed" markdown>
<iframe src="../../assets/interactive/germany_pv_evidence_atlas.html" title="Germany PV evidence atlas" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Hover a cell for its value.
<a href="../../assets/interactive/germany_pv_evidence_atlas.html" target="_blank">Open full screen</a>.
</p>

!!! danger "This atlas's tier totals fail a register check. Do not quote them."
    The evidence atlas reports Verified 38,508 MWp and Best 49,324 MWp for Germany. Both are
    **too high**, and unlike anywhere else this project works, that can be proven rather than
    suspected.

    Verified is the hand-mapped OpenStreetMap population, converted at the module constant
    for rooftop and the land constant for ground. Against the register:

    | | OSM-derived | MaStR registered | |
    |---|---|---|---|
    | Rooftop | 22,032 MWp (122.4 km&sup2; &times; 0.18) | 74,823 MWp | 29.4% of *all* capacity, from a reference covering 3.6% of units |
    | Ground | 43,965 MWp (879.3 km&sup2; &times; 0.05) | 37,138 MWp | **118%** |

    The ground component alone exceeds **all** registered German ground-mount capacity,
    which is impossible. The cause is mapper convention, and it is already measured further
    down this page: nothing in OSM records whether a `generator:source=solar` polygon
    outlines the panel array or the whole roof or site it sits on, and Germany's implied
    kWp/m&sup2; spans 0.02 to 0.99 against the project's 0.18. Area &times; a constant does
    not give German capacity.

    **Germany's defensible number is the segmentation estimator `est_mwp_rc_roof`, at an OLS
    slope of 0.405 against the register.** The atlas is published for its structure and
    per-cell geography, not for its headline figures.

!!! warning "Segmentation-only: no roofclf half, and a register cannot supply one"
    Germany has **zero calibration quadrats**, so neither `roofclf` nor the sub-400 m<sup>2</sup>
    instruments exist for it, the same state as Gujarat. Verified therefore has no
    roofclf-AND-SPPI population to add and Best no roofclf-alone density; both tiers stop at
    the 400 m&sup2; floor, above which sits only 34.5% of German rooftop capacity. The
    register does not substitute: MaStR publishes no coordinates below 30 kWp, which is
    `roofclf`'s entire domain. Closing this needs mapped German quadrats, and the 3.6% OSM
    completeness measured below means they have to be *mapped*, not derived from an OSM pull.

    The six-exposure page previously published here was **deprecated and removed**
    (2026-09-02). `density` used to build it automatically alongside the real product, and
    its hero figure read 114 GWp.

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
| `est_mwp_rc_roof` | **0.405** | 12,509.7 | 0.628 | Recall-corrected. Germany's readable number |
| `est_mwp_exp` | 0.388 | 13,110.4 | 0.656 | Probability-weighted ceiling |
| `est_mwp_det` | 0.340 | 10,699.6 | 0.661 | Precision-honest floor |
| `est_mwp_cal` | 0.167 | 5,190.2 | 0.651 | Precision-weighted |

Two things are worth taking away, and they point in opposite directions.

**Ranking transfers; level does not.** Every estimator lands at &rho; &asymp; 0.63 to 0.66
while slopes span 0.17 to 0.41. The model puts capacity in the right municipalities and gets
the amount wrong. That is the same pattern as Pakistan's
[external comparison](capacity.md#what-this-map-cannot-tell-you-and-what-an-independent-estimate-confirms-it-can),
now confirmed against a mandatory register rather than owner-attested quadrats.

**No estimator here is close to unbiased.** The best-calibrated recovers about 40% of the
capacity it could see. Read that as the honest accuracy of segmentation-only detection at
10 m GSD, not as a defect introduced by the calibration work below.

## What the register found, twice

The full derivation is in
[Validating against a complete register](../methods/mastr-validation.md). Neither correction
would have been visible without a complete reference.

**1. `p_unmapped` was a zero.** No instrument existed for P(candidate is real | no OSM
match), so Germany's table shipped `0.0` and priced every unmapped candidate at nothing.
MaStR closes that above 30 kWp, where it publishes per-unit coordinates. Measured per
placement and chance-corrected, rooftop `p_unmapped` runs 0.061 to 0.759 across the size
bins. `est_mwp_cal` moved 0.038 &rarr; 0.167.

**2. That fix exposed a second, opposite error.** `est_mwp_rc_roof` jumped from 0.262 to
3.11 &mdash; from understating truth to overstating it threefold. Two errors had been
cancelling, and removing one revealed the other.

The cause was not either hypothesis first written down.
`capacity_calibration.derive_placement_tables` restricted **both** sides of the recall
measurement by placement, so a rooftop reference installation only counted as found if the
candidate that found it was itself classified `rooftop`:

| Rooftop bin | vs same-placement candidates | vs any candidate | factor |
|---|---|---|---|
| 500-1k m&sup2; | 0.128 | 0.167 | 1.3x |
| 1k-5k | 0.214 | 0.268 | 1.25x |
| 5k-50k | 0.096 | 0.693 | 7.3x |
| &gt;50k | 0.036 | 0.852 | **23.9x** |

Precision and recall are asymmetric. `mapped_frac` asks "is this candidate real", so its
corroboration must come from references of its own placement. Recall asks "was this real
installation detected at all", and how `postprocess` labelled the finding candidate is
irrelevant to that. The mechanism explains why the error grew with size: a large array
overruns its imagery-derived VIDA footprint, `building_overlap_frac` collapses, and a
candidate that correctly found a rooftop installation is classified `ground_adjacent` or
`no_building` &mdash; the same undersizing the parcel label exists to handle. `1/recall`
then inflated those candidates by up to the 20x clamp.

Fixing it moved `est_mwp_rc` from 114,145 to **24,687 MWp** nationally and its slope from
3.11 to **0.405**, making it the best-calibrated of the four estimators. `est_mwp_det` and
`est_mwp_exp` did not move at all, which is the sanity check: neither uses recall.

!!! danger "Pakistan shares this code and its published figures are overstated"
    The same restriction understated Pakistani recall: rooftop 0.423 &rarr; 0.808 in the
    5k-50k bin, 0.065 &rarr; 0.952 above 50k, ground 0.107 &rarr; 0.417 in 500-1k. Because
    `1/recall` is the multiplier, Pakistan's `est_mwp_rc` &mdash; and therefore its Best
    estimate &mdash; is **too high**. Its numbers come from the checked-in calibration table
    and do not move until that is deliberately re-derived, which needs the glint sample and
    the calibration boxes. That re-derivation has not been run.

Two hypotheses were written down first and both were measured and **refuted**: that oversize
`rooftop` reference features deflated the top bin (they recall at 0.841, no different from
the rest) and that count-recall applied to area inflated the estimator (the area/count ratio
is 1.01 to 1.08). Recorded because the wrong diagnosis was the plausible one.

## The plausibility gate

`check-density` is the pre-publication gate for failure modes `p_real` weighting cannot
catch. Across the three runs:

| | Original | After `p_unmapped` | After the recall fix |
| --- | --- | --- | --- |
| ok | 19 | 17 | **18** |
| suspect | 1 (Saarland, ground-mount 3.6x rooftop) | 0 | 0 |
| fail | 0 | 3 (Hamburg, Bremen) | **2 (Hamburg)** |

Saarland's flag cleared legitimately: it was flagged because ground-mount read 3.6x its
rooftop total, and rooftop capacity rising is exactly the correction that ratio wanted.
Bremen cleared when recall was fixed. Hamburg's remaining failure is structural rather than
a detection &mdash; a city-state spanning a handful of 0.1&deg; cells has a top cell holding
31% of its total no matter what. That is the same reading this project already applies to
Islamabad Capital Territory, and the same standing precedent for publishing a
checked-genuine plausibility failure. The ground:rooftop ratio check correctly skipped it (it
requires `mwp_ground >= 50`; Hamburg has 7.0), while the concentration check has no
equivalent minimum-region-size guard.

One data quirk visible in the output: `plausibility.csv` carries **20 rows for Germany's 16
states**, with Hamburg, Mecklenburg-Vorpommern, Niedersachsen and Schleswig-Holstein each
appearing twice. That is a duplication in the region polygons, not a duplicated estimate, and
it is why Hamburg counts as two failures.

## What this run opens up

Both remaining items are tracked on [Open questions](../open-questions.md).

**MaStR also records installed pose, uncensored** (item 11). `glint_opportunity.py` documents
its pose prior as necessarily *assumed*, because this project's own pose survey was fitted
from observed glints and is therefore censored by construction. The register carries azimuth
and tilt for 97.4% of 4.44M rooftop units, of which 225,138 also have coordinates. Checked
against the assumed prior it is far too narrow: 23.8% of German units are pitched steeper
than 40&deg; where the prior implies 3.04%.

**France, not Germany, is the place to check the small half** (item 4). The 30 kWp coordinate
cliff means this register can say nothing about the sub-400 m&sup2; population, which is
where `roofclf` operates and where the evidence is still 30 purposive Pakistani quadrats.
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

# Measure p_unmapped from geolocated MaStR units, then feed it to the calibration.
# Without this Germany's table carries p_unmapped = 0.0 and est_mwp_cal is a floor.
pixi run python scripts/mastr_p_unmapped.py --base-rate-cells 150
pixi run earthpv calibrate-candidates --aoi germany \
  --mastr-p-unmapped results/germany_mastr_p_unmapped.csv

pixi run earthpv density --aoi germany --districts --force
pixi run earthpv check-density --aoi germany
pixi run earthpv validate-mastr --aoi germany --solar-path <national OSM solar pull>

# The atlas is no longer written by `density`. A raw rooftopsenti OSM pull has no
# `placement` column, so it is prepared first; omitting the --sub400-* pair selects
# the segmentation-only evidence atlas.
pixi run python scripts/prepare_national_osm_solar.py --aoi germany
pixi run earthpv atlas --aoi germany \
  --osm-solar data/labels/germany_national_osm_solar.parquet
```

The composite window must match the register cutoff (`2025-04-01:2025-09-30` against a
2025-09-30 cutoff); the `compose` default is a Punjab dry season, which is German winter.
See [Setup New Country](../reproduce.md) for the full runbook.
