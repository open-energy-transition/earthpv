# PV calibration-ground mapping protocol (Pakistan)

**Audience:** the OSM mapping team building calibration areas for earthpv's
Sentinel-2 solar-density estimation.
**Status:** draft v1, 2026-07-18.

## Why this mapping exists

earthpv estimates rooftop/ground PV density per 0.1° grid cell across Pakistan
from 10 m Sentinel-2 imagery. The model is deliberately recall-first: it
overcounts in some landscapes (bare/arid land looks like panels) and
undercounts in others (small roofs are below sensor resolution, so detection
measured at only ~6% for sub-100 m² installations vs ~73% for utility plants).
To publish honest density numbers, we measure these errors against ground
truth: small areas where **every** PV installation is mapped, so the model's
output over each area can be compared against reality, per landscape type.

That works only if "no PV mapped here" genuinely means "no PV exists here."
This leads to the one rule that overrides everything else:

> **Rule 1, completeness beats coverage.** A quadrat is only usable when
> *every visible panel inside it, as of the reference imagery available to the
> mapper* is mapped, down to the smallest rooftop unit. A half-mapped quadrat
> is worse than an unmapped one, because it silently teaches the calibration
> that the model overcounts. If you cannot finish a quadrat, say so; it will
> be excluded, no harm done.
>
> **Rule 1 is bounded by imagery epoch, not just mapper effort (amended
> 2026-08-11).** JOSM's background imagery (Esri/Bing/Maxar) is generally
> captured earlier than the Sentinel-2 composite the model reads, so a panel
> installed in that gap cannot be mapped no matter how carefully the quadrat
> is swept -- it exists in the model's input and cannot exist in the labels.
> A Rule-1 declaration therefore certifies "every visible panel as of the
> mapping imagery's capture date," not "there is no PV here the model could
> see." Record the imagery layer and its best-known capture date for every
> quadrat (`imagery_layer`/`imagery_date` below) so this gap is visible
> per-quadrat instead of assumed away.

## The quadrat plan

~25–35 quadrats across 6 landscape strata, each quadrat 1–4 km². Each stratum
gets 4–6 quadrats spread across different cities/provinces; one quadrat per
stratum is held out to validate the calibration and must be mapped to the same
standard.

| # | Stratum | Where (examples) | Quadrat size | Why it matters |
|---|---|---|---|---|
| 1 | Affluent planned housing | DHA/Bahria-type societies: Lahore, Karachi, Islamabad/Rawalpindi | 1–2 km² | Highest rooftop-PV adoption; regular concrete roofs |
| 2 | Dense older urban / informal settlement | inner-city Lahore, Karachi, Faisalabad | 1 km² | Small, irregular, often sub-10 m roofs, where the model undercounts most |
| 3 | Peri-urban / tehsil town | mid-size towns, one per province | 2 km² | Middle of the building-size distribution, mixed roof materials |
| 4 | Irrigated rural village + fields | Punjab and Sindh canal-irrigated belts | 2–4 km² incl. surrounding fields | Solar tube wells and irrigation pumps: ground-mounted, small, easily missed |
| 5 | Arid / bare-land settlement | Balochistan, Thar fringe | 2–4 km² | Bare ground is the model's main false-positive class, so these measure overcounting |
| 6 | Industrial zone | Faisalabad, Sialkot, Karachi industrial estates | 1–2 km² | Large metal roofs, big captive-PV arrays, different spectral behaviour |

Utility-scale plants are **not** part of this protocol; they are already well
covered in OSM and TZ-SAM.

### Choosing the exact quadrat

- **The boundary does not have to be a rectangle.** Any closed shape works, and
  following roads, canals or the edge of a built-up area is usually better than a
  square, because a square clips arbitrary halves of whatever it lands on. See
  "Drawing the boundary in JOSM" below for how to hand one over.
- Snap edges to features that are unambiguous on imagery, so a second mapper can
  tell exactly where the boundary runs.
- Pick *typical* neighbourhoods, not showcase ones. Do not choose a quadrat
  because you already know it has (or lacks) solar. That biases the sample.
  Pick by landscape type first, look at panels second.
- Avoid quadrats that straddle two strata (e.g. half planned housing, half
  informal). Move or reshape the boundary until it is one thing. An irregular
  boundary makes this easier, not harder: it can follow the actual edge of the
  stratum instead of splitting the difference.
- Record the boundary as a GeoJSON polygon before mapping starts.

### Drawing the boundary in JOSM

Draw the area in JOSM, select it, and use **File -> Save As -> GeoJSON**. Then hand
the file over and it gets registered with:

```bash
python scripts/new_calibration_quadrat.py --name gujranwala_east \
    --geojson ~/drawn/gujranwala_east.geojson --dry-run   # inspect first
python scripts/new_calibration_quadrat.py --name gujranwala_east \
    --geojson ~/drawn/gujranwala_east.geojson             # then register
```

`--dry-run` prints the geometry report, the overlap check against every existing
quadrat, and the district lookup without writing or fetching anything. The script
refuses to register a boundary that overlaps an existing quadrat unless
`--allow-overlap` is passed, because pooling overlapping quadrats double-counts the
shared installations and breaks leave-one-quadrat-out fold independence (Boxes 9 and
10 share a corner, which is why that check exists).

Four things about a drawn boundary that are worth knowing before you map, not after:

- **Close the way.** JOSM exports a closed way as a GeoJSON polygon only when it
  carries area tags; an untagged closed way comes out as a `LineString`. The importer
  converts a closed `LineString` back to a polygon and rejects an open one with a
  clear error, so either is fine, but an unclosed way is not.
- **Several pieces are allowed.** Multiple features in one file are unioned into one
  boundary. Every stage reads the union, so a two-part quadrat is a single unit for
  base rate, packing distance and leave-one-quadrat-out folds.
- **Keep the bounding box under about 2.2 km in both directions.** A training chip
  is 224 px at 10 m = 2,240 m, so a boundary that fits inside one is framed by one
  chip window. A larger one is tiled across several covering windows, which works and
  loses no mapped ground, but it buys more chips for the same supervision and dilutes
  the quadrat's weight in the training corpus. A long thin shape following a canal for
  4 km is better registered as two or three separate quadrats. The importer prints
  `chip_fit` and `bbox_fill` so this is visible up front, and `earthpv quadrat-chips`
  logs the covered share of every boundary rather than truncating one silently.
- **Size guidance is 1-4 km², and it is guidance.** The importer warns outside
  0.4-4 km² and proceeds; the first Rule-1-complete quadrat is 0.49 km². A small box
  gives a noisy `base_rate`, a large one is a long mapping job.

Nothing downstream cares about the shape: `chips.quadrat_chips`,
`roofclf.building_table` and every quadrat evaluation script mask and rasterise the
real geometry. What *is* shape-dependent is the reported `side_m`, which is written
only for actual squares, and the `_calib_<tag>` name suffix, which becomes the
geodesic area (`..._calib_1p24km2`) instead of a side length.

## What counts as PV (map all of it)

- Rooftop panels of any size, including single-panel household units.
- Ground-mounted arrays of any size, in fields, yards, compounds.
- Solar water pumps / tube-well installations (panels on frames near wells).
- Solar street lights and telecom-site panels **only if** panel area is
  discernible on imagery; a lone pole-top panel smaller than ~1 m² may be
  skipped, consistently.
- Panels under construction: map if panels are physically visible on the
  imagery date.

Not PV: solar water *heaters* (tubes/tanks, usually round or with a visible
cylinder), skylights, blue-painted roofs, water tanks. When genuinely
undecidable at maximum zoom, tag with `fixme=possible solar` rather than
guessing either way.

## How to draw

- **Trace the panel area only, never the whole roof.** The model estimates
  panel area; a roof-sized polygon inflates ground truth.
- One polygon per contiguous panel group. Separate groups on the same roof =
  separate polygons.
- For tiny installations where tracing is hopeless (< ~4 m²), a node with the
  correct tags is acceptable; note `panel:area` in m² if estimable.

## Tags

```
power=generator
generator:source=solar
generator:method=photovoltaic
generator:output:electricity=yes        (add value in kW only if known, never guessed)
location=roof                           (rooftop) | omit for ground-mounted
```

For solar pumps add `pump=powered` on the associated well/pump node where one
exists. Do not invent capacity values; panel geometry is the ground truth
here, not wattage.

## Imagery and dating (critical)

- Map against the **most recent** high-resolution imagery available (Esri
  Clear/Maxar/Bing. Record which, and its capture date if the layer exposes
  it).
- PV in Pakistan grows fast. A calibration quadrat mapped against year-old
  imagery reads as "model overcounts" when the model simply sees newer
  panels. If the best imagery is older than ~12 months, flag the quadrat.
- Record for every quadrat: mapper name, mapping completion date, imagery
  layer + capture date (or "unknown").

**Known gap (2026-08-01):** this field has not actually been populated for any of the
real quadrats mapped so far -- see
[Calibration quadrat imagery dating](issues/calibration-imagery-dating.md) for the
mechanism by which that matters, free tools (Esri Wayback, Google Earth Pro's
historical slider) that can likely backfill it at no cost, and what it would cost to
close the gap with purchased imagery if those don't suffice.
`results/calibration_quadrats.csv` now carries `imagery_layer` and `imagery_date`
columns so the gap is visible per quadrat; they are still empty for all seventeen.

**This bounds what a completeness declaration can mean (owner, 2026-08-05; folded into
the Rule 1 definition itself 2026-08-11).** The OSM background imagery a mapper works
from is generally *older* than the Sentinel-2 composite the model reads, and the newest
installations are therefore unmappable -- they exist in the model's input and cannot
exist in the labels. So **Rule-1 certifies completeness as of the mapping imagery, not as
of the model's epoch**, and it only becomes a statement about the latter once
contemporaneous imagery is acquired and swept. Do not read a Rule-1 declaration as
"there is no PV here that the model could see". The practical consequences: precision
measured against these negatives is a **lower bound**, `base_rate` is a **lower bound**
and `rate_ratio` an **upper bound**; recall over mapped installations is unaffected.
`scripts/fraction_stale_label_audit.py` measures the size of the effect without any new
mapping, and it is large in exactly the dense small-rooftop quadrats the sub-400 m² work
depends on (68.4% of apparent false positives in Karachi coastal).

**Open item, not yet pursued: closing this gap needs imagery contemporaneous with (or
newer than) the Sentinel-2 composite, which JOSM's default background layers do not
reliably provide.** A future completeness pass against high-resolution imagery tasked or
sourced specifically for this purpose (e.g. a commercial Maxar/Planet capture, or any
systematically recent-capture layer) could certify a quadrat against the model's own
epoch rather than an unknown, generally older one -- narrowing or eliminating the
lower-bound/upper-bound qualifications above rather than just measuring their size.
Nothing in the pipeline depends on this happening; `fraction_stale_label_audit.py`
remains the interim, no-new-imagery way to bound the effect until it does.

## Completeness declaration and QA

A quadrat is *done* when:

1. The mapper declares: "every visible PV installation inside the boundary is
   mapped": scanned systematically (street-by-street / block-by-block, not
   free roaming).
2. A **second mapper** independently sweeps the same quadrat and either adds
   what was missed or countersigns. Disagreements resolved together; the
   number of installations added by the second pass is recorded (it is itself
   a useful completeness statistic).
3. The declaration row is added to the shared register:

```
quadrat_id, stratum, province, boundary_geojson, mapper1, mapper2,
date_completed, imagery_layer, imagery_date, n_installations,
n_added_by_second_pass, notes
```

**Packing distance is computed automatically, not recorded by hand.** Once a
quadrat's installations are mapped, `roofclf.packing_density` derives the median
distance from each sub-400 m<sup>2</sup> installation to its nearest neighbour --
measured 2026-07-29 to correlate strongly (r=0.70-0.82) with how a quadrat's
calibration numbers (`exp_scale`, `auc_within_size`) behave, a continuous proxy for
the stratum table above (see [Capacity density](methods/density.md#packing-distance-a-cheap-measured-proxy-for-stratum)).
Worth checking when *choosing* a new quadrat's location. As of 2026-07-29 the existing
nine split cleanly into "packed tighter than one Sentinel-2 pixel" (7-19 m) and
"sparse" (44-52 m) with nothing in between, and this paragraph called a quadrat landing
in that 20-40 m gap new information rather than a duplicate. **Two have since landed
there** -- Rahim Yar Khan at 20.3 m and Peshawar West at 34.0 m -- so the gap is now
known to be an artifact of which boxes had been picked, not a real feature of Pakistani
settlement. The useful check today is therefore the reverse: prefer a location whose
likely packing distance is *under-represented* across the current thirteen, rather than
assuming any particular band is empty.

## Validating every quadrat in one pass

Rule 1 is judged per quadrat against high-res imagery, and doing that one boundary file at
a time is how quadrats end up half-checked. This exports **all** of them as a single JOSM
layer:

```bash
pixi run calib-export
# -> results/calibration_quadrats_validation.geojson   (13 boxes + 3,353 installations)
# -> results/calibration_quadrats_validation.mapcss    (JOSM paint style)
```

Re-run it whenever a quadrat is added or an `_overpass_solar` pull is refreshed; it reads
whatever is on disk (`roofclf.discover_quadrats` plus `_newest_solar`'s dated-file-wins
rule), so it never shows a stale pull. `--boundaries-only` drops the solar polygons if you
only want the boxes; `--no-mapcss` skips the style file.

The layer holds two kinds of feature, and both are needed for the job. The
`quadrat_boundary` polygon is the **exact geodesic box**, drawn as a heavy dashed outline
with almost no fill so imagery reads through it -- completeness is judged strictly *inside*
that line, and a panel one metre outside is out of scope rather than a miss. The
`mapped_solar` polygons are what OSM already has, so what you are hunting is panels in the
imagery with **no** polygon on them.

### Loading it in JOSM

1. **File -> Open** the `.geojson`. It arrives as its own data layer.
2. **Preferences -> Map Paint Styles -> +** and point at the `.mapcss` next to it.
   Without it JOSM paints every imported way the same colour and the boundary stops being
   distinguishable from the panels, which defeats the point.
3. Turn on the imagery layer the register records for that quadrat (see
   [Imagery and dating](#imagery-and-dating-critical)) -- not whatever loads by default.
4. Download OSM data for the box you are working on, then **make every edit in the OSM
   layer**, never in the imported one.

The style encodes what to look at:

| appearance | meaning |
| --- | --- |
| red dashed box | quadrat boundary, Rule-1 complete |
| orange dashed box | quadrat boundary, **not** completeness-checked -- these are the ones worth your time |
| blue fill | mapped installation **below** 400 m², the population most often missing from OSM |
| amber fill | mapped installation at or above 400 m² |
| violet fill | mapped, but only **partly** inside the box (see below) |
| dashed outline | ground-mounted rather than rooftop |

!!! warning "Never upload this layer to OSM"
    The boxes are not OSM features and the solar polygons are a snapshot copy of features
    that already exist. Uploading the layer would duplicate every installation in it and
    add 13 nonsense squares. Every feature carries a `do_not_upload` tag as a tripwire, but
    the real protection is keeping it as a separate layer and editing only in the OSM one.

### Two things in the file that are easy to misread

**Violet "edge straddling" polygons are already mapped.** An installation whose
representative point falls outside the box but whose footprint reaches inside is out of
scope for the completeness count, yet it is still exported -- because a panel visibly
inside the line with nothing drawn on it reads as unmapped, and re-mapping it would
duplicate an existing OSM feature. Each box carries both counts: `n_mapped_solar` (all
installations in the pull, the number
[the overview table](methods/calibration-quadrats.md#current-quadrats) reports) and
`n_inside_box`.

**A missing `placement` tag does not mean "not a rooftop".** Five of the pulls
(Faisalabad, Lahore, Multan, SITE Karachi, Sundar -- the oldest five) predate placement
classification and carry no `placement` at all, so their polygons never render with the
ground-mount dashes regardless of what they are. Absent, not "rooftop".

## Deliverables per quadrat

- Boundary polygon (GeoJSON, in the shared register).
- All PV features mapped **directly in OSM** (they benefit the map as well as
  the calibration, and that is deliberate).
- The register row above.

## Common failure modes (please read)

- Mapping only the obvious or large installations and moving on. Breaks Rule 1.
- Tracing roofs instead of panels. Inflates area ground truth.
- Choosing a quadrat *because* it is full of solar. Biases density upward.
- Copy-pasting a capacity guess into `generator:output:electricity`. Poisons
  downstream capacity estimates; geometry only, unless documented.
- Silent partial work: an unfinished quadrat left looking finished is the one
  error we cannot detect later. Mark unfinished work `fixme=incomplete
  calibration quadrat` immediately.
