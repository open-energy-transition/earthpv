# Nigeria: the checkpoint mattered more than the country did

Nigeria was composed and run between 16 and 23 September 2026. Like
[Zambia](zambia.md), it started from nothing local: no cached imagery, no calibration
quadrats, no national register, no third-party PV dataset. Unlike Zambia, it was scored
against two checkpoints rather than one, and the difference between them turned out to be
the most informative result of the run.

Interactive: [Nigeria PV evidence atlas](../atlas-nigeria.md).

## Headline

| | |
| --- | --- |
| Verified | **90.2 MWp** (90% 71 to 117) |
| Best estimate | **120.9 MWp** (90% 112 to 158) |
| Grid | 6,254 of 6,341 cells of 0.1&deg;, 37 regions |
| Imagery | Sentinel-2 L2A, November 2025 to March 2026 |
| Model | `v5_combined_france` epoch 25 |

!!! warning "A precision floor, not an estimate"
    Nigeria has **no calibration quadrats**, so there is no `roofclf` half and no
    instrument at all below the 400 m&sup2; segmentation floor. It has no glint sample, so
    `p_unmapped` is 0 and `p_real` collapses to the OpenStreetMap-mapped fraction, measured
    at 0.006 to 0.047. Recall was deliberately skipped (`--recall-reference none`). These
    are lower bounds of the kind [France](france.md) and [Zambia](zambia.md) publish, and
    they are not a statement about how much solar Nigeria has.

## The finding: v4 and v5 disagree, and v5 is right

The chain infers twice, with `v4_combined_all` (the production checkpoint everywhere except
France) and `v5_combined_france`, then scores both against the same OpenStreetMap
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

## The blob problem is reduced, not solved

`polygonize_chips` merges every touching thresholded pixel with no upper bound, so a
connected sheet of false positives becomes one candidate. Even under v5, **69.1% of
candidate area sits above the 100,000 m&sup2; cap** and is excluded from capacity by
`density.capacity_relevant_candidates`. The largest survivor is 4.06 km&sup2;.

That exclusion is what keeps the headline honest, but it is not a fix. Nigeria's failure
mode is precision, not recall, and the instrument that addresses it is hard negatives
mined from rejected leads, not more positives.

## Plausibility gate

`earthpv check-density` reports **0 fail and 23 suspect of 37 regions**. Every suspect is
flagged on the ground-to-rooftop ratio with a total below 1.5 MWp, far under the check's own
50 MWp noise floor, so the ratio there is arithmetic on near-zero numbers rather than a
signal. Published with the flags stated rather than suppressed.

## Mapping leads

Nigeria is a recall-first leads product before it is a capacity product. From the v5
candidates, after removing anything within 100 m of an already-mapped OpenStreetMap solar
feature, **5,074 new leads** remain, of which 1,312 are at or above 5,000 m&sup2;. They ship
as two MapRoulette challenges in `data/predictions_v5_nigeria/nigeria/`:

| tier | tasks | area | median | note |
| --- | --- | --- | --- | --- |
| `leads_map` | 1,026 | 32.2 km&sup2; | 21,480 m&sup2; | 5k to 100k m&sup2;, ranked best first |
| `leads_review` | 286 | 83.6 km&sup2; | 184,814 m&sup2; | above the merge cap, redraw rather than trace |

The head of the queue is confidence-1.00 rooftop leads on large roofs in Lagos, Abuja, Kano,
Kaduna, Jos and Maiduguri.

!!! danger "Mapping from leads contaminates the next calibration"
    With no glint sample, `mapped_frac` **is** Nigeria's precision estimate. Mapping the
    model's own leads raises it mechanically, which raises `p_real`, which raises
    `est_mwp_cal` and `est_mwp_rc`. The atlas capacity would climb without the model
    improving at all. Freeze the pre-mapping OpenStreetMap snapshot as the evaluation
    reference, or filter later pulls by feature timestamp. The recall table above was
    computed against the 15 September 2026 snapshot, before any lead-driven mapping.

## What Nigeria needs next, and what it does not

**Not a localisation retrain.** OpenStreetMap holds 1,372 Nigerian solar ways, but the
median mapped feature is 225 m&sup2; and only 22% clear the 400 m&sup2; training floor. At
the label-to-chip ratios observed elsewhere (Gujarat 866 features to 760 chips, Zambia 221
to 31), Nigeria yields roughly 300 to 400 chips. The
[v6 France experiment](../experiments.md) measured a 3,201-chip in-domain retrain landing
*worse* than zero-shot on slope and recovery. Nigeria is an order of magnitude below the
volume that already failed.

**Hard negatives**, mined from leads a mapper rejects, attack the 69% blob problem directly.
`earthpv hard-negative-chips --centers` consumes them, and `pakistan_hard_neg` (2,626 chips)
shows the approach scales.

**One exhaustively mapped calibration quadrat** is worth more than diffuse national mapping,
because it is the only thing that unlocks a `roofclf` half and a real coverage ratio. A list
of installations is not a calibration area: the coverage ratio needs a bounded area where
the *absence* of PV is known. Check imagery date before drawing the box, not after mapping
it. See the [quadrat protocol](../calibration-mapping-protocol.md).

## Reproducing

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
