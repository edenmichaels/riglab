"""Full and quick PC health checks, built on Windows' own tools (no custom scanners).

Each check is a Step. CheckJob runs the steps one after another on a background thread, with progress,
time remaining and Cancel. Steps return report-card items (same shape as core/health.py), which the dial
scores. The parsers and translations at the top are pure functions so they can be tested anywhere.

Quick check: live readings, virus protection status, Device Manager errors, inputs/outputs, drives,
crashes, last memory test result. Full check adds: Windows updates, old drivers, DISM /ScanHealth,
sfc /verifyonly and a full Windows Defender scan. Nothing here repairs anything - repairs are Fix it
buttons (see FIXES), which go through the normal "are you sure" + restore point rules.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from . import explain, health

log = logging.getLogger(__name__)
IS_WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000

# ================================================================== pure helpers (tested)

# Device Manager problem codes (Win32_PnPEntity.ConfigManagerErrorCode) in plain words.
# state: bad = needs fixing, warn = worth checking, none = not a problem (e.g. you switched it off yourself).
CM_CODES = {
    1: ("bad", "isn't set up properly"),
    3: ("bad", "has a driver that may be damaged, or Windows is low on memory"),
    10: ("bad", "can't start"),
    12: ("bad", "can't find enough free resources to work"),
    14: ("warn", "needs your PC to restart before it works"),
    16: ("bad", "isn't fully set up"),
    18: ("bad", "needs its driver reinstalled"),
    19: ("bad", "has damaged settings in Windows"),
    21: ("warn", "is being removed by Windows"),
    22: ("none", "is switched off (you or another app turned it off)"),
    24: ("warn", "isn't connected or isn't working"),
    28: ("warn", "has no driver installed"),
    29: ("warn", "is switched off in your PC's BIOS"),
    31: ("bad", "isn't working properly"),
    32: ("warn", "has its driver switched off"),
    37: ("bad", "has a driver that failed to start"),
    39: ("bad", "has a missing or damaged driver"),
    41: ("bad", "has a driver that loaded but can't find the device"),
    43: ("bad", "was stopped by Windows because it reported a problem"),
    45: ("none", "isn't plugged in right now"),
    47: ("warn", "was prepared for safe removal - unplug and plug it back in"),
    48: ("bad", "has a driver that Windows blocked because of known problems"),
    52: ("bad", "has a driver that isn't signed (Windows can't check it's safe)"),
}


def translate_cm(code) -> tuple[str, str]:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "warn", "has a problem Windows didn't explain"
    if c == 0:
        return "good", "is working properly"
    return CM_CODES.get(c, ("warn", f"has a problem (Windows code {c})"))


def devices_item(devs: list[dict]) -> dict:
    """devs: [{"Name", "ConfigManagerErrorCode", "PNPDeviceID", "PNPClass"}] for devices that report a problem."""
    probs = []
    for d in devs or []:
        st, words = translate_cm(d.get("ConfigManagerErrorCode"))
        if st in ("bad", "warn"):
            probs.append((st, f"{d.get('Name') or 'An unnamed device'} {words}", d))
    st = explain.worst([p[0] for p in probs]) if probs else "good"
    if not probs:
        say = "Every device in Device Manager is working."
    elif len(probs) == 1:
        say = probs[0][1][:1].upper() + probs[0][1][1:] + "."
    else:
        say = f"{len(probs)} devices have problems. The worst: {probs[0][1]}."
    probs.sort(key=lambda p: p[0] != "bad")
    return {"id": "devices", "title": "Devices", "state": st, "say": say,
            "action": {"id": "open_devices", "label": "Open Device Manager"} if probs else None,
            "details": "\n".join(f"[{p[2].get('ConfigManagerErrorCode')}] {p[2].get('Name')} - {p[2].get('PNPClass') or ''} {p[2].get('PNPDeviceID') or ''}"
                                 for p in probs) or "No ConfigManagerErrorCode other than 0."}


IO_KINDS = [("Keyboard", "keyboard", "Keyboard"), ("Mouse", "mouse", "Mouse or touchpad"), ("Monitor", "monitor", "Screen"),
            ("AudioEndpoint", "sound", "Speakers, headphones and microphones"), ("Net", "net", "Network"), ("USB", "usb", "USB ports")]


def io_item(devs: list[dict], net_up: int | None = None) -> dict:
    """devs: Get-PnpDevice -PresentOnly rows {Class, FriendlyName, Status} for the IO_KINDS classes."""
    lines, states, tech = [], [], []
    for cls, _ic, label in IO_KINDS:
        rows = [d for d in devs or [] if (d.get("Class") or "").lower() == cls.lower()]
        ok = [d for d in rows if (d.get("Status") or "").upper() == "OK"]
        bad = [d for d in rows if (d.get("Status") or "").upper() in ("ERROR", "DEGRADED")]
        if bad:
            states.append("bad" if cls in ("Keyboard", "Mouse", "Monitor") else "warn")
            lines.append(f"{label}: {len(bad)} not working ({', '.join(d.get('FriendlyName') or '?' for d in bad[:2])})")
        elif not ok and cls in ("Keyboard", "Mouse"):
            states.append("warn")
            lines.append(f"{label}: none found")
        elif not ok and cls == "Monitor":
            states.append("none")
            lines.append(f"{label}: Windows didn't list one")
        else:
            states.append("good")
            n = len(ok)
            lines.append(f"{label}: {n} working" if n else f"{label}: none")
        tech += [f"{cls}: {d.get('FriendlyName')} [{d.get('Status')}]" for d in rows]
    if net_up == 0:
        states.append("warn")
        lines.append("Network: no connection is active")
    st = explain.worst(states) if states else "none"
    bad_lines = [ln for ln in lines if "not working" in ln or "none found" in ln or "no connection" in ln]
    say = "Keyboard, mouse, screens, sound, network and USB are all working." if st == "good" else "; ".join(bad_lines) + "."
    return {"id": "io", "title": "Inputs and outputs", "state": st, "say": say, "lines": lines,
            "action": {"id": "open_devices", "label": "Open Device Manager"} if st in ("warn", "bad") else None,
            "details": "\n".join(tech)}


_MSDATE = re.compile(r"/Date\((-?\d+)")


def parse_date(v) -> datetime | None:
    """Dates from PowerShell JSON: '/Date(1600000000000)/', WMI '20200101000000.000000-000' or ISO."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v)
    m = _MSDATE.search(s)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
    w = explain.parse_wmi_time(s)
    if w:
        return w
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


OLD_DRIVER_DAYS = 730


def drivers_item(drivers: list[dict], now: datetime | None = None) -> dict:
    """Drivers older than ~2 years, not counting Windows' own built-in ones. Yellow at most, never red:
    lots of perfectly good drivers (chipset, USB) don't change for years."""
    now = now or datetime.now(timezone.utc)
    old = []
    for d in drivers or []:
        prov = (d.get("DriverProviderName") or "").strip()
        name = (d.get("DeviceName") or "").strip()
        dt = parse_date(d.get("DriverDate"))
        # 21 June 2006 is the placeholder date on Windows' built-in drivers, whoever made the device
        if not name or not dt or prov.lower() in ("microsoft", "") or dt.year < 2000 or (dt.year, dt.month, dt.day) == (2006, 6, 21):
            continue
        age = (now - dt).days
        if age > OLD_DRIVER_DAYS:
            old.append((age, name, prov, d.get("DriverVersion"), dt))
    old.sort(reverse=True)
    if not old:
        return {"id": "drivers", "title": "Driver age", "state": "good", "say": "Your drivers are less than 2 years old.",
                "details": f"{len(drivers or [])} drivers checked."}
    n = len(old)
    return {"id": "drivers", "title": "Driver age", "state": "warn",
            "say": f"{n} driver{'s are' if n > 1 else ' is'} over 2 years old. This is often fine, but newer ones can fix bugs.",
            "action": {"id": "open_driver_updates", "label": "Look for driver updates"},
            "details": "\n".join(f"{nm} - {pv} {ver} ({dt.date()}, {age // 365} years old)" for age, nm, pv, ver, dt in old[:40])}


def updates_item(titles: list[str] | None, reboot_pending: bool = False) -> dict:
    """Pending Windows updates. Yellow at most, never red."""
    titles = titles or []
    if titles:
        n = len(titles)
        say = f"{n} Windows update{'s are' if n > 1 else ' is'} waiting to be installed."
        st = "warn"
    elif reboot_pending:
        say, st = "Updates are installed, but your PC needs a restart to finish.", "warn"
    else:
        say, st = "Windows is up to date.", "good"
    if reboot_pending and titles:
        say += " Your PC also needs a restart to finish earlier updates."
    return {"id": "updates", "title": "Windows updates", "state": st, "say": say,
            "action": {"id": "open_updates", "label": "Open Windows Update"} if st == "warn" else None,
            "details": "\n".join(titles) or "No pending updates found."}


def decode_output(raw: bytes) -> str:
    """sfc writes UTF-16 text (with NULs between letters) even when piped; most tools write the console code page."""
    if not raw:
        return ""
    if raw.count(b"\x00") > len(raw) // 4:
        try:
            return raw.decode("utf-16-le", errors="ignore")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8", "cp850", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="ignore")


def sfc_item(text: str, rc: int | None) -> dict:
    t = re.sub(r"\s+", " ", (text or "")).lower()
    base = {"id": "system_files", "title": "Windows system files", "details": (text or "").strip()[-1500:]}
    if "must be an administrator" in t or "administrator running a console" in t:
        return {**base, "state": "none", "say": "Skipped - this check needs RigLab to run as administrator."}
    if "did not find any integrity violations" in t:
        return {**base, "state": "good", "say": "No damaged Windows files found."}
    if "found integrity violations" in t or "found corrupt files" in t:
        return {**base, "state": "bad", "say": "Some Windows files are damaged. Windows can usually repair them itself.",
                "action": {"id": "sfc_repair", "label": "Repair Windows files"}}
    if "could not perform the requested operation" in t or "pending system repair" in t:
        return {**base, "state": "warn", "say": "Windows couldn't finish this check. Restart your PC and try again."}
    return {**base, "state": "warn", "say": "RigLab couldn't read the result of this check. Show details has the full output."}


def dism_item(text: str, rc: int | None) -> dict:
    t = re.sub(r"\s+", " ", (text or "")).lower()
    base = {"id": "windows_image", "title": "Windows repair store", "details": (text or "").strip()[-1500:]}
    if "elevated permissions" in t or "error: 740" in t:
        return {**base, "state": "none", "say": "Skipped - this check needs RigLab to run as administrator."}
    if "no component store corruption detected" in t:
        return {**base, "state": "good", "say": "The copy of Windows that repairs your PC is healthy."}
    if "not repairable" in t:
        return {**base, "state": "bad", "say": "Windows' repair store is damaged and can't fix itself. A Windows reset or repair install may be needed."}
    if "is repairable" in t:
        return {**base, "state": "bad", "say": "Windows' repair store is damaged, but it can be repaired.",
                "action": {"id": "dism_repair", "label": "Repair it (needs internet)"}}
    if rc == 0:
        return {**base, "state": "good", "say": "The copy of Windows that repairs your PC is healthy."}
    return {**base, "state": "warn", "say": "Windows couldn't finish this check. Show details has the full output."}


def protection_item(status: dict | None, products: list[dict] | None) -> dict:
    """Virus protection right now (quick check). status = Get-MpComputerStatus fields, products = SecurityCenter2."""
    s = status or {}
    others = [p.get("displayName") for p in products or [] if p.get("displayName") and "defender" not in p["displayName"].lower()]
    base = {"id": "virus_protection", "title": "Virus protection",
            "details": json.dumps({"defender": {k: s.get(k) for k in ("AMRunningMode", "AntivirusEnabled", "RealTimeProtectionEnabled", "AntivirusSignatureAge")},
                                   "installed": [p.get("displayName") for p in products or []]})}
    defender_on = bool(s.get("AntivirusEnabled")) and (s.get("AMRunningMode") in (None, "Normal", "EDR Block Mode"))
    if not defender_on and others:
        return {**base, "state": "good", "say": f"Your PC is protected by {others[0]}.", "third_party": others[0]}
    if not defender_on:
        return {**base, "state": "bad", "say": "Virus protection is switched off.", "action": {"id": "open_security", "label": "Open Windows Security"}}
    if s.get("RealTimeProtectionEnabled") is False:
        return {**base, "state": "bad", "say": "Windows Defender is installed, but real-time protection is switched off.",
                "action": {"id": "open_security", "label": "Open Windows Security"}}
    age = s.get("AntivirusSignatureAge")
    if isinstance(age, (int, float)) and age > 7:
        return {**base, "state": "warn", "say": f"Windows Defender's virus list is {int(age)} days old. Updating it keeps you protected.",
                "action": {"id": "open_security", "label": "Open Windows Security"}}
    return {**base, "state": "good", "say": "Windows Defender is on and up to date."}


def scan_item(rc: int | None, text: str = "", third_party: str | None = None, cancelled: bool = False) -> dict:
    """Full Defender scan result. MpCmdRun exit codes: 0 = no threats, 2 = threats found (and handled or not)."""
    base = {"id": "virus_scan", "title": "Full virus scan", "details": (text or "").strip()[-1500:]}
    if third_party:
        return {**base, "state": "none", "say": f"Your PC uses {third_party} for virus protection, so RigLab can't run a Windows Defender scan. "
                                                f"Run a full scan in {third_party} instead."}
    if cancelled:
        return {**base, "state": "none", "say": "Cancelled before it finished."}
    if rc == 0:
        return {**base, "state": "good", "say": "No viruses or harmful files were found."}
    if rc == 2:
        return {**base, "state": "bad", "say": "Windows Defender found something harmful. Open Windows Security to see what it found and what it did.",
                "action": {"id": "open_security", "label": "Open Windows Security"}}
    return {**base, "state": "warn", "say": "The virus scan didn't finish. Try again later."}


def memory_item(events: list[dict] | None, now: datetime | None = None) -> dict:
    """Last Windows Memory Diagnostic result (System log, MemoryDiagnostics-Results 1201 = passed, 1202 = errors)."""
    now = now or datetime.now(timezone.utc)
    evs = sorted((e for e in events or [] if parse_date(e.get("TimeCreated"))), key=lambda e: parse_date(e["TimeCreated"]), reverse=True)
    act = {"id": "memtest", "label": "Test my memory on the next restart"}
    if not evs:
        return {"id": "memory", "title": "Memory test", "state": "none", "action": act,
                "say": "Your memory hasn't been tested yet. Windows can test it the next time your PC restarts (it takes about 15 minutes)."}
    e = evs[0]
    when = parse_date(e["TimeCreated"])
    days = (now - when).days
    if int(e.get("Id") or 0) == 1202:
        return {"id": "memory", "title": "Memory test", "state": "bad", "action": act,
                "say": f"Windows found memory errors {days} days ago. Faulty memory can cause crashes and lost work."}
    return {"id": "memory", "title": "Memory test", "state": "good", "action": act if days > 365 else None,
            "say": f"Your memory passed Windows' test {days} days ago." if days else "Your memory passed Windows' test today."}


def skipped(id_: str, title: str, why: str) -> dict:
    return {"id": id_, "title": title, "state": "none", "say": why, "skipped": True}


NO_INTERNET = "Skipped - no internet connection. RigLab will check this next time you're online."


def fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return ""
    s = int(max(0, seconds))
    if s < 45:
        return "less than a minute left"
    m = round(s / 60)
    if m < 60:
        return f"about {m} minute{'s' if m != 1 else ''} left"
    hrs, mm = divmod(m, 60)
    return f"about {hrs} hour{'s' if hrs != 1 else ''}" + (f" {mm} min" if mm else "") + " left"


def defender_estimate(used_bytes: int | None) -> int:
    """Rough full-scan time: Windows doesn't report progress, so estimate ~60 MB/s of used disk space, 10 min to 3 h."""
    if not used_bytes:
        return 45 * 60
    return int(min(3 * 3600, max(600, used_bytes / (60 * 1024 * 1024))))


# ================================================================== the job runner (tested with fake steps)
@dataclass
class Step:
    id: str
    label: str                       # shown under the progress bar, e.g. "Scanning for viruses"
    est: float                       # estimated seconds (for progress and time remaining)
    run: Callable[["Ctx"], list[dict]]
    full_only: bool = False
    needs_internet: bool = False
    title: str = ""                  # report-card title used when skipped


@dataclass
class Ctx:
    job: "CheckJob"
    online: bool = True
    data: dict = field(default_factory=dict)      # shared between steps (e.g. the third-party antivirus name)

    def cancelled(self) -> bool:
        return self.job.cancel_flag.is_set()

    def run(self, cmd: list[str], timeout: float = 3600, on_cancel: list[str] | None = None) -> tuple[int | None, str]:
        """Run a command, killing it if Cancel is pressed. Returns (exit code or None if cancelled/timed out, text)."""
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=CREATE_NO_WINDOW if IS_WIN else 0)
        self.job.proc = p
        out: list[bytes] = []
        reader = threading.Thread(target=lambda: out.append(p.stdout.read() or b""), daemon=True)
        reader.start()
        end = time.monotonic() + timeout
        try:
            while p.poll() is None:
                if self.cancelled() or time.monotonic() > end:
                    _kill(p)
                    if on_cancel:
                        try:
                            subprocess.run(on_cancel, capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW if IS_WIN else 0)
                        except (OSError, subprocess.SubprocessError):
                            pass
                    reader.join(2)
                    return None, decode_output(b"".join(out))
                time.sleep(0.25)
            reader.join(5)
            if self.cancelled():                  # Cancel killed it from the other thread
                return None, decode_output(b"".join(out))
            return p.returncode, decode_output(b"".join(out))
        finally:
            self.job.proc = None


def _kill(p):
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        else:
            p.kill()
    except (OSError, subprocess.SubprocessError):
        pass


class CheckJob:
    """Runs steps one after another on a thread. status() is polled by the screen every second."""

    def __init__(self, kind: str, steps: list[Step], online: bool = True, clock=time.monotonic, finish=None):
        self.kind, self.steps, self.online, self.clock = kind, steps, online, clock
        self.cancel_flag = threading.Event()
        self.items: list[dict] = []
        self.i = -1
        self.step_start = None
        self.started = None
        self.finished = None
        self.result: dict | None = None
        self.error: str | None = None
        self.proc = None
        self.thread: threading.Thread | None = None
        self.on_done: Callable[[dict], None] | None = None
        self.finish = finish          # builds the result from the job (default: a health score from the items)
        self.ctx: Ctx | None = None

    # -- control
    def start(self, background: bool = True):
        self.started = self.clock()
        if background:
            self.thread = threading.Thread(target=self._run, name=f"HealthCheck-{self.kind}", daemon=True)
            self.thread.start()
        else:
            self._run()
        return self

    def cancel(self):
        self.cancel_flag.set()
        p = self.proc
        if p is not None:
            _kill(p)

    def running(self) -> bool:
        return self.started is not None and self.finished is None

    def _run(self):
        ctx = self.ctx = Ctx(self, online=self.online)
        try:
            for i, st in enumerate(self.steps):
                if self.cancel_flag.is_set():
                    break
                self.i, self.step_start = i, self.clock()
                if st.needs_internet and not self.online:
                    self.items.append(skipped(st.id, st.title or st.label, NO_INTERNET))
                    continue
                try:
                    got = st.run(ctx) or []
                except Exception as e:  # noqa: BLE001 - one broken check must never stop the others
                    log.exception("health step %s", st.id)
                    got = [{"id": st.id, "title": st.title or st.label, "state": "none",
                            "say": "RigLab couldn't run this check.", "details": f"{type(e).__name__}: {e}"}]
                if self.cancel_flag.is_set():
                    break
                self.items.extend(got)
        except Exception as e:  # noqa: BLE001
            log.exception("health job")
            self.error = str(e)
        cancelled = self.cancel_flag.is_set()
        result = None
        if not cancelled:          # work out the result BEFORE marking the job finished, so a screen never sees
            try:                   # "finished" with no result yet
                result = self.finish(self) if self.finish else health.result(self.items, kind=self.kind)
            except Exception as e:  # noqa: BLE001
                log.exception("job finish")
                self.error = str(e)
        self.result = result
        self.finished = self.clock()
        if not cancelled:
            if self.on_done:
                try:
                    self.on_done(self.result)
                except Exception:  # noqa: BLE001
                    log.exception("health on_done")

    # -- progress
    def progress(self) -> tuple[float, float | None]:
        """(0..1 done, seconds left). Each step counts by its estimate; a step never shows more than 95% done
        until it really finishes, and a step that runs long keeps a little time left instead of going negative."""
        total = sum(s.est for s in self.steps) or 1.0
        if self.finished is not None:
            return 1.0, 0.0
        if self.i < 0:
            return 0.0, total
        done = sum(s.est for s in self.steps[:self.i])
        cur = self.steps[self.i]
        el = max(0.0, self.clock() - (self.clock() if self.step_start is None else self.step_start))
        part = min(el, cur.est * 0.95)
        left_cur = max(cur.est - el, cur.est * 0.05, 3.0)
        left = left_cur + sum(s.est for s in self.steps[self.i + 1:])
        return min(0.99, (done + part) / total), left

    def status(self) -> dict:
        p, left = self.progress()
        st = self.steps[self.i] if 0 <= self.i < len(self.steps) else None
        return {"kind": self.kind, "running": self.running(), "cancelled": self.cancel_flag.is_set() and self.finished is not None,
                "step": st.label if st and self.running() else "", "index": max(0, self.i) + 1, "count": len(self.steps),
                "progress": round(p, 3), "eta": None if left is None else round(left), "eta_text": fmt_eta(left) if self.running() else "",
                "items": list(self.items), "result": self.result, "error": self.error}


# ================================================================== Windows steps
def _ps_json(ctx: Ctx | None, script: str, timeout: float = 120):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
           "$ErrorActionPreference='SilentlyContinue'; " + script]
    if ctx is not None:
        rc, out = ctx.run(cmd, timeout=timeout)
    else:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW if IS_WIN else 0)
        out = decode_output(r.stdout)
    return parse_json(out)


def parse_json(out: str):
    """PowerShell sometimes prints warnings before the JSON - start at the first [ or {."""
    out = (out or "").strip()
    starts = [i for i in (out.find("["), out.find("{")) if i >= 0]
    if not starts:
        try:
            return json.loads(out) if out else None
        except ValueError:
            return None
    try:
        return json.loads(out[min(starts):])
    except ValueError:
        return None


def _as_list(x):
    return [] if x is None else x if isinstance(x, list) else [x]


def is_online() -> bool:
    """Ask Windows (Network List Manager) whether there's internet - RigLab sends nothing anywhere to find out."""
    if not IS_WIN:
        return False
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Activator]::CreateInstance([Type]::GetTypeFromCLSID([Guid]'DCB00C01-570F-4A9B-8D69-199FDBA5723B')).IsConnectedToInternet"],
                           capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW)
        return r.stdout.strip().lower() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def mpcmdrun() -> str | None:
    base = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows Defender\Platform")
    try:
        vers = sorted((d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "MpCmdRun.exe"))), reverse=True)
        if vers:
            return os.path.join(base, vers[0], "MpCmdRun.exe")
    except OSError:
        pass
    p = os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), r"Windows Defender\MpCmdRun.exe")
    return p if os.path.isfile(p) else None


def step_protection(ctx: Ctx):
    st = _ps_json(ctx, "Get-MpComputerStatus | Select AMRunningMode,AntivirusEnabled,RealTimeProtectionEnabled,AntivirusSignatureAge | ConvertTo-Json -Compress", 60)
    av = _as_list(_ps_json(ctx, "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | Select displayName,productState | ConvertTo-Json -Compress", 60))
    it = protection_item(st if isinstance(st, dict) else None, av)
    ctx.data["third_party"] = it.get("third_party")
    return [it]


def step_devices(ctx: Ctx):
    devs = _as_list(_ps_json(ctx, "Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } | "
                                  "Select Name,ConfigManagerErrorCode,PNPDeviceID,PNPClass | ConvertTo-Json -Compress", 90))
    return [devices_item(devs)]


def step_io(ctx: Ctx):
    devs = _as_list(_ps_json(ctx, "Get-PnpDevice -PresentOnly -Class Keyboard,Mouse,Monitor,AudioEndpoint,Net,USB | "
                                  "Select Class,FriendlyName,Status | ConvertTo-Json -Compress", 90))
    up = _ps_json(ctx, "@(Get-NetAdapter -Physical | Where-Object Status -eq 'Up').Count | ConvertTo-Json", 30)
    return [io_item(devs, up if isinstance(up, int) else None)]


def step_memory(ctx: Ctx):
    evs = _as_list(_ps_json(ctx, "Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-MemoryDiagnostics-Results'} "
                                 "-MaxEvents 5 | Select Id,TimeCreated | ConvertTo-Json -Compress", 60))
    return [memory_item(evs)]


def step_updates(ctx: Ctx):
    script = ("$s=New-Object -ComObject Microsoft.Update.Session; $r=$s.CreateUpdateSearcher().Search(\"IsInstalled=0 and IsHidden=0 and Type='Software'\"); "
              "$t=@($r.Updates | ForEach-Object { $_.Title }); "
              "$rb=(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired'); "
              "@{titles=$t; reboot=$rb} | ConvertTo-Json -Compress")
    d = _ps_json(ctx, script, 600)
    if not isinstance(d, dict):
        return [{"id": "updates", "title": "Windows updates", "state": "none", "say": "Windows Update didn't answer. Try again later."}]
    return [updates_item(_as_list(d.get("titles")), bool(d.get("reboot")))]


def step_drivers(ctx: Ctx):
    drv = _as_list(_ps_json(ctx, "Get-CimInstance Win32_PnPSignedDriver | Where-Object DeviceName | "
                                 "Select DeviceName,DriverVersion,DriverDate,DriverProviderName | ConvertTo-Json -Compress", 180))
    return [drivers_item(drv)]


def step_dism(ctx: Ctx):
    rc, out = ctx.run(["dism", "/English", "/Online", "/Cleanup-Image", "/ScanHealth"], timeout=3600)
    if rc is None and ctx.cancelled():
        return []
    return [dism_item(out, rc)]


def step_sfc(ctx: Ctx):
    sysdir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Sysnative" if _wow64() else "System32")
    rc, out = ctx.run([os.path.join(sysdir, "sfc.exe"), "/verifyonly"], timeout=3600)
    if rc is None and ctx.cancelled():
        return []
    return [sfc_item(out, rc)]


def _wow64() -> bool:
    return IS_WIN and sys.maxsize <= 2 ** 32 and "PROGRAMW6432" in os.environ


def step_defender_scan(ctx: Ctx):
    third = ctx.data.get("third_party")
    if third:
        return [scan_item(None, third_party=third)]
    exe = mpcmdrun()
    if not exe:
        return [scan_item(None, "MpCmdRun.exe not found", third_party="another antivirus program")]
    rc, out = ctx.run([exe, "-Scan", "-ScanType", "2"], timeout=4 * 3600, on_cancel=[exe, "-Scan", "-Cancel"])
    if rc is None and ctx.cancelled():
        return []
    return [scan_item(rc, out)]


def build_steps(kind: str, readings: Callable[[Ctx], list[dict]], used_bytes: int | None = None) -> list[Step]:
    """readings(ctx) gives the live-reading, drive and crash items (from the API, which owns the sensors)."""
    steps = [
        Step("readings", "Checking temperatures, memory, space, fans, drives and crashes", 12, readings),
        Step("virus_protection", "Checking virus protection", 6, step_protection, title="Virus protection"),
        Step("devices", "Looking for problems in Device Manager", 6, step_devices, title="Devices"),
        Step("io", "Checking keyboard, mouse, screens, sound, network and USB", 6, step_io, title="Inputs and outputs"),
        Step("memory", "Looking for memory test results", 3, step_memory, title="Memory test"),
    ]
    if kind == "full":
        steps += [
            Step("updates", "Checking for Windows updates", 90, step_updates, full_only=True, needs_internet=True, title="Windows updates"),
            Step("drivers", "Checking how old your drivers are", 25, step_drivers, full_only=True, title="Driver age"),
            Step("windows_image", "Checking Windows' repair store (DISM)", 6 * 60, step_dism, full_only=True, title="Windows repair store"),
            Step("system_files", "Checking Windows system files (sfc)", 10 * 60, step_sfc, full_only=True, title="Windows system files"),
            Step("virus_scan", "Scanning every file for viruses", defender_estimate(used_bytes), step_defender_scan, full_only=True, title="Full virus scan"),
        ]
    return steps


# ================================================================== Fix it buttons
# risk follows the usual rules (Medium = "are you sure" + restore point). "job" fixes run in the background.
FIXES = {
    "sfc_repair": {"label": "Repair Windows files", "risk": "Medium", "job": True, "est": 15 * 60,
                   "cmd": ["sfc", "/scannow"], "online": False},
    "dism_repair": {"label": "Repair Windows' repair store", "risk": "Medium", "job": True, "est": 20 * 60,
                    "cmd": ["dism", "/English", "/Online", "/Cleanup-Image", "/RestoreHealth"], "online": True},
    "memtest": {"label": "Test my memory on the next restart", "risk": "Low", "job": False, "cmd": ["mdsched.exe"]},
    "open_updates": {"label": "Open Windows Update", "risk": "None", "job": False, "open": "ms-settings:windowsupdate"},
    "open_driver_updates": {"label": "Look for driver updates", "risk": "None", "job": False, "open": "ms-settings:windowsupdate-optionalupdates"},
    "open_devices": {"label": "Open Device Manager", "risk": "None", "job": False, "cmd": ["mmc", "devmgmt.msc"]},
    "open_security": {"label": "Open Windows Security", "risk": "None", "job": False, "open": "windowsdefender://threat"},
}


def repair_item(fix_id: str, rc: int | None, text: str) -> dict:
    t = re.sub(r"\s+", " ", (text or "")).lower()
    if fix_id == "sfc_repair":
        if "successfully repaired" in t or "did not find any integrity violations" in t:
            return {"id": "system_files", "title": "Windows system files", "state": "good", "say": "Windows repaired its files. Restart your PC to finish."}
        if "unable to fix" in t:
            return {"id": "system_files", "title": "Windows system files", "state": "bad", "say": "Windows couldn't repair some files. Try 'Repair Windows' repair store' first, then this again."}
    if fix_id == "dism_repair":
        if "restore operation completed successfully" in t or (rc == 0 and "error" not in t):
            return {"id": "windows_image", "title": "Windows repair store", "state": "good", "say": "Windows' repair store is fixed. Now run 'Repair Windows files'."}
    return {"id": fix_id, "title": FIXES.get(fix_id, {}).get("label", fix_id), "state": "warn",
            "say": "The repair didn't finish. Show details has the full output.", "details": (text or "")[-1500:]}
