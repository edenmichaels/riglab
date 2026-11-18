"""RigLab lighting v3: one engine, every LED, one data stream.

  ManagedOpenRGB   RigLab runs its *own* headless OpenRGB (hardware layer) with a private settings folder and
                   port, so nothing outside RigLab can change or break it. Any other OpenRGB copy is closed
                   first because two programs can't drive the same devices.
  LightingEngine   Discovers every device and zone, keeps per-device settings (enabled, LED counts, fan type,
                   brightness, colour order, direction), builds the LED map, and streams every LED of every
                   device from a single clock at 30 fps, so all lights move in unison.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import ledmap
from .config import app_dir, vendor_dir

log = logging.getLogger(__name__)
NOWIN = 0x08000000 if sys.platform == "win32" else 0
PORT = 6743                     # RigLab's private OpenRGB (normal OpenRGB uses 6742)
WIRELESS_HINTS = ("lightspeed", "wireless")
PROVISIONAL = 48                # LEDs assumed on an unconfigured channel until the user confirms
ORDERS = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")


def _port_up(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


# ======================================================================== managed OpenRGB
class ManagedOpenRGB:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.config_dir = app_dir() / "openrgb"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.status = "stopped"
        self.error: str | None = None
        self.restarts = 0
        self.skip_detectors: set[str] = set()

    def exe(self) -> str | None:
        from .rgb import find_openrgb
        bundled = vendor_dir() / "openrgb" / "OpenRGB.exe"
        if bundled.exists():
            return str(bundled)
        return find_openrgb(self.cfg["openrgb"].get("exe") or None)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None and _port_up(PORT)

    def start(self, progress=None) -> bool:
        say = progress or (lambda m: None)
        if self.running():
            return True
        exe = self.exe()
        if not exe:
            self.status, self.error = "missing", "OpenRGB isn't installed - use Download OpenRGB, or Find OpenRGB.exe if you already have it."
            return False
        say("Closing other OpenRGB copies…")
        self._kill_others()
        self._write_detectors()
        args = [exe, "--server", "--server-port", str(PORT), "--config", str(self.config_dir), "--noautoconnect"]
        say("Starting lighting service…")
        self.status = "starting"
        try:
            logf = open(self.config_dir / "riglab_openrgb_console.log", "w", encoding="utf-8", errors="replace")
            self.proc = subprocess.Popen(args, cwd=str(Path(exe).parent), stdout=logf, stderr=subprocess.STDOUT,
                                         creationflags=NOWIN)
        except OSError as e:
            self.status, self.error = "error", f"Couldn't start OpenRGB: {e}"
            return False
        end = time.time() + 90                       # first detection can take a while
        while time.time() < end:
            if self.proc.poll() is not None:
                self.status, self.error = "error", f"OpenRGB exited straight away (code {self.proc.returncode})."
                return False
            if _port_up(PORT, 0.4):
                self.status, self.error = "running", None
                return True
            say("Detecting your RGB devices…")
            time.sleep(0.5)
        self.status, self.error = "error", "OpenRGB started but its server never came up."
        return False

    def _write_detectors(self):
        """Devices RigLab drives natively are switched off in OpenRGB's (private) detector list so only one
        program ever talks to them. This is RigLab's own config folder - your normal OpenRGB isn't touched."""
        import json
        f = self.config_dir / "OpenRGB.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except ValueError:
            data = {}
        det = data.setdefault("Detectors", {}).setdefault("detectors", {})
        from .native import OPENRGB_DETECTORS
        for name in OPENRGB_DETECTORS:
            det[name] = name not in self.skip_detectors
        f.write_text(json.dumps(data, indent=4), encoding="utf-8")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.status = "stopped"

    def _kill_others(self):
        try:
            import psutil
            mine = self.proc.pid if self.proc else None
            for p in psutil.process_iter(["name", "pid"]):
                if (p.info.get("name") or "").lower() == "openrgb.exe" and p.info["pid"] != mine:
                    p.terminate()
                    try:
                        p.wait(5)
                    except Exception:  # noqa: BLE001
                        p.kill()
        except Exception:  # noqa: BLE001
            pass

    def log_tail(self, n: int = 30) -> list[str]:
        out = []
        for f in [self.config_dir / "riglab_openrgb_console.log",
                  *sorted((self.config_dir / "logs").glob("*.log"), key=os.path.getmtime)[-1:]]:
            if f.exists():
                out += [f"--- {f.name} ---"] + f.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        return out


# ======================================================================== engine
def _zattr(z, name):
    v = getattr(z, name, None)
    if v is None and getattr(z, "data", None) is not None:
        v = getattr(z.data, name, None)
    return v


def _limits(z) -> tuple[int, int]:
    """(min, max) LEDs for a zone. Newer OpenRGB builds don't always report them over the SDK; an empty
    zone is then an addressable header / fan channel that can be sized."""
    lo, hi = _zattr(z, "leds_min"), _zattr(z, "leds_max")
    n = len(z.leds)
    if lo is None or hi is None:
        return (0, 1024) if n == 0 else (n, n)
    return int(lo), int(hi)


def _reorder(c, order: str):
    if order == "RGB":
        return c
    m = {"R": c[0], "G": c[1], "B": c[2]}
    # the hardware reads our bytes in its own order: send them so that it shows the intended colour
    out = [0, 0, 0]
    for i, ch in enumerate(order):
        out[i] = m[ch]
    return tuple(out)


class LightingEngine:
    def __init__(self, cfg, hub=None):
        self.cfg = cfg
        self.hub = hub
        self.host = ManagedOpenRGB(cfg)
        self.client = None
        self.devices: list = []         # openrgb Device objects
        self.keys: list[str] = []       # stable unique key per device (same order)
        self.lock = threading.RLock()
        self.tests: dict = {}           # (key, zone) -> test pattern spec
        self.stats = {"fps": 0.0, "leds": 0, "frames": 0, "errors": 0}
        self.msg = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: dict = {}
        self._fx = None
        self.paused = False
        self.native: list = []
        self.native_error: str | None = None
        self.L = cfg.data.setdefault("lighting", {})
        self.L.setdefault("devices", {})
        self.L.setdefault("state", {"effect": "Rainbow sweep", "color": "#00c8ff", "color2": "#ff00a0", "speed": 1.0,
                                    "brightness": 1.0})

    # ------------------------------------------------------------------ connection & discovery
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="LightingEngine", daemon=True)
        self._thread.start()

    def _find_native(self):
        from . import native
        self.host._kill_others()          # an old OpenRGB may still be holding the node
        for n in self.native:
            n.close(hand_back=False)
        self.native = native.find_devices()
        self.native_error = None
        for n in list(self.native):
            try:
                n.open()
            except Exception as e:  # noqa: BLE001
                log.exception("native open failed")
                self.native_error = f"{n.name}: {e} - is iCUE or SignalRGB running? Close it and press Restart."
                self.native.remove(n)
        self.host.skip_detectors = {n.name for n in self.native}

    def connect(self) -> bool:
        with self.lock:
            if not self.host.running():
                self._find_native()
            if not self.host.start(progress=lambda m: setattr(self, "msg", m)):
                self.msg = self.host.error or "Lighting service not running"
                return False
            try:
                from openrgb import OpenRGBClient
                try:
                    self.client = OpenRGBClient("127.0.0.1", PORT, name="RigLab")
                except Exception:  # noqa: BLE001 - older OpenRGB builds speak an older SDK protocol
                    self.client = OpenRGBClient("127.0.0.1", PORT, name="RigLab", protocol_version=3)
            except Exception as e:  # noqa: BLE001
                self.client = None
                self.msg = f"Couldn't talk to the lighting service: {e}"
                return False
            self.discover()
            self.msg = self.native_error or ""
            return True

    def discover(self):
        """Refresh devices, give each a stable key, apply saved LED counts, switch all to Direct (stream) mode."""
        with self.lock:
            try:
                self.client.update()
            except Exception:  # noqa: BLE001
                pass
            devs = list(self.client.devices) + list(self.native)
            keys, seen = [], {}
            for d in devs:
                seen[d.name] = seen.get(d.name, 0) + 1
                keys.append(d.name if seen[d.name] == 1 else f"{d.name} #{seen[d.name]}")
            self.devices, self.keys = devs, keys
            for d, k in zip(devs, keys):
                ds = self.dev_settings(k)
                for z in d.zones:
                    zs = ds["zones"].get(z.name)
                    lo, hi = _limits(z)
                    if zs is None and lo != hi and len(z.leds) == 0:
                        # nothing reports how many LEDs hang off an addressable header/channel: start with a
                        # provisional size so everything lights up now, and ask the user to confirm it
                        zs = ds["zones"][z.name] = {"size": max(lo, min(hi, PROVISIONAL)), "unconfirmed": True}
                    want = (zs or {}).get("size")
                    if want is not None and len(z.leds) != want:
                        try:
                            z.resize(int(want))
                        except Exception:  # noqa: BLE001
                            log.warning("resize %s/%s failed", k, z.name)
                self._prepare(d, ds)
            try:
                self.client.update()
                self.devices = list(self.client.devices) + list(self.native)
            except Exception:  # noqa: BLE001
                pass
            self._last.clear()
            self._fx = None
            if keys:                                    # remembered for the after-boot rescan
                self.L["known_devices"] = list(keys)
            self.cfg.save()

    def invalidate(self):
        self._fx = None

    def _prepare(self, d, ds):
        if ds["method"] == "static":
            return
        names = [m.name.lower() for m in d.modes]
        for want in ("direct", "custom", "static"):
            if want in names:
                try:
                    if d.modes[d.active_mode].name.lower() != want:
                        d.set_mode(want)
                except Exception:  # noqa: BLE001
                    pass
                return

    def dev_settings(self, key: str) -> dict:
        ds = self.L["devices"].setdefault(key, {})
        ds.setdefault("enabled", True)
        ds.setdefault("brightness", 1.0)
        ds.setdefault("order", "RGB")
        ds.setdefault("reverse", False)
        ds.setdefault("method", "stream")
        ds.setdefault("zones", {})
        return ds

    # ------------------------------------------------------------------ state for the UI
    def device_list(self) -> list[dict]:
        out = []
        with self.lock:
            for i, (d, k) in enumerate(zip(self.devices, self.keys)):
                ds = self.dev_settings(k)
                zones = []
                for zi, z in enumerate(d.zones):
                    lo, hi = _limits(z)
                    zs = ds["zones"].get(z.name) or {}
                    zones.append({"index": zi, "name": z.name, "leds": len(z.leds), "min": lo, "max": hi,
                                  "resizable": lo != hi,
                                  "per": zs.get("per", 0), "empty": zs.get("empty", False),
                                  "unconfirmed": bool(zs.get("unconfirmed"))})
                needs = any(z["resizable"] and z["leds"] == 0 and not z["empty"] for z in zones)
                meta = getattr(d, "metadata", None)
                out.append({"index": i, "key": k, "name": d.name, "type": str(d.type).split(".")[-1].replace("DEVICE_TYPE_", "").title(),
                            "vendor": getattr(meta, "vendor", "") if meta else "", "leds": len(d.leds),
                            "modes": [m.name for m in d.modes], "active_mode": d.modes[d.active_mode].name if d.modes else "",
                            "zones": zones, "needs_setup": needs, "settings": {x: ds[x] for x in
                                                                              ("enabled", "brightness", "order", "reverse", "method")},
                            "wireless": any(h in d.name.lower() for h in WIRELESS_HINTS),
                            "native": bool(getattr(d, "native", False))})
        return out

    def fixtures(self) -> list[dict]:
        if self._fx is not None:
            return self._fx
        devs = [{"name": d["key"], "type": d["type"], "leds": d["leds"], "zones": d["zones"]}
                for d in self.device_list() if d["settings"]["enabled"]]
        meta = {f"{k}|{zn}": {"per": z.get("per", 0)} for k, ds in self.L["devices"].items()
                for zn, z in ds.get("zones", {}).items()}
        self._fx = ledmap.auto_map(devs, meta, self.L.get("map"))
        return self._fx

    # ------------------------------------------------------------------ settings changes
    def set_state(self, **kw):
        self.L["state"].update({k: v for k, v in kw.items() if v is not None})
        self.cfg.save()

    def set_device(self, key: str, **kw):
        ds = self.dev_settings(key)
        ds.update({k: v for k, v in kw.items() if v is not None and k in ("enabled", "brightness", "order", "reverse", "method")})
        self.cfg.save()
        self._fx = None
        with self.lock:
            idx = self.keys.index(key) if key in self.keys else None
            if idx is not None and "method" in kw:
                self._prepare(self.devices[idx], ds)
            self._last.pop(key, None)

    def set_zone(self, key: str, zone: str, size: int | None = None, per: int | None = None, empty: bool | None = None):
        ds = self.dev_settings(key)
        zs = ds["zones"].setdefault(zone, {})
        if size is not None:
            zs["size"] = int(size)
        if per is not None:
            zs["per"] = int(per)
        if empty is not None:
            zs["empty"] = bool(empty)
        zs.pop("unconfirmed", None)
        self.cfg.save()
        self._fx = None
        if size is not None:
            self._resize(key, zone, int(size))
        self._last.pop(key, None)

    def _resize(self, key: str, zone: str, size: int):
        with self.lock:
            if key not in self.keys or self.client is None:
                return
            d = self.devices[self.keys.index(key)]
            z = next((z for z in d.zones if z.name == zone), None)
            if z is None or len(z.leds) == size:
                return
            lo, hi = _limits(z)
            try:
                z.resize(max(lo, min(hi, size)))
                if not getattr(d, "native", False):
                    self.client.update()
                    self.devices = list(self.client.devices) + list(self.native)
            except Exception:  # noqa: BLE001
                log.exception("resize failed")
            self._prepare(self.devices[self.keys.index(key)], self.dev_settings(key))
            self._fx = None

    def reset(self):
        """Fresh start for every LED: clear wizard/identify patterns and effect memory, take every device
        out of whatever effect it was running on its own (onboard/saved effects) and back to direct streaming,
        then resend everything on the next frame."""
        from . import fx
        self.tests.clear()
        fx._STATE.clear()
        fx._SHARED.clear()
        with self.lock:
            for d, k in zip(self.devices, self.keys):
                ds = self.dev_settings(k)
                try:
                    if getattr(d, "native", False):
                        d.reset()
                    elif ds["method"] != "static":
                        names = [m.name.lower() for m in d.modes]
                        want = next((w for w in ("direct", "custom", "static") if w in names), None)
                        if want:
                            d.set_mode(want)        # re-sent even if already active: drops onboard effects
                except Exception:  # noqa: BLE001
                    log.exception("reset %s failed", k)
            self._last.clear()
        self._fx = None

    def set_test(self, key: str, zone: str, spec: dict | None):
        if spec:
            if spec.get("kind") != "solid" and spec.get("size"):
                self._resize(key, zone, int(spec["size"]))     # temporary size while the wizard is open
            self.tests[(key, zone)] = spec
        else:
            self.tests.pop((key, zone), None)
            want = (self.dev_settings(key)["zones"].get(zone) or {}).get("size")
            if want is not None:
                self._resize(key, zone, int(want))
        self._last.pop(key, None)

    # ------------------------------------------------------------------ the stream
    def _value(self, eff):
        if not self.hub:
            return None
        s = self.hub.cpu_temp() if eff == "Temperature reactive" else self.hub.cpu_load() if eff == "Load reactive" else None
        return s.value if s else None

    def render(self, t: float) -> dict:
        from .rgb import frame as base_frame
        st = self.L["state"]
        c1, c2 = _hex(st["color"]), _hex(st["color2"])
        fx = self.fixtures()
        frame = ledmap.render(st["effect"], t, fx, c1, c2, float(st["speed"]), float(st["brightness"]),
                              self.L.get("paint", {}), self._value(st["effect"]),
                              base_frame=lambda e, tt, n, a, b, sp, v: base_frame(e, tt, n, a, sp, v, 1.0, b),
                              intensity=float(st.get("intensity", 0.5)), palette=st.get("palette", "Your colours"))
        for (key, zone), spec in self.tests.items():   # LED-count wizard patterns win over the effect
            frame[(key, zone)] = test_pattern(spec, t)
        return frame

    def _run(self):
        from openrgb.utils import RGBColor
        t0 = time.perf_counter()
        frames, fps_t = 0, time.time()
        while not self._stop.is_set():
            if self.client is None:
                if self.paused:
                    self._stop.wait(1)
                    continue
                if not self.connect():
                    self._stop.wait(15)
                    continue
            tick = time.perf_counter()
            try:
                frame = self.render(tick - t0)
                total = 0
                with self.lock:
                    for d, k in zip(self.devices, self.keys):
                        ds = self.dev_settings(k)
                        if not ds["enabled"]:
                            continue
                        cols = []
                        for z in d.zones:
                            zm = frame.get((k, z.name), {})
                            zc = [zm.get(i, (0, 0, 0)) for i in range(len(z.leds))]
                            if ds["reverse"]:
                                zc.reverse()
                            cols += zc
                        if not cols:
                            continue
                        b = float(ds["brightness"])
                        cols = [_reorder(tuple(int(v * b) for v in c), ds["order"]) for c in cols]
                        total += len(cols)
                        last = self._last.get(k)
                        now = time.time()
                        wireless = any(h in d.name.lower() for h in WIRELESS_HINTS)
                        if last and last[0] == cols and now - last[1] < 2.0:
                            continue                        # unchanged: only refresh every 2 s
                        if wireless and last and now - last[1] < 0.1:
                            continue                        # wireless devices: max ~10 updates/s
                        try:
                            if ds["method"] == "static":
                                if not last or last[0][0] != cols[0] or now - last[1] > 2.0:
                                    self._static(d, cols[0])
                            else:
                                d.set_colors([RGBColor(*c) for c in cols], fast=True)
                            self._last[k] = (cols, now)
                        except (ConnectionError, OSError, BrokenPipeError) as e:
                            if not getattr(d, "native", False):
                                raise
                            self.stats["errors"] += 1          # USB hiccup: reopen on the next frame
                            self.native_error = f"{d.name}: {e}"
                            d.close(hand_back=False)
                        except Exception:  # noqa: BLE001
                            self.stats["errors"] += 1
                self.stats["leds"] = total
                frames += 1
                self.stats["frames"] += 1
                if time.time() - fps_t >= 1:
                    self.stats["fps"] = frames / (time.time() - fps_t)
                    frames, fps_t = 0, time.time()
            except (ConnectionError, OSError, BrokenPipeError) as e:
                log.warning("lighting stream lost: %s", e)
                self.client = None
                self.msg = "Lost the lighting service - reconnecting…"
                continue
            except Exception:  # noqa: BLE001
                log.exception("lighting frame failed")
                self.stats["errors"] += 1
            self._stop.wait(max(0.0, 1 / 30 - (time.perf_counter() - tick)))

    def _static(self, d, c):
        from openrgb.utils import RGBColor
        names = [m.name.lower() for m in d.modes]
        if "static" in names and d.modes[d.active_mode].name.lower() != "static":
            d.set_mode("static")
        d.set_color(RGBColor(*c))

    def stop(self, keep_service: bool = True):
        self._stop.set()
        self.client = None
        if self._thread:
            self._thread.join(timeout=3)
        for n in self.native:
            n.close(hand_back=True)
        self.native = []
        if not keep_service:
            self.host.stop()


def _hex(h: str):
    h = (h or "#000000").lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


TEST_COLOURS = [(255, 0, 0), (0, 255, 0), (0, 80, 255), (255, 200, 0), (255, 0, 255), (0, 255, 255), (255, 255, 255),
                (255, 90, 0)]


def test_pattern(spec: dict, t: float) -> dict:
    """LED-count wizard patterns.
    fans:  every block of `per` LEDs gets its own colour -> with the right fan type each fan shows ONE colour.
    strip: dim blue, with LED number `count` bright red -> move it until the red LED is the last one on the strip."""
    n = int(spec.get("size") or 0)
    out = {}
    if spec.get("kind") == "solid":
        return {i: (255, 255, 255) for i in range(n)}
    if spec.get("kind") == "fans":
        per = max(1, int(spec.get("per") or 1))
        for i in range(n):
            out[i] = TEST_COLOURS[(i // per) % len(TEST_COLOURS)]
    else:
        last = int(spec.get("count") or n) - 1
        for i in range(n):
            out[i] = (255, 0, 0) if i == last else (0, 0, 60) if i < last else (0, 0, 0)
    return out
