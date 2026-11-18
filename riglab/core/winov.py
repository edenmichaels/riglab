"""Windows calls for the overlay window. Every position and size here is in the SAME units (Windows' own
screen pixels): GetWindowRect, SetWindowPos and the monitor work areas all agree, whatever the DPI scaling.
(Before 3.11, sizes came from the web page in CSS pixels and screens from pywebview, which don't match at
125-150% scaling - the overlay could be placed or sized wrongly.) Windows only; every call fails safely."""
from __future__ import annotations

import sys

IS_WIN = sys.platform == "win32"
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_NOOWNERZORDER = 0x1, 0x2, 0x10, 0x40, 0x200
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x80000, 0x20, 0x80, 0x08000000, 0x8
LWA_ALPHA = 0x2
SW_SHOWNOACTIVATE = 4

if IS_WIN:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]


def find(title: str):
    if not IS_WIN:
        return None
    return user32.FindWindowW(None, title) or None


def rect(hwnd):
    if not (IS_WIN and hwnd):
        return None
    r = wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return None


def place(hwnd, x: int, y: int, w: int, h: int) -> bool:
    """Move/resize AND put it back on top of everything, without taking focus from the game."""
    if not (IS_WIN and hwnd):
        return False
    return bool(user32.SetWindowPos(hwnd, HWND_TOPMOST, int(x), int(y), int(w), int(h), SWP_NOACTIVATE | SWP_NOOWNERZORDER))


def keep_on_top(hwnd) -> bool:
    """Borderless games often make themselves 'topmost' when they get focus, which pushes other topmost windows
    behind them. Re-asserting every couple of seconds keeps the overlay in front (cheap: no move, no resize)."""
    if not (IS_WIN and hwnd):
        return False
    return bool(user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER))


def visible(hwnd) -> bool:
    return bool(IS_WIN and hwnd and user32.IsWindowVisible(hwnd))


def show_noactivate(hwnd):
    if IS_WIN and hwnd:
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)


def set_clickthrough(hwnd, on: bool) -> bool:
    """Clicks pass through to the game when on. Before 3.11 RigLab added WS_EX_LAYERED here without ever setting
    the layer's opacity - Windows doesn't draw a layered window until that's done, so the overlay could vanish
    the first time it was locked. Now the opacity is set (only if the window wasn't layered already)."""
    if not (IS_WIN and hwnd):
        return False
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    was_layered = bool(ex & WS_EX_LAYERED)
    new = ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED
    new = (new | WS_EX_TRANSPARENT) if on else (new & ~WS_EX_TRANSPARENT)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)
    if not was_layered:
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    return True


def work_areas() -> list[tuple[int, int, int, int]]:
    """Each monitor's usable area (without the taskbar), in screen pixels."""
    if not IS_WIN:
        return []
    out = []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rc, _lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            w = mi.rcWork
            primary = bool(mi.dwFlags & 1)
            area = (w.left, w.top, w.right - w.left, w.bottom - w.top)
            out.insert(0, area) if primary else out.append(area)       # main screen first
        return 1
    try:
        user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    except Exception:  # noqa: BLE001
        return []
    return out


def foreground():
    """(hwnd, window rect, its monitor's full rect, is it the desktop/taskbar, process id)."""
    if not IS_WIN:
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    r = rect(hwnd)
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, cls, 64)
    shell = cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
    mon = None
    hm = user32.MonitorFromWindow(hwnd, 2)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if hm and user32.GetMonitorInfoW(hm, ctypes.byref(mi)):
        m = mi.rcMonitor
        mon = (m.left, m.top, m.right - m.left, m.bottom - m.top)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd, r, mon, shell, pid.value


def notification_state() -> int | None:
    """SHQueryUserNotificationState: 3 = an exclusive-fullscreen Direct3D game is running."""
    if not IS_WIN:
        return None
    st = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(st)) == 0:
            return st.value
    except Exception:  # noqa: BLE001
        pass
    return None


def keys_down(vks: list[int]) -> bool:
    if not (IS_WIN and vks):
        return False
    return all(user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks)


def process_name(pid: int) -> str | None:
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:  # noqa: BLE001
        return None
