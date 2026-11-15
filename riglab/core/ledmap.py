"""LED map: every fan / strip as a "fixture" with a position, so effects can address each LED individually.

A fixture is one physical fan (a ring of LEDs) or strip (a line). Fixtures are cut out of device zones using
the fan type chosen for that channel (e.g. LL120 = 16 LEDs per fan), and laid out on a simple grid that the
user can rearrange. render() returns colours per LED for every (device, zone).
"""
from __future__ import annotations

import colorsys
import math

WRAP = 5
SPATIAL_EFFECTS = ["Spin", "Comet", "Rainbow sweep", "Colour sweep", "Fan cycle", "Breathing wave", "Custom paint"]


def _hsv(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (r * 255, g * 255, b * 255)


def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(x + (y - x) * t for x, y in zip(a, b))


# ---------------------------------------------------------------- building the map
def auto_map(devices: list[dict], meta: dict, saved: list[dict] | None = None) -> list[dict]:
    """devices: rgb_state()['devices']. meta: {"Device|Zone": {"per": leds_per_fan}}.
    Saved fixtures keep their position/kind/label if the same fixture still exists."""
    fixtures: list[dict] = []
    for row, d in enumerate(devices):
        x = 0
        for z in d.get("zones") or [{"name": "All", "leds": d.get("leds", 0)}]:
            n = int(z.get("leds") or 0)
            if n <= 0:
                continue
            key = f"{d['name']}|{z['name']}"
            per = int((meta.get(key) or {}).get("per") or 0)
            if per and n >= per:
                for i in range(n // per):
                    fixtures.append({"id": f"{key}#{i}", "device": d["name"], "zone": z["name"], "start": i * per,
                                     "count": per, "kind": "fan", "label": f"{z['name']} · fan {i + 1}", "x": x, "y": row})
                    x += 1
                rest = n % per
                if rest:
                    fixtures.append({"id": f"{key}#rest", "device": d["name"], "zone": z["name"], "start": n - rest,
                                     "count": rest, "kind": "strip", "label": f"{z['name']} · extra", "x": x, "y": row})
                    x += 1
            else:
                fan_like = d.get("type") in ("Cooler",) and n in (4, 8, 12, 16, 18, 34)
                fixtures.append({"id": f"{key}#0", "device": d["name"], "zone": z["name"], "start": 0, "count": n,
                                 "kind": "fan" if fan_like else "strip", "label": z["name"] if z["name"] != "All" else d["name"],
                                 "x": x, "y": row})
                x += 1
    for i, f in enumerate(fixtures):          # compact default layout: wrap after WRAP lights
        f["x"], f["y"] = i % WRAP, i // WRAP
    by_id = {f["id"]: f for f in (saved or [])}
    for f in fixtures:
        s = by_id.get(f["id"])
        if s and s.get("count") == f["count"]:
            for k in ("x", "y", "kind", "label"):
                if k in s:
                    f[k] = s[k]
    return fixtures


def led_positions(f: dict) -> list[tuple[float, float, float]]:
    """(x, y, angle 0..1) for every LED of a fixture."""
    n = max(1, f["count"])
    out = []
    for k in range(n):
        a = k / n
        if f["kind"] == "fan":
            out.append((f["x"] + 0.42 * math.cos(2 * math.pi * a), f["y"] + 0.42 * math.sin(2 * math.pi * a), a))
        else:
            out.append((f["x"] - 0.45 + 0.9 * (k / max(1, n - 1)), f["y"], a))
    return out


# ---------------------------------------------------------------- rendering
def render(effect: str, t: float, fixtures: list[dict], c1, c2, speed: float = 1.0, brightness: float = 1.0,
           paint: dict | None = None, value: float | None = None, base_frame=None, intensity: float = 0.5,
           palette: str = "Your colours") -> dict:
    """-> {(device, zone): {led_index_in_zone: (r, g, b)}}.
    base_frame(effect, t, n, c1, c2, speed, value) handles the classic non-spatial effects per fixture."""
    out: dict = {}
    if not fixtures:
        return out
    xs = [f["x"] for f in fixtures]
    x0, x1 = min(xs) - 0.5, max(xs) + 0.5
    ys = [f["y"] for f in fixtures]
    y0, y1 = min(ys) - 0.5, max(ys) + 0.5
    nf = len(fixtures)
    from . import fx
    paint = paint or {}
    for fi, f in enumerate(fixtures):
        key = (f["device"], f["zone"])
        dest = out.setdefault(key, {})
        pos = led_positions(f)
        classic = None
        if effect in fx.EFFECTS:
            norm = [((px - x0) / max(1e-6, x1 - x0), (py - y0) / max(1e-6, y1 - y0), a) for px, py, a in pos]
            classic = fx.render_fixture(effect, f["id"], norm, fi, nf, t, c1, c2, speed, intensity, palette)
        elif effect not in SPATIAL_EFFECTS and base_frame:
            classic = base_frame(effect, t, f["count"], tuple(c1), tuple(c2), speed, value)
        for k, (px, _py, ang) in enumerate(pos):
            gx = (px - x0) / max(1e-6, x1 - x0)
            if classic is not None:
                c = classic[k]
            elif effect == "Spin":
                c = _hsv(ang + t * speed * 0.5)
            elif effect == "Comet":
                head = (t * speed * 0.8 + fi * 0.13) % 1.0
                d = (head - ang) % 1.0                          # how far behind the head this LED is
                k2 = max(0.0, 1 - d * 4) ** 2
                c = _lerp(tuple(v * 0.06 for v in c2), c1, k2)
            elif effect == "Rainbow sweep":
                c = _hsv(gx * 0.8 - t * speed * 0.2)
            elif effect == "Colour sweep":
                c = _lerp(c1, c2, (math.sin(2 * math.pi * (gx - t * speed * 0.3)) + 1) / 2)
            elif effect == "Fan cycle":
                c = _hsv(fi / max(1, nf) + t * speed * 0.1)
            elif effect == "Breathing wave":
                kk = ((math.sin(t * speed * 2 - fi * 0.8) + 1) / 2) ** 2
                c = tuple(v * (0.06 + 0.94 * kk) for v in c1)
            elif effect == "Custom paint":
                hx = (paint.get(f["id"]) or {}).get(str(k))
                c = _hex(hx) if hx else tuple(c1)
            else:
                c = tuple(c1)
            dest[f["start"] + k] = tuple(int(max(0, min(255, v * brightness))) for v in c)
    return out


def _hex(h: str):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
