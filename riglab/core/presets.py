"""Whole-PC presets on Home (Gaming, Balanced, Quiet, Power Saver, Streaming / Creating, Work / Focus).

A preset is a set of switches RigLab already controls: the Windows power plan, the fan setting for every
fan, and a few Windows toggles. Nothing is applied until the person sees the preview and presses Apply.
Only settings that differ from the current ones become changes. Definitions and wording live in
web/js/explain_data.js ("presets", "plans", "fan_presets"). Everything here is pure, so it can be tested.

`current` (built by the API) looks like:
  {"plans": [{"guid", "name", "active"}], "tweaks": {id: True/False/None},
   "fans": {"controls": [{"id", "name", "curve"}], "enabled": bool, "presets": {name: points}}}
"""
from __future__ import annotations

from . import explain
from .tweaks import PLAN_GUIDS

ORDER = ("gaming", "balanced", "quiet", "power_saver", "streaming", "work")
_RANK = {r: i for i, r in enumerate(explain.RISKS)}


def definitions() -> dict:
    return explain.data().get("presets") or {}


def plan_guid(key: str, plans: list[dict]) -> str | None:
    """Find a power plan on this PC by Windows' fixed GUID. Full speed falls back to Ultimate if needed."""
    have = {p["guid"].lower(): p for p in plans or []}
    for k in ([key, "ultimate"] if key == "high" else [key]):
        g = PLAN_GUIDS.get(k)
        if g and g in have:
            return g
    return None


def highest(risks) -> str:
    rs = [r for r in risks if r in _RANK]
    return max(rs, key=_RANK.get) if rs else "None"


def _same(a, b) -> bool:
    try:
        return [list(map(float, p)) for p in a or []] == [list(map(float, p)) for p in b or []]
    except (TypeError, ValueError):
        return False


def preview(pid: str, current: dict) -> dict:
    """Everything the preview panel shows: changes (plain + technical), things already set, things skipped,
    what you'll notice, the overall risk and undo."""
    d = definitions().get(pid)
    if not d:
        raise KeyError(pid)
    data = explain.data()
    names, fan_names = data.get("plans") or {}, data.get("fan_presets") or {}
    want = d.get("set") or {}
    changes, already, skipped = [], [], []

    plans = current.get("plans") or []
    if want.get("plan"):
        key = want["plan"]
        plain = (names.get(key) or {}).get("name", key)
        guid = plan_guid(key, plans)
        active = next((p for p in plans if p.get("active")), None)
        if not plans:
            skipped.append("Power plans aren't available on this PC.")
        elif not guid:
            skipped.append(f"Your PC doesn't have the {plain} power plan, so the power plan stays as it is.")
        elif active and active["guid"].lower() == guid:
            already.append(f"Power plan is already {plain}.")
        else:
            tech = next((p["name"] for p in plans if p["guid"].lower() == guid), (names.get(key) or {}).get("tech", key))
            changes.append({"kind": "plan", "key": key, "to": guid, "risk": explain.action("power.plan")["risk"],
                            "text": f"Switches to the {plain} power plan.",
                            "tech": f"powercfg /setactive {guid}  ({tech}; now: {active['name'] if active else 'unknown'})"})

    fans = current.get("fans") or {}
    if want.get("fans"):
        fp = want["fans"]
        plain = fan_names.get(fp, fp)
        pts = (fans.get("presets") or {}).get(fp)
        ctrls = fans.get("controls") or []
        if not ctrls or pts is None:
            skipped.append("RigLab can't control your fans yet, so they stay as they are.")
        elif fans.get("enabled") and all(c.get("curve") and _same(c["curve"].get("points"), pts) for c in ctrls):
            already.append(f"Fans are already set to {plain}.")
        else:
            changes.append({"kind": "fans", "key": fp, "to": fp, "risk": explain.action("fans.preset")["risk"],
                            "text": f"Sets all {len(ctrls)} fan{'s' if len(ctrls) != 1 else ''} to {plain}.",
                            "tech": f"Fan curve preset '{fp}' {pts} on: " + ", ".join(c.get("name", c["id"]) for c in ctrls)
                            + ". Follows the processor temperature. Safety floors (20% fans / 60% pumps) stay on."})

    tw = current.get("tweaks") or {}
    for tid, on in (want.get("tweaks") or {}).items():
        a = explain.action("tweak." + tid)
        if tid not in tw:
            continue                                         # not on this PC (or not Windows)
        if tw[tid] is not None and bool(tw[tid]) == bool(on):
            already.append(f"“{a['label']}” is already {'on' if on else 'off'}.")
            continue
        changes.append({"kind": "tweak", "key": tid, "to": bool(on), "risk": a["risk"],
                        "text": f"Turns {'on' if on else 'off'} “{a['label']}”.",
                        "tech": f"Tweak '{tid}' -> {'on' if on else 'off'} (now: {_onoff(tw[tid])})"})

    risk = highest(c["risk"] for c in changes)
    return {"id": pid, "name": d.get("name", pid), "desc": d.get("desc", ""), "icon": d.get("icon", "dash"),
            "changes": changes, "already": already, "skipped": skipped, "notice": list(d.get("notice") or []),
            "risk": risk, "undo": "Yes - one click in Change history puts every setting back the way it was.",
            "nothing": not changes}


def _onoff(v) -> str:
    return "unknown" if v is None else "on" if v else "off"


def matches(pid: str, current: dict) -> bool:
    try:
        p = preview(pid, current)
    except KeyError:
        return False
    return not p["changes"] and bool(p["already"])


def active(current: dict, last: str | None = None) -> str | None:
    """The preset the PC currently matches. The one applied last wins a tie, then Balanced, then the rest."""
    order = ([last] if last in definitions() else []) + ["balanced"] + [k for k in ORDER if k != "balanced"]
    seen = set()
    for pid in order:
        if pid in seen or pid not in definitions():
            continue
        seen.add(pid)
        if matches(pid, current):
            return pid
    return None


def cards() -> list[dict]:
    defs = definitions()
    return [{"id": k, "name": defs[k].get("name", k), "desc": defs[k].get("desc", ""), "icon": defs[k].get("icon", "dash"),
             "default": bool(defs[k].get("default"))} for k in ORDER if k in defs]
