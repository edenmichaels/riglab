/* Dashboard, Sensors, Hardware */
"use strict";

// =================================================================== Dashboard
App.pages.dashboard = {
  render(el) {
    const s = App.snap.summary;
    this.el = el;
    el.append(pageHead("Dashboard", "Everything important at a glance. Click a card to dig deeper."));
    this.alerts = h("div");
    el.append(this.alerts);
    this.showAlerts();

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
    el.append(h("div.grid.g2", this.cpu, this.gpu));

    const tile = (title, ic, id, extra) => h("div.card", cardHead(title, ic), h("div.stat-big", { id }, "—"),
      extra, h("canvas.spark#" + id + "-spark", { style: { marginTop: "8px" } }));
    el.append(h("div.grid.g3.mt",
      tile("Memory", "ram", "d-ram", h("div", h("div.bar", { style: { margin: "8px 0 4px" } }, h("i#d-ram-bar")), h("div.small.muted#d-ram-sub", ""))),
      tile("Storage activity", "disk", "d-disk", h("div.small.muted#d-disk-sub", "")),
      tile("Network", "net", "d-net", h("div.small.muted#d-net-sub", ""))));

    this.fans = h("div.fanmini");
    el.append(h("div.grid.g2.mt",
      h("div.card", cardHead("Fans & pumps", "fan", h("button.btn.sm.ghost", { onclick: () => go("cooling") }, "Open cooling →")), this.fans),
      h("div.card", cardHead("Quick actions", "rocket"), h("div.quick",
        h("button.btn", { onclick: () => go("benchmark") }, icon("bench"), "Run benchmark"),
        h("button.btn", { onclick: () => go("stress") }, icon("flame"), "Stability test"),
        h("button.btn", { onclick: () => go("lighting") }, icon("light"), "Lighting"),
        h("button.btn", { onclick: async () => { const r = await App.api.rgb_off(); toast(r === "ok" ? "Lights off" : r, r !== "ok"); } }, icon("power"), "All lights off"),
        h("button.btn", { onclick: () => go("health") }, icon("heart"), "Health check"),
        h("button.btn", { onclick: async () => { const p = await App.api.export_report(); toast("Report saved: " + p); } }, icon("download"), "System report")))));
  },
  async showAlerts() {
    const items = await refreshHealth();
    this.alerts.innerHTML = "";
    for (const n of (await App.api.startup_notes()) || []) {
      this.alerts.append(banner(n.kind === "bad" ? "bad" : "info", n.kind === "bad" ? "alert" : "info", n.text,
        h("button.btn.sm", { onclick: () => go(n.page || (n.kind === "bad" ? "crashes" : "overclock")) }, n.page === "crashes" || n.kind === "bad" ? "Crash Center" : "Overclocking")));
    }
    const bad = items.filter(i => i.ok === false);
    if (bad.length) {
      this.alerts.append(banner("bad", "alert", `<b>${bad.length} thing${bad.length > 1 ? "s" : ""} need${bad.length > 1 ? "" : "s"} attention:</b> ` +
        bad.map(b => b.title).join(" · ") + ". Some sensors or controls will be missing until fixed.",
        h("button.btn.sm", { onclick: () => go("health") }, "Fix it")));
    }
  },
  async tick(snap) {
    const s = snap.summary;
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
    if (!fans.length) this.fans.append(h("div.muted.small", "No fan speed sensors yet - see Health check."));
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
    el.append(pageHead("Sensors", "Every reading your hardware reports. Click a row to graph it.", logBtn));
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
      h("button.btn.primary", { onclick: async () => toast("Report saved: " + await App.api.export_report()) }, icon("download"), "Export report")));
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
