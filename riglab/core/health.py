"""PC health score (0-100) for the dial on Home and PC Health, plus the saved results.

The quick check scores what RigLab can see quickly: temperatures, memory, free space, fans, drive health
and recent crashes. Part C adds the full Windows checks to the same items list, so the dial and the score
rules stay the same. Rules and wording come from web/js/explain_data.js ("score" and "lights").
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import explain
from .config import app_dir

MAX_HISTORY = 400


def rules() -> dict:
    s = explain.data().get("score") or {}
    return {"good": s.get("good", 80), "warn": s.get("warn", 50), "minus_warn": s.get("minus_warn", 8),
            "minus_bad": s.get("minus_bad", 25), "say": s.get("say") or {}}


def score(items) -> int | None:
    """100 minus a little for each yellow item and a lot for each red one. Grey (no reading) items don't count.
    None when nothing could be checked at all."""
    r = rules()
    counted = [i for i in items or [] if i.get("state") in ("good", "warn", "bad")]
    if not counted:
        return None
    lost = sum(r["minus_warn"] if i["state"] == "warn" else r["minus_bad"] if i["state"] == "bad" else 0 for i in counted)
    return max(0, min(100, 100 - lost))


def state(value) -> str:
    """Dial colour: green from 80, yellow from 50, red below."""
    if value is None:
        return "none"
    r = rules()
    return "good" if value >= r["good"] else "warn" if value >= r["warn"] else "bad"


def summary(value, items) -> str:
    """One line under the dial, e.g. '85% — Your PC is in good health. A few things need checking.'"""
    r = rules()
    st = state(value)
    if st == "none":
        return r["say"].get("none", "Not checked yet")
    n = sum(1 for i in items or [] if i.get("state") in ("warn", "bad"))
    if n == 0:
        more = ""
    elif n == 1:
        more = " One thing needs checking."
    elif st == "good":
        more = " A few things need checking."
    else:
        more = f" {n} things need checking."
    return f"{value}% — {r['say'].get(st, '')}{more}"


def _item(kind, value=None, state_=None, say=None, page=None, fix=None, table=None):
    st = state_ or explain.light(kind, value, table)
    lt = (table or explain.lights()).get(kind) or {}
    return {"id": kind, "title": lt.get("name", kind), "state": st, "say": say or (lt.get("say") or {}).get(st, ""),
            "page": page if st in ("warn", "bad") else None, "fix": fix if st in ("warn", "bad") else None}


def quick_items(r: dict, table: dict | None = None) -> list[dict]:
    """Turn readings into report-card items. r = {cpu_temp, gpu_temp, ram_load, disk_free_pct, disk_free,
    fans: 'good'|'warn'|'none', crashes: int|None, drives: ['Good'|'Caution'|'Bad', ...]}"""
    t = table or explain.lights()
    items = [
        _item("cpu_temp", r.get("cpu_temp"), page="cooling", fix="Make my fans work harder", table=t),
        _item("gpu_temp", r.get("gpu_temp"), page="cooling", fix="Make my fans work harder", table=t),
        _item("ram_load", r.get("ram_load"), table=t),
    ]
    free = _item("disk_free", r.get("disk_free_pct"), page="tweaks", fix="Free up space", table=t)
    if r.get("disk_free") is not None and free["state"] != "none":
        free["say"] += f" ({_gb(r['disk_free'])} free)"
    items.append(free)
    items.append(_item("fans", state_=r.get("fans") or "none", page="cooling", fix="Check my fans", table=t))
    items.append(_item("crashes", r.get("crashes"), page="crashes", fix="Find out why", table=t))
    drives = [d for d in r.get("drives") or [] if d in ("Good", "Caution", "Bad")]
    dst = "none" if not drives else "bad" if "Bad" in drives else "warn" if "Caution" in drives else "good"
    items.append(_item("drives", state_=dst, page="hardware", fix="See my drives", table=t))
    return items


def _gb(b) -> str:
    return f"{b / 1024 ** 3:.0f} GB" if b >= 10 * 1024 ** 3 else f"{b / 1024 ** 3:.1f} GB"


def result(items, kind="quick", now=None) -> dict:
    v = score(items)
    return {"time": now or time.time(), "kind": kind, "score": v, "state": state(v), "summary": summary(v, items), "items": items}


class HealthStore:
    """Last result plus a short score history (for the chart in Part C). Kept in health.json, apart from settings."""

    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "health.json"
        self._lock = threading.RLock()
        self.last: dict | None = None
        self.history: list[dict] = []
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.last = d.get("last") if isinstance(d.get("last"), dict) else None
            self.history = [h for h in d.get("history", []) if isinstance(h, dict)]
        except (OSError, ValueError, AttributeError):
            pass

    def add(self, res: dict) -> dict:
        with self._lock:
            self.last = res
            if res.get("score") is not None:
                self.history.append({"time": res["time"], "score": res["score"], "kind": res.get("kind")})
                self.history = self.history[-MAX_HISTORY:]
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"last": self.last, "history": self.history}, indent=1), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                pass
            return res
