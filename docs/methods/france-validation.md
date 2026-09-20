# Validation against France's national register

**Status: shipped, 2026-09-04.** The register-only blocks are final. The earthpv-versus-register
comparison is pending Sentinel-2 coverage and is marked as such in the report itself.

This is the France counterpart to [validation against MaStR](mastr-validation.md), and the
two registers are different enough instruments that a shared module would have hidden more
than it saved. `src/earthpv/france_validation.py` implements it; `earthpv validate-france`
runs it.

## What the French register is

[ODRE](https://odre.opendatasoft.com)'s *registre national des installations de production
et de stockage d'electricite* covers every network operator in France, transmission and
distribution, including the local distributors (ELD) that serve five of the fourteen
hand-mapped communes. It is legally mandated and complete.

It differs from MaStR in four ways that drive every design choice here.

**It censors below 36 kW.** Installations under that threshold are published only as
per-commune or per-IRIS aggregates carrying a unit count and a total capacity. Individual
sizes below the cliff do not exist in the data. `load_register` therefore separates
aggregate rows from individual ones and never pools them: an aggregate row's
`puismaxinstallee` is a SUM over hundreds of censored units and is routinely several
hundred kW, so treating it as a unit size silently reclassifies a village's worth of 5 kW
roofs as one industrial plant.

**The floor share survives the censoring anyway.** The cliff (36 kW) sits below the
detection floor (72 kWp = 400 m&sup2; at 0.18 kWp/m&sup2;), so capacity below the floor is
exactly "all aggregate capacity plus individual units at or below 72 kW", with nothing
interpolated. Shares below 36 kW are genuinely unrecoverable and `size_regime_shares`
returns them as `None` rather than modelling them.

**There are no coordinates, at any size.** Germany's `p_unmapped` precision instrument
tests whether a registered unit's address point falls inside an unmapped candidate polygon.
France offers no counterpart and this module does not invent a substitute.

**There is no rooftop/ground attribute.** Germany's headline is a share of *rooftop*
capacity. France has no rooftop denominator, so every share is bracketed:

- `all_pv`, every registered installation, a firm lower bound on the rooftop share because
  ground-mount is essentially all above the floor.
- `bt_only`, low-voltage connections, a rooftop-leaning upper bound because utility-scale
  farms connect at HTA or above. Large BT-connected ground arrays keep it from being exact.

Neither is presented as "the" French number, and the Germany figure is carried alongside so
the two are not confused.

## What the French register adds: dated vintages

ODRE publishes year-end snapshots of the same register from 2017 onward. This project pulls
2020 through 2025 (`scripts/fetch_odre_vintages.sh`), which trace a clean national growth
curve from 9.3 GWp to 30.4 GWp.

`interpolate_to_date` reads per-commune small-PV capacity back to an arbitrary date by
linear interpolation between the two straddling year-ends. This exists because the
aggregate rows carry one group-level commissioning date covering hundreds of units, so a
registered small installation cannot be dated individually and the current snapshot cannot
be filtered to a past epoch. The vintages can.

**The export endpoint returns truncated CSVs on an SSL reset without an error.** One
2021 pull came back at 5.4 GWp against the true 13.4 and would have read as a year in which
French PV barely existed. `fetch_odre_vintages.sh` re-fetches until the line count is
plausible, and `load_vintages` refuses any vintage under 1 GWp outright rather than
flattening the growth curve it exists to measure.

## The hand-mapped communes

Fourteen communes were swept exhaustively on sub-metre IGN aerial imagery.
`scripts/build_france_quadrats.py` turns them into EarthPV calibration quadrats.

**The `tag` field is load-bearing.** 381 of 3,335 features are `thermal`, solar hot-water
collectors that look like PV to both a mapper and a 10 m multispectral sensor and generate
no electricity. Booking them as PV would inflate every capacity number downstream. `false`
(12) is a mapper-retracted feature. Both are dropped. `unknown` (84) and `missing` (181)
are genuinely ambiguous: tested against OpenPVMapper overlap, `missing` sits at 48.6%
against 66.6% for `normal` and 29.4% for `thermal`, so it is neither cleanly "the model
missed it" nor cleanly "not PV". Both tags are excluded from the primary label set and
written to a parallel sensitivity directory instead, so the wider definition can be
measured without either silently becoming ground truth. It moves the module constant from
0.150 to 0.147, which is to say it does not matter.

**The quadrat boundary is the commune.** `metadata.json` records a `surface` per commune
matching the official INSEE area, so the mapper's unit of work was the whole commune.
Mapping does spill past the commune edge, up to 23% of features in one case, so features
are clipped to the contour: what is certified complete is the inside, and every
area-normalised quantity uses the same denominator the labels do.

**The epoch comes from the labels, not a side file.** `mapping_date` is the median
`imageDate` across a commune's own features rather than `metadata.json`'s single date. Two
communes have no metadata entry at all and a couple were mapped across two flights.

**Placement comes from VIDA footprint overlap**, matching how `postprocess` classifies its
own candidates, so `parcel_pv_area`'s ground/overhang rule sees the same distinction it does
in Pakistan.

Saint-Gely-du-Fesc is marked unfinished by the mapper. It is built as a quadrat but
excluded from every calibration fit, and `scripts/run_france_pipeline.sh` passes explicit
`--quadrat` flags rather than letting `discover_quadrats` glob it back in.

**France quadrats live in `data/labels/france/`, not `data/labels/`.**
`roofclf.discover_quadrats` globs the latter, so a French quadrat placed there would join
the next Pakistani refit without anyone noticing. This is the same footgun recorded for
Kalat Rural in the calibration-box log, and the directory split is the fix.

## A quadrat the size of a commune

Pakistani quadrats are drawn boxes of 1 to 4 km&sup2;. French communes are 4.8 to 32.2
km&sup2;, and that size difference has one concrete consequence in `roofclf`.

The spectral features are read with a proper windowed read across whatever 0.1 degree cells
a boundary spans, so they are unaffected. The **segmentation-probability features**
(`seg_mean`, `seg_max`) are not: `building_table` looks up a single raster, the cell
containing the boundary's representative point, and zero-fills the rest, warning as it does
so. Seven of the fourteen communes straddle two to four cells.

France therefore runs `roof-classifier` **without** `--seg-prob-dir`. A feature that is
correct in some quadrats and partly zero in others is worse than one that is absent
everywhere, because the model would learn the zero-fill pattern rather than the signal.
Little is lost: the modal mapped French installation is 20 m&sup2;, a fifth of one
Sentinel-2 pixel, which is exactly the regime where segmentation carries almost no
information and `roofclf` exists.

**The density-calibration domain is a per-AOI quantity, not a method constant.**
`density.CALIBRATED_BLDG_DENSITY_KM2` is Pakistan's (48.5 to 5,258 bldg/km&sup2;), fit from
Pakistani quadrats. France's communes run 17.5 (Notre-Dame-de-Londres) to 390.8
(Saint-Genis-Laval), an order of magnitude below Pakistan's dense end.
`density.calibrated_density_range(aoi)` selects per AOI and warns loudly when an AOI has no
entry rather than silently borrowing another country's domain.

Only `density.py` reads it that way so far. `sub400_capacity.py` and `growth.py` still take
the module constant directly, so the roofclf capacity chain would apply Pakistan's band to
France. That chain has not been run for France, so nothing published is affected, but it has
to be threaded through before the first French `sub400-capacity` run.

## Measuring the module constant

`module_constant_from_mapped` divides registered capacity by hand-mapped module area. Three
matching rules make the two populations the same population:

1. **Size.** Only mapped installations under 200 m&sup2; count, against the register's
   small-aggregate band alone. 200 m&sup2; is 36 kW at 0.18 kWp/m&sup2;, the module-area
   equivalent of the censoring cliff. Above it the register lists units individually and the
   mapped set stops being complete for them.
2. **Epoch.** The register is interpolated back to the commune's own mapping date. Skipping
   this reads 0.230 kWp/m&sup2; against 0.150, a 53% inflation that is entirely the PV France
   installed between the flight and today.
3. **Technology.** Solar thermal is already gone, by tag.

Communes whose register reports no sub-36 kW capacity at their mapping epoch despite mapped
installations are excluded with the reason recorded: that is a hole in the reference, not a
commune without PV, and booking it as zero capacity over real mapped area would drag the
pooled constant down with a coverage gap.

The result stays bounded in both directions and neither bound is removable. Mapping misses
arrays under tree cover or shadow, pushing the ratio up. The register's small band contains
units the mapper saw no trace of on an older flight, also pushing it up. What it bounds
tightly is whether 0.18 is the right order of magnitude, and it is.

## OpenPVMapper

[OpenPVMapper](https://doi.org/10.5281/zenodo.21534856) is scored against the register
before being used as a reference for anything, so that a later EarthPV comparison can be
read knowing which way the reference leans.

`load_openpvmapper` derives `n_sources` from the `sources` field, because the dataset's own
validation puts single-source precision at 71.5% against 96.9% for two sources and 98.2%
for three. `openpvmapper_by_commune` carries a sub-72 kWp rollup so the below-floor
comparison cuts both sides at the same place; without that the ratio mostly reports that
OpenPVMapper also mapped the large roofs.

`mapped_vs_openpvmapper` splits non-matching polygons into `on_thermal`, `on_retracted` and
`unexplained`. A raw false-positive count would be both unfair and uninformative, since
landing on a solar-thermal collector is the most interesting failure mode in the dataset and
is invisible to any validation that does not carry the tag.

**The mapped communes are OpenPVMapper's own manual-correction layer.** Its rows there have
been corrected toward this ground truth, so precision measured inside them is an optimistic
bound. Recall is the transferable half, and the module reports the caveat in its own output
rather than only here.

## The detection floor, measured from outside

The 400 m&sup2; floor has always been argued from the sensor, 400 m&sup2; being four
Sentinel-2 pixels, and checked against Pakistani quadrats that are themselves labelled off
the same class of imagery. France can do better, because the fourteen communes were swept
on sub-metre IGN orthophotos. An installation present in that truth set and absent from
EarthPV is a real miss rather than an annotation gap, so `mapped_vs_earthpv`
(`earthpv validate-france --pred-dir ...`) measures recall per installation size against
it.

**Recall is the measurable half, and precision is deliberately not reported.** Four of the
fourteen communes were mapped one to three years before the 2024 composite window, so an
unmatched candidate may be a genuinely newer installation rather than a false positive.
That biases precision and leaves recall alone: PV on a roof in 2021 is still there in 2024,
so every mapped installation is a fair thing to require a detector to find. It is the same
precision/recall asymmetry that `derive_placement_tables` was corrected for in September
2026.

**OpenPVMapper is the control that makes the number readable.** It reads the same
installations, inside the same boundaries, from sub-metre imagery. If small installations
were simply drawn less reliably by the mappers, it would show the same gradient EarthPV
does. It does not.

| Installation size | n | EarthPV recall | OpenPVMapper recall |
| --- | --- | --- | --- |
| 0 to 20 m&sup2; | 1,397 | 0.000 | 0.601 |
| 20 to 50 m&sup2; | 873 | 0.010 | 0.797 |
| 50 to 100 m&sup2; | 112 | 0.045 | 0.589 |
| 100 to 200 m&sup2; | 112 | 0.062 | 0.589 |
| 200 to 400 m&sup2; | 84 | 0.095 | 0.583 |
| 400 m&sup2; and above | 44 | 0.045 | 0.750 |

Spearman of recall against size bin is **+0.83 (p = 0.042)** for EarthPV and
**-0.29 (p = 0.58)** for OpenPVMapper. The gradient is the sensor, not the annotator, which
is exactly the control this dataset was brought in to provide.

**Retraining on French data does not move it.** Three independently trained models,
spanning zero to 17,059 French training chips, return the same answer:

| Model | French training chips | Pooled count recall | Gradient (rho) |
| --- | --- | --- | --- |
| v4 zero-shot | 0 | 0.0118 | +0.89 (p = 0.019) |
| v6 France capped | 3,201 | 0.0103 | +0.89 (p = 0.019) |
| v5 full France | 17,059 | 0.0118 | +0.83 (p = 0.042) |
| OpenPVMapper control | n/a, sub-metre | 0.67 | -0.29 (p = 0.58) |

v5 tripled the national candidate count and cut median candidate area from 8,301 to
1,400 m&sup2; without moving recall on small French PV at all. A limit that survives
retraining on in-domain data, while the same installations stay recoverable at sub-metre
resolution, is physical.

Pooled over all 2,622 mapped installations the count recall is **0.0118**
(95% Wilson 0.0083 to 0.0167) and area recall **0.044**. Only 28 candidates fall inside the
fourteen communes at all, against 39,462 nationally, and the median distance from a
400 m&sup2;-plus mapped installation to the nearest candidate is 807 m.

**Two things this measurement does not establish.** The 400 m&sup2;-plus bin holds 44
installations and its recall of 0.045 carries a 95% Wilson interval of 0.013 to 0.151, so it
is far too thin to be read as "EarthPV fails above its own floor". These communes were
chosen to be exhaustively mappable for the module constant, not to contain large arrays, and
a residential commune is close to the worst case for a 10 m detector. The transferable
finding is the gradient and its contrast with the control, not the level in any one bin. The
result also bounds the sensor, not the method: it says nothing about Pakistan, where arrays
are small relative to the 400 m&sup2; floor but still large relative to a pixel.

## Running a country-scale compose

**Put the composites on the roomy filesystem first.** A country is roughly 10 MB per cell,
so France is about 55 GB. `data/composites/germany` and `data/composites/pakistan` are
symlinks to `/home/tobi/earthpv_composites/<aoi>`; France was initially created as a real
directory on the 229 GB external drive and filled it to 100% at 2,789 of 5,471 cells, which
put the whole project's data volume at risk, not just this run. The symptom does not mention
the disk: `compose` exits with Python code 120, a failure to flush stdout, and the log
truncates mid-word. No committed cell is lost when this happens, because each is written to
a `.tif.tmp` and atomically renamed, so recovery is to move the directory, symlink it back
and resume.


France's national compose is the first in this project large enough to expose a
file-descriptor leak in `compose`. The process dies with
`OSError(24, 'Too many open files')` after roughly 150 to 300 cells, on a 524,288 FD limit,
surfacing through whichever remote call comes next so the traceback varies between a raster
write and the STAC client.

Two things disguise it. A Planetary Computer SAS token expires about 24 hours after it is
signed, and a run crossing that boundary gets a 403 storm that accelerates the leak, which
makes the token look like the cause; it is not, because the leak recurs on a fresh token.
And the 403s look like they should corrupt the output, which they do not:
`annual_composite` fails over to Earth Search, and all 224 cells from the first France run
passed a fill-fraction and reflectance check, including the 85 written after expiry.

The fix is to re-invoke a resumable stage rather than to chase the leak, but **the pass
has to be cut on a timer, not on a crash.** Restarting only when the process exits non-zero
was tried and is not enough: well before it dies, the process degrades, and a degraded pass
is indistinguishable from a healthy one unless you read the rate. France's third pass
decayed from 58 to 172 to 256 seconds per cell with resident memory past 8 GB, delivering
0.17 cells per minute against a healthy 0.74, and it never crashed, so the loop never
restarted it and roughly four hours went at a quarter speed. Killing it and starting a fresh
process restored 0.80 cells per minute immediately.

`scripts/run_france_national_compose.sh` therefore wraps each pass in `timeout 7200` and
treats the resulting exit code 124 as the expected path, not an error. Each pass gets a
fresh file-descriptor table, fresh memory and a newly signed token. The stop condition is
"a pass added no new cells", which means either finished or genuinely broken; the pass cap
is just a backstop.

## Results

See [France results](../results/france.md).
