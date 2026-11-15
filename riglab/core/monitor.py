"""Temperature alerts and CSV sensor logging."""
from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Callable

from .config import app_dir


class Alerts:
    def __init__(self, hub, config, notify: Callable[[str, str], None]):
        self.hub, self.config, self.notify = hub, config, notify
        self._last: dict[str, float] = {}
        hub.subscribe(self._check)

    def _check(self, snap):
        a = self.config["alerts"]
        if not a["enabled"]:
            return
        checks = [("cpu", self.hub.cpu_temp(), a["cpu_temp_max"], "CPU"),
                  ("gpu", self.hub.gpu_temp(), a["gpu_temp_max"], "GPU")]
        for s in snap.sensors.values():
            if s.hw_type == "Storage" and s.kind == "Temperature" and s.value is not None:
                checks.append((f"drive:{s.id}", s, a["drive_temp_max"], s.hardware))
        now = time.time()
        for key, sensor, limit, label in checks:
            if sensor is None or sensor.value is None or sensor.value < limit:
                continue
            if now - self._last.get(key, 0) < a["cooldown_seconds"]:
                continue
            self._last[key] = now
            self.notify(f"{label} is hot: {sensor.value:.0f}°C",
                        f"{sensor.name} passed your {limit:.0f}°C alert limit.")


class CsvLogger:
    def __init__(self, hub, config):
        self.hub, self.config = hub, config
        self.path: Path | None = None
        self._fh = None
        self._writer = None
        self._cols: list[str] = []
        self._next = 0.0
        hub.subscribe(self._tick)

    def start(self) -> Path:
        self.stop()
        folder = app_dir() / "logs"
        folder.mkdir(exist_ok=True)
        self.path = folder / time.strftime("sensors_%Y%m%d_%H%M%S.csv")
        snap = self.hub.latest
        self._cols = sorted(snap.sensors)
        self._fh = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        self._writer.writerow(["time"] + [f"{snap.sensors[c].hardware} | {snap.sensors[c].name} "
                                          f"[{snap.sensors[c].unit}]" for c in self._cols])
        self.config["logging"]["enabled"] = True
        return self.path

    def _tick(self, snap):
        if not self._writer or time.time() < self._next:
            return
        self._next = time.time() + self.config["logging"]["interval_s"]
        row = [time.strftime("%Y-%m-%d %H:%M:%S")]
        for c in self._cols:
            s = snap.sensors.get(c)
            row.append("" if s is None or s.value is None else f"{s.value:.2f}")
        self._writer.writerow(row)
        self._fh.flush()

    def stop(self):
        if self._fh:
            self._fh.close()
        self._fh = self._writer = None
        self.config["logging"]["enabled"] = False

    @property
    def active(self) -> bool:
        return self._writer is not None
