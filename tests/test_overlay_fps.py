"""Feature 1: FPS in the overlay - PresentMon parsing, live FPS maths, foreground matching and the shared capture."""
import pytest

from riglab.core import presentmon as pm

HEADER = "Application,ProcessID,SwapChainAddress,Runtime,SyncInterval,PresentFlags,MsBetweenPresents".split(",")


# ---------------------------------------------------------------- parsing
def test_parse_header_finds_columns():
    assert pm.parse_header(HEADER) == (0, 1, 6)


def test_parse_header_newer_frametime_column():
    assert pm.parse_header(["Application", "ProcessID", "FrameTime"]) == (0, 1, 2)


def test_parse_header_rejects_other_lines():
    assert pm.parse_header(["something", "else"]) is None
    assert pm.parse_header(["Application", "ProcessID"]) is None


def test_parse_line_reads_a_frame():
    idx = pm.parse_header(HEADER)
    assert pm.parse_line("game.exe,4242,0x1,DXGI,1,0,6.94".split(","), idx) == ("game.exe", 4242, 6.94)


@pytest.mark.parametrize("row", [
    "dwm.exe,10,0x1,DXGI,1,0,16.6",        # Windows' own compositor
    "game.exe,11,0x1,DXGI,1,0,0",          # nonsense frame time
    "game.exe,11,0x1,DXGI,1,0,abc",
    "game.exe,11",                          # truncated line
])
def test_parse_line_skips_rows_we_dont_use(row):
    assert pm.parse_line(row.split(","), pm.parse_header(HEADER)) is None


# ---------------------------------------------------------------- live maths
def frames(fps, seconds, end, ms=None):
    ms = ms or 1000 / fps
    n = int(fps * seconds)
    return [(end - seconds + (i + 1) * seconds / n, ms) for i in range(n)]


def test_live_reading_fps_and_frametime():
    r = pm.live_reading(frames(144, 3, end=100.0), now=100.0)
    assert 143 <= r["fps"] <= 145
    assert abs(r["frametime"] - 6.94) < 0.05
    assert abs(r["low1"] - 144) < 1.5            # perfectly even frames: 1% low = average


def test_live_reading_one_percent_low_catches_stutter():
    s = frames(100, 10, end=50.0)
    for i in range(0, len(s), 50):                # 2% of frames are 40 ms hitches
        s[i] = (s[i][0], 40.0)
    r = pm.live_reading(s, now=50.0)
    assert r["low1"] == 25.0                      # 1000 / 40 ms


def test_live_reading_none_when_not_rendering():
    assert pm.live_reading(frames(60, 2, end=10.0), now=13.0) is None      # last frame 3 s ago
    assert pm.live_reading([], now=1.0) is None


# ---------------------------------------------------------------- capture + foreground matching
def test_reading_for_foreground_game():
    cap = pm.Capture()
    for t, ms in frames(120, 2, end=500.0):
        cap.add("game.exe", 77, ms, now=t)
    for t, ms in frames(60, 2, end=500.0):
        cap.add("browser.exe", 88, ms, now=t)
    r = cap.reading_for(77, now=500.0)
    assert r["state"] == "ok" and r["app"] == "game.exe" and 119 <= r["fps"] <= 121
    assert cap.reading_for(88, now=500.0)["app"] == "browser.exe"


def test_reading_for_hides_row_when_nothing_rendering_in_front():
    cap = pm.Capture()
    for t, ms in frames(120, 2, end=500.0):
        cap.add("game.exe", 77, ms, now=t)
    assert cap.reading_for(1234, now=500.0) == {"state": "no_game"}      # desktop/other app in front
    assert cap.reading_for(None, now=500.0) == {"state": "no_game"}
    assert cap.reading_for(77, now=510.0) == {"state": "no_game"}        # game stopped presenting: no stale number


def test_live_history_is_bounded():
    cap = pm.Capture()
    for t, ms in frames(200, 60, end=1000.0):     # a minute of frames
        cap.add("game.exe", 5, ms, now=t)
    q = cap.live[5]
    assert q[-1][0] - q[0][0] <= pm.LIVE_WINDOW_S
    assert len(q) <= 3000
    assert not cap.frames                          # nothing kept for statistics unless a benchmark records


def test_recording_keeps_full_history_for_benchmarks():
    cap = pm.Capture()
    cap.start_recording()
    for t, ms in frames(100, 5, end=100.0):
        cap.add("game.exe", 5, ms, now=t)
    cap.stop_recording()
    assert len(cap.frames["game.exe"]) == 500
    assert cap.stats()["fps_avg"] == 100.0


# ---------------------------------------------------------------- one shared PresentMon
class FakeProc:
    def __init__(self):
        self.alive = True
        self.stdout = iter(())

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.alive = False


@pytest.fixture
def fake_presentmon(monkeypatch):
    started = []

    def start(self, allow_download=False):
        self.proc = FakeProc()
        started.append(self)
        return True
    monkeypatch.setattr(pm.Capture, "start", start)
    pm.release_all()
    yield started
    pm.release_all()


def test_overlay_and_benchmark_share_one_capture(fake_presentmon):
    a = pm.acquire("overlay")
    b = pm.acquire("benchmark", record=True)
    assert a is b and len(fake_presentmon) == 1          # never two PresentMon sessions
    assert a.recording == 1
    pm.release("benchmark")
    assert pm.shared() is a and a.recording == 0           # overlay still needs it
    pm.release("overlay")
    assert pm.shared() is None and not a.proc.alive        # nobody needs it: stopped


def test_benchmark_first_then_overlay(fake_presentmon):
    b = pm.acquire("benchmark", record=True)
    o = pm.acquire("overlay")
    assert b is o
    pm.release("overlay")
    assert pm.shared() is b                                 # benchmark keeps capturing
    pm.release("benchmark")
    assert pm.shared() is None


def test_release_all_stops_presentmon(fake_presentmon):
    cap = pm.acquire("overlay")
    pm.release_all()
    assert not cap.proc.alive and pm.holders() == []


def test_overlay_never_downloads_and_fails_quietly(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "exe_path", lambda: tmp_path / "missing" / "PresentMon.exe")
    monkeypatch.setattr(pm, "ensure", lambda *a, **k: pytest.fail("overlay must not download PresentMon"))
    pm.release_all()
    assert pm.acquire("overlay") is None
    assert pm.holders() == []
