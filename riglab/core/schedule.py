"""Optional weekly quick check, using Windows Task Scheduler (off by default).

The task starts RigLab with --weekly-check. If RigLab is already running, that copy runs the check; if not, RigLab
starts hidden in the tray, runs the quick check, shows a notification with the score and closes again.
"""
from __future__ import annotations

import os
import subprocess
import sys

TASK = r"RigLab\Weekly health check"
CREATE_NO_WINDOW = 0x08000000
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def launch_cmd() -> list[str]:
    """How Task Scheduler should start RigLab (the .exe when installed, python + main.py from source)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "main.py")
    return [pyw if os.path.exists(pyw) else exe, main]


def task_line(cmd: list[str]) -> str:
    return " ".join(f'"{c}"' for c in cmd) + " --weekly-check"


def create_args(cmd: list[str], day: str = "SUN", time_: str = "19:00") -> list[str]:
    day = day if day in DAYS else "SUN"
    tr = task_line(cmd)
    if len(tr) > 261:
        raise ValueError("RigLab's folder path is too long for Task Scheduler")
    return ["schtasks", "/Create", "/TN", TASK, "/TR", tr, "/SC", "WEEKLY", "/D", day, "/ST", time_, "/RL", "HIGHEST", "/F"]


def delete_args() -> list[str]:
    return ["schtasks", "/Delete", "/TN", TASK, "/F"]


def _run(args) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Windows only"
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout or r.stderr or "").strip()[:300]


def set_weekly(on: bool) -> tuple[bool, str]:
    if on:
        try:
            return _run(create_args(launch_cmd()))
        except ValueError as e:
            return False, str(e)
    ok, msg = _run(delete_args())
    return ok or "cannot find" in msg.lower(), msg


def is_scheduled() -> bool | None:
    if sys.platform != "win32":
        return None
    ok, _ = _run(["schtasks", "/Query", "/TN", TASK])
    return ok
