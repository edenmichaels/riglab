"""Every theme keeps text and the green / yellow / red status colours readable (WCAG contrast), and every theme
in the picker exists in the stylesheet with all the colours the screens use."""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "riglab" / "web"
CSS = (WEB / "app.css").read_text(encoding="utf-8")
APPJS = (WEB / "js" / "app.js").read_text(encoding="utf-8")
NEEDED = ("--bg", "--bg-2", "--panel", "--panel-2", "--line", "--text", "--muted", "--faint", "--accent", "--accent-2",
          "--accent-rgb", "--on-accent", "--good", "--warn", "--bad", "--good-rgb", "--warn-rgb", "--bad-rgb")


def block(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, selector
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)))


ROOT = block(":root")


def theme(name):
    v = dict(ROOT)
    if name != "dark":
        v.update(block(f'[data-theme="{name}"]'))
    return v


def picker_themes():
    m = re.search(r"const THEMES = \[(.*?)\];", APPJS, re.S)
    assert m, "THEMES list missing in app.js"
    return re.findall(r'\["(\w+)"', m.group(1))


THEMES = picker_themes()


def lum(hexc):
    h = hexc.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_picker_has_the_ten_requested_themes_plus_match_windows():
    for t in ("dark", "light", "dracula", "nord", "catppuccin", "gruvbox", "solarized", "tokyo", "onedark", "contrast", "system"):
        assert t in THEMES


@pytest.mark.parametrize("name", [t for t in THEMES if t != "system"])
def test_theme_defines_every_colour(name):
    v = theme(name)
    for k in NEEDED:
        assert k in v, f"{name} is missing {k}"


@pytest.mark.parametrize("name", [t for t in THEMES if t != "system"])
def test_text_is_readable(name):
    v = theme(name)
    need = 7 if name == "contrast" else 4.5
    for bg in ("--bg", "--panel", "--panel-2"):
        assert contrast(v["--text"], v[bg]) >= need, f"{name}: text on {bg}"
        assert contrast(v["--muted"], v[bg]) >= 4.5, f"{name}: muted text on {bg}"


@pytest.mark.parametrize("name", [t for t in THEMES if t != "system"])
def test_status_colours_are_readable(name):
    """Dots, pills, the dial and coloured numbers: at least 3:1 against cards (WCAG for graphics and large text)."""
    v = theme(name)
    need = 4.5 if name == "contrast" else 3
    for st in ("--good", "--warn", "--bad"):
        for bg in ("--panel", "--panel-2", "--bg"):
            assert contrast(v[st], v[bg]) >= need, f"{name}: {st} on {bg} = {contrast(v[st], v[bg]):.2f}"


@pytest.mark.parametrize("name", [t for t in THEMES if t != "system"])
def test_status_colours_differ_from_each_other(name):
    v = theme(name)
    cols = [v["--good"], v["--warn"], v["--bad"]]
    assert len({c.lower() for c in cols}) == 3


@pytest.mark.parametrize("name", [t for t in THEMES if t != "system"])
def test_buttons_are_readable(name):
    v = theme(name)
    assert contrast(v["--on-accent"], v["--accent"]) >= 4.5, f"{name}: button text on accent"
    assert contrast(v["--accent"], v["--panel"]) >= 3, f"{name}: accent on cards"


def test_rgb_triplets_match_the_hex_colours():
    for name in [t for t in THEMES if t != "system"]:
        v = theme(name)
        for k in ("--good", "--warn", "--bad", "--accent"):
            h = v[k].lstrip("#")
            want = ", ".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))
            assert v[k + "-rgb"].replace(" ", "") == want.replace(" ", ""), f"{name} {k}-rgb"
