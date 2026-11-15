; RigLab installer (Inno Setup 6/7). Built by installer\build.py - values below come from it.
#ifndef AppVer
  #define AppVer "0.0.0"
#endif
#ifndef DistDir
  #error DistDir not set - run "Build RigLab Installer.bat"
#endif

[Setup]
AppId={{6B1F4E2A-8C3D-4F7A-9E51-2D7C0B9A4E31}
AppName=RigLab
AppVersion={#AppVer}
AppVerName=RigLab {#AppVer}
AppPublisher=RigLab
DefaultDirName={autopf}\RigLab
DefaultGroupName=RigLab
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=RigLab-Setup-{#AppVer}
SetupIconFile={#SrcDir}\riglab\web\riglab.ico
UninstallDisplayIcon={app}\RigLab.exe
UninstallDisplayName=RigLab
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVer}
VersionInfoDescription=RigLab installer

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start RigLab with Windows (in the tray, so fan curves, lighting and alerts keep working)"; GroupDescription: "Startup:"; Flags: unchecked

[InstallDelete]
; upgrades: clear the old program files first so nothing stale is left behind (settings live in %APPDATA%\RigLab)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\RigLab"; Filename: "{app}\RigLab.exe"
Name: "{autodesktop}\RigLab"; Filename: "{app}\RigLab.exe"; Tasks: desktopicon

[Run]
; RigLab needs administrator rights, so "start with Windows" is a scheduled task (a normal Run key can't elevate)
Filename: "schtasks.exe"; Parameters: "/Create /F /TN ""RigLab"" /SC ONLOGON /RL HIGHEST /TR ""\""{app}\RigLab.exe\"" --minimized"""; Flags: runhidden; Tasks: autostart
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""RigLab"""; Flags: runhidden; Tasks: not autostart
Filename: "{app}\RigLab.exe"; Description: "Start RigLab now"; Flags: nowait postinstall skipifsilent shellexec runascurrentuser

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM RigLab.exe"; Flags: runhidden; RunOnceId: "KillRigLab"
Filename: "taskkill.exe"; Parameters: "/F /IM PresentMon.exe"; Flags: runhidden; RunOnceId: "KillPresentMon"
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""RigLab"""; Flags: runhidden; RunOnceId: "DelTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\vendor"

[Code]
procedure KillRunning();
var Code: Integer;
begin
  // ask RigLab to close (it hands fans and lights back), then force-close as a fallback so no file is locked
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM RigLab.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(2500);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM RigLab.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM PresentMon.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  // the private OpenRGB copy in the RigLab vendor folder must not hold its files open during an upgrade
  Exec('powershell.exe', '-NoProfile -Command "Get-Process OpenRGB -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''*\RigLab\vendor\*'' } | Stop-Process -Force"',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillRunning();
  Result := '';
end;
