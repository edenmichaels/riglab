"""A small Windows window running on its own thread, with its own message loop (ctypes, no extra packages).

Used by the in-game overlay (ovwin.py) and by the device / sleep watcher (devwatch.py). Every call that touches
the window runs on the window's own thread: other threads use call(fn) / post(fn).
"""
from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
from ctypes import wintypes

log = logging.getLogger(__name__)
IS_WIN = sys.platform == "win32"

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM) if IS_WIN else None

WM_DESTROY, WM_CLOSE, WM_QUIT, WM_TIMER = 0x0002, 0x0010, 0x0012, 0x0113
WM_APP = 0x8000
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x8, 0x20, 0x80, 0x80000, 0x08000000
GWL_EXSTYLE = -20
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HANDLE)]


def _setup():
    if not IS_WIN:
        return None, None, None
    u, k, g = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32"), ctypes.WinDLL("gdi32")
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.DefWindowProcW.restype = LRESULT
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.CreateWindowExW.restype = wintypes.HWND
    u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    u.RegisterClassExW.restype = wintypes.ATOM
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    u.SetTimer.restype = ctypes.c_size_t
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    u.GetMessageW.restype = wintypes.BOOL
    u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    u.DispatchMessageW.restype = LRESULT
    u.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    u.LoadCursorW.restype = wintypes.HANDLE
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k.GetModuleHandleW.restype = wintypes.HMODULE
    return u, k, g


user32, kernel32, gdi32 = _setup()


def set_thread_dpi_aware():
    """Real screen pixels on every monitor (100%, 125%, 150%...). Windows 10 1607+; older Windows ignore it."""
    if not IS_WIN:
        return
    try:
        fn = user32.SetThreadDpiAwarenessContext
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_void_p
        fn(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
    except (AttributeError, OSError):
        pass


_seq = [0]


class MsgWindow:
    """handler(win, msg, wparam, lparam) -> int | None (None = Windows' default handling)."""

    def __init__(self, class_name: str, title: str, handler, ex_style: int = 0, style: int = WS_POPUP, on_ready=None):
        # a new window class each time: a restarted window must never reuse an old (freed) message handler
        _seq[0] += 1
        self.class_name, self.title, self.handler = f"{class_name}{_seq[0]}", title, handler
        self.ex_style, self.style, self.on_ready = ex_style, style, on_ready
        self.hwnd = None
        self.tid = None
        self.thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._jobs: queue.Queue = queue.Queue()
        self._proc = None
        self.error: str | None = None
        self.crashed = False

    def start(self, timeout: float = 5.0) -> bool:
        if not IS_WIN:
            return False
        self._ready.clear()
        self.crashed = False
        self.thread = threading.Thread(target=self._main, name=self.class_name, daemon=True)
        self.thread.start()
        self._ready.wait(timeout)
        return bool(self.hwnd)

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive() and self.hwnd)

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_APP + 1:
                while True:
                    try:
                        fn = self._jobs.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        fn()
                    except Exception:  # noqa: BLE001
                        log.exception("%s job", self.class_name)
                return 0
            r = self.handler(self, msg, wp, lp)
            if r is not None:
                return r
        except Exception as e:  # noqa: BLE001 - an exception escaping a window procedure would crash Python
            self.error = f"{type(e).__name__}: {e}"
            log.exception("%s message %#x", self.class_name, msg)
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _main(self):
        try:
            set_thread_dpi_aware()
            self.tid = kernel32.GetCurrentThreadId()
            hinst = kernel32.GetModuleHandleW(None)
            self._proc = WNDPROC(self._wndproc)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p)
            wc.hInstance = hinst
            wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))     # IDC_ARROW
            wc.hbrBackground = None                                           # never paints a background colour
            wc.lpszClassName = self.class_name
            user32.RegisterClassExW(ctypes.byref(wc))                         # fails harmlessly if already registered
            self.hwnd = user32.CreateWindowExW(self.ex_style, self.class_name, self.title, self.style, 0, 0, 1, 1,
                                               None, None, hinst, None)
            if not self.hwnd:
                self.error = f"CreateWindowEx failed ({ctypes.get_last_error()})"
                return
            if self.on_ready:
                self.on_ready(self)
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            log.exception("%s start", self.class_name)
            return
        finally:
            self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            self.crashed = True
            log.exception("%s loop", self.class_name)
        finally:
            self.hwnd = None
            try:
                user32.UnregisterClassW(self.class_name, kernel32.GetModuleHandleW(None))
            except Exception:  # noqa: BLE001
                pass

    def post(self, fn):
        """Run fn() on the window's thread (returns straight away)."""
        if not self.hwnd:
            return False
        self._jobs.put(fn)
        return bool(user32.PostMessageW(self.hwnd, WM_APP + 1, 0, 0))

    def call(self, fn, timeout: float = 3.0):
        """Run fn() on the window's thread and wait for its result."""
        if threading.get_ident() == getattr(self.thread, "ident", None):
            return fn()
        box, done = {}, threading.Event()

        def job():
            try:
                box["r"] = fn()
            except Exception as e:  # noqa: BLE001
                box["e"] = e
            finally:
                done.set()
        if not self.post(job) or not done.wait(timeout):
            return None
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def stop(self):
        """Close the window and end its thread (no leftover windows)."""
        if self.hwnd:
            try:
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            except Exception:  # noqa: BLE001
                pass
        if self.thread:
            self.thread.join(3)
        self.hwnd = None
