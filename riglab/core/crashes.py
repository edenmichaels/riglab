"""Crash Center: works out why the PC crashed.

Sources
  * Event Viewer (System + Application logs): blue screens, unexpected shutdowns, WHEA hardware errors,
    graphics driver resets, app crashes/hangs, disk errors
  * Reliability Monitor (Win32_ReliabilityRecords + stability index)
  * Dump files: C:\\Windows\\Minidump, MEMORY.DMP, LiveKernelReports (WATCHDOG etc.) - header parsed directly;
    full "!analyze -v" via Microsoft's debugger (cdb.exe from WinDbg) when it's installed
Related events within a few minutes are grouped into one "incident" with a plain-English explanation.
"""
from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import app_dir

IS_WIN = sys.platform == "win32"
NOWIN = 0x08000000 if IS_WIN else 0

# ---------------------------------------------------------------- bug check knowledge base
# code -> (name, plain English, likely causes, oc_related)
BUGCHECKS = {
    0x0A: ("IRQL_NOT_LESS_OR_EQUAL", "A driver touched memory it wasn't allowed to.",
           "Faulty or outdated driver; unstable RAM overclock/EXPO.", True),
    0x1A: ("MEMORY_MANAGEMENT", "Windows found corrupted memory-management data.",
           "Unstable RAM (EXPO/XMP, timings, SoC/VDD voltage) or failing RAM stick; sometimes a driver.", True),
    0x1E: ("KMODE_EXCEPTION_NOT_HANDLED", "A kernel driver crashed.", "Driver bug; unstable CPU/RAM.", True),
    0x3B: ("SYSTEM_SERVICE_EXCEPTION", "A system call crashed in the kernel.",
           "Graphics/anti-cheat/antivirus driver; unstable CPU undervolt or RAM.", True),
    0x50: ("PAGE_FAULT_IN_NONPAGED_AREA", "Invalid memory was referenced.",
           "Unstable RAM, faulty driver or antivirus.", True),
    0x7E: ("SYSTEM_THREAD_EXCEPTION_NOT_HANDLED", "A system thread crashed.", "Driver bug; unstable overclock.", True),
    0x7F: ("UNEXPECTED_KERNEL_MODE_TRAP", "The CPU hit an error the kernel couldn't handle.",
           "Unstable CPU/RAM overclock, overheating, hardware fault.", True),
    0x9F: ("DRIVER_POWER_STATE_FAILURE", "A driver didn't handle sleep/wake properly.",
           "Outdated driver (often USB, network, GPU).", False),
    0xC2: ("BAD_POOL_CALLER", "A driver misused kernel memory.", "Faulty driver.", False),
    0xC5: ("DRIVER_CORRUPTED_EXPOOL", "Kernel memory pool got corrupted.", "Faulty driver; unstable RAM.", True),
    0xD1: ("DRIVER_IRQL_NOT_LESS_OR_EQUAL", "A driver accessed bad memory at high priority.",
           "Network/Wi-Fi/USB/GPU driver bug; unstable RAM.", True),
    0xEF: ("CRITICAL_PROCESS_DIED", "A core Windows process stopped.", "Storage/driver issue, corrupted system files.", False),
    0xF4: ("CRITICAL_OBJECT_TERMINATION", "A critical process ended.", "Failing drive or cable, storage driver.", False),
    0x101: ("CLOCK_WATCHDOG_TIMEOUT", "A CPU core stopped responding.",
            "CPU undervolt / Curve Optimizer too aggressive, CPU overclock, or bad BIOS settings.", True),
    0x109: ("CRITICAL_STRUCTURE_CORRUPTION", "Kernel code or data was modified.",
            "Unstable RAM/CPU, or a driver (anti-cheat, tuning tools).", True),
    0x10E: ("VIDEO_MEMORY_MANAGEMENT_INTERNAL", "The graphics memory manager failed.", "GPU driver; unstable GPU VRAM OC.", True),
    0x113: ("VIDEO_DXGKRNL_FATAL_ERROR", "The DirectX graphics kernel failed.", "GPU driver.", False),
    0x116: ("VIDEO_TDR_FAILURE", "The graphics card stopped responding and couldn't be reset.",
            "GPU overclock/undervolt too aggressive, GPU driver, overheating, PSU.", True),
    0x117: ("VIDEO_TDR_TIMEOUT_DETECTED", "The graphics card stopped responding (recovered).",
            "GPU overclock/undervolt too aggressive, GPU driver.", True),
    0x119: ("VIDEO_SCHEDULER_INTERNAL_ERROR", "The GPU scheduler hit a fatal error.", "GPU driver; GPU OC.", True),
    0x124: ("WHEA_UNCORRECTABLE_ERROR", "The CPU reported a hardware error it couldn't correct.",
            "Unstable CPU overclock/undervolt, RAM/Infinity Fabric (FCLK) instability, SoC voltage, overheating.", True),
    0x133: ("DPC_WATCHDOG_VIOLATION", "A driver took too long at high priority.",
            "Storage (SATA/NVMe) or other driver/firmware; outdated SSD firmware.", False),
    0x139: ("KERNEL_SECURITY_CHECK_FAILURE", "The kernel detected corrupted data.", "Driver; unstable RAM.", True),
    0x13A: ("KERNEL_MODE_HEAP_CORRUPTION", "Kernel heap got corrupted.", "Driver (often GPU); unstable RAM.", True),
    0x141: ("VIDEO_ENGINE_TIMEOUT_DETECTED", "A GPU engine stopped responding (recovered).",
            "GPU overclock/undervolt, GPU driver.", True),
    0x154: ("UNEXPECTED_STORE_EXCEPTION", "Memory compression store failed.", "Drive or RAM problem.", True),
    0x15F: ("CONNECTED_STANDBY_WATCHDOG_TIMEOUT_LIVEDUMP", "Sleep took too long.", "Driver.", False),
    0x19C: ("WIN32K_POWER_WATCHDOG_TIMEOUT", "Display power state change stalled.", "GPU driver/monitor.", False),
    0x1A8: ("BUGCODE_WIFIADAPTER_DRIVER", "Wi-Fi driver issue (live report).", "Wi-Fi driver.", False),
    0x1B0: ("VIDEO_MINIPORT_FAILED_LIVEDUMP", "Graphics driver failure (live report).", "GPU driver/OC.", True),
    0x1C8: ("MANUALLY_INITIATED_POWER_BUTTON_HOLD", "Power button was held down.", "Manual hard reset.", False),
}


def bugcheck_info(code: int) -> dict:
    name, what, causes, oc = BUGCHECKS.get(code, (f"0x{code:X}", "Windows stopped to prevent damage.",
                                                  "Look up this stop code; analyse the dump for the driver.", False))
    return {"code": f"0x{code:X}", "name": name, "what": what, "causes": causes, "oc_related": oc}


# ---------------------------------------------------------------- dump files
DUMP_DIRS = [r"C:\Windows\Minidump", r"C:\Windows\LiveKernelReports"]
DUMP_FILES = [r"C:\Windows\MEMORY.DMP"]
DUMP_TYPES = {1: "Full", 2: "Kernel", 4: "Small (minidump)", 5: "Bitmap", 6: "Automatic", 7: "Active"}


def parse_dump_header(path: str | Path) -> dict:
    """Reads the 64-bit kernel dump header ('PAGEDU64'): stop code, parameters, build, CPU count, time."""
    p = Path(path)
    with open(p, "rb") as fh:
        h = fh.read(0x2000)
    if h[:8] != b"PAGEDU64":
        if h[:4] == b"MDMP":
            return {"kind": "user-mode dump", "valid": False}
        return {"kind": "unknown", "valid": False}
    code = struct.unpack_from("<I", h, 0x38)[0]
    params = struct.unpack_from("<4Q", h, 0x40)
    out = {"valid": True, "kind": "kernel", "code": code, "params": [f"0x{x:X}" for x in params],
           "build": struct.unpack_from("<I", h, 0x0C)[0], "cpus": struct.unpack_from("<I", h, 0x34)[0]}
    dtype = struct.unpack_from("<I", h, 0xF98)[0]
    out["dump_type"] = DUMP_TYPES.get(dtype, str(dtype))
    ft = struct.unpack_from("<Q", h, 0xFA8)[0]
    try:
        t = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ft // 10)
        if 2010 < t.year < 2100:
            out["time"] = t.timestamp()
    except (OverflowError, ValueError):
        pass
    out["bugcheck"] = bugcheck_info(code)
    return out


def list_dumps() -> list[dict]:
    files: list[Path] = []
    for d in DUMP_DIRS:
        if os.path.isdir(d):
            files += [Path(r) / f for r, _, fs in os.walk(d) for f in fs if f.lower().endswith(".dmp")]
    files += [Path(f) for f in DUMP_FILES if os.path.isfile(f)]
    out = []
    for f in files:
        try:
            st = f.stat()
            info = {"path": str(f), "name": f.name, "size": st.st_size, "mtime": st.st_mtime,
                    "folder": f.parent.name, "live": "LiveKernelReports" in str(f)}
            try:
                info.update(parse_dump_header(f))
            except (OSError, struct.error) as e:
                info["error"] = str(e)
            info.setdefault("time", st.st_mtime)
            out.append(info)
        except OSError:
            continue
    return sorted(out, key=lambda d: d["time"], reverse=True)


# ---------------------------------------------------------------- event logs + reliability monitor
EVENT_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$since = (Get-Date).AddDays(-%DAYS%)
$f = @(
  @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=41; StartTime=$since},
  @{LogName='System'; ProviderName='EventLog'; Id=6008; StartTime=$since},
  @{LogName='System'; ProviderName='Microsoft-Windows-WER-SystemErrorReporting'; Id=1001; StartTime=$since},
  @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; StartTime=$since},
  @{LogName='System'; Id=4101; StartTime=$since},
  @{LogName='System'; ProviderName=@('amdkmdag','amdwddmg','nvlddmkm','igfx'); StartTime=$since; Level=@(1,2,3)},
  @{LogName='System'; ProviderName=@('disk','Ntfs','stornvme','storahci','volmgr'); StartTime=$since; Level=@(1,2,3)},
  @{LogName='Application'; ProviderName='Application Error'; Id=1000; StartTime=$since},
  @{LogName='Application'; ProviderName='Application Hang'; Id=1002; StartTime=$since},
  @{LogName='Application'; ProviderName='Windows Error Reporting'; Id=1001; StartTime=$since}
)
$ev = foreach ($q in $f) { Get-WinEvent -FilterHashtable $q -MaxEvents 300 }
$ev | Sort-Object TimeCreated -Descending | Select-Object -First 800 | ForEach-Object {
  [ordered]@{ t = $_.TimeCreated.ToUniversalTime().ToString('o'); id = $_.Id; src = $_.ProviderName;
              level = $_.LevelDisplayName; log = $_.LogName;
              msg = if ($_.Message) { $_.Message.Substring(0, [Math]::Min(1500, $_.Message.Length)) } else { '' };
              data = @($_.Properties | ForEach-Object { "$($_.Value)" }) | Select-Object -First 12 }
} | ConvertTo-Json -Depth 4 -Compress
"""

RELIABILITY_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$since = (Get-Date).AddDays(-%DAYS%)
$r = Get-CimInstance Win32_ReliabilityRecords | Where-Object { $_.TimeGenerated -ge $since } |
  Select-Object -First 400 | ForEach-Object {
    [ordered]@{ t = $_.TimeGenerated.ToUniversalTime().ToString('o'); src = $_.SourceName; product = $_.ProductName;
                id = $_.EventIdentifier; msg = "$($_.Message)".Substring(0, [Math]::Min(800, "$($_.Message)".Length)) } }
$m = Get-CimInstance Win32_ReliabilityStabilityMetrics | Where-Object { $_.TimeGenerated -ge $since } |
  ForEach-Object { [ordered]@{ t = $_.TimeGenerated.ToUniversalTime().ToString('o'); v = $_.SystemStabilityIndex } }
[ordered]@{ records = @($r); stability = @($m) } | ConvertTo-Json -Depth 4 -Compress
"""


def _ps(script: str, timeout: int = 120) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    return r.stdout.strip()


def _ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _list(x):
    return [] if x is None else x if isinstance(x, list) else [x]


def read_events(days: int = 30) -> list[dict]:
    if not IS_WIN:
        return []
    try:
        raw = _list(json.loads(_ps(EVENT_QUERY.replace("%DAYS%", str(int(days)))) or "[]"))
    except (ValueError, subprocess.TimeoutExpired):
        return []
    for e in raw:
        e["time"] = _ts(e.get("t", ""))
        e["data"] = _list(e.get("data"))
    return raw


def read_reliability(days: int = 30) -> dict:
    if not IS_WIN:
        return {"records": [], "stability": []}
    try:
        raw = json.loads(_ps(RELIABILITY_QUERY.replace("%DAYS%", str(int(days)))) or "{}")
    except (ValueError, subprocess.TimeoutExpired):
        return {"records": [], "stability": []}
    recs = _list(raw.get("records"))
    for r in recs:
        r["time"] = _ts(r.get("t", ""))
    stab = [{"time": _ts(m["t"]), "v": m["v"]} for m in _list(raw.get("stability")) if m.get("v") is not None]
    return {"records": recs, "stability": sorted(stab, key=lambda m: m["time"])}


# ---------------------------------------------------------------- classification
WHEA_COMPONENT = re.compile(r"Component:\s*(.+)", re.I)
WHEA_SOURCE = re.compile(r"Error Source:\s*(.+)", re.I)
WHEA_APIC = re.compile(r"APIC ID:\s*(\d+)", re.I)


def classify(e: dict) -> dict:
    """Adds kind/title/detail to an event dict."""
    src, eid, msg = e.get("src", ""), e.get("id"), e.get("msg", "") or ""
    k = {"kind": "other", "severity": 1, "title": f"{src} {eid}", "detail": msg.split("\n")[0][:240]}
    if src == "Microsoft-Windows-Kernel-Power" and eid == 41:
        code = 0
        try:
            code = int(e["data"][0]) if e.get("data") else 0
        except (ValueError, TypeError):
            pass
        k.update(kind="shutdown", severity=3, title="Unexpected shutdown / restart",
                 detail=("Bug check 0x%X recorded with it." % code) if code else
                 "No stop code recorded - typically a hard freeze, power loss, PSU trip, or a very unstable "
                 "overclock that resets the PC instantly.")
        if code:
            k["bugcheck"] = code
    elif src == "EventLog" and eid == 6008:
        k.update(kind="shutdown", severity=2, title="Previous shutdown was unexpected", detail=msg[:200])
    elif src == "Microsoft-Windows-WER-SystemErrorReporting" and eid == 1001:
        m = re.search(r"bugcheck was:\s*(0x[0-9a-fA-F]+)\s*\(([^)]*)\)", msg)
        code = int(m.group(1), 16) if m else 0
        info = bugcheck_info(code)
        dm = re.search(r"dump was saved in:\s*(.+?\.dmp)", msg, re.I)
        k.update(kind="bsod", severity=3, title=f"Blue screen: {info['name']} ({info['code']})",
                 detail=info["what"], bugcheck=code, params=m.group(2) if m else "", dump=dm.group(1).strip() if dm else None)
    elif src == "Microsoft-Windows-WHEA-Logger":
        comp = WHEA_COMPONENT.search(msg)
        srcm = WHEA_SOURCE.search(msg)
        apic = WHEA_APIC.search(msg)
        fatal = eid in (18, 20, 46) or "fatal" in msg.lower()
        k.update(kind="whea", severity=3 if fatal else 2,
                 title="Hardware error (WHEA)" + (" - fatal" if fatal else " - corrected"),
                 detail=f"{comp.group(1).strip() if comp else 'Unknown component'}"
                        f"{' · ' + srcm.group(1).strip() if srcm else ''}"
                        f"{' · APIC ID ' + apic.group(1) if apic else ''}")
        if apic:
            k["apic"] = int(apic.group(1))
        if comp:
            k["component"] = comp.group(1).strip()
        if eid == 19 and "pcie" in msg.lower():
            k["detail"] += " (corrected PCIe errors are common and usually harmless)"
            k["severity"] = 1
    elif eid == 4101 or src in ("amdkmdag", "amdwddmg", "nvlddmkm", "igfx"):
        k.update(kind="gpu", severity=2, title="Graphics driver stopped responding and recovered",
                 detail="Usually an unstable GPU overclock/undervolt, an overheating GPU, or a driver bug.")
    elif src in ("disk", "Ntfs", "stornvme", "storahci", "volmgr"):
        if src == "volmgr" and eid in (161, 162, 46, 45, 49):
            k.update(kind="info", severity=1, title="Crash dump status", detail=msg[:200])
        else:
            k.update(kind="disk", severity=2, title=f"Storage warning ({src} {eid})", detail=msg.split("\n")[0][:200])
    elif src == "Application Error" and eid == 1000:
        app = e["data"][0] if e.get("data") else "app"
        mod = e["data"][3] if len(e.get("data", [])) > 3 else ""
        k.update(kind="app", severity=1, title=f"{app} crashed", detail=f"Faulting module: {mod}" if mod else msg[:160],
                 app=app, module=mod)
    elif src == "Application Hang":
        app = e["data"][0] if e.get("data") else "app"
        k.update(kind="hang", severity=1, title=f"{app} stopped responding", detail="", app=app)
    elif src == "Windows Error Reporting" and "LiveKernelEvent" in msg:
        m = re.search(r"P1:\s*([0-9a-fA-F]+)", msg)
        code = int(m.group(1), 16) if m else 0
        info = bugcheck_info(code)
        k.update(kind="livekernel", severity=2, title=f"Live kernel event: {info['name']}", detail=info["what"],
                 bugcheck=code)
    elif src == "Windows Error Reporting":
        return {**e, "kind": "skip"}
    return {**e, **k}


def build_incidents(events: list[dict], reliability: dict, dumps: list[dict], journal: list[dict] | None = None,
                    window_s: int = 600) -> list[dict]:
    """Group related events (± window) into incidents and explain each one."""
    items = [x for x in (classify(e) for e in events) if x["kind"] not in ("skip", "info")]
    for r in reliability.get("records", []):
        src = (r.get("src") or "")
        if src in ("Application Error", "Application Hang", "Microsoft-Windows-WER-SystemErrorReporting",
                   "Microsoft-Windows-Kernel-Power", "EventLog", "Windows Error Reporting"):
            continue  # already covered by the event log
        if "fail" in (r.get("msg") or "").lower() and r.get("product"):
            items.append({"time": r["time"], "kind": "reliability", "severity": 1, "title": f"{r['product']} failure",
                          "detail": (r.get("msg") or "")[:200], "src": "Reliability Monitor"})
    for d in dumps:
        if d.get("valid"):
            b = d["bugcheck"]
            items.append({"time": d["time"], "kind": "dump", "severity": 2 if not d.get("live") else 1,
                          "title": f"{'Live kernel report' if d.get('live') else 'Crash dump'}: {d['name']}",
                          "detail": f"{b['name']} ({b['code']}) · {d.get('dump_type', '')}", "dump": d["path"],
                          "bugcheck": d["code"], "src": "dump"})
    items.sort(key=lambda x: x["time"])
    incidents: list[dict] = []
    for it in items:
        cur = incidents[-1] if incidents else None
        if cur and it["time"] - cur["end"] <= window_s and (it["severity"] >= 2 or cur["severity"] >= 2 or it["kind"] == "dump"):
            cur["events"].append(it)
            cur["end"] = max(cur["end"], it["time"])
            cur["severity"] = max(cur["severity"], it["severity"])
        else:
            incidents.append({"start": it["time"], "end": it["time"], "severity": it["severity"], "events": [it]})
    out = [_explain(i, journal or []) for i in incidents]
    return sorted(out, key=lambda i: i["time"], reverse=True)


def _explain(inc: dict, journal: list[dict]) -> dict:
    ev = inc["events"]
    kinds = {e["kind"] for e in ev}
    codes = [e["bugcheck"] for e in ev if e.get("bugcheck")]
    code = codes[0] if codes else None
    dumps = [e["dump"] for e in ev if e.get("dump")]
    whea = [e for e in ev if e["kind"] == "whea"]
    cores = sorted({e["apic"] for e in whea if "apic" in e})
    res = {"time": inc["start"], "severity": inc["severity"], "events": ev, "dumps": sorted(set(dumps)),
           "bugcheck": bugcheck_info(code) if code else None}
    if "bsod" in kinds or (code and "shutdown" in kinds):
        b = bugcheck_info(code or 0)
        res["type"], res["title"] = "bsod", f"Blue screen - {b['name']}"
        res["summary"], res["cause"] = b["what"], b["causes"]
    elif "shutdown" in kinds:
        res["type"], res["title"] = "reset", "PC restarted or turned off unexpectedly"
        res["summary"] = "Windows didn't shut down cleanly and no blue screen was recorded."
        res["cause"] = ("Most often: an unstable CPU/RAM overclock or undervolt that resets instantly, the PSU "
                        "tripping under load, overheating, or a power cut / held power button.")
    elif "whea" in kinds and any(e["severity"] >= 2 for e in whea):
        res["type"], res["title"] = "whea", "Hardware errors reported by the CPU"
        res["summary"] = "; ".join(sorted({e["detail"] for e in whea}))[:300]
        res["cause"] = ("Corrected errors are an early warning: the system is right at the edge of stability. "
                        "Common with Curve Optimizer/undervolts, RAM/FCLK overclocks or low SoC voltage.")
    elif "gpu" in kinds or (code and code in (0x116, 0x117, 0x141, 0x1B0)):
        res["type"], res["title"] = "gpu", "Graphics driver crash / reset"
        res["summary"] = "The graphics card stopped responding; Windows reset the driver."
        res["cause"] = ("Usually an unstable GPU tuning (undervolt or VRAM overclock in Adrenalin), GPU "
                        "temperatures, or a driver bug. Back off the last Adrenalin change first.")
    elif "livekernel" in kinds:
        b = bugcheck_info(code or 0)
        res["type"], res["title"] = "livekernel", f"Hardware/driver hiccup - {b['name']}"
        res["summary"], res["cause"] = b["what"] + " Windows recovered without crashing.", b["causes"]
    elif "disk" in kinds:
        res["type"], res["title"] = "disk", "Storage errors"
        res["summary"] = ev[0]["detail"]
        res["cause"] = "Loose/failing SATA cable, drive problems or a storage driver/firmware issue. Check drive health."
    elif kinds <= {"app", "hang", "reliability", "dump"}:
        apps = sorted({e.get("app") or e["title"] for e in ev})
        res["type"], res["title"] = "app", ("App crash: " + ", ".join(apps))[:120]
        mods = sorted({e.get("module") for e in ev if e.get("module")})
        res["summary"] = ("Faulting module: " + ", ".join(mods)) if mods else ev[0]["detail"]
        res["cause"] = ("A single app crashing is usually that app's bug. If many different apps crash at "
                        "random, suspect unstable RAM/CPU tuning.")
    else:
        res["type"], res["title"] = "other", ev[0]["title"]
        res["summary"], res["cause"] = ev[0]["detail"], ""
    if cores:
        res["whea_cores"] = cores
        res["cause"] += (f" WHEA errors point at APIC ID {', '.join(map(str, cores))} - on Ryzen with SMT that's "
                         f"physical core ≈ {', '.join(str(c // 2) for c in cores)}. If you use Curve Optimizer, "
                         "raise (less negative) that core's value.")
    # what changed just before? (overclocking journal)
    before = [j for j in journal if 0 <= inc["start"] - j.get("time", 0) <= 3 * 86400 and j.get("kind") in ("applied", "detected")]
    if before:
        last = max(before, key=lambda j: j["time"])
        mins = (inc["start"] - last["time"]) / 60
        res["recent_change"] = {"text": last.get("text", ""), "ago_min": round(mins)}
        if (res.get("bugcheck") or {}).get("oc_related") or res["type"] in ("reset", "whea", "gpu"):
            res["cause"] += f" Your last tuning change ('{last.get('text', '')}') was {_ago(mins)} before this - try undoing it."
    return res


def _ago(mins: float) -> str:
    if mins < 90:
        return f"{round(mins)} min"
    if mins < 48 * 60:
        return f"{round(mins / 60)} h"
    return f"{round(mins / 1440)} days"


# ---------------------------------------------------------------- deep analysis with Microsoft's debugger
def find_cdb() -> str | None:
    cands = [r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe",
             r"C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe"]
    if IS_WIN:
        try:
            loc = _ps("(Get-AppxPackage -Name Microsoft.WinDbg | Select-Object -First 1).InstallLocation", 30)
            if loc:
                cands = [os.path.join(loc, "amd64", "cdb.exe"), os.path.join(loc, "cdb.exe")] + cands
        except Exception:  # noqa: BLE001
            pass
    return next((c for c in cands if os.path.isfile(c)), None)


ANALYZE_KEYS = ["BUGCHECK_CODE", "BUGCHECK_STR", "PROCESS_NAME", "MODULE_NAME", "IMAGE_NAME", "SYMBOL_NAME",
                "FAILURE_BUCKET_ID", "DEFAULT_BUCKET_ID", "CUSTOMER_CRASH_COUNT", "BLACKBOXBSD", "BLACKBOXPNP"]


def parse_analyze(text: str) -> dict:
    out = {}
    for k in ANALYZE_KEYS:
        m = re.search(rf"^{k}:\s*(.+)$", text, re.M)
        if m:
            out[k] = m.group(1).strip()
    m = re.search(r"Probably caused by\s*:\s*(.+)", text)
    if m:
        out["PROBABLY_CAUSED_BY"] = m.group(1).strip()
    m = re.search(r"^STACK_TEXT:\s*\n((?:.+\n){1,12})", text, re.M)
    if m:
        out["STACK"] = m.group(1).rstrip()
    return out


class DumpAnalyzer:
    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def start(self, path: str) -> dict:
        job = self.jobs.get(path)
        if job and job["state"] == "running":
            return job
        job = self.jobs[path] = {"state": "running", "started": time.time(), "result": None, "error": None, "raw": ""}
        threading.Thread(target=self._run, args=(path, job), daemon=True).start()
        return job

    def _run(self, path: str, job: dict):
        cdb = find_cdb()
        if not cdb:
            job.update(state="error", error="nodebugger")
            return
        sym = app_dir() / "symbols"
        sym.mkdir(exist_ok=True)
        try:
            r = subprocess.run([cdb, "-z", path, "-y", f"srv*{sym}*https://msdl.microsoft.com/download/symbols",
                                "-c", "!analyze -v; q"], capture_output=True, text=True, timeout=600,
                               creationflags=NOWIN, encoding="utf-8", errors="replace")
            job["raw"] = r.stdout[-60000:]
            job["result"] = parse_analyze(r.stdout)
            job["state"] = "done"
        except subprocess.TimeoutExpired:
            job.update(state="error", error="The debugger took more than 10 minutes (symbol download?). Try again.")
        except Exception as e:  # noqa: BLE001
            job.update(state="error", error=str(e))


def install_windbg() -> str:
    subprocess.Popen(["cmd", "/c", "start", "Install WinDbg", "cmd", "/k",
                      "winget install --id Microsoft.WinDbg -e --accept-source-agreements --accept-package-agreements"
                      " && echo. && echo Done - go back to RigLab and press Analyse again."])
    return "WinDbg installer opened in a new window."


# ---------------------------------------------------------------- "crashed since last time?"
STATE = app_dir() / "crash_state.json"


def new_since_last_run(incidents: list[dict]) -> list[dict]:
    try:
        last = json.loads(STATE.read_text(encoding="utf-8")).get("last_seen", 0)
    except (OSError, ValueError):
        last = time.time() - 86400
    STATE.write_text(json.dumps({"last_seen": time.time()}), encoding="utf-8")
    return [i for i in incidents if i["time"] > last and i["severity"] >= 2]
