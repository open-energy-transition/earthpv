#!/usr/bin/env bash
# Building footprints for a new country, VIDA with its holes filled from OpenStreetMap, ready
# for scripts/run_country_queue.sh. Spain's recipe (2026-11-02) as one resumable step:
#
#   1. the country's raw VIDA parquet -> /home/tobi/earthpv_data/<ISO3>.parquet
#      (scripts/ranged_download.py, as scripts/download_vida.sh, but NOT linked yet);
#   2. its Geofabrik extract(s) -> /home/tobi/earthpv_data/geofabrik/<aoi>_<date>/, md5-checked,
#      merged with osmium when a country needs several (Portugal + the Azores);
#   3. scripts/fill_vida_from_osm.py -> /home/tobi/earthpv_data/<ISO3>_vida_osmfill.parquet
#      (every VIDA row kept; OSM buildings only in 0.01 deg blocks VIDA leaves empty);
#   4. data/vida/<ISO3>.parquet -> the filled file. The queue waits for exactly this link
#      (vida_ok), so neither the label pull nor compose ever runs on unfilled footprints.
#
# VIDA is Microsoft-only in Europe, and Spain's mainland had block-shaped holes (9 of 21 city
# centres empty); the fill is additive, so a country without holes gains little. Revert by
# repointing the link at the raw file.
#
#   bash scripts/prepare_country_vida.sh <aoi> <ISO3> <geofabrik region>[,<region>...]
#   bash scripts/prepare_country_vida.sh portugal PRT europe/portugal,europe/azores
#
# VIDA_BOXES="<minlon,minlat,maxlon,maxlat> ..." (2026-11-10, for states run without their
# country) replaces step 1's whole-country download with scripts/vida_subset.py: only the
# footprints inside those boxes, as /home/tobi/earthpv_data/<ISO3>_<aoi>_boxes.parquet.
# The installed data/vida/<ISO3>.parquet then holds NOTHING outside the boxes, so a later
# AOI of the same country needs it redone with its box added (<raw>.json lists them).
#   VIDA_BOXES="-124.5,32.5,-114.1,42.1 -106.7,25.8,-93.4,36.6" bash scripts/prepare_country_vida.sh \
#     california_texas USA north-america/us/california,north-america/us/texas
set -uo pipefail
AOI=${1:?aoi}; ISO3=${2:?ISO3}; REGIONS=${3:?geofabrik region(s), comma-separated}
cd /run/media/tobi/aidisc/earthpv
PY=.pixi/envs/default/bin/python
OSMIUM=/run/media/tobi/aidisc/subdetect/.pixi/envs/default/bin/osmium
HOME_DATA=${HOME_DATA:-/home/tobi/earthpv_data}  # Mexico: /run/media/tobi/moreaidata/earthpv
VIDA_BOXES=${VIDA_BOXES:-}
if [ -n "$VIDA_BOXES" ]; then
  RAW=$HOME_DATA/${ISO3}_${AOI}_boxes.parquet
  FILLED=$HOME_DATA/${ISO3}_${AOI}_boxes_vida_osmfill.parquet
else
  RAW=$HOME_DATA/$ISO3.parquet
  FILLED=$HOME_DATA/${ISO3}_vida_osmfill.parquet
fi
LINK=data/vida/$ISO3.parquet
UA="earthpv-prep/1.0"
say() { echo "$(date '+%F %T') VIDA[$AOI]: $*"; }

if [ -e "$LINK" ]; then say "$LINK already exists -> $(readlink -f "$LINK"); nothing to do"; exit 0; fi

# ---- 1. raw VIDA ------------------------------------------------------------------------
URL="https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country/country_iso=$ISO3/$ISO3.parquet"
BOX_ARGS=(); for b in $VIDA_BOXES; do BOX_ARGS+=("--box=$b"); done
for i in $(seq 1 20); do
  { [ -s "$RAW" ] && [ ! -e "$RAW.part" ]; } && break
  if [ -n "$VIDA_BOXES" ]; then
    $PY scripts/vida_subset.py --iso3 "$ISO3" "${BOX_ARGS[@]}" --out "$RAW" && break
  else
    $PY scripts/ranged_download.py "$URL" "$RAW" --workers 16 && break
  fi
  say "VIDA download pass $i failed, retrying in 60 s"; sleep 60
done
{ [ -s "$RAW" ] && [ ! -e "$RAW.part" ]; } || { say "FAILED: VIDA download did not complete"; exit 1; }
say "raw VIDA: $(stat -c %s "$RAW") bytes"

# ---- 2. Geofabrik extract(s) ------------------------------------------------------------
GF=$(ls -d "$HOME_DATA/geofabrik/${AOI}_"* 2>/dev/null | tail -1)
[ -n "$GF" ] || GF=$HOME_DATA/geofabrik/${AOI}_$(date +%Y%m%d)
mkdir -p "$GF"
PBFS=()
for r in ${REGIONS//,/ }; do
  f=$GF/$(basename "$r")-latest.osm.pbf
  for i in $(seq 1 10); do
    if [ -s "$f" ] && [ -e "$f.ok" ]; then break; fi
    curl -sSfL -A "$UA" -o "$f.md5" "https://download.geofabrik.de/$r-latest.osm.pbf.md5" &&
      curl -sSfL -A "$UA" -C - -o "$f" "https://download.geofabrik.de/$r-latest.osm.pbf" &&
      (cd "$GF" && md5sum -c "$(basename "$f").md5" >/dev/null) && touch "$f.ok" && break
    say "Geofabrik $r attempt $i failed; retrying in 60 s"; rm -f "$f"; sleep 60
  done
  [ -e "$f.ok" ] || { say "FAILED: Geofabrik $r"; exit 1; }
  PBFS+=("$f")
done
if [ ${#PBFS[@]} -gt 1 ]; then
  PBF=$GF/${AOI}-merged.osm.pbf
  [ -s "$PBF" ] || "$OSMIUM" merge "${PBFS[@]}" -o "$PBF" --overwrite || { say "FAILED: osmium merge"; exit 1; }
else
  PBF=${PBFS[0]}
fi
say "OSM extract: $PBF"

# ---- 3. fill ------------------------------------------------------------------------------
if [ ! -s "$FILLED" ]; then
  $PY scripts/fill_vida_from_osm.py --iso3 "$ISO3" --vida "$RAW" --pbf "$PBF" --out "$FILLED" \
    --osmium "$OSMIUM" || { say "FAILED: fill_vida_from_osm.py"; exit 1; }
fi

# ---- 4. install -----------------------------------------------------------------------------
ln -s "$FILLED" "$LINK"
say "installed $LINK -> $FILLED ($(stat -c %s "$FILLED") bytes); raw kept at $RAW"
echo VIDA_READY
