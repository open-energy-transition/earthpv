## Ground-truth calibration boxes

!!! note "OPEN, live log (as of 2026-08-11)"

    This is the running log of calibration-area mapping, and it lags the current state.
    It stops at 21 calibration areas; there are now 23, all Rule-1 complete -- see
    [Calibration quadrats](../methods/calibration-quadrats.md) and
    `results/calibration_quadrats.csv` for current per-area status. The atlas totals and
    the `est_mwp_rc` figure quoted here were superseded several times after they were
    written; current headline numbers are on [Capacity](../results/capacity.md).

Small, hand-verified areas where *all* rooftop PV has been mapped from high-resolution
imagery (not just OSM's usual partial coverage) -- fetched fresh via `earthpv
overpass-labels --bbox` rather than the Overture snapshot, since a just-finished mapping
pass won't be in Overture for weeks/months. Unlike the country-wide `mapped_frac` used by
`capacity_calibration`/`configs/calibration/<aoi>_candidate_precision.yaml` (which only
measures **precision** -- is an existing candidate real -- because it can only check
candidates that exist), a fully-mapped box is small enough to check **recall** too: every
real installation is known, so a candidate-free patch of the box is a genuine miss, not
just "unmapped."

### Box 1 -- Lahore, 1km x 1km around (31.4633307, 74.4045096) -- 2026-07-22

!!! note "Superseded 2026-08-05"
    This 1 km² square was replaced by a hand-drawn 6.61 km² boundary that fully contains
    it (`lahore_calib_6p61km2`) -- see
    [Box 1 replaced](#box-1-replaced-lahore-dha-phase-5-hand-drawn-661-km2-2026-08-05)
    below. Everything in this entry and the two that follow it describes the retired
    square, whose files are at `data/labels/retired/`. The counts below (8 installations)
    are also the *original* stale snapshot, corrected further down the same day.

bbox `74.399244,31.458839,74.409775,31.467822` (`data/labels/retired/lahore_calib_1km_overpass_solar.parquet`).

**Ground truth:** 8 rooftop installations, all clustered in one corner of the box
(74.409-74.410, 31.467-31.468), 314-577 m2 each -- reads as one small residential/
commercial development where each unit got its own rooftop array, not 8 independent
sites.

**Our candidates (pk16085) in/near the box:** exactly 1, a 2702 m2 / confidence 0.49 /
rank_score 0.39 rooftop candidate ~335m from the box center. Checked against a widened
2km search: the closest any candidate gets to any of the 8 real installations is 877m --
not a geometry-offset artifact, a genuine miss.

**Result: 0/8 recall, 1 likely false positive.**
- The model missed all 8 real installations. Each is well below this project's
  ≥1000 m2 recall-first design target (README/CLAUDE.md) -- consistent with, and now a
  direct empirical confirmation of, the known operating point rather than a new bug.
  Doesn't mean small arrays are unrecoverable, just that they're outside what this
  checkpoint was tuned to prioritize.
- The one candidate found in the box is nowhere near any of the 8 confirmed
  installations. Since this box's OSM mapping is asserted complete, a real PV array at
  that location would already be in the fetch -- it isn't, so this candidate is very
  likely a false positive. One useful confirmed-FP data point for the `1k-5k` bucket
  (currently `p_real=0.149` in the interim-mapped-only calibration table).

**Update (2026-07-23): this box now feeds the calibration pipeline, not just this doc.**
`earthpv calibrate-candidates` gained `--calibration-box <parquet>` (repeatable):
it pools a box's per-bin (installations, matched-by-any-candidate) counts directly into
the same `recall_reference` denominator the country snapshot already builds, before the
existing Beta-posterior machinery runs -- so a quadrat's TRUE-recall evidence (every
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

National `est_mwp_rc` moved +0.001% -- negligible, and correctly so: n=8 against a
~2,800-installation country snapshot genuinely can't move a country-scale estimate much,
exactly as this doc originally predicted. What changed is that the pipeline now HAS a
mechanism ready to matter as more of the mapping protocol's planned 25-35 quadrats land
(`docs/calibration-mapping-protocol.md`) -- each new box is one more `--calibration-box`
flag, no code changes needed. The precision side (`mapped_frac`/`p_real`) is genuinely
unaffected here (no candidate sits near these 8 features, confirmed above), by design:
`--calibration-box` only ever feeds recall, the same separation `capacity_calibration.py`
already draws between precision and recall evidence.

One qualitative flag worth carrying forward even though n=8 can't prove it: this box's
TRUE recall (0/8) sits well below the country-snapshot recall in the same size bins
(58-74%) -- consistent with the snapshot itself being an incomplete, and possibly biased,
sample of real installations (a mapper is more likely to have mapped exactly the
installations a model also finds easiest to detect). More quadrats will tell us whether
that gap is real or n=8 noise.

### Direct density-method validation against Box 1 (2026-07-23)

Location confirmed by reverse-geocode: **DHA Phase V, Lahore** -- exactly the mapping
protocol's stratum 1 ("affluent planned housing... highest rooftop-PV adoption"). Boundary
saved as `data/labels/lahore_calib_1km_boundary.geojson`.

Beyond the candidate-level recall check above, this checks `density.py`'s actual per-pixel
and per-building output against the same 8 installations (true total **3,145.8 m²**),
pulling the raw probability raster (cell `0135_0077`) and `buildings.geoparquet` directly --
the same artifacts `density` ships, not a re-derived approximation.

**At the 8 true installation footprints, the model's raw pixel probability is exactly
0.000 -- at every one, not just below threshold.** This is a stronger and more concerning
finding than "recall is low": it means `pv_area_exp` (the metric whose entire premise is
integrating *sub-threshold* signal) has nothing to integrate here -- these installations
aren't faintly visible and miscalibrated, they produce no model activation at all. All
three building-level metrics are therefore zero at every one of the 8 true locations:
`pv_area_det = pv_area_cal = pv_area_exp = 0`.

**Meanwhile the box's only signal is a false positive, elsewhere.** One candidate
(2,701.9 m², rooftop, confidence 0.49) sits 877 m from the nearest real installation --
`density.py` correctly attributes it to 9 nearby (wrong) buildings:

| metric | total in the false-positive cluster | true total (8 real installations) |
|---|---|---|
| `pv_area_det` | 2,281.0 m² | 3,145.8 m² |
| `pv_area_cal` | 340.6 m² | -- |
| `pv_area_exp` | 1,241.4 m² | -- |

**The trap this exposes:** naively summing "PV area estimated in this box" gives
~1,200-2,300 m² -- deceptively close to the true 3,145.8 m², entirely by coincidence.
Every square metre of it is misattributed; the aggregate number would look roughly right
while being 100% spatially wrong. A cell/region-aggregate sanity check (as the density
stage's grid/region layers necessarily are) cannot catch this; only a fully-mapped,
building-level ground truth like this box can.

**Implication for `est_mwp_rc` (recall-corrected estimator):** the recall correction
(dividing calibrated candidate area by a size-bin's country-average recall, ~56-73% for
100-1k m²) is a *population-level* correction -- it is only unbiased in expectation across
many neighbourhoods whose true recall averages out to the country figure. This box is a
direct counterexample at the neighbourhood scale: its true recall is 0%, not 56-73%, so
`est_mwp_rc` for a query scoped to just this box (or a similar single neighbourhood) would
still be far too low -- recall-correction repairs the *national* total, it does not make
any single building- or neighbourhood-level number trustworthy. Worth stating explicitly
wherever `est_mwp_rc` is surfaced at sub-national granularity.

Net read on this one box: 0/8 recall, confirmed at both the candidate-polygon level
(above) and now the raw-probability level (this section) -- the model is currently blind,
not just imprecise, in the exact stratum (affluent planned housing, 300-600 m² rooftop
arrays) the mapping protocol calls the highest-adoption one. That's the single most
useful thing a first calibration box could have told us.

### Correction (2026-07-23, later same day): the 8-feature snapshot was stale AND flawed

Prompted by a direct "have you pulled the newest labels for this?" check -- good catch,
because the answer was no, and it mattered. Re-fetching this exact bbox live via
`earthpv overpass-labels --bbox 74.399244,31.458839,74.409775,31.467822 --iso3 PAK`
returned **1,021 features (52,188.9 m² true PV area)**, not 8 (3,145.8 m²). Comparing
geometries: 2 of the original 8 (both exactly 314 m², same OSM way IDs) are unchanged;
the other 6 have been **replaced by clusters of much smaller polygons 3-20 m away**
(areas now 8-95 m² instead of 314-577 m²) -- i.e. the original mapping pass traced whole
roofs for those 6, not individual panels, exactly the "Common failure mode" the
protocol's Rule 1 warns about, and a second, more careful pass has since fixed it. The
section above and the earlier calibration-table update both used the stale, partly-wrong
file -- corrected below. New size distribution: 882 installations <100 m², 138 in
100-500 m², 1 in 1k-5k m², none larger. **Everything above this point in the file
describes the superseded 8-feature analysis; treat the numbers below as current.**

**Recall, recomputed on the corrected 1,021-installation ground truth:**
- Within 100 m of any candidate: 40/1,021 (3.9%) -- all 40 attributable to the SAME one
  candidate (2,701.9 m², rooftop, confidence 0.49), which sits in/next to a dense cluster
  of small installations, not scattered across the box.
- Literal polygon intersection: only 2/1,021 (0.2%).
- **Raw pixel probability at the true footprints: nonzero for exactly 2/1,021** (the
  same 2 the candidate literally overlaps) -- 1,019/1,021 (99.8%) installations still
  show *exactly* 0.000 probability. The core finding survives correction, just more
  starkly: near-total blindness, not literal-zero-of-everything. `pv_area_exp` recovers
  571.7 of 52,188.9 m² true (1.1%) -- nonzero this time, but still capturing almost none
  of the true signal.
- **This reverses the earlier "false positive, 877 m from nearest install" read on the
  one candidate**: against the corrected ground truth its nearest real installation is
  **0.0 m away** (it literally overlaps one). The candidate is better read as a coarse,
  unresolved detection of a genuine dense small-array cluster -- the model correctly
  flagged that *something* PV-related is happening there, it just can't resolve the
  ~40 individual panels into separate polygons. Different lesson than "spurious FP
  elsewhere in the box": this is a resolution failure on a real signal, not hallucination.

**Calibration table impact (`--calibration-box`, corrected file) -- now genuinely
consequential, unlike the first (stale) pooling:**

| bin | recall before any box | after stale 8-feature box | after corrected 1,021-feature box |
|---|---|---|---|
| <100 m² | 0/142 (0%) | 0/142 (0%, box had none this size) | **34/1,024 (3.3%)** |
| 100-500 m² | 96/164 (58.5%) | 96/170 (56.5%) | **101/302 (33.4%)** |
| 1k-5k m² | 1152/1296 | 1152/1296 | 1153/1297 (negligible) |

The <100 and 100-500 bins moved for real this time -- n=882 and n=138 from one quadrat
are not negligible next to the country snapshot's own n=142/n=164 there. National
`est_mwp_rc`: 18,309.5 → 18,312.0 MWp (+0.014%, still small -- these bins hold little of
the country's total capacity -- but the *interval* widened more meaningfully, 90% CI
[17,065, 21,318] → [17,021, 21,400]).

!!! note "Absolute totals here are superseded"
    The `est_mwp_rc` figures above are from the pre-2026-07-26 conversion, which applied
    the rooftop kWp/m² constant to ground-mount site area and put no bound on candidate
    polygon size. The current national total is roughly a third of the number quoted here
    (see [Capacity density](../methods/density.md)). The *relative* effect this section
    measures -- which is what it is about -- is unaffected: the bins in question still hold
    little of the country's capacity, and the interval still widens.

**Lesson for the mapping protocol itself:** a "done" quadrat should be spot-checked
against a fresh Overpass pull before it feeds any calibration, even hours after
completion -- mapping is iterative (the two-mapper completeness pass is designed to add
exactly this kind of correction), and a calibration mechanism now exists that will
silently encode whatever was cached at pull time as ground truth.

---

### Box 2 -- Faisalabad, 1km x 1km around (31.4976169, 73.0523711) -- 2026-07-24

bbox `73.047103,31.493125,73.057639,31.502108` (`data/labels/faisalabad_calib_1km_overpass_solar.parquet`,
boundary `data/labels/faisalabad_calib_1km_boundary.geojson`). Reverse-geocode: **Punjab
Small Industries Estate, Faisalabad Sadar Tehsil** -- the mapping protocol's **stratum 6
(industrial zone)**, which names Faisalabad as an example location directly.

**Status: NOT a Rule-1-verified quadrat.** This is a live OSM pull, not an
exhaustively-mapped completeness pass -- no second-mapper declaration, no imagery-date
record. Documented here as a useful interim data point; do not fold into
`calibrate-candidates --calibration-box` until it's been through the same completeness
process as Box 1.

**Ground truth (as currently mapped):** 53 installations, all tagged `plant:source=solar`
(deliberate ground-mount/captive-plant tagging, not an ambiguous-generator fallback),
63,501 m² total. Sequential OSM way IDs (1498181449–1498181511) -- one mapping pass.
Size range 193–4,722 m² (median 922 m², mean 1,198 m²) -- squarely in the model's
designed ≥500 m² strength zone, unlike Box 1's sub-100 m² residential cluster.

**Candidate recall (pk16085): 53/53 (100%) within 100 m, 34/53 (64.2%) literal
intersection** -- a sharp contrast with Box 1's 0.2%/3.9%. Consistent with size:
these installations sit well inside the range the model was tuned for. One thing worth
a second look later: several nearby candidates are much larger than any single true
installation here (up to 64,997 m² and 58,697 m², vs. a 4,722 m² true max) -- plausibly
the model merging a dense cluster of adjacent ground arrays into fewer, larger candidate
polygons rather than resolving them individually; not confirmed, just flagged.

### Box 3 -- Multan, 1km x 1km around (30.1262242, 71.3829068) -- 2026-07-24

!!! note "Superseded 2026-08-05"
    This 1 km² square was replaced by a hand-drawn 3.92 km² boundary that fully contains
    it (`multan_calib_3p92km2`) -- see
    [Box 3 replaced](#box-3-replaced-multan-industrial-estate-hand-drawn-392-km2-2026-08-05)
    below. Files retired to `data/labels/retired/`. Everything below describes the
    retired square.

bbox `71.377714,30.121733,71.3881,30.130716` (boundary
`data/labels/multan_calib_1km_boundary.geojson`; no labels parquet -- see below).
Reverse-geocode: **Multan Industrial Estate, Thati Lal, Multan Sadar Tehsil** -- also
stratum 6 (industrial). Sits inside the `pakistan` AOI's `val_tiles` holdout region
(`configs/aoi.yaml`, the Multan cluster used for the model's own validation split).

**Live Overpass pull returned zero `generator:source=solar`/`plant:source=solar`
features.** This is explicitly **not** usable as a "0 installations, 0 recall"
ground-truth point: per Rule 1 of `docs/calibration-mapping-protocol.md`, a quadrat with
no completeness declaration is indistinguishable between "genuinely no PV here" and
"nobody has mapped this area in OSM yet" -- treating an unmapped area as a confirmed
negative is exactly the failure mode the protocol calls out as worse than leaving a
quadrat out entirely. Flagged as an **open mapping task** (industrial zone, Multan,
overlapping the model's own val split -- a high-value quadrat to complete), not a result.

**Both boxes' honest status:** neither has been through a human high-res-imagery
completeness pass. Box 2's plant-tagged, sequential-ID mapping looks like a deliberate,
consistent single pass (a good sign, same pattern the corrected Lahore mapping eventually
showed) but that is circumstantial, not a substitute for the protocol's actual
two-mapper sign-off. Treat both as candidates for the mapping team's queue, not
finished quadrats, until that happens.

### Box 4 -- Sundar Industrial Estate, Lahore, 1km x 1km around (31.2861646, 74.1720942) -- 2026-07-24

!!! note "Superseded 2026-08-05"
    This square was replaced by a hand-drawn 4.34 km² boundary that fully contains it
    (`sundar_calib_4p34km2`); files retired to `data/labels/retired/`. See
    [the 2026-08-05 batch](#box-1-replaced-lahore-dha-phase-5-hand-drawn-661-km2-2026-08-05).
    Everything below describes the retired square.

bbox `74.166838,31.281673,74.17735,31.290656`
(`data/labels/sundar_calib_1km_overpass_solar.parquet`, boundary
`data/labels/sundar_calib_1km_boundary.geojson`). Reverse-geocode: **Sundar Industrial
Estate, Raiwind Tehsil, Lahore District** -- stratum 6 (industrial) again, a third
industrial box alongside Faisalabad and Multan.

**Status: NOT a Rule-1-verified quadrat** (same caveat as Boxes 2/3 -- live pull only,
no completeness declaration).

**Ground truth (as currently mapped):** 38 installations, 72,561 m² total, mixed tagging
(20 `plant`/18 `generator`, 23 ground/15 rooftop by placement) and **non-sequential**
OSM way IDs spanning several ID ranges -- unlike Faisalabad's single contiguous pass,
this looks like several separate mapping sessions over time. Size range 76.7–6,579.7 m²
(median 1,658 m²) -- again squarely in the model's designed strength zone.

**Candidate recall (pk16085): 33/38 (86.8%) within 100 m, 26/38 (68.4%) literal
intersection.** The 5 misses are all at or below 999 m² (76.7, 103.8, 254.4, 722.8,
999.4 m²) -- consistent with the model's known size-dependent recall falloff, not a
surprise. A third data point reinforcing the same pattern as Box 2: this model performs
reasonably well once installations clear roughly the 1,000 m² mark, regardless of
industrial vs. residential context; the failure mode found in Box 1 is specifically
about very small (<500 m²) arrays, not industrial siting per se.

---

### Box 5 -- SITE Karachi, 1km x 1km around (24.9070005, 66.9941461) -- 2026-07-24

bbox `66.989194,24.902509,66.999098,24.911492`
(`data/labels/site_karachi_calib_1km_overpass_solar.parquet`, boundary
`data/labels/site_karachi_calib_1km_boundary.geojson`). Reverse-geocode: **Sindh
Industrial Trading Estate (SITE), Rashid Abad, SITE Town, Kemari District, Karachi** --
stratum 6 (industrial), and the mapping protocol's explicit Karachi example. First
non-Punjab box.

**Ground truth (as currently mapped):** 67 installations (53 rooftop/14 ground),
115,843 m² total, median 1,110 m².

**Candidate recall (pk16085): 67/67 (100%) within 100 m, 60/67 (89.6%) literal
intersection.**

---

## Rule-1-complete quadrats (owner-mapped), 2026-07-29

Three quadrats added directly as Rule-1 complete, following the `karachi_coast_calib_700m`
precedent: mapped and declared complete by the repository owner rather than pulled live
and left as an open task like Boxes 2-5 above. As with `karachi_coast_calib_700m`, "Rule-1
complete" here means the mapper's own completeness declaration per
`docs/calibration-mapping-protocol.md`; there is no separately recorded independent
second-mapper sweep for any of the four owner-mapped boxes, karachi_coast included. Each
boundary was recorded before this doc entry was written, per the protocol's "record the
rectangle... before mapping starts."

### Box 6 -- Sialkot Old City, 1km x 1km around (32.503855, 74.5422037) -- 2026-07-29

bbox `74.536883,32.499346,74.547524,32.508364`
(`data/labels/sialkot_calib_1km_overpass_solar.parquet`, boundary
`data/labels/sialkot_calib_1km_boundary.geojson`). Reverse-geocode: **Puran Nagar / Old
City, Sialkot Tehsil, Sialkot District, Punjab** -- stratum 2 (dense older urban /
informal settlement), the protocol's least-represented stratum among prior boxes.

**Ground truth: 182 installations (177 rooftop / 5 ground), 15,055.8 m² total**, median
63.7 m², max 646.8 m². 148/182 (81.3%) below 100 m², none at or above 1,000 m² -- a second
sub-floor test ground alongside `karachi_coast_calib_700m`, this time in dense inner-city
fabric rather than affluent planned housing.

### Box 7 -- Sheikh Maltoon Town, Mardan, 1km x 1km around (34.189388, 72.0253755) -- 2026-07-29

bbox `72.019951,34.18488,72.0308,34.193896`
(`data/labels/mardan_calib_1km_overpass_solar.parquet`, boundary
`data/labels/mardan_calib_1km_boundary.geojson`). Reverse-geocode: **Sheikh Maltoon Town,
Bypass Road, Mardan Tehsil, Mardan District, Khyber Pakhtunkhwa** -- a planned
residential scheme in a peri-urban tehsil town, so it sits between the protocol's
stratum 1 and stratum 3 examples rather than cleanly inside either. **First
Khyber Pakhtunkhwa quadrat**, and the first outside Punjab/Sindh.

**Ground truth: 794 installations, all rooftop, 20,701.2 m² total**, median 21.7 m²,
max 221.5 m². 784/794 (98.7%) below 100 m², none at or above 500 m² -- the smallest
median installation size of any registered quadrat, and by far the largest installation
count for a 1 km² box so far.

### Box 8 -- Quetta City, 1km x 1km around (30.1915156, 67.015288) -- 2026-07-29

bbox `67.010096,30.187005,67.02048,30.196026`
(`data/labels/quetta_calib_1km_overpass_solar.parquet`, boundary
`data/labels/quetta_calib_1km_boundary.geojson`). Reverse-geocode: **Brahimzai, Abdul
Sattar Road, Quetta City Tehsil, Quetta District, Balochistan** -- stratum 5 (arid /
bare-land settlement). **First Balochistan quadrat** -- notable because
`plausibility.py`'s ground-mount:rooftop check already flags Balochistan as structurally
suspect (see `docs/methods/density.md`), so a trustworthy rooftop-only ground truth here
is high-value independent of the sub-floor question.

**Ground truth: 73 installations, all rooftop, 12,238.3 m² total**, median 103.9 m²,
max 1,856.6 m². Wider size spread than Boxes 6/7 (35/73 below 100 m², 3/73 at or above
1,000 m²) -- not purely a sub-floor test ground, unlike the other two new boxes.

### Box 9 -- Peshawar, 1km x 1km around (34.0199854, 71.5505752) -- 2026-07-30

bbox `71.545162,34.015478,71.555989,34.024493`
(`data/labels/peshawar_calib_1km_overpass_solar.parquet`, boundary
`data/labels/peshawar_calib_1km_boundary.geojson`, geodesic area 999,999.998 m² by
construction -- built as a precise 1 km square via `pyproj.Geod.fwd`, not drawn by eye).
Reverse-geocode against the density stage's own admin polygons: **Peshawar district,
Khyber Pakhtunkhwa** -- the **first Peshawar quadrat**, and the city was already flagged
as a priority target in `docs/methods/density.md`'s sub-400 m² region-suggestion table
(one of the top building-density cities nationally, alongside Karachi/Lahore/Faisalabad/
Islamabad, none of which had a Peshawar-specific quadrat yet).

**Status: NOT a Rule-1-verified quadrat**, same caveat as Boxes 2–5. This is a live
Overpass pull at a center coordinate the user supplied, not an exhaustively-mapped
completeness pass by a human against high-res imagery -- no mapper name, no second-pass
countersign, no imagery-date record. Its boundary and building geometry are exact; its
*completeness* is unverified, so absence of a mapped installation anywhere inside it does
NOT mean absence of PV. Usable as an interim data point and as a `roofclf` training
quadrat (the same way Boxes 2–5 already are), not as a source of trustworthy negatives,
until it goes through the two-mapper sign-off in
`docs/calibration-mapping-protocol.md`.

**Re-pulled twice more, 2026-07-30, same day, after the user added missing OSM labels
each time**: 290 → 353 (+63) → 360 (+7) installations. Every snapshot preserved, none
overwritten: bare `peshawar_calib_1km_overpass_solar.parquet` (pull 1, 290), dated
`..._20260730.parquet` (pull 2, 353), `..._20260730_v2.parquet` (pull 3, 360, current --
`_newest_solar`/`_newest_overpass_path` both pick it, verified). This is the "OSM is
iteratively completed, re-pull after mapping" pattern the protocol expects, not a sign
this box is done -- still not Rule-1 without a completeness declaration and
second-mapper pass; the shrinking increment (+63, then +7) is a reasonable, but not
sufficient, signal that the mapping is converging.

**Ground truth (current pull): 360 installations, 356 rooftop / 4 ground, 28,955.1 m² total**,
median 71.5 m², mean 80.4 m², max 555.8 m². **358/360 (99.4%) below the 400 m² detection
floor, 265/360 (73.6%) below 100 m²** -- the largest single haul of sub-floor installations
of any quadrat registered so far (previous densest was Mardan at 794 installations but a
larger box; Peshawar's 360-in-1 km² is a higher areal density). `packing_density`
(nn_median_m) measures **15.7 m** -- tightly packed, in the same "informal/residential"
cluster as Karachi coastal (16.8 m), Quetta (16.8 m; coincidentally close) and Sialkot
(18.8 m), not the industrial estates' 44–52 m spacing. Geometries are simple `way`
polygons tagged `generator:source=solar`/`location=roof`, consistent with an ordinary
building-by-building OSM mapping pass rather than a bulk import.

### Box 10 -- Peshawar East, 1km x 1km around (34.0242579, 71.5600512) -- 2026-07-30 -- WITHDRAWN 2026-08-05

!!! danger "Withdrawn 2026-08-05 as wrong -- no longer a quadrat"
    Removed from the project at the owner's instruction. Its files are retired to
    `data/labels/retired/peshawar_east_calib_1km_*` (kept, not deleted: `data/` is
    gitignored and there is no other copy), it is gone from
    `results/calibration_quadrats.csv`, the JOSM validation layer and
    `atlas.py::CALIBRATION_BOXES`, and `roofclf.discover_quadrats` no longer finds it.
    Removal is also what resolved the un-deduplicated overlap described below -- **no
    deduplication code was ever written**, so the pre-creation overlap check in
    `scripts/new_calibration_quadrat.py` is still the only guard against a repeat.
    The entry is kept for the record; everything in it is history, not current state.

bbox `71.554638,34.019750,71.565465,34.028766`
(`data/labels/retired/peshawar_east_calib_1km_overpass_solar.parquet`, boundary
`data/labels/retired/peshawar_east_calib_1km_boundary.geojson`, geodesic area 999,999.998 m²).
User-suggested center, ~995 m from Box 9's center -- checked for overlap **before**
creation (per the protocol note added to this doc): the two 1 km boxes share a corner,
**6.56% of this box's area**. Added anyway on the user's confirmation, as adjacent
Peshawar coverage rather than a duplicate.

**The overlap matters more than its area share suggests.** 42 of this box's 131
installations (32.1%) -- nearly a third -- sit inside that 6.56%-of-area shared corner,
i.e. the corner is far denser with PV than the rest of either box. **Consequence: if
`peshawar_calib_1km` and `peshawar_east_calib_1km` are both pooled into `roofclf`
training/LOQO without deduplication, those ~42 installations (and their host buildings)
are double-counted** -- present in both quadrats' building tables, which breaks the
leave-one-quadrat-out independence assumption (holding out one no longer removes all of
that ground truth from training, since the other still carries the overlap). **Not yet
deduplicated** -- `roofclf.building_table`/`discover_quadrats` has no overlap-aware
filtering today. Whoever next runs `earthpv roof-classifier` with both Peshawar quadrats
present should either clip one box's buildings to exclude the shared corner, or treat
this as a known limitation of the resulting fold statistics for these two quadrats
specifically.

**Status: NOT Rule-1 verified**, same caveat as every other non-owner-mapped box.

**Ground truth: 131 installations, 127 rooftop / 4 ground, 7,572.2 m² total**, median
44.9 m², **100% below the 400 m² floor** -- entirely sub-floor, smaller median than even
Box 9. `packing_density` (nn_median_m) **17.3 m**, same tightly-packed cluster.
**base_rate 3.7%** (126/3,382 buildings) -- notably lower than Box 9's 16.5% despite
being 995 m away and sharing a corner; this box's own building count (3,382) is also
60% higher than Box 9's (2,111) over a similarly-sized area, so the two boxes are not
drawn from the same population despite being adjacent and in the same city -- a useful,
concrete illustration of why `base_rate` must be read per quadrat, never pooled, even at
this fine a spatial grain.

### Box 11 -- Rahim Yar Khan District, 1km x 1km around (28.4255547, 70.2779961) -- 2026-07-31

bbox `70.2728926,28.4210431,70.2830996,28.4300663`
(`data/labels/rahim_yar_khan_calib_1km_overpass_solar.parquet`, boundary
`data/labels/rahim_yar_khan_calib_1km_boundary.geojson`, geodesic area 999,999.999 m² by
construction -- `pyproj.Geod.fwd`, not drawn by eye). User-supplied center. Checked for
overlap against all 10 existing boxes before creation (per the protocol note added after
the Peshawar pair): **no intersection with any existing quadrat.**

**Location: Rahim Yar Khan District, Punjab (near Sadiqabad) -- approximate.** Identified
from the coordinates alone (southern Punjab, close to the Sindh border); the exact
settlement is not confirmed against the density stage's admin polygons the way Box 9 was,
so treat "Rahim Yar Khan District" as a district-level placement, not a verified town name.
`stratum` in the boundary file is left as "unclassified pending mapper review," same as
every other non-owner-mapped box at creation.

**Status: NOT a Rule-1-verified quadrat**, same caveat as every other live-pull box. A
single Overpass pull at a user-supplied center, no completeness declaration, no
second-mapper sign-off. Usable as a `roofclf` training quadrat, not as a source of
trustworthy negatives.

**Ground truth: 204 installations, 183 rooftop / 21 ground, 19,803.9 m² total**, median
35.4 m². **97.1% below the 400 m² detection floor, 88.7% below 100 m²** -- solidly in the
small/informal-residential regime this project's sub-400 m² work is most short on
quadrats for.

**Exact base rate resolved 2026-08-04: 10.3% (214 PV buildings / 2,068).** The estimate
recorded here on 2026-07-31 was an approximate **8.7%** (183 rooftop installations against
a 2,099-building live VIDA fetch), pending the composite/VIDA join
`roofclf.building_table` performs. That join has now been run, and this box is in
`results/calibration_quadrats.csv` and
`docs/methods/calibration-quadrats.md`'s overview table.

---

### Box 12 -- Peshawar West, 1.5km x 1.5km around (33.9905887, 71.4261494) -- 2026-08-04

!!! note "Superseded 2026-08-05"
    This square was replaced by a hand-drawn 4.39 km² boundary that fully contains it
    (`peshawar_west_calib_4p39km2`); files retired to `data/labels/retired/`. See
    [the 2026-08-05 batch](#box-1-replaced-lahore-dha-phase-5-hand-drawn-661-km2-2026-08-05).
    Everything below describes the retired square, including its "largest quadrat in the
    set" claim, which the replacement and the Lahore box both overtook.

bbox `71.418032,33.983827,71.434267,33.997350`
(`data/labels/retired/peshawar_west_calib_1500m_overpass_solar.parquet`, boundary
`data/labels/retired/peshawar_west_calib_1500m_boundary.geojson`, geodesic area **2,249,999.991 m²**
by construction). User-supplied center. **The largest quadrat in the set at 2.25 km²** --
the first that is neither 1 km² nor Karachi coastal's 0.49 km², which is exactly why the
naming convention is size-agnostic (`*_calib_*_boundary.geojson`; the stem is
`_calib_1500m`, not `_calib_1km`).

Created with **`scripts/new_calibration_quadrat.py`**, added the same day so this stops
being a hand-built artifact: it builds the square via `pyproj.Geod.fwd`, runs the overlap
check *before writing anything* and refuses to continue on a hit without
`--allow-overlap`, then pulls OSM solar and prints the profile below.

**Overlap check: clear against all 12 existing quadrats.** Nearest is Box 9 (Peshawar) at
**11.95 km** centre-to-centre and Box 10 at 12.92 km, so unlike the Peshawar/Peshawar East
pair this box adds no deduplication debt. Reverse-geocoded against the density stage's own
admin polygons: **Peshawar district, Khyber Pakhtunkhwa** -- the third Peshawar quadrat.

**Status: NOT a Rule-1-verified quadrat**, same caveat as every live-pull box. A single
Overpass pull at a supplied center, no completeness declaration, no second-mapper
sign-off, no imagery-date record. Usable as a `roofclf` training quadrat, not as a source
of trustworthy negatives.

**Ground truth: 163 installations, 143 rooftop / 20 ground, 147,502.4 m² total**, median
416.8 m², mean 904.9 m², max 10,271.1 m². `base_rate` **10.8%** (415 PV buildings /
3,845), `nn_median_m` **34.0 m**.

**This box is unlike the other two Peshawar quadrats, and that is its value.** Boxes 9 and
10 are 99.4% and 100% sub-floor with medians of 71.5 and 44.9 m²; this one is **48.5%
sub-floor by count but only 7.7% sub-floor by area** -- 92.3% of its mapped PV area sits
in installations at or above the 400 m² detection floor, 108,174 m² of it in 38
installations of 1,000 m² or more:

| size bucket | installations | mapped area |
| --- | ---: | ---: |
| 0-100 m² | 36 | 1,854 m² |
| 100-250 m² | 27 | 4,201 m² |
| 250-400 m² | 16 | 5,367 m² |
| 400-1,000 m² | 46 | 27,906 m² |
| >= 1,000 m² | 38 | 108,174 m² |

So this is the **first Peshawar quadrat that can test the segmentation model rather than
only the sub-400 m² instruments** -- the other two have essentially no in-floor population
to score against. Its `nn_median_m` of 34.0 m also falls in what was an empty band between
the "informal/residential" (7-19 m) and "industrial" (44-52 m) clusters, which is why
`docs/methods/calibration-quadrats.md`'s packing section no longer describes that split as
having nothing in between.

Two things to read carefully. **`n_pv_buildings` (415) exceeds `n_installations` (163)**,
unlike every previous box -- not an error: `building_table` flags a footprint by overlap
share, and installations this large span several VIDA polygons each. And 28 of the 163
installations (17%) do not land on any VIDA footprint at all, consistent with the 20
ground-mounted ones plus a few unmapped roofs.

**A silent Overpass failure mode was measured on this box and is worth knowing.** When
`overpass-api.de` returns 504 and `_run_query` fails over, a mirror can answer with **zero
elements instead of an error**: two consecutive pulls of this exact bbox returned 0, then
167. `build_overpass_labels` does raise on an empty result, so nothing empty was written,
but from a single attempt "this box has no PV" and "the endpoint lied" are
indistinguishable. `new_calibration_quadrat.py` therefore treats an empty response as
retryable (`--retries`, default 4) rather than as truth -- never register a 0-installation
quadrat from one attempt.

---

### Box 1 replaced -- Lahore DHA Phase 5, hand-drawn 6.61 km2 -- 2026-08-05

Box 1's 1 km x 1 km square was **replaced** by a boundary drawn in JOSM and supplied as
`data/labels/calibration_boundaries/DH5.geojson`: `lahore_calib_6p61km2`, 6.61 km2, 18
vertices, bbox `74.392709,31.450724,74.432030,31.477134`. It is the **first non-square
quadrat** in the set and the largest by a wide margin (2.9x Box 12). The retired square and
both its Overpass pulls are kept at `data/labels/retired/lahore_calib_1km_*` -- not deleted,
since `data/` is gitignored and there is no other copy.

**The new boundary fully contains the old one** (0.0 m2 of the old square falls outside it),
which makes the replacement checkable rather than a matter of trust. Both checks pass:

- **Nothing was lost.** All 1,014 installations the old box held are present in the new
  pull, matched by OSM id -- 0 absent. (The old core's count rose 1,014 -> 1,031 in the
  new pull, i.e. mapping continued there since 2026-07-25.)
- **The extension is mapped to a comparable standard**, so this is an extension and not a
  dilution with unmapped ground: 1,034 installations/km2 inside the old core against
  **831/km2** across the added 5.61 km2. A fringe that had merely never been mapped would
  show a fraction of that.

**Profile:** 5,688 installations inside the boundary, 13,500 VIDA buildings, base rate
**25.4%** (was 30.1% on the square), median installation **29.0 m2**, **99.0% below the
400 m2 floor**, packing distance **6.8 m** -- the tightest of any quadrat, and now by far
the largest sub-400 m2 ground-truth population in the project (5,631 sub-floor
installations against 5,688 for all twelve other quadrats combined). Still **NOT Rule-1
complete**: no completeness declaration has been made for the added area, so its negatives
remain untrustworthy exactly as before.

**A second, worse Overpass truncation mode was measured here -- read this before trusting
any pull.** The Box 12 note above covers an endpoint answering with *zero* elements;
`build_overpass_labels` raises on empty, so nothing empty is written. This box hit the
non-empty version: a mirror returned **HTTP 200, valid JSON, no `remark`, and a partial
element list**. The first registration pull wrote **68** installations for a box whose
correct answer is ~5,700 -- and it would have been accepted as ground truth, in a box known
to contain 1,034 mapped installations, if the containment invariant had not been checked.
Four consecutive raw queries of the same bbox then returned 5,983 / 5,983 / 5,983 / 72, so
the failure is intermittent and a single query is untrustworthy in *either* direction. Two
guards were added:

- `overpass._run_query` now rejects any response carrying a top-level `remark` (Overpass's
  own "timed out"/"out of memory" signal) and fails over to the next mirror instead of
  returning a truncated element list as data (`OverpassTruncated`).
- `new_calibration_quadrat.py` cross-checks every pull against `confirm_element_count`,
  which takes the **maximum** over three independent queries of the same bbox -- the max,
  because truncation only ever loses elements, so the largest answer is the best available
  lower bound on the truth -- and retries the pull when the written count falls below 98%
  of it.

Neither guard would have caught this from the count alone had the box been new: what
actually caught it was the invariant that a boundary containing a known box cannot hold
fewer installations than it. Prefer replacing a quadrat by *extension* for that reason.

---

### Box 3 replaced -- Multan Industrial Estate, hand-drawn 3.92 km2 -- 2026-08-05

Box 3's 1 km x 1 km square was replaced by a boundary supplied as
`data/labels/calibration_boundaries/multan_industrial.geojson`: `multan_calib_3p92km2`,
3.92 km2 (3.94x the old box), bbox `71.370492,30.117067,71.392508,30.134698`. The retired
square and its pulls are kept at `data/labels/retired/multan_calib_1km_*`.

**Containment checked before registering, as with every replacement so far**: the new
boundary fully contains the old one (0.0 m2 outside it), and all 40 installations the old
box held are present in the new pull -- 0 lost. The pull itself was clean on the first
attempt (166 features written, 166 confirmed by an independent query, no truncation).

**Profile:** 164 installations, 3,419 VIDA buildings, base rate **8.1%** (was 8.6% on the
square), median installation **605.5 m2**, 37.8% below the 400 m2 floor (was 26.7%) --
sub-floor share rose because the extension reaches beyond the estate's core large arrays.
Packing distance **35.2 m**, in the same sparse industrial-estate range as Multan always
was. The added 2.92 km2 is mapped at **34 installations/km2 against the old core's 64** --
about half the density, the same signature Sundar showed on 2026-08-05: consistent with
extending past an industrial estate into surrounding, less array-dense ground rather than a
mapping gap, but the two are not distinguishable without a completeness sweep.

**This is the first extension registered *after* all seventeen quadrats were declared
Rule-1 (2026-08-05, see the mapping protocol), which is why Rule-1 was initially withheld
here.** That declaration was for the boundaries that existed at the time it was made; a
boundary the owner has not yet looked at does not inherit it just by sharing a name with
one that did. The owner then explicitly declared Rule-1 for the extended area the same
day, so `multan_calib_3p92km2` now reads `rule1_complete: yes` in
`results/calibration_quadrats.csv` and status `rule1` in `atlas.py::CALIBRATION_BOXES`,
matching the other sixteen. The general rule for the *next* extension is unchanged:
Rule-1 must be re-asserted for new ground, never inferred from a predecessor's.

---

## Visual verification pass (2026-07-24) -- what this is and is NOT

Prompted by a direct request to bring all boxes to Rule-1-verified status. **Important
scope note, stated plainly: this pass does not achieve that.** Rule 1
(`docs/calibration-mapping-protocol.md`) requires every visible panel traced to polygon
precision AND an independent second human mapper's sign-off, with a dated completeness
declaration. What follows is a single systematic visual pass by Claude against live Esri
World Imagery (fetched via the public ArcGIS `World_Imagery/MapServer/export` REST
endpoint, no API key, capture date not exposed by this endpoint so recorded as
"unknown" per the protocol's own allowance), reading each exported image directly. That
is real, substantive evidence -- a genuine plausibility/completeness check against
imagery, not just trust in existing OSM tags -- but it is **one AI pass, not two
independent human mappers**, and it produces approximate location/plausibility
judgments, not precise digitized polygons. None of these boxes should be described as
"Rule 1 verified" on this basis. Treat this as a strong prioritization signal for the
actual mapping team, not a substitute for their sign-off.

**Method:** fetched a ~1024x1024–2048x2048 export per box (~0.35–0.5 m/pixel -- enough to
resolve individual rooftop panel-grid texture, confirmed by cross-checking specific
claimed installations' exact centroids against the image), plus quadrant crops and
targeted zooms on the largest claimed features per box.

**Findings, box by box:**

- **Box 1 (Lahore DHA):** Confirmed. A close crop of the known-dense NE corner shows
  dozens of distinct small dark-panel-grid rooftops scattered through the residential
  blocks -- visually consistent with the corrected 1,021-installation dataset (already
  established via the OSM re-pull earlier this session).
- **Box 2 (Faisalabad):** **Not confirmed -- a real discrepancy.** The single largest
  claimed installation (`osm-way/1498181472`, 4,722 m², tagged `plant:source=solar`) is
  absent from the imagery at its exact stated centroid (31.499789, 73.051969) -- ordinary
  small rooftops, no large dark array. The general area also doesn't show the kind of
  obvious large ground-mount arrays the claimed size distribution (median 922 m², all 53
  tagged `plant`) would predict, unlike the unambiguous large arrays visible in Boxes 3-5.
  **Recommendation: do not trust this box's labels without independent re-verification --
  possible bad tagging/import, not necessarily "the model is wrong."**
- **Box 3 (Multan):** **Confirmed absent from OSM, confirmed present in reality** -- the
  single most important finding of this pass. All four quadrants show multiple large,
  unambiguous rooftop solar arrays with clear panel-row texture (one in the SE quadrant
  alone is easily several thousand m², with crisp visible panel rows). Roughly a
  dozen-plus plausible installations visible total. This resolves last turn's stated
  ambiguity definitively: **not a solar-free estate, just an unmapped one.** Highest-value
  quadrat for the mapping team to complete next -- real signal is sitting there unmapped,
  and it sits inside the model's own `val_tiles` holdout.
- **Box 4 (Sundar):** Confirmed. Roughly 10-15 large, clearly grid-textured rooftop
  arrays visible across the estate; the three largest claimed installations checked
  against their exact centroids correspond to real visible arrays in the same cluster of
  buildings.
- **Box 5 (SITE Karachi):** Confirmed, most visually dense of all five boxes -- dozens of
  clear rooftop arrays visible across nearly every block, strongly supporting (if
  anything, suggesting the true count could be even higher than) the claimed 67.

**Net effect on box status:**
- Boxes 1, 4, 5: visual pass materially increases confidence but does not constitute
  Rule-1 sign-off. Still recommend NOT pooling 4/5 into `--calibration-box` without an
  actual human completeness pass -- the Faisalabad case below is exactly why that caution
  matters.
- Box 2 (Faisalabad): actively flagged as suspect, not just unverified -- recommend a
  human mapper re-examine these specific 53 features before using them for anything.
- Box 3 (Multan): status changed from "ambiguous, open task" to "confirmed high-value
  open task" -- there is real, visible, substantial PV here that needs mapping.

---

## Glint-method validation against Box 1's full ground truth (2026-07-24)

Direct empirical check of `earthpv.glint`'s own spike-detection/orientation-consistency
method against the corrected 1,021-installation Lahore ground truth -- a genuinely
different question from the model-blindness finding above: does the *independent
physics-based* corroborator (not the trained segmentation model) find anything here?
Reused `glint.tile_scene_series_batch` (all 1,021 targets sit in one 1-degree tile
group, so one shared STAC search) and `glint_validation.analyze_point` unchanged, split
into 7 chunks of ~150 targets each (fresh search + token per chunk) after the
tile-batched country-scale bug (`docs/issues/glint-tile-batched-coverage.md`) bit an
un-chunked first attempt at this exact box (every target came back with an identical,
truncated 55-scene count). Chunking fixed it: scene counts came back in 3 clean,
systematic tiers (136/95/87 scenes, each shared by a large uniform group -- sub-area
band-availability differences, not random loss) rather than one suspicious uniform low
number.

**Result: 48/1,021 (4.7%) showed at least one spike; 0/1,021 (0.0%) reached the
`n_consistent >= 2` validation bar**, against a country-wide reference of 2.5%
(<100 m²) and 8.8% (100-500 m²) validated from the 500-target study. Even generously
discounting for the reduced scene count here (87-136 valid scenes vs. the original
study's typical ~130-150 -- a real methodological difference, not nothing), a clean 0/1,021
against an expectation of roughly 22-34 lands far outside what reduced sample size alone
would explain.

**This is consistent with, not contradicting, the earlier model-blindness finding** -- two
independent detection channels (the trained segmentation model, and the physics-based
glint corroborator) both show near-total failure on this specific stratum. A plausible
physical reason specific to glint: `glint.py`'s own documented caveat is that ~30% of
confirmed real installations show zero spikes over 2 years because their actual
tilt/azimuth doesn't happen to bisect the sun/sensor at the fixed ~10:30 overpass
geometry -- a *per-installation* orientation lottery nationally. But this box is one
affluent planned-housing development (DHA Phase V, stratum 1) where many roofs likely
share a similar pitch/orientation convention by construction standard -- if that shared
convention happens to be glint-unfavorable, it could plausibly apply to nearly the whole
quadrat at once, rather than the ~30% national miss rate being independently rolled per
installation. Not confirmed (would need actual roof-orientation data to check), but a
coherent explanation for why a whole quadrat could read near-zero even though the
technique has real, if modest, power nationally.

**Practical implication:** glint corroboration should not be expected to help recover
capacity in this specific stratum/quadrat type (small, uniform, closely-packed
residential rooftop arrays) -- both the model and the independent physics check are
weak here. Data: `data/glint/calib_box/lahore_calib_box_glint_summary.csv`,
`lahore_calib_box_stats_by_size.csv`.

---

## Two ground-mount solar-farm calibration areas (2026-08-06)

Every box above is rooftop/urban -- ground-mount (site-area, 0.07 kWp/m² conversion) has
had zero dedicated calibration ground truth anywhere in this project, despite being
roughly half of the >= 400 m² capacity estimate and the component `check-density`'s worst
plausibility failures (Balochistan, KP, Gilgit-Baltistan) concentrate in. Two known,
well-mapped Pakistani utility-scale farms, using their own OSM boundary rather than a
drawn/geodesic shape:

- **`sukkur_solar_farm_gmcalib_5p93km2`** -- the combined "Helios Power (Pvt.) Limited
  (Phase 3), Meridian Energy (Pvt.) Ltd (Phase 1), HND Energy (Pvt.) Limited (Phase 2),
  Scatec Sukkur solar farm" complex (`osm-way/1374632672`, `plant:output:electricity`
  50 MW), Sukkur district, Sindh. Plant footprint 2.265 km², boundary buffered +400 m
  to 5.93 km² for surrounding-terrain false-positive testing.
- **`quaid_e_azam_solar_park_gmcalib_14p07km2`** -- Quaid-e-Azam Solar Park
  (`osm-relation/11789995`, operator QA Solar Power Ltd, 400 MW), Bahawalpur district,
  Punjab. Buffered +400 m from 6.65 km² (the relation's own area) to 14.07 km².

Both named `..._gmcalib_...`, not `..._calib_...`, so `roofclf.discover_quadrats()`'s glob
(`*_calib_*_boundary.geojson`) does not pick them up -- confirmed (still 18 quadrats
discovered after adding these). Mixing ground-mount PV into roofclf's rooftop-classifier
training population would contradict the placement separation this project enforces
everywhere else.

**Both raw OSM pulls needed a fix before use.** Each site turned out to have nested,
overlapping OSM mapping at multiple levels -- an outer envelope (oddly tagged
`generator:source=solar` at both sites rather than `plant:source=solar`) drawn over
pre-existing finer per-phase/per-block mapping, with no tags distinguishing the levels
from each other. Naively summing the raw pull's `area_m2` triple-counts the same ground:
8.63 km² raw vs. **2.61 km² dissolved** at Sukkur (21 overlapping elements -> 1), 22.20
km² raw vs. **8.90 km² dissolved** at QASP (6 overlapping elements -> 1). Both quadrats'
`*_overpass_solar.parquet` now hold one dissolved-footprint row rather than the raw pull.

**Checking both sites against the current `candidates.parquet` surfaced a real,
previously undocumented pipeline bug**, since fixed: `replace_with_osm_geometry` now keeps
only the closest match per OSM feature via `groupby(...).idxmin()`, and
`labels.dissolve_overlapping` merges nested `plant`/`generator` ways before any capacity
computation sees them. Short version of the original bug: at Quaid-e-Azam Solar
Park, two *different* model-detected candidates each independently matched their own
nearest OSM feature via `postprocess.replace_with_osm_geometry` -- one to the outer
envelope (8,904,839 m²), one to a member way **100% contained inside it**
(1,745,036 m²) -- and both survive as separate rows in `candidates.parquet`, so this one
site's ~8.90 km² footprint is currently double-counted to ~10.65 km² (+20%) in any
capacity estimate built from this snapshot. At Sukkur the opposite failure shows instead:
the one nearby candidate (44,948 m², never OSM-replaced) undercounts the true 2,606,013 m²
footprint by **58x** -- a second, independent confirmation of this project's established
"segmentation badly underestimates ground-mount" finding, beyond Quaid-e-Azam Solar
Park's own count-zero cell (the evidence-atlas `mwp_best` floor fix, same session).

Not yet folded into any capacity number or plausibility check -- these two quadrats
exist so far only as ground truth for a future targeted evaluation of the segmentation
model's own ground-mount recall/area accuracy (the actually-novel thing solar-farm
calibration areas can measure that rooftop quadrats cannot), and as the source of the
duplicate-match finding above. Not Rule-1 complete in the usual sense (no human
completeness pass over the surrounding buffer for false positives yet) -- the two sites'
own footprints are corroborated by two independently-drawn OSM outlines converging on
the same shape, which is not nothing, but is not a substitute for that pass.

---

### Box 13 -- Hasal, ~1km x 1km around (29.7161176, 72.5512755) -- 2026-08-10

A **drawn** boundary, not a geodesic square (`--geojson data/labels/calibration_boundaries/
hasal.geojson`, a hand-drawn ~1km x 1km rectangle exported from JOSM, feature name
`hasal_1x1`), registered via `scripts/new_calibration_quadrat.py`. Geodesic area
996,572.5 m² (0.9966 km²), stem `hasal_calib_1p00km2`.

**Overlap check: clear against all 18 existing quadrats.** Nearest is `multan_
calib_3p92km2` at 121.74 km, so no deduplication debt. Reverse-geocoded against the
density stage's own admin polygons: **Bahawalpur District, Punjab**.

**Overpass fetch hit a genuine outage, not a truncation.** At creation time all three
mirrors (`overpass-api.de`, `overpass.kumi.systems`, `overpass.openstreetmap.ru`) were
returning 504s or connection timeouts; the first `build_overpass_labels` call itself
succeeded (328 solar elements returned cleanly), but the SECOND, independent confirming
query `new_calibration_quadrat.py` runs specifically to guard against silent partial
responses could not complete against any mirror. The script does not treat an
unavailable confirming check as a failure (an unreachable checker must not read as
"fine" but also must not block registration) -- it wrote the pull with `pull_unverified:
True` recorded on the boundary parquet. 328 features over a ~1 km² box is not the shape
of a truncated response, but this should be re-run once Overpass recovers to get an
actual independent count to check against.

**Ground truth: 328 installations, 318 rooftop / 10 ground, 16,082.9 m² total**, median
31.4 m², mean 49.0 m², max 1,056.3 m². **99.7% of installations (327/328) sit below the
400 m² detection floor**, 93.9% below 100 m² -- one of the most sub-floor-dominated
quadrats registered so far, close to Sialkot/Rahim Yar Khan/Mardan/Sukkur territory.
`nn_median_m` **18.5 m**, the tightly-packed informal/residential cluster.

**Status: Rule-1 complete**, per the repository owner's explicit declaration the same
day the box was created (2026-08-10) -- recorded in `results/calibration_quadrats.csv`
(`rule1_complete: True`). Same standing caveat as every other quadrat in this file: this
is an owner-attested completeness declaration, not an independently second-mapper-verified
one, and (per the Rule-1-is-epoch-relative warning earlier in this file / `docs/methods/
calibration-quadrats.md`) `imagery_layer`/`imagery_date` remain unrecorded for this box
too, so the gap between the mapping imagery's epoch and the Sentinel-2 composite's is
unmeasured here as everywhere else.

**Folded into `roofclf` the same day.** `earthpv roof-classifier` was re-fit on all 19
quadrats: `hasal` contributes 4,378 buildings, 444 with PV (**base_rate 10.14%**), AUC
**0.8048** (mid-pack -- above `mardan` 0.760 and `sukkur` 0.788, below most others).
Its `rate_ratio` (roofclf's own predicted/true adoption-rate ratio) is **0.461** --
roofclf predicts only 4.67% adoption against Hasal's true 10.14%, more than 2x
under-prediction, the same failure shape as Box 11 (Rahim Yar Khan, 0.304-0.332 across
refits). That keeps Hasal just outside `select_calibrated_quadrats`'s `[0.5, 2.0]`
band, so it does **not** enter the trusted-13 set that drives the domain-restricted
sub-400 m² precision/coverage-ratio fit (`sub400_capacity.py`) -- it only widens the
19-quadrat pool behind the pooled LOQO threshold/AUC fit, which moved the deployment
threshold from 0.2405 to **0.2441** and `median_fold_auc` from 0.8824 to 0.8757. This is
a rate-*mismatch*, not a low-quality addition -- Hasal's own discrimination (AUC 0.805)
is unremarkable in the good sense; roofclf simply under-counts adoption there, exactly
as it does at Rahim Yar Khan.

---

### Ground-mount validation against the promoted production checkpoint (2026-08-10)

The "future targeted evaluation" the two ground-mount boxes above were registered for
but never got was run this session: `scripts/validate_groundmount_quadrats.py` scores
`v3_combined_india` (the checkpoint behind `data/predictions/pakistan/prob/` and
`candidates.parquet` -- confirmed the production checkpoint, see CLAUDE.md's "Which
segmentation checkpoint" note) against both sites two ways -- **pixel-level** (raw
probability raster: `scale` = probability-integral / true area, and pixel AUC separating
mapped-PV pixels from background) and **candidate-level** (what `density.py`'s capacity
numbers actually consume, matched within 200 m of the box). Output: `results/
groundmount_quadrat_validation.csv`.

**The model itself is excellent at both sites** -- new evidence, measured cleanly for the
first time:

| site | true area | pixel `scale` | pixel AUC | mean prob on PV / bg |
|---|---:|---:|---:|---:|
| Quaid-e-Azam Solar Park | 8,904,839 m² | **1.011** | **0.9168** | 0.834 / 0.050 |
| Sukkur solar farm | 2,606,013 m² | **0.935** | **0.9552** | 0.885 / 0.024 |

**But almost none of that reaches the published capacity number, and the reason is more
specific than "segmentation underestimates ground-mount" -- and partially corrects the
2026-08-06 entry above.** That entry measured the RAW candidate-area sum at Quaid-e-Azam
Solar Park (10,779,834 m², a "+20% inflation") without checking whether the inflated
area survives `density.py`'s own capacity aggregation. It does not: both contributing
candidates -- the outer-envelope match (8,904,839 m², `osm_matched_id=osm-way/1530316244`)
and the nested member-way match (1,745,036 m², `osm_matched_id=596123516`), confirmed
still geometrically overlapping and still unfixed -- exceed `postprocess.
MAX_CANDIDATE_M2` (100,000 m²) and are excluded from every capacity sum `density.py`
computes. Only one small 13,086 m² fragment survives that filter.

| site | candidate area, all near (old framing) | candidate area, **capacity-relevant** (oversize excluded, matches `density.py`) | capacity-relevant scale |
|---|---:|---:|---:|
| Quaid-e-Azam Solar Park | 10,779,834 m² (scale 1.211, "+20%") | **13,086 m²** | **0.0015** |
| Sukkur solar farm | 44,948 m² (scale 0.017) | 44,948 m² (unaffected -- not oversize) | **0.0172** |

So both sites are near-total misses in the number that actually reaches the atlas --
**~680x undercount at Quaid-e-Azam Solar Park, ~58x at Sukkur** -- via two different
mechanisms now clearly separated from each other and from the model's own (good) output:

- **Quaid-e-Azam Solar Park: correct candidates form, then get discarded.** Both
  oversize candidates have `geometry_source == "osm"` -- they are the exact,
  human-mapped OSM footprint, not a model-polygonized blob. `MAX_CANDIDATE_M2` exists to
  guard against `polygonize_chips` merging an unconstrained false-positive sheet (dry
  riverbed, salt flat) into one multi-km² blob with `confidence` 1.0 by construction --
  it was never meant to also catch a verified real installation whose true footprint
  happens to be large, but currently cannot tell the two cases apart and drops both.
- **Sukkur: root-caused the same session -- `candidates.parquet` is STALE at this site,
  not a `polygonize_chips` failure.** The box spans exactly 2 composite cells
  (`0081_0036`, `0081_0037`, both dated 2026-07-16); `candidates.parquet` is dated
  2026-07-29, 13 days later, so staleness was not the first guess. But re-running
  `postprocess.polygonize_chips` directly against those same two current rasters at the
  standard threshold (0.3) produces **one 2,467,076 m² polygon** -- 94.7% of the true
  footprint, matching the pixel-level `scale` (0.935) almost exactly, and confirming the
  segmentation+polygonize mechanism works fine here once given current data. The 44,948 m²
  fragment sitting in `candidates.parquet` today does not reflect these rasters at all --
  it is stale, from an earlier inference/postprocess pass at this location that was never
  refreshed, the same failure shape already on record elsewhere in this project
  (`candidates.parquet` predating the 2026-07-29 OSM-geometry replacement is the closest
  precedent). The national OSM pull (`pakistan_overpass_solar.parquet`) does have 21
  overlapping elements near this site (largest 2,526,454 m²) -- the same un-dissolved
  nested-mapping problem the quadrat's own targeted pull needed a manual dissolve to fix,
  unfixed at the national source -- so a fresh `postprocess` run's OSM-geometry-replacement
  step would find a match, but which of the 21 raw elements it latches onto (nearest by
  centroid, not necessarily the best single footprint) is not yet checked.

**Not yet fixed.** No change has been made to `postprocess.py` or `density.py`; see the
next section for what a fix would need to look like for each mechanism.

### What a fix would need to look like

**Quaid-e-Azam Solar Park's mechanism has a targeted, low-risk fix candidate: exempt
`geometry_source == "osm"` candidates from the oversize capacity exclusion.** An
OSM-matched candidate's geometry is not something `polygonize_chips` invented -- a human
mapper drew it, so it cannot be the unconstrained-false-positive-sheet failure mode
`MAX_CANDIDATE_M2` exists to catch, regardless of its area. Concretely this would mean
`density.py`'s oversize filter (currently one unconditional `area_m2 > MAX_CANDIDATE_M2`
test) needs to become `(area_m2 > MAX_CANDIDATE_M2) & (geometry_source != "osm")`, or
equivalent. Measured nationally this session: 149 oversize candidates exist (60.72 km² total), of
which **28 are `geometry_source == "osm"`** (18.32 km², every one `placement ==
"no_building"`) -- real, human-verified ground-mount footprints currently excluded from
every capacity number purely for being large. A pairwise geometric-overlap check among
those 28 finds **4 overlapping pairs**: 3 are exact duplicates (same `osm_matched_id`,
identical area -- a trivial dedup, drop one of each pair) and 1 is the QASP nested pair
above (drop the smaller, contained member). Deduped total: **15.22 km²**, which at the
ground-mount site-area constant (`DEFAULT_KWP_PER_M2_LAND = 0.07`) implies roughly
**1,065 MWp** of currently-excluded, OSM-verified ground-mount capacity nationally --
the size of the fix, before touching Sukkur-style staleness at all. Any implementation
needs the same 4-pair dedup this measurement already required, not just the exemption
itself.

**Sukkur needed a different fix: refresh `candidates.parquet`, not change any filter.**
Its mechanism, root-caused above, is stale candidates, not a `polygonize_chips` or
oversize-filter problem -- the segmentation+polygonize pipeline already produces an
accurate large polygon (94.7% of true area) when run against current rasters. The fix
here is operational (re-run `postprocess` nationally so every cell's candidates reflect
the current rasters, addressing the same staleness class already documented for
`candidates.parquet` elsewhere in this project), and once refreshed, Sukkur's new
large candidate would need the SAME OSM-exemption fix as QASP to actually reach
capacity, since it too would land well above `MAX_CANDIDATE_M2`. Whether other
cells nationally carry the same kind of stale-relative-to-current-rasters candidate is
an open question this session did not check beyond these two sites.

### Correction and full fix, same day (2026-08-10, later): Sukkur's root cause was mis-diagnosed above

The staleness explanation above does not survive a direct check: re-running
`postprocess` against Sukkur's own current rasters (no candidate-population change at
all) reproduces the identical 44,948 m² fragment, byte-for-byte. The real mechanism is
the one flagged as unchecked at the end of the entry above -- **the national OSM pull's
21 overlapping, un-dissolved elements near Sukkur**, and `postprocess.
replace_with_osm_geometry`'s nearest-match latching onto whichever small fragment
happens to be closest to a given candidate's polygon, not the site's real combined
footprint. `candidates.parquet` was never stale; the OSM reference it matches against
was un-dissolved.

**Fixed at the source, not by exempting or patching around it.** `labels.
dissolve_overlapping` (new function) merges geometrically-overlapping polygons within
the same `placement` group into one feature per connected cluster, recomputing area
geodesically on the union, before ANY matching happens. `export.
load_mapped_reference_attrs` (feeds `postprocess.replace_with_osm_geometry`) and
`atlas.build_evidence_atlas`'s own OSM Verified-tier sum both now dissolve first.
Measured nationally: ground-mount OSM area 55.95 -> 42.32 km² (-24.4%, the QASP
generator/plant nesting), rooftop 6.21 -> 6.08 km² (-2.1%).

**That fix, on its own, made a second problem WORSE, not better -- caught before
publishing, not after.** A bigger, dissolved reference polygon sits within
`max_distance_m` of more nearby candidates than the smaller fragments it replaced, so
MORE candidates independently matched (and each fully inherited) the SAME real
installation's area: duplicate `osm_matched_id` groups went 16 -> ... a naive
"keep the closest" dedup attempt still left 13 unresolved, because ties at
`dist_m == 0.0` (a candidate whose polygon directly overlaps the OSM feature) are not
resolved by an equality test against the group minimum -- both tied rows pass it.
Fixed with `pandas.groupby(...).idxmin()`, which breaks a tie by position instead of
leaving all of it "the minimum": re-verified on the full national candidate set,
0 duplicate `osm_matched_id` groups remain. Every candidate that matched an
already-claimed feature keeps its OWN original, model-polygonized geometry (not
dropped -- it may be a real, separately-detected patch of the same large site, which is
signal for the human-reviewed leads product even though only the closest match should
carry the site's authoritative OSM footprint for capacity).

**The oversize-exemption fix from the "What a fix would need to look like" section
above was also implemented, as `density.capacity_relevant_candidates`** (a refactor of
the uncommitted `_dedup_osm_oversize` diff already in `density.py` at the start of this
session): `geometry_source == "osm"` candidates are exempted from `MAX_CANDIDATE_M2`,
after deduping overlapping OSM-oversize candidates via `dissolve_overlapping` itself
(replacing the original keep-largest-drop-rest logic, which would have silently lost
whichever part of a smaller, non-fully-nested member sits outside the larger one it
was compared against). `atlas.build_evidence_atlas` now calls the SAME function for
its OSM-matched/unmatched split, so an installation matched only by a candidate this
run excludes from capacity is correctly treated as "still unmatched," not
double-subtracted for nothing (see this doc's earlier "1,704 MWp" measurement, from the
2026-08-10 pipeline-review session, now closed by this shared function).

**The land constant was recalibrated against these same two boxes**, the first
external nameplate-capacity anchors this project has had for it:
`capacity_calibration.DEFAULT_KWP_PER_M2_LAND` moved from a GCR-assumption-derived 0.07
to 0.05 (geometric mean of QASP's 400 MW / 8,904,839 m² dissolved footprint = 0.0449
and Sukkur's confirmed 150 MW combined complex / 2,606,013 m² = 0.0576 -- the OSM tag
on Sukkur's matched way names only one of its three 50 MW phases, so 50 MW alone would
have been a 3x undercount here). See `capacity_calibration.py`'s updated constant
comment for the full derivation.

National re-run of `postprocess` with every fix above (dissolve, dedup,
`capacity_relevant_candidates`): ground-mount candidate area 122.22 -> 123.81 km²
(+1.3%, net of Sukkur-style undercounts being fixed and QASP-style duplicate-match
inflation being fixed roughly cancelling) -- the small net change is not a sign nothing
happened; it is two large, real, opposite-signed corrections landing close to where the
naive number already was, for the first time for the right reason instead of by
coincidence of two uncorrected errors.

### Placement-split calibration, national `density --force`, and a new (different)
### `check-density` failure -- resolved same day, 2026-08-10/11

`capacity_calibration.derive_placement_tables` (new) fits separate rooftop/ground
mapped-fraction and recall tables instead of one pooled set of area bins -- pooling let
ground-mount borrow rooftop's much higher OSM corroboration in the same size bin
(measured: ~1% of surviving ground candidates sit within 100 m of any OSM feature
nationally, vs ~14% for rooftop). Ground bins fall back to `p_unmapped = 0.0`
("interim-mapped-only-by-placement", an honest floor) rather than inheriting the
pooled glint-derived value, since the existing glint sample predates three
candidate-population regenerations and cannot be reliably re-attributed by placement.
Re-derived the calibration table against the **fully refreshed 19-quadrat set**
(15,465 pooled installations, up from the single-box 3,832 the previously-published
table used -- see "redownload all calibration areas" below), then ran `density --force`
(2h18m, 0 cell failures, fingerprint written) followed by a cheap non-`--force` re-run
to pick up the marginal refinement from the last 3 quadrats' refresh (moved the total by
<0.1%). National **`est_mwp_rc`: 5,077.9 -> 4,051.9 MWp** (-20.2%): rooftop
**2,229.9 -> 2,916.3 MWp (+30.8%)**, ground-mount **2,848.0 -> 1,135.6 MWp (-60.1%)** --
exactly the direction predicted going in (pooling had been dragging rooftop's own p_real
down toward ground's, and ground's up toward rooftop's, in every shared bin).

**`check-density` now PASSES the exact check this fix targeted, and fails a different
one.** KP's ground:rooftop ratio (the ratio the 2026-07-30 KP/Balochistan investigation
in this file could not root-cause past "confirmed genuine, not a further bug") moved
3.35-8x -> **0.49x**; Balochistan's moved 3.90-18x -> **2.01x** -- both comfortably
inside the 3.0/5.0 warn/fail band. But 3 regions now fail the OTHER plausibility check,
single-cell concentration (`top_cell_share > 0.25`): Khyber Pakhtunkhwa (cell
`0105_0098`, 42%), Balochistan (`0060_0013`, 31%), Islamabad Capital Territory
(`0120_0099`, 68%). This did not newly appear -- it was always mechanically implied
once the ground-mount over-inflation that used to dominate these regions' totals was
removed: shrinking a wrong, inflated denominator elsewhere in a region necessarily
raises the visible concentration share of whatever legitimate signal remains, even
though that signal did not itself change.

**Checked, not just asserted: all three flagged cells are the calibration quadrats'
own cities, not an artifact.** `0105_0098` and `0060_0013` are Peshawar and Quetta
respectively (`peshawar_calib_1km`/`peshawar_west_calib_4p39km2` and
`quetta_calib_1km` in `results/calibration_quadrats.csv`) -- KP's and Balochistan's
own provincial capitals, and by far their largest cities in provinces that are
otherwise sparse (231 of KP's 733 cells and 148 of Balochistan's 850 carry any
capacity at all, and the gap to the SECOND-largest cell is 4-9x in both). `0120_0099`
is Islamabad's own urban core, in a federal territory of only 10 cells total -- one
city dominating a ten-cell administrative unit built around exactly that city is not a
plausibility failure, it is what the geography actually is. This is the roofclf ge400
domain-replacement mechanism (CLAUDE.md's "roofclf now replaces segmentation's own
rooftop estimate") doing exactly what it was built to do -- concentrate a real,
calibrated per-building estimate in the cells that have calibration ground truth --
made newly visible, not newly wrong, once ground-mount stopped drowning it out.

**Not fixed in code -- a policy question left to the project owner, not a bug this
session found or should silently paper over.** `plausibility.MAX_CELL_SHARE` (0.25) was
never tuned against a province this small or this urban-concentrated; whether it should
gain a size-aware threshold, a per-region exemption (matching Gilgit-Baltistan's
existing `RATIO_CHECK_EXEMPT_REGIONS` precedent for check 1), or simply stay failing
with this documented explanation attached is a threshold-setting decision, not a
correctness one. Full `check-density` output as of this run:

| region | mwp_roof | mwp_ground | nonroof_ratio | top_cell | top_cell_share | status |
|---|---:|---:|---:|---|---:|---|
| Khyber Pakhtunkhwa | 240.3 | 116.8 | 0.49 | 0105_0098 (Peshawar) | 0.42 | fail (concentration) |
| Balochistan | 25.2 | 50.6 | 2.01 | 0060_0013 (Quetta) | 0.31 | fail (concentration) |
| Islamabad Capital Territory | 182.0 | 5.5 | 0.03 | 0120_0099 | 0.68 | fail (concentration) |
| Azad Kashmir | 0.0 | 7.1 | 7052 | -- | 0.12 | suspect (below floor) |
| Punjab | 1,861.5 | 658.4 | 0.35 | 0133_0075 | 0.11 | ok |
| Sindh | 605.4 | 249.1 | 0.41 | 0065_0011 | 0.19 | ok |
| Gilgit-Baltistan | 0.0 | 41.6 | 41584 | -- | 0.13 | ok (ratio check exempted) |

Published anyway, with this table and explanation, matching the project's own
established precedent (the 2026-07-30 KP/Balochistan ratio finding was accepted as
"confirmed genuine" and published unresolved in the same sense) -- the alternative,
holding back a validated, materially-more-correct national number over a heuristic
threshold two calibration-quadrat cities were always going to trip once the number
they used to hide inside was fixed, would be worse than the documented failure.

### All calibration areas re-downloaded, at the owner's request, 2026-08-10/11

All 21 registered quadrats (19 `_calib_` + the 2 `_gmcalib_` ground-mount boxes) were
re-pulled from live Overpass via a new `scripts/refresh_calibration_areas.py`, writing
dated `<stem>_overpass_solar_<date>.parquet` files that never overwrite the pull they
supersede (`roofclf._newest_solar` picks up the newest automatically). Overpass was
under heavy load throughout (repeated 429/504s across all three mirrors), so the run
took several hours and was interrupted once by an unrelated process kill; it resumed
cleanly because the script skips any quadrat whose dated file for the day already
exists, re-fetching only what was still missing.

The two ground-mount boxes produced the most dramatic-looking change: Quaid-e-Azam
Solar Park went from 1 mapped installation to 6, Sukkur solar farm from 1 to 21 -- OSM
had gained more granular way-level mapping of both sites since the last pull. **This
did not change the land-constant calibration**: `labels.dissolve_overlapping` merges
the newly-fragmented ways back into one footprint per site, and the dissolved area came
out byte-identical to the single-feature pull it replaced (8,904,838.5 m² / 2,606,012.6
m² respectively) -- direct confirmation that the dissolve fix is robust to exactly the
kind of re-mapping that motivated re-pulling everything in the first place. The other
17 quadrats' installation counts moved by single digits to low tens of percent (e.g.
Sukkur's rooftop/mixed quadrat 1105 -> 1115, Sundar 132 -> 134), consistent with
ongoing incremental OSM mapping rather than any systematic gap.
