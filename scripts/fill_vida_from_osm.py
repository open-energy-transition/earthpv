#!/usr/bin/env python
"""Fill the holes in a country's VIDA footprints with OpenStreetMap buildings.

VIDA is not complete everywhere it claims to cover. Measured on Spain 2026-11-02: 6.4M
footprints, 3,022 of the 5,803 cells touching the country empty, and zero footprints in a
3 x 3 km box around the centre of Seville (OSM has 9,924 there), Valencia, Malaga, Cordoba,
Granada, Almeria, Huelva, Alicante and Castellon. Every footprint consumer reads the one
file `data/vida/<ISO3>.parquet`, so a hole there is not one defect but three:

  - compose's cell selection never images a city it counts zero buildings in;
  - a rooftop array that is imaged reads as `no_building`, which prices it at the ground
    land constant (about 3.6x below the module constant) and exposes it to the
    low-confidence lead screen;
  - a mapped generator polygon there cannot be classified rooftop by overlap.

The fix writes a second file with VIDA's own schema, so nothing downstream changes:

  - **every VIDA row is kept, unchanged**;
  - an OSM building is added only if its 0.01 degree block (about 1 km) holds no VIDA
    footprint at all. A block takes its buildings from one source, so nothing is counted
    twice. A place where VIDA is present but incomplete is deliberately left alone.

Added rows carry `bf_source = 'osm'` and a NULL `confidence`, which every reader already
handles (`bf_confidence` is empty outside Pakistan). Rows are clustered by 0.05 degree block
in row groups of 5,000, like VIDA's own, so `bbox` row-group pruning still works.

This script never touches `data/vida/`: installing the result is a separate, reversible
step (repoint the symlink). `compose`'s cell cache keys on the file's size and mtime, so it
recomputes by itself after that.

    python scripts/fill_vida_from_osm.py --iso3 ESP \\
        --vida /home/tobi/earthpv_data/ESP.parquet \\
        --pbf /home/tobi/earthpv_data/geofabrik/spain_20261102/spain-latest.osm.pbf \\
        --out /home/tobi/earthpv_data/ESP_vida_osmfill.parquet \\
        --osmium /run/media/tobi/aidisc/subdetect/.pixi/envs/default/bin/osmium
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

log = logging.getLogger("fill_vida_from_osm")

BLOCK_DEG = 0.01  # a block with any VIDA footprint keeps VIDA alone
CLUSTER_PER_DEG = 20  # output row order, 0.05 degree blocks
# Per-building rules (--rule building / osm-first): see conflate_per_building.
OVERLAP = 0.3  # intersection share of either outline that makes two outlines one building
TILE_DEG = 0.1  # work unit
PAD_DEG = 0.003  # ~300 m: primary outlines reaching this far past a tile are compared
# building=* values that do not describe a standing roof.
NOT_A_BUILDING = ("no", "proposed", "construction", "demolished", "razed", "ruins", "collapsed")


def export_buildings(pbf: Path, work: Path, osmium: str) -> Path:
    """OSM building polygons as one GeoJSON feature per line, with only the building tag."""
    filtered = work / "buildings.osm.pbf"
    out = work / "buildings.geojsonl"
    config = work / "export.json"
    config.write_text(json.dumps({
        "attributes": {k: False for k in (
            "type", "id", "version", "changeset", "timestamp", "uid", "user", "way_nodes")},
        "linear_tags": False,
        "area_tags": True,
        "exclude_tags": [],
        "include_tags": ["building"],
    }))
    log.info("osmium tags-filter %s", pbf)
    subprocess.run([osmium, "tags-filter", str(pbf), "a/building", "-o", str(filtered),
                    "--overwrite"], check=True)
    log.info("osmium export -> %s", out)
    subprocess.run([osmium, "export", str(filtered), "-c", str(config), "-f", "geojsonseq",
                    "--geometry-types=polygon", "--format-option=print_record_separator=false",
                    "-o", str(out), "--overwrite"], check=True)
    filtered.unlink()
    return out


def conflate_per_building(con, a, geojson: Path, work: Path) -> int:
    """`--rule building` / `--rule osm-first`: conflate building by building, not by block.

    The block rule leaves VIDA alone wherever a block holds one VIDA footprint, so it cannot
    repair VIDA that is present but incomplete: Belgium's OSM holds 1.68x VIDA's buildings and
    the block rule added 0.6%. Here one source is primary (VIDA for `building`, OSM for
    `osm-first`) and keeps every row; a building from the other source is added unless it is
    the same building as a primary one. Two outlines are the same building when their
    intersection covers at least `--overlap` of EITHER outline, which catches the three ways
    the sources disagree on one roof: a merged VIDA block over several OSM houses (covers each
    house whole), an undersized VIDA outline inside an OSM house (covered whole itself), and
    a 1-3 m misregistration (most of both). Slivers between neighbours stay below the share.

    Work runs per 0.1 degree tile of the secondary source's outline centres against every
    primary outline whose bbox reaches within PAD_DEG of the tile, so a building that
    straddles a tile edge is still compared with its duplicate. Output has VIDA's schema,
    rows from OSM carry `bf_source = 'osm'` and a NULL `confidence`, as the block rule's do.
    """
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    import shapely

    skip = ", ".join(f"'{v}'" for v in NOT_A_BUILDING)
    vida = f"read_parquet('{a.vida}')"
    osm_t = work / "osm_tiled.parquet"
    vida_t = work / "vida_tiled.parquet"
    tile = f"CAST(floor(((xmin + xmax) / 2) / {TILE_DEG}) AS BIGINT)"
    tiley = f"CAST(floor(((ymin + ymax) / 2) / {TILE_DEG}) AS BIGINT)"
    log.info("tiling OSM buildings -> %s", osm_t)
    con.execute(f"""
        COPY (
            SELECT row_number() OVER () AS rid, ST_AsWKB(g) AS wkb, xmin, ymin, xmax, ymax,
                   {tile} AS tx, {tiley} AS ty
            FROM (
                SELECT g, ST_XMin(g) AS xmin, ST_YMin(g) AS ymin, ST_XMax(g) AS xmax,
                       ST_YMax(g) AS ymax
                FROM (
                    SELECT ST_GeomFromGeoJSON(geometry) AS g
                    FROM read_ndjson('{geojson}',
                                     columns = {{'geometry': 'JSON', 'properties': 'STRUCT(building VARCHAR)'}},
                                     maximum_object_size = 134217728)
                    WHERE properties.building NOT IN ({skip})
                )
            )
            ORDER BY tx, ty
        ) TO '{osm_t}' (FORMAT parquet, ROW_GROUP_SIZE 20000)
    """)
    log.info("tiling VIDA footprints -> %s", vida_t)
    con.execute(f"""
        COPY (
            SELECT row_number() OVER () AS rid, ST_AsWKB(geometry) AS wkb,
                   boundary_id, bf_source, confidence, area_in_meters, s2_id, country_iso,
                   geohash, bbox,
                   bbox.xmin AS xmin, bbox.ymin AS ymin, bbox.xmax AS xmax, bbox.ymax AS ymax,
                   CAST(floor(((bbox.xmin + bbox.xmax) / 2) / {TILE_DEG}) AS BIGINT) AS tx,
                   CAST(floor(((bbox.ymin + bbox.ymax) / 2) / {TILE_DEG}) AS BIGINT) AS ty
            FROM {vida}
            ORDER BY tx, ty
        ) TO '{vida_t}' (FORMAT parquet, ROW_GROUP_SIZE 20000)
    """)
    n_osm = con.execute(f"SELECT count(*) FROM read_parquet('{osm_t}')").fetchone()[0]
    n_vida = con.execute(f"SELECT count(*) FROM read_parquet('{vida_t}')").fetchone()[0]
    primary, secondary = (vida_t, osm_t) if a.rule == "building" else (osm_t, vida_t)
    tiles = con.execute(
        f"SELECT DISTINCT tx, ty FROM read_parquet('{secondary}') ORDER BY tx, ty").fetchall()
    log.info("%s: %d OSM, %d VIDA; comparing %d tiles", a.rule, n_osm, n_vida, len(tiles))

    keep_rids: list[np.ndarray] = []
    n_dup = 0
    for k, (tx, ty) in enumerate(tiles):
        x0, y0 = tx * TILE_DEG, ty * TILE_DEG
        sec = con.execute(f"""
            SELECT rid, wkb FROM read_parquet('{secondary}') WHERE tx = {tx} AND ty = {ty}
        """).fetch_arrow_table()
        pri = con.execute(f"""
            SELECT wkb FROM read_parquet('{primary}')
            WHERE tx BETWEEN {tx - 1} AND {tx + 1} AND ty BETWEEN {ty - 1} AND {ty + 1}
              AND xmax >= {x0 - PAD_DEG} AND xmin <= {x0 + TILE_DEG + PAD_DEG}
              AND ymax >= {y0 - PAD_DEG} AND ymin <= {y0 + TILE_DEG + PAD_DEG}
        """).fetch_arrow_table()
        rid = sec.column("rid").to_numpy()
        if pri.num_rows == 0:
            keep_rids.append(rid)
            continue
        sg = shapely.make_valid(shapely.from_wkb(sec.column("wkb").to_numpy(zero_copy_only=False)))
        pg = shapely.make_valid(shapely.from_wkb(pri.column("wkb").to_numpy(zero_copy_only=False)))
        i, j = shapely.STRtree(pg).query(sg, predicate="intersects")
        dup = np.zeros(len(sg), dtype=bool)
        if len(i):
            inter = shapely.area(shapely.intersection(sg[i], pg[j]))
            same = (inter >= a.overlap * shapely.area(sg)[i]) | (inter >= a.overlap * shapely.area(pg)[j])
            dup[i[same]] = True
        n_dup += int(dup.sum())
        keep_rids.append(rid[~dup])
        if (k + 1) % 100 == 0:
            log.info("%d/%d tiles, %d duplicates so far", k + 1, len(tiles), n_dup)

    kept = np.concatenate(keep_rids) if keep_rids else np.zeros(0, dtype=np.int64)
    kept_path = work / "kept_rids.parquet"
    pq.write_table(pa.table({"rid": pa.array(kept, type=pa.int64())}), kept_path)
    n_add = len(kept)

    osm_rows = """
        SELECT NULL::BIGINT AS boundary_id, 'osm' AS bf_source, NULL::DOUBLE AS confidence,
               ST_Area_Spheroid(ST_FlipCoordinates(ST_GeomFromWKB(wkb))) AS area_in_meters,
               NULL::BIGINT AS s2_id, '{iso3}' AS country_iso, NULL::VARCHAR AS geohash,
               ST_GeomFromWKB(wkb) AS geometry,
               {{'xmin': xmin, 'ymin': ymin, 'xmax': xmax, 'ymax': ymax}} AS bbox
        FROM read_parquet('{path}') o {where}
    """
    cols = "boundary_id, bf_source, confidence, area_in_meters, s2_id, country_iso, geohash, geometry, bbox"
    if a.rule == "building":
        body = f"""
            SELECT {cols} FROM {vida}
            UNION ALL
            {osm_rows.format(iso3=a.iso3, path=osm_t,
                             where=f"SEMI JOIN read_parquet('{kept_path}') k ON o.rid = k.rid")}
        """
        expect = n_vida + n_add
    else:
        # VIDA's own columns for the kept rows, carried in the tiled copy under its rid.
        body = f"""
            {osm_rows.format(iso3=a.iso3, path=osm_t, where="")}
            UNION ALL
            SELECT boundary_id, bf_source, confidence, area_in_meters, s2_id, country_iso,
                   geohash, ST_GeomFromWKB(wkb) AS geometry, bbox
            FROM read_parquet('{vida_t}') v
            SEMI JOIN read_parquet('{kept_path}') k ON v.rid = k.rid
        """
        expect = n_osm + n_add
    tmp = a.out.with_name(a.out.name + ".tmp")
    log.info("writing %s", a.out)
    con.execute(f"""
        COPY (
            SELECT {cols} FROM ({body})
            ORDER BY floor(((bbox.ymin + bbox.ymax) / 2) * {CLUSTER_PER_DEG}),
                     floor(((bbox.xmin + bbox.xmax) / 2) * {CLUSTER_PER_DEG})
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 5000)
    """)
    got = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
    if got != expect:
        log.error("wrote %d rows, expected %d; keeping %s for inspection", got, expect, tmp)
        return 1
    os.replace(tmp, a.out)
    report = {
        "iso3": a.iso3, "rule": a.rule, "overlap": a.overlap, "vida": str(a.vida),
        "pbf": str(a.pbf), "vida_rows": n_vida, "osm_buildings": n_osm,
        "primary": "vida" if a.rule == "building" else "osm",
        "secondary_added": n_add, "secondary_duplicates": n_dup, "rows": got,
    }
    a.out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    log.info("FILL_OK %s", json.dumps(report))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--iso3", required=True)
    ap.add_argument("--vida", type=Path, required=True, help="the country's raw VIDA parquet")
    ap.add_argument("--pbf", type=Path, required=True, help="Geofabrik extract of the country")
    ap.add_argument("--out", type=Path, required=True, help="filled parquet to write")
    ap.add_argument("--osmium", default=shutil.which("osmium") or "osmium")
    ap.add_argument("--memory", default="6GB", help="DuckDB memory limit")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--keep-work", action="store_true", help="keep the intermediate GeoJSON")
    ap.add_argument("--rule", choices=("block", "building", "osm-first"), default="block",
                    help="block (default, the published fills): OSM only in 0.01 degree blocks "
                         "with no VIDA. building: every VIDA row plus each OSM building that "
                         "duplicates no VIDA footprint. osm-first: every OSM building plus each "
                         "VIDA footprint that duplicates no OSM building (DBSM/Overture order)")
    ap.add_argument("--overlap", type=float, default=OVERLAP,
                    help="per-building rules: a pair is the same building when their "
                         "intersection covers at least this share of either outline")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from earthpv import overture

    work = a.out.parent / f".{a.out.stem}_work"
    work.mkdir(parents=True, exist_ok=True)
    geojson = work / "buildings.geojsonl"
    if not geojson.exists() or geojson.stat().st_size == 0:
        geojson = export_buildings(a.pbf, work, a.osmium)
    else:
        log.info("reusing %s", geojson)

    con = overture.connect()
    con.execute(f"SET memory_limit='{a.memory}'")
    con.execute(f"SET threads={a.threads}")
    con.execute(f"SET temp_directory='{work / 'duckdb_tmp'}'")

    if a.rule != "block":
        rc = conflate_per_building(con, a, geojson, work)
        if rc == 0 and not a.keep_work:
            shutil.rmtree(work)
        return rc

    skip = ", ".join(f"'{v}'" for v in NOT_A_BUILDING)
    centre = "((xmin + xmax) / 2)"
    middle = "((ymin + ymax) / 2)"
    log.info("reading OSM buildings")
    con.execute(f"""
        CREATE TEMP TABLE osm AS
        SELECT g, xmin, ymin, xmax, ymax,
               CAST(floor({centre} / {BLOCK_DEG}) AS BIGINT) AS bx,
               CAST(floor({middle} / {BLOCK_DEG}) AS BIGINT) AS by_
        FROM (
            SELECT g, ST_XMin(g) AS xmin, ST_YMin(g) AS ymin, ST_XMax(g) AS xmax, ST_YMax(g) AS ymax
            FROM (
                SELECT ST_GeomFromGeoJSON(geometry) AS g
                FROM read_ndjson('{geojson}',
                                 columns = {{'geometry': 'JSON', 'properties': 'STRUCT(building VARCHAR)'}},
                                 maximum_object_size = 134217728)
                WHERE properties.building NOT IN ({skip})
            )
        )
    """)
    n_osm = con.execute("SELECT count(*) FROM osm").fetchone()[0]
    log.info("%d OSM buildings", n_osm)

    vida = f"read_parquet('{a.vida}')"
    con.execute(f"""
        CREATE TEMP TABLE vida_blocks AS
        SELECT DISTINCT
               CAST(floor(((bbox.xmin + bbox.xmax) / 2) / {BLOCK_DEG}) AS BIGINT) AS bx,
               CAST(floor(((bbox.ymin + bbox.ymax) / 2) / {BLOCK_DEG}) AS BIGINT) AS by_
        FROM {vida}
    """)
    n_vida = con.execute(f"SELECT count(*) FROM {vida}").fetchone()[0]
    n_blocks = con.execute("SELECT count(*) FROM vida_blocks").fetchone()[0]
    con.execute("""
        CREATE TEMP TABLE fill AS
        SELECT o.* FROM osm o ANTI JOIN vida_blocks v ON o.bx = v.bx AND o.by_ = v.by_
    """)
    n_fill = con.execute("SELECT count(*) FROM fill").fetchone()[0]
    n_fill_blocks = con.execute("SELECT count(*) FROM (SELECT DISTINCT bx, by_ FROM fill)").fetchone()[0]
    log.info("%d VIDA rows in %d blocks; adding %d of %d OSM buildings in %d empty blocks",
             n_vida, n_blocks, n_fill, n_osm, n_fill_blocks)
    con.execute("DROP TABLE osm")

    tmp = a.out.with_name(a.out.name + ".tmp")
    log.info("writing %s", a.out)
    con.execute(f"""
        COPY (
            SELECT boundary_id, bf_source, confidence, area_in_meters, s2_id, country_iso,
                   geohash, geometry, bbox
            FROM (
                SELECT boundary_id, bf_source, confidence, area_in_meters, s2_id, country_iso,
                       geohash, geometry, bbox
                FROM {vida}
                UNION ALL
                SELECT NULL::BIGINT, 'osm', NULL::DOUBLE,
                       ST_Area_Spheroid(ST_FlipCoordinates(g)), NULL::BIGINT, '{a.iso3}',
                       NULL::VARCHAR, g,
                       {{'xmin': xmin, 'ymin': ymin, 'xmax': xmax, 'ymax': ymax}}
                FROM fill
            )
            ORDER BY floor(((bbox.ymin + bbox.ymax) / 2) * {CLUSTER_PER_DEG}),
                     floor(((bbox.xmin + bbox.xmax) / 2) * {CLUSTER_PER_DEG})
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 5000)
    """)
    got = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
    if got != n_vida + n_fill:
        log.error("wrote %d rows, expected %d; keeping %s for inspection", got, n_vida + n_fill, tmp)
        return 1
    os.replace(tmp, a.out)

    report = {
        "iso3": a.iso3, "vida": str(a.vida), "pbf": str(a.pbf), "block_deg": BLOCK_DEG,
        "vida_rows": n_vida, "vida_blocks": n_blocks, "osm_buildings": n_osm,
        "osm_added": n_fill, "blocks_filled": n_fill_blocks, "rows": got,
    }
    a.out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    log.info("FILL_OK %s", json.dumps(report))
    if not a.keep_work:
        shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
