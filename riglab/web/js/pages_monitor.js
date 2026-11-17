/* Dashboard, Sensors, Hardware */
"use strict";

// =================================================================== Dashboard
/* Readings for the traffic lights, shared by Home and the Dashboard. */
const PcLights = {
  extra: null, at: 0,
  async load() {
    if (Date.now() - this.at > 30000) { this.at = Date.now(); try { this.extra = await App.api.pc_status(); } catch { this.extra = {}; } }
    return this.extra || {};
  },
  fans(snap) {
    const f = snap.sensors.filter(x => x.kind === "Fan" && x.value != null && !/^Gpu/.test(x.type));   // graphics fans stop on purpose when idle
    if (!f.length) return "none";
    return f.some(x => x.value > 0) ? "good" : "warn";
  },
  rows(snap) {
    const s = snap.summary, x = this.extra || {};
    const fanSt = this.fans(snap);
    return [
      ["cpu_temp", s.cpu_temp], ["gpu_temp", s.gpu_temp], ["ram_load", s.ram_load],
      ["disk_free", x.disk_free_pct, { say: x.disk_free != null ? `${lightSay("disk_free", light("disk_free", x.disk_free_pct))} (${fmt.bytes(x.disk_free)} free)` : null }],
      ["fans", null, { state: fanSt }],
      ["crashes", x.crashes, x.crashes == null ? { say: "Not checked yet", right: h("button.btn.sm.ghost", { onclick: () => go("crashes") }, "Check now") } : {}],
    ];
  },
  states(snap) { return this.rows(snap).map(([k, v, o]) => (o && o.state) || light(k, v)); },
  overall(snap) {
    const w = worstLight(this.states(snap));
    return { state: w, say: { good: "Everything looks good", warn: "Something is worth a look", bad: "Something needs fixing", none: "Reading your PC…" }[w] };
  },
};

/* The report card under the dial: one line per check, worst first, with Fix it / Open buttons. Live while a check runs. */
function healthReport() {
  const box = h("div");
  let mounted = false;
  const draw = () => {
    if (mounted && !box.isConnected) { Health.subs.delete(draw); return; }
    if (box.isConnected) mounted = true;
    const job = Health.job || {}, r = Health.last;
    const live = Health.running && job.items;
    const items = live ? job.items : r && r.items;
    const parts = [];
    if (job.kind === "repair" && job.running) parts.push(banner("info", "info", `<b>Repairing: ${job.step}</b> - ${job.eta_text || "working"}. You can keep using your PC.`,
      h("button.btn.sm", { onclick: () => Health.cancel() }, "Cancel")));
    if (!items || !items.length) {
      parts.push(Health.running ? h("div.empty", h("div.spinner"), h("div.mt", "Starting the check…"))
        : h("div.empty.small", "No report yet. Run a quick check to get one."));
      box.replaceChildren(...parts);
      return;
    }
    const order = { bad: 0, warn: 1, good: 2, none: 3 };
    const sorted = [...items].sort((a, b) => order[a.state] - order[b.state]);
    for (const i of sorted) {
      const btns = [];
      if (i.action) btns.push(actionBtn("fix." + i.action.id, () => Health.fix(i.action.id), { cls: "sm" + (i.state === "bad" ? ".primary" : ""), label: i.action.label, always: true }));
      else if (i.page && i.fix) btns.push(h("button.btn.sm" + (i.state === "bad" ? ".primary" : ""), { onclick: () => go(i.page) }, i.fix));
      parts.push(h("div.report-item", dot(i.state, (XD.legend || {})[i.state]),
        h("div", { style: { minWidth: 0 } }, h("div.tl-name", i.title), h("div.small.muted", i.say),
          i.lines && i.state !== "good" ? h("ul.pp-list.small.muted", i.lines.map(l => h("li", l))) : null,
          i.details ? details(isSimple() ? "Show details" : "Technical details", h("pre.log", String(i.details))) : null),
        h("div.row", { style: { gap: "6px" } }, btns)));
    }
    if (live) parts.push(h("div.small.muted", { style: { paddingTop: "10px" } }, "More results appear as each check finishes."));
    else if (r) parts.push(h("div.row.wrap", { style: { paddingTop: "12px", gap: "10px" } },
      h("span.small.muted", `${r.kind === "full" ? "Full check" : "Quick check"} · ${new Date(r.time * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}`),
      h("div.spacer"),
      actionBtn("health.save", async () => { const x = await App.api.health_save_text(); toast(x.msg, !x.ok); }, { cls: "sm", icon: "download" }),
      actionBtn("health.print", () => printReport(r), { cls: "sm", icon: "report" })));
    box.replaceChildren(...parts);
  };
  Health.subs.add(draw);
  draw();
  return box;
}

/* PDF: the print window (choose "Microsoft Print to PDF"). Built from the same report as the text file. */
function printReport(r) {
  const esc = (t) => String(t ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  const words = { good: "Good", warn: "Worth checking", bad: "Needs fixing", none: "Not checked / skipped" };
  const colours = { good: "#1a8f4c", warn: "#b07800", bad: "#c62a3a", none: "#777" };
  const order = { bad: 0, warn: 1, good: 2, none: 3 };
  const rows = [...(r.items || [])].sort((a, b) => order[a.state] - order[b.state]).map(i =>
    `<tr><td style="color:${colours[i.state]};font-weight:700;white-space:nowrap">● ${words[i.state]}</td><td><b>${esc(i.title)}</b><br>${esc(i.say)}</td></tr>`).join("");
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>RigLab health report</title><style>
    body{font:14px/1.5 Segoe UI,Arial,sans-serif;color:#111;margin:32px} h1{margin:0 0 4px} table{border-collapse:collapse;width:100%;margin-top:18px}
    td{border-top:1px solid #ddd;padding:8px;vertical-align:top} .score{font-size:40px;font-weight:800;color:${colours[r.state] || "#111"}}</style></head><body>
    <h1>PC health report</h1><div>${r.kind === "full" ? "Full check" : "Quick check"} · ${esc(new Date(r.time * 1000).toLocaleString())} · RigLab ${esc(App.info.version)}</div>
    <p><span class="score">${r.score ?? "-"}</span> / 100<br><b>${esc(r.summary)}</b></p><table>${rows}</table>
    <p style="color:#666;font-size:12px;margin-top:20px">Good = nothing to do. Worth checking = not urgent. Needs fixing = take a look soon. Skipped items don't change the score.</p></body></html>`;
  const f = h("iframe", { style: { position: "fixed", width: "0", height: "0", border: "0", right: "0", bottom: "0" } });
  document.body.append(f);
  f.contentDocument.open(); f.contentDocument.write(html); f.contentDocument.close();
  setTimeout(() => { try { f.contentWindow.focus(); f.contentWindow.print(); } catch (e) { toast("Couldn't open the print window: " + e, true); } setTimeout(() => f.remove(), 60000); }, 300);
  toast("In the print window, choose “Microsoft Print to PDF” to save a PDF.");
}

/* Score over time (each check is one point). */
function healthChart() {
  const c = h("canvas.chart", { style: { height: "180px" } });
  const note = h("div.small.muted");
  const box = h("div", c, note);
  let mounted = false;
  const draw = () => {
    if (mounted && !box.isConnected) { Health.subs.delete(draw); return; }
    if (box.isConnected) mounted = true;
    const hist = Health.history || [];
    if (hist.length < 2) { note.textContent = hist.length ? "Run another check to start the chart." : "Your score is added here each time you run a check."; c.style.display = "none"; return; }
    c.style.display = "";
    const now = Date.now() / 1000;
    const data = hist.map(p => [-(now - p.time) / 86400, p.score]);
    note.textContent = `${hist.length} checks. Days ago along the bottom, score up the side. The dotted lines are where the colours change (80 and 50).`;
    requestAnimationFrame(() => {
      const xMin = Math.min(-1, data[0][0]);
      const g = drawChart(c, [{ data, color: css("--accent") }, { data: [[xMin, 80], [0, 80]], color: css("--good"), dash: true, width: 1 },
        { data: [[xMin, 50], [0, 50]], color: css("--warn"), dash: true, width: 1 }], { yMin: 0, yMax: 100, xMin, xMax: 0, xLabel: "days ago", yLabel: "score" });
      const [ctx] = fitCanvas(c);
      for (const [x, y] of data) { ctx.beginPath(); ctx.arc(g.X(x), g.Y(y), 4, 0, Math.PI * 2); ctx.fillStyle = css(y >= 80 ? "--good" : y >= 50 ? "--warn" : "--bad"); ctx.fill(); }
    });
  };
  Health.subs.add(draw);
  draw();
  return box;
}

function healthTop() {
  return h("div", h("div.grid", { style: { gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", alignItems: "start" } },
    h("div.stack", { style: { gap: "16px" } },
      h("div.card", { style: { paddingTop: "24px" } }, healthDial({ both: true }), h("div.mt", colourKey())),
      h("div.card", cardHead("Score over time", "pulse"), healthChart())),
    h("div.card", cardHead(isSimple() ? "Report card" : "Health report", "report",
      infoTip("The quick check looks at temperatures, memory, space, fans, drives, crashes, virus protection, devices, and your keyboard, mouse, screens, sound, network and USB. The full check adds a virus scan, a check of Windows' own files, driver ages and Windows updates. Grey items were skipped and don't change the score.", "What's checked?")),
      healthReport())));
}

App.pages.dashboard = {
  render(el) {
    this.el = el;
    if (isSimple()) {
      el.append(pageHead("PC Health", "Your PC's health score, what was checked, and live readings. Green is good, yellow is worth checking, red needs fixing."));
      this.alerts = h("div");
      el.append(this.alerts);
      this.showAlerts();
      el.append(healthTop());
      this.lightsBox = h("div");
      this.overall = h("div.row", { style: { gap: "12px" } });
      el.append(h("div.card.mt", cardHead("Right now", "pulse", this.overall), h("div.small.muted", "These readings update every second."), this.lightsBox,
        h("div.mt", colourKey())));
      el.append(h("div.card.mt", cardHead("Things you can do", "rocket"), h("div.row.wrap", { style: { gap: "10px" } },
        actionBtn("tweaks.recommended", async () => { const r = await App.api.tweaks_recommended(); toast(r.msg, !r.ok); }, { cls: "primary", icon: "rocket" }),
        h("button.btn", { onclick: () => go("tweaks") }, icon("trash"), "Free up space"),
        h("button.btn", { onclick: () => go("cooling") }, icon("fan"), "Change how my fans behave"),
        h("button.btn", { onclick: () => go("crashes") }, icon("alert"), "Find out why my PC crashed"),
        actionBtn("light.off", async () => { const r = await App.api.rgb_off(); toast(r === "ok" ? "Lights off" : r, r !== "ok"); }, { icon: "power" }),
        actionBtn("report.export", async () => { const p = await App.api.export_report(); toast("Report saved: " + p); }, { icon: "download" }))));
      const more = h("div");
      el.append(details("Show the numbers (temperatures, speeds, power)", more));
      this.renderFull(more, false);
      PcLights.load().then(() => this.tick(App.snap));
      return;
    }
    el.append(pageHead("Dashboard", "Everything important at a glance. Click a card to dig deeper."));
    this.alerts = h("div");
    el.append(this.alerts);
    this.showAlerts();
    el.append(details("PC health score and report", healthTop()));
    this.renderFull(el, true);
  },
  renderFull(el, actions) {

    const cpuName = (App.snap.sensors.find(x => x.type === "Cpu") || {}).hw || "Processor";
    const gpuName = (App.snap.sensors.find(x => x.type.startsWith("Gpu")) || {}).hw || "Graphics card";
    const mk = (key, name, ic, clockLabel) => {
      const g = gauge(null, 100, css("--good"), "°C");
      const kv = (k, id) => h("div.kv", h("div.k", k), h("div.v", { id }, "—"));
      const card = h("div.card", { style: { cursor: "pointer" }, onclick: () => go("sensors") },
        cardHead(key === "cpu" ? "Processor" : "Graphics", ic),
        h("div.hero", g, h("div",
          h("div.hero-name", name),
          h("div.kv3", kv("Usage", key + "-load"), kv(clockLabel, key + "-x"), kv("Power", key + "-pw")),
          h("canvas.spark#" + key + "-spark"))));
      card.gauge = g;
      return card;
    };
    this.cpu = mk("cpu", cpuName, "cpu", "Clock");
    this.gpu = mk("gpu", gpuName, "gpu", "Hot spot");
    el.append(h("div.grid", { style: { gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 440px), 1fr))" } }, this.cpu, this.gpu));

    const tile = (title, ic, id, extra) => h("div.card", cardHead(title, ic), h("div.stat-big", { id }, "—"),
      extra, h("canvas.spark#" + id + "-spark", { style: { marginTop: "8px" } }));
    el.append(h("div.grid.g3.mt",
      tile("Memory", "ram", "d-ram", h("div", h("div.bar", { style: { margin: "8px 0 4px" } }, h("i#d-ram-bar")), h("div.small.muted#d-ram-sub", ""))),
      tile("Storage activity", "disk", "d-disk", h("div.small.muted#d-disk-sub", "")),
      tile("Network", "net", "d-net", h("div.small.muted#d-net-sub", ""))));

    this.fans = h("div.fanmini");
    const fanCard = h("div.card", cardHead("Fans & pumps", "fan", h("button.btn.sm.ghost", { onclick: () => go("cooling") }, "Open cooling →")), this.fans);
    el.append(!actions ? h("div.mt", fanCard) : h("div.grid.g2.mt", fanCard,
      h("div.card", cardHead("Quick actions", "rocket"), h("div.quick",
        h("span.act", h("button.btn", { onclick: () => go("benchmark") }, icon("bench"), "Run benchmark"), infoBtn("bench.start")),
        h("span.act", h("button.btn", { onclick: () => go("stress") }, icon("flame"), "Stability test"), infoBtn("stress.start")),
        h("button.btn", { onclick: () => go("lighting") }, icon("light"), "Lighting"),
        actionBtn("light.off", async () => { const r = await App.api.rgb_off(); toast(r === "ok" ? "Lights off" : r, r !== "ok"); }, { icon: "power", label: "All lights off" }),
        h("button.btn", { onclick: () => go("health") }, icon("heart"), "RigLab setup"),
        actionBtn("report.export", async () => { const p = await App.api.export_report(); toast("Report saved: " + p); }, { icon: "download", label: "System report" })))));
  },
  async showAlerts() {
    const items = await refreshHealth();
    this.alerts.innerHTML = "";
    for (const n of (await App.api.startup_notes()) || []) {
      if (isSimple()) {     // tuning notices are Advanced detail; crashes are worth a plain heads-up
        if (n.kind === "bad") this.alerts.append(banner("bad", "alert", "<b>Your PC crashed or restarted by itself recently.</b> RigLab can show you why.",
          h("button.btn.sm", { onclick: () => go("crashes") }, "Find out why")));
        continue;
      }
      this.alerts.append(banner(n.kind === "bad" ? "bad" : "info", n.kind === "bad" ? "alert" : "info", n.text,
        h("button.btn.sm", { onclick: () => go(n.page || (n.kind === "bad" ? "crashes" : "overclock")) }, n.page === "crashes" || n.kind === "bad" ? "Crash Center" : "Overclocking")));
    }
    const bad = items.filter(i => i.ok === false);
    if (bad.length) {
      this.alerts.append(banner("bad", "alert", isSimple()
        ? `<b>RigLab is missing something it needs.</b> Some readings or controls won't show until it's sorted.`
        : `<b>${bad.length} thing${bad.length > 1 ? "s" : ""} need${bad.length > 1 ? "" : "s"} attention:</b> ` + bad.map(b => b.title).join(" · ") + ". Some sensors or controls will be missing until fixed.",
        h("button.btn.sm", { onclick: () => go("health") }, "Fix it")));
    }
  },
  async tick(snap) {
    const s = snap.summary;
    if (this.lightsBox && document.body.contains(this.lightsBox)) {
      PcLights.load();
      this.lightsBox.replaceChildren(...PcLights.rows(snap).map(([k, v, o]) => lightRow(k, v, o || {})));
      const o = PcLights.overall(snap);
      this.overall.replaceChildren(dot(o.state), h("b", o.say));
    }
    const set = (id, v) => { const e = $("#" + id); if (e) e.innerHTML = v; };
    this.cpu.gauge.update(s.cpu_temp, tempColor(s.cpu_temp));
    this.gpu.gauge.update(s.gpu_temp, tempColor(s.gpu_temp));
    set("cpu-load", fmt.n(s.cpu_load, 0) + "<small>%</small>");
    set("cpu-x", s.cpu_clock ? fmt.n(s.cpu_clock / 1000, 2) + "<small>GHz</small>" : "—");
    set("cpu-pw", fmt.n(s.cpu_power, 0) + "<small>W</small>");
    set("gpu-load", fmt.n(s.gpu_load, 0) + "<small>%</small>");
    const hot = snap.sensors.find(x => x.type.startsWith("Gpu") && x.kind === "Temperature" && /hot/i.test(x.name));
    set("gpu-x", hot ? fmt.n(hot.value, 0) + "<small>°C</small>" : "—");
    set("gpu-pw", fmt.n(s.gpu_power, 0) + "<small>W</small>");
    set("d-ram", fmt.n(s.ram_load, 0) + "%");
    const bar = $("#d-ram-bar"); if (bar) bar.style.width = (s.ram_load || 0) + "%";
    set("d-ram-sub", s.ram_used != null ? `${fmt.n(s.ram_used, 1)} GB used · ${fmt.n(s.ram_avail, 1)} GB free` : "");
    set("d-disk", fmt.rate((s.disk_r || 0) + (s.disk_w || 0)));
    set("d-disk-sub", `Read ${fmt.rate(s.disk_r)} · Write ${fmt.rate(s.disk_w)}`);
    set("d-net", "↓ " + fmt.rate(s.net_d));
    set("d-net-sub", "↑ " + fmt.rate(s.net_u));

    const ids = s.ids;
    const ser = await App.api.series([ids.cpu_load, ids.gpu_load, ids.ram_load, "/ps/disk/read", "/ps/net/down"]);
    const sp = (c, d, col, max) => { const e = $("#" + c); if (e) drawSpark(e, d, col, { max }); };
    sp("cpu-spark", ser[ids.cpu_load], css("--accent"), 100);
    sp("gpu-spark", ser[ids.gpu_load], css("--accent-2"), 100);
    sp("d-ram-spark", ser[ids.ram_load], css("--good"), 100);
    sp("d-disk-spark", ser["/ps/disk/read"], "#ff7ab6");
    sp("d-net-spark", ser["/ps/net/down"], "#7aa2ff");

    const fans = snap.sensors.filter(x => x.kind === "Fan" && x.value != null);
    this.fans.innerHTML = "";
    if (!fans.length) this.fans.append(h("div.muted.small", "No fan speed sensors yet - see RigLab setup."));
    for (const f of fans.slice(0, 7)) {
      this.fans.append(h("div.r", h("div", { title: f.hw }, f.name, h("span.faint", " · " + f.hw.split(" › ").pop())),
        h("div.bar", h("i", { style: { width: Math.min(100, f.value / 25) + "%" } })), h("div.mono.small", { style: { textAlign: "right" } }, Math.round(f.value))));
    }
  },
};

// =================================================================== Sensors
const KIND_FILTERS = [["All", null], ["Temperatures", "Temperature"], ["Usage", "Load"], ["Clocks", "Clock"], ["Power", "Power"],
  ["Fans", "Fan"], ["Fan control", "Control"], ["Voltages", "Voltage"], ["Data", "Data|SmallData|Throughput"]];
const KIND_NAMES = { Load: "Usage", Temperature: "Temperatures", Clock: "Clocks", Power: "Power", Fan: "Fans", Control: "Fan / pump control",
  Voltage: "Voltages", Data: "Data", SmallData: "Data", Throughput: "Throughput", Level: "Levels", Current: "Current" };

App.pages.sensors = {
  q: "", kind: null, sel: null,
  render(el) {
    const logBtn = h("button.btn", { onclick: async () => { const r = await App.api.log_toggle(); logBtn.lastChild.textContent = r.active ? "Stop logging" : "Log to CSV"; toast(r.active ? "Logging to " + r.path : "Saved " + r.path); } }, icon("download"), h("span", "Log to CSV"));
    el.append(pageHead("Sensors", "Every reading your hardware reports. Click a row to graph it.", h("span.act", logBtn, infoBtn("log.csv"))));
    el.append(h("div.row.wrap", { style: { marginBottom: "14px" } },
      h("div.search", { style: { maxWidth: "340px" } }, icon("search"), h("input", { type: "text", placeholder: "Search sensors… (e.g. core, nvme, fan)", value: this.q, oninput: (e) => { this.q = e.target.value.toLowerCase(); this.draw(); } })),
      h("div.chips", KIND_FILTERS.map(([l, k]) => h("div.chip" + (this.kind === k ? ".on" : ""), { onclick: (e) => { this.kind = k; $$(".chips .chip", el).forEach(c => c.classList.remove("on")); e.target.classList.add("on"); this.draw(); } }, l)))));
    this.tbody = h("tbody");
    this.chartTitle = h("h3", "Pick a sensor");
    this.chartSub = h("div.sub", "Its last 5 minutes will appear here.");
    this.canvas = h("canvas.chart", { style: { height: "260px" } });
    this.stats = h("div.kv3");
    el.append(h("div.split",
      h("div.card.flush", h("div.scroll-box", h("table.t", h("thead", h("tr", h("th", "Sensor"), h("th", { style: { textAlign: "right" } }, "Now"), h("th", { style: { textAlign: "right" } }, "Min"), h("th", { style: { textAlign: "right" } }, "Max"))), this.tbody))),
      h("div.card.sticky", this.chartTitle, this.chartSub, this.stats, this.canvas)));
    this.draw();
  },
  draw() {
    const snap = App.snap; if (!snap) return;
    const rx = this.kind ? new RegExp("^(" + this.kind + ")$") : null;
    const list = snap.sensors.filter(s => (!rx || rx.test(s.kind)) && (!this.q || (s.hw + " " + s.name + " " + s.kind).toLowerCase().includes(this.q)));
    const groups = {};
    for (const s of list) ((groups[s.hw] ||= {})[KIND_NAMES[s.kind] || s.kind] ||= []).push(s);
    const rows = [];
    for (const hw of Object.keys(groups).sort()) {
      rows.push(h("tr.group", h("td", { colSpan: 4 }, hw)));
      for (const k of Object.keys(groups[hw])) {
        rows.push(h("tr.sub", h("td", { colSpan: 4 }, k)));
        for (const s of groups[hw][k]) {
          const col = s.kind === "Temperature" ? tempColor(s.value) : null;
          rows.push(h("tr.click" + (this.sel === s.id ? ".sel" : ""), { onclick: () => { this.sel = s.id; this.draw(); this.tick(App.snap); } },
            h("td", s.name), h("td.num", { style: col ? { color: col, fontWeight: 650 } : null }, s.fmt), h("td.num.muted", s.fmin), h("td.num.muted", s.fmax)));
        }
      }
    }
    this.tbody.replaceChildren(...(rows.length ? rows : [h("tr", h("td.empty", { colSpan: 4 }, "No sensors match."))]));
  },
  async tick(snap) {
    if (!this.sel) { const t = snap.summary.ids.cpu_temp || snap.summary.ids.cpu_load; if (t) this.sel = t; }
    this.draw();
    if (!this.sel) return;
    const s = snap.sensors.find(x => x.id === this.sel);
    if (!s) return;
    this.chartTitle.textContent = s.name;
    this.chartSub.textContent = s.hw + " · " + (KIND_NAMES[s.kind] || s.kind);
    this.stats.replaceChildren(...[["Now", s.fmt], ["Min", s.fmin], ["Max", s.fmax]].map(([k, v]) => h("div.kv", h("div.k", k), h("div.v", { style: { fontSize: "16px" } }, v || "—"))));
    const ser = (await App.api.series([s.id]))[s.id] || [];
    drawChart(this.canvas, [{ data: ser, color: s.kind === "Temperature" ? css("--warn") : css("--accent") }], { yLabel: s.unit, xLabel: "seconds", xMax: 0 });
  },
};

// =================================================================== Hardware
const SECTION_ICONS = { Processor: "cpu", Graphics: "gpu", Motherboard: "board", Memory: "ram", Storage: "disk", Displays: "monitor",
  Network: "net", Audio: "sound", System: "sys", Errors: "alert" };

App.pages.hardware = {
  render(el) {
    this.el = el;
    el.append(pageHead("Hardware", "What's inside this PC, and how healthy your drives are.",
      h("button.btn", { onclick: () => this.load(true) }, icon("refresh"), "Refresh"),
      actionBtn("report.export", async () => toast("Report saved: " + await App.api.export_report()), { cls: "primary", icon: "download", label: "Export report" })));
    this.body = h("div", h("div.empty", h("div.spinner"), h("div.mt", "Reading hardware inventory… (a few seconds)")));
    el.append(this.body);
    this.load(false);
  },
  async load(refresh) {
    const inv = await App.api.inventory(refresh);
    const order = ["Processor", "Graphics", "Motherboard", "Memory", "Storage", "Displays", "Network", "Audio", "System", "Errors"];
    const secs = Object.keys(inv.sections).sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
    const cards = secs.map(sec => h("div.card",
      cardHead(sec, SECTION_ICONS[sec] || "chip"),
      h("div.spec", inv.sections[sec].flatMap((row, i) => [
        i ? h("div.spec-sep") : null,
        ...Object.entries(row).flatMap(([k, v]) => [h("div.k", k), h("div.v", { style: k.startsWith("⚠") ? { color: css("--warn") } : null }, String(v ?? "—"))])]))));
    const drives = inv.drives || [];
    const pill = v => h("span.pill." + ({ Good: "good", Caution: "warn", Bad: "bad" }[v] || ""), v);
    const dcard = h("div.card.mt", cardHead("Drive health", "disk"),
      h("div.sub", "From Windows' reliability counters. Some drives don't report every value."),
      drives.length ? h("table.t", h("thead", h("tr", ["Drive", "Health", "Temp", "Wear", "Power-on", "Errors (R/W)", "Notes"].map(x => h("th", x)))),
        h("tbody", drives.map(d => h("tr", h("td", h("b", d.Name)), h("td", pill(d.Verdict)), h("td.num", d.Temp != null ? d.Temp + "°C" : "—"),
          h("td.num", d.Wear != null ? d.Wear + "%" : "—"), h("td.num", d.PowerOnHours != null ? fmt.n(d.PowerOnHours) + " h" : "—"),
          h("td.num", `${d.ReadErrors || 0} / ${d.WriteErrors || 0}`), h("td.muted", d.Notes)))))
        : h("div.empty", "No drive data (needs Windows + admin)."));
    this.body.replaceChildren(h("div.grid.g2", cards), dcard);
  },
};
