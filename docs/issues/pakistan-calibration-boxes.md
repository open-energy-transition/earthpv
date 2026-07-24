## Ground-truth calibration boxes

Small, hand-verified areas where *all* rooftop PV has been mapped from high-resolution
imagery (not just OSM's usual partial coverage) — fetched fresh via `earthpv
overpass-labels --bbox` rather than the Overture snapshot, since a just-finished mapping
pass won't be in Overture for weeks/months. Unlike the country-wide `mapped_frac` used by
`capacity_calibration`/`configs/calibration/<aoi>_candidate_precision.yaml` (which only
measures **precision** — is an existing candidate real — because it can only check
candidates that exist), a fully-mapped box is small enough to check **recall** too: every
real installation is known, so a candidate-free patch of the box is a genuine miss, not
just "unmapped."

### Box 1 — Lahore, 1km x 1km around (31.4633307, 74.4045096) — 2026-07-22

bbox `74.399244,31.458839,74.409775,31.467822` (`data/labels/lahore_calib_1km_overpass_solar.parquet`).

**Ground truth:** 8 rooftop installations, all clustered in one corner of the box
(74.409-74.410, 31.467-31.468), 314-577 m2 each — reads as one small residential/
commercial development where each unit got its own rooftop array, not 8 independent
sites.

**Our candidates (pk16085) in/near the box:** exactly 1, a 2702 m2 / confidence 0.49 /
rank_score 0.39 rooftop candidate ~335m from the box center. Checked against a widened
2km search: the closest any candidate gets to any of the 8 real installations is 877m —
not a geometry-offset artifact, a genuine miss.

**Result: 0/8 recall, 1 likely false positive.**
- The model missed all 8 real installations. Each is well below this project's
  ≥1000 m2 recall-first design target (README/CLAUDE.md) — consistent with, and now a
  direct empirical confirmation of, the known operating point rather than a new bug.
  Doesn't mean small arrays are unrecoverable, just that they're outside what this
  checkpoint was tuned to prioritize.
- The one candidate found in the box is nowhere near any of the 8 confirmed
  installations. Since this box's OSM mapping is asserted complete, a real PV array at
  that location would already be in the fetch — it isn't, so this candidate is very
  likely a false positive. One useful confirmed-FP data point for the `1k-5k` bucket
  (currently `p_real=0.149` in the interim-mapped-only calibration table).

**Update (2026-07-23): this box now feeds the calibration pipeline, not just this doc.**
`earthpv calibrate-candidates` gained `--calibration-box <parquet>` (repeatable):
it pools a box's per-bin (installations, matched-by-any-candidate) counts directly into
the same `recall_reference` denominator the country snapshot already builds, before the
existing Beta-posterior machinery runs — so a quadrat's TRUE-recall evidence (every
installation known, unlike the snapshot) moves the recall estimate and its credible
interval by exactly as much as its sample size supports, automatically, no separate
code path. Re-ran for Pakistan with this box pooled in:

```
earthpv calibrate-candidates --aoi pakistan --pred-dir data/predictions_pk16085 \
    --glint-sample data/glint/pakistan_candidate_glint_sample.csv \
    --calibration-box data/labels/lahore_calib_1km_overpass_solar.parquet
```

| bin | recall before | recall after | 90% CI before | 90% CI after |
|---|---|---|---|---|
| 100-500 m² | 96/164 = 58.5% | 96/170 = 56.5% | [52.0, 64.5] | [50.1, 62.4] |
| 500-1k m² | 270/367 = 73.6% | 270/369 = 73.2% | [69.7, 77.2] | [69.3, 76.8] |

National `est_mwp_rc` moved +0.001% — negligible, and correctly so: n=8 against a
~2,800-installation country snapshot genuinely can't move a country-scale estimate much,
exactly as this doc originally predicted. What changed is that the pipeline now HAS a
mechanism ready to matter as more of the mapping protocol's planned 25-35 quadrats land
(`docs/calibration-mapping-protocol.md`) — each new box is one more `--calibration-box`
flag, no code changes needed. The precision side (`mapped_frac`/`p_real`) is genuinely
unaffected here (no candidate sits near these 8 features, confirmed above), by design:
`--calibration-box` only ever feeds recall, the same separation `capacity_calibration.py`
already draws between precision and recall evidence.

One qualitative flag worth carrying forward even though n=8 can't prove it: this box's
TRUE recall (0/8) sits well below the country-snapshot recall in the same size bins
(58-74%) — consistent with the snapshot itself being an incomplete, and possibly biased,
sample of real installations (a mapper is more likely to have mapped exactly the
installations a model also finds easiest to detect). More quadrats will tell us whether
that gap is real or n=8 noise.

### Direct density-method validation against Box 1 (2026-07-23)

Location confirmed by reverse-geocode: **DHA Phase V, Lahore** — exactly the mapping
protocol's stratum 1 ("affluent planned housing... highest rooftop-PV adoption"). Boundary
saved as `data/labels/lahore_calib_1km_boundary.geojson`.

Beyond the candidate-level recall check above, this checks `density.py`'s actual per-pixel
and per-building output against the same 8 installations (true total **3,145.8 m²**),
pulling the raw probability raster (cell `0135_0077`) and `buildings.geoparquet` directly —
the same artifacts `density` ships, not a re-derived approximation.

**At the 8 true installation footprints, the model's raw pixel probability is exactly
0.000 — at every one, not just below threshold.** This is a stronger and more concerning
finding than "recall is low": it means `pv_area_exp` (the metric whose entire premise is
integrating *sub-threshold* signal) has nothing to integrate here — these installations
aren't faintly visible and miscalibrated, they produce no model activation at all. All
three building-level metrics are therefore zero at every one of the 8 true locations:
`pv_area_det = pv_area_cal = pv_area_exp = 0`.

**Meanwhile the box's only signal is a false positive, elsewhere.** One candidate
(2,701.9 m², rooftop, confidence 0.49) sits 877 m from the nearest real installation —
`density.py` correctly attributes it to 9 nearby (wrong) buildings:

| metric | total in the false-positive cluster | true total (8 real installations) |
|---|---|---|
| `pv_area_det` | 2,281.0 m² | 3,145.8 m² |
| `pv_area_cal` | 340.6 m² | — |
| `pv_area_exp` | 1,241.4 m² | — |

**The trap this exposes:** naively summing "PV area estimated in this box" gives
~1,200-2,300 m² — deceptively close to the true 3,145.8 m², entirely by coincidence.
Every square metre of it is misattributed; the aggregate number would look roughly right
while being 100% spatially wrong. A cell/region-aggregate sanity check (as the density
stage's grid/region layers necessarily are) cannot catch this; only a fully-mapped,
building-level ground truth like this box can.

**Implication for `est_mwp_rc` (recall-corrected estimator):** the recall correction
(dividing calibrated candidate area by a size-bin's country-average recall, ~56-73% for
100-1k m²) is a *population-level* correction — it is only unbiased in expectation across
many neighbourhoods whose true recall averages out to the country figure. This box is a
direct counterexample at the neighbourhood scale: its true recall is 0%, not 56-73%, so
`est_mwp_rc` for a query scoped to just this box (or a similar single neighbourhood) would
still be far too low — recall-correction repairs the *national* total, it does not make
any single building- or neighbourhood-level number trustworthy. Worth stating explicitly
wherever `est_mwp_rc` is surfaced at sub-national granularity.

Net read on this one box: 0/8 recall, confirmed at both the candidate-polygon level
(above) and now the raw-probability level (this section) — the model is currently blind,
not just imprecise, in the exact stratum (affluent planned housing, 300-600 m² rooftop
arrays) the mapping protocol calls the highest-adoption one. That's the single most
useful thing a first calibration box could have told us.

### Correction (2026-07-23, later same day): the 8-feature snapshot was stale AND flawed

Prompted by a direct "have you pulled the newest labels for this?" check — good catch,
because the answer was no, and it mattered. Re-fetching this exact bbox live via
`earthpv overpass-labels --bbox 74.399244,31.458839,74.409775,31.467822 --iso3 PAK`
returned **1,021 features (52,188.9 m² true PV area)**, not 8 (3,145.8 m²). Comparing
geometries: 2 of the original 8 (both exactly 314 m², same OSM way IDs) are unchanged;
the other 6 have been **replaced by clusters of much smaller polygons 3-20 m away**
(areas now 8-95 m² instead of 314-577 m²) — i.e. the original mapping pass traced whole
roofs for those 6, not individual panels, exactly the "Common failure mode" the
protocol's Rule 1 warns about, and a second, more careful pass has since fixed it. The
section above and the earlier calibration-table update both used the stale, partly-wrong
file — corrected below. New size distribution: 882 installations <100 m², 138 in
100-500 m², 1 in 1k-5k m², none larger. **Everything above this point in the file
describes the superseded 8-feature analysis; treat the numbers below as current.**

**Recall, recomputed on the corrected 1,021-installation ground truth:**
- Within 100 m of any candidate: 40/1,021 (3.9%) — all 40 attributable to the SAME one
  candidate (2,701.9 m², rooftop, confidence 0.49), which sits in/next to a dense cluster
  of small installations, not scattered across the box.
- Literal polygon intersection: only 2/1,021 (0.2%).
- **Raw pixel probability at the true footprints: nonzero for exactly 2/1,021** (the
  same 2 the candidate literally overlaps) — 1,019/1,021 (99.8%) installations still
  show *exactly* 0.000 probability. The core finding survives correction, just more
  starkly: near-total blindness, not literal-zero-of-everything. `pv_area_exp` recovers
  571.7 of 52,188.9 m² true (1.1%) — nonzero this time, but still capturing almost none
  of the true signal.
- **This reverses the earlier "false positive, 877 m from nearest install" read on the
  one candidate**: against the corrected ground truth its nearest real installation is
  **0.0 m away** (it literally overlaps one). The candidate is better read as a coarse,
  unresolved detection of a genuine dense small-array cluster — the model correctly
  flagged that *something* PV-related is happening there, it just can't resolve the
  ~40 individual panels into separate polygons. Different lesson than "spurious FP
  elsewhere in the box": this is a resolution failure on a real signal, not hallucination.

**Calibration table impact (`--calibration-box`, corrected file) — now genuinely
consequential, unlike the first (stale) pooling:**

| bin | recall before any box | after stale 8-feature box | after corrected 1,021-feature box |
|---|---|---|---|
| <100 m² | 0/142 (0%) | 0/142 (0%, box had none this size) | **34/1,024 (3.3%)** |
| 100-500 m² | 96/164 (58.5%) | 96/170 (56.5%) | **101/302 (33.4%)** |
| 1k-5k m² | 1152/1296 | 1152/1296 | 1153/1297 (negligible) |

The <100 and 100-500 bins moved for real this time — n=882 and n=138 from one quadrat
are not negligible next to the country snapshot's own n=142/n=164 there. National
`est_mwp_rc`: 18,309.5 → 18,312.0 MWp (+0.014%, still small — these bins hold little of
the country's total capacity — but the *interval* widened more meaningfully, 90% CI
[17,065, 21,318] → [17,021, 21,400]).

**Lesson for the mapping protocol itself:** a "done" quadrat should be spot-checked
against a fresh Overpass pull before it feeds any calibration, even hours after
completion — mapping is iterative (the two-mapper completeness pass is designed to add
exactly this kind of correction), and a calibration mechanism now exists that will
silently encode whatever was cached at pull time as ground truth.

---

### Box 2 — Faisalabad, 1km x 1km around (31.4976169, 73.0523711) — 2026-07-24

bbox `73.047103,31.493125,73.057639,31.502108` (`data/labels/faisalabad_calib_1km_overpass_solar.parquet`,
boundary `data/labels/faisalabad_calib_1km_boundary.geojson`). Reverse-geocode: **Punjab
Small Industries Estate, Faisalabad Sadar Tehsil** — the mapping protocol's **stratum 6
(industrial zone)**, which names Faisalabad as an example location directly.

**Status: NOT a Rule-1-verified quadrat.** This is a live OSM pull, not an
exhaustively-mapped completeness pass — no second-mapper declaration, no imagery-date
record. Documented here as a useful interim data point; do not fold into
`calibrate-candidates --calibration-box` until it's been through the same completeness
process as Box 1.

**Ground truth (as currently mapped):** 53 installations, all tagged `plant:source=solar`
(deliberate ground-mount/captive-plant tagging, not an ambiguous-generator fallback),
63,501 m² total. Sequential OSM way IDs (1498181449–1498181511) — one mapping pass.
Size range 193–4,722 m² (median 922 m², mean 1,198 m²) — squarely in the model's
designed ≥500 m² strength zone, unlike Box 1's sub-100 m² residential cluster.

**Candidate recall (pk16085): 53/53 (100%) within 100 m, 34/53 (64.2%) literal
intersection** — a sharp contrast with Box 1's 0.2%/3.9%. Consistent with size:
these installations sit well inside the range the model was tuned for. One thing worth
a second look later: several nearby candidates are much larger than any single true
installation here (up to 64,997 m² and 58,697 m², vs. a 4,722 m² true max) — plausibly
the model merging a dense cluster of adjacent ground arrays into fewer, larger candidate
polygons rather than resolving them individually; not confirmed, just flagged.

### Box 3 — Multan, 1km x 1km around (30.1262242, 71.3829068) — 2026-07-24

bbox `71.377714,30.121733,71.3881,30.130716` (boundary
`data/labels/multan_calib_1km_boundary.geojson`; no labels parquet — see below).
Reverse-geocode: **Multan Industrial Estate, Thati Lal, Multan Sadar Tehsil** — also
stratum 6 (industrial). Sits inside the `pakistan` AOI's `val_tiles` holdout region
(`configs/aoi.yaml`, the Multan cluster used for the model's own validation split).

**Live Overpass pull returned zero `generator:source=solar`/`plant:source=solar`
features.** This is explicitly **not** usable as a "0 installations, 0 recall"
ground-truth point: per Rule 1 of `docs/calibration-mapping-protocol.md`, a quadrat with
no completeness declaration is indistinguishable between "genuinely no PV here" and
"nobody has mapped this area in OSM yet" — treating an unmapped area as a confirmed
negative is exactly the failure mode the protocol calls out as worse than leaving a
quadrat out entirely. Flagged as an **open mapping task** (industrial zone, Multan,
overlapping the model's own val split — a high-value quadrat to complete), not a result.

**Both boxes' honest status:** neither has been through a human high-res-imagery
completeness pass. Box 2's plant-tagged, sequential-ID mapping looks like a deliberate,
consistent single pass (a good sign, same pattern the corrected Lahore mapping eventually
showed) but that is circumstantial, not a substitute for the protocol's actual
two-mapper sign-off. Treat both as candidates for the mapping team's queue, not
finished quadrats, until that happens.

### Box 4 — Sundar Industrial Estate, Lahore, 1km x 1km around (31.2861646, 74.1720942) — 2026-07-24

bbox `74.166838,31.281673,74.17735,31.290656`
(`data/labels/sundar_calib_1km_overpass_solar.parquet`, boundary
`data/labels/sundar_calib_1km_boundary.geojson`). Reverse-geocode: **Sundar Industrial
Estate, Raiwind Tehsil, Lahore District** — stratum 6 (industrial) again, a third
industrial box alongside Faisalabad and Multan.

**Status: NOT a Rule-1-verified quadrat** (same caveat as Boxes 2/3 — live pull only,
no completeness declaration).

**Ground truth (as currently mapped):** 38 installations, 72,561 m² total, mixed tagging
(20 `plant`/18 `generator`, 23 ground/15 rooftop by placement) and **non-sequential**
OSM way IDs spanning several ID ranges — unlike Faisalabad's single contiguous pass,
this looks like several separate mapping sessions over time. Size range 76.7–6,579.7 m²
(median 1,658 m²) — again squarely in the model's designed strength zone.

**Candidate recall (pk16085): 33/38 (86.8%) within 100 m, 26/38 (68.4%) literal
intersection.** The 5 misses are all at or below 999 m² (76.7, 103.8, 254.4, 722.8,
999.4 m²) — consistent with the model's known size-dependent recall falloff, not a
surprise. A third data point reinforcing the same pattern as Box 2: this model performs
reasonably well once installations clear roughly the 1,000 m² mark, regardless of
industrial vs. residential context; the failure mode found in Box 1 is specifically
about very small (<500 m²) arrays, not industrial siting per se.

---

### Box 5 — SITE Karachi, 1km x 1km around (24.9070005, 66.9941461) — 2026-07-24

bbox `66.989194,24.902509,66.999098,24.911492`
(`data/labels/site_karachi_calib_1km_overpass_solar.parquet`, boundary
`data/labels/site_karachi_calib_1km_boundary.geojson`). Reverse-geocode: **Sindh
Industrial Trading Estate (SITE), Rashid Abad, SITE Town, Kemari District, Karachi** —
stratum 6 (industrial), and the mapping protocol's explicit Karachi example. First
non-Punjab box.

**Ground truth (as currently mapped):** 67 installations (53 rooftop/14 ground),
115,843 m² total, median 1,110 m².

**Candidate recall (pk16085): 67/67 (100%) within 100 m, 60/67 (89.6%) literal
intersection.**

---

## Visual verification pass (2026-07-24) — what this is and is NOT

Prompted by a direct request to bring all boxes to Rule-1-verified status. **Important
scope note, stated plainly: this pass does not achieve that.** Rule 1
(`docs/calibration-mapping-protocol.md`) requires every visible panel traced to polygon
precision AND an independent second human mapper's sign-off, with a dated completeness
declaration. What follows is a single systematic visual pass by Claude against live Esri
World Imagery (fetched via the public ArcGIS `World_Imagery/MapServer/export` REST
endpoint, no API key, capture date not exposed by this endpoint so recorded as
"unknown" per the protocol's own allowance), reading each exported image directly. That
is real, substantive evidence — a genuine plausibility/completeness check against
imagery, not just trust in existing OSM tags — but it is **one AI pass, not two
independent human mappers**, and it produces approximate location/plausibility
judgments, not precise digitized polygons. None of these boxes should be described as
"Rule 1 verified" on this basis. Treat this as a strong prioritization signal for the
actual mapping team, not a substitute for their sign-off.

**Method:** fetched a ~1024x1024–2048x2048 export per box (~0.35–0.5 m/pixel — enough to
resolve individual rooftop panel-grid texture, confirmed by cross-checking specific
claimed installations' exact centroids against the image), plus quadrant crops and
targeted zooms on the largest claimed features per box.

**Findings, box by box:**

- **Box 1 (Lahore DHA):** Confirmed. A close crop of the known-dense NE corner shows
  dozens of distinct small dark-panel-grid rooftops scattered through the residential
  blocks — visually consistent with the corrected 1,021-installation dataset (already
  established via the OSM re-pull earlier this session).
- **Box 2 (Faisalabad):** **Not confirmed — a real discrepancy.** The single largest
  claimed installation (`osm-way/1498181472`, 4,722 m², tagged `plant:source=solar`) is
  absent from the imagery at its exact stated centroid (31.499789, 73.051969) — ordinary
  small rooftops, no large dark array. The general area also doesn't show the kind of
  obvious large ground-mount arrays the claimed size distribution (median 922 m², all 53
  tagged `plant`) would predict, unlike the unambiguous large arrays visible in Boxes 3-5.
  **Recommendation: do not trust this box's labels without independent re-verification —
  possible bad tagging/import, not necessarily "the model is wrong."**
- **Box 3 (Multan):** **Confirmed absent from OSM, confirmed present in reality** — the
  single most important finding of this pass. All four quadrants show multiple large,
  unambiguous rooftop solar arrays with clear panel-row texture (one in the SE quadrant
  alone is easily several thousand m², with crisp visible panel rows). Roughly a
  dozen-plus plausible installations visible total. This resolves last turn's stated
  ambiguity definitively: **not a solar-free estate, just an unmapped one.** Highest-value
  quadrat for the mapping team to complete next — real signal is sitting there unmapped,
  and it sits inside the model's own `val_tiles` holdout.
- **Box 4 (Sundar):** Confirmed. Roughly 10-15 large, clearly grid-textured rooftop
  arrays visible across the estate; the three largest claimed installations checked
  against their exact centroids correspond to real visible arrays in the same cluster of
  buildings.
- **Box 5 (SITE Karachi):** Confirmed, most visually dense of all five boxes — dozens of
  clear rooftop arrays visible across nearly every block, strongly supporting (if
  anything, suggesting the true count could be even higher than) the claimed 67.

**Net effect on box status:**
- Boxes 1, 4, 5: visual pass materially increases confidence but does not constitute
  Rule-1 sign-off. Still recommend NOT pooling 4/5 into `--calibration-box` without an
  actual human completeness pass — the Faisalabad case below is exactly why that caution
  matters.
- Box 2 (Faisalabad): actively flagged as suspect, not just unverified — recommend a
  human mapper re-examine these specific 53 features before using them for anything.
- Box 3 (Multan): status changed from "ambiguous, open task" to "confirmed high-value
  open task" — there is real, visible, substantial PV here that needs mapping.

---

## Glint-method validation against Box 1's full ground truth (2026-07-24)

Direct empirical check of `earthpv.glint`'s own spike-detection/orientation-consistency
method against the corrected 1,021-installation Lahore ground truth — a genuinely
different question from the model-blindness finding above: does the *independent
physics-based* corroborator (not the trained segmentation model) find anything here?
Reused `glint.tile_scene_series_batch` (all 1,021 targets sit in one 1-degree tile
group, so one shared STAC search) and `glint_validation.analyze_point` unchanged, split
into 7 chunks of ~150 targets each (fresh search + token per chunk) after the
tile-batched country-scale bug (`docs/issues/glint-tile-batched-coverage.md`) bit an
un-chunked first attempt at this exact box (every target came back with an identical,
truncated 55-scene count). Chunking fixed it: scene counts came back in 3 clean,
systematic tiers (136/95/87 scenes, each shared by a large uniform group — sub-area
band-availability differences, not random loss) rather than one suspicious uniform low
number.

**Result: 48/1,021 (4.7%) showed at least one spike; 0/1,021 (0.0%) reached the
`n_consistent >= 2` validation bar**, against a country-wide reference of 2.5%
(<100 m²) and 8.8% (100-500 m²) validated from the 500-target study. Even generously
discounting for the reduced scene count here (87-136 valid scenes vs. the original
study's typical ~130-150 — a real methodological difference, not nothing), a clean 0/1,021
against an expectation of roughly 22-34 lands far outside what reduced sample size alone
would explain.

**This is consistent with, not contradicting, the earlier model-blindness finding** — two
independent detection channels (the trained segmentation model, and the physics-based
glint corroborator) both show near-total failure on this specific stratum. A plausible
physical reason specific to glint: `glint.py`'s own documented caveat is that ~30% of
confirmed real installations show zero spikes over 2 years because their actual
tilt/azimuth doesn't happen to bisect the sun/sensor at the fixed ~10:30 overpass
geometry — a *per-installation* orientation lottery nationally. But this box is one
affluent planned-housing development (DHA Phase V, stratum 1) where many roofs likely
share a similar pitch/orientation convention by construction standard — if that shared
convention happens to be glint-unfavorable, it could plausibly apply to nearly the whole
quadrat at once, rather than the ~30% national miss rate being independently rolled per
installation. Not confirmed (would need actual roof-orientation data to check), but a
coherent explanation for why a whole quadrat could read near-zero even though the
technique has real, if modest, power nationally.

**Practical implication:** glint corroboration should not be expected to help recover
capacity in this specific stratum/quadrat type (small, uniform, closely-packed
residential rooftop arrays) — both the model and the independent physics check are
weak here. Data: `data/glint/calib_box/lahore_calib_box_glint_summary.csv`,
`lahore_calib_box_stats_by_size.csv`.
