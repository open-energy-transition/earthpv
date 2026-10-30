#!/usr/bin/env python
"""The median acquisition date of the Sentinel-2 scenes behind each evidence atlas.

**Why.** An atlas's composites span a window of months (`compose_window`, five to twelve
of them), while every figure it is compared against carries one date. The "Against
official and published figures" section therefore dates the atlas by the median date of
the scenes its composites were built from, with the middle half of those dates as the
spread (owner, 2026-10-29).

**The composites do not record their scenes**, only the window (`earthpv_window`, and not
even that before 2026-09-19). So the selection is reconstructed: for a random sample of
each AOI's composited cells, the same STAC search `imagery.annual_composite` makes
(Planetary Computer, `eo:cloud_cover` < `MAX_CLOUD`, the cell's own window), the same
ranking (`imagery._rank_items` for cells written after it shipped on `RANK_SINCE`, cloud
cover alone before), the same `MAX_ITEMS`, and the solar days of the scenes kept. Two
limits: scenes tied at the same cloud cover are kept in the catalogue's current order,
which can differ from the order at compose time, and a cell that fell over to Earth
Search is treated as if Planetary Computer had served it. Both move individual scenes
within the window, not the window itself.

The window per cell is its `earthpv_window` tag; an untagged cell takes `WINDOW_FALLBACK`
(a window passed on the command line, documented elsewhere), then the AOI's
`compose_window`, then `annual_composite`'s own default.

    pixi run python scripts/imagery_median_date.py                  # every atlas AOI
    pixi run python scripts/imagery_median_date.py --aoi pakistan --n 150
    EARTHPV_FORCE_IPV4=1 pixi run python scripts/imagery_median_date.py   # see below

Searches go through `compose._harden_python_network` with a 60 s socket timeout (a search
to Planetary Computer can hang on a dead IPv6 socket indefinitely; EARTHPV_FORCE_IPV4=1 is
the cure compose uses), are retried, and a cell that still fails is left out and counted.

Writes configs/atlas_imagery_dates.yaml, which `atlas.imagery_dates` puts into an atlas's
`totals.imagery_dates`; entries for AOIs not re-run are kept.
"""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "configs" / "atlas_imagery_dates.yaml"
ATLAS_AOIS = ["pakistan", "germany", "france", "india", "vietnam", "egypt", "yemen",
              "south_africa", "morocco", "poland", "zambia", "nigeria", "namibia"]
MAX_CLOUD = 60      # compose.py's call to annual_composite
MAX_ITEMS = 12      # annual_composite's default
RANK_SINCE = dt.date(2026, 10, 10)   # imagery._rank_items (coverage before cloud cover)
# Untagged composites whose window was passed on the command line.
WINDOW_FALLBACK = {
    # docs/results/germany.md: matched to the MaStR cutoff and the training imagery.
    "germany": ("2025-04-01", "2025-09-30"),
}


def default_window() -> tuple[str, str]:
    from earthpv.imagery import annual_composite

    return tuple(inspect.signature(annual_composite).parameters["date_range"].default)


def aoi_window(aoi: str) -> tuple[str, str]:
    if aoi in WINDOW_FALLBACK:
        return WINDOW_FALLBACK[aoi]
    cfg = yaml.safe_load((REPO / "configs" / "aoi.yaml").read_text())
    win = (cfg.get("aois") or cfg).get(aoi, {}).get("compose_window")
    return tuple(win) if win else default_window()


def cell_paths(aoi: str) -> list[Path]:
    root = REPO / "data" / "composites" / aoi / "composites"
    return sorted(Path(e.path) / "composite_0.tif" for e in os.scandir(root)
                  if (Path(e.path) / "composite_0.tif").exists())


def scene_days(path: Path, aoi: str, tries: int = 3) -> dict:
    for attempt in range(tries):
        try:
            return _scene_days(path, aoi)
        except Exception as err:  # noqa: BLE001 - a timeout or 5xx: retry, then give up
            last = err
    print(f"    {aoi} {path.parent.name}: failed {tries}x ({last})", flush=True)
    return {"cell": path.parent.name, "window": None, "days": [], "failed": True}


def _scene_days(path: Path, aoi: str) -> dict:
    import rasterio
    from rasterio.warp import transform_bounds

    from earthpv.imagery import _catalog, _rank_items

    with rasterio.open(path) as src:
        tags = src.tags()
        bbox = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    window = tuple(tags["earthpv_window"].split(":")) if "earthpv_window" in tags \
        else aoi_window(aoi)
    built = dt.date.fromtimestamp(path.stat().st_mtime)
    search = _catalog().search(collections=["sentinel-2-l2a"], bbox=bbox,
                               datetime=f"{window[0]}/{window[1]}",
                               query={"eo:cloud_cover": {"lt": MAX_CLOUD}})
    items = sorted(search.items(), key=lambda it: it.properties.get("eo:cloud_cover", 100))
    if built >= RANK_SINCE:
        items = _rank_items(items, bbox)
    days = sorted({it.datetime.date() for it in items[:MAX_ITEMS]})
    return {"cell": path.parent.name, "window": ":".join(window), "days": days}


def quantile_date(days: list[dt.date], q: float) -> dt.date:
    return dt.date.fromordinal(int(round(np.quantile([d.toordinal() for d in days], q))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aoi", action="append", help="repeatable; default every atlas AOI")
    ap.add_argument("--n", type=int, default=120, help="cells sampled per AOI")
    ap.add_argument("--seed", type=int, default=20261029)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    os.environ.setdefault("EARTHPV_NET_TIMEOUT_S", "60")
    from earthpv.compose import _harden_python_network

    _harden_python_network()

    doc = yaml.safe_load(a.out.read_text()) if a.out.exists() else {}
    entries = doc.get("aois", {}) if doc else {}
    for aoi in a.aoi or ATLAS_AOIS:
        cells = cell_paths(aoi)
        sample = random.Random(f"{a.seed}:{aoi}").sample(cells, min(a.n, len(cells)))
        with ThreadPoolExecutor(a.workers) as pool:
            rows = list(pool.map(lambda p: scene_days(p, aoi), sample))
        failed = sum(bool(r.get("failed")) for r in rows)
        rows = [r for r in rows if not r.get("failed")]
        days = [d for r in rows for d in r["days"]]
        empty = sum(not r["days"] for r in rows)
        if not days:
            print(f"  {aoi}: no scenes found in {len(rows)} cells, skipped")
            continue
        windows = sorted({r["window"] for r in rows if r["window"]})
        entries[aoi] = {
            "median": quantile_date(days, 0.5).isoformat(),
            "p25": quantile_date(days, 0.25).isoformat(),
            "p75": quantile_date(days, 0.75).isoformat(),
            "first": min(days).isoformat(),
            "last": max(days).isoformat(),
            "windows": windows,
            "n_cells": len(cells),
            "n_cells_sampled": len(rows),
            "n_cells_no_scene": empty,
            "n_cells_failed": failed,
            "n_scene_days": len(days),
            "made": dt.date.today().isoformat(),
        }
        e = entries[aoi]
        print(f"  {aoi:13s} median {e['median']}  middle half {e['p25']} to {e['p75']}  "
              f"({len(days)} scene-days, {len(rows)} of {len(cells)} cells, windows {windows}"
              + (f", {empty} cells with none" if empty else "")
              + (f", {failed} failed" if failed else "") + ")", flush=True)
        write(a.out, entries)
    return 0


def write(path: Path, entries: dict) -> None:
    """Rewrite the table after every AOI, so a stalled run keeps what it finished."""
    out = {
        "note": "Median acquisition date of the Sentinel-2 scenes behind each evidence atlas's "
                "composites, reconstructed from the STAC catalogue for a random sample of "
                "cells (scripts/imagery_median_date.py). p25/p75 bound the middle half.",
        "aois": dict(sorted(entries.items())),
    }
    path.write_text("# Written by scripts/imagery_median_date.py; do not edit by hand.\n"
                    + yaml.safe_dump(out, sort_keys=False, width=100))


if __name__ == "__main__":
    raise SystemExit(main())
