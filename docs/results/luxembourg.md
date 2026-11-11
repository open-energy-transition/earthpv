# Luxembourg: the larger arrays only, in a country made mostly of border cells

Luxembourg was added on the owner's request on 7 November 2026 with Portugal, Belgium, the
Netherlands and Italy, under the rules every recent country follows: no calibration quadrats,
no register used, the segmentation **localized** on Luxembourg's own OpenStreetMap labels and
shipped only if it beats the general model on a held-out region. It ties, on a thin holdout,
and under the tie rule this page runs on `v33_combined_luxembourg`.

Interactive: [Luxembourg PV evidence atlas](../atlas-luxembourg.md).

## Headline

| | |
| --- | --- |
| Verified | **25.4 MWp** (90% 19 to 34) |
| Best estimate | **40.5 MWp** (90% 32 to 58) |
| Grid | 40 cells of 0.1&deg;, 12 cantons (geoBoundaries) |
| Imagery | Sentinel-2 L2A, May to September 2026, median scene 13 July |
| Model | `v33_combined_luxembourg` epoch 21, localized (see below) |

!!! warning "A precision floor, and blind to most of Luxembourg's solar"
    Luxembourg has **no calibration quadrats**, so there is no `roofclf` half and no
    instrument below the 400 m&sup2; segmentation floor. The regulator, ILR, counted
    **746.35 MW** of photovoltaics installed at the end of 2025, up 35.8% in the year
    ([Statistiques du marché électricité 2025](https://www.ilr.lu/wp-content/uploads/publication/ILR_infographie_statistiques-marches_electricite_20260625-1.pdf)),
    so Best is about 5% of the fleet. Read this page as a map of the larger arrays and of what is
    mapped, not as an estimate of Luxembourg's solar. Panels imported directly from China,
    155.2 MW from February 2017 to August 2026
    ([Ember](https://ember-energy.org/data/china-solar-exports-data/)), are about a fifth of
    the installed fleet, so the page does not call them a ceiling: most of Luxembourg's
    panels arrive through its neighbours.

ILR gives no canton figures, so the page compares the national total only. Its figure is in
MW and does not say whether that is panel (DC) or inverter (AC) capacity. None of these
figures is ground truth for this map.

## Border cells

Luxembourg is small enough that **23 of its 40 cells straddle the border** with France,
Belgium or Germany, and every one is kept whole, as on every country page. Of the model's
21.3 MWp (recall-corrected), **8.3 MWp from 35 outlines lies beyond the border**, nearly
two fifths, and the page's Best counts it. The hand-mapped installations are clipped to
Luxembourg's border (394 of 394 inside), so Verified is Luxembourg's own. The largest single
model contribution, 3.4 MWp, is a 0.16 km&sup2; outline in Germany across the Sauer from
Echternach that matches a park mapped in OpenStreetMap; with a second model outline across
the border in the same cell it is most of Canton Echternach's 7.2 MWp of ground-mounted
capacity. A combined atlas
(`earthpv combine-atlas`) counts each detection in one country only.

## Localizing the detector

The holdout is **Canton Mersch**: 3 cells, 13 of the country's 66 dissolved positives of
400 m&sup2; and up. `pick_val_region.py` first chose Canton Capellen, whose 6 val chips fell
short of the chain's minimum of 8, and Mersch is its rule's next region, set before any
model was trained.

| Compared at equal pixel precision (0.305) | Local `v33` epoch 21 | General `v5` |
| --- | ---: | ---: |
| Recall, installations of 500 m&sup2; and up (of 48) | 0.813 | 0.813 |
| Pixel IoU | 0.247 | 0.246 |
| Pixel F1 | 0.396 | 0.391 |

Both models find the same 39 of 48 installations, and pixel IoU differs by 0.0004, so the
owner's rule (a tie goes to the localized model) decides. The local model ships at
threshold 0.3; the general one needed 0.5 to match its precision. A holdout this small
cannot separate the two by much.

## Plausibility gate

`earthpv check-density` compares each canton's ground-mounted capacity with its rooftop
capacity. It fails none and flags 11 of the 12; only Canton Luxembourg passes:

| Canton | Rooftop (MWp) | Ground (MWp) | Ratio | Status |
| --- | ---: | ---: | ---: | --- |
| Echternach | 0.06 | 7.21 | 124.4 | suspect |
| Esch-sur-Alzette | 0.11 | 4.31 | 40.6 | suspect |
| Grevenmacher | 0.05 | 2.24 | 49.9 | suspect |
| Vianden | 0.02 | 1.09 | 49.3 | suspect |
| Redange | 0.10 | 0.70 | 6.7 | suspect |
| Remich | 0.01 | 0.59 | 65.8 | suspect |
| Capellen | 0.04 | 0.45 | 10.8 | suspect |
| Mersch | 0.12 | 0.43 | 3.6 | suspect |
| Diekirch | 0.08 | 0.42 | 5.4 | suspect |
| Clervaux | 0.11 | 0.34 | 3.1 | suspect |
| Wiltz | 0.05 | 0.19 | 4.0 | suspect |
| Luxembourg | 0.04 | 0.08 | 2.0 | ok |

The same pattern as [Belgium](belgium.md) and the [Netherlands](netherlands.md): household
rooftops are below what the sensor resolves, so the rooftop denominator is tiny.
Echternach's ratio is led by the border cell above, whose ground outlines lie in Germany.
Whether the model's ground outlines are themselves right has **not been
checked by eye in Luxembourg**.

## What is counted

- **OpenStreetMap:** 394 reference features inside the border after the solar thermal
  filter, placed as 195 rooftop, 116 ground and 83 unknown; 66 of them are 400 m&sup2; and up
  and hold 21.8 MWp. Verified is all mapped capacity.
- **Model:** 363 priced candidates. Best adds 15.1 MWp over Verified, mostly on open ground
  (Best is 6.7 MWp rooftop and 33.8 MWp ground). Two outlines above the 100,000 m&sup2; merge
  cap (9.9% of candidate area, the largest 0.15 km&sup2;) are excluded from capacity until
  judged; one OSM-verified oversize candidate (0.16 km&sup2;, the park in Germany above) is
  exempt. One 13.8 ha outline in Canton Esch-sur-Alzette waits in the oversize review.
- **Solar thermal:** no concentrated solar plant; none of the five thermal elements in the
  scan is among the PV features.
- **Footprints:** VIDA, with 907 OSM buildings filling 210 empty 0.01&deg; blocks (0.6% of
  146,345).

## What Luxembourg needs next

**A rooftop instrument.** An area mapped panel by panel would start a small-installation
half, and nearly all of Luxembourg's capacity is in that half.

**The steps still owed.** Judge the oversize outline and draw the large installation
review, publish the mapping leads, and propose calibration areas.

## Reproducing

Luxembourg follows [Scale to a new country](../reproduce.md), with the AOI in
`configs/aoi.yaml` and the model in `configs/terramind_pv_v33_luxembourg.yaml`. The last step:

```bash
pixi run earthpv atlas --aoi luxembourg \
  --osm-solar data/labels/luxembourg_national_osm_solar.parquet --include-offgrid-osm \
  --imagery-date-range "May - Sep 2026" --out results/luxembourg_pv_evidence_atlas.html
```
