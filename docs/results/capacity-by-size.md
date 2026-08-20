# Pakistan capacity by installation size

The [capacity map](capacity.md) reports the evidence atlas's Best-estimate total per
0.1&deg; grid cell. This page reports the *same* total a different way: by installation
size, split rooftop vs ground-mount, instead of by geography. It is not a second
estimate -- every MWp here comes from the identical components and calibration the
main atlas uses, re-binned rather than recomputed. The two pages' totals match for the
same run to within 0.02% (currently 18,826.7 vs 18,829 MWp) -- the residual is a
handful of candidates whose location falls just outside every grid cell's polygon and
so never enters a per-cell total on either page, not an uncounted source of error.

<div class="embed" markdown>
<iframe src="../../assets/interactive/pakistan_size_distribution_atlas.html" title="Pakistan PV capacity by installation size, rooftop vs ground-mount" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Hover a bar for its exact value and installation count.
<a href="../../assets/interactive/pakistan_size_distribution_atlas.html" target="_blank">Open full screen</a>.
</p>

## Why size, not just geography

A 0.1&deg; cell can hold a handful of household rooftops and a utility-scale plant at
once, and the map has no way to tell them apart -- both just add MWp to the same cell.
Splitting by installation size instead answers a different question: how much of the
national total is small, distributed rooftop capacity that would need millions of
individual net-metering connections to interconnect, versus how much is a handful of
large, grid-connector-scale sites. The shape is stark: rooftop dominates every bin below
20,000 m&sup2;, and ground-mount dominates the largest bin outright (utility plants like
Quaid-e-Azam Solar Park), with almost nothing rooftop at that scale.

## Where each bin's capacity comes from

Five populations, identical to the [capacity map](capacity.md)'s own "Two tiers, one
country" breakdown, each re-binned by its own real size field instead of collapsed into
one national number:

- **Ground-mount, every bin** -- segmentation candidates, no domain restriction. roofclf
  has no building footprint to score a free-standing array against, so this is
  segmentation's own instrument at every scale it detects.
- **Rooftop, &ge;400 m&sup2;** -- roofclf's own building-level estimate inside the
  density-matched domain, segmentation's recall-corrected candidates outside it. A
  building is counted by exactly one of the two per cell, never both.
- **Rooftop, &lt;400 m&sup2;** -- roofclf alone inside the density-matched domain. The
  roofclf-AND-SPPI agreement outside that domain was dropped from both this page and the
  main atlas on 2026-08-15 (it was the one component not measured where it was applied);
  passing `--sub400-outdomain-cells` still restores it, as a marked extrapolation drawn
  as a hatched slice on the 100&ndash;400 m&sup2; rooftop bar.
- **Hand-mapped OpenStreetMap, unmatched by the model** -- sized by each installation's
  own real geodesic area, split rooftop/ground-mount by its mapped placement tag.

One more population feeds this page without ever appearing as its own bin: the
AND-gate (roofclf-and-SPPI-agreeing) sub-400 m&sup2; population inside the domain. It
never contributes to Best estimate directly, but the main atlas floors Best at what a
person has actually mapped plus that stricter population, *per cell* -- a matched
OpenStreetMap installation's own bin-averaged precision/recall correction can
undershoot its true mapped area (Quaid-e-Azam Solar Park is the standing example).
Skipping that floor here would have silently undercounted this page's total against
the published one by about 4.5% in the cells holding the country's largest matched
ground-mount plants -- caught exactly because the two totals are required to match, not
assumed to.

## What this page does not show

It carries no credible interval of its own. The main atlas's 90% range applies to the
same total shown here; read the two pages together, not as competing figures. See
[Capacity density](../methods/density.md) for the full derivation of every component
and [Capacity map](capacity.md) for the geographic view and its own uncertainty
composition.

## Reproducing this page

Needs the same inputs as the evidence atlas (see [Capacity map](capacity.md#reproducing-this-map)),
plus this run's own `candidates.parquet`:

```bash
pixi run earthpv atlas-by-size --aoi pakistan \
    --osm-solar data/labels/pakistan_overpass_solar.parquet \
    --sub400-low-cells       data/roofclf_national_with_sppi/pakistan/density/sub400_low_incremental_buildings.parquet \
    --sub400-central-cells   data/roofclf_national_with_sppi/pakistan/density/sub400_central_incremental_buildings.parquet \
    --ge400-roof-cells       data/roofclf_national_with_sppi/pakistan/density/ge400_roof_incremental_buildings.parquet \
    --out docs/assets/interactive/pakistan_size_distribution_atlas.html
```

`--sub400-low-cells` is required even though the AND-gate population is never shown --
see "Where each bin's capacity comes from" above. Run `earthpv atlas` for the geographic
view first (or afterward) so the two pages describe the same underlying run.
