/* Home: the health dial in the centre, whole-PC presets underneath, then a tile for every tool. */
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
  ["dashboard", "PC Health", "heart", "Green, yellow or red for temperatures, memory, space, fans, drives and crashes."],
  ["tweaks", "Performance Tweaks", "rocket", "Make games smoother, choose which apps start with Windows, and free up space."],
  ["cooling", "Fans", "fan", "Make your PC quieter or cooler with one click."],
  ["lighting", "Lights", "light", "Pick a colour or effect for every light in your PC."],
  ["crashes", "Crashes & freezes", "alert", "Find out why your PC crashed or restarted by itself."],
  ["benchmark", "Speed test", "bench", "See how fast your PC is, and whether a change helped."],
  ["history", "Change history", "undo", "Everything RigLab has changed, with an Undo button for each."],
];

App.pages.home = {
  render(el) {
    this.el = el;
    const S = isSimple();
    const hr = new Date().getHours();
    const greet = hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
    this.status = {};
    this.side = h("div.stack", { style: { gap: "16px" } });
    el.append(h("div.card.home-center", h("div.small.muted", greet), healthDial({ link: true }), colourKey()));
    el.append(h("div.mt", h("div.row", { style: { alignItems: "baseline", gap: "12px", padding: "8px 2px 10px" } },
      h("h2.home-h2", "Presets"), h("span.small.muted", "Set up your whole PC for what you're doing. You'll see what changes before anything happens.")),
      presetCards(() => this.load()),
      h("div.small.muted", { style: { marginTop: "8px" } }, h("span.tl.good", { style: { marginRight: "6px", verticalAlign: "middle" } }),
        "A green outline shows the preset you're using now.")));
    const list = S ? HOME_SIMPLE : HOME_TOOLS;
    this.tiles = h("div.home-tiles", list.map(([id, label, ic, desc, page]) => {
      const st = h("div.home-tile-status"); this.status[id] = st;
      return h("div.home-tile", { role: "button", tabIndex: 0, onclick: () => this.open(id, page), onkeydown: (e) => { if (e.key === "Enter") this.open(id, page); } },
        h("div.icon-badge", icon(ic)), h("div", { style: { minWidth: 0 } }, h("b", label), h("div.small.muted", desc), S ? null : st));
    }));
    el.append(h("div.home-grid.mt", h("div", h("div.nav-label", { style: { padding: "12px 2px 10px" } }, S ? "What do you want to do?" : "Tools"), this.tiles), this.side));
    this.load();
  },
  open(id, page) {
    if (page === "overclock") { App.pages.overclock.tab = id; go("overclock"); return; }
    go(id);
  },
  async load() {
    if (isSimple()) return this.loadSimple();
    const A = App.api, safe = (p) => p.then(v => v, () => null);
    const [light, oc, runs, diag] = await Promise.all([safe(A.light_state()), safe(A.oc_state()), safe(A.gpu_runs()), safe(A.diagnostics())]);
    if (!document.body.contains(this.el)) return;
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
    cards.push(await this.recentChanges());
    this.side.replaceChildren(...cards);
  },
  async loadSimple() {
    const card = await this.recentChanges();
    if (document.body.contains(this.el)) this.side.replaceChildren(card);
  },
  async recentChanges() {
    let ch = [];
    try { ch = (await App.api.changes_list()).slice(0, 5); } catch { /* none */ }
    const when = (t) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
    return h("div.card", cardHead("Recent changes", "undo", h("button.btn.sm.ghost", { onclick: () => go("history") }, "See all")),
      ch.length ? h("div.stack", { style: { gap: "8px" } }, ch.map(c => h("div.small", h("span.muted", when(c.time) + "  "), c.title)))
        : h("div.small.muted", "Nothing has changed yet. Everything RigLab changes shows up here, with an Undo button."));
  },
};
