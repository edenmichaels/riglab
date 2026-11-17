"""Settings saved by RigLab 3.6.1 must keep loading: missing keys fall back to defaults, old values stay."""
import pytest
import json

from riglab.core.config import DEFAULTS, Config


def test_old_settings_get_new_defaults(tmp_path):
    old = {"overlay": {"enabled": True, "sensors": [], "corner": "top-right", "opacity": 0.85},
           "fan_curves": {"/lpc/nct6798d/control/1": {"source": "/amdcpu/0/temperature/2",
                                                      "points": [[30, 25], [60, 50], [80, 100]], "pump": False}}}
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(old), encoding="utf-8")
    c = Config(f)
    assert c["overlay"]["show_fps"] is False            # new feature off by default
    assert c["overlay"]["mode"] == "full" and c["overlay"]["size"] == "m"   # looks exactly like before
    assert c["overlay"]["x"] is None and c["overlay"]["opacity"] == 0.85    # still uses its corner
    assert c["overlay"]["enabled"] is True and c["overlay"]["corner"] == "top-right"
    assert c["fan_curves"] == old["fan_curves"]          # old fan curves unchanged


def test_show_fps_off_by_default():
    assert DEFAULTS["overlay"]["show_fps"] is False


def test_370_settings_open_in_simple_view(tmp_path):
    old = {"ui": {"theme": "light", "accent": "violet", "start_page": "last"}, "alerts": {"cpu_temp_max": 85.0}}
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(old), encoding="utf-8")
    c = Config(f)
    assert c["ui"]["view"] == "simple"                   # new default
    assert c["ui"]["theme"] == "light" and c["ui"]["accent"] == "violet" and c["ui"]["start_page"] == "last"
    assert c["alerts"]["cpu_temp_max"] == 85.0 and c["alerts"]["gpu_temp_max"] == DEFAULTS["alerts"]["gpu_temp_max"]


def test_380_settings_get_no_preset(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"ui": {"view": "advanced", "theme": "dark"}}), encoding="utf-8")
    c = Config(f)
    assert c["ui"]["view"] == "advanced" and c["ui"]["preset"] is None


# ------------------------------------------------------------------ 3.10: every older settings file still loads
OLD_FILES = {
    "3.7.0": {"overlay": {"enabled": True, "mode": "fps_detail", "size": "l", "opacity": 0.5, "x": 100, "y": 80, "show_fps": False},
              "ui": {"theme": "light", "accent": "violet", "start_page": "home"},
              "fan_curves": {"/lpc/0/control/1": {"source": "/amdcpu/0/temperature/2", "points": [[30, 25], [80, 100]]}}},
    "3.8.0": {"overlay": {"enabled": True, "mode": "full", "show_fps": True}, "ui": {"theme": "dark", "accent": "cyan", "view": "advanced"}},
    "3.9.0": {"overlay": {"enabled": False, "mode": "full"}, "ui": {"theme": "system", "view": "simple", "preset": "gaming"}},
}


@pytest.mark.parametrize("ver", sorted(OLD_FILES))
def test_older_settings_files_load(tmp_path, ver):
    from riglab.core import overlay as ov
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(OLD_FILES[ver]), encoding="utf-8")
    c = Config(f)
    o = ov.migrate(c["overlay"])                         # what App() does on start
    assert c["ui"]["text_scale"] == 1 and c["ui"]["tour_done"] is False and c["ui"]["tips_hidden"] == []
    assert c["health"]["weekly"] is False
    assert o["stats"] and o["locked"] is True and o["minimised"] is False and o["hotkey"] == ""
    for k, v in OLD_FILES[ver]["ui"].items():
        assert c["ui"][k] == v                          # nothing they chose is lost
    if ver == "3.7.0":
        assert o["stats"] == ["fps", "low1", "frametime"] and o["x"] == 100 and o["size"] == "l" and o["opacity"] == 0.5
        assert c["fan_curves"] == OLD_FILES[ver]["fan_curves"]
    if ver == "3.8.0":
        assert o["stats"][:3] == ["fps", "low1", "frametime"] and "cpu_temp" in o["stats"]
    if ver == "3.9.0":
        assert o["stats"] == ["fps"] and c["ui"]["preset"] == "gaming"


def test_saving_and_reloading_keeps_new_settings(tmp_path):
    f = tmp_path / "settings.json"
    c = Config(f)
    c["ui"]["theme"], c["ui"]["text_scale"] = "dracula", 1.25
    c["overlay"].update({"stats": ["fps", "cpu_temp"], "x": 400, "y": 300, "locked": False, "minimised": True, "layout": "vertical"})
    c.save()
    again = Config(f)
    assert again["ui"]["theme"] == "dracula" and again["ui"]["text_scale"] == 1.25
    assert again["overlay"]["stats"] == ["fps", "cpu_temp"] and (again["overlay"]["x"], again["overlay"]["y"]) == (400, 300)
    assert again["overlay"]["minimised"] is True and again["overlay"]["layout"] == "vertical"
