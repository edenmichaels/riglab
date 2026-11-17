/* Crash Center: Event Viewer + Reliability Monitor + dump files, grouped into explained incidents */
"use strict";

const INC_STYLE = { bsod: ["Blue screen", "bad", "alert"], reset: ["Unexpected restart", "bad", "power"], whea: ["Hardware errors", "warn", "cpu"],
  gpu: ["Graphics driver", "warn", "gpu"], livekernel: ["Recovered hiccup", "warn", "pulse"], disk: ["Storage", "warn", "disk"],
  app: ["App crash", "", "x"], other: ["Other", "", "info"] };
const INC_FILTERS = [["All", null], ["Crashes & restarts", ["bsod", "reset"]], ["Graphics", ["gpu", "livekernel"]], ["Hardware (WHEA)", ["whea"]], ["Apps", ["app"]], ["Storage", ["disk"]]];

App.pages.crashes = {
  days: 30, filter: null,
  render(el) {
    this.el = el;
    const daysSel = h("select", { onchange: e => { this.days = +e.target.value; this.scan(); } },
      [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]].map(([d, l]) => h("option", { value: d, selected: d === this.days }, l)));
    el.append(plainHead("Crashes & freezes", "Why your PC crashed, froze or restarted by itself, explained in plain English.",
      "Crash Center", "Why your PC crashed: Event Viewer, Reliability Monitor and crash dump files, combined and explained in plain English.",
      daysSel, h("span.act", h("button.btn", { onclick: () => this.scan() }, icon("refresh"), isSimple() ? "Look again" : "Rescan"), infoBtn("crash.scan"))));
    this.body = h("div");
    el.append(this.body);
    this.scan();
  },
  async scan() {
    this.body.replaceChildren(h("div.empty", h("div.spinner"), h("div.mt", "Reading Event Viewer, Reliability Monitor and dump files… (5-20 s)")));
    this.data = await App.api.crashes_scan(this.days);
    this.draw();
  },
  draw() {
    const d = this.data, inc = d.incidents;
    const count = (types) => inc.filter(i => types.includes(i.type)).length;
    const tile = (label, n, col, ic) => h("div.card", { style: { padding: "14px 16px" } }, h("div.row", h("div.icon-badge", icon(ic)), h("div.small.muted", label)),
      h("div.stat-big", { style: { marginTop: "8px", color: n ? col : css("--good") } }, n));
    const stab = h("canvas.chart", { style: { height: "120px" } });
    const parts = [
      h("div.grid", { style: { gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" } },
        tile("Blue screens", count(["bsod"]), css("--bad"), "alert"), tile("Unexpected restarts", count(["reset"]), css("--bad"), "power"),
        tile("Graphics resets", count(["gpu", "livekernel"]), css("--warn"), "gpu"), tile("Hardware errors", count(["whea"]), css("--warn"), "cpu"),
        tile("App crashes", count(["app"]), css("--muted"), "x")),
      h("div.card.mt", cardHead("Reliability index", "pulse", h("span.small.muted", "Windows' own 1-10 stability score (Reliability Monitor)")),
        d.stability.length ? stab : h("div.small.muted", "No data (Reliability Monitor may be turned off).")),
    ];
    if (!d.debugger) parts.push(h("div.mt", banner("info", "info", "<b>Want the exact driver behind a blue screen?</b> Install Microsoft's free debugger (WinDbg) - RigLab then runs <span class='mono'>!analyze -v</span> on each dump for you.",
      actionBtn("crash.windbg", async () => toast(await App.api.install_windbg()), { cls: "sm", icon: "download", label: "Install WinDbg", always: true }))));
    const chips = h("div.chips", { style: { margin: "18px 0 12px" } }, INC_FILTERS.map(([l, f]) => h("div.chip" + (JSON.stringify(this.filter) === JSON.stringify(f) ? ".on" : ""), { onclick: () => { this.filter = f; this.draw(); } }, l)));
    parts.push(chips);
    const list = inc.filter(i => !this.filter || this.filter.includes(i.type));
    parts.push(list.length ? h("div.stack", { style: { gap: "12px" } }, list.map(i => this.incident(i)))
      : h("div.card", h("div.empty", icon("check"), h("div", inc.length ? "Nothing in this category." : `No crashes or errors in the last ${d.days} days. 🎉`))));
    this.body.replaceChildren(...parts);
    if (d.stability.length) requestAnimationFrame(() => {
      const t0 = d.stability[0].time;
      drawChart(stab, [{ data: d.stability.map(s => [(s.time - t0) / 86400, s.v]), color: css("--accent") }], { yMin: 0, yMax: 10, xLabel: "days" });
    });
  },
  incident(i) {
    const [label, cls, ic] = INC_STYLE[i.type] || INC_STYLE.other;
    const when = new Date(i.time * 1000);
    const ago = (Date.now() / 1000 - i.time) / 3600;
    const evBox = h("div.hide", { style: { marginTop: "12px" } },
      h("table.t", h("tbody", i.events.map(e => h("tr", h("td.mono.small", { style: { whiteSpace: "nowrap" } }, new Date(e.time * 1000).toLocaleTimeString()),
        h("td.small", h("b", e.title), h("div.muted", e.detail || ""), h("div.faint", `${e.src || ""} ${e.id ?? ""}`)))))));
    const dumpBox = h("div");
    const card = h("div.card", { style: { borderLeft: `4px solid ${cls === "bad" ? css("--bad") : cls === "warn" ? css("--warn") : css("--line-2")}` } },
      h("div.row", h("div.icon-badge", icon(ic)), h("div", { style: { flex: 1 } }, h("div", { style: { fontWeight: 650, fontSize: "15px" } }, i.title),
        h("div.small.muted", `${when.toLocaleString()} · ${ago < 1 ? Math.round(ago * 60) + " min ago" : ago < 48 ? Math.round(ago) + " h ago" : Math.round(ago / 24) + " days ago"}`)),
        h("span.pill." + cls, label)),
      h("div", { style: { marginTop: "10px" } }, i.summary),
      i.cause ? h("div", { style: { marginTop: "10px", background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: "9px", padding: "10px 12px" } },
        h("div.small", { style: { color: css("--accent"), fontWeight: 650, marginBottom: "2px" } }, "Likely cause"), h("div.small", i.cause)) : null,
      i.bugcheck ? h("div.small.muted", { style: { marginTop: "8px" } }, `Stop code ${i.bugcheck.code} (${i.bugcheck.name})`) : null,
      h("div.row.wrap", { style: { marginTop: "12px" } },
        h("button.btn.sm.ghost", { onclick: () => evBox.classList.toggle("hide") }, `Evidence (${i.events.length})`),
        ...i.dumps.map(p => h("button.btn.sm", { onclick: () => this.analyze(p, dumpBox) }, icon("search"), "Analyse " + p.split("\\").pop())),
        i.recent_change ? h("span.pill.warn", `Changed ${i.recent_change.ago_min} min before: ${i.recent_change.text.slice(0, 60)}`) : null),
      evBox, dumpBox);
    return card;
  },
  async analyze(path, box) {
    const st = h("div.small.muted", "Starting Microsoft's debugger…");
    box.replaceChildren(h("div.card", { style: { marginTop: "12px", background: "var(--bg-2)" } }, h("div.row", h("div.spinner"), st)));
    await App.api.crash_analyze(path);
    for (;;) {
      await new Promise(r => setTimeout(r, 1500));
      const s = await App.api.crash_analyze_status(path);
      if (!s) return;
      if (s.state === "running") { st.textContent = `Analysing… ${Math.round(s.elapsed)} s (first run downloads Windows symbols, can take a few minutes)`; continue; }
      if (s.state === "error") {
        box.replaceChildren(s.error === "nodebugger"
          ? banner("info", "info", "Microsoft's debugger isn't installed yet.", actionBtn("crash.windbg", async () => toast(await App.api.install_windbg()), { cls: "sm", label: "Install WinDbg", always: true }))
          : banner("bad", "alert", "Analysis failed: " + s.error));
        return;
      }
      const r = s.result || {}, raw = h("pre.log.hide", s.raw || "");
      const kv = (k, v) => v ? [h("div.k", k), h("div.v.mono", v)] : [];
      box.replaceChildren(h("div.card", { style: { marginTop: "12px", background: "var(--bg-2)" } },
        h("h3", "Debugger analysis"),
        h("div.spec", { style: { marginTop: "8px" } }, ...kv("Probably caused by", r.PROBABLY_CAUSED_BY), ...kv("Driver / module", r.IMAGE_NAME || r.MODULE_NAME),
          ...kv("Process", r.PROCESS_NAME), ...kv("Failure bucket", r.FAILURE_BUCKET_ID), ...kv("Symbol", r.SYMBOL_NAME)),
        hint(r),
        r.STACK ? h("pre.log", r.STACK) : null,
        h("div.row", { style: { marginTop: "8px" } }, h("button.btn.sm.ghost", { onclick: () => raw.classList.toggle("hide") }, "Full output"),
          h("button.btn.sm.ghost", { onclick: () => navigator.clipboard.writeText(s.raw || "").then(() => toast("Copied")) }, "Copy")), raw));
      return;
    }
  },
};

function hint(r) {
  const img = (r.IMAGE_NAME || r.MODULE_NAME || "").toLowerCase();
  let t = null;
  if (/authenticamd|genuineintel|hardware/.test(img)) t = "Points at the CPU itself - classic sign of an unstable Curve Optimizer/undervolt, CPU overclock, or Infinity Fabric/SoC voltage. Undo the last CPU/RAM change.";
  else if (/amdkmdag|atikmdag|atikmpag|amdwddmg/.test(img)) t = "Points at the AMD graphics driver - undo the last Adrenalin tuning change, then try a clean driver install (AMD Cleanup Utility) if it continues.";
  else if (/nvlddmkm/.test(img)) t = "Points at the NVIDIA graphics driver - undo GPU overclocks, then reinstall the driver.";
  else if (/ntoskrnl|memory_corruption|hal\.dll/.test(img)) t = "Windows' own kernel was the victim, not the cause - this usually means memory corruption. Test RAM without EXPO/overclocks.";
  else if (img.endsWith(".sys")) t = `A third-party driver (${img}) is involved - update or remove the software that installed it.`;
  return t ? h("div.banner.info", { style: { margin: "12px 0" } }, icon("info"), h("div.txt.small", t)) : null;
}
