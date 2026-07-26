# Scale to a new country

Pakistan is the first pilot, not the product. Nothing in the pipeline is Pakistan-specific:
every input is a global open dataset, and the model was trained in Germany before it was
ever pointed at Punjab. This page is the path from "we would like a solar map of X" to a
published capacity atlas for X.

The programme's stated next targets are Mexico, Japan, Korea, Indonesia, India, Brazil,
South Africa and Nigeria, and Gujarat in India is already registered as a worked template.
None of them require anything Pakistan required.

## What makes it portable

| Input | Source | Coverage |
| --- | --- | --- |
| Imagery | Copernicus Sentinel-2 L2A, via Planetary Computer or Earth Search | global, every five days, free |
| Labels | OpenStreetMap, via live Overpass or an Overture snapshot | global, wherever mappers have been |
| Building footprints | VIDA Open Buildings (Google and Microsoft) | global, imagery-derived, includes unmapped structures |
| Admin boundaries | geoBoundaries, CC-BY | global, ADM1 and ADM2 |
| Model | TerraMind-tiny, fine-tuned, checkpoint in the repository | reusable as-is for a first pass |

The one thing that is genuinely local is the **human mapping community**, and that is why
the first step below is not a command.

## Before you start: find the mappers

Detection produces leads. Leads only become data when somebody who knows the ground opens
them in the OpenStreetMap editor and decides. In Pakistan that was four interns at the
Lahore University of Management Sciences, and the difference they made is measurable: large-array
recall in Punjab went from 0.18 to 0.55 purely on training data their verification produced.

A run with no mapping community attached gives you a candidate file nobody will validate,
a recall number nobody can check, and a capacity estimate resting on a single global
calibration. Line up a local OpenStreetMap community, a university group, or an NGO first.
[Community](community.md) describes what that collaboration looks like.

## Step 0: preflight

`scripts/new_region.py check` probes all four data sources before you commit any network
time. It is read-only and takes a couple of minutes.

```bash
pixi run python scripts/new_region.py check \
    --bbox 98.5,7.8,101.0,10.2 --iso3 THA --name "Surat Thani"
```

```text
[  ok  ] OpenStreetMap solar labels  412 features {'generator': 301, 'plant': 111}
[  ok  ] VIDA Open Buildings  available remotely, 6.9 GB
[  ok  ] geoBoundaries ADM1  Thailand
[  ok  ] geoBoundaries ADM2  Thailand
[  ok  ] Sentinel-2 imagery  336 scenes under 40% cloud across 16 MGRS tiles, median cloud 19%
[  ok  ] Grid size  600 cells of 0.1 degree over 72,943 km2
```

What the four answers actually tell you:

**OpenStreetMap solar count.** Zero is not a blocker for detection, but it means you have
nothing to train on and nothing to measure recall against, so the capacity number will
carry the global calibration's uncertainty rather than a local one. Under about 50
features, plan on mapping a quadrat early. Country-scale bboxes usually time out on
Overpass; pass `--skip-osm` and query province by province instead.

**VIDA availability.** If the ISO3 code has no parquet, cell selection and the building
prior both fall back to Overture, which undercounts small and informal structures by two
to three orders of magnitude in exactly the places rooftop solar is growing fastest. Check
the code before concluding the country is missing.

**Imagery.** The composite is a median of the least-cloudy scenes in a window, so a wet
window gives a poor base. The default window tested is the northern dry season; adjust
`--window` for the southern hemisphere or a monsoon climate. If the check reports no scenes
under 40 percent cloud, pick a different window before anything else.

**Grid size.** A ceiling, not an estimate. Only building-populated cells get composited: in
Pakistan that was about 4,470 of roughly 62,000, and at one to two minutes per cell that is
the difference between a weekend and a month.

## Step 1: register the area

```bash
pixi run python scripts/new_region.py add \
    --aoi surat_thani --bbox 98.5,7.8,101.0,10.2 --iso3 THA \
    --division "Surat Thani" --subtype region
```

That appends a block to `configs/aoi.yaml`, refuses to clobber an existing area, and
re-parses the file so a malformed insert fails immediately rather than three stages later:

```yaml
  # Added by scripts/new_region.py. No source_region key, so chips and compose fetch
  # from Planetary Computer STAC rather than a local composite cache.
  surat_thani:
    bbox: [98.5, 7.8, 101.0, 10.2]
    division: { name: Surat Thani, country: TH, subtype: region, iso3: THA }
```

The absence of a `source_region` key is what routes everything through the open fetchers.
Areas that have one read a locally cached composite set instead, which is a shortcut
specific to the development machine and not something a new region needs.

!!! tip "Always set `iso3`"
    VIDA and geoBoundaries are both keyed on ISO3. The ISO2-to-ISO3 fallback in
    `buildings.py` only covers the countries that predate this script, so a new area
    without an explicit `iso3` will fail at the density stage rather than at setup.
    `new_region.py add` writes it for you.

## Step 2: get the runbook

```bash
pixi run python scripts/new_region.py plan --aoi surat_thani
```

This prints the ordered command sequence with the area's name, bbox and ISO3 already
substituted, including the `systemd-run` invocation for the long compose job. The rest of
this page explains the reasoning behind those commands.

## Step 3: first pass, no retraining

A first candidate set needs no local training data at all. The existing Germany-plus-Pakistan
checkpoint runs unchanged.

```bash
# labels from live OpenStreetMap
pixi run earthpv overpass-labels --bbox 98.5,7.8,101.0,10.2 --iso3 THA --name surat_thani

# imagery, building-populated cells only, hours and network-bound
systemd-run --user --collect --unit=earthpv-compose-surat-thani \
  -p WorkingDirectory="$PWD" bash scripts/compose_loop.sh surat_thani 0 1000

# detect, rank, export
pixi run -e ml earthpv infer --aoi surat_thani \
    --checkpoint data/models/v2_combined/terramind-pv-epoch=39.ckpt
pixi run earthpv postprocess --aoi surat_thani --threshold 0.3 --max-building-dist 30
pixi run earthpv export --aoi surat_thani --exclude-mapped --min-distance-m 100
```

`compose_loop.sh` takes the area name, an optional target cell count (0 means run until
compose finishes or stalls, which is what you want when the count is unknown) and the
cell-selection threshold. It restarts compose every 30 minutes so a fresh Planetary
Computer signing token replaces one about to expire mid-run.

Expect the first pass to be worse than Pakistan's. That is the domain gap, and it is the
thing the next two steps close.

## Step 4: map, and measure

This is the step that is easy to skip and expensive to skip.

**Send the leads out.** `export` writes a MapRoulette challenge sorted by rank. Mappers
verify against the high-resolution layers and map what is real, which both improves
OpenStreetMap and produces your training positives.

**Map one quadrat exhaustively.** Pick a 1 km<sup>2</sup> box in a built-up area and map
*every* installation inside it, following the
[quadrat protocol](calibration-mapping-protocol.md). This is the only instrument that
measures what the model **misses**. Leads tell you about candidates the model found;
they cannot tell you about the installations it never proposed. The Lahore box is the
reason the Pakistani recall estimate is now suspected of being optimistic, and it took
one afternoon.

**Review a calibration sample.** `earthpv calibrate-sample --aoi <area>` emits a
stratified sample of unmapped candidates for human verdicts. Twenty verdicts per size bin
replace a wide extrapolated interval with a measured one.

## Step 5: retrain in domain

Once mapping has produced local positives, the flywheel turns.

```bash
pixi run earthpv chips --aoi surat_thani
.pixi/envs/default/bin/python scripts/merge_chip_index.py germany surat_thani:2
pixi run -e ml earthpv train --config configs/terramind_pv.yaml
pixi run -e ml earthpv evaluate --aoi surat_thani --checkpoint <new checkpoint>
```

The `:2` oversamples the new area so Germany's much larger chip count does not swamp the
in-domain signal. Set `val_tiles` in `configs/aoi.yaml` to a geographically separate
cluster before trusting any recall number: a validation split that overlaps the training
cluster leaks through chip jitter and window overlap, and an empty `val_tiles` silently
falls back to a random 20 percent split.

## Step 6: capacity

```bash
pixi run earthpv calibrate-candidates --aoi surat_thani
pixi run earthpv density --aoi surat_thani --districts
pixi run earthpv atlas --aoi surat_thani
```

Without local calibration evidence the table marks itself `status: interim-mapped-only`
and the capacity number is an honest lower bound. That is a legitimate thing to publish as
long as you say so. Quadrats and manual review are what turn it into an estimate with an
interval. See [Calibration](methods/calibration.md).

## What to expect, by starting condition

| Your region has | First pass gives you | What to do first |
| --- | --- | --- |
| Dense OpenStreetMap solar already | Good recall, immediately useful leads | Retrain in domain; you have positives now |
| Some solar mapped, patchy | Moderate recall, many real new leads | Send leads out, map one quadrat |
| Almost nothing mapped | Low recall, unknown precision | Map a quadrat before anything else. Detection numbers are uninterpretable without one |
| A national PV register | The Germany situation | Calibrate against it, as `earthpv mastr` and `earthpv calibrate` do |

## Things that will differ from Pakistan

**Climate and the composite window.** A dry-season median is the right base in an arid
climate. In a wet tropical or high-latitude region the least-cloudy twelve scenes may still
be poor, and snow at high latitudes changes the background entirely. Test with
`new_region.py check --window` before composing.

**Roof type.** Pakistan's dominant urban roof is flat concrete, which is why the roof-axis
orientation prior [failed there](experiments.md) and why fitted panel tilts are bimodal. A
region of pitched tile roofs behaves differently, and some priors that failed in Pakistan
may work.

**Glint geometry is latitude-dependent.** Sentinel-2's overpass is at a fixed local time,
so the range of panel orientations that can ever glint into the sensor is a function of
latitude. The [Pakistani pose survey](results/pv-pose.md) could not observe anything west
of due south. A different latitude has a different blind sector, and the southern
hemisphere flips it.

**Installation size distribution.** The 400 m<sup>2</sup> floor bites hardest where
residential PV dominates. In a region of large commercial rooftops, per-object detection
covers far more of the capacity; in a region of 30 m<sup>2</sup> household systems, almost
everything falls to the [density stage](methods/density.md).

**Building data quality.** VIDA is imagery-derived and its completeness varies. Where it is
thin, the building prior weakens and `--max-building-dist` filtering gets riskier.

## Reusing the model itself

The checkpoint under `data/models/` is Germany plus Pakistan. For a region resembling
either, use it directly. For one that resembles neither, the ordering that worked here was:
train on the region with the best label quality available (Germany), infer on the target,
have people verify, retrain with the verified target-region chips oversampled. That
sequence, not a bigger backbone, is what moved the numbers.
