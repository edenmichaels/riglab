"""3.11: first start after boot (lighting rescan with retries + reapply), central Undo (merging, summary,
greyed-out state), internet speed test (maths, parsing, offline), overlay helpers, Start with Windows,
and older settings still loading with the new keys."""
import json
import time
import types

import pytest

from riglab.core import boot, netspeed, overlay
from riglab.core.changes import ChangeLog
from riglab.core.config import DEFAULTS, Config


# ------------------------------------------------------------------ first start after boot
def test_first_start_since_boot():
    assert boot.first_start_since_boot(None, 1_700_000_000)            # never saved -> rescan
    assert not boot.first_start_since_boot(1_700_000_000, 1_700_000_001)  # same boot (tiny clock wobble)
    assert boot.first_start_since_boot(1_700_000_000, 1_700_090_000)   # restarted since
    assert not boot.first_start_since_boot(1_700_000_000, None)        # can't tell -> normal start, no rescan
    assert boot.first_start_since_boot("junk", 1_700_000_000)


# (3.12: the retry logic moved to lightwatch.py - see test_round_312.py)


# ------------------------------------------------------------------ central Undo
def test_quick_changes_merge_into_one_undo(tmp_path):
    log = ChangeLog(tmp_path / "c.json")
    log.add("appearance", "Theme: light", before={"theme": "dark"}, after={"theme": "light"}, merge="appearance", now=100)
    e = log.add("appearance", "Theme: ocean", before={"theme": "light"}, after={"theme": "ocean"}, merge="appearance", now=130)
    assert len(log.entries) == 1 and e["before"] == {"theme": "dark"} and e["after"] == {"theme": "ocean"}
    log.add("appearance", "Theme: forest", before={"theme": "ocean"}, after={"theme": "forest"}, merge="appearance", now=400)
    assert len(log.entries) == 2                                        # too long after: separate step


def test_undo_summary_and_greyed_out_state(tmp_path):
    log = ChangeLog(tmp_path / "c.json")
    s = log.summary()
    assert s["last"] is None and s["count"] == 0                       # nothing to undo -> button greyed out
    a = log.add("tweak", "Put games first: on", before={"on": False}, after={"on": True})
    log.add("junk", "Freed 1 GB", undo=False)
    s = log.summary()
    assert s["last"]["id"] == a["id"] and s["count"] == 1               # newest UNDOABLE change, not the newest change
    assert [r["undoable"] for r in s["recent"]] == [False, True]        # dropdown list, newest first
    u = log.add("tweak", "Undid: Put games first", source="undo")
    log.mark_undone(a["id"], u["id"])
    s = log.summary()
    assert s["last"] is None and s["count"] == 0
    assert len(log.summary(n=1)["recent"]) == 1


# ------------------------------------------------------------------ internet speed test
def test_throughput_skips_the_warm_up_second():
    samples = [(0.5, 10_000_000)] + [(1 + i * 0.5, 1_250_000) for i in range(1, 9)]   # 10 MB in the warm-up, then 10 MB/4 s
    assert netspeed.throughput(samples, 0, 5) == pytest.approx(20.0)                    # 10 MB * 8 / 4 s = 20 Mbps
    assert netspeed.throughput([], 0, 5) is None


def test_parse_ping_english_and_german_and_all_lost():
    en = "Reply from 1.1.1.1: bytes=32 time=12ms TTL=57\nReply from 1.1.1.1: bytes=32 time=14ms TTL=57\nRequest timed out.\n"
    p = netspeed.parse_ping(en, 3)
    assert p == {"times": [12, 14], "sent": 3, "lost": 1}
    de = "Antwort von 1.1.1.1: Bytes=32 Zeit=9ms TTL=57\nAntwort von 1.1.1.1: Bytes=32 Zeit<1ms TTL=57"
    assert netspeed.parse_ping(de, 2)["times"] == [9, 1]
    assert netspeed.parse_ping("", 10)["lost"] == 10


def test_ping_and_jitter():
    assert netspeed.ping_stats([10, 20, 10, 20]) == (15.0, 10.0)
    assert netspeed.ping_stats([12]) == (12.0, 0.0)
    assert netspeed.ping_stats([]) == (None, None)


WLAN = """
    Name                   : Wi-Fi
    State                  : connected
    SSID                   : MyHomeNetwork
    Radio type             : 802.11ax
    Channel                : 36
    Receive rate (Mbps)    : 1201
    Transmit rate (Mbps)   : 960
    Signal                 : 82%
"""


def test_wifi_details_no_network_name_kept():
    w = netspeed.parse_wlan(WLAN)
    assert w["signal"] == 82 and w["band"] == "5 GHz" and w["radio"] == "802.11ax" and w["rx_mbps"] == 1201
    assert "MyHomeNetwork" not in json.dumps(w)
    assert netspeed.parse_wlan("Channel : 6")["band"] == "2.4 GHz"


def test_connection_type_prefers_cable_and_adds_wifi_signal():
    wifi = {"Name": "Wi-Fi", "InterfaceDescription": "Intel Wi-Fi 6E AX210", "LinkSpeed": "1.2 Gbps", "PhysicalMediaType": "Native 802.11"}
    cable = {"Name": "Ethernet", "InterfaceDescription": "Realtek 2.5GbE", "LinkSpeed": "2.5 Gbps", "PhysicalMediaType": "802.3"}
    c = netspeed.connection([wifi], netspeed.parse_wlan(WLAN))
    assert c["type"] == "Wi-Fi" and c["signal"] == 82 and c["signal_words"] == "excellent" and c["link"] == "1.2 Gbps"
    assert netspeed.connection([wifi, cable], None)["type"] == "Ethernet"
    assert netspeed.connection([], None) == {"type": None}


def test_plain_summary():
    fast = {"download": 300, "upload": 40, "ping": 12, "jitter": 2, "loss": 0}
    assert netspeed.summary(fast)["say"] == "Fast enough for 4K streaming and online gaming."
    assert netspeed.summary(fast)["state"] == "good"
    laggy = dict(fast, ping=150)
    s = netspeed.summary(laggy)
    assert "laggy" in s["say"] and "ping" in s["say"] and s["state"] == "bad"
    assert netspeed.summary({"offline": True})["say"].startswith("No internet connection")
    assert netspeed.summary({"download": 1, "upload": 0.2, "ping": 40, "jitter": 3, "loss": 0})["say"].startswith("Slow")
    assert netspeed.light("download", 3) == "bad" and netspeed.light("ping", 30) == "good" and netspeed.light("loss", None) == "none"


def test_history_keeps_last_50_and_survives_damage(tmp_path):
    f = tmp_path / "netspeed.json"
    h = netspeed.History(f)
    for i in range(55):
        h.add({"time": i, "download": i, "junk": "x"})
    again = netspeed.History(f)
    assert len(again.items) == 50 and again.items[0]["time"] == 5 and "junk" not in again.items[0]
    f.write_text("{not json", encoding="utf-8")
    assert netspeed.History(f).items == []


def _speed_api(tmp_path):
    from riglab.api import Api
    a = object.__new__(Api)
    a._net, a._net_hist = None, netspeed.History(tmp_path / "n.json")
    return a


def _wait(a):
    for _ in range(500):
        st = a.netspeed_status()
        if not st["running"]:
            return st
        time.sleep(0.02)
    raise AssertionError("speed test didn't finish")


def test_speed_test_offline_says_so_and_saves_nothing(tmp_path, monkeypatch):
    from riglab.core import healthcheck
    monkeypatch.setattr(healthcheck, "is_online", lambda: False)
    monkeypatch.setattr(netspeed, "connection_info", lambda: {"type": None})
    monkeypatch.setattr(netspeed, "transfer", lambda *a, **k: pytest.fail("no data should be sent when offline"))
    a = _speed_api(tmp_path)
    a.netspeed_start()
    st = _wait(a)
    r = st["result"]
    assert r["offline"] and r["summary"]["say"].startswith("No internet connection")
    assert a.netspeed_history()["items"] == []


def test_speed_test_online_with_fake_server(tmp_path, monkeypatch):
    from riglab.core import healthcheck
    monkeypatch.setattr(healthcheck, "is_online", lambda: True)
    monkeypatch.setattr(netspeed, "connection_info", lambda: {"type": "Ethernet", "link": "1 Gbps"})
    monkeypatch.setattr(netspeed, "meta", lambda: {"ip": "203.0.113.5", "isp": "Example ISP", "server": "Cloudflare BNE"})
    monkeypatch.setattr(netspeed, "ping_text", lambda run, n=10: "")                 # ICMP blocked -> web fallback
    monkeypatch.setattr(netspeed, "http_latency", lambda **k: [10, 12, 11])
    monkeypatch.setattr(netspeed, "transfer", lambda d, **k: {"mbps": 250.0 if d == "down" else 30.0, "bytes": 5_000_000})
    a = _speed_api(tmp_path)
    a.netspeed_start()
    r = _wait(a)["result"]
    assert r["download"] == 250.0 and r["upload"] == 30.0 and r["ping"] == 11 and r["isp"] == "Example ISP"
    assert r["data_mb"] == 10.0 and r["lights"]["download"] == "good" and not r.get("error")
    h = a.netspeed_history()
    assert len(h["items"]) == 1 and "data" in h["note"]


def test_speed_test_server_down_is_an_error_not_a_zero(tmp_path, monkeypatch):
    from riglab.core import healthcheck
    monkeypatch.setattr(healthcheck, "is_online", lambda: True)
    monkeypatch.setattr(netspeed, "connection_info", lambda: {"type": None})
    monkeypatch.setattr(netspeed, "meta", lambda: {})
    monkeypatch.setattr(netspeed, "ping_text", lambda run, n=10: "")
    monkeypatch.setattr(netspeed, "http_latency", lambda **k: [])
    monkeypatch.setattr(netspeed, "transfer", lambda d, **k: {"mbps": None, "bytes": 0})
    a = _speed_api(tmp_path)
    a.netspeed_start()
    r = _wait(a)["result"]
    assert r["error"] and a.netspeed_history()["items"] == []


def test_speed_test_uses_cloudflare_not_ookla_or_mlab():
    assert netspeed.SERVER == "https://speed.cloudflare.com"
    assert "Cloudflare" in netspeed.__doc__ and "Ookla" in netspeed.__doc__ and "M-Lab" in netspeed.__doc__


# ------------------------------------------------------------------ overlay helpers
def test_exclusive_fullscreen_is_detected_and_explained_once():
    assert overlay.classify_fullscreen(3) == "exclusive"
    assert overlay.classify_fullscreen(2, (0, 0, 1920, 1080), (0, 0, 1920, 1080)) == "borderless"
    assert overlay.classify_fullscreen(2, (100, 100, 900, 700), (0, 0, 1920, 1080)) == "windowed"
    assert overlay.classify_fullscreen(2, (0, 0, 1920, 1080), (0, 0, 1920, 1080), is_shell=True) is None
    told = set()
    msg = overlay.exclusive_notice("exclusive", "Game.exe", told)
    assert "Borderless" in msg and "Windowed" in msg
    assert overlay.exclusive_notice("exclusive", "game.exe", told) is None        # not repeated
    assert overlay.exclusive_notice("borderless", "Other.exe", told) is None


def test_hold_to_move_and_edit_mode():
    assert overlay.parse_hold("Ctrl+Alt") == [0x11, 0x12]
    assert overlay.parse_hold("Ctrl") is None and overlay.parse_hold("Ctrl+Nope") is None and overlay.parse_hold("") is None
    assert overlay.edit_step(False, False, True) == (True, "start")     # hold keys -> movable
    assert overlay.edit_step(True, False, True) == (True, None)
    assert overlay.edit_step(True, False, False) == (False, "end")      # let go -> locked again (and saved)
    assert overlay.edit_step(False, True, False) == (True, "start")     # "Edit position" switch
    assert overlay.edit_step(False, False, False) == (False, None)


def test_window_size_follows_dpi_and_visibility_rules():
    assert overlay.window_size(200, 50, 1.0) == (202, 52)
    assert overlay.window_size(200, 50, 1.5) == (302, 77)
    assert overlay.window_size(200, 50, None) == (202, 52)
    assert overlay.window_size(200, 50, 99) == (202, 52)              # nonsense ignored
    assert overlay.should_be_visible({"enabled": True}, False, "borderless")
    assert not overlay.should_be_visible({"enabled": True}, True, None)
    assert not overlay.should_be_visible({"enabled": True}, False, "exclusive")
    assert not overlay.should_be_visible({"enabled": False}, False, None)


def test_overlay_move_hold_setting_migrates():
    o = overlay.migrate({"enabled": True})
    assert o["move_hold"] == "Ctrl+Alt"
    assert overlay.migrate({"move_hold": "nonsense"})["move_hold"] == "Ctrl+Alt"
    assert overlay.migrate({"move_hold": ""})["move_hold"] == ""


# ------------------------------------------------------------------ Start with Windows
def test_autostart_task_runs_minimised_as_admin_without_uac_prompt():
    from riglab.core import schedule
    args = schedule.autostart_args([r"C:\Program Files\RigLab\RigLab.exe"], r"PC\eden")
    assert args[:4] == ["schtasks", "/Create", "/TN", schedule.AUTOSTART_TASK]
    tr = args[args.index("/TR") + 1]
    assert tr.endswith("--minimized") and '"C:\\Program Files\\RigLab\\RigLab.exe"' in tr
    assert "ONLOGON" in args and "HIGHEST" in args and "/IT" in args
    with pytest.raises(ValueError):
        schedule.autostart_args(["C:\\" + "x" * 300], "u")


def test_start_with_windows_defaults_to_undecided_then_on():
    assert DEFAULTS["startup"]["with_windows"] is None        # 3.11 turns it on at first start (and logs it)
    assert DEFAULTS["system"]["last_boot"] is None


# ------------------------------------------------------------------ older settings still load
@pytest.mark.parametrize("old", [
    {"ui": {"theme": "light", "accent": "violet"}},                                               # 3.7
    {"ui": {"theme": "ocean", "view": "advanced", "text_scale": 1.25}, "overlay": {"enabled": True, "stats": ["fps"]}},  # 3.9
    {"ui": {"theme": "forest", "view": "simple", "tour_done": True}, "health": {"weekly": True},
     "overlay": {"enabled": True, "layout": "minimal", "hotkey": "Ctrl+Shift+O", "x": 10, "y": 20}},                   # 3.10
])
def test_older_settings_load_with_new_keys(tmp_path, old):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(old), encoding="utf-8")
    c = Config(f)
    assert c["ui"]["theme"] == old["ui"]["theme"]                  # theme choice kept (now on the Themes page)
    assert c["ui"]["reduce_motion"] is False
    assert c["startup"]["with_windows"] is None and c["system"]["last_boot"] is None
    o = overlay.migrate(c.data.get("overlay") or {})
    assert o["move_hold"] == "Ctrl+Alt"
    if "x" in old.get("overlay", {}):
        assert (o["x"], o["y"]) == (10, 20)                        # saved position kept


def test_speed_test_uses_windows_ping_when_it_answers(tmp_path, monkeypatch):
    from riglab.core import healthcheck
    monkeypatch.setattr(healthcheck, "is_online", lambda: True)
    monkeypatch.setattr(netspeed, "connection_info", lambda: {"type": None})
    monkeypatch.setattr(netspeed, "meta", lambda: {})
    out = "\n".join(f"Reply from 1.1.1.1: bytes=32 time={t}ms TTL=57" for t in (10, 12, 10, 12, 10, 12, 10, 12, 10))
    monkeypatch.setattr(netspeed, "ping_text", lambda run, n=10: out)               # 9 of 10 answered
    monkeypatch.setattr(netspeed, "http_latency", lambda **k: pytest.fail("not needed when ping works"))
    monkeypatch.setattr(netspeed, "transfer", lambda d, **k: {"mbps": 100.0, "bytes": 1})
    a = _speed_api(tmp_path)
    a.netspeed_start()
    r = _wait(a)["result"]
    assert r["ping"] == 10 and r["jitter"] == 2.0 and r["loss"] == 10.0


# ------------------------------------------------------------------ old screens after an update
def test_window_cache_is_cleared_but_saved_choices_are_kept(tmp_path):
    from riglab.core import webcache
    prof = tmp_path / "EBWebView" / "Default"
    for d in ("Cache/Cache_Data", "Code Cache/js", "GPUCache", "Service Worker/CacheStorage", "Local Storage/leveldb"):
        (prof / d).mkdir(parents=True)
        (prof / d / "f").write_text("x")
    gone = webcache.clear(tmp_path)
    assert not (prof / "Cache").exists() and not (prof / "Code Cache").exists() and not (prof / "GPUCache").exists()
    assert not (prof / "Service Worker" / "CacheStorage").exists()
    assert (prof / "Local Storage" / "leveldb" / "f").exists()          # theme/page choices stay
    assert len(gone) == 4
    assert webcache.clear(tmp_path / "missing") == []


def test_screens_version_matches_program_version():
    import re
    from pathlib import Path
    from riglab.core.config import APP_VERSION
    js = (Path(__file__).resolve().parents[1] / "riglab" / "web" / "js" / "app.js").read_text(encoding="utf-8")
    assert re.search(r'const WEB_VERSION = "([^"]+)"', js).group(1) == APP_VERSION
    demo = (Path(__file__).resolve().parents[1] / "riglab" / "web" / "js" / "demo.js").read_text(encoding="utf-8")
    assert f'version: "{APP_VERSION}"' in demo


def test_lights_page_says_what_the_after_restart_check_found():
    from riglab.api import boot_words
    assert boot_words(None) is None
    assert boot_words({"first_since_boot": False}) is None
    assert "checking" in boot_words({"first_since_boot": True, "running": True})["say"]
    ok = boot_words({"first_since_boot": True, "rescan": {"found": ["kb", "ram"], "missing": [], "reapplied": True}})
    assert ok["state"] == "good" and "found 2 devices" in ok["say"] and "reapplied" in ok["say"]
    miss = boot_words({"first_since_boot": True, "rescan": {"found": ["kb"], "missing": ["fans"], "reapplied": True}})
    assert miss["state"] == "warn" and "fans" in miss["say"]
