# Scaling EarthPV globally

!!! note "OPEN OPTION, under discussion (as of 2026-09-23)"

    Nothing on this page has been adopted. It records one proposal for taking EarthPV from a
    handful of countries to a global product maintained by TraceTheSun and its community, along
    with the measurements it rests on. Figures are as of 2026-09-23. Where a number is an
    estimate rather than a measurement, the text says so.

The question: how could EarthPV be scaled to every country as a community project,
maintained by [TraceTheSun](22072026-Concept-Note-TraceTheSun.md) and calibrated for each
country? Three narrower questions follow from it. Does every country need its own
calibration data? How should the data be stored? And what high-resolution imagery is worth
buying to validate an atlas that is meant as a good first estimate?

**The short answer: centralise the compute and let the community supply the evidence.**
Every country can get a published lower bound with no local calibration at all. A
calibrated central estimate with an honest uncertainty range does need local evidence in
every country, because none of the constants that set the number have transferred between
countries so far. That evidence can be much smaller than Pakistan's 30 quadrats, and where a
complete national register exists it does not have to be quadrats at all.

## What the running India and Vietnam jobs show

The Vietnam and national India runs were launched on 2026-09-23 as one unattended queue.
They are the first test of the pipeline at subcontinental scale.

- **Compositing cannot run from one workstation at global scale.** India has 25,553 cells
  with at least 1,000 buildings each.
    - The best sustained rate measured on this machine is about 57 cells per hour (Nigeria,
      after the provider-timeout fix). At that rate India alone takes about 19 days.
    - The link to Planetary Computer measured 2.3 MB/s when the run launched. At that speed
      India takes closer to 50 days. It is also queued behind Vietnam.
    - Each cell downloads about 410 MB to keep about 13 MB
      ([open question 18](open-questions.md)).
- **The world is probably 150,000-300,000 cells.** This is an extrapolation from the
  per-country counts, not a measurement: Pakistan 4,463, Germany 4,656, France 6,021,
  Nigeria 6,341, India 25,553. At 57 cells per hour that is 4-7 months of continuous
  compositing for each yearly update, moving 60-120 TB to keep 2-4 TB.
- **Inference is not the bottleneck.** It takes about 3 s per cell on the project's GTX 1060
  (1,396 Pakistani cells in 71 minutes), so about a week for the whole world on one old card.
- **India will be published as a lower bound from the segmentation model only**, the same tier
  as Gujarat. It has no calibration quadrats and no complete PV register.
- **India's home rooftop systems may look like France's, not Pakistan's.**
    - The median mapped array across Pakistan's 31 quadrats is **47 m²** (IQR 23-91 m²,
      16,035 polygons, 20% under 20 m²).
    - The median in France's hand-mapped communes is about 20 m². The small-roof classifier
      `roofclf` failed there: median fold AUC 0.710, against 0.868 in Pakistan
      ([France validation](methods/france-validation.md)).
    - India's PM Surya Ghar scheme caps its home-system subsidy at 3 kW, which is about
      17-20 m² at the project's module constants. If subsidised systems dominate, India's home
      rooftops are in France's regime.
- **Cell grids only line up for India and Vietnam.** Every country config names its 0.1°
  cells from its own origin.
    - India's origin (68.0, 6.7) and Vietnam's (102.1, 8.4) sit on the global 0.1° lattice.
    - Pakistan's origin (69.3405, 27.7090), inherited from Punjab, is 0.405 cells east and
      0.09 cells north of that lattice.
    - Germany, France, Nigeria and Zambia are also offset.
    - Cells on either side of a border therefore do not match, and the countries cannot be
      joined into one global product as they stand.

## Operating model: central compute, community evidence

| Who | Owns |
| --- | --- |
| **TraceTheSun core** | Compositing, inference, national scoring and atlas builds, run centrally; the model registry; the global grid; quality gates; versioned releases; buying imagery and negotiating its licences |
| **Country teams** (e.g. WIT/LUMS for Pakistan) | The country pack; mapping calibration quadrats; reviewing validation cells; local context; owning the national atlas page |
| **OpenStreetMap volunteers** | Mapping PV leads from the MapRoulette challenges that `export` already writes. Each round of new labels feeds the next local retrain |

Community members never need a GPU or a fast link.

**Composite next to the archive.** This is the route [open question 18](open-questions.md)
prices:

- Earth Search's `sentinel-cogs` bucket is in AWS `us-west-2`, and Planetary Computer's
  storage is in Azure West Europe. Reads in the same region are free and fast.
- Use one provider for each yearly update. Mixing them hands cells between providers and
  downloads them twice.
- The acceptance test before switching: build a few dozen cells of an existing country
  in the cloud and diff them byte for byte against the ones built on the workstation.

**One country pack per country, kept in git.** It holds:

- the country block in `configs/aoi.yaml` and its atlas config, `configs/atlas/<aoi>.yaml`
- the holdout region, chosen before training
- the source of the admin boundaries
- a register adapter, where a register exists
- the quadrat boundaries, each with its sign-off record: mapper, second reviewer, imagery
  layer and imagery capture date

Changes arrive as pull requests. CI runs the existing guards and adds two checks: quadrat
overlap, and a missing imagery date.

**Make random-cell review a gate on publishing.**

- `results/roofclf_random_validation_log.csv` holds 40 rows, all without a verdict. The
  2026-09-20 batch is not logged at all.
- So Pakistan's published 24,330 MWp currently rests on a rescoring nobody has reviewed.
- One maintainer cannot keep up with this. A community with a second-reviewer rule can.

**One model or many.** The current rule is to retrain for each country on its own OSM
labels and ship whichever model wins on that country's holdout.

- At 100 countries that means 100 checkpoints to maintain.
- A single model retrained each release on every country's labels combined is also trained
  on each country's own labels, so it meets the same rule if it wins every holdout.
- France's capped-corpus retrain (v6) showed that a smaller local corpus can do worse than
  either extreme. A combined corpus only grows.
- Worth measuring once the Vietnam (v9) and India (v10) checkpoints exist. The existing
  ship rule is the test.

## Does every country need calibration data?

**For the lower bound, no. For the central estimate, yes.** Two different calibrations are
involved, and they want different evidence
([mapping protocol](calibration-mapping-protocol.md)):

- **Precision of segmentation's own candidates** (≥ 400 m²): human verdicts on a sample of
  the model's candidates, spread across the size range (`calibrate-sample`, then
  `calibrate-candidates`).
- **The below-400 m² estimate**: small areas where every installation is mapped (Rule 1), or
  a complete register.

### Why the evidence has to be local

Every constant that sets the number has moved between countries, or within one:

| Measured | Where | Range |
| --- | --- | --- |
| Predicted / true adoption rate (`rate_ratio`) | Across Pakistan's quadrats | 0.2-5x |
| Module constant | France, register against hand-mapped communes | 0.150 kWp/m² against an assumed 0.180 |
| Ground-mount land constant | Two Zambian plants (a spot check, not a calibration) | 0.085 kWp/m² against 0.050 |
| Share of rooftop capacity below the 400 m² floor | Germany against France | 65.5% against a 17-31% bracket |
| Capacity per sub-36 kW unit | Across the French-German border | 5.34 against 10.41 kWp (1.95x) |
| `roofclf` median fold AUC | Pakistan against France | 0.868 against 0.710 |

The border result is the sharpest: array size is set by subsidy policy, not geography, so it
cannot be read off a neighbouring country.

### What does transfer, and only needs doing once

- the foundation model and the fine-tuning recipe
- `roofclf`'s ranking of roofs (ranking transfers across quadrats; absolute adoption rates do
  not)
- the pipeline itself
- the plausibility gates
- the glint geometry

### Three tiers of evidence

| Tier | Evidence | What gets published | Examples |
| --- | --- | --- | --- |
| 0 | OSM labels, and a segmentation model retrained on them | A lower bound | India, Vietnam, Nigeria, Zambia |
| 1 | A complete register with totals per municipality | Calibrated against the register, as [Germany](methods/mastr-validation.md) is, with no quadrats | Germany and France. Brazil's ANEEL distributed-generation register is in the [data registry](data-registry.md). Japan's per-municipality feed-in-tariff statistics are likely usable but unchecked |
| 2 | A random sample of dated high-resolution imagery, mapped completely | Coverage ratio, recall and calibrated density range, plus an independent validation | Pakistan, with the caveat that its quadrats were chosen by hand |

A register helps the two calibrations differently:

- Only a register that locates individual units (MaStR does at 30 kWp and above) gives the
  candidate-precision calibration.
- A register of municipal totals gives the aggregate calibration.
- Neither reaches below a register's own reporting threshold.

### Check array size before paying for quadrats

Measure the median array size first. Sources, cheapest first:

- kWp per unit from the register
- the subsidy scheme's caps
- a few km² of dated high-resolution imagery

`roofclf` works at Pakistan's 47 m² and fails at France's 20 m². The cutoff lies somewhere
between the two and has not been measured. A country near France's regime gets the register
route and a lower bound, not quadrats for `roofclf`.

### Sampling rules

- **Validation units must be a probability sample from a defined national frame.** Today's
  quadrats were chosen by hand, and adding more hand-picked quadrats cannot fix that
  ([open question 5](open-questions.md)). Calibration quadrats can still be hand-placed to
  widen the density range.
- **Use the atlas to design the sample.** Stratify by building density and weight the draw by
  the atlas's own predicted capacity. That puts the mapping effort where the capacity is, and
  keeps the national total estimable without bias through model-assisted estimation.
- **Keep adding units until the 90% range is narrow enough.** Pakistan's 30 hand-picked
  quadrats give -14% / +38% around its central estimate. That is the benchmark to beat.

## Storing the data

The principles:

- Don't store what can be recomputed cheaply from a public archive.
- Store everything that is expensive to recreate as immutable, versioned releases.
- Use cloud-native formats that can be queried in place.
- Key every table to one global grid, so countries join without seams.

| Asset | Scale (global, estimated) | Format | Where |
| --- | --- | --- | --- |
| Raw Sentinel-2 scenes | 60-120 TB moved per yearly update | Not stored; scene IDs recorded in STAC | Stays in the AWS / Azure archives |
| Composites | 2-4 TB per yearly update (about 13 MB per cell) | Cloud-optimised GeoTIFF, one STAC item per cell, tagged with provider, window and resampling | Object storage, ideally free open-data hosting (source.coop, which already hosts VIDA, or the AWS Open Data programme) |
| Probability rasters | Smaller (one 8-bit band) | Cloud-optimised GeoTIFF | Same |
| Candidates, grid cells, regions | GB | GeoParquet 1.1, partitioned by country, with a bbox column | Same; queried in place with DuckDB |
| Per-building scores | India alone is 527M buildings | Parquet keyed by geohash plus VIDA release, or by Overture GERS ID, with no geometry. VIDA has no stable building ID | Same |
| Models | One per release (or per country) | Checkpoint, plus a model card with each country's holdout scores | Hugging Face Hub, where TerraMind already lives |
| National releases | One per country per update | Atlas page, GeoParquet and a provenance manifest | Zenodo, with a DOI |
| Country packs, quadrats, calibration tables | MB | YAML / GeoJSON | Git, reviewed by pull request |
| Web maps | | PMTiles | Static hosting |

**The provenance manifest is what makes a release reproducible.** It records the code commit,
the checkpoint hash, the calibration-table hash, the composite epoch, provider and
resampling, the OSM snapshot date and the VIDA release. Two checkpoints behind published
figures have already vanished from disk, and a calibration table was once silently
overwritten. Content hashes in the manifest stop both from happening again. Today everything
lives on one workstation's disks.

## High-resolution imagery to buy

### Resolution: 30-50 cm

At 30-50 cm a 20 m² array covers 80-200 pixels.

- 1.5 m (SPOT-class) only resolves the arrays that free imagery plus OSM can already check.
- 3 m (PlanetScope) is too coarse for this.
- Choose 30 cm (WorldView-class, Pléiades Neo) where solar water heaters are common, India
  included. 381 of the 3,335 hand-mapped French features were solar thermal collectors, told
  apart on 20 cm imagery. That distinction is hard to make at 50 cm.
- Elsewhere, 50 cm (Pléiades, SkySat) is enough.

### The capture date matters more than resolution

Stale imagery is what blocked widening Pakistan's density range (Box 17 in the
[calibration boxes log](issues/pakistan-calibration-boxes.md)) and what makes rural
random cells unreviewable
([calibration imagery dating](issues/calibration-imagery-dating.md)).

- Buy archive imagery captured inside the Sentinel-2 composite window: India's is
  2025-11-01 to 2026-03-15.
- Ask for off-nadir under about 20° and cloud under 5%.

With dated imagery, a quadrat's "every visible panel mapped" sign-off refers to the same
date the satellite composite does. The caveat that precision is a lower bound, because the
mapping imagery is older, then goes away.

### Buy a sample, never whole countries

Archive orders usually carry a minimum area of about 25 km² per polygon, so design around it:

- Draw 10-15 random 5 × 5 km blocks per country, stratified and weighted as in the sampling
  rules above.
- Map randomly chosen km² inside each block completely. Keep the calibration squares and the
  validation squares separate.
- The rest of each block serves candidate-precision review.

### Rough cost

**Indicative only; get quotes.** Reseller list prices for 30-50 cm archive imagery have
typically been around USD 10-25 per km². New tasking costs more and has larger minimums.

- 250-375 km² per country comes to roughly USD 3-9k before discounts.
- The concept note's eight target countries would come to roughly USD 25-75k.
- Tier 1 countries need far less.

### Licence

- Standard single-user licences do not cover a group of volunteers. Negotiate a multi-user
  licence that explicitly allows the traced outlines to be published openly.
- Putting those outlines into OpenStreetMap needs the provider's explicit permission. Without
  it, keep the quadrats in TraceTheSun's own openly licensed calibration registry.

### Use free sources first

- National orthophotos, such as France's IGN 20 cm imagery (already used for the French
  communes) and many German states' open orthophotos.
- ESA's Third Party Missions programme, which grants research access to some commercial
  missions by proposal. Check the current mission list.
- Esri World Imagery Wayback, to screen capture dates before drawing a quadrat.
- For ground-mount, don't buy imagery at all. Check utility-scale plants against open
  inventories such as Global Energy Monitor's solar tracker and TransitionZero's Solar Asset
  Mapper, after checking their licences.

## Suggested first steps, starting with India

1. **Trial compositing in the cloud, next to the archive.** Build 200 India cells with the same
   provider, window and `nearest` resampling as the running job, and diff them against cells
   built locally. This settles throughput, cost and byte-identity in one step.
2. **Move to the global 0.1° lattice.** India and Vietnam are already on it. Re-grid the other
   countries the next time they are recomposited, since a country's composites must not mix
   grids or resampling modes.
3. **Check array size in India** before committing to Indian quadrats. Use dated imagery from
   inside India's composite window, in the four states whose district-level PM Surya Ghar
   figures are in the [data registry](data-registry.md): Karnataka, Maharashtra, Odisha and
   West Bengal.
4. **Use those district figures as a lower-bound cross-check, not a calibration.** They count
   only the subsidy programme, not every rooftop system.
5. **Clear the random-cell review backlog** as the first community task, and make it a gate on
   publishing.

## Related pages

- [TraceTheSun concept note](22072026-Concept-Note-TraceTheSun.md)
- [Setup New Country](reproduce.md#scale-to-a-new-country)
- [Calibration mapping protocol](calibration-mapping-protocol.md) and
  [Contribute a calibration area](contribute.md)
- [Calibration quadrats overview](methods/calibration-quadrats.md)
- [Validation against MaStR](methods/mastr-validation.md) and
  [against the French register](methods/france-validation.md)
- [Roofclf random-cell validation](methods/roofclf-national-validation.md)
- [Open questions](open-questions.md)
