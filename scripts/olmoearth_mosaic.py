"""Read OlmoEarth v1.3 embeddings from Source Cooperative, chunk by chunk.

Ai2's annual embeddings (OlmoEarth-v1.3-Base over a calendar year of Sentinel-1,
Sentinel-2 and Landsat 8/9; OlmoEarth Artifact License) are a Zarr v3 store with one group
per UTM zone, `embeddings.zarr/utmNN/embeddings` of shape (time 2017-2025, band 128, y, x)
at 10 m, int8. Each shard is one year, all 128 bands, 2048 x 2048 pixels, holding
(1, 64, 256, 256) zstd inner chunks: bands 0-63 (a complete Matryoshka embedding on their
own) and 64-127 are separate chunks, so a 64-d read costs half. The shard index sits at
the end: two little-endian uint64 (offset, length) per inner chunk in C order over
(band block, row, col), then a 4-byte crc32c.

So one 256 x 256 tile costs one suffix request per shard for the index (2,052 bytes, cached)
and one range request per band block. Same approach and no new dependency as
`aef_mosaic.py` (pyarrow decompresses zstd); compressed chunks are cached on disk.

Grid: every zone is stored as EPSG:326NN with origin (0, 9,502,720) and 10 m pixels; a
southern location has a negative northing. A zone holds only its own 6-degree band, so an
area crossing a zone edge is read once per zone. As of the 2026-10-22 release 2023-2025 are
global and 2017-2022 cover selected countries.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import rasterio

BASE = "https://data.source.coop/olmoearth/olmoearth-v1-3-embeddings/embeddings.zarr"
YEARS = tuple(range(2017, 2026))
GSD = 10.0
SHARD, INNER = 2048, 256
PER = SHARD // INNER  # inner chunks per shard side
BLOCKS = 2  # band blocks of 64
NODATA = -128
CACHE = Path("/home/tobi/earthpv_data/olmoearth/chunks")
_UA = {"User-Agent": "earthpv-olmoearth-research/0.1"}  # source.coop 403s without one
_EMPTY = np.iinfo("u8").max

_local = threading.local()
_lock = threading.Lock()
_index: dict[tuple, np.ndarray] = {}
_zones: dict[int, dict] = {}


def zone_of(lon: float) -> int:
    return int((lon + 180) // 6) + 1


def epsg(zone: int) -> str:
    return f"EPSG:{32600 + zone}"


def _session():
    import requests

    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
        s.headers.update(_UA)
    return s


def _get(url: str, rng: str | None = None, tries: int = 6) -> bytes:
    for k in range(tries):
        try:
            r = _session().get(url, headers={"Range": rng} if rng else {}, timeout=120)
            if r.status_code == 404:
                return b""
            r.raise_for_status()
            return r.content
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))
    return b""


def zone_meta(zone: int) -> dict:
    """The zone group's affine transform and shape, cached on disk; checked against the
    layout this reader assumes."""
    with _lock:
        if zone in _zones:
            return _zones[zone]
    path = CACHE / "meta" / f"utm{zone:02d}.json"
    if not path.exists():
        g = json.loads(_get(f"{BASE}/utm{zone:02d}/zarr.json"))["attributes"]
        a = json.loads(_get(f"{BASE}/utm{zone:02d}/embeddings/zarr.json"))
        shard = a["codecs"][0]["configuration"]
        assert a["chunk_grid"]["configuration"]["chunk_shape"] == [1, 128, SHARD, SHARD], a
        assert shard["chunk_shape"] == [1, 64, INNER, INNER] and shard["index_location"] == "end"
        assert g["proj:code"] == epsg(zone), g["proj:code"]
        meta = {"transform": g["spatial:transform"], "shape": a["shape"]}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta))
    meta = json.loads(path.read_text())
    gsd, _, x0, _, neg_gsd, y0 = meta["transform"]
    assert gsd == GSD and neg_gsd == -GSD, meta
    meta["x0"], meta["y0"] = float(x0), float(y0)
    with _lock:
        _zones[zone] = meta
    return meta


def _shard_url(zone: int, t: int, sy: int, sx: int) -> str:
    return f"{BASE}/utm{zone:02d}/embeddings/c/{t}/0/{sy}/{sx}"


def _shard_index(zone: int, t: int, sy: int, sx: int) -> np.ndarray:
    key = (zone, t, sy, sx)
    with _lock:
        if key in _index:
            return _index[key]
    path = CACHE / "index" / f"{zone}_{t}_{sy}_{sx}.npy"
    n = BLOCKS * PER * PER
    idx = None
    if path.exists():
        try:
            idx = np.load(path)
        except ValueError:  # a truncated file from a killed run: fetch it again
            idx = None
    if idx is None or idx.shape != (n, 2):
        raw = _get(_shard_url(zone, t, sy, sx), f"bytes=-{n * 16 + 4}")
        idx = (np.frombuffer(raw[:-4], dtype="<u8").reshape(n, 2).copy()
               if raw else np.full((n, 2), _EMPTY, dtype="u8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic, as for chunks: worker threads share shards, and one must never read
        # another's half-written index.
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        with open(tmp, "wb") as f:
            np.save(f, idx)
        tmp.replace(path)
    with _lock:
        _index[key] = idx
    return idx


def _chunk_path(zone: int, year: int, block: int, cy: int, cx: int) -> Path:
    return CACHE / f"utm{zone:02d}" / str(year) / f"b{block}_{cy}_{cx}.zst"


def fetch(zone: int, year: int, block: int, cy: int, cx: int) -> int:
    """Make sure one inner chunk is cached; returns the bytes downloaded (0 if cached). An
    empty file marks a chunk the store does not have (no embedding computed there)."""
    path = _chunk_path(zone, year, block, cy, cx)
    if path.exists():
        return 0
    t = YEARS.index(year)
    sy, sx = cy // PER, cx // PER
    off, n = _shard_index(zone, t, sy, sx)[block * PER * PER + (cy % PER) * PER + (cx % PER)]
    raw = (b"" if n == _EMPTY
           else _get(_shard_url(zone, t, sy, sx), f"bytes={int(off)}-{int(off + n - 1)}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return len(raw)


def chunk(zone: int, year: int, cy: int, cx: int, dims: int = 128) -> np.ndarray | None:
    """(dims, 256, 256) int8 tile at global inner-chunk row/col, or None if empty."""
    import pyarrow as pa

    parts = []
    for b in range(dims // 64):
        fetch(zone, year, b, cy, cx)
        raw = _chunk_path(zone, year, b, cy, cx).read_bytes()
        if not raw:
            return None
        buf = pa.decompress(raw, decompressed_size=64 * INNER * INNER, codec="zstd")
        parts.append(np.frombuffer(buf, dtype=np.int8).reshape(64, INNER, INNER))
    return parts[0] if len(parts) == 1 else np.concatenate(parts)


def chunks_for_bounds(zone: int, minx, miny, maxx, maxy) -> list[tuple[int, int]]:
    """Inner-chunk (row, col) keys covering bounds in the zone's UTM CRS."""
    m = zone_meta(zone)
    c0, c1 = int((minx - m["x0"]) // GSD) // INNER, int((maxx - m["x0"]) // GSD) // INNER
    r0, r1 = int((m["y0"] - maxy) // GSD) // INNER, int((m["y0"] - miny) // GSD) // INNER
    return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


def chunk_transform(zone: int, cy: int, cx: int) -> rasterio.Affine:
    m = zone_meta(zone)
    return rasterio.Affine(GSD, 0.0, m["x0"] + cx * INNER * GSD,
                           0.0, -GSD, m["y0"] - cy * INNER * GSD)


def window(zone: int, year: int, minx, miny, maxx, maxy, dims: int = 128):
    """Int8 (dims, h, w) window covering UTM bounds in `zone`, and its transform."""
    m = zone_meta(zone)
    col0, col1 = int((minx - m["x0"]) // GSD), int((maxx - m["x0"]) // GSD) + 1
    row0, row1 = int((m["y0"] - maxy) // GSD), int((m["y0"] - miny) // GSD) + 1
    out = np.full((dims, row1 - row0, col1 - col0), NODATA, dtype=np.int8)
    for cy, cx in chunks_for_bounds(zone, minx, miny, maxx, maxy):
        a = chunk(zone, year, cy, cx, dims)
        if a is None:
            continue
        r_a, c_a = cy * INNER, cx * INNER
        rs, re_ = max(row0, r_a), min(row1, r_a + INNER)
        cs, ce = max(col0, c_a), min(col1, c_a + INNER)
        out[:, rs - row0:re_ - row0, cs - col0:ce - col0] = a[:, rs - r_a:re_ - r_a, cs - c_a:ce - c_a]
    transform = rasterio.Affine(GSD, 0.0, m["x0"] + col0 * GSD, 0.0, -GSD, m["y0"] - row0 * GSD)
    return out, transform


def prefetch(keys, workers: int = 6) -> int:
    """Fetch (zone, year, block, cy, cx) keys in parallel; returns bytes downloaded."""
    import logging
    from concurrent.futures import ThreadPoolExecutor

    log = logging.getLogger("olmoearth_mosaic")
    keys = [k for k in keys if not _chunk_path(*k).exists()]
    total, t0 = 0, time.time()
    with ThreadPoolExecutor(workers) as ex:
        for i, n in enumerate(ex.map(lambda k: fetch(*k), keys)):
            total += n
            if (i + 1) % 200 == 0:
                log.info("  fetched %d/%d chunks, %.1f GB, %.1f MB/s", i + 1, len(keys),
                         total / 1e9, total / 1e6 / max(time.time() - t0, 1))
    return total


def dequantize(v: np.ndarray) -> np.ndarray:
    f = v.astype("float32")
    out = np.sign(f) * (np.abs(f) / 127.5) ** 2
    out[v == NODATA] = np.nan
    return out
