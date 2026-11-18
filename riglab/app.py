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
        from .core import overlay as _ov
        cfg.data["overlay"] = _ov.migrate(cfg.data.get("overlay") or {})     # 3.7-3.9 overlay settings -> stats/presets
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
        # in-game overlay (3.12: RigLab's own see-through window, see core/ovwin.py)
        from .core import overlay as _ovm
        from .core.ovcontrol import OverlayController
        self.ovctl = OverlayController(lambda: self.config["overlay"], self.config.save, data=self.api.overlay_data,
                                       look=lambda: (self.config.data.get("ui", {}).get("theme", "dark"),
                                                     self.config.data.get("ui", {}).get("accent", "theme")))
        self.ovwin = None
        self._ov_told = set()         # games we've already warned about exclusive fullscreen
        self._ov_notice = None
        self._ov_repairs = 0
        self._ov_last_error = None
        self._ov_hotkey_ok = True
        self._ov_hold_vks = _ovm.parse_hold(cfg.data["overlay"].get("move_hold", "")) or []
        self._hotkey_tid = None       # thread id of the hotkey listener
        # lighting: start-up log, the watcher that keeps devices found, and Windows' device/sleep messages
        from .core.eventlog import EventLog
        from .core.lightwatch import LightWatch
        self.events = EventLog()
        self.lightwatch = LightWatch(self.light, save=cfg.save, events=self.events, notes=self.api.startup_notes_list,
                                     enabled=lambda: bool(self.config["openrgb"].get("autostart", True)),
                                     quitting=lambda: self._quitting)
        self.devwatch = None
        self.gpu_win = None
        self.gpu_params = {"mode": "bench", "seconds": 30}
        self.gpu_result = None
        self.tray = None
        self._quitting = False
        self.boot_info = None          # set by _boot_rescan: what the after-boot lighting check found

    # ------------------------------------------------------------------ run
    def run(self):
        self.window = webview.create_window(
            APP_NAME, str(WEB / "index.html"), js_api=self.api, width=1380, height=880, min_size=(1100, 700),
            background_color="#0a0c11", text_select=False,
            hidden=self.config["start_minimized"] or "--minimized" in sys.argv or "--weekly-check" in sys.argv)
        self.window.events.closing += self._on_closing
        self._start_tray()
        from .core import instance
        instance.serve(self.quit, self.weekly_check)
        storage = (app_dir() / "webview") if getattr(sys, "frozen", False) else (project_root() / ".webview")
        from .core import webcache
        gone = webcache.clear(storage)          # never show screens left over from an older version (see webcache.py)
        if gone:
            log.info("cleared %d saved web cache folders", len(gone))
        webview.start(self._after_start, private_mode=False, storage_path=str(storage), debug="--debug" in sys.argv)
        self.shutdown()

    def _after_start(self):
        self._log_start()
        if self.config["overlay"]["enabled"]:
            self.apply_overlay()
        self._ov_hotkey_ok = self.overlay_hotkey() or not self.config["overlay"].get("hotkey")
        threading.Thread(target=self._ov_keeper, name="OverlayKeeper", daemon=True).start()
        threading.Thread(target=self._lighting_start, name="Lighting", daemon=True).start()
        threading.Thread(target=self._startup_checks, name="StartupChecks", daemon=True).start()
        threading.Thread(target=self.api.autostart_first_run, name="Autostart", daemon=True).start()
        if "--weekly-check" in sys.argv:          # started by Task Scheduler only to run the check
            threading.Thread(target=lambda: self.weekly_check(quit_after=True), name="WeeklyCheck", daemon=True).start()

    def weekly_check(self, quit_after: bool = False):
        """The weekly scheduled quick check: run it, then show the score as a Windows notification."""
        if quit_after:
            time.sleep(25)                       # let the sensors warm up first
        try:
            r = self.api.health_quick()
            if r and r.get("summary"):
                self.notify("RigLab weekly check", r["summary"])
        except Exception:  # noqa: BLE001
            log.exception("weekly check")
        if quit_after:
            time.sleep(8)                        # leave time for the notification
            self.quit()

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

    def _log_start(self):
        """First lines of the start-up log: how RigLab was started and how long ago Windows started."""
        from .core import boot
        sysd = self.config.data.setdefault("system", {})
        now_boot = boot.boot_time()
        first = boot.first_start_since_boot(sysd.get("last_boot"), now_boot)
        if now_boot is not None:
            sysd["last_boot"] = now_boot
            self.config.save()
        by = "by Start with Windows" if "--minimized" in sys.argv else "by you"
        up = f"Windows started {int((time.time() - now_boot) // 60)} min ago" if now_boot else "Windows start time unknown"
        self.events.add("start", f"RigLab started {by}. {up}" + (" (first start since then)." if first else ".")
                        + f" Start with Windows: {'on' if self.config.data.get('startup', {}).get('with_windows') else 'off or not set'}.")
        self.boot_info = {"first_since_boot": first, "time": time.time()}

    def _lighting_start(self):
        """One-time repair of the user's own OpenRGB settings (RigLab 2.2 disabled a detector there), start
        RigLab's private lighting service + stream, then make sure every remembered device is there (retrying for
        about two minutes) and keep watching for devices plugged in and the PC waking from sleep."""
        L = self.light.L
        if not L.get("migrated_v3"):
            try:
                self.api.light_fix_openrgb()
            except Exception:  # noqa: BLE001
                log.exception("OpenRGB settings repair failed")
            self.config.data["corsair_direct"] = False
            L["migrated_v3"] = True
            self.config.save()
        if not self.config["openrgb"].get("autostart", True):
            self.events.add("scan", "Lighting is turned off in RigLab, so no devices were scanned.")
            return
        self.light.start()
        for _ in range(200):                     # wait (up to ~100 s) for the service's first connect attempt
            if self.light.client or self._quitting or self.light.host.status in ("error", "missing"):
                break
            time.sleep(0.5)
        if not self.light.client:
            self.events.add("error", "The lighting service didn't start: " + (self.light.msg or self.light.host.error or "unknown reason"),
                            level="error")
        try:
            from .core.devwatch import DeviceWatcher
            self.devwatch = DeviceWatcher(
                on_device=lambda vid, name: self.lightwatch.request("device", f"A device was plugged in ({self._vid_name(vid)})."),
                on_wake=lambda: self.lightwatch.request("wake", "The PC woke from sleep."))
            if not self.devwatch.start() and sys.platform == "win32":
                self.events.add("error", "Couldn't listen for devices being plugged in.", level="warn")
        except Exception as e:  # noqa: BLE001
            self.events.add("error", f"Couldn't listen for devices being plugged in: {e}", level="warn")
        self.lightwatch.check("startup")

    @staticmethod
    def _vid_name(vid):
        from .core.lightwatch import LIGHT_VIDS
        return LIGHT_VIDS.get((vid or "").upper(), "USB") + " device"

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
            if self.ovwin:
                self.ovwin.stop()                # no leftover overlay window
            if self.devwatch:
                self.devwatch.stop()
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
            pystray.MenuItem("Edit overlay position", lambda: self.overlay_edit(not self.ovctl.manual_edit),
                             checked=lambda _: self.ovctl.editing),
            pystray.MenuItem("Quit", lambda: self.quit()))
        self.tray = pystray.Icon("RigLab", img, APP_NAME, menu)
        self.tray.run_detached()

    def notify(self, title: str, msg: str):
        if self.tray:
            try:
                self.tray.notify(msg, title)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ overlay (3.12: native see-through window)
    def _ov_should_show(self) -> bool:
        return self.ovctl.should_show()

    def apply_overlay(self):
        """Show/hide, size and place the overlay from the settings. Safe to call any time, from any thread."""
        o = self.config["overlay"]
        if sys.platform != "win32":
            self._sync_overlay_fps()
            return
        if o.get("enabled") and not (self.ovwin and self.ovwin.alive()):
            self._ov_start_window()
        elif self.ovwin:
            self.ovwin.redraw()
        self._sync_overlay_fps()

    def _ov_start_window(self) -> bool:
        from .core import overlay as ov
        from .core.ovwin import NativeOverlay
        from .core import winov
        if self.ovwin:
            self.ovwin.stop()
        self.ovwin = NativeOverlay(self.ovctl, holding=lambda: bool(self._ov_hold_vks) and winov.keys_down(self._ov_hold_vks),
                                   needs_fps=lambda: ov.needs_fps(self.config["overlay"]))
        ok = self.ovwin.start()
        if not ok:
            self._ov_last_error = self.ovwin.error or "the overlay window couldn't be created"
            log.warning("overlay window: %s", self._ov_last_error)
        return ok

    def overlay_edit(self, on: bool) -> dict:
        """'Edit position' (overlay settings or tray): the overlay takes clicks and shows an outline and a drag bar
        until you press Done. Holding the move keys does the same while they're held."""
        self.ovctl.set_edit(bool(on))
        self.apply_overlay()
        o = self.config["overlay"]
        return {"edit": self.ovctl.editing, "x": o.get("x"), "y": o.get("y")}

    def overlay_lock(self, locked: bool) -> dict:
        r = self.overlay_edit(not locked)
        return {"locked": not r["edit"], "x": r["x"], "y": r["y"]}

    def overlay_minimise(self, on: bool) -> dict:
        """Shrink to a small dot (click it to bring the overlay back) - in the same spot."""
        self.ovctl.minimise(bool(on))
        self.apply_overlay()
        return {"minimised": bool(self.config["overlay"].get("minimised"))}

    def overlay_corner(self, corner: str):
        self.ovctl.corner(corner)
        self.apply_overlay()

    def overlay_status(self) -> dict:
        """For the overlay settings: what's going on, in plain words."""
        o = self.config["overlay"]
        st = self.ovctl.status()
        win_err = (self.ovwin.error or (self.ovwin.win.error if self.ovwin and self.ovwin.win else None)) if self.ovwin else None
        return {"enabled": bool(o.get("enabled")), "visible": st["visible"], "hidden_by_key": st["hidden_by_key"],
                "editing": st["editing"], "fullscreen": st["fullscreen"], "app": st["app"], "notice": self._ov_notice,
                "hotkey_ok": self._ov_hotkey_ok, "repairs": self._ov_repairs, "last_error": self._ov_last_error or win_err,
                "running": bool(self.ovwin and self.ovwin.alive()), "minimised": bool(o.get("minimised"))}

    def _ov_keeper(self):
        """One light thread: which kind of window is in front (exclusive fullscreen?) once a second, and bring the
        overlay window back if it ever stops (it restarts itself, at most 5 times in 10 minutes)."""
        restarts = []
        while not self._quitting:
            time.sleep(1.0)
            o = self.config["overlay"]
            try:
                if not o.get("enabled"):
                    if self.ovwin and self.ovwin.alive():
                        self.ovwin.redraw()             # it hides itself
                    continue
                self._ov_fullscreen_tick()
                if sys.platform == "win32" and not (self.ovwin and self.ovwin.alive()):
                    now = time.monotonic()
                    restarts = [t for t in restarts if now - t < 600]
                    if len(restarts) < 5:
                        restarts.append(now)
                        self._ov_repairs += 1
                        log.warning("overlay window stopped - starting it again (%d)", self._ov_repairs)
                        self._ov_start_window()
            except Exception as e:  # noqa: BLE001 - never let the keeper die silently
                self._ov_last_error = f"{type(e).__name__}: {e}"
                log.exception("overlay keeper")

    def _ov_fullscreen_tick(self):
        from .core import overlay as ov
        from .core import winov
        fg = winov.foreground()
        own = self.ovwin.hwnd() if self.ovwin else None
        if fg and fg[0] in (own, winov.find(APP_NAME)):
            return                                            # RigLab itself in front: keep the last answer
        state = ov.classify_fullscreen(winov.notification_state(), fg[1] if fg else None, fg[2] if fg else None, fg[3] if fg else False)
        app = winov.process_name(fg[4]) if fg and state else None
        old = self.ovctl.fullscreen
        self.ovctl.set_fullscreen(state, app)
        msg = ov.exclusive_notice(state, app, self._ov_told)
        if msg:
            self._ov_notice = msg
            self.notify("RigLab overlay can't show", msg)
        if (old == "exclusive") != (state == "exclusive") and self.ovwin:
            self.ovwin.redraw()

    def overlay_toggle_hidden(self):
        """The show/hide hotkey: hides it until pressed again (the setting itself doesn't change)."""
        self.ovctl.toggle_hidden()
        self.apply_overlay()

    def overlay_hotkey(self):
        """(Re)register the show/hide hotkey on its own thread (Windows sends WM_HOTKEY to the thread that registered it)."""
        from .core import overlay as ov
        if sys.platform != "win32":
            return False
        import ctypes
        from ctypes import wintypes
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        if self._hotkey_tid:
            u.PostThreadMessageW(self._hotkey_tid, 0x0012, 0, 0)    # WM_QUIT stops the old listener
            self._hotkey_tid = None
        parsed = ov.parse_hotkey(self.config["overlay"].get("hotkey", ""))
        if not parsed:
            return False
        ok = threading.Event()
        result = {"ok": False}

        def listen():
            self._hotkey_tid = k.GetCurrentThreadId()
            result["ok"] = bool(u.RegisterHotKey(None, 1, parsed[0], parsed[1]))
            ok.set()
            if not result["ok"]:
                log.warning("overlay hotkey %s is already used by another app", self.config["overlay"].get("hotkey"))
                return
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:                           # WM_HOTKEY
                    self.overlay_toggle_hidden()
            u.UnregisterHotKey(None, 1)
        threading.Thread(target=listen, name="OverlayHotkey", daemon=True).start()
        ok.wait(2)
        return result["ok"]

    def _sync_overlay_fps(self):
        """PresentMon runs for the overlay only while the overlay is visible AND shows FPS in any style."""
        from .core import overlay as ov
        from .core import presentmon
        if ov.needs_fps(self.config["overlay"]) and not self._quitting:
            self._fps_retry_at = 0.0
            threading.Thread(target=self.ensure_overlay_fps, name="OverlayFPS", daemon=True).start()
        else:
            presentmon.release("overlay")

    def ensure_overlay_fps(self):
        """(Re)join the shared capture for the overlay; retried at most every 30 s if PresentMon can't run."""
        from .core import overlay as ov
        from .core import presentmon
        if not ov.needs_fps(self.config["overlay"]) or self._quitting:
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
