#!/usr/bin/env python
"""A country's VIDA footprints inside a few boxes only, read from the remote file.

For a state run without its country: the United States' VIDA file is 20.5 GB (145M
footprints, Microsoft only), and California's and Texas's boxes hold 4.4 GB of it. The
file is spatially sorted (row groups about 0.1 x 0.06 degrees), so the `bbox` row-group
filter reads only those groups. Output keeps VIDA's schema and its 5,000-row groups, in the
source's order per box, so `scripts/fill_vida_from_osm.py` and every reader take it as the
whole file. A footprint belongs to the first box holding its `bbox.xmin, bbox.ymin` corner,
so overlapping boxes never write a footprint twice.

**The result is not the country.** Installed as `data/vida/<ISO3>.parquet`, it silently
holds nothing outside its boxes: a later AOI of the same country needs the file redone
with its box added. `<out>.json` records the boxes.

    python scripts/vida_subset.py --iso3 USA --box=-124.5,32.5,-114.1,42.1 \\
        --box=-106.7,25.8,-93.4,36.6 --out /home/tobi/earthpv_data/USA_california_texas.parquet
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from earthpv import overture  # noqa: E402
from earthpv.buildings import VIDA_URL  # noqa: E402

log = logging.getLogger("vida_subset")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso3", required=True)
    ap.add_argument("--box", action="append", required=True,
                    help="minlon,minlat,maxlon,maxlat (repeatable; write --box=-124.5,... )")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    boxes = [tuple(float(v) for v in b.split(",")) for b in a.box]
    url = VIDA_URL.format(iso3=a.iso3.upper())

    def inside(b) -> str:
        x0, y0, x1, y1 = b
        return (f"(bbox.xmin >= {x0} AND bbox.xmin <= {x1} "
                f"AND bbox.ymin >= {y0} AND bbox.ymin <= {y1})")

    # One scan per box keeps each a plain AND of struct-field bounds, which DuckDB pushes
    # into the parquet row-group statistics (an OR across boxes might not be).
    parts = []
    for k, b in enumerate(boxes):
        earlier = " AND ".join(f"NOT {inside(p)}" for p in boxes[:k])
        parts.append(f"SELECT * FROM read_parquet('{url}') WHERE {inside(b)}"
                     + (f" AND {earlier}" if earlier else ""))
    con = overture.connect()
    con.execute("SET preserve_insertion_order=true;")
    tmp = a.out.with_name(a.out.name + ".tmp")
    log.info("reading %d box(es) of %s into %s", len(boxes), url, a.out)
    con.execute(f"COPY ({' UNION ALL '.join(parts)}) TO '{tmp}' "
                "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 5000)")
    n = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
    if n == 0:
        log.error("no footprints inside the boxes; keeping %s for inspection", tmp)
        return 1
    os.replace(tmp, a.out)
    Path(str(a.out) + ".json").write_text(json.dumps(
        {"iso3": a.iso3.upper(), "source": url, "boxes": boxes, "rows": int(n)}, indent=1))
    log.info("%d footprints, %.2f GB", n, a.out.stat().st_size / 1e9)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
