#!/usr/bin/env bash
# One-screen status of the Vietnam + India run (scripts/run_vn_in_queue.sh).
# Read-only. What each 6-hourly check-in starts from.
#
#   bash scripts/vn_in_status.sh
cd "$(dirname "$0")/.."
Q=data/vn_in_queue_markers
now=$(date +%s)
echo "== $(date '+%F %T')  earthpv Vietnam + India status"

echo "-- units"
systemctl --user list-units --all --no-legend 'earthpv-*' 2>/dev/null \
  | awk '{printf "   %-40s %s/%s\n", $1, $3, $4}'
for u in earthpv-compose-vietnam earthpv-compose-india earthpv-vietnam-compute earthpv-india-compute; do
  systemctl --user is-active --quiet "$u" && \
    echo "   $u mem $(systemctl --user show -p MemoryCurrent --value "$u" | awk '{printf "%.1fG", $1/1e9}')"
done

echo "-- compose"
for a in vietnam india; do
  log=data/compose_$a.log
  got=$(find -L data/composites/$a/composites -name composite_0.tif 2>/dev/null | wc -l)
  sel=$(grep -aoE "Selected [0-9]+ cells" "$log" 2>/dev/null | tail -1 | grep -oE "[0-9]+")
  lbl=$(grep -aoE "[0-9]+ contain OSM solar labels" "$log" 2>/dev/null | tail -1 | grep -oE "^[0-9]+")
  # cells landed in the last 6 h, from file mtimes (a rate that cannot be fooled by logs)
  r6=$(find -L data/composites/$a/composites -name composite_0.tif -newermt "-6 hours" 2>/dev/null | wc -l)
  rate=$(awk -v n="$r6" 'BEGIN{printf "%.1f", n/6}')
  if [ -n "$sel" ] && [ "$r6" -gt 0 ]; then
    eta=$(awk -v s="$sel" -v g="$got" -v r="$rate" 'BEGIN{printf "%.1f d", (s-g)/r/24}')
  else eta="-"; fi
  echo "   $a: $got/${sel:-?} cells (label cells ${lbl:-?}), last 6 h: $r6 (${rate}/h), ETA $eta"
  echo "      done marker: $(cat $Q/${a}_compose_done 2>/dev/null || echo no)" \
       " | unproductive rounds: $(cat $Q/${a}_unproductive 2>/dev/null || echo 0)"
  hand=$(grep -ac "exceeded" "$log" 2>/dev/null); errs=$(grep -acE "ERROR|Traceback" "$log" 2>/dev/null)
  echo "      log: $(tail -c 300000 "$log" 2>/dev/null | grep -aoE '[0-9]+/[0-9]+ \[[^]]*\]' | tail -1)  PC hand-offs total $hand, errors total $errs"
done

echo "-- compute (markers)"
for a in vietnam india; do
  m=data/${a}_pipeline_markers
  echo "   $a: $(ls $m 2>/dev/null | tr '\n' ' ')"
  [ -f "results/${a}_checkpoint_decision.json" ] && \
    echo "      decision: $(python3 -c "import json;d=json.load(open('results/${a}_checkpoint_decision.json'));print(d['winner'],'|',d['reason'])")"
  tail -1 data/${a}_pipeline.log 2>/dev/null | sed 's/^/      last: /' | cut -c1-200
  [ -f "$Q/${a}_needs_attention" ] && echo "      !!! NEEDS ATTENTION"
done
[ -f data/.gpu.lock ] && echo "   gpu: $(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null)"

echo "-- inputs"
echo "   VNM VIDA: $( [ -s data/vida/VNM.parquet ] && [ ! -e /home/tobi/earthpv_data/VNM.parquet.part ] && echo ready || echo "downloading $(wc -l < /home/tobi/earthpv_data/VNM.parquet.part.done 2>/dev/null)/246 chunks")"
for a in vietnam india; do
  f=data/labels/${a}_overpass_solar.parquet
  echo "   $a labels: $( [ -s $f ] && echo "ready ($(stat -c %s $f) B)" || echo "pending ($(ls data/labels/.overpass_tiles/${a}_*/ 2>/dev/null | wc -l) tiles cached)")"
done

echo "-- disk / memory / link"
df -h / /run/media/tobi/aidisc | awk 'NR>1{printf "   %-28s %s free (%s used)\n", $6, $4, $5}'
free -g | awk '/Mem/{printf "   RAM %sG used of %sG, available %sG\n", $3, $2, $7}'
IF=wlxb44bd62bd203; r0=$(cat /sys/class/net/$IF/statistics/rx_bytes); sleep 5; r1=$(cat /sys/class/net/$IF/statistics/rx_bytes)
echo "   link rx now: $(( (r1 - r0) / 5000 )) kB/s"

echo "-- queue log (last 8)"
tail -8 data/vn_in_queue.log 2>/dev/null | sed 's/^/   /'
