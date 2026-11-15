@echo off
setlocal EnableExtensions
title Building the RigLab installer
cd /d "%~dp0"
echo.
echo  ==================================================================
echo    RigLab - building the installer (RigLab-Setup.exe)
echo  ==================================================================
echo.

rem --- must be run from an extracted folder, not from inside the zip
echo "%~dp0" | findstr /i /c:"\AppData\Local\Temp\" >nul && (
  echo  It looks like this is running from inside the zip file.
  echo  Right-click the zip, choose "Extract All...", then run this file from the extracted folder.
  echo.
  pause & exit /b 1
)
if not exist "riglab\app.py" (
  echo  Some files are missing - this file has to sit next to the "riglab" and "installer" folders.
  echo.
  pause & exit /b 1
)

rem --- 1. Python (only needed to BUILD; the installed RigLab doesn't need Python)
echo  [1/4] Python
set "PY="
for %%V in (3.12 3.13 3.11) do (
  if not defined PY ( py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V" )
)
if not defined PY (
  echo        Python 3.12 not found - installing it once with winget...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements >nul
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
)
if not defined PY (
  echo        Couldn't find or install Python. Install Python 3.12 from https://www.python.org/downloads/ and run this again.
  pause & exit /b 1
)

rem --- build environment lives outside Dropbox/OneDrive and is reused next time
set "WORK=%LOCALAPPDATA%\RigLab-build"
if not exist "%WORK%\venv\Scripts\python.exe" (
  echo        Creating the build environment in %WORK% ...
  %PY% -m venv "%WORK%\venv" || ( echo        Couldn't create it. & pause & exit /b 1 )
)
set "BPY=%WORK%\venv\Scripts\python.exe"
echo        Installing build packages (first time takes a few minutes)...
"%BPY%" -m pip install --quiet --disable-pip-version-check --upgrade pip
"%BPY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller
if errorlevel 1 ( echo        Package install failed - check your internet connection and run this again. & pause & exit /b 1 )

rem --- 2-4. tools, RigLab.exe, installer
"%BPY%" installer\build.py
if errorlevel 1 (
  echo.
  echo  The log is in %APPDATA%\RigLab\build.log - Claude can read it from there.
  pause & exit /b 1
)
echo.
pause
