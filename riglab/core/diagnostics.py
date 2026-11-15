"""Health check: explains why a sensor or feature is missing and how to fix it."""
from __future__ import annotations

import subprocess
import sys
import webbrowser

from .tweaks import CREATE_NO_WINDOW, is_admin

IS_WIN = sys.platform == "win32"


def _service_exists(name: str) -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{name}"))
        return True
    except OSError:
        return False


def pawnio_installed() -> bool:
    return _service_exists("PawnIO")


def check(hub, rgb) -> list[dict]:
    """Each item: id, title, ok (True/False/None=info), detail, fix (action id or None), fix_label."""
    s = hub.latest.sensors.values()
    items: list[dict] = []

    def add(id_, title, ok, detail, fix=None, fix_label=None):
        items.append({"id": id_, "title": title, "ok": ok, "detail": detail, "fix": fix, "fix_label": fix_label})

    admin = is_admin()
    add("admin", "Running as administrator", admin,
        "Good." if admin else "Temperatures, power, voltages and fan control need admin rights.",
        None if admin else "restart_admin", "Restart as admin")

    lhm_status = hub.status.get("LibreHardwareMonitor", "unavailable")
    from .lhm_setup import installed_info
    inst = installed_info()
    ver = f" Installed: {inst}." if inst else " Not installed."
    title = "Detailed sensor library (LibreHardwareMonitor)"
    if lhm_status == "active":
        add("lhm", title, True, f"Loaded.{ver}", "redownload_lhm", "Re-download")
    elif lhm_status in ("starting", "updating"):
        add("lhm", title, None, "Starting up… (can take up to a minute the first time)")
    else:
        add("lhm", title, False, f"Not loaded: {lhm_status}.{ver}", "redownload_lhm", "Re-download")
        items[-1]["trace"] = (hub.lhm.info or {}).get("trace")
        if "coreclr" in (inst or "") and ".NET" in lhm_status:
            add("dotnet", ".NET runtime", False, "This LibreHardwareMonitor build needs the .NET runtime.",
                "install_dotnet", "Install .NET")

    pawn = pawnio_installed()
    add("pawnio", "PawnIO driver", pawn,
        "Installed." if pawn else "Needed for CPU temperature/power, motherboard sensors and motherboard fan "
                                  "control. LibreHardwareMonitor can't read these without it.",
        None if pawn else "install_pawnio", "Install PawnIO")

    has = lambda pred: any(pred(x) for x in s)  # noqa: E731
    cpu_t = has(lambda x: x.hw_type == "Cpu" and x.kind == "Temperature" and x.value is not None)
    cpu_p = has(lambda x: x.hw_type == "Cpu" and x.kind == "Power" and x.value is not None)
    if cpu_t:
        detail = "Reading." if cpu_p else "Temperature OK; this CPU doesn't report package power."
    else:
        detail = ("Needs: LibreHardwareMonitor loaded + admin + PawnIO. If all three are OK, your CPU may be "
                  "too new for this LHM version - try Re-download (gets the latest nightly).")
    add("cpu_temp", "CPU temperature & power", cpu_t, detail)

    gpu = has(lambda x: x.hw_type.startswith("Gpu") and x.kind == "Temperature" and x.value is not None)
    nv = hub.status.get("NVIDIA NVML", "")
    add("gpu", "Graphics card sensors", gpu,
        "Reading." if gpu else "No GPU temperature yet. NVIDIA/AMD/Intel GPUs are read through "
                               "LibreHardwareMonitor (no admin needed) - fix that first. "
                               f"NVIDIA driver check: {nv}")

    fans = [x for x in s if x.controllable]
    mobo_fans = [x for x in fans if not x.id.startswith("/liquidctl/")]
    hub_fans = [x for x in fans if x.id.startswith("/liquidctl/")]
    lq = hub.status.get("liquidctl (fan hubs / AIOs)", "")
    add("fans_mobo", "Motherboard fan headers", bool(mobo_fans) or None,
        f"{len(mobo_fans)} controllable." if mobo_fans else
        "None controllable. Needs LibreHardwareMonitor + admin + PawnIO, and a motherboard fan chip LHM "
        "supports. Fans plugged into a USB hub (Corsair Commander etc.) are listed separately below.")
    add("fans_hub", "USB fan hubs / AIOs (Corsair Commander Core/XT/ST/Pro, NZXT…)", bool(hub_fans) or None,
        (f"{len(hub_fans)} channels controllable via liquidctl." + (
            f" Left alone: {'; '.join(hub.liquid.skipped)}." if hub.liquid.skipped else "")) if hub_fans else
        f"{lq}. Corsair iCUE LINK hubs aren't supported by liquidctl yet - those need iCUE or FanControl "
        "with the CorsairLink plugin. Close iCUE if it's running; it locks the hub.",
        "rescan_hubs", "Rescan")

    if rgb.client:
        add("openrgb", "Lighting service", True, f"Running - {len(rgb.devices)} RGB devices, {rgb.stats.get('leds', 0)} LEDs streaming.")
    elif rgb.host.status == "missing":
        add("openrgb", "Lighting service", False, "RigLab drives RGB through OpenRGB's device drivers, and OpenRGB "
            "wasn't found. Use Download OpenRGB below, or point RigLab to OpenRGB.exe on the Lighting page.",
            "open_openrgb", "Download OpenRGB")
    else:
        add("openrgb", "Lighting service", None, (rgb.host.error or rgb.msg or "Starting…"), "connect_openrgb", "Restart")
    return items


def fix(action: str, hub) -> str:
    if action == "restart_admin":
        return "restart_admin"  # handled by the app (needs to relaunch itself)
    if action == "install_pawnio":
        r = subprocess.run(["winget", "install", "--id", "namazso.PawnIO", "-e", "--accept-source-agreements",
                            "--accept-package-agreements"], capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0:
            webbrowser.open("https://pawnio.eu")
            return "Opened pawnio.eu - install it, then restart RigLab."
        return "PawnIO installed. Restart RigLab (or your PC if it asks)."
    if action == "install_dotnet":
        # visible console so any prompts can be answered
        subprocess.Popen(["cmd", "/c", "start", "Install .NET", "cmd", "/k",
                          "winget install --id Microsoft.DotNet.Runtime.10 -e --accept-source-agreements "
                          "--accept-package-agreements && echo. && echo Done - restart RigLab."])
        return "Installer opened in a new window."
    if action == "retry_lhm":
        hub.start_lhm()
        return "Reloading sensors…"
    if action == "rescan_hubs":
        hub.liquid.stop()
        if hub.liquid in hub.active:
            hub.active.remove(hub.liquid)
        ok = hub._start_backend(hub.liquid)
        return "Found hub(s)." if ok else hub.liquid.error or "Nothing found."
    if action == "open_openrgb":
        webbrowser.open("https://openrgb.org")
        return "Opened openrgb.org"
    return "Unknown action"
