"""Stability / stress testing.

CPU workers repeat a deterministic calculation and compare each answer against the first
one - any mismatch means the CPU (or its overclock/undervolt) is making mistakes, the same
idea Prime95 uses. RAM test fills memory with patterns and reads them back.
While running, a monitor thread watches temps and clocks to spot thermal throttling.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import psutil


# ---------------------------------------------------------------- workers (top level for spawn)
def cpu_worker(stop, errors, iterations, mode: str):
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[k] = "1"
    import numpy as np
    n = 256 if mode == "heavy" else 64       # heavy = big FMA/AVX blocks = max heat
    rng = np.random.default_rng(99)
    a0 = rng.random((n, n))
    b = rng.random((n, n)) / n
    def work():
        a = a0.copy()
        for _ in range(8):
            a = a @ b
            a = np.sqrt(np.abs(a) + 1.0)
        return float(a.sum())

    # reference = the answer two runs in a row agree on (guards against a glitch in the very first run)
    ref = work()
    while not stop.is_set():
        r2 = work()
        if r2 == ref:
            break
        ref = r2
    while not stop.is_set():
        if work() != ref:   # a correct CPU always gets exactly the same answer
            with errors.get_lock():
                errors.value += 1
        with iterations.get_lock():
            iterations.value += 1


def ram_worker(stop, errors, iterations, megabytes: int):
    import numpy as np
    n = megabytes * 2**20 // 8
    try:
        buf = np.empty(n, dtype=np.uint64)
    except MemoryError:
        with errors.get_lock():
            errors.value += 1_000_000   # signals allocation failure
        return
    patterns = [0x0000000000000000, 0xFFFFFFFFFFFFFFFF, 0xAAAAAAAAAAAAAAAA, 0x5555555555555555]
    idx = np.arange(n, dtype=np.uint64)
    p = 0
    while not stop.is_set():
        pat = np.uint64(patterns[p % len(patterns)])
        p += 1
        buf.fill(pat)
        bad = int(np.count_nonzero(buf != pat))
        # address-in-address test catches stuck address lines
        np.bitwise_xor(idx, pat, out=buf)
        bad += int(np.count_nonzero(buf != (idx ^ pat)))
        if bad:
            with errors.get_lock():
                errors.value += bad
        with iterations.get_lock():
            iterations.value += 1


# ---------------------------------------------------------------- controller
@dataclass
class StressSample:
    t: float
    cpu_temp: float | None
    cpu_clock: float | None
    cpu_power: float | None
    cpu_load: float | None
    gpu_temp: float | None


@dataclass
class StressReport:
    duration_s: float = 0
    errors: int = 0
    iterations: int = 0
    max_cpu_temp: float | None = None
    avg_cpu_temp: float | None = None
    max_cpu_power: float | None = None
    peak_clock: float | None = None
    end_clock: float | None = None
    throttling: bool = False
    stopped_reason: str = "completed"
    samples: list[StressSample] = field(default_factory=list)
    started_at: float = 0.0
    per_core: dict = field(default_factory=dict)   # core-cycle mode: {core: {"seconds": s, "errors": n}}
    core_cycle: bool = False

    def verdict(self) -> tuple[str, str]:
        if self.errors >= 1_000_000:
            return "FAIL", "Could not allocate the requested memory - pick a smaller RAM test size."
        if self.errors:
            bad = [c for c, v in self.per_core.items() if v["errors"]]
            if bad:
                return "FAIL", (f"Calculation errors on core {', '.join(str(c) for c in bad)}. That core can't "
                                "hold your current Curve Optimizer value - make it less negative (e.g. +5) "
                                "for that core only.")
            return "FAIL", (f"{self.errors} calculation/memory errors. The system is unstable - "
                            "undo recent overclocks/undervolts, disable XMP to test, or check RAM.")
        if self.stopped_reason.startswith("safety"):
            return "STOPPED", self.stopped_reason
        if self.throttling:
            return "PASS (throttling)", ("No errors, but clocks dropped under heat. Check cooler mounting, "
                                         "paste, case airflow and fan curves.")
        if self.max_cpu_temp and self.max_cpu_temp >= 90:
            return "PASS (hot)", "No errors, but temps are high - stable for now, cooling has little headroom."
        return "PASS", "No errors and no throttling detected."


class StressTest:
    def __init__(self, hub, on_sample: Callable[[StressSample, dict], None] | None = None):
        self.hub = hub
        self.on_sample = on_sample
        self.procs: list[mp.Process] = []
        self.stop_evt = None
        self.errors = None
        self.iters = None
        self.report = StressReport()
        self._monitor: threading.Thread | None = None
        self._halt = threading.Event()
        self.running = False

    def start(self, cpu: bool = True, cpu_mode: str = "heavy", threads: int | None = None,
              ram_percent: int = 0, duration_s: int = 600, safety_temp: float = 98.0,
              core_cycle: bool = False, seconds_per_core: int = 60):
        """core_cycle: one light single-thread worker hopping core to core - the best test for
        Curve Optimizer / undervolt stability, because single-core boost is where CO fails."""
        ctx = mp.get_context("spawn")
        self.stop_evt = ctx.Event()
        self.errors = ctx.Value("q", 0)
        self.iters = ctx.Value("q", 0)
        self.report = StressReport(started_at=time.time(), core_cycle=core_cycle)
        self._halt.clear()
        self._cycle = None
        if core_cycle:
            p = ctx.Process(target=cpu_worker, args=(self.stop_evt, self.errors, self.iters, "light"), daemon=True)
            p.start()
            self.procs.append(p)
            phys = psutil.cpu_count(logical=False) or 1
            logical = psutil.cpu_count() or phys
            step = logical // phys if logical % phys == 0 else 1
            self._cycle = {"pid": p.pid, "cores": [(c, c * step) for c in range(phys)], "i": -1,
                           "every": max(10, seconds_per_core), "next": 0.0, "err0": 0}
            cpu = False
        if cpu:
            for _ in range(threads or os.cpu_count() or 1):
                p = ctx.Process(target=cpu_worker, args=(self.stop_evt, self.errors, self.iters, cpu_mode), daemon=True)
                p.start()
                self.procs.append(p)
        if ram_percent > 0:
            avail = psutil.virtual_memory().available
            total_mb = int(avail * ram_percent / 100 / 2**20)
            workers = max(1, min(4, total_mb // 1024))
            for _ in range(workers):
                p = ctx.Process(target=ram_worker, args=(self.stop_evt, self.errors, self.iters,
                                                         total_mb // workers), daemon=True)
                p.start()
                self.procs.append(p)
        self.running = True
        self._monitor = threading.Thread(target=self._watch, args=(duration_s, safety_temp), daemon=True)
        self._monitor.start()

    def _watch(self, duration_s: int, safety_temp: float):
        t0 = time.time()
        r = self.report
        temps = []
        while not self._halt.wait(1.0):
            el = time.time() - t0
            hub = self.hub
            ct = hub.cpu_temp()
            gt = hub.gpu_temp()
            cp = hub.cpu_power()
            cl = hub.cpu_load()
            s = StressSample(el, ct.value if ct else None, hub.cpu_clock(),
                             cp.value if cp else None, cl.value if cl else None, gt.value if gt else None)
            r.samples.append(s)
            if s.cpu_temp is not None:
                temps.append(s.cpu_temp)
                r.max_cpu_temp = max(r.max_cpu_temp or 0, s.cpu_temp)
                r.avg_cpu_temp = sum(temps) / len(temps)
            if s.cpu_power is not None:
                r.max_cpu_power = max(r.max_cpu_power or 0, s.cpu_power)
            if s.cpu_clock:
                if el < 30:
                    r.peak_clock = max(r.peak_clock or 0, s.cpu_clock)
                r.end_clock = s.cpu_clock
                # throttle = clocks >12% under the early peak while hot and still fully loaded
                if (r.peak_clock and el > 30 and s.cpu_clock < r.peak_clock * 0.88
                        and (s.cpu_temp or 0) >= 85 and (s.cpu_load or 100) > 90):
                    r.throttling = True
            r.errors = self.errors.value
            r.iterations = self.iters.value
            r.duration_s = el
            if self._cycle:
                self._rotate(el)
            if self.on_sample:
                self.on_sample(s, {"errors": r.errors, "iterations": r.iterations, "elapsed": el})
            if s.cpu_temp is not None and s.cpu_temp >= safety_temp:
                r.stopped_reason = f"safety stop: CPU reached {s.cpu_temp:.0f}°C (limit {safety_temp:.0f}°C)"
                break
            if el >= duration_s:
                break
            if self.procs and not any(p.is_alive() for p in self.procs):
                r.stopped_reason = "workers exited"
                break
        self._shutdown()

    def _rotate(self, el: float):
        c = self._cycle
        if c["i"] >= 0:  # book-keep the core we were on
            core = c["cores"][c["i"]][0]
            pc = self.report.per_core.setdefault(core, {"seconds": 0, "errors": 0})
            pc["seconds"] += 1
            pc["errors"] += self.errors.value - c["err0"]
            c["err0"] = self.errors.value
        if el >= c["next"]:
            c["i"] = (c["i"] + 1) % len(c["cores"])
            c["next"] = el + c["every"]
            try:
                psutil.Process(c["pid"]).cpu_affinity([c["cores"][c["i"]][1]])
            except Exception:  # noqa: BLE001
                pass

    @property
    def current_core(self):
        c = getattr(self, "_cycle", None)
        return c["cores"][c["i"]][0] if c and c["i"] >= 0 else None

    def stop(self, reason: str = "stopped by user"):
        if self.running:
            self.report.stopped_reason = reason
            self._halt.set()

    def _shutdown(self):
        if self.stop_evt:
            self.stop_evt.set()
        for p in self.procs:
            p.join(timeout=3)
            if p.is_alive():
                p.terminate()
        self.procs.clear()
        if self.errors is not None:
            self.report.errors = self.errors.value
            self.report.iterations = self.iters.value
        self.running = False
