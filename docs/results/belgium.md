# Belgium: the larger arrays only, against a fleet that is mostly small

Belgium was added on the owner's request on 7 November 2026 with Portugal, the Netherlands,
Luxembourg and Italy, under the rules every recent country follows: no calibration quadrats,
no register used, the segmentation **localized** on Belgium's own OpenStreetMap labels and
shipped only if it beats the general model on a held-out region. It does, narrowly and on a
thin holdout, and this page runs on `v31_combined_belgium`.

Interactive: [Belgium PV evidence atlas](../atlas-belgium.md).

## Headline

| | |
| --- | --- |
| Verified | **502.3 MWp** (90% 413 to 629) |
| Best estimate | **639.3 MWp** (90% 557 to 774) |
| Grid | 423 cells of 0.1&deg;, 3 regions (geoBoundaries) |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 1 July |
| Model | `v31_combined_belgium` epoch 22, localized (see below) |

!!! warning "A precision floor, and blind to most of Belgium's solar"
    Belgium has **no calibration quadrats**, so there is no `roofclf` half and no instrument
    below the 400 m&sup2; segmentation floor, and recall was deliberately not corrected
    (`--recall-reference none`). Elia, the transmission system operator, monitored
    **12,128 MW** of solar on 30 September 2026
    ([ods032](https://opendata.elia.be/explore/dataset/ods032/)), so Best is about 5% of the
    fleet. Read this page as a map of the larger arrays and of what is mapped, not as an
    estimate of Belgian solar. Panels imported directly from China, 25.4 GW from January 2017
    to August 2026 ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are
    about twice the installed fleet, so they are a very loose ceiling here.

## Against Elia, by region

| Region | Verified (MWp) | Best (MWp) | Elia monitored (MW) | Best as a share of Elia |
| --- | ---: | ---: | ---: | ---: |
| Vlaams Gewest | 218.3 | 290.5 | 8,713.8 | 3.3% |
| Wallonne Gewest | 248.5 | 273.9 | 3,083.1 | 8.9% |
| Brussels Hoofdstedelijk | 26.8 | 27.6 | 331.4 | 8.3% |
| **Belgium** | **502.3** | **639.3** | **12,128.3** | **5.3%** |

The regions sum to 493.6 MWp Verified and 592.0 MWp Best; the rest of the national totals lies
in border cells outside the three regions. Elia's dataset gives monitored capacity in MW and
does not say whether that is panel (DC) or inverter (AC) capacity. None of these figures is
ground truth for this map.

## Localizing the detector

The holdout is the **Brussels-Capital Region**: 2 cells, 4.8% of the country's positive chips,
171 mapped installations of 500 m&sup2; and up. It is one dense city, so it says little about
the rest of the country.

| Compared at equal pixel precision (0.268) | Local `v31` epoch 22 | General `v5` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up | 0.795 | 0.801 |
| Pixel IoU | 0.275 | 0.240 |
| Pixel F1 | 0.448 | 0.370 |

Recall ties (a difference of 0.006), so the owner's rule goes to pixel IoU, where the local
model wins by 0.035. It ships at threshold 0.3, where on the same holdout its pixel precision
is 0.320, pixel IoU 0.288 and recall at 500 m&sup2; and up 0.760.

## Plausibility gate

`earthpv check-density` compares each region's ground-mounted capacity with its rooftop
capacity. It fails Wallonia and flags Flanders:

| Region | Rooftop (MWp) | Ground (MWp) | Ratio | Status |
| --- | ---: | ---: | ---: | --- |
| Wallonne Gewest | 13.7 | 83.8 | 6.10 | fail |
| Vlaams Gewest | 30.8 | 97.4 | 3.17 | suspect |
| Brussels Hoofdstedelijk | 2.5 | 0.8 | 0.31 | ok |

The same pattern as [Poland](poland.md) and [Spain](spain.md): household rooftops are below
what the sensor resolves, so the rooftop denominator is small. Whether the model's ground
outlines are themselves right has **not been checked by eye in Belgium**.

## What is counted

- **OpenStreetMap:** 25,054 reference features inside the border after the solar thermal
  filter, placed as 22,549 rooftop, 1,703 ground and 802 unknown. Verified is all mapped
  capacity.
- **Model:** 1,440 candidates. Best adds 137.0 MWp over Verified. Four outlines above the
  100,000 m&sup2; merge cap (3.8% of candidate area, the largest 0.24 km&sup2;) are excluded
  from capacity until judged; 15 OSM-verified oversize candidates are exempt.
- **Border cells are kept whole:** 158 priced candidates (58.8 MWp recall-corrected) lie beyond
  the border in cells the page keeps whole, and its total counts them. A combined atlas does
  not.
- **Solar thermal:** no concentrated solar plant. Four thermal plants make no electricity and
  do not count.
- **Footprints:** VIDA, with 27,636 OSM buildings filling 710 empty 0.01&deg; blocks (0.6% of
  4.58 million).

## Operational notes

An internet outage on 9 November (02:48 to 05:01 and 06:32 to 08:29) hit several steps of the
chain. The density, plausibility, OSM solar, solar thermal and atlas steps and the imagery
dates were re-run afterwards; the totals did not change, and the district layer and the solar
thermal check now exist. Two steps have not been redone: `export` skipped its steep-ground
lead screen, and the solar farm review package was not drawn.

## What Belgium needs next

**A rooftop instrument.** An area mapped panel by panel would start a small-installation half.
No regional installation records have been looked at for this page.

**The steps still owed.** Re-run `export` for the steep-ground screen, draw the solar farm
review for the four oversize outlines, publish the mapping leads, and propose calibration areas.

## Reproducing

Belgium follows [Scale to a new country](../reproduce.md), with the AOI in `configs/aoi.yaml`
and the model in `configs/terramind_pv_v31_belgium.yaml`. The last step:

```bash
pixi run earthpv atlas --aoi belgium \
  --osm-solar data/labels/belgium_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/belgium_pv_evidence_atlas.html
```
