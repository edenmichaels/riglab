"""Health score for the dial, and the Home presets (preview, risk, matching)."""
import pytest

from riglab.core import health, presets
from riglab.core.tweaks import PLAN_GUIDS


def items(*states):
    return [{"id": f"x{i}", "state": s} for i, s in enumerate(states)]


# ------------------------------------------------------------------ score
def test_all_green_is_100():
    assert health.score(items("good", "good", "good")) == 100


def test_yellow_and_red_cost_points():
    assert health.score(items("good", "warn")) == 92
    assert health.score(items("bad", "warn", "warn")) == 59
    assert health.score(items(*["bad"] * 6)) == 0            # never below 0


def test_grey_items_do_not_count_and_nothing_checked_is_none():
    assert health.score(items("good", "none")) == 100
    assert health.score(items("none", "none")) is None
    assert health.score([]) is None


@pytest.mark.parametrize("v,st", [(100, "good"), (80, "good"), (79, "warn"), (50, "warn"), (49, "bad"), (0, "bad"), (None, "none")])
def test_dial_colour(v, st):
    assert health.state(v) == st


def test_summary_lines():
    assert health.summary(100, items("good")) == "100% — Your PC is in good health."
    assert health.summary(92, items("good", "warn")).endswith("in good health. One thing needs checking.")
    assert health.summary(84, items("warn", "warn")).endswith("in good health. A few things need checking.")
    assert health.summary(59, items("bad", "warn", "warn")) == "59% — Your PC needs some attention. 3 things need checking."
    assert "problems that need fixing" in health.summary(25, items("bad", "bad", "bad"))
    assert health.summary(None, []) == "Not checked yet"


def test_quick_items_from_readings():
    r = {"cpu_temp": 60, "gpu_temp": 88, "ram_load": 40, "disk_free_pct": 4, "disk_free": 20 * 1024 ** 3,
         "fans": "good", "crashes": None, "drives": ["Good", "Caution"]}
    it = {i["id"]: i for i in health.quick_items(r)}
    assert it["cpu_temp"]["state"] == "good" and it["cpu_temp"]["page"] is None
    assert it["gpu_temp"]["state"] == "bad" and it["gpu_temp"]["page"] == "cooling" and it["gpu_temp"]["fix"]
    assert it["disk_free"]["state"] == "bad" and "20 GB free" in it["disk_free"]["say"]
    assert it["crashes"]["state"] == "none"                   # not scanned: grey, doesn't count
    assert it["drives"]["state"] == "warn"


def test_store_keeps_last_and_history(tmp_path):
    s = health.HealthStore(tmp_path / "h.json")
    s.add(health.result(items("good"), now=1))
    s.add(health.result(items("none"), now=2))               # nothing checked: saved as last, not charted
    again = health.HealthStore(tmp_path / "h.json")
    assert again.last["time"] == 2 and [h["score"] for h in again.history] == [100]


def test_damaged_store_starts_fresh(tmp_path):
    (tmp_path / "h.json").write_text("{nope", encoding="utf-8")
    s = health.HealthStore(tmp_path / "h.json")
    assert s.last is None and s.history == []


# ------------------------------------------------------------------ presets
PLANS = [{"guid": PLAN_GUIDS["balanced"], "name": "Balanced", "active": True},
         {"guid": PLAN_GUIDS["high"], "name": "High performance", "active": False},
         {"guid": PLAN_GUIDS["saver"], "name": "Power saver", "active": False}]
FANP = {"Silent": [[30, 20], [85, 100]], "Balanced": [[30, 25], [82, 100]], "Performance": [[30, 40], [78, 100]], "Full speed": [[0, 100], [100, 100]]}


def cur(plan="balanced", fans="Balanced", **tw):
    t = {"game_mode": True, "game_dvr": True, "notifications": True, "transparency": True}
    t.update(tw)
    plans = [dict(p, active=(p["guid"] == PLAN_GUIDS[plan])) for p in PLANS]
    ctrls = [{"id": f"/f/{i}", "name": f"Fan {i}", "curve": {"points": FANP[fans], "source": "/cpu"} if fans else None} for i in range(3)]
    return {"plans": plans, "tweaks": t, "fans": {"controls": ctrls, "enabled": bool(fans), "presets": FANP}}


def test_six_presets_in_order_and_balanced_is_default():
    c = presets.cards()
    assert [x["id"] for x in c] == list(presets.ORDER)
    assert [x["id"] for x in c if x["default"]] == ["balanced"]
    assert all(x["name"] and x["desc"] and x["icon"] for x in c)


def test_gaming_preview_lists_only_real_changes():
    p = presets.preview("gaming", cur())
    kinds = [(c["kind"], c["key"]) for c in p["changes"]]
    assert ("plan", "high") in kinds and ("fans", "Performance") in kinds
    assert ("tweak", "game_dvr") in kinds and ("tweak", "notifications") in kinds
    assert ("tweak", "game_mode") not in kinds                        # already on -> listed as already set
    assert any("already" in a for a in p["already"])
    assert all(c["text"] and c["tech"] for c in p["changes"])
    assert p["risk"] == "Low" and p["notice"] and "Change history" in p["undo"]


def test_preset_risk_is_the_highest_change():
    assert presets.highest(["None", "Low"]) == "Low"
    assert presets.highest(["Low", "High", "Medium"]) == "High"
    assert presets.highest([]) == "None"


def test_missing_plan_and_no_fans_are_skipped_not_failed():
    c = cur(fans=None)
    c["fans"]["controls"] = []                                               # RigLab can't see any fans
    c["plans"] = [p for p in c["plans"] if p["guid"] != PLAN_GUIDS["saver"]]
    p = presets.preview("power_saver", c)
    assert not any(x["kind"] in ("plan", "fans") for x in p["changes"])
    assert any("Save power" in s for s in p["skipped"]) and any("fans" in s for s in p["skipped"])


def test_full_speed_falls_back_to_ultimate():
    plans = [{"guid": PLAN_GUIDS["balanced"], "name": "Balanced", "active": True},
             {"guid": PLAN_GUIDS["ultimate"], "name": "Ultimate Performance", "active": False}]
    assert presets.plan_guid("high", plans) == PLAN_GUIDS["ultimate"]
    assert presets.plan_guid("saver", plans) is None


def test_matching_and_active():
    assert presets.matches("balanced", cur())
    assert presets.active(cur()) == "balanced"
    g = cur(plan="high", fans="Performance", game_dvr=False, notifications=False)
    assert presets.active(g) == "gaming"
    s = cur(plan="high", fans="Balanced", game_dvr=False, notifications=False)
    assert presets.active(s) == "streaming"
    assert presets.active(cur(plan="saver", fans="Balanced")) is None        # own mix -> nothing highlighted


def test_last_applied_wins_a_tie():
    c = cur(fans="Balanced", game_dvr=False, notifications=False)            # matches Work, not Balanced
    assert presets.active(c) == "work"
    both = cur(fans="Balanced")                                              # Balanced; Work needs notifications off
    assert presets.active(both, last="work") == "balanced"


def test_unknown_preset():
    with pytest.raises(KeyError):
        presets.preview("turbo", cur())
    assert presets.matches("turbo", cur()) is False


def test_tweaks_missing_on_this_pc_are_ignored():
    c = cur()
    del c["tweaks"]["notifications"]
    p = presets.preview("work", c)
    assert not any(x["key"] == "notifications" for x in p["changes"])
