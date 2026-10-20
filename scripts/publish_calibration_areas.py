#!/usr/bin/env python
"""Publish every calibration area's boundary as a small static GeoJSON, for the atlas's
"Open in JOSM / iD" buttons.

The boundaries live in `data/labels/`, which is gitignored, so an outside mapper could not
get one without a clone, the data folder and Python. The atlas embeds its areas too, but
rounded to 3 decimals (about 100 m, `atlas._rings`): a map marker, not a line anyone can
map to. This writes, under `docs/assets/labels/calibration_areas/` (committed, served by
Pages with `Access-Control-Allow-Origin: *`):

- `<aoi>/<stem>.geojson`: one area, one feature, coordinates to 7 decimals (OSM's own
  precision). JOSM's Remote Control `import` and iD's `#gpx=` load it from its URL, and
  both pick the format from the `.geojson` extension, so the name must keep it.
- `<aoi>.geojson`: every area of that AOI, which the atlas fetches at runtime by its AOI
  key. Runtime rather than embedded, because `scripts/retemplate_atlas.py` moves a page
  onto a new template without touching its data: a new candidate reaches every atlas the
  next time this runs, with no rebuild. Every configured or published AOI gets one, empty
  if it has no areas, so the page's fetch never 404s.

Three kinds of area:

- `calibration`: a box listed in `configs/atlas/<aoi>.yaml` (`calibration_boxes`), with that
  config's name and status. Drawn and clickable on the atlas.
- `candidate`: `candidate_quadrats/*_candidate.geojson`, minus any already registered and
  any screened out (the rejection register, plus Box 18's three stale-imagery rejects,
  which predate it). Proposed, never mapped; drawn hollow.
- `unlisted`: a registered quadrat the config does not list. Not drawn, since its status
  is a human decision the config has not recorded; published so the atlas's "Propose
  area" overlap check sees every existing quadrat, as `new_calibration_quadrat.py`'s does.

Every feature carries `do_not_upload`, and only whitelisted properties: a boundary's own
properties include local paths (`source_geojson`, `labels_file`) that do not belong on a
public site. No timestamps, so a re-run with nothing new produces no diff.

    pixi run calib-publish
    python scripts/publish_calibration_areas.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shapely.geometry import mapping  # noqa: E402

from earthpv import atlas, atlas_config, roofclf  # noqa: E402
from earthpv.labels import geodesic_area_m2  # noqa: E402

LABELS = Path("data/labels")
CONFIGS = Path("configs/atlas")
OUT = Path("docs/assets/labels/calibration_areas")
PAGES = Path("docs/assets/interactive")
PAGE_AOI = re.compile(r"(.+?)_(?:pv_)?evidence_atlas\.html$")   # as retemplate_atlas.aoi_of
# The flat `data/labels/` directory is Pakistan's (see `atlas.calib_boundary_path`); every
# other AOI keeps its quadrats, and its candidates, under `data/labels/<aoi>/`.
FLAT_AOI = "pakistan"
# Only the flat directory feeds `new_calibration_quadrat.py` (it writes and checks overlap
# there alone), so only that AOI's popups offer its command.
REGISTER_SCRIPT = "scripts/new_calibration_quadrat.py"
REJECT_REGISTER = Path("results/calibration_rejected_regions.csv")
# Box 18 (docs/issues/pakistan-calibration-boxes.md): screened and dropped for stale imagery
# before the rejection register existed. Their files stay in candidate_quadrats/ as a record
# of what was screened out, not as pending work.
SCREENED_OUT = {"mardan_periurban_calib_2km", "shikarpur_periurban_calib_2km",
                "sialkot_periurban_calib_2km"}
# Same text as scripts/export_calibration_quadrats_geojson.py, so a mapper sees one warning.
DO_NOT_UPLOAD = "earthpv calibration reference layer - do not upload to OSM"
DECIMALS = 7
BOUNDARY = "_boundary.geojson"
CANDIDATE = "_candidate.geojson"


def _round(coords):
    if isinstance(coords[0], (int, float)):
        return [round(float(c), DECIMALS) for c in coords[:2]]
    return [_round(c) for c in coords]


def _props(path: Path) -> dict:
    """The first feature's own properties, or none (a JOSM-drawn file may carry none)."""
    feats = json.loads(path.read_text()).get("features") or [{}]
    return feats[0].get("properties") or {}


def _feature(path: Path, stem: str, name: str, kind: str, status: str, extra: dict) -> dict:
    geom = roofclf.load_boundary(path)
    g = mapping(geom)
    props = {"id": stem, "name": name, "kind": kind, "status": status,
             "area_km2": round(geodesic_area_m2(geom) / 1e6, 3)}
    props.update({k: v for k, v in extra.items() if v not in (None, "")})
    props["do_not_upload"] = DO_NOT_UPLOAD
    return {"type": "Feature", "id": stem, "properties": props,
            "geometry": {"type": g["type"], "coordinates": _round(g["coordinates"])}}


def _rejected() -> set[str]:
    """Names recorded by `new_calibration_quadrat.py --reject` (its `--name`, no size tag)."""
    if not REJECT_REGISTER.exists():
        return set()
    with REJECT_REGISTER.open(newline="") as fh:
        return {r["name"] for r in csv.DictReader(fh) if r.get("name")}


def _label(stem: str) -> str:
    return roofclf.quadrat_label(stem).replace("_", " ").title()


def areas_for(aoi: str, labels_dir: Path = LABELS, configs_dir: Path = CONFIGS) -> list[dict]:
    cfg = atlas_config.load(aoi, configs_dir)
    feats, listed = [], set()
    for box in cfg.calibration_boxes:
        path = atlas.calib_boundary_path(aoi, box["stem"], labels_dir)
        if not path.exists():
            raise SystemExit(f"{aoi}: configured box {box['stem']!r} has no boundary at {path}")
        p = _props(path)
        feats.append(_feature(path, box["stem"], box["name"], "calibration", box["status"], {
            "location": p.get("location"), "side_m": p.get("side_m"),
            "imagery_layer": p.get("imagery_layer"), "imagery_date": p.get("imagery_date")}))
        listed.add(box["stem"])

    scoped = Path(labels_dir) / aoi
    home = scoped if scoped.is_dir() else (Path(labels_dir) if aoi == FLAT_AOI else None)
    if home is None:
        return feats
    registered = {p.name[: -len(BOUNDARY)]: p for p in sorted(home.glob(f"*_calib_*{BOUNDARY}"))}
    for stem, path in registered.items():
        if stem not in listed:
            p = _props(path)
            feats.append(_feature(path, stem, _label(stem), "unlisted", "unlisted",
                                  {"location": p.get("location")}))

    rejected = _rejected()
    for path in sorted((home / "candidate_quadrats").glob(f"*{CANDIDATE}")):
        stem = path.name[: -len(CANDIDATE)]
        if stem in registered or stem in SCREENED_OUT or roofclf.quadrat_label(stem) in rejected:
            continue
        p = _props(path)
        loc = p.get("location") or ""
        feats.append(_feature(path, stem, loc.split(",")[0] or _label(stem), "candidate",
                              "candidate", {
                                  "location": loc, "side_m": p.get("side_m"),
                                  "density_bldg_km2": p.get("source_grid_density_bldg_km2"),
                                  "note": p.get("note")}))
    return feats


def _collection(feats: list[dict], meta: dict) -> str:
    """One feature per line, so a changed area is a one-line diff."""
    head = json.dumps({"type": "FeatureCollection", "earthpv": meta}, separators=(",", ":"))
    body = ",\n".join(json.dumps(f, separators=(",", ":"), ensure_ascii=False) for f in feats)
    return head[:-1] + ',"features":[\n' + body + "\n]}\n"


def publish(labels_dir: Path = LABELS, configs_dir: Path = CONFIGS, out: Path = OUT,
            dry_run: bool = False, pages: Path = PAGES) -> dict[str, list[dict]]:
    # A published page without a config (Nigeria) still fetches its index.
    aois = sorted({p.stem for p in Path(configs_dir).glob("*.yaml")}
                  | {m.group(1) for p in Path(pages).glob("*evidence_atlas.html")
                     if (m := PAGE_AOI.match(p.name))})
    plan: dict[Path, str] = {}
    result = {}
    for aoi in aois:
        feats = areas_for(aoi, labels_dir, configs_dir)
        result[aoi] = feats
        meta = {"aoi": aoi, "warning": DO_NOT_UPLOAD,
                "register_script": REGISTER_SCRIPT if aoi == FLAT_AOI else None}
        plan[out / f"{aoi}.geojson"] = _collection(feats, meta)
        for f in feats:
            plan[out / aoi / f"{f['id']}.geojson"] = _collection([f], meta)

    stale = [p for p in Path(out).rglob("*.geojson") if p not in plan] if Path(out).is_dir() else []
    if dry_run:
        return result
    for path, text in plan.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
    for p in stale:
        p.unlink()
    for d in sorted((d for d in Path(out).glob("*") if d.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()
    os.chdir(ROOT)  # configs/atlas/ and data/labels/ are repository-relative
    result = publish(dry_run=args.dry_run)
    for aoi, feats in result.items():
        if not feats:
            continue
        kinds = {}
        for f in feats:
            kinds[f["properties"]["kind"]] = kinds.get(f["properties"]["kind"], 0) + 1
        print(f"  {aoi}: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    if not args.dry_run:
        size = sum(p.stat().st_size for p in OUT.rglob("*.geojson"))
        print(f"wrote {OUT}/ ({size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
