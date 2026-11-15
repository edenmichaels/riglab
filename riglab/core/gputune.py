"""Live GPU tuning + performance runs - for whatever graphics card is in the machine.

detect_gpus() asks Windows which cards are installed (PCI vendor id), then the matching backend is used:
  NVIDIA  -> NVML (nvml.dll, ships with every NVIDIA driver): core/memory clock offsets, max-clock cap,
             power limit, manual fan speed.
  AMD     -> ADLX (see below).
  Intel   -> live readout + benchmarks (tuning is done in Intel Graphics Software).
FPS for third-party benchmarks/games comes from PresentMon (Intel, MIT licence) on any brand of card.

AMD Radeon (RDNA2/RDNA3/RDNA4) -> ADLX, the driver's own tuning interface (amdadlx64.dll, ships with
Adrenalin; SDK is MIT-licensed: github.com/GPUOpen-LibrariesAndSDKs/ADLX). We call its C interfaces through
ctypes (vtable indices taken from the SDK's C headers). Everything runs in a separate worker process, so a
driver hiccup can never take RigLab down with it. Settings are applied exactly like Adrenalin's Tuning page.

NVIDIA -> NVML power limit (clock offsets need MSI Afterburner).
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
from pathlib import Path

from .config import app_dir

log = logging.getLogger(__name__)
RUNS_FILE = "gpu_runs.json"
PENDING_FILE = "gpu_tune_pending.json"
MEM_TIMINGS = {0: "Default", 1: "Fast Timing", 2: "Fast Timing level 2", 3: "Automatic", 4: "Level 1", 5: "Level 2"}


# =========================================================================== ADLX (worker side)
class _ADLX:
    def __init__(self):
        import ctypes as C
        self.C = C
        dll = C.CDLL("amdadlx64.dll")
        ver = C.c_uint64(0)
        dll.ADLXQueryFullVersion.argtypes = [C.POINTER(C.c_uint64)]
        dll.ADLXQueryFullVersion(C.byref(ver))
        self.sys = C.c_void_p()
        if hasattr(dll, "ADLXInitialize2"):
            mapping = C.c_void_p()
            dll.ADLXInitialize2.argtypes = [C.c_uint64, C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)]
            res = dll.ADLXInitialize2(ver.value, C.byref(self.sys), C.byref(mapping))
        else:
            dll.ADLXInitialize.argtypes = [C.c_uint64, C.POINTER(C.c_void_p)]
            res = dll.ADLXInitialize(ver.value, C.byref(self.sys))
        if res not in (0, 1, 2) or not self.sys:
            raise RuntimeError(f"ADLX initialise failed (code {res}) - update the AMD Adrenalin driver")
        self.dll, self.version = dll, ver.value
        self.tuning = self._out(self.sys, 8)                         # IADLXSystem::GetGPUTuningServices
        self.perf = self._out(self.sys, 9)                           # GetPerformanceMonitoringServices
        gpus = self._out(self.sys, 1)                                # GetGPUs
        self.gpu = None
        n = self._call(gpus, 3, (), restype=C.c_uint)                 # Size
        for i in range(n):
            g = C.c_void_p()
            if self._call(gpus, 11, (C.c_uint, C.POINTER(C.c_void_p)), C.c_uint(i), C.byref(g)) == 0 and g:  # At_GPUList
                vendor = self._str(g, 3)
                if self.gpu is None or vendor.lower() == "1002" and self._u(g, 11) > self._u(self.gpu, 11):
                    self.gpu = g                                      # biggest AMD card wins (skip iGPU)
        if self.gpu is None:
            raise RuntimeError("No AMD graphics card found by ADLX")
        self.gfx = self.vram = self.power = self.fan = None
        self.gfx_def = None
        for idx_sup, idx_get, attr, iids in ((8, 14, "gfx", ("IADLXManualGraphicsTuning2_1", "IADLXManualGraphicsTuning2")),
                                             (9, 15, "vram", ("IADLXManualVRAMTuning2",)),
                                             (11, 17, "power", ("IADLXManualPowerTuning1", "IADLXManualPowerTuning")),
                                             (10, 16, "fan", ("IADLXManualFanTuning",))):
            if not self._bool_gpu(self.tuning, idx_sup):
                continue
            base = self._out_gpu(self.tuning, idx_get)
            for iid in iids:
                q = self._qi(base, iid)
                if q:
                    setattr(self, attr, (q, iid))
                    break

    # ---------------------------------------------------------------- ctypes plumbing
    def _call(self, obj, idx, argtypes, *args, restype=None):
        C = self.C
        vtbl = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p)))[0]
        fn = C.WINFUNCTYPE(restype or C.c_int, C.c_void_p, *argtypes)(vtbl[idx])
        return fn(obj, *args)

    def _out(self, obj, idx):
        p = self.C.c_void_p()
        r = self._call(obj, idx, (self.C.POINTER(self.C.c_void_p),), self.C.byref(p))
        return p if r == 0 and p else None

    def _out_gpu(self, obj, idx):
        p = self.C.c_void_p()
        r = self._call(obj, idx, (self.C.c_void_p, self.C.POINTER(self.C.c_void_p)), self.gpu, self.C.byref(p))
        return p if r == 0 and p else None

    def _bool_gpu(self, obj, idx):
        b = self.C.c_bool(False)
        r = self._call(obj, idx, (self.C.c_void_p, self.C.POINTER(self.C.c_bool)), self.gpu, self.C.byref(b))
        return r == 0 and bool(b.value)

    def _qi(self, obj, iid):
        if not obj:
            return None
        p = self.C.c_void_p()
        r = self._call(obj, 2, (self.C.c_wchar_p, self.C.POINTER(self.C.c_void_p)), iid, self.C.byref(p))
        return p if r == 0 and p else None

    def _str(self, obj, idx):
        s = self.C.c_char_p()
        self._call(obj, idx, (self.C.POINTER(self.C.c_char_p),), self.C.byref(s))
        return (s.value or b"").decode(errors="replace")

    def _u(self, obj, idx):
        v = self.C.c_uint(0)
        self._call(obj, idx, (self.C.POINTER(self.C.c_uint),), self.C.byref(v))
        return v.value

    def _int(self, obj, idx):
        v = self.C.c_int(0)
        return v.value if self._call(obj, idx, (self.C.POINTER(self.C.c_int),), self.C.byref(v)) == 0 else None

    def _dbl(self, obj, idx):
        v = self.C.c_double(0)
        return v.value if self._call(obj, idx, (self.C.POINTER(self.C.c_double),), self.C.byref(v)) == 0 else None

    def _bool(self, obj, idx):
        v = self.C.c_bool(False)
        return bool(v.value) if self._call(obj, idx, (self.C.POINTER(self.C.c_bool),), self.C.byref(v)) == 0 else None

    def _range(self, obj, idx):
        C = self.C

        class R(C.Structure):
            _fields_ = [("min", C.c_int), ("max", C.c_int), ("step", C.c_int)]
        r = R()
        return {"min": r.min, "max": r.max, "step": max(1, r.step)} if self._call(obj, idx, (C.POINTER(R),), C.byref(r)) == 0 else None

    def _set(self, obj, idx, value):
        return self._call(obj, idx, (self.C.c_int,), self.C.c_int(int(value)))

    def _setb(self, obj, idx, value):
        return self._call(obj, idx, (self.C.c_bool,), self.C.c_bool(bool(value)))

    # ---------------------------------------------------------------- public (worker commands)
    def info(self):
        g = self.gpu
        name = self._str(g, 7)
        g1 = self._qi(g, "IADLXGPU1")
        if g1:
            name = self._str(g1, 22) or name
        C = self.C
        pn, ver, date = C.c_char_p(), C.c_char_p(), C.c_char_p()
        self._call(g, 13, (C.POINTER(C.c_char_p),) * 3, C.byref(pn), C.byref(ver), C.byref(date))
        return {"name": name, "vram_mb": self._u(g, 11), "vram_type": self._str(g, 12), "device_id": self._str(g, 14),
                "bios": (ver.value or b"").decode(errors="replace"), "bios_date": (date.value or b"").decode(errors="replace"),
                "adlx": f"{self.version >> 48}.{(self.version >> 32) & 0xFFFF}.{self.version & 0xFFFF}"}

    def _ctl(self, obj, rng_idx, get_idx, def_idx=None, label="", unit="", help=""):
        rng = self._range(obj, rng_idx)
        if not rng:
            return None
        d = self._int(obj, def_idx) if def_idx is not None else None
        return dict(rng, value=self._int(obj, get_idx), default=d, label=label, unit=unit, help=help)

    def read(self):
        out, caps = {}, {}
        if self.gfx:
            o, iid = self.gfx
            has_def = iid.endswith("_1")
            caps["core_max"] = self._ctl(o, 6, 7, 13 if has_def else None, "Max core clock", "MHz",
                                         "Upper clock the GPU boosts to. Raise in 25-50 MHz steps and test each step.")
            caps["core_min"] = self._ctl(o, 3, 4, 12 if has_def else None, "Min core clock", "MHz",
                                         "Lowest clock under load. Leave at stock unless clocks drop in light games.")
            caps["voltage"] = self._ctl(o, 9, 10, 14 if has_def else None, "Max voltage", "mV",
                                        "Lower = undervolt: cooler, quieter and often faster on RDNA3. Drop 10-25 mV at a time.")
        if self.vram:
            o, _ = self.vram
            caps["vram_max"] = self._ctl(o, 7, 8, None, "Max VRAM clock", "MHz",
                                         "Memory speed. Fast Timing first, then +25-50 MHz steps. Watch for artefacts and lower scores.")
            if self._bool(o, 3):
                v = self.C.c_int(0)
                self._call(o, 5, (self.C.POINTER(self.C.c_int),), self.C.byref(v))
                caps["mem_timing"] = {"value": v.value, "options": {k: MEM_TIMINGS[k] for k in (0, 1, 2)}, "label": "Memory timing",
                                      "help": "Fast Timing tightens VRAM timings: free performance on most cards."}
        if self.power:
            o, iid = self.power
            has_def = iid.endswith("1")
            caps["power"] = self._ctl(o, 3, 4, 10 if has_def else None, "Power limit", "%",
                                      "How much more power the card may draw. Max it out when overclocking - it's safe within AMD's range.")
            if self._bool(o, 6):
                caps["tdc"] = self._ctl(o, 7, 8, 11 if has_def else None, "Current limit (TDC)", "%", "Current limit. Usually leave at stock.")
        if self.fan:
            o, _ = self.fan
            if self._bool(o, 8):
                caps["zero_rpm"] = {"value": self._bool(o, 9), "label": "Zero RPM", "help": "Fans stop at idle. Turn off for a cooler card at idle."}
            if self._bool(o, 15):
                caps["fan_min"] = self._ctl(o, 16, 17, None, "Min fan speed", "%", "Fans never spin slower than this under load.")
            if self._bool(o, 19):
                caps["fan_target"] = self._ctl(o, 20, 21, None, "Target fan speed", "RPM", "Speed the fans aim for under load.")
            if self._bool(o, 11):
                caps["fan_acoustic"] = self._ctl(o, 12, 13, None, "Acoustic limit", "MHz", "Clock where the fans start ramping.")
        out["caps"] = {k: v for k, v in caps.items() if v}
        f = self.C.c_bool(False)
        self._call(self.tuning, 4, (self.C.c_void_p, self.C.POINTER(self.C.c_bool)), self.gpu, self.C.byref(f))
        out["at_factory"] = bool(f.value)
        return out

    SETTERS = {"core_max": ("gfx", 8), "core_min": ("gfx", 5), "voltage": ("gfx", 11), "vram_max": ("vram", 9),
               "mem_timing": ("vram", 6), "power": ("power", 5), "tdc": ("power", 9), "zero_rpm": ("fan", 10),
               "fan_min": ("fan", 18), "fan_target": ("fan", 22), "fan_acoustic": ("fan", 14)}

    def apply(self, values: dict):
        res = {}
        for k, v in values.items():
            if k not in self.SETTERS or v is None:
                continue
            attr, idx = self.SETTERS[k]
            obj = getattr(self, attr)
            if not obj:
                res[k] = "not supported"
                continue
            r = self._setb(obj[0], idx, v) if k == "zero_rpm" else self._set(obj[0], idx, v)
            res[k] = "ok" if r in (0, 1) else {3: "rejected", 4: "out of range", 9: "not supported", 10: "busy"}.get(r, f"error {r}")
        return res

    def reset(self):
        return self._call(self.tuning, 5, (self.C.c_void_p,), self.gpu) == 0

    def metrics(self):
        m = self._out_gpu(self.perf, 18)
        if not m:
            return {}
        out = {"usage": self._dbl(m, 4), "clock": self._int(m, 5), "vram_clock": self._int(m, 6), "temp": self._dbl(m, 7),
               "hotspot": self._dbl(m, 8), "power": self._dbl(m, 9), "board_power": self._dbl(m, 10), "fan": self._int(m, 11),
               "vram_used": self._int(m, 12), "voltage": self._int(m, 13)}
        self._call(m, 1, (), restype=self.C.c_long)
        fps = self._out(self.perf, 20)
        if fps:
            v = self.C.c_int(0)
            if self._call(fps, 4, (self.C.POINTER(self.C.c_int),), self.C.byref(v)) == 0 and v.value > 0:
                out["fps"] = v.value
            self._call(fps, 1, (), restype=self.C.c_long)
        return {k: v for k, v in out.items() if v is not None and v != -1}


def worker(conn):
    """Separate process: owns the ADLX connection and answers commands."""
    try:
        a = _ADLX()
        conn.send(("ready", a.info()))
    except Exception as e:  # noqa: BLE001
        conn.send(("error", str(e)))
        return
    while True:
        try:
            cmd, args = conn.recv()
        except (EOFError, OSError):
            return
        try:
            if cmd == "quit":
                return
            conn.send(("ok", getattr(a, cmd)(*args)))
        except Exception as e:  # noqa: BLE001
            conn.send(("error", f"{type(e).__name__}: {e}"))


# =========================================================================== detection
VENDORS = {"10DE": "nvidia", "1002": "amd", "8086": "intel"}


def detect_gpus() -> list[dict]:
    """Every display adapter Windows knows about, discrete cards first."""
    if sys.platform != "win32":
        return []
    ps = ("Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,DriverVersion,AdapterRAM,"
          "VideoProcessor | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20,
                             creationflags=0x08000000).stdout
        data = json.loads(out or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    if isinstance(data, dict):
        data = [data]
    gpus = []
    for d in data:
        pnp = (d.get("PNPDeviceID") or "").upper()
        m = re.search(r"VEN_([0-9A-F]{4})", pnp)
        vendor = VENDORS.get(m.group(1) if m else "", "other")
        name = d.get("Name") or "Unknown"
        if "basic display" in name.lower() or "remote" in name.lower():
            continue
        integrated = vendor == "intel" and "arc" not in name.lower() or \
            vendor == "amd" and re.search(r"radeon\(tm\) graphics|vega \d+ graphics|radeon graphics$", name, re.I) is not None
        gpus.append({"name": name, "vendor": vendor, "driver": d.get("DriverVersion"), "pnp": pnp, "integrated": integrated})
    gpus.sort(key=lambda g: (g["integrated"], {"nvidia": 0, "amd": 1, "intel": 2}.get(g["vendor"], 3)))
    return gpus


# =========================================================================== NVIDIA (NVML)
class _NVML:
    """NVIDIA cards through NVML (nvml.dll, part of every NVIDIA driver). Runs in-process: NVML is stable."""

    STATE = "gpu_nvml_state.json"

    def __init__(self, index: int = 0):
        import pynvml as nv
        nv.nvmlInit()
        self.nv = nv
        self.h = nv.nvmlDeviceGetHandleByIndex(index)
        self.mine = _read(self.STATE, {})          # things NVML can set but not read back (max-clock cap, fan mode)

    def _try(self, fn, *a, default=None):
        try:
            return fn(*a)
        except Exception:  # noqa: BLE001
            return default

    def info(self):
        nv, h = self.nv, self.h
        name = nv.nvmlDeviceGetName(h)
        mem = self._try(nv.nvmlDeviceGetMemoryInfo, h)
        return {"name": name if isinstance(name, str) else name.decode(), "vram_mb": int(mem.total / 2**20) if mem else None,
                "bios": self._try(nv.nvmlDeviceGetVbiosVersion, h), "driver": self._try(nv.nvmlSystemGetDriverVersion),
                "vram_type": "", "api": "NVML"}

    def _offsets(self, kind):
        """(value, lo, hi) of a clock offset, via whichever NVML API this driver has."""
        nv, h = self.nv, self.h
        get, rng = ((nv.nvmlDeviceGetGpcClkVfOffset, nv.nvmlDeviceGetGpcClkMinMaxVfOffset) if kind == "core" else
                    (nv.nvmlDeviceGetMemClkVfOffset, nv.nvmlDeviceGetMemClkMinMaxVfOffset))
        v, r = self._try(get, h), self._try(rng, h)
        if v is not None and r:
            return v, r[0], r[1]
        info = self._clock_offsets(kind)
        if info is not None:
            return info.clockOffsetMHz, info.minClockOffsetMHz, info.maxClockOffsetMHz
        return None

    def _clock_offsets(self, kind, set_mhz=None):
        """Newer NVML clock-offset API (drivers 555+). Called directly: the Python wrapper ignores errors."""
        import ctypes
        nv = self.nv
        if not hasattr(nv, "c_nvmlClockOffset_t"):
            return None
        info = nv.c_nvmlClockOffset_t()
        info.version = nv.nvmlClockOffset_v1
        info.type = nv.NVML_CLOCK_GRAPHICS if kind == "core" else nv.NVML_CLOCK_MEM
        info.pstate = nv.NVML_PSTATE_0
        try:
            get = nv._nvmlGetFunctionPointer("nvmlDeviceGetClockOffsets")
            if get(self.h, ctypes.byref(info)) != 0:
                return None
            if set_mhz is not None:
                info.clockOffsetMHz = int(set_mhz)
                ret = nv._nvmlGetFunctionPointer("nvmlDeviceSetClockOffsets")(self.h, ctypes.byref(info))
                if ret != 0:
                    raise nv.NVMLError(ret)
            return info
        except nv.NVMLError:
            raise
        except Exception:  # noqa: BLE001
            return None

    def read(self):
        caps, self.read_errors = {}, {}
        for part in (self._read_core, self._read_mem, self._read_cap, self._read_power, self._read_fans):
            try:
                part(caps)
            except Exception as e:  # noqa: BLE001
                self.read_errors[part.__name__[6:]] = f"{type(e).__name__}: {e}"
                log.warning("NVML %s: %s", part.__name__, e)
        stock = all(c.get("default") is None or c["value"] == c["default"] for c in caps.values() if "min" in c) \
            and not self.mine.get("fan_manual")
        return {"caps": caps, "at_factory": stock, "errors": self.read_errors}

    def _read_core(self, caps):
        o = self._offsets("core")
        if o:
            caps["core_offset"] = {"value": o[0], "min": max(o[1], -500), "max": min(o[2], 500), "step": 5, "default": 0,
                                   "label": "Core clock offset", "unit": "MHz",
                                   "help": "Shifts the whole boost curve. Raise in +15-30 MHz steps and test each step."}

    def _read_mem(self, caps):
        o = self._offsets("mem")
        if o:
            caps["mem_offset"] = {"value": o[0], "min": max(o[1], -1000), "max": min(o[2], 3000), "step": 10, "default": 0,
                                  "label": "Memory clock offset", "unit": "MHz",
                                  "help": "VRAM overclock. Go up +100-200 at a time; if the score drops, memory error-correction "
                                          "has kicked in, so back off."}

    def _read_cap(self, caps):
        nv, h = self.nv, self.h
        mx = self._try(nv.nvmlDeviceGetMaxClockInfo, h, nv.NVML_CLOCK_GRAPHICS)
        if mx:
            cap = self.mine.get("core_cap", mx)
            caps["core_cap"] = {"value": cap, "min": max(600, mx // 3), "max": mx, "step": 15, "default": mx,
                                "label": "Max core clock (cap)", "unit": "MHz",
                                "help": "Undervolt the easy way: cap the clock a little below your stock boost and add a core offset. "
                                        "The card then reaches that clock at a lower voltage."}

    def _read_power(self, caps):
        nv, h = self.nv, self.h
        pl = self._try(nv.nvmlDeviceGetPowerManagementLimitConstraints, h)
        if pl:
            caps["power"] = {"value": self._try(nv.nvmlDeviceGetPowerManagementLimit, h, default=pl[1]) // 1000,
                             "min": pl[0] // 1000, "max": pl[1] // 1000, "step": 1,
                             "default": self._try(nv.nvmlDeviceGetPowerManagementDefaultLimit, h, default=pl[1]) // 1000,
                             "label": "Power limit", "unit": "W",
                             "help": "Maximum board power. Raise it when overclocking, or lower it for a quieter, more efficient card."}
            if pl[0] == pl[1]:
                caps["power"]["help"] = "This card's BIOS locks the power limit at this value, so it can't be changed."

    def _read_fans(self, caps):
        nv, h = self.nv, self.h
        fans = self._try(nv.nvmlDeviceGetNumFans, h, default=0)
        if fans:
            lo_hi = self._try(nv.nvmlDeviceGetMinMaxFanSpeed, h, default=(30, 100))
            caps["fan_manual"] = {"value": bool(self.mine.get("fan_manual")), "label": "Manual fan speed",
                                  "help": "Off = the card's automatic fan curve."}
            caps["fan_speed"] = {"value": self.mine.get("fan_speed", 60), "min": lo_hi[0], "max": lo_hi[1], "step": 1, "default": None,
                                 "label": "Fan speed (manual)", "unit": "%", "help": "Used while Manual fan speed is on."}

    def apply(self, values: dict):
        nv, h, res = self.nv, self.h, {}

        def do(key, fn):
            try:
                fn()
                res[key] = "ok"
            except Exception as e:  # noqa: BLE001
                res[key] = "not supported" if "NotSupported" in type(e).__name__ or "Not Supported" in str(e) else str(e)

        def offset(kind, mhz):
            setter = nv.nvmlDeviceSetGpcClkVfOffset if kind == "core" else nv.nvmlDeviceSetMemClkVfOffset
            try:
                setter(h, int(mhz))
            except Exception:  # noqa: BLE001
                if self._clock_offsets(kind, set_mhz=mhz) is None:
                    raise
        if "power" in values:
            do("power", lambda: nv.nvmlDeviceSetPowerManagementLimit(h, int(values["power"]) * 1000))
        if "core_offset" in values:
            do("core_offset", lambda: offset("core", values["core_offset"]))
        if "mem_offset" in values:
            do("mem_offset", lambda: offset("mem", values["mem_offset"]))
        if "core_cap" in values:
            mx = nv.nvmlDeviceGetMaxClockInfo(h, nv.NVML_CLOCK_GRAPHICS)
            cap = int(values["core_cap"])
            do("core_cap", (lambda: nv.nvmlDeviceResetGpuLockedClocks(h)) if cap >= mx else
               (lambda: nv.nvmlDeviceSetGpuLockedClocks(h, 0, cap)))
            self.mine["core_cap"] = cap
        manual = values.get("fan_manual", self.mine.get("fan_manual"))
        if "fan_manual" in values or "fan_speed" in values:
            speed = int(values.get("fan_speed", self.mine.get("fan_speed", 60)))
            n = nv.nvmlDeviceGetNumFans(h)
            do("fan_speed" if "fan_speed" in values else "fan_manual", lambda: [
                nv.nvmlDeviceSetFanSpeed_v2(h, i, speed) if manual else nv.nvmlDeviceSetDefaultFanSpeed_v2(h, i) for i in range(n)])
            self.mine["fan_manual"], self.mine["fan_speed"] = bool(manual), speed
        _write(self.STATE, self.mine)
        return res

    def reset(self):
        c = self.read()["caps"]
        vals = {k: c[k]["default"] for k in ("core_offset", "mem_offset", "core_cap", "power") if k in c}
        if "fan_manual" in c:
            vals["fan_manual"] = False
        return all(v == "ok" for v in self.apply(vals).values())

    def metrics(self):
        nv, h = self.nv, self.h
        t = self._try
        util = t(nv.nvmlDeviceGetUtilizationRates, h)
        mem = t(nv.nvmlDeviceGetMemoryInfo, h)
        power = t(nv.nvmlDeviceGetPowerUsage, h)
        out = {"clock": t(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_GRAPHICS),
               "vram_clock": t(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_MEM),
               "temp": t(nv.nvmlDeviceGetTemperature, h, nv.NVML_TEMPERATURE_GPU),
               "board_power": round(power / 1000, 1) if power else None,
               "usage": util.gpu if util else None, "vram_used": int(mem.used / 2**20) if mem else None,
               "fan_pct": t(nv.nvmlDeviceGetFanSpeed, h),
               "power_limit": (lambda v: round(v / 1000) if v else None)(t(nv.nvmlDeviceGetEnforcedPowerLimit, h)),
               "vram_total": int(mem.total / 2**20) if mem else None}
        fn = getattr(nv, "nvmlDeviceGetCurrentClocksEventReasons", None) or getattr(nv, "nvmlDeviceGetCurrentClocksThrottleReasons", None)
        r = t(fn, h) if fn else None
        if r is not None:
            out["limits"] = int(r)              # 0x4/0x80 power, 0x20/0x40 thermal, 0x8 hardware slowdown
        return {k: v for k, v in out.items() if v is not None}


# =========================================================================== tuner (app side)
BACKEND_LABEL = {"adlx": "Live control via AMD driver (ADLX)", "nvml": "Live control via NVIDIA driver (NVML)",
                 "readout": "Readout only", "none": "No live control"}


class GpuTuner:
    """Picks the right backend for the card that's actually installed."""

    def __init__(self, hub=None):
        self.hub = hub
        self.proc = None
        self.conn = None
        self.backend: str | None = None
        self.nvml: _NVML | None = None
        self.gpus: list[dict] = []
        self.selected = 0
        self.info: dict = {}
        self.error: str | None = None
        self.note: str | None = None
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- choose a backend
    def detect(self, force=False):
        if self.backend and not force:
            return
        self.stop()
        self.backend, self.nvml, self.error, self.note = None, None, None, None
        self.gpus = detect_gpus()
        g = self.gpus[self.selected] if self.selected < len(self.gpus) else None
        vendor = g["vendor"] if g else None
        if vendor in (None, "nvidia"):
            try:
                idx = sum(1 for x in self.gpus[:self.selected] if x["vendor"] == "nvidia")
                self.nvml = _NVML(idx)
                self.backend, self.info = "nvml", self.nvml.info()
                return
            except Exception as e:  # noqa: BLE001
                if vendor == "nvidia":
                    self.error = f"Couldn't talk to the NVIDIA driver ({e}). Update the driver from nvidia.com."
        if vendor in (None, "amd"):
            if self._start_adlx():
                self.backend = "adlx"
                return
        if g:
            self.backend = "readout"
            self.info = {"name": g["name"], "driver": g.get("driver")}
            if vendor == "intel":
                self.note = ("Intel cards are tuned in Intel Graphics Software (Performance tab). RigLab still gives you the live "
                             "readout and before/after benchmarks here.")
            elif not self.error:
                self.note = "RigLab can't tune this card directly. Live readout and benchmarks still work."
        else:
            self.backend = "none"
            self.error = self.error or "No graphics card detected."

    def select(self, index: int):
        self.selected = int(index)
        self.detect(force=True)

    def _start_adlx(self):
        if self.proc and self.proc.is_alive():
            return True
        if sys.platform != "win32":
            return False
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=worker, args=(child,), daemon=True, name="RigLab-ADLX")
        self.proc.start()
        if not self.conn.poll(20):
            self.error = "AMD tuning service didn't answer."
            self.proc.kill()
            return False
        kind, data = self.conn.recv()
        if kind == "error":
            self.error = data
            self.proc.join(2)
            return False
        self.info, self.error = data, None
        return True

    def call(self, cmd, *args, timeout=15):
        """Run a command on the active backend."""
        with self.lock:
            self.detect()
            if self.backend == "nvml":
                try:
                    return getattr(self.nvml, cmd)(*args)
                except Exception as e:  # noqa: BLE001
                    self.error = f"NVIDIA driver: {e}"
                    return None
            if self.backend != "adlx" or not self._start_adlx():
                return None
            try:
                self.conn.send((cmd, args))
                if not self.conn.poll(timeout):
                    raise TimeoutError("no answer")
                kind, data = self.conn.recv()
            except (OSError, EOFError, TimeoutError) as e:
                self.error = f"AMD tuning service stopped ({e}) - it restarts automatically."
                if self.proc:
                    self.proc.kill()
                self.proc = None
                return None
            if kind == "error":
                self.error = data
                return None
            return data

    # ---------------------------------------------------------------- public
    def state(self) -> dict:
        r = self.call("read") or {}
        if self.error or r.get("errors"):
            log.warning("GPU tuning state: backend=%s error=%s read_errors=%s", self.backend, self.error, r.get("errors"))
        return {"read_errors": r.get("errors") or {}, "backend": self.backend or "none", "backend_label": BACKEND_LABEL.get(self.backend or "none"),
                "error": self.error, "note": self.note, "gpu": self.info, "gpus": self.gpus, "selected": self.selected,
                "caps": r.get("caps", {}), "at_factory": r.get("at_factory"), "pending": pending()}

    def apply(self, values: dict) -> dict:
        before = self.state()
        res = self.call("apply", values) or {k: (self.error or "no live control") for k in values}
        _write(PENDING_FILE, {"state": "unverified", "time": time.time(), "values": values, "gpu": self.info.get("name"),
                              "previous": {k: v.get("value") for k, v in before.get("caps", {}).items() if isinstance(v, dict)}})
        from . import oc
        oc.add_journal("gpu", f"GPU tuning applied on {self.info.get('name')}: " + ", ".join(f"{k}={v}" for k, v in values.items()),
                       result=res)
        return res

    def reset(self) -> bool:
        ok = bool(self.call("reset"))
        _write(PENDING_FILE, {"state": "stock", "time": time.time()})
        from . import oc
        oc.add_journal("gpu", f"GPU tuning reset to stock on {self.info.get('name')}")
        return ok

    def confirm(self):
        p = pending()
        if p.get("state") == "unverified":
            p["state"] = "verified"
            _write(PENDING_FILE, p)

    def metrics(self) -> dict:
        m = self.call("metrics", timeout=5) if self.backend in ("adlx", "nvml") else None
        h = self.hub
        out = dict(m or {})
        if h:                                       # fill gaps (voltage, hotspot, fan RPM...) from the sensor library
            def v(s):
                return round(s.value, 1) if s and s.value is not None else None
            fb = {"temp": v(h.gpu_temp()), "usage": v(h.gpu_load()), "board_power": v(h.gpu_power())}
            for kind, key, words in (("Clock", "clock", ("Core", "GPU")), ("Clock", "vram_clock", ("Memory",)),
                                     ("Temperature", "hotspot", ("Hot Spot", "Junction")), ("Fan", "fan", ()),
                                     ("Voltage", "voltage_v", ("Core", "GPU"))):
                fb[key] = v(h.find("Gpu", kind, words))
            if fb.get("voltage_v") and "voltage" not in out:
                fb["voltage"] = round(fb["voltage_v"] * 1000) if fb["voltage_v"] < 5 else fb["voltage_v"]
            fb.pop("voltage_v", None)
            for k, x in fb.items():
                if x is not None and out.get(k) is None:
                    out[k] = x
        if self.fps is not None:
            f = self.fps.current()
            if f:
                out["fps"] = f
        return out

    fps = None          # set by RunRecorder while PresentMon is capturing

    def stop(self):
        if self.proc and self.proc.is_alive():
            try:
                self.conn.send(("quit", ()))
            except OSError:
                pass
            self.proc.join(2)
            if self.proc.is_alive():
                self.proc.kill()
        self.proc = None


def startup_safety(tuner: GpuTuner) -> str | None:
    """If the last tune was never confirmed stable (crash, freeze, driver reset), go back to stock."""
    p = pending()
    if p.get("state") == "unverified":
        tuner.reset()
        return "Your last GPU tune wasn't confirmed stable, so RigLab reset the card to stock settings."
    return None


# =========================================================================== storage
def _read(name, default):
    try:
        return json.loads((app_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name, data):
    (app_dir() / name).write_text(json.dumps(data, indent=1), encoding="utf-8")


def pending() -> dict:
    return _read(PENDING_FILE, {})


def runs() -> list[dict]:
    return _read(RUNS_FILE, [])


def save_runs(r):
    _write(RUNS_FILE, r[-60:])


# =========================================================================== external benchmarks
BENCHMARKS = [
    ("Unigine Superposition", [r"Unigine\Superposition Benchmark\Superposition.exe"]),
    ("Unigine Heaven", [r"Unigine\Heaven Benchmark 4.0\heaven.bat", r"Unigine\Heaven Benchmark 4.0\bin\browser_x64.exe"]),
    ("Unigine Valley", [r"Unigine\Valley Benchmark 1.0\valley.bat"]),
    ("3DMark", [r"UL\3DMark\3DMark.exe", r"Steam\steamapps\common\3DMark\bin\x64\3DMark.exe"]),
    ("FurMark 2", [r"Geeks3D\FurMark2_x64\FurMark_GUI.exe", r"Geeks3D\FurMark2\FurMark_GUI.exe"]),
    ("FurMark", [r"Geeks3D\Benchmarks\FurMark\FurMark.exe"]),
    ("OCCT", [r"OCCT\OCCT.exe"]),
    ("Cinebench", [r"Maxon\Cinebench 2024\Cinebench.exe"]),
]


def find_benchmarks(extra: list[str] | None = None) -> list[dict]:
    roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")] + [r"C:\Program Files (x86)"]
    found, seen = [], set()
    for name, rels in BENCHMARKS:
        for root in filter(None, roots):
            hit = next((str(Path(root) / r) for r in rels if (Path(root) / r).exists()), None)
            if hit and name not in seen:
                found.append({"name": name, "exe": hit})
                seen.add(name)
    for p in extra or []:
        if Path(p).exists() and p not in {f["exe"] for f in found}:
            found.append({"name": Path(p).stem, "exe": p})
    return found


def launch(exe: str) -> subprocess.Popen:
    p = Path(exe)
    if p.suffix.lower() == ".bat":
        return subprocess.Popen(["cmd", "/c", p.name], cwd=str(p.parent))
    return subprocess.Popen([str(p)], cwd=str(p.parent))


# =========================================================================== performance runs
def driver_resets(since: float) -> int:
    """Graphics driver crashes/recoveries (TDR) logged by Windows since `since` (epoch seconds)."""
    if sys.platform != "win32":
        return 0
    start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(since - 5))
    ps = ("$s=[datetime]'" + start + "'; @(Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$s} -ErrorAction SilentlyContinue | "
          "Where-Object { $_.ProviderName -in 'nvlddmkm','amdkmdag','amdwddmg','igfx','Display' -or $_.Id -eq 4101 }).Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30,
                             creationflags=0x08000000).stdout.strip()
        return int(out or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0



def summarize(samples: list[dict], fps_builtin: dict | None, score: float | None) -> dict:
    def col(k):
        return [s[k] for s in samples if s.get(k) is not None]

    def avg(k):
        v = col(k)
        return round(sum(v) / len(v), 1) if v else None

    def mx(k):
        v = col(k)
        return round(max(v), 1) if v else None
    st = {"clock_avg": avg("clock"), "clock_max": mx("clock"), "vram_clock_avg": avg("vram_clock"),
          "power_avg": avg("board_power") or avg("power"), "power_max": mx("board_power") or mx("power"),
          "temp_avg": avg("temp"), "temp_max": mx("temp"), "hotspot_max": mx("hotspot"), "fan_avg": avg("fan"),
          "voltage_avg": avg("voltage"), "usage_avg": avg("usage"), "samples": len(samples)}
    load = [x for x in samples if (x.get("usage") or 0) >= 60]
    st["load_samples"] = len(load)
    clocks = sorted(x["clock"] for x in load if x.get("clock"))
    if clocks:
        st["clock_p5"] = clocks[max(0, len(clocks) // 20)]
        st["clock_drop_pct"] = round((clocks[-1] - st["clock_p5"]) / clocks[-1] * 100, 1) if clocks[-1] else None
    lim = [x["limits"] for x in load if x.get("limits") is not None]
    if lim:
        n = len(lim)
        st["pct_power_limited"] = round(sum(1 for v in lim if v & 0x84) / n * 100)
        st["pct_thermal_limited"] = round(sum(1 for v in lim if v & 0x60) / n * 100)
        st["pct_hw_slowdown"] = round(sum(1 for v in lim if v & 0x08) / n * 100)
    hd = [x["hotspot"] - x["temp"] for x in samples if x.get("hotspot") and x.get("temp")]
    if hd:
        st["hotspot_delta_max"] = round(max(hd), 1)
    for k in ("vram_used", "fan_pct", "usage"):
        if col(k):
            st[k + "_max"] = mx(k)
    st["fan_pct_avg"] = avg("fan_pct")
    pl = col("power_limit")
    if pl:
        st["power_limit"] = pl[-1]
    vt = col("vram_total")
    if vt:
        st["vram_total"] = vt[-1]
    fps = col("fps")
    if fps:
        st["fps_max"] = max(fps)
    if fps_builtin and "fps_avg" in fps_builtin:
        st["fps_avg"], st["fps_low"] = fps_builtin["fps_avg"], fps_builtin["fps_low"]
        for k in ("fps_low01", "fps_max", "spikes", "spikes_per_min", "frametime_p99"):
            if fps_builtin.get(k) is not None:
                st[k] = fps_builtin[k]
    elif fps_builtin and "avg_fps" in fps_builtin:
        st["fps_avg"], st["fps_low"] = round(fps_builtin["avg_fps"], 1), round(fps_builtin["low_fps"], 1)
        st["score"] = round(fps_builtin.get("score", 0))
        if fps_builtin.get("max_fps"):
            st["fps_max"] = round(fps_builtin["max_fps"], 1)
        if fps_builtin.get("low01_fps"):
            st["fps_low01"] = round(fps_builtin["low01_fps"], 1)
        st["resolution"] = fps_builtin.get("resolution")
    elif fps:
        s = sorted(fps)
        st["fps_avg"], st["fps_low"] = round(sum(s) / len(s), 1), s[max(0, len(s) // 100)]
    if score:
        st["score"] = float(score)
    if st.get("fps_avg") and st.get("power_avg"):
        st["fps_per_watt"] = round(st["fps_avg"] / st["power_avg"], 3)
    return st


class RunRecorder:
    """Samples GPU metrics twice a second while a benchmark runs (built-in or any external program)."""

    def __init__(self, tuner: GpuTuner, app):
        self.tuner, self.app = tuner, app
        self.cur: dict | None = None
        self._stop = threading.Event()

    def start(self, source: str, exe: str | None, seconds: int, label: str):
        if self.cur and self.cur.get("running"):
            return {"error": "A run is already in progress"}
        st = self.tuner.state()
        self.cur = {"id": int(time.time()), "label": label, "source": source if source == "builtin" else Path(exe or "").stem or source,
                    "exe": exe, "seconds": seconds, "started": time.time(), "running": True, "samples": [], "msg": "Starting…",
                    "gpu": st.get("gpu", {}).get("name"),
                    "settings": {k: v.get("value") for k, v in st.get("caps", {}).items() if isinstance(v, dict)},
                    "at_factory": st.get("at_factory")}
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True, name="GpuRun").start()
        return {"ok": True}

    def _run(self):
        c = self.cur
        proc, fps_builtin, cap = None, None, None
        try:
            if c["source"] != "builtin":
                from .presentmon import Capture
                c["msg"] = "Starting frame-rate capture…"
                cap = Capture()
                if cap.start():
                    self.tuner.fps = cap
                else:
                    c["warning"] = cap.error
                    cap = None
            if c["source"] == "builtin":
                self.app.open_gpu_window("bench", c["seconds"])
                c["msg"] = "Running RigLab's 3D benchmark…"
            elif c.get("exe"):
                proc = launch(c["exe"])
                c["msg"] = f"Recording while {c['source']} runs - start its benchmark now. Stop here when it finishes."
            else:
                c["msg"] = "Recording - run your game or benchmark now, then press Stop."
            t0 = time.time()
            while not self._stop.is_set():
                m = self.tuner.metrics()
                if m:
                    m["t"] = round(time.time() - t0, 1)
                    c["samples"].append(m)
                    c["live"] = m
                if c["source"] == "builtin":
                    r = self.app.gpu_result
                    if r is not None:
                        self.app.gpu_result = None
                        if "error" in r:
                            c["error"] = r["error"]
                        else:
                            fps_builtin = r
                        break
                elif c["seconds"] and time.time() - t0 > c["seconds"]:
                    break
                elif proc and proc.poll() is not None and time.time() - t0 > 20:
                    break                                    # the benchmark closed
                self._stop.wait(0.5)
        except Exception as e:  # noqa: BLE001
            log.exception("gpu run failed")
            c["error"] = str(e)
        finally:
            pm = {}
            if cap:
                cap.stop()
                pm = cap.stats()
                self.tuner.fps = None
            c["running"] = False
            c["stats"] = summarize(c["samples"], fps_builtin or (pm or None), c.get("score"))
            if pm:
                c["stats"]["app"] = pm["app"]
            if fps_builtin and fps_builtin.get("fps_series"):          # put the built-in benchmark's FPS on the timeline
                ser = dict((int(t), f) for t, f in fps_builtin["fps_series"])
                for smp in c["samples"]:
                    smp.setdefault("fps", ser.get(int(smp.get("t", -1))))
            c["stats"]["driver_resets"] = driver_resets(c["started"])
            c["duration"] = round(time.time() - c["started"])
            c["msg"] = "Done" if not c.get("error") else c["error"]
            if c["samples"] and not c.get("error"):
                keep = {k: c[k] for k in ("id", "label", "source", "gpu", "settings", "at_factory", "stats", "duration")}
                keep["time"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["started"]))
                # columns: t, clock, power, temp, fps, hotspot, usage, vram_clock, fan_pct, limits
                keep["trace"] = [[s.get("t"), s.get("clock"), s.get("board_power") or s.get("power"), s.get("temp"), s.get("fps"),
                                  s.get("hotspot"), s.get("usage"), s.get("vram_clock"), s.get("fan_pct"), s.get("limits")]
                                 for s in c["samples"]][:1200]
                r = runs()
                r.append(keep)
                save_runs(r)
                c["saved"] = keep["id"]
                if not c["stats"].get("driver_resets"):
                    self.tuner.confirm()         # finished a full benchmark on these settings without a driver crash

    def stop(self, score=None):
        if self.cur:
            if score:
                self.cur["score"] = float(score)
            self._stop.set()
            if self.cur.get("source") == "builtin":
                self.app.close_gpu_window()

    def status(self):
        c = self.cur
        if not c:
            return {"running": False}
        return {k: c.get(k) for k in ("id", "label", "source", "running", "msg", "live", "stats", "error", "saved", "seconds",
                                      "warning")} | {
            "elapsed": round(time.time() - c["started"]), "n": len(c["samples"])}
