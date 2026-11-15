"""Settings saved by RigLab 3.6.1 must keep loading: missing keys fall back to defaults, old values stay."""
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
    assert c["overlay"]["enabled"] is True and c["overlay"]["corner"] == "top-right"
    assert c["fan_curves"] == old["fan_curves"]          # old fan curves unchanged


def test_show_fps_off_by_default():
    assert DEFAULTS["overlay"]["show_fps"] is False
