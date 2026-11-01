---
title: "EarthPV: quality levels"
---

# Quality levels: Gold, Silver and Bronze

Every country atlas carries a calibration badge in its corner: **Gold**, **Silver** or **Bronze**. It says how far the atlas's figures have been checked, against installations mapped by hand and by people looking at what the model found, not how much solar a country has. The levels add up: Silver needs everything Bronze asks for, and Gold everything Silver asks for. A country shows the highest level whose every criterion it meets.

## Bronze: every published atlas

| Criterion | What it means | Where it is set |
| --- | --- | --- |
| **Model trained on the country's own map** | The segmentation model is fine-tuned on the country's own OpenStreetMap solar, and the shipped checkpoint is whichever of that local model and a general one finds more mapped installations in a held-out region chosen before training; a tie goes to the local model. Zambia, run before this rule, uses a general model. | `scripts/pick_val_region.py`, `scripts/compare_local_vs_v5.py` |
| **Imagery over every populated cell** | A dry-season Sentinel-2 composite over every 0.1&deg; cell with at least 1,000 buildings, plus every cell holding mapped solar. Cells nobody imaged are hatched on the map, so bare land means imaged with nothing found. | `earthpv compose` |
| **Hand-mapped solar counted once** | <em>Verified</em> is OpenStreetMap's own solar, clipped to the border and dissolved so a plant outline and the panels mapped inside it count once. | `scripts/prepare_national_osm_solar.py` |
| **Model outlines priced by measured precision** | <em>Best</em> adds the model's outlines of about 400 m&sup2; and up, each weighted by the share of outlines of its size and placement that turned out to be real. Without a local recall reference this is a floor. | `configs/calibration/<aoi>_candidate_precision.yaml` |
| **Plausibility gate** | Before publication each region's ground-mount to rooftop ratio and its single-cell concentration are checked; a failure is looked at and stated on the page. | `earthpv check-density` |
| **Mapping leads published** | The model's outlines more than 100 m from any solar installation in OpenStreetMap, most promising first. Leads under 1,000 m&sup2; on ground steeper than 15&deg; are left out (shaded slopes and cliff edges read like panels); larger ones on steep ground stay, marked <code>steep_review</code>, because a solar farm can stand on a mountainside. France's audited lead release predates this rule. | `scripts/release_leads.py` |

## Silver: Bronze, plus local ground truth and checked leads

| Criterion | What it means | Where it is set |
| --- | --- | --- |
| **Local ground truth** | The model's precision table is fitted against the country's own mapped installations as a recall reference, or the country has calibration areas in use where every visible panel is mapped (Rule 1). | `atlas.derive_validation_score` |
| **Every mapping lead checked** | A person has looked at every lead in the country's current lead file on recent high-resolution imagery and mapped the real installations. The record names the lead file it covers, so a rebuilt file starts unchecked. Until the check is recorded the atlas shows Bronze, whatever its calibration earns. | `validation.leads_checked` in `configs/atlas/<aoi>.yaml` |

## Gold: Silver, plus installations below 400 m&sup2;

| Criterion | What it means | Where it is set |
| --- | --- | --- |
| **Installations below 400 m&sup2; calibrated** | An estimate below the 400 m&sup2; floor, where 10 m pixels cannot outline an array: the rooftop classifier priced by a coverage ratio fitted on calibration areas mapped panel by panel, its interval from resampling those areas, or a legally complete national register. | `roofclf`, `sub400_capacity.py` |
| **The small-installation estimate holds up** | That estimate survives the check against its own ground truth: leaving each mapped area out in turn, or the register's municipal totals. | owner judgement, `validation.score` |

## When a lead counts as checked

A lead is checked when a person has looked at it on recent high-resolution imagery and either mapped the installation in OpenStreetMap or judged it not solar. Rooftop leads in towns and leads beside roads deserve the same look as the rest: dark asphalt junctions and shadows are the model's commonest false alarms. Leads marked <code>steep_review</code> need a look at the terrain as well. The [lead mapping guide](contribute/leads.md) walks through a lead file in JOSM. When every lead in a country's current file has a verdict, a maintainer records it as `validation.leads_checked` in the country's configuration, naming the file by its date; the badge then shows the level the calibration earns.

## Where each country stands

| Country | Shows | Calibration earns | Below 400 m&sup2; | Leads checked | Missing for the next level |
| --- | --- | --- | --- | --- | --- |
| [Pakistan](atlas.md) | Gold | Gold | rooftop | yes, 2026-10-31 | - |
| [Germany](atlas-germany.md) | Bronze | Silver | rooftop (register-calibrated, not validated) | no (17,575 leads) | Check every lead (17,575); then: a small-installation estimate that passes the register check |
| [France](atlas-france.md) | Bronze | Silver | not measured | no (28,734 leads) | Check every lead (28,734); then: a calibrated estimate below 400 m&sup2; |
| [Egypt](atlas-egypt.md) | Bronze | Bronze | not measured | no (1,148 leads) | Local ground truth: map a calibration area; check every lead |
| [India](atlas-india.md) | Bronze | Bronze | not measured | no (95,313 leads) | Local ground truth: map a calibration area; check every lead |
| [Morocco](atlas-morocco.md) | Bronze | Bronze | not measured | no (664 leads) | Local ground truth: map a calibration area; check every lead |
| [Namibia](atlas-namibia.md) | Bronze | Bronze | not measured | no (842 leads) | Local ground truth: map a calibration area; check every lead |
| [Nigeria](atlas-nigeria.md) | Bronze | Bronze | not measured | no (4,821 leads) | Local ground truth: map a calibration area; check every lead |
| [Poland](atlas-poland.md) | Bronze | Bronze | not measured | no (5,706 leads) | Local ground truth: map a calibration area; check every lead |
| [South Africa](atlas-south-africa.md) | Bronze | Bronze | not measured | no (8,031 leads) | Local ground truth: map a calibration area; check every lead |
| [Vietnam](atlas-vietnam.md) | Bronze | Bronze | not measured | no (4,910 leads) | Local ground truth: map a calibration area; check every lead |
| [Yemen](atlas-yemen.md) | Bronze | Silver | farm ground | no (1,933 leads) | Check every lead (1,933); then: household rooftops below 400 m&sup2; calibrated on mapped building areas |
| [Zambia](atlas-zambia.md) | Bronze | Bronze | not measured | no (651 leads) | Local ground truth: map a calibration area; check every lead |

The table is read from each atlas's own badge and data, and from the lead files' records, so it changes when they do.

## Judgements

The level is derived from what each atlas has on disk. Where the evidence is of a different kind, the owner's decision is recorded in the country's configuration (`validation.score`) and wins over the derived level; the lead check still applies on top.

- **Germany**: Silver, not Gold (2026-10-22): its small-installation half is calibrated on the register, but misses the register's municipal totals by about half.
- **Yemen**: Silver (2026-10-23): its farm areas calibrate small solar-irrigation arrays only; household rooftops below 400 m&sup2; are not estimated.
- **Egypt**: Bronze (2026-10-29): its one registered area, a farm area with no solar, is not used by the figures.
- **India**: Bronze (2026-10-28): its two registered areas are not used by the figures, so nothing on the page is fitted on local ground truth.

Code: `atlas.derive_validation_score` (the derived level), `atlas.resolve_validation_badge` and `atlas.leads_checked` (the lead check); this page is written by `scripts/build_atlas_pages.py`.
