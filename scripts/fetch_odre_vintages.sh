#!/usr/bin/env bash
# Pull year-end ODRE register vintages, verifying each one.
# The export endpoint has returned truncated CSVs on an SSL reset with a zero exit path
# through a loop, so every file is re-fetched until its line count is stable and its
# last line parses -- a short file here silently becomes "PV did not exist yet".
set -u
UA="earthpv-research/1.0 (research tool; contact via repo issues)"
BASE="https://odre.opendatasoft.com/api/explore/v2.1/catalog/datasets"
OUT=data/register
mkdir -p "$OUT"
for y in "$@"; do
  f="$OUT/odre_solaire_3112${y}.csv"
  for attempt in 1 2 3 4 5; do
    curl -sSL -A "$UA" --max-time 1800 --retry 3 --retry-delay 15 \
      -G "$BASE/registre-national-installation-production-stockage-electricite-agrege-3112${y}/exports/csv" \
      --data-urlencode "where=filiere like 'Solaire'" --data-urlencode "delimiter=;" \
      -o "$f.part" && mv "$f.part" "$f" || { echo "20$y attempt $attempt failed"; sleep 20; continue; }
    n=$(wc -l < "$f")
    # A real year-end French solar register has tens of thousands of rows; anything
    # under 20k means the export was cut off mid-stream.
    if [ "$n" -ge 20000 ] && tail -1 "$f" | grep -q ';'; then
      echo "20$y ok: $n lines, $(du -h "$f" | cut -f1)"; break
    fi
    echo "20$y short ($n lines), retrying"; sleep 20
  done
done
