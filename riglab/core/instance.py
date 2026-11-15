"""Only one RigLab at a time.

RigLab keeps running in the tray when its window is closed, so starting it again (e.g. after updating)
used to leave the old copy running too - two copies then stream different effects to the same LEDs and
the lights flash between them. The running copy listens on a local port; a new copy asks it to quit
(cleanly: fans and lights are handed back) and only force-closes it if it doesn't respond.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time

log = logging.getLogger(__name__)
PORT = 47613


def take_over(timeout: float = 12.0) -> str:
    """Close any older RigLab. Returns what happened (for the log)."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1) as s:
            s.sendall(b"quit\n")
    except OSError:
        return _kill_strays() or "no other copy"
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
            time.sleep(0.3)
        except OSError:
            time.sleep(1.0)                     # give it a moment to release USB devices
            return "previous copy closed itself"
    return _kill_strays() or "previous copy didn't respond"


def _kill_strays() -> str:
    """Older RigLab builds (before this lock existed) can't be asked, so close them by process."""
    try:
        import psutil
    except ImportError:
        return ""
    me = {os.getpid(), os.getppid()}
    killed = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or []).lower()
            name = (p.info.get("name") or "").lower()
            if p.info["pid"] in me:
                continue
            # only RigLab itself - never its installer/uninstaller, which may be the program that started us
            if name == "riglab.exe" or ("python" in name and "main.py" in cmd and "riglab" in cmd):
                p.terminate()
                killed.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if killed:
        psutil.wait_procs(killed, timeout=5)
        return f"closed {len(killed)} older RigLab process(es)"
    return ""


def serve(on_quit):
    """Listen for 'quit' from a newer copy."""
    def run():
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", PORT))
            srv.listen(2)
        except OSError:
            log.warning("instance port busy")
            return
        while True:
            conn, _ = srv.accept()
            with conn:
                if conn.recv(16).startswith(b"quit"):
                    log.info("newer RigLab started - closing this copy")
                    srv.close()
                    on_quit()
                    return
    threading.Thread(target=run, name="Instance", daemon=True).start()
