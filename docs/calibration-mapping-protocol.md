# PV calibration-ground mapping protocol (Pakistan)

**Audience:** the OSM mapping team building calibration areas for earthpv's
Sentinel-2 solar-density estimation.
**Status:** draft v1, 2026-07-18.

## Why this mapping exists

earthpv estimates rooftop/ground PV density per 0.1° grid cell across Pakistan
from 10 m Sentinel-2 imagery. The model is deliberately recall-first: it
overcounts in some landscapes (bare/arid land looks like panels) and
undercounts in others (small roofs are below sensor resolution — detection
measured at only ~6% for sub-100 m² installations vs ~73% for utility plants).
To publish honest density numbers, we measure these errors against ground
truth: small areas where **every** PV installation is mapped, so the model's
output over each area can be compared against reality, per landscape type.

That works only if "no PV mapped here" genuinely means "no PV exists here."
This leads to the one rule that overrides everything else:

> **Rule 1 — completeness beats coverage.** A quadrat is only usable when
> *every visible panel inside it* is mapped, down to the smallest rooftop
> unit. A half-mapped quadrat is worse than an unmapped one, because it
> silently teaches the calibration that the model overcounts. If you cannot
> finish a quadrat, say so — it will be excluded, no harm done.

## The quadrat plan

~25–35 quadrats across 6 landscape strata, each quadrat 1–4 km². Each stratum
gets 4–6 quadrats spread across different cities/provinces; one quadrat per
stratum is held out to validate the calibration and must be mapped to the same
standard.

| # | Stratum | Where (examples) | Quadrat size | Why it matters |
|---|---|---|---|---|
| 1 | Affluent planned housing | DHA/Bahria-type societies: Lahore, Karachi, Islamabad/Rawalpindi | 1–2 km² | Highest rooftop-PV adoption; regular concrete roofs |
| 2 | Dense older urban / informal settlement | inner-city Lahore, Karachi, Faisalabad | 1 km² | Small, irregular, often sub-10 m roofs — where the model undercounts most |
| 3 | Peri-urban / tehsil town | mid-size towns, one per province | 2 km² | Middle of the building-size distribution, mixed roof materials |
| 4 | Irrigated rural village + fields | Punjab and Sindh canal-irrigated belts | 2–4 km² incl. surrounding fields | Solar tube wells / irrigation pumps — ground-mounted, small, easily missed |
| 5 | Arid / bare-land settlement | Balochistan, Thar fringe | 2–4 km² | Bare ground is the model's main false-positive class — these measure overcounting |
| 6 | Industrial zone | Faisalabad, Sialkot, Karachi industrial estates | 1–2 km² | Large metal roofs, big captive-PV arrays, different spectral behaviour |

Utility-scale plants are **not** part of this protocol — they are already well
covered in OSM and TZ-SAM.

### Choosing the exact quadrat

- Draw a simple rectangle; snap edges to roads/canals so the boundary is
  unambiguous on imagery.
- Pick *typical* neighbourhoods, not showcase ones. Do not choose a quadrat
  because you already know it has (or lacks) solar — that biases the sample.
  Pick by landscape type first, look at panels second.
- Avoid quadrats that straddle two strata (e.g. half planned housing, half
  informal). Move the rectangle until it is one thing.
- Record the rectangle as a GeoJSON polygon before mapping starts.

## What counts as PV (map all of it)

- Rooftop panels of any size — including single-panel household units.
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
exists. Do not invent capacity values — panel geometry is the ground truth
here, not wattage.

## Imagery and dating (critical)

- Map against the **most recent** high-resolution imagery available (Esri
  Clear/Maxar/Bing — record which, and its capture date if the layer exposes
  it).
- PV in Pakistan grows fast. A calibration quadrat mapped against year-old
  imagery reads as "model overcounts" when the model simply sees newer
  panels. If the best imagery is older than ~12 months, flag the quadrat.
- Record for every quadrat: mapper name, mapping completion date, imagery
  layer + capture date (or "unknown").

## Completeness declaration and QA

A quadrat is *done* when:

1. The mapper declares: "every visible PV installation inside the boundary is
   mapped" — scanned systematically (street-by-street / block-by-block, not
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

## Deliverables per quadrat

- Boundary polygon (GeoJSON, in the shared register).
- All PV features mapped **directly in OSM** (they benefit the map as well as
  the calibration — that's deliberate).
- The register row above.

## Common failure modes (please read)

- Mapping only the obvious/large installations and moving on — breaks Rule 1.
- Tracing roofs instead of panels — inflates area ground truth.
- Choosing a quadrat *because* it is full of solar — biases density upward.
- Copy-pasting a capacity guess into `generator:output:electricity` — poisons
  downstream capacity estimates; geometry only, unless documented.
- Silent partial work: an unfinished quadrat left looking finished is the one
  error we cannot detect later. Mark unfinished work `fixme=incomplete
  calibration quadrat` immediately.
