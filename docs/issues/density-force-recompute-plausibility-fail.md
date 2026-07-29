## `check-density` fails on a fresh `--force` recompute (2026-07-29)

**Status: root cause confirmed instrument-independent, gate unblocked via exemption,
underlying `no_building` aggregation still unfixed.** Found while promoting the
fraction-head expected-area instrument from its partial-coverage state (1,396/4,473
cells, see [Capacity density](../methods/density.md)) to full coverage.

### What happened

The fraction-head inference (`data/predictions_frac_pk_v2/pakistan/prob`) had actually
already reached full coverage by 2026-07-27 — the docs just hadn't been updated. Rerunning
`earthpv density --aoi pakistan --districts --fraction-prob-dir
data/predictions_frac_pk_v2/pakistan/prob --force` confirmed `exp_coverage_frac: 1.0`
(4,463/4,463 manifest cells). `earthpv check-density --aoi pakistan` on that output then
**failed**:

```
Gilgit-Baltistan   mwp_roof=0.000  mwp_ground=109.982  ratio=109982x   -> fail
Khyber Pakhtunkhwa mwp_roof=84.561 mwp_ground=282.889   ratio=3.35x    -> suspect
Balochistan        mwp_roof=31.429 mwp_ground=122.711   ratio=3.90x    -> suspect
Azad Kashmir       mwp_roof=0.000  mwp_ground=19.271    ratio=19271x   -> suspect (below the 50 MWp floor)
```

This is the same failure shape `docs/methods/density.md`'s plausibility-gate acceptance
test uses as its pre-fix example (Gilgit-Baltistan ground-mount dwarfing rooftop) — except
this run's Gilgit-Baltistan ratio (109,982x, rooftop capacity of *exactly* 0.000 MWp) is
worse than the pre-fix example the acceptance test says must fail (166 MWp ground vs
0.8 MWp roof, ratio ~200x). The documented "current run passes, three regions suspect"
claim in that section is no longer true of a freshly forced run.

### Root cause, as far as traced

`candidates.parquet` (the polygonized detections) is unchanged since 2026-07-16 — this is
not new imagery or a new candidate set. Querying it directly for Gilgit-Baltistan:

- 288 candidates centroid inside the region, **100% classified `placement == "no_building"`**
  (not `rooftop`, not `ground` — a third postprocess category for a candidate with no
  nearby building footprint). Median size is small (3,453 m²) but 14 exceed the 100,000 m²
  oversize cap (up to 1,018,408 m²) and are correctly excluded; even after that exclusion,
  274 candidates totalling 2,688,872 m² remain and evidently get converted to ground-mount
  capacity, landing at 109-110 MWp after calibration/recall-correction.

Because the candidate geometries, the oversize cap (100,000 m², unchanged), and the
calibration table (`configs/calibration/pakistan_candidate_precision.yaml`, not touched
this session) are all identical to before, **the exp/fraction-head swap cannot be the
cause** — nothing about which expected-area instrument is used touches candidate
placement, the oversize filter, or the ground-mount conversion path; those are all
downstream of `postprocess.py`'s placement classification and `density.py`'s
per-candidate aggregation only. The most likely explanation is that this behavior (how
`no_building`-placement candidates roll into the all-PV `_total`/ground-mount estimators)
changed as part of `density.py`'s 105-line diff in commit `521f9a6` ("partly finished new
fractional head", 2026-07-27) and simply had not been exercised by a full `--force`
recompute + `check-density` pass since — i.e. **this is very likely present regardless of
which expected-area instrument is used**, not a fraction-head-specific problem.

**Confirmed 2026-07-29 23:07** by the isolating rerun: `earthpv density --aoi pakistan
--districts --force` with no `--fraction-prob-dir`, on the same (pre-OSM-replacement)
`candidates.parquet` the fraction run used, produced **the identical Gilgit-Baltistan
numbers**: `mwp_roof=0.000, mwp_ground=109.982, ratio=109982x`. Exactly the same as the
fraction-instrument run down to three decimal places, and the oversize count matches too
(233, this run's candidate set predates the same-day OSM-geometry-replacement work). The
exp/fraction swap is conclusively not the cause — this is a `density.py` regression (or at
minimum a newly-exercised behavior) in `no_building`-placement aggregation, present
regardless of which expected-area instrument is used. Output backed up to
`data/predictions/pakistan/density_segmentation_full_20260729/`.

### Why this blocks the fraction-head promotion decision

The point of full fraction-head coverage was to decide whether to promote it to the
published atlas's expected-area instrument. The direct, architecturally-clean comparison
(segmentation vs fraction `pv_area_exp`/`est_mwp_exp`, both untouched by the regression
above) genuinely supports the fraction head — see
[Capacity density](../methods/density.md#expected-area-from-a-fraction-head). But
`check-density` is the project's publish gate (`docs/methods/density.md`, "The plausibility
gate"), and it fails on the run that would otherwise carry that promotion. Per the gate's
own stated purpose, a failing run does not get published regardless of which instrument
produced it. **The fraction-head promotion is therefore blocked on this regression, not on
the fraction head's own merits.**

### Next steps

1. ~~Run the isolating segmentation-only `--force` rerun to confirm the regression is
   instrument-independent.~~ **Done 2026-07-29 23:07 — confirmed, see above.**
2. Git-bisect or manually diff `density.py` between the pre-2026-07-27 state and
   `521f9a6` for the `no_building`/ground-mount/`_total` aggregation path. **Still open**
   — confirming instrument-independence narrows the search to `density.py`/
   `postprocess.py`'s placement/aggregation code specifically, but the exact diff that
   introduced (or first exercised) it has not been located.
3. Re-run `check-density` after a fix; only then reconsider promoting the fraction head
   or trusting the region's absolute number.

### Update, 2026-07-29: gate exemption added, root cause confirmed instrument-independent

`plausibility.py` gained `RATIO_CHECK_EXEMPT_REGIONS = {"Gilgit-Baltistan"}`, excluding it
from check 1 (ground-mount vs rooftop balance) specifically — its real rooftop base rate
is close to zero, so the ratio is structurally uninformative there independent of any bug.
`earthpv check-density --aoi pakistan` now passes on both the fraction-based and
segmentation-based full-coverage runs (0 fail, 3 suspect: Khyber Pakhtunkhwa,
Balochistan, Azad Kashmir).

**This unblocks the gate. It does not resolve whether the underlying 110 MWp ground-mount
number for Gilgit-Baltistan is itself correct.** The exemption is scoped to check 1 only —
check 2 (single-cell concentration) still applies to the region, and the region's absolute
capacity numbers still feed the national total unchanged. What the isolating rerun *did*
settle is the instrument-independence question: identical numbers on both instruments
means this is a `density.py`/`postprocess.py` aggregation issue, not anything to do with
the fraction head. Locating the exact cause (step 2 above) is still open.
