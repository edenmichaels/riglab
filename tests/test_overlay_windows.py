"""Runs only on Windows (the GitHub check runs on Windows): creates the real overlay window and checks it's
see-through (no box), on top, click-through, editable, and closes cleanly. Also the device/sleep watcher."""
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def _wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def _screen_pixel(x, y):
    """What's really on screen at (x, y), including see-through windows (BitBlt with CAPTUREBLT)."""
    import ctypes
    from ctypes import wintypes
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    u.GetDC.restype = wintypes.HDC
    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    g.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    scr = u.GetDC(None)
    mem = g.CreateCompatibleDC(scr)
    bmp = g.CreateCompatibleBitmap(scr, 1, 1)
    old = g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, 1, 1, scr, x, y, 0x00CC0020 | 0x40000000)
    px = g.GetPixel(mem, 0, 0)
    g.SelectObject(mem, old)
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(None, scr)
    return px


@pytest.fixture
def overlay():
    from riglab.core import overlay as ov
    from riglab.core.ovcontrol import OverlayController
    from riglab.core.ovwin import NativeOverlay
    store = {"o": ov.migrate({"enabled": True, "x": 200, "y": 200})}
    data = {"fps": {"state": "ok", "fps": 144, "low1": 100, "frametime": 6.9}, "cpu_temp": 60}
    c = OverlayController(lambda: store["o"], lambda: None, data=lambda: data)
    w = NativeOverlay(c)
    assert w.start(), w.error
    yield w, c, store
    w.stop()


def test_window_is_layered_topmost_clickthrough_and_never_activates(overlay):
    import ctypes
    from riglab.core import win32win as W
    w, c, _ = overlay
    assert _wait(lambda: w._shown)
    ex = W.user32.GetWindowLongPtrW(w.hwnd(), W.GWL_EXSTYLE)
    for bit in (W.WS_EX_LAYERED, W.WS_EX_TOPMOST, W.WS_EX_TRANSPARENT, W.WS_EX_TOOLWINDOW, W.WS_EX_NOACTIVATE):
        assert ex & bit, hex(bit)
    assert ctypes.windll.user32.IsWindowVisible(w.hwnd())


def test_no_box_behind_the_overlay(overlay):
    w, c, _ = overlay
    assert _wait(lambda: w._shown)
    x, y = c.pos
    corner = (x + 1, y + 1)                          # outside the rounded panel: must show what's underneath
    c.toggle_hidden()
    w.redraw()
    assert _wait(lambda: not w._shown)
    time.sleep(0.3)
    under = _screen_pixel(*corner)
    c.toggle_hidden()
    w.redraw()
    assert _wait(lambda: w._shown)
    time.sleep(0.3)
    assert _screen_pixel(*corner) == under


def test_edit_mode_takes_clicks_then_locks_again(overlay):
    from riglab.core import win32win as W
    w, c, store = overlay
    assert _wait(lambda: w._shown)
    c.set_edit(True)
    w.redraw()
    assert _wait(lambda: not (W.user32.GetWindowLongPtrW(w.hwnd(), W.GWL_EXSTYLE) & W.WS_EX_TRANSPARENT))
    c.set_edit(False)
    w.redraw()
    assert _wait(lambda: W.user32.GetWindowLongPtrW(w.hwnd(), W.GWL_EXSTYLE) & W.WS_EX_TRANSPARENT)
    assert store["o"]["locked"]


def test_stops_cleanly_with_no_leftover_window():
    from riglab.core import overlay as ov
    from riglab.core import winov
    from riglab.core.ovcontrol import OverlayController
    from riglab.core.ovwin import NativeOverlay
    o = ov.migrate({"enabled": True})
    w = NativeOverlay(OverlayController(lambda: o, lambda: None))
    assert w.start()
    assert _wait(lambda: winov.find("RigLab Overlay"))
    w.stop()
    assert _wait(lambda: not winov.find("RigLab Overlay"))


def test_device_watcher_starts_and_stops():
    from riglab.core.devwatch import DeviceWatcher
    d = DeviceWatcher(lambda vid, name: None, lambda: None)
    assert d.start()
    assert d.alive()
    d.stop()
    assert not d.alive()
