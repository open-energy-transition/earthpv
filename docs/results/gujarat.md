# Gujarat capacity map (India)

Gujarat was registered as this project's first non-Pakistan AOI to prove the pipeline
runs anywhere Sentinel-2 flies, without any locally cached labels or building data (see
[Setup New Country](../reproduce.md#running-on-a-new-region)). This page is its first
capacity estimate, produced 2026-08-07 end to end from compose through the atlas below.

<div class="embed" markdown>
<iframe src="../../assets/interactive/gujarat_pv_atlas.html" title="Gujarat PV capacity atlas" loading="lazy"></iframe>
</div>
<p class="embed-note">
Interactive. Hover a cell for its value.
<a href="../../assets/interactive/gujarat_pv_atlas.html" target="_blank">Open full screen</a>.
</p>

!!! warning "Segmentation-only: no evidence atlas here yet"
    Gujarat has no calibration quadrats (0, against Pakistan's 17 Rule-1-complete ones),
    so neither `roofclf` nor the sub-400 m<sup>2</sup>/&ge;400 m<sup>2</sup>-rooftop-swap
    instruments described on the [Pakistan capacity page](capacity.md) exist for it. This
    is the segmentation-only atlas `earthpv atlas --aoi gujarat` produces with no
    `--sub400-*`/`--ge400-roof-cells` flags -- per this project's documented fallback,
    that is still the main workflow's output for a country with no mapped quadrats yet,
    not a lesser product, but it means every number below carries only segmentation's own
    (currently uncalibrated-for-Gujarat) precision, not the two-detector cross-check
    Pakistan's headline figures do.

## Headline

| | |
| --- | --- |
| **812.6 MWp** | Recall-uncorrected, precision-weighted total (`est_mwp_rc`, &ge;400 m<sup>2</sup>) |
| 197.0 MWp | of which rooftop |
| 615.6 MWp | of which ground-mount |
| 866 | installations hand-mapped in OpenStreetMap (129 rooftop, 723 ground, 14 unclassified) |
| 1,527 | 0.1&deg; cells composited and inferred (100% of the building-populated AOI) |

**"Recall-uncorrected" is the load-bearing caveat.** `est_mwp_rc` normally divides
detected area by a measured per-size-bin recall (the Horvitz-Thompson correction
Pakistan's own numbers use); Gujarat has no pipeline-independent mapped reference to
measure that recall against yet (no pre-pipeline OSM snapshot exists for India the way
`rooftopsenti`'s cache does for Pakistan/Germany, and no calibration quadrat has been
hand-mapped here), so `earthpv calibrate-candidates --aoi gujarat --recall-reference
none` was used deliberately -- `est_mwp_rc` degenerates to `est_mwp_cal`, precision-only,
with no recall inflation. That makes 812.6 MWp a **floor**, not a central estimate: every
one of Pakistan's own size bins has recall well under 100% (CLAUDE.md's Density stage
section), and there is no reason to expect Gujarat's is different. The precision table
itself is also `status: interim-mapped-only` (`p_unmapped = 0` in every bin, i.e. an
unmapped candidate is never credited as real) for the same reason -- no glint sample or
manual review has been done for this AOI yet.

**`check-density` passes with 3 suspect regions, 0 failing** (`data/predictions/gujarat/
density/plausibility.csv`): the AOI's bounding box spills slightly into four neighbouring
states/territories (Rajasthan, Madhya Pradesh, Maharashtra, Dadra and Nagar Haveli and
Daman and Diu), three of which show implausible ground:rooftop ratios on very small
absolute MWp (all below the plausibility gate's 50 MWp floor for that check, hence
`suspect` rather than `fail`) -- expected edge spillover, not a Gujarat-specific finding.
Gujarat state itself: 168.7 MWp rooftop, 596.3 MWp ground, ratio 3.5x, `suspect` (same
status Pakistan's own passing atlas carries for three of its provinces). 634 oversize
candidates (>100,000 m<sup>2</sup>, 250.4 km<sup>2</sup>) were excluded from capacity, the
same `postprocess.MAX_CANDIDATE_M2` cap Pakistan's pipeline uses.

## Segmentation checkpoint: an open provenance gap, not a silent substitution

**This atlas was NOT built with `v3_combined_india`**, the checkpoint the owner directed
this project to use for all future development (2026-08-07). Gujarat's compose + infer +
candidate-extraction had already been run in full (1,527/1,527 cells composited,
1,526/1,527 inferred, `candidates.parquet` with 4,816 rows) on 2026-07-12 -- three days
*before* `v3_combined_india` was even trained (2026-07-15/16). Re-running inference with
the directed checkpoint was not possible: **the `v3_combined_india` checkpoint file no
longer exists anywhere on this machine** (searched the full filesystem), and neither does
`v2_combined`, the checkpoint `configs/aoi.yaml`'s own Gujarat comment names as what was
used ("the existing Germany-trained checkpoint ... unchanged, same as the original
Punjab bootstrap"). Both were apparently cleaned up at some point after producing their
outputs, before this session. This atlas therefore uses whichever checkpoint produced
Gujarat's existing, already-complete candidates -- almost certainly `v2_combined` per
that comment, but this can no longer be verified against the weights themselves.

Practical consequence: treat this atlas as a **placeholder proof that the pipeline runs
end-to-end for Gujarat**, not as a like-for-like comparison with Pakistan's
`v3_combined_india`-based numbers. Re-running Gujarat's compose+infer with
`v3_combined_india` (or whatever checkpoint is current when someone next revisits this
AOI) and re-deriving from there is the natural next step; it was not done here because
the specific weights the owner asked for are not recoverable without a fresh training
run, which is a materially bigger undertaking than a re-inference pass and was judged
out of scope for finishing this session's work.

## Reproducing this map

```bash
# Compose + infer + postprocess had already been run for this AOI (see the checkpoint
# note above for why they were not repeated here). From candidates.parquet onward:
pixi run earthpv calibrate-candidates --aoi gujarat --recall-reference none
pixi run earthpv density --aoi gujarat --districts --force
pixi run earthpv check-density --aoi gujarat
pixi run earthpv atlas --aoi gujarat --out docs/assets/interactive/gujarat_pv_atlas.html
```

No `--sub400-*`/`--ge400-roof-cells` flags: those need calibration quadrats, which do not
exist for Gujarat yet. See
[Setup New Country](../reproduce.md#running-on-a-new-region) for what a quadrat-mapping
pass here would need, and [Capacity density](../methods/density.md) for what every metric
in `grid.geoparquet`/`meta.json` means.
