"""GPU setup check: find the card, recommend drivers, and get everything the tuning sliders need in place.

check() runs these steps and reports each one as ok / warn / bad, with a fix action where RigLab can fix it:
  1. detect     - which graphics card(s) are installed (PCI vendor id via Windows)
  2. driver     - installed driver version vs. the newest one the vendor offers for this exact card
                  (NVIDIA: NVIDIA's own driver lookup service; AMD / Intel: their update tools)
  3. admin      - tuning needs administrator rights
  4. interface  - the driver's tuning interface loads (NVML for NVIDIA, ADLX for AMD)
  5. controls   - every control is read AND written back with its current value (a no-op) to prove the
                  driver really accepts changes from RigLab
  6. fps        - PresentMon is available for FPS in third-party benchmarks
  7. fallback   - when the driver refuses some controls, MSI Afterburner is offered (works on every card)

fix(action) runs a fix in the background; job() reports its progress.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import gputune, presentmon
from .config import app_dir

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 RigLab"}
NV_PRODUCTS = "https://www.nvidia.com/Download/API/lookupValueSearch.aspx?TypeID=3"
NV_LOOKUP = ("https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/AjaxDriverService.php"
             "?func=DriverManualLookup&psid={psid}&pfid={pfid}&osID={os}&languageCode=1033&beta=0&isWHQL=1"
             "&dltype=-1&dch=1&upCRD=0&qnf=0&sort1=0&numberOfResults=1")
PAGES = {"nvidia": "https://www.nvidia.com/en-us/drivers/", "amd": "https://www.amd.com/en/support/download/drivers.html",
         "intel": "https://www.intel.com/content/www/us/en/support/detect.html"}
AFTERBURNER = [r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe", r"C:\Program Files\MSI Afterburner\MSIAfterburner.exe"]
NO_WRITE_PROBE = {"core_cap", "fan_manual", "fan_speed", "zero_rpm", "fan_min", "fan_target", "fan_acoustic"}


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _get(url, timeout=20) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def nv_version_from_wmi(v: str | None) -> str | None:
    """Windows reports NVIDIA drivers as e.g. 32.0.15.8157 -> 581.57."""
    if not v:
        return None
    digits = "".join(v.split(".")[-2:])
    if len(digits) < 5:
        return None
    d = digits[-5:]
    return f"{int(d[:3])}.{d[3:]}"


def _vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0"))[:3])


# ======================================================================== latest drivers
def nvidia_latest(name: str) -> dict | None:
    """Newest Game Ready (WHQL) driver for this exact card, straight from NVIDIA."""
    clean = re.sub(r"^NVIDIA\s+", "", name, flags=re.I).strip()
    cache = app_dir() / "nv_products.xml"
    if not cache.exists() or time.time() - cache.stat().st_mtime > 7 * 86400:
        cache.write_bytes(_get(NV_PRODUCTS))
    root = ET.fromstring(cache.read_bytes())
    match = None
    for v in root.iter("LookupValue"):
        n = (v.findtext("Name") or "").strip()
        if n.lower() == clean.lower():
            match = v
            break
    if match is None:
        return None
    psid, pfid = match.get("ParentID"), match.findtext("Value")
    try:
        build = sys.getwindowsversion().build
    except AttributeError:
        build = 22000
    os_id = 135 if build >= 22000 else 57                       # Windows 11 / Windows 10 64-bit
    data = json.loads(_get(NV_LOOKUP.format(psid=psid, pfid=pfid, os=os_id)))
    info = (data.get("IDS") or [{}])[0].get("downloadInfo") or {}
    if not info.get("Version"):
        return None
    return {"version": info["Version"], "url": info.get("DownloadURL"), "date": info.get("ReleaseDateTime"),
            "size": info.get("DownloadURLFileSize"), "name": urllib.request.unquote(info.get("Name") or "Game Ready Driver")}


# ======================================================================== the check
def check(tuner: gputune.GpuTuner, online: bool = True) -> dict:
    steps = []

    def add(sid, title, state, text, action=None, label=None, **extra):
        steps.append(dict(id=sid, title=title, state=state, text=text, action=action, label=label, **extra))

    gpus = gputune.detect_gpus()
    tuner.gpus = gpus or tuner.gpus
    if not gpus:
        add("detect", "Graphics card", "bad", "Windows didn't report any graphics card.", None)
        return {"steps": steps, "ready": False}
    g = gpus[min(tuner.selected, len(gpus) - 1)]
    vendor = g["vendor"]
    add("detect", "Graphics card", "ok", f"{g['name']} ({vendor.upper() if vendor != 'other' else 'unknown vendor'})"
        + (f" - plus {len(gpus) - 1} more" if len(gpus) > 1 else ""), gpu=g)

    # ---- driver
    installed = nv_version_from_wmi(g.get("driver")) if vendor == "nvidia" else g.get("driver")
    if vendor == "nvidia":
        latest = None
        if online:
            try:
                latest = nvidia_latest(g["name"])
            except Exception as e:  # noqa: BLE001
                log.warning("NVIDIA lookup failed: %s", e)
        if latest and _vtuple(latest["version"]) > _vtuple(installed):
            add("driver", "Driver", "warn", f"Installed {installed}. NVIDIA's newest for your card is {latest['version']} "
                f"({(latest.get('date') or '')[:30]}). Newer drivers fix tuning bugs and add support.",
                "install_nvidia", f"Download & install {latest['version']}", latest=latest)
        elif latest:
            add("driver", "Driver", "ok", f"{installed} - the newest for your card.")
        else:
            add("driver", "Driver", "warn" if online else "ok", f"Installed {installed or 'unknown'}. "
                + ("Couldn't check NVIDIA for a newer one right now." if online else ""), "open_page", "Open NVIDIA drivers")
    elif vendor == "amd":
        add("driver", "Driver", "ok" if installed else "bad", f"Installed {installed or 'none found'}. AMD Adrenalin's own "
            "updater checks for newer versions (Adrenalin → Settings → System → Check for updates).", "open_page", "Open AMD drivers")
    elif vendor == "intel":
        add("driver", "Driver", "ok", f"Installed {installed or 'unknown'}. Intel's Driver & Support Assistant keeps it current.",
            "install_intel_dsa", "Install Intel Driver Assistant")

    # ---- admin
    add("admin", "Administrator rights", "ok" if is_admin() else "bad",
        "RigLab runs as administrator." if is_admin() else "Tuning needs administrator rights. Close RigLab and start it again from its shortcut (Windows asks for permission).")

    # ---- interface + controls
    tuner.detect(force=True)
    st = tuner.state()
    caps = st.get("caps") or {}
    if st["backend"] in ("nvml", "adlx"):
        add("interface", "Tuning interface", "ok", st["backend_label"] + f" - {len(caps)} controls found.")
    elif vendor == "nvidia":
        add("interface", "Tuning interface", "bad", f"NVIDIA's tuning interface (NVML) didn't load: {st.get('error') or 'unknown error'}. "
            "It comes with the NVIDIA driver - (re)installing the driver fixes it.", "install_nvidia", "Install NVIDIA driver")
    elif vendor == "amd":
        add("interface", "Tuning interface", "bad", f"AMD's tuning interface (ADLX) didn't load: {st.get('error') or 'unknown error'}. "
            "It comes with AMD Software: Adrenalin Edition.", "open_page", "Get AMD Adrenalin")
    else:
        add("interface", "Tuning interface", "warn", st.get("note") or "No tuning interface for this card.")

    refused = []
    if caps:
        results = {}
        for key, c in caps.items():
            if not isinstance(c, dict) or c.get("value") is None:
                continue
            if key in NO_WRITE_PROBE or "min" not in c:
                results[key] = "ok (not write-tested)"
                continue
            r = tuner.call("apply", {key: c["value"]}) or {}
            results[key] = r.get(key, tuner.error or "no answer")
        bad = {k: v for k, v in results.items() if not str(v).startswith("ok")}
        refused = list(bad)
        if bad:
            add("controls", "Controls", "warn", "The driver refused: " + ", ".join(f"{caps[k].get('label', k)} ({v})" for k, v in bad.items())
                + ". The other sliders work. MSI Afterburner can usually still change these.", "install_afterburner",
                "Install MSI Afterburner", results=results)
        else:
            add("controls", "Controls", "ok", "Every slider was tested and the driver accepts changes: "
                + ", ".join(c.get("label", k) for k, c in caps.items() if isinstance(c, dict)) + ".", results=results)
    elif st["backend"] in ("nvml", "adlx"):
        add("controls", "Controls", "bad", f"The driver loaded but offered no tuning controls ({st.get('error') or 'no detail'}). "
            "This usually means the driver is too old.", "install_nvidia" if vendor == "nvidia" else "open_page", "Update driver")

    # ---- FPS capture
    pm = presentmon.exe_path().exists()
    add("fps", "FPS capture (PresentMon)", "ok" if pm else "warn",
        "Ready for third-party benchmarks and games." if pm else "Not downloaded yet - needed for FPS in third-party benchmarks.",
        None if pm else "get_presentmon", None if pm else "Download PresentMon")

    # ---- fallback tool
    ab = next((p for p in AFTERBURNER if Path(p).exists()), None)
    if refused or vendor not in ("nvidia", "amd"):
        add("afterburner", "MSI Afterburner (optional)", "ok" if ab else "warn",
            "Installed - use it for the controls the driver refused here." if ab else
            "Not installed. Optional: works on every NVIDIA/AMD card for anything RigLab can't change directly.",
            "open_afterburner" if ab else "install_afterburner", "Open Afterburner" if ab else "Install MSI Afterburner")

    ready = bool(caps) and not any(s["state"] == "bad" for s in steps)
    out = {"steps": steps, "ready": ready, "gpu": g, "time": time.time()}
    (app_dir() / "gpu_setup.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    log.info("GPU setup check: %s", [(s["id"], s["state"], s["text"][:120]) for s in steps])
    return out


# ======================================================================== fixes (background jobs)
class Fixer:
    def __init__(self):
        self.job: dict = {}

    def status(self):
        return dict(self.job)

    def run(self, action: str, data: dict | None = None):
        if self.job.get("running"):
            return {"error": "Another fix is still running"}
        self.job = {"action": action, "running": True, "msg": "Starting…", "pct": None, "ok": None}
        threading.Thread(target=self._run, args=(action, data or {}), daemon=True, name="GpuFix").start()
        return {"ok": True}

    def _say(self, msg, pct=None):
        self.job.update(msg=msg, pct=pct)

    def _run(self, action, data):
        try:
            ok, msg = getattr(self, "_" + action)(data)
        except Exception as e:  # noqa: BLE001
            log.exception("gpu fix %s failed", action)
            ok, msg = False, str(e)
        self.job.update(running=False, ok=ok, msg=msg, pct=None)

    def _download(self, url, dest: Path):
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, open(dest, "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                self._say(f"Downloading… {done / 2**20:.0f} / {total / 2**20:.0f} MB" if total else f"Downloading… {done / 2**20:.0f} MB",
                          round(done / total * 100) if total else None)

    def _install_nvidia(self, data):
        latest = data.get("latest")
        if not latest:
            gpus = [g for g in gputune.detect_gpus() if g["vendor"] == "nvidia"]
            latest = nvidia_latest(gpus[0]["name"]) if gpus else None
        if not latest or not latest.get("url"):
            _open(PAGES["nvidia"])
            return False, "Couldn't find the driver automatically - opened NVIDIA's driver page instead."
        dest = Path(tempfile.gettempdir()) / f"nvidia-{latest['version']}.exe"
        if not dest.exists() or dest.stat().st_size < 50 * 2**20:
            self._download(latest["url"], dest)
        self._say("Starting the NVIDIA installer…")
        subprocess.Popen([str(dest)], cwd=str(dest.parent))
        return True, (f"NVIDIA installer {latest['version']} started. Choose Express installation; the screen flickers while it "
                      "installs. Run the setup check again afterwards.")

    def _get_presentmon(self, data):
        p = presentmon.ensure(progress=self._say)
        return (True, "PresentMon is ready.") if p else (False, "Couldn't download PresentMon - check your internet connection.")

    def _winget(self, pkg, name):
        self._say(f"Installing {name} with winget…")
        r = subprocess.run(["winget", "install", "-e", "--id", pkg, "--accept-source-agreements", "--accept-package-agreements",
                            "--silent"], capture_output=True, text=True, timeout=900, creationflags=0x08000000)
        tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
        return (r.returncode == 0 or "already installed" in (r.stdout or "").lower()), f"{name}: {tail[0] or ('done' if r.returncode == 0 else 'failed')}"

    def _install_afterburner(self, data):
        return self._winget("Guru3D.Afterburner", "MSI Afterburner")

    def _install_intel_dsa(self, data):
        return self._winget("Intel.IntelDriverAndSupportAssistant", "Intel Driver & Support Assistant")

    def _open_afterburner(self, data):
        p = next((p for p in AFTERBURNER if Path(p).exists()), None)
        if not p:
            return False, "MSI Afterburner isn't installed."
        subprocess.Popen([p])
        return True, "MSI Afterburner opened."

    def _open_page(self, data):
        _open(PAGES.get(data.get("vendor") or "nvidia"))
        return True, "Opened the driver page in your browser."


def _open(url):
    if sys.platform == "win32":
        os.startfile(url)  # noqa: S606
