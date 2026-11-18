"""Overlay styles, sizes and placement (dragging, corners, unplugged monitors)."""
import pytest

from riglab.core import overlay as ov

MAIN = (0, 0, 1920, 1080)
RIGHT = (1920, 0, 2560, 1440)          # second monitor to the right


def test_unknown_style_falls_back_to_full():
    assert ov.norm_mode("banana") == "full" and ov.norm_mode(None) == "full"


@pytest.mark.parametrize("o, expected", [
    ({"enabled": False, "mode": "fps"}, False),                     # overlay off: never runs PresentMon
    ({"enabled": True, "mode": "full", "show_fps": False}, False),
    ({"enabled": True, "mode": "full", "show_fps": True}, True),
    ({"enabled": True, "mode": "fps"}, True),                        # every counter style needs FPS
    ({"enabled": True, "mode": "fps_graph", "show_fps": False}, True),
])
def test_needs_fps(o, expected):
    assert ov.needs_fps(o) is expected


def test_guess_size_grows_with_text_size_and_stats():
    small = ov.guess_size({"stats": ["fps"], "size": "s"})
    large = ov.guess_size({"stats": ["fps"], "size": "l"})
    assert large[0] > small[0] and large[1] > small[1]
    full_h = ov.guess_size({"stats": ov.PRESETS["full"], "layout": "horizontal"})
    full_v = ov.guess_size({"stats": ov.PRESETS["full"], "layout": "vertical"})
    assert full_h[0] > full_v[0] and full_v[1] > full_h[1]
    assert ov.guess_size({"stats": ["fps"]})[0] < full_h[0]
    assert ov.guess_size({"stats": ["fps"], "minimised": True}) == (ov.DOT, ov.DOT)


@pytest.mark.parametrize("corner, xy", [
    ("top-left", (12, 12)), ("top-right", (1920 - 300 - 12, 12)),
    ("bottom-left", (12, 1080 - 110 - 12 - 48)), ("bottom-right", (1920 - 300 - 12, 1080 - 110 - 12 - 48)),
    ("nonsense", (12, 12)),
])
def test_corner_position(corner, xy):
    assert ov.corner_position(corner, 300, 110, MAIN) == xy


def test_dragged_position_kept_when_on_screen():
    assert ov.clamp_position(500, 300, 200, 80, [MAIN, RIGHT]) == (500, 300)
    assert ov.clamp_position(2500, 900, 200, 80, [MAIN, RIGHT]) == (2500, 900)       # on the second monitor


def test_partly_off_screen_is_pulled_back_in():
    assert ov.clamp_position(1850, -30, 200, 80, [MAIN]) == (1720, 0)


def test_unplugged_monitor_moves_overlay_to_nearest_screen():
    x, y = ov.clamp_position(3000, 200, 200, 80, [MAIN])          # was on a monitor that's gone
    assert (x, y) == (1720, 200)


def test_place_uses_dragged_spot_else_corner():
    assert ov.place({"x": 400, "y": 50, "corner": "bottom-right"}, 200, 80, [MAIN]) == (400, 50)
    assert ov.place({"x": None, "y": None, "corner": "top-right"}, 200, 80, [MAIN]) == (1920 - 200 - 12, 12)
    assert ov.place({"corner": "top-left"}, 200, 80, []) == (12, 12)
