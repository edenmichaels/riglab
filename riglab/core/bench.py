"""Built-in benchmarks: CPU (single + multi), memory, disk. GPU lives in ui/gpu_test.py (OpenGL).

Scores are meant for comparing this PC against itself over time (before/after a tweak,
a new cooler, a BIOS change). Every run is saved to bench_history.json.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Callable

from .config import app_dir

Progress = Callable[[str, float], None]   # (message, 0..1)


@dataclass
class BenchResult:
    name: str
    score: float
    unit: str
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------- CPU workers (top level for spawn)
def _int_work(seconds: float) -> float:
    """Integer/branchy work: primes + hashing + sorting. Returns ops/sec."""
    end = time.perf_counter() + seconds
    ops = 0
    rnd = random.Random(1234)
    while time.perf_counter() < end:
        # sieve
        n = 20000
        sieve = bytearray(b"\x01") * (n + 1)
        sieve[0:2] = b"\x00\x00"
        for i in range(2, int(n ** 0.5) + 1):
            if sieve[i]:
                sieve[i * i::i] = bytes(len(range(i * i, n + 1, i)))
        # hashing-ish mixing
        h = 2166136261
        for i in range(5000):
            h = ((h ^ i) * 16777619) & 0xFFFFFFFF
        # sort
        data = [rnd.random() for _ in range(3000)]
        data.sort()
        ops += 1
    return ops / seconds


def _float_work(seconds: float) -> float:
    """Dense FP work via numpy matmul (single BLAS thread). Returns GFLOPS."""
    import numpy as np
    n = 384
    a = np.random.default_rng(1).random((n, n), dtype=np.float64)
    b = np.random.default_rng(2).random((n, n), dtype=np.float64)
    flops_per = 2 * n ** 3
    count = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        a = a @ b
        a *= 1.0 / (np.abs(a).max() + 1e-9)  # keep numbers sane
        count += 1
    return count * flops_per / (time.perf_counter() - t0) / 1e9


@contextmanager
def _single_thread_blas():
    keys = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
    old = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = "1"
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _pool_run(fn, workers: int, seconds: float) -> list[float]:
    with _single_thread_blas(), ProcessPoolExecutor(max_workers=workers) as ex:
        # warm-up so process start time isn't measured
        list(ex.map(fn, [0.2] * workers))
        return list(ex.map(fn, [seconds] * workers))


def bench_cpu(progress: Progress, seconds: float = 6.0) -> list[BenchResult]:
    threads = os.cpu_count() or 1
    progress("CPU single-core: integer", 0.05)
    st_int = _pool_run(_int_work, 1, seconds)[0]
    progress("CPU single-core: floating point", 0.25)
    st_fp = _pool_run(_float_work, 1, seconds)[0]
    progress(f"CPU multi-core ({threads} threads): integer", 0.45)
    mt_int = sum(_pool_run(_int_work, threads, seconds))
    progress(f"CPU multi-core ({threads} threads): floating point", 0.7)
    mt_fp = sum(_pool_run(_float_work, threads, seconds))
    single = math.sqrt(st_int * 10 * st_fp * 100)
    multi = math.sqrt(mt_int * 10 * mt_fp * 100)
    return [
        BenchResult("CPU single-core", round(single), "pts",
                    {"Integer ops/s": round(st_int, 1), "FP GFLOPS": round(st_fp, 2)}),
        BenchResult("CPU multi-core", round(multi), "pts",
                    {"Integer ops/s": round(mt_int, 1), "FP GFLOPS": round(mt_fp, 2),
                     "Threads": threads, "Scaling": f"{multi / max(single, 1e-9):.1f}x"}),
    ]


# ---------------------------------------------------------------- memory
def bench_memory(progress: Progress, size_mb: int = 512) -> list[BenchResult]:
    import numpy as np
    progress("Memory: bandwidth (copy)", 0.0)
    n = size_mb * 2**20 // 8
    src = np.ones(n, dtype=np.float64)
    dst = np.empty_like(src)
    np.copyto(dst, src)  # touch pages
    reps, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 3:
        np.copyto(dst, src)
        reps += 1
    copy_gbs = reps * 2 * src.nbytes / (time.perf_counter() - t0) / 1e9   # read + write

    progress("Memory: random access", 0.5)
    # random gathers from a buffer far bigger than any CPU cache -> stresses RAM latency + TLB
    big = src  # reuse the already-touched buffer
    idx = np.random.default_rng(7).integers(0, n, size=4_000_000)
    np.take(big, idx[:1000])
    reps, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 3:
        np.take(big, idx)
        reps += 1
    rand_mops = reps * idx.size / (time.perf_counter() - t0) / 1e6
    del src, dst, idx, big
    return [
        BenchResult("Memory bandwidth", round(copy_gbs, 1), "GB/s", {"Buffer": f"{size_mb} MB"}),
        BenchResult("Memory random access", round(rand_mops, 1), "M/s",
                    {"Note": "Random 8-byte reads per second across the buffer (latency-bound)"}),
    ]


# ---------------------------------------------------------------- disk
class _RawFile:
    """Unbuffered file I/O so Windows' cache doesn't fake the read speed."""

    ALIGN = 4096

    def __init__(self, path: str, write: bool):
        self.path, self.write = path, write
        self.win = sys.platform == "win32"
        if self.win:
            import ctypes
            from ctypes import wintypes
            self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self.k32.CreateFileW.restype = wintypes.HANDLE
            self.k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            self.k32.VirtualAlloc.restype = ctypes.c_void_p
            self.k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
            self.k32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
            self.k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            self.k32.WriteFile.argtypes = self.k32.ReadFile.argtypes
            self.k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                                  ctypes.c_void_p, wintypes.DWORD]
            self.k32.CloseHandle.argtypes = [wintypes.HANDLE]
            GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
            NO_BUFFERING, WRITE_THROUGH = 0x20000000, 0x80000000
            access = GENERIC_WRITE if write else GENERIC_READ
            disp = 2 if write else 3  # CREATE_ALWAYS / OPEN_EXISTING
            flags = NO_BUFFERING | (WRITE_THROUGH if write else 0)
            self.h = self.k32.CreateFileW(path, access, 0, None, disp, flags, None)
            if self.h in (None, ctypes.c_void_p(-1).value):
                raise OSError(ctypes.get_last_error(), "CreateFileW failed")
            self.ctypes, self.wt = ctypes, wintypes
        else:
            self.fh = open(path, "wb" if write else "rb", buffering=0)

    def buffer(self, size: int):
        if self.win:
            p = self.k32.VirtualAlloc(None, size, 0x3000, 0x04)  # MEM_COMMIT|RESERVE, RW
            buf = (self.ctypes.c_char * size).from_address(p)
            self.ctypes.memset(p, 0x5A, size)
            return p, buf
        b = bytearray(os.urandom(64) * (size // 64))
        return None, b

    def free(self, p, size):
        if self.win and p:
            self.k32.VirtualFree(p, 0, 0x8000)

    def seek(self, off: int):
        if self.win:
            self.k32.SetFilePointerEx(self.h, off, None, 0)
        else:
            self.fh.seek(off)

    def io(self, p, buf, size: int) -> int:
        if self.win:
            n = self.wt.DWORD(0)
            fn = self.k32.WriteFile if self.write else self.k32.ReadFile
            if not fn(self.h, p, size, self.ctypes.byref(n), None):
                raise OSError(self.ctypes.get_last_error(), "I/O failed")
            return n.value
        if self.write:
            return self.fh.write(buf)
        return self.fh.readinto(buf)

    def close(self):
        if self.win:
            self.k32.CloseHandle(self.h)
        else:
            if self.write:
                self.fh.flush()
                os.fsync(self.fh.fileno())
            self.fh.close()


def bench_disk(progress: Progress, folder: str | None = None, size_mb: int = 1024,
               cancel: threading.Event | None = None) -> list[BenchResult]:
    folder = folder or tempfile.gettempdir()
    path = os.path.join(folder, "riglab_disktest.bin")
    block = 1 << 20  # 1 MiB
    total = size_mb * block
    cancel = cancel or threading.Event()
    results = []
    try:
        # sequential write
        f = _RawFile(path, write=True)
        p, buf = f.buffer(block)
        t0 = time.perf_counter()
        written = 0
        while written < total and not cancel.is_set():
            written += f.io(p, buf, block)
            if written % (64 * block) == 0:
                progress(f"Disk: sequential write {written // block}/{size_mb} MB", 0.3 * written / total)
        f.free(p, block)
        f.close()
        wr = written / (time.perf_counter() - t0) / 1e6

        # sequential read
        f = _RawFile(path, write=False)
        p, buf = f.buffer(block)
        t0 = time.perf_counter()
        got = 0
        while got < written and not cancel.is_set():
            n = f.io(p, buf, block)
            if not n:
                break
            got += n
            if got % (64 * block) == 0:
                progress(f"Disk: sequential read {got // block}/{size_mb} MB", 0.3 + 0.3 * got / total)
        rd = got / (time.perf_counter() - t0) / 1e6
        f.free(p, block)

        # random 4K reads
        progress("Disk: random 4K reads", 0.65)
        small = 4096
        p, buf = f.buffer(small)
        blocks = written // small
        rng = random.Random(42)
        count, t0 = 0, time.perf_counter()
        while time.perf_counter() - t0 < 5 and not cancel.is_set():
            f.seek(rng.randrange(blocks) * small)
            f.io(p, buf, small)
            count += 1
        el = time.perf_counter() - t0
        f.free(p, small)
        f.close()
        iops = count / el
        cached = "" if sys.platform == "win32" else " (OS cache may inflate reads off Windows)"
        results = [
            BenchResult("Disk sequential write", round(wr), "MB/s", {"Test file": f"{size_mb} MB in {folder}"}),
            BenchResult("Disk sequential read", round(rd), "MB/s", {"Note": "Unbuffered" + cached}),
            BenchResult("Disk random 4K read", round(iops), "IOPS",
                        {"Avg latency": f"{el / max(count, 1) * 1e6:.0f} µs", "QD": 1}),
        ]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return results


# ---------------------------------------------------------------- history
HISTORY = app_dir() / "bench_history.json"


def save_run(results: list[BenchResult]) -> None:
    hist = load_history()
    hist.append({"time": time.strftime("%Y-%m-%d %H:%M"), "results": [asdict(r) for r in results]})
    HISTORY.write_text(json.dumps(hist[-100:], indent=1), encoding="utf-8")


def load_history() -> list[dict]:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def previous_best(name: str) -> float | None:
    vals = [r["score"] for run in load_history() for r in run["results"] if r["name"] == name]
    if not vals:
        return None
    return max(vals)
