/* Live GPU tuning (Overclocking → GPU tuning tab): sliders, live readout, before/after performance runs. */
"use strict";

const GT_GROUPS = [["Core", ["core_offset", "core_cap", "core_max", "core_min", "voltage"]], ["Memory (VRAM)", ["mem_offset", "vram_max", "mem_timing"]],
  ["Power", ["power", "tdc"]], ["Fans", ["fan_manual", "fan_speed", "zero_rpm", "fan_min", "fan_target", "fan_acoustic"]]];
const GT_STATS = [ // key, label, unit, better: 1 higher, -1 lower, 0 neutral
  ["score", "Score", "", 1], ["fps_avg", "Average FPS", "", 1], ["fps_low", "1% low FPS", "", 1], ["fps_per_watt", "FPS per watt", "", 1],
  ["clock_avg", "Core clock (avg)", " MHz", 1], ["clock_max", "Core clock (peak)", " MHz", 1], ["vram_clock_avg", "VRAM clock", " MHz", 1],
  ["power_avg", "Board power (avg)", " W", 0], ["power_max", "Board power (peak)", " W", 0], ["voltage_avg", "Core voltage", " mV", -1],
  ["temp_avg", "GPU temp (avg)", " °C", -1], ["temp_max", "GPU temp (peak)", " °C", -1], ["hotspot_max", "Hotspot (peak)", " °C", -1],
  ["fan_avg", "Fan speed (avg)", " RPM", -1], ["usage_avg", "GPU usage", " %", 0], ["fps_low01", "0.1% low FPS", "", 1],
  ["frametime_p99", "99th pct frame time", " ms", -1]];
const GT_LIVE = [["clock", "Core", "MHz"], ["vram_clock", "VRAM", "MHz"], ["board_power", "Board power", "W"], ["temp", "Temp", "°C"],
  ["hotspot", "Hotspot", "°C"], ["voltage", "Voltage", "mV"], ["fan", "Fan", "RPM"], ["fan_pct", "Fan", "%"], ["usage", "Load", "%"], ["fps", "FPS", ""]];

function gtSlider(key, c, draft, onchange) {
  const id = "gt-" + key, unit = c.unit ? " " + c.unit : "";
  const cur = () => draft[key] ?? c.value;
  const big = Math.max(c.step || 1, c.unit === "MHz" ? 10 : c.unit === "mV" ? 5 : 1);
  const clamp = (v) => Math.min(c.max, Math.max(c.min, Math.round(v / (c.step || 1)) * (c.step || 1)));
  const range = h("input", { type: "range", id, min: c.min, max: c.max, step: c.step || 1, value: cur(), "aria-label": c.label,
    "aria-valuetext": cur() + unit, oninput: (e) => set(+e.target.value) });
  const num = h("input.gt-num", { type: "number", min: c.min, max: c.max, step: c.step || 1, value: cur(), "aria-label": c.label + " value in " + (c.unit || "units"),
    onchange: (e) => set(+e.target.value) });
  const delta = h("span.gt-delta");
  const row = h("div.gt-row", { role: "group", "aria-labelledby": id + "-l" });
  const set = (v) => {
    v = clamp(v);
    if (v === c.value) delete draft[key]; else draft[key] = v;
    range.value = v; num.value = v; range.setAttribute("aria-valuetext", v + unit);
    const ref = c.default ?? c.value, d = v - ref;
    delta.textContent = c.default != null && d ? `${d > 0 ? "+" : ""}${d}${unit} vs stock` : c.default != null ? "stock" : "";
    row.classList.toggle("changed", key in draft);
    onchange();
  };
  const stockPct = c.default != null ? (c.default - c.min) / Math.max(1, c.max - c.min) * 100 : null;
  row.append(
    h("div.gt-head", h("label", { id: id + "-l", for: id }, c.label), delta, h("div.spacer"),
      h("span.small.muted", `${c.min}-${c.max}${unit}${c.default != null ? ` · stock ${c.default}${unit}` : ""}`)),
    h("div.gt-ctl",
      h("button.btn.gt-step", { "aria-label": `Lower ${c.label} by ${big}${unit}`, title: `−${big}${unit} (Shift: ×5)`, onclick: (e) => set(cur() - big * (e.shiftKey ? 5 : 1)) }, "−"),
      h("div.gt-track", range, stockPct != null ? h("i.gt-stock", { style: { left: `calc(${stockPct}% )` }, title: "stock" }) : null),
      h("button.btn.gt-step", { "aria-label": `Raise ${c.label} by ${big}${unit}`, title: `+${big}${unit} (Shift: ×5)`, onclick: (e) => set(cur() + big * (e.shiftKey ? 5 : 1)) }, "+"),
      num, h("span.gt-unit", c.unit || ""),
      c.default != null ? h("button.btn.sm.ghost", { "aria-label": `Set ${c.label} to stock`, onclick: () => set(c.default) }, "Stock") : null),
    c.help ? h("div.small.muted.gt-help", c.help) : null);
  set(cur());
  return row;
}

function gtToggle(key, c, draft, onchange) {
  const cur = () => draft[key] ?? c.value;
  return h("div.gt-row", h("div.opt", h("div", h("div.t", c.label), h("div.d", c.help || "")),
    switchEl(!!cur(), (v) => { if (v === c.value) delete draft[key]; else draft[key] = v; onchange(); })));
}

function gtSelect(key, c, draft, onchange) {
  return h("div.gt-row", h("div.gt-head", h("label", { for: "gt-" + key }, c.label)),
    h("select", { id: "gt-" + key, style: { width: "100%", maxWidth: "320px" }, onchange: (e) => { const v = +e.target.value; if (v === c.value) delete draft[key]; else draft[key] = v; onchange(); } },
      Object.entries(c.options).map(([v, l]) => h("option", { value: v, selected: +v === (draft[key] ?? c.value) }, l))),
    c.help ? h("div.small.muted.gt-help", c.help) : null);
}

const gtFmt = (v, u = "") => v == null ? "—" : (Math.abs(v) >= 100 ? Math.round(v) : Math.abs(v) < 10 ? Math.round(v * 100) / 100 : Math.round(v * 10) / 10) + u;

const GpuTune = {
  draft: {}, before: null, after: null,
  async draw(page, el) {
    this.page = page; this.el = el;
    el.replaceChildren(h("div.empty", h("div.spinner"), h("div.mt", "Connecting to the graphics driver…")));
    [this.st, this.runs, this.benches] = await Promise.all([App.api.gpu_tune_state(), App.api.gpu_runs(), App.api.gpu_benchmarks()]);
    this.render();
    if (!this.setupResult || Date.now() - this.setupAt > 10 * 60e3) this.runSetup();
    clearInterval(this.timer);
    this.timer = setInterval(() => this.tick(), 1000);
  },
  render() {
    const st = this.st, g = st.gpu || {}, caps = st.caps || {};
    const pend = st.pending || {};
    const stateTxt = st.at_factory ? ["Stock settings", "good"] : pend.state === "unverified" ? ["Tuned - not confirmed stable yet", "warn"] : ["Tuned", "good"];
    this.applyBar = h("div.row.wrap");
    const header = h("div.card", cardHead(g.name || "Graphics card", "gpu",
        (st.gpus || []).length > 1 ? h("select", { "aria-label": "Graphics card", onchange: async (e) => { this.st = await App.api.gpu_select(+e.target.value); this.draft = {}; this.render(); } },
          st.gpus.map((x, i) => h("option", { value: i, selected: i === st.selected }, `${x.name}${x.integrated ? " (integrated)" : ""}`))) : null,
        h("span.pill." + (["adlx", "nvml"].includes(st.backend) ? "good" : st.backend === "readout" ? "info" : "bad"), st.backend_label || st.backend),
        ["adlx", "nvml"].includes(st.backend) ? h("span.pill." + stateTxt[1], stateTxt[0]) : null),
      h("div.small.muted", [g.vram_mb ? `${Math.round(g.vram_mb / 1024)} GB ${g.vram_type || ""}` : "", g.driver ? `Driver ${g.driver}` : "", g.bios ? `BIOS ${g.bios}` : "", g.adlx ? `ADLX ${g.adlx}` : ""].filter(Boolean).join(" · ")),
      st.note ? banner("info", "info", st.note) : null,
      st.error ? banner("bad", "alert", st.error + (st.backend === "none" ? " - you can still use the guided steps on the Graphics tab, and run benchmarks below." : "")) : null,
      pend.state === "unverified" ? banner("warn", "alert", "<b>These settings aren't confirmed stable yet.</b> Run a benchmark or a 10-minute graphics test. If RigLab is closed before you confirm (or the PC crashes), the card goes back to stock on the next start.",
        h("button.btn.sm.primary", { onclick: async () => { await App.api.gpu_tune_confirm(); toast("Settings kept"); this.refresh(); } }, "Keep these settings")) : null,
      this.applyBar);
    this.live = h("div.gt-live");
    const groups = GT_GROUPS.map(([title, keys]) => {
      const rows = keys.filter(k => caps[k]).map(k => typeof caps[k].value === "boolean" ? gtToggle(k, caps[k], this.draft, () => this.drawApply())
        : caps[k].options ? gtSelect(k, caps[k], this.draft, () => this.drawApply()) : gtSlider(k, caps[k], this.draft, () => this.drawApply()));
      return rows.length ? h("div.card", h("h3", { style: { marginBottom: "10px" } }, title), ...rows) : null;
    }).filter(Boolean);
    const presets = Object.keys(caps).length ? h("div.card", h("h3", "Quick starts"),
      h("div.small.muted", { style: { margin: "4px 0 12px" } }, "Fill the sliders with a sensible first step. Nothing changes until you press Apply."),
      h("div.row.wrap",
        caps.power ? h("button.btn", { onclick: () => this.preset({ power: caps.power.max }) }, "Max power limit") : null,
        caps.voltage ? h("button.btn", { onclick: () => this.preset({ voltage: (caps.voltage.default ?? caps.voltage.value) - 30, power: caps.power?.max }) }, "Undervolt −30 mV + max power") : null,
        caps.core_max ? h("button.btn", { onclick: () => this.preset({ core_max: (caps.core_max.default ?? caps.core_max.value) + 50, power: caps.power?.max }) }, "Core +50 MHz + max power") : null,
        caps.mem_timing ? h("button.btn", { onclick: () => this.preset({ mem_timing: 1 }) }, "VRAM Fast Timing") : null,
        caps.core_offset ? h("button.btn", { onclick: () => this.preset({ core_offset: 60, power: caps.power?.max }) }, "Core +60 MHz + max power") : null,
        caps.mem_offset ? h("button.btn", { onclick: () => this.preset({ mem_offset: 500 }) }, "Memory +500 MHz") : null,
        caps.power && caps.power.unit === "W" ? h("button.btn", { onclick: () => this.preset({ power: Math.max(caps.power.min, Math.round((caps.power.default ?? caps.power.value) * 0.8)) }) }, "Quiet: 80% power") : null)) : null;
    this.setupBox = this.setupBox || h("div");
    this.el.replaceChildren(this.setupBox, header, h("div.card", cardHead("Live readout", "pulse"), this.live), presets,
      h("div.grid.g2", { style: { alignItems: "start" } }, ...groups), this.perfCard());
    this.drawApply(); this.tick(); this.drawSetup();
  },
  // ---------------------------------------------------------------- setup check
  async runSetup() {
    this.setupBusy = true; this.drawSetup();
    try { this.setupResult = await App.api.gpu_setup_check(true); this.setupAt = Date.now(); }
    catch (e) { this.setupResult = { steps: [{ id: "x", title: "Setup check", state: "bad", text: String(e) }] }; }
    this.setupBusy = false;
    const had = Object.keys(this.st.caps || {}).length;
    this.st = await App.api.gpu_tune_state();
    if (Object.keys(this.st.caps || {}).length !== had) this.render(); else this.drawSetup();
  },
  drawSetup() {
    if (!this.setupBox) return;
    const r = this.setupResult, busy = this.setupBusy, job = this.job;
    const noCaps = !Object.keys(this.st.caps || {}).length;
    if (!r && !busy) return this.setupBox.replaceChildren();
    const ICON = { ok: ["st.ok", "check"], warn: ["st.na", "alert"], bad: ["st.bad", "x"] };
    const open = this.setupOpen ?? (noCaps || (r && !r.ready));
    const issues = r ? r.steps.filter(s => s.state !== "ok").length : 0;
    const head = h("div.row", { style: { cursor: "pointer" }, onclick: () => { this.setupOpen = !open; this.drawSetup(); } },
      h("h3", { style: { margin: 0 } }, "Setup check"), busy ? h("div.spinner") : null,
      h("span.pill." + (busy ? "info" : r?.ready ? "good" : issues ? "warn" : "good"), busy ? "Checking card, driver and controls…" : r?.ready ? "Ready - all sliders work" : `${issues} thing${issues === 1 ? "" : "s"} to sort out`),
      h("div.spacer"), h("button.btn.sm.ghost", { onclick: (e) => { e.stopPropagation(); this.runSetup(); }, disabled: busy }, icon("refresh"), "Check again"),
      h("span.small.muted", open ? "▲" : "▼"));
    const rows = open && r ? r.steps.map(s => h("div.gt-setup-row",
      h("div." + ICON[s.state][0], icon(ICON[s.state][1])),
      h("div", { style: { minWidth: 0 } }, h("b", s.title), h("div.small.muted", { style: { lineHeight: "1.6" } }, s.text)),
      s.action && s.label && s.state !== "ok" ? h("button.btn.sm" + (s.state === "bad" ? ".primary" : ""), { disabled: job?.running,
        onclick: () => this.fix(s.action, { latest: s.latest, vendor: r.gpu?.vendor }) }, s.label) : null)) : [];
    const jobRow = job && (job.running || job.msg) ? h("div.banner." + (job.running ? "info" : job.ok ? "good" : "bad"), { style: { marginTop: "12px", marginBottom: 0 } },
      job.running ? h("div.spinner") : icon(job.ok ? "check" : "alert"), h("div.txt", h("div", job.msg),
        job.pct != null ? h("div.bar", { style: { marginTop: "8px" } }, h("i", { style: { width: job.pct + "%" } })) : null)) : null;
    this.setupBox.replaceChildren(h("div.card" + (noCaps && !busy ? ".glow" : ""), head, ...rows, jobRow,
      noCaps && r && !busy ? h("div.small", { style: { marginTop: "10px" } }, "The sliders appear as soon as the items above are sorted out.") : null));
  },
  async fix(action, data) {
    const r = await guarded("gpu.setup", () => App.api.gpu_setup_fix(action, data));
    if (r == null) return;
    if (r.error) return toast(r.error, true);
    this.job = { running: true, msg: "Starting…" }; this.drawSetup();
    const poll = async () => {
      this.job = await App.api.gpu_setup_job(); this.drawSetup();
      if (this.job.running) return setTimeout(poll, 800);
      toast(this.job.msg, !this.job.ok);
      if (this.job.ok && !["install_nvidia", "open_page", "open_afterburner"].includes(action)) this.runSetup();
    };
    poll();
  },
  preset(v) {
    for (const [k, val] of Object.entries(v)) if (val != null && this.st.caps[k]) this.draft[k] = val;
    this.render(); toast("Preset loaded - press Apply to send it to the card");
  },
  drawApply() {
    if (!this.applyBar) return;
    const n = Object.keys(this.draft).length, has = this.st.backend !== "none";
    this.applyBar.replaceChildren(
      h("span.act", h("button.btn.primary", { disabled: !n, onclick: () => this.apply() }, icon("check"), n ? `Apply ${n} change${n > 1 ? "s" : ""}` : "No changes"), infoBtn("gpu.tune")),
      h("button.btn", { disabled: !n, onclick: () => { this.draft = {}; this.render(); } }, icon("undo"), "Discard"),
      h("button.btn.ghost", { disabled: !has, onclick: async () => { if (!confirm("Reset the graphics card to stock settings?")) return; const r = await App.api.gpu_tune_reset(); this.st = r.state; this.draft = {}; toast("Stock settings restored"); this.render(); } }, icon("refresh"), "Reset to stock"), infoBtn("gpu.reset"),
      h("span.small.muted", n ? "Changes go straight to the card through its driver. Test after every step." : ""));
  },
  async apply() {
    const r = await guarded("gpu.tune", () => App.api.gpu_tune_apply(this.draft));
    if (r == null) return;
    const bad = Object.entries(r.result || {}).filter(([, v]) => v !== "ok");
    toast(bad.length ? "Some settings were refused: " + bad.map(([k, v]) => `${k} (${v})`).join(", ") : "Applied - now run a benchmark to compare", !!bad.length);
    this.st = r.state; this.draft = {}; this.render();
  },
  async refresh() { this.st = await App.api.gpu_tune_state(); this.render(); },
  async tick() {
    if (!document.body.contains(this.el)) return clearInterval(this.timer);
    const m = await App.api.gpu_metrics();
    if (this.live) this.live.replaceChildren(...GT_LIVE.filter(([k]) => m[k] != null || ["clock", "temp", "board_power", "fps"].includes(k)).map(([k, l, u]) => h("div.gt-metric", h("div.small.muted", l), h("div.stat-big", gtFmt(m[k]), h("small", " " + u)))));
    if (this.runBox && (this.running || this.lastRun)) this.drawRun(await App.api.gpu_run_status());
  },
  // ---------------------------------------------------------------- performance runs
  perfCard() {
    const label = h("select", { "aria-label": "Save this run as" }, ["Before", "After", "Run"].map(x => h("option", { selected: x === (this.st.at_factory ? "Before" : "After") }, x)));
    this.labelSel = label;
    const secs = h("select", { "aria-label": "Built-in benchmark length" }, [[30, "30 s"], [60, "60 s"], [120, "2 min"], [300, "5 min"]].map(([v, l]) => h("option", { value: v, selected: v === 60 }, l)));
    this.runBox = h("div");
    const start = async (source, exe, seconds) => {
      const r = await App.api.gpu_run_start(source, exe || null, seconds, label.value);
      if (r.error) return toast(r.error, true);
      this.running = true; this.lastRun = null; this.tick();
    };
    return h("div.card", cardHead("Performance: before & after", "bench"),
      h("div.small.muted", { style: { marginBottom: "12px", lineHeight: "1.7" } },
        "Run the same benchmark at stock (save as ", h("b", "Before"), ") and after tuning (", h("b", "After"), "). RigLab records clocks, power, temperatures, fan, voltage and FPS throughout and compares them. ",
        "Any game or third-party benchmark works on any card: RigLab measures every frame with PresentMon while it runs (average, 1% and 0.1% lows), and you can type in the benchmark's own score at the end."),
      h("div.row.wrap", { style: { gap: "10px", marginBottom: "12px" } }, h("span.small", "Save as"), label,
        h("button.btn.primary", { onclick: () => start("builtin", null, +secs.value) }, icon("play"), "RigLab 3D benchmark"), secs),
      h("div.row.wrap", { style: { gap: "8px" } },
        ...this.benches.map(b => h("button.btn", { title: b.exe, onclick: () => start("external", b.exe, 0) }, icon("play"), b.name)),
        h("button.btn.ghost", { onclick: () => start("external", null, 0) }, icon("pulse"), "Record while I run something"),
        h("button.btn.ghost", { onclick: async () => { this.benches = await App.api.gpu_bench_add(); this.render(); } }, icon("folder"), "Add benchmark / game…")),
      !this.benches.length ? h("div.small.faint", { style: { marginTop: "8px" } }, "No third-party benchmarks found (Superposition, Heaven, 3DMark, FurMark, OCCT…). Add any .exe with the button.") : null,
      this.runBox, this.compareView());
  },
  drawRun(s) {
    if (!s || (!s.running && !this.running)) return;
    if (!s.running && this.running) {
      this.running = false; this.lastRun = s;
      App.api.gpu_runs().then(r => { this.runs = r; if (s.saved) { if (s.label === "Before") this.before = s.saved; else this.after = s.saved; } this.render(); });
      toast(s.error ? "Run failed: " + s.error : s.warning ? "Run saved - " + s.warning : "Run saved as " + s.label, !!(s.error || s.warning));
      return;
    }
    const score = h("input", { type: "number", placeholder: "Score (optional)", "aria-label": "Benchmark score", style: { width: "160px" } });
    const L = s.live || {};
    this.runBox.replaceChildren(h("div.banner.info", { style: { marginTop: "14px" } }, h("div.spinner"),
      h("div.txt", h("b", `${s.label}: ${s.source} · ${s.elapsed}s${s.seconds ? " / " + s.seconds + "s" : ""}`), h("div.small", s.msg),
        h("div.small.muted", `${gtFmt(L.clock, " MHz")} · ${gtFmt(L.board_power, " W")} · ${gtFmt(L.temp, " °C")}${L.fps ? " · " + L.fps + " FPS" : ""} · ${s.n} samples`)),
      s.source !== "builtin" ? score : null,
      h("button.btn.primary", { onclick: () => App.api.gpu_run_stop(score.value || null) }, "Stop & save")));
  },
  compareView() {
    const runs = this.runs || [];
    if (!runs.length) return h("div.small.faint", { style: { marginTop: "16px" } }, "No runs yet. Start with a Before run at stock settings.");
    const byId = Object.fromEntries(runs.map(r => [r.id, r]));
    this.before ??= [...runs].reverse().find(r => r.label === "Before")?.id ?? runs[0].id;
    this.after ??= [...runs].reverse().find(r => r.label === "After")?.id ?? runs[runs.length - 1].id;
    const A = byId[this.before], B = byId[this.after];
    const pick = (which) => h("select", { "aria-label": which + " run", onchange: (e) => { this[which] = +e.target.value; this.render(); } },
      [...runs].reverse().map(r => h("option", { value: r.id, selected: r.id === this[which] }, `${r.label} · ${r.source} · ${r.time}`)));
    const rows = GT_STATS.filter(([k]) => A?.stats[k] != null || B?.stats[k] != null).map(([k, l, u, better]) => {
      const a = A?.stats[k], b = B?.stats[k];
      let d = null, cls = "";
      if (a != null && b != null && a !== 0) {
        const pct = (b - a) / Math.abs(a) * 100;
        d = `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
        cls = Math.abs(pct) < 0.5 || !better ? "" : (pct > 0) === (better > 0) ? "good" : "bad";
      }
      return h("tr", h("td", l), h("td.num", gtFmt(a, u)), h("td.num", gtFmt(b, u)), h("td.num", d ? h("span.pill." + (cls || "x"), d) : "—"));
    });
    const sets = new Set([...Object.keys(A?.settings || {}), ...Object.keys(B?.settings || {})]);
    const capL = (k) => this.st.caps?.[k]?.label || k;
    const setRows = [...sets].filter(k => (A?.settings[k]) !== (B?.settings[k])).map(k => h("tr", h("td.muted", capL(k)), h("td.num", String(A?.settings[k] ?? "—")), h("td.num", String(B?.settings[k] ?? "—")), h("td")));
    const chart = h("canvas", { style: { width: "100%", height: "150px", marginTop: "12px" }, "aria-label": "Core clock over time, before and after" });
    requestAnimationFrame(() => this.drawTrace(chart, A, B));
    return h("div", { style: { marginTop: "18px" } },
      h("div.row.wrap", { style: { gap: "10px", marginBottom: "10px" } }, h("b", "Compare"), pick("before"), h("span", "→"), pick("after"),
        h("div.spacer"),
        B ? h("button.btn.sm.ghost", { onclick: async () => { const sc = prompt("Score for this run (from the benchmark):", B.stats.score ?? ""); if (sc == null) return; this.runs = await App.api.gpu_run_edit(B.id, null, sc); this.render(); } }, "Add score to After") : null,
        B ? h("button.btn.sm.ghost", { onclick: async () => { if (!confirm("Delete this run?")) return; this.runs = await App.api.gpu_run_edit(B.id, null, null, true); this.after = null; this.render(); } }, "Delete After run") : null),
      h("table.t", h("thead", h("tr", h("th", "Metric"), h("th", { style: { textAlign: "right" } }, "Before"), h("th", { style: { textAlign: "right" } }, "After"), h("th", { style: { textAlign: "right" } }, "Change"))),
        h("tbody", ...rows, setRows.length ? h("tr", h("td", { colSpan: 4 }, h("b.small", "Settings that differ"))) : null, ...setRows)),
      chart, h("div.small.faint", "Core clock over the run: before (grey) and after (blue)."));
  },
  drawTrace(cv, A, B) {
    const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    cv.width = r.width * dpr; cv.height = r.height * dpr;
    const x = cv.getContext("2d"); x.scale(dpr, dpr);
    const series = [[A, "rgba(150,160,180,.8)"], [B, css("--accent") || "#36d6ff"]].filter(([run]) => run?.trace?.length);
    const vals = series.flatMap(([run]) => run.trace.map(p => p[1]).filter(v => v != null));
    if (!vals.length) return;
    const lo = Math.min(...vals) * 0.97, hi = Math.max(...vals) * 1.02, tmax = Math.max(...series.map(([run]) => run.trace[run.trace.length - 1][0] || 1));
    x.fillStyle = css("--muted"); x.font = "11px sans-serif";
    x.fillText(Math.round(hi) + " MHz", 4, 12); x.fillText(Math.round(lo) + " MHz", 4, r.height - 4);
    for (const [run, col] of series) {
      x.strokeStyle = col; x.lineWidth = 2; x.beginPath();
      run.trace.forEach((p, i) => { if (p[1] == null) return; const px = 60 + (p[0] / tmax) * (r.width - 70), py = r.height - 8 - (p[1] - lo) / (hi - lo) * (r.height - 20); i ? x.lineTo(px, py) : x.moveTo(px, py); });
      x.stroke();
    }
  },
};

/* ======================================================================= GPU results tab */
const GR_KPIS = [["fps_max", "Max FPS", "", 1], ["fps_avg", "Average FPS", "", 1], ["fps_low", "1% low", "", 1], ["fps_low01", "0.1% low", "", 1],
  ["score", "Score", "", 1], ["fps_per_watt", "FPS per watt", "", 1], ["clock_avg", "Avg core clock", " MHz", 1], ["power_avg", "Avg board power", " W", 0],
  ["temp_max", "Peak GPU temp", " °C", -1], ["hotspot_max", "Peak hotspot", " °C", -1]];
const GR_ALL = [...GT_STATS, ["fps_max", "Max FPS", "", 1], ["clock_p5", "Core clock (worst 5%)", " MHz", 1], ["clock_drop_pct", "Clock swing under load", " %", -1],
  ["pct_power_limited", "Time power-limited", " %", 0], ["pct_thermal_limited", "Time thermal-throttled", " %", -1], ["pct_hw_slowdown", "Time in hardware slowdown", " %", -1],
  ["hotspot_delta_max", "Core-to-hotspot gap", " °C", -1], ["vram_used_max", "VRAM used (peak)", " MB", 0], ["fan_pct_max", "Fan speed (peak)", " %", -1],
  ["spikes", "Frame-time spikes", "", -1], ["driver_resets", "Driver crashes", "", -1], ["power_limit", "Power limit", " W", 0]];
const GR_LEVEL = { bad: ["bad", "alert"], warn: ["warn", "alert"], info: ["info", "info"], good: ["good", "check"] };

function grChart(cv, series, unit, bands) {
  const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  cv.width = r.width * dpr; cv.height = r.height * dpr;
  const x = cv.getContext("2d"); x.scale(dpr, dpr);
  const W = r.width, H = r.height, L = 46, R = 8, T = 10, B = 20;
  const pts = series.flatMap(s => s.pts.filter(p => p[1] != null));
  if (!pts.length) { x.fillStyle = css("--faint"); x.font = "12px " + css("--font"); x.fillText("Not recorded on this run", L, H / 2); return; }
  let lo = Math.min(...pts.map(p => p[1])), hi = Math.max(...pts.map(p => p[1]));
  const pad = (hi - lo) * 0.1 || hi * 0.05 || 1; lo = Math.max(0, lo - pad); hi += pad;
  const tmax = Math.max(...pts.map(p => p[0]), 1);
  const X = t => L + t / tmax * (W - L - R), Y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  for (const [a, b, col] of bands || []) { x.fillStyle = col; x.fillRect(X(a), T, Math.max(2, X(b) - X(a)), H - T - B); }
  x.strokeStyle = css("--line"); x.lineWidth = 1; x.fillStyle = css("--faint"); x.font = "11px " + css("--mono");
  for (let i = 0; i <= 3; i++) { const v = lo + (hi - lo) * i / 3, y = Y(v); x.beginPath(); x.moveTo(L, y); x.lineTo(W - R, y); x.stroke(); x.fillText(Math.round(v) + unit, 2, y + 4); }
  x.fillText("0 s", L, H - 4); x.fillText(Math.round(tmax) + " s", W - R - 36, H - 4);
  for (const s of series) {
    x.strokeStyle = s.color; x.lineWidth = s.width || 2; x.setLineDash(s.dash || []); x.beginPath(); let st = false;
    for (const [t, v] of s.pts) { if (v == null) { st = false; continue; } st ? x.lineTo(X(t), Y(v)) : x.moveTo(X(t), Y(v)); st = true; }
    x.stroke(); x.setLineDash([]);
  }
}

const GpuResults = {
  async draw(page, el, runId, baseId) {
    this.el = el;
    el.replaceChildren(h("div.empty", h("div.spinner"), h("div.mt", "Analysing your runs…")));
    const r = await App.api.gpu_results(runId ?? this.runId ?? null, baseId ?? this.baseId ?? null);
    this.data = r;
    if (!r.run) {
      el.replaceChildren(h("div.card", { style: { maxWidth: "760px" } }, cardHead("No results yet", "report"),
        h("div.muted", { style: { lineHeight: "1.7" } }, "Record a benchmark run on the GPU tuning tab first - one at stock (Before) and one after tuning (After). This tab then gives you the full readout: max and average FPS, lows, clocks, temperatures, throttling, and anything you should worry about."),
        h("div.row.mt", h("button.btn.primary", { onclick: () => { page.tab = "gputune"; page.drawTabs(); page.draw(); } }, icon("sliders"), "Go to GPU tuning"))));
      return;
    }
    this.runId = r.run.id; this.baseId = r.base?.id ?? null;
    const run = r.run, s = run.stats, b = r.base?.stats || null;
    const pick = (cur, onch, allowNone) => h("select", { onchange: (e) => onch(e.target.value === "" ? null : +e.target.value) },
      allowNone ? h("option", { value: "", selected: cur == null }, "Nothing") : null,
      [...r.runs].reverse().map(x => h("option", { value: x.id, selected: x.id === cur }, `${x.label} · ${x.source} · ${x.time}`)));
    const V = r.verdict, vl = GR_LEVEL[V.level];
    const delta = (k, better) => {
      if (!b || s[k] == null || b[k] == null || !b[k]) return null;
      const pct = (s[k] - b[k]) / Math.abs(b[k]) * 100;
      if (Math.abs(pct) < 0.5) return h("span.gr-delta", "±0%");
      const good = better === 0 ? null : (pct > 0) === (better > 0);
      return h("span.gr-delta." + (good == null ? "x" : good ? "good" : "bad"), `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`);
    };
    const kpis = h("div.gr-kpis", GR_KPIS.filter(([k]) => s[k] != null).map(([k, l, u, better]) => h("div.gr-kpi" + (k === "fps_max" ? ".gr-hero" : ""),
      h("div.small.muted", l), h("div.stat-big", gtFmt(s[k]), h("small", u)), delta(k, better), b && b[k] != null ? h("div.small.faint", `was ${gtFmt(b[k], u)}`) : null)));
    const issues = h("div.stack", { style: { gap: "10px" } }, r.issues.map(i => h("div.gr-issue." + GR_LEVEL[i.level][0],
      h("div.gr-ico", icon(GR_LEVEL[i.level][1])), h("div", { style: { minWidth: 0 } }, h("b", i.title), h("div.small", { style: { marginTop: "2px", lineHeight: "1.6" } }, i.detail),
        i.fix ? h("div.small.muted", { style: { marginTop: "4px" } }, h("b", "What to do: "), i.fix) : null))));
    // charts
    const T = run.trace || [], BT = r.base?.trace || [];
    const col = (tr, i) => tr.map(p => [p[0], p[i]]);
    const thermalBands = [];
    for (let i = 0; i < T.length; i++) if (T[i][9] != null && (T[i][9] & 0x60)) thermalBands.push([T[i][0], (T[i + 1] || T[i])[0], `rgba(${css("--bad-rgb")},.14)`]);
    const powerBands = [];
    for (let i = 0; i < T.length; i++) if (T[i][9] != null && (T[i][9] & 0x84)) powerBands.push([T[i][0], (T[i + 1] || T[i])[0], `rgba(${css("--warn-rgb")},.10)`]);
    const acc = css("--accent"), grey = "rgba(140,150,170,.55)";
    const chart = (title, sub, draw) => { const cv = h("canvas", { style: { width: "100%", height: "170px", display: "block" }, "aria-label": title });
      requestAnimationFrame(() => draw(cv)); return h("div.card", h("div.row", h("b", title), h("div.spacer"), h("span.small.muted", sub)), cv); };
    const legend = r.base ? `blue = ${run.label}, grey = ${r.base.label}` : run.label;
    const charts = h("div.stack", { style: { gap: "16px" } },
      chart("Frame rate", legend, cv => grChart(cv, [{ pts: col(BT, 4), color: grey, width: 1.5 }, { pts: col(T, 4), color: acc }], "")),
      chart("Core clock", legend + (powerBands.length ? " · yellow = power-limited" : ""), cv => grChart(cv, [{ pts: col(BT, 1), color: grey, width: 1.5 }, { pts: col(T, 1), color: acc }], "", powerBands)),
      chart("Temperatures", "core (solid), hotspot (dashed)" + (thermalBands.length ? " · red = thermal throttle" : ""), cv => grChart(cv,
        [{ pts: col(T, 3), color: css("--warn") }, { pts: col(T, 5), color: css("--bad"), dash: [5, 4] }, { pts: col(BT, 3), color: grey, width: 1.5 }], "°", thermalBands)),
      chart("Board power", legend, cv => grChart(cv, [{ pts: col(BT, 2), color: grey, width: 1.5 }, { pts: col(T, 2), color: acc }], "W")));
    const rows = GR_ALL.filter(([k], i, a) => a.findIndex(x => x[0] === k) === i && (s[k] != null || b?.[k] != null)).map(([k, l, u, better]) =>
      h("tr", h("td", l), h("td.num", gtFmt(s[k], u)), b ? h("td.num", gtFmt(b[k], u)) : null, b ? h("td.num", delta(k, better) || "—") : null));
    const setKeys = [...new Set([...Object.keys(run.settings || {}), ...Object.keys(r.base?.settings || {})])];
    el.replaceChildren(
      h("div.row.wrap", { style: { gap: "10px", marginBottom: "14px" } }, h("b", "Run"), pick(this.runId, v => this.draw(page, el, v, this.baseId)),
        h("span.muted", "compared with"), pick(this.baseId, v => { this.baseId = v; this.draw(page, el, this.runId, v ?? -1); }, true), h("div.spacer"),
        h("button.btn.ghost.sm", { onclick: () => { page.tab = "gputune"; page.drawTabs(); page.draw(); } }, icon("sliders"), "New run")),
      h("div.banner." + vl[0], { style: { marginBottom: "16px" } }, icon(vl[1]), h("div.txt", h("b", V.title), " - " + V.text,
        h("div.small.muted", `${run.gpu || ""} · ${run.source} · ${run.time} · ${run.duration || "?"} s${s.app ? " · " + s.app : ""}${s.resolution ? " · " + s.resolution : ""}`))),
      kpis,
      h("div.grid", { style: { gridTemplateColumns: "minmax(0, 1.2fr) minmax(0, 1fr)", gap: "16px", alignItems: "start", marginTop: "16px" } },
        h("div.stack", { style: { gap: "16px" } }, h("div.card", cardHead("What to worry about", "alert"), issues), charts),
        h("div.card", cardHead("All numbers", "report"), h("table.t", h("thead", h("tr", h("th", "Metric"), h("th", { style: { textAlign: "right" } }, run.label),
          b ? h("th", { style: { textAlign: "right" } }, r.base.label) : null, b ? h("th", { style: { textAlign: "right" } }, "Change") : null)), h("tbody", ...rows)),
          setKeys.length ? h("div.small.muted", { style: { marginTop: "12px", lineHeight: "1.7" } }, h("b", "Settings: "),
            setKeys.map(k => `${k.replace(/_/g, " ")} ${run.settings?.[k] ?? "—"}${b ? ` (was ${r.base.settings?.[k] ?? "—"})` : ""}`).join(" · ")) : null)));
  },
};
