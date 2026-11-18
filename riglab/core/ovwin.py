"""The in-game overlay's window (Windows only), rebuilt in 3.12.

A plain Windows "layered" window that shows a picture with real see-through pixels (UpdateLayeredWindow with
per-pixel alpha). The picture comes from ovrender.py and the decisions from ovcontrol.py. Why this fixes things:

- no white/black box: there is no web page and no window background at all - the window IS the picture, and
  every pixel outside the overlay's panel has alpha 0. Nothing is shown until the first picture is ready, so
  there's no flash when it appears, moves or resizes.
- click-through: WS_EX_TRANSPARENT (clicks go to the game) except while editing or as a dot.
- never takes focus from the game (WS_EX_NOACTIVATE, WM_MOUSEACTIVATE -> MA_NOACTIVATE).
- stays on top: created topmost, and re-asserted every 2 seconds.
- real pixels on every monitor (per-monitor DPI aware), drawn at each monitor's own scaling.
- dragging is done by Windows itself (WM_NCHITTEST -> HTCAPTION) while editing, so it's smooth.
- light: redraws at most twice a second (once a second without FPS) and only sends a new picture when it changed.
"""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

from . import ovrender
from .win32win import (IS_WIN, WM_TIMER, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST,
                       WS_EX_TRANSPARENT, GWL_EXSTYLE, MsgWindow, gdi32, user32)

log = logging.getLogger(__name__)

WM_MOUSEACTIVATE, WM_NCHITTEST, WM_LBUTTONUP, WM_MOVING, WM_EXITSIZEMOVE = 0x21, 0x84, 0x202, 0x216, 0x232
WM_DISPLAYCHANGE, WM_DPICHANGED, WM_SETTINGCHANGE = 0x7E, 0x2E0, 0x1A
HTCLIENT, HTCAPTION, HTTRANSPARENT, MA_NOACTIVATE = 1, 2, -1, 3
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = wintypes.HWND(-1) if IS_WIN else None
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x1, 0x2, 0x10, 0x200
ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 2, 0, 1
TICK_MS = 100
WM_NCLBUTTONDBLCLK, WM_NCRBUTTONUP, WM_CONTEXTMENU = 0xA3, 0xA5, 0x7B


def _types():
    """Proper 64-bit handle types (without these, Windows handles can be cut down to 32 bits)."""
    if not IS_WIN:
        return
    H = wintypes.HANDLE
    user32.GetDC.argtypes, user32.GetDC.restype = [wintypes.HWND], wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p, wintypes.LPARAM]
    gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteObject.argtypes = [H]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), H, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p, wintypes.HDC,
                                           ctypes.c_void_p, wintypes.COLORREF, ctypes.c_void_p, wintypes.DWORD]


_types()


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _signed16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def monitors() -> list[tuple[int, int, int, int, float]]:
    """Each monitor's usable area in real pixels, with its scaling (1.25 = 125%). Main monitor first."""
    if not IS_WIN:
        return []
    out = []
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:
        shcore = None
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rc, _lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcWork
            scale = 1.0
            if shcore is not None:
                dx, dy = wintypes.UINT(), wintypes.UINT()
                try:
                    if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
                        scale = dx.value / 96.0
                except OSError:
                    pass
            item = (r.left, r.top, r.right - r.left, r.bottom - r.top, scale)
            if mi.dwFlags & 1:              # MONITORINFOF_PRIMARY
                out.insert(0, item)
            else:
                out.append(item)
        return 1
    user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    return out


class NativeOverlay:
    """Owns the overlay window. holding() -> True while the move keys are held."""

    def __init__(self, ctrl, holding=lambda: False, needs_fps=lambda: False):
        self.ctrl, self.holding, self.needs_fps = ctrl, holding, needs_fps
        self.win: MsgWindow | None = None
        self._last_key = None
        self._shown = False
        self._n = 0
        self._dirty = True
        self.draws = 0
        self.restarts = 0
        self.error: str | None = None

    # ------------------------------------------------------------------ life cycle
    def start(self) -> bool:
        if not IS_WIN:
            return False
        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
        self.win = MsgWindow("RigLabOverlay", "RigLab Overlay", self._handle, ex_style=ex, on_ready=self._ready)
        self._shown, self._last_key, self._dirty = False, None, True
        ok = self.win.start()
        if not ok:
            self.error = self.win.error
        return ok

    def alive(self) -> bool:
        return bool(self.win and self.win.alive())

    def stop(self):
        if self.win:
            self.win.stop()
        self.win = None

    def redraw(self):
        """Ask for a new picture now (settings changed, hotkey, edit mode...). Safe from any thread."""
        self._dirty = True
        if self.win:
            self.win.post(self._draw)

    def hwnd(self):
        return self.win.hwnd if self.win else None

    # ------------------------------------------------------------------ window thread
    def _ready(self, win):
        self.ctrl.set_screens(monitors())
        user32.SetTimer(win.hwnd, 1, TICK_MS, None)
        self._draw()

    def _handle(self, win, msg, wp, lp):
        if msg == WM_TIMER:
            self._tick()
            return 0
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg in (WM_NCLBUTTONDBLCLK, WM_NCRBUTTONUP, WM_CONTEXTMENU):
            return 0                                     # no maximise on double-click, no window menu
        if msg == WM_NCHITTEST:
            r = wintypes.RECT()
            user32.GetWindowRect(win.hwnd, ctypes.byref(r))
            what = self.ctrl.hit(_signed16(lp) - r.left, _signed16(lp >> 16) - r.top)
            return {"button": HTCLIENT, "drag": HTCAPTION}.get(what, HTTRANSPARENT)
        if msg == WM_LBUTTONUP:
            if self.ctrl.click(_signed16(lp), _signed16(lp >> 16)):
                self._dirty = True
                self._draw()
            return 0
        if msg == WM_MOVING:
            rc = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
            self.ctrl.moving(rc.left, rc.top)
            return None
        if msg == WM_EXITSIZEMOVE:
            r = wintypes.RECT()
            user32.GetWindowRect(win.hwnd, ctypes.byref(r))
            self.ctrl.moved(r.left, r.top)
            self._dirty = True
            self._draw()
            return 0
        if msg in (WM_DISPLAYCHANGE, WM_DPICHANGED, WM_SETTINGCHANGE):
            self.ctrl.set_screens(monitors())       # monitor plugged in/out, scaling changed, taskbar moved
            self._dirty = True
            self._draw()
            return 0
        return None

    def _tick(self):
        self._n += 1
        ev = self.ctrl.set_holding(self.holding())
        every = 5 if self.needs_fps() else 10          # 2 or 1 pictures a second
        if ev or self._dirty or self._n % every == 0:
            self._draw()
        if self._n % 20 == 0 and self._shown:          # every 2 s: back on top (games that make themselves topmost)
            user32.SetWindowPos(self.win.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)

    def _draw(self):
        if not self.win or not self.win.hwnd:
            return
        self._dirty = False
        try:
            show = self.ctrl.compose()
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            log.exception("overlay compose")
            return
        hwnd = self.win.hwnd
        if not show.visible:
            if self._shown:
                user32.ShowWindow(hwnd, SW_HIDE)
                self._shown = False
            return
        self._set_clickthrough(hwnd, show.clickthrough)
        data = ovrender.premultiplied_bgra(show.frame.image)
        w, h = show.frame.size
        key = (hash(data), w, h, show.x, show.y)
        if key != self._last_key or not self._shown:
            self._push(hwnd, data, w, h, None if self.ctrl.dragging else (show.x, show.y))
            self._last_key = key
            self.draws += 1
        if not self._shown:
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)     # only after the first picture is in: no flash
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)
            self._shown = True

    @staticmethod
    def _set_clickthrough(hwnd, on: bool):
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        want = (ex | WS_EX_TRANSPARENT) if on else (ex & ~WS_EX_TRANSPARENT)
        want |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        if want != ex:
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, want)

    @staticmethod
    def _push(hwnd, data: bytes, w: int, h: int, pos):
        """Hand Windows the picture (premultiplied BGRA) - UpdateLayeredWindow with per-pixel alpha."""
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        try:
            if not bmp or not bits.value:
                raise OSError("CreateDIBSection failed")
            ctypes.memmove(bits, data, len(data))
            old = gdi32.SelectObject(mem, bmp)
            size = wintypes.SIZE(w, h)
            src = wintypes.POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            dst = ctypes.byref(wintypes.POINT(*pos)) if pos else None
            if not user32.UpdateLayeredWindow(hwnd, screen, dst, ctypes.byref(size), mem, ctypes.byref(src), 0,
                                              ctypes.byref(blend), ULW_ALPHA):
                log.warning("UpdateLayeredWindow failed (%d)", ctypes.get_last_error())
            gdi32.SelectObject(mem, old)
        finally:
            if bmp:
                gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)


def wait_closed(ov: NativeOverlay, timeout=3.0):
    end = time.time() + timeout
    while ov.alive() and time.time() < end:
        time.sleep(0.05)
    return not ov.alive()
