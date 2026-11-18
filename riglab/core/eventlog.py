"""A small saved log of what RigLab did at start-up and in the background (lighting scans, wake from sleep,
devices plugged in). Shown in Advanced view -> RigLab setup, so problems are easy to see and to send for help."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .config import app_dir


class EventLog:
    def __init__(self, path: Path | None = None, keep: int = 300, clock=time.time):
        self.path = path or app_dir() / "startup_log.json"
        self.keep, self.clock = keep, clock
        self._lock = threading.Lock()
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = [e for e in d if isinstance(e, dict) and "text" in e] if isinstance(d, list) else []
        except (OSError, ValueError):
            self.entries = []

    def add(self, kind: str, text: str, level: str = "info", **extra) -> dict:
        """kind: start | scan | found | missing | blocked | wake | device | error | reapply. level: info | warn | error."""
        e = {"time": self.clock(), "kind": kind, "level": level, "text": str(text)}
        e.update({k: v for k, v in extra.items() if v is not None})
        with self._lock:
            self.entries = (self.entries + [e])[-self.keep:]
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.entries, indent=1, default=str), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                pass
        return e

    def items(self, n: int = 200) -> list[dict]:
        with self._lock:
            return list(reversed(self.entries[-n:]))

    def text(self, n: int = 200) -> str:
        lines = []
        for e in reversed(self.items(n)):
            t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["time"]))
            lines.append(f"{t}  [{e.get('level', 'info')}] {e.get('kind', '')}: {e['text']}")
        return "\n".join(lines) or "Nothing logged yet."
