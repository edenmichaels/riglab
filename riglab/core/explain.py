"""Plain-English layer: what each action does and how risky it is, traffic-light rules for readings,
and the restore-point rules for Medium/High risk actions.

The wording lives in web/js/explain_data.js so the screens (and demo mode) and Python share one copy.
Everything here is pure logic so it can be tested without Windows.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

RISKS = ("None", "Low", "Medium", "High")
GUARDED = ("Medium", "High")              # these ask "are you sure?" and need a restore point first
RECENT = timedelta(hours=24)              # a restore point this new counts as "covered"
_DATA = Path(__file__).resolve().parents[1] / "web" / "js" / "explain_data.js"


@lru_cache(maxsize=1)
def data() -> dict:
    """The shared catalogue (actions, lights, risks)."""
    try:
        text = _DATA.read_text(encoding="utf-8")
        body = text[text.index("{", text.index("\nwindow.EXPLAIN_DATA")):].strip().rstrip(";")
        return json.loads(body)
    except (OSError, ValueError):
        return {"risks": {}, "lights": {}, "actions": {}}


def action(aid: str) -> dict:
    """Catalogue entry with safe defaults. Unknown ids are treated as Low risk, never as risk-free."""
    a = dict(data()["actions"].get(aid) or {})
    a.setdefault("label", aid)
    a.setdefault("risk", "Low")
    a.setdefault("undo", "")
    a.setdefault("does", "")
    a.setdefault("notice", "")
    a.setdefault("advanced", a["risk"] in GUARDED)
    a["id"] = aid
    return a


def needs_guard(risk: str) -> bool:
    return risk in GUARDED or risk not in RISKS       # unknown risk -> be careful


# ------------------------------------------------------------------ traffic lights
def lights(alerts: dict | None = None) -> dict:
    """Light thresholds. Temperatures follow the user's alert limits (red at the limit, yellow 10° below)."""
    t = copy.deepcopy(data()["lights"])
    a = alerts or {}
    for kind, key in (("cpu_temp", "cpu_temp_max"), ("gpu_temp", "gpu_temp_max"), ("drive_temp", "drive_temp_max")):
        if kind in t and isinstance(a.get(key), (int, float)):
            t[kind]["bad"] = float(a[key])
            t[kind]["warn"] = float(a[key]) - 10
    return t


def light(kind: str, value, table: dict | None = None) -> str:
    """'good' / 'warn' / 'bad', or 'none' when there's no reading."""
    if value is None:
        return "none"
    t = (table or lights()).get(kind)
    if not t:
        return "none"
    v = float(value)
    if t.get("low_bad"):
        return "bad" if v <= t["bad"] else "warn" if v <= t["warn"] else "good"
    return "bad" if v >= t["bad"] else "warn" if v >= t["warn"] else "good"


def worst(states) -> str:
    order = {"bad": 3, "warn": 2, "good": 1, "none": 0}
    best = "none"
    for s in states:
        if order.get(s, 0) > order[best]:
            best = s
    return best


SERIOUS = ("bsod", "reset", "whea")          # blue screens, sudden restarts, hardware errors


def serious_crashes(incidents) -> int:
    """How many crash-center incidents count towards the 'Crashes' traffic light (app crashes don't)."""
    return sum(1 for i in incidents or [] if isinstance(i, dict) and i.get("type") in SERIOUS)


def free_pct(total, free) -> float | None:
    try:
        return round(float(free) / float(total) * 100, 1) if total else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ restore points
_WMI = re.compile(r"^(\d{4})(\d\d)(\d\d)(\d\d)(\d\d)(\d\d)(?:\.(\d+))?([+-]\d{1,4})?")


def parse_wmi_time(s) -> datetime | None:
    """'20261117084200.000000-000' (WMI/CIM text, offset in minutes) -> aware datetime."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    m = _WMI.match(str(s or "").strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss = (int(x) for x in m.groups()[:6])
    off = int(m.group(8) or 0)
    try:
        return datetime(y, mo, d, hh, mi, ss, tzinfo=timezone(timedelta(minutes=off)))
    except ValueError:
        return None


def fmt_when(dt: datetime, now: datetime | None = None) -> str:
    """Friendly local time, e.g. 'today at 6:42 pm' or 'Mon 16 Nov at 9:05 am'."""
    local = dt.astimezone()
    now_l = (now or datetime.now(timezone.utc)).astimezone()
    clock = local.strftime("%I:%M %p").lstrip("0").lower()
    if local.date() == now_l.date():
        return f"today at {clock}"
    if local.date() == (now_l - timedelta(days=1)).date():
        return f"yesterday at {clock}"
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')} at {clock}"


def _recent(status: dict, now: datetime) -> dict | None:
    p = status.get("latest")
    if not p:
        return None
    t = parse_wmi_time(p.get("time"))
    if t is None or t > now + timedelta(minutes=5) or now - t > RECENT:
        return None
    return {"time": t, "desc": p.get("desc") or "restore point"}


def _covered(p: dict, now: datetime, made: bool = False) -> dict:
    when = fmt_when(p["time"], now)
    msg = (f"Safety backup made {when}." if made else
           f"Windows already has a restore point from {when} (\"{p['desc']}\"). RigLab will use that one as your safety backup.")
    return {"go": "proceed", "msg": msg, "point": {"time": p["time"].isoformat(), "desc": p["desc"], "when": when}}


def _failed(risk: str, why: str, fix: str | None = None) -> dict:
    if risk == "High":
        return {"go": "block", "fix": fix,
                "msg": f"{why} This change is high risk, so RigLab won't make it without a safety backup."}
    return {"go": "ask", "fix": fix, "msg": f"{why} You can carry on without one, but you won't have an easy way back."}


def plan_restore(risk: str, status: dict, now: datetime | None = None) -> dict:
    """What to do before a change. status = {"enabled": bool|None, "policy_off": bool, "latest": {"time", "desc"}|None}.
    Returns go = proceed | create | ask | block."""
    now = now or datetime.now(timezone.utc)
    if not needs_guard(risk):
        return {"go": "proceed", "msg": ""}
    p = _recent(status, now)
    if p:
        return _covered(p, now)
    if status.get("policy_off"):
        return _failed(risk, "Restore points have been switched off by whoever manages this PC.")
    if status.get("enabled") is False:
        return _failed(risk, "Restore points are switched off on this PC, so RigLab can't make a safety backup.", "restore.enable")
    return {"go": "create", "msg": "Making a safety restore point first. This can take a minute."}


def after_create(risk: str, ok: bool, msg: str, status: dict, now: datetime | None = None) -> dict:
    """Decide after trying to make a restore point."""
    now = now or datetime.now(timezone.utc)
    p = _recent(status, now)
    if p:
        return _covered(p, now, made=ok)
    if ok:
        said = "already made a restore point" in (msg or "")
        return {"go": "proceed", "point": None,
                "msg": "Windows says it already made a restore point in the last 24 hours, so RigLab will use that one."
                if said else "Safety backup made."}
    fix = "restore.enable" if ("off" in (msg or "").lower() or status.get("enabled") is False) else None
    return _failed(risk, f"RigLab couldn't make a restore point ({(msg or 'no reason given').strip().rstrip('.')}).", fix)
