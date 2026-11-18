"""3.12: lighting watcher (start-up / wake / device-arrival checks, retry timing, reapply, vendor apps, log),
the rebuilt overlay (see-through picture, controller: click-through, edit, drag, lock, dot, hotkey, saved spot,
monitors and scaling, exclusive fullscreen), overlay settings/presets and the start-up log."""
import json
import types

import pytest
from PIL import Image

from riglab.core import lightwatch as lw
from riglab.core import overlay as ov
from riglab.core import ovrender
from riglab.core.eventlog import EventLog
from riglab.core.ovcontrol import OverlayController


# ------------------------------------------------------------------ lighting
class FakeEngine:
    """Devices appear only after `ready_after` fresh scans (like USB devices that weren't ready at boot)."""

    def __init__(self, devices, ready_after=1, first=None, fail_restarts=0):
        self.L = {"state": {"effect": "Static", "color": "#ff0000"}}
        self.all, self.ready_after, self.fail_restarts = devices, ready_after, fail_restarts
        self.keys = list(first if first is not None else [])
        self.client = object()
        self.paused = False
        self.msg = ""
        self.restarts = self.reads = 0
        self.applied = []

    def discover(self):
        self.reads += 1

    def full_rescan(self):
        self.restarts += 1
        if self.restarts <= self.fail_restarts:
            self.client = None
            self.msg = "OpenRGB exited straight away"
            return False
        self.client = object()
        if self.restarts >= self.ready_after:
            self.keys = list(self.all)
        return True

    def reapply(self):
        self.applied.append(dict(self.L["state"]))


DEVS = ["Logitech G560 Lightsync Speakers", "SteelSeries Apex 3", "Corsair Lighting Node Pro"]


def watch(engine, procs=frozenset(), **kw):
    slept = []
    w = lw.LightWatch(engine, events=EventLog(kw.pop("log_path")), processes=lambda: set(procs), sleep=slept.append,
                      clock=lambda: 1_000_000.0, **kw)
    return w, slept


def test_startup_finds_late_devices_with_a_real_fresh_scan(tmp_path):
    e = FakeEngine(DEVS, ready_after=1, first=["Corsair Lighting Node Pro"])     # only one was ready at first
    lw.remember(e.L, DEVS, now=999_000.0)
    w, slept = watch(e, log_path=tmp_path / "log.json")
    r = w.check("startup")
    assert r["ok"] and r["found"] == DEVS and e.restarts == 1                    # re-reading alone never finds them
    assert e.applied == [{"effect": "Static", "color": "#ff0000"}]                 # last effect reapplied
    assert slept == [4, 6]                                                         # read, read, then the fresh scan


def test_retry_timing_grows_and_lasts_about_two_minutes(tmp_path):
    e = FakeEngine(DEVS, ready_after=99)                                           # never comes back
    lw.remember(e.L, DEVS, now=999_000.0)
    w, slept = watch(e, log_path=tmp_path / "log.json")
    r = w.check("startup")
    assert not r["ok"] and r["tries"] == len(lw.SCHEDULES["startup"])
    assert slept == sorted(slept) and 100 <= sum(slept) <= 130                     # increasing waits, ~2 minutes
    assert e.restarts == 3                                                         # only a few fresh scans (each one blinks the lights)


def test_nothing_missing_means_no_rescan_on_a_normal_start(tmp_path):
    e = FakeEngine(DEVS, first=DEVS)
    lw.remember(e.L, DEVS, now=999_000.0)
    w, slept = watch(e, log_path=tmp_path / "log.json")
    r = w.check("startup")
    assert r["ok"] and r["tries"] == 1 and e.restarts == 0 and slept == []
    assert e.applied                                                               # still reapplied once


def test_wake_from_sleep_rescans_and_reapplies(tmp_path):
    e = FakeEngine(DEVS, ready_after=1, first=DEVS)
    lw.remember(e.L, DEVS, now=999_000.0)
    w, slept = watch(e, log_path=tmp_path / "log.json")
    r = w.check("wake")
    assert r["ok"] and e.restarts == 1 and slept[0] == 4 and e.applied


def test_device_plugged_in_gets_found_and_lit(tmp_path):
    e = FakeEngine(DEVS, ready_after=1, first=DEVS[:2])
    w, _ = watch(e, log_path=tmp_path / "log.json")
    r = w.check("device")
    assert e.restarts == 1 and "Corsair Lighting Node Pro" in r["found"] and e.applied
    assert set(lw.known_devices(e.L)) == set(DEVS)                                 # remembered for next time


def test_vendor_app_holding_a_device_is_named_with_what_to_do(tmp_path):
    e = FakeEngine(DEVS, ready_after=99, first=["Corsair Lighting Node Pro"])
    lw.remember(e.L, DEVS, now=999_000.0)
    notes = []
    w, _ = watch(e, procs={"lghub.exe", "explorer.exe"}, notes=notes, log_path=tmp_path / "log.json")
    r = w.check("startup")
    assert [b["app"] for b in r["blocked"]] == ["Logitech G HUB"]
    assert "Quit G HUB" in r["blocked"][0]["say"] and "G560" in r["blocked"][0]["say"]
    assert notes and notes[-1]["title"] == "Lighting device not found" and "G HUB" in notes[-1]["text"]
    gg = lw.blockers(["SteelSeries Apex 3"], {"steelseriesgg.exe"})
    assert gg[0]["app"] == "SteelSeries GG"
    icue = lw.blockers(["Corsair Lighting Node Pro"], {"icue.exe"})
    assert icue[0]["app"] == "Corsair iCUE"
    assert lw.blockers(["SteelSeries Apex 3"], {"lghub.exe"}) == []                # G HUB doesn't hold SteelSeries gear


def test_errors_are_logged_not_swallowed(tmp_path):
    e = FakeEngine(DEVS, ready_after=2, fail_restarts=1, first=[])
    lw.remember(e.L, DEVS, now=999_000.0)
    w, _ = watch(e, log_path=tmp_path / "log.json")
    r = w.check("startup")
    assert r["ok"] and r["errors"]
    log = w.events.items()
    assert any(x["kind"] == "error" and "OpenRGB exited" in x["text"] for x in log)
    assert any(x["kind"] == "found" for x in log) and any(x["kind"] == "reapply" for x in log)


def test_lighting_off_skips_and_says_so(tmp_path):
    e = FakeEngine(DEVS)
    w, _ = watch(e, enabled=lambda: False, log_path=tmp_path / "log.json")
    assert w.check("startup")["skipped"] and "turned off" in w.events.items()[0]["text"]


def test_known_devices_migrate_merge_and_expire():
    L = {"known_devices": ["A", "B"]}                                              # 3.11 saved a list
    assert sorted(lw.known_devices(L, now=100.0)) == ["A", "B"]
    lw.remember(L, ["C"], now=200.0)
    lw.remember(L, ["A"], now=200.0)                                               # a partial scan never removes B
    assert sorted(L["known_devices"]) == ["A", "B", "C"]
    L["known_devices"]["B"] = 200.0 - 31 * 86400                                   # not seen for a month
    assert sorted(lw.expected(L, now=200.0)) == ["A", "C"]


def test_only_lighting_makers_trigger_a_scan():
    assert lw.vid_of(r"\\?\HID#VID_046D&PID_0AB5&MI_03#7&1#{4d1e55b2}") == "046D"
    assert lw.is_lighting_vid("1038") and lw.is_lighting_vid("1b1c")
    assert not lw.is_lighting_vid("0781")                                          # a SanDisk USB stick
    assert not lw.is_lighting_vid(None)


def test_requests_are_merged_into_one_check(tmp_path):
    e = FakeEngine(DEVS, first=DEVS)
    w, _ = watch(e, log_path=tmp_path / "log.json")
    done = []
    w.check = lambda reason: done.append(reason)
    w._q.put("device")
    w._q.put("device")
    w._q.put("wake")
    w.idle = 0.01
    w._worker()                                                                    # drains the queue, then stops
    assert done == ["wake"]


def test_event_log_saves_trims_and_reads_back(tmp_path):
    f = tmp_path / "startup_log.json"
    log = EventLog(f, keep=5, clock=lambda: 1_700_000_000.0)
    for i in range(8):
        log.add("scan", f"step {i}")
    again = EventLog(f)
    assert [e["text"] for e in again.items()] == [f"step {i}" for i in (7, 6, 5, 4, 3)]
    assert "step 7" in again.text()
    f.write_text("garbage", encoding="utf-8")
    assert EventLog(f).items() == []


def test_devwatch_parses_guids():
    from riglab.core import devwatch
    g = devwatch.GUID.parse(devwatch.GUID_HID)
    assert hex(g.Data1) == "0x4d1e55b2" and g.Data4[7] == 0x30


# ------------------------------------------------------------------ overlay picture
SAMPLE = {"fps": {"state": "ok", "fps": 144.4, "low1": 98, "frametime": 6.9}, "cpu_temp": 62, "gpu_temp": 80,
          "cpu_load": 30, "gpu_load": 95, "ram": 40, "cpu_clock": 4950, "gpu_clock": 2600}


def corners_clear(img):
    a = img.getchannel("A")
    w, h = img.size
    return all(a.getpixel(p) == 0 for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)))


@pytest.mark.parametrize("preset", ["minimal", "standard", "full"])
@pytest.mark.parametrize("layout", ["horizontal", "vertical"])
def test_overlay_background_is_truly_see_through(preset, layout):
    o = ov.apply_preset(ov.migrate({}), preset)
    o["layout"] = layout
    f = ovrender.render(o, SAMPLE)
    assert f.image.mode == "RGBA" and corners_clear(f.image)                       # no box round the panel
    x0, y0, x1, y1 = f.regions["panel"]
    assert f.image.getchannel("A").getpixel(((x0 + x1) // 2, y0 + 3)) == round(255 * 0.85)  # panel at its opacity
    for bg in ((255, 255, 255), (0, 0, 0)):                                        # composited on light and dark games:
        canvas = Image.new("RGB", (f.size[0] + 40, f.size[1] + 40), bg)
        canvas.paste(f.image, (20, 20), f.image)
        assert canvas.getpixel((21, 21)) == bg                                      # the corner shows the game, not a box


def test_overlay_with_no_background_draws_only_text():
    o = dict(ov.migrate({}), opacity=0.1)
    f = ovrender.render(o, SAMPLE)
    a = f.image.getchannel("A")
    x0, y0, x1, y1 = f.regions["panel"]
    assert a.getpixel((x0 + 1, y1 - 1)) == 0                                        # no panel at all
    assert max(a.getdata()) == 255                                                 # but the text is solid


def test_overlay_premultiplied_pixels_for_windows():
    f = ovrender.render(ov.migrate({}), SAMPLE)
    data = ovrender.premultiplied_bgra(f.image)
    assert len(data) == f.size[0] * f.size[1] * 4
    assert data[:4] == b"\x00\x00\x00\x00"                                          # transparent = all zero (no colour leaks)


def test_overlay_values_never_show_none_or_nan():
    for key in ovrender.NAMES:
        v, u, st = ovrender.value_of(key, {"fps": {"state": "no_game"}, "cpu_temp": float("nan"), "gpu_temp": None})
        assert v == "—" and "None" not in v and "nan" not in v.lower()


def test_overlay_draws_bigger_at_windows_scaling_and_size():
    o = ov.apply_preset(ov.migrate({}), "standard")
    w100 = ovrender.render(o, SAMPLE, dpi_scale=1.0).size[0]
    w125 = ovrender.render(o, SAMPLE, dpi_scale=1.25).size[0]
    w150 = ovrender.render(o, SAMPLE, dpi_scale=1.5).size[0]
    assert w100 < w125 < w150 and abs(w150 / w100 - 1.5) < 0.12
    assert ovrender.render(dict(o, size="xl"), SAMPLE).size[0] > w100


def test_overlay_edit_mode_has_handle_outline_and_buttons():
    f = ovrender.render(ov.migrate({}), SAMPLE, editing=True)
    assert {"bar", "min", "done", "panel"} <= set(f.regions)
    assert f.regions["bar"][3] < f.regions["panel"][1]                              # the handle sits above the panel
    dot = ovrender.render(ov.migrate({}), SAMPLE, minimised=True)
    assert set(dot.regions) == {"dot"} and dot.size[0] < 50 and corners_clear(dot.image)


def test_overlay_text_colour_and_theme_follow_settings():
    o = dict(ov.migrate({}), text_color="#ff00ff", fps_color="plain")
    img = ovrender.render(o, SAMPLE).image.convert("RGBA")
    assert (255, 0, 255, 255) in set(img.getdata())
    light = ovrender.colours("light")
    dark = ovrender.colours("dark")
    assert light["panel"] != dark["panel"]
    assert ovrender.colours("nonsense")["panel"] == dark["panel"]


# ------------------------------------------------------------------ overlay controller
SCREENS = [(0, 0, 1920, 1040, 1.0), (1920, 0, 2560, 1400, 1.5)]


def ctl(cfg=None):
    store = {"o": ov.migrate(dict({"enabled": True}, **(cfg or {}))), "saves": 0}

    def save():
        store["saves"] += 1
    c = OverlayController(lambda: store["o"], save, data=lambda: SAMPLE)
    c.set_screens(SCREENS)
    return c, store


def test_clickthrough_by_default_and_hit_test():
    c, _ = ctl()
    show = c.compose()
    assert show.visible and show.clickthrough
    assert c.hit(10, 10) == "through"                                              # clicks go to the game


def test_edit_drag_lock_and_saved_position_survive_restart():
    c, store = ctl()
    c.compose()
    assert c.set_edit(True) == "start"
    show = c.compose()
    assert not show.clickthrough and c.editing
    bar = show.frame.regions["bar"]
    assert c.hit(bar[0] + 30, bar[1] + 5) == "drag"
    done = show.frame.regions["done"]
    assert c.hit(done[0] + 2, done[1] + 2) == "button"
    c.moving(600, 400)                                                             # Windows drags it
    assert c.compose().x == 600                                                    # not fought while dragging
    c.moved(600, 400)
    assert c.click(done[0] + 2, done[1] + 2) == "lock"
    assert not c.editing and store["o"]["locked"] and c.compose().clickthrough
    saved = (store["o"]["x"], store["o"]["y"])
    c2 = OverlayController(lambda: store["o"], lambda: None, data=lambda: SAMPLE)  # "restart RigLab"
    c2.set_screens(SCREENS)
    s2 = c2.compose()
    assert (s2.x, s2.y) == saved


def test_panel_stays_put_when_the_drag_bar_appears():
    c, store = ctl({"x": 300, "y": 300})
    a = c.compose()
    c.set_edit(True)
    b = c.compose()
    pa, pb = a.frame.regions["panel"], b.frame.regions["panel"]
    assert a.y + pa[1] == b.y + pb[1]                                              # panel on the same screen line


def test_hold_keys_edit_then_lock_on_release():
    c, store = ctl()
    c.compose()
    assert c.set_holding(True) == "start" and c.editing
    assert c.set_holding(False) == "end" and not c.editing and store["o"]["locked"]


def test_minimise_to_dot_and_restore():
    c, store = ctl()
    c.set_edit(True)
    show = c.compose()
    mn = show.frame.regions["min"]
    assert c.click(mn[0] + 2, mn[1] + 2) == "minimise"
    dot = c.compose()
    assert store["o"]["minimised"] and not dot.clickthrough and "dot" in dot.frame.regions   # the dot is clickable
    assert c.hit(5, 5) == "button"
    assert c.click(5, 5) == "restore" and not store["o"]["minimised"]
    assert c.compose().clickthrough


def test_hotkey_hides_and_shows_and_exclusive_fullscreen_hides():
    c, _ = ctl()
    c.toggle_hidden()
    assert not c.compose().visible
    c.toggle_hidden()
    assert c.compose().visible
    c.set_fullscreen("exclusive", "Game.exe")
    assert not c.compose().visible and c.status()["fullscreen"] == "exclusive"
    c.set_fullscreen("borderless", "Game.exe")
    assert c.compose().visible


def test_off_screen_position_comes_back_and_second_monitor_scaling():
    c, store = ctl({"x": 9000, "y": 9000})                                          # monitor unplugged
    s = c.compose()
    assert 0 <= s.x < 1920 + 2560 and 0 <= s.y < 1400
    c2, _ = ctl({"x": 2100, "y": 100})                                              # on the 150% monitor
    small = ctl({"x": 100, "y": 100})[0].compose().frame.size[0]
    assert c2.compose().frame.size[0] > small * 1.3


def test_snap_to_corner_on_drop():
    c, store = ctl({"snap": True})
    c.compose()
    c.set_edit(True)
    c.compose()
    c.moved(1800, 950)
    c.set_edit(False)
    w, h = c.size
    assert store["o"]["x"] > 1700 and store["o"]["y"] > 900


def test_broken_reading_never_takes_the_overlay_down():
    store = {"o": ov.migrate({"enabled": True})}

    def boom():
        raise RuntimeError("sensor died")
    c = OverlayController(lambda: store["o"], lambda: None, data=boom)
    assert c.compose().visible


# ------------------------------------------------------------------ overlay settings and presets
def test_overlay_presets_and_settings_save_and_load(tmp_path):
    from riglab.core.config import Config
    f = tmp_path / "settings.json"
    c = Config(f)
    o = ov.apply_preset(ov.migrate(c.data.get("overlay") or {}), "standard")
    o.update(layout="vertical", size="l", opacity=0.5, text_color="#ffffff", snap=True, hotkey="Ctrl+Shift+O")
    c.data["overlay"] = ov.migrate(o)
    c.save()
    again = ov.migrate(Config(f).data["overlay"])
    assert again["stats"] == ov.PRESETS["standard"] and again["preset"] == "standard"
    assert (again["layout"], again["size"], again["opacity"], again["snap"], again["hotkey"]) == ("vertical", "l", 0.5, True, "Ctrl+Shift+O")
    assert ov.migrate({})["stats"] == ["fps"]                                      # new users: Minimal
    assert json.loads(f.read_text(encoding="utf-8"))["overlay"]["text_color"] == "#ffffff"


def test_api_overlay_preview_is_a_picture_of_the_draft():
    from riglab.api import Api
    from riglab.core.config import Config
    a = object.__new__(Api)
    a._cfg = Config.__new__(Config)
    a._cfg.data = {"overlay": ov.migrate({}), "ui": {"theme": "dark"}}
    r = a.overlay_preview({"preset": "full", "layout": "vertical"}, "light")
    assert r["png"].startswith("data:image/png;base64,") and r["h"] > r["w"]       # full + vertical = tall
    assert a._cfg.data["overlay"]["stats"] == ["fps"]                                # preview doesn't apply anything
