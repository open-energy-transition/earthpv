#!/usr/bin/env python
"""Bootstrap a new country or region: register it, check the data actually exists,
and print the exact command sequence to run.

Everything earthpv needs for a region it has never seen comes from four open
sources. This script checks all four before you spend hours of network time, then
writes the AOI block for you.

    # 1. is there anything to find, and is the data reachable?
    pixi run python scripts/new_region.py check \\
        --bbox 98.5,7.8,101.0,10.2 --iso3 THA --name "Surat Thani"

    # 2. register it in configs/aoi.yaml
    pixi run python scripts/new_region.py add \\
        --aoi surat_thani --bbox 98.5,7.8,101.0,10.2 --iso3 THA \\
        --division "Surat Thani" --subtype region

    # 3. print the ordered runbook, with this AOI's name filled in
    pixi run python scripts/new_region.py plan --aoi surat_thani

`check` is read-only and takes a couple of minutes. `add` edits `configs/aoi.yaml`
in place and refuses to overwrite an existing AOI. Neither downloads imagery.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import textwrap
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

CONFIG = REPO / "configs" / "aoi.yaml"

VIDA_URL = (
    "https://data.source.coop/vida/google-microsoft-open-buildings/"
    "geoparquet/by_country/country_iso={iso3}/{iso3}.parquet"
)
GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{level}/"
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

OK, WARN, BAD = "  ok  ", " warn ", " fail "
UA = {"User-Agent": "earthpv-new-region/1.0 (research tool; contact via repo issues)"}


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    parts = [float(x) for x in text.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be minlon,minlat,maxlon,maxlat")
    minx, miny, maxx, maxy = parts
    if not (minx < maxx and miny < maxy):
        raise argparse.ArgumentTypeError("bbox must be minlon,minlat,maxlon,maxlat with min < max")
    return minx, miny, maxx, maxy


def bbox_area_km2(bbox) -> float:
    minx, miny, maxx, maxy = bbox
    mid = math.radians((miny + maxy) / 2)
    return (maxx - minx) * 111.32 * math.cos(mid) * (maxy - miny) * 110.57


def line(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f"  {detail}" if detail else ""))


# ------------------------------------------------------------------------------ checks


def check_osm(bbox, timeout: int) -> int | None:
    """Count OpenStreetMap solar features in the bbox. These become training labels."""
    from earthpv.overpass import fetch_solar_overpass

    try:
        gdf = fetch_solar_overpass(bbox=bbox, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - a failed preflight is information, not a crash
        line(WARN, "OpenStreetMap solar labels", f"Overpass failed: {e}")
        print("        Country-scale bboxes usually need per-province chunking, or use")
        print("        --skip-osm and query provinces one at a time with overpass-labels.")
        return None
    n = len(gdf)
    kinds = gdf["kind"].value_counts().to_dict() if n else {}
    if n == 0:
        line(WARN, "OpenStreetMap solar labels", "0 features")
        print("        Detection still works with the existing checkpoint, but there is")
        print("        nothing to train on and nothing to measure recall against here.")
    elif n < 50:
        line(WARN, "OpenStreetMap solar labels", f"{n} features {kinds}")
        print("        Thin. Expect to map a calibration quadrat before trusting recall.")
    else:
        line(OK, "OpenStreetMap solar labels", f"{n} features {kinds}")
    return n


def check_vida(iso3: str, timeout: int) -> bool:
    """VIDA Open Buildings supplies the footprints that gate cells and place candidates."""
    local = REPO / "data" / "vida" / f"{iso3}.parquet"
    if local.exists():
        line(OK, "VIDA Open Buildings", f"cached locally, {local.stat().st_size / 1e9:.1f} GB")
        return True
    url = VIDA_URL.format(iso3=iso3)
    # source.coop rejects requests with no User-Agent with a bare 403, which reads
    # exactly like "this country does not exist". Send one.
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            size = int(resp.headers.get("Content-Length", 0))
        line(OK, "VIDA Open Buildings", f"available remotely, {size / 1e9:.1f} GB")
        if size > 2e9:
            print("        Large. For country-scale work download it once to")
            print(f"        data/vida/{iso3}.parquet; remote row-group scans are far slower.")
        return True
    except Exception as e:  # noqa: BLE001
        line(BAD, "VIDA Open Buildings", f"no parquet for {iso3}: {e}")
        print("        Check the ISO3 code. Without footprints, cell selection and the")
        print("        building prior both fall back to Overture, which undercounts")
        print("        small and informal structures badly.")
        return False


def check_geoboundaries(iso3: str, timeout: int) -> bool:
    """Admin polygons, needed by the density stage to aggregate per province."""
    ok = True
    for level in ("ADM1", "ADM2"):
        try:
            meta = json.load(urllib.request.urlopen(urllib.request.Request(
                GEOBOUNDARIES_API.format(iso3=iso3, level=level), headers=UA),
                timeout=timeout))
            line(OK, f"geoBoundaries {level}", meta.get("boundaryName", iso3))
        except Exception as e:  # noqa: BLE001
            line(WARN, f"geoBoundaries {level}", f"unavailable: {e}")
            if level == "ADM1":
                ok = False
                print("        Density still runs; pass --regions-file with your own polygons.")
    return ok


def check_imagery(bbox, window: str, timeout: int) -> int | None:
    """Sentinel-2 coverage over the bbox for the compose window."""
    try:
        import planetary_computer
        import pystac_client
    except ImportError:
        line(WARN, "Sentinel-2 imagery", "pystac_client not installed in this environment")
        return None
    start, end = window.split(":")
    try:
        cat = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
        search = cat.search(
            collections=["sentinel-2-l2a"], bbox=list(bbox),
            datetime=f"{start}/{end}", limit=500,
            query={"eo:cloud_cover": {"lt": 40}},
        )
        items = list(search.items())
    except Exception as e:  # noqa: BLE001
        line(WARN, "Sentinel-2 imagery", f"STAC search failed: {e}")
        print("        Planetary Computer has frequent multi-hour outages. Retry later;")
        print("        compose also falls back to Earth Search on AWS Open Data.")
        return None
    if not items:
        line(BAD, "Sentinel-2 imagery", f"no scenes under 40% cloud in {window}")
        print("        Pick a drier window for this latitude. The composite is a median")
        print("        of the least-cloudy scenes, so a wet window gives a poor base.")
        return 0
    clouds = sorted(i.properties.get("eo:cloud_cover", 100) for i in items)
    tiles = {i.properties.get("s2:mgrs_tile") for i in items}
    line(OK, "Sentinel-2 imagery",
         f"{len(items)} scenes under 40% cloud across {len(tiles)} MGRS tiles, "
         f"median cloud {clouds[len(clouds) // 2]:.0f}%")
    return len(items)


def estimate_cost(bbox) -> None:
    """Rough compose budget. The real number needs a VIDA scan; this is the ceiling."""
    minx, miny, maxx, maxy = bbox
    total = math.ceil((maxx - minx) / 0.1) * math.ceil((maxy - miny) / 0.1)
    line(OK, "Grid size", f"{total:,} cells of 0.1 degree over {bbox_area_km2(bbox):,.0f} km2")
    print("        Only building-populated cells are composited. In Pakistan that was")
    print("        about 4,470 of 62,000. At one to two minutes per cell, budget")
    print(f"        {total * 0.07 / 60:.0f} to {total * 0.15 / 60:.0f} hours if a "
          "similar 7 to 15 percent are populated.")
    print("        Run `earthpv compose --aoi <aoi> --min-buildings 1000` for the real count.")


def cmd_check(args) -> int:
    bbox = args.bbox
    iso3 = args.iso3.upper()
    print(f"\nPreflight for {args.name or iso3}  bbox={bbox}  iso3={iso3}\n")
    results = []
    if not args.skip_osm:
        results.append(check_osm(bbox, args.timeout) is not None)
    results.append(check_vida(iso3, args.timeout))
    check_geoboundaries(iso3, args.timeout)
    results.append(check_imagery(bbox, args.window, args.timeout) not in (0, None))
    estimate_cost(bbox)
    print()
    if all(results):
        print("All required sources reachable. Register the AOI with `new_region.py add`.")
        return 0
    print("Some sources need attention. See the notes above; most are workable.")
    return 1


# --------------------------------------------------------------------------------- add


DEFAULT_COMMENT = (
    "Added by scripts/new_region.py. No source_region key, so chips and compose "
    "fetch from Planetary Computer STAC rather than a local composite cache."
)

TEMPLATE = """
{comment}
  {aoi}:
    bbox: [{minx}, {miny}, {maxx}, {maxy}]
    division: {{ name: {division}, country: {iso2}, subtype: {subtype}, iso3: {iso3} }}
"""


def cmd_add(args) -> int:
    import yaml

    text = CONFIG.read_text()
    raw = yaml.safe_load(text)
    if args.aoi in (raw.get("aois") or {}):
        print(f"AOI '{args.aoi}' already exists in {CONFIG.relative_to(REPO)}. "
              "Edit it by hand or pick another name.")
        return 1

    minx, miny, maxx, maxy = args.bbox
    iso3 = args.iso3.upper()
    comment = "\n".join(
        f"  # {ln}" for ln in textwrap.wrap(args.comment or DEFAULT_COMMENT, 84)
    )
    block = TEMPLATE.format(
        comment=comment,
        aoi=args.aoi, minx=minx, miny=miny, maxx=maxx, maxy=maxy,
        division=args.division or args.aoi.replace("_", " ").title(),
        iso2=args.iso2 or iso3[:2], subtype=args.subtype, iso3=iso3,
    )

    # The `aois:` mapping is followed by a top-level `seasons:` block; insert before it
    # so the new entry lands inside `aois` regardless of how the file grows.
    marker = "\nseasons:"
    if marker not in text:
        print(f"Could not find the `seasons:` block in {CONFIG}; append by hand:\n{block}")
        return 1
    head, tail = text.split(marker, 1)
    CONFIG.write_text(head.rstrip("\n") + "\n" + block + marker + tail)

    # Re-parse so a malformed insert fails here rather than three stages later.
    reparsed = yaml.safe_load(CONFIG.read_text())
    if args.aoi not in (reparsed.get("aois") or {}):
        print("Insert produced invalid YAML. Restore with `git checkout configs/aoi.yaml`.")
        return 1
    print(f"Added '{args.aoi}' to {CONFIG.relative_to(REPO)}:\n{block}")
    print(f"Next: pixi run python scripts/new_region.py plan --aoi {args.aoi}")
    return 0


# -------------------------------------------------------------------------------- plan


PLAN = """
Runbook for '{aoi}'
{rule}

Nothing below needs pre-downloaded data. Every stage is resumable; relaunch the
same command after an interruption and it continues.

  1. Labels, from live OpenStreetMap
     pixi run earthpv overpass-labels --bbox {bbox} --iso3 {iso3} --name {aoi}
     For a whole country, query province by province with --place instead; a
     single country-wide Overpass call usually times out.

  2. Imagery, only over building-populated cells        (network-bound, hours)
     pixi run -e ml earthpv compose --aoi {aoi} --min-buildings 1000 --workers 6
     Run it detached under its own unit, see the operations notes:
     systemd-run --user --collect --unit=earthpv-compose-{aoi} \\
       -p WorkingDirectory={repo} bash scripts/compose_loop.sh {aoi} 0 1000

  3. Detect, reusing the existing checkpoint            (GPU)
     pixi run -e ml earthpv infer --aoi {aoi} \\
       --checkpoint data/models/v2_combined/terramind-pv-epoch=39.ckpt

  4. Rank and export leads for mappers
     pixi run earthpv postprocess --aoi {aoi} --threshold 0.3 --max-building-dist 30
     pixi run earthpv export --aoi {aoi} --exclude-mapped --min-distance-m 100

  ---- stop here for a first candidate set. Everything below needs local evidence ----

  5. Map, and measure. Send the leads to mappers, and map one 1 km2 quadrat
     exhaustively (docs/calibration-mapping-protocol.md). The quadrat is what
     tells you the model's real recall here; leads alone only confirm what it finds.

  6. Retrain in domain, once mapping has produced local positives
     pixi run earthpv chips --aoi {aoi}
     .pixi/envs/default/bin/python scripts/merge_chip_index.py germany {aoi}:2
     pixi run -e ml earthpv train --config configs/terramind_pv.yaml
     pixi run -e ml earthpv evaluate --aoi {aoi} --checkpoint <new ckpt>

  7. Capacity, once precision is calibrated
     pixi run earthpv calibrate-candidates --aoi {aoi}
     pixi run earthpv density --aoi {aoi} --districts
     pixi run earthpv atlas --aoi {aoi}

Full guide: https://open-energy-transition.github.io/earthpv/scale/
"""


def cmd_plan(args) -> int:
    from earthpv.buildings import _iso3_for
    from earthpv.config import Settings

    settings = Settings.load()
    cfg = settings.aois.get(args.aoi)
    if cfg is None:
        print(f"Unknown AOI '{args.aoi}'. Known: {', '.join(sorted(settings.aois))}")
        return 1
    bbox = ",".join(str(v) for v in cfg["bbox"])
    iso3 = _iso3_for(cfg) or "<ISO3>"
    if iso3 == "<ISO3>":
        print(f"warning: AOI '{args.aoi}' has no resolvable ISO3. Add "
              "`iso3: XXX` to its division block, or the VIDA and geoBoundaries "
              "lookups will fail later.\n")
    print(PLAN.format(aoi=args.aoi, bbox=bbox, iso3=iso3, repo=REPO,
                      rule="=" * (len(args.aoi) + 14)))
    return 0


# --------------------------------------------------------------------------------- cli


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="preflight the four open data sources, read-only")
    c.add_argument("--bbox", type=parse_bbox, required=True,
                   help="minlon,minlat,maxlon,maxlat")
    c.add_argument("--iso3", required=True, help="ISO3 country code, e.g. THA")
    c.add_argument("--name", help="label for the report")
    c.add_argument("--window", default="2025-11-01:2026-03-15",
                   help="dry-season window to test imagery for, START:END")
    c.add_argument("--skip-osm", action="store_true",
                   help="skip the Overpass query, which times out on country-scale bboxes")
    c.add_argument("--timeout", type=int, default=180)
    c.set_defaults(func=cmd_check)

    a = sub.add_parser("add", help="register the AOI in configs/aoi.yaml")
    a.add_argument("--aoi", required=True, help="short key, lowercase with underscores")
    a.add_argument("--bbox", type=parse_bbox, required=True)
    a.add_argument("--iso3", required=True)
    a.add_argument("--iso2", help="ISO2 country code, defaults to the first two ISO3 letters")
    a.add_argument("--division", help="administrative name, defaults to a title-cased AOI key")
    a.add_argument("--subtype", default="region", choices=["country", "region", "county"])
    a.add_argument("--comment", help="one-line note written above the AOI block")
    a.set_defaults(func=cmd_add)

    pl = sub.add_parser("plan", help="print the ordered runbook for a registered AOI")
    pl.add_argument("--aoi", required=True)
    pl.set_defaults(func=cmd_plan)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
