"""Download one large HTTP file as parallel byte ranges, resumable, with per-chunk retries.

A single long-lived curl stream from source.coop degrades on this connection (measured
2026-09-23: 18 KB/s on the live stream while a fresh range request got 1.5 MB/s, and the
HTTP/2 resets are not covered by curl's own --retry). Fixed-size chunks fetched by a small
thread pool keep every connection short, so a slow or reset one costs one chunk rather
than the whole file.

Resumable: finished chunks are recorded in `<dest>.part.done` and skipped on a rerun.
The file is renamed into place only once every chunk has landed and the size matches.

    python scripts/ranged_download.py <url> <dest> [--workers 6] [--chunk-mb 32]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys
import threading
import time

import requests

UA = "earthpv-new-region/1.0 (research tool; contact via repo issues)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("dest")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--chunk-mb", type=int, default=32)
    ap.add_argument("--retries", type=int, default=30)
    a = ap.parse_args()

    head = requests.head(a.url, headers={"User-Agent": UA}, timeout=60, allow_redirects=True)
    head.raise_for_status()
    size = int(head.headers["Content-Length"])
    chunk = a.chunk_mb * 1024 * 1024
    n_chunks = (size + chunk - 1) // chunk
    part, done_path = a.dest + ".part", a.dest + ".part.done"
    if not os.path.exists(part) or os.path.getsize(part) != size:
        with open(part, "wb") as f:
            f.truncate(size)
        if os.path.exists(done_path):
            os.remove(done_path)
    done = set()
    if os.path.exists(done_path):
        done = {int(x) for x in open(done_path).read().split()}
    todo = [i for i in range(n_chunks) if i not in done]
    print(f"{size} bytes, {n_chunks} chunks, {len(todo)} to fetch", flush=True)
    lock = threading.Lock()
    t0, fetched = time.time(), [0]

    def fetch(i: int) -> None:
        lo, hi = i * chunk, min(size, (i + 1) * chunk) - 1
        for attempt in range(1, a.retries + 1):
            try:
                r = requests.get(a.url, headers={"User-Agent": UA, "Range": f"bytes={lo}-{hi}"},
                                 timeout=(30, 120))
                r.raise_for_status()
                body = r.content
                if len(body) != hi - lo + 1:
                    raise OSError(f"short chunk {len(body)} != {hi - lo + 1}")
                with open(part, "r+b") as f:
                    f.seek(lo)
                    f.write(body)
                with lock:
                    with open(done_path, "a") as d:
                        d.write(f"{i}\n")
                    fetched[0] += len(body)
                return
            except Exception as e:  # noqa: BLE001 - retried, then fatal
                print(f"chunk {i} attempt {attempt} failed: {e}", flush=True)
                time.sleep(min(60, 5 * attempt))
        raise RuntimeError(f"chunk {i} failed after {a.retries} attempts")

    last = time.time()
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(fetch, i) for i in todo]
        for k, fut in enumerate(cf.as_completed(futs), 1):
            fut.result()
            if time.time() - last > 60 or k == len(futs):
                last = time.time()
                rate = fetched[0] / max(1e-9, last - t0) / 1e6
                print(f"{time.strftime('%F %T')} {k}/{len(futs)} chunks, {rate:.2f} MB/s",
                      flush=True)
    if os.path.getsize(part) != size:
        print("size mismatch after download", flush=True)
        return 1
    os.replace(part, a.dest)
    os.remove(done_path)
    print("DOWNLOAD_OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
