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

from .core import bench, crashes, diagnostics, lhm_setup, oc, report, sysinfo, tweaks
from .core.config import APP_VERSION, app_dir
from .core.fans import PRESETS
from .core import fx, gpuresults, gpusetup, gputune, ledmap
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
        self.startup_notes_list = []

    # ------------------------------------------------------------------ general
    def info(self):
        return {"version": APP_VERSION, "admin": tweaks.is_admin(), "platform": sys.platform,
                "status": dict(self._hub.status), "demo": False, "ui": self._cfg.data.get("ui", {})}

    def ui_set(self, values):
        """Appearance + start page (saved immediately, no Save button needed)."""
        self._cfg.data.setdefault("ui", {}).update({k: v for k, v in values.items() if k in ("theme", "accent", "start_page")})
        self._cfg.save()
        return self._cfg.data["ui"]

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
        return self._gpufix.run(action, data)

    def gpu_setup_job(self):
        return self._gpufix.status()

    def gpu_select(self, index):
        self._gpu.select(index)
        return self._gpu.state()

    def gpu_tune_apply(self, values):
        res = self._gpu.apply({k: v for k, v in values.items()})
        return {"result": res, "state": self._gpu.state()}

    def gpu_tune_reset(self):
        ok = self._gpu.reset()
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
        ok = oc.set_cpu_windows(boost_mode, max_state)
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
        self._light.set_state(**state)
        return True

    def light_device(self, key, settings):
        self._light.set_device(key, **settings)
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
        self._light.set_state(effect="Off")
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

    def fans_set_curve(self, cid, source, points, pump=False):
        self._fans.set_curve(cid, source, points, bool(pump))
        return True

    def fans_remove(self, cid):
        self._fans.remove_curve(cid)
        return True

    def fans_enable(self, on):
        if on:
            self._fans.enabled = True
        else:
            self._fans.release_all()
        return self._fans.enabled

    def fans_manual(self, cid, pct=None):
        if pct is not None and cid in self._fans.curves and self._fans.enabled:
            self._fans.release_all()
        return self._hub.set_control(cid, None if pct is None else max(20.0, float(pct)))

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
        startup = [{"i": i, "name": s.name, "cmd": s.command, "where": s.location, "on": s.enabled}
                   for i, s in enumerate(self._startup)]
        return {"tweaks": out, "plans": plans, "gpu": gpu, "startup": startup, "admin": tweaks.is_admin()}

    def tweak_set(self, tid, on):
        try:
            self._tweaks[tid].set(bool(on))
            return "ok"
        except Exception as e:  # noqa: BLE001
            return str(e)

    def restore_point(self):
        ok, msg = tweaks.create_restore_point()
        return {"ok": ok, "msg": msg}

    def set_power_plan(self, guid):
        return tweaks.set_power_plan(guid)

    def add_ultimate(self):
        return tweaks.add_ultimate_plan()

    def set_gpu_power(self, watts):
        try:
            self._hub.nvml.set_power_limit(float(watts))
            return "ok"
        except Exception as e:  # noqa: BLE001
            return str(e)

    def startup_set(self, i, on):
        try:
            tweaks.set_startup_enabled(self._startup[int(i)], bool(on))
            return "ok"
        except Exception as e:  # noqa: BLE001
            return str(e)

    def junk(self, clean=False):
        b, n = tweaks.clean_junk() if clean else tweaks.scan_junk()
        return {"bytes": b, "files": n}

    # ------------------------------------------------------------------ settings
    def settings(self):
        return self._cfg.data

    def save_settings(self, data):
        for k in ("alerts", "overlay", "logging", "openrgb", "liquidctl"):
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
