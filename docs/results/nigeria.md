# Nigeria: a model localized on Nigeria's own map

Nigeria was composed and run between 16 and 23 September 2026 and published on a general
checkpoint, `v5_combined_france`, which had never seen it. On the owner's request (14 November)
it was run again from a fresh OpenStreetMap pull with a model localized on Nigeria's own map,
`v45r_resnet50_nigeria`. That model beat v5 on a held-out region and has run this page since
19 November. Nigeria still has no calibration quadrats, no national register and no
third-party PV dataset.

Interactive: [Nigeria PV evidence atlas](../atlas-nigeria.md).

## Headline

| | |
| --- | --- |
| Verified | **128.7 MWp** (90% 102 to 166) |
| Best estimate | **164.8 MWp** (90% 154 to 185) |
| Generation | 0.25 TWh/yr from Best (90% 0.23 to 0.28), 1,519 kWh/kWp |
| Grid | 6,254 of 6,341 cells of 0.1&deg;, 37 regions |
| Imagery | Sentinel-2 L2A, November 2025 to March 2026, median scene 1 January |
| Model | `v45r_resnet50_nigeria`, epoch 11, at threshold 0.3, localized (see below) |

!!! note "Revised on 19 November: the localized model, its reviews, and the November map"
    Until 19 November this page ran on v5 and read Verified 90.2 and Best 157.3 MWp (90% 142
    to 187). The localized model draws fewer and different outlines, so the reviews started
    again: the owner judged 513 of its 524 unmapped outlines from 1 ha up to the 10 ha merge
    cap (18 solar, 495 not) and all 157 above the cap (69.8 km&sup2;, none solar). On the
    September map that put Best at 128.0 MWp: rooftop 51.6 to 39.0, ground 105.6 to 89.0, most
    of the fall in Kano, Lagos and the Federal Capital Territory. Verified now counts the
    14 November pull, 1,018 mapped features against 482: 90.2 to 128.7 MWp, most of it in the
    Federal Capital Territory (8.5 to 22.6), Lagos (0.2 to 10.7) and Kano (28.0 to 35.6), and
    Best to 164.8. Earlier, on v5: Best 120.9 MWp, then 126.9 after one park was judged among
    226 outlines above the cap (4 November), then 157.3 after 28 of 369 large outlines were
    judged solar (10 November).

!!! warning "A precision floor, not an estimate"
    Nigeria has **no calibration quadrats**, so there is no `roofclf` half and no
    instrument at all below the 400 m&sup2; segmentation floor. It has no glint sample, so
    `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction, measured
    at 0.010 to 0.028 per size class. Recall was deliberately skipped
    (`--recall-reference none`). Where a person judged an outline, the verdict replaces that
    price. These are lower bounds of the kind [France](france.md) and [Zambia](zambia.md)
    publish, and they are not a statement about how much solar Nigeria has.

## The localized model (v45r, 2026-11-19)

**Labels.** A national Overpass pull of 14 November holds 1,687 solar features, 407 of them
400 m&sup2; and up, against 1,268 and 285 in September; none is solar thermal. Some of the
new ones are the model's own leads, mapped since (below).

**Holdout.** `pick_val_region.py` chose **Lagos** from that label map before training: 24
cells, 31 of 289 dissolved positives of 400 m&sup2; and up (10.7%). The largest region, the
Federal Capital Territory (105), is never the holdout.

**Training.** A ResNet-50 pretrained on SSL4EO-S12, the architecture of the released
[v28](../pretrained-model.md), with the recipe of the localized ResNets that beat both
localized TerraMind and v28 in Denmark, California and Texas. Its corpus is v28's (v5's plus
South Africa) with Nigeria's chips added (210 train, 22 val, 126 holding PV). The holdout
holds too few installations to choose among epochs by recall, so epoch 11, the val/mIoU pick,
ships at 0.3.

| On the Lagos holdout, at equal pixel precision | Local `v45r` | General `v5` |
| --- | ---: | ---: |
| Installations of 500 m&sup2; and up found (of 73) | **59** (0.808) | 48 (0.658) |
| of 1,000 m&sup2; and up (of 59) | 50 | 47 |
| of 500 to 1,000 m&sup2; (of 14) | 7 | 3 |
| Pixel IoU | **0.497** | 0.414 |
| Pixel F1 | 0.651 | 0.615 |

v5 never reaches the local model's precision, so both are compared at v5's best (0.74, v5 at
threshold 0.98). Scored with `fair_score.py` at v5's production precision over the 76
held-out installations of 400 m&sup2; and up, the local model finds 61 against v5's 50, 11
more and none fewer (McNemar p = 0.001). The released v28, which never saw Nigeria, ties it
there (61, 13 more and 2 fewer than v5), so most of the gain is the ResNet, not Nigeria's
labels. 72 of the 73 held-out installations are ground-mounted, so rooftop recall is not
measured.

**The candidate population.** The local model draws fewer, larger outlines:

| | v5 | v45r |
| --- | ---: | ---: |
| candidates | 5,109 | 4,054 |
| rooftop candidates | 650 | 317 |
| above the 100,000 m&sup2; cap, out of capacity until judged | 286 (69.1% of candidate area) | 160 (71.4%) |
| largest single outline | 4.06 km&sup2; | 7.39 km&sup2; |
| candidate area up to the cap | 36.8 km&sup2; | 28.7 km&sup2; |
| `est_mwp_exp`, the ceiling | 398.0 MWp | 291.9 MWp |
| `check-density` | 24 suspect of 37, 0 fail | **15 suspect of 37**, 0 fail |

**What the reviews found.** On v45r's large installation page, 495 of the 513 judged leads
are not solar (11 of them bright roofs), and on open ground 414 of 429. The 18 judged solar
(0.53 km&sup2;) count whole, roofs at 1/2.5 of the outline; 11 left unsure keep their size
class's price. All 157 outlines above the cap were judged not solar. v5's verdicts were not
carried over: they name v5's outlines. Of the 29 v5 outlines judged solar, 14 are mapped in
OpenStreetMap since and 11 are among v45r's 18; the other 4 (0.17 km&sup2;) are outlines
v45r draws but that were not on its page.

**The earlier claim was wrong.** This page said in September that a localization retrain
would not help Nigeria, because too few mapped arrays clear the training floor. The localized
run found 11 more of 73 held-out installations at equal precision. It also shows that this
does not close the gap to Ember's import figure: on the same map Best fell, because the new
outlines were judged and most large ones are not solar. What moved the page up was mapping
(Verified 90.2 to 128.7 MWp from the November pull), not the model.

## The finding: v4 and v5 disagree, and v5 is right

This section is the September run, on two general checkpoints. The chain inferred twice, with
`v4_combined_all` (then the production checkpoint everywhere except France) and
`v5_combined_france`, then scored both against the same OpenStreetMap
population. Scored over 191 dissolved mapped installations at or above 400 m&sup2;:

| size bin | n | v4 recall | v5 recall |
| --- | --- | --- | --- |
| 100 to 500 m&sup2; | 74 | 0.486 | **0.649** |
| 500 m&sup2; to 1k | 54 | 0.648 | **0.889** |
| 1k to 5k | 34 | 0.588 | **0.706** |
| 5k to 50k | 23 | 0.609 | **0.696** |
| above 50k | 6 | 0.500 | 0.500 |
| **pooled** | **191** | **0.565** | **0.728** |

v5 is **strictly dominant**: it finds everything v4 finds and 31 more. v4 finds nothing v5
misses. McNemar exact two-sided p = 0.000.

This is not a small recalibration. It changes what the candidate population *is*:

| | v4 | v5 |
| --- | --- | --- |
| candidates | 9,569 | 5,109 |
| oversize, excluded from capacity | 2,504 | **286** |
| share of candidate area excluded | 89.1% | **69.1%** |
| largest single blob | 12.92 km&sup2; | **4.06 km&sup2;** |
| rooftop candidates | 173 | **650** |
| `est_mwp_exp`, the ceiling | 1,141.8 MWp | **398.0 MWp** |
| `est_mwp_rc` rooftop | 1.68 MWp | **4.63 MWp** |
| `est_mwp_rc` ground | 26.36 MWp | 27.22 MWp |
| `check-density` | 32 suspect of 36 | **23 suspect of 37**, 0 fail |

The published total barely moved, from 117.5 to 120.9 MWp. Everything else did. The
probability-weighted ceiling fell by a factor of 2.9 while the recall-corrected rooftop
estimate rose by a factor of 2.8: v5 replaced merged false-positive sheets with actual
rooftop detections. Fourteen regions now pass the ground-to-rooftop plausibility check
against four before, including Lagos, Kano, Kaduna, Abuja and Rivers.

**Why this matters beyond Nigeria.** v5 was trained because v4 was bad over *France*, and
its French gain was attributed to French training data. Nigeria has no training data in
either checkpoint, so it is a genuine third regime, and v5 wins here too. That reframes the
[v5 result](france.md) as at least partly a general improvement rather than a purely French
one. It also means every AOI still on v4 should be re-scored before its numbers are trusted.

The v4 artifacts are kept as `*_PRE_v5_20260923` so the comparison stays reproducible.

## The blob problem is not solved

`polygonize_chips` merges every touching thresholded pixel with no upper bound, so a
connected sheet of false positives becomes one candidate. Under v45r, **71.4% of candidate
area sits above the 100,000 m&sup2; cap** (69.1% under v5) and is excluded from capacity by
`density.capacity_relevant_candidates` until a person judges it; the largest outline is
7.39 km&sup2;. v5's 226 such outlines were judged in November and one was a park; v45r's 157
were judged on 19 November and none is.

That exclusion is what keeps the headline honest, but it is not a fix. Nigeria's failure
mode is precision, not recall: 495 of 513 judged large leads were not solar.

## Plausibility gate

`earthpv check-density` reports **0 fail and 15 suspect of 37 regions** (24 suspect under
v5). Every suspect is flagged on the ground-to-rooftop ratio, the largest Imo with
5.1 MWp in all, far under the check's own 50 MWp noise floor, so the ratio there is
arithmetic on near-zero numbers rather than a signal. Published with the flags stated rather
than suppressed.

## Mapping leads

The atlas offers mappers only the outlines a person has judged solar: v45r's
`nigeria_pv_confirmed_leads.geojson` holds those 18, in release `pv-new-leads-2026-11-02`.
The unchecked lead files stay local: 1,877 leads from v45r's candidates more than 100 m from
any solar feature of the 14 November pull, after the lead screens and without the 495 judged
not solar; the 157 outlines above the cap, all judged not solar, are in no file. Every model
outline (4,029 inside the regions) and the 1,018 mapped features are in
`nigeria_pv_polygons.parquet`, release `pv-polygons-2026-11-11`.

!!! danger "Mapping from leads contaminates the next calibration"
    With no glint sample, `mapped_frac` **is** Nigeria's precision estimate. Mapping the
    model's own leads raises it mechanically, which raises `p_real`, which raises
    `est_mwp_cal` and `est_mwp_rc`. The atlas capacity would climb without the model
    improving at all. Freeze the pre-mapping OpenStreetMap snapshot as the evaluation
    reference, or filter later pulls by feature timestamp. v4 and v5 were compared against
    the 15 September 2026 snapshot, before any lead-driven mapping. The 14 November pull v45r
    trained on already holds some: 14 of the 29 v5 outlines judged solar are mapped since.

## What Nigeria needs next

**The precision table on the November map.** v45r's mapped share (0.010 to 0.028) is still
measured against the September pull, the reference its postprocess and export used; Verified
already counts the November one. Re-deriving the table from the November pull would raise the
mapped share where the new mapping lies.

**One exhaustively mapped calibration quadrat** is worth more than diffuse national mapping,
because it is the only thing that unlocks a `roofclf` half and a real coverage ratio. Ten
candidate boxes pass the imagery gate; none is mapped yet. A list of installations is not a
calibration area: the coverage ratio needs a bounded area where the *absence* of PV is known.
Check imagery date before drawing the box, not after mapping it. See the
[quadrat protocol](../calibration-mapping-protocol.md).

**Hard negatives**, from the 495 large leads judged not solar and from leads a mapper
rejects, attack the precision problem directly. Whether review verdicts should train the
next model is being tested on Texas first.

## Reproducing

The September run (imagery, v4 and v5):

```bash
pixi run python scripts/new_region.py check --iso3 NGA --name nigeria
bash scripts/nigeria_bootstrap.sh
systemd-run --user --collect --unit=earthpv-nigeria-chain \
  -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 -p MemoryMax=20G \
  bash scripts/run_nigeria_chain.sh
```

Compose reached 6,254 of 6,341 cells. The 87 that never completed are almost all in the
Niger Delta and the southeast, where no Sentinel-2 scene in the November to March window
clears the 30% scene cloud filter. That is a real refusal rather than a transient failure,
and it is why the chain's coverage gate is set at 97% rather than 100%.

Two operational notes from the run, both now recorded in `CLAUDE.md`. A country-scale
compose must set `EARTHPV_PC_TIMEOUT_S` well above the per-cell wall time when running
several workers, or every cell trips the 60 s Planetary Computer patience and is downloaded
twice; Nigeria livelocked for 17 hours on this and the log was indistinguishable from a
provider outage. And the compose unit is memory-capped, so expect roughly one OOM restart
per 10 hours, which the restart loop absorbs.

The localized run (labels pulled 2026-11-14, holdout written into `configs/aoi.yaml` by
`pick_val_region.py --labels`, model `v45r_resnet50_nigeria`) reused those composites, with
58 defective cells recomposed. Its predictions are in `data/predictions_nigeria_20261114/`,
and the page's last steps were:

```bash
pixi run python scripts/prepare_national_osm_solar.py --aoi nigeria \
  --labels data/labels/nigeria_overpass_solar_pull20261114.parquet \
  --keep-detected-screen results/nigeria_osm_ground_screen/screen_full.csv
pixi run earthpv density --aoi nigeria --pred-dir data/predictions_nigeria_20261114 \
  --districts --threshold 0.3 --calibration configs/calibration/nigeria_candidate_precision.yaml
pixi run earthpv atlas --aoi nigeria --pred-dir data/predictions_nigeria_20261114 \
  --osm-solar data/labels/nigeria_national_osm_solar.parquet \
  --imagery-date-range "Nov 2025 - Mar 2026" --out results/nigeria_pv_evidence_atlas.html
```
