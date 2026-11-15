"""Download / install LibreHardwareMonitor into vendor/lhm (pure Python, with progress + log).

Used by the installer build and by Health check → Re-download / Install from zip.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .config import app_dir, vendor_dir

SOURCES = [
    # 1) GitHub's "latest release" redirect - no API, no rate limit
    ("latest release", "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/latest/download/LibreHardwareMonitor.zip"),
    # 2) older releases named their .NET Framework zip like this
    ("latest release (net472 name)", "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/latest/download/LibreHardwareMonitor-net472.zip"),
    # 3) nightly build (newest hardware support)
    ("nightly build", "https://nightly.link/LibreHardwareMonitor/LibreHardwareMonitor/workflows/master/master/LibreHardwareMonitor-net472.zip"),
]
API = "https://api.github.com/repos/LibreHardwareMonitor/LibreHardwareMonitor/releases/latest"
UA = {"User-Agent": "RigLab-setup"}


def dest_dir() -> Path:
    return vendor_dir() / "lhm"


class Installer:
    """Runs on a thread; the UI polls .state."""

    def __init__(self):
        self.state = {"running": False, "step": "", "progress": 0.0, "log": [], "ok": None, "error": None}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ logging
    def log(self, msg: str):
        line = time.strftime("%H:%M:%S ") + msg
        self.state["log"].append(line)
        self.state["step"] = msg
        try:
            with open(app_dir() / "lhm_download.log", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        print(line, flush=True)

    # ------------------------------------------------------------------ public
    def start(self, zip_path: str | None = None, before_install=None, after_install=None):
        with self._lock:
            if self.state["running"]:
                return False
            self.state = {"running": True, "step": "Starting…", "progress": 0.0, "log": [], "ok": None, "error": None}
        threading.Thread(target=self.run, args=(zip_path, before_install, after_install), daemon=True).start()
        return True

    def run(self, zip_path=None, before_install=None, after_install=None):
        try:
            if zip_path:
                self.log(f"Using your file: {zip_path}")
                data = Path(zip_path).read_bytes()
                src = "your zip file"
            else:
                data, src = self._download_any()
            self.state["progress"] = 0.85
            if before_install:
                self.log("Stopping the sensor process…")
                before_install()
            info = self._install(data, src)
            self.state["progress"] = 0.95
            self.state["ok"] = True
            self.log(f"Installed {info}.")
            if after_install:
                self.log("Starting sensors…")
                after_install()
            self.state["progress"] = 1.0
        except Exception as e:  # noqa: BLE001
            self.state["ok"] = False
            self.state["error"] = str(e)
            self.log(f"FAILED: {e}")
        finally:
            self.state["running"] = False

    # ------------------------------------------------------------------ steps
    def _download_any(self) -> tuple[bytes, str]:
        errors = []
        urls = list(SOURCES)
        try:  # also ask the API, in case the asset name changed again
            req = urllib.request.Request(API, headers=UA)
            rel = json.load(urllib.request.urlopen(req, timeout=15))
            for a in rel.get("assets", []):
                if a["name"].lower().endswith(".zip"):
                    urls.insert(1, (f"{rel['tag_name']} {a['name']}", a["browser_download_url"]))
        except Exception as e:  # noqa: BLE001
            self.log(f"(GitHub API not reachable: {e} - using direct links)")
        tried = set()
        for label, url in urls:
            if url in tried:
                continue
            tried.add(url)
            try:
                data = self._download(label, url)
                fw = _zip_framework(data)
                if fw is None:
                    raise ValueError("no LibreHardwareMonitorLib.dll inside")
                self.log(f"  build type: {fw}")
                return data, label
            except Exception as e:  # noqa: BLE001
                self.log(f"  {label}: {e}")
                errors.append(f"{label}: {e}")
        raise RuntimeError("Every download source failed. Use 'Install from zip…' instead "
                           "(download LibreHardwareMonitor.zip from GitHub in your browser first).")

    def _download(self, label: str, url: str) -> bytes:
        self.log(f"Downloading {label}…")
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            total = int(r.headers.get("Content-Length") or 0)
            buf = io.BytesIO()
            last = time.monotonic()
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                buf.write(chunk)
                if total:
                    self.state["progress"] = 0.8 * buf.tell() / total
                if time.monotonic() - last > 1:
                    last = time.monotonic()
                    self.state["step"] = f"Downloading {label}… {buf.tell() / 2**20:.1f}" + (
                        f" / {total / 2**20:.1f} MB" if total else " MB")
        self.log(f"  got {buf.tell() / 2**20:.1f} MB")
        return buf.getvalue()

    def _install(self, data: bytes, src: str) -> str:
        z = zipfile.ZipFile(io.BytesIO(data))
        libs = [n for n in z.namelist() if n.lower().endswith("librehardwaremonitorlib.dll")]
        if not libs:
            raise ValueError("That zip doesn't contain LibreHardwareMonitorLib.dll")
        # prefer the .NET Framework build if the zip holds several
        best = None
        for n in libs:
            fw = _framework(z.read(n))
            if best is None or fw.startswith("netfx"):
                best, best_fw = n, fw
        prefix = best[: -len("LibreHardwareMonitorLib.dll")]
        dest = dest_dir()
        tmp = dest.with_name("lhm_new")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for n in z.namelist():
            if n.startswith(prefix) and not n.endswith("/"):
                out = tmp / n[len(prefix):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(n))
        (tmp / "VERSION.txt").write_text(f"{src} ({best_fw})", encoding="utf-8")
        self.log(f"Unpacked {sum(1 for _ in tmp.rglob('*'))} files ({best_fw})")
        # swap folders (retry: Windows can briefly hold DLL locks after the old process exits)
        for attempt in range(10):
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                tmp.rename(dest)
                break
            except OSError as e:
                if attempt == 9:
                    raise RuntimeError(f"Couldn't replace {dest} (files in use? close LibreHardwareMonitor "
                                       f"if it's open): {e}") from e
                time.sleep(0.5)
        if best_fw.startswith("coreclr"):
            self.log("Note: this build needs the .NET runtime - Health check will offer to install it if missing.")
        return f"{src} ({best_fw})"


def _framework(dll_bytes: bytes) -> str:
    import re
    m = re.search(rb"\.NETCoreApp,Version=v(\d+)", dll_bytes)
    if m:
        return f"coreclr {m.group(1).decode()}"
    m = re.search(rb"\.NETFramework,Version=v([\d.]+)", dll_bytes)
    return f"netfx {m.group(1).decode()}" if m else "netfx ?"


def _zip_framework(data: bytes) -> str | None:
    z = zipfile.ZipFile(io.BytesIO(data))
    for n in z.namelist():
        if n.lower().endswith("librehardwaremonitorlib.dll"):
            return _framework(z.read(n))
    return None


def installed_info() -> str | None:
    f = dest_dir() / "VERSION.txt"
    if (dest_dir() / "LibreHardwareMonitorLib.dll").exists():
        return f.read_text(encoding="utf-8").strip() if f.exists() else "unknown version"
    return None


if __name__ == "__main__":
    force = "--force" in sys.argv
    info = installed_info()
    if info and "(" in info and not force:   # RigLab 2 installs are tagged "(netfx ...)" / "(coreclr ...)"
        print(f"LibreHardwareMonitor already installed: {info}")
        sys.exit(0)
    inst = Installer()
    inst.run()
    sys.exit(0 if inst.state["ok"] else 1)
