/* Lighting: device list | effect gallery + live preview | colour panel */
"use strict";

const EFFECT_INFO = {
  "Static": ["One solid colour", 1],
  "Breathing": ["Slow fade in and out", 1],
  "Spectrum cycle": ["Every LED shifts through the rainbow together", 0],
  "Rainbow wave": ["A rainbow flowing across the LEDs", 0],
  "Colour wave": ["Your two colours rolling across", 2],
  "Gradient": ["A smooth blend from colour 1 to colour 2", 2],
  "Twinkle": ["Sparkles of colour 2 over a dim colour 1", 2],
  "Strobe": ["Fast flashes", 1],
  "Temperature reactive": ["Blue when cool, red when hot (CPU temp)", 0],
  "Load reactive": ["Green at idle, red at full CPU load", 0],
  "Off": ["Lights out", 0],
  "Spin": ["A rainbow spinning around every fan", 0],
  "Comet": ["A bright dot racing around each fan", 2],
  "Rainbow sweep": ["A rainbow sweeping across all your fans", 0],
  "Colour sweep": ["Your two colours sweeping across the fans", 2],
  "Fan cycle": ["Each fan its own colour, slowly cycling", 0],
  "Breathing wave": ["Fans breathe one after another", 1],
  "Custom paint": ["Your own design, LED by LED (LED map)", 1],
};
const FX_USES = { "Larson scanner": 1, "Meteor": 1, "Candle": 1, "Heartbeat": 1, "Dissolve": 2, "Rain": 1 };
for (const [name, [, desc]] of Object.entries(FX)) EFFECT_INFO[name] = [desc, FX_USES[name] ?? 0, "pack"];
const SPATIAL = new Set(["Spin", "Comet", "Rainbow sweep", "Colour sweep", "Fan cycle", "Breathing wave", "Custom paint"]);
const ANIMATED = new Set([...Object.keys(FX), "Breathing", "Spectrum cycle", "Rainbow wave", "Colour wave", "Twinkle", "Strobe", "Spin", "Comet", "Rainbow sweep", "Colour sweep", "Fan cycle", "Breathing wave"]);
const DEV_ICONS = { Motherboard: "board", Dram: "ram", Gpu: "gpu", Cooler: "fan", Ledstrip: "strip", Keyboard: "keyboard", Mouse: "mouse",
  Mousemat: "mouse", Headset: "sound", Speaker: "sound", Light: "light", Virtual: "light" };
const SWATCHES = ["#ff0000", "#ff5a00", "#ffb000", "#fff200", "#7dff00", "#00ff6a", "#00ffd5", "#00c8ff",
  "#0066ff", "#3a00ff", "#8f00ff", "#d400ff", "#ff00b4", "#ff3c78", "#ffffff", "#ffd7a0"];

// ------------------------------------------------------------------ colour maths (mirrors core/rgb.py)
const hexToRgb = (x) => { x = x.replace("#", ""); if (x.length === 3) x = [...x].map(c => c + c).join(""); return [0, 2, 4].map(i => parseInt(x.substr(i, 2), 16) || 0); };
const rgbToHex = (c) => "#" + c.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
function hsvToRgb(hh, s, v) {
  hh = ((hh % 1) + 1) % 1; const i = Math.floor(hh * 6), f = hh * 6 - i, p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
  const [r, g, b] = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6];
  return [r * 255, g * 255, b * 255];
}
function rgbToHsv([r, g, b]) {
  r /= 255; g /= 255; b /= 255; const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let hh = 0;
  if (d) hh = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [((hh / 6) + 1) % 1, mx ? d / mx : 0, mx];
}
const lerpC = (a, b, t) => a.map((x, i) => x + (b[i] - x) * Math.max(0, Math.min(1, t)));
const scaleC = (c, k) => c.map(v => v * k);
function tempColor3(t) { const k = Math.max(0, Math.min(1, ((t ?? 40) - 40) / 45)); return hsvToRgb(0.66 * (1 - k), 1, 1); }
function twinkle(i, t, sp) { const ph = Math.abs(Math.sin(i * 12.9898) * 43758.5453) % 1; const x = (t * sp * 0.6 + ph) % 1; return x < 0.3 ? Math.max(0, 1 - Math.abs(x - 0.15) / 0.15) : 0; }

function effectFrame(eff, t, n, c1, c2, sp, br, value, key = "stage") {
  if (FX[eff]) { const o = App.pages.lighting.o || {}; return fxFrame(eff, key, t, n, c1, c2, sp, br, o.intensity, o.palette); }
  if (SPATIAL.has(eff)) {   // preview as one fan ring laid out flat
    const out = [...Array(n)].map((_, k) => spatialColor(eff, t, 0, 3, k, n, k / n, c1, c2, sp, null));
    return br < 0.999 ? out.map(c => scaleC(c, br)) : out;
  }
  let out;
  switch (eff) {
    case "Off": out = Array(n).fill([0, 0, 0]); break;
    case "Breathing": { const k = (Math.sin(t * sp * 2) + 1) / 2; out = Array(n).fill(scaleC(c1, 0.05 + 0.95 * k * k)); break; }
    case "Spectrum cycle": out = Array(n).fill(hsvToRgb(t * sp * 0.1, 1, 1)); break;
    case "Rainbow wave": out = [...Array(n)].map((_, i) => hsvToRgb(t * sp * 0.15 + i / n, 1, 1)); break;
    case "Colour wave": out = [...Array(n)].map((_, i) => lerpC(c2, c1, (Math.sin(t * sp * 2 - i / n * Math.PI * 2) + 1) / 2)); break;
    case "Gradient": out = [...Array(n)].map((_, i) => lerpC(c1, c2, i / Math.max(1, n - 1))); break;
    case "Twinkle": out = [...Array(n)].map((_, i) => lerpC(scaleC(c1, 0.08), c2, twinkle(i, t, sp))); break;
    case "Strobe": out = Array(n).fill((t * sp * 4) % 1 < 0.15 ? c1 : [0, 0, 0]); break;
    case "Temperature reactive": out = Array(n).fill(tempColor3(value?.temp)); break;
    case "Load reactive": out = Array(n).fill(lerpC([0, 255, 60], [255, 0, 0], (value?.load ?? 0) / 100)); break;
    default: out = Array(n).fill(c1);
  }
  return br < 0.999 ? out.map(c => scaleC(c, br)) : out;
}

// per-LED colour for map effects - mirrors riglab/core/ledmap.py
function spatialColor(eff, t, fi, nf, k, n, gx, c1, c2, sp, paintHex) {
  const ang = k / Math.max(1, n);
  switch (eff) {
    case "Spin": return hsvToRgb(ang + t * sp * 0.5, 1, 1);
    case "Comet": { const head = (t * sp * 0.8 + fi * 0.13) % 1, d = ((head - ang) % 1 + 1) % 1, k2 = Math.max(0, 1 - d * 4) ** 2; return lerpC(scaleC(c2, 0.06), c1, k2); }
    case "Rainbow sweep": return hsvToRgb(gx * 0.8 - t * sp * 0.2, 1, 1);
    case "Colour sweep": return lerpC(c1, c2, (Math.sin(2 * Math.PI * (gx - t * sp * 0.3)) + 1) / 2);
    case "Fan cycle": return hsvToRgb(fi / Math.max(1, nf) + t * sp * 0.1, 1, 1);
    case "Breathing wave": { const kk = ((Math.sin(t * sp * 2 - fi * 0.8) + 1) / 2) ** 2; return scaleC(c1, 0.06 + 0.94 * kk); }
    case "Custom paint": return paintHex ? hexToRgb(paintHex) : c1;
  }
  return c1;
}

function drawLeds(canvas, cols, { glow = true, gap = 0.35, round = true } = {}) {
  const [ctx, w, hh] = fitCanvas(canvas);
  ctx.fillStyle = "#05060a"; ctx.fillRect(0, 0, w, hh);
  const n = cols.length, cw = w / n, r = Math.min(cw * (1 - gap) / 2, hh * 0.32);
  for (let i = 0; i < n; i++) {
    const [R, G, B] = cols[i].map(Math.round), x = cw * (i + 0.5), y = hh / 2;
    if (glow) { const g = ctx.createRadialGradient(x, y, 0, x, y, r * 3.2); g.addColorStop(0, `rgba(${R},${G},${B},.55)`); g.addColorStop(1, `rgba(${R},${G},${B},0)`); ctx.fillStyle = g; ctx.fillRect(x - r * 3.2, 0, r * 6.4, hh); }
    ctx.fillStyle = `rgb(${R},${G},${B})`;
    ctx.beginPath(); round ? ctx.arc(x, y, r, 0, Math.PI * 2) : ctx.rect(x - cw / 2 + 1, 0, cw - 2, hh); ctx.fill();
  }
}

// ------------------------------------------------------------------ colour wheel widget
function colorWheel(initial, onchange) {
  const size = 236, wrap = h("div.wheel"), cv = h("canvas", { width: size * 2, height: size * 2 }), knob = h("div.knob");
  wrap.append(cv, knob);
  const ctx = cv.getContext("2d"), img = ctx.createImageData(size * 2, size * 2), R = size;
  for (let y = 0; y < size * 2; y++) for (let x = 0; x < size * 2; x++) {
    const dx = x - R, dy = y - R, d = Math.hypot(dx, dy) / R, i = (y * size * 2 + x) * 4;
    if (d > 1) { img.data[i + 3] = 0; continue; }
    const [r, g, b] = hsvToRgb(Math.atan2(dy, dx) / (Math.PI * 2), Math.min(1, d), 1);
    img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b; img.data[i + 3] = d > 0.985 ? 255 * (1 - d) / 0.015 : 255;
  }
  ctx.putImageData(img, 0, 0);
  let hsv = rgbToHsv(hexToRgb(initial));
  const place = () => {
    const a = hsv[0] * Math.PI * 2, r = hsv[1] * size / 2;
    knob.style.left = size / 2 + Math.cos(a) * r + "px"; knob.style.top = size / 2 + Math.sin(a) * r + "px";
    knob.style.background = rgbToHex(hsvToRgb(hsv[0], hsv[1], 1));
  };
  const pick = (e) => {
    const b = cv.getBoundingClientRect(), dx = e.clientX - b.left - size / 2, dy = e.clientY - b.top - size / 2;
    hsv = [((Math.atan2(dy, dx) / (Math.PI * 2)) + 1) % 1, Math.min(1, Math.hypot(dx, dy) / (size / 2)), 1];
    place(); onchange(rgbToHex(hsvToRgb(hsv[0], hsv[1], 1)));
  };
  let drag = false;
  wrap.addEventListener("pointerdown", e => { drag = true; wrap.setPointerCapture(e.pointerId); pick(e); });
  wrap.addEventListener("pointermove", e => drag && pick(e));
  wrap.addEventListener("pointerup", () => { drag = false; });
  wrap.set = (hex) => { hsv = rgbToHsv(hexToRgb(hex)); hsv[2] = 1; place(); };
  place();
  return wrap;
}

// ------------------------------------------------------------------ page
App.pages.lighting = {
  st: null,
  render(el) {
    this.el = el;
    this.o = null;
    this.view = this.view || "effects";
    this.viewChips = h("div.chips");
    this.statusPill = h("span.pill");
    el.append(plainHead("Lights", "Pick a colour or effect for every light in your PC.", "Lighting", "Every RGB device, every LED, one stream - all moving in sync.",
      this.statusPill, this.viewChips,
      h("button.btn", { title: "Copy diagnostics to paste when asking for help", onclick: () => this.copyReport() }, icon("info"), "Copy report"),
      h("button.btn", { onclick: async () => { toast("Rescanning devices…"); await App.api.light_rescan(); this.load(); } }, icon("refresh"), "Rescan"),
      h("span.act", h("button.btn", { onclick: () => this.setState({ effect: "Off" }, true) }, icon("power"), "All off"), infoBtn("light.off"))));
    this.body = h("div", h("div.empty", h("div.spinner"), h("div.mt", "Starting the lighting service…")));
    el.append(this.body);
    App.api.light_reset();          // every LED starts clean each time this page opens
    this.load();
    clearInterval(this.poll);
    this.poll = setInterval(() => this.refreshStatus(), 1500);
  },
  async copyReport() { const t = await App.api.light_report(); navigator.clipboard.writeText(t).then(() => toast("Lighting report copied - paste it to Claude"), () => toast(t.slice(0, 300))); },
  async load() {
    const st = await App.api.light_state();
    this.st = st;
    if (!this.o) this.o = Object.assign({ slot: 0 }, st.state);
    this.drawStatus();
    if (st.status !== "running") return this.renderNotRunning(st);
    if (!st.devices.length) return this.renderNoDevices();
    this.renderMain();
  },
  async refreshStatus() {
    if (!document.body.contains(this.body)) return clearInterval(this.poll);
    const st = await App.api.light_state();
    const was = this.st?.status, n = this.st?.devices.length;
    this.st = Object.assign(this.st || {}, { status: st.status, msg: st.msg, error: st.error, stats: st.stats });
    this.drawStatus();
    if (st.status !== was || st.devices.length !== n) { this.st = st; this.load(); }
    else if (this.notRunMsg) this.notRunMsg.textContent = st.msg || st.error || "Starting…";
  },
  drawStatus() {
    const st = this.st, s = st.stats || {};
    const on = st.status === "running";
    this.statusPill.className = "pill " + (on ? "good" : st.status === "paused" ? "" : "bad");
    this.statusPill.textContent = on ? `● Streaming ${s.leds || 0} LEDs · ${Math.round(s.fps || 0)} fps` : st.status === "paused" ? "Paused" : "○ " + (st.status || "stopped");
  },
  renderNotRunning(st) {
    this.notRunMsg = h("div.muted", st.msg || st.error || "Starting…");
    const missing = st.status === "missing";
    const starting = st.status === "starting" || (!st.error && st.status !== "paused" && !missing);
    this.body.replaceChildren(h("div.card", { style: { maxWidth: "820px" } },
      cardHead(missing ? "Device drivers not found" : st.status === "paused" ? "Lighting is paused" : "Starting the lighting service", "light"),
      h("div.row", { style: { marginBottom: "14px" } }, starting ? h("div.spinner") : null, this.notRunMsg),
      h("div.small.muted", { style: { lineHeight: "1.8", marginBottom: "16px" } },
        missing ? ["RigLab drives your RGB hardware with OpenRGB's device drivers, running privately in the background (own settings, own port ", st.port, ") - you never need to open OpenRGB. Install it with the button below, or point RigLab to an existing OpenRGB.exe."]
          : st.status === "paused" ? "RigLab has handed your RGB devices back so another program can use them."
          : ["RigLab runs its own private copy of the RGB drivers and closes any other OpenRGB window (two programs can't drive the same LEDs). ", h("br"),
             "The first start can take 10-30 seconds while every device is detected. Close iCUE, Armoury Crate, RGB Fusion and SignalRGB - they fight over the same hardware."]),
      h("div.row.wrap",
        h("button.btn.primary", { onclick: async () => { await App.api.light_connect(); toast("Starting…"); this.load(); } }, icon("link"), st.status === "paused" ? "Resume" : "Restart service"),
        h("button.btn", { onclick: async () => { this.st = await App.api.light_pick_exe(); this.load(); } }, icon("folder"), "Find OpenRGB.exe…"),
        h("button.btn" + (missing ? "" : ".ghost"), { onclick: () => App.api.open_url("https://openrgb.org") }, icon("download"), "Download OpenRGB"),
        h("button.btn.ghost", { onclick: () => this.copyReport() }, icon("info"), "Copy report"))));
  },
  renderNoDevices() {
    this.body.replaceChildren(h("div.card", { style: { maxWidth: "800px" } }, cardHead("No RGB devices found", "light"),
      h("div.muted", { style: { lineHeight: "1.8" } }, "The lighting service is running but found nothing. Close other RGB apps (iCUE, Armoury Crate, RGB Fusion, SignalRGB) and make sure RigLab runs as administrator - motherboard and RAM lighting needs it."),
      h("div.row.mt", h("button.btn.primary", { onclick: async () => { await App.api.light_rescan(); this.load(); } }, icon("refresh"), "Rescan"),
        h("button.btn", { onclick: () => this.copyReport() }, icon("info"), "Copy report"))));
  },
  renderMain() {
    const st = this.st, o = this.o;
    this.viewChips.replaceChildren(...[["effects", "Effects"], ["map", "LED map & paint"], ["devices", "Devices & setup"]].map(([k, l]) =>
      h("div.chip" + (this.view === k ? ".on" : ""), { onclick: () => { this.view = k; this.wiz = null; this.renderMain(); } }, l)));
    const setup = st.setup || [];
    const nerr = st.native_error ? banner("bad", "alert", "<b>Direct USB:</b> " + st.native_error) : null;
    const warn = setup.length && this.view !== "devices" ? banner("info", "info", `<b>Confirm LED counts:</b> ${setup.map(x => `${x.key} › ${x.zone}`).join(", ")}. ` +
      "Fan hubs and addressable headers can't report what's plugged in, so RigLab is using a guess for now. A 30-second wizard sets the exact count so every LED maps correctly.",
      h("button.btn.sm", { onclick: () => { this.view = "devices"; this.wiz = { key: setup[0].key, zone: setup[0].zone }; this.renderMain(); } }, "Set up now")) : null;
    if (this.view === "devices") {
      this.mapView = null;
      this.body.replaceChildren(...[nerr, warn, this.devicesView()].filter(Boolean));
      this.animate();
      return;
    }
    // ---- left: devices (on/off)
    this.devList = h("div.stack", { style: { gap: "4px" } });
    const left = h("div.stack",
      h("div.card", { style: { padding: "14px" } }, h("div.row", { style: { marginBottom: "8px", padding: "0 4px" } }, h("h3", { style: { margin: 0 } }, "Devices"), h("div.spacer"),
        h("span.small.muted", "in sync")), this.devList,
        h("div.small.faint", { style: { marginTop: "10px", padding: "0 4px" } }, "Every switched-on device runs the same effect from one clock. Fine-tune counts, colour order and brightness under Devices & setup.")));
    this.stageName = h("span.eff"); this.stageSub = h("span.muted"); this.stageCv = h("canvas");
    this.gallery = h("div.effects");
    const centre = h("div.stack", { style: { gap: "16px" } },
      h("div.stage", h("div.stage-title", this.stageName, this.stageSub), this.stageCv),
      h("div.card", cardHead("Effects", "light"), this.gallery));
    this.slotTabs = h("div.color-tabs");
    this.wheel = colorWheel(o.slot ? o.color2 : o.color, hex => this.setColor(hex, false));
    this.hex = h("input", { type: "text", maxLength: 7, onchange: e => { const v = e.target.value.trim(); if (/^#?[0-9a-f]{6}$/i.test(v)) this.setColor(v[0] === "#" ? v : "#" + v, true); } });
    this.cur = h("div.cur");
    this.swatches = h("div.swatches", SWATCHES.map(c => h("div.sw", { style: { background: c }, title: c, onclick: () => this.setColor(c, true) })));
    this.recent = h("div.swatches");
    this.speedRow = sliderRow("Speed", 0.2, 5, o.speed, 0.1, "×", v => { o.speed = v; this.changed(); });
    o.intensity ??= 0.5; o.palette ||= "Your colours";
    this.intRow = sliderRow("Intensity", 0, 100, Math.round(o.intensity * 100), 1, "%", v => { o.intensity = v / 100; this.changed(); });
    this.palSw = h("canvas", { style: { width: "100%", height: "14px", borderRadius: "6px", display: "block", marginTop: "6px" } });
    this.palSel = h("select", { style: { width: "100%" }, onchange: e => { o.palette = e.target.value; this.drawPalette(); this.changed(); } },
      (st.palettes || ["Your colours"]).map(p => h("option", { selected: o.palette === p }, p)));
    this.palBox = h("div", { style: { marginTop: "14px" } }, h("div.small.muted", { style: { marginBottom: "6px" } }, "Palette"), this.palSel, this.palSw);
    const right = h("div.card", { style: { padding: "16px" } },
      h("h3", { style: { marginBottom: "12px" } }, "Colour"),
      this.slotTabs, h("div.wheel-wrap", this.wheel),
      h("div.hexrow", this.cur, this.hex),
      h("div.small.muted", { style: { margin: "14px 0 8px" } }, "Presets"), this.swatches,
      h("div.small.muted", { style: { margin: "14px 0 8px" } }, "Recent"), this.recent,
      h("div.stack.mt", { style: { gap: "14px" } },
        sliderRow("Brightness", 5, 100, Math.round(o.brightness * 100), 1, "%", v => { o.brightness = v / 100; this.changed(); }),
        this.speedRow, this.intRow),
      this.palBox,
      h("div.small.faint", { style: { marginTop: "12px" } }, "Changes go to every LED instantly."));
    if (this.view === "map") { this.mapView = ledMapView(this); centre.replaceChildren(this.mapView.el); } else this.mapView = null;
    this.body.replaceChildren(...[nerr, warn, h("div.light-layout", left, centre, right)].filter(Boolean));
    this.drawDevices(); this.drawGallery(); this.drawSlots(); this.syncColorUI(); this.drawRecent();
    this.animate();
  },
  drawDevices() {
    this.devList.replaceChildren(...this.st.devices.map(d => {
      const cv = h("canvas"); d._cv = cv;
      return h("div.dev", { onclick: (e) => { if (e.target.closest(".switch")) return; this.view = "devices"; this.wiz = null; this.focus = d.key; this.renderMain(); } },
        h("div.icon-badge", icon(DEV_ICONS[d.type] || "light")),
        h("div", h("div.name", d.name), h("div.meta", `${d.type} · ${d.leds} LEDs`, d.zones.some(z => z.unconfirmed) ? h("span.pill.info", { style: { marginLeft: "6px" } }, "confirm LEDs") : null)),
        switchEl(d.settings.enabled, async v => { d.settings.enabled = v; await App.api.light_device(d.key, { enabled: v }); }),
        cv);
    }));
  },
  // ------------------------------------------------------------------ devices & setup
  devicesView() {
    if (this.wiz) return this.wizardView();
    const st = this.st;
    const card = (d) => {
      const s = d.settings, set = async (k, v) => { s[k] = v; this.st = await App.api.light_device(d.key, { [k]: v }); };
      return h("div.card" + (this.focus === d.key ? ".sel" : ""), { style: { padding: "16px" } },
        h("div.row", h("div.icon-badge", icon(DEV_ICONS[d.type] || "light")),
          h("div", { style: { flex: 1, minWidth: 0 } }, h("h3", { style: { margin: 0 } }, d.name), h("div.small.muted", `${d.type}${d.vendor ? " · " + d.vendor : ""} · ${d.leds} LEDs · ${d.zones.length} zone${d.zones.length === 1 ? "" : "s"}${d.wireless ? " · wireless (≤10 updates/s)" : ""}`),
            d.native ? h("span.pill.good", { style: { marginTop: "4px", display: "inline-block" } }, "Direct USB - RigLab's own driver") : null),
          switchEl(s.enabled, v => set("enabled", v))),
        h("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: "12px", marginTop: "14px" } },
          h("label.small.muted", "Brightness", sliderRow("", 5, 100, Math.round(s.brightness * 100), 1, "%", v => { clearTimeout(this.bt); this.bt = setTimeout(() => set("brightness", v / 100), 150); })),
          h("label.small.muted", "Colour order", h("select", { style: { width: "100%" }, onchange: e => set("order", e.target.value) }, st.orders.map(x => h("option", { selected: s.order === x }, x))),
            h("div.faint", "Red shows as green/blue? Change this.")),
          h("label.small.muted", "How colours are sent", h("select", { style: { width: "100%" }, onchange: e => set("method", e.target.value) },
            [["stream", "Per-LED stream (Direct)"], ["static", "Compatibility (one colour)"]].map(([v, l]) => h("option", { value: v, selected: s.method === v }, l))),
            h("div.faint", "Only use Compatibility if this device stays dark.")),
          h("div.opt", h("div", h("div.t", "Reverse direction"), h("div.d", "Effects run the wrong way round?")), switchEl(s.reverse, v => set("reverse", v)))),
        h("div.nav-label", { style: { padding: "14px 0 4px" } }, "Zones"),
        ...d.zones.map(z => h("div.row.small", { style: { padding: "6px 0", borderBottom: "1px solid var(--line)" } },
          h("b", { style: { flex: 1 } }, z.name),
          h("span" + (z.unconfirmed ? ".pill.info" : ".muted"), z.empty ? "nothing connected" : `${z.leds} LEDs${z.per ? ` · ${Math.round(z.leds / z.per)} × ${z.per}-LED fans` : ""}${z.unconfirmed ? " (guess)" : ""}`),
          z.resizable ? h("button.btn.sm" + (z.unconfirmed ? ".primary" : ""), { onclick: () => { this.wiz = { key: d.key, zone: z.name }; this.renderMain(); } }, z.unconfirmed ? "Set up" : "Change") : null,
          h("button.btn.sm.ghost", { onclick: () => { App.api.light_identify(d.key, z.name); toast(`${z.name} flashing white for 3 s`); } }, "Identify"))),
        h("div.row.mt", h("button.btn.sm", { onclick: () => { App.api.light_identify(d.key, null); toast(`${d.name} flashing white for 3 s`); } }, icon("light"), "Identify device")));
    };
    return h("div.stack", { style: { gap: "14px" } },
      h("div.card", { style: { padding: "14px 16px" } }, h("div.row.wrap",
        h("div.small.muted", { style: { flex: 1, minWidth: "260px", lineHeight: "1.7" } }, "RigLab found these devices automatically and streams every LED on them. If something looks wrong - wrong LED count, swapped colours, an effect running backwards - fix it here. Changes apply instantly."),
        h("button.btn.sm", { onclick: async () => { const r = await App.api.light_fix_openrgb(); toast(r); } }, icon("undo"), "Repair my OpenRGB settings"),
        h("button.btn.sm.ghost", { onclick: async () => { const p = st.status !== "paused"; await App.api.light_pause(p); toast(p ? "Lighting paused - devices released" : "Resuming…"); this.load(); } }, icon("power"), "Release devices"))),
      ...st.devices.map(card));
  },
  wizardView() {
    const w = this.wiz, st = this.st;
    const d = st.devices.find(x => x.key === w.key), z = d && d.zones.find(x => x.name === w.zone);
    if (!z) { this.wiz = null; return this.devicesView(); }
    const isNode = /lighting node|commander|hub|fan/i.test(d.name + " " + z.name);
    w.kind = w.kind || (isNode ? "fans" : "strip");
    w.per = w.per || z.per || 16;
    w.fans = w.fans || (z.per ? Math.max(1, Math.round(z.leds / z.per)) : 3);
    w.count = w.count || (z.unconfirmed ? Math.min(z.max || 60, 30) : z.leds || 30);
    const maxStrip = Math.min(z.max || 300, Math.max(120, w.count + 40));
    const spec = () => w.kind === "fans" ? { kind: "fans", per: w.per, size: w.per * w.fans } : { kind: "strip", count: w.count, size: maxStrip };
    const push = () => { clearTimeout(this.wt); this.wt = setTimeout(() => App.api.light_test(d.key, z.name, spec()), 120); };
    const body = h("div");
    const close = async (save) => {
      if (save === "empty") this.st = await App.api.light_zone(d.key, z.name, z.min || 0, 0, true);
      else if (save) { const sp = spec(); this.st = await App.api.light_zone(d.key, z.name, w.kind === "fans" ? sp.size : w.count, w.kind === "fans" ? w.per : 0, false); toast(`${z.name}: ${w.kind === "fans" ? sp.size : w.count} LEDs saved`); }
      else await App.api.light_test(d.key, z.name, null);
      this.wiz = null; this.load();
    };
    const draw = () => {
      const preview = h("canvas", { style: { width: "100%", height: "40px" } });
      const sp = spec(), cols = [];
      const COLS = [[255, 0, 0], [0, 255, 0], [0, 80, 255], [255, 200, 0], [255, 0, 255], [0, 255, 255], [255, 255, 255], [255, 90, 0]];
      if (w.kind === "fans") for (let i = 0; i < sp.size; i++) cols.push(COLS[Math.floor(i / w.per) % COLS.length]);
      else for (let i = 0; i < Math.min(sp.size, w.count + 6); i++) cols.push(i === w.count - 1 ? [255, 0, 0] : i < w.count ? [0, 0, 60] : [0, 0, 0]);
      body.replaceChildren(
        h("div.chips", { style: { margin: "4px 0 16px" } }, [["fans", "Fans / rings"], ["strip", "LED strip / other"]].map(([k, l]) =>
          h("div.chip" + (w.kind === k ? ".on" : ""), { onclick: () => { w.kind = k; draw(); push(); } }, l))),
        w.kind === "fans" ? h("div.stack", { style: { gap: "12px" } },
          h("div.row.wrap", h("label.small.muted", { style: { flex: 1, minWidth: "220px" } }, "Fan model", h("select", { style: { width: "100%" }, onchange: e => { w.per = +e.target.value; draw(); push(); } },
            Object.entries(st.fan_types).map(([n, c]) => h("option", { value: c, selected: c === w.per }, `${n} - ${c} LEDs`)))),
            h("label.small.muted", "Fans on this channel", h("div.row", h("button.btn.sm", { onclick: () => { w.fans = Math.max(1, w.fans - 1); draw(); push(); } }, "−"),
              h("b", { style: { minWidth: "28px", textAlign: "center" } }, w.fans), h("button.btn.sm", { onclick: () => { w.fans = Math.min(8, w.fans + 1); draw(); push(); } }, "+")))),
          h("div.small", { style: { lineHeight: "1.8" } }, h("b", "Look at your fans now. "), "Each fan should be ", h("b", "one solid colour"), ", and each fan a different colour (red, green, blue…).",
            h("ul.small.muted", { style: { paddingLeft: "18px", margin: "6px 0" } },
              h("li", "A fan shows two colours → wrong fan model, pick another."),
              h("li", "The last fan is dark → add a fan. Colours spill past the last fan → remove one."),
              h("li", "Fans on a splitter show the same colours - count them once.")))) :
          h("div.stack", { style: { gap: "12px" } },
            sliderRow("LEDs", 1, maxStrip, w.count, 1, "", v => { w.count = v; draw(); push(); }),
            h("div.small", { style: { lineHeight: "1.8" } }, h("b", "Look at the strip now. "), "Move the slider until the ", h("b", "red LED is the very last LED"), " on the strip. Everything before it glows dim blue; nothing after it should be lit.")),
        h("div.small.muted", { style: { margin: "12px 0 6px" } }, "What RigLab is sending:"), preview,
        h("div.row.mt.wrap", h("button.btn.primary", { onclick: () => close(true) }, icon("check"), "Looks right - save"),
          h("button.btn", { onclick: () => close("empty") }, "Nothing is plugged in here"),
          h("button.btn.ghost", { onclick: () => close(false) }, "Cancel")));
      requestAnimationFrame(() => drawLeds(preview, cols.length ? cols : [[0, 0, 0]], { glow: false, gap: 0.15, round: false }));
    };
    draw(); push();
    return h("div.card", { style: { maxWidth: "820px", padding: "18px" } },
      h("div.row", h("h3", { style: { margin: 0 } }, `LED setup · ${d.name} › ${z.name}`), h("div.spacer"), h("span.small.muted", `allowed ${z.min ?? 0}-${z.max ?? "?"} LEDs`)),
      h("div.small.muted", { style: { margin: "6px 0 10px" } }, "RigLab is lighting this channel with a test pattern right now. Adjust until what you see in your case matches the description."),
      body);
  },
  // ------------------------------------------------------------------ effects
  drawGallery() {
    const groups = [["Effect pack", "WLED / FastLED-style effects - pick a palette and intensity on the right", e => !!FX[e]],
      ["Across your fans", "Use the LED map, so every fan and LED plays its own part", e => SPATIAL.has(e)],
      ["Classic", "", e => !FX[e] && !SPATIAL.has(e)]];
    const card = (e) => { const cv = h("canvas"); cv.dataset.eff = e;
      return h("div.eff-card" + (this.o.effect === e ? ".on" : ""), { onclick: () => this.selectEffect(e) }, cv, h("div.n", e), h("div.d", (EFFECT_INFO[e] || [""])[0])); };
    this.gallery.replaceChildren(...groups.flatMap(([title, sub, test]) => {
      const list = this.st.effects.filter(test);
      return list.length ? [h("div.eff-group", h("b", title), sub ? h("span.small.muted", " · " + sub) : null), ...list.map(card)] : [];
    }));
  },
  selectEffect(e) {
    this.o.effect = e;
    if (this.gallery) $$(".eff-card", this.gallery).forEach(c => c.classList.toggle("on", c.querySelector(".n")?.textContent === e));
    this.drawSlots(); this.changed();
  },
  drawSlots() {
    if (!this.slotTabs) return;
    const o = this.o, uses = (EFFECT_INFO[o.effect] || ["", 1])[1];
    if (uses < 2 && o.slot === 1) o.slot = 0;
    this.slotTabs.replaceChildren(
      h("div" + (o.slot === 0 ? ".on" : ""), { onclick: () => { o.slot = 0; this.drawSlots(); this.syncColorUI(); } }, h("i", { style: { background: o.color } }), "Colour 1"),
      h("div" + (o.slot === 1 ? ".on" : ""), { style: uses < 2 ? { opacity: .4, pointerEvents: "none" } : null, title: "Used by Colour wave, Gradient, Twinkle, Comet and sweeps", onclick: () => { o.slot = 1; this.drawSlots(); this.syncColorUI(); } }, h("i", { style: { background: o.color2 } }), "Colour 2"));
    this.speedRow.style.opacity = ANIMATED.has(o.effect) ? 1 : .35;
    const pack = !!FX[o.effect];
    this.intRow.style.opacity = pack ? 1 : .35;
    this.palBox.style.opacity = pack ? 1 : .35;
    this.drawPalette();
    this.stageName.textContent = o.effect;
    this.stageSub.textContent = (EFFECT_INFO[o.effect] || [""])[0];
  },
  drawPalette() {
    if (!this.palSw) return;
    const o = this.o; requestAnimationFrame(() => drawLeds(this.palSw, paletteSwatch(o.palette, hexToRgb(o.color), hexToRgb(o.color2), 32), { glow: false, gap: 0, round: false }));
  },
  syncColorUI() {
    const c = this.o.slot ? this.o.color2 : this.o.color;
    this.wheel.set(c); this.hex.value = c.toUpperCase(); this.cur.style.background = c;
    $$(".sw", this.swatches).forEach(s => s.classList.toggle("on", s.title.toLowerCase() === c.toLowerCase()));
  },
  setColor(hex, moveWheel) {
    if (this.o.slot) this.o.color2 = hex; else this.o.color = hex;
    if (moveWheel) this.wheel.set(hex);
    this.hex.value = hex.toUpperCase(); this.cur.style.background = hex;
    $$(".sw", this.swatches).forEach(s => s.classList.toggle("on", s.title.toLowerCase() === hex.toLowerCase()));
    this.drawSlots();
    this.changed();
  },
  drawRecent() {
    let rec = [];
    try { rec = JSON.parse(localStorage.getItem("riglab.recent") || "[]"); } catch { /* ignore */ }
    this.recent.replaceChildren(...(rec.length ? rec.map(c => h("div.sw", { style: { background: c }, title: c, onclick: () => this.setColor(c, true) })) : [h("div.small.faint", { style: { gridColumn: "1/-1" } }, "Colours you use show up here.")]));
  },
  async setState(patch, announce) {
    Object.assign(this.o, patch);
    const o = this.o;
    await App.api.light_set({ effect: o.effect, color: o.color, color2: o.color2, speed: o.speed, brightness: o.brightness, intensity: o.intensity ?? 0.5, palette: o.palette || "Your colours" });
    if (announce) toast(this.o.effect === "Off" ? "All lights off" : this.o.effect);
    if (patch.effect && this.gallery) this.selectEffect(patch.effect);
  },
  changed() {
    clearTimeout(this.deb);
    this.deb = setTimeout(() => {
      this.setState({});
      let rec = [];
      try { rec = JSON.parse(localStorage.getItem("riglab.recent") || "[]"); } catch { /* ignore */ }
      rec = [this.o.color, ...rec.filter(x => x !== this.o.color)].slice(0, 8);
      try { localStorage.setItem("riglab.recent", JSON.stringify(rec)); } catch { /* ignore */ }
    }, 120);
  },
  apply() { this.changed(); },
  animate() {
    cancelAnimationFrame(this.raf);
    const t0 = performance.now();
    const step = () => {
      if (!document.body.contains(this.body)) return;
      const t = (performance.now() - t0) / 1000, o = this.o, c1 = hexToRgb(o.color), c2 = hexToRgb(o.color2);
      const val = { temp: App.snap?.summary.cpu_temp, load: App.snap?.summary.cpu_load };
      if (this.stageCv && document.body.contains(this.stageCv)) drawLeds(this.stageCv, effectFrame(o.effect, t, 36, c1, c2, o.speed, o.brightness, val));
      if (this.mapView) this.mapView.draw(t);
      if (this.gallery && document.body.contains(this.gallery)) for (const cv of $$(".eff-card canvas", this.gallery)) drawLeds(cv, effectFrame(cv.dataset.eff, t, 14, c1, c2, 1, 1, val, "card"), { gap: .25 });
      for (const d of this.st.devices) if (d._cv && document.body.contains(d._cv)) {
        const n = Math.min(28, Math.max(4, d.leds));
        drawLeds(d._cv, d.settings.enabled ? effectFrame(o.effect, t, n, c1, c2, o.speed, o.brightness * d.settings.brightness, val, "dev" + d.key) : Array(n).fill([25, 28, 36]), { glow: false, gap: 0.15, round: false });
      }
      this.raf = requestAnimationFrame(step);
    };
    step();
  },
  leave() { cancelAnimationFrame(this.raf); clearInterval(this.poll); if (this.wiz) App.api.light_test(this.wiz.key, this.wiz.zone, null); },
};
