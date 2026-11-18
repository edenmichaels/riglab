"""Internet speed test.

Service: Cloudflare's speed test servers (speed.cloudflare.com/__down, /__up, /meta) - the same endpoints
Cloudflare's own MIT-licensed speed test library uses by default. Chosen over M-Lab NDT7 (M-Lab's policy asks
commercial apps to sponsor the platform, and every M-Lab result, including your IP address, is published as
open data) and the Ookla CLI (its licence doesn't allow use inside a commercial app). SERVER can be changed
in one place if a different service is ever needed.

Ping, jitter and packet loss come from Windows' own `ping` command to Cloudflare's 1.1.1.1 (packet loss can't
be measured over a normal web connection). Download/upload use several connections at once for about 8 seconds
each, ignoring the first second (connections are still speeding up), with a data cap.
Nothing runs unless you press Start, and the test is skipped with a clear message when you're offline.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .config import app_dir

SERVER = "https://speed.cloudflare.com"
PING_HOST = "1.1.1.1"
SECONDS = 8.0                    # per direction
WARMUP = 1.0
STREAMS = 4
MAX_DOWN = 250 * 1024 * 1024     # data caps (what the "uses some data" warning quotes)
MAX_UP = 60 * 1024 * 1024
DATA_NOTE = "A test uses some internet data: up to about 300 MB on a fast connection, much less on a slow one."
CREATE_NO_WINDOW = 0x08000000
UA = {"User-Agent": "RigLab speed test"}

# traffic lights for each reading (low_bad: lower is worse)
LIGHTS = {
    "download": {"warn": 25, "bad": 5, "low_bad": True},
    "upload": {"warn": 5, "bad": 1, "low_bad": True},
    "ping": {"warn": 60, "bad": 120},
    "jitter": {"warn": 20, "bad": 50},
    "loss": {"warn": 0.5, "bad": 3},
}


def light(kind: str, v) -> str:
    t = LIGHTS.get(kind)
    if v is None or t is None:
        return "none"
    if t.get("low_bad"):
        return "bad" if v < t["bad"] else "warn" if v < t["warn"] else "good"
    return "bad" if v >= t["bad"] else "warn" if v >= t["warn"] else "good"


# ------------------------------------------------------------------ pure maths and parsing (tested)
def throughput(samples: list[tuple[float, int]], start: float, end: float, warmup: float = WARMUP) -> float | None:
    """Megabits per second from (time, bytes) samples, ignoring the first `warmup` seconds."""
    t0 = start + warmup
    if end - t0 <= 0.2:
        t0 = start                                     # very short test: use everything
    got = sum(b for t, b in samples if t0 <= t <= end)
    span = end - t0
    return round(got * 8 / span / 1e6, 2) if span > 0 and got else None


PING_TIME = re.compile(r"(?:time|zeit|temps|tiempo|tempo)[=<]\s*(\d+)\s*ms", re.I)
PING_LOSS = re.compile(r"\((\d+)%\s*\w*")


def parse_ping(text: str, sent: int) -> dict:
    """Windows `ping -n N` output -> {times, sent, lost}. Works with English and most European Windows."""
    times = [int(m) for m in PING_TIME.findall(text or "")]
    lost = max(0, sent - len(times))
    return {"times": times, "sent": sent, "lost": lost}


def ping_text(run, n: int = 10) -> str:
    """Windows' own ping to 1.1.1.1 (run = the job's command runner). Empty when not on Windows."""
    if sys.platform != "win32":
        return ""
    rc, out = run(["ping", "-n", str(n), "-w", "1000", PING_HOST], timeout=40)
    return out or ""


def ping_stats(times: list[float]) -> tuple[float | None, float | None]:
    """(ping = median, jitter = average change between one ping and the next)."""
    if not times:
        return None, None
    ping = round(statistics.median(times), 1)
    jitter = round(sum(abs(a - b) for a, b in zip(times, times[1:])) / (len(times) - 1), 1) if len(times) > 1 else 0.0
    return ping, jitter


def parse_wlan(text: str) -> dict:
    """`netsh wlan show interfaces` -> signal %, band, Wi-Fi type and link rates (no network name is kept)."""
    out = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        kl = k.lower()
        if kl == "signal":
            m = re.match(r"(\d+)", v)
            out["signal"] = int(m.group(1)) if m else None
        elif kl == "band":
            out["band"] = v
        elif kl == "radio type":
            out["radio"] = v
        elif kl.startswith("receive rate"):
            out["rx_mbps"] = _num(v)
        elif kl.startswith("transmit rate"):
            out["tx_mbps"] = _num(v)
        elif kl == "channel":
            out["channel"] = _num(v)
        elif kl == "state":
            out["state"] = v
    if "band" not in out and out.get("channel"):
        out["band"] = "2.4 GHz" if out["channel"] <= 14 else "5 GHz" if out["channel"] <= 177 else "6 GHz"
    return out


def _num(v):
    m = re.search(r"(\d+(?:\.\d+)?)", str(v or ""))
    return float(m.group(1)) if m else None


def signal_words(pct) -> str | None:
    if pct is None:
        return None
    return "excellent" if pct >= 80 else "good" if pct >= 60 else "okay" if pct >= 40 else "weak"


def connection(adapters: list[dict], wlan: dict | None) -> dict:
    """adapters: Get-NetAdapter -Physical rows that are Up {Name, InterfaceDescription, LinkSpeed, PhysicalMediaType}."""
    up = [a for a in adapters or [] if a]
    if not up:
        return {"type": None}
    wifi = [a for a in up if "802.11" in str(a.get("PhysicalMediaType", "")) or re.search(r"wi-?fi|wireless|wlan", f"{a.get('Name')} {a.get('InterfaceDescription')}", re.I)]
    wired = [a for a in up if a not in wifi]
    a = wired[0] if wired else wifi[0]
    info = {"type": "Ethernet" if wired else "Wi-Fi", "adapter": a.get("InterfaceDescription") or a.get("Name"), "link": a.get("LinkSpeed")}
    if not wired and wlan:
        info.update({k: wlan.get(k) for k in ("signal", "band", "radio") if wlan.get(k) is not None})
        info["signal_words"] = signal_words(wlan.get("signal"))
    return info


ACTIVITIES = [
    ("4K streaming", lambda r: (r.get("download") or 0) >= 25),
    ("HD streaming and video calls", lambda r: (r.get("download") or 0) >= 8 and (r.get("upload") or 0) >= 2),
    ("online gaming", lambda r: r.get("ping") is not None and r["ping"] < 60 and (r.get("jitter") or 0) < 20 and (r.get("loss") or 0) < 1),
    ("uploading big files and streaming yourself", lambda r: (r.get("upload") or 0) >= 10),
]


def summary(r: dict) -> dict:
    """The plain-English line for Simple view, e.g. 'Fast enough for 4K streaming and online gaming.'"""
    if r.get("offline"):
        return {"state": "bad", "say": "No internet connection. Connect to the internet and try again."}
    if r.get("error"):
        return {"state": "none", "say": "The test didn't finish: " + r["error"]}
    ok = [name for name, test in ACTIVITIES if test(r)]
    no = [name for name, test in ACTIVITIES if not test(r)]
    states = [light(k, r.get(k)) for k in ("download", "upload", "ping", "jitter", "loss")]
    st = "bad" if "bad" in states else "warn" if "warn" in states else "good"
    if light("download", r.get("download")) == "bad":
        say = "Slow - web pages and videos may take a while to load."
        if "online gaming" in ok:
            say += " Online games should still be OK."
    elif "4K streaming" in ok and "online gaming" in ok:
        say = "Fast enough for 4K streaming and online gaming."
    elif ok:
        say = "Good enough for " + _and(ok[:2]) + "."
    else:
        say = "OK for browsing and standard video, but HD video and games may struggle."
    if "online gaming" in no and r.get("ping") is not None:
        why = "the delay (ping) is high" if r["ping"] >= 60 else "the delay jumps around (jitter)" if (r.get("jitter") or 0) >= 20 else "some data is getting lost"
        say += f" Online games may feel laggy because {why}."
    return {"state": st, "say": say, "good_for": ok, "not_for": no}


def _and(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


class History:
    """Past results in netspeed.json (last 50), apart from settings."""

    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "netspeed.json"
        self._lock = threading.Lock()
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []
        except (OSError, ValueError):
            self.items = []

    def add(self, r: dict) -> dict:
        keep = {k: r.get(k) for k in ("time", "download", "upload", "ping", "jitter", "loss", "server", "isp", "ip", "conn", "summary", "data_mb")}
        with self._lock:
            self.items = (self.items + [keep])[-50:]
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.items, indent=1), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                pass
        return keep


# ------------------------------------------------------------------ the network parts
def _open(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers=dict(UA, **({"Content-Type": "application/octet-stream"} if data else {})),
                                 method="POST" if data is not None else "GET")
    return urllib.request.urlopen(req, timeout=timeout)    # noqa: S310 - fixed https URL


def meta(server: str = SERVER) -> dict:
    try:
        with _open(server + "/meta", timeout=10) as r:
            m = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return {}
    loc = ", ".join(x for x in (m.get("city"), m.get("country")) if x)
    return {"ip": m.get("clientIp"), "isp": m.get("asOrganization"),
            "server": f"Cloudflare {m.get('colo') or ''}".strip() + (f" ({loc})" if loc else "")}


def http_latency(server: str = SERVER, n: int = 8, cancelled=lambda: False) -> list[float]:
    """Fallback ping when ICMP is blocked: time for a tiny request, minus the server's own processing time."""
    out = []
    for _ in range(n):
        if cancelled():
            break
        t = time.perf_counter()
        try:
            with _open(server + "/__down?bytes=0", timeout=5) as r:
                r.read()
                st = r.headers.get("Server-Timing", "")
        except Exception:  # noqa: BLE001
            continue
        ms = (time.perf_counter() - t) * 1000
        m = re.search(r"dur=([\d.]+)", st)
        out.append(round(max(0.1, ms - (float(m.group(1)) if m else 0)), 1))
    return out


def transfer(direction: str, server: str = SERVER, seconds: float = SECONDS, streams: int = STREAMS,
             cancelled=lambda: False, clock=time.perf_counter) -> dict:
    """Download or upload with several connections for `seconds`. Returns {"mbps", "bytes"}."""
    cap = MAX_DOWN if direction == "down" else MAX_UP
    samples: list[tuple[float, int]] = []
    lock = threading.Lock()
    total = [0]
    cap_at = []
    start = clock()
    end_at = start + seconds
    stop = threading.Event()

    def note(n):
        with lock:
            samples.append((clock(), n))
            total[0] += n
            if total[0] >= cap and not cap_at:
                cap_at.append(clock())
                stop.set()

    def worker():
        size = 1_000_000
        while not stop.is_set() and clock() < end_at and not cancelled():
            t = clock()
            try:
                if direction == "down":
                    with _open(f"{server}/__down?bytes={size}", timeout=10) as r:
                        while not stop.is_set() and not cancelled():
                            chunk = r.read(65536)
                            if not chunk:
                                break
                            note(len(chunk))
                            if clock() > end_at:
                                stop.set()
                else:
                    with _open(f"{server}/__up", data=b"0" * size, timeout=20) as r:
                        r.read()
                    note(size)
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
                continue
            took = max(0.05, clock() - t)
            size = int(min(25_000_000 if direction == "down" else 8_000_000, max(100_000, size * 1.5 / took)))  # aim for ~1.5 s per request
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(streams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(seconds + 25)
    end = min(cap_at[0] if cap_at else clock(), end_at)
    return {"mbps": throughput(samples, start, max(end, start + 0.01)), "bytes": total[0]}


def connection_info() -> dict:
    if sys.platform != "win32":
        return {"type": None}
    from .healthcheck import parse_json
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select Name,InterfaceDescription,LinkSpeed,PhysicalMediaType | ConvertTo-Json -Compress"],
                           capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        ad = parse_json(r.stdout)
        ad = ad if isinstance(ad, list) else [ad] if ad else []
    except (OSError, subprocess.SubprocessError):
        ad = []
    wl = None
    try:
        r = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW)
        wl = parse_wlan(r.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return connection(ad, wl)
