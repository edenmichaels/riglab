"""Plain-English catalogue, traffic lights and the restore-point rules."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from riglab.core import explain

NOW = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)


def wmi(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S.000000-000")


# ------------------------------------------------------------------ catalogue
def test_catalogue_loads_from_the_shared_js_file():
    d = explain.data()
    assert len(d["actions"]) > 20 and "cpu_temp" in d["lights"] and set(d["risks"]) == set(explain.RISKS)


@pytest.mark.parametrize("aid", sorted(explain.data()["actions"]))
def test_every_action_is_fully_described(aid):
    a = explain.data()["actions"][aid]
    assert a["risk"] in explain.RISKS
    for k in ("label", "does", "notice", "undo"):
        assert a.get(k, "").strip(), f"{aid} is missing '{k}'"
    if a["risk"] in explain.GUARDED:          # risky things never show in Simple view
        assert a.get("advanced") is True, f"{aid} is {a['risk']} risk but not marked advanced"


def test_unknown_action_is_treated_carefully():
    a = explain.action("something.new")
    assert a["risk"] == "Low" and a["label"] == "something.new"
    assert explain.needs_guard("High") and explain.needs_guard("Medium") and explain.needs_guard("???")
    assert not explain.needs_guard("Low") and not explain.needs_guard("None")


# ------------------------------------------------------------------ traffic lights
def test_temperature_lights_follow_alert_limits():
    t = explain.lights({"cpu_temp_max": 90, "gpu_temp_max": 85, "drive_temp_max": 65})
    assert explain.light("cpu_temp", 60, t) == "good"
    assert explain.light("cpu_temp", 80, t) == "warn"
    assert explain.light("cpu_temp", 90, t) == "bad"
    assert explain.light("gpu_temp", 74.9, t) == "good" and explain.light("gpu_temp", 75, t) == "warn"
    t2 = explain.lights({"cpu_temp_max": 80})
    assert explain.light("cpu_temp", 75, t2) == "warn" and explain.light("cpu_temp", 80, t2) == "bad"


def test_low_is_bad_for_free_space():
    t = explain.lights()
    assert explain.light("disk_free", 50, t) == "good"
    assert explain.light("disk_free", 12, t) == "warn"
    assert explain.light("disk_free", 3, t) == "bad"


def test_missing_reading_is_grey_not_green():
    assert explain.light("cpu_temp", None) == "none"
    assert explain.light("no_such_reading", 50) == "none"


def test_crash_count_lights():
    t = explain.lights()
    assert [explain.light("crashes", n, t) for n in (0, 1, 2, 7)] == ["good", "warn", "bad", "bad"]


def test_worst():
    assert explain.worst(["good", "warn", "none"]) == "warn"
    assert explain.worst(["good", "bad", "warn"]) == "bad"
    assert explain.worst([]) == "none"


# ------------------------------------------------------------------ WMI time
def test_parse_wmi_time():
    t = explain.parse_wmi_time("20261117084200.123456-000")
    assert t == datetime(2026, 11, 17, 8, 42, tzinfo=timezone.utc)
    t = explain.parse_wmi_time("20261117184200.000000+600")          # Brisbane local time
    assert t == datetime(2026, 11, 17, 8, 42, tzinfo=timezone.utc)
    assert explain.parse_wmi_time("garbage") is None and explain.parse_wmi_time(None) is None


def test_fmt_when_is_friendly():
    s = explain.fmt_when(NOW - timedelta(minutes=5), NOW)
    assert s.startswith("today at ") and s.endswith(("am", "pm"))


# ------------------------------------------------------------------ restore points
def status(enabled=True, latest_age=None, policy_off=False):
    latest = None if latest_age is None else {"time": wmi(NOW - latest_age), "desc": "Windows Update"}
    return {"enabled": enabled, "policy_off": policy_off, "latest": latest}


@pytest.mark.parametrize("risk", ["None", "Low"])
def test_low_risk_never_needs_a_restore_point(risk):
    assert explain.plan_restore(risk, status(enabled=False), NOW)["go"] == "proceed"


@pytest.mark.parametrize("risk", ["Medium", "High"])
def test_recent_restore_point_counts_as_covered(risk):
    d = explain.plan_restore(risk, status(latest_age=timedelta(hours=3)), NOW)
    assert d["go"] == "proceed"
    assert "Windows Update" in d["msg"] and d["point"]["when"] in d["msg"]      # says which one, with date/time


def test_recent_point_counts_even_if_protection_now_reads_off():
    assert explain.plan_restore("High", status(enabled=False, latest_age=timedelta(hours=1)), NOW)["go"] == "proceed"


@pytest.mark.parametrize("risk", ["Medium", "High"])
def test_old_restore_point_means_make_a_new_one(risk):
    assert explain.plan_restore(risk, status(latest_age=timedelta(hours=25)), NOW)["go"] == "create"
    assert explain.plan_restore(risk, status(enabled=None), NOW)["go"] == "create"     # unknown: just try


def test_future_dated_point_is_not_trusted():
    assert explain.plan_restore("High", status(latest_age=-timedelta(days=2)), NOW)["go"] == "create"


def test_switched_off_blocks_high_and_asks_medium_with_a_fix():
    hi = explain.plan_restore("High", status(enabled=False), NOW)
    md = explain.plan_restore("Medium", status(enabled=False), NOW)
    assert hi["go"] == "block" and md["go"] == "ask"
    assert hi["fix"] == md["fix"] == "restore.enable"


def test_policy_off_has_no_fix_button():
    d = explain.plan_restore("High", status(enabled=False, policy_off=True), NOW)
    assert d["go"] == "block" and not d.get("fix")


def test_after_create_success():
    d = explain.after_create("High", True, "Restore point created", status(latest_age=timedelta(seconds=30)), NOW)
    assert d["go"] == "proceed" and d["msg"].startswith("Safety backup made")
    d = explain.after_create("High", True, "Restore point created", status(enabled=None), NOW)   # couldn't list it
    assert d["go"] == "proceed"


def test_after_create_failure():
    hi = explain.after_create("High", False, "Failed (needs admin)", status(), NOW)
    md = explain.after_create("Medium", False, "Failed (needs admin)", status(), NOW)
    assert hi["go"] == "block" and md["go"] == "ask" and "needs admin" in hi["msg"]
    off = explain.after_create("High", False, "System Protection is off for C:.", status(enabled=None), NOW)
    assert off["fix"] == "restore.enable"


# ------------------------------------------------------------------ added with the Simple view screens
JS = Path(__file__).resolve().parents[1] / "riglab" / "web" / "js"
_USE = re.compile(r"""\b(?:actionBtn|infoBtn|guarded|switchRow|infoCard|act)\(\s*["']([\w.]+)["']""")


def test_every_action_the_screens_use_has_an_info_card():
    """A typo in an action id would show an empty ⓘ card and default to Low risk - catch it here."""
    used = set()
    for f in JS.glob("*.js"):
        used |= set(_USE.findall(f.read_text(encoding="utf-8")))
    used = {u for u in used if not u.endswith(".")}         # "tweak." + id is checked below
    missing = sorted(u for u in used if u not in explain.data()["actions"])
    assert used and not missing, missing


def test_switch_rows_built_from_tweak_ids_exist():
    for tid in ("game_mode", "game_dvr", "mouse_accel", "transparency", "hags", "net_throttle"):
        assert "tweak." + tid in explain.data()["actions"]


def test_medium_and_high_actions_are_hidden_in_simple_view():
    for aid in explain.data()["actions"]:
        a = explain.action(aid)
        if a["risk"] in ("Medium", "High"):
            assert a["advanced"], aid


def test_serious_crashes_ignore_app_crashes():
    inc = [{"type": "bsod"}, {"type": "app"}, {"type": "reset"}, {"type": "gpu"}, {"type": "whea"}, "junk", None]
    assert explain.serious_crashes(inc) == 3
    assert explain.serious_crashes(None) == 0


def test_free_pct():
    assert explain.free_pct(1000, 250) == 25.0
    assert explain.free_pct(0, 0) is None
    assert explain.free_pct(None, 5) is None
