# Calibration data from bought imagery

!!! note "PROPOSED (2026-11-27)"

    Nothing has been bought and nothing below is built. Prices are UP42's catalogue prices
    as printed on 2026-11-27. Whether the archive holds a clear capture over each area
    inside the compose window has not been checked. Airbus's and Planet's licences were read
    in full; Vantor's and the licences UP42 shows per product were not.

!!! tip "Recommended: the OpenStreetMap way"

    The default way to make calibration data is to map it in OpenStreetMap: volunteers trace
    every panel inside a calibration area from the imagery their editor offers (Esri, Bing,
    Mapbox), following [the mapping protocol](calibration-mapping-protocol.md), and the
    [Map a calibration area](contribute/calibration-areas.md) guide. **Use it wherever it
    works.** Data in OpenStreetMap is easier to maintain: anyone can correct it, add the
    panels installed since, or remove the ones taken down; other mappers check it; everyone
    can reuse it; and EarthPV re-reads it with one Overpass query whenever an area is
    refreshed. Outlines traced from bought imagery live only in EarthPV's own files, only the
    buyer's people can see the imagery behind them, and nobody else can keep them current.

This page describes the alternative for places where the OpenStreetMap way cannot deliver:
**buy very-high-resolution archive imagery for just the places that need it, captured inside
the country's Sentinel-2 compose window, and have it mapped or judged by people the buyer
employs or contracts.** For very small regions the place to buy is
[UP42](https://up42.com/), whose catalogue bills an area by its own size, down to 0.1 to 5 km²
depending on the product. Nigeria's ten calibration candidates are the worked example.

!!! warning "The licence must let EarthPV use the data and combine it with other data"

    Imagery is only worth buying for EarthPV if its licence allows everything EarthPV does
    with calibration data. Before ordering, check that the licence lets the buyer and EarthPV:

    1. use outlines and verdicts derived from the imagery in EarthPV's published estimates;
    2. combine them with other data: Sentinel-2, OpenStreetMap, building footprints,
       registers, other countries' calibration areas;
    3. train and evaluate EarthPV's models on them, whose weights are released openly;
    4. publish the derived outlines openly, under EarthPV's data licences.

    A licence that allows only internal use, or forbids using the data to improve other
    datasets, makes the purchase useless to EarthPV however cheap it is. See
    [Which licences qualify](#which-licences-qualify).

## When to use it

Only where the OpenStreetMap way cannot give a usable result:

- **The free imagery predates the composite.** Rule 1 certifies completeness only as of the
  mapping imagery's capture date, so an area mapped on imagery older than the compose window
  misses the newest arrays, and its precision and `base_rate` become lower bounds
  ([imagery dating](issues/calibration-imagery-dating.md)). Imagery bought from inside the
  window closes that gap, and its metadata fills `imagery_date` to the minute.
- **A sampled area fails the imagery gate.** The candidate sampler drops boxes whose Esri
  capture is too old. In Nigeria it rejected 31 draws (captures from 2019-01 to 2024-09) before
  ten passed, so the surviving set is conditioned on where Esri happens to be recent, the bias
  the stratified draw exists to prevent. A bought capture lets a rejected draw stay in.
- **The free imagery is too soft.** By eye, 30 of the 166 open calibration areas were too soft
  on Esri to map small arrays, at a nominal 0.31 to 0.34 m (review of 2026-11-08). A bought
  product states its off-nadir angle, sun elevation and cloud cover over the box before it is
  ordered.
- **A verdict needs more than Sentinel-2.** Since 2026-11-20 reviewers judge candidates on
  Sentinel-2 alone, and what 10 m pixels cannot settle stays unsure and out of capacity until
  someone maps it. A 30 or 50 cm capture of the candidate can settle it.
- **Nobody volunteers, but someone can pay.** A partner with staff but no mapping community can
  still produce complete areas.

## Nigeria's calibration areas

Nigeria's ten candidate areas, as published on the [Nigeria atlas](atlas-nigeria.md) in
mapping order, cover 28 km² and hold about 9,500 buildings. Esri already passes the 12-month
gate on all ten, but the capture over eight of them predates the compose window (2025-11-01 to
2026-03-15) by 5.6 to 11.8 months. Buildings are VIDA footprints inside the box; the Esri date is
the oldest of centre and corners.

| # | area | state | box | buildings | Esri capture | before the window opens |
|---:|---|---|---|---:|---|---:|
| 1 | Ikeja (start here) | Lagos | 1 km | 1,231 | 2025-05-15 | 5.6 months |
| 2 | Ikorodu | Lagos | 1 km | 711 | 2024-11-30 | 11.0 months |
| 3 | Ado Odo/Ota | Ogun | 1 km | 2,291 | 2025-04-29 | 6.1 months |
| 4 | Ojo | Lagos | 1 km | 979 | 2024-11-06 | 11.8 months |
| 5 | Kware | Sokoto | 2 km | 2,053 | 2025-03-16 | 7.6 months |
| 6 | Kafur | Katsina | 2 km | 777 | 2025-04-15 | 6.6 months |
| 7 | Kibiya | Kano | 2 km | 565 | 2025-02-18 | 8.4 months |
| 8 | Ukwa West | Abia | 2 km | 464 | 2024-12-18 | 10.4 months |
| 9 | Bauchi | Bauchi | 2 km | 256 | 2025-12-21 | inside |
| 10 | Gombi | Adamawa | 2 km | 156 | 2025-12-11 | inside |
| | **total** | | **28 km²** | **9,483** | | |

### What the imagery costs

UP42 prices in credits (100 credits = €1, sold from €100). An area smaller than a product's
minimum is billed at the minimum. One capture per area; the margin adds 100 m around each box
for alignment and for arrays on the line. The four Lagos-area boxes lie 20 to 25 km apart, so
each area is its own order.

| product | resolution | credits per km² | minimum billed area | ten boxes (28 km²) | with 100 m margin (34.8 km²) |
|---|---|---:|---|---:|---:|
| Airbus Pléiades Neo (Display or Analytic) | 30 cm | 1,800 | 0.1 km² for scenes ready in 10 minutes; 5 km² for scenes delivered in 2 days | €504; €900 at the 5 km² minimum | €626; €900 |
| Vantor WorldView Legion or WorldView-3 | 30 cm | 2,200 | 1 km² | €616 | €766 |
| Airbus Pléiades | 50 cm | 1,000 | 0.1 km² or 1 km² | €280 | €348 |

**One 30 cm capture of all ten areas costs about €500 to €900.** For rooftop arrays of a few
panels, buy 30 cm; Pléiades Neo's "HD15" product is computed from the same 30 cm data, adds no
information to settle a verdict on, and is billed at 25 km². UP42 bills its non-integrated
products at 25 km² too, so stay with the integrated ones above. Whether a scene is in the
10-minute catalogue shows only in a catalogue search.

The protocol asks mappers to flip between imagery layers, because an array dark on one pass is
obvious on another; one bought capture is one look. A second date per area doubles the figures
(about €1,000 to €1,800 for Nigeria) and is worth most in the dense Lagos boxes.

If the archive holds nothing clear in the window, UP42 also takes orders for a new capture,
at higher prices and larger minimum areas; not costed here. Southern Nigeria (Lagos, Ukwa West)
is cloudy for much of the year and the north hazy with Harmattan dust from December to
February, so the south is where the archive is likeliest to come up empty.

Any other country's 1 to 4 km² candidate boxes cost the same way: about €20 to €90 per area for
one 30 cm capture.

### The imagery is the small cost

Every one of the ~9,500 buildings in Nigeria's boxes still has to be inspected and every panel
traced. This project has no measured mapping rate, so the time is not estimated here, but paid
mapping of that many roofs costs well above the imagery. Bought imagery cannot go to
volunteers (below), so a bought area is mapped by the buyer's own people, and it keeps costing:
when the area is refreshed, someone has to buy a newer capture and update the outlines, work
OpenStreetMap's mappers would otherwise share.

## Checks on candidates

The [candidate-precision calibration](methods/calibration.md) needs people's verdicts on the model's
large outlines. The same catalogue makes a high-resolution look at one candidate cheap: a
300 m window around a lead is 0.09 km², billed at the product's minimum.

| product | resolution | one lead, 10-minute scene | one lead, 2-day scene |
|---|---|---:|---:|
| Airbus Pléiades | 50 cm | €1.00 | €10.00 |
| Airbus Pléiades Neo | 30 cm | €1.80 | €90.00 |
| Vantor WorldView Legion or WorldView-3 | 30 cm | €22.00 (1 km² minimum) | €22.00 |

Leads of a hectare and more are well resolved at 50 cm, so a hundred unsure verdicts cost
roughly €100 to €1,000 of imagery. The verdicts are then recorded in the review files with the
product as their imagery, not mapped into OpenStreetMap (see below).

## Which licences qualify

**Airbus, Standard End-User Licence (version November 2025)**, which covers Pléiades and
Pléiades Neo, meets all four requirements above:

- 1.1(e) grants "the right to access or use the PRODUCT for the purpose of developing or
  training machine learning algorithms".
- 1.1(c) and (g): the end user may produce derivative works and "owns and may freely
  distribute DERIVATIVE WORKS to third parties". A derivative work "does not contain any
  imagery data from the PRODUCT and is irreversible and uncoupled from the PRODUCT". A traced
  outline or a verdict is one, so it can be combined with any other data and published under
  EarthPV's licences. If a partner buys the imagery, it can still hand the outlines to EarthPV.

Its limits fall on the imagery, not on what is derived from it:

- 1.2(a): the imagery may go to no third party other than contractors who agree in writing,
  in advance, to the same limits and to return it (1.1(f)), "nor transfer outside of the
  territory of its establishment, unless expressly authorised by AIRBUS DS". So
  **volunteers cannot map bought areas**, and **who buys decides where the mapping happens**:
  imagery bought in Germany may not go to mappers in Nigeria without Airbus's written consent,
  while imagery bought by a Nigerian organisation stays in Nigeria and only the outlines travel.
- 1.2(d) forbids publishing a competitive analysis or benchmark of the product, for instance
  a public comparison of what Pléiades Neo shows against Esri.

**Planet, Master Content License Agreement 2026.1 (effective 2026-06-24)** fails: 3.2(a)(g)
forbids using the content or its derivative products "to calibrate, tune, or otherwise improve
the accuracy of any non-Planet satellite imagery or geospatial datasets, whether via
algorithmic processing, artificial intelligence training, or manual correlation", and 3.2(b)
bars open-sourcing a model improved on the content unless the order permits it. Do not buy
Planet products (SkySat) for EarthPV under these terms.

**Check before ordering**: UP42 shows each product's licence only in its console (Account
management, EULAs), and Vantor's licence text was not read. Read the licence attached to the
order against the four requirements, and ask UP42 in writing where it is unclear. A Pléiades or
Pléiades Neo order should carry Airbus's Standard licence or one at least as permissive.

**OpenStreetMap.** The OSM Foundation's Licence and Legal FAQ (2.1.2) does not allow importing
data whose rights belong to someone else "unless you have a specific waiver and their agreement
that it will be licensed under the ODbL". Outlines traced from bought imagery therefore stay in
EarthPV's own files unless the imagery owner grants that waiver. Ask for it with the order:
with a waiver the outlines can go into OpenStreetMap and be maintained there like any other
calibration area, which is the better outcome.

**The project's own rule.** Since 2026-11-20 a verdict EarthPV uses rests on Sentinel-2 or is an
installation mapped in OpenStreetMap (CLAUDE.md, "No verdict from imagery the project may not
use"). Imagery bought under a licence that meets the four requirements is imagery the project
may use, but the rule names only those two sources: admitting a third is the owner's decision.

## How it would run

1. **Pick the places that need it**: calibration candidates whose free imagery fails the date
   gate or is too soft (for Nigeria, the ten, or a redraw of the sampled eight without the Esri
   gate), or candidates whose Sentinel-2 verdict stayed unsure.
2. **Search UP42's catalogue** (free) for each: a capture inside the compose window, clear over
   the box, off-nadir below about 20 to 25 degrees, nearest the window's middle.
3. **Read the licence** against the four requirements, then order 30 cm (50 cm for candidate
   checks), one polygon per area with a 100 m margin. Keep the product id, capture time,
   off-nadir angle and licence with the order.
4. **Map or judge** in JOSM or QGIS with the image as a local layer, by the buyer's staff or
   contractors who have signed the licence's terms. Rule 1 is unchanged: every panel inside the
   line, and a second mapper checks.
5. **Store** the outlines as a label file with the columns of an Overpass pull, published under
   EarthPV's data licences; upload to OpenStreetMap only with the imagery owner's waiver.
6. **Register** the area with `imagery_layer` = the product and `imagery_date` = its capture
   date.

What would need building: `scripts/new_calibration_quadrat.py` always pulls an area's labels
from Overpass, so it needs a file-based label source and the provenance fields;
`propose_calibration_candidates.imagery_gate` reads Esri only; the review pages record
Sentinel-2 as every verdict's imagery; and the atlas offers every area for "Open in iD/JOSM",
which a bought area cannot offer the public, so it needs a "mapped on bought imagery" state.

## Decisions for the owner

1. Whether verdicts and outlines from bought imagery under a qualifying licence may feed
   calibration (an addition to the 2026-11-20 rule).
2. Who buys, which decides who may map: Open Energy Transition, or a partner in the country
   whose people map there.
3. One capture per area or two.
4. For Nigeria, keep the ten Esri-gated candidates or redraw without the Esri gate.
5. Ask the imagery owner for an OpenStreetMap waiver (recommended, so the outlines can be
   maintained in OpenStreetMap), or keep them in EarthPV's files.

## Sources

Read on 2026-11-27.

- UP42: [minimum charges for catalog](https://docs.up42.com/data/catalog-min-charges),
  [Pléiades Neo](https://docs.up42.com/data/pleiades-neo), [Pléiades](https://docs.up42.com/data/pleiades),
  [Vantor](https://docs.up42.com/data/vantor), [credit purchase](https://docs.up42.com/getting-started/credits/purchase)
  and [EULAs](https://docs.up42.com/getting-started/eulas).
- Airbus Defence and Space, [licences](https://space-solutions.airbus.com/legal/licences/):
  Standard End-User Licence Agreement, version November 2025.
- Planet, [Master Content License Agreement 2026.1](https://planet.widen.net/s/gmbbjxcggq/master-content-license-agreement_2026.1).
- Vantor, [legal index](https://vantor.com/legal).
- OSM Foundation, [Licence and Legal FAQ](https://osmfoundation.org/wiki/Licence/Licence_and_Legal_FAQ).
- Nigeria's candidate areas: `docs/assets/labels/calibration_areas/nigeria.geojson` and
  `data/labels/nigeria/candidate_quadrats/screened_out.csv`.
