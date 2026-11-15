"""FPS and frame times for any game or benchmark, on any GPU brand, via PresentMon.

PresentMon is Intel's open-source frame-capture tool (MIT licence, github.com/GameTechDev/PresentMon).
It's a single console exe bundled in vendor/presentmon. It runs hidden while a GPU benchmark run is
recording and/or while the overlay shows FPS. Both share ONE capture (acquire/release below), so they
never start two PresentMon sessions. Needs administrator rights (RigLab already has them).
"""
from __future__ import annotations

import collections
import json
import logging
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from .config import vendor_dir

log = logging.getLogger(__name__)
API = "https://api.github.com/repos/GameTechDev/PresentMon/releases/latest"
IGNORE = {"dwm.exe", "explorer.exe", "riglab.exe", "pythonw.exe", "python.exe", "msedgewebview2.exe", "textinputhost.exe",
          "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "applicationframehost.exe"}


def exe_path() -> Path:
    return vendor_dir() / "presentmon" / "PresentMon.exe"


def ensure(progress=None) -> Path | None:
    """Download PresentMon once (about 3 MB). Returns the exe path, or None if offline."""
    p = exe_path()
    if p.exists():
        return p
    say = progress or (lambda m: None)
    try:
        say("Getting PresentMon (frame-rate capture)…")
        req = urllib.request.Request(API, headers={"User-Agent": "RigLab", "Accept": "application/vnd.github+json"})
        rel = json.loads(urllib.request.urlopen(req, timeout=20).read())
        asset = next(a for a in rel["assets"] if re.match(r"^PresentMon-[\d.]+-x64\.exe$", a["name"]))
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        with urllib.request.urlopen(urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "RigLab"}),
                                    timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
        tmp.replace(p)
        (p.parent / "VERSION.txt").write_text(rel.get("tag_name", ""), encoding="utf-8")
        return p
    except Exception as e:  # noqa: BLE001
        log.warning("PresentMon download failed: %s", e)
        return None


LIVE_WINDOW_S = 10.0          # how much frame history the overlay keeps per program (bounded memory)


def parse_header(parts: list[str]) -> tuple[int, int | None, int] | None:
    """Column positions of (Application, ProcessID, frame time) in PresentMon's CSV header, or None."""
    if "Application" not in parts:
        return None
    cols = {c: i for i, c in enumerate(parts)}
    ims = cols.get("MsBetweenPresents", cols.get("FrameTime"))
    if ims is None:
        return None
    return cols["Application"], cols.get("ProcessID"), ims


def parse_line(parts: list[str], idx: tuple[int, int | None, int]) -> tuple[str, int | None, float] | None:
    """One CSV row -> (app, pid, frame time in ms), or None for rows we don't use."""
    ia, ipid, ims = idx
    try:
        app, ms = parts[ia], float(parts[ims])
        pid = int(parts[ipid]) if ipid is not None else None
    except (IndexError, ValueError):
        return None
    if app.lower() in IGNORE or not (0 < ms < 1000):
        return None
    return app, pid, ms


def live_reading(samples, now: float) -> dict | None:
    """FPS (last 1 s), 1% low (last 10 s) and average frame time from [(monotonic time, ms), ...].
    None when the program hasn't presented a frame for 1.5 s (it isn't rendering)."""
    recent10 = [ms for t, ms in samples if now - t <= LIVE_WINDOW_S]
    recent1 = [ms for t, ms in samples if now - t <= 1.0]
    if not recent1 or not any(now - t <= 1.5 for t, _ in samples[-3:]):
        return None
    s = sorted(recent10)
    p99 = s[min(len(s) - 1, int(len(s) * 0.99))]
    return {"fps": len(recent1), "low1": round(1000 / p99, 1) if p99 else None,
            "frametime": round(sum(recent1) / len(recent1), 2)}


class Capture:
    """Runs PresentMon and keeps frame times per process.
    - live:   last ~10 s per process id (always, bounded) - for the overlay
    - frames: full per-app history, only while a benchmark is recording - for run statistics"""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.frames: dict[str, list[float]] = collections.defaultdict(list)   # app -> frame times (ms)
        self.recent: dict[str, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=2000))
        self.live: dict[int, collections.deque] = {}
        self.names: dict[int, str] = {}
        self.recording = 0
        self.error: str | None = None
        self._t = None
        self._lock = threading.RLock()

    def start(self, allow_download: bool = False) -> bool:
        exe = ensure() if allow_download else (exe_path() if exe_path().exists() else None)
        if not exe:
            self.error = "PresentMon isn't available - FPS won't be recorded."
            return False
        args = [str(exe), "--output_stdout", "--no_console_stats", "--stop_existing_session", "--session_name", "RigLab"]
        for x in ("dwm.exe", "RigLab.exe", "msedgewebview2.exe"):
            args += ["--exclude", x]
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                         creationflags=0x08000000)
        except OSError as e:
            self.error = f"Couldn't start PresentMon: {e}"
            return False
        self._t = threading.Thread(target=self._read, daemon=True, name="PresentMon")
        self._t.start()
        return True

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _read(self):
        idx = None
        for line in self.proc.stdout:
            parts = line.rstrip("\n").split(",")
            if idx is None:
                idx = parse_header(parts)
                continue
            row = parse_line(parts, idx)
            if row:
                self.add(*row)

    def add(self, app: str, pid: int | None, ms: float, now: float | None = None):
        now = time.monotonic() if now is None else now
        with self._lock:
            if self.recording:
                self.frames[app].append(ms)
            self.recent[app].append(now)
            if pid is not None:
                q = self.live.get(pid)
                if q is None:
                    self._prune(now)                      # forget programs that stopped rendering a minute ago
                    q = self.live[pid] = collections.deque(maxlen=3000)
                    self.names[pid] = app
                q.append((now, ms))
                while q and now - q[0][0] > LIVE_WINDOW_S:
                    q.popleft()

    def _prune(self, now):
        for pid in [p for p, q in self.live.items() if not q or now - q[-1][0] > 60]:
            self.live.pop(pid, None)
            self.names.pop(pid, None)

    def start_recording(self):
        with self._lock:
            if not self.recording:
                self.frames.clear()
            self.recording += 1

    def stop_recording(self):
        with self._lock:
            self.recording = max(0, self.recording - 1)

    def reading_for(self, pid: int | None, now: float | None = None) -> dict:
        """Overlay reading for the program in front: {"state": "ok", fps, low1, frametime, app} or {"state": "no_game"}."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = list(self.live.get(pid, ())) if pid is not None else []
            name = self.names.get(pid)
        r = live_reading(q, now) if q else None
        if not r:
            return {"state": "no_game"}
        return {"state": "ok", "app": name, **r}

    def main_app(self) -> str | None:
        with self._lock:
            return max(self.frames, key=lambda a: len(self.frames[a]), default=None)

    def current(self) -> float | None:
        """Frames per second of the main app over the last second."""
        app = self.main_app()
        if not app:
            return None
        now = time.monotonic()
        with self._lock:
            n = sum(1 for t in self.recent[app] if now - t <= 1.0)
        return float(n) if n else None

    def stats(self) -> dict:
        app = self.main_app()
        with self._lock:
            ft = list(self.frames.get(app) or [])
        if len(ft) < 30:
            return {}
        s = sorted(ft)
        avg_ms = sum(ft) / len(ft)
        p99 = s[min(len(s) - 1, int(len(s) * 0.99))]
        p999 = s[min(len(s) - 1, int(len(s) * 0.999))]
        med = s[len(s) // 2]
        spikes = sum(1 for x in ft if x > med * 2.5 and x > 25)          # hitches you can feel
        # best 1-second window = max FPS
        best, win, acc = 0.0, [], 0.0
        for x in ft:
            win.append(x)
            acc += x
            while acc > 1000 and len(win) > 1:
                acc -= win.pop(0)
            if acc >= 900:
                best = max(best, len(win) * 1000 / acc)
        return {"app": app, "frames": len(ft), "fps_avg": round(1000 / avg_ms, 1), "fps_low": round(1000 / p99, 1),
                "fps_low01": round(1000 / p999, 1), "fps_max": round(best or 1000 / s[0], 1), "frametime_avg": round(avg_ms, 2),
                "frametime_p99": round(p99, 2), "spikes": spikes, "spikes_per_min": round(spikes / max(1e-6, sum(ft) / 60000), 1)}

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ------------------------------------------------------------------------------ one shared capture
_shared: Capture | None = None
_owners: dict[str, bool] = {}          # owner -> is recording
_mgr_lock = threading.Lock()


def acquire(owner: str, record: bool = False, allow_download: bool = False) -> Capture | None:
    """Start (or join) the single PresentMon capture. Returns None if it can't run."""
    global _shared
    with _mgr_lock:
        if _shared is None or not _shared.running():
            cap = Capture()
            if not cap.start(allow_download=allow_download):
                log.info("PresentMon not started for %s: %s", owner, cap.error)
                return None
            _shared = cap
        if owner not in _owners:
            _owners[owner] = record
            if record:
                _shared.start_recording()
        return _shared


def release(owner: str):
    """Leave the shared capture; PresentMon stops when nobody needs it any more."""
    global _shared
    with _mgr_lock:
        rec = _owners.pop(owner, None)
        if _shared is not None and rec:
            _shared.stop_recording()
        if not _owners and _shared is not None:
            _shared.stop()
            _shared = None


def release_all():
    for o in list(_owners):
        release(o)
    with _mgr_lock:
        global _shared
        if _shared is not None:
            _shared.stop()
            _shared = None


def shared() -> Capture | None:
    return _shared if _shared is not None and _shared.running() else None


def holders() -> list[str]:
    return list(_owners)


def foreground_pid() -> int | None:
    """Process id of the window in front (one cheap Windows call, no process scan)."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value or None
    except Exception:  # noqa: BLE001
        return None
