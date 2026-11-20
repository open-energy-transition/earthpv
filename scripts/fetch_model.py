"""Download EarthPV's released segmentation checkpoint and check its SHA-256.

The checkpoint is a GitHub Release asset, not a tracked file: `data/` is gitignored and a
model does not belong in git history. This is the one command the setup docs point at, so
it uses the standard library only and runs in the `default` environment, before the
multi-GB `ml` solve has even started.

    pixi run fetch-model                  # -> data/models/release/<file>
    pixi run fetch-model -- --model terramind
    pixi run fetch-model -- --out-dir /somewhere/else

Two releases are kept (owner, 2026-11-20): the default, `resnet`, is v28, the ResNet-50
released on 2026-11-12; `terramind` is v14, the TerraMind Tiny released on 2026-10-23, kept
as the alternative for where a TerraMind finds more (deserts and dark open ground, very large
parks; docs/pretrained-model.md#the-terramind-alternative-v14).

Re-running is safe: a file already on disk with the right checksum is left alone, and a
download is written to `<file>.part` and only renamed once its checksum matches, so an
interrupted transfer never leaves a truncated checkpoint where `infer` would load it.

To publish a new model, upload it to a release and change its entry in RELEASES below (tag,
file name, SHA-256 from `sha256sum`), then update docs/pretrained-model.md.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

REPO = "open-energy-transition/earthpv"
RELEASES = {
    "resnet": {
        "tag": "segmentation-model-v28-2026-11-12",
        "file": "earthpv_segmentation_v28.ckpt",
        "sha256": "0c2a24b50f66a0c33aad86b0fea6d52a781d23e71b6f9a39950fa0dd19640fe8",
    },
    "terramind": {
        "tag": "segmentation-model-v14-2026-10-23",
        "file": "earthpv_segmentation_v14.ckpt",
        "sha256": "d39d38a864d249c9eff8e6eaf5e5b8d8388ce2c2c9c1f0f1ab66d3bf1a89bbbe",
    },
}
DEFAULT = "resnet"
RELEASE = RELEASES[DEFAULT]  # the default model; scripts/new_region.py reads it


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", choices=sorted(RELEASES), default=DEFAULT,
                    help=f"which released model (default {DEFAULT}: "
                         f"{RELEASES[DEFAULT]['file']})")
    ap.add_argument("--out-dir", type=Path, default=Path("data/models/release"))
    args = ap.parse_args()
    rel = RELEASES[args.model]

    dest = args.out_dir / rel["file"]
    if dest.exists() and sha256(dest) == rel["sha256"]:
        print(f"{dest} already present, checksum OK")
        return 0

    url = f"https://github.com/{REPO}/releases/download/{rel['tag']}/{rel['file']}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    print(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as r, part.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        for block in iter(lambda: r.read(1 << 20), b""):
            f.write(block)
            done += len(block)
            if total:
                print(f"\r  {done / 1e6:5.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()

    got = sha256(part)
    if got != rel["sha256"]:
        part.unlink()
        print(f"Checksum mismatch: expected {rel['sha256']}, got {got}", file=sys.stderr)
        return 1
    part.replace(dest)
    print(f"{dest} (checksum OK)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
