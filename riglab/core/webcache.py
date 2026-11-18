"""Clear the window's saved copies of RigLab's screens before it opens.

Why: RigLab's window is a built-in browser (WebView2) that loads the screens from a small local web server on the
same address every time. Like any browser it keeps copies of those files, and it can keep using the old copies for
hours after an update. After installing 3.11 that showed the old 3.10 screens (no Undo button, no Themes page)
on top of the new program. Clearing the copies on every start costs nothing (the files are on this PC) and
guarantees the screens always match the installed version. Saved choices (theme, page, overlay preview) live in
"Local Storage", which is left alone."""
from __future__ import annotations

import shutil
from pathlib import Path

CACHE_DIRS = ("Cache", "Code Cache", "GPUCache", "CacheStorage", "ScriptCache")


def clear(storage: Path | str) -> list[str]:
    """Delete WebView2's cache folders under `storage`. Returns what was removed. Never raises."""
    root = Path(storage)
    removed: list[str] = []
    if not root.is_dir():
        return removed
    try:
        found = [p for p in root.rglob("*") if p.is_dir() and p.name in CACHE_DIRS]
    except OSError:
        return removed
    for p in sorted(found, key=lambda x: len(x.parts)):
        if any(str(p).startswith(r + "/") or str(p).startswith(r + "\\") for r in removed):
            continue                          # already gone with its parent
        try:
            shutil.rmtree(p)
            removed.append(str(p))
        except OSError:
            pass                              # in use (another RigLab window): harmless, try again next start
    return removed
