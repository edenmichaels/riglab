RigLab 3.7.0
============

NEW IN 3.7.0
  In-game overlay can show FPS, 1% low and frame time for the game in front
  (Settings -> In-game overlay -> Show FPS; off by default, fully offline).

INSTALL (once)
  1. Right-click the zip -> Extract All.
  2. Open the extracted folder and double-click  "Build RigLab Installer.bat".
     The first build takes 5-10 minutes; later builds take 1-2.
     It sets up everything it needs by itself and keeps it in %LOCALAPPDATA%\RigLab-build.
  3. When it finishes, the "Installer" folder opens with RigLab-Setup-3.7.0.exe.
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
