"""The overlay's brain: what to show, where, whether clicks pass through, and what a click or drag means.

No Windows code here (ovwin.py does the window), so every behaviour is unit-tested: show/hide with the hotkey,
edit mode (Settings switch or holding the move keys), dragging and saving the spot, lock, minimise to a dot and
back, exclusive fullscreen, several monitors and Windows scaling.

Positions are in the screen's real pixels. `screens` are the monitors' usable areas (x, y, w, h) with the
scaling of each (1.0 = 100%, 1.5 = 150%), so the overlay is drawn at the right size on every monitor.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from . import overlay as ov
from . import ovrender


@dataclass
class Show:
    visible: bool
    frame: object = None          # ovrender.Frame
    x: int = 0
    y: int = 0
    clickthrough: bool = True


class OverlayController:
    def __init__(self, get_cfg, save, data=lambda: {}, look=lambda: ("dark", "theme"), clock=time.monotonic):
        self.get_cfg, self.save, self.data, self.look, self.clock = get_cfg, save, data, look, clock
        self.lock = threading.RLock()
        self.hidden_by_key = False
        self.manual_edit = False
        self.holding = False
        self.editing = False
        self.fullscreen: str | None = None
        self.fullscreen_app: str | None = None
        self.screens: list[tuple[int, int, int, int, float]] = [(0, 0, 1920, 1080, 1.0)]
        self.history: list = []
        self.pos: tuple[int, int] | None = None      # where the window is now (top-left)
        self.size: tuple[int, int] = (0, 0)
        self.last: Show | None = None
        self.dragging = False
        self.offset = 0

    # ------------------------------------------------------------------ state
    @property
    def cfg(self) -> dict:
        return self.get_cfg()

    def should_show(self) -> bool:
        return ov.should_be_visible(self.cfg, self.hidden_by_key, self.fullscreen)

    def set_screens(self, screens):
        good = [tuple(s) + ((1.0,) if len(s) == 4 else ()) for s in screens or [] if s and s[2] > 0 and s[3] > 0]
        with self.lock:
            self.screens = good or [(0, 0, 1920, 1080, 1.0)]

    def _areas(self):
        return [s[:4] for s in self.screens]

    def scale_at(self, x: int, y: int, w: int = 1, h: int = 1) -> float:
        """Windows scaling of the monitor the overlay is (mostly) on."""
        best = ov._best_screen(x, y, w, h, self._areas())
        for s in self.screens:
            if tuple(s[:4]) == tuple(best):
                return float(s[4]) if len(s) > 4 and s[4] else 1.0
        return 1.0

    def toggle_hidden(self):
        with self.lock:
            self.hidden_by_key = not self.hidden_by_key
            return self.hidden_by_key

    def set_fullscreen(self, state, app=None):
        with self.lock:
            self.fullscreen, self.fullscreen_app = state, app

    def set_edit(self, on: bool) -> str | None:
        """'Edit position' switch (Settings or tray). Returns 'start' / 'end' / None."""
        with self.lock:
            o = self.cfg
            if on and not o.get("enabled"):
                o["enabled"] = True
                self.save()
            self.manual_edit = bool(on)
            return self._edit_step()

    def set_holding(self, on: bool) -> str | None:
        with self.lock:
            self.holding = bool(on) and bool(self.cfg.get("enabled"))
            return self._edit_step()

    def _edit_step(self):
        editing, ev = ov.edit_step(self.editing, self.manual_edit, self.holding)
        self.editing = editing
        o = self.cfg
        if ev == "start":
            if o.get("minimised"):
                o["minimised"] = False
                self.save()
            o["locked"] = False
        elif ev == "end":
            o["locked"] = True
            self.dragging = False
            if self.pos:
                self._settle(*self.pos)
            self.save()
        return ev

    # ------------------------------------------------------------------ drawing and placing
    def compose(self, data: dict | None = None) -> Show:
        """Called about once a second (twice when it shows FPS). Returns what the window should look like."""
        with self.lock:
            o = self.cfg
            if not self.should_show():
                self.last = Show(False)
                return self.last
            if data is None:
                try:
                    data = self.data() or {}
                except Exception:  # noqa: BLE001 - a broken reading must never take the overlay down
                    data = {}
            fps = data.get("fps") if isinstance(data.get("fps"), dict) else None
            if "graph" in (o.get("stats") or []):
                self.history.append(fps.get("frametime") if fps and fps.get("state") == "ok" else None)
                self.history = self.history[-60:]
            theme, accent = self.look()
            guess = self.pos or ov.place(o, *(self.size if self.size != (0, 0) else ov.guess_size(o)), self._areas())
            dpi = self.scale_at(guess[0], guess[1], *(self.size if self.size != (0, 0) else (100, 40)))
            minimised = bool(o.get("minimised")) and not self.editing
            frame = ovrender.render(o, data, dpi_scale=dpi, editing=self.editing, minimised=minimised,
                                    theme=theme, accent=accent, history=self.history)
            w, h = frame.size
            # while editing, a drag bar sits above the panel: move the window up by that much so the panel itself
            # stays exactly where it was (saved x/y always mean "where the panel's box starts")
            panel = frame.regions.get("panel")
            self.offset = (panel[1] - ovrender.PAD) if (panel and self.editing) else 0
            if self.dragging and self.pos:
                x, y = self.pos                         # Windows is moving it: don't fight the mouse
            elif o.get("x") is not None and o.get("y") is not None:
                x, y = ov.clamp_position(int(o["x"]), int(o["y"]) - self.offset, w, h, self._areas())
            else:
                x, y = ov.place(o, w, h, self._areas())
                y -= self.offset
            self.size, self.pos = (w, h), (x, y)
            self.last = Show(True, frame, x, y, clickthrough=not self.editing and not minimised)
            return self.last

    # ------------------------------------------------------------------ mouse
    def _region(self, lx, ly):
        if not self.last or not self.last.frame:
            return None
        for name in ("min", "done", "dot", "bar", "panel"):
            r = self.last.frame.regions.get(name)
            if r and r[0] <= lx <= r[2] and r[1] <= ly <= r[3]:
                return name
        return None

    def hit(self, lx: int, ly: int) -> str:
        """What the mouse is over, in window pixels: 'button' (min/done/dot: a click), 'drag' (moves the window),
        or 'through' (clicks go to the game)."""
        with self.lock:
            if self.last is None or self.last.clickthrough:
                return "through"
            r = self._region(lx, ly)
            if r in ("min", "done", "dot"):
                return "button"
            if r in ("bar", "panel") and self.editing:
                return "drag"
            return "through"

    def click(self, lx: int, ly: int) -> str | None:
        with self.lock:
            r = self._region(lx, ly)
            o = self.cfg
            if r == "dot" and o.get("minimised"):
                o["minimised"] = False
                self.save()
                return "restore"
            if r == "min" and self.editing:
                o["minimised"] = True
                self.manual_edit = False
                self.holding = False
                self._edit_step()                       # "–" also locks it
                self.save()
                return "minimise"
            if r == "done" and self.editing:
                self.manual_edit = False
                self.holding = False
                self._edit_step()
                return "lock"
            return None

    def minimise(self, on: bool):
        with self.lock:
            o = self.cfg
            if on:
                self.manual_edit = self.holding = False
                self._edit_step()
            o["minimised"] = bool(on)
            self.save()

    def moving(self, x: int, y: int):
        """Windows is dragging the window (WM_MOVING / WM_MOVE)."""
        with self.lock:
            self.dragging = True
            self.pos = (int(x), int(y))

    def moved(self, x: int, y: int):
        """The drag finished (WM_EXITSIZEMOVE): keep it on screen, snap if asked, remember the spot."""
        with self.lock:
            self.dragging = False
            return self._settle(int(x), int(y))

    def _settle(self, x, y):
        o = self.cfg
        w, h = self.size if self.size != (0, 0) else ov.guess_size(o)
        nx, ny = ov.drop_position(o, x, y + self.offset, w, h - self.offset, self._areas())
        self.pos = (nx, ny - self.offset)
        ny = int(ny)
        if (o.get("x"), o.get("y")) != (nx, ny):
            o["x"], o["y"] = nx, ny
            self.save()
        return nx, ny

    def corner(self, name: str):
        with self.lock:
            o = self.cfg
            o["corner"], o["x"], o["y"] = (name if name in ov.CORNERS else "top-left"), None, None
            self.pos = None
            self.save()

    def status(self) -> dict:
        with self.lock:
            return {"visible": self.should_show(), "hidden_by_key": self.hidden_by_key, "editing": self.editing,
                    "fullscreen": self.fullscreen, "app": self.fullscreen_app, "pos": self.pos, "size": self.size}
