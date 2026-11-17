RigLab 3.8.0
============

NEW IN 3.8.0 - Simple by default
  - Simple view (the new default): plain words everywhere, and green / yellow / red lights for every
    reading. Settings -> "How much detail?" switches to Advanced, which shows everything as before.
    Nothing is removed in Simple view - risky settings and technical pages are only hidden.
  - Every action has an (i) button: what it does, what you'll notice, how risky it is, and if it can be undone.
  - Medium and High risk changes ask "Are you sure?" and make sure there's a Windows restore point first.
    A restore point from the last 24 hours counts. High risk changes are blocked without one; Medium risk
    changes let you choose. If restore points are switched off, a "Turn on restore points" button appears.
  - Change history (new page): every change RigLab makes, including Fix it buttons and undos, with a
    one-click Undo where possible. Kept in %APPDATA%\RigLab\changes.json.
  - "Make games run smoother" button and one-click fan settings (Quiet / Balanced / Cool).
  - "Health check" is now called "RigLab setup" (it checks RigLab's own helpers) and lives in Advanced view.

NEW IN 3.7.0
  In-game overlay (Settings -> In-game overlay):
  - Show FPS: FPS, 1% low and frame time for the game in front (off by default, fully offline)
  - Styles: full stats, or an FPS counter (number only, + 1% low, + frame time, detailed, + graph)
  - Move overlay: drag it anywhere on any screen (also in the tray menu); or snap to a corner
  - Text size, FPS colour and background transparency (0% = text only)

INSTALL (once)
  1. Right-click the zip -> Extract All.
  2. Open the extracted folder and double-click  "Build RigLab Installer.bat".
     The first build takes 5-10 minutes; later builds take 1-2.
     It sets up everything it needs by itself and keeps it in %LOCALAPPDATA%\RigLab-build.
  3. When it finishes, the "Installer" folder opens with RigLab-Setup-3.8.0.exe.
     Double-click it: RigLab installs to Program Files with Start-menu and desktop shortcuts.

UPDATE
  Extract the new zip, run "Build RigLab Installer.bat" again, then run the new RigLab-Setup exe.
  It updates RigLab in place. Your settings, LED counts, fan curves and benchmark results are kept
  (they live in %APPDATA%\RigLab).

UNINSTALL
  Windows Settings -> Apps -> RigLab -> Uninstall.

WHAT'S IN THIS FOLDER
  Build RigLab Installer.bat   builds the installer (the only file you run)
  installer\                   build script + installer definition
  riglab\                      RigLab itself (Python + the interface)
  main.py, requirements.txt    start file and the packages RigLab uses

If anything goes wrong, the build log is saved to %APPDATA%\RigLab\build.log.
