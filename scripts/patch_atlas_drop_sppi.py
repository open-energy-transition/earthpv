#!/usr/bin/env python
"""Take the retired roofclf+SPPI fields out of a published evidence atlas without rebuilding it.

The owner took SPPI out of the atlases on 2026-11-13: Verified is the hand-mapped capacity
alone, and neither the roofclf-AND-SPPI floor (`small_low`) nor its out-of-domain
extrapolation (`small_outdomain`, `is_extended`) is an input any more. A page whose floor was
non-zero (Pakistan's) changes figures and must be rebuilt with `earthpv atlas`; this refuses
it. On every other page those fields are zero, so dropping them changes no figure:

- the cells' `small_low`, `small_outdomain` and `is_extended` columns and their names in
  `cell_cols`;
- `totals.small_low`, `totals.small_outdomain`, `totals.n_extended_cells`;
- the provinces' `small_low` and `small_outdomain`, the size bins' `roof_extrapolated_mwp`;
- in `totals.uncertainty`: the two components, their coverage bootstraps,
  `mwp_best_ci_without_extrapolation` (equal to `mwp_best_ci` without an extrapolation) and
  `outdomain_extrapolation_ci90`.

Every other key is re-serialised byte for byte, which is checked before writing. The page's
`<stem>_capacity_by_cell.parquet`, where there is one, loses the same three columns. Run
`scripts/retemplate_atlas.py` on the page too, for the template that no longer draws them
(it reads cells by name, so it draws a page either way). Re-running is a no-op.

`--growth` does the same for Pakistan's growth atlas (`atlas.build_growth_atlas`), whose SPPI
onset view was corroboration only and never in a total: the cells' `n_onset_buildings`,
`onset_roof_area_km2` and `onset_mwp`, the provinces' `n_onset`, `onset_km2` and `onset_mwp`,
and the same three totals go, non-zero as they are.

    pixi run python scripts/patch_atlas_drop_sppi.py results/spain_pv_evidence_atlas.html ...
    pixi run python scripts/patch_atlas_drop_sppi.py --growth results/pakistan_pv_growth_atlas.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from patch_atlas_pose import DUMPS  # noqa: E402

DATA_BLOCK = re.compile(r'(<script id="pv" type="application/json">)(.*?)(</script>)', re.S)
CELL_COLS = ("small_low", "small_outdomain", "is_extended")
TOTALS = ("small_low", "small_outdomain", "n_extended_cells")
PROVINCE_KEYS = ("small_low", "small_outdomain")
COMPONENTS = ("small_low", "small_outdomain")
GROWTH_CELL_COLS = ("n_onset_buildings", "onset_roof_area_km2", "onset_mwp")
GROWTH_TOTALS = ("n_onset_buildings", "onset_km2", "onset_mwp")
GROWTH_PROVINCE_KEYS = ("n_onset", "onset_km2", "onset_mwp")


def _zero(where: str, value) -> None:
    if value not in (None, 0, 0.0, False):
        raise ValueError(f"{where} is {value!r}, not zero: rebuild this page with `earthpv atlas` "
                         "instead, its figures change")


def _load(html: str):
    block = DATA_BLOCK.search(html)
    if block is None:
        raise ValueError("no atlas data block")
    data = json.loads(block.group(2))
    if json.dumps(data, **DUMPS) != block.group(2):
        raise ValueError("the data block does not re-serialise byte for byte")
    return block, data


def patch_growth(html: str) -> tuple[str, int]:
    """The growth atlas without its SPPI onset fields, and how many keys or columns went."""
    block, data = _load(html)
    n = 0
    cols = data.get("cell_cols") or []
    drop = [i for i, c in enumerate(cols) if c in GROWTH_CELL_COLS]
    if drop:
        keep = [i for i in range(len(cols)) if i not in drop]
        data["cells"] = [[row[i] for i in keep] for row in data["cells"]]
        data["cell_cols"] = [cols[i] for i in keep]
        n += len(drop)
    for k in GROWTH_TOTALS:
        if k in data["totals"]:
            data["totals"].pop(k)
            n += 1
    for p in data.get("provinces") or []:
        for k in GROWTH_PROVINCE_KEYS:
            if k in p:
                p.pop(k)
                n += 1
    new = block.group(1) + json.dumps(data, **DUMPS) + block.group(3)
    return html[:block.start()] + new + html[block.end():], n


def patch(html: str) -> tuple[str, int]:
    """The page without the retired fields, and how many keys or columns went."""
    block, data = _load(html)
    n = 0

    cols = data.get("cell_cols") or []
    drop = [i for i, c in enumerate(cols) if c in CELL_COLS]
    if drop:
        for row in data["cells"]:
            for i in drop:
                _zero(f"cell {row[0]},{row[1]} {cols[i]}", row[i])
        keep = [i for i in range(len(cols)) if i not in drop]
        data["cells"] = [[row[i] for i in keep] for row in data["cells"]]
        data["cell_cols"] = [cols[i] for i in keep]
        n += len(drop)

    t = data["totals"]
    for k in TOTALS:
        if k in t:
            _zero(f"totals.{k}", t.pop(k))
            n += 1
    for p in data.get("provinces") or []:
        for k in PROVINCE_KEYS:
            if k in p:
                _zero(f"province {p.get('name')} {k}", p.pop(k))
                n += 1
    for b in data.get("bins") or []:
        if "roof_extrapolated_mwp" in b:
            _zero(f"bin {b.get('label')} roof_extrapolated_mwp", b.pop("roof_extrapolated_mwp"))
            n += 1

    u = t.get("uncertainty") or {}
    comps = u.get("components") or {}
    for k in COMPONENTS:
        if k in comps:
            _zero(f"uncertainty component {k}", comps.pop(k).get("mwp"))
            n += 1
    for k in COMPONENTS:
        if k in (u.get("coverage_bootstrap") or {}):
            u["coverage_bootstrap"].pop(k)
            n += 1
    missing = u.get("coverage_bootstrap_missing") or []
    if any(m in COMPONENTS for m in missing):
        u["coverage_bootstrap_missing"] = [m for m in missing if m not in COMPONENTS]
        n += 1
    if "mwp_best_ci_without_extrapolation" in u:
        if u["mwp_best_ci_without_extrapolation"] != u.get("mwp_best_ci"):
            raise ValueError("mwp_best_ci_without_extrapolation differs from mwp_best_ci: "
                             "this page carries an extrapolation; rebuild it")
        u.pop("mwp_best_ci_without_extrapolation")
        n += 1
    if "outdomain_extrapolation_ci90" in u:
        u.pop("outdomain_extrapolation_ci90")
        n += 1

    new = block.group(1) + json.dumps(data, **DUMPS) + block.group(3)
    return html[:block.start()] + new + html[block.end():], n


def patch_parquet(page: Path, growth: bool = False) -> bool:
    import geopandas as gpd

    pq = page.with_name(page.stem + "_capacity_by_cell.parquet")
    if not pq.exists():
        return False
    gdf = gpd.read_parquet(pq)
    drop = [c for c in (GROWTH_CELL_COLS if growth else CELL_COLS) if c in gdf.columns]
    if not drop:
        return False
    for c in drop:
        if not growth and (gdf[c].fillna(0) != 0).any():
            raise ValueError(f"{pq.name}: {c} is not zero everywhere")
    gdf.drop(columns=drop).to_parquet(pq)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pages", nargs="+", type=Path)
    ap.add_argument("--growth", action="store_true",
                    help="the growth atlas's SPPI onset fields instead of an evidence atlas's")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for page in args.pages:
        new, n = (patch_growth if args.growth else patch)(page.read_text())
        if args.dry_run:
            print(f"{page}: would drop {n} keys/columns")
            continue
        if n:
            page.write_text(new)
        pq = patch_parquet(page, growth=args.growth)
        print(f"{page}: dropped {n} keys/columns" + (", parquet too" if pq else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
