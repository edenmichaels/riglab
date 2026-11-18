RigLab 3.11.0
=============

NEW IN 3.11.0
  In-game overlay (fixed)
  - Why it kept disappearing: the FPS-only counter hid itself whenever the window in front wasn't the one
    drawing frames (launchers, anti-cheat, Store games); borderless games could cover it because RigLab never
    put it back on top; a Windows setting could make the click-through window invisible; and sizes were
    mixed up at 125% / 150% display scaling. All fixed. It now stays on top (checked every 2 seconds), uses
    the busiest game if the front window isn't drawing, and sizes itself correctly at any scaling.
  - Clicks go straight through it to your game. To move it, hold Ctrl+Alt (changeable) and drag, or press
    "Edit position" in Settings > In-game overlay. You see an outline and a drag bar; it locks again after.
  - Exclusive fullscreen games: RigLab tells you once, in plain words, to switch the game to Borderless or
    Windowed fullscreen (Windows doesn't let anything draw over exclusive fullscreen).
  - The status line in Settings shows if it's hidden by the show/hide key or if the key is taken.
  Lighting after a restart
  - The first time RigLab starts after Windows boots, it looks for your lighting devices again (for up to
    about a minute) and reapplies your last effect. If a device is missing you get a quiet notice.
  - RigLab now starts with Windows (minimised, no admin pop-up). Turn it off in Settings > Start-up.
  New
  - Internet speed (Tools): download, upload, ping, jitter, packet loss, server, internet provider, public
    IP (hidden until you press Show), cable or Wi-Fi with signal and band, a plain summary and past results.
    Uses Cloudflare's speed test servers. A test uses some data (up to about 300 MB on fast internet).
  - Undo button in the top bar: undoes your last change. The arrow lists recent changes. Covers presets,
    tweaks, fans, power plans, start-up apps, Fix it, lights, overlay, settings and themes.
  - Themes have their own page (RigLab > Themes).
  - More tools / All tools: every feature in one list. Advanced features show a card in Simple view that
    takes you straight there.
  - Smoother health dial: a scanning glow while checking, then it fills, counts up and changes colour.
    Settings > Display > Reduce animations (RigLab also follows Windows' animation setting).
  Changed
  - "My PC Explained" is now "PC Info". The "One-click for gamers" card is gone (use the Gaming preset on
    Home or "Put games first"). "How hard should my PC work" is now at the top of Performance Tweaks.

NEW IN 3.10.0
  Help
  - A short walkthrough the first time RigLab opens (skip it, or replay it from Settings).
  - A tip at the top of each page, with "Got it" and "Don't show again".
  - "Start here" on Home: My PC is slow / My games stutter / Check if my PC is healthy / Clean up space.
  PC health
  - Quick check and Full check. The full check adds a Windows Defender virus scan, sfc and DISM checks,
    driver ages and Windows updates. Every check also looks at Device Manager, and at keyboard, mouse,
    screens, sound, network and USB. Progress, time left, Cancel, "skipped, no internet" when offline,
    a score-over-time chart, and Save report (text, or PDF with Microsoft Print to PDF).
  - Fix it buttons: repair Windows files (sfc), repair the Windows store (DISM, needs internet), test memory
    on the next restart, and shortcuts to Windows Update, Device Manager and Windows Security.
  - If you use another antivirus (e.g. Norton), RigLab says so instead of running a Defender scan.
  Extras
  - My PC explained: your hardware in plain English.
  - Free up space: drive space, temporary files, old Windows update files and your biggest files
    (moved to the Recycle Bin, never deleted outright).
  - Startup apps show a High / Medium / Low impact rating.
  - Optional weekly quick check (Sundays at 7 pm) with a notification. Off unless you turn it on.
  Look and feel
  - Themes: Dark, Light, Dracula, Nord, Catppuccin Mocha, Gruvbox, Solarized Dark, Tokyo Night, One Dark,
    High Contrast (credits in Settings > About). Text size: Small / Normal / Large / Extra Large (Aa button).
  In-game overlay
  - Pick exactly what it shows (FPS, 1% lows, frame time, CPU/GPU temps, usage, clocks, RAM, graph),
    side by side or stacked, size, background, text colour. Presets: Minimal, Standard, Full.
  - Unlock to drag it anywhere (it stays on screen, and can snap to corners), shrink it to a dot,
    lock it so clicks go to your game, and an optional show/hide key.

NEW IN 3.9.0
  - Simple / Advanced switch in the top bar of every page. It switches instantly and remembers your choice.
  - Home: a big health dial (0-100) in the centre. Click it to open PC Health. "Run a quick check" scores
    temperatures, memory, free space, fans, drive health and crashes in the last 30 days.
  - Home presets: Gaming, Balanced, Quiet, Power Saver, Streaming / Creating, Work / Focus. Clicking one
    shows exactly what will change first; nothing happens until you press Apply. One Undo puts it all back.
  - PC Health page (was "How my PC is doing"): the same dial with a report card underneath.
  - "What do the colours mean?" keys on every page that uses coloured dots or risk levels.
  - Renamed: "Make it better" -> Tools, "Speed-ups" -> Performance Tweaks.
  - New Windows switch: pop-up notifications on/off (used by the Gaming, Streaming and Work presets).
  - Clearer wording throughout Simple view.

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
  3. When it finishes, the "Installer" folder opens with RigLab-Setup-3.11.0.exe.
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
