"""App shell: desktop window (pywebview + Edge WebView2), tray icon, overlay, GPU test window."""
from __future__ import annotations

import logging
import sys
import threading
import time

import webview

from .api import Api
from .core.config import APP_NAME, Config, app_dir, project_root
from .core.fans import FanCurveEngine
from .core.hw import SensorHub
from .core.monitor import Alerts, CsvLogger
from .core.lighting import LightingEngine

log = logging.getLogger(__name__)
WEB = project_root() / "riglab" / "web"


def make_icon(size: int = 64):
    """RigLab logo (tray icon + RigLab.ico for the exe)."""
    from PIL import Image, ImageDraw
    k = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4 * k, 4 * k, 60 * k, 60 * k), 14 * k, fill=(20, 24, 34, 255), outline=(54, 214, 255, 255),
                        width=max(1, round(4 * k)))
    d.polygon([(32 * k, 14 * k), (50 * k, 32 * k), (32 * k, 50 * k), (14 * k, 32 * k)], fill=(54, 214, 255, 255))
    return img


class App:
    def __init__(self):
        self.config = cfg = Config()
        self.hub = SensorHub(cfg["poll_interval_ms"] / 1000, cfg["history_seconds"])
        self.hub.liquid.enabled = cfg["liquidctl"].get("enabled", True)
        self.hub.liquid.excluded = set(cfg["liquidctl"].get("exclude", []))
        self.hub.start()
        self.light = LightingEngine(cfg, self.hub)
        self.fans = FanCurveEngine(self.hub, cfg)
        self.fans.enabled = bool(cfg["fan_curves"])          # resume saved curves
        self.alerts = Alerts(self.hub, cfg, self.notify)
        self.csv_logger = CsvLogger(self.hub, cfg)
        self.api = Api(self)
        self.window = None
        self.overlay = None
        self.gpu_win = None
        self.gpu_params = {"mode": "bench", "seconds": 30}
        self.gpu_result = None
        self.tray = None
        self._quitting = False

    # ------------------------------------------------------------------ run
    def run(self):
        self.window = webview.create_window(
            APP_NAME, str(WEB / "index.html"), js_api=self.api, width=1380, height=880, min_size=(1100, 700),
            background_color="#0a0c11", text_select=False, hidden=self.config["start_minimized"] or "--minimized" in sys.argv)
        self.window.events.closing += self._on_closing
        self.overlay = webview.create_window(
            "RigLab Overlay", str(WEB / "overlay.html"), js_api=self.api, width=300,
            height=136 if self.config["overlay"].get("show_fps") else 110,
            frameless=True, on_top=True, transparent=True, easy_drag=False, hidden=True, focus=False)
        self.overlay.events.shown += self._make_clickthrough
        self._start_tray()
        from .core import instance
        instance.serve(self.quit)
        webview.start(self._after_start, private_mode=False, storage_path=str((app_dir() / "webview") if getattr(sys, "frozen", False) else (project_root() / ".webview")),
                      debug="--debug" in sys.argv)
        self.shutdown()

    def _after_start(self):
        if self.config["overlay"]["enabled"]:
            self.apply_overlay()
        threading.Thread(target=self._lighting_start, name="Lighting", daemon=True).start()
        threading.Thread(target=self._startup_checks, name="StartupChecks", daemon=True).start()

    def _startup_checks(self):
        """Did the PC crash during a test or since last time? Did BIOS settings change?"""
        from .core import crashes, oc
        notes = self.api.startup_notes_list
        try:
            run = oc.check_crash_during_test()
            if run:
                notes.append({"kind": "bad", "text": f"Your PC crashed or restarted during the {run['kind']} "
                              "validation test - that step is marked as failed. Undo the last change."})
            from .core import gputune
            msg = gputune.startup_safety(self.api._gpu)
            if msg:
                notes.append({"kind": "bad", "text": msg, "page": "overclock"})
            changes = oc.boot_snapshot(oc.platform_profile(self.api.inventory(), []))
            for ch in changes:
                notes.append({"kind": "info", "text": "Detected: " + ch})
            data = self.api.crashes_scan(14)
            for inc in crashes.new_since_last_run(data["incidents"]):
                notes.append({"kind": "bad", "text": f"Crash detected: {inc['title']}", "page": "crashes"})
                self.notify("RigLab: crash detected", inc["title"])
        except Exception:  # noqa: BLE001
            log.exception("startup checks failed")

    def _lighting_start(self):
        """One-time repair of the user's own OpenRGB settings (RigLab 2.2 disabled a detector there),
        then start RigLab's private lighting service + stream."""
        L = self.light.L
        if not L.get("migrated_v3"):
            try:
                self.api.light_fix_openrgb()
            except Exception:  # noqa: BLE001
                log.exception("OpenRGB settings repair failed")
            self.config.data["corsair_direct"] = False
            L["migrated_v3"] = True
            self.config.save()
        if self.config["openrgb"].get("autostart", True):
            self.light.start()

    # ------------------------------------------------------------------ window events
    def _on_closing(self):
        if self._quitting or not self.config["minimize_to_tray"] or self.tray is None:
            self._quitting = True
            for w in list(webview.windows):
                if w is not self.window:
                    try:
                        w.destroy()
                    except Exception:  # noqa: BLE001
                        pass
            return True
        self.window.hide()
        if not getattr(self, "_told", False):
            self._told = True
            self.notify(APP_NAME, "Still running in the tray - right-click the icon to quit.")
        return False   # cancel the close

    def show(self):
        self.window.show()
        self.window.restore()

    def quit(self):
        self._quitting = True
        self.window.destroy()

    def shutdown(self):
        self._quitting = True
        if self.api._stress.running:
            self.api._stress.stop("app closed")
        self.fans.release_all()     # fans back to BIOS / hub defaults
        try:
            from .core import presentmon
            presentmon.release_all()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.api._gpu.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.light.stop(keep_service=False)
        except Exception:  # noqa: BLE001
            pass
        self.csv_logger.stop()
        self.config.save()
        self.hub.stop()
        if self.tray:
            self.tray.stop()

    def restart_as_admin(self):
        from main import relaunch_as_admin
        if relaunch_as_admin():
            self._quitting = True
            threading.Timer(0.5, self.window.destroy).start()

    # ------------------------------------------------------------------ tray + notifications
    def _start_tray(self):
        try:
            import pystray
            import PIL  # noqa: F401
        except ImportError:
            log.warning("pystray/Pillow missing - no tray icon")
            return
        img = make_icon(64)
        menu = pystray.Menu(
            pystray.MenuItem("Open RigLab", lambda: self.show(), default=True),
            pystray.MenuItem("Overlay", lambda: self.toggle_overlay(),
                             checked=lambda _: self.config["overlay"]["enabled"]),
            pystray.MenuItem("Quit", lambda: self.quit()))
        self.tray = pystray.Icon("RigLab", img, APP_NAME, menu)
        self.tray.run_detached()

    def notify(self, title: str, msg: str):
        if self.tray:
            try:
                self.tray.notify(msg, title)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ overlay
    def apply_overlay(self):
        if not self.overlay:
            return
        o = self.config["overlay"]
        fps = bool(o.get("show_fps"))
        if o["enabled"]:
            try:
                scr = webview.screens[0]
                w, h, m = 300, (136 if fps else 110), 12
                self.overlay.resize(w, h)
                x = m if "left" in o["corner"] else scr.width - w - m
                y = m if "top" in o["corner"] else scr.height - h - m - 48
                self.overlay.move(x, y)
            except Exception:  # noqa: BLE001
                pass
            self.overlay.show()
        else:
            self.overlay.hide()
        self._sync_overlay_fps()

    def _sync_overlay_fps(self):
        """PresentMon runs for the overlay only while the overlay is visible AND Show FPS is on."""
        from .core import presentmon
        o = self.config["overlay"]
        if o["enabled"] and o.get("show_fps") and not self._quitting:
            self._fps_retry_at = 0.0
            threading.Thread(target=self.ensure_overlay_fps, name="OverlayFPS", daemon=True).start()
        else:
            presentmon.release("overlay")

    def ensure_overlay_fps(self):
        """(Re)join the shared capture for the overlay; retried at most every 30 s if PresentMon can't run."""
        from .core import presentmon
        o = self.config["overlay"]
        if not (o["enabled"] and o.get("show_fps")) or self._quitting:
            return None
        cap = presentmon.shared()
        if cap and "overlay" in presentmon.holders():
            return cap
        if time.monotonic() < getattr(self, "_fps_retry_at", 0.0):
            return None
        self._fps_retry_at = time.monotonic() + 30
        presentmon.release("overlay")                 # drop a dead capture before trying again
        return presentmon.acquire("overlay")

    def toggle_overlay(self):
        self.config["overlay"]["enabled"] = not self.config["overlay"]["enabled"]
        self.config.save()
        self.apply_overlay()

    def _make_clickthrough(self):
        """Let mouse clicks pass through the overlay to the game underneath."""
        if sys.platform != "win32":
            return
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, "RigLab Overlay")
        if hwnd:
            GWL_EXSTYLE, LAYERED, TRANSPARENT, TOOLWINDOW, NOACTIVATE = -20, 0x80000, 0x20, 0x80, 0x08000000
            style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | LAYERED | TRANSPARENT | TOOLWINDOW | NOACTIVATE)

    def pick_file(self, label: str) -> str | None:
        kind = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        res = self.window.create_file_dialog(kind, allow_multiple=False, file_types=(label,))
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else res

    # ------------------------------------------------------------------ GPU test window
    def open_gpu_window(self, mode: str, seconds: int):
        self.close_gpu_window()
        self.gpu_params = {"mode": mode, "seconds": seconds}
        self.gpu_result = None
        self.gpu_win = webview.create_window(
            "RigLab GPU " + ("benchmark" if mode == "bench" else "stress test"), str(WEB / "gpu.html"),
            js_api=self.api, width=1280, height=720, background_color="#000000")
        win = self.gpu_win

        def closed():
            if self.gpu_win is win:
                self.gpu_win = None
            if mode == "bench" and self.gpu_result is None:
                self.gpu_result = {"error": "Cancelled"}
        win.events.closed += closed

    def close_gpu_window(self):
        w, self.gpu_win = self.gpu_win, None
        if w:
            try:
                w.destroy()
            except Exception:  # noqa: BLE001
                pass
