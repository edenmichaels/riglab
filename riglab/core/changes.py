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
            risk: str = "Low", detail: str = "", ok: bool = True) -> dict:
        """source: 'you' (a button you pressed), 'fix' (a Fix it button), 'undo', or 'auto' (RigLab did it for safety)."""
        with self._lock:
            e = {"id": (max((x["id"] for x in self.entries), default=0) + 1), "time": time.time(), "kind": kind,
                 "title": title, "detail": detail, "before": before, "after": after, "risk": risk, "source": source,
                 "can_undo": bool(undo) and ok and source != "undo", "undone_by": None, "ok": ok}
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
