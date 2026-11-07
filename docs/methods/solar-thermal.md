# Solar thermal power plants

!!! info "Status: shipped 2026-11-07"
    Evidence atlases count concentrated solar power (CSP) plants mapped in OpenStreetMap in
    their Best estimate and their Verified floor, at their electric rating, and keep solar
    thermal out of every photovoltaic figure. Every published country has been checked except
    France and Germany (see the table at the end).

OpenStreetMap tags solar thermal installations with the same `generator:source=solar` (or
`plant:source=solar`) as photovoltaic ones. Two kinds matter here: concentrated solar power
plants, mirror fields that focus sunlight to drive a steam turbine, and solar water heaters,
collectors on roofs that heat water. Neither is photovoltaic. Counted as PV, a mirror field
adds capacity that does not exist (South Africa's Khi Solar One covers 5.97 km&sup2;, which the
ground-mount land constant of 0.05 kWp per m&sup2; would read as 298 MWp against its 50 MW), and
as training labels it teaches the model that mirrors are panels.

Since October 2026 solar thermal has been taken out of each new country's labels
(`scripts/drop_solar_thermal.py`). Since 7 November 2026 the atlas also counts the CSP plants
themselves, in every country, as a component of their own.

## What counts

A plant counts when OpenStreetMap maps it as a `power=plant` whose `plant:method` names
`thermal` (never `photovoltaic`: a hybrid outline is part PV and stays with PV) and which
carries a `plant:output:electricity` tag. A thermal plant with only a hot-water or heat output
is a heating plant (solar district heating, common in Germany and Poland) and does not count,
nor do solar water heaters: the atlas measures electricity. A plant lying mostly inside
another plant's outline is a part of it (Solaben 2 inside the Solaben complex) and counts once,
through the larger outline. A few plants carry no thermal tag at all and are named in
`drop_solar_thermal.KNOWN_THERMAL` on documentary evidence (Parque solar Alvarado II in Spain,
whose English name says "Solar Thermal Power Plant").

What is solar thermal at all, for removal from the PV side, is wider: any element whose
method names thermal, whose `generator:type` is a CSP collector type or
`solar_thermal_collector` (added 7 November 2026: Spain had 161 collector rows typed that way
with no method tag, 156 of them inside Alvarado II), and any feature lying at least half
inside a CSP plant's outline whatever its tags. The last rule exists because mappers often
draw a plant's mirror rows with the photovoltaic preset: all seven South African plants carry
such rows, 50 of them covering 13.4 km&sup2;, which the published page counted as about 670 MWp
of ground-mount PV.

## Capacity

The plant's own `plant:output:electricity` where it gives a number. Where it does not (a
bare `yes`), or where the number is implausibly high for the site, capacity is the site area
times **27.2 MW per km&sup2;**, the median of the 46 plants of at least 0.2 km&sup2; that carried
an MW tag in South Africa, Morocco, Spain and Turkey (10-90%: 18.9-42.8 MW per km&sup2;).
"Implausibly high" means more than three times that density on a site of at least
0.5 km&sup2;, which is what a tag naming a whole complex looks like: Noor 3's outline is tagged
582 MW, the total of Noor 1 to 4, and the site rule gives it 158.6 MW against its rated 150.
Only high tags are overruled: tower plants are legitimately sparse (Khi Solar One 8.4 MW per
km&sup2;, Gemasolar 10.4).

## In the atlas

The plants join the hand-mapped population after its dissolve, as ground rows priced at their
rating instead of an area constant. They are always counted from the map: no satellite
detection stands in for a mirror field, and they never enter the absorption of mapped misses
into the satellite total. So they are in Verified and in Best, in the map's OSM-mapped view and
in the province figures, and they have:

- a tile, *Solar thermal power (CSP), OpenStreetMap, MW*, where the country has any, so the
  tiles still add up to Best;
- a map quantity of their own in *Show*;
- a row in the composition bar and in the uncertainty plot;
- a step in *How the estimate is built*.

A tagged plant is its nameplate and carries no error of its own. Plants priced from site area
share one lognormal draw with the measured spread (log-SD 0.41), which, like the kWp
constants, is the same draw in every country. A page whose country was never checked says so
(`totals.csp_status.checked: false`) rather than showing zero.

Best and Verified are otherwise photovoltaic module capacity in MWp; the CSP plants add
their electric rating in MW, and the page says so wherever it shows them.

## Running it

`scripts/solar_thermal_plants.py --aoi <aoi> --osm-solar <the atlas's OSM file>
[--candidates <candidates.parquet>]` does it for one country: it drops solar thermal from the
OSM file the atlas counts (rewritten in place, the original kept beside it), writes
`data/labels/<aoi>_csp_plants.parquet` (even when empty), removes model candidates at least
half inside a solar thermal outline, and writes its reports to `results/solar_thermal/`. The
atlas reads the table by itself. A changed candidate file means `density` must run again
before the atlas. `run_country_compute.sh` runs it after the national OSM file is built.

## Per country

Checked 7 November 2026. *Removed from PV* is what left the OSM file the atlas counts;
*candidates* are model outlines removed because they lay on a solar thermal outline.

| Country | CSP plants | MW | Removed from PV | Candidates | Page |
| --- | ---: | ---: | --- | ---: | --- |
| Spain | 43 | 2,383.0 | 1,409 label features (281 PV-tagged inside plants) | - | atlas not yet built |
| South Africa | 7 | 600.0 | 50 PV-tagged mirror rows, 13.4 km&sup2; | 0 | Verified 9,393.8 to 9,322.7; Best 9,910.2 to 9,839.0 |
| Morocco | 3 | 518.6 | none (filtered in October) | 0 | Verified 380.4 to 898.9; Best 416.5 to 935.1 |
| India | 4 | 197.9 | 30 outlines, 9.1 km&sup2; | 5 | Verified 70,523.4 to 70,266.0; Best 103,036.9 to 102,779.7 |
| Turkey | 1 | 5.8 | none | 0 | Verified 10,709.1 to 10,714.9; Best 17,592.6 to 17,598.4 |
| Poland | 0 | 0 | 14 collectors, 0.003 km&sup2; | 0 | Verified 6,604.3 to 6,604.1; Best 9,110.3 to 9,110.2 |
| Egypt, Pakistan, Namibia, Zambia, Nigeria, Yemen, Vietnam | 0 | 0 | none | 0 | unchanged, page not rebuilt |
| France, Germany |  |  |  |  | not checked yet (scan stopped 7 November) |

Spain's MW is 2,243 from tags and 140 from site area (Helios, tagged only `yes`, reads 65 MW
against its 2 x 50 MW). Plants left out as heating plants: four in Spain (among them the
Plataforma Solar de Almer&iacute;a research site), the NISE campus at Gwal Pahari in India, two
solar district heating plants in Poland's area (Senftenberg among them, tagged
`plant:output:electricity=no`) and one unnamed plant in Turkey.
