"""Native USB drivers: RigLab talks to the hardware directly, no OpenRGB / iCUE in between.

Corsair Lighting Node Pro / Lighting Node Core / Commander Pro (HID, VID 1B1C)
    Software ("direct") control as used by OpenRGB's CorsairLightingNodeController:
      0x38 [ch, 0x02]           port state -> software (0x01 = back to hardware effects)
      0x39 [ch, 0x64]           channel brightness 100 %  (left at 0 by some effect tools -> dark fans)
      0x32 [ch, start, n, c, …]  n (≤50) values of colour component c (0 R, 1 G, 2 B) starting at LED `start`
      0x33 [0xFF]               commit (show the frame); also needed every few seconds as keep-alive
    Every packet is 64 bytes (+ report id 0) and the node answers each with a 16-byte status report.

These objects look like openrgb-python devices (name/zones/modes/set_colors) so the LightingEngine streams
to them exactly like it does to every other device.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

CORSAIR_VID = 0x1B1C
NODES = {0x0C0B: ("Corsair Lighting Node Pro", 2), 0x0C1A: ("Corsair Lighting Node Core", 1),
         0x0C10: ("Corsair Commander Pro", 2)}
OPENRGB_DETECTORS = {"Corsair Lighting Node Pro", "Corsair Lighting Node Core", "Corsair Commander Pro"}
MAX_PER_CHANNEL = 204


class _Mode:
    def __init__(self, name):
        self.name = name


class NativeZone:
    def __init__(self, dev, idx, name):
        self.dev, self.idx, self.name = dev, idx, name
        self.leds: list = []
        self.leds_min, self.leds_max = 0, MAX_PER_CHANNEL

    def resize(self, n: int):
        self.leds = [0] * max(0, min(MAX_PER_CHANNEL, int(n)))


class CorsairNode:
    """One Lighting Node Pro / Core / Commander Pro, driven directly over HID."""

    type = "DeviceType.LEDSTRIP"
    metadata = None
    native = True

    def __init__(self, info: dict):
        self.info = info
        self.name, nch = NODES[info["product_id"]]
        self.zones = [NativeZone(self, i, f"Channel {i + 1}") for i in range(nch)]
        self.modes = [_Mode("Direct")]
        self.active_mode = 0
        self.h = None
        self.lock = threading.Lock()
        self.last_commit = 0.0
        self.error: str | None = None
        self.writes = 0

    @property
    def leds(self):
        return [0] * sum(len(z.leds) for z in self.zones)

    # ---------------------------------------------------------------- low level
    def open(self):
        import hid
        h = hid.device()
        h.open_path(self.info["path"])
        self.h = h
        for z in self.zones:
            self._send(0x38, [z.idx, 0x02])     # software control
            self._send(0x39, [z.idx, 0x64])     # full brightness
        self._send(0x33, [0xFF])
        log.info("%s opened natively", self.name)

    def _send(self, cmd: int, data: list[int]):
        buf = bytes([0x00, cmd] + [int(x) & 0xFF for x in data])
        buf = buf + bytes(65 - len(buf))
        if self.h.write(buf) < 0:
            raise OSError(f"write to {self.name} failed")
        self.writes += 1
        try:
            self.h.read(17, 30)                 # status reply; we don't need it, but drain it
        except Exception:  # noqa: BLE001
            pass

    def reset(self):
        """Back to a clean software-controlled state: software mode + full brightness on every channel."""
        with self.lock:
            if self.h is None:
                self.open()
                return
            for z in self.zones:
                self._send(0x38, [z.idx, 0x02])
                self._send(0x39, [z.idx, 0x64])
            self._send(0x33, [0xFF])

    def set_mode(self, _name):
        return None

    def set_color(self, c):
        self.set_colors([c] * len(self.leds))

    def set_colors(self, colours, fast=True):
        with self.lock:
            if self.h is None:
                self.open()
            i = 0
            for z in self.zones:
                n = len(z.leds)
                part = colours[i:i + n]
                i += n
                if not n:
                    continue
                comps = ([c.red for c in part], [c.green for c in part], [c.blue for c in part])
                for ci, vals in enumerate(comps):
                    for off in range(0, n, 50):
                        chunk = vals[off:off + 50]
                        self._send(0x32, [z.idx, off, len(chunk), ci] + chunk)
            self._send(0x33, [0xFF])
            self.last_commit = time.time()

    def close(self, hand_back: bool = True):
        with self.lock:
            if self.h is None:
                return
            try:
                if hand_back:
                    for z in self.zones:
                        self._send(0x38, [z.idx, 0x01])     # node's own saved effect takes over again
            except Exception:  # noqa: BLE001
                pass
            try:
                self.h.close()
            except Exception:  # noqa: BLE001
                pass
            self.h = None


def find_devices() -> list:
    """All supported devices that are plugged in (one object per physical device)."""
    try:
        import hid
    except ImportError:
        log.warning("hidapi isn't installed - native drivers disabled")
        return []
    out, seen = [], set()
    for info in hid.enumerate(CORSAIR_VID, 0):
        pid = info.get("product_id")
        if pid in NODES and info.get("serial_number", "") + str(pid) not in seen:
            seen.add(info.get("serial_number", "") + str(pid))
            out.append(CorsairNode(info))
    return out
