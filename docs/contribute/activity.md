# Follow activity in calibration areas

Anyone with a copy of this repository can see what has happened in every calibration area:
which ones have solar mapped, when it was uploaded, and whether anyone edited an area after
it was registered. A script reads OpenStreetMap's public edit history and writes one row per
area to a CSV file. It only reads: nothing is uploaded or changed.

It does not replace a [report](report.md). OpenStreetMap records edits, so it can show that
someone worked in an area, but not that they finished.

## What you need

- A copy of the repository: `git clone https://github.com/open-energy-transition/earthpv`.
  The area boundaries are in it. You do not need the pipeline's `data/` folder or its
  environment.
- Python 3.9 or newer. The commands below use `pixi`; without it, replace
  `pixi run calib-activity --` with `python scripts/calibration_area_activity.py`.
- An OpenStreetMap account, to get an OSMCha API key.

## Get your OSMCha API key

[OSMCha](https://osmcha.org) is a community tool for reviewing OpenStreetMap changesets. The
script uses it to search changesets by comment and by place, which OpenStreetMap's own API
cannot do.

1. Open [osmcha.org](https://osmcha.org) and choose **Sign in**. It uses your OpenStreetMap
   account.
2. Open **Account settings** from the menu, or go straight to
   [osmcha.org/user](https://osmcha.org/user).
3. Find the line **API key:**. It shows the word `Token` followed by a long string of letters
   and digits.
4. Copy it. The clipboard button next to it also copies the word `Token`; the script accepts
   the key with or without that word.

## Save the key outside the repository

The script looks for the key in `~/.config/earthpv/osmcha_token`. On Linux or macOS:

```bash
mkdir -p ~/.config/earthpv
chmod 700 ~/.config/earthpv
(umask 077; cat > ~/.config/earthpv/osmcha_token)
```

The last command waits for your input: paste the key, press Enter, then press Ctrl-D.
Entering it this way keeps it out of your shell history. On Windows, save a file holding
only the key at `C:\Users\<you>\.config\earthpv\osmcha_token`, with no file extension.

To keep the key somewhere else, add `--token-file <path>` to the commands below.

Treat the key like a password, because it acts as your OSMCha account:

- Never commit it, or paste it into an issue, a chat or a screenshot.
- Use your own key, not someone else's.
- The script refuses a key file inside the repository or one that other accounts on your
  computer can read, sends the key only to osmcha.org, and has no command-line option for
  the key itself, which would leave it in your shell history.
- OSMCha's account page has no button to replace a key. If yours leaks, ask the
  [OSMCha maintainers](https://github.com/OSMCha) to reset it.

## Run it

```bash
pixi run calib-activity -- --aoi yemen                # one country
pixi run calib-activity                               # every country
pixi run calib-activity -- --area swabi_f4_farm_calib_3km
pixi run calib-activity -- --registered-only --since 2026-10-01
pixi run calib-activity -- --dry-run                  # list the areas, fetch nothing
```

Country keys are the file names in `docs/assets/labels/calibration_areas/`, and area ids are
the `id` values inside those files. The result is written to
`data/calibration_activity/activity_<date>.csv`, a folder git ignores. `--out <path>` writes
it elsewhere.

Without a key, `--skip-osmcha` still gives the solar elements, their dates and the number of
changesets behind them. The columns that need OSMCha stay blank.

Both services are run for the community. Prefer one country at a time, and do not run the
whole list more than about once a week. One country takes from a minute to about 20 minutes
and the whole list about an hour, most of it waiting for Overpass. If a service stays
unavailable after several retries, the script stops and writes nothing, so try again later.

## Read the result

The `activity` column sums up each area:

| activity | meaning |
|---|---|
| calibration upload | solar elements in the area were last edited in a changeset whose comment names `earthpv-calibration` |
| calibration upload nearby | a small calibration changeset overlaps the area's box, but no solar element inside the area comes from it |
| other EarthPV upload | solar elements come from a changeset that names EarthPV without the calibration tag, such as mapping of model leads |
| other solar edits | the area holds solar elements, none from a changeset naming EarthPV |
| local edits, no solar elements | people have edited here, such as roads or buildings, but no solar is mapped |
| no activity seen | no solar elements and no small changeset since January 2025 |
| solar elements present, no solar elements seen | the two values you get with `--skip-osmcha` |

**A blank cell means not checked, never zero.** The other columns:

| column | meaning |
|---|---|
| `solar_elements_now` | elements tagged as solar whose point falls inside the area. These are elements, not installations: a plant outline and the generators inside it count separately |
| `oldest_edit`, `newest_edit` | dates of the current version of those elements |
| `newest_changeset` | the latest changeset among them, to open at `https://www.openstreetmap.org/changeset/<id>` |
| `changesets_on_elements`, `mappers` | how many different changesets and accounts made the current versions |
| `calibration_changesets`, `earthpv_changesets` | how many of those changesets name the calibration tag, or EarthPV at all |
| `share_on_calibration_changesets` | the share of the area's solar elements that came from a calibration changeset |
| `since`, `since_basis` | where the change window starts: `--since`, the date of the OpenStreetMap copy the pipeline reads for that area, on a maintainer's copy of the data (`local snapshot`), or the last 90 days (`window`). Blank for a candidate, which was never registered |
| `added_since`, `changed_since` | elements first created, or given a new version, inside the window |
| `removed_since` | elements deleted or no longer tagged as solar inside the window. Blank means it was not looked for, because no small changeset touched the area in the window. `--check-all-removals` looks anyway |
| `local_changesets`, `newest_local_changeset_date` | small changesets on any subject over the area since January 2025. Small means a bounding box under 10 times the area's own |
| `local_calibration_changesets` | how many of those are calibration uploads |
| `osm_data_time` | how current the Overpass data was |

After a run, the script also lists every registered area edited inside its window. Those
are worth a look: the pipeline reads a saved copy of OpenStreetMap for each area, so later
edits do not reach the calibration until a maintainer pulls the area again. France's areas
are the exception. They are surveys drawn on IGN aerial imagery rather than copies of
OpenStreetMap, so these counts say nothing about their calibration.

## What this cannot tell you

- **Whether an area is finished.** Only a person who checked every roof can say that, which
  is why [reports](report.md) and the second pass exist.
- **Whether an area is empty.** Someone who sweeps an area and finds no panels has nothing
  to upload. Jacobabad in Pakistan is confirmed to hold no solar, and it reads exactly like
  an area nobody has visited. So `no activity seen` never means there is no solar, and an
  empty area still needs a report.
- **The full history of an element.** The script sees each element's latest version, so a
  later retag replaces the date and changeset of the original mapping.
- **Uploads it cannot match.** Campaign changesets are found from the changeset comment, so
  keep the prefilled text, or write `#earthpv-calibration` in your own. One upload spanning
  two distant areas is too large for the local search, although its elements are still
  counted.

## Keep it about areas, not people

The CSV holds counts and changeset ids, and leaves mapper names out on purpose. Please keep
anything you publish from it at the level of areas too.
