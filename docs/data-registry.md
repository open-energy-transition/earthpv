# Country data registry

Extending earthpv to a new country starts with a question this page answers: **what does this
country already publish?** Ninety-one datasets across fifty-one countries are catalogued here, and
most countries have something, even where OpenStreetMap is nearly empty.

<div class="page-full-bleed" markdown>
<iframe src="../assets/interactive/training_data_registry.html" title="Filterable registry of PV labels, registers and roof-context datasets by country"></iframe>
</div>

The table above is filterable by country, continent and role. The same data is in
[`earthpv_training_data_registry.csv`](assets/registry/earthpv_training_data_registry.csv), which
ships with the repository, and on the command line:

```bash
earthpv data-sources --country kenya
earthpv data-sources --continent Africa --role train_positives
earthpv data-sources --role calibration_only --min-priority A --urls
```

## The one distinction that matters

A dataset being about solar does not make it a training label. The registry records what each
source **is**; earthpv tags each row with what you can actually **do** with it, derived from
two columns: whether PV presence is confirmed, and whether the records carry geometry.

| Role | What it is | What it is for |
| --- | --- | --- |
| **Train on it** | Confirmed PV, with geometry | Gold or Silver labels for `labels` and `chips` |
| **Roof context** | Buildings or roof potential, no PV label | The roof universe, and reliable negatives |
| **Bronze only** | Model-derived detections | Active-learning pools, never validation |
| **Calibrate only** | Counts or capacity by area, no geometry | Per-region calibration, adoption priors |
| **Ask first** | Register exists, export restricted | A partnership lead, not a download |

Three ways to misread this table, all of which have cost real work somewhere:

**Roof potential is not installed PV.** A rooftop-potential layer says how much capacity a roof
*could* host. Training on it teaches a model to find large roofs, which is the failure mode
[Germany's calibration](results/germany.md) ran into from the opposite direction.

**Aggregate statistics cannot be training labels.** A district-level count has no geometry.
It is genuinely valuable for calibration, which is exactly how
[MaStR](methods/mastr-validation.md) and the [French register](methods/france-validation.md)
are used, but it cannot supervise a per-building model.

**Agreement with a model-derived inventory is not validation.** Those datasets carry their own
error rate. OpenPVMapper is ~74-75% precise and earthpv agreeing with it proves nothing; it was
used [as a control, not as truth](results/france.md).

## Using a source to train

Datasets tagged **Train on it** carry PV geometry. The path into the pipeline:

```bash
# 1. Add the AOI, which must carry division.iso3
python scripts/new_region.py check --iso3 KEN --name kenya
python scripts/new_region.py add   --iso3 KEN --name kenya

# 2. Point the label stage at the downloaded geometry, then build chips and train
earthpv labels --aoi kenya
earthpv chips  --aoi kenya
.pixi/envs/ml/bin/python -m earthpv.cli train --config configs/terramind_pv.yaml
```

Two things decide whether this is worth doing at all, and both are measurable before you
train. **Array size relative to a Sentinel-2 pixel** is the binding constraint on the
sub-400 m&sup2; half: see
[where the spectral detector stops working](how-it-works.md#where-the-spectral-detector-stops-working).
And **point records are Silver, not Gold** -- match them to building footprints and verify a
sample against imagery before treating them as labels, because an address point is not an
array outline.

## Using a source to validate

Datasets tagged **Calibrate only** have no geometry and are the more common case. They are
what the two register validations in this project are built on, and the pattern transfers:
aggregate earthpv's own output to the same administrative unit, then compare.

```bash
earthpv density --aoi <aoi> --districts
earthpv check-density --aoi <aoi>
```

`validate-mastr` and `validate-france` are worked examples of that comparison, including the
parts that go wrong. The most transferable lesson from both:
**a national total agreeing with a register is not evidence the geography is right.** Germany's
cross-validated national total landed at 1.003 while the median municipality was off by 53%,
because over-prediction of the largest places cancelled under-prediction of everywhere else.
Compare per region, and report the per-region error.

## Licences

The `license_or_access` column is recorded per dataset and is not uniform: ODbL with
share-alike, CC BY-SA, research-only, and several registers whose reuse terms are not stated.
Check it before redistributing anything derived from a source, and note that
"publicly visible on a government page" is not the same as "openly licensed".
