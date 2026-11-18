"""Storage clean-up: the biggest files in your own folders, old Windows update downloads, and startup-app impact.

Only ever looks inside the person's own folders (Downloads, Desktop, Documents, Videos, Pictures, Music) for big
files, and nothing is deleted without them choosing it: files go to the Recycle Bin so they can be put back.
Pure functions are tested with temporary folders.
"""
from __future__ import annotations

import heapq
import os
import re
import time
from pathlib import Path

USER_FOLDERS = ("Downloads", "Desktop", "Documents", "Videos", "Pictures", "Music")
SKIP_DIRS = {"node_modules", ".git", "appdata", "$recycle.bin", "windows", "program files", "program files (x86)"}


def user_roots(home: str | os.PathLike | None = None) -> list[Path]:
    home = Path(home or os.path.expanduser("~"))
    return [home / f for f in USER_FOLDERS if (home / f).is_dir()]


def largest_files(roots, limit: int = 25, min_size: int = 200 * 1024 * 1024, deadline: float | None = None,
                  cancelled=lambda: False) -> tuple[list[dict], bool]:
    """Biggest files under roots, biggest first. Returns (files, finished). Stops early at the deadline or on cancel."""
    heap: list[tuple[int, str]] = []
    stack = [Path(r) for r in roots]
    seen = set()
    while stack:
        if cancelled() or (deadline and time.monotonic() > deadline):
            return _out(heap), False
        d = stack.pop()
        try:
            real = os.path.realpath(d)
            if real in seen:
                continue
            seen.add(real)
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            if e.name.lower() not in SKIP_DIRS and not e.name.startswith("."):
                                stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            sz = e.stat(follow_symlinks=False).st_size
                            if sz >= min_size:
                                if len(heap) < limit:
                                    heapq.heappush(heap, (sz, e.path))
                                elif sz > heap[0][0]:
                                    heapq.heapreplace(heap, (sz, e.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return _out(heap), True


def _out(heap):
    return [{"path": p, "name": os.path.basename(p), "folder": os.path.dirname(p), "size": s, "kind": kind_of(p)}
            for s, p in sorted(heap, reverse=True)]


KINDS = [(r"\.(mp4|mkv|mov|avi|wmv|webm|m4v)$", "Video"), (r"\.(iso|img|vhdx?|vmdk)$", "Disk image"),
         (r"\.(zip|7z|rar|tar|gz|xz)$", "Archive"), (r"\.(exe|msi|msix|appx)$", "Installer"),
         (r"\.(jpg|jpeg|png|raw|cr2|nef|arw|psd|tif)$", "Picture"), (r"\.(mp3|flac|wav|m4a|aac)$", "Music"),
         (r"\.(pst|ost)$", "Email file"), (r"\.(bak|old|tmp|log)$", "Leftover file")]


def kind_of(path: str) -> str:
    p = path.lower()
    for rx, k in KINDS:
        if re.search(rx, p):
            return k
    return "File"


def inside(path: str | os.PathLike, roots) -> bool:
    """True only if path is really inside one of the roots (no tricks with .. or links)."""
    try:
        p = os.path.realpath(path)
        for r in roots:
            rr = os.path.realpath(r)
            if os.path.commonpath([p, rr]) == rr and p != rr:
                return True
    except (OSError, ValueError):
        return False
    return False


def folder_size(path: str | os.PathLike, older_than_days: float = 0) -> tuple[int, int]:
    """(bytes, files) under a folder, optionally only files older than N days."""
    cutoff = time.time() - older_than_days * 86400
    total = count = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                st = os.stat(os.path.join(dirpath, f))
                if not older_than_days or st.st_mtime < cutoff:
                    total += st.st_size
                    count += 1
            except OSError:
                continue
    return total, count


def update_cache_dir() -> Path:
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "SoftwareDistribution" / "Download"


def clean_folder(path: str | os.PathLike, older_than_days: float = 10) -> tuple[int, int]:
    """Delete files older than N days (files in use are skipped). Returns (bytes, files) removed."""
    cutoff = time.time() - older_than_days * 86400
    freed = n = 0
    for dirpath, dirs, files in os.walk(path, topdown=False):
        for f in files:
            fp = os.path.join(dirpath, f)
            try:
                st = os.stat(fp)
                if st.st_mtime < cutoff:
                    os.remove(fp)
                    freed += st.st_size
                    n += 1
            except OSError:
                continue
        for d in dirs:
            try:
                os.rmdir(os.path.join(dirpath, d))      # only removes empty folders
            except OSError:
                pass
    return freed, n


# ------------------------------------------------------------------ startup impact
HEAVY = re.compile(r"(steam|epicgames|epic games|discord|teams|onedrive|spotify|adobe|creative ?cloud|icue|corsair|synapse|razer|"
                   r"armoury|armory crate|lghub|logitech g hub|ea ?app|origin|battle\.net|ubisoft|gog ?galaxy|zoom|skype|dropbox|"
                   r"googledrive|google drive|nvidia broadcast|opera|msedge|edge.*--no-startup-window|wallpaper ?engine|signalrgb|nzxt cam|"
                   r"riot ?client|xbox|whatsapp|slack|outlook|acrobat)", re.I)
LIGHT = re.compile(r"(securityhealth|windows ?defender|rtkaud|realtek|igfx|nvcplui|ctfmon|bthelper|audio ?control|"
                   r"synaptics|elan|touchpad|cortana|openrgb|riglab|keyboard|wacom|onboard ?display)", re.I)


def exe_path(cmd: str) -> str | None:
    cmd = (cmd or "").strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        return cmd[1:end] if end > 0 else None
    m = re.match(r"(.+?\.(exe|lnk|bat|cmd))\b", cmd, re.I)
    return m.group(1) if m else (cmd.split(" ")[0] or None)


def startup_impact(name: str, cmd: str, size: int | None = None) -> tuple[str, str]:
    """('High' | 'Medium' | 'Low', why). An estimate: Windows doesn't say exactly how much each app slows start-up."""
    text = f"{name} {cmd}"
    if LIGHT.search(text):
        return "Low", "A small helper. It barely affects how fast Windows starts."
    if HEAVY.search(text):
        return "High", "A big app that also connects to the internet when it starts. It can slow Windows down for a while."
    if size is not None and size > 80 * 1024 * 1024:
        return "High", "A large program. It can slow Windows down when it starts."
    if size is not None and size < 3 * 1024 * 1024:
        return "Low", "A small program. It barely affects how fast Windows starts."
    return "Medium", "Uses a little time and memory when Windows starts."
