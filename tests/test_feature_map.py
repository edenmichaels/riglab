"""Simple and Advanced view must match after the 3.12 menu clean-up: five menu places, every other feature is a
tile on Tools or a tab in Settings, and everything is reachable from both views (advanced-only features show a
Simple tile that switches view). Also the search box, pins and this round's screen changes."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "riglab" / "web" / "js"
ALL = {p.name: p.read_text(encoding="utf-8") for p in JS.glob("*.js")}
FEAT = ALL["features.js"]


def block(name):
    i = FEAT.index(f"window.{name} =") + len(f"window.{name} =")
    j = FEAT.index("];", i) + 1
    return json.loads(FEAT[i:j])


MENU, TABS, F = block("MENU"), block("SETTINGS_TABS"), block("FEATURES")
PAGES = set(re.findall(r"App\.pages\.(\w+)\s*=", "\n".join(ALL.values())))
ANCHORS = set(re.findall(r'"data-anchor":\s*(?:actions \? )?"(\w+)"', "\n".join(ALL.values())))


def reachable(simple: bool) -> set:
    """Pages you can get to by clicking: the menu, Tools tiles, Settings tabs."""
    pages = {m["page"] for m in MENU}
    pages |= {f[("simple" if simple else "advanced")]["page"] for f in F if f.get("tile") and not (simple and f["simple"].get("link"))}
    pages |= {t["page"] for t in TABS if not (simple and t.get("advanced"))}
    return pages


def test_menu_is_five_calm_places():
    assert [m["name"] for m in MENU] == ["Home", "PC Health", "Lighting", "Tools", "Settings"]
    assert [t["name"] for t in TABS] == ["General", "Themes", "RigLab setup"]
    assert "const NAV = (window.MENU" in ALL["app.js"]                         # the same menu in both views


def test_feature_list_is_valid():
    ids = [f["id"] for f in F]
    assert len(ids) == len(set(ids)) and len(F) >= 30
    for f in F:
        assert f["name"] and f["simple"]["page"] and f["advanced"]["page"], f
        if f.get("tile"):
            t = f["tile"]
            assert t["short"] and t["desc"] and t["icon"] and len(t["desc"]) <= 60, f["id"]


@pytest.mark.parametrize("f", F, ids=lambda f: f["id"])
def test_every_feature_is_reachable_from_both_views(f):
    a, s = f["advanced"], f["simple"]
    assert a["page"] in PAGES, f"{f['id']}: no screen called {a['page']}"
    assert a["page"] in reachable(False), f"{f['id']}: can't be reached in Advanced view"
    if s.get("link"):
        assert s["page"] == a["page"] and s.get("focus") == a.get("focus") and s.get("tab") == a.get("tab")
        tiled = f.get("tile") or any(t["page"] == a["page"] and t.get("advanced") for t in TABS)
        assert tiled, f"{f['id']}: advanced-only but has no Simple tile/tab that links to it"
    else:
        assert s["page"] in reachable(True), f"{f['id']}: can't be reached in Simple view"
    for side in (a, s):
        if side.get("focus"):
            assert side["focus"] in ANCHORS, f"{f['id']}: no section marked data-anchor={side['focus']!r}"


def test_nothing_exists_in_only_one_view():
    adv, simple = reachable(False), reachable(True)
    linked = {f["advanced"]["page"] for f in F if f["simple"].get("link")} | {t["page"] for t in TABS if t.get("advanced")}
    assert simple <= adv, f"Simple-only pages: {simple - adv}"
    assert adv - simple <= linked, f"Advanced-only pages with no Simple tile: {(adv - simple) - linked}"
    covered = {f["advanced"]["page"] for f in F}
    assert adv <= covered | {"tools"}, f"pages missing from the feature list: {adv - covered}"


def test_simple_tiles_for_advanced_tools_switch_view():
    s = ALL["simple.js"] + ALL["app.js"] + ALL["pages_extras.js"]
    assert re.search(r'function openAdvanced.{0,200}?setView\("advanced"', s, re.S)
    assert "if (S && t.link) return openAdvanced(" in ALL["app.js"]
    assert "Advanced view →" in ALL["pages_extras.js"]


def test_tools_have_back_button_and_settings_tabs():
    app = ALL["app.js"]
    assert 'go("tools")' in app and "Back to Tools" in app
    assert "settingsTabs(id)" in app


def test_renames_removed_card_tweaks_order_themes_tab():
    sysjs = ALL["pages_system.js"]
    assert "My PC Explained" not in "\n".join(ALL.values())
    assert "One click for gamers" not in sysjs and "One-click for gamers" not in sysjs
    tw = sysjs[sysjs.index("App.pages.tweaks"):]
    assert tw.index('"data-anchor": "power"') < tw.index('"data-anchor": "windows"')
    settings = sysjs[sysjs.index("App.pages.settings"):]
    assert "THEMES" not in settings and "overlayCard" not in settings          # themes and overlay moved out
    assert "App.pages.themes" in ALL["pages_extras.js"] and "App.pages.overlay" in ALL["pages_overlay.js"]


def test_home_is_calm_and_presets_cover_gaming():
    from riglab.core import presets
    home = ALL["pages_home.js"]
    assert 'MAIN_PRESETS = ["gaming", "balanced", "quiet", "power_saver"]' in home and "More presets" in home
    assert "Pinned tools" in home and "Lighting" in home and "healthDial" in home
    assert "start-here" not in home and "HOME_TOOLS" not in home
    assert presets.ORDER[0] == "gaming"


def test_undo_uses_the_standard_icon_with_tooltip():
    ui = ALL["ui.js"]
    assert 'undo: "M9 14L4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"' in ui     # Lucide undo-2
    assert "Undo last change" in ALL["app.js"]
    assert "Lucide" in ALL["pages_system.js"] and "ISC licence" in ALL["pages_system.js"]


def test_every_dial_is_the_shared_gauge():
    others = {k: v for k, v in ALL.items() if k != "gauge.js"}
    assert "function gauge(" not in ALL["ui.js"]                               # the old separate dial is gone
    assert "Gauge.create(" in ALL["simple.js"] and "Gauge.create(" in ALL["pages_net.js"] and "Gauge.create(" in ALL["pages_monitor.js"]
    assert not any("<circle" in v and "stroke-dasharray" in v for v in others.values()), "a page draws its own dial"


# ------------------------------------------------------------------ search (runs the real JS with node)
NODE = shutil.which("node")


def run_js(code: str):
    src = "global.window = {};\n" + FEAT + "\n" + code
    r = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="node isn't installed")
@pytest.mark.parametrize("query,first", [
    ("fans", "fans"), ("speed test", "netspeed"), ("internet", "netspeed"), ("overlay", "overlay"), ("fps", "overlay"),
    ("theme", "themes"), ("dark", "themes"), ("lights", "lighting"), ("rgb", "lighting"), ("startup", "startup"),
    ("crash", "crashes"), ("text size", "text_size"), ("start with windows", "autostart"), ("overclock", "overclock"),
    ("disk space", "storage"), ("undo", "history"), ("log", "setup"),
])
def test_search_finds_the_right_tool(query, first):
    out = run_js(f"console.log(JSON.stringify(window.searchFeatures({json.dumps(query)}, window.FEATURES, true).map(r => [r.f.id, r.advanced])))")
    assert out and out[0][0] == first, out


@pytest.mark.skipif(not NODE, reason="node isn't installed")
def test_search_marks_advanced_tools_in_simple_view_and_handles_nonsense():
    out = run_js("console.log(JSON.stringify([window.searchFeatures('stress', window.FEATURES, true).map(r => r.advanced),"
                 " window.searchFeatures('stress', window.FEATURES, false).map(r => r.advanced),"
                 " window.searchFeatures('zzzqqq', window.FEATURES, true).length, window.searchFeatures('', window.FEATURES, true).length,"
                 " window.searchFeatures('(.*', window.FEATURES, true).length]))")
    assert out[0][0] is True and out[1][0] is False and out[2] == 0 and out[3] == 0 and out[4] == 0


# ------------------------------------------------------------------ pins (favourites)
def block_pins():
    m = re.search(r"window\.DEFAULT_PINS = (\[[^\]]*\]);", FEAT)
    return json.loads(m.group(1))


def test_pins_are_cleaned_capped_and_saved(tmp_path):
    from riglab.api import DEFAULT_PINS, MAX_PINS, ui_values
    from riglab.core.config import Config
    assert ui_values({"pins": ["fans", "fans", "netspeed", 3, "", "overlay", "storage", "tweaks"]})["pins"] == ["fans", "netspeed", "overlay", "storage"]
    assert MAX_PINS == 4 and len(DEFAULT_PINS) == 4
    assert set(DEFAULT_PINS) <= {f["id"] for f in F if f.get("tile")}
    assert block_pins() == DEFAULT_PINS                                        # the screen's defaults match Python's
    f = tmp_path / "settings.json"
    c = Config(f)
    c.data["ui"].update(ui_values({"pins": ["overlay", "fans"]}))
    c.save()
    assert Config(f).data["ui"]["pins"] == ["overlay", "fans"]
    f.write_text(json.dumps({"ui": {"theme": "dark"}}), encoding="utf-8")       # older settings: no pins yet
    assert Config(f).data["ui"]["pins"] is None                                # = use the defaults


def test_pins_undo_back_to_defaults(tmp_path):
    from riglab.api import Api
    from riglab.core.changes import ChangeLog
    from riglab.core.config import Config
    a = object.__new__(Api)
    a._cfg = Config(tmp_path / "s.json")
    a._changes = ChangeLog(tmp_path / "c.json")
    a.ui_set({"pins": ["overlay"]})
    e = a._changes.list()[0]
    assert e["kind"] == "appearance" and e["before"] == {"pins": None}
    a.ui_set(dict(e["before"], _undo=True))
    assert a._cfg.data["ui"]["pins"] is None
