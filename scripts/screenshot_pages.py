#!/usr/bin/env python
"""Render the project's interactive HTML pages to PNG with headless Firefox.

The README cannot embed an iframe, so the hero images there are screenshots of the
same interactive pages the documentation site serves. Regenerating them by hand is
exactly the kind of step that silently goes stale, so it is a script.

    pixi run docs-screenshots
    # or
    .pixi/envs/default/bin/python scripts/screenshot_pages.py

Outputs go to `docs/assets/figures/`. Requires `firefox` on PATH; if it is missing
the script says so and exits 0, leaving any existing PNGs in place, so a machine
without a browser can still build the docs.

Snap note, learned the hard way: Firefox installed as a snap can only read files
under a NON-hidden directory in $HOME. `/tmp`, an external drive, and even
`~/.cache` (snap's `home` interface excludes dot-directories) all fail, and the
failure mode is a hang rather than an error. Pages are therefore staged in
`~/earthpv-screenshots/`, with the process cwd set there too, and the PNG is moved
back into the repository afterwards.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "figures"
STAGE = Path.home() / "earthpv-screenshots"   # must not be a dot-directory, see above


@dataclass(frozen=True)
class Shot:
    src: str          # repo-relative HTML page
    name: str         # output PNG stem
    width: int
    height: int       # viewport height; render tall enough for the section you want
    crop: tuple | None = None   # (left, top, right, bottom) in captured pixels
    max_width: int = 1600       # downscale target for the committed PNG


SHOTS = [
    # The capacity atlas, framed on the headline number and the national map.
    Shot("results/pakistan_pv_estimator_atlas.html", "pakistan_capacity_atlas",
         width=1500, height=2100, crop=(0, 0, 1500, 1650)),
    # The glint pose survey, framed on the polar plot and its stat column.
    Shot("results/glint_validation_pakistan/pv_pose_country2000.html", "pakistan_pv_pose",
         width=1400, height=1500, crop=(0, 0, 1400, 1272)),
]


def have_firefox() -> str | None:
    return shutil.which("firefox")


def capture(firefox: str, shot: Shot) -> bool:
    src = ROOT / shot.src
    if not src.exists():
        print(f"  {shot.src} missing, skipping")
        return False

    STAGE.mkdir(parents=True, exist_ok=True)
    staged_html = STAGE / f"{shot.name}.html"
    staged_png = STAGE / f"{shot.name}.png"
    staged_html.write_bytes(src.read_bytes())
    staged_png.unlink(missing_ok=True)

    cmd = [firefox, "--headless", f"--window-size={shot.width},{shot.height}",
           f"--screenshot={staged_png}", f"file://{staged_html}"]
    # cwd must also be readable by the snap, or firefox never starts.
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=STAGE)
    if not staged_png.exists():
        print(f"  firefox produced no image for {shot.name} (exit {proc.returncode})")
        print(f"  {proc.stderr.strip()[:300]}")
        return False

    from PIL import Image

    im = Image.open(staged_png).convert("RGB")
    if shot.crop:
        im = im.crop(shot.crop)
    if im.width > shot.max_width:
        im.thumbnail((shot.max_width, shot.max_width * 4), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"{shot.name}.png"
    im.save(dst, optimize=True)
    print(f"  wrote {dst.relative_to(ROOT)} ({im.width}x{im.height})")
    staged_html.unlink(missing_ok=True)
    staged_png.unlink(missing_ok=True)
    return True


def main() -> int:
    firefox = have_firefox()
    if not firefox:
        print("firefox not found on PATH; keeping the existing screenshots.")
        print("Install Firefox, or capture the pages by hand into docs/assets/figures/.")
        return 0
    print(f"screenshots via {firefox}")
    ok = all([capture(firefox, s) for s in SHOTS])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
