"""FPS and frame times for any game or benchmark, on any GPU brand, via PresentMon.

PresentMon is Intel's open-source frame-capture tool (MIT licence, github.com/GameTechDev/PresentMon).
It's a single console exe; RigLab fetches it once into vendor/presentmon and runs it hidden while a
performance run is recording. Needs administrator rights (RigLab already has them).
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


class Capture:
    """Runs PresentMon and keeps frame times per process. The busiest 3D app is treated as 'the game'."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.frames: dict[str, list[float]] = collections.defaultdict(list)   # app -> frame times (ms)
        self.recent: dict[str, collections.deque] = collections.defaultdict(lambda: collections.deque(maxlen=2000))
        self.error: str | None = None
        self._t = None

    def start(self) -> bool:
        exe = ensure()
        if not exe:
            self.error = "PresentMon isn't available (offline?) - FPS won't be recorded for this run."
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

    def _read(self):
        cols = None
        for line in self.proc.stdout:
            parts = line.rstrip("\n").split(",")
            if cols is None:
                if "Application" in parts:
                    cols = {c: i for i, c in enumerate(parts)}
                    ia, ims = cols["Application"], cols.get("MsBetweenPresents", cols.get("FrameTime"))
                    if ims is None:
                        self.error = "PresentMon output not understood"
                        return
                continue
            try:
                app, ms = parts[ia], float(parts[ims])
            except (IndexError, ValueError):
                continue
            if app.lower() in IGNORE or not (0 < ms < 1000):
                continue
            self.frames[app].append(ms)
            self.recent[app].append(time.monotonic())

    def main_app(self) -> str | None:
        return max(self.frames, key=lambda a: len(self.frames[a]), default=None)

    def current(self) -> float | None:
        """Frames per second of the main app over the last second."""
        app = self.main_app()
        if not app:
            return None
        now = time.monotonic()
        n = sum(1 for t in self.recent[app] if now - t <= 1.0)
        return float(n) if n else None

    def stats(self) -> dict:
        app = self.main_app()
        ft = self.frames.get(app) or []
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
