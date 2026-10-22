"""Read AlphaEarth embeddings from the Source Cooperative Zarr mosaic, chunk by chunk.

The COG mirror (`tge-labs/aef/v1/annual`) stores each of the 64 bands in its own 1024 x
1024 block, so any read, however small, costs ~38 MB per year: fine for 30 contiguous
quadrats, ruinous for a few thousand objects scattered across a country. The Zarr mosaic
(`tge-labs/aef-mosaic/embeddings`, EPSG:4326 at 1/11132 deg, 2017-2025) shards the same data
into 4096 x 4096 shards of (1, 64, 256, 256) inner chunks, ~2.5 MB each, and a shard's index
sits at its end. So one object costs one suffix range request for the index (4,100 bytes,
cached per shard) plus one range request per inner chunk it touches.

No zarr or zstandard dependency: the index is two little-endian uint64 per inner chunk, and
pyarrow (already a dependency) decompresses zstd. Compressed chunks are cached on disk, so a
re-run never refetches.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import rasterio

BASE = "https://data.source.coop/tge-labs/aef-mosaic/embeddings/c"
YEARS = tuple(range(2017, 2026))
GSD = 0.00008983111749910169
X0, Y0 = -180.0, 83.68570533713473
SHARD, INNER = 4096, 256
PER = SHARD // INNER
NODATA = -128
CACHE = Path("/home/tobi/earthpv_data/aef/mosaic_chunks")
_UA = {"User-Agent": "earthpv-aef-research/0.1"}  # source.coop 403s without one

_local = threading.local()
_index_lock = threading.Lock()
_index: dict[tuple, np.ndarray] = {}


def _session():
    import requests

    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = requests.Session()
        s.headers.update(_UA)
    return s


def _get(url: str, rng: str, tries: int = 6) -> bytes:
    for k in range(tries):
        try:
            r = _session().get(url, headers={"Range": rng}, timeout=120)
            if r.status_code == 404:
                return b""
            r.raise_for_status()
            return r.content
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))
    return b""


def _shard_index(t: int, sy: int, sx: int) -> np.ndarray | None:
    key = (t, sy, sx)
    with _index_lock:
        if key in _index:
            return _index[key]
    path = CACHE / "index" / f"{t}_{sy}_{sx}.npy"
    if path.exists():
        idx = np.load(path)
    else:
        raw = _get(f"{BASE}/{t}/0/{sy}/{sx}", f"bytes=-{PER * PER * 16 + 4}")
        idx = (np.frombuffer(raw[:-4], dtype="<u8").reshape(PER * PER, 2).copy()
               if raw else np.full((PER * PER, 2), np.iinfo("u8").max, dtype="u8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, idx)
    with _index_lock:
        _index[key] = idx
    return idx


def fetch(year: int, cy: int, cx: int) -> int:
    """Make sure one inner chunk is cached on disk; returns the bytes downloaded (0 if it
    was already cached). An empty file marks a chunk the mosaic does not have."""
    path = CACHE / str(year) / f"{cy}_{cx}.zst"
    if path.exists():
        return 0
    t = YEARS.index(year)
    sy, sx = cy // PER, cx // PER
    off, n = _shard_index(t, sy, sx)[(cy % PER) * PER + (cx % PER)]
    raw = (b"" if n == np.iinfo("u8").max
           else _get(f"{BASE}/{t}/0/{sy}/{sx}", f"bytes={int(off)}-{int(off + n - 1)}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return len(raw)


def chunk(year: int, cy: int, cx: int) -> np.ndarray | None:
    """(64, 256, 256) int8 inner chunk at global inner-chunk row/col, or None if empty."""
    import pyarrow as pa

    fetch(year, cy, cx)
    raw = (CACHE / str(year) / f"{cy}_{cx}.zst").read_bytes()
    if not raw:
        return None
    buf = pa.decompress(raw, decompressed_size=64 * INNER * INNER, codec="zstd")
    return np.frombuffer(buf, dtype=np.int8).reshape(64, INNER, INNER)


def chunks_for_bounds(minx, miny, maxx, maxy) -> list[tuple[int, int]]:
    c0, c1 = int((minx - X0) / GSD) // INNER, int((maxx - X0) / GSD) // INNER
    r0, r1 = int((Y0 - maxy) / GSD) // INNER, int((Y0 - miny) / GSD) // INNER
    return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


def window(year: int, minx, miny, maxx, maxy, chunk_fn=chunk):
    """Int8 (64, h, w) mosaic window covering the bounds (EPSG:4326), and its transform."""
    col0, col1 = int((minx - X0) / GSD), int((maxx - X0) / GSD) + 1
    row0, row1 = int((Y0 - maxy) / GSD), int((Y0 - miny) / GSD) + 1
    out = np.full((64, row1 - row0, col1 - col0), NODATA, dtype=np.int8)
    for cy, cx in chunks_for_bounds(minx, miny, maxx, maxy):
        a = chunk_fn(year, cy, cx)
        if a is None:
            continue
        r_a, c_a = cy * INNER, cx * INNER
        rs, re_ = max(row0, r_a), min(row1, r_a + INNER)
        cs, ce = max(col0, c_a), min(col1, c_a + INNER)
        out[:, rs - row0:re_ - row0, cs - col0:ce - col0] = a[:, rs - r_a:re_ - r_a, cs - c_a:ce - c_a]
    transform = rasterio.Affine(GSD, 0.0, X0 + col0 * GSD, 0.0, -GSD, Y0 - row0 * GSD)
    return out, transform


def dequantize(v: np.ndarray) -> np.ndarray:
    f = v.astype("float32")
    out = np.sign(f) * (f / 127.5) ** 2
    out[v == NODATA] = np.nan
    return out
