"""Keeps your lighting devices found and lit without ever pressing Rescan (3.12).

What was wrong before (see the 3.12 notes): RigLab's "rescan" never actually asked the lighting service to look
for new hardware (the library has no such call), so retrying only re-read the same incomplete list; the list of
devices to wait for was overwritten by that incomplete list, so the retry stopped at once; after a full
shutdown with Windows' Fast Startup the boot time doesn't change, so the check didn't even run; and errors
were swallowed.

Now:
- every start, and after waking from sleep, and whenever a lighting device is plugged in, RigLab checks that
  every device it has seen in the last 30 days is there. Missing ones -> it re-reads the device list and, a few
  times, restarts its private lighting service (a real fresh hardware scan), with growing waits, for about two
  minutes after start-up. Then it reapplies your last effect.
- vendor apps that grab devices (G HUB, SteelSeries GG, iCUE...) are named in plain words with what to do.
- everything goes into the start-up log (Advanced view -> RigLab setup).
Pure logic + an engine interface, so it's tested with fakes.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time

log = logging.getLogger(__name__)

REMEMBER_DAYS = 30
# (seconds to wait before this try, what to do). "read" = ask the lighting service for its device list again
# (it may still be finding devices); "restart" = restart the lighting service so it scans the hardware afresh.
SCHEDULES = {
    "startup": [(0, "read"), (4, "read"), (6, "restart"), (10, "read"), (15, "restart"), (20, "read"), (25, "restart"), (30, "read")],
    "wake": [(4, "restart"), (8, "read"), (12, "restart"), (20, "read"), (30, "restart")],
    "device": [(3, "restart"), (6, "read"), (12, "read"), (20, "restart")],
    "manual": [(0, "restart"), (4, "read")],
}
REASON_WORDS = {"startup": "RigLab started", "wake": "the PC woke from sleep", "device": "a device was plugged in",
                "manual": "you pressed Rescan"}

VENDORS = [
    {"app": "Logitech G HUB", "procs": ["lghub.exe", "lghub_agent.exe", "lghub_system_tray.exe", "lghub_updater.exe"],
     "match": ["logitech", "lightsync", "g560", "g502", "g915", "g815", "g213", "g203", "g pro"],
     "fix": "Quit G HUB (right-click its icon next to the clock, then Quit), or turn off lighting control for that device in G HUB."},
    {"app": "SteelSeries GG", "procs": ["steelseriesgg.exe", "steelseriesengine.exe", "steelseriesggclient.exe"],
     "match": ["steelseries", "apex", "rival", "arctis", "aerox", "prime"],
     "fix": "Quit SteelSeries GG (right-click its icon next to the clock, then Exit), or turn off its lighting (Engine -> Illumination) for that device."},
    {"app": "Corsair iCUE", "procs": ["icue.exe", "corsair.service.exe", "icue5.exe", "corsairservice.exe"],
     "match": ["corsair", "lighting node", "commander", "vengeance", "dominator", "icue"],
     "fix": "Quit iCUE (right-click its icon next to the clock, then Quit), or turn on 'Enable SDK' in iCUE's settings so other apps can share the device."},
    {"app": "SignalRGB", "procs": ["signalrgb.exe", "signalrgblauncher.exe"], "match": [""],
     "fix": "Quit SignalRGB - it takes over most lighting devices."},
    {"app": "ASUS Armoury Crate", "procs": ["armourycrate.service.exe", "armourysocketserver.exe", "lightingservice.exe"],
     "match": ["asus", "aura", "rog"], "fix": "Turn off Aura Sync in Armoury Crate, or quit it."},
    {"app": "Razer Synapse", "procs": ["razer synapse 3.exe", "razersynapse.exe", "razer synapse service.exe"],
     "match": ["razer"], "fix": "Quit Razer Synapse, or turn off Chroma for that device."},
    {"app": "MSI Center", "procs": ["msi.centralserver.exe", "mysticlight_service.exe", "ledkeeper2.exe"],
     "match": ["msi", "mystic"], "fix": "Turn off Mystic Light in MSI Center, or quit it."},
]

# USB vendor IDs of lighting hardware: a device from one of these makers being plugged in triggers a scan
LIGHT_VIDS = {"046D": "Logitech", "1038": "SteelSeries", "1B1C": "Corsair", "0B05": "ASUS", "1462": "MSI", "1532": "Razer",
              "1E71": "NZXT", "048D": "ITE (motherboard RGB)", "1044": "Gigabyte", "0951": "HyperX", "03F0": "HyperX",
              "2516": "Cooler Master", "264A": "Thermaltake", "0CF2": "Lian Li", "26CE": "ASRock", "1A2C": "Evision",
              "3633": "Glorious", "2EA8": "Wooting", "320F": "Glorious", "1E7D": "ROCCAT"}


def vid_of(device_path: str) -> str | None:
    m = re.search(r"VID[_&]?([0-9A-F]{4})", (device_path or "").upper())
    return m.group(1) if m else None


def is_lighting_vid(vid: str | None) -> bool:
    return bool(vid) and vid.upper() in LIGHT_VIDS


def blockers(missing: list[str], running: set[str]) -> list[dict]:
    """Which running vendor apps could be holding the missing devices. running = lower-case process names."""
    out = []
    for v in VENDORS:
        if not any(p in running for p in v["procs"]):
            continue
        devs = [d for d in missing if any(m and m in d.lower() for m in v["match"])] if v["match"] != [""] else list(missing)
        if devs:
            out.append({"app": v["app"], "devices": devs,
                        "say": f"{v['app']} is running and may be holding {', '.join(devs)}. {v['fix']} RigLab will pick it up by itself."})
    return out


def running_processes() -> set[str]:
    try:
        import psutil
        return {(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
    except Exception:  # noqa: BLE001
        return set()


def known_devices(L: dict, now: float | None = None) -> dict:
    """Devices seen before, {name: last seen}. Older RigLab saved a plain list."""
    now = time.time() if now is None else now
    k = L.get("known_devices")
    if isinstance(k, list):
        k = {name: now for name in k if isinstance(name, str)}
    elif not isinstance(k, dict):
        k = {}
    L["known_devices"] = k
    return k


def remember(L: dict, keys, now: float | None = None) -> None:
    now = time.time() if now is None else now
    k = known_devices(L, now)
    for name in keys or []:
        k[name] = now


def expected(L: dict, now: float | None = None, days: float = REMEMBER_DAYS) -> list[str]:
    now = time.time() if now is None else now
    return [n for n, t in known_devices(L, now).items() if isinstance(t, (int, float)) and now - t <= days * 86400]


class LightWatch:
    """engine: needs .L, .keys, .client, .paused, .discover(), .full_rescan() -> bool, .reapply(), .msg"""

    def __init__(self, engine, save=lambda: None, events=None, notes=None, processes=running_processes,
                 sleep=time.sleep, clock=time.time, enabled=lambda: True, quitting=lambda: False):
        self.engine, self.save, self.events = engine, save, events
        self.notes = notes if notes is not None else []
        self.processes, self.sleep, self.clock = processes, sleep, clock
        self.enabled, self.quitting = enabled, quitting
        self.busy = False
        self.last: dict | None = None
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.idle = 5.0                               # the worker thread ends after this long with nothing to do

    def _log(self, kind, text, level="info", **extra):
        if self.events is not None:
            self.events.add(kind, text, level=level, **extra)
        (log.warning if level != "info" else log.info)("lighting %s: %s", kind, text)

    # ------------------------------------------------------------------ one check
    def check(self, reason: str = "startup") -> dict:
        """Look for every remembered device, retrying on the reason's schedule, then reapply the effect."""
        e = self.engine
        if not self.enabled() or getattr(e, "paused", False):
            self._log("scan", f"Skipped the lighting check ({REASON_WORDS.get(reason, reason)}): lighting is turned off in RigLab.")
            return {"skipped": True, "reason": reason}
        want = expected(e.L, self.clock())
        self.busy = True
        self._log("scan", f"Looking for your lights because {REASON_WORDS.get(reason, reason)}."
                  + (f" Expecting: {', '.join(want)}." if want else " No devices remembered yet."))
        tries, found, errors, restarted = 0, [], [], False
        try:
            for wait, action in SCHEDULES.get(reason, SCHEDULES["startup"]):
                if self.quitting():
                    break
                if wait:
                    self.sleep(wait)
                tries += 1
                try:
                    if action == "restart":
                        restarted = True
                        ok = e.full_rescan()
                        if not ok:
                            raise RuntimeError(getattr(e, "msg", "") or "the lighting service didn't start")
                    else:
                        if not e.client:
                            raise RuntimeError(getattr(e, "msg", "") or "the lighting service isn't running yet")
                        e.discover()
                    found = list(e.keys)
                except Exception as ex:  # noqa: BLE001 - logged, then the next try
                    errors.append(str(ex))
                    self._log("error", f"Try {tries} ({'fresh scan' if action == 'restart' else 'check'}): {ex}", level="warn")
                    continue
                missing = [d for d in want if d not in found]
                self._log("found", f"Try {tries} ({'fresh scan' if action == 'restart' else 'check'}): found {len(found)} - "
                          + (", ".join(found) or "nothing") + (f". Still missing: {', '.join(missing)}." if missing else "."),
                          level="info" if not missing else "warn", found=found, missing=missing)
                if found and not missing and (want or reason in ("startup", "manual") or restarted):
                    break
        finally:
            self.busy = False
        remember(e.L, found, self.clock())
        missing = [d for d in want if d not in found]
        reapplied = False
        if found:
            try:
                e.reapply()
                reapplied = True
                self._log("reapply", "Reapplied your last lighting effect to " + ", ".join(found) + ".")
            except Exception as ex:  # noqa: BLE001
                self._log("error", f"Couldn't reapply the effect: {ex}", level="error")
        blocked = blockers(missing, self.processes()) if missing else []
        for b in blocked:
            self._log("blocked", b["say"], level="warn")
        if missing:
            msg = (f"RigLab couldn't find {', '.join(missing)}. " + (" ".join(b["say"] for b in blocked) if blocked else
                   "Check it's plugged in. RigLab keeps watching and will light it as soon as it appears."))
            self._log("missing", msg, level="warn")
            self.notes[:] = [n for n in self.notes if n.get("title") != "Lighting device not found"]
            self.notes.append({"kind": "light", "title": "Lighting device not found", "text": msg, "page": "lighting"})
        else:
            self.notes[:] = [n for n in self.notes if n.get("title") != "Lighting device not found"]
        try:
            self.save()
        except Exception:  # noqa: BLE001
            pass
        self.last = {"reason": reason, "time": self.clock(), "tries": tries, "found": found, "missing": missing,
                     "blocked": blocked, "errors": errors, "reapplied": reapplied, "ok": not missing}
        return self.last

    # ------------------------------------------------------------------ background
    def request(self, reason: str, detail: str | None = None):
        """From any thread (device plugged in, PC woke up, start-up). Bursts are merged into one check."""
        if detail:
            self._log(reason if reason in ("wake", "device") else "scan", detail)
        self._q.put(reason)
        with self._lock:
            if not (self._thread and self._thread.is_alive()):
                self._thread = threading.Thread(target=self._worker, name="LightWatch", daemon=True)
                self._thread.start()

    def _worker(self):
        while not self.quitting():
            try:
                reason = self._q.get(timeout=self.idle)
            except queue.Empty:
                return
            self.sleep(1.5)                              # devices arrive in bursts: gather them up
            pending = {reason}
            while True:
                try:
                    pending.add(self._q.get_nowait())
                except queue.Empty:
                    break
            for r in ("manual", "startup", "wake", "device"):
                if r in pending:
                    try:
                        self.check(r)
                    except Exception as ex:  # noqa: BLE001
                        self._log("error", f"Lighting check failed: {ex}", level="error")
                    break
