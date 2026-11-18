/* Tweaks, Health check, Settings */
"use strict";

// =================================================================== Tweaks
const PLAN_PLAIN = { "power saver": ["Save power", "Slower, cooler and quieter. Good for laptops on battery."],
  "balanced": ["Balanced (recommended)", "Fast when you need it, saves power the rest of the time."],
  "high performance": ["Full speed", "Keeps the processor ready at all times. Uses more power."],
  "ultimate performance": ["Maximum speed", "Like Full speed, with even less waiting. Uses the most power."] };

App.pages.tweaks = {
  async render(el) {
    this.el = el;
    el.append(plainHead("Performance Tweaks", "Simple changes that make your PC feel faster. You can undo every change in Change history.",
      "Tweaks", "Windows and gaming tweaks. Every change is logged in Change history and can be undone. Medium-risk changes make a restore point first.",
      actionBtn("restore.create", () => this.restore(), { icon: "undo", label: isSimple() ? "Make a safety backup" : "Create restore point" })));
    this.body = h("div", h("div.empty", h("div.spinner")));
    el.append(h("div", { style: { margin: "-8px 0 12px" } }, riskKey()), this.body);
    const st = await App.api.tweaks_state();
    this.draw(st);
  },
  async restore() {
    const b = busyModal("Making a restore point… this can take a minute.");
    let r;
    try { r = await App.api.restore_point(); } finally { b.close(); }
    toast((r.ok ? "✓ " : "✗ ") + r.msg, !r.ok);
  },
  async redraw() { this.draw(await App.api.tweaks_state()); },
  draw(st) {
    const S = isSimple(), parts = [];


    const plainPlan = (p) => PLAN_PLAIN[p.name.toLowerCase()] || [p.name, ""];
    const plans = h("div.plans", st.plans.map(p => h("div.plan" + (p.active ? ".on" : ""), { role: "button", tabIndex: 0,
      onclick: async () => { if (p.active) return; const ok = await guarded("power.plan", () => App.api.set_power_plan(p.guid)); if (ok != null) { toast(S ? "Now using: " + plainPlan(p)[0] : "Power plan: " + p.name); this.redraw(); } } },
      h("div.n", S ? plainPlan(p)[0] : p.name), h("div.small.muted", p.active ? (S ? "In use now" : "Active") : (S ? plainPlan(p)[1] || "Click to use" : "Click to use")))));
    parts.push(h("div.card", { "data-anchor": "power" }, cardHead(S ? "How hard should my PC work?" : "Power plan", "bolt", infoBtn("power.plan"),
      actionBtn("power.ultimate", async () => { await App.api.add_ultimate(); this.redraw(); }, { cls: "sm", label: S ? "+ Maximum speed" : "+ Ultimate Performance" })),
      h("div.sub", S ? "Pick one. You can change it back any time." : "High performance / Ultimate keep clocks up for lower latency but use more power. Balanced is fine for most modern CPUs."),
      st.plans.length ? plans : h("div.muted.small", "Windows only.")));
    if (!st.admin) parts.push(h("div.mt", banner("bad", "alert", S ? "Some of these need RigLab to have full permission (administrator)." : "Some tweaks need RigLab running as administrator.",
      h("button.btn.sm", { onclick: () => App.api.fix("restart_admin") }, S ? "Give RigLab permission" : "Restart as admin"))));

    const cats = {};
    for (const t of st.tweaks) (cats[t.cat] ||= []).push(t);
    const tcard = h("div.card.mt", { "data-anchor": "windows" }, cardHead(S ? "Windows settings" : "Windows & gaming", "sliders"));
    let shownCount = 0;
    for (const [cat, list] of Object.entries(cats)) {
      const rows = list.map(t => {
        const pills = [];
        if (t.reboot) pills.push(h("span.pill", { style: { marginLeft: "8px" } }, S ? "needs a restart" : "restart needed"));
        if (t.admin && !st.admin) pills.push(h("span.pill.warn", { style: { marginLeft: "8px" } }, "needs admin"));
        return switchRow("tweak." + t.id, t.on, async (v) => { const r = await App.api.tweak_set(t.id, v); if (r !== "ok") { toast(r, true); return false; } toast(`${S ? act("tweak." + t.id).label : t.name}: ${v ? "on" : "off"}`); return true; },
          { label: S ? undefined : t.name, desc: S ? undefined : t.desc, pills, disabled: t.admin && !st.admin });
      }).filter(Boolean);
      if (!rows.length) continue;
      shownCount += rows.length;
      tcard.append(h("div.nav-label", { style: { padding: "10px 0 0" } }, S ? ({ Gaming: "Games", Input: "Mouse", Visual: "Looks", Network: "Internet" }[cat] || cat) : cat), ...rows);
    }
    parts.push(tcard);
    if (S) parts.push(h("div.mt.stack", { style: { gap: "8px" } },
      st.tweaks.length > shownCount ? advLink("More Windows settings (GPU scheduling, network throttling)", "tweaks", { focus: "windows", desc: "Medium-risk settings that need a restart." }) : null,
      advLink("Graphics card power limit", "tweaks", { focus: "gpu", icon: "gpu", desc: "Make the graphics card cooler and quieter by limiting its power." })));

    if (!S) {
      const g = st.gpu;
      const gcard = h("div.card.mt", { "data-anchor": "gpu" }, cardHead("Graphics card power limit", "gpu", infoBtn("gpu.power_limit")));
      if (g && !g.error) {
        let w = Math.round(g.cur);
        gcard.append(h("div.sub", `${g.name} · allowed ${Math.round(g.min)}–${Math.round(g.max)} W. Lower = cooler & quieter for a small FPS loss. Resets on reboot.`),
          h("div.row", h("div", { style: { flex: 1 } }, sliderRow("Limit", Math.round(g.min), Math.round(g.max), w, 1, " W", v => { w = v; })),
            actionBtn("gpu.power_limit", async () => { const r = await App.api.set_gpu_power(w); toast(r === "ok" ? `Power limit ${w} W` : r, r !== "ok"); }, { label: "Apply" })));
      } else gcard.append(h("div.muted.small", g && g.error ? g.error : "No NVIDIA card detected. AMD/Intel: use Adrenalin or Arc Control for power limits."));
      parts.push(gcard);
    }

    const IMPACT = { High: "bad", Medium: "warn", Low: "good" };
    const startup = h("div.card.mt", { "data-anchor": "startup" }, cardHead(S ? "Apps that open when Windows starts" : "Startup apps", "power", infoBtn("startup.toggle")),
      h("div.sub", S ? "Fewer apps here means Windows starts faster. Switching one off doesn't delete it - you can still open it yourself." : "Turn off apps you don't need starting with Windows. Same switch Task Manager uses - nothing is deleted."),
      st.startup.length ? h("div", st.startup.map(x => {
        const pill = x.impact ? h("span.pill.impact." + IMPACT[x.impact], { title: x.why, style: { marginLeft: "8px" } }, x.impact + " impact") : null;
        const row = switchRow("startup.toggle", x.on, async (v) => { const r = await App.api.startup_set(x.i, v); if (r !== "ok") { toast(r, true); return false; } return true; },
          { label: x.name, pills: pill ? [pill] : [], desc: S ? (x.why || (x.on ? "Opens when Windows starts" : "Doesn't open by itself")) : x.where + " · " + (x.cmd.length > 90 ? x.cmd.slice(0, 90) + "…" : x.cmd) });
        if (!S) row.querySelector(".d").title = x.cmd;
        return row;
      })) : h("div.muted.small", "Nothing found."),
      h("details.key", h("summary", "What do the impact ratings mean?"), h("div.key-body",
        h("div.key-row", h("span.pill.bad.impact", "High impact"), "Slows Windows down for a while after it starts. Good to switch off if you don't need it straight away."),
        h("div.key-row", h("span.pill.warn.impact", "Medium impact"), "Uses a little time and memory when Windows starts."),
        h("div.key-row", h("span.pill.good.impact", "Low impact"), "A small helper. It barely affects start-up."),
        h("div.small.muted", "These are RigLab's estimates from the app's name and size. Windows doesn't say exactly."))));
    parts.push(startup);

    parts.push(h("div.card.mt", cardHead(S ? "Free up space" : "Junk cleanup", "trash"),
      h("div.sub", "Temporary files, old Windows update files and your biggest files are now on their own page."),
      h("button.btn", { onclick: () => go("storage") }, icon("trash"), S ? "Go to Free up space" : "Open Storage cleanup")));
    this.body.replaceChildren(...parts);
  },
};

// =================================================================== Health check
App.pages.health = {
  async render(el) {
    this.el = el;
    el.append(plainHead("RigLab setup", "Checks that RigLab has everything it needs to read temperatures and control fans and lights. Press Fix it next to anything red.",
      "RigLab setup", "Why a sensor or control might be missing, and one-click fixes.",
      h("button.btn", { onclick: () => this.load() }, icon("refresh"), isSimple() ? "Check again" : "Re-check")));
    this.progress = h("div");
    el.append(this.progress);
    this.box = h("div.card");
    el.append(this.box);
    const corsair = h("div.card.mt", cardHead("About Corsair fans", "fan"), h("div.small.muted", { style: { lineHeight: "1.7" } },
      "Turning lights off in OpenRGB only switches off the fans' LEDs - OpenRGB never controls fan speed. ",
      "Fan speed depends on what the fans are plugged into: ",
      h("br"), "• A ", h("b", "motherboard fan header"), " → controlled through LibreHardwareMonitor (needs admin + PawnIO).",
      h("br"), "• A ", h("b", "Corsair Commander Core / Core XT / ST / Commander Pro"), " → RigLab controls it directly via liquidctl. iCUE is not needed (close it if it's running).",
      h("br"), "• A ", h("b", "Corsair Lighting Node"), " → lighting only; the fans' speed cables go to the motherboard.",
      h("br"), "• An ", h("b", "iCUE LINK System Hub"), " → not supported by open-source tools yet; use iCUE, or FanControl with the CorsairLink plugin."));
    el.append(isSimple() ? details("Why can't RigLab control my Corsair fans?", corsair) : corsair);
    this.logBox = h("div.card.mt", { "data-anchor": "startlog" });
    el.append(this.logBox);
    this.drawLog();
    this.load();
    const st = await App.api.lhm_status();
    if (st.running) this.watch();
  },
  /* Start-up log: what RigLab scanned and found at start-up, after sleep and when devices were plugged in. */
  async drawLog() {
    let r = { items: [], text: "" };
    try { r = await App.api.startup_log(); } catch { /* none */ }
    if (!this.logBox || !this.logBox.isConnected && this.logBox.dataset.drawn) return;
    this.logBox.dataset.drawn = "1";
    const lv = { info: "good", warn: "warn", error: "bad" };
    const rows = (r.items || []).slice(0, 60).map(e => h("div.log-row", dot(lv[e.level] || "none"),
      h("span.small.muted.mono", new Date(e.time * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" })),
      h("span", safe(e.text))));
    this.logBox.replaceChildren(cardHead("Start-up log", "report",
        h("button.btn.sm", { onclick: () => this.drawLog() }, icon("refresh"), "Refresh"),
        h("button.btn.sm", { onclick: () => navigator.clipboard.writeText(r.text || "").then(() => toast("Start-up log copied - paste it when asking for help"), () => toast("Couldn't copy", true)) }, icon("download"), "Copy")),
      h("div.sub", "What RigLab looked for when it started, after the PC woke from sleep, and when devices were plugged in - and what it found."),
      rows.length ? h("div.log-list", rows) : h("div.small.muted", "Nothing logged yet."),
      colourKey({ label: "What do the dots mean?" }));
  },
  async load() {
    this.box.replaceChildren(h("div.empty", h("div.spinner")));
    const items = await refreshHealth();
    this.box.replaceChildren(...items.map(i => {
      const btns = [];
      if (i.fix === "redownload_lhm") {
        btns.push(infoBtn("setup.sensors"), h("button.btn.sm" + (i.ok === false ? ".primary" : ""), { onclick: () => this.install(false) }, icon("download"), "Re-download"),
          h("button.btn.sm", { title: "Use a LibreHardwareMonitor.zip you downloaded in your browser", onclick: () => this.install(true) }, icon("folder"), "Install from zip…"));
        if (i.ok === false) btns.push(h("button.btn.sm", { onclick: async () => { toast(await App.api.fix("retry_lhm")); setTimeout(() => this.load(), 4000); } }, icon("refresh"), "Retry"));
      } else if (i.fix) {
        const b = h("button.btn.sm" + (i.ok === false ? ".primary" : ""), {
          onclick: async () => { b.disabled = true; b.textContent = "Working…"; toast(await App.api.fix(i.fix)); setTimeout(() => this.load(), 2500); } }, i.fix_label);
        btns.push(b, infoBtn("setup.fix"));
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
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* Display: text size, start page and animations. (Themes and colours have their own Themes page.) */
function displayCard(c) {
  const ui = c.ui || (c.ui = {});
  const box = h("div.card#display", { "data-anchor": "display" });
  const draw = () => {
    const cur = Theme.cur;
    box.replaceChildren(cardHead("Display", "monitor"),
      h("div.opt", h("div", h("div.t", "Text size"), h("div.d", "Makes all text, buttons and cards bigger or smaller. Also on the Aa button at the top.")),
        h("div.seg", TEXT_SIZES.map(([v, l]) => h("button" + (+cur.text_scale === v ? ".on" : ""), { "aria-pressed": +cur.text_scale === v,
          onclick: () => { ui.text_scale = v; Theme.set({ text_scale: v }); draw(); } }, l)))),
      h("div.opt", h("div", h("div.t", "Reduce animations"), h("div.d", "Shows simple fades instead of moving effects (like the health dial filling up). RigLab also follows Windows' own 'Animation effects' setting.")),
        switchEl(!!cur.reduce_motion, (v) => { ui.reduce_motion = v; Theme.set({ reduce_motion: v }); })),
      h("div.opt", h("div", h("div.t", "Open RigLab on"), h("div.d", "The page you see when the app starts.")),
        h("select", { onchange: e => { ui.start_page = e.target.value; App.api.ui_set({ start_page: e.target.value }); } },
          [["home", "Home"], ["dashboard", isSimple() ? "PC Health" : "Dashboard"], ["last", "Last page I used"]].map(([v, l]) => h("option", { value: v, selected: (ui.start_page || "home") === v }, l)))),
      h("div.small.muted", { style: { paddingTop: "8px" } }, "Themes and colours are on the ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); go("themes"); } }, "Themes"), " page."));
  };
  draw();
  return box;
}

function helpCard() {
  const box = h("div.card", { "data-anchor": "startup" });
  const draw = async () => {
    let w = { on: false }, a = { on: false };
    try { w = await App.api.weekly_state(); a = await App.api.autostart_state(); } catch { /* preview */ }
    box.replaceChildren(cardHead("Start-up, help and regular checks", "info"),
      h("div.opt", h("div", h("div.t", "Walkthrough"), h("div.d", "A short tour of the main screen.")),
        h("button.btn.sm", { onclick: () => Tour.start() }, icon("play"), "Replay the walkthrough")),
      h("div.opt", h("div", h("div.t", "Tips"), h("div.d", "The tips at the top of each page, including ones you chose not to show again.")),
        h("button.btn.sm", { onclick: async () => { await Tips.reset(); toast("Tips will show again on each page"); } }, icon("refresh"), "Show tips again")),
      switchRow("autostart.set", a.on, async (v) => { const r = await App.api.autostart_set(v); toast(r.msg, !r.ok); return !!r.ok; },
        { always: true, desc: "Starts RigLab in the tray when you sign in, so your lights, fans and overlay come back after a restart." }),
      switchRow("weekly.set", w.on, async (v) => { const r = await App.api.weekly_set(v); toast(r.msg, !r.ok); return !!r.ok; },
        { always: true, desc: "Runs a quick check every Sunday at 7 pm and shows your score in a notification. Off unless you turn it on." }));
  };
  draw();
  return box;
}

function creditsList() {
  return details("Credits and licences", h("div.small", { style: { lineHeight: 1.7 } },
    THEMES.filter(([, , c]) => /licen/i.test(c)).map(([, n, c]) => h("div", h("b", n), " - ", c)),
    h("div.muted", "All theme palettes are used under the MIT licence, which allows use in commercial software with credit."),
    h("div", { style: { marginTop: "6px" } }, h("b", "Icons"), " - the Undo, star, back-arrow and help icons are from Lucide (lucide.dev), ISC licence. Other icons are RigLab's own."),
    h("div", h("b", "Speed test"), " - uses Cloudflare's speed test servers (speed.cloudflare.com).")));
}

function viewCard() {
  const box = h("div.card.glow", { "data-anchor": "view" });
  const draw = () => {
    const S = isSimple();
    const b = (v, l) => h("button" + ((v === "simple") === S ? ".on" : ""), { "aria-pressed": (v === "simple") === S, onclick: () => setView(v) }, l);
    box.replaceChildren(cardHead("How much detail?", "sliders"),
      h("div.row.wrap", { style: { gap: "16px" } }, h("div.seg", b("simple", "Simple"), b("advanced", "Advanced")),
        h("div.small.muted", { style: { flex: 1, minWidth: "240px" } }, S
          ? "Simple shows plain words and green / yellow / red lights, and hides risky settings. Nothing is removed - switch to Advanced to see everything."
          : "Advanced shows every sensor, voltage, clock speed and hardware detail, plus overclocking, stress tests and risky tweaks.")));
  };
  draw();
  return box;
}

App.pages.settings = {
  async render(el) {
    const c = await App.api.settings();
    const a = c.alerts, S = isSimple();
    const save = async () => { await App.api.save_settings(c); try { App.info = await App.api.info(); } catch { /* keep old */ } toast("Settings saved"); };
    el.append(pageHead("Settings", null, h("button.btn.primary", { onclick: save }, icon("check"), "Save")));
    el.append(viewCard());
    el.append(h("div.mt", displayCard(c)));
    const general = [
      h("div.opt", h("div", h("div.t", S ? "Keep RigLab running when I close the window" : "Keep running in the tray"), h("div.d", S ? "Temperature warnings and your fan settings keep working. RigLab sits by the clock." : "Closing the window keeps alerts and fan curves working.")), switchEl(c.minimize_to_tray, v => { c.minimize_to_tray = v; })),
      h("div.opt", h("div", h("div.t", S ? "Start hidden by the clock" : "Start minimised")), switchEl(c.start_minimized, v => { c.start_minimized = v; }))];
    const technical = [
        h("div.opt", h("div", h("div.t", "Sensor refresh"), h("div.d", "Applies after restart")), h("select", { onchange: e => { c.poll_interval_ms = +e.target.value; } },
          [[500, "0.5 s"], [1000, "1 s"], [2000, "2 s"]].map(([v, l]) => h("option", { value: v, selected: c.poll_interval_ms === v }, l)))),
        h("div.opt", h("div", h("div.t", "CSV log interval")), h("input", { type: "number", min: 1, max: 600, value: c.logging.interval_s, style: { width: "80px" }, onchange: e => { c.logging.interval_s = +e.target.value; } })),
        h("div.opt", h("div", h("div.t", "Control USB fan hubs (Corsair Commander / NZXT)"), h("div.d", "Turn off if another app (iCUE, NZXT CAM) should own them. Lighting-only devices like the Lighting Node Pro are never touched. Applies after restart.")), switchEl((c.liquidctl || {}).enabled !== false, v => { c.liquidctl = c.liquidctl || { exclude: [] }; c.liquidctl.enabled = v; })),
        h("div.opt", h("div", h("div.t", "Start OpenRGB automatically"), h("div.d", "Launches OpenRGB in the background with its SDK server on when RigLab starts.")), switchEl(c.openrgb.autostart !== false, v => { c.openrgb.autostart = v; })),
        h("div.opt", h("div", h("div.t", "OpenRGB SDK port")), h("input", { type: "number", value: c.openrgb.port, style: { width: "100px" }, onchange: e => { c.openrgb.port = +e.target.value; } }))];
    const about = [h("div.spec", h("div.k", "Version"), h("div.v", App.info.version), h("div.k", "Administrator"), h("div.v", App.info.admin ? "Yes" : "No"),
          ...(S ? [] : Object.entries(App.snap.status).flatMap(([k, v]) => [h("div.k", k), h("div.v", { style: { color: v === "active" ? css("--good") : css("--muted") } }, v)]))),
        h("div.row.mt", h("button.btn", { onclick: () => App.api.open_folder("data") }, icon("folder"), S ? "Open RigLab's folder" : "Open data folder"))];
    if (S) {
      el.append(h("div.grid.g2.mt",
        h("div.card", { "data-anchor": "alerts" }, cardHead("Too-hot warnings", "thermo"), h("div.sub", "A Windows pop-up warns you when something gets too hot. These limits also decide when lights turn yellow and red."),
          h("div.opt", h("div.t", "Warn me"), switchEl(a.enabled, v => { a.enabled = v; })),
          details("Change the limits",
            h("div.stack", { style: { gap: "14px" } },
              sliderRow("Processor", 60, 105, a.cpu_temp_max, 1, "°C", v => { a.cpu_temp_max = v; }),
              sliderRow("Graphics card", 60, 100, a.gpu_temp_max, 1, "°C", v => { a.gpu_temp_max = v; }),
              sliderRow("Drives", 40, 80, a.drive_temp_max, 1, "°C", v => { a.drive_temp_max = v; })))),
        h("div.card", cardHead("General", "gear"), ...general, details("Technical settings", ...technical)),
        h("div.card", cardHead("About", "info"), ...about, creditsList()),
        helpCard()));
      return;
    }
    el.append(h("div.grid.g2.mt",
      h("div.card", { "data-anchor": "alerts" }, cardHead("Temperature alerts", "thermo"), h("div.sub", "A Windows notification pops up when something gets too hot."),
        h("div.opt", h("div.t", "Alerts on"), switchEl(a.enabled, v => { a.enabled = v; })),
        h("div.stack.mt", { style: { gap: "14px" } },
          sliderRow("CPU", 60, 105, a.cpu_temp_max, 1, "°C", v => { a.cpu_temp_max = v; }),
          sliderRow("GPU", 60, 100, a.gpu_temp_max, 1, "°C", v => { a.gpu_temp_max = v; }),
          sliderRow("Drives", 40, 80, a.drive_temp_max, 1, "°C", v => { a.drive_temp_max = v; }))),
      h("div.card", cardHead("General", "gear"), ...general, ...technical),
      h("div.card", cardHead("About", "info"), ...about, creditsList()),
      helpCard()));
  },
};
