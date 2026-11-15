"""Static hardware inventory (what's in the box).

On Windows this asks WMI/CIM through one PowerShell call so no extra packages are needed.
Elsewhere it falls back to whatever psutil/platform can tell us.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys

import psutil

from .hw import _cpu_name, fmt_bytes

CREATE_NO_WINDOW = 0x08000000

PS_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$o = [ordered]@{}
$o.cpu   = Get-CimInstance Win32_Processor | Select Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,L2CacheSize,L3CacheSize,SocketDesignation,VirtualizationFirmwareEnabled
$o.board = Get-CimInstance Win32_BaseBoard | Select Manufacturer,Product,Version,SerialNumber
$o.bios  = Get-CimInstance Win32_BIOS | Select Manufacturer,SMBIOSBIOSVersion,ReleaseDate
$o.ram   = Get-CimInstance Win32_PhysicalMemory | Select BankLabel,DeviceLocator,Manufacturer,PartNumber,Capacity,Speed,ConfiguredClockSpeed,SMBIOSMemoryType
$o.gpu   = Get-CimInstance Win32_VideoController | Select Name,DriverVersion,DriverDate,AdapterRAM,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate,VideoProcessor
$o.disk  = Get-PhysicalDisk | Select FriendlyName,MediaType,BusType,Size,HealthStatus,OperationalStatus,SerialNumber,FirmwareVersion,DeviceId
$o.os    = Get-CimInstance Win32_OperatingSystem | Select Caption,Version,BuildNumber,OSArchitecture,InstallDate,LastBootUpTime
$o.net   = Get-CimInstance Win32_NetworkAdapter -Filter 'PhysicalAdapter=True' | Select Name,MACAddress,Speed,NetEnabled
$o.audio = Get-CimInstance Win32_SoundDevice | Select Name,Manufacturer,Status
$o.monitors = Get-CimInstance -Namespace root\wmi WmiMonitorID | ForEach-Object {
    [ordered]@{ Name = (($_.UserFriendlyName | ? {$_ -ne 0} | % {[char]$_}) -join '');
                Maker = (($_.ManufacturerName | ? {$_ -ne 0} | % {[char]$_}) -join '') } }
$o | ConvertTo-Json -Depth 4 -Compress
"""

MEM_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 35: "LPDDR5"}


def run_powershell(script: str, timeout: int = 60) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return r.stdout


def _list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def collect() -> dict[str, list[tuple[str, str]] | list[dict]]:
    """Returns {section: [ {field: value, ...}, ... ]} ready for display."""
    if sys.platform == "win32":
        try:
            raw = json.loads(run_powershell(PS_QUERY) or "{}")
            return _format_windows(raw)
        except Exception as e:  # noqa: BLE001
            info = _generic()
            info["Errors"] = [{"WMI query failed": str(e)}]
            return info
    return _generic()


def _format_windows(raw: dict) -> dict:
    out: dict[str, list[dict]] = {}
    out["Processor"] = [{
        "Model": c.get("Name", "").strip(),
        "Cores / Threads": f"{c.get('NumberOfCores')} / {c.get('NumberOfLogicalProcessors')}",
        "Max clock": f"{c.get('MaxClockSpeed')} MHz",
        "L2 / L3 cache": f"{(c.get('L2CacheSize') or 0) // 1024} MB / {(c.get('L3CacheSize') or 0) // 1024} MB",
        "Socket": c.get("SocketDesignation"),
        "Virtualization": "Enabled" if c.get("VirtualizationFirmwareEnabled") else "Disabled",
    } for c in _list(raw.get("cpu"))]

    out["Motherboard"] = [{
        "Manufacturer": b.get("Manufacturer"), "Model": b.get("Product"), "Revision": b.get("Version"),
    } for b in _list(raw.get("board"))]
    for b in _list(raw.get("bios")):
        out["Motherboard"].append({"BIOS": f"{b.get('Manufacturer')} {b.get('SMBIOSBIOSVersion')}",
                                   "BIOS date": str(b.get("ReleaseDate", ""))[:10]})

    sticks = _list(raw.get("ram"))
    total = sum(int(s.get("Capacity") or 0) for s in sticks)
    rated = max((s.get("Speed") or 0 for s in sticks), default=0)
    running = max((s.get("ConfiguredClockSpeed") or 0 for s in sticks), default=0)
    summary = {"Total": fmt_bytes(total), "Sticks": str(len(sticks)),
               "Type": MEM_TYPES.get(sticks[0].get("SMBIOSMemoryType"), "Unknown") if sticks else "—",
               "Rated speed": f"{rated} MT/s", "Running speed": f"{running} MT/s"}
    if rated and running and running < rated * 0.8:
        summary["⚠ Note"] = "RAM is running well below its rated speed - XMP/EXPO is probably off in BIOS"
    out["Memory"] = [summary] + [{
        "Slot": s.get("DeviceLocator") or s.get("BankLabel"),
        "Size": fmt_bytes(int(s.get("Capacity") or 0)),
        "Maker / Part": f"{(s.get('Manufacturer') or '').strip()} {(s.get('PartNumber') or '').strip()}",
        "Speed": f"{s.get('ConfiguredClockSpeed')} / {s.get('Speed')} MT/s",
    } for s in sticks]

    out["Graphics"] = [{
        "Model": g.get("Name"),
        "Driver": f"{g.get('DriverVersion')} ({str(g.get('DriverDate', ''))[:10]})",
        "Display": (f"{g.get('CurrentHorizontalResolution')}x{g.get('CurrentVerticalResolution')} @ "
                    f"{g.get('CurrentRefreshRate')} Hz") if g.get("CurrentHorizontalResolution") else "—",
    } for g in _list(raw.get("gpu"))]

    out["Storage"] = [{
        "Drive": d.get("FriendlyName"),
        "Type": f"{_media(d.get('MediaType'))} ({_bus(d.get('BusType'))})",
        "Size": fmt_bytes(int(d.get("Size") or 0)),
        "Health": d.get("HealthStatus") if isinstance(d.get("HealthStatus"), str) else
        {0: "Healthy", 1: "Warning", 2: "Unhealthy"}.get(d.get("HealthStatus"), "Unknown"),
        "Firmware": d.get("FirmwareVersion"),
    } for d in _list(raw.get("disk"))]
    for p in psutil.disk_partitions():
        try:
            u = psutil.disk_usage(p.mountpoint)
            out["Storage"].append({"Volume": p.mountpoint, "File system": p.fstype,
                                   "Used": f"{fmt_bytes(u.used)} of {fmt_bytes(u.total)} ({u.percent:.0f}%)"})
        except OSError:
            pass

    out["Displays"] = [{"Monitor": m.get("Name") or "Unknown", "Maker code": m.get("Maker")}
                       for m in _list(raw.get("monitors"))]
    out["Network"] = [{"Adapter": n.get("Name"), "MAC": n.get("MACAddress"),
                       "Link": f"{int(n['Speed']) // 1_000_000} Mbps" if n.get("Speed") and n.get("NetEnabled") else "Disconnected"}
                      for n in _list(raw.get("net"))]
    out["Audio"] = [{"Device": a.get("Name"), "Status": a.get("Status")} for a in _list(raw.get("audio"))]
    for o in _list(raw.get("os")):
        out["System"] = [{"OS": o.get("Caption"), "Build": f"{o.get('Version')} ({o.get('OSArchitecture')})",
                          "Uptime": _uptime()}]
    return out


def _media(v):
    return {3: "HDD", 4: "SSD", 5: "SCM", 0: "Unspecified"}.get(v, v if isinstance(v, str) else "Unknown")


def _bus(v):
    return {7: "USB", 11: "SATA", 17: "NVMe", 8: "RAID", 1: "SCSI"}.get(v, v if isinstance(v, str) else "Other")


def _uptime() -> str:
    import time
    s = int(time.time() - psutil.boot_time())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    return f"{d}d {h}h {s // 60}m"


def _generic() -> dict:
    vm = psutil.virtual_memory()
    f = psutil.cpu_freq()
    out = {
        "Processor": [{"Model": _cpu_name(),
                       "Cores / Threads": f"{psutil.cpu_count(False)} / {psutil.cpu_count()}",
                       "Max clock": f"{f.max:.0f} MHz" if f and f.max else "—"}],
        "Memory": [{"Total": fmt_bytes(vm.total)}],
        "System": [{"OS": f"{platform.system()} {platform.release()}", "Uptime": _uptime()}],
        "Storage": [],
    }
    for p in psutil.disk_partitions():
        try:
            u = psutil.disk_usage(p.mountpoint)
            out["Storage"].append({"Volume": p.mountpoint, "File system": p.fstype,
                                   "Used": f"{fmt_bytes(u.used)} of {fmt_bytes(u.total)}"})
        except OSError:
            pass
    return out


def drive_health() -> list[dict]:
    """S.M.A.R.T.-style reliability counters via Storage cmdlets (admin gives more fields)."""
    if sys.platform != "win32":
        return []
    script = r"""
$ErrorActionPreference='SilentlyContinue'
Get-PhysicalDisk | ForEach-Object {
  $r = $_ | Get-StorageReliabilityCounter
  [ordered]@{ Name=$_.FriendlyName; Health=[string]$_.HealthStatus; Media=[string]$_.MediaType;
    Temp=$r.Temperature; TempMax=$r.TemperatureMax; Wear=$r.Wear; PowerOnHours=$r.PowerOnHours;
    ReadErrors=$r.ReadErrorsUncorrected; WriteErrors=$r.WriteErrorsUncorrected;
    StartStop=$r.StartStopCycleCount; Size=$_.Size }
} | ConvertTo-Json -Depth 3 -Compress
"""
    try:
        data = _list(json.loads(run_powershell(script) or "[]"))
    except Exception:  # noqa: BLE001
        return []
    for d in data:
        verdict, notes = "Good", []
        if d.get("Health") not in (None, "Healthy", "0"):
            verdict = "Bad"
            notes.append(f"Windows reports health: {d.get('Health')}")
        if (d.get("Wear") or 0) >= 80:
            verdict = "Bad" if d["Wear"] >= 95 else "Caution"
            notes.append(f"SSD wear at {d['Wear']}% of rated life")
        if (d.get("ReadErrors") or 0) > 0 or (d.get("WriteErrors") or 0) > 0:
            verdict = "Caution" if verdict == "Good" else verdict
            notes.append("Uncorrected read/write errors logged - back up this drive")
        if (d.get("Temp") or 0) >= 65:
            notes.append("Running hot")
        d["Verdict"] = verdict
        d["Notes"] = "; ".join(notes) or "No problems found"
    return data
