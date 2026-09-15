# Zambia: what a country with no ground truth at all looks like

Zambia was run end to end between 13 and 15 September 2026, from an empty start: no locally
cached imagery, no building data, no calibration quadrats, no national register, and no
third-party PV dataset to check against. It is the cleanest test so far of what this
pipeline produces when nothing but the global open sources exist.

Interactive: [Zambia PV evidence atlas](../atlas-zambia.md).

## Headline

| | |
| --- | --- |
| Verified | **505.8 MWp** (90% 376 to 698) |
| Best estimate | **526.3 MWp** (90% 451 to 699) |
| Grid | 1,843 cells of 0.1&deg;, all 10 provinces |
| Imagery | Sentinel-2 L2A, May to October 2025 |
| Model | `v4_combined_all` epoch 41, zero-shot |

!!! warning "A precision floor, not an estimate"
    Zambia has **no calibration quadrats**, so there is no `roofclf` half and no
    two-detector cross-check. It also has no glint sample, so `p_unmapped` is 0 and
    `p_real` collapses to the OpenStreetMap-mapped fraction; and recall was deliberately
    **skipped** (`--recall-reference none`) rather than measured against a reference made
    mostly of solar-farm perimeters. Every number here is a lower bound of the kind
    [France publishes](france.md), not a recall-corrected estimate.

Best exceeds Verified by only 20.5 MWp. The atlas is overwhelmingly the hand-mapped
OpenStreetMap population converted at the project's constants, with a thin layer of model
detections on top. That is the honest shape of a first pass with no local evidence.

## The finding: a third of the mapped capacity was never built

Zambia's OpenStreetMap solar population is 221 features, but 20.2 of its 20.6 km&sup2; of
ground area sat in sixteen `power=plant` perimeters of 0.3 to 2.8 km&sup2;, eleven of them
added in a single mapping pass on 4 August 2026. Taken at face value that population implies
about **1,089 MWp**, against a real Zambian fleet of roughly 100 to 150 MW.

That matters twice over: those polygons feed the Verified tier directly, and `chips` burns
every OpenStreetMap polygon at or above 400 m&sup2; as a **positive training mask**. An
announced-but-unbuilt project site would be both booked as capacity and taught to the model
as the appearance of PV.

`scripts/screen_osm_ground_perimeters.py` measures, for each perimeter over every composited
cell it touches, what fraction is imaged at all and what fraction the model lights up. Each
flagged one was then checked against the RGB imagery by eye.

| | perimeters | area | at 0.05 kWp/m&sup2; |
| --- | --- | --- | --- |
| Array visible, model covers 34 to 99% | 6 | 6.4 km&sup2; | counted |
| **Fully imaged, model finds nothing, imagery shows bare ground, bush or fields** | **8** | **11.7 km&sup2;** | **583 MWp, removed** |
| Not judgeable | 1 | 2.1 km&sup2; | ~104 MWp, kept and flagged |

Removing them moved Verified from 755.1 to **505.8 MWp**.

**The screen only ranks what to look at.** `det_frac` is the model's opinion about its own
training labels and settles nothing by itself. Two things make the zeros credible: the same
checkpoint covers Bangweulu at 98.8% and Itimpi at 99.7% of their imaged area in the same
country and the same imagery epoch, so it is demonstrably not blind to Zambian ground-mount;
and `p_max` is *exactly* 0.00 over a full square kilometre, which is a different statement
from a low mean. The verdicts came from the imagery. The audit trail, screen table and RGB
crops are in `results/zambia_osm_ground_screen/`, and the exclusions are a hand-written,
commented list at `configs/zambia_osm_ground_exclusions.txt`.

**This is not a claim that the projects do not exist**, only that no array had been built as
of the imagery epoch. A site that fills in will come back on a re-screen.

The one perimeter that could not be judged failed for an unexpected reason: its cell
(`0069_0068`) carries a genuine nodata hole exactly under the polygon, 25,993 pixels that are
zero in all ten bands, and the cell is only 22.8% filled. That is rare rather than systemic
(of 120 cells sampled nationally, median fill is 100% and only two are below 50%).
Re-composing that single cell on a wider window would settle it.

## In-domain retraining was measured, and rejected

Zambia's OpenStreetMap holds 221 solar features. After `dissolve_overlapping` merges nested
`power=plant` and `power=generator` elements, and after the screen, the country has **34
distinct installations at or above the 400 m&sup2; floor**. `sample_chip_centers` dedupes
positives sharing a ~2 km cell, and Zambian PV is concentrated in a handful of sites, so
those collapse to **25 spatially distinct training positives** (18 train, 7 validation) with
**zero background chips**.

A localisation retrain was built and then not shipped. On the held-out Copperbelt cluster,
roughly 700 km from the Lusaka training cluster, zero-shot `v4` already detects **3 of 3**
installations at 95.6% median area coverage. There is no headroom on a three-installation
holdout for a retrain to demonstrate anything, and the project's own
[v6 France experiment](../experiments.md) is the standing evidence that a half-measure
retrain can land worse than zero-shot. The config is kept at
`configs/terramind_pv_v7_zambia.yaml` as the record.

What Zambia actually needs is **hard negatives** (bright bare soil, burn scars, dry-season
miombo) and **one exhaustively mapped calibration quadrat** &mdash; not more OpenStreetMap
solar polygons. See the [quadrat protocol](../calibration-mapping-protocol.md).

## Plausibility gate

`earthpv check-density` reports 1 fail and 8 suspect of 10 provinces, and both are
interpretable rather than artefacts:

* **Lusaka fails single-cell concentration**, 90% of the province in cell `0064_0025`. That
  cell is the Lusaka South Multi-Facility Economic Zone, which is genuinely where Zambia's
  utility and large rooftop PV is.
* **Eight provinces are flagged suspect** on the ground-to-rooftop ratio, every one of them
  with a total between 0.7 and 7 MWp, far below the check's own 50 MWp noise floor.

Published per this project's standing precedent for a checked-genuine plausibility failure,
with the failure stated rather than suppressed.

## Two constants worth revisiting

Bangweulu and Ngonye together are about 88 MW over roughly 1.04 km&sup2; of mapped perimeter,
which is **0.085 kWp/m&sup2; against the assumed 0.050** for ground-mount site area. Germany's
own measurement against MaStR put the same constant at 0.081 (1.62x). So `DEFAULT_KWP_PER_M2_LAND`,
currently calibrated on two Pakistani plants, looks biased low in two independent places,
while the unbuilt perimeters pushed the total the other way. The
[country data registry](../data-registry.md) now lists GMSEUS, which carries an explicit
ground cover ratio for 18,502 arrays and could settle it.

## Reproducing

```bash
pixi run python scripts/new_region.py check --bbox 21.999,-18.08,33.706,-8.224 --iso3 ZMB
pixi run python scripts/overpass_labels_chunked.py \
    --bbox 21.999,-18.08,33.706,-8.224 --iso3 ZMB --name zambia --tiles 4x4
systemd-run --user --collect --unit=earthpv-compose-zambia -p WorkingDirectory="$PWD" \
  -p Environment=EARTHPV_STAC_PROVIDER=earth-search \
  bash scripts/compose_loop.sh zambia 0 1000 4 3600 600
bash scripts/run_zambia_pipeline.sh data/models/v4_combined_all/terramind-pv-epoch=41-step=16590.ckpt
```

A country-scale Overpass pull needs the chunked script: a single national query times out on
every public mirror, and the national boundary clip matters &mdash; a bbox around Zambia
returns 2,283 features, of which 2,062 are Zimbabwean and Congolese.
