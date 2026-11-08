#!/usr/bin/env python
"""Add what the installed PV generates per year to a published evidence atlas, without a rebuild.

`earthpv atlas` writes `totals.generation` on every page by itself, from the AOI's PVGIS probe
grid (`pv_capacity.irradiance_probes_path`: the density run's `irradiance_probes.csv`, which
`roof-potential` writes, else `data/irradiance_probes/<aoi>.csv`, fetched on a first build), and
the page's KPI strip shows it in place of the cell-coverage tile. This does the same for a page
already published: `atlas.generation_totals` on the page's own cells, so nothing but
`totals.generation` changes
(every other key is re-serialised byte for byte, checked before writing). `--fetch` queries
PVGIS for an AOI with no cached grid (`--n-probe` points over the page's cells, a few minutes)
and caches it under `data/irradiance_probes/`, where the next build finds it.

    pixi run python scripts/patch_atlas_generation.py docs/assets/interactive/*_evidence_atlas.html --fetch
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from patch_atlas_pose import DUMPS  # noqa: E402
from retemplate_atlas import aoi_of  # noqa: E402

from earthpv import pv_capacity  # noqa: E402
from earthpv.atlas import generation_totals  # noqa: E402

DATA_BLOCK = re.compile(r'(<script id="pv" type="application/json">)(.*?)(</script>)', re.S)


def probes_for(aoi: str, data: dict, fetch: bool, n_probe: int) -> pd.DataFrame | None:
    path = pv_capacity.irradiance_probes_path(aoi, ROOT / "data" / "predictions" / aoi / "density")
    if path is None and fetch:
        cols = data["cell_cols"]
        path = pv_capacity.fetch_irradiance_probes(
            aoi, [c[cols.index("lon0")] for c in data["cells"]],
            [c[cols.index("lat0")] for c in data["cells"]], n_probe=n_probe)
    return pd.read_csv(path) if path else None


def patch(html: str, aoi: str, fetch: bool, n_probe: int) -> tuple[str, dict | None]:
    block = DATA_BLOCK.search(html)
    data = json.loads(block.group(2))
    if json.dumps(data, **DUMPS) != block.group(2):
        raise ValueError("the data block does not re-serialise byte for byte")
    probes = probes_for(aoi, data, fetch, n_probe)
    gen = generation_totals(data, probes) if probes is not None else None
    if gen is None:
        return html, None
    data["totals"]["generation"] = gen
    new = block.group(1) + json.dumps(data, **DUMPS) + block.group(3)
    return html[:block.start()] + new + html[block.end():], gen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", nargs="+", type=Path)
    ap.add_argument("--fetch", action="store_true",
                    help="query PVGIS for an AOI with no cached probe grid")
    ap.add_argument("--n-probe", type=int, default=pv_capacity.DEFAULT_GENERATION_N_PROBE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for page in args.pages:
        aoi = aoi_of(page)
        html, gen = patch(page.read_text(), aoi, args.fetch, args.n_probe)
        if gen is None:
            print(f"{page}: no PVGIS probe grid for {aoi} (pass --fetch), unchanged")
            continue
        if not args.dry_run:
            page.write_text(html)
        print(f"{page}: {gen['gwh'] / 1000:.2f} TWh/yr at {gen['kwh_per_kwp']} kWh/kWp "
              f"({gen['n_probes']} probes){' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
