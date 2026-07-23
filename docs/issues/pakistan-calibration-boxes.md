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

**What this does and doesn't change:** re-ran `calibrate-candidates` after adding this
box's labels — the country-wide `mapped_frac` table is numerically unchanged, because
none of our candidates sit near these 8 features (they only affect stats for candidates
that are near them). The existing calibration pipeline has no mechanism to fold in a
recall signal at all — a box like this is currently a qualitative spot-check, not
something that moves `p_real`. n=8 ground truth / n=1 candidate is also far too small a
sample to recalibrate a bucket on its own (contrast the glint LR calibration's 500-target
study). Treat this box as one data point in what should become a small library of them —
useful pattern going forward: fetch fresh Overpass data for any newly-completed mapping
pass and log precision/recall here, the same way `pakistan_stats_by_size.csv` accumulated
from repeated glint studies.
