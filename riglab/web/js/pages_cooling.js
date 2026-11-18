/* Cooling: fan list + draggable curve editor */
"use strict";

// Simple view names for the presets in core/fans.py (same curves; "Full speed" stays in Advanced)
const FAN_SIMPLE = [["Silent", "Quiet", "Less noise. Parts run a bit warmer."], ["Balanced", "Balanced", "A good mix of quiet and cool. Recommended."],
  ["Performance", "Cool", "Parts stay colder. Fans are louder."]];

App.pages.cooling = {
  sel: null, points: null, source: null, pump: false,
  async render(el) {
    this.el = el;
    const S = isSimple();
    el.append(plainHead("Fans", "Make your PC quieter or cooler with one click. RigLab's safety rules always stay on.",
      "Cooling", "Custom fan and pump curves. Drag the points on the graph to shape how fast fans spin as things heat up."));
    this.top = h("div");
    el.append(this.top);
    this.list = h("div.fan-list");
    this.editor = h("div.card");
    const editorGrid = h("div.grid", { "data-anchor": "curves", style: { gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 380px), 1fr))", alignItems: "start" } },
      h("div.card", cardHead("Fans & pumps", "fan"), this.list), this.editor);
    const safety = h("div.card.mt", cardHead(S ? "Safety rules (always on)" : "Safety rules (always on)", "info"), h("div.small.muted", { style: { lineHeight: "1.8" } }, S
      ? ["• Fans never spin slower than 20%, and pumps never slower than 60%.", h("br"), "• If RigLab loses a temperature reading, or something passes 90°C, the fans go to full speed.", h("br"), "• When RigLab closes, your fans go back to how they were before."]
      : ["• Fans never go below 20%, pumps never below 60%.  • If the temperature sensor disappears or passes 90°C, the fan goes to 100%.  ",
        "• When RigLab closes, motherboard fans go back to BIOS control and USB hubs go back to their own defaults."]));
    if (S) {
      this.simpleBox = h("div");
      el.append(this.simpleBox, safety, details("Fine-tune each fan (draw your own fan curves)", editorGrid),
        h("div.mt", advLink("Hold a fan at one speed (for testing)", "cooling", { focus: "curves", icon: "fan" })));
    } else {
      this.simpleBox = null;
      el.append(editorGrid, safety);
    }
    await this.refresh(true);
  },
  drawSimple() {
    if (!this.simpleBox) return;
    const st = this.st;
    if (!st.controls.length) { this.simpleBox.replaceChildren(); return; }
    const same = (a, b) => a && b && JSON.stringify(a) === JSON.stringify(b);
    const cur = FAN_SIMPLE.find(([k]) => st.enabled && st.controls.every(c => c.curve && same(c.curve.points, st.presets[k])));
    const goals = h("div.goal-grid", FAN_SIMPLE.map(([k, label, desc]) => h("button.goal" + (cur && cur[0] === k ? ".on" : ""), {
      onclick: async () => { const r = await guarded("fans.preset", () => App.api.fans_preset(k)); if (r) { toast(r.ok ? `All fans set to ${label}` : r.msg, !r.ok); this.refresh(); } } },
      h("div.icon-badge", icon("fan")), h("div", h("div", label, cur && cur[0] === k ? h("span.pill.good", { style: { marginLeft: "8px" } }, "In use") : null), h("div.small.muted", { style: { fontWeight: 400 } }, desc)))));
    const fanRows = st.controls.map(c => {
      const state = c.rpm == null ? "none" : c.rpm > 0 ? "good" : (c.pump ? "bad" : "warn");
      return lightRow("fans", null, { state, label: c.name, say: c.rpm == null ? "RigLab can't see its speed" : c.rpm > 0 ? "Spinning" : (c.pump ? "Pump not spinning - needs fixing" : "Not spinning right now") });
    });
    this.simpleBox.replaceChildren(
      h("div.card", cardHead("How should my fans behave?", "fan", infoBtn("fans.preset")),
        h("div.sub", cur ? `Your fans are set to ${cur[1]}.` : st.enabled ? "Your fans use your own settings. Pick one below to change them all." : "Your fans are controlled by your motherboard right now. Pick one below to let RigLab look after them."), goals),
      h("div.card.mt", cardHead("Your fans", "fan"), fanRows, h("div", { style: { padding: "6px 0" } }, colourKey()),
        switchRow("fans.enable", st.enabled, async (v) => { await App.api.fans_enable(v); toast(v ? "RigLab is looking after your fans" : "Fans handed back to your motherboard"); this.refresh(); return true; })));
  },
  async refresh(first) {
    const st = await App.api.fans_state();
    this.st = st;
    const hubs = st.controls.filter(c => c.hub).length, mobo = st.controls.length - hubs;
    this.top.replaceChildren(
      st.controls.length ? h("div.card", { style: { marginBottom: "16px" } }, h("div.row",
        h("div.icon-badge", icon("fan")), h("div", h("div", { style: { fontWeight: 650 } }, "RigLab fan control"),
          h("div.small.muted", `${mobo} motherboard header${mobo === 1 ? "" : "s"} · ${hubs} USB hub channel${hubs === 1 ? "" : "s"}`)),
        h("div.spacer"), infoBtn("fans.enable"), switchEl(st.enabled, async v => { await App.api.fans_enable(v); toast(v ? "Fan curves active" : "Fans handed back to BIOS / hub"); this.refresh(); })))
        : banner("bad", "alert", isSimple() ? "<b>RigLab can't control your fans yet.</b> It usually needs a small helper or full permission first. RigLab setup shows what's missing."
          : "<b>No controllable fans found.</b> Motherboard fans need admin + the PawnIO driver + LibreHardwareMonitor. Corsair Commander Core / Core XT / ST / Pro and NZXT hubs are controlled directly (close iCUE / NZXT CAM first). iCUE LINK hubs aren't supported yet.",
          h("button.btn.sm", { onclick: () => go("health") }, isSimple() ? "Find out why" : "RigLab setup")));
    if (this.simpleBox && st.controls.length) this.top.replaceChildren();     // Simple view has its own on/off switch
    if (first && st.controls.length && !this.sel) this.select(st.controls[0].id);
    else if (first && st.controls.length && this.sel) this.select(this.sel);
    this.drawList();
    this.drawSimple();
  },
  drawList() {
    const st = this.st;
    if (!st.controls.length) { this.list.replaceChildren(h("div.empty.small", icon("fan"), h("div", "Nothing to control yet."))); this.editor.replaceChildren(h("div.empty", "Fix the items in RigLab setup, then come back.")); return; }
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
        c.curve ? actionBtn("fans.remove", async () => { await App.api.fans_remove(c.id); toast("Curve removed"); await this.refresh(); this.select(c.id); }, { icon: "undo", label: "Remove curve", always: true }) : null,
        actionBtn("fans.curve", async () => { await App.api.fans_set_curve(c.id, this.source, this.points, this.pump); if (!this.st.enabled) await App.api.fans_enable(true); toast("Curve saved and active"); await this.refresh(); }, { cls: "primary", icon: "check", label: "Save curve", always: true })),
      isSimple() ? null : h("div.opt", { style: { marginTop: "14px", borderTop: "1px solid var(--line)", paddingTop: "14px" } },
        h("div", h("div.t", "Manual override ", infoBtn("fans.manual")), h("div.d", "Hold a fixed speed for testing (pauses curves). Release gives control back.")),
        h("div.row.wrap", h("div", { style: { width: "min(320px, 100%)" } }, manual),
          h("button.btn.sm", { onclick: async () => { const ok = await guarded("fans.manual", () => App.api.fans_manual(c.id, this.manualV)); if (ok != null) toast(ok ? `Set to ${this.manualV}%` : "This channel didn't accept the change", !ok); } }, "Set"),
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
