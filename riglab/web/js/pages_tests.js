/* Benchmark and Stress test */
"use strict";

// =================================================================== Benchmark
const BENCH_TESTS = [
  ["cpu", "Processor", "cpu", "Single & multi-core, ~30 s"],
  ["memory", "Memory", "ram", "Bandwidth & random access, ~8 s"],
  ["disk", "Storage", "disk", "1 GB read/write, then deleted"],
  ["gpu", "Graphics", "gpu", "3D fractal render, 30 s"],
];

App.pages.benchmark = {
  sel: { cpu: true, memory: true, disk: true, gpu: true },
  async render(el) {
    el.append(pageHead("Benchmark", "Measure your PC, then re-run after a change - new cooler, BIOS update, a tweak - to see if it helped. Close games and heavy apps first."));
    const drives = await App.api.drives();
    this.drive = h("select", drives.map(d => h("option", { value: d }, d)));
    const cards = BENCH_TESTS.map(([id, name, ic, sub]) => {
      const c = h("div.test-card" + (this.sel[id] ? ".on" : ""), { onclick: () => { this.sel[id] = !this.sel[id]; c.classList.toggle("on"); } },
        h("div.top", h("div.icon-badge", icon(ic)), h("b", name), h("div.check")), h("div.small.muted", sub));
      return c;
    });
    this.btn = h("button.btn.primary.big", { onclick: () => this.run() }, icon("play"), "Run benchmark");
    this.bar = h("i");
    this.msg = h("div.muted.small", "Ready.");
    el.append(h("div.card", h("div.test-cards", cards),
      h("div.row.mt", this.btn, h("div.muted.small", { style: { marginLeft: "8px" } }, "Disk to test:"), this.drive, h("div.spacer")),
      h("div.mt", h("div.progress", this.bar), h("div", { style: { marginTop: "8px" } }, this.msg))));
    this.results = h("div.card.mt", cardHead("Results", "bench"), h("div.empty", "Run a benchmark to see scores. Each result is compared with your best previous run on this PC."));
    el.append(this.results);
    this.history = h("div.card.mt");
    el.append(this.history);
    this.showHistory();
  },
  async run() {
    if (!Object.values(this.sel).some(Boolean)) return toast("Pick at least one test", true);
    this.btn.disabled = true;
    const o = { ...this.sel, folder: this.drive.value };
    const cpuSide = o.cpu || o.memory || o.disk;
    if (cpuSide) {
      await App.api.bench_start(o);
      for (;;) {
        await new Promise(r => setTimeout(r, 500));
        const s = await App.api.bench_status();
        this.bar.style.width = (s.progress * (o.gpu ? 70 : 100)) + "%";
        this.msg.textContent = s.msg;
        if (s.error) { toast("Benchmark failed: " + s.error, true); this.btn.disabled = false; return; }
        if (!s.running) break;
      }
    }
    let gpu = null;
    if (o.gpu) {
      this.msg.textContent = "Graphics test running in its own window - don't touch it (Esc cancels)…";
      await App.api.gpu_window("bench", 30);
      const t0 = Date.now();
      for (;;) {
        await new Promise(r => setTimeout(r, 700));
        this.bar.style.width = (70 + Math.min(30, (Date.now() - t0) / 1000)) + "%";
        gpu = await App.api.gpu_poll();
        if (gpu) break;
      }
      if (gpu.error) toast("Graphics test: " + gpu.error, true);
    }
    const rows = await App.api.bench_finish(gpu);
    this.bar.style.width = "100%";
    this.msg.textContent = "Done - results saved.";
    this.btn.disabled = false;
    this.showResults(rows);
    this.showHistory();
  },
  showResults(rows) {
    const t = h("table.t", h("thead", h("tr", ["Test", "Score", "Your best before", "Change", "Details"].map(x => h("th", x)))),
      h("tbody", rows.map(r => h("tr",
        h("td", h("b", r.name)),
        h("td.num", { style: { fontSize: "16px", fontWeight: 700, textAlign: "left" } }, fmt.n(r.score, r.score < 100 ? 1 : 0), h("span.muted.small", " " + r.unit)),
        h("td.num.muted", { style: { textAlign: "left" } }, r.best ? fmt.n(r.best, r.best < 100 ? 1 : 0) + " " + r.unit : "first run"),
        h("td.num", { style: { textAlign: "left" } }, r.change == null ? "—" : h("span.delta." + (r.change > 2 ? "up" : r.change < -5 ? "down" : ""), (r.change > 0 ? "+" : "") + r.change + "%")),
        h("td.muted.small", Object.entries(r.details).map(([k, v]) => `${k}: ${v}`).join(" · "))))));
    this.results.replaceChildren(cardHead("Results", "bench"), t);
  },
  async showHistory() {
    const hist = (await App.api.bench_history()).slice().reverse();
    this.history.replaceChildren(cardHead("History", "clock"), hist.length ? h("table.t",
      h("thead", h("tr", h("th", "When"), h("th", "Results"))),
      h("tbody", hist.map(r => h("tr", h("td.mono.small", { style: { whiteSpace: "nowrap" } }, r.time),
        h("td.small", r.results.map(x => `${x.name}: ${fmt.n(x.score, x.score < 100 ? 1 : 0)} ${x.unit}`).join("  ·  "))))))
      : h("div.empty", "No runs yet."));
  },
};

// =================================================================== Stress test
const DURATIONS = [["1 min", 60, "Quick check"], ["10 min", 600, "Normal"], ["30 min", 1800, "Thorough"], ["1 hour", 3600, "Overclock validation"], ["∞", 1e9, "Until stopped"]];

App.pages.stress = {
  o: { cpu: true, mode: "heavy", ram: 0, gpu: false, duration: 600, safety: 95 },
  samples: [],
  render(el) {
    this.el = el;
    el.append(pageHead("Stress test", "Pushes your hardware to 100% to prove it's stable and cool enough. RigLab stops by itself if the CPU reaches the safety limit."));
    const o = this.o;
    const tog = (label, sub, key, ic) => h("div.opt", h("div.row", h("div.icon-badge", icon(ic)), h("div", h("div.t", label), h("div.d", sub))),
      switchEl(!!o[key], v => { o[key] = v; }));
    const ramRow = sliderRow("RAM test", 0, 85, o.ram, 5, "%", v => { o.ram = v; });
    const modeChips = h("div.chips", [["heavy", "Heavy (max heat)"], ["light", "Light"]].map(([k, l]) =>
      h("div.chip" + (o.mode === k ? ".on" : ""), { onclick: (e) => { o.mode = k; $$(".chip", modeChips).forEach(c => c.classList.remove("on")); e.target.classList.add("on"); } }, l)));
    const durChips = h("div.chips", DURATIONS.map(([l, v, d]) =>
      h("div.chip" + (o.duration === v ? ".on" : ""), { title: d, onclick: (e) => { o.duration = v; $$(".chip", durChips).forEach(c => c.classList.remove("on")); e.target.classList.add("on"); } }, l)));
    this.btn = h("button.btn.primary.big", { onclick: () => this.toggle() }, icon("play"), h("span", "Start test"));
    el.append(h("div.grid", { style: { gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" } },
      h("div.card", cardHead("What to stress", "flame"),
        tog("Processor", "All cores, error-checked maths", "cpu", "cpu"),
        h("div.opt", h("div.muted.small", "CPU load type"), modeChips),
        tog("Graphics card", "Opens a 3D render window", "gpu", "gpu"),
        h("div.opt", { style: { display: "block" } }, ramRow, h("div.d.small.muted", { style: { marginTop: "6px" } }, "Percent of free memory to fill and verify. 0 = off."))),
      h("div.card", cardHead("How long", "clock"), durChips,
        h("div.mt", sliderRow("Safety stop", 75, 105, o.safety, 1, "°C", v => { o.safety = v; })),
        h("div.small.muted", { style: { marginTop: "8px" } }, "Most CPUs are designed to run up to 90-100°C. The test stops instantly at this temperature."),
        h("div.mt", this.btn))));

    const st = (k, id) => h("div.kv", h("div.k", k), h("div.v", { id }, "—"));
    this.chart = h("canvas.chart", { style: { height: "300px" } });
    el.append(h("div.card.mt", cardHead("Live", "pulse",
      h("div.legend", h("span", h("i", { style: { background: css("--warn") } }), "CPU °C"), h("span", h("i", { style: { background: "#ff7ab6" } }), "GPU °C"),
        h("span", h("i", { style: { background: css("--accent") } }), "CPU clock (MHz, right)"))),
      h("div.grid.g4", { style: { gridTemplateColumns: "repeat(5,1fr)", marginBottom: "14px" } },
        st("Time", "s-time"), st("CPU temp (max)", "s-temp"), st("CPU clock", "s-clock"), st("CPU power", "s-power"), st("Errors", "s-err")),
      this.chart));
    this.verdict = h("div.mt");
    el.append(this.verdict);
    this.samples = [];
    this.poll();
  },
  async toggle() {
    const st = await App.api.stress_status(0);
    if (st.running) { await App.api.stress_stop(); return; }
    if (!this.o.cpu && !this.o.gpu && !this.o.ram) return toast("Turn on at least one test", true);
    this.samples = [];
    this.verdict.innerHTML = "";
    await App.api.stress_start(this.o);
    this.poll();
  },
  async poll() {
    clearTimeout(this.timer);
    if (!document.body.contains(this.chart)) return;
    const st = await App.api.stress_status(this.samples.length);
    this.samples.push(...st.samples);
    this.btn.className = "btn big " + (st.running ? "danger" : "primary");
    this.btn.replaceChildren(icon(st.running ? "stop" : "play"), h("span", st.running ? "Stop test" : "Start test"));
    const S = this.samples, last = S[S.length - 1] || [];
    const set = (id, v) => { const e = $("#" + id); if (e) e.innerHTML = v; };
    set("s-time", fmt.time(st.elapsed));
    set("s-temp", last[1] != null ? `${Math.round(last[1])}° <small>(${Math.round(st.max_temp)}°)</small>` : "—");
    set("s-clock", last[3] ? fmt.n(last[3] / 1000, 2) + "<small>GHz</small>" : "—");
    set("s-power", last[4] != null ? fmt.n(last[4], 0) + "<small>W</small>" : "—");
    set("s-err", `<span style="color:${st.errors ? css("--bad") : css("--good")}">${st.errors}</span>`);
    if (S.length > 1) drawChart(this.chart, [
      { data: S.map(s => [s[0], s[1]]), color: css("--warn") },
      { data: S.map(s => [s[0], s[2]]), color: "#ff7ab6" },
      { data: S.map(s => [s[0], s[3]]), color: css("--accent"), dash: true, right: true, width: 1.5 },
    ], { yLabel: "°C", rLabel: "MHz", xLabel: "seconds", yMin: 20, yMax: 105 });
    if (st.verdict && !st.running) this.showVerdict(st);
    if (st.running) this.timer = setTimeout(() => this.poll(), 1000);
  },
  showVerdict(st) {
    const [title, text] = st.verdict;
    const cls = title === "PASS" ? "pass" : title.startsWith("PASS") ? "warn" : "fail";
    const extra = [st.max_temp != null && `CPU max ${Math.round(st.max_temp)}°C / avg ${Math.round(st.avg_temp)}°C`,
      st.peak_clock && st.end_clock && `clock ${fmt.n(st.peak_clock)} → ${fmt.n(st.end_clock)} MHz`,
      st.max_power && `peak power ${Math.round(st.max_power)} W`, `ended: ${st.reason}`, `${fmt.n(st.iterations)} work units checked`].filter(Boolean);
    this.verdict.replaceChildren(h("div.verdict." + cls,
      h("div.st." + (cls === "fail" ? "bad" : "ok"), { style: { width: "46px", height: "46px" } }, icon(cls === "fail" ? "x" : "check")),
      h("div", h("div.big", title), h("div", text), h("div.small.muted", { style: { marginTop: "4px" } }, extra.join(" · ")))));
  },
  leave() { clearTimeout(this.timer); },
};
