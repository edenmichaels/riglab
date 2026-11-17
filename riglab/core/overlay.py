"""In-game overlay: which stats it shows, presets, size, where it goes, snapping, the lock and the hotkey
(pure logic, no window code - unit-tested).

Settings (config "overlay"):
  stats       which readings to show, in order (see STATS). None = not chosen yet (older settings) -> migrate()
  preset      minimal | standard | full | custom
  layout      horizontal | vertical
  size        s | m | l | xl         opacity  0..1 (background)
  text_color  theme | white | #rrggbb
  locked      True = clicks pass straight through to the game (can't be dragged)
  minimised   True = shrunk to a small dot (click the dot to bring it back)
  snap        True = when you let go after dragging, it jumps to the nearest corner
  x, y        where it was dragged to (None = use "corner")
  hotkey      e.g. "Ctrl+Shift+O" to show/hide it, "" = none
"""
from __future__ import annotations

STATS = {
    "fps": "FPS", "low1": "1% low", "frametime": "Frame time", "cpu_temp": "CPU temp", "gpu_temp": "GPU temp",
    "cpu_load": "CPU usage", "gpu_load": "GPU usage", "ram": "RAM", "cpu_clock": "CPU clock", "gpu_clock": "GPU clock",
    "graph": "Frame-time graph",
}
FPS_STATS = {"fps", "low1", "frametime", "graph"}
PRESETS = {
    "minimal": ["fps"],
    "standard": ["fps", "cpu_temp", "gpu_temp"],
    "full": ["fps", "low1", "frametime", "cpu_temp", "gpu_temp", "cpu_load", "gpu_load", "ram", "cpu_clock", "gpu_clock"],
}
LAYOUTS = ("horizontal", "vertical")
SIZES = {"s": 0.85, "m": 1.0, "l": 1.3, "xl": 1.7}
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
MARGIN = 12
TASKBAR = 48            # keep bottom corners clear of the taskbar
DOT = 26                # minimised size (px)

# older (3.7.0 - 3.9.0) "mode" styles -> stats
_OLD_MODES = {"fps": ["fps"], "fps_low": ["fps", "low1"], "fps_time": ["fps", "frametime"],
              "fps_detail": ["fps", "low1", "frametime"], "fps_graph": ["fps", "graph"]}
MODES = ("full",) + tuple(_OLD_MODES)        # kept so older code/settings still make sense


def clean_stats(stats) -> list[str]:
    out = []
    for s in stats or []:
        if s in STATS and s not in out:
            out.append(s)
    return out


def preset_of(stats) -> str:
    st = clean_stats(stats)
    for k, v in PRESETS.items():
        if st == v:
            return k
    return "custom"


def migrate(o: dict) -> dict:
    """Bring overlay settings from 3.7.0-3.9.0 up to date without losing what the person chose.
    stats is None when the file was saved before stats existed."""
    o = dict(o or {})
    if o.get("stats") is None:
        mode = o.get("mode") or "full"
        if mode in _OLD_MODES:
            stats = list(_OLD_MODES[mode])
        elif o.get("enabled") or o.get("show_fps"):          # they used the full CPU/GPU/RAM box
            stats = ["cpu_temp", "cpu_load", "gpu_temp", "gpu_load", "ram"]
            if o.get("show_fps"):
                stats = ["fps", "low1", "frametime"] + stats
        else:
            stats = list(PRESETS["minimal"])                 # never used it: start with the simple FPS counter
        o["stats"] = stats
        o.setdefault("layout", "vertical" if len(stats) > 3 else "horizontal")
    o["stats"] = clean_stats(o["stats"]) or list(PRESETS["minimal"])
    o["preset"] = preset_of(o["stats"])
    if o.get("layout") not in LAYOUTS:
        o["layout"] = "horizontal"
    if o.get("size") not in SIZES:
        o["size"] = "m"
    try:
        o["opacity"] = max(0.0, min(1.0, float(o.get("opacity", 0.85))))
    except (TypeError, ValueError):
        o["opacity"] = 0.85
    tc = o.get("text_color") or "theme"
    o["text_color"] = tc if tc in ("theme", "white") or (isinstance(tc, str) and len(tc) == 7 and tc.startswith("#")) else "theme"
    for k, d in (("locked", True), ("minimised", False), ("snap", False)):
        o[k] = bool(o.get(k, d))
    if o.get("corner") not in CORNERS:
        o["corner"] = "top-left"
    o["hotkey"] = o.get("hotkey") or ""
    return o


def apply_preset(o: dict, name: str) -> dict:
    o = dict(o)
    if name in PRESETS:
        o["stats"] = list(PRESETS[name])
        o["preset"] = name
        o["layout"] = "vertical" if name == "full" else "horizontal"
    return o


def norm_mode(mode) -> str:
    return mode if mode in MODES else "full"


def needs_fps(o: dict) -> bool:
    """PresentMon is needed only when the overlay is on and shows an FPS reading."""
    if not o.get("enabled"):
        return False
    stats = o.get("stats")
    if stats is None:                                       # not migrated yet
        stats = migrate(o)["stats"]
    return bool(FPS_STATS & set(stats))


def guess_size(o: dict) -> tuple[int, int]:
    """Rough window size until the overlay page reports its real size."""
    if o.get("minimised"):
        return DOT, DOT
    st = o.get("stats")
    if st is None:
        st = migrate(o)["stats"]
    n = max(1, len([s for s in st if s != "graph"]))
    graph = "graph" in st
    if o.get("layout") == "vertical":
        w, h = 190, 22 + 24 * n + (54 if graph else 0)
    else:
        w, h = 18 + 92 * n + (150 if graph else 0), 56
    k = SIZES.get(o.get("size"), 1.0)
    return int(w * k), int(h * k)


def corner_position(corner: str, w: int, h: int, screen: tuple[int, int, int, int]) -> tuple[int, int]:
    """Top-left of the window for a corner preset on a screen (x, y, width, height)."""
    sx, sy, sw, sh = screen
    corner = corner if corner in CORNERS else "top-left"
    x = sx + MARGIN if "left" in corner else sx + sw - w - MARGIN
    y = sy + MARGIN if "top" in corner else sy + sh - h - MARGIN - TASKBAR
    return x, y


def _best_screen(x, y, w, h, screens):
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
    return best


def clamp_position(x: int, y: int, w: int, h: int, screens: list[tuple[int, int, int, int]]) -> tuple[int, int]:
    """Keep the overlay fully inside a screen's edges. Uses the screen holding most of it; if it's on none
    (a monitor was unplugged), it goes to the nearest screen."""
    if not screens:
        return x, y
    sx, sy, sw, sh = _best_screen(x, y, w, h, screens)
    return int(min(max(x, sx), sx + max(0, sw - w))), int(min(max(y, sy), sy + max(0, sh - h)))


def nearest_corner(x: int, y: int, w: int, h: int, screens) -> tuple[str, tuple[int, int, int, int]]:
    s = _best_screen(x, y, w, h, screens) if screens else (0, 0, 1920, 1080)
    sx, sy, sw, sh = s
    cx, cy = x + w / 2, y + h / 2
    corner = ("top" if cy < sy + sh / 2 else "bottom") + "-" + ("left" if cx < sx + sw / 2 else "right")
    return corner, s


def drop_position(o: dict, x: int, y: int, w: int, h: int, screens) -> tuple[int, int]:
    """Where the overlay ends up when you let go: inside the screen, or in the nearest corner if snapping is on."""
    if o.get("snap") and screens:
        corner, s = nearest_corner(x, y, w, h, screens)
        return corner_position(corner, w, h, s)
    return clamp_position(x, y, w, h, screens)


def place(o: dict, w: int, h: int, screens: list[tuple[int, int, int, int]]) -> tuple[int, int]:
    """Where the overlay goes: the spot it was dragged to, else its corner on the main screen."""
    if o.get("x") is not None and o.get("y") is not None:
        return clamp_position(int(o["x"]), int(o["y"]), w, h, screens)
    return corner_position(o.get("corner", "top-left"), w, h, screens[0] if screens else (0, 0, 1920, 1080))


def clickthrough(o: dict) -> bool:
    """Clicks pass through to the game only when locked and not minimised (the dot must be clickable)."""
    return bool(o.get("locked", True)) and not o.get("minimised")


class DragTracker:
    """The window is dragged by Windows itself, so RigLab only sees where it is now. Feed the position every
    half second: returns "moving" while it changes, then "settled" once when it stops (time to clamp/snap/save)."""

    def __init__(self, pos=None):
        self.last = pos
        self.moving = False

    def feed(self, pos) -> str | None:
        if pos is None:
            return None
        if self.last is not None and tuple(pos) != tuple(self.last):
            self.last, self.moving = pos, True
            return "moving"
        self.last = pos
        if self.moving:
            self.moving = False
            return "settled"
        return None


# ------------------------------------------------------------------ hotkey
MODS = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
NAMED_VK = {"space": 0x20, "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "`": 0xC0, "-": 0xBD, "=": 0xBB}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Shift+O' -> (modifier flags, virtual key) for RegisterHotKey. Needs a modifier unless it's F1-F24,
    so normal typing in games is never caught."""
    if not text or not isinstance(text, str):
        return None
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, None
    for p in parts:
        if p in MODS:
            mods |= MODS[p]
        elif key is None:
            key = p
        else:
            return None
    if key is None:
        return None
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    elif key in NAMED_VK:
        vk = NAMED_VK[key]
    else:
        return None
    if mods == 0 and not (0x70 <= vk <= 0x87):
        return None
    return mods | 0x4000, vk                     # 0x4000 = MOD_NOREPEAT (holding the keys doesn't flicker it)


def hotkey_label(text: str) -> str:
    p = parse_hotkey(text)
    if not p:
        return ""
    return "+".join(w.upper() if len(w) <= 3 and w.lower() not in ("alt", "win") else w[:1].upper() + w[1:].lower()
                    for w in text.replace(" ", "").split("+"))
