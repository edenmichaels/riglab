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
from .core.overlay import guess_size as _ov_guess
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
        self.overlay = None
        self._ov_size = None          # size the overlay page asked for
        self._ov_hidden = False       # hidden with the hotkey (not saved)
        self._ov_lock = threading.RLock()
        self._ov_editing = False      # Edit position on (from Settings/tray, or while the move keys are held)
        self._ov_manual_edit = False
        self._ov_fs = None            # what's in front: exclusive / borderless / windowed
        self._ov_told = set()         # games we've already warned about exclusive fullscreen
        self._ov_notice = None
        self._ov_repairs = 0
        self._ov_last_error = None
        self._ov_hotkey_ok = True
        from .core import overlay as _ovm
        self._ov_hold_vks = _ovm.parse_hold(cfg.data["overlay"].get("move_hold", "")) or []
        self._ov_drag = None          # DragTracker while unlocked
        self._hotkey_tid = None       # thread id of the hotkey listener
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
        self.overlay = webview.create_window(
            "RigLab Overlay", str(WEB / "overlay.html"), js_api=self.api,
            width=_ov_guess(self.config["overlay"])[0], height=_ov_guess(self.config["overlay"])[1],
            frameless=True, on_top=True, transparent=True, easy_drag=False, hidden=True, focus=False)
        self.overlay.events.shown += self._make_clickthrough
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
        self._boot_rescan()

    def _boot_rescan(self):
        """First start since Windows booted: USB RGB devices often appear late, so rescan a few times over about a
        minute and reapply the last effect. Normal reopens skip this."""
        from .core import boot
        sysd = self.config.data.setdefault("system", {})
        now_boot = boot.boot_time()
        first = boot.first_start_since_boot(sysd.get("last_boot"), now_boot)
        if now_boot is not None:
            sysd["last_boot"] = now_boot
            self.config.save()
        self.boot_info = {"first_since_boot": first, "rescan": None, "running": False, "time": time.time()}
        if not first or self.light.paused or not self.config["openrgb"].get("autostart", True):
            return
        log.info("first start since boot: rescanning lighting (expecting %s)", self.light.L.get("known_devices"))
        self.boot_info["running"] = True
        try:
            res = boot.rescan_and_reapply(self.light, quitting=lambda: self._quitting)
        finally:
            self.boot_info["running"] = False
        self.boot_info["rescan"] = res
        if not res.get("reapplied"):
            log.warning("couldn't reapply lighting after boot")
        msg = res.get("notice")
        if msg:
            log.warning(msg)
            self.api.startup_notes_list.append({"kind": "light", "title": "Lighting device not found", "text": msg, "page": "lighting"})

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
            pystray.MenuItem("Edit overlay position", lambda: self.overlay_edit(not self._ov_manual_edit),
                             checked=lambda _: self._ov_editing),
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
    def _screens(self) -> list[tuple[int, int, int, int]]:
        """Usable area of each monitor in Windows' screen pixels (same units as the overlay's position)."""
        from .core import winov
        areas = winov.work_areas()
        if areas:
            return areas
        out = []
        for sc in getattr(webview, "screens", []) or []:
            out.append((int(getattr(sc, "x", 0) or 0), int(getattr(sc, "y", 0) or 0), int(sc.width), int(sc.height)))
        return out or [(0, 0, 1920, 1080)]

    def _ov_dims(self):
        from .core import overlay as ov
        o = self.config["overlay"]
        return (ov.DOT, ov.DOT) if o.get("minimised") else (self._ov_size or ov.guess_size(o))

    def _ov_should_show(self) -> bool:
        from .core import overlay as ov
        return ov.should_be_visible(self.config["overlay"], self._ov_hidden, (self._ov_fs or {}).get("state"))

    def apply_overlay(self):
        """Show/hide, size and place the overlay from the settings. Safe to call any time."""
        from .core import overlay as ov
        from .core import winov
        if not self.overlay:
            return
        o = self.config["overlay"]
        with self._ov_lock:
            if self._ov_should_show():
                w, h = self._ov_dims()
                x, y = ov.place(o, w, h, self._screens())
                try:
                    self.overlay.show()
                except Exception:  # noqa: BLE001
                    log.exception("overlay show")
                hwnd = self._overlay_hwnd()
                winov.show_noactivate(hwnd)
                winov.place(hwnd, x, y, w, h)
                winov.set_clickthrough(hwnd, not self._ov_editing and not o.get("minimised"))
            else:
                try:
                    self.overlay.hide()
                except Exception:  # noqa: BLE001
                    pass
        self._sync_overlay_fps()

    def overlay_fit(self, w: float, h: float, dpr: float | None = None):
        """The overlay page reports the size its content needs (CSS pixels + the screen's scaling)."""
        from .core import overlay as ov
        from .core import winov
        o = self.config["overlay"]
        if o.get("minimised"):
            return
        w, h = ov.window_size(max(20, min(1600, float(w))), max(12, min(900, float(h))), dpr)
        if self._ov_size == (w, h) or not self.overlay:
            return
        self._ov_size = (w, h)
        x, y = ov.place(o, w, h, self._screens())
        winov.place(self._overlay_hwnd(), x, y, w, h)

    def overlay_edit(self, on: bool) -> dict:
        """'Edit position' from Settings or the tray: the overlay takes clicks and shows a drag handle until you
        press Done (or turn it off). Holding the move keys does the same while they're held."""
        o = self.config["overlay"]
        if on and not o["enabled"]:
            o["enabled"] = True
            self.config.save()
            self.apply_overlay()
        self._ov_manual_edit = bool(on)
        self._ov_edit_tick()
        return {"edit": self._ov_editing, "x": o.get("x"), "y": o.get("y")}

    def overlay_lock(self, locked: bool) -> dict:
        """Older name (3.10): unlocked = editing."""
        r = self.overlay_edit(not locked)
        return {"locked": not r["edit"], "x": r["x"], "y": r["y"]}

    def overlay_minimise(self, on: bool) -> dict:
        """Shrink to a small dot (clickable) or bring it back, in the same spot."""
        o = self.config["overlay"]
        if bool(on) == bool(o.get("minimised")):
            return {"minimised": o["minimised"]}
        self._save_overlay_pos()
        o["minimised"] = bool(on)
        if on:
            self._ov_manual_edit = False        # "–" also locks it (a dot can't be dragged; you click it to restore)
        self.config.save()
        self.apply_overlay()
        return {"minimised": o["minimised"]}

    def overlay_track(self) -> dict:
        """3.10's overlay page called this; the keeper thread tracks dragging now."""
        o = self.config["overlay"]
        return {"state": None, "x": o.get("x"), "y": o.get("y")}

    def _save_overlay_pos(self, drop: bool = False):
        from .core import overlay as ov
        from .core import winov
        o = self.config["overlay"]
        r = winov.rect(self._overlay_hwnd())
        if not r:
            return
        x0, y0, w, h = r
        x, y = ov.drop_position(o, x0, y0, w, h, self._screens()) if drop else ov.clamp_position(x0, y0, w, h, self._screens())
        if (x, y) != (x0, y0):
            winov.place(self._overlay_hwnd(), x, y, w, h)
        if (o.get("x"), o.get("y")) != (x, y):
            o["x"], o["y"] = x, y
            self.config.save()
        if self._ov_drag:
            self._ov_drag.last = (x, y)

    def overlay_corner(self, corner: str):
        """Move to a corner (forgets the dragged spot)."""
        o = self.config["overlay"]
        o["corner"], o["x"], o["y"] = corner, None, None
        self.config.save()
        self.apply_overlay()

    def overlay_status(self) -> dict:
        """For the overlay settings panel: what's going on, in plain words."""
        o = self.config["overlay"]
        fs = self._ov_fs or {}
        return {"enabled": bool(o.get("enabled")), "visible": self._ov_should_show(), "hidden_by_key": self._ov_hidden,
                "editing": self._ov_editing, "fullscreen": fs.get("state"), "app": fs.get("app"), "notice": self._ov_notice,
                "hotkey_ok": self._ov_hotkey_ok, "repairs": self._ov_repairs, "last_error": self._ov_last_error}

    # -- the keeper: one light thread (4 checks a second, almost no CPU) that makes the overlay reliable
    def _ov_keeper(self):
        from .core import winov
        n = 0
        while not self._quitting:
            time.sleep(0.25)
            o = self.config["overlay"]
            if not o.get("enabled") or not self.overlay:
                if self._ov_editing:
                    self._ov_manual_edit = False
                    self._ov_edit_tick()
                continue
            n += 1
            try:
                self._ov_edit_tick()
                if n % 4 == 0:
                    self._ov_fullscreen_tick()
                if n % 8 == 0 and self._ov_should_show():
                    hwnd = self._overlay_hwnd()
                    if hwnd and not winov.visible(hwnd):       # something hid it: put it back (and remember we had to)
                        self._ov_repairs += 1
                        log.warning("overlay was hidden by something else - showing it again (%d)", self._ov_repairs)
                        self.apply_overlay()
                    else:
                        winov.keep_on_top(hwnd)
            except Exception as e:  # noqa: BLE001 - never let the keeper die silently
                self._ov_last_error = f"{type(e).__name__}: {e}"
                log.exception("overlay keeper")

    def _ov_edit_tick(self):
        from .core import overlay as ov
        from .core import winov
        o = self.config["overlay"]
        holding = bool(self._ov_hold_vks) and winov.keys_down(self._ov_hold_vks) and o.get("enabled")
        editing, ev = ov.edit_step(self._ov_editing, self._ov_manual_edit, holding)
        hwnd = self._overlay_hwnd()
        if ev == "start":
            self._ov_editing = True
            if o.get("minimised"):
                o["minimised"] = False
                self.config.save()
                self.apply_overlay()
            winov.set_clickthrough(hwnd, False)
            r = winov.rect(hwnd)
            self._ov_drag = ov.DragTracker(r[:2] if r else None)
        elif ev == "end":
            self._ov_editing = False
            self._save_overlay_pos(drop=True)
            self._ov_drag = None
            winov.set_clickthrough(hwnd, not o.get("minimised"))
        elif editing and self._ov_drag is not None:
            r = winov.rect(hwnd)
            if r and self._ov_drag.feed(r[:2]) == "settled":
                self._save_overlay_pos(drop=True)

    def _ov_fullscreen_tick(self):
        from .core import overlay as ov
        from .core import winov
        fg = winov.foreground()
        own = self._overlay_hwnd()
        if fg and fg[0] in (own, winov.find(APP_NAME)):
            return                                            # RigLab itself in front: keep the last answer
        state = ov.classify_fullscreen(winov.notification_state(), fg[1] if fg else None, fg[2] if fg else None, fg[3] if fg else False)
        app = winov.process_name(fg[4]) if fg and state else None
        old = (self._ov_fs or {}).get("state")
        self._ov_fs = {"state": state, "app": app}
        msg = ov.exclusive_notice(state, app, self._ov_told)
        if msg:
            self._ov_notice = msg
            self.notify("RigLab overlay can't show", msg)
        if (old == "exclusive") != (state == "exclusive"):
            self.apply_overlay()

    def overlay_toggle_hidden(self):
        """The show/hide hotkey: hides it until pressed again (the setting itself doesn't change)."""
        self._ov_hidden = not self._ov_hidden
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

    def _overlay_hwnd(self):
        from .core import winov
        return winov.find("RigLab Overlay")

    def _overlay_pos(self):
        from .core import winov
        r = winov.rect(self._overlay_hwnd())
        return r[:2] if r else None

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

    def _make_clickthrough(self):
        """When the overlay window first appears: clicks pass through to the game (unless editing or a dot)."""
        from .core import winov
        o = self.config["overlay"]
        winov.set_clickthrough(self._overlay_hwnd(), not self._ov_editing and not o.get("minimised"))

    def _set_clickthrough(self, on: bool):
        from .core import winov
        winov.set_clickthrough(self._overlay_hwnd(), on)

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
