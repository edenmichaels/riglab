"""LibreHardwareMonitor runs in its own process.

Why: the interface (pywebview) and LHM both use .NET through pythonnet, and one process can only
host one .NET runtime. Newer LHM releases may be built for .NET 10 instead of .NET Framework, so
keeping LHM separate lets it use whichever runtime its DLL needs. It also means a driver hiccup
can't freeze the window.

Messages worker -> main:  ("status", {...}) once, then ("sensors", [dict, ...]) every interval,
                          ("ack", id, ok) after a control command.
Messages main -> worker:  ("set", sensor_id, percent|None), ("stop",)
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from pathlib import Path


def detect_framework(dll: Path) -> tuple[str, str]:
    """('netfx'|'coreclr', version) from the assembly's TargetFramework attribute."""
    data = dll.read_bytes()
    m = re.search(rb"\.NETCoreApp,Version=v(\d+)\.(\d+)", data)
    if m:
        return "coreclr", f"{int(m.group(1))}.{int(m.group(2))}"
    m = re.search(rb"\.NETFramework,Version=v([\d.]+)", data)
    if m:
        return "netfx", m.group(1).decode()
    # netstandard / unknown: .NET Framework 4.7.2+ can load netstandard2.0
    return "netfx", "?"


def _runtime_config(folder: Path, version: str) -> Path:
    major = version.split(".")[0]
    cfg = folder / "riglab.runtimeconfig.json"
    cfg.write_text(json.dumps({"runtimeOptions": {
        "tfm": f"net{major}.0",
        "rollForward": "LatestMajor",
        "framework": {"name": "Microsoft.NETCore.App", "version": f"{major}.0.0"}}}), encoding="utf-8")
    return cfg


def load_lhm(dll: Path):
    runtime, version = detect_framework(dll)
    if getattr(sys, "frozen", False):          # exe build: tell pythonnet where the bundled python3xx.dll is
        import os
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        pydll = base / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        if pydll.exists():
            os.environ.setdefault("PYTHONNET_PYDLL", str(pydll))
    import pythonnet
    if runtime == "coreclr":
        pythonnet.load("coreclr", runtime_config=str(_runtime_config(dll.parent, version)))
    else:
        pythonnet.load("netfx")
    import clr  # noqa: F401  (pythonnet)
    sys.path.append(str(dll.parent))
    clr.AddReference(str(dll))
    from LibreHardwareMonitor.Hardware import Computer  # type: ignore
    c = Computer()
    for attr in ("IsCpuEnabled", "IsGpuEnabled", "IsMemoryEnabled", "IsMotherboardEnabled",
                 "IsControllerEnabled", "IsStorageEnabled", "IsNetworkEnabled", "IsPsuEnabled",
                 "IsBatteryEnabled"):
        if hasattr(c, attr):
            setattr(c, attr, True)
    c.Open()
    return c, runtime, version


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def run_worker(conn, dll_path: str, interval: float):
    """Entry point of the sensor process (must be top level for multiprocessing spawn)."""
    dll = Path(dll_path)
    try:
        computer, runtime, version = load_lhm(dll)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        hint = ""
        if "coreclr" in msg.lower() or "hostfxr" in msg.lower() or "Microsoft.NETCore.App" in msg:
            hint = " - this LibreHardwareMonitor build needs the .NET runtime. Use Health check → Fix."
        conn.send(("status", {"ok": False, "error": f"{type(e).__name__}: {msg}{hint}",
                              "trace": traceback.format_exc()[-2000:]}))
        return
    conn.send(("status", {"ok": True, "runtime": runtime, "version": version}))

    objs: dict = {}
    touched: set = set()

    def read():
        out = []

        def walk(hw, top):
            hw.Update()
            for s in hw.Sensors:
                sid = str(s.Identifier)
                objs[sid] = s
                ctrl = getattr(s, "Control", None)
                out.append({"id": sid, "hardware": top if str(hw.Name) == top else f"{top} › {hw.Name}",
                            "hw_type": str(hw.HardwareType), "kind": str(s.SensorType), "name": str(s.Name),
                            "value": _f(s.Value), "min": _f(s.Min), "max": _f(s.Max),
                            "controllable": ctrl is not None})
            for sub in hw.SubHardware:
                walk(sub, top)

        for hw in computer.Hardware:
            try:
                walk(hw, str(hw.Name))
            except Exception:  # noqa: BLE001
                pass
        return out

    def set_control(sid, pct):
        s = objs.get(sid)
        ctrl = getattr(s, "Control", None) if s is not None else None
        if ctrl is None:
            return False
        if pct is None:
            ctrl.SetDefault()
            touched.discard(sid)
        else:
            lo, hi = float(ctrl.MinSoftwareValue), float(ctrl.MaxSoftwareValue)
            ctrl.SetSoftware(float(max(lo, min(hi, pct))))
            touched.add(sid)
        return True

    next_t = 0.0
    try:
        while True:
            timeout = max(0.0, next_t - time.monotonic())
            if conn.poll(timeout):
                msg = conn.recv()
                if msg[0] == "stop":
                    break
                if msg[0] == "set":
                    try:
                        ok = set_control(msg[1], msg[2])
                    except Exception:  # noqa: BLE001
                        ok = False
                    conn.send(("ack", msg[1], ok))
                continue
            next_t = time.monotonic() + interval
            conn.send(("sensors", read()))
    except (EOFError, BrokenPipeError, OSError):
        pass  # main app went away
    finally:
        for sid in list(touched):       # always give fans back to the BIOS
            try:
                set_control(sid, None)
            except Exception:  # noqa: BLE001
                pass
        try:
            computer.Close()
        except Exception:  # noqa: BLE001
            pass
