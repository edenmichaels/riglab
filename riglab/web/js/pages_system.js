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
    if (!st.admin) parts.push(banner("bad", "alert", S ? "Some of these need RigLab to have full permission (administrator)." : "Some tweaks need RigLab running as administrator.",
      h("button.btn.sm", { onclick: () => App.api.fix("restart_admin") }, S ? "Give RigLab permission" : "Restart as admin")));

    parts.push(h("div.card.glow", cardHead(S ? "One click for gamers" : "Recommended for gaming", "rocket"),
      h("div.sub", "Switches on Game Mode and switches off background game recording. Only changes what isn't set already."),
      actionBtn("tweaks.recommended", async () => { const r = await App.api.tweaks_recommended(); toast(r.msg, !r.ok); this.redraw(); }, { cls: "primary", icon: "rocket" })));

    const plainPlan = (p) => PLAN_PLAIN[p.name.toLowerCase()] || [p.name, ""];
    const plans = h("div.plans", st.plans.map(p => h("div.plan" + (p.active ? ".on" : ""), { role: "button", tabIndex: 0,
      onclick: async () => { if (p.active) return; const ok = await guarded("power.plan", () => App.api.set_power_plan(p.guid)); if (ok != null) { toast(S ? "Now using: " + plainPlan(p)[0] : "Power plan: " + p.name); this.redraw(); } } },
      h("div.n", S ? plainPlan(p)[0] : p.name), h("div.small.muted", p.active ? (S ? "In use now" : "Active") : (S ? plainPlan(p)[1] || "Click to use" : "Click to use")))));
    parts.push(h("div.card.mt", cardHead(S ? "How hard should my PC work?" : "Power plan", "bolt", infoBtn("power.plan"),
      actionBtn("power.ultimate", async () => { await App.api.add_ultimate(); this.redraw(); }, { cls: "sm", label: S ? "+ Maximum speed" : "+ Ultimate Performance" })),
      h("div.sub", S ? "Pick one. You can change it back any time." : "High performance / Ultimate keep clocks up for lower latency but use more power. Balanced is fine for most modern CPUs."),
      st.plans.length ? plans : h("div.muted.small", "Windows only.")));

    const cats = {};
    for (const t of st.tweaks) (cats[t.cat] ||= []).push(t);
    const tcard = h("div.card.mt", cardHead(S ? "Windows settings" : "Windows & gaming", "sliders"));
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
    if (S && st.tweaks.length > shownCount) tcard.append(h("div.small.muted", { style: { paddingTop: "10px" } }, "More settings are in Advanced view. Use the Simple / Advanced switch at the top of the window."));
    parts.push(tcard);

    if (!S) {
      const g = st.gpu;
      const gcard = h("div.card.mt", cardHead("Graphics card power limit", "gpu", infoBtn("gpu.power_limit")));
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
const OV_STATS = [["fps", "FPS"], ["low1", "1% lows"], ["frametime", "Frame time"], ["cpu_temp", "CPU temp"], ["gpu_temp", "GPU temp"],
  ["cpu_load", "CPU usage"], ["gpu_load", "GPU usage"], ["ram", "RAM"], ["cpu_clock", "CPU clock"], ["gpu_clock", "GPU clock"], ["graph", "Frame-time graph"]];
const OV_PRESETS = [["minimal", "Minimal", "FPS only"], ["standard", "Standard", "FPS + temperatures"], ["full", "Full", "Everything"]];

/* Overlay settings. Every change applies straight away (no Save needed) and is saved. */
function overlayCard(initial) {
  let ov = Object.assign({}, initial);
  const box = h("div.card#overlay-settings");
  const set = async (values) => {
    try { const r = await App.api.overlay_set(values); ov = r.overlay; if (values.hotkey !== undefined && !r.hotkey_ok) toast("That key combination is already used by another app. Try a different one.", true); }
    catch (e) { toast("Couldn't change the overlay: " + e, true); }
    draw();
  };
  const seg = (items, cur, onPick) => h("div.seg", items.map(([k, l]) => h("button" + (cur === k ? ".on" : ""), { "aria-pressed": cur === k, onclick: () => onPick(k) }, l)));
  const draw = () => {
    const S = isSimple(), stats = ov.stats || ["fps"];
    const hk = h("input", { type: "text", readOnly: true, value: ov.hotkey || "", placeholder: "Click, then press keys", style: { width: "170px" }, "aria-label": "Show/hide hotkey",
      onkeydown: (e) => {
        e.preventDefault();
        if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
        if (e.key === "Escape" || e.key === "Backspace") { set({ hotkey: "" }); return; }
        const k = e.key.length === 1 ? e.key.toUpperCase() : e.key;
        const combo = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", k].filter(Boolean).join("+");
        if (!e.ctrlKey && !e.altKey && !/^F\d+$/.test(k)) { toast("Use Ctrl, Alt or Shift with a key (or an F key), so normal typing in games isn't caught.", true); return; }
        set({ hotkey: combo });
      } });
    const more = [
      h("div.small.muted", { style: { margin: "6px 0" } }, "What to show"),
      h("div.chips", OV_STATS.map(([k, l]) => h("div.chip" + (stats.includes(k) ? ".on" : ""), { role: "checkbox", "aria-checked": stats.includes(k), tabIndex: 0,
        onclick: () => { const st = stats.includes(k) ? stats.filter(x => x !== k) : [...stats, k]; if (!st.length) return toast("Keep at least one thing on the overlay", true); set({ stats: st }); } }, l))),
      h("div.opt", h("div.t", "Layout"), seg([["horizontal", "Side by side"], ["vertical", "Stacked"]], ov.layout, (v) => set({ layout: v }))),
      h("div.opt", h("div", h("div.t", "Text colour"), h("div.d", "Follow theme uses your RigLab theme's colours.")),
        h("div.row", { style: { gap: "8px" } }, seg([["theme", "Follow theme"], ["white", "White"], ["custom", "Custom"]], /^#/.test(ov.text_color || "") ? "custom" : ov.text_color,
          (v) => set({ text_color: v === "custom" ? "#36d6ff" : v })),
          /^#/.test(ov.text_color || "") ? h("input", { type: "color", value: ov.text_color, "aria-label": "Custom text colour", onchange: (e) => set({ text_color: e.target.value }) }) : null)),
      h("div.opt", h("div", h("div.t", "Colour numbers green / yellow / red"), h("div.d", "FPS and temperatures change colour when they're good, worth checking, or a problem.")),
        switchEl(ov.fps_color !== "plain", (v) => set({ fps_color: v ? "auto" : "plain" }))),
      h("div.opt", h("div", h("div.t", "Snap to the nearest corner"), h("div.d", "When you let go after dragging, it jumps neatly into the closest corner.")),
        switchEl(!!ov.snap, (v) => set({ snap: v }))),
      h("div.opt", h("div", h("div.t", "Show / hide key"), h("div.d", ov.hotkey ? `Press ${ov.hotkey} in any game to hide or show the overlay. Backspace clears it.` : "Optional. Pick a key combination to hide or show the overlay in any game.")),
        h("div.row", { style: { gap: "6px" } }, hk, ov.hotkey ? h("button.btn.sm", { onclick: () => set({ hotkey: "" }) }, "Clear") : null)),
      h("div.opt", h("div.t", "Move to a corner now"),
        h("select", { "aria-label": "Move the overlay to a corner", onchange: async (e) => { if (!e.target.value) return; await App.api.overlay_corner(e.target.value); ov.x = ov.y = null; ov.corner = e.target.value; toast("Moved to the " + e.target.value.replace("-", " ") + " corner"); draw(); } },
          h("option", { value: "" }, "Choose a corner…"), [["top-left", "Top left"], ["top-right", "Top right"], ["bottom-left", "Bottom left"], ["bottom-right", "Bottom right"]].map(([k, l]) => h("option", { value: k }, l)))),
    ];
    box.replaceChildren(cardHead("In-game overlay", "overlay"),
      h("div.sub", "A small box on top of your games that shows FPS and other readings. It works in borderless and windowed games (not exclusive fullscreen)."),
      h("div.opt", h("div.t", "Show overlay"), switchEl(!!ov.enabled, (v) => set({ enabled: v }))),
      h("div.small.muted", { style: { margin: "8px 0 6px" } }, "Preset"),
      h("div.row.wrap", { style: { gap: "8px" } }, OV_PRESETS.map(([k, l, d]) => h("button.btn.sm" + (ov.preset === k ? ".primary" : ""), { "aria-pressed": ov.preset === k, title: d, onclick: () => set({ preset: k }) }, l, h("span.small", { style: { opacity: .75, marginLeft: "6px" } }, d))),
        ov.preset === "custom" ? h("span.pill", "Your own mix") : null),
      h("div.opt", h("div.t", "Size"), seg([["s", "Small"], ["m", "Medium"], ["l", "Large"], ["xl", "Extra large"]], ov.size, (v) => set({ size: v }))),
      h("div", { style: { padding: "6px 0" } }, sliderRow("Background", 0, 100, Math.round((ov.opacity ?? 0.85) * 100), 5, "%", debounce((v) => set({ opacity: v / 100 }), 250))),
      h("div.opt", h("div", h("div.t", "Lock in place"), h("div.d", ov.locked !== false ? "Locked: clicks go straight through to your game." : "Unlocked: drag the overlay anywhere. Its – button shrinks it to a dot.")),
        switchEl(ov.locked !== false, async (v) => { await App.api.overlay_lock(v); ov.locked = v; if (!v) ov.enabled = true; toast(v ? "Overlay locked" : "Overlay unlocked - drag it where you want it"); draw(); })),
      h("div.opt", h("div", h("div.t", "Shrink to a dot"), h("div.d", "Hides the readings and leaves a small dot. Click the dot to bring them back.")),
        switchEl(!!ov.minimised, async (v) => { await App.api.overlay_minimise(v); ov.minimised = v; draw(); })),
      S ? details("More overlay options (what to show, layout, colours, hotkey)", ...more) : h("div", ...more),
      h("div.mt", colourKey({ label: "What do the overlay colours mean?" })),
      App.demo ? h("div.small.muted.mt", "Preview mode: ", h("a", { href: "overlay.html", target: "_blank" }, "open the overlay preview"), " to see and drag it.") : null);
  };
  draw();
  return box;
}

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

function appearanceCard(c) {
  const ui = c.ui || (c.ui = { theme: "dark", accent: "cyan", start_page: "home" });
  const box = h("div.card#appearance");
  const draw = () => {
    const cur = Theme.cur;
    box.replaceChildren(cardHead("Themes", "sliders"),
      h("div.sub", "Pick a look. It changes straight away and is saved. Green, yellow and red stay easy to read in every theme."),
      h("div.theme-grid", THEMES.map(([id, name]) => {
        const pvTheme = id === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : id;
        return h("button.theme-card" + (cur.theme === id ? ".on" : ""), { "aria-pressed": cur.theme === id, title: name,
          onclick: () => { ui.theme = id; ui.accent = "theme"; Theme.set({ theme: id, accent: "theme" }); draw(); } },
          h("div.theme-pv", { "data-theme": pvTheme }, h("div.side"), h("div.main", h("div.ln"), h("div.ln.m"),
            h("div.dots", h("i", { style: { background: "var(--good)" } }), h("i", { style: { background: "var(--warn)" } }), h("i", { style: { background: "var(--bad)" } }),
              h("i", { style: { background: "var(--accent)", marginLeft: "auto" } })))),
          h("div.theme-name", { "data-theme": pvTheme }, name, cur.theme === id ? " ✓" : ""));
      })),
      h("div.small.muted", { style: { margin: "16px 0 8px" } }, "Highlight colour"),
      h("div.row.wrap", { style: { gap: "12px" } }, Object.entries(THEME_ACCENTS).map(([k, l]) => {
        const pal = { theme: ["var(--accent)", "var(--accent-2)"], cyan: ["#36d6ff", "#8f6bff"], violet: ["#a37bff", "#ff5fb8"], emerald: ["#2fe0a0", "#2fb5ff"], amber: ["#ffb636", "#ff6b3d"], crimson: ["#ff4d6d", "#ff9a3d"], ocean: ["#4d8dff", "#36d6ff"], mono: ["#c7cedb", "#7d8799"] }[k];
        const on = (cur.accent || "theme") === k;
        return h("div", { style: { textAlign: "center" } }, h("div.theme-swatch" + (on ? ".on" : ""), { role: "button", tabIndex: 0, title: l, "aria-label": l + " highlight colour", "aria-pressed": on,
          style: { background: k === "theme" ? `linear-gradient(135deg, ${pal[0]} 50%, ${pal[1]} 50%)` : `linear-gradient(135deg, ${pal[0]}, ${pal[1]})` },
          onclick: () => { ui.accent = k; Theme.set({ accent: k }); draw(); } }), h("div.small.muted", { style: { marginTop: "4px" } }, k === "theme" ? "Theme's own" : l));
      })),
      h("div.opt", { style: { marginTop: "14px" } }, h("div", h("div.t", "Text size"), h("div.d", "Makes all text, buttons and cards bigger or smaller. Also on the Aa button at the top.")),
        h("div.seg", TEXT_SIZES.map(([v, l]) => h("button" + (+cur.text_scale === v ? ".on" : ""), { "aria-pressed": +cur.text_scale === v,
          onclick: () => { ui.text_scale = v; Theme.set({ text_scale: v }); draw(); } }, l)))),
      h("div.opt", h("div", h("div.t", "Open RigLab on"), h("div.d", "The page you see when the app starts.")),
        h("select", { onchange: e => { ui.start_page = e.target.value; App.api.ui_set({ start_page: e.target.value }); } },
          [["home", "Home"], ["dashboard", isSimple() ? "PC Health" : "Dashboard"], ["last", "Last page I used"]].map(([v, l]) => h("option", { value: v, selected: (ui.start_page || "home") === v }, l)))));
  };
  draw();
  return box;
}

function helpCard() {
  const box = h("div.card");
  const draw = async () => {
    let w = { on: false };
    try { w = await App.api.weekly_state(); } catch { /* preview */ }
    box.replaceChildren(cardHead("Help and regular checks", "info"),
      h("div.opt", h("div", h("div.t", "Walkthrough"), h("div.d", "A short tour of the main screen.")),
        h("button.btn.sm", { onclick: () => Tour.start() }, icon("play"), "Replay the walkthrough")),
      h("div.opt", h("div", h("div.t", "Tips"), h("div.d", "The tips at the top of each page, including ones you chose not to show again.")),
        h("button.btn.sm", { onclick: async () => { await Tips.reset(); toast("Tips will show again on each page"); } }, icon("refresh"), "Show tips again")),
      switchRow("weekly.set", w.on, async (v) => { const r = await App.api.weekly_set(v); toast(r.msg, !r.ok); return !!r.ok; },
        { always: true, desc: "Runs a quick check every Sunday at 7 pm and shows your score in a notification. Off unless you turn it on." }));
  };
  draw();
  return box;
}

function creditsList() {
  return details("Theme credits and licences", h("div.small", { style: { lineHeight: 1.7 } },
    THEMES.filter(([, , c]) => /licen/i.test(c)).map(([, n, c]) => h("div", h("b", n), " - ", c)),
    h("div.muted", "All theme palettes are used under the MIT licence, which allows use in commercial software with credit.")));
}

function viewCard() {
  const box = h("div.card.glow");
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
    const a = c.alerts, ov = c.overlay, S = isSimple();
    const save = async () => { await App.api.save_settings(c); try { App.info = await App.api.info(); } catch { /* keep old */ } toast("Settings saved"); };
    el.append(pageHead("Settings", null, h("button.btn.primary", { onclick: save }, icon("check"), "Save")));
    el.append(viewCard());
    el.append(h("div.mt", appearanceCard(c)));
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
        h("div.card", cardHead("Too-hot warnings", "thermo"), h("div.sub", "A Windows pop-up warns you when something gets too hot. These limits also decide when lights turn yellow and red."),
          h("div.opt", h("div.t", "Warn me"), switchEl(a.enabled, v => { a.enabled = v; })),
          details("Change the limits",
            h("div.stack", { style: { gap: "14px" } },
              sliderRow("Processor", 60, 105, a.cpu_temp_max, 1, "°C", v => { a.cpu_temp_max = v; }),
              sliderRow("Graphics card", 60, 100, a.gpu_temp_max, 1, "°C", v => { a.gpu_temp_max = v; }),
              sliderRow("Drives", 40, 80, a.drive_temp_max, 1, "°C", v => { a.drive_temp_max = v; })))),
        overlayCard(ov),
        h("div.card", cardHead("General", "gear"), ...general, details("Technical settings", ...technical)),
        h("div.card", cardHead("About", "info"), ...about, creditsList()),
        helpCard()));
      return;
    }
    el.append(h("div.grid.g2.mt",
      h("div.card", cardHead("Temperature alerts", "thermo"), h("div.sub", "A Windows notification pops up when something gets too hot."),
        h("div.opt", h("div.t", "Alerts on"), switchEl(a.enabled, v => { a.enabled = v; })),
        h("div.stack.mt", { style: { gap: "14px" } },
          sliderRow("CPU", 60, 105, a.cpu_temp_max, 1, "°C", v => { a.cpu_temp_max = v; }),
          sliderRow("GPU", 60, 100, a.gpu_temp_max, 1, "°C", v => { a.gpu_temp_max = v; }),
          sliderRow("Drives", 40, 80, a.drive_temp_max, 1, "°C", v => { a.drive_temp_max = v; }))),
      overlayCard(ov),
      h("div.card", cardHead("General", "gear"), ...general, ...technical),
      h("div.card", cardHead("About", "info"), ...about, creditsList()),
      helpCard()));
  },
};
