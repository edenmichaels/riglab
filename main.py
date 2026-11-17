"""RigLab - hardware diagnostics, benchmarks, stress tests, RGB, fans and overclocking for Windows.

Installed RigLab is RigLab.exe (built by "Build RigLab Installer.bat"). Options:
  --minimized   start in the tray (used by "Start with Windows")
  --debug       open the browser dev tools
  --weekly-check  run a quick health check and show the score (used by the optional weekly task)
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import sys

if getattr(sys, "frozen", False):
    # RigLab.exe: pythonnet (used by the window and the sensor library) must find the bundled python3xx.dll
    _dll = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)),
                        f"python{sys.version_info.major}{sys.version_info.minor}.dll")
    if os.path.exists(_dll):
        os.environ.setdefault("PYTHONNET_PYDLL", _dll)


def relaunch_as_admin() -> bool:
    """Ask Windows (UAC) to restart us elevated. Returns True if the elevated copy launched."""
    import ctypes
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, sys.argv[1:]
        cwd = os.path.dirname(sys.executable)
    else:
        exe = sys.executable  # running from source
        script = os.path.abspath(sys.argv[0])
        args = [script] + sys.argv[1:]
        cwd = os.path.dirname(script)
    params = " ".join(f'"{a}"' for a in args) + " --elevated"
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, cwd, 1)
    return rc > 32


def main():
    from riglab.core.config import app_dir
    logging.basicConfig(filename=app_dir() / "riglab.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # pythonw has no console, so make sure crashes end up in riglab.log
    sys.excepthook = lambda t, v, tb: logging.critical("Unhandled error", exc_info=(t, v, tb))

    if sys.platform == "win32" and "--no-admin" not in sys.argv and "--elevated" not in sys.argv:
        from riglab.core.tweaks import is_admin
        if not is_admin() and relaunch_as_admin():
            return  # the elevated copy takes over

    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RigLab.App")  # own taskbar icon

    from riglab.core import instance
    if "--weekly-check" in sys.argv and instance.ask("check"):
        logging.info("weekly check handed to the running RigLab")
        return
    logging.info("startup: %s", instance.take_over())

    from riglab.app import App
    App().run()

if __name__ == "__main__":
    multiprocessing.freeze_support()   # needed for stress/benchmark workers in the .exe build
    main()
