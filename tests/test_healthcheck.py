"""Full health check: translations, parsers, offline/skipped handling, the job runner (progress, cancel) and the report."""
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from riglab.core import health, healthcheck as hc

NOW = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ Device Manager codes
@pytest.mark.parametrize("code,state", [(0, "good"), (10, "bad"), (43, "bad"), (28, "warn"), (14, "warn"), (22, "none"), (45, "none"), (999, "warn"), ("x", "warn")])
def test_cm_code_translation(code, state):
    st, words = hc.translate_cm(code)
    assert st == state and words and "code" not in words.lower() or code == 999


def test_every_known_code_has_plain_words():
    for code, (st, words) in hc.CM_CODES.items():
        assert st in ("good", "warn", "bad", "none") and len(words) > 8 and "ConfigManager" not in words


def test_devices_item():
    assert hc.devices_item([])["state"] == "good"
    it = hc.devices_item([{"Name": "Intel Wi-Fi", "ConfigManagerErrorCode": 43}, {"Name": "SM Bus", "ConfigManagerErrorCode": 28},
                          {"Name": "Old webcam", "ConfigManagerErrorCode": 22}])
    assert it["state"] == "bad" and "2 devices" in it["say"] and "Intel Wi-Fi" in it["say"]
    assert it["action"]["id"] == "open_devices" and "[43]" in it["details"] and "Old webcam" not in it["details"]
    one = hc.devices_item([{"Name": "SM Bus", "ConfigManagerErrorCode": 28}])
    assert one["state"] == "warn" and one["say"].startswith("SM Bus has no driver")


# ------------------------------------------------------------------ inputs / outputs
def dev(cls, name, status="OK"):
    return {"Class": cls, "FriendlyName": name, "Status": status}


def test_io_all_good():
    devs = [dev("Keyboard", "HID Keyboard"), dev("Mouse", "HID mouse"), dev("Monitor", "Dell"), dev("AudioEndpoint", "Speakers"),
            dev("Net", "Intel Ethernet"), dev("USB", "USB Root Hub")]
    it = hc.io_item(devs, net_up=1)
    assert it["state"] == "good" and len(it["lines"]) == 6 and "all working" in it["say"]


def test_io_problems():
    devs = [dev("Keyboard", "HID Keyboard"), dev("Mouse", "Mouse", "Error"), dev("USB", "Hub", "Degraded")]
    it = hc.io_item(devs, net_up=0)
    assert it["state"] == "bad"                                       # a broken mouse is red
    assert "Mouse or touchpad: 1 not working" in it["say"] and "no connection" in it["say"]
    assert hc.io_item([dev("Mouse", "m")])["state"] == "warn"            # no keyboard found -> yellow


# ------------------------------------------------------------------ drivers and updates: yellow, never red
def test_parse_date_formats():
    assert hc.parse_date("/Date(1600000000000)/").year == 2020
    assert hc.parse_date("20200101000000.000000-000").year == 2020
    assert hc.parse_date("2021-05-01T00:00:00Z").month == 5
    assert hc.parse_date("nonsense") is None and hc.parse_date(None) is None


def test_old_drivers_are_yellow_and_skip_windows_own():
    old = int((NOW - timedelta(days=1500)).timestamp() * 1000)
    new = int((NOW - timedelta(days=100)).timestamp() * 1000)
    drv = [{"DeviceName": "Realtek Audio", "DriverProviderName": "Realtek", "DriverDate": f"/Date({old})/", "DriverVersion": "6.0"},
           {"DeviceName": "PCI bus", "DriverProviderName": "Microsoft", "DriverDate": f"/Date({old})/"},
           {"DeviceName": "Generic", "DriverProviderName": "Intel", "DriverDate": "/Date(1150848000000)/"},     # 2006 inbox date
           {"DeviceName": "NVIDIA", "DriverProviderName": "NVIDIA", "DriverDate": f"/Date({new})/"}]
    it = hc.drivers_item(drv, NOW)
    assert it["state"] == "warn" and it["say"].startswith("1 driver is over 2 years old")
    assert "Realtek" in it["details"] and "PCI bus" not in it["details"]
    assert hc.drivers_item([], NOW)["state"] == "good"
    many = [dict(drv[0], DeviceName=f"Dev {i}") for i in range(50)]
    assert hc.drivers_item(many, NOW)["state"] == "warn"                 # never red, however many


def test_updates_never_red():
    assert hc.updates_item([])["state"] == "good"
    assert hc.updates_item(["KB1"] * 30)["state"] == "warn"
    r = hc.updates_item([], reboot_pending=True)
    assert r["state"] == "warn" and "restart" in r["say"]


# ------------------------------------------------------------------ sfc / DISM / Defender
def test_decode_utf16_sfc_output():
    raw = "Windows Resource Protection did not find any integrity violations.".encode("utf-16-le")
    assert "integrity violations" in hc.decode_output(raw)
    assert hc.decode_output(b"plain text") == "plain text"


@pytest.mark.parametrize("text,state,action", [
    ("Windows Resource Protection did not find any integrity violations.", "good", None),
    ("Windows Resource Protection found integrity violations.", "bad", "sfc_repair"),
    ("You must be an administrator running a console session", "none", None),
    ("Windows Resource Protection could not perform the requested operation.", "warn", None),
    ("something in another language", "warn", None)])
def test_sfc_parsing(text, state, action):
    it = hc.sfc_item(text, 0)
    assert it["state"] == state and (it.get("action") or {}).get("id") == action


@pytest.mark.parametrize("text,rc,state,action", [
    ("No component store corruption detected.\nThe operation completed successfully.", 0, "good", None),
    ("The component store is repairable.", 0, "bad", "dism_repair"),
    ("The component store is not repairable.", 0, "bad", None),
    ("Error: 740\nElevated permissions are required", 740, "none", None),
    ("", 0, "good", None), ("garbled", 87, "warn", None)])
def test_dism_parsing(text, rc, state, action):
    it = hc.dism_item(text, rc)
    assert it["state"] == state and (it.get("action") or {}).get("id") == action


def test_third_party_antivirus_is_a_plain_message_not_a_failure():
    st = {"AMRunningMode": "Passive mode", "AntivirusEnabled": False}
    av = [{"displayName": "Windows Defender"}, {"displayName": "Norton 360"}]
    p = hc.protection_item(st, av)
    assert p["state"] == "good" and "Norton 360" in p["say"] and p["third_party"] == "Norton 360"
    s = hc.scan_item(None, third_party="Norton 360")
    assert s["state"] == "none" and "Norton 360" in s["say"] and "scan" in s["say"]   # grey: doesn't hurt the score


def test_protection_states():
    assert hc.protection_item({"AntivirusEnabled": True, "AMRunningMode": "Normal", "RealTimeProtectionEnabled": True, "AntivirusSignatureAge": 1}, [])["state"] == "good"
    assert hc.protection_item({"AntivirusEnabled": True, "AMRunningMode": "Normal", "RealTimeProtectionEnabled": False}, [])["state"] == "bad"
    assert hc.protection_item({"AntivirusEnabled": True, "AMRunningMode": "Normal", "AntivirusSignatureAge": 20}, [])["state"] == "warn"
    assert hc.protection_item({}, [])["state"] == "bad"                 # nothing protecting the PC


def test_scan_exit_codes():
    assert hc.scan_item(0)["state"] == "good"
    assert hc.scan_item(2)["state"] == "bad" and hc.scan_item(2)["action"]["id"] == "open_security"
    assert hc.scan_item(None, cancelled=True)["state"] == "none"
    assert hc.scan_item(5)["state"] == "warn"


def test_memory_item():
    assert hc.memory_item([], NOW)["state"] == "none" and hc.memory_item([], NOW)["action"]["id"] == "memtest"
    ok = hc.memory_item([{"Id": 1201, "TimeCreated": (NOW - timedelta(days=3)).isoformat()}], NOW)
    assert ok["state"] == "good" and "3 days ago" in ok["say"]
    bad = hc.memory_item([{"Id": 1201, "TimeCreated": (NOW - timedelta(days=30)).isoformat()},
                          {"Id": 1202, "TimeCreated": (NOW - timedelta(days=2)).isoformat()}], NOW)
    assert bad["state"] == "bad"


def test_parse_json_skips_warnings():
    assert hc.parse_json('WARNING: blah\n[{"a":1}]') == [{"a": 1}]
    assert hc.parse_json('{"x": 2}') == {"x": 2}
    assert hc.parse_json("") is None and hc.parse_json("3") == 3 and hc.parse_json("nope") is None


def test_eta_text_and_defender_estimate():
    assert hc.fmt_eta(20) == "less than a minute left"
    assert hc.fmt_eta(600) == "about 10 minutes left"
    assert hc.fmt_eta(3900) == "about 1 hour 5 min left"
    assert hc.defender_estimate(None) == 2700
    assert hc.defender_estimate(10) == 600 and hc.defender_estimate(10 ** 15) == 3 * 3600


def test_full_check_has_all_steps_and_quick_does_not():
    full = [s.id for s in hc.build_steps("full", lambda c: [])]
    quick = [s.id for s in hc.build_steps("quick", lambda c: [])]
    for sid in ("virus_protection", "devices", "io", "memory"):
        assert sid in quick and sid in full
    for sid in ("updates", "drivers", "windows_image", "system_files", "virus_scan"):
        assert sid in full and sid not in quick
    assert full[-1] == "virus_scan"                                      # the longest one goes last
    assert [s.id for s in hc.build_steps("full", lambda c: []) if s.needs_internet] == ["updates"]


def test_every_fix_has_a_known_risk():
    for fid, f in hc.FIXES.items():
        assert f["risk"] in ("None", "Low", "Medium", "High") and f["label"]
        assert ("cmd" in f) or ("open" in f)
    assert hc.FIXES["sfc_repair"]["risk"] == "Medium" and hc.FIXES["dism_repair"]["online"]


# ------------------------------------------------------------------ job runner
class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def item(i, st="good"):
    return {"id": i, "title": i, "state": st, "say": i}


def test_job_runs_steps_and_scores():
    steps = [hc.Step("a", "A", 10, lambda c: [item("a")]), hc.Step("b", "B", 10, lambda c: [item("b", "warn")])]
    got = []
    j = hc.CheckJob("quick", steps)
    j.on_done = got.append
    j.start(background=False)
    st = j.status()
    assert not st["running"] and st["progress"] == 1.0 and st["result"]["score"] == 92 and got == [st["result"]]


def test_offline_steps_are_skipped_not_failed():
    called = []
    steps = [hc.Step("a", "A", 1, lambda c: [item("a")]),
             hc.Step("updates", "Checking for updates", 1, lambda c: called.append(1) or [item("u")], needs_internet=True, title="Windows updates")]
    j = hc.CheckJob("full", steps, online=False).start(background=False)
    u = [i for i in j.items if i["id"] == "updates"][0]
    assert not called and u["state"] == "none" and "no internet" in u["say"].lower() and u["title"] == "Windows updates"
    assert j.result["score"] == 100                                    # skipped doesn't lower the score


def test_a_broken_step_does_not_stop_the_others():
    def boom(c):
        raise RuntimeError("WMI broke")
    j = hc.CheckJob("quick", [hc.Step("x", "X", 1, boom, title="Devices"), hc.Step("y", "Y", 1, lambda c: [item("y")])]).start(background=False)
    assert [i["id"] for i in j.items] == ["x", "y"] and j.items[0]["state"] == "none" and "WMI broke" in j.items[0]["details"]


def test_progress_and_time_left():
    clk = Clock()
    gate = threading.Event()
    steps = [hc.Step("a", "A", 100, lambda c: gate.wait(5) and [item("a")]), hc.Step("b", "B", 300, lambda c: [item("b")])]
    j = hc.CheckJob("full", steps, clock=clk)
    p0, left0 = j.progress()
    assert p0 == 0 and left0 == 400
    j.start()
    time.sleep(0.1)
    clk.t = 50
    p, left = j.progress()
    assert 0.12 < p < 0.13 and left == 350                              # 50 of 400 done
    clk.t = 500                                                         # step a runs long: never negative, never 100%
    p2, left2 = j.progress()
    assert p2 <= 0.99 and left2 >= 300
    st = j.status()
    assert st["running"] and st["step"] == "A" and st["eta_text"]
    gate.set()
    j.thread.join(5)
    assert j.status()["progress"] == 1.0


def test_cancel_stops_and_saves_nothing():
    started = threading.Event()
    later = []

    def slow(c):
        started.set()
        while not c.cancelled():
            time.sleep(0.01)
        return [item("slow")]
    got = []
    j = hc.CheckJob("full", [hc.Step("s", "S", 60, slow), hc.Step("t", "T", 1, lambda c: later.append(1) or [item("t")])])
    j.on_done = got.append
    j.start()
    started.wait(5)
    j.cancel()
    j.thread.join(5)
    st = j.status()
    assert st["cancelled"] and not st["running"] and st["result"] is None and not later and not got


def test_ctx_run_kills_the_process_on_cancel():
    j = hc.CheckJob("full", [])
    ctx = hc.Ctx(j)
    t = threading.Timer(0.5, j.cancel)
    t.start()
    t0 = time.monotonic()
    rc, _ = ctx.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60)
    assert rc is None and time.monotonic() - t0 < 15


def test_ctx_run_returns_output():
    rc, out = hc.Ctx(hc.CheckJob("x", [])).run([sys.executable, "-c", "print('hello')"], timeout=30)
    assert rc == 0 and "hello" in out


# ------------------------------------------------------------------ score with the full check items + report
def test_full_items_feed_the_same_score():
    items = [item("cpu"), hc.drivers_item([], NOW), hc.updates_item(["KB1"]), hc.scan_item(None, third_party="Norton"),
             hc.sfc_item("found integrity violations", 0)]
    r = health.result(items, kind="full")
    assert r["score"] == 100 - 8 - 25 and r["state"] == "warn" and r["kind"] == "full"


def test_report_text():
    r = health.result([hc.updates_item(["KB5031455 Cumulative Update"]), item("cpu")], kind="full")
    t = health.report_text(r, "3.10.0")
    assert "RigLab 3.10.0" in t and "Full check" in t and "Health score: 92 / 100" in t
    assert t.index("Worth checking") < t.index("[Good]") and "KB5031455" in t
