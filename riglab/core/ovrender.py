"""Draws the in-game overlay as a picture with real see-through pixels (Pillow, no web page).

3.12 rebuilt the overlay: the old one was a web page in a "transparent" browser window, and Windows doesn't
reliably let a browser window be see-through (that's where the white box came from). Now RigLab draws the
overlay itself into an image whose background pixels are fully transparent, and Windows shows exactly that image
(see ovwin.py). Anything that isn't the overlay's own panel has alpha 0, so a box behind it is impossible.

render(cfg, data, ...) -> Frame(image, regions). Regions are rectangles (x0, y0, x1, y1) in the image's pixels
for the parts you can click while editing: "bar", "min", "done", "panel", "dot". Pure and unit-tested.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .overlay import SIZES

NAMES = {"fps": "FPS", "low1": "1% LOW", "frametime": "FRAME", "cpu_temp": "CPU", "gpu_temp": "GPU", "cpu_load": "CPU USE",
         "gpu_load": "GPU USE", "ram": "RAM", "cpu_clock": "CPU CLK", "gpu_clock": "GPU CLK"}
FALLBACK = {"panel": "#10141c", "panel-2": "#161b26", "line": "#222938", "line-2": "#2c3446", "text": "#e8ebf2",
            "muted": "#8b94a8", "accent": "#36d6ff", "good": "#3ee08f", "warn": "#ffc046", "bad": "#ff5c6c"}
CSS = Path(__file__).resolve().parents[1] / "web" / "app.css"
PAD = 2                     # transparent margin round the drawing (anti-aliased edges)


@dataclass
class Frame:
    image: Image.Image
    regions: dict = field(default_factory=dict)

    @property
    def size(self):
        return self.image.size


# ------------------------------------------------------------------ colours (taken from the app's own themes)
@lru_cache(maxsize=None)
def _css_blocks() -> dict:
    try:
        text = CSS.read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for sel, body in re.findall(r"(:root|\[data-(?:theme|accent)=\"[\w-]+\"\])\s*\{([^}]*)\}", text):
        out.setdefault(sel, {}).update(dict((k, v.strip()) for k, v in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", body)))
    return out


def colours(theme: str = "dark", accent: str = "theme") -> dict:
    blocks = _css_blocks()
    c = dict(FALLBACK)
    c.update({k: v for k, v in blocks.get(":root", {}).items() if k in FALLBACK})
    if theme and theme not in ("dark", "system"):
        c.update({k: v for k, v in blocks.get(f'[data-theme="{theme}"]', {}).items() if k in FALLBACK})
    if accent and accent != "theme":
        a = blocks.get(f'[data-accent="{accent}"]', {}).get("accent")
        if a:
            c["accent"] = a
    return {k: _rgb(v, FALLBACK[k]) for k, v in c.items()}


def _rgb(v: str, fallback: str) -> tuple[int, int, int]:
    m = re.match(r"#([0-9a-f]{6})\b", (v or "").strip(), re.I) or re.match(r"#([0-9a-f]{6})", fallback, re.I)
    n = int(m.group(1), 16)
    return n >> 16 & 255, n >> 8 & 255, n & 255


# ------------------------------------------------------------------ fonts
FONT_FILES = {
    "bold": ["segoeuib.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "semi": ["seguisb.ttf", "segoeui.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
}
FONT_DIRS = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu"),
             Path("/usr/share/fonts/truetype/liberation")]


@lru_cache(maxsize=64)
def font(kind: str, px: int):
    px = max(6, int(round(px)))
    for name in FONT_FILES[kind]:
        for d in FONT_DIRS:
            f = d / name
            if f.exists():
                try:
                    return ImageFont.truetype(str(f), px)
                except OSError:
                    continue
    return ImageFont.load_default(px)


# ------------------------------------------------------------------ values
def _state_temp(t):
    return None if t is None else "bad" if t >= 85 else "warn" if t >= 75 else "good"


def _state_fps(f):
    return None if f is None else "good" if f >= 60 else "warn" if f >= 30 else "bad"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f            # NaN -> None


def value_of(key: str, d: dict) -> tuple[str, str, str | None]:
    """(value text, unit, colour state). Missing readings show a dash, never 'None' or 'nan'."""
    fps = d.get("fps") if isinstance(d.get("fps"), dict) and d["fps"].get("state") == "ok" else None
    dash = "—"
    if key == "fps":
        f = _num(fps.get("fps")) if fps else None
        return (dash if f is None else str(round(f))), "", _state_fps(f)
    if key == "low1":
        f = _num(fps.get("low1")) if fps else None
        return (dash if f is None else str(round(f))), "", _state_fps(f)
    if key == "frametime":
        f = _num(fps.get("frametime")) if fps else None
        return (dash if f is None else f"{f:.1f}"), "ms", None
    v = _num(d.get(key))
    if key in ("cpu_temp", "gpu_temp"):
        return (dash if v is None else str(round(v))), "°C", _state_temp(v)
    if key in ("cpu_load", "gpu_load", "ram"):
        return (dash if v is None else str(round(v))), "%", None
    if key == "cpu_clock":
        return (dash if v is None else f"{v / 1000:.2f}"), "GHz", None
    if key == "gpu_clock":
        return (dash if v is None else str(round(v))), "MHz", None
    return dash, "", None


# ------------------------------------------------------------------ drawing
def scale_of(cfg: dict, dpi_scale: float = 1.0) -> float:
    try:
        d = float(dpi_scale)
    except (TypeError, ValueError):
        d = 1.0
    d = d if 0.5 <= d <= 4 else 1.0
    return SIZES.get(cfg.get("size"), 1.0) * d


def _text_colour(cfg, C):
    tc = cfg.get("text_color") or "theme"
    if tc == "white":
        return (255, 255, 255), (214, 219, 228)
    if isinstance(tc, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", tc):
        c = _rgb(tc, "#ffffff")
        return c, c
    return C["text"], C["muted"]


def render(cfg: dict, data: dict | None, dpi_scale: float = 1.0, editing: bool = False, minimised: bool = False,
           theme: str = "dark", accent: str = "theme", history: list | None = None) -> Frame:
    C = colours(theme, accent)
    k = scale_of(cfg, dpi_scale)
    if minimised:
        return _dot(C, k)
    data = data or {}
    stats = [s for s in (cfg.get("stats") or ["fps"]) if s in NAMES or s == "graph"] or ["fps"]
    vertical = cfg.get("layout") == "vertical"
    try:
        opacity = max(0.0, min(1.0, float(cfg.get("opacity", 0.85))))
    except (TypeError, ValueError):
        opacity = 0.85
    text_c, muted_c = _text_colour(cfg, C)
    plain = cfg.get("fps_color") in ("plain", "white")
    only_fps = all(s in ("fps", "low1", "frametime", "graph") for s in stats)
    fps_ok = isinstance(data.get("fps"), dict) and data["fps"].get("state") == "ok"
    idle = only_fps and not fps_ok                    # nothing is drawing frames: dim dashes (never hide)
    shadow = opacity < 0.25                           # no background: outline the text so it reads over any game

    f_big, f_val, f_unit, f_lab = font("bold", 22 * k), font("bold", 16 * k), font("semi", 10 * k), font("semi", 10 * k)
    items = []                                        # (key, value, unit, colour, value font)
    for s in stats:
        if s == "graph":
            continue
        v, u, st = value_of(s, data)
        col = text_c if (plain or not st) else C[st]
        if idle:
            col = tuple(int(c * 0.55 + m * 0.45) for c, m in zip(col, C["panel"]))
        items.append((s, v, u, col, f_big if (s == "fps" and not vertical) else f_val))
    graph = "graph" in stats
    gap, padx, pady = round(14 * k), round(12 * k), round(6 * k)
    gw, gh = round(160 * k), round(30 * k)

    def tw(f, t):
        return f.getlength(t) if t else 0

    # measure
    asc = max(f.getmetrics()[0] for f in (f_big if any(i[0] == "fps" for i in items) and not vertical else f_val, f_lab))
    if vertical:
        row_h = round(20 * k)
        lab_w = max([tw(f_lab, NAMES[i[0]]) for i in items] or [0])
        val_w = max([tw(i[4], i[1]) + (tw(f_unit, " " + i[2]) if i[2] else 0) for i in items] or [0])
        inner_w = max(lab_w + round(16 * k) + val_w, gw if graph else 0)
        inner_h = row_h * len(items) + ((gh + round(4 * k)) if graph else 0)
    else:
        widths = [tw(i[4], i[1]) + round(5 * k) + (tw(f_unit, i[2]) + round(5 * k) if i[2] else 0) + tw(f_lab, NAMES[i[0]]) for i in items]
        inner_w = sum(widths) + gap * max(0, len(items) - 1) + ((gap + gw) if graph else 0)
        inner_h = max(asc + round(6 * k), gh if graph else 0)
    pw, ph = int(inner_w + 2 * padx), int(inner_h + 2 * pady)
    bar_h = round(24 * k) if editing else 0
    bar_gap = round(4 * k) if editing else 0
    bar_w = 0
    if editing:
        fb = font("bold", 11 * k)
        bar_w = int(round(8 * k) + round(14 * k) + tw(fb, "Drag to move") + round(10 * k) + 2 * (round(8 * k) * 2) + tw(fb, "–") + tw(fb, "Done") + round(14 * k))
    P = max(PAD, round(2 * k) + 1) if editing else PAD      # room for the edit outline, which is drawn on the panel's edge
    W = max(pw, bar_w) + 2 * P
    H = ph + bar_h + bar_gap + 2 * P
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))     # every pixel starts fully see-through
    dr = ImageDraw.Draw(img)
    regions = {}
    y0 = P + bar_h + bar_gap
    panel = (P, y0, P + pw - 1, y0 + ph - 1)
    regions["panel"] = panel
    radius = round(10 * k)
    if not shadow:
        a = int(round(255 * opacity))
        dr.rounded_rectangle(panel, radius, fill=C["panel"] + (a,), outline=C["line"] + (a,), width=max(1, round(k)))
    if editing:
        _dashed_round_rect(dr, panel, radius, C["accent"], max(2, round(2 * k)), round(6 * k))
        regions.update(_bar(dr, C, k, P, P, bar_w, bar_h))

    def text(xy, t, f, fill, anchor="ls"):
        if shadow:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1)):
                dr.text((xy[0] + dx, xy[1] + dy), t, font=f, fill=(0, 0, 0, 220), anchor=anchor)
        dr.text(xy, t, font=f, fill=fill + (255,), anchor=anchor)

    if vertical:
        row_h = round(20 * k)
        y = y0 + pady
        for key, v, u, col, f in items:
            base = y + round(row_h * 0.75)
            text((P + padx, base), NAMES[key], f_lab, muted_c)
            x_right = P + pw - padx
            if u:
                text((x_right, base), u, f_unit, muted_c, anchor="rs")
                x_right -= tw(f_unit, u) + round(3 * k)
            text((x_right, base), v, f, col, anchor="rs")
            y += row_h
        if graph:
            _graph(dr, C, (P + padx, y + round(4 * k), P + padx + gw, y + round(4 * k) + gh), history)
    else:
        base = y0 + pady + asc + round(2 * k)
        x = P + padx
        for key, v, u, col, f in items:
            text((x, base), v, f, col)
            x += tw(f, v) + round(5 * k)
            if u:
                text((x, base), u, f_unit, muted_c)
                x += tw(f_unit, u) + round(5 * k)
            text((x, base), NAMES[key], f_lab, muted_c)
            x += tw(f_lab, NAMES[key]) + gap
        if graph:
            gy = y0 + (ph - gh) // 2
            _graph(dr, C, (int(x), gy, int(x) + gw, gy + gh), history)
    return Frame(img, regions)


def _dot(C, k) -> Frame:
    d = max(14, round(20 * k))
    m = max(3, round(3 * k))
    size = d + 2 * m + 2 * PAD
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    o = PAD + m
    dr.ellipse((o - 2, o - 2, o + d + 1, o + d + 1), fill=C["panel"] + (255,))          # thin dark ring
    dr.ellipse((o, o, o + d - 1, o + d - 1), fill=C["accent"] + (255,))
    return Frame(img, {"dot": (0, 0, size - 1, size - 1)})


def _bar(dr, C, k, x, y, w, h) -> dict:
    fb = font("bold", 11 * k)
    dr.rounded_rectangle((x, y, x + w - 1, y + h - 1), round(7 * k), fill=C["panel"] + (245,), outline=C["accent"] + (255,), width=max(1, round(k)))
    cx, cy = x + round(8 * k), y + h // 2
    for i in range(2):                                   # grip: two columns of dots
        for j in (-1, 0, 1):
            r = max(1, round(1.3 * k))
            px, py = cx + i * round(5 * k), cy + j * round(4 * k)
            dr.ellipse((px - r, py - r, px + r, py + r), fill=C["accent"] + (255,))
    tx = cx + round(14 * k)
    dr.text((tx, cy), "Drag to move", font=fb, fill=C["accent"] + (255,), anchor="lm")
    bx = int(tx + fb.getlength("Drag to move") + round(10 * k))
    out = {"bar": (x, y, x + w - 1, y + h - 1)}
    for name, label in (("min", "–"), ("done", "Done")):
        bw = int(fb.getlength(label) + 2 * round(8 * k))
        r = (bx, y + round(3 * k), bx + bw, y + h - 1 - round(3 * k))
        dr.rounded_rectangle(r, round(5 * k), fill=C["panel-2"] + (255,), outline=C["line-2"] + (255,), width=1)
        dr.text(((r[0] + r[2]) / 2, cy), label, font=fb, fill=C["text"] + (255,), anchor="mm")
        out[name] = r
        bx = r[2] + round(4 * k)
    return out


def _dashed_round_rect(dr, box, radius, colour, width, dash):
    x0, y0, x1, y1 = box
    c = colour + (255,)
    for (ax, ay, bx, by) in ((x0 + radius, y0, x1 - radius, y0), (x0 + radius, y1, x1 - radius, y1),
                             (x0, y0 + radius, x0, y1 - radius), (x1, y0 + radius, x1, y1 - radius)):
        length = max(abs(bx - ax), abs(by - ay))
        steps = max(1, int(length // (2 * dash)))
        for i in range(steps + 1):
            s = i * 2 * dash
            e = min(length, s + dash)
            if s >= length:
                break
            if ay == by:
                dr.line((ax + s, ay, ax + e, ay), fill=c, width=width)
            else:
                dr.line((ax, ay + s, ax, ay + e), fill=c, width=width)
    for (cx, cy, start) in ((x0, y0, 180), (x1 - 2 * radius, y0, 270), (x1 - 2 * radius, y1 - 2 * radius, 0), (x0, y1 - 2 * radius, 90)):
        dr.arc((cx, cy, cx + 2 * radius, cy + 2 * radius), start, start + 90, fill=c, width=width)


def _graph(dr, C, box, history):
    x0, y0, x1, y1 = box
    dr.line((x0, y1, x1, y1), fill=C["line"] + (255,), width=1)
    pts = [p for p in (history or []) if isinstance(p, (int, float))]
    if len(pts) < 2:
        return
    hi = max(pts) * 1.25 or 1
    n = len(history)
    line = []
    for i, p in enumerate(history):
        if not isinstance(p, (int, float)):
            continue
        line.append((x0 + i / max(1, n - 1) * (x1 - x0), y1 - 2 - p / hi * (y1 - y0 - 4)))
    if len(line) > 1:
        dr.line(line, fill=C["accent"] + (255,), width=2, joint="curve")


def premultiplied_bgra(img: Image.Image) -> bytes:
    """The byte layout Windows' UpdateLayeredWindow needs: blue, green, red, alpha, with colours pre-multiplied
    by alpha (a fully transparent pixel is 0,0,0,0)."""
    r, g, b, a = img.convert("RGBa").split()
    return Image.merge("RGBa", (b, g, r, a)).tobytes()


def on_platform_fonts() -> bool:
    return sys.platform == "win32"
