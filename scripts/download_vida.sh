#!/bin/bash
# Bulk-download one country's VIDA Open Buildings parquet to /home, then symlink it into
# data/vida/. Generalises download_vida_nga.sh: `bash scripts/download_vida.sh VNM`.
#
# aidisc is the binding disk constraint (CLAUDE.md), so the file always lands on /home.
# A single long-lived curl stream degrades on this connection (HTTP/2 resets, measured
# 18 KB/s on a live stream against 1.5 MB/s for a fresh range request), so the file is
# fetched as parallel, resumable byte ranges by scripts/ranged_download.py. source.coop
# 403s any request without a User-Agent, which reads exactly like "no such country".
set -u
ISO3=${1:?usage: download_vida.sh <ISO3>}
cd /run/media/tobi/aidisc/earthpv
DEST=/home/tobi/earthpv_data/$ISO3.parquet
LINK=data/vida/$ISO3.parquet
URL="https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country/country_iso=$ISO3/$ISO3.parquet"
if [ -s "$DEST" ] && [ ! -e "$DEST.part" ]; then
  ln -sf "$DEST" "$LINK"; echo "already present: $DEST"; echo DOWNLOAD_OK; exit 0
fi
for i in $(seq 1 20); do
  .pixi/envs/default/bin/python scripts/ranged_download.py "$URL" "$DEST" --workers 16 && break
  echo "$(date '+%F %T') ranged download pass $i failed, retrying in 60 s"
  sleep 60
done
[ -s "$DEST" ] && [ ! -e "$DEST.part" ] || { echo "download did not complete"; exit 1; }
ln -sf "$DEST" "$LINK"
echo "$(date '+%F %T') $ISO3: $(stat -c %s "$DEST") bytes"
echo DOWNLOAD_OK
