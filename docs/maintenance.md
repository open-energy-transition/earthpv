# Keeping PV data current

A PV inventory starts going out of date the day it is published. Where solar is booming,
a register or a one-off survey cannot keep up: Pakistan's [growth map](results/growth.md)
shows how much of today's rooftop fleet appeared after 2022. EarthPV is built so that
updating a country is a **re-run of the same pipeline on new imagery**, not a new project,
and so that every round leaves the next one better informed: more of the map verified by
people, more local training data, and a calibration measured against a larger reference.

![The mapping flywheel: six numbered stations run clockwise round a ring with OpenStreetMap at the hub. 1, detect from space with each country's TerraMind model and the small-installation classifiers. 2, publish the evidence atlas with mapping leads and areas to map. 3, people map the leads of 400 square metres and more. 4, people map calibration areas completely. 5, people investigate local datasets such as registers and official statistics. 6, retrain the models and recalibrate on what was mapped. Arrows from stations 3 and 4 carry mapped panels into OpenStreetMap, and arrows out of it carry them to the atlas as counted capacity and to retraining as labels. A dashed frame round the whole wheel marks an LLM assistant that helps at every station but never edits OpenStreetMap, declares an area complete or signs off a number.](assets/figures/osm_ai_flywheel.svg#only-light)
![The mapping flywheel: six numbered stations run clockwise round a ring with OpenStreetMap at the hub. 1, detect from space with each country's TerraMind model and the small-installation classifiers. 2, publish the evidence atlas with mapping leads and areas to map. 3, people map the leads of 400 square metres and more. 4, people map calibration areas completely. 5, people investigate local datasets such as registers and official statistics. 6, retrain the models and recalibrate on what was mapped. Arrows from stations 3 and 4 carry mapped panels into OpenStreetMap, and arrows out of it carry them to the atlas as counted capacity and to retraining as labels. A dashed frame round the whole wheel marks an LLM assistant that helps at every station but never edits OpenStreetMap, declares an area complete or signs off a number.](assets/figures/osm_ai_flywheel.dark.svg#only-dark)

## One round of maintenance

1. **New imagery.** Sentinel-2 revisits every place every five days, free. `compose`
   builds a dry-season composite for each 0.1&deg; cell. A country's grid is pinned
   (`grid_origin` in `configs/aoi.yaml`), so a cell keeps its name from one round to the
   next and two rounds compare cell by cell. A new epoch is written beside the old one
   (`--index 1`), never over it.
2. **Detect.** `infer` scores every cell with the current checkpoint. Both steps resume
   cell by cell, so an interrupted run loses nothing.
3. **See what changed.** `growth` diffs two epochs scored by the *same* checkpoint, so the
   difference is new panels rather than a new model. Diffing across checkpoints was the
   first growth map's core flaw.
4. **Hand out only what is new.** `export --exclude-mapped` drops every detection within
   100 m of an installation already in OpenStreetMap and ranks the rest as mapping leads,
   with a ready-made MapRoulette challenge.
5. **Verify.** Mappers check each lead against high-resolution imagery in the
   OpenStreetMap editor and map what is real. That is the only step that needs people,
   and it is where the map improves.
6. **Learn.** The next label pull contains their work. The detector is retrained on the
   country's own labels, and the new checkpoint replaces the old one **only if it scores
   better on a held-out region of the same country**.
7. **Publish.** `density`, `check-density` and `atlas` rebuild the country page, and
   `scripts/build_atlas_data_pack.py` packages the per-cell table as a dated release, so
   every round stays citable and comparable with the last.

```bash
earthpv compose --aoi <aoi> --window 2027-04-01:2027-09-30 --index 1   # new epoch
earthpv infer   --aoi <aoi> --checkpoint <ckpt> --index 1 --out-dir data/predictions_2027
earthpv growth  --aoi <aoi> --current-pred-dir data/predictions_2027 \
                --preboom-pred-dir data/predictions ...                # see `growth --help`
earthpv export  --aoi <aoi> --exclude-mapped --min-distance-m 100
```

[Setting up a new country](reproduce.md) has the full command sequence.

## What one round costs

Measured on the 2026 runs, on one desktop with a 6 GB GTX 1060 and a home connection:

| Step | Rate | South Africa (3,647 cells) |
| --- | --- | --- |
| Compose | about 85 cells an hour, network-bound | about 2 days |
| Inference | about 1,300 cells an hour | 2 h 47 min |
| Building join, density, atlas | CPU only | about 1 h 15 min |
| Localized retrain | GPU | 16 h (only when new labels warrant it) |

The imagery is the long pole, and it is free. Nothing else needs re-downloading: label
tiles, building footprints and per-cell building counts are cached, and an atlas rebuild
from finished outputs takes seconds.

## Why each round is better than the last

- **The verified layer grows.** Hand-mapped installations count in Verified at their own
  outlines. Every lead a mapper confirms moves capacity from "model estimate" to
  "verified", and Best never falls below Verified in any cell.
- **The calibration sharpens.** The precision table is re-derived against a larger mapped
  reference each round. A guard refuses to overwrite a table carrying evidence the new
  one lacks, so a careless re-run cannot quietly downgrade it.
- **Localization pays off as labels accumulate.** With 452 held-out positive chips, South
  Africa's own model beat the general one clearly (pixel IoU 0.671 against 0.364); with
  seven and nine, Egypt's and Yemen's holdouts decided on four installations and on none.
  Mapping is what turns a country from the second case into the first.

- **What is measured widens.** Each newly completed calibration area refits the
  small-installation classifier and can widen the building-density band a figure is
  published in, and each local dataset found adds a register or statistic the atlas is
  drawn beside. Those are stations 4 and 5 of the [flywheel](how-it-works.md#workflow), and
  neither waits for new imagery.

## Checks that keep an update honest

- **The ship rule.** A retrained model ships only if it beats the current one on a
  held-out region; a tie goes to the local model.
- **The ground-perimeter screen.** A mapped park above 5 km&sup2; that the imagery shows
  unbuilt is not counted as capacity.
- **The plausibility gate.** `check-density` flags regions where ground-mount dwarfs
  rooftop or one cell carries a whole region.
- **Clean labels.** Each pull is clipped to the national border and stripped of
  solar-thermal plants, which share OpenStreetMap's solar tag but are not photovoltaic.
- **People in the loop.** After a national `roofclf` scoring, 20 random cells are checked
  against high-resolution imagery, and calibration areas are dated by the imagery they
  were mapped on.

## What is still manual

Verifying leads, mapping and certifying calibration areas, and signing off the random-cell
review all need people, by design. Each round is a per-country snapshot: there is no
combiner yet that merges countries or rounds into one global time series.
