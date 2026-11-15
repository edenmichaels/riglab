"""In-game overlay: styles, sizes and where the window goes (pure logic, no window code - unit-tested).

Styles ("mode"):
  full        CPU / GPU / RAM rows (+ an FPS row when "Show FPS" is on)
  fps         just the FPS number
  fps_low     FPS + 1% low
  fps_time    FPS + frame time
  fps_detail  FPS + 1% low + frame time + game name
  fps_graph   FPS + a live frame-time graph
"""
from __future__ import annotations

MODES = ("full", "fps", "fps_low", "fps_time", "fps_detail", "fps_graph")
SIZES = {"s": 0.85, "m": 1.0, "l": 1.3, "xl": 1.7}
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
MARGIN = 12
TASKBAR = 48            # keep bottom corners clear of the taskbar

# rough window size per style at text size "m", until the overlay reports its real size
_BASE = {"full": (300, 110), "fps": (110, 56), "fps_low": (150, 70), "fps_time": (150, 70),
         "fps_detail": (230, 92), "fps_graph": (230, 96)}


def norm_mode(mode) -> str:
    return mode if mode in MODES else "full"


def needs_fps(o: dict) -> bool:
    """PresentMon is needed when the overlay is on and shows FPS in any style."""
    if not o.get("enabled"):
        return False
    return norm_mode(o.get("mode")) != "full" or bool(o.get("show_fps"))


def guess_size(o: dict) -> tuple[int, int]:
    mode = norm_mode(o.get("mode"))
    w, h = _BASE[mode]
    if mode == "full" and o.get("show_fps"):
        h += 26
    k = SIZES.get(o.get("size"), 1.0)
    return int(w * k), int(h * k)


def corner_position(corner: str, w: int, h: int, screen: tuple[int, int, int, int]) -> tuple[int, int]:
    """Top-left of the window for a corner preset on a screen (x, y, width, height)."""
    sx, sy, sw, sh = screen
    corner = corner if corner in CORNERS else "top-left"
    x = sx + MARGIN if "left" in corner else sx + sw - w - MARGIN
    y = sy + MARGIN if "top" in corner else sy + sh - h - MARGIN - TASKBAR
    return x, y


def clamp_position(x: int, y: int, w: int, h: int, screens: list[tuple[int, int, int, int]]) -> tuple[int, int]:
    """Keep a dragged overlay fully on a screen. Uses the screen holding most of it; if it's on none
    (a monitor was unplugged), it goes to the nearest screen."""
    if not screens:
        return x, y

    def overlap(s):
        sx, sy, sw, sh = s
        return max(0, min(x + w, sx + sw) - max(x, sx)) * max(0, min(y + h, sy + sh) - max(y, sy))

    def dist(s):
        sx, sy, sw, sh = s
        cx, cy = x + w / 2, y + h / 2
        dx = max(sx - cx, 0, cx - (sx + sw))
        dy = max(sy - cy, 0, cy - (sy + sh))
        return dx * dx + dy * dy
    best = max(screens, key=overlap)
    if overlap(best) == 0:
        best = min(screens, key=dist)
    sx, sy, sw, sh = best
    return int(min(max(x, sx), sx + max(0, sw - w))), int(min(max(y, sy), sy + max(0, sh - h)))


def place(o: dict, w: int, h: int, screens: list[tuple[int, int, int, int]]) -> tuple[int, int]:
    """Where the overlay goes: the spot it was dragged to, else its corner on the main screen."""
    if o.get("x") is not None and o.get("y") is not None:
        return clamp_position(int(o["x"]), int(o["y"]), w, h, screens)
    return corner_position(o.get("corner", "top-left"), w, h, screens[0] if screens else (0, 0, 1920, 1080))
