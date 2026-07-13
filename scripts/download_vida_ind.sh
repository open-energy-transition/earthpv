#!/bin/bash
# Bulk-download VIDA IND buildings to the aidata drive, then symlink into data/vida/.
# HTTP/2 stream resets mid-transfer are common on this connection (same as the earlier
# PAK download) and are not covered by curl's own --retry, so resume in a loop.
mkdir -p /run/media/tobi/aidata/vida
for i in $(seq 1 50); do
  curl -sS --retry 5 --retry-delay 10 -C - \
    -o /run/media/tobi/aidata/vida/IND.parquet.part \
    "https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country/country_iso=IND/IND.parquet" \
    && break
  echo "curl attempt $i failed, resuming..."
  sleep 10
done
mv /run/media/tobi/aidata/vida/IND.parquet.part /run/media/tobi/aidata/vida/IND.parquet
ln -sf /run/media/tobi/aidata/vida/IND.parquet /run/media/tobi/aidisc/earthpv/data/vida/IND.parquet
echo DOWNLOAD_OK
