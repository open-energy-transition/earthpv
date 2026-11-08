#!/usr/bin/env python
"""What has happened in each calibration area, read from OpenStreetMap's own edit history.

Writes one CSV row per area in `docs/assets/labels/calibration_areas/`, from two read-only
sources:

- **OSMCha**: changeset search, which OSM's own API lacks. Every changeset whose comment names
  the campaign, and the small changesets over each area (`area_lt` drops the continent-wide
  tag edits that were 98-100% of OSM's `changesets?bbox=` results on three Pakistani areas).
- **Overpass**: the solar elements in each area with the changesets that made them, plus an
  `adiff` query for elements removed since the area's registration snapshot.

Overpass is used sparingly on purpose. One query took 30-60 s even for an empty 2 km box and
the public endpoint asks automated clients to keep their volume down, so the script makes one
combined query per country instead of two per area, and assigns elements to areas here. It
takes additions and edits from each element's own metadata (`version` and `timestamp`). Only
removals need `adiff`, and only an area a small changeset has touched since its window began
is checked for them, unless `--check-all-removals` is given.

It needs only the Python standard library and a clone: the boundaries are the published ones,
so `data/` is optional. Where `data/labels/` exists, a registered area's window starts when
the OSM pull the pipeline reads for it was made (the newest `<stem>_overpass_solar*.parquet`);
otherwise it starts `--window-days` ago, and `since_basis` says which. France's areas are
surveys drawn on IGN imagery, not OSM pulls, so their OSM counts say nothing about their labels. A candidate has no snapshot to drift from, so it has no window
unless `--since` is given.

**A changeset records edits, never a sweep.** A mapper who checks an area and finds no panels
uploads nothing, so a confirmed-empty area reads like an untouched one (Jacobabad: confirmed
no PV, no solar elements, no local changeset). `activity` therefore says "no activity seen",
never zero PV, and a blank cell means not checked. Whether an area is finished stays a human
declaration: see `docs/contribute/activity.md`.

The output holds counts and changeset ids, never mapper names.

The OSMCha API key is read from `--token-file` (default `~/.config/earthpv/osmcha_token`) and
sent only to osmcha.org, in a header. There is deliberately no option to pass it on the
command line, where it would reach the shell history and the process list, and a key file
inside the repository or readable by other accounts is refused.

    pixi run calib-activity                              # every area
    pixi run calib-activity -- --aoi yemen
    pixi run calib-activity -- --registered-only --since 2026-10-01
    pixi run calib-activity -- --skip-osmcha             # Overpass columns only, no key
    python scripts/calibration_area_activity.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import http.client
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AREAS_DIR = REPO / "docs" / "assets" / "labels" / "calibration_areas"
DEFAULT_TOKEN_FILE = Path("~/.config/earthpv/osmcha_token")
DOCS_HINT = "See docs/contribute/activity.md for how to get and save the key."

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSMCHA_URL = "https://osmcha.org/api/v1/changesets/"
USER_AGENT = "earthpv-calibration-activity/1.0 (https://github.com/open-energy-transition/earthpv)"

# The same two selectors as earthpv.overpass, which this script does not import so that it
# runs without the pipeline's environment.
SELECTORS = ('["generator:source"="solar"]', '["plant:source"="solar"]')
QUERY_TIMEOUT_S = 280
HTTP_TIMEOUT_S = 420
RETRY_WAITS_S = (15, 45, 90, 180)
RETRYABLE_HTTP = {429, 500, 502, 503, 504}

OSMCHA_PAGE_SIZE = 500
OSMCHA_PAUSE_S = 1.0
CAMPAIGN_START = dt.date(2026, 7, 1)  # the first changeset naming EarthPV is from 2026-07-18
# Keep a changeset whose bounding box is under this many times the area's own bounding box.
# A mapper's upload for one area passes; a national tag edit does not.
LOCAL_AREA_RATIO = 10

FIELDS = [
    "aoi", "area_id", "name", "kind", "status", "area_km2",
    "activity",
    "solar_elements_now", "oldest_edit", "newest_edit", "newest_changeset",
    "changesets_on_elements", "mappers",
    "calibration_changesets", "earthpv_changesets", "share_on_calibration_changesets",
    "since", "since_basis", "added_since", "changed_since", "removed_since",
    "local_changesets", "local_calibration_changesets", "newest_local_changeset_date",
    "osm_data_time",
]


class ServiceFailure(Exception):
    """Overpass or OSMCha did not give a usable answer after every retry."""


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies request headers onto a redirect, so the key could reach another host."""

    def redirect_request(self, *args, **kwargs):
        return None


OSMCHA_OPENER = urllib.request.build_opener(_RefuseRedirect)


def load_token(path: Path) -> str:
    """The OSMCha key from `path`. Its value is never printed, here or anywhere else."""
    shown = path
    path = path.expanduser().resolve()
    if path.is_relative_to(REPO):
        sys.exit(f"Refusing an OSMCha key inside the repository ({shown}). "
                 f"Move it out so it cannot be committed. {DOCS_HINT}")
    if not path.is_file():
        sys.exit(f"No OSMCha API key at {shown}. {DOCS_HINT} "
                 "Or pass --skip-osmcha for the Overpass columns only.")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        sys.exit(f"{shown} is readable by other accounts. Run: chmod 600 {shown}")
    # OSMCha's copy button copies the header value, "Token <key>", so accept either form.
    key = path.read_text().strip().removeprefix("Token ").strip()
    if not key or any(ch.isspace() for ch in key):
        sys.exit(f"{shown} does not hold a single API key. {DOCS_HINT}")
    return key


def with_retries(label: str, attempt):
    """Call `attempt`, waiting through the rate limits and truncated replies both services give."""
    last = ""
    for wait in (*RETRY_WAITS_S, None):
        try:
            return attempt()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_HTTP:
                raise ServiceFailure(f"{label}: HTTP {exc.code}") from None
            last = f"HTTP {exc.code}"
            retry_after = exc.headers.get("Retry-After", "")
            if wait is not None and retry_after.isdigit():
                wait = max(wait, int(retry_after))
        except (OSError, http.client.HTTPException, ValueError, KeyError, ET.ParseError) as exc:
            last = type(exc).__name__
        if wait is not None:
            time.sleep(wait)
    raise ServiceFailure(f"{label}: {last} after {len(RETRY_WAITS_S) + 1} attempts")


def overpass(query: str, url: str, parse):
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT})

    def attempt():
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            return parse(response.read())

    return with_retries("Overpass", attempt)


def parse_current(raw: bytes):
    """A runtime error arrives as a 200 with a remark and partial elements: never trust those."""
    payload = json.loads(raw)
    if "remark" in payload:
        raise ValueError(payload["remark"])
    return payload["osm3s"]["timestamp_osm_base"], payload["elements"]


def parse_removals(raw: bytes) -> list[tuple[str, list[tuple[float, float]]]]:
    """(time removed, vertices of the old version) per element that left the solar set."""
    root = ET.fromstring(raw)
    remark = root.find("remark")
    if remark is not None:
        raise ValueError(remark.text)
    if root.find("meta") is None:
        raise ValueError("no meta element")
    removals = []
    for action in root.findall("action"):
        if action.get("type") != "delete":
            continue
        old, new = action.find("old")[0], action.find("new")[0]
        vertices = [(float(node.get("lon")), float(node.get("lat")))
                    for node in old.iter() if node.get("lat") is not None]
        removals.append((new.get("timestamp") or "", vertices))
    return removals


def osmcha_get(params: dict, token: str) -> dict:
    request = urllib.request.Request(
        f"{OSMCHA_URL}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": f"Token {token}", "Accept": "application/json",
                 "User-Agent": USER_AGENT})

    def attempt():
        try:
            with OSMCHA_OPENER.open(request, timeout=HTTP_TIMEOUT_S) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                sys.exit(f"OSMCha refused the API key (HTTP {exc.code}). {DOCS_HINT}")
            raise

    return with_retries("OSMCha", attempt)


def campaign_kind(comment: str) -> str:
    """The atlas's editor links write both spellings into every calibration comment."""
    low = comment.lower()
    return "calibration" if "earthpv-calibration" in low or "earthpv calibration" in low else "earthpv"


def campaign_changesets(token: str) -> dict[int, str]:
    """{changeset id: 'calibration' | 'earthpv'} for every changeset naming the campaign.

    A comment search scans the table: 21 s back to July 2026, 72 s back to January, an HTTP
    500 back to 2025. One month at a time stays small however long the campaign runs.
    """
    found: dict[int, str] = {}
    start = CAMPAIGN_START
    today = dt.datetime.now(dt.timezone.utc).date()
    while start <= today:
        end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        page = 1
        while True:
            payload = osmcha_get({"comment": "earthpv", "date__gte": start.isoformat(),
                                  "date__lte": end.isoformat(), "page": page,
                                  "page_size": OSMCHA_PAGE_SIZE}, token)
            for feature in payload["features"]:
                found[int(feature["id"])] = campaign_kind(
                    feature["properties"].get("comment") or "")
            time.sleep(OSMCHA_PAUSE_S)
            if not payload.get("next"):
                break
            page += 1
        start = end
    return found


def outer_rings(geometry: dict) -> list:
    """The published areas have no holes, so the outer rings are the whole boundary."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    return [polygon[0] for polygon in geometry["coordinates"]]


def iso_utc(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_time(area_id: str, aoi: str) -> dt.datetime | None:
    """When the OSM pull the pipeline reads for this area was made, on a maintainer's clone.

    That is the last name in sort order, as in `roofclf`: an area re-pulled later carries
    `<stem>_overpass_solar_<date>.parquet` beside the original, which the fit no longer reads.
    """
    labels = REPO / "data" / "labels"
    for folder in (labels, labels / aoi):
        pulls = sorted(folder.glob(f"{area_id}_overpass_solar*.parquet"))
        if pulls:
            return dt.datetime.fromtimestamp(pulls[-1].stat().st_mtime, dt.timezone.utc)
    return None


def window_for(props: dict, aoi: str, args) -> tuple[str | None, str]:
    """The start of an area's change window and what it rests on."""
    if args.since:
        return args.since, "--since"
    if props["kind"] == "candidate":
        return None, ""
    snapshot = snapshot_time(props["id"], aoi)
    if snapshot is not None:
        return iso_utc(snapshot), "local snapshot"
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.window_days)
    return iso_utc(start), f"window ({args.window_days} days)"


def load_areas(args) -> dict[str, list[dict]]:
    """The selected areas per country, each with its bounding box and change window."""
    available = sorted(path.stem for path in AREAS_DIR.glob("*.geojson"))
    unknown = sorted(set(args.aoi or []) - set(available))
    if unknown:
        sys.exit(f"Unknown --aoi {unknown}. Available: {available}")
    selected: dict[str, list[dict]] = {}
    for aoi in args.aoi or available:
        collection = json.loads((AREAS_DIR / f"{aoi}.geojson").read_text())
        for feature in collection["features"]:
            props = feature["properties"]
            if args.registered_only and props["kind"] == "candidate":
                continue
            if args.area and props["id"] not in args.area:
                continue
            rings = outer_rings(feature["geometry"])
            lons = [point[0] for ring in rings for point in ring]
            lats = [point[1] for ring in rings for point in ring]
            since, basis = window_for(props, aoi, args)
            selected.setdefault(aoi, []).append({
                **props, "aoi": aoi, "rings": rings, "since": since, "since_basis": basis,
                "bbox": (min(lons), min(lats), max(lons), max(lats))})
    found = {area["id"] for group in selected.values() for area in group}
    missing = sorted(set(args.area or []) - found)
    if missing:
        sys.exit(f"No such area in the selection: {missing}")
    return selected


def in_rings(lon: float, lat: float, rings: list) -> bool:
    for ring in rings:
        inside = False
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            if (y0 > lat) != (y1 > lat) and lon < x0 + (lat - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
        if inside:
            return True
    return False


def in_area(lon: float, lat: float, area: dict) -> bool:
    west, south, east, north = area["bbox"]
    return west <= lon <= east and south <= lat <= north and in_rings(lon, lat, area["rings"])


def bbox_clauses(areas: list[dict]) -> str:
    return "".join(f"nwr{selector}({area['bbox'][1]},{area['bbox'][0]},"
                   f"{area['bbox'][3]},{area['bbox'][2]});"
                   for area in areas for selector in SELECTORS)


def elements_in(area: dict, elements: list[dict]) -> list[dict]:
    """An element belongs to an area when its point (a way's or relation's centre) is inside."""
    found = []
    for element in elements:
        where = element if "lat" in element else element.get("center")
        if where and in_area(where["lon"], where["lat"], area):
            found.append(element)
    return found


def fill_elements(row: dict, area: dict, elements: list[dict],
                  campaign: dict[int, str] | None) -> None:
    row["solar_elements_now"] = len(elements)
    row["changesets_on_elements"] = len({element["changeset"] for element in elements})
    row["mappers"] = len({element["uid"] for element in elements})
    if elements:
        newest = max(elements, key=lambda element: element["timestamp"])
        row["oldest_edit"] = min(element["timestamp"] for element in elements)[:10]
        row["newest_edit"] = newest["timestamp"][:10]
        row["newest_changeset"] = newest["changeset"]
    if area["since"] is not None:
        edited = [element for element in elements if element["timestamp"] >= area["since"]]
        row["added_since"] = sum(element["version"] == 1 for element in edited)
        row["changed_since"] = len(edited) - row["added_since"]
    if campaign is None:
        return
    on_elements = {element["changeset"] for element in elements}
    calibration = {cid for cid in on_elements if campaign.get(cid) == "calibration"}
    row["calibration_changesets"] = len(calibration)
    row["earthpv_changesets"] = len(on_elements & set(campaign))
    if elements:
        on_calibration = sum(element["changeset"] in calibration for element in elements)
        row["share_on_calibration_changesets"] = round(on_calibration / len(elements), 3)


def fill_local(row: dict, area: dict, token: str, args, campaign: dict[int, str]) -> None:
    west, south, east, north = area["bbox"]
    payload = osmcha_get({"in_bbox": f"{west},{south},{east},{north}",
                          "area_lt": LOCAL_AREA_RATIO, "date__gte": args.osmcha_since,
                          "page": 1, "page_size": OSMCHA_PAGE_SIZE}, token)
    features = payload["features"]
    row["local_changesets"] = payload["count"]
    row["local_calibration_changesets"] = sum(
        campaign.get(int(feature["id"])) == "calibration" for feature in features)
    if features:
        row["newest_local_changeset_date"] = max(
            feature["properties"]["date"] for feature in features)[:10]


def needs_removal_check(area: dict, row: dict, args) -> bool:
    if area["since"] is None:
        return False
    if args.check_all_removals:
        return True
    return row["newest_local_changeset_date"] >= area["since"][:10]  # "" sorts before any date


def fill_removals(pairs: list[tuple[dict, dict]], args) -> None:
    """One adiff for the country, from its earliest window; each area keeps its own window."""
    if not pairs:
        return
    start = min(area["since"] for area, _ in pairs)
    query = (f'[out:xml][timeout:{QUERY_TIMEOUT_S}][adiff:"{start}"];'
             f"({bbox_clauses([area for area, _ in pairs])});out meta geom;")
    removals = overpass(query, args.overpass_url, parse_removals)
    for area, row in pairs:
        row["removed_since"] = sum(
            (not when or when >= area["since"])
            and any(in_area(lon, lat, area) for lon, lat in vertices)
            for when, vertices in removals)
    time.sleep(args.pause)


def classify(row: dict) -> str:
    """Words, not a number: no value here may read as a measurement of how much PV exists."""
    elements = row["solar_elements_now"]
    if row["local_changesets"] == "":
        return "solar elements present" if elements else "no solar elements seen"
    if row["calibration_changesets"]:
        return "calibration upload"
    if row["local_calibration_changesets"]:
        return "calibration upload nearby"
    if row["earthpv_changesets"]:
        return "other EarthPV upload"
    if elements:
        return "other solar edits"
    return "local edits, no solar elements" if row["local_changesets"] else "no activity seen"


def check_country(aoi: str, areas: list[dict], args, token: str | None,
                  campaign: dict[int, str] | None) -> list[dict]:
    rows = []
    for area in areas:
        row = dict.fromkeys(FIELDS, "")
        row.update(aoi=aoi, area_id=area["id"], name=area.get("name", ""), kind=area["kind"],
                   status=area.get("status", ""), area_km2=area.get("area_km2", ""))
        if area["since"] is not None:
            row["since"], row["since_basis"] = area["since"], area["since_basis"]
        if token is not None:
            fill_local(row, area, token, args, campaign)
            time.sleep(OSMCHA_PAUSE_S)
        rows.append(row)
    query = (f"[out:json][timeout:{QUERY_TIMEOUT_S}];"
             f"({bbox_clauses(areas)});out meta center;")
    base_time, elements = overpass(query, args.overpass_url, parse_current)
    time.sleep(args.pause)
    for area, row in zip(areas, rows):
        row["osm_data_time"] = base_time
        fill_elements(row, area, elements_in(area, elements), campaign)
    fill_removals([(area, row) for area, row in zip(areas, rows)
                   if needs_removal_check(area, row, args)], args)
    for row in rows:
        row["activity"] = classify(row)
    return rows


def report(rows: list[dict], out: Path) -> None:
    print(f"\n{len(rows)} areas written to {out}")
    for activity, count in Counter(row["activity"] for row in rows).most_common():
        print(f"  {count:4d}  {activity}")
    edited = [row for row in rows if row["kind"] != "candidate"
              and (row["added_since"] or row["changed_since"] or row["removed_since"])]
    if edited:
        print("\nRegistered areas edited inside their window (added/changed/removed):")
        for row in edited:
            removed = "not checked" if row["removed_since"] == "" else row["removed_since"]
            print(f"  {row['aoi']}/{row['area_id']}: {row['added_since']}/{row['changed_since']}"
                  f"/{removed} since {row['since'][:10]} ({row['since_basis']})")
    print("\n'no activity seen' means nothing was edited there. It does not mean no PV.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One row per calibration area: its OSM solar elements, the changesets "
                    "behind them, and what changed since registration. Read-only.")
    parser.add_argument("--aoi", action="append", help="country key; repeatable (default: all)")
    parser.add_argument("--area", action="append", help="area id; repeatable")
    parser.add_argument("--registered-only", action="store_true", help="leave candidates out")
    parser.add_argument("--since", help="YYYY-MM-DD: one change window for every area, "
                                        "candidates included (default: per area)")
    parser.add_argument("--window-days", type=int, default=90,
                        help="window for a registered area with no local snapshot (default 90)")
    parser.add_argument("--osmcha-since", default="2025-01-01",
                        help="oldest changeset in the per-area OSMCha search (default 2025-01-01)")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE,
                        help=f"file holding the OSMCha API key (default {DEFAULT_TOKEN_FILE})")
    parser.add_argument("--skip-osmcha", action="store_true",
                        help="no API key: leave the OSMCha columns blank")
    parser.add_argument("--check-all-removals", action="store_true",
                        help="look for removals in every area with a window, not only those "
                             "a small changeset has touched (heavier on Overpass)")
    parser.add_argument("--out", type=Path, help="CSV path (default "
                        "data/calibration_activity/activity_<UTC date>.csv)")
    parser.add_argument("--pause", type=float, default=5.0,
                        help="seconds between Overpass queries (default 5)")
    parser.add_argument("--overpass-url", default=OVERPASS_URL)
    parser.add_argument("--dry-run", action="store_true",
                        help="list the areas and their windows; no network, nothing written")
    args = parser.parse_args()
    for name in ("since", "osmcha_since"):
        value = getattr(args, name)
        if value:
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                parser.error(f"--{name.replace('_', '-')} must be YYYY-MM-DD, got {value!r}")
    if args.since:
        args.since = f"{args.since}T00:00:00Z"
    return args


def run(args) -> None:
    selected = load_areas(args)
    if args.dry_run:
        total = 0
        for aoi, areas in selected.items():
            for area in areas:
                total += 1
                print(f"{aoi}/{area['id']} [{area['kind']}] "
                      f"since={area['since'] or '-'} {area['since_basis']}")
        print(f"\n{total} areas; nothing fetched")
        return

    token = None if args.skip_osmcha else load_token(args.token_file)
    campaign = None
    if token is not None:
        campaign = campaign_changesets(token)
        print(f"OSMCha: {len(campaign)} changesets name the campaign", flush=True)
    else:
        print("OSMCha skipped: its columns stay blank (not 0).", flush=True)

    rows: list[dict] = []
    for aoi, areas in selected.items():
        started = time.time()
        rows += check_country(aoi, areas, args, token, campaign)
        print(f"{aoi}: {len(areas)} areas in {time.time() - started:.0f} s", flush=True)

    today = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    out = args.out or REPO / "data" / "calibration_activity" / f"activity_{today}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f"{out.name}.tmp")
    with partial.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    partial.replace(out)
    report(rows, out)


def main() -> None:
    args = parse_args()
    try:
        run(args)
    except ServiceFailure as exc:
        sys.exit(f"{exc}. Nothing was written. Try again later, or one country with --aoi.")


if __name__ == "__main__":
    main()
