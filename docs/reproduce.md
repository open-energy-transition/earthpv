# Reproduce

Everything in this documentation was produced by the commands on this page. Every stage is
resumable and safe to re-run: existing chips, composites and predictions are skipped rather
than rebuilt. That matters, because most real runs here are network-bound or GPU-bound for
hours.

## Requirements

* An NVIDIA GPU for training and inference. The project targets a **GTX 1060 (Pascal,
  sm_61)**, which is why PyTorch is pinned to **cu126** wheels: CUDA 13 dropped Pascal
  support. Anything newer works and needs no change.
* Disk. `data/` is gitignored and expected on a fast local or external drive. Chips,
  composites, models and predictions run from multi-GB to multi-hundred-GB.
* Nothing else. The already-configured AOIs reuse imagery a sibling project downloaded on
  the development machine, but that is a shortcut, not a requirement, and
  [running on a new region](#running-on-a-new-region) covers the standalone path.

## Install

```bash
pixi install              # data pipeline: DuckDB, geopandas, rasterio, odc-stac
pixi install -e ml        # adds PyTorch cu126 and TerraTorch, a multi-GB solve
pixi run -e ml gpu-check  # confirms torch.cuda.is_available() and the device name
```

Two environments share one solve group. `default` has no PyTorch and covers every data and
network stage; `ml` adds torch and terratorch and is only needed for `train`, `infer`,
`evaluate` and `hard-negatives`. On long runs, calling
`.pixi/envs/ml/bin/python -m earthpv.cli ...` directly skips pixi's per-invocation
overhead.

A third environment, `docs`, builds this site and is independent of both.

## Smoke test first

A complete, minutes-long pass through every stage that touches the GPU. Do this on a fresh
checkout before committing to a multi-hour run.

```bash
pixi run earthpv labels --aoi freiburg                    # tiny bbox, seconds
pixi run earthpv chips  --aoi freiburg --limit 50         # 50 chips, about a minute
pixi run -e ml earthpv train --config configs/terramind_pv.yaml --smoke
pixi run -e ml earthpv evaluate --aoi freiburg --checkpoint data/models/last.ckpt
```

`--smoke` runs 50 optimizer steps. That is enough to confirm the model loads, the GPU is
used and a checkpoint is written, and nowhere near enough to detect anything. Do not read
anything into the evaluate numbers here.

## The full pipeline

Ordered by dependency. Every stage after `train` needs a checkpoint path.

=== "1. Labels"

    Building footprints and OpenStreetMap solar polygons for an area.

    ```bash
    pixi run earthpv labels --aoi germany

    # Freshly mapped region, bypassing Overture's snapshot lag, for example right
    # after a mapping session:
    pixi run earthpv overpass-labels --place "Lahore" --iso3 PAK
    ```

    Country-scale Overpass fetches need per-province chunking or they time out.

=== "2. Chips"

    Sentinel-2 composite windows with PV masks burned in: the training set.

    ```bash
    pixi run earthpv chips --aoi germany                # full run, 3 to 4k chips
    pixi run earthpv chips --aoi germany --limit 500    # capped, for iteration
    pixi run earthpv chips --aoi germany --fraction     # continuous coverage-fraction target
    ```

=== "3. Train"

    ```bash
    pixi run -e ml earthpv train --config configs/terramind_pv.yaml

    # Merge several areas into one training set first. The `:2` oversamples Pakistan's
    # rows so Germany's larger chip count does not swamp the in-domain signal.
    .pixi/envs/default/bin/python scripts/merge_chip_index.py germany pakistan:2
    ```

=== "4. Evaluate"

    Pixel IoU and F1, plus per-installation recall bucketed by array size.

    ```bash
    pixi run -e ml earthpv evaluate --aoi germany \
        --checkpoint data/models/<run>/<epoch>.ckpt
    ```

=== "5. Compose"

    Build Sentinel-2 composites for areas with no local imagery. Skip for areas whose
    `source_region` already has them.

    ```bash
    pixi run -e ml earthpv compose --aoi punjab --min-buildings 1000 --workers 6

    # A second epoch on the same grid, here the pre-2022-boom baseline:
    pixi run -e ml earthpv compose --aoi pakistan --index 1 \
        --window 2021-10-01:2022-01-24 --use-vida --workers 6
    ```

    The pre-boom window deliberately ends 2022-01-24 to stay on one Sentinel-2 processing
    baseline: the 04.00 change in January 2022 shifts the digital-number convention by
    +1000 mid-window.

=== "6. Infer"

    Tiled inference writing one probability GeoTIFF per cell.

    ```bash
    pixi run -e ml earthpv infer --aoi punjab \
        --checkpoint data/models/<run>/<epoch>.ckpt
    ```

=== "7. Postprocess"

    Threshold, polygonize, join to buildings, rank.

    ```bash
    pixi run earthpv postprocess --aoi punjab --threshold 0.3

    # Drop isolated candidates far from any building:
    pixi run earthpv postprocess --aoi punjab --threshold 0.3 --max-building-dist 30

    # Physics-based glint corroboration, calibrated and budgeted:
    pixi run earthpv postprocess --aoi punjab --check-glint \
        --glint-top-n 300 --glint-skip-top 100
    ```

=== "8. Export"

    GeoParquet, GeoJSON and a MapRoulette challenge, ordered by `rank_score`.

    ```bash
    pixi run earthpv export --aoi punjab

    # New leads only, excluding anything within 100 m of mapped OpenStreetMap solar:
    pixi run earthpv export --aoi punjab --exclude-mapped --min-distance-m 100

    # Plus the pre-boom and vegetation vetoes, into new_leads_clean:
    pixi run earthpv export --aoi punjab --exclude-mapped --min-distance-m 100 \
        --epoch-clean --veg-max-ndvi 0.35
    ```

=== "9. Density"

    Per-building PV area and capacity, plus grid and region aggregates. No GPU, no
    retraining, runs on artifacts already on disk.

    ```bash
    pixi run earthpv calibrate-candidates --aoi pakistan
    pixi run earthpv density --aoi pakistan --districts

    # Optional precision upgrade for the bins below 1,000 m2, where glint is blind:
    pixi run earthpv calibrate-sample --aoi pakistan     # fill `verdict` in JOSM or QGIS
    pixi run earthpv calibrate-candidates --aoi pakistan --manual-reviews <reviewed file>
    ```

=== "10. Germany calibration"

    Optional, Germany only. Cross-check against the legally complete MaStR register.

    ```bash
    pixi run earthpv mastr        # download and aggregate MaStR
    pixi run earthpv calibrate --aoi germany
    pixi run earthpv pv-yield --aoi germany   # pvlib GWh/yr cross-check
    ```

Areas and their parameters live in `configs/aoi.yaml`; model and training configs in
`configs/*.yaml`.

## Running on a new region

The configured areas reuse locally cached imagery. `gujarat` in `configs/aoi.yaml` is the
template for a region with **no local data at all**:

```yaml
gujarat:
  bbox: [68.0, 20.0, 74.6, 24.8]
  division: { name: Gujarat, country: IN, subtype: region }
  # no source_region key, so chips and compose fall back to Planetary Computer STAC
```

1. `labels` or `overpass-labels` fetch OpenStreetMap solar polygons directly, from Overture
   or live Overpass, instead of reading a cached parquet.
2. `chips` and `compose` fetch Sentinel-2 from Planetary Computer STAC. Same code path,
   just slower, and it needs nothing pre-downloaded.
3. The building join fetches VIDA Open Buildings for the area's country on first use and
   caches it. Works for any ISO3 code.
4. Detection reuses the existing Germany-trained checkpoint unchanged. No region-specific
   retraining is needed for a first candidate set; retraining on in-domain chips is what
   closes the domain gap afterwards.

## Rebuilding this site

```bash
pixi run docs-figures          # regenerate every chart, diagram and embedded page
pixi run -e docs docs-serve    # live preview at http://127.0.0.1:8000
pixi run -e docs docs-build    # strict build into site/
```

`scripts/build_docs_figures.py` reads its numbers from files on disk wherever a file
exists, so after a new pipeline pass the figures update themselves. Pushing to `main`
publishes the site through GitHub Pages via `.github/workflows/docs.yml`.

## Operational notes

These are the things that cost time on this project.

!!! danger "Long jobs die silently on logout"
    `nohup setsid` is **not** enough. systemd-logind kills a session's whole cgroup when
    the session ends unless lingering is enabled. Before launching anything multi-hour:

    ```bash
    loginctl show-user "$USER" | grep Linger
    loginctl enable-linger "$USER"     # once, no sudo needed for your own account
    ```

    Run each long job as its own transient unit so one job's out-of-memory kill does not
    take the others with it:

    ```bash
    systemd-run --user --collect --unit=earthpv-compose \
      -p WorkingDirectory=/path/to/earthpv bash scripts/compose_loop.sh
    ```

**Planetary Computer has frequent multi-hour outages**, either Azure Front Door 504s or
requests that hang with no error at all. Every network-bound stage is resumable by design,
with temp-then-rename writes and per-cell or per-target skip-if-exists. The practical
pattern is to launch detached, poll a log for a completion marker or a stall of 20 to 30
minutes with no new output, and relaunch the same command if stalled.
`scripts/compose_loop.sh` automates exactly that cycle, and also restarts every 30 minutes
so a fresh signing token replaces one about to expire mid-run.

**The progress bar does not flush to a redirected log.** Watch checkpoint files or cell
counts to gauge progress, not the log tail.

**`row.mask` and `row.image` on a pandas row** resolve to `Series.mask`, the method, not
your column. Use bracket access, `row["mask"]`. This has caused real bugs here more than
once.

**Areas are geodesic** (`labels.geodesic_area_m2`). Never call `.area` on latitude and
longitude geometries; it silently returns square degrees.

**Geographic validation splits must match real coverage.** `val_tiles` in
`configs/aoi.yaml` has to name MGRS tiles or composed cells the area actually produced, or
the validation set is silently empty and the datamodule falls back to a random 20 percent
split. Check that `evaluate`'s reported installation count per bucket is not suspiciously
small before trusting a recall number.

**Changing `MIN_PV_AREA`** requires rebuilding chips and retraining. It is baked into the
burned masks, not a runtime parameter.

## Orchestration scripts

| Script | What it does |
| --- | --- |
| `compose_loop.sh` | Auto-restarts `compose` every 30 minutes for a fresh token; exits on target reached, clean completion, or three no-progress cycles. |
| `rebuild_training.sh` | Rebuilds an area's chips after its compose finishes, then remerges the combined training index. |
| `infer_after_compose.sh` | Waits for compose, then chains infer into postprocess into export. |
| `run_preboom_pipeline.sh` | The full two-epoch pipeline behind marker-file resumability. |
| `run_sr_experiments.sh` | The three super-resolution feasibility tests in sequence. |
| `download_vida_ind.sh` | Bulk VIDA India buildings download with retry on reset. |
| `build_docs_figures.py` | Every figure and embedded page on this site. |

There is no test suite and no wired lint task. Ruff is configured at line length 100 and
run manually. The practical "does it work" check is the smoke test above.
