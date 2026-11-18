"""Everything the HTML interface can call, as `pywebview.api.<method>(...)` in JavaScript.

Rules: return plain JSON types; never block for long (slow jobs run on threads and are polled).
Attributes start with "_" so pywebview doesn't expose internals to the page.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict

from datetime import datetime, timezone

from .core import bench, crashes, diagnostics, explain, health, healthcheck, lhm_setup, netspeed, oc, pcinfo, presets, report, schedule, storage, sysinfo, tweaks
from .core.changes import ChangeLog
from .core.config import APP_VERSION, app_dir
from .core.fans import PRESETS
from .core import fx, gpuresults, gpusetup, gputune, ledmap, overlay, presentmon
from .core.lighting import ORDERS, PORT
from .core.rgb import CORSAIR_LED_COUNTS, EFFECTS
from .core.stress import StressTest

log = logging.getLogger(__name__)


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


class Api:
    def __init__(self, app):
        self._app = app
        self._hub = app.hub
        self._cfg = app.config
        self._light = app.light
        self._gpu = gputune.GpuTuner(app.hub)
        self._gpurun = gputune.RunRecorder(self._gpu, app)
        self._gpufix = gpusetup.Fixer()
        self._fans = app.fans
        self._bench = {"running": False, "msg": "", "progress": 0.0, "results": [], "error": None, "best": {}}
        self._stress = StressTest(self._hub)
        self._inventory_cache = None
        self._startup = []
        self._tweaks = {t.id: t for t in tweaks.all_tweaks()}
        self._lhm_installer = lhm_setup.Installer()
        self._validation = None
        self._dumps = crashes.DumpAnalyzer()
        self._crash_cache = None
        self._changes = ChangeLog()
        self._health = health.HealthStore()
        self._job = None
        self._big = None              # largest-files scan
        self._net = None              # internet speed test job
        self._net_hist = netspeed.History()
        self.startup_notes_list = []

    # ------------------------------------------------------------------ general
    def info(self):
        return {"version": APP_VERSION, "admin": tweaks.is_admin(), "platform": sys.platform,
                "status": dict(self._hub.status), "demo": False, "ui": self._cfg.data.get("ui", {}),
                "view": self._cfg.data.get("ui", {}).get("view", "simple"), "lights": explain.lights(self._cfg.data.get("alerts"))}

    def ui_set(self, values):
        """Appearance + start page (saved immediately, no Save button needed). Theme, colour, text size and
        animation changes go in Change history (clicking through several themes = one entry, one Undo)."""
        ui = self._cfg.data.setdefault("ui", {})
        new = ui_values(values)
        watched = {k: v for k, v in new.items() if k in APPEARANCE_KEYS and ui.get(k) != v}
        before = {k: ui.get(k) for k in watched}
        ui.update(new)
        self._cfg.save()
        if watched and not (values or {}).get("_undo"):
            self._log("appearance", "Look changed: " + ", ".join(APPEARANCE_KEYS[k] for k in watched), before=before, after=watched, merge="appearance")
        return ui

    def snapshot(self):
        h = self._hub
        snap = h.latest
        sensors = [{"id": s.id, "hw": s.hardware, "type": s.hw_type, "kind": s.kind, "name": s.name,
                    "value": _r(s.value, 2), "min": _r(s.min, 2), "max": _r(s.max, 2), "unit": s.unit,
                    "fmt": s.fmt(), "fmin": s.fmt(s.min) if s.min is not None else "",
                    "fmax": s.fmt(s.max) if s.max is not None else "", "ctrl": s.controllable}
                   for s in snap.sensors.values()]

        def v(sensor):
            return _r(sensor.value) if sensor is not None and sensor.value is not None else None

        def sid(sensor):
            return sensor.id if sensor is not None else None

        g = snap.sensors.get
        picks = {"cpu_temp": h.cpu_temp(), "cpu_load": h.cpu_load(), "cpu_power": h.cpu_power(),
                 "gpu_temp": h.gpu_temp(), "gpu_load": h.gpu_load(), "gpu_power": h.gpu_power(),
                 "ram_load": h.ram_load()}
        summary = {k: v(s) for k, s in picks.items()}
        summary["ids"] = {k: sid(s) for k, s in picks.items()}
        summary["cpu_clock"] = _r(h.cpu_clock(), 0)
        for key, id_ in (("ram_used", "/ps/ram/used"), ("ram_avail", "/ps/ram/avail"), ("disk_r", "/ps/disk/read"),
                         ("disk_w", "/ps/disk/write"), ("net_d", "/ps/net/down"), ("net_u", "/ps/net/up")):
            summary[key] = v(g(id_))
        return {"t": snap.t, "sensors": sensors, "summary": summary, "status": dict(h.status)}

    def pc_status(self):
        """Extra readings for the traffic lights: free space on the Windows drive, and crashes (only if the
        Crash Center has already looked in the last hour - scanning takes too long to do every few seconds)."""
        out = {"disk_free_pct": None, "disk_free": None, "crashes": None}
        try:
            import shutil
            u = shutil.disk_usage(os.environ.get("SYSTEMDRIVE", "C:") + "\\" if sys.platform == "win32" else "/")
            out["disk_free_pct"], out["disk_free"] = explain.free_pct(u.total, u.free), u.free
        except OSError:
            pass
        c = self._crash_cache
        if c and c.get("days", 30) >= 30 and time.time() - c.get("scanned", 0) < 3600:
            out["crashes"] = explain.serious_crashes(c.get("incidents"))
        return out

    def series(self, ids):
        out = {}
        now = time.time()
        for i in ids or []:
            if i:
                out[i] = [[round(t - now, 1), round(val, 2)] for t, val in self._hub.series(i)]
        return out

    # ------------------------------------------------------------------ hardware
    def inventory(self, refresh=False):
        if self._inventory_cache is None or refresh:
            self._inventory_cache = {"sections": sysinfo.collect(), "drives": sysinfo.drive_health()}
        return self._inventory_cache

    def export_report(self):
        inv = self.inventory()
        path = report.build(inv["sections"], self._hub, inv["drives"])
        _open_path(path)
        return str(path)

    # ------------------------------------------------------------------ health check
    def diagnostics(self):
        return diagnostics.check(self._hub, self._light)

    def fix(self, action):
        res = self._fix(action)
        self._log("fix", "Fix it: " + _FIX_NAMES.get(action, action.replace("_", " ")), undo=False, source="fix",
                  detail=str(res)[:200])
        return res

    def _fix(self, action):
        if action == "redownload_lhm":
            return "started" if self.lhm_install(False) else "Already running"
        if action == "connect_openrgb":
            self.light_connect()
            return "Starting the lighting service - see the Lighting page"
        res = diagnostics.fix(action, self._hub)
        if res == "restart_admin":
            self._app.restart_as_admin()
            return "Restarting…"
        return res

    # ------------------------------------------------------------------ sensor library install
    def lhm_install(self, from_zip=False):
        zip_path = None
        if from_zip:
            zip_path = self._app.pick_file("Zip files (*.zip)")
            if not zip_path:
                return False
        hub = self._hub

        def before():
            if hub.lhm in hub.active:
                hub.active.remove(hub.lhm)
            hub.lhm.stop()
            hub.status[hub.lhm.name] = "updating"

        return self._lhm_installer.start(zip_path, before, hub.start_lhm)

    def lhm_status(self):
        st = dict(self._lhm_installer.state)
        st["log"] = st["log"][-40:]
        st["lhm"] = self._hub.status.get("LibreHardwareMonitor", "")
        st["installed"] = lhm_setup.installed_info()
        st["trace"] = self._hub.lhm.info.get("trace") if self._hub.lhm.info else None
        return st

    # ------------------------------------------------------------------ benchmark
    def bench_start(self, opts):
        b = self._bench
        if b["running"]:
            return False
        b.update(running=True, msg="Starting…", progress=0.0, results=[], error=None)
        b["best"] = {}

        def prog(m, p):
            b["msg"], b["progress"] = m, p

        def job():
            try:
                res = []
                if opts.get("cpu"):
                    res += bench.bench_cpu(lambda m, p: prog(m, p * 0.5))
                if opts.get("memory"):
                    res += bench.bench_memory(lambda m, p: prog(m, 0.5 + p * 0.15))
                if opts.get("disk"):
                    res += bench.bench_disk(lambda m, p: prog(m, 0.65 + p * 0.35), folder=opts.get("folder") or None)
                b["results"] = [asdict(r) for r in res]
                b["msg"], b["progress"] = ("Waiting for GPU test…" if opts.get("gpu") else "Done"), 1.0
            except Exception as e:  # noqa: BLE001
                log.exception("benchmark failed")
                b["error"] = str(e)
            finally:
                b["running"] = False
        threading.Thread(target=job, daemon=True).start()
        return True

    def bench_status(self):
        return self._bench

    def bench_finish(self, gpu_result=None):
        """Called by the page after CPU/disk (and optional GPU) are done. Saves history, returns table."""
        results = [bench.BenchResult(**r) for r in self._bench["results"]]
        if gpu_result and "score" in gpu_result:
            results.append(bench.BenchResult("GPU 3D render", round(gpu_result["score"]), "pts", {
                "Avg FPS": round(gpu_result["avg_fps"], 1), "1% low FPS": round(gpu_result["low_fps"], 1),
                "Resolution": gpu_result.get("resolution", "")}))
        rows = []
        for r in results:
            best = bench.previous_best(r.name)
            rows.append({**asdict(r), "best": best,
                         "change": None if not best else round((r.score - best) / best * 100, 1)})
        if results:
            bench.save_run(results)
        return rows

    def bench_history(self):
        return bench.load_history()[-20:]

    def drives(self):
        import psutil
        return [p.mountpoint for p in psutil.disk_partitions() if p.fstype and "cdrom" not in p.opts]

    # ------------------------------------------------------------------ GPU live tuning + performance runs
    def gpu_tune_state(self):
        return self._gpu.state()

    def gpu_setup_check(self, online=True):
        return gpusetup.check(self._gpu, online)

    def gpu_setup_fix(self, action, data=None):
        r = self._gpufix.run(action, data)
        if not (isinstance(r, dict) and r.get("error")):
            self._log("gpu_setup", "Graphics card setup: " + action.replace("_", " "), undo=False, source="fix", risk="Medium")
        return r

    def gpu_setup_job(self):
        return self._gpufix.status()

    def gpu_select(self, index):
        self._gpu.select(index)
        return self._gpu.state()

    def gpu_tune_apply(self, values):
        res = self._gpu.apply({k: v for k, v in values.items()})
        good = [k for k, v in (res or {}).items() if v == "ok"]
        if good:
            self._log("gpu_tune", "Applied graphics card tuning (" + ", ".join(good) + ")", before="stock",
                      after={k: values.get(k) for k in good}, risk="High")
        return {"result": res, "state": self._gpu.state()}

    def gpu_tune_reset(self):
        ok = self._gpu.reset()
        self._log("gpu_reset", "Put the graphics card back to normal settings", undo=False, ok=bool(ok), risk="None")
        return {"ok": ok, "state": self._gpu.state()}

    def gpu_tune_confirm(self):
        self._gpu.confirm()
        return True

    def gpu_metrics(self):
        return self._gpu.metrics()

    def gpu_benchmarks(self):
        return gputune.find_benchmarks(self._cfg.data.get("gpu_bench_extra", []))

    def gpu_bench_add(self):
        path = self._app.pick_file("Benchmark or game (*.exe;*.bat)")
        if path:
            extra = self._cfg.data.setdefault("gpu_bench_extra", [])
            if path not in extra:
                extra.append(path)
                self._cfg.save()
        return self.gpu_benchmarks()

    def gpu_run_start(self, source="builtin", exe=None, seconds=60, label="Run"):
        return self._gpurun.start(source, exe, int(seconds or 0), label)

    def gpu_run_status(self):
        return self._gpurun.status()

    def gpu_run_stop(self, score=None):
        self._gpurun.stop(score)
        return True

    def overlay_config(self):
        """What the overlay page should draw (re-read every second, so Settings changes show up live)."""
        o = self._cfg["overlay"]
        ui = self._cfg.data.get("ui", {})
        return {"stats": list(o.get("stats") or ["fps"]), "layout": o.get("layout", "horizontal"), "size": o.get("size", "m"),
                "opacity": float(o.get("opacity", 0.85)), "text_color": o.get("text_color", "theme"), "fps_color": o.get("fps_color", "auto"),
                "locked": not self._app._ov_editing, "minimised": bool(o.get("minimised")), "theme": ui.get("theme", "dark"),
                "edit": self._app._ov_editing, "editing": self._app._ov_editing, "hotkey": overlay.hotkey_label(o.get("hotkey", "")),
                "move_hold": o.get("move_hold", ""), "visible": self._app._ov_should_show()}

    def overlay_data(self):
        """Just the readings the overlay shows (much lighter than snapshot)."""
        h = self._hub
        val = lambda s: _r(s.value) if s is not None and s.value is not None else None  # noqa: E731
        out = {"cpu_temp": val(h.cpu_temp()), "gpu_temp": val(h.gpu_temp()), "cpu_load": val(h.cpu_load()),
               "gpu_load": val(h.gpu_load()), "ram": val(h.ram_load()), "cpu_clock": _r(h.cpu_clock(), 0)}
        gc = next((s for s in h.latest.sensors.values() if s.kind == "Clock" and (s.hw_type or "").startswith("Gpu")
                   and "core" in s.name.lower() and s.value is not None), None)
        out["gpu_clock"] = _r(gc.value, 0) if gc else None
        out["fps"] = self.overlay_fps()
        return out

    def overlay_edit(self, on):
        return self._app.overlay_edit(bool(on))

    def overlay_status(self):
        return self._app.overlay_status()

    def overlay_log(self, msg):
        """The overlay page reports its own script errors here (they used to vanish silently)."""
        self._app._ov_last_error = str(msg)[:300]
        log.warning("overlay page: %s", msg)
        return True

    def overlay_lock(self, locked):
        return self._app.overlay_lock(bool(locked))

    def overlay_minimise(self, on):
        return self._app.overlay_minimise(bool(on))

    def overlay_track(self):
        return self._app.overlay_track()

    def overlay_set(self, values):
        """Overlay settings panel: applies straight away (no Save button). Position is only changed by dragging."""
        o = self._cfg["overlay"]
        new = dict(o)
        for k, v in (values or {}).items():
            if k in ("enabled", "stats", "layout", "size", "opacity", "text_color", "snap", "hotkey", "fps_color", "move_hold"):
                new[k] = v
        if values.get("preset") in overlay.PRESETS:
            new = overlay.apply_preset(new, values["preset"])
        new = overlay.migrate(new)
        hotkey_changed = new.get("hotkey") != o.get("hotkey")
        if new.get("hotkey") and not overlay.parse_hotkey(new["hotkey"]):
            new["hotkey"] = o.get("hotkey", "")
        before = {k: o.get(k) for k in ("enabled", "stats", "layout", "size", "opacity", "text_color", "snap", "hotkey", "fps_color", "move_hold")}
        o.clear()
        o.update(new)
        self._cfg.save()
        self._app._ov_size = None
        self._app._ov_hold_vks = overlay.parse_hold(o.get("move_hold", "")) or []
        self._app.apply_overlay()
        ok = True
        if hotkey_changed:
            ok = bool(self._app.overlay_hotkey()) or not o.get("hotkey")
            self._app._ov_hotkey_ok = ok
        after = {k: o.get(k) for k in before}
        if after != before and not values.get("_undo"):
            self._log("overlay", "Overlay settings changed", before=before, after=after, merge="overlay")
        return {"overlay": o, "hotkey_ok": ok}

    def overlay_corner(self, corner):
        self._app.overlay_corner(corner)
        return True

    def overlay_fit(self, w, h, dpr=None):
        self._app.overlay_fit(w, h, dpr)
        return True

    def overlay_fps(self):
        """FPS row for the overlay: {"state": "off" | "unavailable" | "no_game"} or {"state": "ok", fps, low1, frametime, app}."""
        o = self._cfg["overlay"]
        if not overlay.needs_fps(o):
            return {"state": "off"}
        try:
            cap = self._app.ensure_overlay_fps()
            if not cap:
                return {"state": "unavailable"}
            return cap.reading_for(presentmon.foreground_pid())
        except Exception:  # noqa: BLE001 - the overlay must never show errors
            log.exception("overlay fps")
            return {"state": "unavailable"}

    def gpu_results(self, run_id=None, base_id=None):
        return gpuresults.report(run_id, base_id)

    def gpu_runs(self):
        return gputune.runs()

    def gpu_run_edit(self, run_id, label=None, score=None, delete=False):
        r = gputune.runs()
        for x in list(r):
            if x["id"] == run_id:
                if delete:
                    r.remove(x)
                if label is not None:
                    x["label"] = label
                if score not in (None, ""):
                    x["stats"]["score"] = float(score)
                    if x["stats"].get("power_avg") and not x["stats"].get("fps_avg"):
                        x["stats"]["score_per_watt"] = round(float(score) / x["stats"]["power_avg"], 2)
        gputune.save_runs(r)
        return r

    # ------------------------------------------------------------------ GPU window
    def gpu_window(self, mode="bench", seconds=30):
        self._app.open_gpu_window(mode, int(seconds))
        return True

    def gpu_params(self):
        return self._app.gpu_params

    def gpu_result(self, result):
        self._app.gpu_result = result
        self._app.close_gpu_window()
        return True

    def gpu_poll(self):
        r = self._app.gpu_result
        if r is not None:
            self._app.gpu_result = None
        return r

    # ------------------------------------------------------------------ stress
    def stress_start(self, o):
        if self._stress.running:
            return False
        self._stress.start(cpu=o.get("cpu", True), cpu_mode=o.get("mode", "heavy"),
                           threads=int(o.get("threads") or os.cpu_count() or 1),
                           ram_percent=int(o.get("ram", 0)), duration_s=int(o.get("duration", 600)),
                           safety_temp=float(o.get("safety", 95)))
        if o.get("gpu"):
            self._app.open_gpu_window("stress", 0)
        return True

    def stress_stop(self):
        self._stress.stop()
        return True

    def stress_status(self, since=0):
        r = self._stress.report
        samples = [[s.t, _r(s.cpu_temp), _r(s.gpu_temp), _r(s.cpu_clock, 0), _r(s.cpu_power)]
                   for s in r.samples[int(since):]]
        out = {"running": self._stress.running, "elapsed": r.duration_s, "errors": r.errors,
               "iterations": r.iterations, "max_temp": _r(r.max_cpu_temp), "avg_temp": _r(r.avg_cpu_temp),
               "peak_clock": _r(r.peak_clock, 0), "end_clock": _r(r.end_clock, 0), "max_power": _r(r.max_cpu_power),
               "throttling": r.throttling, "reason": r.stopped_reason, "samples": samples,
               "total": len(r.samples)}
        if not self._stress.running and r.samples:
            out["verdict"] = r.verdict()
            self._app.close_gpu_window()
        return out

    # ------------------------------------------------------------------ overclocking
    def oc_state(self):
        prof = oc.platform_profile(self.inventory(), [])
        return {"profile": prof, "plans": oc.plans(prof), "progress": oc.progress(),
                "journal": oc.journal()[-60:][::-1], "windows": oc.cpu_windows_settings(),
                "validation": self._validation}

    def oc_step(self, step_id, state, text=""):
        oc.set_progress(step_id, state)
        kind = {"applied": "applied", "passed": "passed", "failed": "failed", "reverted": "reverted"}.get(state, state)
        if text:
            oc.add_journal(kind, text, step=step_id)
        return oc.progress()

    def oc_note(self, text):
        return oc.add_journal("note", text)

    def oc_windows_set(self, boost_mode=None, max_state=None):
        try:
            cur = oc.cpu_windows_settings()
            before = {"boost_mode": cur.get("boost_mode"), "max_state": cur.get("max_state")}
        except Exception:  # noqa: BLE001
            before = None
        ok = oc.set_cpu_windows(boost_mode, max_state)
        self._log("oc_windows", "Changed how hard the processor boosts", before=before,
                  after={"boost_mode": boost_mode, "max_state": max_state}, undo=before is not None, ok=ok, risk="Medium")
        oc.add_journal("applied", f"Windows CPU: boost mode={boost_mode}, max state={max_state}")
        return {"ok": ok, **oc.cpu_windows_settings()}

    def oc_validate(self, step_id, kind, minutes=10, title=""):
        """Run the right test for a step, then mark it passed/failed (also checks Event Viewer for WHEA /
        driver resets that happened during the test)."""
        if self._stress.running:
            return False
        cores = __import__("psutil").cpu_count(logical=False) or 8
        if kind == "core_cycle":
            per = 60
            dur = cores * per * 2            # two full passes over every core
            self._stress.start(cpu=False, core_cycle=True, seconds_per_core=per, duration_s=dur, safety_temp=95)
        elif kind == "ram":
            dur = int(minutes) * 60
            self._stress.start(cpu=False, ram_percent=70, duration_s=dur, safety_temp=95)
        elif kind == "gpu":
            dur = int(minutes) * 60
            self._stress.start(cpu=False, duration_s=dur, safety_temp=95)
            self._app.open_gpu_window("stress", 0)
        else:
            dur = int(minutes) * 60
            self._stress.start(cpu=True, cpu_mode="heavy", duration_s=dur, safety_temp=95)
        self._validation = {"step": step_id, "kind": kind, "title": title, "start": time.time(),
                            "duration": dur, "state": "running", "verdict": None}
        oc.mark_test_running(step_id, kind)
        threading.Thread(target=self._finish_validation, daemon=True).start()
        return True

    def _finish_validation(self):
        v = self._validation
        while self._stress.running:
            time.sleep(1)
        self._app.close_gpu_window()
        oc.clear_test_running()
        r = self._stress.report
        title, text = r.verdict()
        bad = []
        try:
            for e in crashes.read_events(days=1):
                if e.get("time", 0) >= v["start"] - 5:
                    k = crashes.classify(e)
                    if k["kind"] in ("whea", "gpu", "bsod") and k["severity"] >= 1:
                        bad.append(k["title"] + (": " + k["detail"] if k.get("detail") else ""))
        except Exception:  # noqa: BLE001
            pass
        stopped = r.stopped_reason not in ("completed",)
        if r.stopped_reason.startswith("safety"):
            state = "failed"
        elif stopped:
            state = "stopped"
        else:
            state = "failed" if (title == "FAIL" or bad) else "passed"
        if bad and title != "FAIL":
            text = "No calculation errors, but Windows logged: " + "; ".join(bad[:3])
        v.update(state=state, verdict=[title if not bad else "FAIL", text], events=bad,
                 per_core=r.per_core, max_temp=r.max_cpu_temp)
        if state in ("passed", "failed"):
            oc.set_progress(v["step"], state, text)
            oc.add_journal(state, f"{v.get('title') or v['step']}: {state.upper()} - {text}", step=v["step"])

    def oc_validation(self):
        v = self._validation
        if not v:
            return None
        out = dict(v)
        out["elapsed"] = self._stress.report.duration_s if v["state"] == "running" else v["duration"]
        out["core"] = self._stress.current_core
        out["errors"] = self._stress.report.errors
        out["max_temp"] = self._stress.report.max_cpu_temp
        return out

    def oc_validation_stop(self):
        self._stress.stop("stopped by user")
        return True

    # ------------------------------------------------------------------ crash center
    def crashes_scan(self, days=30):
        dumps = crashes.list_dumps()
        rel = crashes.read_reliability(days)
        events = crashes.read_events(days)
        inc = crashes.build_incidents(events, rel, dumps, oc.journal())
        self._crash_cache = {"incidents": inc, "stability": rel["stability"], "dumps": dumps,
                             "debugger": bool(crashes.find_cdb()), "scanned": time.time(), "days": days}
        return self._crash_cache

    def crash_analyze(self, path):
        job = self._dumps.start(path)
        return {k: job[k] for k in ("state", "error", "result")}

    def crash_analyze_status(self, path):
        job = self._dumps.jobs.get(path)
        if not job:
            return None
        return {"state": job["state"], "error": job["error"], "result": job["result"], "raw": job["raw"][-20000:],
                "elapsed": time.time() - job["started"]}

    def install_windbg(self):
        self._log("windbg", "Installed Microsoft's crash reader (WinDbg)", undo=False)
        return crashes.install_windbg()

    def startup_notes(self):
        return self.startup_notes_list

    # ------------------------------------------------------------------ Lighting (v3 engine)
    def light_state(self):
        e = self._light
        h = e.host
        devs = e.device_list() if e.client else []
        return {"native_error": e.native_error, "status": "running" if e.client else ("paused" if e.paused else h.status), "msg": e.msg,
                "error": h.error, "stats": dict(e.stats), "devices": devs, "state": e.L["state"],
                "effects": [x for x in EFFECTS if x != "Off"] + ledmap.SPATIAL_EFFECTS + list(fx.EFFECTS) + ["Off"],
                "palettes": list(fx.PALETTES),
                "fan_types": CORSAIR_LED_COUNTS, "orders": list(ORDERS), "exe": h.exe(), "port": PORT,
                "setup": [{"key": d["key"], "zone": z["name"]} for d in devs for z in d["zones"] if z.get("unconfirmed")]}

    def light_reset(self):
        """Called every time the Lighting page opens."""
        if self._light.client:
            threading.Thread(target=self._light.reset, daemon=True).start()
        return True

    def light_connect(self):
        """(Re)start RigLab's lighting service and rediscover every device."""
        e = self._light
        e.paused = False
        e.client = None
        e.host.stop()
        e.start()
        return True

    def light_pause(self, on):
        """Hand the hardware back (e.g. to use another RGB program) or take it again."""
        e = self._light
        if on:
            e.paused = True
            e.stop(keep_service=False)
        else:
            self.light_connect()
        return bool(on)

    def light_pick_exe(self):
        path = self._app.pick_file("OpenRGB (OpenRGB.exe)")
        if path:
            self._cfg["openrgb"]["exe"] = path
            self._cfg.save()
            self.light_connect()
        return self.light_state()

    def light_set(self, state):
        before = dict(self._light.L["state"])
        self._light.set_state(**state)
        after = dict(self._light.L["state"])
        if after != before:
            self._log("lighting", f"Lights: {after.get('effect', 'changed')}", before={"state": before}, after={"state": after}, merge="lighting")
        return True

    def light_device(self, key, settings):
        ds = self._light.dev_settings(key)
        before = {k: ds.get(k) for k in settings}
        self._light.set_device(key, **settings)
        if before != {k: ds.get(k) for k in settings}:
            self._log("light_device", f"Lights: {key} settings", before={"key": key, "settings": before}, after={"key": key, "settings": settings},
                      merge="light_device:" + key)
        return self.light_state()

    def light_zone(self, key, zone, size=None, per=None, empty=None):
        self._light.set_zone(key, zone, size, per, empty)
        self._light.set_test(key, zone, None)
        return self.light_state()

    def light_test(self, key, zone, spec=None):
        self._light.set_test(key, zone, spec)
        return True

    def light_identify(self, key, zone=None):
        """Light one device (or one zone) white for 3 s, everything else stays on the effect."""
        e = self._light
        d = next((x for x in e.device_list() if x["key"] == key), None)
        if not d:
            return False
        zs = [z for z in d["zones"] if zone is None or z["name"] == zone]
        for z in zs:
            e.set_test(key, z["name"], {"kind": "solid", "size": z["leds"]})

        def clear():
            time.sleep(3)
            for z in zs:
                e.set_test(key, z["name"], None)
        threading.Thread(target=clear, daemon=True).start()
        return True

    def light_rescan(self):
        e = self._light
        if not e.client:
            return self.light_connect()
        try:
            e.client.rescan_devices() if hasattr(e.client, "rescan_devices") else None
            time.sleep(2)
            e.discover()
        except Exception as ex:  # noqa: BLE001
            return {"error": str(ex)}
        return self.light_state()

    def light_map(self):
        return {"fixtures": self._light.fixtures(), "paint": self._light.L.get("paint", {}),
                "effects": ledmap.SPATIAL_EFFECTS}

    def light_map_save(self, fixtures):
        self._light.L["map"] = fixtures
        self._light.invalidate()
        self._cfg.save()
        return True

    def light_paint_save(self, paint):
        self._light.L["paint"] = paint
        self._cfg.save()
        return True

    def light_fix_openrgb(self):
        """Repair your normal OpenRGB's settings (undo what RigLab 2.2 changed)."""
        from .core.corsair_direct import restore_openrgb_settings, set_openrgb_detector
        exe = self._light.host.exe()
        if restore_openrgb_settings(exe):
            return "Restored your original OpenRGB settings."
        set_openrgb_detector("Corsair Lighting Node Pro", True, exe)
        return "Re-enabled the Corsair Lighting Node detector in your OpenRGB settings."

    def light_report(self):
        e = self._light
        lines = [f"RigLab {APP_VERSION} lighting report",
                 f"Service: {e.host.status} {e.host.error or ''} | exe={e.host.exe()} | port {PORT} | config {e.host.config_dir}",
                 f"Stream: {e.stats} | paused={e.paused} | msg={e.msg}",
                 f"Native USB: {[(n.name, n.info.get('product_id'), 'open' if n.h else 'closed', n.writes) for n in e.native]} "
                 f"error={e.native_error}",
                 f"State: {e.L['state']}", f"liquidctl skipped: {getattr(self._hub.liquid, 'skipped', [])}"]
        try:
            import psutil
            procs = [p.info.get("exe") or p.info.get("name") for p in psutil.process_iter(["name", "exe"])
                     if (p.info.get("name") or "").lower() in ("openrgb.exe", "icue.exe", "signalrgb.exe", "lightingservice.exe")]
            lines.append(f"RGB processes: {procs}")
        except Exception as ex:  # noqa: BLE001
            lines.append(f"process check failed: {ex}")
        for d in e.device_list():
            lines.append(f"[{d['key']}] type={d['type']} mode={d['active_mode']} modes={d['modes']} settings={d['settings']}")
            for z in d["zones"]:
                lines.append(f"     zone '{z['name']}': {z['leds']} LEDs (min {z['min']}, max {z['max']}, per-fan {z['per']}"
                             f"{', unconfirmed' if z.get('unconfirmed') else ''})")
        lines += e.host.log_tail(25)
        return "\n".join(lines)

    def rgb_off(self):           # used by the dashboard button
        self.light_set({"effect": "Off"})
        return "ok"

    # ------------------------------------------------------------------ fans
    def fans_state(self):
        snap = self._hub.latest.sensors
        ctrls = []
        for s in self._hub.controls():
            rpm = None
            # pair "Fan #2" control with the matching RPM sensor when we can
            for o in snap.values():
                if o.kind == "Fan" and o.hardware == s.hardware and _num(o.name) == _num(s.name) and o.value is not None:
                    rpm = round(o.value)
                    break
            ctrls.append({"id": s.id, "name": s.name, "hw": s.hardware, "value": _r(s.value, 0), "rpm": rpm,
                          "hub": s.id.startswith("/liquidctl/"), "pump": "pump" in s.name.lower(),
                          "curve": self._fans.curves.get(s.id), "applied": self._fans.applied.get(s.id)})
        temps = sorted(({"id": s.id, "name": f"{s.hardware} › {s.name}", "value": _r(s.value)}
                        for s in snap.values() if s.kind == "Temperature" and s.value is not None),
                       key=lambda d: (not d["name"].lower().startswith(("amd", "intel")), d["name"]))
        return {"controls": ctrls, "temps": temps, "enabled": self._fans.enabled, "presets": PRESETS}

    def fans_set_curve(self, cid, source, points, pump=False, label=None):
        before = _copy(self._fans.curves.get(cid))
        self._fans.set_curve(cid, source, points, bool(pump))
        self._log("fan_curve", label or f"New fan curve for {self._fan_name(cid)}", before={"cid": cid, "curve": before},
                  after={"cid": cid, "curve": _copy(self._fans.curves.get(cid))})
        return True

    def fans_preset(self, name):
        """Simple view: one preset on every fan, following the processor temperature."""
        if name not in PRESETS:
            return {"ok": False, "msg": "Unknown preset"}
        st = self.fans_state()
        if not st["controls"] or not st["temps"]:
            return {"ok": False, "msg": "RigLab can't see any fans it can control yet"}
        src = st["temps"][0]["id"]
        for c in st["controls"]:
            pump = bool(c["pump"] or (c["curve"] or {}).get("pump"))
            self.fans_set_curve(c["id"], src, [list(x) for x in PRESETS[name]], pump, label=f"{c['name']}: {name} fan setting")
        if not self._fans.enabled:
            self.fans_enable(True)
        return {"ok": True, "msg": f"All fans set to {name}", "count": len(st["controls"])}

    def fans_remove(self, cid):
        before = _copy(self._fans.curves.get(cid))
        self._fans.remove_curve(cid)
        if before:
            self._log("fan_curve", f"Handed {self._fan_name(cid)} back to the motherboard",
                      before={"cid": cid, "curve": before}, after={"cid": cid, "curve": None}, risk="None")
        return True

    def fans_enable(self, on):
        was = self._fans.enabled
        if on:
            self._fans.enabled = True
        else:
            self._fans.release_all()
        if was != self._fans.enabled:
            self._log("fans_enabled", "RigLab fan control " + ("on" if self._fans.enabled else "off"),
                      before={"on": was}, after={"on": self._fans.enabled})
        return self._fans.enabled

    def fans_manual(self, cid, pct=None):
        if pct is not None and cid in self._fans.curves and self._fans.enabled:
            self._fans.release_all()
        ok = self._hub.set_control(cid, None if pct is None else max(20.0, float(pct)))
        if pct is None:
            self._log("fan_manual", f"Released {self._fan_name(cid)}", undo=False, ok=bool(ok), risk="None")
        else:
            self._log("fan_manual", f"Held {self._fan_name(cid)} at {max(20, round(float(pct)))}%", before={"cid": cid},
                      after={"cid": cid, "pct": pct}, ok=bool(ok), risk="Medium")
        return ok

    def _fan_name(self, cid):
        return next((s.name for s in self._hub.controls() if s.id == cid), "fan")

    # ------------------------------------------------------------------ tweaks
    def tweaks_state(self):
        out = []
        for t in self._tweaks.values():
            try:
                st = t.get()
            except Exception:  # noqa: BLE001
                st = None
            out.append({"id": t.id, "name": t.name, "desc": t.description, "on": st, "admin": t.needs_admin,
                        "reboot": t.needs_reboot, "cat": t.category})
        plans = tweaks.power_plans()
        nv = self._hub.nvml
        gpu = None
        if nv.handles:
            try:
                lo, hi, cur = nv.power_limits()
                gpu = {"name": nv.gpu_name(0), "min": lo, "max": hi, "cur": cur}
            except Exception as e:  # noqa: BLE001
                gpu = {"error": str(e)}
        self._startup = tweaks.startup_items()
        startup = []
        for i, it in enumerate(self._startup):
            size = None
            try:
                p = storage.exe_path(it.command)
                size = os.path.getsize(os.path.expandvars(p)) if p else None
            except OSError:
                pass
            impact, why = storage.startup_impact(it.name, it.command, size)
            startup.append({"i": i, "name": it.name, "cmd": it.command, "where": it.location, "on": it.enabled, "impact": impact, "why": why})
        return {"tweaks": out, "plans": plans, "gpu": gpu, "startup": startup, "admin": tweaks.is_admin()}

    def tweak_set(self, tid, on, source="you"):
        t = self._tweaks[tid]
        try:
            before = t.get()
        except Exception:  # noqa: BLE001
            before = None
        a = explain.action("tweak." + tid)
        try:
            t.set(bool(on))
        except Exception as e:  # noqa: BLE001
            return str(e)
        self._log("tweak", f"{a['label']}: {'on' if on else 'off'}", before={"id": tid, "on": before},
                  after={"id": tid, "on": bool(on)}, undo=before is not None, source=source, risk=a["risk"])
        return "ok"

    def tweaks_recommended(self):
        """'Make games run smoother': Game Mode on, background recording off. Only changes what isn't set yet."""
        done = []
        for tid, want in (("game_mode", True), ("game_dvr", False)):
            t = self._tweaks.get(tid)
            if not t:
                continue
            try:
                if t.get() == want:
                    continue
            except Exception:  # noqa: BLE001
                pass
            if self.tweak_set(tid, want) == "ok":
                done.append(tid)
        return {"ok": True, "changed": done,
                "msg": "Done - games should run a little smoother" if done else "Already set up for games - nothing to change"}

    def restore_point(self):
        ok, msg = tweaks.create_restore_point()
        self._log("restore_point", "Made a safety restore point", undo=False, ok=ok, risk="None", detail=msg)
        return {"ok": ok, "msg": msg}

    def restore_prepare(self, risk="Medium"):
        """Called before every Medium/High risk action. Uses a restore point from the last 24 hours if there is one,
        otherwise makes one. Returns go = proceed / ask (Medium, carry on?) / block (High)."""
        now = datetime.now(timezone.utc)
        d = explain.plan_restore(risk, tweaks.restore_status(), now)
        if d["go"] == "create":
            ok, msg = tweaks.create_restore_point("RigLab safety backup")
            d = explain.after_create(risk, ok, msg, tweaks.restore_status(), now)
            self._log("restore_point", "Made a safety restore point" if ok else "Couldn't make a safety restore point",
                      undo=False, ok=ok, source="auto", risk="None", detail=msg)
        return d

    def restore_enable(self):
        ok, msg = tweaks.enable_restore()
        self._log("restore_enable", "Turned on restore points", undo=False, ok=ok, source="fix", detail=msg)
        return {"ok": ok, "msg": msg}

    def set_power_plan(self, guid):
        plans = tweaks.power_plans()
        before = next((p for p in plans if p["active"]), None)
        name = next((p["name"] for p in plans if p["guid"] == guid), "power plan")
        ok = tweaks.set_power_plan(guid)
        self._log("power_plan", f"Power plan: {name}", before={"guid": before["guid"]} if before else None,
                  after={"guid": guid}, undo=before is not None, ok=ok)
        return ok

    def add_ultimate(self):
        ok = tweaks.add_ultimate_plan()
        self._log("power_ultimate", "Added the Ultimate Performance power plan", undo=False, ok=ok, risk="None")
        return ok

    def set_gpu_power(self, watts):
        nv = self._hub.nvml
        try:
            before = nv.power_limits()[2]
        except Exception:  # noqa: BLE001
            before = None
        try:
            nv.set_power_limit(float(watts))
        except Exception as e:  # noqa: BLE001
            return str(e)
        self._log("gpu_power", f"Graphics card power limit: {round(float(watts))} W", before={"watts": before},
                  after={"watts": float(watts)}, undo=before is not None, risk="Medium")
        return "ok"

    def startup_set(self, i, on):
        try:
            item = self._startup[int(i)]
            before = item.enabled
            tweaks.set_startup_enabled(item, bool(on))
        except Exception as e:  # noqa: BLE001
            return str(e)
        self._log("startup", f"{item.name}: {'opens' if on else 'no longer opens'} when Windows starts",
                  before={"name": item.name, "where": item.location, "on": before},
                  after={"name": item.name, "where": item.location, "on": bool(on)})
        return "ok"

    def junk(self, clean=False):
        b, n = tweaks.clean_junk() if clean else tweaks.scan_junk()
        if clean:
            self._log("junk", f"Freed {_size(b)} of temporary files", undo=False, detail=f"{n} files")
        return {"bytes": b, "files": n}

    # ------------------------------------------------------------------ presets (Home)
    def _preset_current(self):
        tw = {}
        for t in self._tweaks.values():
            try:
                tw[t.id] = t.get()
            except Exception:  # noqa: BLE001
                tw[t.id] = None
        st = self.fans_state()
        return {"plans": tweaks.power_plans(), "tweaks": tw,
                "fans": {"controls": [{"id": c["id"], "name": c["name"], "curve": c["curve"], "pump": c["pump"]} for c in st["controls"]],
                         "enabled": st["enabled"], "presets": st["presets"], "source": (st["temps"][0]["id"] if st["temps"] else None)}}

    def preset_state(self):
        last = self._cfg.data.get("ui", {}).get("preset")
        try:
            act = presets.active(self._preset_current(), last)
        except Exception:  # noqa: BLE001
            log.exception("preset state")
            act = None
        return {"cards": presets.cards(), "active": act, "last": last}

    def preset_preview(self, pid):
        try:
            return presets.preview(pid, self._preset_current())
        except KeyError:
            return {"error": "Unknown preset"}

    def preset_apply(self, pid):
        """Apply a preset the person has just previewed. Logged as ONE change, so one Undo puts it all back."""
        cur = self._preset_current()
        try:
            p = presets.preview(pid, cur)
        except KeyError:
            return {"ok": False, "msg": "Unknown preset"}
        if p["nothing"]:
            self._cfg.data.setdefault("ui", {})["preset"] = pid
            self._cfg.save()
            return {"ok": True, "msg": f"Your PC is already set up for {p['name']}", "changed": 0}
        fans = cur["fans"]
        before = {"plan": next((x["guid"] for x in cur["plans"] if x["active"]), None), "tweaks": {},
                  "fans": {c["id"]: _copy(c["curve"]) for c in fans["controls"]}, "fans_enabled": fans["enabled"]}
        done, failed = [], []
        for c in p["changes"]:
            try:
                if c["kind"] == "plan":
                    if not tweaks.set_power_plan(c["to"]):
                        raise RuntimeError("Windows didn't accept the power plan")
                elif c["kind"] == "tweak":
                    before["tweaks"][c["key"]] = cur["tweaks"].get(c["key"])
                    self._tweaks[c["key"]].set(bool(c["to"]))
                elif c["kind"] == "fans":
                    pts = [list(x) for x in fans["presets"][c["to"]]]
                    for ctl in fans["controls"]:                       # new curves go on before anything is released
                        pump = bool(ctl["pump"] or (ctl["curve"] or {}).get("pump"))
                        self._fans.set_curve(ctl["id"], fans["source"], pts, pump)
                    self._fans.enabled = True
                done.append(c["text"])
            except Exception as e:  # noqa: BLE001
                failed.append(f"{c['text']} ({e})")
        self._cfg.data.setdefault("ui", {})["preset"] = pid
        self._cfg.save()
        ok = bool(done)
        self._log("preset", f"Applied the {p['name']} preset", before=before, after={"preset": pid}, undo=ok, ok=ok,
                  risk=p["risk"], detail=" ".join(done + ["Didn't work: " + f for f in failed]))
        if failed:
            return {"ok": ok, "changed": len(done), "msg": f"{p['name']} applied, but {len(failed)} change{'s' if len(failed) > 1 else ''} didn't work: " + "; ".join(failed)}
        return {"ok": True, "changed": len(done), "msg": f"{p['name']} preset applied. You can undo it in Change history."}

    def _undo_preset(self, b):
        if b.get("plan"):
            tweaks.set_power_plan(b["plan"])
        for tid, on in (b.get("tweaks") or {}).items():
            if on is not None and tid in self._tweaks:
                self._tweaks[tid].set(bool(on))
        for cid, curve in (b.get("fans") or {}).items():
            if curve:
                self._fans.set_curve(cid, curve.get("source"), curve.get("points"), bool(curve.get("pump")))
        for cid, curve in (b.get("fans") or {}).items():          # release only after the others are back in place
            if not curve and cid in self._fans.curves:
                self._fans.remove_curve(cid)
        if b.get("fans_enabled") is False:
            self._fans.release_all()

    # ------------------------------------------------------------------ PC health (dial)
    def health_last(self):
        return {"last": self._health.last, "history": self._health.history[-60:]}

    def _readings_items(self, ctx=None):
        """Live readings + drive health + crashes in the last 30 days, as report-card items."""
        snap = self.snapshot()["summary"]
        extra = self.pc_status()
        fans = [x for x in self._hub.latest.sensors.values() if x.kind == "Fan" and x.value is not None
                and not (x.hw_type or "").startswith("Gpu")]
        try:
            crash = explain.serious_crashes(self.crashes_scan(30).get("incidents"))
        except Exception:  # noqa: BLE001
            log.exception("health: crashes")
            crash = None
        try:
            drives = [d.get("Verdict") for d in sysinfo.drive_health()]
        except Exception:  # noqa: BLE001
            drives = []
        readings = {"cpu_temp": snap.get("cpu_temp"), "gpu_temp": snap.get("gpu_temp"), "ram_load": snap.get("ram_load"),
                    "disk_free_pct": extra.get("disk_free_pct"), "disk_free": extra.get("disk_free"),
                    "fans": "none" if not fans else "good" if any(f.value > 0 for f in fans) else "warn",
                    "crashes": crash, "drives": drives}
        return health.quick_items(readings, explain.lights(self._cfg.data.get("alerts")))

    def health_start(self, kind="quick"):
        """Start a quick or full check in the background. The screen polls health_status() for progress."""
        j = self._job
        if j and j.running():
            return {"busy": True, **j.status()}
        kind = "full" if kind == "full" else "quick"
        used = None
        try:
            import shutil
            used = shutil.disk_usage(os.environ.get("SYSTEMDRIVE", "C:") + "\\").used if sys.platform == "win32" else None
        except OSError:
            pass
        online = healthcheck.is_online() if kind == "full" else True
        self._job = healthcheck.CheckJob(kind, healthcheck.build_steps(kind, self._readings_items, used), online=online)
        self._job.on_done = self._health.add
        self._job.start()
        return self._job.status()

    def health_status(self):
        j = self._job
        return j.status() if j else {"running": False, "result": None, "items": []}

    def health_cancel(self):
        if self._job and self._job.running():
            self._job.cancel()
            return True
        return False

    def health_quick(self):
        """Quick check without the progress screen (used by the weekly scheduled check). Waits for the result."""
        if self._job and self._job.running():
            return {"busy": True}
        self._job = healthcheck.CheckJob("quick", healthcheck.build_steps("quick", self._readings_items), online=True)
        self._job.on_done = self._health.add
        self._job.start(background=False)
        return self._job.result or {}

    def health_fix(self, fix_id):
        """A Fix it button on the report card. Risky ones were confirmed (and a restore point made) by the screen."""
        f = healthcheck.FIXES.get(fix_id)
        if not f:
            return {"ok": False, "msg": "Unknown fix"}
        if f.get("online") and not healthcheck.is_online():
            return {"ok": False, "msg": "This repair needs an internet connection. Connect and try again."}
        if not f.get("job"):
            try:
                if f.get("open"):
                    os.startfile(f["open"]) if sys.platform == "win32" else None
                else:
                    subprocess.Popen(f["cmd"], creationflags=0x08000000 if sys.platform == "win32" else 0)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "msg": f"Couldn't open it: {e}"}
            if fix_id == "memtest":
                self._log("fix", "Fix it: scheduled Windows' memory test", undo=False, source="fix", risk=f["risk"],
                          detail="Windows Memory Diagnostic opened - choose when to restart.")
            return {"ok": True, "msg": "Opened" if f.get("open") or fix_id.startswith("open_") else "Started"}
        if self._job and self._job.running():
            return {"ok": False, "msg": "Another check or repair is still running"}

        def repair(ctx):
            rc, out = ctx.run(f["cmd"], timeout=2 * 3600)
            return [healthcheck.repair_item(fix_id, rc, out)]
        self._job = healthcheck.CheckJob("repair", [healthcheck.Step(fix_id, f["label"], f["est"], repair)])

        def done(_res):
            it = self._job.items[0] if self._job.items else {}
            self._log("fix", "Fix it: " + f["label"], undo=False, source="fix", risk=f["risk"], ok=it.get("state") == "good",
                      detail=it.get("say", ""))
        self._job.on_done = done
        self._job.start()
        return {"ok": True, "msg": "Started", **self._job.status()}

    def health_history(self):
        return self._health.history[-200:]

    def health_save_text(self):
        """Save the last report as a text file in Documents\\RigLab reports and show it."""
        r = self._health.last
        if not r:
            return {"ok": False, "msg": "Run a check first"}
        folder = os.path.join(os.path.expanduser("~"), "Documents", "RigLab reports")
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, time.strftime("RigLab health report %Y-%m-%d %H%M.txt", time.localtime(r["time"])))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(health.report_text(r, APP_VERSION))
        except OSError as e:
            return {"ok": False, "msg": f"Couldn't save the report: {e}"}
        _open_path(path)
        return {"ok": True, "msg": "Report saved: " + path, "path": path}

    # ------------------------------------------------------------------ Explain my PC
    def explain_pc(self):
        inv = self.inventory()
        return {"items": pcinfo.explain(inv.get("sections") or {})}

    # ------------------------------------------------------------------ storage clean-up
    def storage_state(self):
        drives = []
        try:
            import psutil
            for p in psutil.disk_partitions():
                try:
                    u = psutil.disk_usage(p.mountpoint)
                    drives.append({"name": p.mountpoint, "total": u.total, "free": u.free, "pct_free": explain.free_pct(u.total, u.free)})
                except OSError:
                    continue
        except ImportError:
            pass
        try:
            ub, un = storage.folder_size(storage.update_cache_dir(), older_than_days=10) if sys.platform == "win32" else (0, 0)
        except OSError:
            ub, un = 0, 0
        return {"drives": drives, "updates": {"bytes": ub, "files": un}, "big": self.storage_big_status()}

    def storage_big_start(self):
        if self._big and self._big.get("running"):
            return self.storage_big_status()
        roots = storage.user_roots()
        job = {"running": True, "files": [], "finished": False, "roots": [str(r) for r in roots], "cancel": False, "started": time.time()}
        self._big = job

        def run():
            files, done = storage.largest_files(roots, deadline=time.monotonic() + 120, cancelled=lambda: job["cancel"])
            job.update(files=files, finished=done, running=False)
        threading.Thread(target=run, name="LargestFiles", daemon=True).start()
        return self.storage_big_status()

    def storage_big_status(self):
        j = self._big
        if not j:
            return {"running": False, "files": None}
        return {"running": j["running"], "files": j["files"] if not j["running"] else None, "finished": j["finished"],
                "roots": j["roots"], "elapsed": time.time() - j["started"]}

    def storage_recycle(self, path):
        """Move one of the listed big files to the Recycle Bin (only files inside your own folders)."""
        roots = storage.user_roots()
        if not storage.inside(path, roots) or not os.path.isfile(path):
            return {"ok": False, "msg": "RigLab only removes files from your own folders"}
        size = os.path.getsize(path)
        if sys.platform != "win32":
            return {"ok": False, "msg": "Windows only"}
        script = ("Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
                  "$env:RIGLAB_PATH, 'OnlyErrorDialogs', 'SendToRecycleBin')")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=120,
                           env={**os.environ, "RIGLAB_PATH": path}, creationflags=0x08000000)
        ok = r.returncode == 0 and not os.path.exists(path)
        self._log("recycle", f"Moved {os.path.basename(path)} to the Recycle Bin ({_size(size)})", undo=False, ok=ok,
                  detail="You can put it back from the Recycle Bin." if ok else (r.stderr or "")[:200])
        if ok and self._big and self._big.get("files"):
            self._big["files"] = [f for f in self._big["files"] if f["path"] != path]
        return {"ok": ok, "msg": "Moved to the Recycle Bin. You can put it back from there." if ok else "Windows didn't move it (is it open in another app?)"}

    def storage_show(self, path):
        if sys.platform == "win32" and storage.inside(path, storage.user_roots()):
            subprocess.Popen(["explorer", "/select,", path])
            return True
        return False

    def storage_clean_updates(self):
        if sys.platform != "win32":
            return {"ok": False, "msg": "Windows only"}
        b, n = storage.clean_folder(storage.update_cache_dir(), older_than_days=10)
        self._log("update_cache", f"Removed {_size(b)} of old Windows update downloads", undo=False, detail=f"{n} files")
        return {"ok": True, "bytes": b, "files": n, "msg": f"Freed {_size(b)}"}

    # ------------------------------------------------------------------ internet speed test
    def netspeed_start(self):
        """Run the speed test in the background (screen polls netspeed_status). Uses Cloudflare's test servers."""
        if self._net and self._net.running():
            return self._net.status()
        H = healthcheck

        def conn(ctx):
            ctx.data["conn"] = netspeed.connection_info()
            if not H.is_online():
                ctx.data["offline"] = True
            return []

        def server(ctx):
            if not ctx.data.get("offline"):
                ctx.data.update(netspeed.meta())
            return []

        def ping(ctx):
            if ctx.data.get("offline"):
                return []
            n = 10
            rc, out = ctx.run(["ping", "-n", str(n), "-w", "1000", netspeed.PING_HOST], timeout=40) if sys.platform == "win32" else (None, "")
            p = netspeed.parse_ping(out, n)
            times = p["times"]
            if times:
                ctx.data["loss"] = round(p["lost"] / n * 100, 1)
            else:                                   # ICMP blocked on this network: measure delay over the web instead
                times = netspeed.http_latency(cancelled=ctx.cancelled)
                ctx.data["loss"] = None
            ctx.data["ping"], ctx.data["jitter"] = netspeed.ping_stats(times)
            return []

        def down(ctx):
            if not ctx.data.get("offline"):
                r = netspeed.transfer("down", cancelled=ctx.cancelled)
                ctx.data["download"], ctx.data["down_bytes"] = r["mbps"], r["bytes"]
            return []

        def up(ctx):
            if not ctx.data.get("offline"):
                r = netspeed.transfer("up", cancelled=ctx.cancelled)
                ctx.data["upload"], ctx.data["up_bytes"] = r["mbps"], r["bytes"]
            return []

        def finish(job):
            d = dict(job.ctx.data)
            r = {"time": time.time(), "offline": bool(d.get("offline")), **{k: d.get(k) for k in ("download", "upload", "ping", "jitter", "loss", "server", "isp", "ip", "conn")},
                 "data_mb": round(((d.get("down_bytes") or 0) + (d.get("up_bytes") or 0)) / 1e6, 1)}
            if not r["offline"] and r["download"] is None and r["upload"] is None:
                r["error"] = "Cloudflare's test server didn't answer. Try again in a minute."
            r["summary"] = netspeed.summary(r)
            r["lights"] = {k: netspeed.light(k, r.get(k)) for k in netspeed.LIGHTS}
            if not r["offline"] and not r.get("error"):
                self._net_hist.add(r)
            return r
        S = H.Step
        self._net = H.CheckJob("netspeed", [S("conn", "Checking your connection", 3, conn), S("server", "Finding the nearest test server", 2, server),
                                            S("ping", "Measuring ping, jitter and packet loss", 11, ping), S("down", "Testing download speed", 10, down),
                                            S("up", "Testing upload speed", 10, up)], finish=finish)
        self._net.start()
        return self._net.status()

    def netspeed_status(self):
        j = self._net
        if not j:
            return {"running": False, "result": None}
        st = j.status()
        st["partial"] = {k: v for k, v in (j.ctx.data if j.ctx else {}).items() if k in ("download", "upload", "ping", "jitter", "loss", "offline")}
        return st

    def netspeed_cancel(self):
        if self._net and self._net.running():
            self._net.cancel()
            return True
        return False

    def netspeed_history(self):
        return {"items": list(reversed(self._net_hist.items)), "note": netspeed.DATA_NOTE}

    # ------------------------------------------------------------------ start with Windows
    def autostart_state(self):
        return {"on": bool(self._cfg.data.get("startup", {}).get("with_windows")), "task": schedule.autostart_on()}

    def autostart_set(self, on, source="you"):
        ok, msg = schedule.set_autostart(bool(on))
        if ok:
            was = self._cfg.data.setdefault("startup", {}).get("with_windows")
            self._cfg.data["startup"]["with_windows"] = bool(on)
            self._cfg.save()
            self._log("autostart", "RigLab starts with Windows: " + ("on" if on else "off"), before={"on": bool(was)}, after={"on": bool(on)},
                      source=source, detail=msg)
        return {"ok": ok, "msg": ("RigLab will start when you sign in to Windows." if on else "RigLab won't start with Windows.") if ok
                else f"Task Scheduler didn't accept it: {msg}"}

    def autostart_first_run(self):
        """First start of 3.11: turn on start-with-Windows once (the after-boot lighting rescan needs it)."""
        st = self._cfg.data.setdefault("startup", {})
        if st.get("with_windows") is not None or sys.platform != "win32":
            return None
        r = self.autostart_set(True, source="auto")
        if r["ok"]:
            self.startup_notes_list.append({"kind": "light", "title": "Starts with Windows",
                                            "text": "RigLab now starts when you sign in, so your lights come back after a restart. "
                                                    "You can turn this off in Settings, or undo it in Change history.", "page": "settings"})
        else:
            st["with_windows"] = False
            self._cfg.save()
        return r

    # ------------------------------------------------------------------ weekly check
    def weekly_state(self):
        return {"on": bool(self._cfg.data.get("health", {}).get("weekly")), "scheduled": schedule.is_scheduled()}

    def weekly_set(self, on, source="you"):
        ok, msg = schedule.set_weekly(bool(on))
        if ok:
            was = bool(self._cfg.data.setdefault("health", {}).get("weekly"))
            self._cfg.data["health"]["weekly"] = bool(on)
            self._cfg.save()
            self._log("weekly", "Weekly quick check " + ("on (Sundays at 7 pm)" if on else "off"), before={"on": was}, after={"on": bool(on)},
                      source=source, detail=msg)
        return {"ok": ok, "msg": ("Weekly check is on. It runs on Sundays at 7 pm." if on else "Weekly check is off.") if ok else
                f"Task Scheduler didn't accept it: {msg}"}

    # ------------------------------------------------------------------ change history
    def _log(self, kind, title, before=None, after=None, undo=True, source="you", risk="Low", detail="", ok=True):
        try:
            return self._changes.add(kind, title, before, after, undo=undo, source=source, risk=risk, detail=detail, ok=ok)
        except Exception:  # noqa: BLE001
            log.exception("change history")
            return None

    def changes_list(self):
        return self._changes.list()

    def changes_summary(self):
        """For the Undo button in the top bar."""
        return self._changes.summary()

    def change_undo(self, cid):
        e = self._changes.get(cid)
        if not self._changes.undoable(e):
            return {"ok": False, "msg": "This change can't be undone (or was already undone)"}
        b = e["before"]
        try:
            k = e["kind"]
            if k == "tweak":
                self._tweaks[b["id"]].set(bool(b["on"]))
            elif k == "power_plan":
                if not tweaks.set_power_plan(b["guid"]):
                    raise RuntimeError("Windows didn't accept the power plan")
            elif k == "startup":
                item = next((s for s in tweaks.startup_items() if s.name == b["name"] and s.location == b["where"]), None)
                if not item:
                    raise RuntimeError("That app isn't in the startup list any more")
                tweaks.set_startup_enabled(item, bool(b["on"]))
            elif k == "fan_curve":
                if b["curve"]:
                    c = b["curve"]
                    self._fans.set_curve(b["cid"], c.get("source"), c.get("points"), bool(c.get("pump")))
                else:
                    self._fans.remove_curve(b["cid"])
            elif k == "fans_enabled":
                if b["on"]:
                    self._fans.enabled = True
                else:
                    self._fans.release_all()
            elif k == "fan_manual":
                self._hub.set_control(b["cid"], None)
            elif k == "gpu_power":
                self._hub.nvml.set_power_limit(float(b["watts"]))
            elif k == "gpu_tune":
                if not self._gpu.reset():
                    raise RuntimeError("The graphics card didn't accept the reset")
            elif k == "lighting":
                self._light.set_state(**b["state"])
            elif k == "light_device":
                self._light.set_device(b["key"], **b["settings"])
            elif k == "settings":
                self._save_settings(b)
                self._cfg.save()
            elif k == "appearance":
                self.ui_set(dict(b, _undo=True))
            elif k == "overlay":
                self.overlay_set(dict(b, _undo=True))
            elif k == "autostart":
                ok, msg = schedule.set_autostart(bool(b["on"]))
                if not ok:
                    raise RuntimeError(msg)
                self._cfg.data.setdefault("startup", {})["with_windows"] = bool(b["on"])
                self._cfg.save()
            elif k == "weekly":
                ok, msg = schedule.set_weekly(bool(b["on"]))
                if not ok:
                    raise RuntimeError(msg)
                self._cfg.data.setdefault("health", {})["weekly"] = bool(b["on"])
                self._cfg.save()
            elif k == "preset":
                self._undo_preset(b)
            elif k == "oc_windows":
                if not oc.set_cpu_windows(b.get("boost_mode"), b.get("max_state")):
                    raise RuntimeError("Windows didn't accept the change (needs admin)")
            else:
                return {"ok": False, "msg": "RigLab doesn't know how to undo this one"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "msg": f"Couldn't undo: {e}"}
        new = self._changes.add(e["kind"], "Undid: " + e["title"], before=e["after"], after=e["before"],
                                undo=False, source="undo", risk=e.get("risk", "Low"))
        self._changes.mark_undone(e["id"], new["id"])
        return {"ok": True, "msg": "Put back the way it was"}

    # ------------------------------------------------------------------ settings
    def settings(self):
        return self._cfg.data

    def save_settings(self, data):
        # the overlay saves itself as you change it (overlay_set), so a stale copy here never overwrites it
        import copy
        keys = ("alerts", "logging", "openrgb", "liquidctl", "minimize_to_tray", "poll_interval_ms", "start_minimized")
        before = {k: copy.deepcopy(self._cfg.data.get(k)) for k in keys}
        self._save_settings(data)
        changed = {k: before[k] for k in keys if self._cfg.data.get(k) != before[k]}
        if changed and not (data or {}).get("_undo"):
            self._log("settings", "Settings changed: " + ", ".join(SETTING_NAMES.get(k, k) for k in changed), before=changed,
                      after={k: copy.deepcopy(self._cfg.data.get(k)) for k in changed})
        return True

    def _save_settings(self, data):
        for k in ("alerts", "logging", "openrgb", "liquidctl"):
            if k in data:
                self._cfg[k].update(data[k])
        for k in ("minimize_to_tray", "poll_interval_ms", "start_minimized"):
            if k in data:
                self._cfg[k] = data[k]
        self._cfg.save()
        self._app.apply_overlay()
        return True

    def log_toggle(self):
        lg = self._app.csv_logger
        if lg.active:
            lg.stop()
            _open_path(lg.path.parent)
            return {"active": False, "path": str(lg.path)}
        p = lg.start()
        return {"active": True, "path": str(p)}

    def open_folder(self, which="data"):
        _open_path(app_dir() / ("" if which == "data" else which))
        return True

    def open_url(self, url):
        webbrowser.open(url)
        return True


_FIX_NAMES = {"redownload_lhm": "downloaded the sensor reader", "connect_openrgb": "started the lighting service",
              "restart_admin": "restarted RigLab as administrator", "retry_lhm": "retried the sensor reader"}


def _copy(v):
    import copy
    return copy.deepcopy(v)


def _size(b):
    for u in ("bytes", "KB", "MB", "GB"):
        if b < 1024 or u == "GB":
            return f"{b:.0f} {u}" if u == "bytes" else f"{b:.1f} {u}"
        b /= 1024


APPEARANCE_KEYS = {"theme": "theme", "accent": "highlight colour", "text_scale": "text size", "reduce_motion": "animations"}
SETTING_NAMES = {"alerts": "too-hot warnings", "logging": "logging", "openrgb": "lighting service", "liquidctl": "fan hubs",
                 "minimize_to_tray": "keep running", "poll_interval_ms": "sensor refresh", "start_minimized": "start hidden"}
THEME_IDS = ("dark", "light", "system", "dracula", "nord", "catppuccin", "gruvbox", "solarized", "tokyo", "onedark", "contrast")
ACCENTS = ("theme", "cyan", "violet", "emerald", "amber", "crimson", "ocean", "mono")
TEXT_SCALES = (0.8, 1, 1.25, 1.5)


def ui_values(values: dict) -> dict:
    """Only known appearance/tour keys with valid values get saved (anything else is ignored)."""
    out = {}
    for k, v in (values or {}).items():
        if k == "theme" and v in THEME_IDS:
            out[k] = v
        elif k == "accent" and v in ACCENTS:
            out[k] = v
        elif k == "start_page" and isinstance(v, str) and len(v) < 40:
            out[k] = v
        elif k == "view" and v in ("simple", "advanced"):
            out[k] = v
        elif k == "text_scale" and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = min(TEXT_SCALES, key=lambda x: abs(x - float(v)))
        elif k == "tour_done" and isinstance(v, bool):
            out[k] = v
        elif k == "reduce_motion" and isinstance(v, bool):
            out[k] = v
        elif k == "tips_hidden" and isinstance(v, list):
            out[k] = [str(x)[:40] for x in v][:100]
    return out


def _num(s: str) -> str:
    import re
    m = re.search(r"(\d+)", s)
    return m.group(1) if m else ""


def _open_path(p):
    p = str(p)
    if sys.platform == "win32":
        os.startfile(p)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", p])
