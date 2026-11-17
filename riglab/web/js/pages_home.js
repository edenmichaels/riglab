/* Home: a start screen with a live summary of the PC, a tile for every tool and recent activity. */
"use strict";

const HOME_TOOLS = [
  ["dashboard", "Dashboard", "dash", "Live temperatures, loads, clocks and fans at a glance."],
  ["overclock", "Overclocking", "bolt", "Guided CPU, RAM and GPU tuning with tests and a journal."],
  ["gputune", "GPU tuning", "sliders", "Live sliders, before/after benchmarks and results.", "overclock"],
  ["lighting", "Lighting", "light", "Every RGB LED in sync, effects, palettes and the LED map."],
  ["cooling", "Cooling", "fan", "Fan curves for case fans, pumps and fan hubs."],
  ["benchmark", "Benchmark", "bench", "CPU, memory, drive and 3D benchmarks with history."],
  ["stress", "Stress test", "flame", "Find instability before games do."],
  ["sensors", "Sensors", "pulse", "Every sensor in the PC, with min/max and logging."],
  ["hardware", "Hardware", "chip", "Full specs of every component, drive health, report."],
  ["crashes", "Crash Center", "alert", "Why the PC crashed: Event Viewer, Reliability and dump files."],
  ["tweaks", "Tweaks", "sliders", "Power plans, Windows gaming settings, startup apps."],
  ["history", "Change history", "undo", "Everything RigLab changed, with one-click undo."],
  ["health", "RigLab setup", "heart", "Make sure every RigLab feature can do its job."],
];

// Simple view: plain names and descriptions; only pages listed in the Simple menu.
const HOME_SIMPLE = [
  ["dashboard", "How my PC is doing", "heart", "Green, yellow or red for temperatures, memory, space, fans and crashes."],
  ["tweaks", "Speed-ups", "rocket", "Make games smoother, choose what opens with Windows and free up space."],
  ["cooling", "Fans", "fan", "Make your PC quieter or cooler with one click."],
  ["lighting", "Lights", "light", "Pick a colour or effect for every light in your PC."],
  ["crashes", "Crashes & freezes", "alert", "Find out why your PC crashed or restarted by itself."],
  ["benchmark", "Speed test", "bench", "See how fast your PC is, and whether a change helped."],
  ["history", "Change history", "undo", "Everything RigLab has changed, with an Undo button for each."],
];

App.pages.home = {
  async render(el) {
    this.el = el;
    if (isSimple()) return this.renderSimple(el);
    const hr = new Date().getHours();
    const greet = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
    this.gauges = h("div.home-gauges");
    this.status = {};
    this.hero = h("div.home-hero",
      h("div", { style: { minWidth: 0 } }, h("div.small.muted", greet), h("h1.home-title#home-title", "Your PC"),
        h("div.muted#home-sub", "Reading your hardware…"),
        h("div.row.wrap.mt", { style: { gap: "10px" } },
          h("button.btn.primary", { onclick: () => go("dashboard") }, icon("dash"), "Open dashboard"),
          h("button.btn", { onclick: () => this.open("gputune") }, icon("sliders"), "Tune the GPU"),
          h("button.btn.ghost", { onclick: () => go("health") }, icon("heart"), "RigLab setup"))),
      this.gauges);
    this.tiles = h("div.home-tiles", HOME_TOOLS.map(([id, label, ic, desc, page]) => {
      const st = h("div.home-tile-status"); this.status[id] = st;
      return h("div.home-tile", { role: "button", tabIndex: 0, onclick: () => this.open(id, page), onkeydown: (e) => { if (e.key === "Enter") this.open(id, page); } },
        h("div.icon-badge", icon(ic)), h("div", { style: { minWidth: 0 } }, h("b", label), h("div.small.muted", desc), st));
    }));
    this.side = h("div.stack", { style: { gap: "16px" } });
    el.append(this.hero, h("div.home-grid", h("div", h("div.nav-label", { style: { padding: "4px 2px 10px" } }, "Tools"), this.tiles), this.side));
    this.tick(App.snap);
    this.load();
  },
  renderSimple(el) {
    const hr = new Date().getHours();
    const greet = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
    this.gauges = null;
    this.status = {};
    this.ovDot = h("span"); this.ovSay = h("span", "Reading your PC…");
    this.lightsBox = h("div");
    this.hero = h("div.home-hero",
      h("div", { style: { minWidth: 0 } }, h("div.small.muted", greet), h("h1.home-title", "Your PC"),
        h("div.row", { style: { gap: "10px", fontSize: "17px", fontWeight: 600 } }, this.ovDot, this.ovSay),
        h("div.row.wrap.mt", { style: { gap: "10px" } },
          h("button.btn.primary", { onclick: () => go("dashboard") }, icon("heart"), "See how my PC is doing"),
          actionBtn("tweaks.recommended", async () => { const r = await App.api.tweaks_recommended(); toast(r.msg, !r.ok); this.load(); }, { icon: "rocket" }))),
      h("div.card", { style: { minWidth: "300px" } }, this.lightsBox));
    this.tiles = h("div.home-tiles", HOME_SIMPLE.map(([id, label, ic, desc]) =>
      h("div.home-tile", { role: "button", tabIndex: 0, onclick: () => go(id), onkeydown: (e) => { if (e.key === "Enter") go(id); } },
        h("div.icon-badge", icon(ic)), h("div", { style: { minWidth: 0 } }, h("b", label), h("div.small.muted", desc)))));
    this.side = h("div.stack", { style: { gap: "16px" } });
    el.append(this.hero, h("div.home-grid", h("div", h("div.nav-label", { style: { padding: "4px 2px 10px" } }, "What do you want to do?"), this.tiles), this.side));
    PcLights.load().then(() => this.tick(App.snap));
    this.tick(App.snap);
    this.load();
  },
  async loadSimple() {
    let ch = [];
    try { ch = (await App.api.changes_list()).slice(0, 5); } catch { /* none */ }
    if (!document.body.contains(this.el)) return;
    const when = (t) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
    this.side.replaceChildren(h("div.card", cardHead("Recent changes", "undo", h("button.btn.sm.ghost", { onclick: () => go("history") }, "See all")),
      ch.length ? h("div.stack", { style: { gap: "8px" } }, ch.map(c => h("div.small", h("span.muted", when(c.time) + "  "), c.title)))
        : h("div.small.muted", "Nothing changed yet. Everything RigLab changes shows up here, with an Undo button.")));
  },
  open(id, page) {
    if (page === "overclock") { App.pages.overclock.tab = id; go("overclock"); return; }
    go(id);
  },
  async load() {
    if (isSimple()) return this.loadSimple();
    const A = App.api, safe = (p) => p.then(v => v, () => null);
    const [inv, light, oc, runs, diag] = await Promise.all([safe(A.inventory()), safe(A.light_state()), safe(A.oc_state()), safe(A.gpu_runs()), safe(A.diagnostics())]);
    if (!document.body.contains(this.el)) return;
    // --- headline: CPU + GPU names
    const prof = oc?.profile || {};
    const cpu = prof.cpu?.name, gpu = prof.gpu?.name, ram = prof.ram;
    $("#home-title", this.el).textContent = gpu ? gpu.replace(/^(NVIDIA|AMD)\s+/, "") : "Your PC";
    $("#home-sub", this.el).textContent = [cpu, ram?.total ? `${ram.total} ${ram.type || ""} @ ${ram.running || "?"} MT/s` : null].filter(Boolean).join("  ·  ") || "";
    // --- tile status lines
    const set = (id, txt, cls = "") => { const s = this.status[id]; if (s) { s.textContent = txt; s.className = "home-tile-status " + cls; } };
    if (light) set("lighting", light.status === "running" ? `● ${light.stats?.leds || 0} LEDs · ${light.devices?.length || 0} devices · ${light.state?.effect || ""}` : `○ ${light.status}`, light.status === "running" ? "good" : "warn");
    if (oc) {
      const pr = oc.progress || {}, plans = oc.plans || {};
      const done = (k) => (plans[k]?.steps || []).filter(s => ["passed", "applied"].includes(pr[s.id]?.state)).length;
      const tot = (k) => (plans[k]?.steps || []).length;
      set("overclock", `CPU ${done("cpu")}/${tot("cpu")} · RAM ${done("ram")}/${tot("ram")} · GPU ${done("gpu")}/${tot("gpu")} steps done`);
    }
    if (runs && runs.length) { const r = runs[runs.length - 1]; set("gputune", `Last run: ${r.label} · ${r.stats.fps_avg ? r.stats.fps_avg + " FPS" : (r.stats.score ? "score " + r.stats.score : "")} · ${r.time}`); }
    else set("gputune", "No benchmark runs yet");
    if (diag) { const bad = diag.filter(i => i.ok === false).length; set("health", bad ? `${bad} thing${bad > 1 ? "s" : ""} need attention` : "● Everything working", bad ? "bad" : "good"); }
    // --- side column: latest GPU result + recent activity
    const cards = [];
    if (runs && runs.length) {
      const r = runs[runs.length - 1], s = r.stats;
      cards.push(h("div.card", cardHead("Latest GPU result", "report", h("button.btn.sm.ghost", { onclick: () => this.open("gpuresults", "overclock") }, "Full readout")),
        h("div.home-kpis", [["Avg FPS", s.fps_avg], ["Max FPS", s.fps_max], ["1% low", s.fps_low], ["Peak temp", s.temp_max, "°C"]].map(([l, v, u]) =>
          h("div", h("div.small.muted", l), h("div.stat-big", v == null ? "—" : Math.round(v), h("small", u ? " " + u : ""))))),
        h("div.small.muted", { style: { marginTop: "8px" } }, `${r.label} · ${r.source} · ${r.time}`)));
    }
    const jr = (oc?.journal || []).slice(0, 6);
    cards.push(h("div.card", cardHead("Recent activity", "clock"),
      jr.length ? h("div.stack", { style: { gap: "8px" } }, jr.map(j => h("div.small", h("span.muted", new Date(j.time * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) + "  "), j.text)))
        : h("div.small.muted", "Tuning changes and test results show up here.")));
    this.side.replaceChildren(...cards);
  },
  tick(snap) {
    if (snap && this.lightsBox && !this.gauges && document.body.contains(this.lightsBox)) {
      PcLights.load();
      const rows = PcLights.rows(snap);
      this.lightsBox.replaceChildren(...rows.map(([k, v, o]) => lightRow(k, v, o || {})));
      const o = PcLights.overall(snap);
      this.ovDot.replaceChildren(dot(o.state)); this.ovSay.textContent = o.say;
      return;
    }
    if (!snap || !this.gauges) return;
    const s = snap.summary;
    const g = (label, v, unit, max, colorFn) => h("div.home-gauge", h("div.small.muted", label),
      h("div.stat-big", { style: { color: colorFn ? colorFn(v) : "" } }, v == null ? "—" : Math.round(v), h("small", " " + unit)),
      h("div.bar", h("i", { style: { width: `${v == null ? 0 : Math.min(100, v / max * 100)}%` } })));
    this.gauges.replaceChildren(
      g("CPU temp", s.cpu_temp, "°C", 100, tempColor), g("CPU load", s.cpu_load, "%", 100),
      g("GPU temp", s.gpu_temp, "°C", 100, tempColor), g("GPU load", s.gpu_load, "%", 100),
      g("RAM", s.ram_load, "%", 100), g("GPU power", s.gpu_power, "W", 400));
  },
};
