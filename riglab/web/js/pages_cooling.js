/* Cooling: fan list + draggable curve editor */
"use strict";

App.pages.cooling = {
  sel: null, points: null, source: null, pump: false,
  async render(el) {
    this.el = el;
    el.append(pageHead("Cooling", "Custom fan and pump curves. Drag the points on the graph to shape how fast fans spin as things heat up."));
    this.top = h("div");
    el.append(this.top);
    this.list = h("div.fan-list");
    this.editor = h("div.card");
    el.append(h("div.grid", { style: { gridTemplateColumns: "400px minmax(0,1fr)", alignItems: "start" } },
      h("div.card", cardHead("Fans & pumps", "fan"), this.list), this.editor));
    el.append(h("div.card.mt", cardHead("Safety rules (always on)", "info"), h("div.small.muted", { style: { lineHeight: "1.8" } },
      "• Fans never go below 20%, pumps never below 60%.  • If the temperature sensor disappears or passes 90°C, the fan goes to 100%.  ",
      "• When RigLab closes, motherboard fans go back to BIOS control and USB hubs go back to their own defaults.")));
    await this.refresh(true);
  },
  async refresh(first) {
    const st = await App.api.fans_state();
    this.st = st;
    const hubs = st.controls.filter(c => c.hub).length, mobo = st.controls.length - hubs;
    this.top.replaceChildren(
      st.controls.length ? h("div.card", { style: { marginBottom: "16px" } }, h("div.row",
        h("div.icon-badge", icon("fan")), h("div", h("div", { style: { fontWeight: 650 } }, "RigLab fan control"),
          h("div.small.muted", `${mobo} motherboard header${mobo === 1 ? "" : "s"} · ${hubs} USB hub channel${hubs === 1 ? "" : "s"}`)),
        h("div.spacer"), switchEl(st.enabled, async v => { await App.api.fans_enable(v); toast(v ? "Fan curves active" : "Fans handed back to BIOS / hub"); this.refresh(); })))
        : banner("bad", "alert", "<b>No controllable fans found.</b> Motherboard fans need admin + the PawnIO driver + LibreHardwareMonitor. Corsair Commander Core / Core XT / ST / Pro and NZXT hubs are controlled directly (close iCUE / NZXT CAM first). iCUE LINK hubs aren't supported yet.",
          h("button.btn.sm", { onclick: () => go("health") }, "Health check")));
    if (first && st.controls.length && !this.sel) this.select(st.controls[0].id);
    this.drawList();
  },
  drawList() {
    const st = this.st;
    if (!st.controls.length) { this.list.replaceChildren(h("div.empty.small", icon("fan"), h("div", "Nothing to control yet."))); this.editor.replaceChildren(h("div.empty", "Fix the items in Health check, then come back.")); return; }
    this.list.replaceChildren(...st.controls.map(c => {
      const spin = icon("fan", "spin" + (c.rpm ? " go" : ""));
      if (c.rpm) spin.style.animationDuration = Math.max(0.25, 60 / Math.max(c.rpm, 1) * 8) + "s";
      return h("div.fan-item" + (this.sel === c.id ? ".sel" : ""), { onclick: () => this.select(c.id) },
        spin,
        h("div", { style: { minWidth: 0 } }, h("div", { style: { fontWeight: 600 } }, c.name), h("div.small.muted", { title: c.hw, style: { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, c.hw.split(" › ")[0]),
          h("div.row", { style: { gap: "6px", marginTop: "4px" } },
            c.curve ? h("span.pill.info", "Curve") : h("span.pill", c.hub ? "Hub default" : "BIOS"),
            c.hub ? h("span.pill", "USB hub") : null, c.pump || (c.curve && c.curve.pump) ? h("span.pill.warn", "Pump") : null)),
        h("div", h("div.rpm", c.rpm != null ? fmt.n(c.rpm) + " rpm" : "—"), h("div.small.muted", { style: { textAlign: "right" } }, c.value != null ? Math.round(c.value) + "%" : "")));
    }));
  },
  select(id) {
    this.sel = id;
    const c = this.st.controls.find(x => x.id === id);
    const curve = c.curve;
    this.points = (curve ? curve.points : this.st.presets.Balanced).map(p => [...p]);
    this.source = curve ? curve.source : (this.st.temps[0] || {}).id;
    this.pump = curve ? !!curve.pump : c.pump;
    this.drawList();
    this.drawEditor(c);
  },
  drawEditor(c) {
    const srcSel = h("select", { style: { flex: 1 }, onchange: e => { this.source = e.target.value; } },
      this.st.temps.map(t => h("option", { value: t.id, selected: t.id === this.source }, `${t.name}  (${fmt.n(t.value, 0)}°C)`)));
    const presets = h("div.chips", Object.keys(this.st.presets).map(n => h("div.chip", { onclick: () => { this.points = this.st.presets[n].map(p => [...p]); this.drawCurve(); } }, n)));
    this.cv = h("canvas");
    this.live = h("div.small.muted");
    const manual = sliderRow("Fixed speed", 20, 100, 60, 1, "%", v => { this.manualV = v; });
    this.manualV = 60;
    this.editor.replaceChildren(
      cardHead(c.name, "sliders", h("span.small.muted", c.hw)),
      h("div.row.wrap", { style: { marginBottom: "12px" } }, h("span.muted.small", "Follow temperature of"), srcSel),
      h("div.row.wrap", { style: { marginBottom: "12px" } }, h("span.muted.small", "Presets"), presets, h("div.spacer"),
        h("label.row.small", { style: { gap: "8px" } }, "This is a pump", switchEl(this.pump, v => { this.pump = v; this.drawCurve(); }))),
      h("div.curve-box", this.cv),
      h("div.row", { style: { marginTop: "10px" } }, this.live, h("div.spacer"),
        c.curve ? h("button.btn", { onclick: async () => { await App.api.fans_remove(c.id); toast("Curve removed"); await this.refresh(); this.select(c.id); } }, icon("undo"), "Remove curve") : null,
        h("button.btn.primary", { onclick: async () => { await App.api.fans_set_curve(c.id, this.source, this.points, this.pump); if (!this.st.enabled) await App.api.fans_enable(true); toast("Curve saved and active"); await this.refresh(); } }, icon("check"), "Save curve")),
      h("div.opt", { style: { marginTop: "14px", borderTop: "1px solid var(--line)", paddingTop: "14px" } },
        h("div", h("div.t", "Manual override"), h("div.d", "Hold a fixed speed for testing (pauses curves). Release gives control back.")),
        h("div.row", h("div", { style: { width: "320px" } }, manual),
          h("button.btn.sm", { onclick: async () => toast(await App.api.fans_manual(c.id, this.manualV) ? `Set to ${this.manualV}%` : "This channel didn't accept the change", false) }, "Set"),
          h("button.btn.sm", { onclick: async () => { await App.api.fans_manual(c.id, null); toast("Released"); } }, "Release"))));
    this.bindDrag();
    requestAnimationFrame(() => this.drawCurve());
  },
  drawCurve() {
    if (!this.cv) return;
    this.cv.style.height = "300px";
    const floor = this.pump ? 60 : 20;
    const pts = this.points.slice().sort((a, b) => a[0] - b[0]);
    const g = drawChart(this.cv, [], { xMin: 20, xMax: 100, yMin: 0, yMax: 100, xLabel: "°C", yLabel: "fan %" });
    const [ctx] = fitCanvas(this.cv);
    this.geo = g;
    ctx.fillStyle = "rgba(255,92,108,.08)"; ctx.fillRect(g.X(20), g.Y(floor), g.X(100) - g.X(20), g.Y(0) - g.Y(floor));
    ctx.fillStyle = "rgba(255,92,108,.08)"; ctx.fillRect(g.X(90), g.Y(100), g.X(100) - g.X(90), g.Y(0) - g.Y(100));
    const grad = ctx.createLinearGradient(0, g.Y(100), 0, g.Y(0));
    grad.addColorStop(0, `rgba(${css("--accent-rgb")},.28)`); grad.addColorStop(1, `rgba(${css("--accent-2-rgb")},.02)`);
    ctx.beginPath(); ctx.moveTo(g.X(20), g.Y(Math.max(floor, pts[0][1])));
    for (const [t, p] of pts) ctx.lineTo(g.X(t), g.Y(Math.max(floor, p)));
    ctx.lineTo(g.X(100), g.Y(Math.max(floor, pts[pts.length - 1][1])));
    ctx.lineTo(g.X(100), g.Y(0)); ctx.lineTo(g.X(20), g.Y(0)); ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath(); ctx.moveTo(g.X(20), g.Y(Math.max(floor, pts[0][1])));
    for (const [t, p] of pts) ctx.lineTo(g.X(t), g.Y(Math.max(floor, p)));
    ctx.lineTo(g.X(100), g.Y(Math.max(floor, pts[pts.length - 1][1])));
    ctx.strokeStyle = css("--accent"); ctx.lineWidth = 2.5; ctx.stroke();
    for (const [t, p] of this.points) {
      ctx.beginPath(); ctx.arc(g.X(t), g.Y(p), 7, 0, Math.PI * 2); ctx.fillStyle = "#fff"; ctx.fill();
      ctx.lineWidth = 3; ctx.strokeStyle = css("--accent"); ctx.stroke();
    }
    // current operating point
    const src = App.snap?.sensors.find(s => s.id === this.source);
    if (src && src.value != null) {
      const v = Math.max(floor, interp(pts, src.value));
      ctx.beginPath(); ctx.arc(g.X(Math.min(100, Math.max(20, src.value))), g.Y(v), 6, 0, Math.PI * 2); ctx.fillStyle = css("--warn"); ctx.fill();
      this.live.innerHTML = `Now: <b>${fmt.n(src.value, 1)}°C</b> → curve says <b>${Math.round(v)}%</b>`;
    }
    ctx.font = "11px " + css("--font"); ctx.fillStyle = "rgba(255,92,108,.7)"; ctx.textAlign = "left";
    ctx.fillText(`minimum ${floor}%`, g.X(21), g.Y(floor) + 14);
    ctx.textAlign = "right"; ctx.fillText("90°C+ → 100%", g.X(99), g.Y(100) + 14);
  },
  bindDrag() {
    let idx = -1;
    const pos = e => { const b = this.cv.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top]; };
    this.cv.addEventListener("pointerdown", e => {
      const [x, y] = pos(e), g = this.geo;
      idx = this.points.findIndex(([t, p]) => Math.hypot(g.X(t) - x, g.Y(p) - y) < 14);
      if (idx >= 0) { this.cv.setPointerCapture(e.pointerId); this.cv.style.cursor = "grabbing"; }
    });
    this.cv.addEventListener("pointermove", e => {
      if (idx < 0) return;
      const [x, y] = pos(e), g = this.geo;
      const t = 20 + (x - g.pad.l) / (g.w - g.pad.l - g.pad.r) * 80, p = (g.h - g.pad.b - y) / (g.h - g.pad.t - g.pad.b) * 100;
      this.points[idx] = [Math.round(Math.max(20, Math.min(100, t))), Math.round(Math.max(0, Math.min(100, p)))];
      this.drawCurve();
    });
    this.cv.addEventListener("pointerup", () => { idx = -1; this.cv.style.cursor = "grab"; });
  },
  tick() {
    if (this.st && Date.now() - (this.lastRefresh || 0) > 2000) { this.lastRefresh = Date.now(); this.refresh(); }
    this.drawCurve();
  },
};

function interp(pts, t) {
  if (t <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) if (t <= pts[i][0]) { const [a, b] = [pts[i - 1], pts[i]]; return a[1] + (b[1] - a[1]) * (t - a[0]) / ((b[0] - a[0]) || 1); }
  return pts[pts.length - 1][1];
}
