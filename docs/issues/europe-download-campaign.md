# Europe-wide data campaign: plan, 2026-09-20

!!! note "PLANNED, NOT STARTED (2026-09-20)"

    Nothing in this page has been built or run. It is the agreed design for a
    Europe-wide download campaign (all of Europe except Russia and Belarus, including
    Turkey), prepared so it can be launched in one command and left to run unattended
    for weeks. Every measurement quoted below was taken on 2026-09-20 against the live
    system; every schedule figure is an estimate derived from those measurements and is
    superseded the moment `scripts/europe_cell_survey.py` runs for real.

    Decisions already taken by the owner, and not open: all 43 countries in
    installed-PV priority order, accepting that the tail runs past the return date; the
    base 44-country list; `--resampling nearest` pinned across the campaign; and the
    full segmentation atlas per country, as Zambia and Nigeria were run.

## Why

France and Germany are the only European countries earthpv has imaged. Everything the
pipeline needs for a country it has never seen comes from four open sources, and three of
them are cheap. The expensive one, Sentinel-2 composites, is bandwidth-bound on this
machine, which makes a Europe-wide run a scheduling problem rather than an engineering
one. This page records the design, the measurements behind it, and the things that will
silently go wrong if they are not guarded before launch.

## Four facts that set the shape

**One AOI per country is forced by the code, not chosen.** `compose._aoi_boundary`
resolves exactly one ISO3, `buildings.fetch_vida_building_points` reads exactly one
`data/vida/<ISO3>.parquet`, and `buildings._iso3_for` returns one code. A single `europe`
AOI would resolve one country's border and one country's buildings and silently drop the
other 43 through the `contains_xy` clip. So the campaign is **42 new AOI blocks**; France
and Germany are reused as they stand and are never re-run.

**All 44 countries are available in VIDA.** Every ISO3 was probed with a HEAD request on
2026-09-20 and every one returned HTTP 200. Total **36.9 GB**, of which FRA (4.09 GB) and
DEU (4.27 GB) are already on disk, leaving **~28.5 GB** to fetch. The largest are UKR
3.48 GB, GBR 2.80 GB, TUR 2.75 GB, POL 2.44 GB, ITA 2.35 GB.

**The schedule is a property of the link, not the pipeline.** Compose is bandwidth-bound
at roughly 6 MB/s over a USB WiFi adapter; the built-in ethernet interface reports
`NO-CARRIER`. Measured sustained rates across three country runs:

| Run | Cells | Wall clock | cells/min |
|---|---|---|---|
| Zambia, clean, terminated on `rc=0` | 1,843 | 34.4 h | 0.89 |
| France, national build, 2 h passes | +5,249 | 131.8 h | 0.66 |
| France, no-filter top-up | +1,385 | 31.8 h | 0.73 |
| Nigeria, including a 17 h livelock | 2,393 | 83.4 h | 0.48 |

Europe is **40,000 to 74,000 cells** depending on the density filter, so **7 to 12 weeks**.
Plugging an ethernet cable into the router before leaving is worth more than every
optimisation in this plan combined.

**Bulk output goes on `/` (sda4, 1.1 TB free), never on aidisc** (19 GB free, 92% used).
`data/composites/{france,germany,nigeria,pakistan,zambia}` are already symlinks into
`/home/tobi/earthpv_composites/`; France was once created as a real directory on aidisc
and filled the drive to 2.0 MB free at 2,789 of 5,471 cells.

## Scope and budget

| Layer | Volume | Wall clock | Lands in |
|---|---|---|---|
| geoBoundaries ADM1/ADM2 | under 1 GB | minutes | `data/geoboundaries/` |
| VIDA buildings, 42 countries | ~28.5 GB | 1-2 days | `/home/tobi/earthpv_data/vida/` |
| OSM solar labels, 42 countries | under 1 GB | 1-2 days | `data/labels/<aoi>_overpass_solar.parquet` |
| Sentinel-2 composites | ~490 GB at `--min-buildings 1000` | **7-12 weeks** | `/home/tobi/earthpv_composites/<aoi>/` |
| Probability rasters and atlas per country | ~25 GB | overlaps compose | `/home/tobi/earthpv_data/predictions/<aoi>/` |

Per-cell constants measured on this machine: **~12 MB per composite cell**, **~0.26 MB per
prediction cell** (France: 6,858 cells, 1.8 GB). Hard floor: pause the queue when `/` drops
below **120 GB** free.

`--min-buildings 1000` is sweep 1, matching Zambia and Nigeria. Germany and France are
already at no filter. A later `--min-buildings 1` sweep is purely additive, since the
`n >= 1000` cell set is a subset of the `n >= 1` set and compose skips what already exists,
so it can be run on return without redoing anything.

## Priority order

By installed PV capacity, because that is what "where is the capacity" means. Ordering by
area would put Norway and Iceland first for roughly zero GWp.

```
italy, spain, netherlands, poland, turkey, united_kingdom, belgium, greece, austria,
switzerland, hungary, portugal, romania, czechia, bulgaria, denmark, sweden, ireland,
slovakia, lithuania, slovenia, croatia, estonia, finland, latvia, ukraine, cyprus,
luxembourg, malta, serbia, moldova, bosnia_herzegovina, north_macedonia, albania,
montenegro, kosovo, norway, iceland, andorra, liechtenstein, san_marino, monaco
```

The queue completes countries one at a time, so at any moment the finished ones are whole
and usable and the unfinished ones are untouched.

## What gets built

### `scripts/europe_countries.py`

Single source of truth imported by every other script here: one row per country with
`iso3`, `iso2`, `aoi` key, display name, priority rank and compose-window band. No bounding
boxes live here; those are derived, so they cannot drift from the boundary the code
actually clips on.

### `scripts/europe_preflight.py`

Read-only, run before anything is registered. Per country it fetches and caches
geoBoundaries ADM1, computes the ADM1-union bounds, and derives `bbox` and `grid_origin`
such that **both cell-naming paths agree**.

This is the top unattended correctness risk. `compose.populated_cells` takes its grid
origin from `boundary.total_bounds` when the boundary resolved and from `cfg["bbox"]` when
it did not, and `density.fetch_geoboundaries` has no cache, no User-Agent and no retry. One
transient failure mid-campaign would rename every cell and orphan what is already on disk.
Setting `bbox` to the ADM1 bounds floored and ceiled to 0.1 degrees, and `grid_origin` to
that same floored corner, makes the two paths produce identical names. The script asserts
this per country and refuses to emit a row that fails.

It also HEADs the VIDA URL and counts Sentinel-2 scenes under 40% cloud in the proposed
window, the same probes `scripts/new_region.py check` runs. Outputs
`configs/europe_manifest.yaml` and `data/europe_preflight.csv`.

### `scripts/europe_register_aois.py`

Writes the 42 AOI blocks into `configs/aoi.yaml` from the manifest, reusing
`new_region.py`'s insert-before-`seasons:` mechanism and its re-parse validation.
Idempotent, refuses to touch `france` or `germany`, and has a `--dry-run`. Each block
carries `bbox`, `grid_origin`, `division{name, country, subtype: country, iso3}` and a
`compose_window`. **`iso3` is mandatory**: without it `_iso3_for` falls back to a map
covering only PK, DE and IN, and compose raises.

It also pre-creates `data/composites/<aoi>` as a symlink into
`/home/tobi/earthpv_composites/<aoi>` and refuses to proceed if any such path is a real
directory on aidisc.

Compose windows by band, never the `annual_composite` default, which is the Punjab dry
season and therefore European winter:

- Mediterranean, Turkey, Iberia, Greece, Cyprus, Malta: `2026-04-15:2026-09-30`
- Continental and Atlantic, the proven Germany window: `2026-04-01:2026-09-30`
- Nordic and Baltic, short high-sun season: `2026-05-01:2026-09-15`

2026 is the freshest complete summer as of the launch date.

### `scripts/download_vida_europe.sh`

Generalises `scripts/download_vida_nga.sh`: sequential over the priority order,
`-A "$UA"` because source.coop 403s a bare request in a way that reads as "no such
country", `curl -C -` inside a 50-attempt loop because HTTP/2 stream resets are not covered
by `--retry`, skips a country whose parquet already exists, writes to
`/home/tobi/earthpv_data/vida/<ISO3>.parquet` and symlinks into `data/vida/`, and checks the
disk floor before each file.

### `scripts/europe_labels.sh`

Per country, `scripts/overpass_labels_chunked.py --bbox ... --iso3 ... --name <aoi>
--tiles NxN`, with the tile grid sized from bbox area: 4x4 up to roughly 100,000 km2, 5x5
to 400,000, 6x6 above, since the cost of a tile is the area scanned. Skips a country whose
output parquet already exists. The chunked script already refuses to write a partial result
if any tile never lands, retries with linear backoff, and fails over across three Overpass
mirrors.

**Must run after that country's VIDA download.** Its `classify_placement` step does a
per-0.25-degree-cell building lookup that falls back to remote row-group scans of a
multi-GB parquet without a local file.

### `scripts/europe_cell_survey.py`

Generalises `scripts/nigeria_cell_survey.py` across all countries: runs the real
`compose.populated_cells` selection at `min_buildings=1`, histograms per-cell building
counts, and prints cells, share of buildings, GB and days for thresholds 1, 100, 250, 500,
1000 and 2000. Writes `data/europe_cell_survey.csv` and the per-AOI cached cell lists the
queue then reuses. **This replaces every estimate on this page with measured numbers** and
should be read before the queue is started.

### `scripts/europe_queue.sh`

The long pole, launched once as a systemd unit. Per country, in priority order:

1. Preconditions: VIDA parquet present, `data/composites/<aoi>` is a symlink onto `/`, `/`
   free space above the floor. Otherwise log and pause rather than fail.
2. Yield while any other `earthpv-compose-*` unit is active. The Nigeria compose is running
   at the time of writing and the link is the binding constraint for both, so overlapping
   them finishes neither sooner. This is the same courtesy `run_nigeria_chain.sh` extends
   to the France run.
3. Compose, wrapped in the Nigeria coverage-gate round loop. Inner engine is
   `scripts/compose_loop.sh <aoi> 0 1000 4 3600 2400` with
   `--setenv=EARTHPV_PC_TIMEOUT_S=600` and extra args `--window <band> --resampling
   nearest`. The round loop exists because `compose_loop.sh`'s "no progress 3x" **cannot
   distinguish "every remaining cell has no scenes" from "the STAC provider is down"**: on
   2026-09-17 it exited Nigeria at 428 of 6,341 cells during a Planetary Computer outage.
   Gate: at least 97% of selected cells, bounded rounds, a wait only after an unproductive
   round.
4. `find -L data/composites/<aoi> -name '*.tif.tmp' -delete` between rounds, as
   `run_france_national_compose.sh` does.
5. On the gate passing, hand off to the downstream chain, write a marker, move to the next
   country. On the gate failing, **move on to the next country rather than aborting the
   campaign**, and record it for review.

Every cell counter uses `find -L`. `data/composites/<aoi>` is a symlink, plain `find`
returns 0 through one, and an "added nothing" guard reading 0 will kill a perfectly healthy
run.

### `scripts/europe_downstream.sh`

The per-country segmentation chain, marker-based exactly like
`scripts/run_nigeria_pipeline.sh`, with `data/europe_markers/<aoi>/<step>` holding the
return code and `check_density` whitelisted as non-fatal:

```
infer --checkpoint data/models/v5_combined_france/terramind-pv-epoch=25-step=37986.ckpt
postprocess --threshold 0.3                     # no --max-building-dist, as Zambia/Nigeria
export --exclude-mapped --min-distance-m 100
screen_osm_ground_perimeters.py                 # writes CSV and PNGs for review
calibrate-candidates --recall-reference none    # no quadrat, no register: precision floor
density --districts
check-density                                   # rc 1 is a finding, not an abort
prepare_national_osm_solar.py --labels data/labels/<aoi>_overpass_solar.parquet
atlas --osm-solar data/labels/<aoi>_national_osm_solar.parquet
```

Two deliberate choices. **`--labels` is passed explicitly** because
`export.load_mapped_reference_attrs` globs `data/labels/*_overpass_solar.parquet`
AOI-agnostically and would otherwise pool 42 countries into every country's mapped
reference. **The ground-perimeter exclusion list is never auto-applied**: that screen is
hand-audited by design, so the chain produces the review artefacts and leaves
`configs/<aoi>_osm_ground_exclusions.txt` absent unless one is written by hand.

Checkpoint is **v5**, not v4. It is the only checkpoint with European supervision beyond
Germany, and it is the one that fixed the merged false-positive sheets `polygonize_chips`
produces over Europe: on France, blobs at or above 10,000 m2 fell 6,036 to 2,076 and total
candidate area fell 364 to 255 km2 while candidate count tripled. Germany and France keep
their own published checkpoints and are not re-run. One variable at the top of the script
flips this.

### `scripts/europe_status.py`

One command for a progress report: per country the stage reached, cells done against cells
selected, GB on disk, recent cells per minute, ETA, plus disk free and which unit is live.
This is what makes a multi-week unattended run legible.

## Code changes

All three are additive and opt-in, so Pakistan, Germany, France, Zambia and Nigeria keep
their exact current behaviour.

**`density.fetch_geoboundaries`**: add a disk cache under
`data/geoboundaries/gb_<ISO3>_<LEVEL>.geojson`, a `User-Agent` header, and three retries
with backoff. Today it makes two uncached HTTP requests on every call, which means every
compose pass, for every country, for weeks; and on failure it returns `None`, which
silently degrades compose to an unclipped raw bbox. Cache plus retry removes the load and
the silent-failure mode together. `overpass_labels_chunked.py`,
`prepare_national_osm_solar.py` and `density._load` all benefit equally.

**`compose.populated_cells`**: an optional cell-list cache behind a new `--cache-cells`
flag on the `compose` CLI, persisted to `data/composites/<aoi>/cells.parquet`, with
`--refresh-cells` to invalidate. Today every pass re-runs a full-country VIDA scan
materialised into pandas, a `union_all()` over all ADM1 parts, and `shapely.contains_xy`
over tens of millions of points before the first cell lands. That preamble is 3 to 5
minutes per pass, which at a one-hour pass is 5 to 8% of the entire campaign, repeated
identically every time.

**`compose` fail-closed on an unresolved boundary**: when `EARTHPV_REQUIRE_BOUNDARY=1`,
set by `europe_queue.sh` and unset everywhere else, raise instead of falling back to the
raw bbox. That fallback is what put 795 of France's 6,774 cells outside France. Unattended
and at 42-country scale it must fail loudly rather than quietly composite the
Mediterranean.

## Launch checklist

1. `pixi run python scripts/europe_preflight.py`. Read-only, 10 to 15 minutes. Read
   `data/europe_preflight.csv`: every country must show ADM1 resolved, VIDA 200, scenes
   found, and grid-origin invariant OK. Nothing has been written to `configs/aoi.yaml` yet.
2. `pixi run python scripts/europe_register_aois.py --dry-run`, then for real.
   `git diff configs/aoi.yaml` to eyeball the 42 blocks, then
   `pixi run python -c "from earthpv.config import Settings; print(len(Settings.load().aois))"`.
   A malformed insert must fail here, not three weeks in.
3. **End-to-end smoke on the smallest country.** Luxembourg (about 32 cells, 20 MB of VIDA)
   or Malta (3 cells, 10 MB): `download_vida_europe.sh --only LUX`, `europe_labels.sh
   --only luxembourg`, then `europe_queue.sh --only luxembourg` and let it run the whole
   chain to an atlas. One to two hours, and it exercises every stage, every symlink, the
   disk guard, the marker logic and the atlas template. This is the real "does it work"
   check; the repo has no test suite.
4. `pixi run python scripts/europe_cell_survey.py` once the first few VIDA files are down.
   This replaces the estimates above with the measured cell count and schedule per country.
5. `loginctl show-user "$USER" | grep Linger`. Already `Linger=yes` on this machine, so
   confirm it has not changed. Without it systemd-logind kills the whole session cgroup on
   logout.
6. `df -h /`, confirm the 1.1 TB, then launch:

```bash
systemd-run --user --collect --unit=earthpv-europe \
  -p WorkingDirectory="$PWD" -p LimitNOFILE=65536:65536 -p MemoryMax=20G \
  bash scripts/europe_queue.sh
```

7. `pixi run python scripts/europe_status.py`. Confirm it reports the live unit and the
   first country's cell count climbing, then leave.

## Known limits, stated rather than hidden

- **Europe will not finish in some weeks.** At the measured 0.6 cells per minute the queue
  needs 7 to 12 weeks for the full list. The design's answer is that it completes countries
  sequentially, so whatever is done is whole. An ethernet cable would change this more than
  anything else here.
- No calibration quadrats exist anywhere in Europe outside France's 14 communes, so every
  country's atlas is **segmentation-only, precision-honest and recall-uncorrected**: a
  floor, not an estimate, the same status [Zambia's](../results/zambia.md) and
  [Gujarat's](../results/gujarat.md) carry. No `roofclf` half.
- `roofclf` is known **not to transfer to French residential PV** (median fold AUC 0.710
  against Pakistan's 0.857), because the median mapped French installation is 20 m2 against
  a 100 m2 Sentinel-2 pixel, and the size regime is set by national subsidy design rather
  than geography. See [France validation](../methods/france-validation.md). Expect the same
  wherever European residential PV is small, and do not promise a sub-400 m2 half for any
  of these countries in advance.
- Germany's and France's composites are `nearest`, and so is this campaign, deliberately.
  The measured +0.0041 `roofclf` AUC from `20m-bilinear` is forgone to keep one homogeneous
  corpus that matches every trained checkpoint.

Related: [Setup New Country](../reproduce.md) for the single-country version of this
workflow, and [Country data registry](../data-registry.md) for what each AOI currently
holds.
