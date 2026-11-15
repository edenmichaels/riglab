"""RGB control through the OpenRGB SDK server.

OpenRGB (openrgb.org) already speaks to hundreds of RGB devices - motherboards, RAM, GPUs,
fans/hubs, keyboards, mice, strips. Run it with the SDK server enabled and RigLab drives it.
Effects (breathing, rainbow, temperature-reactive...) are animated here, so they work on any
device OpenRGB can set to direct/custom mode.
"""
from __future__ import annotations

import colorsys
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

EFFECTS = ["Static", "Breathing", "Spectrum cycle", "Rainbow wave", "Colour wave", "Gradient", "Twinkle",
           "Strobe", "Temperature reactive", "Load reactive", "Off"]


# ---------------------------------------------------------------- pure colour maths (unit tested)
def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(c: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*c)


def lerp(a: tuple, b: tuple, t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


def hsv(h: float, s: float = 1.0, v: float = 1.0) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def temp_color(temp: float, cool: float = 40, hot: float = 85) -> tuple[int, int, int]:
    """Blue (cool) -> green -> yellow -> red (hot)."""
    t = (temp - cool) / (hot - cool)
    t = max(0.0, min(1.0, t))
    return hsv(0.66 * (1 - t))


def _scale(c, k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(v * k))) for v in c)  # type: ignore[return-value]


def _twinkle(i: int, t: float, speed: float) -> float:
    """Deterministic pseudo-random sparkle per LED."""
    phase = (math.sin(i * 12.9898) * 43758.5453) % 1.0
    x = (t * speed * 0.6 + phase) % 1.0
    return max(0.0, 1.0 - abs(x - 0.15) / 0.15) if x < 0.3 else 0.0


def frame(effect: str, t: float, n_leds: int, base: tuple[int, int, int], speed: float = 1.0,
          value: float | None = None, brightness: float = 1.0,
          color2: tuple[int, int, int] = (255, 0, 160)) -> list[tuple[int, int, int]]:
    """Colours for every LED of one device at time t (seconds)."""
    n = max(1, n_leds)
    if effect == "Off":
        out = [(0, 0, 0)] * n
    elif effect == "Breathing":
        k = (math.sin(t * speed * 2) + 1) / 2
        out = [_scale(base, 0.05 + 0.95 * k * k)] * n
    elif effect == "Spectrum cycle":
        out = [hsv(t * speed * 0.1)] * n
    elif effect == "Rainbow wave":
        out = [hsv(t * speed * 0.15 + i / n) for i in range(n)]
    elif effect == "Colour wave":
        out = [lerp(color2, base, (math.sin(t * speed * 2 - i / n * math.tau) + 1) / 2) for i in range(n)]
    elif effect == "Gradient":
        out = [lerp(base, color2, i / max(1, n - 1)) for i in range(n)]
    elif effect == "Twinkle":
        out = [lerp(_scale(base, 0.08), color2, _twinkle(i, t, speed)) for i in range(n)]
    elif effect == "Strobe":
        out = [base if (t * speed * 4) % 1.0 < 0.15 else (0, 0, 0)] * n
    elif effect == "Temperature reactive":
        out = [temp_color(value if value is not None else 40)] * n
    elif effect == "Load reactive":
        out = [lerp((0, 255, 60), (255, 0, 0), (value or 0) / 100)] * n
    else:  # Static
        out = [base] * n
    if brightness < 0.999:
        out = [_scale(c, brightness) for c in out]
    return out


# ---------------------------------------------------------------- finding / starting OpenRGB
def find_openrgb(hint: str | None = None) -> str | None:
    """Path to OpenRGB.exe: user's choice, a running copy, common install folders, or the uninstall registry."""
    import os
    import sys
    from pathlib import Path
    cands = []
    if hint:
        cands.append(Path(hint))
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == "openrgb.exe" and p.info.get("exe"):
                cands.insert(0, Path(p.info["exe"]))
    except Exception:  # noqa: BLE001
        pass
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands.append(Path(base) / "OpenRGB" / "OpenRGB.exe")
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget.is_dir():
        cands += list(winget.glob("*OpenRGB*/**/OpenRGB.exe"))
    if sys.platform == "win32":
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    with winreg.OpenKey(root, key) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            try:
                                with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                                    name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                                    if "openrgb" not in name.lower():
                                        continue
                                    for val in ("InstallLocation", "DisplayIcon"):
                                        try:
                                            v = str(winreg.QueryValueEx(sub, val)[0]).strip('"').split(",")[0]
                                            p = Path(v)
                                            cands.append(p if p.suffix.lower() == ".exe" else p / "OpenRGB.exe")
                                        except OSError:
                                            pass
                            except OSError:
                                continue
                except OSError:
                    continue
    for c in cands:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return None


def start_openrgb(exe: str):
    """Launch OpenRGB minimised with its SDK server on. If it's already open without the server, it is
    restarted so the server switch takes effect."""
    import subprocess
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == "openrgb.exe":
                p.terminate()
                p.wait(5)
    except Exception:  # noqa: BLE001
        pass
    from pathlib import Path
    subprocess.Popen([exe, "--server", "--startminimized"], cwd=str(Path(exe).parent),
                     creationflags=0x00000008 if __import__("sys").platform == "win32" else 0)  # DETACHED_PROCESS


# ---------------------------------------------------------------- OpenRGB connection
@dataclass
class DeviceInfo:
    index: int
    name: str
    type: str
    leds: int
    modes: list[str]
    active_mode: str
    zones: list = None          # [{index, name, leds, min, max, resizable}]
    needs_setup: bool = False   # a resizable zone (fan channel) has 0 LEDs configured


# LEDs per fan/strip on Corsair Lighting Node Pro / Core / Commander Pro channels
CORSAIR_LED_COUNTS = {"LL120 / LL140": 16, "QL120 / QL140": 34, "HD120 RGB": 12, "ML120 / ML140 Pro RGB": 4,
                      "SP120 RGB Elite": 8, "Lighting Node LED strip": 10, "LS100 strip (250 mm)": 15}


def _zone_attr(z, name):
    v = getattr(z, name, None)
    if v is None and getattr(z, "data", None) is not None:
        v = getattr(z.data, name, None)
    return v


class RGBController:
    def __init__(self, host: str = "127.0.0.1", port: int = 6742):
        self.host, self.port = host, port
        self.client = None
        self.error: str | None = None
        self.stage = "idle"
        self.methods: dict[str, str] = {}
        self._effect_thread: threading.Thread | None = None
        self._effect_stop = threading.Event()
        self.lock = threading.Lock()

    # -- connection
    def server_up(self, timeout: float = 1.0) -> bool:
        """Is anything listening on the OpenRGB SDK port?"""
        import socket
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout):
                return True
        except OSError:
            return False

    def connect(self, launch: bool = False, exe_hint: str | None = None, progress=None) -> bool:
        """Connect to OpenRGB's SDK server. With launch=True, start OpenRGB (with its server on) if needed.
        Sets self.error and self.stage ('ok' | 'not_installed' | 'not_running' | 'protocol' | 'missing_lib')."""
        say = progress or (lambda m: None)
        try:
            from openrgb import OpenRGBClient
        except ImportError:
            self.client, self.stage = None, "missing_lib"
            self.error = "openrgb-python is missing - reinstall RigLab."
            return False
        if self.client is not None:
            return True
        if not self.server_up():
            exe = find_openrgb(exe_hint)
            if not launch:
                self.client = None
                self.stage = "not_running" if exe else "not_installed"
                self.error = ("OpenRGB isn't running with its SDK server on." if exe else
                              "OpenRGB wasn't found on this PC.")
                return False
            if not exe:
                self.client, self.stage = None, "not_installed"
                self.error = "OpenRGB wasn't found on this PC. Install it, or point RigLab to OpenRGB.exe."
                return False
            say("Starting OpenRGB…")
            start_openrgb(exe)
            deadline = time.time() + 40
            while time.time() < deadline and not self.server_up(0.5):
                time.sleep(0.5)
            if not self.server_up():
                self.client, self.stage = None, "not_running"
                self.error = ("OpenRGB opened but its SDK server didn't start. In OpenRGB, open the 'SDK Server' "
                              "tab and click 'Start Server', then press Connect again.")
                return False
        say("Connecting…")
        last = None
        for proto in (None, 3):           # newest protocol first, then an older one some versions need
            try:
                kw = {} if proto is None else {"protocol_version": proto}
                self.client = OpenRGBClient(self.host, self.port, name="RigLab", **kw)
                self.error, self.stage = None, "ok"
                return True
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("OpenRGB connect (protocol %s) failed: %r", proto, e)
        self.client, self.stage = None, "protocol"
        self.error = (f"OpenRGB is running but the connection failed ({type(last).__name__}: {last}). "
                      "Updating OpenRGB to the latest version usually fixes this.")
        return False

    def wait_for_devices(self, seconds: float = 20, progress=None) -> int:
        """Right after OpenRGB starts it's still detecting hardware - rescan until devices appear."""
        end = time.time() + seconds
        n = 0
        while self.client and time.time() < end:
            try:
                with self.lock:
                    self.client.update()
                n = len(self.client.devices)
            except Exception:  # noqa: BLE001
                n = 0
            if n:
                return n
            if progress:
                progress("OpenRGB is still detecting your devices…")
            time.sleep(2)
        return n

    @property
    def connected(self) -> bool:
        return self.client is not None

    def disconnect(self):
        self.stop_effect()
        if self.client:
            try:
                self.client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.client = None

    def rescan(self):
        if self.client:
            with self.lock:
                self.client.update()

    def devices(self) -> list[DeviceInfo]:
        if not self.client:
            return []
        out = []
        for i, d in enumerate(self.client.devices):
            try:
                zones = []
                for zi, z in enumerate(d.zones):
                    lo, hi = _zone_attr(z, "leds_min"), _zone_attr(z, "leds_max")
                    n = len(z.leds)
                    zones.append({"index": zi, "name": z.name, "leds": n, "min": lo, "max": hi,
                                  "resizable": lo is not None and hi is not None and lo != hi})
                info = DeviceInfo(i, d.name, str(d.type).split(".")[-1].replace("DEVICE_TYPE_", "").title(),
                                  len(d.leds), [m.name for m in d.modes], d.modes[d.active_mode].name, zones)
                rz = [z for z in zones if z["resizable"]]
                info.needs_setup = bool(rz) and all(z["leds"] == 0 for z in rz)   # every fan channel empty
                out.append(info)
            except Exception:  # noqa: BLE001
                continue
        return out

    def resize_zone(self, device_index: int, zone_index: int, size: int):
        """Tell OpenRGB how many LEDs are on a channel (fan hubs can't detect what's plugged in)."""
        with self.lock:
            dev = self.client.devices[device_index]
            z = dev.zones[zone_index]
            lo, hi = _zone_attr(z, "leds_min") or 0, _zone_attr(z, "leds_max") or size
            z.resize(max(lo, min(hi, int(size))))
            self.client.update()
            self._direct(self.client.devices[device_index])

    def apply_saved_sizes(self, saved: dict) -> int:
        """Re-apply channel sizes RigLab remembers (OpenRGB can lose them, e.g. a different OpenRGB install)."""
        n = 0
        for i, d in enumerate(list(self.client.devices)):
            for zi, z in enumerate(d.zones):
                want = saved.get(f"{d.name}|{z.name}")
                if want is not None and len(z.leds) != want:
                    try:
                        self.resize_zone(i, zi, want)
                        n += 1
                    except Exception:  # noqa: BLE001
                        log.exception("resize failed")
        return n

    # -- direct control
    def _direct(self, dev):
        """Put a device into the mode that allows per-LED colour, if it has one."""
        names = [m.name.lower() for m in dev.modes]
        for want in ("direct", "custom", "static"):
            if want in names:
                if dev.modes[dev.active_mode].name.lower() != want:
                    dev.set_mode(want)
                return
        dev.set_custom_mode()

    def _method(self, dev) -> str:
        return (self.methods or {}).get(dev.name, "auto")

    def _solid(self, dev, rgb):
        """Solid colour. Prefer the device's own 'Static' mode (works on far more motherboards than Direct);
        fall back to Direct/per-LED. Per-device override: methods[name] = 'auto' | 'static' | 'direct'."""
        from openrgb.utils import RGBColor
        names = [m.name.lower() for m in dev.modes]
        method = self._method(dev)
        if method in ("auto", "static") and "static" in names:
            try:
                if dev.modes[dev.active_mode].name.lower() != "static":
                    dev.set_mode("static")
                dev.set_color(RGBColor(*rgb))
                return
            except Exception:  # noqa: BLE001
                log.warning("static mode failed on %s, trying direct", dev.name)
        self._direct(dev)
        dev.set_color(RGBColor(*rgb))

    def set_color(self, rgb: tuple[int, int, int], device_index: int | None = None):
        self.stop_effect()
        with self.lock:
            targets = self.client.devices if device_index is None else [self.client.devices[device_index]]
            for d in targets:
                try:
                    self._solid(d, rgb)
                except Exception:  # noqa: BLE001
                    log.exception("set_color failed on %s", d.name)

    # -- per-LED streaming from the LED map
    def start_stream(self, render_fn, devices: list[int], fps: int = 30, extra_sink=None):
        """render_fn(t) -> {(device_name, zone_name): {led_in_zone: rgb}}. Streams every LED of each target
        device (OpenRGB Direct mode). extra_sink(frame) receives each frame too (Corsair direct streamer)."""
        from openrgb.utils import RGBColor
        self.stop_effect()
        targets = [self.client.devices[i] for i in devices] if self.client else []
        with self.lock:
            for d in targets:
                try:
                    self._direct(d)
                except Exception:  # noqa: BLE001
                    pass
        self._effect_stop.clear()

        def run():
            t0 = time.perf_counter()
            while not self._effect_stop.wait(1 / fps):
                frame = render_fn(time.perf_counter() - t0)
                if extra_sink:
                    try:
                        extra_sink(frame)
                    except Exception:  # noqa: BLE001
                        log.exception("extra sink failed")
                with self.lock:
                    for d in targets:
                        try:
                            cols = []
                            for z in d.zones:
                                zmap = frame.get((d.name, z.name), {})
                                cols += [RGBColor(*zmap.get(k, (0, 0, 0))) for k in range(len(z.leds))]
                            if cols:
                                d.set_colors(cols, fast=True)
                        except Exception:  # noqa: BLE001
                            pass

        self._effect_thread = threading.Thread(target=run, name="RGBStream", daemon=True)
        self._effect_thread.start()

    def set_hardware_mode(self, device_index: int, mode: str):
        """Use the device's own built-in effect (runs even when RigLab is closed)."""
        self.stop_effect()
        with self.lock:
            self.client.devices[device_index].set_mode(mode)

    def save_to_device(self, device_index: int):
        with self.lock:
            self.client.devices[device_index].save_mode()

    def off(self):
        self.stop_effect()
        with self.lock:
            self.client.clear()

    # -- server-side OpenRGB profiles
    def profiles(self) -> list[str]:
        try:
            return [p.name for p in self.client.profiles]
        except Exception:  # noqa: BLE001
            return []

    def load_profile(self, name: str):
        self.stop_effect()
        with self.lock:
            self.client.load_profile(name)

    def save_profile(self, name: str):
        with self.lock:
            self.client.save_profile(name)

    # -- software effects
    def start_effect(self, effect: str, base: tuple[int, int, int], speed: float = 1.0,
                     devices: list[int] | None = None, value_fn: Callable[[], float | None] | None = None,
                     fps: int = 30, brightness: float = 1.0, color2: tuple[int, int, int] = (255, 0, 160)):
        from openrgb.utils import RGBColor
        self.stop_effect()
        if effect in ("Static", "Off"):
            if effect == "Off":
                self.off()
            else:
                for i in (devices if devices is not None else range(len(self.client.devices))):
                    self.set_color(_scale(base, brightness), i)   # uses each device's Static mode when it has one
            return
        targets = [self.client.devices[i] for i in (devices if devices is not None else range(len(self.client.devices)))]
        with self.lock:
            for d in targets:
                try:
                    if self._method(d) != "static":
                        self._direct(d)
                except Exception:  # noqa: BLE001
                    pass
        self._effect_stop.clear()
        reactive = effect in ("Temperature reactive", "Load reactive")
        smooth: dict[str, float] = {"v": 0.0}

        tick = {"n": 0}

        def run():
            t0 = time.perf_counter()
            last_v = 0.0
            while not self._effect_stop.wait(1 / fps):
                t = time.perf_counter() - t0
                v = None
                if reactive and value_fn:
                    raw = value_fn()
                    if raw is not None:
                        last_v = raw
                    smooth["v"] += (last_v - smooth["v"]) * 0.1   # ease so colours don't flicker
                    v = smooth["v"]
                tick["n"] += 1
                with self.lock:
                    for d in targets:
                        try:
                            cols = frame(effect, t, len(d.leds), base, speed, v, brightness, color2)
                            if self._method(d) == "static":
                                if tick["n"] % 3 == 0:          # mode colour only, ~10 updates/s
                                    self._solid(d, cols[0])
                                continue
                            d.set_colors([RGBColor(*c) for c in cols], fast=True)
                        except Exception:  # noqa: BLE001
                            pass

        self._effect_thread = threading.Thread(target=run, name="RGBEffect", daemon=True)
        self._effect_thread.start()

    def stop_effect(self):
        self._effect_stop.set()
        if self._effect_thread and self._effect_thread is not threading.current_thread():
            self._effect_thread.join(timeout=1)
        self._effect_thread = None
