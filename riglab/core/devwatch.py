"""Listens for Windows telling apps "a device was plugged in" and "the PC woke from sleep" (Windows only).

A hidden window (never shown) receives WM_DEVICECHANGE for USB and HID devices and WM_POWERBROADCAST.
Lighting hardware is recognised by its USB maker ID (lightwatch.LIGHT_VIDS), so plugging in a USB stick doesn't
make RigLab rescan the lights.
"""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

from .lightwatch import is_lighting_vid, vid_of
from .win32win import IS_WIN, MsgWindow, user32

log = logging.getLogger(__name__)

WM_DEVICECHANGE, WM_POWERBROADCAST = 0x0219, 0x0218
DBT_DEVICEARRIVAL, DBT_DEVTYP_DEVICEINTERFACE = 0x8000, 5
PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 0x7, 0x12
DEVICE_NOTIFY_WINDOW_HANDLE = 0
GUID_HID = "{4D1E55B2-F16F-11CF-88CB-001111000030}"
GUID_USB_DEVICE = "{A5DCBF10-6530-11D2-901F-00C04FB951ED}"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s: str):
        h = s.strip("{}").replace("-", "")
        g = cls(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16))
        for i in range(8):
            g.Data4[i] = int(h[16 + 2 * i:18 + 2 * i], 16)
        return g


class DEV_BROADCAST_DEVICEINTERFACE_W(ctypes.Structure):
    _fields_ = [("dbcc_size", wintypes.DWORD), ("dbcc_devicetype", wintypes.DWORD), ("dbcc_reserved", wintypes.DWORD),
                ("dbcc_classguid", GUID), ("dbcc_name", ctypes.c_wchar * 1)]


class DeviceWatcher:
    def __init__(self, on_device, on_wake, clock=time.monotonic):
        self.on_device, self.on_wake, self.clock = on_device, on_wake, clock
        self.win: MsgWindow | None = None
        self._handles = []
        self._last_wake = 0.0

    def start(self) -> bool:
        if not IS_WIN:
            return False
        self.win = MsgWindow("RigLabDeviceWatch", "RigLab device watcher", self._handle, on_ready=self._ready)
        return self.win.start()

    def stop(self):
        for h in self._handles:
            try:
                user32.UnregisterDeviceNotification(h)
            except Exception:  # noqa: BLE001
                pass
        self._handles = []
        if self.win:
            self.win.stop()

    def alive(self) -> bool:
        return bool(self.win and self.win.alive())

    def _ready(self, win):
        user32.RegisterDeviceNotificationW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        user32.RegisterDeviceNotificationW.restype = wintypes.HANDLE
        for g in (GUID_HID, GUID_USB_DEVICE):
            f = DEV_BROADCAST_DEVICEINTERFACE_W()
            f.dbcc_size = ctypes.sizeof(DEV_BROADCAST_DEVICEINTERFACE_W)
            f.dbcc_devicetype = DBT_DEVTYP_DEVICEINTERFACE
            f.dbcc_classguid = GUID.parse(g)
            h = user32.RegisterDeviceNotificationW(win.hwnd, ctypes.byref(f), DEVICE_NOTIFY_WINDOW_HANDLE)
            if h:
                self._handles.append(h)
            else:
                log.warning("RegisterDeviceNotification failed for %s", g)
        try:                                       # make sure sleep/wake messages reach a hidden window too
            user32.RegisterSuspendResumeNotification.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            user32.RegisterSuspendResumeNotification.restype = wintypes.HANDLE
            user32.RegisterSuspendResumeNotification(win.hwnd, DEVICE_NOTIFY_WINDOW_HANDLE)
        except (AttributeError, OSError):
            pass

    def _handle(self, win, msg, wp, lp):
        if msg == WM_DEVICECHANGE and wp == DBT_DEVICEARRIVAL and lp:
            hdr = ctypes.cast(lp, ctypes.POINTER(DEV_BROADCAST_DEVICEINTERFACE_W)).contents
            if hdr.dbcc_devicetype == DBT_DEVTYP_DEVICEINTERFACE:
                name = ctypes.wstring_at(lp + DEV_BROADCAST_DEVICEINTERFACE_W.dbcc_name.offset)
                vid = vid_of(name)
                if is_lighting_vid(vid):
                    self.on_device(vid, name)
            return 1
        if msg == WM_POWERBROADCAST:
            if wp in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND) and self.clock() - self._last_wake > 20:
                self._last_wake = self.clock()           # Windows sends both: act once
                self.on_wake()
            return 1
        return None
