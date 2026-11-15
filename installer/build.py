"""Builds RigLab-Setup-<version>.exe. Started by "Build RigLab Installer.bat" - don't run it directly.

Everything heavy happens in %LOCALAPPDATA%\\RigLab-build (outside Dropbox/OneDrive, reused next time):
  1. bundled tools: LibreHardwareMonitor (sensors), PresentMon (FPS), OpenRGB (RGB drivers)
  2. PyInstaller -> RigLab.exe + its files (no Python needed on the PC that installs it)
  3. Inno Setup -> one installer exe with Start-menu/desktop shortcuts and an uninstaller
A copy of the log goes to %APPDATA%\\RigLab\\build.log.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RigLab-build"
VENDOR = WORK / "vendor"
DIST = WORK / "dist"
OUT = SRC / "Installer"
LOG = WORK / "build.log"
NOWIN = 0x08000000


def say(msg=""):
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def fail(msg):
    say("")
    say("BUILD FAILED: " + msg)
    _copy_log()
    sys.exit(1)


def _copy_log():
    try:
        dest = Path(os.environ["APPDATA"]) / "RigLab"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LOG, dest / "build.log")
    except (OSError, KeyError):
        pass


def run(args, **kw):
    say("  > " + " ".join(str(a) for a in args)[:300])
    try:
        p = subprocess.run([str(a) for a in args], capture_output=True, text=True, errors="replace", **kw)
    except FileNotFoundError as e:       # e.g. winget missing on a build server
        p = subprocess.CompletedProcess(args, 127, "", str(e))
    with open(LOG, "a", encoding="utf-8") as f:
        f.write((p.stdout or "")[-20000:] + (p.stderr or "")[-20000:] + "\n")
    return p


def version() -> str:
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', (SRC / "riglab" / "core" / "config.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "0.0.0"


# ----------------------------------------------------------------------------- 1. bundled tools
def tools():
    say("[2/4] Bundled tools")
    os.environ["RIGLAB_VENDOR"] = str(VENDOR)
    sys.path.insert(0, str(SRC))
    VENDOR.mkdir(parents=True, exist_ok=True)

    from riglab.core import lhm_setup, presentmon
    if not (VENDOR / "lhm" / "LibreHardwareMonitorLib.dll").exists():
        say("  Sensor library (LibreHardwareMonitor)…")
        inst = lhm_setup.Installer()
        inst.run()
        say("  " + ("ok" if inst.state.get("ok") else "not downloaded - RigLab's Health check can fetch it later"))
    else:
        say("  Sensor library: already here")
    say("  Frame-rate capture (PresentMon): " + ("ok" if presentmon.ensure() else "not downloaded - RigLab fetches it on first use"))

    orgb = VENDOR / "openrgb" / "OpenRGB.exe"
    if not orgb.exists():
        src = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "OpenRGB"
        if not (src / "OpenRGB.exe").exists():
            say("  RGB drivers (OpenRGB) not installed - installing once with winget…")
            run(["winget", "install", "-e", "--id", "CalcProgrammer1.OpenRGB", "--silent",
                 "--accept-source-agreements", "--accept-package-agreements"], creationflags=NOWIN)
        if (src / "OpenRGB.exe").exists():
            shutil.copytree(src, VENDOR / "openrgb", dirs_exist_ok=True)
    say("  RGB drivers (OpenRGB): " + ("ok" if orgb.exists() else "not bundled - the Lighting page offers the download"))


# ----------------------------------------------------------------------------- 2. RigLab.exe
def exe():
    say("[3/4] Building RigLab.exe (a few minutes the first time)…")
    shutil.rmtree(DIST, ignore_errors=True)
    ico = SRC / "riglab" / "web" / "riglab.ico"
    p = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
             "--windowed", "--uac-admin", "--name", "RigLab", "--icon", ico,
             "--distpath", DIST, "--workpath", WORK / "pyi", "--specpath", WORK,
             "--add-data", f"{SRC / 'riglab' / 'web'};riglab/web",
             "--collect-submodules", "riglab",
             "--collect-all", "pythonnet", "--collect-all", "clr_loader", "--collect-all", "webview", "--collect-all", "liquidctl",
             "--hidden-import", "hid", "--hidden-import", "openrgb", "--hidden-import", "pynvml", "--hidden-import", "pystray._win32",
             SRC / "main.py"], cwd=SRC)
    app = DIST / "RigLab" / "RigLab.exe"
    if p.returncode != 0 or not app.exists():
        tail = "\n".join(((p.stderr or "") + (p.stdout or "")).strip().splitlines()[-15:])
        fail("PyInstaller couldn't build RigLab.exe:\n" + tail)
    if VENDOR.exists():
        shutil.copytree(VENDOR, DIST / "RigLab" / "vendor", dirs_exist_ok=True)
    size = sum(f.stat().st_size for f in (DIST / "RigLab").rglob("*") if f.is_file()) / 2**20
    say(f"  RigLab.exe built ({size:.0f} MB with its files)")


# ----------------------------------------------------------------------------- 3. installer
def find_iscc() -> Path | None:
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for r in filter(None, roots):
        for base in (Path(r), Path(r) / "Programs"):
            for d in sorted(base.glob("Inno Setup*"), reverse=True):
                if (d / "ISCC.exe").exists():
                    return d / "ISCC.exe"
    return None


def installer(ver):
    say("[4/4] Making the installer…")
    iscc = find_iscc()
    if not iscc:
        say("  Inno Setup (free installer maker) not found - installing it once with winget…")
        run(["winget", "install", "-e", "--id", "JRSoftware.InnoSetup", "--silent",
             "--accept-source-agreements", "--accept-package-agreements"], creationflags=NOWIN)
        iscc = find_iscc()
    if not iscc:
        fail("Inno Setup isn't installed and winget couldn't install it. Install it from https://jrsoftware.org/isdl.php "
             "and run this again.")
    # Inno writes the exe in place and edits it afterwards; Dropbox/OneDrive/antivirus grabbing the half-written file
    # makes that fail ("EndUpdateResource failed"). So compile in the build folder and copy the finished file over.
    tmp_out = WORK / "output"
    shutil.rmtree(tmp_out, ignore_errors=True)
    tmp_out.mkdir(parents=True)
    built = tmp_out / f"RigLab-Setup-{ver}.exe"
    for attempt in (1, 2):
        p = run([iscc, "/Qp", f"/DAppVer={ver}", f"/DDistDir={DIST / 'RigLab'}", f"/DSrcDir={SRC}", f"/O{tmp_out}",
                 SRC / "installer" / "riglab.iss"])
        if p.returncode == 0 and built.exists():
            break
        if attempt == 1 and "EndUpdateResource" in (p.stdout or "") + (p.stderr or ""):
            say("  Windows Defender was scanning the new file - trying again in 5 s…")
            time.sleep(5)
            continue
        fail("Inno Setup couldn't make the installer:\n" + "\n".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-15:]))
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("RigLab-Setup-*.exe"):
        try:
            old.unlink()
        except OSError:
            pass
    setup = OUT / built.name
    try:
        shutil.copy2(built, setup)
    except OSError:
        setup = built                    # couldn't copy into the source folder - leave it in the build folder
    say(f"  {setup.name} ({setup.stat().st_size / 2**20:.0f} MB)")
    return setup


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    LOG.write_text(f"RigLab installer build {time.ctime()}\nsource: {SRC}\npython: {sys.version}\n", encoding="utf-8")
    ver = version()
    say(f"Building RigLab {ver}")
    tools()
    exe()
    setup = installer(ver)
    _copy_log()
    say("")
    say("=" * 70)
    say(f" Done!  {setup}")
    say(" Double-click it to install RigLab (it updates any older RigLab in place).")
    say("=" * 70)
    if sys.platform == "win32" and not os.environ.get("CI"):
        subprocess.Popen(["explorer", "/select,", str(setup)])


if __name__ == "__main__":
    main()
