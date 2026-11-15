"""RigLab effect pack: palettes + effects in the style of WLED / FastLED demos.

Written from scratch for RigLab (WLED itself is EUPL-licensed, so no code is copied - only the effect ideas).
Mirrored 1:1 in riglab/web/js/fx.js for the live previews; keep the two in sync.

render_fixture() returns float RGB for every LED of one fixture (fan ring / strip). Each LED has a
position (gx, gy in 0..1 across the whole LED map, ang 0..1 around a fan), so 2D effects (Plasma, Ripple,
Aurora...) flow across the case as one picture.
"""
from __future__ import annotations

import math
import random

# --------------------------------------------------------------------------- palettes
PALETTES = {
    "Your colours": None,                      # colour 1 -> colour 2 -> colour 1
    "Rainbow": [(0, (255, 0, 0)), (.17, (255, 255, 0)), (.33, (0, 255, 0)), (.5, (0, 255, 255)), (.67, (0, 0, 255)),
                (.83, (255, 0, 255)), (1, (255, 0, 0))],
    "Party": [(0, (90, 0, 255)), (.25, (255, 0, 120)), (.5, (255, 90, 0)), (.75, (255, 200, 0)), (1, (90, 0, 255))],
    "Lava": [(0, (0, 0, 0)), (.3, (120, 0, 0)), (.55, (255, 30, 0)), (.75, (255, 140, 0)), (.9, (255, 230, 120)), (1, (0, 0, 0))],
    "Ocean": [(0, (0, 10, 60)), (.3, (0, 60, 160)), (.55, (0, 160, 200)), (.75, (40, 220, 200)), (1, (0, 10, 60))],
    "Forest": [(0, (0, 40, 0)), (.3, (20, 120, 10)), (.55, (90, 180, 30)), (.75, (0, 90, 40)), (1, (0, 40, 0))],
    "Heat": [(0, (0, 0, 0)), (.35, (200, 0, 0)), (.65, (255, 140, 0)), (.85, (255, 230, 60)), (1, (255, 255, 220))],
    "Sunset": [(0, (120, 0, 60)), (.3, (255, 40, 40)), (.55, (255, 140, 0)), (.75, (255, 60, 120)), (1, (120, 0, 60))],
    "Aurora": [(0, (0, 30, 20)), (.3, (0, 220, 100)), (.55, (0, 120, 200)), (.75, (140, 0, 220)), (1, (0, 30, 20))],
    "Cyberpunk": [(0, (255, 0, 160)), (.33, (120, 0, 255)), (.66, (0, 220, 255)), (1, (255, 0, 160))],
    "Ice": [(0, (0, 20, 80)), (.4, (0, 140, 255)), (.7, (180, 240, 255)), (1, (0, 20, 80))],
}


def palette_fn(name: str, c1, c2):
    stops = PALETTES.get(name) or [(0, c1), (.5, c2), (1, c1)]

    def pal(x: float):
        x %= 1.0
        for i in range(1, len(stops)):
            p1, a = stops[i - 1]
            p2, b = stops[i]
            if x <= p2:
                k = (x - p1) / max(1e-6, p2 - p1)
                return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k)
        return stops[-1][1]
    return pal


# --------------------------------------------------------------------------- helpers
def _hash(i: float) -> float:
    return math.modf(abs(math.sin(i * 12.9898 + 78.233) * 43758.5453))[0]


def _noise2(x: float, y: float) -> float:
    """Smooth value noise, 0..1."""
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    u, v = xf * xf * (3 - 2 * xf), yf * yf * (3 - 2 * yf)
    a, b = _hash(xi + yi * 57), _hash(xi + 1 + yi * 57)
    c, d = _hash(xi + (yi + 1) * 57), _hash(xi + 1 + (yi + 1) * 57)
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v


def _hsv(h, s=1.0, v=1.0):
    h = (h % 1.0) * 6
    i, f = int(h), h - int(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]
    return (r * 255, g * 255, b * 255)


def _scale(c, k):
    return (c[0] * k, c[1] * k, c[2] * k)


def _add(a, b):
    return (min(255, a[0] + b[0]), min(255, a[1] + b[1]), min(255, a[2] + b[2]))


def _tri(x):
    """0 -> 1 -> 0 triangle wave, period 1."""
    x %= 1.0
    return 1 - abs(2 * x - 1)


def _buf(st, n):
    b = st.get("buf")
    if b is None or len(b) != n:
        b = st["buf"] = [(0.0, 0.0, 0.0)] * n
    return b


def _fade(b, keep):
    for i, c in enumerate(b):
        b[i] = (c[0] * keep, c[1] * keep, c[2] * keep)


# --------------------------------------------------------------------------- effects
# fn(n, pos, P, st) -> list[(r,g,b)]; pos[k] = (gx, gy, ang); P = params; st = per-fixture state
def fx_palette_flow(n, pos, P, st):
    return [P["pal"](k / n * (0.5 + P["int"]) - P["t"] * P["sp"] * 0.2) for k in range(n)]


def fx_running(n, pos, P, st):
    out = []
    for k in range(n):
        w = (math.sin(2 * math.pi * (k / n * (1 + P["int"] * 4) - P["t"] * P["sp"] * 0.5)) + 1) / 2
        out.append(_scale(P["pal"](k / n), w * w))
    return out


def fx_theater(n, pos, P, st):
    step = int(P["t"] * P["sp"] * 8)
    gap = 2 + int(P["int"] * 4)
    return [P["pal"](k / n + P["t"] * 0.05) if (k + step) % gap == 0 else (0, 0, 0) for k in range(n)]


def fx_larson(n, pos, P, st):
    head = _tri(P["t"] * P["sp"] * 0.35) * (n - 1)
    width = 1 + P["int"] * n * 0.3
    return [_scale(P["c1"], max(0.0, 1 - abs(k - head) / width) ** 2) for k in range(n)]


def fx_sinelon(n, pos, P, st):
    b = _buf(st, n)
    _fade(b, 0.80 + P["int"] * 0.17)
    i = int((math.sin(P["t"] * P["sp"] * 1.6 + P["fi"]) + 1) / 2 * (n - 1) + 0.5)
    b[i] = P["pal"](P["t"] * 0.05)
    return list(b)


def fx_juggle(n, pos, P, st):
    b = _buf(st, n)
    _fade(b, 0.82)
    dots = 3 + int(P["int"] * 5)
    for j in range(dots):
        i = int((math.sin(P["t"] * P["sp"] * (0.7 + j * 0.31)) + 1) / 2 * (n - 1) + 0.5)
        b[i] = _add(b[i], _scale(_hsv(j / dots), 0.8))
    return list(b)


def fx_bpm(n, pos, P, st):
    beat = (math.sin(P["t"] * P["sp"] * 2 * math.pi * 1.0) + 1) / 2
    return [_scale(P["pal"](k / n * 0.6 + P["t"] * 0.1), 0.25 + 0.75 * beat * (0.6 + 0.4 * math.sin(k * 0.6))) for k in range(n)]


def fx_meteor(n, pos, P, st):
    b = _buf(st, n)
    for i in range(n):                                       # random trail decay = sparkly tail
        if random.random() < 0.6:
            b[i] = _scale(b[i], 0.55 + P["int"] * 0.35)
    head = int((P["t"] * P["sp"] * 0.6 + P["fi"] * 0.21) % 1.0 * n)
    for j in range(max(1, n // 12)):
        b[(head - j) % n] = P["c1"]
    return list(b)


def fx_fire(n, pos, P, st):
    heat = st.get("heat")
    if heat is None or len(heat) != n:
        heat = st["heat"] = [0.0] * n
    cool = 0.05 + (1 - P["int"]) * 0.12
    for i in range(n):                                       # cool down
        heat[i] = max(0.0, heat[i] - random.random() * cool)
    for i in range(n - 1, 1, -1):                            # heat rises
        heat[i] = (heat[i - 1] + heat[i - 2] * 2) / 3
    if random.random() < 0.35 + P["int"] * 0.5:             # sparks at the bottom
        j = random.randint(0, min(2, n - 1))
        heat[j] = min(1.0, heat[j] + 0.6 + random.random() * 0.4)
    pal = PALETTES[P["palname"]] and P["pal"] or palette_fn("Heat", P["c1"], P["c2"])
    return [pal(min(0.99, h) * 0.999) for h in heat]


def fx_candle(n, pos, P, st):
    v = st.get("v", 0.8)
    v += (random.random() - 0.5) * (0.15 + P["int"] * 0.4) * P["sp"]
    v = st["v"] = max(0.35, min(1.0, v * 0.97 + 0.8 * 0.03))
    base = P["c1"] if P["palname"] == "Your colours" else (255, 120, 20)
    return [_scale(base, v * (0.9 + 0.1 * _hash(k + int(P["t"] * 20)))) for k in range(n)]


def fx_confetti(n, pos, P, st):
    b = _buf(st, n)
    _fade(b, 0.90)
    for _ in range(1 + int(P["int"] * 3)):
        if random.random() < 0.5 * P["sp"]:
            b[random.randrange(n)] = P["pal"](random.random())
    return list(b)


def fx_glitter(n, pos, P, st):
    out = [P["pal"](k / n - P["t"] * P["sp"] * 0.15) for k in range(n)]
    for _ in range(1 + int(P["int"] * 4)):
        if random.random() < 0.6:
            out[random.randrange(n)] = (255, 255, 255)
    return out


def fx_twinklefox(n, pos, P, st):
    out = []
    for k in range(n):
        ph, rate = _hash(k + P["fi"] * 101), 0.5 + _hash(k * 7 + 3) * 1.5
        w = max(0.0, math.sin(2 * math.pi * (P["t"] * P["sp"] * rate * 0.4 + ph)))
        w = w ** (1 + (1 - P["int"]) * 4)
        out.append(_scale(P["pal"](_hash(k * 13 + 1)), w))
    return out


def fx_fireworks(n, pos, P, st):
    b = _buf(st, n)
    _fade(b, 0.86)
    sparks = st.setdefault("sparks", [])
    if random.random() < 0.06 * P["sp"] * (0.5 + P["int"]):
        c, at = P["pal"](random.random()), random.randrange(n)
        sparks += [[at, (random.random() - 0.5) * 1.6, c, 1.0] for _ in range(6)]
    for s in sparks:
        s[0] += s[1]
        s[3] *= 0.9
        i = int(s[0]) % n
        b[i] = _add(b[i], _scale(s[2], s[3]))
    st["sparks"] = [s for s in sparks if s[3] > 0.05]
    return list(b)


def fx_lightning(n, pos, P, st):
    if st.get("until", -1.0) < P["t"] or "a" not in st:
        if random.random() < 0.02 * P["sp"] * (0.5 + P["int"]):
            st["until"] = P["t"] + 0.05 + random.random() * 0.2
            st["a"], st["len"] = random.randrange(n), max(2, int(n * (0.3 + random.random() * 0.7)))
        return [(0, 0, 0)] * n
    on = random.random() < 0.7
    return [(255, 255, 255) if on and (k - st["a"]) % n < st["len"] else (0, 0, 0) for k in range(n)]


def fx_police(n, pos, P, st):
    ph = int(P["t"] * P["sp"] * 6) % 4
    left = ph in (0, 1) and int(P["t"] * P["sp"] * 24) % 2 == 0
    right = ph in (2, 3) and int(P["t"] * P["sp"] * 24) % 2 == 0
    return [(255, 0, 0) if (k < n / 2 and left) else (0, 40, 255) if (k >= n / 2 and right) else (0, 0, 0) for k in range(n)]


def fx_heartbeat(n, pos, P, st):
    x = (P["t"] * P["sp"] * 1.1) % 1.0
    v = max(math.exp(-((x - 0.05) / 0.04) ** 2), 0.7 * math.exp(-((x - 0.25) / 0.05) ** 2))
    return [_scale(P["c1"], 0.08 + 0.92 * v)] * n


def fx_dissolve(n, pos, P, st):
    b = st.get("d")
    if b is None or len(b) != n:
        b = st["d"] = [False] * n
        st["dir"] = True
    for _ in range(1 + int(P["int"] * 3)):
        if random.random() < 0.7 * P["sp"]:
            b[random.randrange(n)] = st["dir"]
    if all(x == st["dir"] for x in b):
        st["dir"] = not st["dir"]
    return [P["c1"] if x else P["c2"] for x in b]


def fx_bouncing(n, pos, P, st):
    out = [(0.0, 0.0, 0.0)] * n
    balls = 2 + int(P["int"] * 3)
    for j in range(balls):
        period = 1.2 + j * 0.37
        x = ((P["t"] * P["sp"] + j * 0.53) % period) / period
        h = 1 - (2 * x - 1) ** 2                              # parabola: one bounce per period
        i = int(h * (n - 1))
        out[i] = _add(out[i], P["pal"](j / balls))
    return out


def fx_rain(n, pos, P, st):
    out = []
    for k, (gx, gy, _a) in enumerate(pos):
        col = int(gx * 12)
        head = (P["t"] * P["sp"] * (0.4 + _hash(col) * 0.6) + _hash(col * 3)) % 1.4
        d = head - gy
        w = math.exp(-d * (6 - P["int"] * 4)) if d >= 0 else 0.0
        out.append(_scale(P["pal"](0.5 + _hash(col) * 0.3) if P["palname"] != "Your colours" else P["c1"], w))
    return out


def fx_plasma(n, pos, P, st):
    t, s = P["t"] * P["sp"], 2 + P["int"] * 6
    out = []
    for gx, gy, _a in pos:
        v = math.sin(gx * s + t) + math.sin(gy * s * 0.8 - t * 1.3) + math.sin((gx + gy) * s * 0.6 + t * 0.7)
        out.append(P["pal"]((v + 3) / 6 + t * 0.05))
    return out


def fx_noise(n, pos, P, st):
    t, s = P["t"] * P["sp"] * 0.4, 1.5 + P["int"] * 5
    return [P["pal"](_noise2(gx * s + t, gy * s - t * 0.7)) for gx, gy, _a in pos]


def fx_aurora(n, pos, P, st):
    t = P["t"] * P["sp"] * 0.25
    pal = P["pal"] if P["palname"] != "Your colours" else palette_fn("Aurora", 0, 0)
    out = []
    for gx, gy, _a in pos:
        band = _noise2(gx * (2 + P["int"] * 4) + t, t * 0.6)
        curtain = (math.sin(gx * 9 + t * 3 + band * 4) + 1) / 2
        out.append(_scale(pal(band * 0.8 + gy * 0.2), 0.2 + 0.8 * curtain * (1 - gy * 0.5)))
    return out


def fx_pacifica(n, pos, P, st):
    t = P["t"] * P["sp"]
    out = []
    for gx, gy, _a in pos:
        w = (math.sin(gx * 7 + t * 0.9) + math.sin(gx * 13 - t * 1.4 + gy * 3) + math.sin(gx * 3 + t * 0.4)) / 3
        k = (w + 1) / 2
        base = (0, 20 + 60 * k, 60 + 120 * k)
        crest = max(0.0, k - 0.75) * 4 * (0.5 + P["int"])
        out.append(_add(base, (crest * 120, crest * 220, crest * 200)))
    return out


def fx_ripple(n, pos, P, st):
    # shared across all fixtures (one ripple pond for the whole map), stored on the global state
    g = P["shared"].setdefault("ripples", [])
    if P["fi"] == 0:
        if random.random() < 0.03 * P["sp"] * (0.5 + P["int"] * 2):
            g.append([random.random(), random.random(), P["t"], P["pal"](random.random())])
        P["shared"]["ripples"] = [r for r in g if P["t"] - r[2] < 2.5]
        g = P["shared"]["ripples"]
    out = []
    for gx, gy, _a in pos:
        c = (0.0, 0.0, 0.0)
        for rx, ry, t0, col in g:
            age = (P["t"] - t0) * P["sp"]
            d = abs(math.hypot(gx - rx, gy - ry) - age * 0.6)
            c = _add(c, _scale(col, max(0.0, 1 - d * 12) * max(0.0, 1 - age / 2.5)))
        out.append(c)
    return out


def fx_colourwaves(n, pos, P, st):
    t = P["t"] * P["sp"]
    return [P["pal"](gx * (0.5 + P["int"]) + math.sin(t * 0.7 + gy * 3) * 0.2 - t * 0.08) for gx, gy, _a in pos]


EFFECTS = {
    # name: (fn, description, colours used (0 palette-only / 1 / 2), animated)
    "Palette flow": (fx_palette_flow, "The palette scrolling along every light"),
    "Running lights": (fx_running, "Soft waves of light running along"),
    "Theater chase": (fx_theater, "Marquee-style chasing dots"),
    "Larson scanner": (fx_larson, "Knight Rider / Cylon eye sweeping back and forth"),
    "Sinelon": (fx_sinelon, "A dot swinging back and forth with a fading trail"),
    "Juggle": (fx_juggle, "Several coloured dots weaving in and out"),
    "BPM": (fx_bpm, "Palette stripes pulsing to a beat"),
    "Meteor": (fx_meteor, "A meteor with a sparkling, decaying tail"),
    "Fire": (fx_fire, "Flickering flames (heat simulation)"),
    "Candle": (fx_candle, "Gentle candle flicker in colour 1"),
    "Confetti": (fx_confetti, "Random pops of colour that fade away"),
    "Glitter": (fx_glitter, "Rainbow with white glitter sparkles"),
    "Twinklefox": (fx_twinklefox, "Each LED twinkling on its own rhythm"),
    "Fireworks": (fx_fireworks, "Bursts of sparks exploding and fading"),
    "Lightning": (fx_lightning, "Random white lightning strikes"),
    "Police": (fx_police, "Red / blue emergency strobe"),
    "Heartbeat": (fx_heartbeat, "Double pulse like a heartbeat"),
    "Dissolve": (fx_dissolve, "Colour 1 and 2 dissolving into each other"),
    "Bouncing balls": (fx_bouncing, "Balls bouncing with gravity"),
    "Rain": (fx_rain, "Digital rain falling down your case"),
    "Plasma": (fx_plasma, "Psychedelic plasma flowing across the whole case"),
    "Noise": (fx_noise, "Organic, lava-lamp-like palette noise"),
    "Aurora": (fx_aurora, "Northern-lights curtains drifting across"),
    "Pacifica": (fx_pacifica, "Gentle ocean waves with white crests"),
    "Ripple": (fx_ripple, "Raindrop ripples spreading across all fans"),
    "Colour waves": (fx_colourwaves, "Palette waves rolling across the case"),
}

_STATE: dict = {}
_SHARED: dict = {}


def render_fixture(effect: str, fid: str, pos: list, fi: int, nf: int, t: float, c1, c2, speed: float,
                   intensity: float, palname: str) -> list:
    fn = EFFECTS[effect][0]
    n = len(pos)
    if n == 0:
        return []
    st = _STATE.setdefault((effect, fid), {})
    P = {"t": t, "sp": speed, "int": max(0.0, min(1.0, intensity)), "c1": tuple(c1), "c2": tuple(c2),
         "pal": palette_fn(palname, tuple(c1), tuple(c2)), "palname": palname if palname in PALETTES else "Your colours",
         "fi": fi, "nf": nf, "shared": _SHARED}
    return fn(n, pos, P, st)
