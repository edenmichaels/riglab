"""Live hardware sensors.

Backends, tried in order and merged:
  1. LibreHardwareMonitor (via pythonnet) - temps, clocks, voltages, fans, power, controls
  2. NVIDIA NVML (pynvml)                - NVIDIA GPU stats even without LHM
  3. psutil                               - always-available CPU/RAM/disk/network usage
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import psutil

from .config import project_root, vendor_dir

log = logging.getLogger(__name__)

UNITS = {
    "Temperature": "°C", "Load": "%", "Clock": "MHz", "Voltage": "V", "Current": "A",
    "Power": "W", "Fan": "RPM", "Control": "%", "Level": "%", "Data": "GB",
    "SmallData": "MB", "Throughput": "B/s", "Frequency": "Hz", "Energy": "mWh",
    "Factor": "", "TimeSpan": "s", "Flow": "L/h", "Noise": "dBA", "Humidity": "%",
    "Conductivity": "µS/cm",
}


@dataclass
class Sensor:
    id: str               # stable unique id, e.g. "/amdcpu/0/temperature/2"
    hardware: str         # "AMD Ryzen 7 5800X"
    hw_type: str          # "Cpu", "GpuNvidia", "Memory", "Storage", "Motherboard", ...
    kind: str             # "Temperature", "Load", ...
    name: str             # "Core (Tctl/Tdie)"
    value: float | None
    min: float | None = None
    max: float | None = None
    controllable: bool = False

    @property
    def unit(self) -> str:
        return UNITS.get(self.kind, "")

    def fmt(self, value: float | None = None) -> str:
        v = self.value if value is None else value
        if v is None:
            return "—"
        if self.kind == "Throughput":
            return fmt_bytes(v) + "/s"
        if self.kind in ("Fan", "Clock"):
            return f"{v:,.0f} {self.unit}"
        if self.kind == "Voltage":
            return f"{v:.3f} V"
        return f"{v:.1f} {self.unit}".strip()


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n:.0f} B"
        n /= 1024
    return f"{n:.1f} TB"


# --------------------------------------------------------------------------- backends
class LHMBackend:
    """Proxy for the LibreHardwareMonitor worker process (see lhm_worker.py)."""

    name = "LibreHardwareMonitor"

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.proc = None
        self.conn = None
        self.error: str | None = None
        self.info: dict = {}
        self._latest: list[Sensor] = []
        self._send_lock = threading.Lock()
        self._controllable: set[str] = set()

    @staticmethod
    def dll_path() -> Path | None:
        for p in (vendor_dir() / "lhm", project_root() / "vendor" / "lhm"):
            dll = p / "LibreHardwareMonitorLib.dll"
            if dll.exists():
                return dll
        return None

    def start(self) -> bool:
        if sys.platform != "win32":
            self.error = "Windows only"
            return False
        dll = self.dll_path()
        if not dll:
            self.error = "LibreHardwareMonitorLib.dll is missing - Health check → Fix downloads it"
            return False
        import multiprocessing as mp
        from .lhm_worker import run_worker
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=run_worker, args=(child, str(dll), self.interval),
                                name="RigLabSensors", daemon=True)
        self.proc.start()
        if not self.conn.poll(45):
            self.error = "Sensor process didn't respond (timed out loading LibreHardwareMonitor)"
            self.stop()
            return False
        kind, info = self.conn.recv()
        self.info = info
        if not info.get("ok"):
            self.error = info.get("error", "unknown error")
            log.error("LHM worker failed: %s\n%s", self.error, info.get("trace", ""))
            self.stop()
            return False
        return True

    def read(self) -> list[Sensor]:
        if not self.conn:
            return self._latest
        try:
            while self.conn.poll(0):
                msg = self.conn.recv()
                if msg[0] == "sensors":
                    self._latest = [Sensor(**d) for d in msg[1]]
                    self._controllable = {s.id for s in self._latest if s.controllable}
        except (EOFError, OSError):
            self.error = "Sensor process stopped unexpectedly"
            self.conn = None
        return self._latest

    def set_control(self, sensor_id: str, percent: float | None) -> bool:
        if not self.conn or sensor_id not in self._controllable:
            return False
        with self._send_lock:
            try:
                self.conn.send(("set", sensor_id, percent))
            except (OSError, BrokenPipeError):
                return False
        return True

    def stop(self):
        if self.conn:
            try:
                with self._send_lock:
                    self.conn.send(("stop",))
            except (OSError, BrokenPipeError):
                pass
        if self.proc:
            self.proc.join(timeout=5)   # worker resets fans to BIOS control before exiting
            if self.proc.is_alive():
                self.proc.terminate()
        self.proc = None
        self.conn = None


LIGHTING_ONLY = ("lighting node", "vengeance", "hue 2", "hue+", "smart device v1 lighting", "aura", "rgb fusion")


class LiquidctlBackend:
    """USB fan hubs and AIOs through liquidctl - Corsair Commander Core / Core XT / ST / Pro,
    NZXT hubs and Krakens, etc. No iCUE / CAM needed."""

    name = "liquidctl (fan hubs / AIOs)"

    def __init__(self):
        self.devices: list = []
        self.error: str | None = None
        self.duty: dict[str, float] = {}         # sensor id -> last % we set
        self.channels: dict[str, tuple] = {}     # sensor id -> (device, channel)
        self._lock = threading.Lock()
        self.excluded: set[str] = set()
        self.skipped: list[str] = []
        self.enabled = True

    def start(self) -> bool:
        if not self.enabled:
            self.error = "Turned off in Settings"
            return False
        try:
            from liquidctl import find_liquidctl_devices
        except ImportError:
            self.error = "liquidctl is missing - reinstall RigLab"
            return False
        self.skipped = []
        try:
            for dev in find_liquidctl_devices():
                desc = dev.description
                # Lighting-only devices: never touch them - OpenRGB drives their LEDs, and resetting/polling
                # them from here breaks the lighting (e.g. Corsair Lighting Node Pro/Core).
                if any(k in desc.lower() for k in LIGHTING_ONLY) or desc in self.excluded:
                    self.skipped.append(f"{desc} (lighting only - left to OpenRGB)" if desc not in self.excluded
                                        else f"{desc} (excluded in Settings)")
                    continue
                try:
                    dev.connect()
                    dev.initialize()
                    if not any(u == "rpm" for _, _, u in dev.get_status()):
                        self.skipped.append(f"{desc} (no fan channels)")
                        dev.disconnect()
                        continue
                    self.devices.append(dev)
                except Exception as e:  # noqa: BLE001
                    log.warning("liquidctl: %s failed to init: %s", desc, e)
                    self.skipped.append(f"{desc} (failed: {e})")
                    try:
                        dev.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as e:  # noqa: BLE001
            self.error = f"liquidctl scan failed: {e}"
            return False
        if not self.devices:
            self.error = "No USB fan hubs/AIOs with fan control found" + (
                f" (skipped: {'; '.join(self.skipped)})" if self.skipped else "")
            return False
        return True

    def read(self) -> list[Sensor]:
        out: list[Sensor] = []
        with self._lock:
            for i, dev in enumerate(self.devices):
                name = dev.description.replace(" (experimental)", "")
                try:
                    status = dev.get_status()
                except Exception:  # noqa: BLE001
                    continue
                for key, value, unit in status:
                    k = key.lower()
                    base = f"/liquidctl/{i}/"
                    if unit == "rpm":
                        m = re.search(r"(\d)", key)
                        ch = "pump" if "pump" in k else f"fan{m.group(1)}" if m else "fan"
                        out.append(Sensor(base + "rpm/" + ch, name, "Controller", "Fan", key, float(value)))
                        cid = base + "control/" + ch
                        if float(value) <= 0 and cid not in self.duty:
                            continue  # nothing plugged into this channel
                        self.channels[cid] = (dev, ch)
                        out.append(Sensor(cid, name, "Controller", "Control",
                                          "Pump" if ch == "pump" else f"Fan {ch[3:]}".strip(),
                                          self.duty.get(cid), controllable=True))
                    elif unit in ("°C", "C"):
                        out.append(Sensor(base + "temp/" + re.sub(r"\W+", "_", k), name, "Controller",
                                          "Temperature", key, float(value)))
                    elif unit == "%" and "duty" in k:
                        pass
        return out

    def set_control(self, sensor_id: str, percent: float | None) -> bool:
        target = self.channels.get(sensor_id)
        if not target:
            return False
        dev, ch = target
        with self._lock:
            try:
                if percent is None:
                    dev.initialize()             # back to the hub's own default speeds
                    for cid, (d, _) in self.channels.items():
                        if d is dev:
                            self.duty.pop(cid, None)
                else:
                    dev.set_fixed_speed(ch, int(round(percent)))
                    self.duty[sensor_id] = float(round(percent))
                return True
            except Exception:  # noqa: BLE001
                log.exception("liquidctl set failed")
                return False

    def stop(self):
        with self._lock:
            for dev in self.devices:
                try:
                    if any(d is dev for d, _ in self.channels.values()):
                        dev.initialize()
                    dev.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            self.devices.clear()


def _f(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


class NVMLBackend:
    name = "NVIDIA NVML"

    def __init__(self):
        self.nv = None
        self.handles = []
        self.error: str | None = None

    def start(self) -> bool:
        try:
            import pynvml as nv
            nv.nvmlInit()
            self.nv = nv
            self.handles = [nv.nvmlDeviceGetHandleByIndex(i) for i in range(nv.nvmlDeviceGetCount())]
            return bool(self.handles)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            return False

    def gpu_name(self, i: int) -> str:
        n = self.nv.nvmlDeviceGetName(self.handles[i])
        return n.decode() if isinstance(n, bytes) else str(n)

    def read(self) -> list[Sensor]:
        nv, out = self.nv, []
        for i, h in enumerate(self.handles):
            name = self.gpu_name(i)
            base = f"/nvml/{i}"

            def add(kind, label, fn, scale=1.0):
                try:
                    out.append(Sensor(f"{base}/{kind.lower()}/{label}", name, "GpuNvidia", kind, label, fn() * scale))
                except Exception:  # noqa: BLE001
                    pass

            add("Temperature", "GPU Core", lambda: nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU))
            add("Load", "GPU Core", lambda: nv.nvmlDeviceGetUtilizationRates(h).gpu)
            add("Load", "GPU Memory Controller", lambda: nv.nvmlDeviceGetUtilizationRates(h).memory)
            add("Clock", "GPU Core", lambda: nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_GRAPHICS))
            add("Clock", "GPU Memory", lambda: nv.nvmlDeviceGetClockInfo(h, nv.NVML_CLOCK_MEM))
            add("Power", "GPU Package", lambda: nv.nvmlDeviceGetPowerUsage(h), 0.001)
            add("Control", "GPU Fan", lambda: nv.nvmlDeviceGetFanSpeed(h))
            add("SmallData", "GPU Memory Used", lambda: nv.nvmlDeviceGetMemoryInfo(h).used, 1 / 2**20)
            add("SmallData", "GPU Memory Total", lambda: nv.nvmlDeviceGetMemoryInfo(h).total, 1 / 2**20)
        return out

    # ---- power limit tweak (needs admin)
    def power_limits(self, i: int = 0) -> tuple[float, float, float]:
        """(min_w, max_w, current_w)"""
        h = self.handles[i]
        lo, hi = self.nv.nvmlDeviceGetPowerManagementLimitConstraints(h)
        cur = self.nv.nvmlDeviceGetPowerManagementLimit(h)
        return lo / 1000, hi / 1000, cur / 1000

    def set_power_limit(self, watts: float, i: int = 0) -> None:
        lo, hi, _ = self.power_limits(i)
        w = max(lo, min(hi, watts))
        self.nv.nvmlDeviceSetPowerManagementLimit(self.handles[i], int(w * 1000))

    def stop(self):
        if self.nv:
            try:
                self.nv.nvmlShutdown()
            except Exception:  # noqa: BLE001
                pass


class PsutilBackend:
    name = "psutil"

    def __init__(self):
        self._last_net = None
        self._last_disk = None
        self._last_t = None
        self.error = None
        self.cpu_name = _cpu_name()

    def start(self) -> bool:
        psutil.cpu_percent(percpu=True)  # prime
        return True

    def read(self) -> list[Sensor]:
        out: list[Sensor] = []
        cpu = self.cpu_name
        per = psutil.cpu_percent(percpu=True)
        out.append(Sensor("/ps/cpu/load/total", cpu, "Cpu", "Load", "CPU Total", sum(per) / max(1, len(per))))
        for i, p in enumerate(per):
            out.append(Sensor(f"/ps/cpu/load/{i}", cpu, "Cpu", "Load", f"Thread #{i + 1}", p))
        f = psutil.cpu_freq()
        if f:
            out.append(Sensor("/ps/cpu/clock/avg", cpu, "Cpu", "Clock", "Average Clock", f.current))

        vm = psutil.virtual_memory()
        out.append(Sensor("/ps/ram/load", "Memory", "Memory", "Load", "Memory", vm.percent))
        out.append(Sensor("/ps/ram/used", "Memory", "Memory", "Data", "Memory Used", vm.used / 2**30))
        out.append(Sensor("/ps/ram/avail", "Memory", "Memory", "Data", "Memory Available", vm.available / 2**30))

        now = time.monotonic()
        net = psutil.net_io_counters()
        try:
            disk = psutil.disk_io_counters()
        except Exception:  # noqa: BLE001
            disk = None
        if self._last_t is not None:
            dt = max(1e-3, now - self._last_t)
            out.append(Sensor("/ps/net/down", "Network", "Network", "Throughput", "Download",
                              (net.bytes_recv - self._last_net.bytes_recv) / dt))
            out.append(Sensor("/ps/net/up", "Network", "Network", "Throughput", "Upload",
                              (net.bytes_sent - self._last_net.bytes_sent) / dt))
            if disk and self._last_disk:
                out.append(Sensor("/ps/disk/read", "Disks (all)", "Storage", "Throughput", "Read",
                                  (disk.read_bytes - self._last_disk.read_bytes) / dt))
                out.append(Sensor("/ps/disk/write", "Disks (all)", "Storage", "Throughput", "Write",
                                  (disk.write_bytes - self._last_disk.write_bytes) / dt))
        self._last_net, self._last_disk, self._last_t = net, disk, now

        # Linux/mac only - Windows returns nothing here, LHM covers it.
        temps = getattr(psutil, "sensors_temperatures", lambda: {})()
        for chip, entries in (temps or {}).items():
            for j, t in enumerate(entries):
                out.append(Sensor(f"/ps/temp/{chip}/{j}", chip, "Motherboard", "Temperature",
                                  t.label or f"{chip} {j}", t.current))
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if bat:
            out.append(Sensor("/ps/battery", "Battery", "Battery", "Level", "Charge", bat.percent))
        return out

    def stop(self):
        pass


def _cpu_name() -> str:
    import platform
    if sys.platform == "win32":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "CPU"


# --------------------------------------------------------------------------- hub
@dataclass
class Snapshot:
    t: float
    sensors: dict[str, Sensor] = field(default_factory=dict)


class SensorHub:
    """Polls all backends on a background thread and keeps history for graphs."""

    def __init__(self, interval_s: float = 1.0, history_s: int = 300):
        self.interval_s = interval_s
        self.lhm = LHMBackend(interval_s)
        self.liquid = LiquidctlBackend()
        self.nvml = NVMLBackend()
        self.ps = PsutilBackend()
        self._minmax: dict[str, list[float]] = {}
        self.active: list = []
        self.latest = Snapshot(time.time())
        self.history: dict[str, deque] = {}
        self.history_len = max(10, int(history_s / max(0.1, interval_s)))
        self._listeners: list[Callable[[Snapshot], None]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status: dict[str, str] = {}

    def start(self):
        for b in (self.nvml, self.liquid, self.ps):
            self._start_backend(b)
        self._poll_once()
        self._thread = threading.Thread(target=self._run, name="SensorHub", daemon=True)
        self._thread.start()
        self.start_lhm()

    def _start_backend(self, b) -> bool:
        ok = False
        try:
            ok = b.start()
        except Exception as e:  # noqa: BLE001
            b.error = str(e)
        self.status[b.name] = "active" if ok else (b.error or "unavailable")
        if ok and b not in self.active:
            self.active.insert(0, b)
        return ok

    def start_lhm(self):
        """LHM can take a while to load, so it starts in the background."""
        if self.lhm in self.active:
            self.active.remove(self.lhm)
            self.lhm.stop()
        self.lhm.error = None
        self.lhm.info = {}
        self.status[self.lhm.name] = "starting"
        threading.Thread(target=self._start_backend, args=(self.lhm,), daemon=True).start()

    def set_control(self, sensor_id: str, percent: float | None) -> bool:
        b = self.liquid if sensor_id.startswith("/liquidctl/") else self.lhm
        return b.set_control(sensor_id, percent)

    def subscribe(self, fn: Callable[[Snapshot], None]):
        self._listeners.append(fn)

    def _run(self):
        while not self._stop.wait(self.interval_s):
            self._poll_once()

    def _poll_once(self):
        merged: dict[str, Sensor] = {}
        lhm_has_nvidia = lhm_has_cpu = False
        for b in list(self.active):
            if b is self.nvml and lhm_has_nvidia:
                continue  # avoid duplicate GPU rows
            try:
                for s in b.read():
                    if b is self.ps and lhm_has_cpu and s.id.startswith("/ps/cpu/"):
                        continue  # LHM already has better CPU data
                    merged[s.id] = s
                    if b is self.lhm and s.hw_type == "Cpu":
                        lhm_has_cpu = True
                    if b is self.lhm and s.hw_type == "GpuNvidia":
                        lhm_has_nvidia = True
            except Exception:  # noqa: BLE001
                log.exception("backend %s read failed", b.name)
        snap = Snapshot(time.time(), merged)
        with self._lock:
            self.latest = snap
            for sid, s in merged.items():
                if s.value is None:
                    continue
                mm = self._minmax.setdefault(sid, [s.value, s.value])
                mm[0], mm[1] = min(mm[0], s.value), max(mm[1], s.value)
                if s.min is None:
                    s.min = mm[0]
                if s.max is None:
                    s.max = mm[1]
                dq = self.history.get(sid)
                if dq is None:
                    dq = self.history[sid] = deque(maxlen=self.history_len)
                dq.append((snap.t, s.value))
        for fn in list(self._listeners):
            try:
                fn(snap)
            except Exception:  # noqa: BLE001
                log.exception("listener failed")

    def series(self, sensor_id: str) -> list[tuple[float, float]]:
        with self._lock:
            return list(self.history.get(sensor_id, ()))

    # ---- convenience lookups used by dashboard / alerts / stress test
    def find(self, hw_type_prefix: str, kind: str, name_contains: tuple[str, ...] = ()) -> Sensor | None:
        cands = [s for s in self.latest.sensors.values()
                 if s.hw_type.startswith(hw_type_prefix) and s.kind == kind and s.value is not None]
        for needle in name_contains:
            for s in cands:
                if needle.lower() in s.name.lower():
                    return s
        return cands[0] if cands else None

    def cpu_temp(self) -> Sensor | None:
        return self.find("Cpu", "Temperature", ("Tctl", "Package", "Tdie", "Core (Tctl", "CPU", "Core Max"))

    def cpu_load(self) -> Sensor | None:
        return self.find("Cpu", "Load", ("Total",))

    def cpu_clock(self) -> float | None:
        clocks = [s.value for s in self.latest.sensors.values()
                  if s.hw_type == "Cpu" and s.kind == "Clock" and "core" in s.name.lower()
                  and "bus" not in s.name.lower() and s.value]
        if clocks:
            return sum(clocks) / len(clocks)
        s = self.find("Cpu", "Clock")
        return s.value if s else None

    def cpu_power(self) -> Sensor | None:
        return self.find("Cpu", "Power", ("Package", "CPU"))

    def gpu_temp(self) -> Sensor | None:
        return self.find("Gpu", "Temperature", ("Core", "GPU", "Hot"))

    def gpu_load(self) -> Sensor | None:
        return self.find("Gpu", "Load", ("Core", "D3D 3D", "GPU"))

    def gpu_power(self) -> Sensor | None:
        return self.find("Gpu", "Power", ("Package", "Total", "GPU"))

    def ram_load(self) -> Sensor | None:
        return self.find("Memory", "Load", ("Memory",))

    def controls(self) -> list[Sensor]:
        return [s for s in self.latest.sensors.values() if s.controllable]

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        for b in list(self.active) + [self.lhm]:
            try:
                b.stop()
            except Exception:  # noqa: BLE001
                pass
