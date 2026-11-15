"""Fan / pump curves applied through LibreHardwareMonitor's controls.

Safety rules baked in:
  * a curve can never go below MIN_PCT (pumps get PUMP_MIN_PCT)
  * if the source sensor stops reporting, the fan goes to 100%
  * if the source sensor goes above PANIC_TEMP, the fan goes to 100%
  * on exit every controlled fan is handed back to the BIOS/default
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MIN_PCT = 20.0
PUMP_MIN_PCT = 60.0
PANIC_TEMP = 90.0
HYSTERESIS = 2.0  # °C - ignore small dips so fans don't hunt up and down

PRESETS = {
    "Silent":      [[30, 20], [50, 30], [65, 50], [75, 75], [85, 100]],
    "Balanced":    [[30, 25], [45, 35], [60, 55], [72, 80], [82, 100]],
    "Performance": [[30, 40], [45, 55], [60, 75], [70, 90], [78, 100]],
    "Full speed":  [[0, 100], [100, 100]],
}


def interpolate(points: list[list[float]], temp: float) -> float:
    pts = sorted(points)
    if not pts:
        return 100.0
    if temp <= pts[0][0]:
        return pts[0][1]
    if temp >= pts[-1][0]:
        return pts[-1][1]
    for (t1, p1), (t2, p2) in zip(pts, pts[1:]):
        if t1 <= temp <= t2:
            return p1 + (p2 - p1) * (temp - t1) / max(1e-9, t2 - t1)
    return pts[-1][1]


class FanCurveEngine:
    def __init__(self, hub, config):
        self.hub = hub
        self.config = config
        self.enabled = False
        self._last_temp: dict[str, float] = {}
        self.applied: dict[str, float] = {}
        hub.subscribe(self._tick)

    @property
    def curves(self) -> dict:
        return self.config["fan_curves"]

    def set_curve(self, control_id: str, source_id: str, points: list[list[float]], is_pump: bool = False):
        self.curves[control_id] = {"source": source_id, "points": points, "pump": is_pump}
        self._last_temp.pop(control_id, None)
        self.config.save()

    def remove_curve(self, control_id: str):
        self.curves.pop(control_id, None)
        self.hub.set_control(control_id, None)
        self.applied.pop(control_id, None)
        self.config.save()

    def target_for(self, control_id: str, sensors: dict) -> float:
        c = self.curves[control_id]
        src = sensors.get(c["source"])
        floor = PUMP_MIN_PCT if c.get("pump") else MIN_PCT
        if src is None or src.value is None:
            return 100.0                      # lost sensor -> fail safe
        temp = src.value
        if temp >= PANIC_TEMP:
            return 100.0
        prev = self._last_temp.get(control_id)
        if prev is not None and prev - HYSTERESIS < temp < prev:
            temp = prev                       # small drop: hold
        self._last_temp[control_id] = temp
        return max(floor, min(100.0, interpolate(c["points"], temp)))

    def _tick(self, snap):
        if not self.enabled:
            return
        for cid in list(self.curves):
            pct = self.target_for(cid, snap.sensors)
            if abs(self.applied.get(cid, -99) - pct) >= 1:
                if self.hub.set_control(cid, pct):
                    self.applied[cid] = pct

    def release_all(self):
        """Give every fan back to BIOS control."""
        self.enabled = False
        for cid in list(self.applied):
            self.hub.set_control(cid, None)
        self.applied.clear()
