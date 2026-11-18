/* Tools -> Overlay: the in-game overlay's settings (3.12). Two parts:
   1. "Show and move" - applies straight away: show/hide, edit position (drag) and lock, shrink to a dot, corner,
      show/hide key, hold-to-move keys, and a status line that says what's going on in plain words.
   2. "How it looks" - a live preview of exactly what the overlay will draw (the same drawing code as the real
      overlay), on a dark or light pretend game. Changes stay in the preview until you press Apply.
   Simple view shows the presets (Minimal is the default) and size; Advanced shows every option. */
"use strict";

const OV_STATS = [["fps", "FPS"], ["low1", "1% lows"], ["frametime", "Frame time"], ["cpu_temp", "CPU temp"], ["gpu_temp", "GPU temp"],
  ["cpu_load", "CPU usage"], ["gpu_load", "GPU usage"], ["ram", "RAM"], ["cpu_clock", "CPU clock"], ["gpu_clock", "GPU clock"], ["graph", "Frame-time graph"]];
const OV_PRESETS = [["minimal", "Minimal", "FPS only"], ["standard", "Standard", "FPS + temperatures"], ["full", "Full", "Everything"]];
const OV_PRESET_STATS = { minimal: ["fps"], standard: ["fps", "cpu_temp", "gpu_temp"],
  full: ["fps", "low1", "frametime", "cpu_temp", "gpu_temp", "cpu_load", "gpu_load", "ram", "cpu_clock", "gpu_clock"] };
const OV_LOOK = ["stats", "layout", "size", "opacity", "text_color", "fps_color", "snap"];

function ovPresetOf(stats) {
  for (const [k, v] of Object.entries(OV_PRESET_STATS)) if (JSON.stringify(v) === JSON.stringify(stats || [])) return k;
  return "custom";
}

/* The preview in preview mode (no Python to draw the real picture): same layout and colours, built with HTML. */
function ovMock(d) {
  const k = { s: .85, m: 1, l: 1.3, xl: 1.7 }[d.size] || 1, vert = d.layout === "vertical";
  const names = { fps: "FPS", low1: "1% LOW", frametime: "FRAME", cpu_temp: "CPU", gpu_temp: "GPU", cpu_load: "CPU USE", gpu_load: "GPU USE", ram: "RAM", cpu_clock: "CPU CLK", gpu_clock: "GPU CLK" };
  const vals = { fps: ["144", "", "good"], low1: ["102", "", "good"], frametime: ["6.9", "ms"], cpu_temp: ["64", "°C", "good"], gpu_temp: ["78", "°C", "warn"],
    cpu_load: ["38", "%"], gpu_load: ["96", "%"], ram: ["47", "%"], cpu_clock: ["4.95", "GHz"], gpu_clock: ["2610", "MHz"] };
  const tc = d.text_color === "white" ? "#fff" : /^#/.test(d.text_color || "") ? d.text_color : "var(--text)";
  const plain = d.fps_color === "plain";
  const items = (d.stats || ["fps"]).filter(s => s !== "graph").map(s => {
    const [v, u, st] = vals[s] || ["—", ""];
    return h("div.ovm-i", h("span.ovm-v" + (s === "fps" && !vert ? ".big" : ""), { style: { color: st && !plain ? `var(--${st})` : tc } }, v),
      u ? h("span.ovm-u", u) : null, h("span.ovm-k", names[s] || s));
  });
  const graph = (d.stats || []).includes("graph") ? h("div.ovm-graph") : null;
  return h("div.ovm" + (vert ? ".vert" : "") + ((d.opacity ?? .85) < .25 ? ".clear" : ""), {
    style: { "--k": k, "--ov-a": Math.round((d.opacity ?? .85) * 100) + "%", "--ov-t": tc } }, items, graph);
}

App.pages.overlay = {
  render(el) {
    this.el = el;
    el.append(plainHead("Overlay", "Show your FPS and temperatures on top of your games. Clicks always go straight through to the game.",
      "In-game overlay", "RigLab's own see-through window (per-pixel alpha, click-through, topmost, per-monitor DPI). Works in borderless and windowed games, not exclusive fullscreen."));
    this.ctrlBox = h("div.card");
    this.lookBox = h("div.card.mt");
    el.append(this.ctrlBox, this.lookBox);
    this.load();
  },
  async load() {
    const c = await App.api.settings();
    if (!document.body.contains(this.el)) return;
    this.ov = Object.assign({}, c.overlay || {});
    this.draft = this.pick(this.ov);
    this.bg = this.bg || "dark";
    this.drawCtrl();
    this.drawLook();
    this.poll();
  },
  pick(o) { const d = {}; for (const k of OV_LOOK) d[k] = Array.isArray(o[k]) ? [...o[k]] : o[k]; d.stats ||= ["fps"]; return d; },
  async set(values) {
    try {
      const r = await App.api.overlay_set(values);
      this.ov = Object.assign({}, r.overlay || this.ov);
      if (values.hotkey !== undefined && !r.hotkey_ok) toast("That key combination is already used by another app. Try a different one.", true);
    } catch (e) { toast("Couldn't change the overlay: " + e, true); }
    this.drawCtrl();
  },
  async poll() {
    clearTimeout(this.t);
    if (!document.body.contains(this.el)) return;
    let st = null;
    try { st = await App.api.overlay_status(); } catch { /* preview */ }
    if (st) {
      this.st = st;
      const was = this.editing;
      this.editing = !!st.editing;
      if (was !== this.editing || this.ov.minimised !== st.minimised) { this.ov.minimised = !!st.minimised; this.drawCtrl(); }
      else this.drawStatus();
    }
    this.t = setTimeout(() => this.poll(), 1500);
  },
  drawStatus() {
    const st = this.st || {}, ov = this.ov, msgs = [];
    if (!ov.enabled) msgs.push(h("div.row.small", { style: { gap: "8px" } }, dot("none"), "The overlay is off."));
    else if (st.fullscreen === "exclusive") msgs.push(banner("bad", "alert", "<b>The overlay can't show over this game.</b> " +
      (st.notice || "It uses exclusive fullscreen. In the game's display settings, choose Borderless or Windowed fullscreen.")));
    else if (st.hidden_by_key) msgs.push(banner("info", "info", `The overlay is hidden with your show/hide key${ov.hotkey ? ` (${ov.hotkey})` : ""}. Press it again to show it.`));
    else msgs.push(h("div.row.small", { style: { gap: "8px" } }, dot("good"), ov.minimised ? "On, shrunk to a small dot. Click the dot to bring it back." :
      this.editing ? "On. You can drag it now - press Done when it's where you want it." : "On, and clicks go straight through to your game."));
    if (st.hotkey_ok === false) msgs.push(banner("bad", "alert", "Another app is already using your show/hide key. Pick a different one below."));
    if (st.last_error && !App.demo) msgs.push(h("div.small.muted", "Last overlay problem (in RigLab's log): " + st.last_error));
    if (this.statusBox) this.statusBox.replaceChildren(...msgs);
  },
  drawCtrl() {
    const ov = this.ov, S = isSimple(), editing = !!this.editing;
    this.statusBox = h("div.stack", { style: { gap: "8px", margin: "4px 0 10px" } });
    const hk = h("input", { type: "text", readOnly: true, value: ov.hotkey || "", placeholder: "Click, then press keys", style: { width: "170px" }, "aria-label": "Show/hide key",
      onkeydown: (e) => {
        e.preventDefault();
        if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
        if (e.key === "Escape" || e.key === "Backspace") { this.set({ hotkey: "" }); return; }
        const k = e.key.length === 1 ? e.key.toUpperCase() : e.key;
        const combo = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", k].filter(Boolean).join("+");
        if (!e.ctrlKey && !e.altKey && !/^F\d+$/.test(k)) { toast("Use Ctrl, Alt or Shift with a key (or an F key), so normal typing in games isn't caught.", true); return; }
        this.set({ hotkey: combo });
      } });
    this.ctrlBox.replaceChildren(cardHead("Show and move", "overlay", infoTip("Click-through: your mouse clicks always reach the game. The overlay only takes clicks while you're moving it, or when it's a dot.")),
      h("div.opt", h("div", h("div.t", "Show overlay"), h("div.d", "Works in borderless and windowed games.")), switchEl(!!ov.enabled, (v) => this.set({ enabled: v }))),
      this.statusBox,
      h("div.row.wrap", { style: { gap: "8px" } },
        h("button.btn" + (editing ? ".primary" : ""), { "data-ov": "edit", onclick: async () => { const r = await App.api.overlay_edit(!editing); this.editing = r.edit; ov.enabled = true; ov.minimised = false; this.drawCtrl(); } },
          icon(editing ? "check" : "move"), editing ? "Done - lock it here" : "Edit position"),
        h("button.btn", { "data-ov": "dot", onclick: async () => { await App.api.overlay_minimise(!ov.minimised); ov.minimised = !ov.minimised; this.editing = false; this.drawCtrl(); } },
          icon(ov.minimised ? "maximise" : "minimise"), ov.minimised ? "Bring it back" : "Shrink to a dot"),
        h("select", { "aria-label": "Move the overlay to a corner", onchange: async (e) => { if (!e.target.value) return; await App.api.overlay_corner(e.target.value); toast("Moved to the " + e.target.value.replace("-", " ") + " corner"); e.target.value = ""; } },
          h("option", { value: "" }, "Move to a corner…"), [["top-left", "Top left"], ["top-right", "Top right"], ["bottom-left", "Bottom left"], ["bottom-right", "Bottom right"]].map(([k, l]) => h("option", { value: k }, l)))),
      h("div.small.muted", { style: { margin: "8px 0 4px" } }, editing ? "Drag the overlay by its bar, then press Done (on the overlay or here). It remembers the spot."
        : ov.move_hold ? `To move it any time, hold ${ov.move_hold.replace("+", " + ")} and drag it. Let go to lock it.` : "Press Edit position to move it."),
      h("div.opt", h("div", h("div.t", "Show / hide key"), h("div.d", ov.hotkey ? `Press ${ov.hotkey} in any game to hide or show the overlay. Backspace clears it.` : "Optional. Pick keys to hide or show the overlay in any game.")),
        h("div.row", { style: { gap: "6px" } }, hk, ov.hotkey ? h("button.btn.sm", { onclick: () => this.set({ hotkey: "" }) }, "Clear") : null)),
      S ? null : h("div.opt", h("div", h("div.t", "Hold to move"), h("div.d", "Hold these keys and drag the overlay.")),
        h("select", { "aria-label": "Keys to hold to move the overlay", onchange: (e) => this.set({ move_hold: e.target.value }) },
          [["Ctrl+Alt", "Ctrl + Alt"], ["Ctrl+Shift", "Ctrl + Shift"], ["Alt+Shift", "Alt + Shift"], ["", "Off (use Edit position)"]].map(([v, l]) => h("option", { value: v, selected: (ov.move_hold ?? "Ctrl+Alt") === v }, l)))));
    this.drawStatus();
  },
  drawLook() {
    const S = isSimple(), d = this.draft, cur = this.pick(this.ov);
    const dirty = JSON.stringify(d) !== JSON.stringify(cur);
    const preset = ovPresetOf(d.stats);
    const upd = (v) => { Object.assign(this.draft, v); this.drawLook(); };
    const seg = (items, val, on) => h("div.seg", items.map(([k, l]) => h("button" + (val === k ? ".on" : ""), { "aria-pressed": val === k, onclick: () => on(k) }, l)));
    const pv = h("div.ov-preview" + (this.bg === "light" ? ".light" : ""), { "data-preview": "overlay" });
    this.preview(pv);
    const opts = [
      h("div.small.muted", { style: { margin: "4px 0 6px" } }, "Preset"),
      h("div.row.wrap", { style: { gap: "8px" } }, OV_PRESETS.map(([k, l, desc]) => h("button.btn.sm" + (preset === k ? ".primary" : ""), { "aria-pressed": preset === k, "data-preset": k,
        onclick: () => upd({ stats: [...OV_PRESET_STATS[k]], layout: k === "full" ? "vertical" : "horizontal" }) }, l, h("span.small", { style: { opacity: .75, marginLeft: "6px" } }, desc))),
        preset === "custom" ? h("span.pill", "Your own mix") : null),
      h("div.opt", h("div.t", "Size"), seg([["s", "Small"], ["m", "Medium"], ["l", "Large"], ["xl", "Extra large"]], d.size || "m", (v) => upd({ size: v }))),
    ];
    if (!S) opts.push(
      h("div.small.muted", { style: { margin: "10px 0 6px" } }, "What to show"),
      h("div.chips", OV_STATS.map(([k, l]) => h("div.chip" + (d.stats.includes(k) ? ".on" : ""), { role: "checkbox", "aria-checked": d.stats.includes(k), tabIndex: 0, "data-stat": k,
        onclick: () => { const st = d.stats.includes(k) ? d.stats.filter(x => x !== k) : [...d.stats, k]; if (!st.length) return toast("Keep at least one thing on the overlay", true); upd({ stats: st }); } }, l))),
      h("div.opt", h("div.t", "Layout"), seg([["horizontal", "Side by side"], ["vertical", "Stacked"]], d.layout || "horizontal", (v) => upd({ layout: v }))),
      h("div", { style: { padding: "6px 0" } }, sliderRow("Background", 0, 100, Math.round((d.opacity ?? 0.85) * 100), 5, "%", (v) => { this.draft.opacity = v / 100; this.preview(pv); this.markDirty(); })),
      h("div.opt", h("div", h("div.t", "Text colour"), h("div.d", "Follow theme uses your RigLab theme's colours.")),
        h("div.row", { style: { gap: "8px" } }, seg([["theme", "Follow theme"], ["white", "White"], ["custom", "Custom"]], /^#/.test(d.text_color || "") ? "custom" : (d.text_color || "theme"),
          (v) => upd({ text_color: v === "custom" ? "#36d6ff" : v })),
          /^#/.test(d.text_color || "") ? h("input", { type: "color", value: d.text_color, "aria-label": "Custom text colour", onchange: (e) => upd({ text_color: e.target.value }) }) : null)),
      h("div.opt", h("div", h("div.t", "Colour numbers green / yellow / red"), h("div.d", "FPS and temperatures change colour when they're good, worth checking, or a problem.")),
        switchEl(d.fps_color !== "plain", (v) => upd({ fps_color: v ? "auto" : "plain" }))),
      h("div.opt", h("div", h("div.t", "Snap to the nearest corner"), h("div.d", "When you let go after moving it, it jumps neatly into the closest corner.")),
        switchEl(!!d.snap, (v) => upd({ snap: v }))));
    else opts.push(h("div.mt", advLink("More overlay options (what it shows, layout, colours)", "overlay", { icon: "overlay" })));
    this.applyBtn = h("button.btn.primary", { disabled: !dirty, "data-ov": "apply", onclick: async () => { await this.set(this.draft); this.draft = this.pick(this.ov); toast("Overlay updated"); this.drawLook(); } }, icon("check"), "Apply");
    this.lookBox.replaceChildren(cardHead("How it looks", "palette", h("span.small.muted", dirty ? "Not applied yet" : "This is what's on screen")),
      h("div.ov-look",
        h("div", opts, h("div.row.mt", { style: { gap: "8px" } }, this.applyBtn,
          h("button.btn", { disabled: !dirty, onclick: () => { this.draft = this.pick(this.ov); this.drawLook(); } }, "Undo changes"))),
        h("div",
          h("div.row", { style: { gap: "8px", marginBottom: "8px" } }, h("span.small.muted", "Preview on a"),
            seg([["dark", "dark game"], ["light", "light game"]], this.bg, (v) => { this.bg = v; this.drawLook(); })),
          pv,
          h("div.small.muted", { style: { marginTop: "6px" } }, "Example numbers. Only the overlay's own box is drawn - nothing behind it."))));
  },
  markDirty() {
    const dirty = JSON.stringify(this.draft) !== JSON.stringify(this.pick(this.ov));
    if (this.applyBtn) this.applyBtn.disabled = !dirty;
  },
  async preview(box) {
    const d = this.draft;
    clearTimeout(this.pvT);
    this.pvT = setTimeout(async () => {
      let r = null;
      try { r = await App.api.overlay_preview(d, this.bg); } catch { r = null; }
      if (!box.isConnected && box.dataset.drawn) return;
      box.dataset.drawn = "1";
      box.replaceChildren(r && r.png ? h("img", { src: r.png, alt: "Overlay preview", style: { maxWidth: "100%" } }) : ovMock(d));
    }, 60);
  },
};
