"""Change history: every change RigLab makes to the PC, with what it was before so it can be undone.

Stored in its own file (%APPDATA%\\RigLab\\changes.json), separate from settings, so a problem here can
never break settings. A damaged file is set aside as changes.bad.json and a fresh history starts.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .config import app_dir

MAX_ENTRIES = 500
MERGE_SECONDS = 90


class ChangeLog:
    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "changes.json"
        self._lock = threading.RLock()
        self.entries: list[dict] = []
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = [e for e in data if isinstance(e, dict) and "id" in e] if isinstance(data, list) else []
        except (OSError, ValueError):
            try:
                os.replace(self.path, self.path.with_name("changes.bad.json"))
            except OSError:
                pass
            self.entries = []

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, kind: str, title: str, before=None, after=None, undo: bool = True, source: str = "you",
            risk: str = "Low", detail: str = "", ok: bool = True, merge: str | None = None, now: float | None = None) -> dict:
        """source: 'you' (a button you pressed), 'fix' (a Fix it button), 'undo', or 'auto' (RigLab did it for safety).
        merge: changes with the same merge key within MERGE_SECONDS (e.g. dragging a brightness slider, clicking
        through themes) become ONE entry that keeps the original 'before', so one Undo goes all the way back."""
        now = time.time() if now is None else now
        with self._lock:
            last = self.entries[-1] if self.entries else None
            if (merge and last and last.get("merge") == merge and last["kind"] == kind and self.undoable(last)
                    and now - last["time"] <= MERGE_SECONDS and ok and source == last.get("source")):
                last.update(title=title, after=after, time=now, detail=detail or last.get("detail", ""))
                try:
                    self._save()
                except OSError:
                    pass
                return last
            e = {"id": (max((x["id"] for x in self.entries), default=0) + 1), "time": now, "kind": kind,
                 "title": title, "detail": detail, "before": before, "after": after, "risk": risk, "source": source,
                 "can_undo": bool(undo) and ok and source != "undo", "undone_by": None, "ok": ok, "merge": merge}
            self.entries.append(e)
            if len(self.entries) > MAX_ENTRIES:
                self.entries = self.entries[-MAX_ENTRIES:]
            try:
                self._save()
            except OSError:
                pass             # history is best-effort; never block the change itself
            return e

    def get(self, cid) -> dict | None:
        with self._lock:
            return next((e for e in self.entries if e["id"] == int(cid)), None)

    def undoable(self, e: dict | None) -> bool:
        return bool(e) and e.get("can_undo") and not e.get("undone_by")

    def mark_undone(self, cid, by_id: int):
        with self._lock:
            e = self.get(cid)
            if e:
                e["undone_by"] = by_id
                try:
                    self._save()
                except OSError:
                    pass

    def list(self, limit: int = 200) -> list[dict]:
        with self._lock:
            out = []
            for e in reversed(self.entries[-limit:]):
                d = dict(e)
                d["undoable"] = self.undoable(e)
                out.append(d)
            return out

    def summary(self, n: int = 8) -> dict:
        """For the Undo button in the top bar: the newest change that can be undone, and the recent changes."""
        with self._lock:
            last = next((e for e in reversed(self.entries) if self.undoable(e)), None)
            recent = [dict(e, undoable=self.undoable(e)) for e in reversed(self.entries[-n:])]
            slim = lambda e: {k: e.get(k) for k in ("id", "time", "kind", "title", "risk", "source", "undoable", "undone_by", "ok")}  # noqa: E731
            return {"last": slim(dict(last, undoable=True)) if last else None, "recent": [slim(e) for e in recent],
                    "count": sum(1 for e in self.entries if self.undoable(e))}
