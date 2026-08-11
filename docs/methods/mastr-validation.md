# Validating against a complete register: Germany and MaStR

Every accuracy figure this project quotes for Pakistan is bounded by the same thing: the
21 calibration quadrats behind it were hand-picked rather than randomly sampled, their
completeness is attested by one mapper rather than independently verified, and that
completeness is relative to the date of the background imagery used for mapping rather
than the date of the Sentinel-2 composite the model actually reads. Those are real limits
and no amount of additional modelling removes them.

Germany is the one place where a different standard is available. Registration in the
**Marktstammdatenregister (MaStR)** is legally mandatory for grid-connected PV, so
per-municipality rooftop capacity there is not a sample to be compared against, it is the
answer. `earthpv validate-mastr` uses it to test the parts of the capacity chain that
nothing else in this project can check.

```bash
earthpv mastr                       # once: download the register (multi-GB, hours)
earthpv validate-mastr --aoi germany \
  --solar-path /path/to/rooftopsenti/data/germany_500/osm/solar.parquet
```

Writes `results/germany_mastr_validation.json`. Everything except the last section runs
in the default (no-torch) environment, needs no GPU, and takes under a minute once the
register is downloaded.

## What is below the detection floor, measured rather than proxied

The reason this project has two detectors instead of one is the claim that the &ge; 400 m&sup2;
segmentation model is blind to most rooftop capacity. Until now that claim was supported
by MaStR's "72.6% of rooftop capacity is in units &le; 100 kWp" &mdash; a round-number
proxy, quoted nationally.

The register carries exact per-unit capacity, so the share below the project's *own* floor
can be measured directly. 400 m&sup2; of module area at 0.18 kWp/m&sup2; is **72 kWp**:

| Unit size | Share of rooftop **capacity** | Share of rooftop **installations** |
|---|---|---|
| &le; 10 kWp | 24.0% | 60.0% |
| &le; 30 kWp | 56.8% | 93.9% |
| **&le; 72 kWp (the 400 m&sup2; floor)** | **65.5%** | **97.2%** |
| &le; 100 kWp | 72.6% | 98.5% |
| &le; 300 kWp | 83.2% | 99.6% |
| &le; 1000 kWp | 96.4% | 100.0% |

Measured 2026-08-11 on 4,411,015 rooftop units totalling 74.8 GWp, commissioning cutoff
2025-09-30. The &le; 100 kWp row reproduces the figure this project already quotes, which
is the check that the filters here match `mastr.aggregate_gemeinden`'s.

Two things to take from this table. First, the claim holds and is now measured at the right
threshold: **65.5%** of German rooftop capacity sits below the segmentation floor, so an
instrument that only sees above it is describing roughly a third of the quantity a "rooftop
solar" headline implies. Second, the capacity and installation columns are very far apart
&mdash; 97.2% of installations against 65.5% of capacity &mdash; and quoting the count share
when the reader will hear the capacity share overstates the gap substantially. Both belong
in any statement of this result.

## The same share is not transferable as one number

This project transfers Germany's share to Pakistan as a constant, to sanity-check its own
sub-400 m&sup2; total (`docs/methods/density.md`'s MaStR-shape transfer, which implied
roughly 5.9 GWp). A transfer like that is only as good as the constancy of the thing being
transferred, and measured across 10,675 German municipalities with at least 100 kW of
rooftop capacity, it is not constant:

| | Share below 72 kWp | Share below 100 kWp |
|---|---|---|
| National (capacity-weighted) | 0.655 | 0.726 |
| Unweighted mean over municipalities | 0.724 | 0.785 |
| Median municipality | 0.762 | 0.845 |
| 5th &ndash; 95th percentile | 0.249 &ndash; 1.000 | 0.295 &ndash; 1.000 |
| Standard deviation | 0.235 | 0.228 |
| Spearman vs. municipality capacity | **-0.42** | **-0.47** |

The negative rank correlation is the part that matters, because it is a bias with a known
direction rather than just noise. Rooftop capacity concentrates in municipalities with
large industrial roofs, and those have a *lower* small-PV share than a typical
municipality. So the unweighted average across municipalities (0.724) sits 7 points above
the national capacity-weighted figure (0.655), and any transfer that reasons from "a
typical place" rather than from a capacity-weighted total will overstate the small-PV
share. The 5th-to-95th spread of 0.25 to 1.00 sets the wider caution: this is a quantity
that varies by a factor of about 2.7 between the 10th and 90th percentile municipality
within a single country, so carrying it across a border as a point value is a much weaker
step than the tidy national percentage makes it look.

## OpenStreetMap cannot serve as the complete reference, even in Germany

A natural plan is to skip the register and use German OSM as ground truth, since Germany
is famously well mapped. Measured against MaStR, that plan does not survive.

The measurement has to avoid one specific circularity. `data/calibration/completeness.parquet`
defines completeness as `0.18 x osm_area / kw_rooftop`, which already assumes the very
kWp/m&sup2; constant one might want to test; selecting "well-mapped" municipalities with it
and then measuring `kw_rooftop / osm_area` is selecting on the estimator. So
`osm_completeness_by_count` measures completeness by **unit count** against the register
instead, which involves no area and no conversion constant at all.

National result: of 4,411,015 registered rooftop units, OSM has **3.6%**. The well-mapped
tail is thin, and the implied constant is unstable across it:

| Minimum count completeness | Municipalities | Pooled implied kWp/m&sup2; |
|---|---|---|
| &ge; 30% | 55 | 0.239 |
| &ge; 50% | 18 | 0.083 |
| &ge; 80% | 3 | 0.069 |

Per-municipality implied values span 0.02 to 0.99 against the project's 0.18. A spread
like that is not sampling noise around a true value: nothing in OSM records whether a
`generator:source=solar` polygon outlines the panel array or the whole roof it sits on, so
the ratio is measuring mapper convention. **The module constant therefore stays as
calibrated, and this route is recorded as a measured negative result rather than a
blocked one.**

Two consequences travel beyond Germany. "Germany is well mapped in OSM" is true of
buildings and false of rooftop PV, and the two are easy to conflate. And the same
array-versus-roof ambiguity applies to this project's Pakistani OSM reference, which is
used both as a recall denominator and as the Verified tier's own population &mdash; it is
not exempt.

## The end-to-end comparison, and what still blocks it

`validate_density_against_mastr` zonal-joins a `density` run's grid onto German
municipalities and reports, per estimator, the origin-forced OLS slope (multiplicative
bias, 1.0 = right on average), the median per-municipality ratio, Spearman rank
correlation and log-log Pearson. Because MaStR is complete, a slope against it is a real
accuracy statement rather than a comparison of two estimates &mdash; which is exactly what
Pakistan cannot provide.

It reports its own imagery coverage and refuses to describe a partial-coverage result as
national. That guard is not hypothetical: a run covering 4 of Germany's 76 MGRS tiles
would produce a national sum around 5% of the truth, and the resulting slope would read as
a catastrophic model failure rather than as missing imagery.

**As of 2026-08-11 this section cannot run**, and the blockers are data acquisition rather
than missing code:

1. **Imagery.** `data/composites/germany/` does not exist. The sibling `rooftopsenti`
   project has composites for **14 of the 76 MGRS tiles** Germany's bbox needs, and the
   existing `data/predictions/germany/prob/` holds 4 tiles, written per-MGRS-tile rather
   than in the per-0.1&deg;-cell layout `density` reads. Closing this means
   `earthpv compose --aoi germany` followed by `infer`, both resumable and network-bound.
2. **A building layer with small roofs.** `roofclf` scores per building and needs the
   sub-400 m&sup2; population. Germany has only the Overture &ge; 500 m&sup2; set here
   (1.6M rows); `data/vida/DEU.parquet` is absent.
3. **Mapped quadrats.** All 21 calibration quadrats are Pakistani, and `roofclf` cannot be
   fit without exhaustively mapped ground where a no-PV building is a real negative. The
   3.6% OSM completeness measured above means German quadrats have to be *mapped*, not
   derived from an OSM pull &mdash; the same cost as the Pakistani ones.

Until then, `validate-mastr` reports `density_vs_mastr: {status: absent}` and the three
register-internal sections above stand on their own, since none of them need imagery.

Because the harness cannot be exercised against real data yet, it is covered by
`tests/test_mastr_validation.py`, which feeds the register back through it synthetically:
a grid carrying exactly MaStR's own capacity must return slope 1.0, one carrying half of it
must return 0.5, and a 200-municipality grid must be refused as non-national. That pins the
arithmetic &mdash; units, the origin-forced fit, the kW-to-MWp conversion, the coverage
guard &mdash; rather than merely running the code.
