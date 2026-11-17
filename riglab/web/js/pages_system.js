/* Tweaks, Health check, Settings */
"use strict";

// =================================================================== Tweaks
App.pages.tweaks = {
  async render(el) {
    this.el = el;
    this.rpDone = false;
    el.append(pageHead("Tweaks", "Safe, reversible Windows and gaming tweaks. RigLab makes a restore point before your first change each session.",
      h("button.btn", { onclick: () => this.restore(true) }, icon("undo"), "Create restore point")));
    this.body = h("div", h("div.empty", h("div.spinner")));
    el.append(this.body);
    const st = await App.api.tweaks_state();
    this.draw(st);
  },
  async restore(force) {
    if (this.rpDone && !force) return;
    toast("Creating restore point… (can take a minute)");
    const r = await App.api.restore_point();
    this.rpDone = r.ok || this.rpDone;
    toast((r.ok ? "✓ " : "✗ ") + r.msg, !r.ok);
  },
  draw(st) {
    const parts = [];
    if (!st.admin) parts.push(banner("bad", "alert", "Some tweaks need RigLab running as administrator.", h("button.btn.sm", { onclick: () => App.api.fix("restart_admin") }, "Restart as admin")));

    const plans = h("div.plans", st.plans.map(p => h("div.plan" + (p.active ? ".on" : ""), { onclick: async () => { await App.api.set_power_plan(p.guid); this.draw(await App.api.tweaks_state()); } },
      h("div.n", p.name), h("div.small.muted", p.active ? "Active" : "Click to use"))));
    parts.push(h("div.card", cardHead("Power plan", "bolt", h("button.btn.sm", { onclick: async () => { await App.api.add_ultimate(); this.draw(await App.api.tweaks_state()); } }, "+ Ultimate Performance")),
      h("div.sub", "High performance / Ultimate keep clocks up for lower latency but use more power. Balanced is fine for most modern CPUs."),
      st.plans.length ? plans : h("div.muted.small", "Windows only.")));

    const cats = {};
    for (const t of st.tweaks) (cats[t.cat] ||= []).push(t);
    const tcard = h("div.card.mt", cardHead("Windows & gaming", "rocket"));
    for (const [cat, list] of Object.entries(cats)) {
      tcard.append(h("div.nav-label", { style: { padding: "10px 0 0" } }, cat));
      for (const t of list) tcard.append(h("div.opt",
        h("div", h("div.t", t.name, t.reboot ? h("span.pill", { style: { marginLeft: "8px" } }, "restart needed") : null, t.admin && !st.admin ? h("span.pill.warn", { style: { marginLeft: "8px" } }, "needs admin") : null), h("div.d", t.desc)),
        switchEl(!!t.on, async (v, inp) => { await this.restore(false); const r = await App.api.tweak_set(t.id, v); if (r !== "ok") { inp.checked = !v; toast(r, true); } else toast(`${t.name}: ${v ? "on" : "off"}`); }, t.admin && !st.admin)));
    }
    parts.push(tcard);

    const g = st.gpu;
    const gcard = h("div.card.mt", cardHead("Graphics card power limit", "gpu"));
    if (g && !g.error) {
      let w = Math.round(g.cur);
      gcard.append(h("div.sub", `${g.name} · allowed ${Math.round(g.min)}–${Math.round(g.max)} W. Lower = cooler & quieter for a small FPS loss. Resets on reboot.`),
        h("div.row", h("div", { style: { flex: 1 } }, sliderRow("Limit", Math.round(g.min), Math.round(g.max), w, 1, " W", v => { w = v; })),
          h("button.btn", { onclick: async () => { const r = await App.api.set_gpu_power(w); toast(r === "ok" ? `Power limit ${w} W` : r, r !== "ok"); } }, "Apply")));
    } else gcard.append(h("div.muted.small", g && g.error ? g.error : "No NVIDIA card detected. AMD/Intel: use Adrenalin or Arc Control for power limits."));
    parts.push(gcard);

    const startup = h("div.card.mt", cardHead("Startup apps", "power"), h("div.sub", "Turn off apps you don't need starting with Windows. Same switch Task Manager uses - nothing is deleted."),
      st.startup.length ? h("div", st.startup.map(s => h("div.opt",
        h("div", h("div.t", s.name), h("div.d", { title: s.cmd }, s.where + " · " + (s.cmd.length > 90 ? s.cmd.slice(0, 90) + "…" : s.cmd))),
        switchEl(s.on, async (v, inp) => { const r = await App.api.startup_set(s.i, v); if (r !== "ok") { inp.checked = !v; toast(r, true); } }))))
        : h("div.muted.small", "Nothing found."));
    parts.push(startup);

    const junkTxt = h("span.muted.small", "");
    parts.push(h("div.card.mt", cardHead("Junk cleanup", "trash"),
      h("div.sub", "Deletes temp files and shader caches older than 24 h. Files in use are skipped. Games rebuild shader caches on next launch."),
      h("div.row", h("button.btn", { onclick: async () => { junkTxt.textContent = "Scanning…"; const r = await App.api.junk(false); junkTxt.textContent = `${fmt.bytes(r.bytes)} in ${fmt.n(r.files)} files can be removed`; } }, icon("search"), "Scan"),
        h("button.btn", { onclick: async () => { junkTxt.textContent = "Cleaning…"; const r = await App.api.junk(true); junkTxt.textContent = `Freed ${fmt.bytes(r.bytes)} (${fmt.n(r.files)} files)`; } }, icon("trash"), "Clean"), junkTxt)));
    this.body.replaceChildren(...parts);
  },
};

// =================================================================== Health check
App.pages.health = {
  async render(el) {
    this.el = el;
    el.append(pageHead("Health check", "Why a sensor or control might be missing, and one-click fixes.",
      h("button.btn", { onclick: () => this.load() }, icon("refresh"), "Re-check")));
    this.progress = h("div");
    el.append(this.progress);
    this.box = h("div.card");
    el.append(this.box);
    el.append(h("div.card.mt", cardHead("About Corsair fans", "fan"), h("div.small.muted", { style: { lineHeight: "1.7" } },
      "Turning lights off in OpenRGB only switches off the fans' LEDs - OpenRGB never controls fan speed. ",
      "Fan speed depends on what the fans are plugged into: ",
      h("br"), "• A ", h("b", "motherboard fan header"), " → controlled through LibreHardwareMonitor (needs admin + PawnIO).",
      h("br"), "• A ", h("b", "Corsair Commander Core / Core XT / ST / Commander Pro"), " → RigLab controls it directly via liquidctl. iCUE is not needed (close it if it's running).",
      h("br"), "• A ", h("b", "Corsair Lighting Node"), " → lighting only; the fans' speed cables go to the motherboard.",
      h("br"), "• An ", h("b", "iCUE LINK System Hub"), " → not supported by open-source tools yet; use iCUE, or FanControl with the CorsairLink plugin.")));
    this.load();
    const st = await App.api.lhm_status();
    if (st.running) this.watch();
  },
  async load() {
    this.box.replaceChildren(h("div.empty", h("div.spinner")));
    const items = await refreshHealth();
    this.box.replaceChildren(...items.map(i => {
      const btns = [];
      if (i.fix === "redownload_lhm") {
        btns.push(h("button.btn.sm" + (i.ok === false ? ".primary" : ""), { onclick: () => this.install(false) }, icon("download"), "Re-download"),
          h("button.btn.sm", { title: "Use a LibreHardwareMonitor.zip you downloaded in your browser", onclick: () => this.install(true) }, icon("folder"), "Install from zip…"));
        if (i.ok === false) btns.push(h("button.btn.sm", { onclick: async () => { toast(await App.api.fix("retry_lhm")); setTimeout(() => this.load(), 4000); } }, icon("refresh"), "Retry"));
      } else if (i.fix) {
        const b = h("button.btn.sm" + (i.ok === false ? ".primary" : ""), {
          onclick: async () => { b.disabled = true; b.textContent = "Working…"; toast(await App.api.fix(i.fix)); setTimeout(() => this.load(), 2500); } }, i.fix_label);
        btns.push(b);
      }
      let details = null;
      if (i.trace) {
        const pre = h("pre.log.hide", i.trace);
        details = h("div", { style: { marginTop: "6px" } },
          h("button.btn.sm.ghost", { onclick: () => pre.classList.toggle("hide") }, "Show error details"),
          h("button.btn.sm.ghost", { onclick: () => { navigator.clipboard.writeText(i.trace).then(() => toast("Copied - paste it to Claude"), () => toast("Couldn't copy", true)); } }, "Copy"),
          pre);
      }
      return h("div.check-item",
        h("div.st." + (i.ok === true ? "ok" : i.ok === false ? "bad" : "na"), icon(i.ok === true ? "check" : i.ok === false ? "x" : "info")),
        h("div", h("div", { style: { fontWeight: 600 } }, i.title), h("div.small.muted", i.detail), details),
        h("div.row", btns));
    }));
  },
  async install(fromZip) {
    if (fromZip) toast("Pick the LibreHardwareMonitor.zip you downloaded");
    const ok = await App.api.lhm_install(fromZip);
    if (!ok && !fromZip) toast("A download is already running");
    if (ok) this.watch();
  },
  async watch() {
    const bar = h("i"), step = h("div.small", "Starting…"), log = h("pre.log");
    this.progress.replaceChildren(h("div.card.glow", { style: { marginBottom: "16px" } },
      cardHead("Installing LibreHardwareMonitor", "download"), h("div.progress", bar), h("div", { style: { margin: "10px 0" } }, step), log));
    for (;;) {
      const st = await App.api.lhm_status();
      bar.style.width = Math.round(st.progress * 100) + "%";
      step.textContent = st.running ? st.step : st.ok ? `Done. Sensor library: ${st.lhm}` : "Failed: " + st.error;
      log.textContent = st.log.join("\n");
      log.scrollTop = log.scrollHeight;
      if (!st.running && !["starting", "updating"].includes(st.lhm)) {
        step.style.color = st.ok && st.lhm === "active" ? css("--good") : css("--bad");
        if (st.ok && st.lhm === "active") step.textContent = "Done - detailed sensors are loaded.";
        else if (st.ok) step.textContent = "Installed, but it didn't load: " + st.lhm + " (see error details below).";
        this.load();
        return;
      }
      await new Promise(r => setTimeout(r, 600));
    }
  },
};

// =================================================================== Settings
function overlayCard(ov) {
  ov.mode = ov.mode || "full"; ov.size = ov.size || "m"; ov.fps_color = ov.fps_color || "auto";
  if (ov.opacity == null) ov.opacity = 0.85;
  const box = h("div.card");
  const STYLES = [["full", "Full stats (CPU, GPU, RAM)"], ["fps", "FPS counter: number only"], ["fps_low", "FPS counter: + 1% low"],
    ["fps_time", "FPS counter: + frame time"], ["fps_detail", "FPS counter: detailed (1% low, frame time, game)"], ["fps_graph", "FPS counter: + frame-time graph"]];
  let moving = false;
  const moveBtn = h("button.btn.sm", { onclick: async () => {
    const r = await App.api.overlay_edit(!moving); moving = !!r.edit; ov.enabled = true;
    moveBtn.replaceChildren(icon(moving ? "check" : "move"), moving ? "Done moving" : "Move overlay");
    toast(moving ? "Drag the overlay where you want it, then click Done" : "Position saved"); draw(); } }, icon("move"), "Move overlay");
  const draw = () => {
    const counter = ov.mode !== "full";
    box.replaceChildren(cardHead("In-game overlay", "overlay"),
      h("div.sub", "Small always-on-top stats box. Works over games in borderless/windowed mode (not exclusive fullscreen). Clicks pass straight through it, except while you're moving it."),
      h("div.opt", h("div.t", "Show overlay"), switchEl(ov.enabled, v => { ov.enabled = v; })),
      h("div.opt", h("div.t", "Style"), h("select", { "aria-label": "Overlay style", onchange: e => { ov.mode = e.target.value; draw(); } },
        STYLES.map(([k, l]) => h("option", { value: k, selected: ov.mode === k }, l)))),
      !counter ? h("div.opt", h("div", h("div.t", "Show FPS"), h("div.d", "Adds an FPS row (FPS, 1% low, frame time) for the game in front, measured with PresentMon.")),
        switchEl(!!ov.show_fps, v => { ov.show_fps = v; })) : h("div.small.muted", { style: { padding: "2px 0 8px" } }, "FPS is measured with PresentMon only while the overlay is showing. The counter hides itself when no game is in front."),
      h("div.opt", h("div.t", "Text size"), h("select", { "aria-label": "Overlay text size", onchange: e => { ov.size = e.target.value; } },
        [["s", "Small"], ["m", "Medium"], ["l", "Large"], ["xl", "Extra large"]].map(([k, l]) => h("option", { value: k, selected: ov.size === k }, l)))),
      h("div.opt", h("div.t", "FPS colour"), h("select", { "aria-label": "FPS colour", onchange: e => { ov.fps_color = e.target.value; } },
        [["auto", "By performance (green / yellow / red)"], ["white", "White"], ["accent", "Cyan"]].map(([k, l]) => h("option", { value: k, selected: ov.fps_color === k }, l)))),
      h("div", { style: { padding: "6px 0" } }, sliderRow("Background", 0, 100, Math.round(ov.opacity * 100), 5, "%", v => { ov.opacity = v / 100; })),
      h("div.opt", h("div", h("div.t", "Position"), h("div.d", ov.x != null ? "Where you dragged it" : "Corner: " + (ov.corner || "top-left"))),
        h("div.row", { style: { gap: "6px" } }, moveBtn,
          h("select", { "aria-label": "Snap overlay to a corner", onchange: async e => { if (!e.target.value) return; ov.corner = e.target.value; ov.x = ov.y = null; await App.api.overlay_corner(e.target.value); toast("Snapped to " + e.target.value); draw(); } },
            h("option", { value: "" }, "Snap to corner…"), ["top-left", "top-right", "bottom-left", "bottom-right"].map(k => h("option", { value: k }, k))))),
      h("div.small.faint", "Style, size, colour and background apply when you press Save."));
  };
  draw();
  return box;
}

function appearanceCard(c) {
  const ui = c.ui || (c.ui = { theme: "dark", accent: "cyan", start_page: "home" });
  const box = h("div.card");
  const draw = () => {
    const modes = [["dark", "Dark", "#0b0e14", "#161b26"], ["light", "Light", "#f7f8fb", "#ffffff"], ["system", "Match Windows", "linear-gradient(90deg,#0b0e14 50%,#f7f8fb 50%)", ""]];
    box.replaceChildren(cardHead("Appearance", "sliders"),
      h("div.sub", "Changes apply instantly."),
      h("div.small.muted", { style: { margin: "6px 0 8px" } }, "Mode"),
      h("div.row.wrap", { style: { gap: "10px" } }, modes.map(([k, l, bg, fg]) => h("div.theme-mode" + (ui.theme === k ? ".on" : ""), { role: "button", tabIndex: 0, "aria-pressed": ui.theme === k,
        onclick: () => { ui.theme = k; Theme.set({ theme: k }); draw(); } },
        h("div.pv", { style: { background: bg } }, fg ? h("div", { style: { margin: "10px", height: "24px", borderRadius: "5px", background: fg, border: "1px solid rgba(128,128,128,.25)" } }) : null), h("b.small", l)))),
      h("div.small.muted", { style: { margin: "16px 0 8px" } }, "Colour theme"),
      h("div.row.wrap", { style: { gap: "12px" } }, Object.entries(THEME_ACCENTS).map(([k, l]) => {
        const pal = { cyan: ["#36d6ff", "#8f6bff"], violet: ["#a37bff", "#ff5fb8"], emerald: ["#2fe0a0", "#2fb5ff"], amber: ["#ffb636", "#ff6b3d"], crimson: ["#ff4d6d", "#ff9a3d"], ocean: ["#4d8dff", "#36d6ff"], mono: ["#c7cedb", "#7d8799"] }[k];
        return h("div", { style: { textAlign: "center" } }, h("div.theme-swatch" + (ui.accent === k ? ".on" : ""), { role: "button", tabIndex: 0, title: l, "aria-label": l + " colour theme", "aria-pressed": ui.accent === k,
          style: { background: `linear-gradient(135deg, ${pal[0]}, ${pal[1]})` }, onclick: () => { ui.accent = k; Theme.set({ accent: k }); draw(); } }), h("div.small.muted", { style: { marginTop: "4px" } }, l));
      })),
      h("div.opt", { style: { marginTop: "14px" } }, h("div", h("div.t", "Open RigLab on"), h("div.d", "The page you see when the app starts.")),
        h("select", { onchange: e => { ui.start_page = e.target.value; App.api.ui_set({ start_page: e.target.value }); } },
          [["home", "Home"], ["dashboard", "Dashboard"], ["last", "Last page I used"]].map(([v, l]) => h("option", { value: v, selected: (ui.start_page || "home") === v }, l)))));
  };
  draw();
  return box;
}

App.pages.settings = {
  async render(el) {
    const c = await App.api.settings();
    const a = c.alerts, ov = c.overlay;
    const save = async () => { await App.api.save_settings(c); toast("Settings saved"); };
    el.append(pageHead("Settings", null, h("button.btn.primary", { onclick: save }, icon("check"), "Save")));
    el.append(appearanceCard(c));
    el.append(h("div.grid.g2.mt",
      h("div.card", cardHead("Temperature alerts", "thermo"), h("div.sub", "A Windows notification pops up when something gets too hot."),
        h("div.opt", h("div.t", "Alerts on"), switchEl(a.enabled, v => { a.enabled = v; })),
        h("div.stack.mt", { style: { gap: "14px" } },
          sliderRow("CPU", 60, 105, a.cpu_temp_max, 1, "°C", v => { a.cpu_temp_max = v; }),
          sliderRow("GPU", 60, 100, a.gpu_temp_max, 1, "°C", v => { a.gpu_temp_max = v; }),
          sliderRow("Drives", 40, 80, a.drive_temp_max, 1, "°C", v => { a.drive_temp_max = v; }))),
      overlayCard(ov),
      h("div.card", cardHead("General", "gear"),
        h("div.opt", h("div", h("div.t", "Keep running in the tray"), h("div.d", "Closing the window keeps alerts and fan curves working.")), switchEl(c.minimize_to_tray, v => { c.minimize_to_tray = v; })),
        h("div.opt", h("div", h("div.t", "Start minimised")), switchEl(c.start_minimized, v => { c.start_minimized = v; })),
        h("div.opt", h("div", h("div.t", "Sensor refresh"), h("div.d", "Applies after restart")), h("select", { onchange: e => { c.poll_interval_ms = +e.target.value; } },
          [[500, "0.5 s"], [1000, "1 s"], [2000, "2 s"]].map(([v, l]) => h("option", { value: v, selected: c.poll_interval_ms === v }, l)))),
        h("div.opt", h("div", h("div.t", "CSV log interval")), h("input", { type: "number", min: 1, max: 600, value: c.logging.interval_s, style: { width: "80px" }, onchange: e => { c.logging.interval_s = +e.target.value; } })),
        h("div.opt", h("div", h("div.t", "Control USB fan hubs (Corsair Commander / NZXT)"), h("div.d", "Turn off if another app (iCUE, NZXT CAM) should own them. Lighting-only devices like the Lighting Node Pro are never touched. Applies after restart.")), switchEl((c.liquidctl || {}).enabled !== false, v => { c.liquidctl = c.liquidctl || { exclude: [] }; c.liquidctl.enabled = v; })),
        h("div.opt", h("div", h("div.t", "Start OpenRGB automatically"), h("div.d", "Launches OpenRGB in the background with its SDK server on when RigLab starts.")), switchEl(c.openrgb.autostart !== false, v => { c.openrgb.autostart = v; })),
        h("div.opt", h("div", h("div.t", "OpenRGB SDK port")), h("input", { type: "number", value: c.openrgb.port, style: { width: "100px" }, onchange: e => { c.openrgb.port = +e.target.value; } }))),
      h("div.card", cardHead("About", "info"),
        h("div.spec", h("div.k", "Version"), h("div.v", App.info.version), h("div.k", "Administrator"), h("div.v", App.info.admin ? "Yes" : "No"),
          ...Object.entries(App.snap.status).flatMap(([k, v]) => [h("div.k", k), h("div.v", { style: { color: v === "active" ? css("--good") : css("--muted") } }, v)])),
        h("div.row.mt", h("button.btn", { onclick: () => App.api.open_folder("data") }, icon("folder"), "Open data folder")))));
  },
};
