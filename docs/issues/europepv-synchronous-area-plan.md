# EuropePV: an evidence atlas for the Continental Europe Synchronous Area, plan, 2026-11-12

!!! note "PLANNED, NOT STARTED (2026-11-12)"

    Nothing on this page has been built or run. It is the proposed design, the data
    inventory and the time and disk estimate for one combined evidence atlas over the
    Continental Europe Synchronous Area (CESA), reusing national PV registers in place of
    calibration quadrats for the half below 400 m². Every rate quoted below was read off
    this machine's own pipeline markers and logs on 2026-11-12; every schedule figure is
    derived from those rates and is an estimate. Register coverage in "The data" is a
    desk inventory and must be verified source by source before anything depends on it.

    Not yet decided by the owner: whether to build it at all, the scope (EU core plus
    Switzerland first, or the whole area), which disk takes it, and whether the GPU is
    shared with the ResNet runs launched 2026-11-11 while it runs.

    Updated 2026-11-13: which registers and calibration data are already on this machine
    and what each can calibrate ("Already on this machine"), every resource the build needs
    in one place ("Resources"), and the disk and queue state that day ("State on
    2026-11-13").

## Why

A per-cell, size-resolved, imagery-dated inventory of existing PV across the synchronous
area does not exist. The global inventories stop at utility scale; the national registers
stop at their borders and their schemas; every TSO forecast and adequacy study carries
behind-the-meter PV as a modelled residual, which the 28 April 2025 Iberian blackout
investigation singled out as a visibility gap. EarthPV already has eleven European atlases
and the combine machinery to sum them on the global lattice. What it lacks is a sub-400 m²
instrument that does not need hand-mapped calibration quadrats in every country, because
those cannot be produced for twenty-five countries.

## The method: registers replace quadrats, footprints replace the classifier

The German result (`docs/results/germany.md`) decides the method. Where rooftop PV is
near-ubiquitous, roof area in the 200-400 m² band priced at a register-fitted constant
beats roofclf at municipality scale (median municipal error 35.6% against 48.4%), and no
label strategy ever moved the classifier past that baseline. Quadrats exist to measure the
coverage ratio a classifier's scores need. A roof-area estimator needs only a level per
regime, and a register gives that at municipality resolution: thousands of calibration
points instead of nineteen.

The sub-400 m² half of EuropePV is therefore:

1. **Band roof area everywhere**, from VIDA footprints with OSM fill
   (`scripts/fill_vida_from_osm.py`). It needs no imagery, so the sub-400 half of every
   country can be built before a single composite exists.
2. **One constant per register country**, fitted per municipality as
   `scripts/calibrate_germany_capacity.py` does, with that country's own cross-validated
   municipal error as its stated uncertainty.
3. **Countries with only a national statistic** (Eurostat, IRENA and SolarPower Europe cover
   every CESA member) take the level from the national rooftop total and the geography from
   band roof area. The page must say the geography there is unmeasured: band roof area is
   nearly proportional to population, and the standing rule applies, a national total
   agreeing is not evidence the geography is right.
4. **A transfer test for free**: fit on Germany, predict Denmark, the Netherlands, Italy and
   Switzerland per municipality. That measures how far the geography transfers between
   subsidy regimes, which a continental product must state and which quadrats could never
   give.
5. **Registers with coordinates calibrate the >= 400 m² half's precision too**, the way
   MaStR's `p_unmapped` already does for Germany (`scripts/mastr_p_unmapped.py`), so
   segmentation's precision tables for those countries need no quadrats either.

Where adoption is sparse (most of the western Balkans, Ukraine, the Maghreb) the band method
overpredicts geography and the page reads "not measured" below 400 m² unless a register pins
it: the existing segmentation-only atlas path, nothing new.

The >= 400 m² half stays as it is: segmentation localized per country on its own OSM labels
(owner rule), the blob and large-installation reviews, the lead files.

## The data

### Registers (desk inventory, to verify)

| Resolution | Countries |
| --- | --- |
| Per unit with coordinates or address (confident) | Germany (MaStR, >= 30 kWp located), Denmark (Energistyrelsen), Switzerland (BFE production plants) |
| Per municipality (confident) | France (ODRE), Netherlands (CBS per gemeente), Italy (GSE Atlaimpianti per comune, by size class), Flanders (VEKA), Wallonia (CWaPE) |
| Per region or national only (needs checking) | Austria, Czechia, Poland (URE prosumer counts), Hungary, Slovenia, Croatia, Spain, Portugal (DGEG NUTS II), Luxembourg (ILR), Greece, Romania, Bulgaria |

The first deliverable is a checked-in inventory, one row per CESA country (source, URL,
resolution, size classes, vintage, licence), beside `configs/external/official_capacity.yaml`,
and a generic register adapter in place of the MaStR-only fit (AGS join, MaStR schema).

### Already on this machine (checked 2026-11-13)

Only Germany and France are on disk at municipal resolution. Every other European figure
the atlases use was typed into `scripts/official_capacity.py` (`PUBLISHED`) at national or
regional level, so it can set a country's level or check its province chart but cannot fit a
constant per municipality.

| Country | Data | Where | Resolution | Vintage | What it calibrates today | What it can calibrate for EuropePV |
| --- | --- | --- | --- | --- | --- | --- |
| Germany | MaStR (open-MaStR) | `~/.open-MaStR/data/sqlite/open-mastr.db` (4.6 GB); per Gemeinde in `data/calibration/mastr_gemeinden.parquet`, `mastr_rooftop_counts.parquet`, `mastr_rooftop_units_by_ags.parquet`; boundaries `data/calibration/vg250_gem.parquet` | per unit, coordinates from 30 kWp; per Gemeinde | downloaded 2026-07-08 | sub-400 constant 0.03493 kWp/m² on 200-400 m² roof area (median municipal error 35.6%); `p_unmapped` for segmentation; province chart | the reference fit, the source side of the transfer test, and the template for the register adapter. Refresh the snapshot first (four months old). |
| France | ODRE year-end vintages 2020-2025 | `data/register/odre_solaire_3112{20..25}.csv` (177 MB; `scripts/fetch_odre_vintages.sh`) | per commune or IRIS; units below 36 kW aggregated; no coordinates, no rooftop or ground field | 2025-12-31 is the newest vintage on disk | module constant 0.150 kWp/m² against 14 hand-mapped communes; province chart | a per-commune fit, with the rooftop share bracketed (17-31%), never stated |
| France | 14 hand-mapped communes (Rule 1) | `data/labels/france/` | quadrats | mapped 2026 | the module-constant check | an independent check of the French fit at commune level |
| Poland | URE renewable installation list ("Mapa OZE") | `data/external/ure/MAPAOZEna30092026nastroneURE.xlsx` | 8,337 PV installations with gmina, powiat, voivodeship; no coordinates; 50 kW and up only (13.4 GW) | 2026-09-30 | province chart | precision of the >= 400 m² half per gmina. Not the sub-400 half: the list leaves out the microinstallations (about 13.7 GW), which need ARE or DSO counts |
| Netherlands | CBS 85005NED | typed in (`PUBLISHED`), national | the table itself is published per gemeente and by capacity class | 2025-12-31 | national comparison | per-gemeente fit once the gemeente rows are downloaded |
| Italy | GSE Rapporto Statistico 2025 | typed in, 21 regions summed into ISTAT's 5 macro-regions | regional (GSE Atlaimpianti has per-comune data, not downloaded) | 2025-12-31 | province chart | per-comune fit once Atlaimpianti is downloaded |
| Belgium | Elia ods032 | typed in, 3 regions | regional (VEKA and CWaPE publish per municipality, not downloaded) | 2026-09-30 | province chart | per-municipality fit for Flanders and Wallonia once downloaded |
| Denmark | Energistyrelsen quarterly note | typed in, national | national (the Energistyrelsen plant register is per unit, not downloaded) | 2026-09-30 | national comparison | per-unit fit once the register is downloaded |
| Portugal, Spain, Luxembourg | DGEG (NUTS II), REE, ILR | typed in | regional or national | 2025-12-31 to 2026-09-30 | national comparison | level only |
| All | Ember China panel exports | `data/external/ember_20261019/` | national | 2026-10 | import ceiling on every page | nothing (not ground truth) |

Other local data that EuropePV reuses directly: VIDA footprints with OSM fill for Belgium,
Denmark, Spain, Italy, Luxembourg, the Netherlands and Portugal
(`/home/tobi/earthpv_data/<ISO3>_vida_osmfill.parquet`) and raw VIDA for Germany, France,
Poland and Turkey (never checked for holes; Spain's and the Netherlands' had block-shaped
ones); per-country OSM solar pulls and CSP tables in `data/labels/`; geoBoundaries ADM1/ADM2
in `data/geoboundaries/`; the PVGIS probe grids in `data/irradiance_probes/`; the Europe
preview in `data/combined/` (uncommitted).

### Already on disk (2026-11-12)

Eleven European AOIs are composed, 32,772 cells at about 10 MB each (330 GB on /home):

| AOI | Cells | State |
| --- | --- | --- |
| France | 6,858 | published, off the global lattice |
| Spain | 5,712 | published |
| Turkey | 5,534 | published |
| Germany | 4,871 | published, off the lattice; `density_gcell` split exists |
| Poland | 3,948 | published |
| Italy | 3,193 | published 2026-11-12 |
| Portugal | 948 | published |
| Denmark | 704 | published 2026-11-12 |
| Netherlands | 541 | published |
| Belgium | 423 | published |
| Luxembourg | 40 | published |

Also reusable: `earthpv combine-atlas` (Europe preview of DE+FR+PL+TR, 21,051 cells, Best
125,416 MWp, unpublished and uncommitted), the size-band builder
(`scripts/build_germany_sub400_atlas_inputs.py --method size_band`), the register fit,
Morocco's atlas for the Maghreb ring, VIDA footprints for DE, FR, NL, BE, LU, IT, DK, ES,
PT, PL.

Two gotchas carry over. Germany and France sit off the lattice (Germany's roofclf half is
already split per global cell; France has no roofclf half). The first-wave composites
(Germany, France, Poland) are `nearest` resampled while the later ones are bilinear, so the
localized models see two kinds of imagery; never mix modes within an AOI.

### Missing

- **EU core plus Switzerland**: Austria, Switzerland, Czechia, Slovakia, Hungary, Slovenia,
  Croatia, Romania, Bulgaria, Greece. About 904,000 km², which at roughly 80 km² per lattice
  cell and the 1,000-buildings floor is **8,000 to 11,000 new cells**. No VIDA, no
  composites, no labels, no AOI blocks.
- **Second ring**: the Baltics (in CESA since February 2025), the western Balkans, Ukraine
  and Moldova (since 2022), and the populated Maghreb (Algeria, Tunisia; Morocco exists).
  About **14,500 more cells**.
- **A footprint-only sub-400 builder.** The size-band builder as written reads the national
  roofclf scoring output for its building list, so it still needs `roofclf-score-national`
  (about 2.4 min per cell on Germany: eight days for a Germany-sized country). A DuckDB
  pass over VIDA per cell, with no classifier, is about a day of work and reduces that step
  to minutes per country. Build it first.
- **The combined page at continental scale**: built at 21,000 cells, needed at 60,000 or
  more. Two to three days.

## Measured rates

| Stage | On this PC |
| --- | --- |
| Compose | 80 to 85 cells per hour (link bound, 7 MB/s), about 10 MB per cell |
| Train, checkpoint pick, local-vs-v5 decision | 10 to 30 GPU hours per country |
| Infer | about 1,400 cells per hour (Spain 5,712 in 4 h, Italy 3,193 in 2 h) |
| Postprocess through atlas | 1 to 5 hours per country |
| roofclf national scoring | about 2.4 min per cell (Germany); avoided by the footprint-only builder |

## Timeline

Three tracks run in parallel; the link and the single GTX 1060 are the pacing resources, not
CPU or RAM.

**EU core plus Switzerland, 3 to 4 weeks:**

- *Compose track*: about 115 h continuous for 9,500 cells, realistically 7 to 10 days with
  DNS drops, restarts and VIDA preparation per country (source.coop throttles single
  streams; `scripts/ranged_download.py`).
- *GPU track*: ten countries at about 20 h each is 8 to 9 days with the GPU exclusive, plus a
  day of inference. Doubles if the ResNet v41 and localized-ResNet runs keep the lock.
- *Register track* (CPU and agent time, no imagery): the inventory, the adapter, seven or
  eight registers with different schemas, the per-municipality fits and the transfer test.
  One to two weeks, overlapping the other two completely.
- *Then*: the continental combine, and the owner's blob and large-installation reviews per
  country (hours of human time each), which gate what counts.

**Whole area, 6 to 8 weeks**: about a week more of compose and ten more GPU days for twelve
small countries.

## Disk

| Item | EU core + CH | Whole area |
| --- | --- | --- |
| Composites (10 MB per cell) | 95 GB | 240 GB |
| VIDA footprints with OSM fill (1 to 4 GB per country) | 15 GB | 30 GB |
| Chips (2 to 4 GB per country) | 30 GB | 70 GB |
| Predictions, density, atlases (0.5 MB per cell) | 5 GB | 12 GB |
| Registers and combined output | under 10 GB | under 10 GB |
| **Total new** | **about 150 GB** | **about 350 GB** |

Headroom on 2026-11-12: moreaidata 180 GB free, the root disk 35 GB free at 98%, aidisc
31 GB. The EU core fits on moreaidata alone if nothing else grows. The whole area needs
about 200 GB more, which `/home/tobi/earthpv_data` (341 GB) can give up without a new disk
once the owner confirms what each block still backs:

| Directory | Size | What it is |
| --- | --- | --- |
| `roofclf_national_with_sppi` | 44 GB | Pakistan's national scoring passes, with dated PRE copies |
| `archive` | 33 GB | superseded runs |
| `aef` | 32 GB | AlphaEarth embeddings, rejected 2026-10-22 |
| `fair_score` | 26 GB | zero-shot benchmark scoring of candidate models |
| `roofclf_points` | 15 GB | Pakistan's 75.7 M scores as points, for owner verification |
| `geofabrik` | 13 GB | PBF extracts, re-downloadable |

The root disk at 98% is a risk for anything running now: compose on a full disk dies with
exit code 120 and a truncated log. Free it before launch.

## Resources

Everything the build needs, in one place. Rates, timeline and disk are derived above.

**Machine.**

- *Network link*, about 7 MB/s: paces compose at 80 to 85 cells per hour, and every VIDA,
  Geofabrik and register download. More compose workers make it slower, not faster.
- *GPU*, one GTX 1060 6 GB, shared by every earthpv and subdetect job through
  `data/.gpu.lock`: paces training (10 to 30 h per country) and inference (about 1,400 cells
  per hour). `scripts/gpu_priority.py --aoi <aoi>` gives a country the card between its
  steps.
- *CPU and RAM* do not pace anything. Long jobs run as their own `systemd-run --user` units
  with a `MemoryMax` (lingering is on), never as `nohup`.

**Disk.** About 150 GB new for the EU core plus Switzerland and 350 GB for the whole area
(table above), best on moreaidata. That disk is a partition of the same spinning disk as
`/home`, so it adds no throughput, and it is mounted by udisks, not fstab: after a reboot
its links in `data/` dangle until it is mounted again. The root disk must be freed before
anything starts (see "State on 2026-11-13").

**People (the owner, or any named reviewer).**

- *Solar farm and large installation reviews*, one page per country, which gate what
  counts. For scale: Germany 581 blobs and 7,592 large leads, Spain 998 blobs, Italy 377
  blobs and 4,586 large leads. The owner judged 2,335 large leads of seven countries in
  one day (2026-11-10).
- *Decisions*: whether to build, the scope, the disk, the GPU order against other runs,
  which registers may set a country's level, and what space under
  `/home/tobi/earthpv_data` may be freed.
- *No calibration areas to map* in a country whose register is municipal or finer; that is
  the point of the method. A country with only a national figure gets a level with its
  geography marked unmeasured, again without mapping.

**Agent work (code and data, no imagery).**

| Item | Estimate |
| --- | --- |
| Register inventory YAML, one row per CESA country, every source checked | 1 to 2 days |
| Generic register adapter (municipal boundaries, a join key, size classes, vintage) replacing the MaStR-only fit | about 2 days |
| Download and parse the municipal registers (CBS gemeente, GSE Atlaimpianti, VEKA, CWaPE, Energistyrelsen, BFE, a refreshed MaStR) | 3 to 4 days |
| Per-country fits with cross-validated municipal error, and the cross-regime transfer test | about 2 days |
| *Register track in all (the four rows above)* | *8 to 10 working days, the "one to two weeks" of the timeline* |
| Footprint-only size-band builder (DuckDB over VIDA per cell, no classifier) | about 1 day |
| Combined page and `combine-atlas` at 60,000+ cells | 2 to 3 days |
| Per new country: AOI block, `configs/atlas/<aoi>.yaml`, official figures, Ember re-run, results page, `ATLASES` row | a few hours each |

**External data (all open; licences go in the inventory).** Sentinel-2 L2A from Planetary
Computer (Earth Search as fallback); VIDA Open Buildings from source.coop (needs a
User-Agent; `scripts/ranged_download.py`); Geofabrik extracts for the OSM fill; Overpass
for solar labels and roads; geoBoundaries ADM1/ADM2; the registers above plus Eurostat,
IRENA or SolarPower Europe for countries with only a national figure; Copernicus GLO-90 for
the steep-lead screen; PVGIS for the generation tile; Ember for the import ceiling.

**Software.** Nothing new to install: the `default`, `ml` and `docs` pixi environments as
they are.

## State on 2026-11-13

- **Disk**: the root disk (`/home`) has 14 GB free (100%), down from 35 GB the day before,
  while California's compose (1,225 of 1,405 cells) still writes to it. moreaidata has
  178 GB free, aidisc 31 GB. `/home/tobi/earthpv_data` holds 343 GB, the reclaimable blocks
  in "Disk" among them. Nothing should be added to `/home` before space is freed.
- **Link and GPU are committed** to the runs queued 2026-11-10: California (composing),
  Texas (trained, waiting for the GPU for its decision and inference), Mexico (VIDA ready
  on moreaidata, compose not started), the ResNet floor-100 test (v43 trained, v42
  training) and the localized ResNet comparisons for California, Texas and Mexico. EuropePV's
  compose and GPU tracks start after them unless the owner reorders the queue; the register
  track does not need either and can start at any time.
- **The released model changed**: v28, the ResNet-50, became the default model on
  2026-11-12. New countries are still localized on their own labels (owner rule). Whether
  that fine-tune starts from TerraMind as today or from the ResNet, and so what each
  country's training costs, is open until the localized ResNet runs report (Denmark, on
  a thin holdout: +28/-1 arrays against its TerraMind model at that model's precision).
- **Italy and Denmark are published** (2026-11-12), so all eleven European AOIs in the
  table above have a published atlas. The Europe preview (Germany, France, Poland, Turkey)
  is still unpublished and uncommitted.

## Order of work

1. Register inventory YAML and the generic register adapter; fit Germany, Denmark,
   Switzerland, the Netherlands, Italy, France, Belgium; run the cross-regime transfer test
   and record the per-country municipal error.
2. Footprint-only size-band builder; rebuild the sub-400 half of every existing European
   atlas with it where a register exists (Germany's published figure must reproduce).
3. VIDA, labels, AOI blocks and compose for the EU core plus Switzerland, in installed-PV
   order, through the existing country queue; segmentation chain per country as today.
4. Continental combine at 60,000+ cells; the "like for like" layer and per-member caveats as
   in the Europe preview; publish.
5. Second ring, same steps.

## Who would use it

PyPSA-Eur and the open energy modelling community (brownfield existing capacity per cell);
ENTSO-E (TYNDP and ERAA distributed-generation assumptions) and the TSOs that run the load
forecasts (RTE, Terna, REE, TenneT, the German four); DSOs and regulators checking register
completeness; the JRC, IEA PVPS and SolarPower Europe as a spatial layer under their
statistics; ESA and IBM as a continental TerraMind showcase; the OSM solar mapping community
through the per-country lead files. What makes it defensible is the validation story: six to
eight countries where every municipality is a test point, with the transfer error between
regimes stated on the page, at no mapping cost.
