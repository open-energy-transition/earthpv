#!/usr/bin/env python
"""Give one country's compute chain the GPU first (owner, 2026-11-07: Spain).

Every GPU job on this machine (earthpv and subdetect) takes `data/.gpu.lock` with flock(1),
which serves whichever waiter the kernel happens to wake first. A country's chain takes the
lock once per GPU step (train, the recall pick, the local-vs-v5 decision, national
inference), so between its steps a queued job from another unit can take the card for hours.

From START (the queue's `<aoi>_compose_done` marker: the compute chain starts within minutes)
until UNTIL (the chain's `infer` marker), this watcher:

- pauses (SIGSTOP) every other process WAITING for the lock: a `flock` with the lock file
  open, no child yet, asleep in the kernel's lock wait. A stopped waiter leaves the wait and
  re-enters it on SIGCONT (the syscall restarts), so nothing fails and nothing is lost. A job
  already RUNNING on the GPU is never touched: the country waits for it to finish;
- holds the lock itself whenever the country is not using it, so a runner that calls flock
  while the lock is free cannot take it either, and hands it over as soon as the country's
  own `flock` (a process in `earthpv-<aoi>-compute.service`) is waiting.

`--now` reserves from the moment it starts instead (owner, 2026-11-07: Spain's training and
inference should run directly, so no long job may start in the hours before it needs the card;
the GPU may sit idle meanwhile). If the compute unit is not active for `--idle-release-min`
once compose is done (it failed, or the
queue has not relaunched it), the watcher lets go until it is active again. At UNTIL, after
`--max-hours`, on SIGTERM and on any error it unlocks and resumes every process it paused. If
it is killed hard (SIGKILL, OOM) the paused waiters stay stopped: `pkill -CONT -x flock`.

    systemd-run --user --collect --unit=earthpv-gpu-priority-spain -p WorkingDirectory=$PWD \\
        .pixi/envs/default/bin/python scripts/gpu_priority.py --aoi spain
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def log(msg: str) -> None:
    print(f"{dt.datetime.now():%F %T} GPU-PRIORITY: {msg}", flush=True)


def _starttime(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except OSError:
        return None


def _children(pid: int) -> bool:
    try:
        return bool(Path(f"/proc/{pid}/task/{pid}/children").read_text().split())
    except OSError:
        return False


def lock_processes(lock: Path):
    """(pid, unit cgroup, waiting) for every `flock` process with `lock` open."""
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if (d / "comm").read_text().strip() != "flock":
                continue
            fds = [os.readlink(f) for f in (d / "fd").iterdir()]
        except OSError:
            continue
        if str(lock) not in fds:
            continue
        pid = int(d.name)
        try:
            cg = (d / "cgroup").read_text().strip()
            wchan = (d / "wchan").read_text()
            state = (d / "stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        waiting = not _children(pid) and ("lock" in wchan or state == "T")
        out.append((pid, cg, waiting, state))
    return out


def unit_active(unit: str) -> bool:
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit]).returncode == 0


class Holder:
    """The watcher's own hold on the lock, taken by a blocking flock in a thread, so it sits
    in the kernel's queue and wins the moment the running job lets go."""

    def __init__(self, lock: Path):
        self.fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o664)
        self.held = threading.Event()
        self.thread: threading.Thread | None = None

    def arm(self) -> None:
        if self.held.is_set() or (self.thread and self.thread.is_alive()):
            return

        def take():
            fcntl.flock(self.fd, fcntl.LOCK_EX)
            self.held.set()
            log("holding the lock for the country")

        self.thread = threading.Thread(target=take, daemon=True)
        self.thread.start()

    def release(self) -> None:
        if self.held.is_set():
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.held.clear()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", required=True)
    ap.add_argument("--qmark", type=Path, default=REPO / "data/country_queue_markers")
    ap.add_argument("--idle-release-min", type=float, default=45.0)
    ap.add_argument("--max-hours", type=float, default=60.0)
    ap.add_argument("--poll-s", type=float, default=0.25)
    ap.add_argument("--now", action="store_true",
                    help="reserve from now, not from compose_done (the GPU may sit idle until "
                         "the chain needs it; the idle release still waits for compose_done)")
    ap.add_argument("--lock", type=Path, help="(tests) another lock file")
    ap.add_argument("--until-marker", type=Path, help="(tests) another end marker")
    a = ap.parse_args()

    lock = (a.lock or REPO / "data/.gpu.lock").resolve()
    unit = f"earthpv-{a.aoi}-compute.service"
    start_marker = a.qmark / f"{a.aoi}_compose_done"
    until_marker = a.until_marker or REPO / f"data/{a.aoi}_pipeline_markers/infer"
    paused: dict[int, str | None] = {}
    holder: Holder | None = None
    t_start = None
    idle_since = None

    def resume_all(why: str) -> None:
        nonlocal holder
        if holder is not None:
            holder.release()
        for pid, st in list(paused.items()):
            if _starttime(pid) == st:
                try:
                    os.kill(pid, signal.SIGCONT)
                except OSError:
                    pass
            paused.pop(pid, None)
        log(f"released ({why}); every paused waiter resumed")

    def on_term(signum, frame):
        resume_all(f"signal {signum}")
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    log(f"watching for {start_marker.name}; the GPU goes to {unit} until {until_marker}")
    try:
        while True:
            if until_marker.exists():
                resume_all(f"{a.aoi} inference is done")
                return 0
            if not (a.now or start_marker.exists()):
                time.sleep(60)
                continue
            if t_start is None:
                t_start = time.time()
                log(f"reserving the GPU for {a.aoi} "
                    f"({'from now' if not start_marker.exists() else start_marker.name + ' exists'})")
            if time.time() - t_start > a.max_hours * 3600:
                resume_all(f"over {a.max_hours} h")
                return 1
            # Let go while the country's chain is not running at all (failed, not relaunched).
            if start_marker.exists() and not unit_active(unit):
                idle_since = idle_since or time.time()
                if time.time() - idle_since > a.idle_release_min * 60:
                    if paused or (holder and holder.held.is_set()):
                        resume_all(f"{unit} inactive for {a.idle_release_min:.0f} min")
                    time.sleep(60)
                    continue
            else:
                if idle_since and time.time() - idle_since > a.idle_release_min * 60:
                    log(f"{unit} active again: reserving the GPU once more")
                idle_since = None
            if holder is None:
                holder = Holder(lock)
            procs = lock_processes(lock)
            mine = [p for p in procs if unit in p[1]]
            for pid, cg, waiting, state in procs:
                if unit in cg or not waiting or pid in paused or state == "T":
                    continue
                try:
                    os.kill(pid, signal.SIGSTOP)
                    paused[pid] = _starttime(pid)
                    log(f"paused waiter {pid} ({cg.rsplit('/', 1)[-1]})")
                except OSError:
                    pass
            country_waiting = any(w for _, _, w, _ in mine)
            if holder.held.is_set() and country_waiting:
                holder.release()
                log("handed the lock to the country")
                # Give its flock the lock before ours asks again (an immediate re-request
                # would win the free lock back from the woken waiter).
                t0 = time.time()
                while time.time() - t0 < 10:
                    if not any(w for p, cg, w, _ in lock_processes(lock) if unit in cg):
                        break
                    time.sleep(0.1)
            if not country_waiting:
                holder.arm()
            time.sleep(a.poll_s)
    except Exception as e:  # noqa: BLE001 - never leave waiters stopped
        resume_all(f"error: {e!r}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
