"""Settings storage. Everything lives in %APPDATA%\\RigLab (or ~/.riglab elsewhere)."""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

APP_NAME = "RigLab"
APP_VERSION = "3.7.0"


def app_dir() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else None
    d = Path(base) / APP_NAME if base else Path.home() / ".riglab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_root() -> Path:
    """Folder containing main.py (or the exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def vendor_dir() -> Path:
    """Bundled helpers (LibreHardwareMonitor, OpenRGB drivers). In the exe build this sits next to
    RigLab.exe (not inside _internal) so it stays writable and can be updated in place."""
    if os.environ.get("RIGLAB_VENDOR"):          # the installer build fetches the tools into its own folder
        return Path(os.environ["RIGLAB_VENDOR"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "vendor"
    return project_root() / "vendor"


DEFAULTS: dict = {
    "poll_interval_ms": 1000,
    "history_seconds": 300,
    "temperature_unit": "C",
    "start_minimized": False,
    "minimize_to_tray": True,
    "alerts": {
        "enabled": True,
        "cpu_temp_max": 90.0,
        "gpu_temp_max": 85.0,
        "drive_temp_max": 65.0,
        "cooldown_seconds": 120,
    },
    "logging": {"enabled": False, "interval_s": 5},
    "openrgb": {"host": "127.0.0.1", "port": 6742, "autostart": True, "exe": ""},
    "liquidctl": {"enabled": True, "exclude": []},
    "fan_curves": {},          # control_id -> {"source": sensor_id, "points": [[temp, pct], ...]}
    "rgb_profiles": {},        # name -> {device_name: "#rrggbb"}
    "overlay": {"enabled": False, "sensors": [], "corner": "top-left", "opacity": 0.85, "show_fps": False},
    "ui": {"theme": "dark", "accent": "cyan", "start_page": "home"},
}


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "settings.json"
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                _deep_merge(self.data, saved)
            except (OSError, ValueError):
                pass  # corrupt file -> keep defaults

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value


def _deep_merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
