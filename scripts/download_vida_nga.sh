#!/bin/bash
# Bulk-download VIDA NGA buildings to /home (aidisc is at 99%), then symlink into data/vida/.
# HTTP/2 stream resets mid-transfer are common on this connection (same as the earlier PAK
# and IND downloads) and are not covered by curl's own --retry, so resume in a loop.
# source.coop 403s any request without a User-Agent, which reads exactly like "no such
# country" (CLAUDE.md, "Adding a new AOI").
DEST=/home/tobi/earthpv_data/NGA.parquet
UA="earthpv-new-region/1.0 (research tool; contact via repo issues)"
for i in $(seq 1 50); do
  curl -sS --retry 5 --retry-delay 10 -C - -A "$UA" \
    -o "$DEST.part" \
    "https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country/country_iso=NGA/NGA.parquet" \
    && break
  echo "curl attempt $i failed, resuming..."
  sleep 10
done
mv "$DEST.part" "$DEST"
ln -sf "$DEST" /run/media/tobi/aidisc/earthpv/data/vida/NGA.parquet
echo DOWNLOAD_OK
