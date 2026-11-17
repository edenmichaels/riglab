"""Windows tweaks, power plans, startup manager and cleanup.

Everything here is reversible from inside the app. Tweaks that touch the system ask for a
restore point first (Tweaks page does that automatically once per session).
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

IS_WIN = sys.platform == "win32"
if IS_WIN:
    import winreg
CREATE_NO_WINDOW = 0x08000000


def is_admin() -> bool:
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW if IS_WIN else 0)


# ---------------------------------------------------------------- registry helpers
def reg_get(root, path: str, name: str, default=None):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def reg_set(root, path: str, name: str, value, kind=None):
    kind = kind if kind is not None else (winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ)
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


# ---------------------------------------------------------------- restore point
def create_restore_point(desc: str = "RigLab tweaks") -> tuple[bool, str]:
    if not IS_WIN:
        return False, "Windows only"
    r = run(["powershell", "-NoProfile", "-Command",
             f"Checkpoint-Computer -Description '{desc}' -RestorePointType MODIFY_SETTINGS"], timeout=180)
    if r.returncode == 0:
        return True, "Restore point created"
    msg = (r.stderr or r.stdout).strip()
    if "1440" in msg or "frequency" in msg.lower():
        return True, "Windows already made a restore point in the last 24h (that one covers you)"
    if "disabled" in msg.lower() or "0x80042306" in msg:
        return False, "System Protection is off for C:. Turn it on in 'Create a restore point' to enable this."
    return False, msg[:300] or "Failed (needs admin)"


SPP_CLIENTS = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SPP\Clients"
SPP_SYSTEM = "{09F7EDC5-294E-4180-AF6A-FB0E6A0E9513}"     # the "System Protection" client
SR_POLICY = r"SOFTWARE\Policies\Microsoft\Windows NT\SystemRestore"


def restore_status() -> dict:
    """{"enabled": True/False/None (unknown), "policy_off": bool, "latest": {"time", "desc"} or None}."""
    if not IS_WIN:
        return {"enabled": None, "policy_off": False, "latest": None}
    drive = os.environ.get("SYSTEMDRIVE", "C:").rstrip("\\").upper()      # e.g. "C:"
    vols = reg_get(winreg.HKEY_LOCAL_MACHINE, SPP_CLIENTS, SPP_SYSTEM)
    if vols is None:
        try:
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SPP_CLIENTS).Close()
            enabled = False            # the list exists but the Windows drive isn't in it
        except OSError:
            enabled = None             # can't tell - RigLab will just try
    else:
        vols = vols if isinstance(vols, list) else [str(vols)]
        enabled = any(f"({drive.replace(':', '%3A')})" in v.upper() for v in vols)
    policy_off = reg_get(winreg.HKEY_LOCAL_MACHINE, SR_POLICY, "DisableSR", 0) == 1
    latest = None
    try:
        r = run(["powershell", "-NoProfile", "-Command",
                 "Get-ComputerRestorePoint -ErrorAction Stop | Sort-Object SequenceNumber | Select-Object -Last 1 "
                 "Description,CreationTime | ConvertTo-Json -Compress"], timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            import json
            p = json.loads(r.stdout)
            latest = {"time": p.get("CreationTime"), "desc": p.get("Description")}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if latest and enabled is None:
        enabled = True
    return {"enabled": enabled, "policy_off": policy_off, "latest": latest}


def enable_restore() -> tuple[bool, str]:
    """Turn System Protection on for the Windows drive (same as ticking it in 'Create a restore point')."""
    if not IS_WIN:
        return False, "Windows only"
    r = run(["powershell", "-NoProfile", "-Command", 'Enable-ComputerRestore -Drive "$env:SystemDrive\\"'], timeout=120)
    if r.returncode == 0 and restore_status()["enabled"] is not False:
        return True, "Restore points are now switched on"
    return False, ((r.stderr or r.stdout).strip()[:300] or "Windows refused (RigLab needs to run as administrator)")


# ---------------------------------------------------------------- power plans
ULTIMATE_GUID = "e9a42b02-d5df-448d-aa00-03f14749eb61"
# Windows' built-in plans have the same GUID on every PC (their names are translated, so match by GUID)
PLAN_GUIDS = {"high": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
              "saver": "a1841308-3542-4f79-b6ab-2f2e9fdb7f9d", "ultimate": ULTIMATE_GUID}


def power_plans() -> list[dict]:
    if not IS_WIN:
        return []
    out = run(["powercfg", "/list"]).stdout
    plans = []
    for m in re.finditer(r"GUID:\s*([0-9a-f-]{36})\s+\((.+?)\)\s*(\*)?", out, re.I):
        plans.append({"guid": m.group(1), "name": m.group(2), "active": bool(m.group(3))})
    return plans


def set_power_plan(guid: str) -> bool:
    return run(["powercfg", "/setactive", guid]).returncode == 0


def add_ultimate_plan() -> bool:
    if any("ultimate" in p["name"].lower() for p in power_plans()):
        return True
    return run(["powercfg", "-duplicatescheme", ULTIMATE_GUID]).returncode == 0


# ---------------------------------------------------------------- toggle tweaks
@dataclass
class Tweak:
    id: str
    name: str
    description: str
    get: Callable[[], bool | None]
    set: Callable[[bool], None]
    needs_admin: bool = False
    needs_reboot: bool = False
    category: str = "Gaming"


def _game_mode_get():
    return reg_get(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1) == 1


def _game_mode_set(on: bool):
    reg_set(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1 if on else 0)


HAGS = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers"


def _hags_get():
    v = reg_get(winreg.HKEY_LOCAL_MACHINE, HAGS, "HwSchMode")
    return None if v is None else v == 2


def _hags_set(on: bool):
    reg_set(winreg.HKEY_LOCAL_MACHINE, HAGS, "HwSchMode", 2 if on else 1)


def _mouse_accel_get():
    return reg_get(winreg.HKEY_CURRENT_USER, r"Control Panel\Mouse", "MouseSpeed", "1") != "0"


def _mouse_accel_set(on: bool):
    vals = ("1", "6", "10") if on else ("0", "0", "0")
    for name, v in zip(("MouseSpeed", "MouseThreshold1", "MouseThreshold2"), vals):
        reg_set(winreg.HKEY_CURRENT_USER, r"Control Panel\Mouse", name, v, winreg.REG_SZ)
    arr = (ctypes.c_int * 3)(int(vals[1]), int(vals[2]), int(vals[0]))
    ctypes.windll.user32.SystemParametersInfoW(0x0004, 0, arr, 0x01 | 0x02)  # SPI_SETMOUSE, apply live


GAMEDVR = r"System\GameConfigStore"


def _gamedvr_get():
    return reg_get(winreg.HKEY_CURRENT_USER, GAMEDVR, "GameDVR_Enabled", 1) == 1


def _gamedvr_set(on: bool):
    reg_set(winreg.HKEY_CURRENT_USER, GAMEDVR, "GameDVR_Enabled", 1 if on else 0)
    reg_set(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
            "AppCaptureEnabled", 1 if on else 0)


VFX = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"


def _transparency_get():
    return reg_get(winreg.HKEY_CURRENT_USER,
                   r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 1) == 1


def _transparency_set(on: bool):
    reg_set(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "EnableTransparency", 1 if on else 0)


SYSPROF = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"


def _netthrottle_get():
    v = reg_get(winreg.HKEY_LOCAL_MACHINE, SYSPROF, "NetworkThrottlingIndex", 10)
    return v != 0xFFFFFFFF


def _netthrottle_set(on: bool):
    reg_set(winreg.HKEY_LOCAL_MACHINE, SYSPROF, "NetworkThrottlingIndex", 10 if on else 0xFFFFFFFF)


TOASTS = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"


def _toasts_get():
    return reg_get(winreg.HKEY_CURRENT_USER, TOASTS, "ToastEnabled", 1) == 1


def _toasts_set(on: bool):
    reg_set(winreg.HKEY_CURRENT_USER, TOASTS, "ToastEnabled", 1 if on else 0)


def all_tweaks() -> list[Tweak]:
    if not IS_WIN:
        return []
    return [
        Tweak("game_mode", "Windows Game Mode", "Prioritises the game you're playing and pauses Windows Update "
              "restarts while gaming. Recommended ON.", _game_mode_get, _game_mode_set),
        Tweak("hags", "Hardware-accelerated GPU scheduling", "Lets the GPU manage its own memory scheduling. Can "
              "lower latency on modern GPUs and is needed for DLSS Frame Generation. Recommended ON.",
              _hags_get, _hags_set, needs_admin=True, needs_reboot=True),
        Tweak("game_dvr", "Xbox Game Bar background recording", "Constantly records gameplay in the background so "
              "you can save clips. Costs a few FPS. Turn OFF if you don't use it.", _gamedvr_get, _gamedvr_set),
        Tweak("mouse_accel", "Mouse acceleration (Enhance pointer precision)", "Makes the cursor move further when "
              "you move the mouse fast. Most FPS players turn this OFF for consistent aim.",
              _mouse_accel_get, _mouse_accel_set, category="Input"),
        Tweak("notifications", "Notification banners", "Windows and app pop-up notifications (the switch at the top of "
              "Settings > System > Notifications). OFF stops banners appearing over games, streams and work.",
              _toasts_get, _toasts_set, category="Visual"),
        Tweak("transparency", "Transparency effects", "Windows blur/glass effects. Turning OFF frees a little GPU "
              "on low-end systems.", _transparency_get, _transparency_set, category="Visual"),
        Tweak("net_throttle", "Multimedia network throttling", "Windows limits non-media network traffic while "
              "audio/video plays. OFF can help online games on some PCs.", _netthrottle_get, _netthrottle_set,
              needs_admin=True, needs_reboot=True, category="Network"),
    ]


# ---------------------------------------------------------------- startup manager
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


@dataclass
class StartupItem:
    name: str
    command: str
    location: str           # human readable
    root: object            # HKCU / HKLM / None for folder
    approved_key: str       # StartupApproved subkey
    enabled: bool


def startup_items() -> list[StartupItem]:
    if not IS_WIN:
        return []
    items: list[StartupItem] = []
    sources = [
        (winreg.HKEY_CURRENT_USER, RUN, "Run", "Current user"),
        (winreg.HKEY_LOCAL_MACHINE, RUN, "Run", "All users"),
        (winreg.HKEY_LOCAL_MACHINE, RUN32, "Run32", "All users (32-bit)"),
    ]
    for root, path, approved, label in sources:
        try:
            with winreg.OpenKey(root, path) as k:
                i = 0
                while True:
                    try:
                        name, cmd, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    items.append(StartupItem(name, str(cmd), label, root, approved,
                                             _approved_state(root, approved, name)))
        except OSError:
            continue
    folders = [
        (Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
         winreg.HKEY_CURRENT_USER, "Startup folder (user)"),
        (Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
         winreg.HKEY_LOCAL_MACHINE, "Startup folder (all users)"),
    ]
    for folder, root, label in folders:
        if folder.is_dir():
            for f in folder.iterdir():
                if f.name.lower() == "desktop.ini":
                    continue
                items.append(StartupItem(f.name, str(f), label, root, "StartupFolder",
                                         _approved_state(root, "StartupFolder", f.name)))
    return items


def _approved_state(root, sub: str, name: str) -> bool:
    v = reg_get(root, f"{APPROVED}\\{sub}", name)
    if not v:
        return True
    return v[0] in (0x02, 0x06)   # 0x03 / 0x07 = disabled (same flags Task Manager writes)


def set_startup_enabled(item: StartupItem, enabled: bool):
    """Flip it exactly like Task Manager does - nothing is deleted."""
    data = bytes([0x02 if enabled else 0x03]) + bytes(11)
    if not enabled:  # store disable time like Task Manager
        ft = int((time.time() + 11644473600) * 10_000_000)
        data = bytes([0x03, 0, 0, 0]) + ft.to_bytes(8, "little")
    reg_set(item.root, f"{APPROVED}\\{item.approved_key}", item.name, data, winreg.REG_BINARY)
    item.enabled = enabled


# ---------------------------------------------------------------- junk cleanup
def temp_folders() -> list[Path]:
    dirs = [Path(os.environ.get("TEMP", "/tmp"))]
    if IS_WIN:
        dirs += [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Temp",
                 Path(os.environ.get("LOCALAPPDATA", "")) / r"NVIDIA\DXCache",
                 Path(os.environ.get("LOCALAPPDATA", "")) / r"AMD\DxCache",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "D3DSCache",
                 Path(os.environ.get("LOCALAPPDATA", "")) / r"CrashDumps"]
    return [d for d in dirs if d.is_dir()]


def scan_junk(min_age_hours: float = 24) -> tuple[int, int]:
    """(bytes, files) that cleanup would remove."""
    cutoff = time.time() - min_age_hours * 3600
    total = count = 0
    for d in temp_folders():
        for root, _, files in os.walk(d):
            for f in files:
                try:
                    st = os.stat(os.path.join(root, f))
                    if st.st_mtime < cutoff:
                        total += st.st_size
                        count += 1
                except OSError:
                    pass
    return total, count


def clean_junk(min_age_hours: float = 24) -> tuple[int, int]:
    """Deletes temp files older than min_age_hours. Files in use are skipped. Returns (bytes, files)."""
    cutoff = time.time() - min_age_hours * 3600
    freed = removed = 0
    for d in temp_folders():
        for root, dirs, files in os.walk(d, topdown=False):
            for f in files:
                p = os.path.join(root, f)
                try:
                    st = os.stat(p)
                    if st.st_mtime < cutoff:
                        os.remove(p)
                        freed += st.st_size
                        removed += 1
                except OSError:
                    pass
            for sub in dirs:
                try:
                    os.rmdir(os.path.join(root, sub))  # only removes if empty
                except OSError:
                    pass
    return freed, removed


def disk_free(path: str = "C:\\" if IS_WIN else "/") -> int:
    return shutil.disk_usage(path).free
