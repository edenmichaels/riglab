"""Overclocking workbench.

What can be changed where (honest version):
  * CPU (Ryzen): PBO, Curve Optimizer, boost override, EXPO/FCLK, voltages -> BIOS. RigLab gives the exact
    steps for your board, then validates each one (per-core test for Curve Optimizer) and logs the result.
  * Windows CPU behaviour (boost mode, max processor state) -> live, from RigLab (powercfg).
  * RAM / motherboard -> BIOS (memory is trained at boot; Windows can't change it while running).
  * Radeon GPU -> AMD Adrenalin (Performance > Tuning). RigLab guides, stress-tests and catches driver resets.
  * NVIDIA GPU -> live core/memory offsets + power limit via NVML (if an NVIDIA card is present).
Each "Applied" step is written to a journal so crashes can be linked back to the change that caused them.
If the PC crashes during a validation test, the next start marks that step as failed automatically.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time

from .config import app_dir

NOWIN = 0x08000000 if sys.platform == "win32" else 0
JOURNAL = app_dir() / "oc_journal.json"
SNAP = app_dir() / "oc_boot_snapshot.json"
PROGRESS = app_dir() / "oc_progress.json"


# ---------------------------------------------------------------- platform detection
def platform_profile(inventory: dict, sensors: list) -> dict:
    sec = inventory.get("sections", inventory)
    cpu_name = (sec.get("Processor") or [{}])[0].get("Model", "")
    gpus = [g.get("Model", "") for g in sec.get("Graphics", [])]
    gpu = next((g for g in gpus if re.search(r"radeon rx|geforce|rtx|gtx|arc", g, re.I)), gpus[0] if gpus else "")
    mem = (sec.get("Memory") or [{}])[0]
    board = (sec.get("Motherboard") or [{}])
    board0 = board[0] if board else {}
    bios = next((b for b in board if "BIOS" in b), {})

    p = {"cpu": {"name": cpu_name}, "gpu": {"name": gpu}, "ram": {}, "board": {}}
    c = p["cpu"]
    c["vendor"] = "amd" if re.search(r"amd|ryzen", cpu_name, re.I) else "intel" if "intel" in cpu_name.lower() else "other"
    m = re.search(r"Ryzen\s+\d\s+(?:PRO\s+)?(\d)(\d)(\d\d)(X3D|X|G|F|GT|GE)?", cpu_name, re.I)
    if c["vendor"] == "amd" and m:
        series = int(m.group(1))
        c["series"] = series * 1000
        c["x3d"] = (m.group(4) or "").upper() == "X3D"
        c["platform"] = "AM5" if series >= 7 else "AM4"
        if series in (5,):
            c["zen"] = 3
        elif series in (7, 8):
            c["zen"] = 4
        elif series == 9:
            c["zen"] = 5
        else:
            c["zen"] = 2
        c["co_steps"] = [-10, -20, -30, -40] if c["zen"] == 5 else [-10, -20, -25, -30]
        c["boost_override"] = not (c["x3d"] and c["zen"] < 5)  # Zen5 X3D allows it, older X3D don't
        c["pbo"] = not (c["x3d"] and c["zen"] == 3)             # 5800X3D: no PBO (CO only on newer BIOSes)
    r = p["ram"]
    r["type"] = mem.get("Type", "")
    r["rated"] = _num(mem.get("Rated speed"))
    r["running"] = _num(mem.get("Running speed"))
    r["total"] = mem.get("Total")
    r["profile_on"] = bool(r["rated"] and r["running"] and r["running"] >= r["rated"] * 0.97)
    b = p["board"]
    b["name"] = f"{board0.get('Manufacturer', '')} {board0.get('Model', '')}".strip()
    b["vendor"] = _board_vendor(board0.get("Manufacturer", "") + " " + board0.get("Model", ""))
    b["bios"] = bios.get("BIOS", "")
    b["bios_date"] = bios.get("BIOS date", "")
    g = p["gpu"]
    g["vendor"] = "amd" if re.search(r"radeon|amd", gpu, re.I) else "nvidia" if re.search(r"nvidia|geforce|rtx|gtx", gpu, re.I) else "other"
    mg = re.search(r"RX\s*(\d)(\d)\d\d", gpu, re.I)
    if mg:
        g["rdna"] = {6: 2, 7: 3, 9: 4}.get(int(mg.group(1)), 1)
    return p


def _num(s) -> int:
    m = re.search(r"(\d+)", str(s or ""))
    return int(m.group(1)) if m else 0


def _board_vendor(s: str) -> str:
    s = s.lower()
    for k, v in (("asus", "asus"), ("asustek", "asus"), ("micro-star", "msi"), ("msi", "msi"),
                 ("gigabyte", "gigabyte"), ("aorus", "gigabyte"), ("asrock", "asrock")):
        if k in s:
            return v
    return "other"


# BIOS menu paths by board vendor (names vary a little between BIOS versions)
MENUS = {
    "expo": {"asus": "Ai Tweaker → Ai Overclock Tuner → EXPO I (or EXPO II)",
             "msi": "OC → Extreme Memory Profile (EXPO/A-XMP) → Profile 1",
             "gigabyte": "Tweaker → Extreme Memory Profile (X.M.P./EXPO) → Profile 1",
             "asrock": "OC Tweaker → DRAM Profile Configuration → DRAM Profile Setting → EXPO/XMP Profile 1",
             "other": "Overclocking / Memory menu → EXPO (AMD) or XMP profile → Profile 1"},
    "pbo": {"asus": "Ai Tweaker → Precision Boost Overdrive",
            "msi": "OC → Advanced CPU Configuration → AMD Overclocking → Precision Boost Overdrive",
            "gigabyte": "Tweaker → Advanced CPU Settings → Precision Boost Overdrive (or Settings → AMD Overclocking)",
            "asrock": "Advanced → AMD Overclocking → Precision Boost Overdrive",
            "other": "Advanced → AMD Overclocking → Precision Boost Overdrive"},
    "fclk": {"asus": "Ai Tweaker → FCLK Frequency", "msi": "OC → Advanced DRAM Configuration… (FCLK Frequency on the OC page)",
             "gigabyte": "Tweaker → Advanced Memory Settings → Infinity Fabric Frequency and Dividers",
             "asrock": "OC Tweaker → Infinity Fabric Frequency and Dividers",
             "other": "Advanced → AMD Overclocking → DDR and Infinity Fabric Frequency/Timings → Infinity Fabric Frequency"},
    "rebar": {"asus": "Advanced → PCI Subsystem Settings → Above 4G Decoding = Enabled, Re-Size BAR = Enabled",
              "msi": "Settings → Advanced → PCIe/PCI Sub-system Settings → Re-Size BAR Support = Enabled",
              "gigabyte": "Settings → IO Ports → Above 4G Decoding + Re-Size BAR Support = Enabled",
              "asrock": "Advanced → PCI Configuration → Above 4G Decoding + C.A.M. (Re-Size BAR) = Enabled",
              "other": "PCI settings → Above 4G Decoding = Enabled, Re-Size BAR = Enabled (needs CSM off / UEFI boot)"},
}


def _m(key: str, vendor: str) -> str:
    return MENUS[key].get(vendor, MENUS[key]["other"])


# ---------------------------------------------------------------- the plans
def plans(p: dict) -> dict:
    """Ordered steps per component. Each step: id, title, where, set, why, test{kind,minutes}, risk, rollback."""
    v = p["board"].get("vendor", "other")
    c, r, g = p["cpu"], p["ram"], p["gpu"]
    out: dict[str, dict] = {}

    # ---------------- CPU
    cpu_steps = [dict(id="cpu_baseline", title="Record a baseline", where="RigLab", risk="none",
                      set="Run the Benchmark page (CPU) and a 10-minute CPU stress test with nothing changed.",
                      why="So every later step can be measured against stock.", test={"kind": "cpu", "minutes": 10})]
    if c.get("vendor") == "amd" and c.get("zen", 0) >= 3:
        if c.get("pbo", True):
            cpu_steps.append(dict(
                id="cpu_pbo", title="Turn on Precision Boost Overdrive", where=_m("pbo", v), risk="low",
                set=("Precision Boost Overdrive = Advanced (or Enabled), PBO Limits = Motherboard"
                     if not c.get("x3d") else "Precision Boost Overdrive = Advanced (limits stay locked on X3D chips)"),
                why="Lets the CPU boost harder for longer when cooling allows. Fully automatic and safe.",
                test={"kind": "cpu", "minutes": 15}, rollback="Set Precision Boost Overdrive back to Auto."))
        for val in c.get("co_steps", [-10, -20, -25, -30]):
            cpu_steps.append(dict(
                id=f"cpu_co{abs(val)}", title=f"Curve Optimizer: all cores {val}", where=_m("pbo", v) + " → Curve Optimizer",
                set=f"Curve Optimizer = All Cores, Sign = Negative, Magnitude = {abs(val)}", risk="medium",
                why=("An undervolt: same clocks with less voltage, so lower temps and higher sustained boost. "
                     "Every chip is different - the per-core test finds the limit of each core."),
                test={"kind": "core_cycle", "minutes": 0},
                rollback=f"If a core fails, go to Per Core mode and give only that core {val + 5} (or less negative)."))
        if c.get("boost_override"):
            cpu_steps.append(dict(
                id="cpu_boost", title="Boost override +100 MHz (optional)", where=_m("pbo", v), risk="medium",
                set="Max CPU Boost Clock Override = +100 MHz (up to +200 on Ryzen 7000/9000)",
                why="Raises the boost ceiling. Small gain; may need a less negative Curve Optimizer.",
                test={"kind": "core_cycle", "minutes": 0}, rollback="Set the override back to 0."))
        cpu_steps.append(dict(
            id="cpu_temp", title="Temperature limit (optional, for quieter/cooler)", where=_m("pbo", v), risk="none",
            set="Platform Thermal Throttle Limit = Manual, 85 °C (default is 95 °C on Ryzen 7000/9000)",
            why="Trades a few % of all-core performance for a lot less heat and fan noise.",
            test={"kind": "cpu", "minutes": 10}, rollback="Set it back to Auto."))
    out["cpu"] = {"title": "Processor", "steps": cpu_steps, "limits": [
        "Never set a fixed high Vcore for daily use - Curve Optimizer is the safe way on Ryzen.",
        "Ryzen 7000/9000 SoC voltage must stay at or below 1.30 V.",
        "X3D chips: no manual multiplier overclocking - PBO/Curve Optimizer only.",
    ] if c.get("vendor") == "amd" else ["Intel: use Intel XTU or the BIOS; undervolting is locked on many 12th-14th gen boards."]}

    # ---------------- RAM
    ram_steps = []
    if r.get("rated"):
        ram_steps.append(dict(
            id="ram_expo", title=f"Turn on EXPO/XMP ({r['rated']} MT/s)", where=_m("expo", v), risk="low",
            set="Select EXPO (AMD) / XMP Profile 1. Save & exit.",
            why=(f"Your RAM is rated for {r['rated']} MT/s but runs at {r['running']} MT/s. This is the single biggest "
                 "free speed-up for games." if not r.get("profile_on") else "Already on - nothing to do."),
            note="First boot after this can show a black screen for 1-3 minutes while memory trains - don't panic or reset.",
            test={"kind": "ram", "minutes": 30}, rollback="If it won't boot: clear CMOS (see Motherboard) and try EXPO II / lower speed.",
            done=r.get("profile_on", False)))
    if p["cpu"].get("platform") == "AM5" and "DDR5" in (r.get("type") or "DDR5"):
        ram_steps.append(dict(
            id="ram_fclk", title="Infinity Fabric 2000 MHz", where=_m("fclk", v), risk="medium",
            set="FCLK Frequency = 2000 MHz; UCLK DIV1 MODE = UCLK=MEMCLK (if your kit is 6000 MT/s)",
            why="Speeds up the link between the CPU chiplets and memory. 2000 MHz works on most Ryzen 7000/9000.",
            test={"kind": "ram", "minutes": 30}, rollback="Set FCLK back to Auto (1733/1800)."))
    elif p["cpu"].get("platform") == "AM4":
        ram_steps.append(dict(
            id="ram_fclk", title="Infinity Fabric 1:1 with memory", where=_m("fclk", v), risk="medium",
            set="FCLK = half your RAM speed (e.g. 1800 MHz for DDR4-3600), up to 1900 MHz",
            why="Ryzen 5000 is fastest when fabric and memory clocks match (1:1).",
            test={"kind": "ram", "minutes": 30}, rollback="Set FCLK back to Auto."))
    ram_steps.append(dict(
        id="ram_timings", title="Tighter timings (advanced, optional)", where="Advanced DRAM timing menu", risk="high",
        set="Change ONE timing at a time (start with tRFC), test, repeat. Read current timings with ZenTimings.",
        why="Lower latency for a few % more FPS in CPU-heavy games. Slow and fiddly - only if you enjoy it.",
        test={"kind": "ram", "minutes": 60}, rollback="Set timings back to Auto."))
    out["ram"] = {"title": "Memory", "steps": ram_steps, "limits": [
        "DDR5 VDD/VDDQ: stay at or below 1.40 V for daily use.", "DDR4: stay at or below 1.45 V for daily use.",
        "Memory errors are sneaky - always run the full 30-minute test after every change."]}

    # ---------------- GPU
    if g.get("vendor") == "amd":
        tune = "AMD Software: Adrenalin Edition → Performance → Tuning → Custom"
        gsteps = [
            dict(id="gpu_baseline", title="Record a baseline", where="RigLab", risk="none",
                 set="Run the Benchmark page (Graphics) with stock settings.", why="So you can see what each change gains.",
                 test={"kind": "gpu", "minutes": 5}),
            dict(id="gpu_power", controls=["power"], title="Raise the power limit", where=tune + " → Power Tuning", risk="low",
                 set="Power Limit (%) = maximum allowed (often +10 or +15)",
                 why="Lets the card hold higher clocks under heavy load. Raises heat and power a bit.",
                 test={"kind": "gpu", "minutes": 10}, rollback="Adrenalin → Tuning → Reset."),
            dict(id="gpu_uv", controls=["voltage"], title="Undervolt", where=tune + " → GPU Tuning → Voltage" + (" Offset" if g.get("rdna", 3) >= 3 else " (mV)"),
                 risk="medium", set="Lower voltage by 25 mV, test, repeat. When it crashes, go back 10-15 mV from the last stable value.",
                 why="Usually the biggest win on Radeon: cooler, quieter and higher sustained clocks.",
                 test={"kind": "gpu", "minutes": 15}, rollback="Raise voltage by 10 mV, or Reset in Adrenalin."),
            dict(id="gpu_vram", controls=["mem_timing", "vram_max"], title="VRAM: Fast Timing + small overclock", where=tune + " → VRAM Tuning", risk="medium",
                 set="Memory Timing = Fast Timing; Max VRAM Frequency +50 MHz steps (stop at the first artifacts/crash, go back 50)",
                 why="More memory bandwidth. Watch for flickering/sparkles - that means too far.",
                 test={"kind": "gpu", "minutes": 15}, rollback="Memory Timing = Default; frequency back to stock."),
            dict(id="gpu_profile", title="Save your profile", where="Adrenalin → Performance → Tuning → (… menu) → Export", risk="none",
                 set="Export the tuning profile to a file.", why="Driver updates sometimes reset tuning; re-import in one click.",
                 test=None),
        ]
        gl = ["Adrenalin resets tuning to stock after a driver crash - if your settings 'disappear', the last change was unstable.",
              "Keep the GPU hotspot (junction) below about 100 °C."]
    elif g.get("vendor") == "nvidia":
        gsteps = [dict(id="gpu_baseline", bench=True, title="Record a baseline", where="GPU tuning tab → Performance: before & after", risk="none",
                       set="Run a benchmark at stock and save it as Before.", why="Every later change is measured against it.",
                       test={"kind": "gpu", "minutes": 5}),
                  dict(id="gpu_nv_power", controls=["power"], title="Max out the power limit", where="Right here - sliders below", risk="low",
                       set="Slide the power limit to its maximum.", why="Lets the card hold higher boost clocks.",
                       test={"kind": "gpu", "minutes": 10}),
                  dict(id="gpu_nv_core", controls=["core_offset"], title="Core clock offset", where="Right here - sliders below", risk="medium",
                       set="+30 MHz at a time; run a benchmark after each step.", why="Shifts the whole boost curve up.",
                       test={"kind": "gpu", "minutes": 15}, rollback="Lower by 30 MHz, or Reset to stock."),
                  dict(id="gpu_nv_mem", controls=["mem_offset"], title="Memory clock offset", where="Right here - sliders below", risk="medium",
                       set="+200 MHz at a time. Stop when the score stops rising.", why="More memory bandwidth.",
                       test={"kind": "gpu", "minutes": 15}, rollback="Lower by 200 MHz."),
                  dict(id="gpu_nv_uv", controls=["core_cap", "core_offset"], title="Optional: undervolt", where="Right here - sliders below", risk="medium",
                       set="Cap the clock at your average benchmark clock and add +100-150 MHz core offset.",
                       why="Same performance at lower voltage: cooler and quieter.", test={"kind": "gpu", "minutes": 15})]
        gl = ["After a driver crash (black screen, 'display driver stopped responding') the last change was unstable - back it off.",
              "Keep the GPU below about 83 °C; the card slows itself down above that."]
    else:
        gsteps, gl = [], []
    out["gpu"] = {"title": "Graphics", "steps": gsteps, "limits": gl}

    # ---------------- Motherboard
    out["board"] = {"title": "Motherboard", "steps": [
        dict(id="mb_bios", title="Update the BIOS first", where=f"{p['board'].get('name') or 'Your board'} support page",
             risk="low", set=f"Current: {p['board'].get('bios') or '?'} ({p['board'].get('bios_date') or '?'}). "
                             "Download the newest stable BIOS from the manufacturer and flash it with the BIOS's own flash tool.",
             why="New BIOSes fix memory compatibility, add Curve Optimizer features and include AMD safety fixes.",
             note="Updating resets BIOS settings - do it before overclocking, and never turn the PC off during a flash.",
             test=None),
        dict(id="mb_rebar", title="Resizable BAR / Smart Access Memory", where=_m("rebar", v), risk="none",
             set="Above 4G Decoding = Enabled, Re-Size BAR = Enabled", why="Free FPS on Radeon (AMD SAM) in many games.",
             test={"kind": "gpu", "minutes": 5}),
        dict(id="mb_cmos", title="Know how to clear CMOS", where="Board manual", risk="none",
             set="Find the Clear CMOS button (back I/O) or jumper (CLR_CMOS). Most AM5 boards also recover by themselves after 3 failed boots.",
             why="Your undo button if an overclock won't boot.", test=None),
    ], "limits": []}
    return out


# ---------------------------------------------------------------- journal & progress
def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def journal() -> list[dict]:
    return _load(JOURNAL, [])


def add_journal(kind: str, text: str, **extra) -> dict:
    j = journal()
    e = {"time": time.time(), "kind": kind, "text": text, **extra}
    j.append(e)
    JOURNAL.write_text(json.dumps(j[-500:], indent=1), encoding="utf-8")
    return e


def progress() -> dict:
    return _load(PROGRESS, {})


def set_progress(step_id: str, state: str, note: str = ""):
    pr = progress()
    pr[step_id] = {"state": state, "time": time.time(), "note": note}
    PROGRESS.write_text(json.dumps(pr, indent=1), encoding="utf-8")


def mark_test_running(step_id: str | None, kind: str):
    pr = progress()
    pr["_running_test"] = {"step": step_id, "kind": kind, "time": time.time()}
    PROGRESS.write_text(json.dumps(pr, indent=1), encoding="utf-8")


def clear_test_running():
    pr = progress()
    pr.pop("_running_test", None)
    PROGRESS.write_text(json.dumps(pr, indent=1), encoding="utf-8")


def check_crash_during_test() -> dict | None:
    """Called at startup: if a validation was running when RigLab last stopped, the PC probably crashed."""
    pr = progress()
    run = pr.get("_running_test")
    if not run:
        return None
    clear_test_running()
    if run.get("step"):
        set_progress(run["step"], "failed", "PC crashed or restarted during the validation test")
    add_journal("crash", f"PC crashed/restarted during the {run['kind']} validation test", step=run.get("step"))
    return run


# ---------------------------------------------------------------- boot snapshot: notice BIOS changes
def boot_snapshot(profile: dict) -> list[str]:
    """Compare important settings with the last run and journal any differences."""
    now = {"ram_speed": profile["ram"].get("running"), "bios": profile["board"].get("bios"),
           "cpu": profile["cpu"].get("name"), "gpu": profile["gpu"].get("name")}
    old = _load(SNAP, None)
    SNAP.write_text(json.dumps(now), encoding="utf-8")
    if not old:
        return []
    labels = {"ram_speed": "RAM speed", "bios": "BIOS version", "cpu": "CPU", "gpu": "Graphics card"}
    changes = []
    for k, label in labels.items():
        if old.get(k) and now.get(k) and old[k] != now[k]:
            unit = " MT/s" if k == "ram_speed" else ""
            changes.append(f"{label} changed: {old[k]}{unit} → {now[k]}{unit}")
    for ch in changes:
        add_journal("detected", ch)
    return changes


# ---------------------------------------------------------------- live Windows CPU settings
BOOST_MODES = {0: "Disabled (no boost - coolest)", 1: "Enabled", 2: "Aggressive (default)", 3: "Efficient Enabled",
               4: "Efficient Aggressive"}


def _pc(*args) -> str:
    r = subprocess.run(["powercfg", *args], capture_output=True, text=True, creationflags=NOWIN)
    return r.stdout


def _read_index(alias: str) -> int | None:
    out = _pc("/q", "SCHEME_CURRENT", "SUB_PROCESSOR", alias)
    m = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", out)
    return int(m.group(1), 16) if m else None


def cpu_windows_settings() -> dict:
    if sys.platform != "win32":
        return {"available": False}
    _pc("-attributes", "SUB_PROCESSOR", "PERFBOOSTMODE", "-ATTRIB_HIDE")   # un-hide the boost mode setting
    return {"available": True, "boost_mode": _read_index("PERFBOOSTMODE"), "max_state": _read_index("PROCTHROTTLEMAX"),
            "modes": BOOST_MODES}


def set_cpu_windows(boost_mode: int | None = None, max_state: int | None = None) -> bool:
    ok = True
    if boost_mode is not None:
        for flag in ("/setacvalueindex", "/setdcvalueindex"):
            ok &= subprocess.run(["powercfg", flag, "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFBOOSTMODE",
                                  str(int(boost_mode))], creationflags=NOWIN).returncode == 0
    if max_state is not None:
        ms = max(50, min(100, int(max_state)))
        for flag in ("/setacvalueindex", "/setdcvalueindex"):
            ok &= subprocess.run(["powercfg", flag, "SCHEME_CURRENT", "SUB_PROCESSOR", "PROCTHROTTLEMAX", str(ms)],
                                 creationflags=NOWIN).returncode == 0
    subprocess.run(["powercfg", "/setactive", "SCHEME_CURRENT"], creationflags=NOWIN)
    return ok
