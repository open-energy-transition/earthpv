#!/usr/bin/env bash
# building_layer_stage_tree.sh <variant> : a staging copy of the earthpv repo in which Belgium's and the
# Netherlands' building file is the given variant, so postprocess -> atlas can be rerun
# without writing into the repo. Everything a step WRITES is a real copy here; everything
# it only reads is a symlink to the repo.
set -euo pipefail
V=$1
REPO=/run/media/tobi/aidisc/earthpv
S=/home/tobi/earthpv_data/stage_buildings_20261122
T=$S/tree_$V
AOIS="belgium netherlands"
rm -rf "$T"; mkdir -p "$T"
for e in "$REPO"/* "$REPO"/.pixi; do
  n=$(basename "$e")
  case $n in data|configs|results|src|scripts) ;; *) ln -s "$e" "$T/$n" ;; esac
done
cp -a "$REPO/configs" "$T/configs"
# code resolves REPO_ROOT from __file__, so it must live in the tree, not behind a symlink
rsync -a --exclude __pycache__ "$REPO/src/" "$T/src/"
rsync -a --exclude __pycache__ "$REPO/scripts/" "$T/scripts/"
# results: copies of the two countries' dirs and files, symlinks for the rest
mkdir "$T/results"
for e in "$REPO"/results/*; do
  n=$(basename "$e")
  case $n in belgium_*|netherlands_*|solar_thermal) cp -a "$e" "$T/results/$n" ;;
              *) ln -s "$e" "$T/results/$n" ;; esac
done
# data: symlinks, except labels, predictions and vida
mkdir "$T/data"
for e in "$REPO"/data/* "$REPO"/data/.[!.]*; do
  n=$(basename "$e")
  case $n in labels|predictions|vida|calibration) ;; *) ln -s "$e" "$T/data/$n" ;; esac
done
for d in labels calibration; do
  mkdir "$T/data/$d"
  for e in "$REPO"/data/$d/*; do
    n=$(basename "$e")
    case $n in belgium_*|netherlands_*) cp -a "$e" "$T/data/$d/$n" ;; *) ln -s "$e" "$T/data/$d/$n" ;; esac
  done
done
mkdir -p "$T/data/vida"
for e in "$REPO"/data/vida/*; do ln -s "$(readlink -f "$e")" "$T/data/vida/$(basename "$e")"; done
case $V in
  baseline) ;;  # the installed block fill, as published
  *) for iso in BEL NLD; do ln -sfn "$S/vida/${iso}_${V}.parquet" "$T/data/vida/$iso.parquet"; done ;;
esac
mkdir -p "$T/data/predictions"
for a in $AOIS; do
  mkdir -p "$T/data/predictions/$a"
  ln -s "$(readlink -f "$REPO/data/predictions/$a")/prob" "$T/data/predictions/$a/prob"
done
echo "tree $T: BEL -> $(readlink "$T/data/vida/BEL.parquet"), NLD -> $(readlink "$T/data/vida/NLD.parquet")"
