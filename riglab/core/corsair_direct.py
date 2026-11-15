"""Drive a Corsair Lighting Node Pro / Core / Commander Pro's LEDs directly (via liquidctl), without OpenRGB or iCUE.

Effects run in the node's own hardware, so they keep going after RigLab closes. When this "direct" mode is on,
OpenRGB's Lighting Node detector is switched off so the two programs don't fight over the device.
The node keeps a list of saved effects (max 8 per channel), so every apply clears the old ones first.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
NODE_NAMES = ("lighting node pro", "lighting node core", "commander pro")
OPENRGB_DETECTORS = {"lighting node pro": "Corsair Lighting Node Pro", "lighting node core": "Corsair Lighting Node Core",
                     "commander pro": "Corsair Commander Pro"}


def _scale(c, k):
    return [max(0, min(255, int(v * k))) for v in c]


def _lerp(a, b, t):
    return [int(x + (y - x) * t) for x, y in zip(a, b)]


class CorsairDirect:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_error: str | None = None
        self.description: str | None = None

    # ------------------------------------------------------------------ device
    def _find(self):
        from liquidctl import find_liquidctl_devices
        for d in find_liquidctl_devices():
            if any(n in d.description.lower() for n in NODE_NAMES):
                return d
        return None

    def present(self) -> str | None:
        try:
            d = self._find()
            self.description = d.description if d else None
            return self.description
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            return None

    def channels(self) -> list[str]:
        return ["led"] if self.description and "core" in self.description.lower() else ["led1", "led2"]

    # ------------------------------------------------------------------ apply
    def apply(self, effect: str, c1, c2, speed: float = 1.0, brightness: float = 1.0,
              sizes: dict | None = None) -> str:
        """Returns 'ok' or an error message. sizes: {'led1': n, 'led2': n} LED counts (unknown -> 204)."""
        sizes = sizes or {}
        spd = "slow" if speed < 0.8 else "medium" if speed < 2 else "fast"
        a, b = _scale(c1, brightness), _scale(c2, brightness)
        plan = {  # RigLab effect -> (liquidctl mode, colours)
            "Static": ("fixed", [a]), "Breathing": ("color_pulse", [a, a]), "Spectrum cycle": ("rainbow", []),
            "Rainbow wave": ("rainbow2", []), "Colour wave": ("color_wave", [a, b]), "Twinkle": ("color_shift", [a, b]),
            "Strobe": ("blink", [a, a]), "Off": ("off", []),
            "Temperature reactive": ("fixed", [a]), "Load reactive": ("fixed", [a]),
            # per-LED map effects -> closest effect the node can run on its own
            "Spin": ("rainbow2", []), "Comet": ("marquee", [a]), "Rainbow sweep": ("rainbow2", []),
            "Colour sweep": ("color_wave", [a, b]), "Fan cycle": ("rainbow", []), "Breathing wave": ("color_pulse", [a, a]),
            "Custom paint": ("fixed", [a]),
        }
        with self.lock:
            dev = None
            try:
                dev = self._find()
                if not dev:
                    return "Lighting Node not found over USB"
                self.description = dev.description
                dev.connect()
                dev.initialize()
                for ch in self.channels():
                    n = int(sizes.get(ch) or 204)
                    dev.set_color(ch, "clear", [])              # wipe saved effects (max 8 per channel)
                    if effect == "Gradient":                     # 8 fixed segments blending colour 1 -> 2
                        seg = max(1, n // 8)
                        for i in range(8):
                            dev.set_color(ch, "fixed", [_lerp(a, b, i / 7)], start_led=1 + i * seg,
                                          maximum_leds=seg if i < 7 else n - 7 * seg)
                        continue
                    mode, cols = plan.get(effect, ("fixed", [a]))
                    dev.set_color(ch, mode, cols, speed=spd, direction="forward", start_led=1, maximum_leds=n)
                self.last_error = None
                return "ok"
            except Exception as e:  # noqa: BLE001
                log.exception("direct Corsair lighting failed")
                self.last_error = f"{type(e).__name__}: {e}"
                return self.last_error
            finally:
                if dev is not None:
                    try:
                        dev.disconnect()
                    except Exception:  # noqa: BLE001
                        pass


HARDWARE_EFFECTS = {"Static", "Breathing", "Spectrum cycle", "Rainbow wave", "Colour wave", "Strobe", "Off"}


def restore_openrgb_settings(exe: str | None) -> list[str]:
    """Put back the OpenRGB.json from before RigLab ever touched it (oldest RigLab backup)."""
    restored = []
    for f in openrgb_config_files(exe):
        backups = sorted(f.parent.glob(f.name + ".riglab-backup-*"), key=lambda p: p.stat().st_mtime) if f.parent.exists() else []
        if not backups:
            backups = sorted(f.parent.glob(f.stem + ".json.riglab-backup-*"), key=lambda p: p.stat().st_mtime) if f.parent.exists() else []
        if backups:
            shutil.copy2(backups[0], f)
            restored.append(f"{f} (from {backups[0].name})")
    return restored


# ---------------------------------------------------------------- per-LED streaming (software mode)
# Corsair Lighting Node protocol (as used by iCUE/OpenRGB; documented by the CorsairLightingProtocol project):
#   0x38 [channel, mode]            port state: 0x01 hardware effects, 0x02 software (host streams colours)
#   0x32 [ch, offset, n<=50, colour(0=R,1=G,2=B), v0..vn]   LED colour values for one colour component
#   0x33 [0xFF]                     commit / show
# In software mode the node falls back to its hardware effects if it isn't refreshed for a few seconds,
# so frames (or a keepalive commit) are sent continuously.
CMD_COLOURS, CMD_COMMIT, CMD_PORT_STATE = 0x32, 0x33, 0x38
STATE_HARDWARE, STATE_SOFTWARE = 0x01, 0x02


def _send(dev, cmd: int, data: list[int]):
    """Use liquidctl's own (tested) transport for this device family when available."""
    if hasattr(dev, "_send_command"):
        return dev._send_command(cmd, data)
    buf = bytearray(65)                     # report id 0 + 64 byte report
    buf[1] = cmd
    buf[2:2 + len(data)] = bytes(data)
    dev.device.write(buf)
    return dev.device.read(16)


class DirectStreamer:
    """Streams per-LED colours to the node's channels at ~25 fps while RigLab is running."""

    def __init__(self, direct: CorsairDirect):
        self.direct = direct
        self.frame: dict[str, list] = {}       # channel -> [(r,g,b), ...]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.frames_sent = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def push(self, channel_colours: dict[str, list]):
        self.frame = channel_colours

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, name="CorsairStream", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None

    def _run(self):
        if True:  # (no long-held lock: hardware applies stop the streamer first)
            dev = None
            try:
                dev = self.direct._find()
                if not dev:
                    self.error = "Lighting Node not found"
                    return
                dev.connect()
                chans = self.direct.channels()
                ch_num = {"led1": 0, "led2": 1, "led": 0}
                for ch in chans:
                    _send(dev, CMD_PORT_STATE, [ch_num[ch], STATE_SOFTWARE])
                last = None
                while not self._stop.wait(0.04):
                    frame = self.frame
                    if frame is last:
                        _send(dev, CMD_COMMIT, [0xFF])          # keepalive
                        continue
                    last = frame
                    for ch in chans:
                        cols = frame.get(ch) or []
                        for comp in range(3):
                            vals = [int(c[comp]) for c in cols]
                            for off in range(0, len(vals), 50):
                                chunk = vals[off:off + 50]
                                _send(dev, CMD_COLOURS, [ch_num[ch], off, len(chunk), comp] + chunk)
                    _send(dev, CMD_COMMIT, [0xFF])
                    self.frames_sent += 1
            except Exception as e:  # noqa: BLE001
                log.exception("Corsair streaming failed")
                self.error = f"{type(e).__name__}: {e}"
            finally:
                if dev is not None:
                    try:
                        for ch in self.direct.channels():
                            _send(dev, CMD_PORT_STATE, [{"led1": 0, "led2": 1, "led": 0}[ch], STATE_HARDWARE])
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        dev.disconnect()
                    except Exception:  # noqa: BLE001
                        pass


# ---------------------------------------------------------------- OpenRGB settings: hand the node over / back
def openrgb_config_files(exe: str | None) -> list[Path]:
    out = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "OpenRGB" / "OpenRGB.json")
    if exe:
        out.append(Path(exe).parent / "OpenRGB.json")      # portable copies keep settings next to the exe
    return [p for p in out if p.exists()] or out[:1]


def set_openrgb_detector(description: str, enabled: bool, exe: str | None) -> list[str]:
    """Enable/disable OpenRGB's detector for this node. OpenRGB must be closed while editing."""
    key = next((v for k, v in OPENRGB_DETECTORS.items() if k in (description or "").lower()), None)
    if not key:
        return []
    changed = []
    for f in openrgb_config_files(exe):
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except (OSError, ValueError):
            continue
        if f.exists():
            shutil.copy2(f, f.with_suffix(f".json.riglab-backup-{int(time.time())}"))
        data.setdefault("Detectors", {}).setdefault("detectors", {})[key] = bool(enabled)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=4), encoding="utf-8")
        changed.append(str(f))
    return changed


def stop_openrgb():
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == "openrgb.exe":
                p.terminate()
                p.wait(5)
    except Exception:  # noqa: BLE001
        pass
