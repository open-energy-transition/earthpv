# Vietnam: a localized detector, and a size cap that did not travel

Vietnam was composed and run between 23 and 26 September 2026. Like
[Zambia](zambia.md) and [Nigeria](nigeria.md), it started from nothing local: no cached
imagery, no calibration quadrats, no national register, no third-party PV dataset. It is
the first country run under the owner's standing instruction to **localize the
segmentation** on the country's own OpenStreetMap labels rather than run an existing
checkpoint zero-shot, and to ship whichever of the two scores better on a held-out region.

Interactive: [Vietnam PV evidence atlas](../atlas-vietnam.md).

## Headline

| | |
| --- | --- |
| Verified | **8,179.8 MWp** (90% 6,006 to 11,425) |
| Best estimate | **8,860.5 MWp** (90% 7,881 to 11,655) |
| Grid | 2,611 of 2,611 cells of 0.1&deg;, 64 provinces (geoBoundaries, pre-2025 boundaries) |
| Imagery | Sentinel-2 L2A, September 2025 to August 2026 |
| Model | `v9_combined_vietnam` epoch 36, localized (see below) |

!!! warning "A precision floor, not an estimate"
    Vietnam has **no calibration quadrats**, so there is no `roofclf` half and no
    instrument at all below the 400 m&sup2; segmentation floor. It has no glint sample, so
    `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction. Recall
    was deliberately skipped (`--recall-reference none`). For scale: EVN reported more than
    11,200 MWp of rooftop solar alone at the end of July 2026
    ([pv magazine, 22 September 2026](http://www.pv-magazine.com/2026/09/22/vietnam-pushes-provinces-to-accelerate-rooftop-solar-rollout/)),
    and national solar has been reported above 19 GW
    ([Vietnam Briefing](https://www.vietnam-briefing.com/news/vietnams-solar-energy-market-a-comprehensive-outlook-for-investors.html/)).
    This page is a floor at roughly half of that, and the missing half is overwhelmingly
    rooftop.

## Localizing the detector

**Labels.** 2,244 OpenStreetMap solar features inside Vietnam (720 rooftop, 1,522 ground),
out of 2,853 in the country's bounding box. Unlike Nigeria's, this population is large-array
heavy: the mapped polygons are mostly utility farms and large commercial roofs, which is
exactly what a 10 m sensor can learn from.

**Holdout, chosen from the label map before any training.** The Central Highlands (Kon Tum,
Gia Lai, Dak Lak, Dak Nong): 385 cells holding 206 of the 1,199 spatially distinct
positives (17.2%), outside the Ninh Thuan / Binh Thuan farm core, and a mix of utility
farms and the farm-roof PV of the 2020 boom. Training chips in the one-cell ring around it
were dropped (`scripts/mark_val_buffer.py`, 26 chips) so that neither the ~900 m chip jitter
nor the 2.24 km window can put a held-out installation into training.

**Corpus and recipe.** 1,735 train and 359 val chips (1,289 with PV), repeated x4 and merged
with v5's five corpora into 32,563 rows, so Vietnam is about a quarter of the training rows.
The recipe is v5's verbatim; only the corpus changed. Early-stopped with the best epoch at
36, about 14 hours on the GTX 1060.

**The ship decision**, `scripts/compare_local_vs_v5.py` on the 359 held-out chips:

| | v5 (zero-shot) | v9 (localized) |
| --- | --- | --- |
| pixel IoU | 0.724 | **0.762** |
| pixel F1 | 0.840 | **0.865** |
| recall, installations at or above 500 m&sup2; | **0.973** (434 of 446) | 0.960 (428 of 446) |

The rule compares recall first, and a difference inside 0.02 is a tie; pixel IoU then
decides. v9 draws markedly cleaner outlines at the cost of six missed installation
instances in 446, which is noise at this size. Two things to read it with: v9's best epoch
was selected on a pooled validation set that includes these chips, which is a small
advantage v5 did not get; and both checkpoints already find nearly every large array here,
so the gain is in shape, not in detection.

## The 5 km&sup2; ground cap did not travel

`scripts/prepare_national_osm_solar.py` drops every ground polygon above 5 km&sup2;. That
threshold is a German measurement: against the national register, **no** German OSM ground
polygon above 5 km&sup2; contained a registered unit, and Germany's largest real park is
about 5 km&sup2;. In Vietnam it removed the five largest mapped plants, 5.6 to 8.3 km&sup2;
each and 38.4 km&sup2; together, and every one of them is fully imaged and **92 to 99%
detected** by the model. They sit in Binh Phuoc, Tay Ninh, Ninh Thuan and Dak Lak, where the
country's largest parks are.

The cap now has an evidence-gated exception (`--keep-detected-screen`): a ground feature
above it is kept only when the perimeter screen shows it imaged and at least 50% detected.
Default behaviour, and therefore Germany's, is unchanged. Keeping the five raised Verified
from 6,258 to 8,180 MWp. India, whose largest parks are tens of km&sup2;, runs with the same
gate.

## OpenStreetMap's ground population here is real

Zambia's screen found announced-but-unbuilt `power=plant` outlines carrying a third of its
hand-mapped capacity. Vietnam's does not: all **274 ground perimeters of 50,000 m&sup2; or
more** are imaged, the model detects PV over a **median 99%** of each, and only three
(0.5 of 132.8 km&sup2;) fall below 60%. No exclusion list was needed.

## Plausibility gate

`earthpv check-density` reports **14 fail and 16 suspect of 64 provinces**. Every failure is
the ground-to-rooftop ratio above 5x, a single cell above 25% of its province, or both, and
the failing provinces are the solar-farm belt: Ninh Thuan, Binh Thuan, Tay Ninh, Binh Phuoc,
Dak Lak, Long An, Binh Dinh, Phu Yen. The check exists to catch ground-mount false positives
on bright bare land, so it was tested directly: the share of the model's ground-mount
candidate area that lies **inside a hand-mapped OSM plant perimeter** is **82 to 99% in 12 of
the 14 failing provinces, and 78% nationally**. These are real plants, and the top cells of
the four largest concentration failures (Tay Ninh, Binh Phuoc, Ninh Thuan, Dak Lak) are
exactly the five large parks above. Published with the flags
stated, per this project's precedent for a checked-genuine failure.

Two exceptions are not explained that way and are candidates for review rather than
capacity anyone should quote: Dak Nong (35% of 4.1 km&sup2; inside mapped plants) and Gia
Lai (45% of 5.3 km&sup2;, suspect). A cluster of small northern mountain provinces (Cao Bang,
Ha Giang, Lai Chau, Dien Bien and others, 0.15 to 0.72 km&sup2; each) has no mapped plant at
all and is most likely false positives. The rooftop side of the ratio is also understated,
for the reason in the warning above, which inflates every ratio the gate computes.

## Candidate population

6,536 candidates: 3,678 rooftop, 1,688 ground-adjacent, 1,170 with no building. Only 90
exceed the 100,000 m&sup2; merge cap, 17.7% of candidate area, against 69.1% for v5 on
Nigeria; 103 more are OSM-verified plant geometries and are exempt. The model's own
estimate (`est_mwp_rc`) is 4,225 MWp, 823 rooftop and 3,403 ground, and the
probability-weighted ceiling (`est_mwp_exp`) is 8,039 MWp. Best exceeds Verified by only
681 MWp because the model mostly re-finds mapped plants and, with no glint sample, its
unmapped detections are discounted to the mapped fraction.

## Operational notes

Compose built 2,611 cells in about 59 hours on a 12-month window: northern Vietnam is
overcast for much of its dry season (Hanoi had 16 scenes under 30% cloud in 20 months), and
`annual_composite` keeps the 12 least-cloudy scenes per cell whatever the window. Three
network failure modes surfaced and were fixed along the way, taking the rate from about 36
to about 90 cells per hour:

- the Planetary Computer patience was raised to 1,800 s, since 30% of cells were being
  downloaded twice under a shared link;
- GDAL now keeps pooled connections alive and aborts a transfer that stalls for 60 s. Dead
  keep-alive connections had been waiting out the kernel's ~15 minute retransmission
  timeout per request;
- a socket timeout was added on the Python side, because one hung STAC search holds the
  process-wide search lock and stalls every worker, including the Earth Search fallback.

The cost of the stall abort is about one dropped band read per cell, so the median for that
band is over 11 scenes rather than 12.

Postprocess was OOM-killed three times at 14 GB holding every building within 2 km of any
candidate. It now runs with `--building-buffer-m 500`; placement and the rank prior only use
buildings within about 40 m.

## What Vietnam needs next

**A calibration quadrat.** Vietnam's rooftop PV, more than 11 GWp registered, is almost
entirely outside what this page can see. One exhaustively mapped box in a rooftop-dense area
(the Ho Chi Minh City industrial belt, or the Central Highlands' farm roofs) is what would
unlock a `roofclf` half. Check the imagery date before drawing it; see the
[quadrat protocol](../calibration-mapping-protocol.md).

**The land constant.** Ground-mount converts at 0.05 kWp/m&sup2; of site area, calibrated on
two Pakistani plants. Germany's register put German plants at 0.081 and Zambia's two measured
plants at 0.085. If Vietnam's parks are as dense, the ground half here is understated by a
similar factor; checking it against published plant capacities is the obvious next
measurement and has not been done.

## Reproducing

```bash
bash scripts/download_vida.sh VNM
pixi run python scripts/overpass_labels_chunked.py --bbox 102.1,8.4,109.5,23.4 \
  --iso3 VNM --name vietnam --tiles 3x8 --timeout 300 --retries 8
systemd-run --user --collect --unit=earthpv-vn-in-queue -p WorkingDirectory="$PWD" \
  -p LimitNOFILE=65536:65536 -p MemoryMax=4G bash scripts/run_vn_in_queue.sh
```

The queue composes Vietnam, then hands it to `scripts/run_country_compute.sh vietnam` (chips,
training, the v5 comparison, inference and the atlas chain, behind marker files). Status at
any time: `bash scripts/vn_in_status.sh`.
