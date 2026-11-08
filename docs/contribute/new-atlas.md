---
title: Build an atlas on your PC
---

# Build an atlas for your country, on your own PC

<div class="atlas-start" data-new-atlas hidden markdown="0">
  <p class="atlas-start__lead"><strong data-new-atlas-country></strong> has no atlas yet. You could be the person who draws it.</p>
  <p class="atlas-start__note">The commands below are already filled in for this country. Its box comes from a world map, so check it before you start.</p>
</div>

Every atlas on the [globe](../index.md) came out of this pipeline on one desktop computer with a
GTX 1060, and this page is the shortest path through it. The satellite imagery, the building footprints, the solar labels and
the trained model are all free, and you need no account for any of them. When you finish, your
country goes from a pencil line to ink on the globe, and your atlas tells the country something
it may never have measured.

**Tell us which country you are starting** on [Discord](https://discord.gg/T5zh6N24Hv), so that
two people do not spend the same week on it. It is also the fastest place to get unstuck.

## What it takes

| You need | How much | Good to know |
| --- | --- | --- |
| **An NVIDIA graphics card** | 6 GB of memory is enough | The target card is a GTX 1060. Anything newer works unchanged. |
| **Free disk space** | About 15 GB per 1,000 cells, plus one building file of 3 to 10 GB | India's building file alone is 64 GB. An external drive is fine. |
| **A steady connection** | About 300 MB per cell | This sets how long your run takes. Everything else waits on it. |
| **Linux** | The commands use `systemd-run` | Other systems have not been tested. |
| **A little of your own judgement** | A few hours, spread out | Two steps need a person looking at imagery. No script or agent can do them for you. |

Only cells with buildings are imaged, so a country is usually far smaller than its map suggests.
The cell counts are real, and so are the detection times on a GTX 1060, except India's. Download
times and the other disk figures are worked out from about 1.1 cells a minute on a 6 MB/s home
connection and about 11 MB per cell:

| Country | Cells imaged | Imagery download | Detection | Disk for imagery |
| --- | --- | --- | --- | --- |
| Namibia | 459 | about 7 hours | 25 minutes | 6 GB |
| Egypt | 946 | about 15 hours | 46 minutes | 12 GB |
| Poland | 3,948 | about 2.5 days | 2 hours | 45 GB |
| Spain | 5,712 | about 3.5 days | 4 hours | 62 GB |
| India | 29,171 | weeks | a day or more | over 300 GB |

Every long step can be stopped and restarted, and it carries on where it left off.

## 1. Get the code

Install [pixi](https://pixi.sh) and the [GitHub CLI](https://cli.github.com), then:

```bash
gh repo fork open-energy-transition/earthpv --clone --remote
cd earthpv
git switch -c atlas/YOUR_AOI

pixi install                # the data pipeline
pixi install -e ml          # PyTorch, a large download
pixi run -e ml gpu-check    # should print your card's name
pixi run fetch-model        # the released detection model, 33 MB
```

## 2. Check the country

This asks each open data source whether it covers your country. It only reads, and takes a couple
of minutes.

```bash
pixi run python scripts/new_region.py check \
    --bbox=YOUR_BBOX --iso3 YOUR_ISO3 --name "YOUR_COUNTRY" --skip-osm
```

The box runs `west,south,east,north`. Look at the line about Sentinel-2 scenes: if it finds little
under 40% cloud, the default months are your country's wet season. Pick drier ones with
`--window 2025-11-01:2026-03-15` and try again.

Then add the country to the configuration:

```bash
pixi run python scripts/new_region.py add \
    --aoi YOUR_AOI --bbox=YOUR_BBOX --iso3 YOUR_ISO3 \
    --division "YOUR_COUNTRY" --subtype country
```

If you picked other months, add them to the country's new block in `configs/aoi.yaml`, for example
`compose_window: ["2025-11-01", "2026-03-15"]`.

## 3. Download what is already mapped

```bash
pixi run python scripts/overpass_labels_chunked.py \
    --bbox=YOUR_BBOX --iso3 YOUR_ISO3 --name YOUR_AOI
pixi run python scripts/drop_solar_thermal.py --aoi YOUR_AOI
```

The first run also downloads the country's building footprints once. Solar water heaters and
mirror fields carry the same OpenStreetMap tag as panels, so the second command takes them out.

## 4. Build the imagery

This is the long one. It runs in the background, survives closing the terminal, and resumes if your
computer restarts. First make sure your long jobs outlive your login:

```bash
loginctl enable-linger "$USER"

systemd-run --user --collect --unit=earthpv-compose-YOUR_AOI \
    -p WorkingDirectory="$PWD" bash scripts/compose_loop.sh YOUR_AOI 0 1000

journalctl --user -fu earthpv-compose-YOUR_AOI     # watch it, Ctrl+C only stops watching
```

The `1000` means imaging only cells with at least 1,000 buildings. Use a lower number in a country
of small villages.

## 5. Find the solar

Once the imagery is done, detect the arrays and turn the outlines into a ranked list of mapping
leads. This is the first thing you get to look at.

```bash
pixi run -e ml earthpv infer --aoi YOUR_AOI \
    --checkpoint data/models/release/earthpv_segmentation_v14.ckpt

pixi run earthpv postprocess --aoi YOUR_AOI --threshold 0.3 --building-buffer-m 500 --stream-buildings
pixi run python scripts/drop_solar_thermal.py --aoi YOUR_AOI --candidates
pixi run earthpv export --aoi YOUR_AOI --exclude-mapped --min-distance-m 100
```

## 6. Judge the very large outlines

A very large outline counts only after a person has judged it to be solar. This step opens a page
with one picture of each, and you press 1, 2 or 3. You can stop at any time: anything you have not
judged simply stays out of the total.

```bash
pixi run blob-review draw --aoi YOUR_AOI --labels data/labels/YOUR_AOI_overpass_solar.parquet
# open data/oversize_review/index.html, judge, export the verdicts
pixi run blob-review apply --aoi YOUR_AOI --reviewer "Your name" \
    --verdicts YOUR_AOI_blob_verdicts.csv
```

## 7. Draw the atlas

```bash
pixi run python scripts/screen_osm_ground_perimeters.py --aoi YOUR_AOI \
    --labels data/labels/YOUR_AOI_overpass_solar.parquet \
    --prob-dir data/predictions/YOUR_AOI/prob --min-area-m2 50000 --threshold 0.3 \
    --out results/YOUR_AOI_osm_ground_screen/screen_full.csv \
    --png-dir results/YOUR_AOI_osm_ground_screen

pixi run earthpv calibrate-candidates --aoi YOUR_AOI --recall-reference none
pixi run earthpv density --aoi YOUR_AOI --districts --threshold 0.3
pixi run earthpv check-density --aoi YOUR_AOI

pixi run python scripts/prepare_national_osm_solar.py --aoi YOUR_AOI \
    --labels data/labels/YOUR_AOI_overpass_solar.parquet \
    --keep-detected-screen results/YOUR_AOI_osm_ground_screen/screen_full.csv
pixi run python scripts/solar_thermal_plants.py --aoi YOUR_AOI \
    --osm-solar data/labels/YOUR_AOI_national_osm_solar.parquet

pixi run earthpv atlas --aoi YOUR_AOI --include-offgrid-osm \
    --osm-solar data/labels/YOUR_AOI_national_osm_solar.parquet \
    --out results/YOUR_AOI_pv_evidence_atlas.html
```

Open `results/YOUR_AOI_pv_evidence_atlas.html` in your browser. That is your country's solar map.

`check-density` reports regions that look implausible. It is telling you where to look, and in a
country with no small-rooftop estimate some warnings are expected.

## 8. Put it on the globe

Copy the atlas into the site, add one line to `ATLASES` in `scripts/build_atlas_pages.py`, and
open a pull request:

```bash
cp results/YOUR_AOI_pv_evidence_atlas.html docs/assets/interactive/
# add ("atlas-YOUR_AOI", "YOUR_COUNTRY", "YOUR_AOI_pv_evidence_atlas.html", None), to ATLASES
pixi run python scripts/build_atlas_pages.py --nav   # writes the pages, inks the globe
# paste the printed PV Atlas block into mkdocs.yml, then:
pixi run -e docs mkdocs build --strict
gh pr create --fill
```

Say in the pull request what the atlas does **not** know yet. A first atlas is a floor: it sees
arrays of about 400 m<sup>2</sup> and up, and it says so on the page. The longer checklist, and how
to publish the per-cell data tables, is in
[Contribute your country atlas back](../reproduce.md#contribute-your-country-atlas-back).

## Make it better than a first pass

The released model has never seen your country. The published atlases each retrain it on their own
country's labels, then keep whichever model scores better on a part of the country held back for
the test, which took a few hours on the same card. Mapping is what makes that possible:

1. [Map the leads](leads.md) from step 5 in OpenStreetMap. They count at the next rebuild, and they
   become training examples.
2. [Map a calibration area](index.md) completely. That is what lets the atlas estimate the small
   rooftop systems it cannot see directly.
3. [Retrain on your own labels](../reproduce.md#step-5-retrain-in-domain) and draw the atlas again.

## Let a coding agent run it

Most of this is long, resumable and well documented, which suits an agent. `CLAUDE.md` in the
repository is its brief. Start one in the repository folder and give it the country:

> Read CLAUDE.md and docs/contribute/new-atlas.md. Build a segmentation-only evidence atlas for
> YOUR_COUNTRY (key YOUR_AOI, ISO3 YOUR_ISO3, box YOUR_BBOX), following that page step by step. Run
> long stages as detached systemd units and report what each one produced. Stop before anything
> that needs a person to look at imagery and tell me what you need.

Keep the judgement for yourself: **only a person can judge the very large outlines, declare a
mapped area complete, or sign off a number.** Those are the steps where evidence enters the atlas.
