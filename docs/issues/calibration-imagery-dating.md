# Calibration quadrat imagery dating: an unrecorded gap, and what closing it would cost (2026-08-01)

## The known issue

`docs/calibration-mapping-protocol.md`'s "Imagery and dating (critical)" section already
anticipated this risk when the protocol was written (2026-07-18):

> PV in Pakistan grows fast. A calibration quadrat mapped against year-old imagery reads
> as "model overcounts" when the model simply sees newer panels. If the best imagery is
> older than ~12 months, flag the quadrat.

It requires every quadrat's register row to carry `imagery_layer` and `imagery_date`. In
practice, **that field has never been populated for any of the real quadrats** --
`docs/issues/pakistan-calibration-boxes.md` records "no imagery-date record" repeatedly
across the boxes it documents. So the true capture date of the Esri/Bing/Mapbox/Maxar
background imagery a mapper used to declare "no PV here" is genuinely unknown for every
quadrat currently feeding `roofclf`'s LOQO training/eval, the SPPI cross-validation, and
every precision/recall/AUC number derived from them (`docs/methods/density.md`).

This is a gap in *provenance*, not a demonstrated error -- it does not mean any specific
number above is wrong. It means the tool to check whether it's wrong (comparing label
imagery date against the Sentinel-2 window the model actually scored) doesn't exist yet.

## The mechanism, and why it specifically threatens the numbers already on record

Neither Esri World Imagery nor Mapbox Satellite (nor Bing) is a single-date snapshot --
each is a rolling composite mosaic stitched from many source captures, refreshed at
different cadences per region. Pakistan sits outside the highest-priority refresh tier
these commercial providers maintain, and -- based on how these services generally
operate, not on a Pakistan-specific check -- rural/informal/arid tiles (several of this
project's calibration strata) are plausibly on the older end of whatever range applies.

The Sentinel-2 composites this project scores against default to a
`2025-11-01`–`2026-03-15` window (`imagery.py::annual_composite`'s default; the actual
local Pakistan composites reused from `rooftopsenti` may use a different window -- not
verified here). If a quadrat's background imagery predates that window, any panel
installed in the gap is real in the Sentinel-2 data but absent from the ground-truth
label -- the model's correct detection gets scored as a false positive, deflating
measured precision for reasons that have nothing to do with the classifier being wrong.

This would bite hardest in the fastest-growing, highest-adoption quadrats -- which is at
least *suggestive* alongside the already-documented finding that `roofclf` overestimates
2x+ specifically in the low-base-rate quadrats (Multan, Sialkot, Sundar;
`docs/methods/density.md`'s "SPPI cross-validation" section). **This is a plausible
contributing confound, not a replacement for the other false-positive mechanisms already
verified in this project** (bare/arid land, industrial roof glare) -- it has not been
measured to actually explain any share of the overestimation, only proposed as untested.

## What it would cost to close the gap by buying dated imagery

Explored 2026-08-01 as a live question ("could we just buy fresh, dated imagery for the
existing ~9-20 quadrats"), not executed:

- **Area is small but minimum-order size dominates cost.** Quadrats run 1-4 km²
  (averaging ~2 km², per the mapping protocol), so 20 quadrats is only ~40 km² of
  nominal coverage. Commercial providers (Maxar, Airbus/Pleiades, Planet SkySat)
  generally enforce a minimum order area regardless of how small the actual AOI is --
  historically often 25 km² for archive-style orders, sometimes 100 km² for fresh
  tasking -- so small quadrats get billed at the minimum floor, not a naive
  area &times; per-km² rate.
- **Archive vs. tasked (new) capture** is the other major lever: archive imagery (an
  existing recent pass) is markedly cheaper than tasking a brand-new collection
  (weather-dependent, slower, pricier, larger minimum order).
- **Rough, uncertain estimate** (2026 pricing not independently verified -- treat as a
  ballpark, not a quote): archive imagery with minimum-order fees absorbed, roughly
  **$5,000-$25,000** for 20 quadrats; if any require fresh tasked capture, potentially
  **$20,000-$60,000+**. Getting an actual number would need a quote from a provider or
  reseller (Apollo Mapping, EOS Data Analytics, etc.), ideally requesting several small
  AOIs bundled into one order to dodge per-order minimums.
- **Licensing wrinkle**: a standard commercial purchase (Maxar SecureWatch, Airbus,
  Planet) does not automatically grant the right to trace new features into OpenStreetMap
  the way Esri/Bing/Mapbox's existing JOSM arrangement does. That only matters if the
  goal is tracing new PV from the purchased imagery; if the goal is only checking a
  date for QA (not tracing), standard licensing terms are irrelevant.

## Cheaper alternatives, likely sufficient for the actual need

The immediate need identified above is "know the capture date," not "acquire new
traceable imagery" -- two free tools plausibly answer that without any purchase:

- **Esri World Imagery Wayback** -- a free archive of dated historical captures per
  tile, built specifically because the live Esri layer has no single date.
- **Google Earth Pro's historical-imagery slider** -- free, date-stamped, often has
  multiple passes per year even for Pakistan.

## Recommendation

1. Before considering any purchase, check the existing 9-10 calibration quadrats
   against Esri Wayback and/or Google Earth Pro's historical slider, and backfill the
   `imagery_layer`/`imagery_date` fields the protocol already asks for
   (`docs/calibration-mapping-protocol.md`'s register schema) -- this is very likely
   free and directly closes the provenance gap.
2. Only pursue a commercial purchase if free tools cannot resolve the date for a
   specific quadrat, and even then, request one bundled quote across all quadrats
   needing it rather than 20 separate small orders.
3. Once dates are known, compare them against the Sentinel-2 compose window actually
   used for that quadrat's cell(s) to test -- for the first time with real data, rather
   than by inference -- whether stale reference imagery contributes to any of the
   documented overestimation in low-base-rate quadrats.
