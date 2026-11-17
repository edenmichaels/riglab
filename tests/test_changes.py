"""Change history: saved, listed newest first, undo bookkeeping, survives a damaged file."""
from riglab.core.changes import MAX_ENTRIES, ChangeLog


def test_add_list_and_reload(tmp_path):
    f = tmp_path / "changes.json"
    log = ChangeLog(f)
    a = log.add("tweak", "Put games first: on", before={"id": "game_mode", "on": False}, after={"id": "game_mode", "on": True})
    b = log.add("junk", "Freed 1.2 GB", undo=False)
    items = log.list()
    assert [i["id"] for i in items] == [b["id"], a["id"]]       # newest first
    assert items[1]["undoable"] and not items[0]["undoable"]
    again = ChangeLog(f)
    assert again.get(a["id"])["before"] == {"id": "game_mode", "on": False}


def test_undo_bookkeeping(tmp_path):
    log = ChangeLog(tmp_path / "c.json")
    a = log.add("power_plan", "Power plan: High performance", before={"guid": "x"}, after={"guid": "y"})
    u = log.add("power_plan", "Undid: Power plan", source="undo")
    assert not u["can_undo"]                                     # an undo can't itself be undone
    log.mark_undone(a["id"], u["id"])
    assert not log.undoable(log.get(a["id"]))
    assert not log.undoable(None)


def test_failed_change_is_logged_but_not_undoable(tmp_path):
    log = ChangeLog(tmp_path / "c.json")
    e = log.add("oc_windows", "Changed boost", before={"boost_mode": 1}, ok=False)
    assert e["ok"] is False and not log.undoable(e)


def test_fix_and_auto_sources(tmp_path):
    log = ChangeLog(tmp_path / "c.json")
    log.add("fix", "Fix it: restarted RigLab as administrator", undo=False, source="fix")
    log.add("restore_point", "Made a safety restore point", undo=False, source="auto")
    assert [i["source"] for i in log.list()] == ["auto", "fix"]


def test_damaged_file_is_set_aside(tmp_path):
    f = tmp_path / "changes.json"
    f.write_text("{not json", encoding="utf-8")
    log = ChangeLog(f)
    assert log.list() == []
    assert (tmp_path / "changes.bad.json").exists()
    log.add("tweak", "x", before={"id": "t", "on": True})
    assert ChangeLog(f).list()[0]["title"] == "x"


def test_history_is_capped(tmp_path):
    log = ChangeLog(tmp_path / "c.json")
    for i in range(MAX_ENTRIES + 20):
        log.add("tweak", f"t{i}", undo=False)
    assert len(log.entries) == MAX_ENTRIES and log.entries[-1]["title"] == f"t{MAX_ENTRIES + 19}"
    assert len({e["id"] for e in log.entries}) == MAX_ENTRIES   # ids stay unique
