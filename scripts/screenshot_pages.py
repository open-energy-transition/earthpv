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

**Captured over WebDriver BiDi, not `--screenshot` (2026-10-19).** The evidence atlas's map
is drawn by MapLibre GL into a WebGL canvas after the load event, and `--screenshot` fires
AT the load event, so it captured an empty map. Each page is now loaded in a headless
Firefox driven over its remote-debugging socket, and the shot is taken once the page says
it is ready (a `ready` expression per Shot; the atlas sets `data-atlas-ready` when its map
has drawn a complete frame). The BiDi client below is stdlib only, so the script still
needs nothing beyond Firefox.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
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
    # (left, top, right, bottom) in captured pixels. **Cut on a component boundary,
    # never through one.** These pages are laid out as cards, so a crop chosen by
    # eyeballing a pixel height will slice a card in half and the hero image reads as
    # broken. Pick the bottom edge just below the last FULL row you want to keep, and
    # the right edge just outside the rightmost panel rather than through its padding.
    crop: tuple | None = None
    max_width: int = 1600       # downscale target for the committed PNG
    # JS expression that is true once the page has finished drawing; None = the load event.
    ready: str | None = None


SHOTS = [
    # The evidence atlas (Verified / Best estimate) -- this project's primary output,
    # combining segmentation (>=400 m2) with the roofclf/SPPI sub-400 m2 instruments.
    # Framed on the KPI strip and the map. Lives directly under docs/ (2026-08-06),
    # not results/ -- it is this project's primary output, so its canonical copy is
    # wherever the site and README read it from, with no separate results/ original.
    #
    # The crop ends immediately BELOW the four-card KPI row and just outside the right
    # edge of the province panel, so every visible block is whole (owner, 2026-09-20,
    # correcting a 1500x1650 box that cut through the row beneath). Re-check this box
    # whenever the page layout changes -- a card added or resized moves the boundary,
    # and the failure is silent. Re-cut 2026-10-19 for the MapLibre/Plot page, whose
    # toolbar row made the map card taller.
    Shot("docs/assets/interactive/pakistan_evidence_atlas.html", "pakistan_evidence_atlas",
         width=1500, height=2100, crop=(128, 24, 1360, 1308),
         ready="document.documentElement.dataset.atlasReady === '1'"),
    # The glint pose survey, framed on the polar plot and its stat column.
    Shot("results/glint_validation_pakistan/pv_pose_country2000.html", "pakistan_pv_pose",
         width=1400, height=1500, crop=(0, 0, 1400, 1272)),
    # The growth atlas (segmentation + SPPI epoch-diff), framed on the KPI strip and map.
    # Same rule as the evidence atlas above: 1650 cut through the "What each view means"
    # card and left a sentence sliced in half. 1515 lands in the 22 px gutter under the
    # map and province panels instead.
    Shot("results/pakistan_pv_growth_atlas.html", "pakistan_pv_growth",
         width=1500, height=2100, crop=(0, 0, 1500, 1515)),
]


def have_firefox() -> str | None:
    return shutil.which("firefox")


def dark_profile() -> Path:
    """A throwaway Firefox profile pinned to a dark system theme (see module docstring).

    Also pins `ui.prefersReducedMotion`, which fixes a defect the committed PNGs carried
    for months: the atlas pages animate their hero figure with a count-up, and
    `--screenshot` fires while that animation is still running, so the captured hero read
    885 against a real total of 11,230 (and 4,818 against 16,441 after the numbers moved).
    Every one of these templates already short-circuits its count-up to the final value
    when reduced motion is requested, so asking for it is enough -- no extra wait, and no
    template change.
    """
    prof = STAGE / "profile-dark"
    shutil.rmtree(prof, ignore_errors=True)
    prof.mkdir(parents=True)
    (prof / "user.js").write_text(
        'user_pref("ui.systemUsesDarkTheme", 1);\n'
        'user_pref("ui.prefersReducedMotion", 1);\n'
        'user_pref("browser.shell.checkDefaultBrowser", false);\n'
        # Headless Firefox falls back to software GL; without this some drivers refuse
        # WebGL outright and the atlas map draws its "could not start" notice instead.
        'user_pref("webgl.force-enabled", true);\n'
    )
    return prof


class BiDi:
    """The few WebDriver BiDi calls a screenshot needs, over a stdlib WebSocket."""

    def __init__(self, port: int, timeout: float = 120):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET /session HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(request.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("remote agent closed the handshake")
            head += chunk
        head, self.buf = head.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head.decode(errors="replace")[:200])
        self.seq = 0

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("remote agent closed the socket")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, opcode: int, payload: bytes) -> None:
        n, mask = len(payload), os.urandom(4)       # client frames must be masked
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(head + mask + body)

    def _message(self) -> str:
        data = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            opcode = b1 & 0x0F
            if opcode == 0x9:                       # ping
                self._send(0xA, payload)
                continue
            if opcode == 0x8:
                raise ConnectionError("remote agent closed the session")
            data += payload
            if b1 & 0x80:
                return data.decode()

    def call(self, method: str, **params) -> dict:
        self.seq += 1
        self._send(0x1, json.dumps({"id": self.seq, "method": method, "params": params}).encode())
        while True:
            msg = json.loads(self._message())
            if msg.get("id") == self.seq:
                if msg.get("type") == "error":
                    raise RuntimeError(f"{method}: {msg.get('error')}: {msg.get('message')}")
                return msg["result"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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

    port = _free_port()
    # cwd must also be readable by the snap, or firefox never starts.
    proc = subprocess.Popen([firefox, "--headless", "--no-remote", "-profile", str(profile),
                             f"--remote-debugging-port={port}", "about:blank"],
                            cwd=STAGE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        bidi = None
        for _ in range(120):                       # the snap can take a while to start
            time.sleep(0.5)
            try:
                bidi = BiDi(port)
                break
            except OSError:
                if proc.poll() is not None:
                    break
        if bidi is None:
            print(f"  firefox did not open a remote-debugging socket for {shot.name}")
            print(f"  {(proc.stderr.read() if proc.poll() is not None else '')[:300]}")
            return False
        bidi.call("session.new", capabilities={})
        ctx = bidi.call("browsingContext.getTree")["contexts"][0]["context"]
        bidi.call("browsingContext.setViewport", context=ctx,
                  viewport={"width": shot.width, "height": shot.height})
        bidi.call("browsingContext.navigate", context=ctx, url=f"file://{staged_html}",
                  wait="complete")
        deadline = time.time() + 90
        while shot.ready and time.time() < deadline:
            res = bidi.call("script.evaluate", expression=f"!!({shot.ready})",
                            target={"context": ctx}, awaitPromise=False)
            if res.get("result", {}).get("value") is True:
                break
            time.sleep(0.5)
        else:
            if shot.ready:
                print(f"  {shot.name}: page never reported ready, capturing anyway")
        time.sleep(1.0)                             # let the last frame composite
        shot_b64 = bidi.call("browsingContext.captureScreenshot", context=ctx,
                             origin="document")["data"]
        staged_png.write_bytes(base64.b64decode(shot_b64))
    except Exception as err:  # noqa: BLE001 - report and keep going with the other shots
        print(f"  capturing {shot.name} failed: {err}")
        return False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

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
