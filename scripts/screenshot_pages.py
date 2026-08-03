#!/usr/bin/env python
"""Render the project's interactive HTML pages to PNG with headless Firefox.

The README cannot embed an iframe, so the hero images there are screenshots of the
same interactive pages the documentation site serves. Regenerating them by hand is
exactly the kind of step that silently goes stale, so it is a script.

    pixi run docs-screenshots
    # or
    .pixi/envs/default/bin/python scripts/screenshot_pages.py
    .pixi/envs/default/bin/python scripts/screenshot_pages.py pakistan_pv_pose

Any arguments are treated as output stems to re-render, so a palette change to one
page does not have to re-render (and re-commit) all of them.

Outputs go to `docs/assets/figures/`. Requires `firefox` on PATH; if it is missing
the script says so and exits 0, leaving any existing PNGs in place, so a machine
without a browser can still build the docs.

Every page here paints itself from `prefers-color-scheme`, and the committed PNGs are
the dark rendering, so this drives Firefox with a throwaway profile pinning
`ui.systemUsesDarkTheme`. Without it the output silently follows whichever theme the
operator's desktop happens to be in, and a light-desktop re-run would replace all of
them with the light rendering.

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
    # The three-tier evidence atlas (Verified / Best estimate / Ceiling) -- the
    # current recommended capacity page, combining segmentation (>=400 m2) with the
    # roofclf/SPPI sub-400 m2 instruments. Framed on the KPI strip and the map.
    Shot("results/pakistan_pv_evidence_atlas.html", "pakistan_evidence_atlas",
         width=1500, height=2100, crop=(0, 0, 1500, 1650)),
    # The glint pose survey, framed on the polar plot and its stat column.
    Shot("results/glint_validation_pakistan/pv_pose_country2000.html", "pakistan_pv_pose",
         width=1400, height=1500, crop=(0, 0, 1400, 1272)),
    # The growth atlas (segmentation + SPPI epoch-diff), framed on the KPI strip and map.
    Shot("results/pakistan_pv_growth_atlas.html", "pakistan_pv_growth",
         width=1500, height=2100, crop=(0, 0, 1500, 1650)),
]


def have_firefox() -> str | None:
    return shutil.which("firefox")


def dark_profile() -> Path:
    """A throwaway Firefox profile pinned to a dark system theme (see module docstring)."""
    prof = STAGE / "profile-dark"
    shutil.rmtree(prof, ignore_errors=True)
    prof.mkdir(parents=True)
    (prof / "user.js").write_text(
        'user_pref("ui.systemUsesDarkTheme", 1);\n'
        'user_pref("browser.shell.checkDefaultBrowser", false);\n'
    )
    return prof


def capture(firefox: str, shot: Shot, profile: Path) -> bool:
    src = ROOT / shot.src
    if not src.exists():
        print(f"  {shot.src} missing, skipping")
        return False

    STAGE.mkdir(parents=True, exist_ok=True)
    staged_html = STAGE / f"{shot.name}.html"
    staged_png = STAGE / f"{shot.name}.png"
    staged_html.write_bytes(src.read_bytes())
    staged_png.unlink(missing_ok=True)

    cmd = [firefox, "--headless", "--no-remote", "-profile", str(profile),
           f"--window-size={shot.width},{shot.height}",
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

    wanted = set(sys.argv[1:])
    shots = [s for s in SHOTS if not wanted or s.name in wanted]
    unknown = wanted - {s.name for s in SHOTS}
    if unknown:
        print(f"no such shot: {', '.join(sorted(unknown))}")
        print(f"known: {', '.join(s.name for s in SHOTS)}")
        return 1

    print(f"screenshots via {firefox}")
    profile = dark_profile()
    ok = all([capture(firefox, s, profile) for s in shots])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
