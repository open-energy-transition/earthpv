# Country data registry

Extending earthpv to a new country starts with a question this page answers: **what does this
country already publish?** A hundred and four datasets across fifty-six countries are catalogued here, and
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

Four ways to misread this table, all of which have cost real work somewhere:

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

**A list of installations is not a calibration area.** `roofclf`'s coverage ratio and area
recall are fitted on a BOUNDED area where the absence of PV is known, which is what a Rule-1
quadrat or a mandatory register provides. Positives alone give a numerator with no
denominator. Checked across Africa on 2026-09-19 and none of the candidates clears it:
**Senegal's registry** is the best-licensed African source (CC BY 4.0, geolocated, an API)
and still cannot calibrate, because its 478 records are all self-*declared* with none
verified, 379 of them agricultural pumping at a 5.0 kWc median, and the densest 0.1 degree
cell holds 12 installations. **Uganda's ProREU Lango mapping** is the one African source
that publishes PV-free buildings alongside PV-bearing ones, which is exactly the missing
denominator, and it exists only as PDF maps. **Cape Town's Smart Facilities Solar** is
properly machine-readable but is 839 monthly rows over 23 council buildings. The route to an
African calibration area is therefore to draw and map one with
`scripts/new_calibration_quadrat.py`, gated on imagery date rather than mapping effort, not
to find a dataset.

## What the 2026-09-20 screening pass changed

Twenty-seven candidate sources were screened against what they actually publish. Thirteen
were added. The other fourteen are worth recording, because the two reasons they did not
make it are the reasons most candidate sources do not.

**Nine were already here under their authoritative name.** Brazil's ANEEL distributed
register, Australia's Clean Energy Regulator small-scale postcode data, Japan's FIT/FIP
project disclosure, Korea's national solar permit standard data, the Dutch PIR/VertiCer
registers, Denmark's BBR installation flags, Switzerland's plant register (which is the
Pronovo-sourced file), India's PM Surya Ghar portal and the APVI solar map, which is a
presentation layer over the Clean Energy Regulator data rather than a separate source. A
candidate list assembled from programme names will collide with a registry indexed by
publisher; check the publisher, not the programme.

**Five lost their coordinates on inspection**, and that is the more useful failure. Every one
of them was recorded in the candidate list as carrying coordinates, and in each case the
register holds them internally but does not publish them:

| Source | Claimed | Published |
| --- | --- | --- |
| CaliforniaDGStats NEM / Rule 21 | Coordinates, "very high" | ZIP code, for customer privacy |
| Austria E-Control Anlagenregister | Coordinates | Locality and postcode |
| Japan FIT/FIP disclosure | Coordinates | Municipality |
| Massachusetts SMART / PTS | Coordinates | Town |
| Spain PRETOR | Coordinates | No record-level export located |

This is the [30 kWp coordinate cliff](methods/mastr-validation.md) again, and it is not a
German quirk. A register that geolocates its own records for administration will usually
suppress that field on publication once the records are small enough to identify a household.
**Assume a distributed-generation register publishes an administrative area, not a point,
until its schema says otherwise** -- which also means the cliff sits exactly where `roofclf`
needs help and exactly where segmentation does not.

Two additions are worth singling out, both because of a column rather than a country. The UK
[REPD](https://www.gov.uk/government/publications/renewable-energy-planning-database-quarterly-extract)
publishes **site area** alongside capacity for operational solar, and
`DEFAULT_KWP_PER_M2_LAND` currently rests on two Pakistani plants, so the land constant can be
re-derived on a real sample. [EIA Form 860](https://www.eia.gov/electricity/data/eia860/)
publishes per-generator **tilt, azimuth and mount technology**, which is the panel pose
[glint](methods/glint.md) needs and which MaStR was previously the only register here known to
carry.

## Known gaps

Ranked by what they would unblock, not by market size.

**A third sub-400 m&sup2; regime.** `roofclf` works in Pakistan and
[does not transfer to France](results/france.md), where the median mapped array is 20 m&sup2;
against a 100 m&sup2; pixel. Two points do not make a rule. Australia's typical residential
array is French-sized and Brazil's MMGD population is closer to Pakistan's, and both countries
have registers already listed here, so either one turns that bound into a threshold.

**Italy.** Atlaimpianti has about 790,000 georeferenced units and is the largest European
population missing from this project. It is listed as access dependent rather than open
because its reuse terms were not established; reading the published terms-of-use document is
the whole unblock.

**Spain and Chile.** Spain has a national register with no open record-level export, so it is
a partnership lead. Chile publishes plant data through the Coordinador Electrico Nacional's
Infotecnica platform and pairs large ground-mount with near-permanent clear sky, which is the
easiest imagery regime available anywhere and therefore the cleanest possible test of the
ground-mount half. Neither has been verified in depth.

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
