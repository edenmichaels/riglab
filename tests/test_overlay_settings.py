"""Overlay settings: migrating 3.7-3.9 settings, presets, stats, snapping, the lock, drag tracking and hotkeys."""
import pytest

from riglab.core import overlay as ov
from riglab.core.config import DEFAULTS

MAIN = (0, 0, 1920, 1080)
RIGHT = (1920, 0, 2560, 1440)


def test_new_install_defaults_to_minimal_fps_counter_and_locked():
    o = ov.migrate(DEFAULTS["overlay"])
    assert o["stats"] == ["fps"] and o["preset"] == "minimal" and o["locked"] is True
    assert o["minimised"] is False and o["snap"] is False and o["hotkey"] == "" and o["text_color"] == "theme"


@pytest.mark.parametrize("old, stats", [
    ({"enabled": False, "mode": "full", "show_fps": False}, ["fps"]),                       # never used it
    ({"enabled": True, "mode": "full", "show_fps": False}, ["cpu_temp", "cpu_load", "gpu_temp", "gpu_load", "ram"]),
    ({"enabled": True, "mode": "full", "show_fps": True}, ["fps", "low1", "frametime", "cpu_temp", "cpu_load", "gpu_temp", "gpu_load", "ram"]),
    ({"enabled": True, "mode": "fps_low"}, ["fps", "low1"]),
    ({"enabled": True, "mode": "fps_detail"}, ["fps", "low1", "frametime"]),
    ({"enabled": True, "mode": "fps_graph"}, ["fps", "graph"]),
])
def test_older_overlay_settings_keep_what_you_chose(old, stats):
    o = ov.migrate(dict(old, stats=None, x=300, y=200, size="l", opacity=0.4, fps_color="auto"))
    assert o["stats"] == stats and o["x"] == 300 and o["y"] == 200 and o["size"] == "l" and o["opacity"] == 0.4


def test_bad_values_are_repaired():
    o = ov.migrate({"stats": ["fps", "banana", "fps", "ram"], "layout": "diagonal", "size": "huge", "opacity": "x",
                    "text_color": "javascript:", "corner": "middle", "locked": 0})
    assert o["stats"] == ["fps", "ram"] and o["layout"] == "horizontal" and o["size"] == "m" and o["opacity"] == 0.85
    assert o["text_color"] == "theme" and o["corner"] == "top-left" and o["locked"] is False and o["preset"] == "custom"
    assert ov.migrate({"stats": []})["stats"] == ["fps"]
    assert ov.migrate({"stats": None, "text_color": "#ff8800"})["text_color"] == "#ff8800"


def test_presets():
    assert ov.PRESETS["minimal"] == ["fps"]
    assert ov.PRESETS["standard"] == ["fps", "cpu_temp", "gpu_temp"]
    assert set(ov.PRESETS["full"]) >= {"fps", "low1", "frametime", "cpu_temp", "gpu_temp", "cpu_load", "gpu_load", "ram", "cpu_clock", "gpu_clock"}
    o = ov.apply_preset({"stats": ["fps"]}, "full")
    assert o["preset"] == "full" and o["layout"] == "vertical"
    assert ov.preset_of(["fps", "cpu_temp", "gpu_temp"]) == "standard" and ov.preset_of(["ram"]) == "custom"
    assert ov.apply_preset({"stats": ["ram"]}, "nope")["stats"] == ["ram"]


@pytest.mark.parametrize("o, expected", [
    ({"enabled": True, "stats": ["cpu_temp", "gpu_temp"]}, False),        # no FPS stat: PresentMon never runs
    ({"enabled": True, "stats": ["graph"]}, True),
    ({"enabled": False, "stats": ["fps"]}, False),
])
def test_presentmon_only_for_fps_stats(o, expected):
    assert ov.needs_fps(o) is expected


def test_clickthrough_follows_lock_and_dot():
    assert ov.clickthrough({"locked": True}) is True
    assert ov.clickthrough({"locked": False}) is False
    assert ov.clickthrough({"locked": True, "minimised": True}) is False       # the dot must be clickable


def test_drop_stays_inside_the_screen_edges():
    assert ov.drop_position({}, -50, 1070, 200, 60, [MAIN]) == (0, 1080 - 60)
    assert ov.drop_position({}, 1900, 500, 200, 60, [MAIN, RIGHT]) == (1920, 500)      # mostly on the right monitor


@pytest.mark.parametrize("x, y, corner", [(100, 100, "top-left"), (1700, 50, "top-right"), (40, 900, "bottom-left"), (1500, 800, "bottom-right")])
def test_snap_to_nearest_corner(x, y, corner):
    c, _ = ov.nearest_corner(x, y, 200, 60, [MAIN])
    assert c == corner
    assert ov.drop_position({"snap": True}, x, y, 200, 60, [MAIN]) == ov.corner_position(corner, 200, 60, MAIN)


def test_snap_uses_the_monitor_it_was_dropped_on():
    x, y = ov.drop_position({"snap": True}, 4300, 1300, 200, 60, [MAIN, RIGHT])
    assert x > 1920 and y > 1000


def test_drag_tracker_reports_settled_once():
    t = ov.DragTracker((10, 10))
    assert t.feed((10, 10)) is None
    assert t.feed((50, 60)) == "moving" and t.feed((90, 60)) == "moving"
    assert t.feed((90, 60)) == "settled"
    assert t.feed((90, 60)) is None and t.feed(None) is None


@pytest.mark.parametrize("text, ok", [("Ctrl+Shift+O", True), ("Alt+F10", True), ("F9", True), ("ctrl + `", True),
                                      ("O", False), ("Ctrl+", False), ("Ctrl+Shift", False), ("Ctrl+O+P", False), ("", False), (None, False), ("Ctrl+Banana", False)])
def test_parse_hotkey(text, ok):
    assert (ov.parse_hotkey(text) is not None) is ok


def test_hotkey_codes():
    mods, vk = ov.parse_hotkey("Ctrl+Shift+O")
    assert vk == ord("O") and mods & 0x2 and mods & 0x4 and mods & 0x4000
    assert ov.parse_hotkey("F10")[1] == 0x79
    assert ov.hotkey_label("ctrl+shift+o") == "Ctrl+Shift+O" and ov.hotkey_label("alt+f10") == "Alt+F10" and ov.hotkey_label("nope") == ""
