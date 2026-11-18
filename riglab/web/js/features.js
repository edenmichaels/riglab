/* Every RigLab feature and where it lives (3.12). This one list drives the Tools grid, the Settings tabs, the
   search box in the top bar and the Simple-view "advanced feature" tiles, and tests/test_feature_map.py checks
   it against the menu so nothing can exist in only one view.
   Each feature: id, name (what search shows), keywords, and where it is in each view:
     simple / advanced: {page, focus (a section on that page), tab (a tab on that page), link: true = Simple view
     shows a tile that switches to Advanced view and opens it}
   tile: shown as a tile on the Tools grid {short name, desc (one line), icon}.
   Keep each part after "=" strict JSON (the test reads it). */
window.MENU = [
  {"page": "home", "name": "Home", "icon": "home"},
  {"page": "dashboard", "name": "PC Health", "icon": "heart"},
  {"page": "lighting", "name": "Lighting", "icon": "light"},
  {"page": "tools", "name": "Tools", "icon": "grid"},
  {"page": "settings", "name": "Settings", "icon": "gear"}
];
window.SETTINGS_TABS = [
  {"page": "settings", "name": "General"},
  {"page": "themes", "name": "Themes"},
  {"page": "health", "name": "RigLab setup", "advanced": true}
];
window.FEATURES = [
  {"id": "home", "name": "Home", "keywords": "start main dial presets pinned", "simple": {"page": "home"}, "advanced": {"page": "home"}},
  {"id": "presets", "name": "Presets (Gaming, Balanced, Quiet...)", "keywords": "gaming quiet power saver streaming work balanced mode", "simple": {"page": "home", "focus": "presets"}, "advanced": {"page": "home", "focus": "presets"}},
  {"id": "health", "name": "PC Health check", "keywords": "score dial report quick full check scan", "simple": {"page": "dashboard"}, "advanced": {"page": "dashboard"}},
  {"id": "live", "name": "Live temperatures and usage", "keywords": "temperature temp cpu gpu usage load dashboard", "simple": {"page": "dashboard", "focus": "live"}, "advanced": {"page": "dashboard", "focus": "live"}},
  {"id": "lighting", "name": "Lighting", "keywords": "rgb lights led effect colour color rainbow off rescan", "simple": {"page": "lighting"}, "advanced": {"page": "lighting"}},
  {"id": "netspeed", "name": "Internet speed test", "keywords": "network wifi wi-fi download upload ping jitter internet broadband",
   "tile": {"short": "Speed Test", "desc": "How fast is your internet?", "icon": "speed"}, "simple": {"page": "netspeed"}, "advanced": {"page": "netspeed"}},
  {"id": "tweaks", "name": "Performance Tweaks", "keywords": "faster games smoother power plan windows settings game mode",
   "tile": {"short": "Performance Tweaks", "desc": "Make games smoother and Windows faster.", "icon": "rocket"}, "simple": {"page": "tweaks"}, "advanced": {"page": "tweaks"}},
  {"id": "power", "name": "How hard should my PC work (power plan)", "keywords": "power plan balanced high performance battery", "simple": {"page": "tweaks", "focus": "power"}, "advanced": {"page": "tweaks", "focus": "power"}},
  {"id": "startup", "name": "Startup programs", "keywords": "apps start with windows boot slow startup",
   "tile": {"short": "Startup Programs", "desc": "Choose which apps open with Windows.", "icon": "power"}, "simple": {"page": "tweaks", "focus": "startup"}, "advanced": {"page": "tweaks", "focus": "startup"}},
  {"id": "fans", "name": "Fans", "keywords": "fan cooling quiet noise curve pump",
   "tile": {"short": "Fans", "desc": "Quieter or cooler, in one click.", "icon": "fan"}, "simple": {"page": "cooling"}, "advanced": {"page": "cooling"}},
  {"id": "fan_curves", "name": "Fan curves", "keywords": "fan curve temperature speed", "simple": {"page": "cooling", "focus": "curves"}, "advanced": {"page": "cooling", "focus": "curves"}},
  {"id": "overlay", "name": "In-game overlay", "keywords": "fps overlay counter game hud frames hotkey",
   "tile": {"short": "Overlay", "desc": "See FPS and temperatures in your games.", "icon": "overlay"}, "simple": {"page": "overlay"}, "advanced": {"page": "overlay"}},
  {"id": "storage", "name": "Storage cleanup", "keywords": "disk space free up delete temp files big files drive full",
   "tile": {"short": "Storage Cleanup", "desc": "Free up space on your drives.", "icon": "trash"}, "simple": {"page": "storage"}, "advanced": {"page": "storage"}},
  {"id": "explain", "name": "PC Info", "keywords": "specs hardware what's inside processor graphics memory",
   "tile": {"short": "PC Info", "desc": "What's inside your PC, in plain words.", "icon": "chip"}, "simple": {"page": "explain"}, "advanced": {"page": "explain"}},
  {"id": "benchmark", "name": "PC benchmark", "keywords": "benchmark score how fast pc test",
   "tile": {"short": "PC Benchmark", "desc": "See how fast your PC is.", "icon": "bench"}, "simple": {"page": "benchmark"}, "advanced": {"page": "benchmark"}},
  {"id": "crashes", "name": "Crashes and freezes", "keywords": "crash blue screen bsod freeze restart error",
   "tile": {"short": "Crashes & Freezes", "desc": "Find out why your PC crashed.", "icon": "alert"}, "simple": {"page": "crashes"}, "advanced": {"page": "crashes"}},
  {"id": "history", "name": "Change history", "keywords": "undo changes history log revert",
   "tile": {"short": "Change History", "desc": "See and undo what RigLab changed.", "icon": "undo"}, "simple": {"page": "history"}, "advanced": {"page": "history"}},
  {"id": "sensors", "name": "Every sensor, graphs and recording", "keywords": "sensors voltage clock graph log csv",
   "tile": {"short": "Sensors", "desc": "Every sensor, with graphs and recording.", "icon": "pulse"}, "simple": {"page": "sensors", "link": true}, "advanced": {"page": "sensors"}},
  {"id": "hardware", "name": "Hardware details and drive health", "keywords": "hardware specs smart drive health serial",
   "tile": {"short": "Hardware Details", "desc": "Full specs and drive health.", "icon": "board"}, "simple": {"page": "hardware", "link": true}, "advanced": {"page": "hardware"}},
  {"id": "stress", "name": "Stress test", "keywords": "stability stress test burn",
   "tile": {"short": "Stress Test", "desc": "Check your PC is stable under load.", "icon": "flame"}, "simple": {"page": "stress", "link": true}, "advanced": {"page": "stress"}},
  {"id": "overclock", "name": "Overclocking", "keywords": "overclock oc cpu ram memory xmp tuning",
   "tile": {"short": "Overclocking", "desc": "Guided processor, memory and graphics tuning.", "icon": "bolt"}, "simple": {"page": "overclock", "link": true}, "advanced": {"page": "overclock"}},
  {"id": "gputune", "name": "Graphics card tuning and results", "keywords": "gpu tuning undervolt clock afterburner",
   "tile": {"short": "Graphics Tuning", "desc": "Live sliders and before/after results.", "icon": "gpu"}, "simple": {"page": "overclock", "link": true, "tab": "gputune"}, "advanced": {"page": "overclock", "tab": "gputune"}},
  {"id": "risky_tweaks", "name": "Advanced Windows tweaks", "keywords": "gpu scheduling hags network throttling",
   "tile": {"short": "Windows Tweaks", "desc": "Extra Windows settings that need a restart.", "icon": "sliders"}, "simple": {"page": "tweaks", "link": true, "focus": "windows"}, "advanced": {"page": "tweaks", "focus": "windows"}},
  {"id": "gpu_power", "name": "Graphics card power limit", "keywords": "gpu power limit watts quieter cooler",
   "tile": {"short": "Graphics Power", "desc": "Make the graphics card cooler and quieter.", "icon": "gpu"}, "simple": {"page": "tweaks", "link": true, "focus": "gpu"}, "advanced": {"page": "tweaks", "focus": "gpu"}},
  {"id": "fan_manual", "name": "Hold a fan at one speed", "keywords": "fixed fan speed manual",
   "tile": {"short": "Fixed Fan Speed", "desc": "Hold a fan at one speed for testing.", "icon": "fan"}, "simple": {"page": "cooling", "link": true, "focus": "curves"}, "advanced": {"page": "cooling", "focus": "curves"}},
  {"id": "settings", "name": "Settings", "keywords": "options preferences", "simple": {"page": "settings"}, "advanced": {"page": "settings"}},
  {"id": "view", "name": "Simple or Advanced view", "keywords": "simple advanced detail view mode", "simple": {"page": "settings", "focus": "view"}, "advanced": {"page": "settings", "focus": "view"}},
  {"id": "text_size", "name": "Text size and animations", "keywords": "text size bigger font zoom animation reduce motion", "simple": {"page": "settings", "focus": "display"}, "advanced": {"page": "settings", "focus": "display"}},
  {"id": "alerts", "name": "Too-hot warnings", "keywords": "temperature alerts warning notification hot", "simple": {"page": "settings", "focus": "alerts"}, "advanced": {"page": "settings", "focus": "alerts"}},
  {"id": "autostart", "name": "Start with Windows", "keywords": "startup autostart boot start with windows tray", "simple": {"page": "settings", "focus": "startup"}, "advanced": {"page": "settings", "focus": "startup"}},
  {"id": "themes", "name": "Themes and highlight colour", "keywords": "theme dark light colour color accent look", "simple": {"page": "themes"}, "advanced": {"page": "themes"}},
  {"id": "setup", "name": "RigLab setup and start-up log", "keywords": "setup helpers drivers log diagnose startup log lighting log",
   "simple": {"page": "health", "link": true}, "advanced": {"page": "health"}},
  {"id": "tools", "name": "All tools", "keywords": "tools list everything", "simple": {"page": "tools"}, "advanced": {"page": "tools"}}
];

/* Search: rank features by how well the words match (name first, then keywords). Pure - tested with node. */
window.searchFeatures = function (q, features, simple) {
  const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const out = [];
  for (const f of features || []) {
    const name = f.name.toLowerCase(), more = ((f.keywords || "") + " " + ((f.tile || {}).short || "") + " " + ((f.tile || {}).desc || "")).toLowerCase();
    let score = 0;
    for (const w of words) {
      if (name.startsWith(w)) score += 6;
      else if (new RegExp("\\b" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).test(name)) score += 4;
      else if (name.includes(w)) score += 3;
      else if (more.includes(w)) score += 2;
      else { score = 0; break; }                       // every word must match somewhere
    }
    if (score) out.push({ f, score: score + (f.tile ? 1 : 0), advanced: !!(simple && f.simple.link) });
  }
  return out.sort((a, b) => b.score - a.score || a.f.name.length - b.f.name.length).slice(0, 8);
};
window.DEFAULT_PINS = ["netspeed", "storage", "fans", "overlay"];
window.MAX_PINS = 4;
