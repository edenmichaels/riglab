"""Simple and Advanced view must match: every feature is reachable from both views, nothing exists in only one.
Checks the feature list (web/js/features.js) against the menus in app.js and the pages/sections that exist.
Also checks this round's screen changes: renames, the removed gamers card, the Tweaks order and the Themes tab."""
import json
import re
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "riglab" / "web" / "js"
ALL = {p.name: p.read_text(encoding="utf-8") for p in JS.glob("*.js")}
APPJS = ALL["app.js"]


def features():
    s = ALL["features.js"]
    i = s.index("window.FEATURES =") + len("window.FEATURES =")
    return json.loads(s[i:].strip().rstrip(";"))


def nav():
    body = re.search(r"const NAV = \[(.*?)\n\];", APPJS, re.S).group(1)
    rows = re.findall(r'\["(\w+)",\s*(null|"[^"]*")(?:,\s*(null|"[^"]*"))?(?:,\s*"([^"]*)")?\]', body)
    adv = {r[0] for r in rows if r[0] != "label" and r[1] != "null"}
    simple = {r[0] for r in rows if r[0] != "label" and r[3]}
    return simple, adv


SIMPLE_NAV, ADV_NAV = nav()
F = features()
PAGES = set(re.findall(r"App\.pages\.(\w+)\s*=", "\n".join(ALL.values())))
ANCHORS = set(re.findall(r'"data-anchor":\s*"(\w+)"', "\n".join(ALL.values())))


def test_feature_list_is_valid():
    ids = [f["id"] for f in F]
    assert len(ids) == len(set(ids)) and len(F) >= 20
    for f in F:
        assert f["name"] and f["simple"]["page"] and f["advanced"]["page"], f


@pytest.mark.parametrize("f", F, ids=lambda f: f["id"])
def test_every_feature_is_reachable_from_both_views(f):
    a, s = f["advanced"], f["simple"]
    assert a["page"] in PAGES and a["page"] in ADV_NAV, f"{f['id']}: Advanced page missing from the Advanced menu"
    if s.get("link"):
        # advanced-only: Simple view shows an "Open in Advanced view" card on More tools, which must point to the same place
        assert s["page"] == a["page"] and s.get("focus") == a.get("focus") and s.get("tab") == a.get("tab")
        assert "tools" in SIMPLE_NAV
    else:
        assert s["page"] in SIMPLE_NAV, f"{f['id']}: not in the Simple menu"
    for side in (a, s):
        if side.get("focus"):
            assert side["focus"] in ANCHORS, f"{f['id']}: no section marked data-anchor={side['focus']!r}"


def test_no_menu_page_exists_in_only_one_view():
    covered = {f["advanced"]["page"] for f in F}
    for page in SIMPLE_NAV | ADV_NAV:
        assert page in covered, f"{page} is in a menu but not in the feature list"
        assert page in PAGES, f"{page} has no screen"
    only_adv = ADV_NAV - SIMPLE_NAV
    linked = {f["advanced"]["page"] for f in F if f["simple"].get("link")}
    assert only_adv <= linked, f"Advanced-only pages without a Simple card: {only_adv - linked}"
    assert SIMPLE_NAV <= ADV_NAV, f"Simple-only pages: {SIMPLE_NAV - ADV_NAV}"


def test_advanced_cards_say_so_and_switch_view():
    s = ALL["simple.js"]
    assert "this is an advanced feature." in s and "Open in Advanced view →" in s
    assert re.search(r'function openAdvanced.{0,200}?setView\("advanced"', s, re.S)


def test_renames_removed_card_tweaks_order_and_themes_tab():
    assert re.search(r'\["explain",\s*"[^"]+",\s*"\w+",\s*"PC Info"\]', APPJS)
    assert "My PC Explained" not in "\n".join(ALL.values())
    sysjs = ALL["pages_system.js"]
    assert "One click for gamers" not in sysjs and "One-click for gamers" not in sysjs
    assert "game_mode" in sysjs or "Put games first" in "\n".join(ALL.values())         # put games first kept
    tw = sysjs[sysjs.index("App.pages.tweaks"):]
    assert tw.index('"data-anchor": "power"') < tw.index('"data-anchor": "windows"')   # How hard should my PC work: first
    assert '["themes", "Themes", "palette", "Themes"]' in APPJS
    settings = sysjs[sysjs.index("App.pages.settings"):]
    assert "THEMES" not in settings and "accentSwatch" not in settings and "themeCard" not in settings
    assert "App.pages.themes" in ALL["pages_extras.js"]


def test_home_presets_still_cover_gaming():
    from riglab.core import presets
    assert presets.ORDER[0] == "gaming"          # the removed gamers card is covered by Home's Gaming preset
