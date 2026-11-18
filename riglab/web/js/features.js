/* Every RigLab feature and where it lives in each view. This one list drives the "More tools" / "All tools"
   page and the Simple-view "Open in Advanced view" cards, and tests/test_feature_map.py checks it against the
   menu so nothing can exist in only one view.
   simple.page / advanced.page: the page it's on. simple.link = true: Simple view shows a card that switches to
   Advanced view and opens it. focus: a section on that page. Keep the part after "=" strict JSON. */
window.FEATURES = [
  {"id": "home", "name": "Home: health dial, Start here, presets", "simple": {"page": "home"}, "advanced": {"page": "home"}},
  {"id": "health", "name": "PC health check (quick and full) and report card", "simple": {"page": "dashboard"}, "advanced": {"page": "dashboard"}},
  {"id": "live", "name": "Live temperatures, loads and fans", "simple": {"page": "dashboard"}, "advanced": {"page": "dashboard"}},
  {"id": "explain", "name": "PC Info (your hardware in plain English)", "simple": {"page": "explain"}, "advanced": {"page": "explain"}},
  {"id": "sensors", "name": "Every sensor, graphs and recording to a file", "simple": {"page": "sensors", "link": true}, "advanced": {"page": "sensors"}},
  {"id": "hardware", "name": "Full hardware details and drive health", "simple": {"page": "hardware", "link": true}, "advanced": {"page": "hardware"}},
  {"id": "crashes", "name": "Crashes and freezes explained", "simple": {"page": "crashes"}, "advanced": {"page": "crashes"}},
  {"id": "benchmark", "name": "Speed test (benchmark)", "simple": {"page": "benchmark"}, "advanced": {"page": "benchmark"}},
  {"id": "stress", "name": "Stress test (check your PC is stable)", "simple": {"page": "stress", "link": true}, "advanced": {"page": "stress"}},
  {"id": "netspeed", "name": "Internet speed test", "simple": {"page": "netspeed"}, "advanced": {"page": "netspeed"}},
  {"id": "overclock", "name": "Overclocking (processor, memory, graphics card)", "simple": {"page": "overclock", "link": true}, "advanced": {"page": "overclock"}},
  {"id": "gputune", "name": "Graphics card tuning and results", "simple": {"page": "overclock", "link": true, "tab": "gputune"}, "advanced": {"page": "overclock", "tab": "gputune"}},
  {"id": "tweaks", "name": "Performance Tweaks (power plan, Windows settings)", "simple": {"page": "tweaks"}, "advanced": {"page": "tweaks"}},
  {"id": "risky_tweaks", "name": "Advanced Windows tweaks (GPU scheduling, network throttling)", "simple": {"page": "tweaks", "link": true, "focus": "windows"}, "advanced": {"page": "tweaks", "focus": "windows"}},
  {"id": "gpu_power", "name": "Graphics card power limit", "simple": {"page": "tweaks", "link": true, "focus": "gpu"}, "advanced": {"page": "tweaks", "focus": "gpu"}},
  {"id": "startup", "name": "Apps that start with Windows (with impact ratings)", "simple": {"page": "tweaks", "focus": "startup"}, "advanced": {"page": "tweaks", "focus": "startup"}},
  {"id": "storage", "name": "Free up space (biggest files, temp and update files)", "simple": {"page": "storage"}, "advanced": {"page": "storage"}},
  {"id": "fans", "name": "Fans: Quiet / Balanced / Cool", "simple": {"page": "cooling"}, "advanced": {"page": "cooling"}},
  {"id": "fan_curves", "name": "Fan curves (draw your own)", "simple": {"page": "cooling", "focus": "curves"}, "advanced": {"page": "cooling", "focus": "curves"}},
  {"id": "fan_manual", "name": "Hold a fan at one speed (testing)", "simple": {"page": "cooling", "link": true, "focus": "curves"}, "advanced": {"page": "cooling", "focus": "curves"}},
  {"id": "lighting", "name": "Lights (RGB effects, devices, LED map)", "simple": {"page": "lighting"}, "advanced": {"page": "lighting"}},
  {"id": "history", "name": "Change history and Undo", "simple": {"page": "history"}, "advanced": {"page": "history"}},
  {"id": "setup", "name": "RigLab setup (helpers RigLab needs)", "simple": {"page": "health", "link": true}, "advanced": {"page": "health"}},
  {"id": "themes", "name": "Themes and highlight colours", "simple": {"page": "themes"}, "advanced": {"page": "themes"}},
  {"id": "settings", "name": "Settings (warnings, start with Windows, help, about)", "simple": {"page": "settings"}, "advanced": {"page": "settings"}},
  {"id": "overlay", "name": "In-game overlay", "simple": {"page": "settings", "focus": "overlay"}, "advanced": {"page": "settings", "focus": "overlay"}},
  {"id": "tools", "name": "List of every tool (this page)", "simple": {"page": "tools"}, "advanced": {"page": "tools"}}
];
